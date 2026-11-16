"""Stage 19 - a neutral temporal performance grammar for POKEY.

These tests pin the experiment to the four corpus songs, prove it is read-only and deterministic,
lock down the property the whole stage rests on - every candidate is a real byte format that
decodes back to the canonical raw payload exactly - and hold the two negative results in place:
DELTA earns its definition in no song, and a REPEAT lexicon transfers nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest
from click.testing import CliRunner

from atari_music import stage15
from atari_music import stage19
from atari_music.cli import cli

pytestmark = pytest.mark.experimental

requires_corpus = pytest.mark.skipif(
    not stage19.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage19.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage19.run_analysis()


def channel(values: List[int], register: str = "AUDF1") -> stage19.RegisterChannel:
    return stage19.RegisterChannel(register=register, values=tuple(values))


ALL_OPS = (stage19.OP_SET,) + stage19.STRUCTURAL_OPS


def roundtrip(values: List[int], ops=ALL_OPS, table=()) -> List[int]:
    """Segment one channel, encode a full payload, decode it, and return what came back.

    A payload always carries one program per register, so the channel under test is repeated into
    every register slot. That keeps the helper honest - it goes through exactly the same container
    and framing a whole song does - while still testing a single construction sequence.
    """
    segmented = [
        stage19.segment_channel(values, ops) for _ in range(stage19.FRAME_BYTES)
    ]
    payload = stage19.encode_payload(segmented, table)
    decoded = stage19.read_channels(payload, len(values), table)
    return decoded["AUDF1"]


# ---------------------------------------------------------------------------
# 1. Determinism and read-only behaviour
# ---------------------------------------------------------------------------
@requires_corpus
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage19.run_analysis() == bundle

    def test_writing_twice_is_byte_identical(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        """Write the same bundle twice, then write a *fresh* run, and compare every artefact.

        The fresh run is included so the test covers the whole claim - that two independent runs
        produce byte-identical artefacts - without paying for a third run.
        """
        first = stage19.write_analysis(
            bundle, stage19_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        second = stage19.write_analysis(
            bundle, stage19_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        fresh = stage19.write_analysis(
            stage19.run_analysis(), stage19_dir=tmp_path / "c", docs_dir=tmp_path / "c"
        )
        hashes = [
            {name: hashlib.sha256(path.read_bytes()).hexdigest()
             for name, path in written.items()}
            for written in (first, second, fresh)
        ]
        assert hashes[0] == hashes[1] == hashes[2]
        assert set(hashes[0]) == set(stage19.STAGE19_FILES) | {stage19.STAGE19_DOC}
        assert len(stage19.STAGE19_FILES) == 12

    def test_nothing_upstream_is_written(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        watched = (
            list(stage15.list_traces())
            + sorted(stage19.DEFAULT_STAGE15_DIR.glob("*.json"))
            + sorted(stage19.DEFAULT_STAGE16_DIR.glob("*.json"))
            + sorted(stage19.DEFAULT_STAGE17_DIR.glob("*.json"))
            + sorted(stage19.DEFAULT_STAGE18_DIR.glob("*.json"))
            + [stage19.stage18.DEFAULT_PLAYER_ASM]
        )
        before = {str(path): stage19.sha256_file(path) for path in watched if path.is_file()}
        assert before, "expected some upstream artefacts to watch"
        stage19.write_analysis(bundle, stage19_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        after = {str(path): stage19.sha256_file(path) for path in watched if path.is_file()}
        assert before == after

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle)
        assert "created_utc" not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text)

    def test_only_json_and_markdown_are_produced(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        written = stage19.write_analysis(
            bundle, stage19_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        assert {path.suffix for path in written.values()} == {".json", ".md"}

    def test_the_source_hash_travels_with_the_bundle(self, bundle: Dict[str, Any]) -> None:
        assert bundle["determinism"]["source_hash"] == stage19.sha256_file(
            Path(stage19.__file__)
        )

    def test_every_tie_break_is_declared(self, bundle: Dict[str, Any]) -> None:
        text = bundle["determinism"]["tie_breaks"].lower()
        assert "longer construction" in text
        assert "lower opcode" in text
        assert "longer block" in text
        assert "descending use" in text


@requires_corpus
class TestTieBreaks:
    def test_segmenter_prefers_the_longer_construction_on_a_tie(self) -> None:
        """A 2-frame arithmetic run costs the same as a 2-frame literal; the longer wins first."""
        values = [0, 1, 2, 3, 4, 5]
        ops = stage19.segment_channel(values, ALL_OPS)
        assert [op.name for op in ops] == ["RAMP"]
        assert ops[0].length == 6

    def test_segmenter_prefers_the_lower_opcode_on_an_exact_tie(self) -> None:
        """A 2-frame RAMP and a 2-frame LITERAL both cost 4 bytes; RAMP has the lower opcode."""
        values = [3, 7]
        ops = stage19.segment_channel(values, ALL_OPS)
        assert [op.name for op in ops] == ["RAMP"]

    def test_induction_tie_break_is_the_lower_opcode(self) -> None:
        assert stage19._addition_order()[0] == stage19.OP_HOLD
        assert stage19._addition_order() == tuple(sorted(stage19.STRUCTURAL_OPS))

    def test_block_table_order_is_deterministic(self) -> None:
        pattern = [10, 20, 10, 20, 10, 20]
        values = pattern * 4
        _, table, _ = stage19.extract_references([channel(values)], [
            stage19.segment_channel(values, ALL_OPS)
        ])
        _, again, _ = stage19.extract_references([channel(values)], [
            stage19.segment_channel(values, ALL_OPS)
        ])
        assert table == again


# ---------------------------------------------------------------------------
# 2. The canonical representation and the atom
# ---------------------------------------------------------------------------
@requires_corpus
class TestCanonical:
    def test_the_corpus_is_the_four_songs_the_brief_names(self, bundle: Dict[str, Any]) -> None:
        assert tuple(sorted(bundle["dataset"]["songs"])) == tuple(sorted(stage19.EXPECTED_SLUGS))

    def test_a_frame_is_nine_registers_in_pokeys_order(self) -> None:
        assert stage19.FRAME_BYTES == 9
        assert stage19.REGISTER_ORDER == (
            "AUDF1", "AUDC1", "AUDF2", "AUDC2", "AUDF3", "AUDC3", "AUDF4", "AUDC4", "AUDCTL",
        )

    def test_the_order_agrees_with_stages_17_and_18(self) -> None:
        assert stage19.REGISTER_ORDER == stage19.stage18.REGISTER_ORDER
        from atari_music import stage17

        assert stage19.REGISTER_ORDER == tuple(stage17.REGISTER_ORDER)

    def test_the_canonical_form_is_stage_18s_by_import(self, bundle: Dict[str, Any]) -> None:
        assert bundle["canonical"]["frame_bytes"] == stage19.stage18.FRAME_BYTES
        assert (
            bundle["canonical"]["container_header_bytes"]
            == stage19.stage18.CONTAINER_HEADER_BYTES
        )
        assert bundle["canonical"]["stage18_hash"] == stage19.sha256_file(
            Path(stage19.stage18.__file__)
        )

    def test_a_wrong_corpus_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(stage19.GrammarError):
            stage19.load_dataset(tmp_path)

    def test_the_atom_is_one_register_channel(self) -> None:
        values = [1, 2, 3, 3, 3]
        chan = channel(values)
        assert chan.frames == 5
        assert chan.runs() == [(1, 1), (1, 2), (3, 3)]
        assert chan.change_events() == 3

    def test_the_payload_is_interleaved_and_exact(
        self, bundle: Dict[str, Any]
    ) -> None:
        streams, _ = stage19.load_dataset()
        for stream in streams:
            payload = stream.payload()
            assert len(payload) == stream.frames * stage19.FRAME_BYTES
            rebuilt = stage19.registers_to_payload(
                stage19.read_channels(
                    stage19.encode_payload(
                        [
                            stage19.segment_channel(
                                stage19.RegisterChannel(
                                    register=name, values=stream.registers[name]
                                ).values,
                                ALL_OPS,
                            )
                            for name in stage19.REGISTER_ORDER
                        ]
                    ),
                    stream.frames,
                )
            )
            assert rebuilt == payload


# ---------------------------------------------------------------------------
# 3. Construction encode/decode and exact reconstruction
# ---------------------------------------------------------------------------
class TestConstructionRoundTrips:
    def test_empty_input(self) -> None:
        assert roundtrip([]) == []

    def test_single_frame(self) -> None:
        assert roundtrip([0]) == [0]
        assert roundtrip([255]) == [255]

    def test_constant_sequence(self) -> None:
        values = [7] * 500
        assert roundtrip(values) == values
        ops = stage19.segment_channel(values, ALL_OPS)
        assert {op.name for op in ops} <= {"HOLD", "SET"}

    def test_delta_sequence(self) -> None:
        values = [100, 99, 98, 97, 96]
        assert roundtrip(values) == values

    def test_ramp_sequence(self) -> None:
        values = [(index * 3) & 0xFF for index in range(120)]
        assert roundtrip(values) == values
        ops = stage19.segment_channel(values, ALL_OPS)
        assert any(op.name == "RAMP" for op in ops)

    def test_toggle_sequence(self) -> None:
        values = [40, 90] * 60
        assert roundtrip(values) == values
        ops = stage19.segment_channel(values, ALL_OPS)
        assert [op.name for op in ops] == ["TOGGLE"]
        assert ops[0].length == 120

    def test_residual_sequence(self) -> None:
        """A third-order sequence is not CONST, LINEAR or QUAD, so the residual must carry it."""
        values = [(index * 37 + index ** 2 * 11 + index ** 3 * 5) % 256 for index in range(200)]
        assert roundtrip(values) == values
        ops = stage19.segment_channel(values, ALL_OPS)
        assert any(op.name == "LITERAL" for op in ops)

    def test_boundary_values_wrap_in_both_directions(self) -> None:
        values = [250, 252, 255, 3, 8, 14, 22, 32]
        assert roundtrip(values) == values

    def test_maximum_register_values(self) -> None:
        values = [255] * 64
        assert roundtrip(values) == values

    def test_a_mixed_sequence_of_every_construction(self) -> None:
        values = (
            [5] * 10 + [(index * 2) & 0xFF for index in range(10)] + [77, 200] * 8
            + [9] * 4 + [1, 2, 3, 4, 5]
        )
        assert roundtrip(values) == values

    def test_restricting_the_vocabulary_keeps_exactness(self) -> None:
        values = ([(index * 3) & 0xFF for index in range(40)] + [7] * 20 + [90, 20] * 10)
        for ops in (
            stage19.SET_HOLD,
            stage19.SET_HOLD_DELTA,
            stage19.SET_HOLD_DELTA_RAMP,
            stage19.FULL,
        ):
            assert roundtrip(values, ops) == values

    def test_the_container_round_trips(self) -> None:
        stream = stage19.stage18.stream_from_payload("x", 2, 20056, bytes(range(18)))
        chans = stage19.channels_of(stream)
        segmented = [stage19.segment_channel(c.values, ALL_OPS) for c in chans]
        payload = stage19.encode_payload(segmented)
        container = stage19.wrap(payload, stream.frames, stream.frame_period_us)
        frames, read_payload = stage19.unwrap(container)
        assert frames == stream.frames
        assert read_payload == payload

    def test_the_payload_has_no_trailing_bytes(self) -> None:
        values = [1, 2, 3, 4]
        segmented = [
            stage19.segment_channel(values, ALL_OPS) for _ in range(stage19.FRAME_BYTES)
        ]
        payload = stage19.encode_payload(segmented)
        with pytest.raises(stage19.GrammarError):
            stage19.read_channels(payload + b"\x00", len(values))

    def test_the_block_table_round_trips(self) -> None:
        body = [[1, 2, 3, 4], [9, 9, 9, 9, 9]]
        assert stage19.write_table(body) == (
            stage19.stage18.uvarint(len(body))
            + stage19.stage18.uvarint(4) + bytes([1, 2, 3, 4])
            + stage19.stage18.uvarint(5) + bytes([9, 9, 9, 9, 9])
        )



class TestCorruptedInput:
    """A decoder must refuse a broken stream deterministically, never guess or invent frames."""

    def test_every_truncation_of_a_real_program_is_refused(self) -> None:
        values = (
            [5] * 12 + [(index * 3) & 0xFF for index in range(12)] + [70, 30] * 8
            + [1, 2, 3, 4, 250, 251]
        )
        program = stage19.write_program(stage19.segment_channel(values, ALL_OPS))
        for cut in range(len(program)):
            with pytest.raises(stage19.GrammarError):
                stage19.read_program(program[:cut], len(values))

    def test_an_unknown_opcode_is_refused(self) -> None:
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(b"\x7f", 1)

    def test_a_zero_length_hold_is_refused(self) -> None:
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(bytes([stage19.OP_HOLD, 0]), 1)

    def test_a_single_frame_delta_is_refused(self) -> None:
        payload = bytes([stage19.OP_DELTA]) + stage19.stage18.uvarint(1) + b"\x01"
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(payload, 1)

    def test_a_zero_step_ramp_is_refused(self) -> None:
        payload = (
            bytes([stage19.OP_RAMP]) + b"\x05" + stage19.stage18.uvarint(0)
            + stage19.stage18.uvarint(3)
        )
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(payload, 3)

    def test_a_toggle_with_equal_endpoints_is_refused(self) -> None:
        payload = (
            bytes([stage19.OP_TOGGLE]) + b"\x05\x05" + stage19.stage18.uvarint(4)
        )
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(payload, 4)

    def test_an_out_of_range_literal_is_refused(self) -> None:
        payload = bytes([stage19.OP_LITERAL]) + stage19.stage18.uvarint(
            stage19.MAX_LITERAL_FRAMES + 1
        )
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(payload, 40)

    def test_a_truncated_literal_body_is_refused(self) -> None:
        payload = bytes([stage19.OP_LITERAL]) + stage19.stage18.uvarint(5) + b"\x01\x02"
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(payload, 5)

    def test_a_program_that_writes_too_many_frames_is_refused(self) -> None:
        program = stage19.write_program([stage19.Op(stage19.OP_HOLD, 10)])
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(program, 5)

    def test_a_program_that_writes_too_few_frames_is_refused(self) -> None:
        program = stage19.write_program([stage19.Op(stage19.OP_HOLD, 3)])
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(program, 9)

    def test_a_repeat_index_outside_the_table_is_refused(self) -> None:
        payload = bytes([stage19.OP_REFERENCE]) + stage19.stage18.uvarint(3)
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(payload, 4, [[1, 2, 3, 4]])

    def test_a_payload_declaring_the_wrong_channel_count_is_refused(self) -> None:
        with pytest.raises(stage19.GrammarError):
            stage19.read_channels(stage19.stage18.uvarint(4), 1)

    def test_a_truncated_block_table_entry_is_refused(self) -> None:
        payload = (
            stage19.stage18.uvarint(stage19.FRAME_BYTES) + stage19.stage18.uvarint(1)
            + stage19.stage18.uvarint(9) + b"\x01\x02"
        )
        with pytest.raises(stage19.GrammarError):
            stage19.read_channels(payload, 1)

    def test_a_zero_length_block_is_refused(self) -> None:
        payload = (
            stage19.stage18.uvarint(stage19.FRAME_BYTES) + stage19.stage18.uvarint(1)
            + stage19.stage18.uvarint(0)
        )
        with pytest.raises(stage19.GrammarError):
            stage19.read_channels(payload, 1)

    def test_a_truncated_container_is_refused(self) -> None:
        with pytest.raises(stage19.stage18.Stage18Error):
            stage19.unwrap(b"P8")

    def test_a_program_shorter_than_one_frame_is_refused(self) -> None:
        with pytest.raises(stage19.GrammarError):
            stage19.read_program(b"", 1)



# ---------------------------------------------------------------------------
# 4. Cost accounting: nothing may be hidden outside the model
# ---------------------------------------------------------------------------
@requires_corpus
class TestCostAccounting:
    def test_the_grammar_definition_is_charged(self) -> None:
        small = stage19.complexity_score(stage19.SET_HOLD)
        large = stage19.complexity_score(stage19.FULL)
        assert large["definition_lines_estimate"] > small["definition_lines_estimate"]
        assert stage19.grammar_definition_lines(stage19.SET_HOLD) == (
            stage19.INTERPRETER_CODE_LINES
            + stage19.PRIMITIVES[stage19.OP_SET].code_lines
            + stage19.PRIMITIVES[stage19.OP_HOLD].code_lines
        )

    def test_every_bucket_sums_to_the_container(self, bundle: Dict[str, Any]) -> None:
        for name, row in bundle["candidates"].items():
            if not row["per_song"]:
                continue
            for slug, song in row["per_song"].items():
                assert song["accounting_check"] is True, (name, slug)
                parts = (
                    song["bytes"]["stream"] + song["bytes"]["parameter"]
                    + song["bytes"]["exception"] + song["bytes"]["reference_table"]
                )
                assert parts == song["container_bytes"]
                assert song["bytes"]["grand_total"] == (
                    parts + song["bytes"]["grammar_definition"] + song["bytes"]["decoder"]
                )

    def test_the_grand_total_is_never_smaller_than_the_artefact(
        self, bundle: Dict[str, Any]
    ) -> None:
        for row in bundle["candidates"].values():
            if not row["per_song"]:
                continue
            for song in row["per_song"].values():
                assert song["bytes"]["grand_total"] >= song["container_bytes"]

    def test_raw_has_no_grammar_cost(self, bundle: Dict[str, Any]) -> None:
        assert bundle["candidates"]["G0"]["ratio"] == 1.0
        assert bundle["candidates"]["G0"]["bytes"]["grammar_definition"] == 0

    def test_a_variant_costs_more_to_install_than_its_subset(self, bundle: Dict[str, Any]) -> None:
        candidates = bundle["candidates"]
        assert (
            candidates["G5"]["bytes"]["grammar_definition"]
            > candidates["G2"]["bytes"]["grammar_definition"]
        )

    def test_the_operating_parameters_are_reported(self, bundle: Dict[str, Any]) -> None:
        params = bundle["primitives"]["min_span"]
        assert params["TOGGLE"] == 4
        assert params["HOLD"] == params["DELTA"] == params["RAMP"] == 2

    def test_the_table_cost_is_counted_for_the_repeat_candidate(
        self, bundle: Dict[str, Any]
    ) -> None:
        for song in bundle["candidates"]["G6"]["per_song"].values():
            assert song["bytes"]["reference_table"] > 0
            assert song["reference_table"]["table_bytes"] == song["bytes"]["reference_table"]

    def test_the_table_bucket_is_only_the_one_byte_table_length_field(
        self, bundle: Dict[str, Any]
    ) -> None:
        """Every payload carries the table-length field, so a tableless grammar pays exactly 1."""
        for song in bundle["candidates"]["G5"]["per_song"].values():
            assert song["bytes"]["reference_table"] == stage19.stage18.uvarint_bytes(0)
        for song in bundle["candidates"]["G6"]["per_song"].values():
            assert song["bytes"]["reference_table"] > stage19.stage18.uvarint_bytes(0)


@requires_corpus
class TestComplexity:
    def test_the_score_is_the_sum_of_its_parts(self) -> None:
        for ops in (stage19.SET_HOLD, stage19.SET_HOLD_DELTA, stage19.FULL):
            score = stage19.complexity_score(ops)
            assert score["score"] == (
                score["primitives"] + score["parameter_fields"]
                + score["decoder_states"] + score["special_cases"]
            )

    def test_the_score_grows_with_the_vocabulary(self) -> None:
        scores = [
            stage19.complexity_score(ops)["score"]
            for ops in (
                stage19.SET_HOLD, stage19.SET_HOLD_DELTA, stage19.SET_HOLD_DELTA_RAMP,
                stage19.FULL,
            )
        ]
        assert scores == sorted(scores)
        assert len(set(scores)) == len(scores)

    def test_the_frontier_is_deterministic_and_on_the_scores(
        self, bundle: Dict[str, Any]
    ) -> None:
        candidates = [
            bundle["candidates"][name] for name in ("G2", "G3", "G4", "G5", "G6")
        ]
        assert stage19.pareto_frontier(candidates) == stage19.pareto_frontier(candidates)
        for row in bundle["pareto_frontier"]:
            assert row["variant"] in {"G2", "G3", "G4", "G5", "G6"}

    def test_the_decoder_ram_is_reported_and_small(self, bundle: Dict[str, Any]) -> None:
        assert bundle["candidates"]["G5"]["ram_bytes"] == (
            stage19.STATE_BYTES_PER_CHANNEL * stage19.FRAME_BYTES
        )
        assert bundle["candidates"]["G5"]["ram_bytes"] <= 128



# ---------------------------------------------------------------------------
# 5. Induction, shared vocabulary, leave-one-out and parameters
# ---------------------------------------------------------------------------
@requires_corpus
class TestInduction:
    def test_every_song_took_hold(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["induction"].values():
            assert "HOLD" in row["induced_primitives"]
            assert "SET" in row["induced_primitives"]

    def test_every_song_rejected_delta(self, bundle: Dict[str, Any]) -> None:
        """The headline negative result, held in place so it cannot drift unnoticed."""
        for row in bundle["induction"].values():
            assert "DELTA" not in row["induced_primitives"]

    def test_the_stopping_decision_is_auditable(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["induction"].values():
            assert row["steps"], "a song that added nothing would not be an induction"
            assert row["steps"][-1]["accepted"] is False
            assert row["steps"][-1]["gain_bytes"] <= 0
            for step in row["steps"][:-1]:
                assert step["accepted"] is True
                assert step["gain_bytes"] > 0

    def test_every_step_reports_all_the_trials_it_weighed(
        self, bundle: Dict[str, Any]
    ) -> None:
        for row in bundle["induction"].values():
            for step in row["steps"]:
                assert step["all_trials"]
                for trial in step["all_trials"]:
                    assert trial["add"] and trial["grand_total"] > 0

    def test_the_induced_grammar_is_measured_like_any_other(
        self, bundle: Dict[str, Any]
    ) -> None:
        for slug, row in bundle["per_song"].items():
            assert row["minimal_grammar_ratio"] is not None
            assert row["minimal_grammar_coverage"] is not None
            assert row["measurement"]["exact"] is True, slug
            assert set(row["induced_primitives"]) == {
                stage19.OP_NAMES[op] for op in
                bundle["induction"][slug]["induced_ops"]
            }

    def test_parameter_diversity_is_reported_per_song(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["per_song"].values():
            assert "HOLD" in row["parameter_diversity"]

    def test_the_shared_vocabulary_is_the_intersection(self, bundle: Dict[str, Any]) -> None:
        shared = bundle["shared_grammar"]
        for name in ("HOLD", "TOGGLE"):
            assert name in shared["intersection"]
        assert "RAMP" not in shared["intersection"]
        assert "RAMP" in shared["union"]
        assert set(shared["intersection"]) <= set(shared["union"])

    def test_each_shared_construction_names_the_songs_that_have_it(
        self, bundle: Dict[str, Any]
    ) -> None:
        for name, slugs in bundle["shared_grammar"]["present_in"].items():
            assert slugs, name
            assert set(slugs) <= set(bundle["dataset"]["songs"])
        assert len(bundle["shared_grammar"]["present_in"]["RAMP"]) >= 3



@requires_corpus
class TestGeneralization:
    def test_leave_one_out_covers_every_song_once(self, bundle: Dict[str, Any]) -> None:
        folds = bundle["leave_one_out"]["folds"]
        assert len(folds) == 4
        assert {fold["held_out"] for fold in folds} == set(bundle["dataset"]["songs"])
        for fold in folds:
            assert fold["held_out"] not in fold["trained_on"]
            assert len(fold["trained_on"]) == 3

    def test_every_leave_one_out_arm_is_exact(self, bundle: Dict[str, Any]) -> None:
        assert bundle["leave_one_out"]["all_exact"] is True
        for fold in bundle["leave_one_out"]["folds"]:
            for arm in ("shared_vocabulary_arm", "union_vocabulary_arm",
                        "frozen_parameter_arm"):
                assert fold[arm]["exact"] is True, (fold["held_out"], arm)

    def test_the_vocabulary_transfers_almost_without_loss(self, bundle: Dict[str, Any]) -> None:
        in_sample = bundle["candidates"]["G5"]["ratio"]
        out_of_sample = bundle["leave_one_out"]["mean_ratio_by_arm"]["union_vocabulary_arm"]
        assert out_of_sample is not None and in_sample is not None
        assert out_of_sample < in_sample * 1.10

    def test_freezing_the_parameters_costs_something(self, bundle: Dict[str, Any]) -> None:
        """Parameter transfer is harder than vocabulary transfer, and the numbers must show it."""
        free = bundle["leave_one_out"]["mean_ratio_by_arm"]["union_vocabulary_arm"]
        frozen = bundle["leave_one_out"]["mean_ratio_by_arm"]["frozen_parameter_arm"]
        assert frozen is not None and free is not None
        assert frozen >= free

    def test_unseen_parameters_are_counted_per_primitive(self, bundle: Dict[str, Any]) -> None:
        for fold in bundle["leave_one_out"]["folds"]:
            unseen = fold["unseen_parameters"]
            assert unseen["structural_occurrences"] > 0
            assert 0 <= unseen["unseen_occurrences"] <= unseen["structural_occurrences"]
            assert unseen["unseen_share"] == pytest.approx(
                unseen["unseen_occurrences"] / unseen["structural_occurrences"], abs=1e-6
            )

    def test_parameter_generalization_separates_shape_from_values(
        self, bundle: Dict[str, Any]
    ) -> None:
        primitives = bundle["parameters"]["primitives"]
        assert primitives
        for name, row in primitives.items():
            assert row["songs_present_count"] >= 1
            assert row["total_parameter_cardinality"] >= row["shared_parameter_count"]
            assert row["generalises_parameters"] == (
                row["songs_present_count"] == 4 and row["shared_parameter_count"] > 0
            ), name

    def test_the_register_is_not_part_of_a_parameter_shape(self) -> None:
        assert stage19.parameter_key(stage19.OP_HOLD, ()) == ()
        assert stage19.parameter_key(stage19.OP_RAMP, (120, 3)) == (3,)
        assert stage19.parameter_key(stage19.OP_TOGGLE, (10, 90)) == (10, 90)

    def test_the_lexicon_does_not_transfer(self, bundle: Dict[str, Any]) -> None:
        """The decisive negative result: a shared REPEAT lexicon supplies nothing to a new song."""
        lexicon = bundle["lexicon_leave_one_out"]
        assert lexicon["all_exact"] is True
        assert sum(fold["references_emitted"] for fold in lexicon["folds"]) == 0
        assert lexicon["mean_ratio"] == pytest.approx(
            bundle["candidates"]["G5"]["ratio"], abs=1e-6
        )

    def test_the_shared_lexicon_was_large_enough_to_matter(self, bundle: Dict[str, Any]) -> None:
        """A tiny lexicon would make the null result trivial; it was not tiny."""
        assert bundle["lexicon_leave_one_out"]["mean_shared_lexicon_blocks"] > 100

    def test_the_repeat_candidate_wins_in_sample_and_loses_out_of_sample(
        self, bundle: Dict[str, Any]
    ) -> None:
        g5 = bundle["candidates"]["G5"]["ratio"]
        g6 = bundle["candidates"]["G6"]["ratio"]
        out = bundle["lexicon_leave_one_out"]["mean_ratio"]
        assert g6 is not None and g5 is not None and out is not None
        assert g6 < g5
        assert out > g6



# ---------------------------------------------------------------------------
# 6. Pattern induction and the anti-overfitting rule
# ---------------------------------------------------------------------------
@requires_corpus
class TestPatternInduction:
    def test_the_saving_cannot_exceed_the_data_it_replaces(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The first version summed overlapping n-grams and claimed more than the corpus held."""
        extraction = bundle["patterns"]["extraction"]
        assert extraction["bounded_by_operation_bytes"] is True
        assert extraction["gross_saving_bytes"] <= bundle["patterns"]["totals"]["operation_bytes"]

    def test_the_extraction_never_references_an_operation_twice(
        self, bundle: Dict[str, Any]
    ) -> None:
        extraction = bundle["patterns"]["extraction"]
        consumed = sum(
            row["references"] * len(row["pattern"]) for row in extraction["top_patterns_used"]
        )
        assert consumed <= bundle["patterns"]["totals"]["operations"]

    def test_the_two_levels_are_kept_apart(self, bundle: Dict[str, Any]) -> None:
        patterns = bundle["patterns"]
        assert "structural" in patterns["levels"]
        assert "exact" in patterns["levels"]
        assert "detection" in patterns["levels"]["structural"]

    def test_the_structural_table_is_labelled_as_detection(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["patterns"]["structural_patterns"]:
            assert "not a coverage figure" in row["note"]
            assert row["occurrences"] >= 2

    def test_a_pattern_used_once_can_never_pay(self) -> None:
        body = bytes(range(10))
        reference_cost = 1 + stage19.stage18.uvarint_bytes(0)
        table_cost = 1 + stage19.stage18.uvarint_bytes(len(body)) + len(body)
        assert 1 * (len(body) - reference_cost) <= table_cost

    def test_a_pattern_used_many_times_can_pay(self) -> None:
        body = bytes(range(10))
        reference_cost = 1 + stage19.stage18.uvarint_bytes(0)
        table_cost = 1 + stage19.stage18.uvarint_bytes(len(body)) + len(body)
        assert 8 * (len(body) - reference_cost) > table_cost

    def test_the_corpus_verdict_is_stated(self, bundle: Dict[str, Any]) -> None:
        assert bundle["patterns"]["verdict"] in (
            "REPEAT_CONSTRUCTION_PAYS", "REPEAT_CONSTRUCTION_DOES_NOT_PAY",
        )
        considered = bundle["primitives"]["new_constructions_considered"]
        assert considered and considered[0]["construction"] == "REPEAT"



@requires_corpus
class TestStage17And18Comparison:
    def test_stage_17_questions_all_get_a_status_and_a_verdict(
        self, bundle: Dict[str, Any]
    ) -> None:
        comparison = bundle["stage17_comparison"]
        assert comparison["available"] is True
        assert comparison["source"].endswith("architecture.json")
        assert comparison["answers"]
        for item in comparison["answers"]:
            assert item["status"] in ("ADDRESSED", "NOT_ADDRESSED")
            assert item["verdict"] in (
                "ADDRESSED", "NOT_ADDRESSED", "SUPPORTED", "REFUTED", "INCONCLUSIVE",
            )
            assert item["question"] and item["evidence"]

    def test_no_stage_17_question_is_silently_skipped(self, bundle: Dict[str, Any]) -> None:
        record = json.loads(
            Path(bundle["stage17_comparison"]["source"]).read_text(encoding="utf-8")
        )
        asked = [item["question"] for item in record["stage18_candidates"]]
        answered = [item["question"] for item in bundle["stage17_comparison"]["answers"]]
        assert sorted(asked) == sorted(answered)

    def test_stage_18_figures_are_read_from_stage_18s_own_record(
        self, bundle: Dict[str, Any]
    ) -> None:
        comparison = bundle["stage18_comparison"]["stage18"]
        assert comparison["available"] is True
        assert comparison["source_summary_sha256"] == stage19.sha256_file(
            Path(comparison["source_summary"])
        )

    def test_every_song_is_compared_with_stage_18(self, bundle: Dict[str, Any]) -> None:
        rows = bundle["stage18_comparison"]["songs"]
        assert {row["slug"] for row in rows} == set(bundle["dataset"]["songs"])
        for row in rows:
            assert row["stage18_bytes"] > 0
            assert row["g5_vs_stage18"] is not None
            assert row["g6_lexicon_share"] is not None

    def test_the_grammar_does_not_beat_stage_18_in_bytes(self, bundle: Dict[str, Any]) -> None:
        """The measured claim the deciding condition rests on."""
        summary = bundle["stage18_comparison"]["summary"]
        assert summary["g5_mean_ratio_with_grammar"] >= summary["stage18_mean_ratio"]

    def test_the_repeat_candidate_does_beat_stage_18_in_bytes(
        self, bundle: Dict[str, Any]
    ) -> None:
        summary = bundle["stage18_comparison"]["summary"]
        assert summary["g6_mean_ratio"] < summary["stage18_mean_ratio"]

    def test_the_stage_15_techniques_are_mapped_empirically(
        self, bundle: Dict[str, Any]
    ) -> None:
        techniques = bundle["techniques"]
        assert techniques["available"] is True
        assert techniques["techniques"]
        for row in techniques["techniques"]:
            assert row["correspondence"] in (
                "EXACT_CORRESPONDENCE", "PARTIAL_CORRESPONDENCE", "NO_CORRESPONDENCE",
            )
            assert row["frames_inspected"] > 0
            assert row["operation_histogram"]

    def test_the_mapping_is_labelled_an_interpretation(self, bundle: Dict[str, Any]) -> None:
        assert "interpretations" in bundle["techniques"]["reading"]



# ---------------------------------------------------------------------------
# 7. Falsification, verdicts and the final answer
# ---------------------------------------------------------------------------
@requires_corpus
class TestFalsification:
    def test_all_six_tests_were_run(self, bundle: Dict[str, Any]) -> None:
        tests = bundle["falsification"]
        for name in ("F1", "F2", "F3", "F4", "F5", "F6"):
            assert any(key.startswith(name) for key in tests), name

    def test_every_test_states_what_would_refute_it(self, bundle: Dict[str, Any]) -> None:
        for name, item in bundle["falsification"].items():
            if not isinstance(item, Mapping):
                continue
            assert item["question"] and item["refuting_condition"]
            assert isinstance(item["holds"], bool)
            assert item["verdict"]

    def test_f1_set_is_not_the_majority(self, bundle: Dict[str, Any]) -> None:
        measured = bundle["falsification"]["F1_mostly_SET"]["measured"]
        assert measured["set_share"] < 0.5
        assert bundle["falsification"]["F1_mostly_SET"]["holds"] is False

    def test_f2_delta_is_rejected_but_ramp_and_toggle_are_shared(
        self, bundle: Dict[str, Any]
    ) -> None:
        measured = bundle["falsification"]["F2_constructions_in_many_songs"]["measured"]
        assert measured["DELTA_songs"] == []
        assert len(measured["RAMP_songs"]) >= 3
        assert len(measured["TOGGLE_songs"]) == 4

    def test_f3_coverage_does_not_collapse(self, bundle: Dict[str, Any]) -> None:
        item = bundle["falsification"]["F3_coverage_collapse_on_leave_one_out"]
        assert item["holds"] is False
        measured = item["measured"]
        assert measured["shared_vocabulary_coverage"] >= (
            0.5 * measured["in_sample_structural_coverage"]
        )

    def test_f4_confirms_the_lexicon_dominance(self, bundle: Dict[str, Any]) -> None:
        item = bundle["falsification"]["F4_residual_dominance"]
        assert item["holds"] is True
        assert item["measured"]["lexicon_share_of_G6"] > 0.5
        assert item["measured"]["lexicon_loo_references"] == 0

    def test_f5_reports_the_parameter_question_honestly(self, bundle: Dict[str, Any]) -> None:
        item = bundle["falsification"]["F5_small_only_because_of_parameters"]
        assert item["measured"]
        for row in item["measured"].values():
            assert row["total_parameter_cardinality"] >= row["shared_parameter_count"]

    def test_f6_reports_the_marginal_gains(self, bundle: Dict[str, Any]) -> None:
        measured = bundle["falsification"]["F6_marginal_gain"]["measured"]
        assert measured["G2"]["mean_grand_total"] > measured["G5"]["mean_grand_total"]
        assert measured["G4"]["mean_grand_total"] > measured["G5"]["mean_grand_total"]

    def test_the_reading_names_the_two_results_that_matter(
        self, bundle: Dict[str, Any]
    ) -> None:
        reading = bundle["falsification"]["reading"]
        assert "F1" in reading and "F4" in reading



@requires_corpus
class TestVerdictsAndAnswer:
    def test_all_four_verdicts_are_from_the_allowed_sets(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["H1"]["verdict"] in stage19.VERDICT_EXISTENCE
        assert verdicts["H2"]["verdict"] in stage19.VERDICT_GENERALIZATION
        assert verdicts["H3"]["verdict"] in stage19.VERDICT_GENERATOR
        assert verdicts["player_integration"]["verdict"] in stage19.VERDICT_INTEGRATION

    def test_h1_follows_from_its_stated_thresholds(self, bundle: Dict[str, Any]) -> None:
        block = bundle["verdicts"]["H1"]
        measured = block["measured"]
        expected = (
            stage19.VERDICT_EXISTENCE[0]
            if (measured["structural_coverage"] >= stage19.H1_COVERAGE_THRESHOLD
                and measured["saving_percent_with_grammar"]
                >= stage19.H1_SAVING_THRESHOLD_PERCENT
                and measured["all_exact"])
            else stage19.VERDICT_EXISTENCE[1]
        )
        assert block["verdict"] == expected

    def test_h3_is_never_promising_without_a_transferring_lexicon(
        self, bundle: Dict[str, Any]
    ) -> None:
        block = bundle["verdicts"]["H3"]
        if not block["measured"]["lexicon_transfers"]:
            assert block["verdict"] == "GENERATOR_LAYER_NOT_JUSTIFIED"
        assert block["verdict"] != "GENERATOR_LAYER_PROMISING"

    def test_the_integration_verdict_names_a_deciding_condition(
        self, bundle: Dict[str, Any]
    ) -> None:
        block = bundle["verdicts"]["player_integration"]
        assert len(block["conditions"]) == 7
        expected = (
            stage19.VERDICT_INTEGRATION[0]
            if all(item["met"] for item in block["conditions"])
            else stage19.VERDICT_INTEGRATION[1]
        )
        assert block["verdict"] == expected
        if block["verdict"] == stage19.VERDICT_INTEGRATION[1]:
            failed = [item for item in block["conditions"] if not item["met"]]
            assert block["deciding_condition"] == failed[0]["condition"]

    def test_the_final_answer_answers_every_axis(self, bundle: Dict[str, Any]) -> None:
        answer = bundle["final_answer"]
        assert "answer_in_short" in answer
        lines = answer["answer_in_two_lines"]
        for key in ("existence", "generalization", "generative_usefulness"):
            assert key in lines, key
        assert len(answer["what_would_change_the_answer"]) >= 3
        assert answer["what_this_stage_does_not_claim"]

    def test_the_answer_never_claims_musical_usefulness(self, bundle: Dict[str, Any]) -> None:
        claims = bundle["final_answer"]["what_this_stage_does_not_claim"]
        assert any("usefulness" in item or "meaning" in item for item in claims)

    def test_compression_is_not_equated_with_usefulness(self, bundle: Dict[str, Any]) -> None:
        claims = " ".join(bundle["final_answer"]["what_this_stage_does_not_claim"]).lower()
        assert "compression" in claims or "meaning" in claims



# ---------------------------------------------------------------------------
# 8. The report and the CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestReport:
    def test_the_report_has_the_eighteen_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle)
        for number in range(1, 19):
            assert re.search(rf"(?m)^## {number}\. ", text), f"section {number} missing"

    def test_the_report_ends_with_the_final_question(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle)
        assert "## Final question" in text
        assert text.index("## Final question") > text.index("## 18. Final Verdict")

    def test_the_report_renders_without_a_traceback(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle)
        assert "Traceback" not in text
        assert "None" not in text
        assert len(text) > 20000

    def test_the_report_names_the_stop_condition(self, bundle: Dict[str, Any]) -> None:
        assert "nothing was implemented in production" in stage19.render_report(bundle).lower()

    def test_the_report_says_what_it_does_not_claim(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle).lower()
        assert "not claim" in text
        assert "no listening test was run" in text

    def test_the_report_states_the_neutrality_rule(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle).lower()
        assert "melody" in text
        assert "musical concept" in text

    def test_the_report_records_the_corrected_overclaim(self, bundle: Dict[str, Any]) -> None:
        """The self-evidently impossible pattern saving is documented, not quietly removed."""
        text = stage19.render_report(bundle)
        assert "955,678" in text
        assert "self-evidently impossible" in text

    def test_the_report_records_the_toggle_artefact(self, bundle: Dict[str, Any]) -> None:
        text = stage19.render_report(bundle)
        assert "9,175 frames" in text

    def test_the_summary_is_written(self, bundle: Dict[str, Any]) -> None:
        summary = bundle["summary"]
        for key in (
            "analysis_version", "songs", "shared_vocabulary", "grammar_ratio",
            "grammar_ratio_with_grammar", "grammar_structural_coverage", "repeat_ratio",
            "repeat_leave_one_out_ratio", "verdicts", "final_answer_short",
        ):
            assert key in summary, key


@requires_corpus
class TestCli:
    def test_the_command_writes_the_record_and_the_document(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        docs = tmp_path / "docs"
        result = CliRunner().invoke(
            cli, ["analyze-stage19", "--reports-dir", str(reports), "--docs-dir", str(docs)]
        )
        assert result.exit_code == 0, result.output
        assert (docs / stage19.STAGE19_DOC).is_file()
        for name in stage19.STAGE19_FILES:
            assert (reports / name).is_file()
        assert "TEMPORAL_GRAMMAR" in result.output
        assert "DELTA" not in result.output.split("Induced per song:")[1].split("\n")[0]

    def test_the_cli_reports_the_same_verdicts_as_the_bundle(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["analyze-stage19", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d")],
        )
        assert result.exit_code == 0, result.output
        written = json.loads((tmp_path / "r" / "summary.json").read_text(encoding="utf-8"))
        for verdict in written["verdicts"].values():
            assert verdict in result.output


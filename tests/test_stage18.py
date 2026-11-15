"""Stage 18 — temporal compression of the POKEY performance history.

These tests pin the experiment to the four Stage 16 songs, prove it is read-only and
deterministic, and lock down the property the whole stage rests on: every codec is a *real*
byte format that decodes back to the canonical raw representation exactly.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage15
from atari_music import stage18
from atari_music.cli import cli

requires_corpus = pytest.mark.skipif(
    not stage18.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage18.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage18.run_analysis()


# --- synthetic streams, so the edge cases do not depend on the corpus ---------------------
def make_stream(slug: str, columns: Dict[str, Any], period_us: int = 20000) -> stage18.FrameStream:
    frames = len(next(iter(columns.values()))) if columns else 0
    return stage18.FrameStream(
        slug=slug, frames=frames, frame_period_us=period_us,
        registers={name: tuple(columns[name]) for name in stage18.REGISTER_ORDER},
    )


def uniform(frames: int, value: int) -> stage18.FrameStream:
    return make_stream(
        "uniform-" + str(frames),
        {name: [value] * frames for name in stage18.REGISTER_ORDER},
    )


def linear(frames: int, step: int) -> stage18.FrameStream:
    return make_stream(
        "linear-" + str(frames),
        {name: [(index * step) & 0xFF for index in range(frames)]
         for name in stage18.REGISTER_ORDER},
    )


def empty_stream() -> stage18.FrameStream:
    return make_stream("empty", {name: [] for name in stage18.REGISTER_ORDER})


def every_codec() -> list:
    """One instance of every codec family, for the round-trip sweeps."""
    return (
        [stage18.RAW_CODEC]
        + list(stage18.RLE_CODECS)
        + list(stage18.DELTA_CODECS)
        + list(stage18.ramp_codecs((3,)))
        + list(stage18.lz_codecs((64,), (2,)))
        + [stage18.dictionary_codec(
            [(2, bytes(range(stage18.FRAME_BYTES * 2)))], ["synthetic"]
        )]
        + list(stage18.hybrid_codecs((256,)))
    )


# ---------------------------------------------------------------------------
# 1. Determinism and read-only behaviour
# ---------------------------------------------------------------------------
@requires_corpus
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage18.run_analysis() == bundle

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        first = stage18.write_analysis(
            stage18.run_analysis(), stage18_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        second = stage18.write_analysis(
            stage18.run_analysis(), stage18_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        hashes_a = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in first.items()
        }
        hashes_b = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in second.items()
        }
        assert hashes_a == hashes_b
        assert set(hashes_a) == set(stage18.STAGE18_FILES) | {stage18.STAGE18_DOC}
        assert len(stage18.STAGE18_FILES) == 12

    def test_nothing_upstream_is_written(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        watched = (
            list(stage15.list_traces())
            + sorted(stage18.DEFAULT_STAGE15_DIR.glob("*.json"))
            + sorted(stage18.DEFAULT_STAGE16_DIR.glob("*.json"))
            + sorted(stage18.DEFAULT_STAGE17_DIR.glob("*.json"))
            + [stage18.DEFAULT_PLAYER_ASM]
        )
        before = {str(path): stage18.sha256_file(path) for path in watched if path.is_file()}
        assert before, "expected some upstream artefacts to watch"
        stage18.write_analysis(bundle, stage18_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        after = {str(path): stage18.sha256_file(path) for path in watched if path.is_file()}
        assert before == after

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage18.render_report(bundle)
        assert "created_utc" not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text)

    def test_no_audio_or_music_is_produced(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        written = stage18.write_analysis(
            bundle, stage18_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        assert {path.suffix for path in written.values()} == {".json", ".md"}

    def test_the_source_hash_travels_with_the_bundle(self, bundle: Dict[str, Any]) -> None:
        assert bundle["determinism"]["source_hash"] == stage18.sha256_file(Path(stage18.__file__))

    def test_equal_cost_choices_have_a_stated_tie_break(self, bundle: Dict[str, Any]) -> None:
        assert "tie_breaks" in bundle["determinism"]
        assert "earliest member" in bundle["determinism"]["tie_breaks"]


# ---------------------------------------------------------------------------
# 2. The canonical representation and the container
# ---------------------------------------------------------------------------
@requires_corpus
class TestCanonicalRepresentation:
    def test_a_frame_is_nine_registers_in_a_fixed_order(self) -> None:
        assert stage18.FRAME_BYTES == 9
        assert stage18.REGISTER_ORDER == (
            "AUDF1", "AUDC1", "AUDF2", "AUDC2", "AUDF3", "AUDC3", "AUDF4", "AUDC4", "AUDCTL",
        )

    def test_the_order_agrees_with_stage17(self) -> None:
        from atari_music import stage17

        assert stage18.REGISTER_ORDER == tuple(stage17.REGISTER_ORDER)

    def test_the_payload_is_frames_times_nine(self, bundle: Dict[str, Any]) -> None:
        streams, _ = stage18.load_dataset()
        for stream in streams:
            assert len(stream.payload()) == stream.frames * stage18.FRAME_BYTES

    def test_the_payload_is_interleaved_not_planar(self) -> None:
        stream = make_stream(
            "interleave",
            {name: [index + 1] for index, name in enumerate(stage18.REGISTER_ORDER)},
        )
        assert stream.payload() == bytes(range(1, 10))

    def test_a_payload_round_trips_through_the_stream_object(self) -> None:
        stream = linear(10, 3)
        rebuilt = stage18.stream_from_payload("x", 10, 20000, stream.payload())
        assert rebuilt.payload() == stream.payload()
        assert rebuilt.registers == stream.registers

    def test_a_short_payload_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.stream_from_payload("x", 10, 20000, b"\x00" * 8)

    def test_the_container_round_trips(self) -> None:
        payload = b"\x01\x02\x03"
        container = stage18.make_container(7, 1234, 20056, payload)
        codec_id, flags, frames, period, read_payload = stage18.parse_container(container)
        assert (codec_id, flags, frames, period) == (7, 0, 1234, 20056)
        assert read_payload == payload

    def test_the_container_header_is_the_same_size_for_every_codec(self) -> None:
        stream = uniform(4, 0x11)
        sizes = {
            len(stage18.make_container(0, stream.frames, stream.frame_period_us,
                                       codec.encode(stream)))
            - len(codec.encode(stream))
            for codec in every_codec()
        }
        assert sizes == {stage18.CONTAINER_HEADER_BYTES}

    def test_a_bad_magic_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.parse_container(b"XX" + b"\x00" * 10)

    def test_a_truncated_container_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.parse_container(b"P8")



# ---------------------------------------------------------------------------
# 3. Round trips: the corpus, and the synthetic edge cases
# ---------------------------------------------------------------------------
@requires_corpus
class TestCorpusRoundTrips:
    def test_every_measurement_in_the_suite_is_lossless(self, bundle: Dict[str, Any]) -> None:
        assert bundle["reconstruction"]["failures"] == []
        assert bundle["reconstruction"]["all_lossless"] is True

    def test_each_recorded_measurement_decoded_exactly(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["reconstruction"]["per_codec"]:
            assert row["lossless"] is True, (row["label"], row["slug"])
            assert row["first_divergence_frame"] is None
            assert row["differing_values"] == 0
            assert row["max_error"] == 0
            assert row["correct_frame_percent"] == 100.0

    def test_the_number_of_measurements_matches_the_codec_count(
        self, bundle: Dict[str, Any]
    ) -> None:
        assert bundle["reconstruction"]["measurements"] == len(
            bundle["reconstruction"]["per_codec"]
        )
        assert bundle["reconstruction"]["measurements"] > 100


class TestSyntheticRoundTrips:
    def _check(self, stream: stage18.FrameStream, codecs: list) -> None:
        reference = stream.payload()
        for codec in codecs:
            encoded = codec.encode(stream)
            assert codec.decode(encoded, stream.frames) == reference, codec.label

    def test_empty_trace(self) -> None:
        self._check(empty_stream(), every_codec())

    def test_single_frame(self) -> None:
        self._check(uniform(1, 0x00), every_codec())
        self._check(uniform(1, 0xFF), every_codec())

    def test_long_run(self) -> None:
        self._check(uniform(5000, 0x5A), every_codec())

    def test_maximum_register_values(self) -> None:
        self._check(uniform(64, 0xFF), every_codec())

    def test_boundary_values(self) -> None:
        """0x00 and 0xFF alternating exercises the delta wrap in both directions."""
        columns = {
            name: [0x00 if index % 2 else 0xFF for index in range(64)]
            for name in stage18.REGISTER_ORDER
        }
        self._check(make_stream("boundary", columns), every_codec())

    def test_a_linear_ramp(self) -> None:
        self._check(linear(400, 1), every_codec())
        self._check(linear(400, 7), every_codec())

    def test_a_periodic_motif(self) -> None:
        pattern = [bytes([index * 3 % 256] * stage18.FRAME_BYTES) for index in range(4)]
        flattened = (pattern * 50)
        columns = {
            name: [chunk[offset] for chunk in flattened]
            for offset, name in enumerate(stage18.REGISTER_ORDER)
        }
        self._check(make_stream("periodic", columns), every_codec())

    def test_the_ramp_codec_uses_a_literal_escape_when_it_must(self) -> None:
        """A third-order sequence is not CONST, LINEAR or QUAD, so the escape must carry it.

        The first attempt at this test used ``i*37 + i*i*11``, which has a *constant second
        difference* and is therefore a perfect QUAD run - the finder was right and the test was
        wrong. A cubic term makes the second difference change every step.
        """
        values = [(index * 37 + index * index * 11 + index ** 3 * 5) % 256
                  for index in range(200)]
        columns = {name: list(values) for name in stage18.REGISTER_ORDER}
        stream = make_stream("third-order", columns)
        codec = stage18.ramp_codecs((3,))[0]
        self._check(stream, [codec])
        segments = stage18.segment_register(values, 3)
        assert any(tag == stage18.SEG_LITERAL for tag, _, _ in segments)


class TestCodecInternals:
    def test_uvarint_round_trips_at_the_boundaries(self) -> None:
        for value in (0, 1, 127, 128, 16383, 16384, 2 ** 21, 2 ** 28):
            encoded = stage18.uvarint(value)
            assert len(encoded) == stage18.uvarint_bytes(value)
            decoded, pos = stage18.read_uvarint(encoded, 0)
            assert decoded == value and pos == len(encoded)

    def test_uvarint_refuses_a_negative_value(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.uvarint(-1)

    def test_zigzag_round_trips(self) -> None:
        for value in (-1000, -1, 0, 1, 1000):
            assert stage18.unzigzag(stage18.zigzag(value)) == value

    def test_a_truncated_uvarint_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.read_uvarint(b"\x80", 0)

    def test_rle_groups_maximal_runs(self) -> None:
        assert stage18._group_runs([1, 1, 2, 2, 2, 3]) == [(2, 1), (3, 2), (1, 3)]
        assert stage18._group_runs([]) == []

    def test_the_segment_finders_measure_the_right_span(self) -> None:
        assert stage18._const_length([5, 5, 5, 6], 0) == 3
        assert stage18._linear_length([1, 3, 5, 7, 9], 0) == 5
        assert stage18._quad_length([0, 1, 3, 6, 10, 15], 0) == 6

    def test_the_quad_recurrence_wraps_modulo_256(self) -> None:
        values = [250, 252, 255, 3, 8, 14]
        assert stage18._quad_length(values, 0) == 6
        params = stage18._segment_params(stage18.SEG_QUAD, values, 0)
        assert stage18.segment_values(stage18.SEG_QUAD, 6, params) == values


@requires_corpus
class TestCorruptedInput:
    """A decoder must refuse a broken stream, not silently invent frames."""

    def _codecs(self) -> list:
        return every_codec()

    def test_truncated_payloads_are_refused(self) -> None:
        streams, _ = stage18.load_dataset()
        stream = min(streams, key=lambda item: item.frames)
        short = stage18.substream(stream, 0, 400)
        for codec in self._codecs():
            payload = codec.encode(short)
            for cut in (0, 1, 2, len(payload) // 2, len(payload) - 1):
                with pytest.raises(stage18.Stage18Error):
                    codec.decode(payload[:cut], short.frames)

    def test_an_unknown_token_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.decode_lz(b"\x7F", 1)
        with pytest.raises(stage18.Stage18Error):
            stage18.decode_dictionary(b"\x00\x7F", 1)

    def test_an_unknown_segment_tag_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.decode_ramps_stream(b"\x01\x09\x00", 1)

    def test_an_out_of_range_dictionary_reference_is_refused(self) -> None:
        payload = stage18.uvarint(0) + bytes([stage18.TOKEN_DICT]) + stage18.uvarint(5)
        with pytest.raises(stage18.Stage18Error):
            stage18.decode_dictionary(payload, 1)

    def test_an_lz_match_before_the_start_is_refused(self) -> None:
        payload = bytes([stage18.TOKEN_MATCH]) + stage18.uvarint(9) + stage18.uvarint(1)
        with pytest.raises(stage18.Stage18Error):
            stage18.decode_lz(payload, 1)

    def test_a_stream_that_decodes_to_the_wrong_frame_count_is_refused(self) -> None:
        payload = stage18.encode_rle_frame(uniform(5, 0x11))
        with pytest.raises(stage18.Stage18Error):
            stage18.decode_rle_frame(payload, 6)

    def test_a_register_out_of_range_is_refused(self) -> None:
        with pytest.raises(stage18.Stage18Error):
            stage18.registers_to_payload({name: [999] for name in stage18.REGISTER_ORDER}, 1)


# ---------------------------------------------------------------------------
# 4. Dictionary, cross-song model and generalisation
# ---------------------------------------------------------------------------
@requires_corpus
class TestDictionaryAndCrossSong:
    def test_a_motif_table_is_built_deterministically(self) -> None:
        stream = make_stream(
            "periodic",
            {name: [index % 3 for index in range(60)] for name in stage18.REGISTER_ORDER},
        )
        first = stage18.build_motif_table([stream], lengths=(2, 3), top_k=8)
        second = stage18.build_motif_table([stream], lengths=(2, 3), top_k=8)
        assert first == second
        assert first, "a repeating stream must yield at least one motif"

    def test_the_dictionary_table_travels_inside_the_payload(self) -> None:
        stream = make_stream(
            "periodic",
            {name: [index % 3 for index in range(60)] for name in stage18.REGISTER_ORDER},
        )
        table = stage18.build_motif_table([stream], lengths=(2, 3), top_k=4)
        payload = stage18.encode_dictionary(stream, table)
        split = stage18.dictionary_split(payload)
        assert split["dictionary_bytes"] > 0
        assert split["body_bytes"] > 0
        assert split["dictionary_bytes"] + split["body_bytes"] == len(payload)

    def test_a_dictionary_payload_is_not_smaller_than_its_table(self) -> None:
        """The table is charged, which is the whole point of the failure it measures."""
        stream = make_stream(
            "periodic",
            {name: [index % 5 for index in range(200)] for name in stage18.REGISTER_ORDER},
        )
        table = stage18.build_motif_table([stream], lengths=(2, 4), top_k=16)
        payload = stage18.encode_dictionary(stream, table)
        assert stage18.dictionary_split(payload)["dictionary_bytes"] > 0

    def test_leave_one_out_reports_a_fold_per_song(self, bundle: Dict[str, Any]) -> None:
        folds = bundle["dictionary"]["folds"]
        assert len(folds) == 4
        slugs = {fold["held_out"] for fold in folds}
        assert slugs == set(bundle["summary"]["songs"])
        for fold in folds:
            assert fold["held_out"] not in fold["trained_on"]
            assert len(fold["trained_on"]) == 3

    def test_one_shared_configuration_is_lossless_on_every_song(
        self, bundle: Dict[str, Any]
    ) -> None:
        best = bundle["best_configurations"]["overall_best"]
        assert best["lossless_on_all_songs"] is True

    def test_the_per_song_best_is_reported_for_every_song(self, bundle: Dict[str, Any]) -> None:
        per_song = bundle["best_configurations"]["best_per_song"]
        assert set(per_song) == set(bundle["summary"]["songs"])
        for row in per_song.values():
            assert row["label"] and row["ratio"] <= 1.0

    def test_only_lossless_configurations_are_eligible_for_best(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The best is the minimum mean ratio among the lossless rows, and nothing else."""
        rows = bundle["cross_song"]["configurations"]
        lossless = [row for row in rows if row["lossless_on_all_songs"]]
        assert lossless, "expected at least one lossless configuration"
        expected = sorted(lossless, key=lambda row: (row["ratio"]["mean"], row["label"]))[0]
        best = bundle["best_configurations"]["overall_best"]
        assert best["label"] == expected["label"]
        assert best["mean_ratio"] == expected["ratio"]["mean"]



# ---------------------------------------------------------------------------
# 5. Compression accounting, costs and comparison
# ---------------------------------------------------------------------------
@requires_corpus
class TestAccounting:
    def test_ratios_are_compressed_over_raw(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["reconstruction"]["per_codec"]:
            assert row["compression_ratio"] == pytest.approx(
                row["compressed_bytes"] / row["raw_bytes"], abs=1e-5
            )

    def test_saving_percent_is_consistent_with_the_ratio(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["reconstruction"]["per_codec"]:
            assert row["saving_percent"] == pytest.approx(
                100.0 * (1.0 - row["compression_ratio"]), abs=1e-4
            )

    def test_the_container_header_is_counted_in_every_total(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["reconstruction"]["per_codec"]:
            assert row["compressed_bytes"] == row["payload_bytes"] + row["header_bytes"]
            assert row["header_bytes"] == stage18.CONTAINER_HEADER_BYTES
            assert row["raw_bytes"] > 0

    def test_raw_is_the_baseline_at_exactly_one(self, bundle: Dict[str, Any]) -> None:
        raw_rows = [row for row in bundle["reconstruction"]["per_codec"] if row["codec"] == "raw"]
        assert raw_rows
        for row in raw_rows:
            assert row["compression_ratio"] == 1.0
            assert row["saving_percent"] == 0.0

    def test_whole_frame_rle_is_larger_than_raw(self, bundle: Dict[str, Any]) -> None:
        rows = [row for row in bundle["reconstruction"]["per_codec"] if row["codec"] == "rle_frame"]
        assert all(row["compression_ratio"] > 1.0 for row in rows)

    def test_the_explicit_dictionary_plane_fails(self, bundle: Dict[str, Any]) -> None:
        scopes = bundle["dictionary"]["mean_ratio_by_scope"]
        assert scopes["per_song"] > 1.0
        assert scopes["shared"] > 1.0
        assert scopes["leave_one_out"] > 1.0

    def test_no_reported_result_is_below_the_container_size(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["reconstruction"]["per_codec"]:
            assert row["payload_bytes"] >= 0


@requires_corpus
class TestCostsAndComparison:
    def test_every_codec_family_has_a_cost_row(self, bundle: Dict[str, Any]) -> None:
        families = {row["codec"] for row in bundle["decoder_cost"]["codecs"]}
        assert {"raw", "rle_frame", "rle_register", "delta_gap", "ramps", "lz",
                "dictionary", "hybrid"} <= families

    def test_the_cost_model_is_labelled_an_estimate(self, bundle: Dict[str, Any]) -> None:
        assert "ESTIMATE" in bundle["decoder_cost"]["method"]
        for row in bundle["decoder_cost"]["codecs"]:
            assert row["basis"] == "ESTIMATE"

    def test_a_large_lz_window_is_charged_as_buffer_ram(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["decoder_cost"]["codecs"]:
            if row["codec"] == "lz" and row["label"].endswith("window_frames=1024]"):
                assert row["dictionary_or_buffer_bytes"] == 1024 * stage18.FRAME_BYTES
                break
        else:
            pytest.fail("expected an lz codec with a 1024-frame window")

    def test_a_dictionary_is_charged_its_table(self, bundle: Dict[str, Any]) -> None:
        rows = [row for row in bundle["decoder_cost"]["codecs"] if row["codec"] == "dictionary"]
        assert rows
        assert any(row["dictionary_or_buffer_bytes"] > 0 for row in rows)

    def test_the_comparison_reads_stage17s_own_numbers(self, bundle: Dict[str, Any]) -> None:
        previous = bundle["comparison"]["previous_record"]
        assert previous["available"] is True
        assert previous["source_sha256"] == stage18.sha256_file(Path(previous["source"]))

    def test_the_comparison_covers_all_four_representations(
        self, bundle: Dict[str, Any]
    ) -> None:
        names = {row["representation"] for row in bundle["comparison"]["configurations"]}
        assert len(names) == 4
        assert any("raw" in name for name in names)
        assert any("Stage 17" in name for name in names)
        assert any("current note format" in name for name in names)
        assert any("temporal" in name for name in names)

    def test_the_note_format_is_marked_not_exact(self, bundle: Dict[str, Any]) -> None:
        row = next(
            item for item in bundle["comparison"]["configurations"]
            if item["representation"] == "current note format"
        )
        assert row["exact"] is False

    def test_the_current_format_is_smaller_than_the_temporal_encoding(
        self, bundle: Dict[str, Any]
    ) -> None:
        mean = bundle["comparison"]["summary"]["current_note_format_vs_temporal"]["mean"]
        assert mean is not None and mean < 1.0

    def test_temporal_compression_beats_stage17(self, bundle: Dict[str, Any]) -> None:
        mean = bundle["comparison"]["summary"]["stage17_exact_vs_temporal"]["mean"]
        assert mean is not None and mean > 1.0



# ---------------------------------------------------------------------------
# 6. Verdicts, failure analysis, falsification and the report
# ---------------------------------------------------------------------------
@requires_corpus
class TestVerdictsAndReport:
    def test_both_verdicts_are_chosen(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["temporal_compression"]["verdict"] in (
            "TEMPORAL_COMPRESSION_SUPPORTED", "TEMPORAL_COMPRESSION_PARTIALLY_SUPPORTED",
            "TEMPORAL_COMPRESSION_NOT_SUPPORTED",
        )
        assert verdicts["player_integration"]["verdict"] in (
            "PLAYER_INTEGRATION_JUSTIFIED", "PLAYER_INTEGRATION_NOT_JUSTIFIED",
        )

    def test_the_compression_verdict_follows_from_its_rule(self, bundle: Dict[str, Any]) -> None:
        row = bundle["verdicts"]["temporal_compression"]
        saving = row["mean_saving_percent"]
        lossless = row["lossless_on_all_songs"]
        if saving >= stage18.SUPPORTED_SAVING_PERCENT and lossless:
            expected = "TEMPORAL_COMPRESSION_SUPPORTED"
        elif saving >= stage18.PARTIAL_SAVING_PERCENT and lossless:
            expected = "TEMPORAL_COMPRESSION_PARTIALLY_SUPPORTED"
        else:
            expected = "TEMPORAL_COMPRESSION_NOT_SUPPORTED"
        assert row["verdict"] == expected

    def test_the_integration_verdict_follows_from_all_seven_conditions(
        self, bundle: Dict[str, Any]
    ) -> None:
        integration = bundle["verdicts"]["player_integration"]
        assert len(integration["conditions"]) == 7
        expected = (
            "PLAYER_INTEGRATION_JUSTIFIED"
            if all(item["met"] for item in integration["conditions"])
            else "PLAYER_INTEGRATION_NOT_JUSTIFIED"
        )
        assert integration["verdict"] == expected

    def test_the_deciding_condition_is_named_when_integration_is_refused(
        self, bundle: Dict[str, Any]
    ) -> None:
        integration = bundle["verdicts"]["player_integration"]
        if integration["verdict"] == "PLAYER_INTEGRATION_NOT_JUSTIFIED":
            assert integration["deciding_condition"]
            failed = [item for item in integration["conditions"] if not item["met"]]
            assert integration["deciding_condition"] == failed[0]["condition"]

    def test_every_failure_has_a_cause(self, bundle: Dict[str, Any]) -> None:
        failures = bundle["failure_analysis"]["failures"]
        assert failures
        for item in failures:
            assert item["method"] and item["measured"] and item["cause"] and item["verdict"]

    def test_the_falsification_section_lists_refutations(self, bundle: Dict[str, Any]) -> None:
        refuting = bundle["falsification"]["refuting_results"]
        assert refuting
        for item in refuting:
            assert item["result"] and item["detail"]

    def test_the_final_answer_answers_both_halves(self, bundle: Dict[str, Any]) -> None:
        answer = bundle["final_answer"]
        lines = answer["answer_in_two_lines"]
        assert "versus_stage_17_event_ir" in lines
        assert "versus_current_note_format" in lines
        assert len(answer["what_would_change_the_answer"]) >= 3

    def test_the_report_has_the_seventeen_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage18.render_report(bundle)
        for number in range(1, 18):
            assert re.search(rf"(?m)^## {number}\. ", text), f"section {number} missing"

    def test_the_report_ends_with_the_final_question(self, bundle: Dict[str, Any]) -> None:
        assert "## Final question" in stage18.render_report(bundle)

    def test_the_report_renders_without_a_traceback(self, bundle: Dict[str, Any]) -> None:
        text = stage18.render_report(bundle)
        assert "Traceback" not in text
        assert len(text) > 20000

    def test_the_report_names_the_stop_condition(self, bundle: Dict[str, Any]) -> None:
        assert "nothing was implemented in production" in stage18.render_report(bundle).lower()

    def test_the_raw_baseline_is_documented(self, bundle: Dict[str, Any]) -> None:
        baseline = bundle["raw_baseline"]
        for key in ("absolute_or_delta", "how_no_change_is_represented", "first_values",
                    "audctl", "container"):
            assert key in baseline["choices"]
        assert baseline["percent_baseline"] == 100.0

    def test_the_motif_section_reports_detection_not_a_size(self, bundle: Dict[str, Any]) -> None:
        assert bundle["motifs"]["statistics"]
        text = stage18.render_report(bundle)
        assert "compression result" in text
        assert "upper bound" in text

    def test_coverage_is_a_union_not_a_sum_of_occurrences(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The first version of this column summed overlapping occurrences and read 1.0 always."""
        for row in bundle["motifs"]["statistics"]:
            for length_row in row["by_length"]:
                assert 0.0 <= length_row["coverage_share"] <= 1.0
                assert length_row["covered_frames"] <= row["frames"]
            shares = {item["coverage_share"] for item in row["by_length"]}
            assert len(shares) > 1, "a constant column carries no information"

    def test_the_optimistic_bound_arithmetic_is_consistent(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["motifs"]["statistics"]:
            for length_row in row["by_length"]:
                assert length_row["net_optimistic_bytes"] == (
                    length_row["optimistic_saving_bytes"] - length_row["table_cost_bytes"]
                )
                assert length_row["optimistic_saving_bytes"] > 0
                assert "upper bound" in length_row["upper_bound_note"]

    def test_the_bound_does_not_rule_out_short_motifs(self, bundle: Dict[str, Any]) -> None:
        """Honesty check: at length 2 the optimistic net is positive, so the bound is not a proof.

        The stage may only claim that the bound *narrows* the window. If this ever becomes
        negative the report's prose must change with it, so the assertion is on the fact, not on
        the wish.
        """
        short = [
            length_row
            for row in bundle["motifs"]["statistics"]
            for length_row in row["by_length"]
            if length_row["length_frames"] == 2
        ]
        assert short
        assert all(item["net_optimistic_bytes"] > 0 for item in short)
        text = stage18.render_report(bundle)
        assert "does **not** settle the question" in text

    def test_the_real_dictionary_fails_even_where_the_bound_was_positive(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The whole point: a generous bound said yes to length 2, the real encoder said no."""
        assert all(
            value > 1.0 for value in bundle["dictionary"]["mean_ratio_by_scope"].values()
        )

    def test_stage17s_open_questions_are_accounted_for(self, bundle: Dict[str, Any]) -> None:
        """Every question Stage 17 handed over gets an explicit status, answered or not."""
        questions = bundle["previous_questions"]
        assert questions["available"] is True
        assert questions["source"].endswith("architecture.json")
        assert questions["answers"], "Stage 17 named candidates for this stage"
        assert questions["answered_count"] == sum(
            1 for item in questions["answers"] if item["status"] == "answered"
        )
        for item in questions["answers"]:
            assert item["status"] in ("answered", "not addressed")
            assert item["question"] and item["evidence"] and item["candidate"]

    def test_the_unanswered_questions_are_stated_as_such(self, bundle: Dict[str, Any]) -> None:
        questions = bundle["previous_questions"]
        unanswered = [item for item in questions["answers"] if item["status"] != "answered"]
        assert unanswered, "this stage must not pretend to close every open question"
        text = stage18.render_report(bundle)
        assert "deliberately left open" in text

    def test_a_question_about_a_composer_is_not_claimed(self, bundle: Dict[str, Any]) -> None:
        """The stage generates no music, so it must not claim the composer question."""
        item = next(
            question for question in bundle["previous_questions"]["answers"]
            if "composer" in question["question"].lower()
        )
        assert item["status"] == "not addressed"





# ---------------------------------------------------------------------------
# 7. CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestCli:
    def test_the_command_writes_the_record_and_the_document(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        docs = tmp_path / "docs"
        result = CliRunner().invoke(
            cli, ["analyze-stage18", "--reports-dir", str(reports), "--docs-dir", str(docs)]
        )
        assert result.exit_code == 0, result.output
        assert (docs / stage18.STAGE18_DOC).is_file()
        for name in stage18.STAGE18_FILES:
            assert (reports / name).is_file()
        assert "TEMPORAL_COMPRESSION" in result.output

    def test_the_cli_reports_the_same_verdicts_as_the_bundle(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["analyze-stage18", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d")],
        )
        assert result.exit_code == 0, result.output
        written = json.loads((tmp_path / "r" / "summary.json").read_text(encoding="utf-8"))
        assert written["verdicts"]["temporal_compression"] in result.output
        assert written["verdicts"]["player_integration"] in result.output

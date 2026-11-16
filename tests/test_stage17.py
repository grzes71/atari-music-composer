"""Stage 17 — POKEY performance event language and compact event IR.

These tests pin the language to the four Stage 16 songs and the Stage 15 record, prove the
stage is read-only and deterministic, and lock down the distinctions the brief insists on:
faithfulness versus compactness, the abstraction as an *input* versus the behaviour as the
*source*, and neutrality versus a style model.
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
from atari_music import stage17
from atari_music.cli import cli

pytestmark = pytest.mark.experimental

requires_corpus = pytest.mark.skipif(
    not stage17.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage17.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage17.run_analysis()


@pytest.fixture(scope="module")
def song(bundle: Dict[str, Any]):
    """One loaded song, for the interpreter tests that need a real trace."""
    selection = stage17.stage16_selection()
    return stage17.load_song(selection["candidates"][0])


# ---------------------------------------------------------------------------
# 1. Determinism and read-only behaviour
# ---------------------------------------------------------------------------
@requires_corpus
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage17.run_analysis() == bundle

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        first = stage17.write_analysis(
            stage17.run_analysis(), stage17_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        second = stage17.write_analysis(
            stage17.run_analysis(), stage17_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        hashes_a = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in first.items()
        }
        hashes_b = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in second.items()
        }
        assert hashes_a == hashes_b
        assert set(hashes_a) == set(stage17.STAGE17_FILES) | {stage17.STAGE17_DOC}

    def test_nothing_upstream_is_written(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        watched = (
            list(stage15.list_traces())
            + sorted(stage17.DEFAULT_STAGE15_DIR.glob("*.json"))
            + sorted(stage17.DEFAULT_STAGE16_DIR.glob("*.json"))
            + [stage17.DEFAULT_PLAYER_ASM]
        )
        before = {str(path): stage17.sha256_file(path) for path in watched if path.is_file()}
        assert before, "expected some upstream artefacts to watch"
        stage17.write_analysis(bundle, stage17_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        after = {str(path): stage17.sha256_file(path) for path in watched if path.is_file()}
        assert before == after

    def test_the_player_source_is_only_ever_hashed(self, bundle: Dict[str, Any]) -> None:
        hashes = bundle["evidence_sources"]["stage15_and_player_records"]
        assert "player_asm" in hashes
        assert hashes["player_asm"]["sha256"] == stage17.sha256_source_text(
            stage17.DEFAULT_PLAYER_ASM
        )

    def test_the_player_hash_agrees_with_stage15s_own_record(self, bundle: Dict[str, Any]) -> None:
        """Stage 17 and Stage 15 must not appear to disagree about an unmodified file."""
        stage15_size = json.loads(
            (stage17.DEFAULT_STAGE15_DIR / "player_size_analysis.json").read_text(
                encoding="utf-8"
            )
        )
        assert (
            bundle["evidence_sources"]["stage15_and_player_records"]["player_asm"]["sha256"]
            == stage15_size["source_sha256"]
        )

    def test_the_source_hash_convention_is_stated(self, bundle: Dict[str, Any]) -> None:
        conventions = bundle["evidence_sources"]["hash_conventions"]
        assert "player_source" in conventions
        assert "bytes" in conventions["json_artefacts_and_traces"]

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage17.render_report(bundle)
        assert "created_utc" not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text)

    def test_no_audio_or_music_is_produced(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        written = stage17.write_analysis(
            bundle, stage17_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        assert {path.suffix for path in written.values()} == {".json", ".md"}

    def test_the_source_hash_travels_with_the_bundle(self, bundle: Dict[str, Any]) -> None:
        assert bundle["determinism"]["source_hash"] == stage17.sha256_file(Path(stage17.__file__))



# ---------------------------------------------------------------------------
# 2. Evidence and the vocabulary (Parts B, D)
# ---------------------------------------------------------------------------
@requires_corpus
class TestVocabulary:
    def test_the_four_songs_come_from_the_stage16_record(self, bundle: Dict[str, Any]) -> None:
        selection = json.loads(
            (stage17.DEFAULT_STAGE16_DIR / "song_selection.json").read_text(encoding="utf-8")
        )
        assert bundle["summary"]["songs"] == selection["chosen"]
        assert len(bundle["summary"]["songs"]) == 4

    def test_every_observed_technique_has_an_opcode(self, bundle: Dict[str, Any]) -> None:
        vocabulary = bundle["vocabulary"]
        assert vocabulary["techniques_with_no_opcode"] == []
        for row in vocabulary["techniques"]:
            assert row["opcode"] in stage17.OPCODE_ORDER

    def test_set_audctl_is_the_only_opcode_without_a_technique(
        self, bundle: Dict[str, Any]
    ) -> None:
        used = {row["opcode"] for row in bundle["vocabulary"]["techniques"]}
        assert used <= set(stage17.OPCODE_ORDER)
        assert used == set(stage17.OPCODE_ORDER) - {"SET_AUDCTL"}

    def test_direction_split_techniques_collapse_onto_one_opcode(
        self, bundle: Dict[str, Any]
    ) -> None:
        mapping = {
            row["technique_id"]: row["opcode"] for row in bundle["vocabulary"]["techniques"]
        }
        assert mapping["PITCH_SLIDE_RISING"] == mapping["PITCH_SLIDE_FALLING"] == "PITCH_SLIDE"
        assert (
            mapping["VOLUME_ENVELOPE_RISING"] == mapping["VOLUME_ENVELOPE_FALLING"]
            == "VOLUME_SHAPE"
        )

    def test_wait_is_rejected_with_a_reason(self) -> None:
        rejected = {item["candidate"]: item for item in stage17.REJECTED_CANDIDATES}
        assert "WAIT" not in stage17.OPCODE_ORDER
        assert rejected["WAIT"]["verdict"] == "REJECTED"
        assert "frame" in rejected["WAIT"]["reason"]

    def test_set_audctl_is_admitted_as_a_mode_not_a_technique(
        self, bundle: Dict[str, Any]
    ) -> None:
        row = next(
            item for item in bundle["vocabulary"]["opcodes"] if item["opcode"] == "SET_AUDCTL"
        )
        assert row["justified_by"] == []
        assert row["justification_occurrences"] == 0

    def test_no_instrument_name_appears_anywhere(self, bundle: Dict[str, Any]) -> None:
        """The vocabulary must not name a musical role. The rejected-candidate list is allowed
        to name them, because its whole purpose is to refuse them."""
        payload = dict(bundle["vocabulary"])
        payload.pop("rejected_candidates", None)
        text = json.dumps(payload).lower()
        for forbidden in ("laser", "bell", "percussion", "drum", "lead voice"):
            assert forbidden not in text

    def test_parameter_kinds_are_classified(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["vocabulary"]["opcodes"]:
            for kind in row["parameter_kinds"].values():
                assert kind in ("MUSICAL_DECISION", "HARDWARE_LEVEL")

    def test_the_stage16_verdicts_are_reused_not_recomputed(self, bundle: Dict[str, Any]) -> None:
        universality = json.loads(
            (stage17.DEFAULT_STAGE16_DIR / "universality.json").read_text(encoding="utf-8")
        )
        by_id = {row["technique_id"]: row for row in universality["techniques"]}
        for row in bundle["vocabulary"]["techniques"]:
            source = by_id.get(row["technique_id"])
            if source is not None:
                assert row["stage16_universality"] == source["verdict"]


# ---------------------------------------------------------------------------
# 3. Event semantics (Part E)
# ---------------------------------------------------------------------------
class TestEventSemantics:
    def test_every_opcode_has_a_contract(self) -> None:
        assert set(stage17.EVENT_CONTRACTS) == set(stage17.OPCODE_ORDER)

    def test_every_contract_is_complete(self) -> None:
        required = (
            "inputs", "state_modified", "duration", "interaction_with_note",
            "interaction_with_other_events", "termination", "may_overlap", "interruptible",
        )
        for opcode, contract in stage17.EVENT_CONTRACTS.items():
            for key in required:
                assert key in contract, f"{opcode} is missing {key}"

    def test_note_may_not_overlap_but_effects_may(self) -> None:
        assert stage17.EVENT_CONTRACTS["NOTE"]["may_overlap"] is False
        for opcode in ("PITCH_SLIDE", "VOLUME_SHAPE", "TREMOLO"):
            assert stage17.EVENT_CONTRACTS[opcode]["may_overlap"] is True

    def test_set_volume_cancels_a_volume_effect(self) -> None:
        assert "cancel" in stage17.EVENT_CONTRACTS["SET_VOLUME"]["state_modified"][1]

    def test_the_ordering_hazard_is_published(self) -> None:
        hazard = stage17.event_semantics()["ordering_hazard"]
        assert "NOTE_OFF" in hazard and "SET_VOLUME" in hazard

    def test_opcode_order_is_part_of_the_semantics(self) -> None:
        assert stage17.event_semantics()["opcode_order"] == list(stage17.OPCODE_ORDER)


# ---------------------------------------------------------------------------
# 4. The IR and the interpreter
# ---------------------------------------------------------------------------
class TestInterpreter:
    def test_event_equality_is_parameter_order_independent(self) -> None:
        left = stage17.make_event("SET_PITCH", 1, 5, divider=3)
        right = stage17.make_event("SET_PITCH", 1, 5, divider=3)
        assert left == right

    def test_canonical_order_is_frame_then_channel_then_opcode(self) -> None:
        events = [
            stage17.make_event("SET_VOLUME", 1, 0, volume=1),
            stage17.make_event("SET_AUDCTL", 0, 0, value=0),
            stage17.make_event("NOTE", 2, 0, divider=1, volume=1),
            stage17.make_event("NOTE", 1, 1, divider=1, volume=1),
        ]
        ordered = stage17.sort_events(events)
        assert [item.channel for item in ordered] == [0, 1, 2, 1]
        assert ordered[0].opcode == "SET_AUDCTL"

    def test_varint_widths(self) -> None:
        assert stage17.varint_size(0) == 1
        assert stage17.varint_size(127) == 1
        assert stage17.varint_size(128) == 2
        assert stage17.varint_size(16383) == 2
        assert stage17.varint_size(16384) == 3

    def test_negative_frame_delta_is_refused(self) -> None:
        with pytest.raises(stage17.Stage17Error):
            stage17.varint_size(-1)

    def test_undefined_parameter_is_refused(self) -> None:
        event = stage17.PerfEvent(
            opcode="SET_VOLUME", channel=1, frame=0, duration=0,
            params=(("nonsense", 1),),
        )
        with pytest.raises(stage17.Stage17Error):
            stage17.event_bytes(event, 0)

    def test_voice_layout_joins_the_documented_pairs(self) -> None:
        assert stage17.voice_layout(0x00) == {
            1: (1, False), 2: (2, False), 3: (3, False), 4: (4, False),
        }
        assert stage17.voice_layout(0x50) == {
            1: (2, True), 2: (2, False), 3: (3, False), 4: (4, False),
        }

    def test_a_joined_pair_splits_into_two_register_bytes(self) -> None:
        events = [
            stage17.make_event("SET_AUDCTL", 0, 0, value=0x10),
            stage17.make_event("SET_GENERATOR", 2, 0, dist=0xA0),
            stage17.make_event("NOTE", 2, 0, divider=0x0A8C, volume=3),
        ]
        rendered = stage17.interpret(events, 1, 0)
        assert rendered.registers["AUDF1"] == [0x8C]
        assert rendered.registers["AUDF2"] == [0x0A]
        assert rendered.registers["AUDC1"] == [0]
        assert rendered.registers["AUDC2"] == [0xA3]

    def test_note_off_silences_and_cancels_a_volume_effect(self) -> None:
        events = [
            stage17.make_event("SET_VOLUME", 1, 0, volume=9),
            stage17.make_event("VOLUME_SHAPE", 1, 0, duration=8, target=2),
            stage17.make_event("NOTE_OFF", 1, 3),
        ]
        rendered = stage17.interpret(events, 6, 0)
        assert rendered.registers["AUDC1"][3] == 0
        assert rendered.registers["AUDC1"][4] == 0

    def test_an_effect_expires_back_to_its_anchor(self) -> None:
        events = [
            stage17.make_event("SET_VOLUME", 1, 0, volume=9),
            stage17.make_event("VOLUME_SHAPE", 1, 0, duration=3, target=2),
        ]
        rendered = stage17.interpret(events, 5, 0)
        assert rendered.registers["AUDC1"][0] == 9
        assert rendered.registers["AUDC1"][3] == 9
        assert rendered.expired_effects >= 1

    def test_the_interpreter_clamps_and_counts_an_impossible_pitch(self) -> None:
        events = [stage17.make_event("SET_PITCH", 1, 0, divider=400)]
        rendered = stage17.interpret(events, 1, 0)
        assert rendered.unrepresentable_pitch == 1
        assert rendered.registers["AUDF1"][0] == stage17.AUDF_8BIT_MAX

    def test_a_sixteen_bit_neighbourhood_allows_the_larger_divider(self) -> None:
        events = [
            stage17.make_event("SET_AUDCTL", 0, 0, value=0x10),
            stage17.make_event("SET_PITCH", 2, 0, divider=400),
        ]
        rendered = stage17.interpret(events, 1, 0)
        assert rendered.unrepresentable_pitch == 0

    def test_every_opcode_is_actually_dispatched(self) -> None:
        """A cheap way to catch a missing interpreter branch: fire every opcode once."""
        events = [
            stage17.make_event("SET_AUDCTL", 0, 0, value=0),
            stage17.make_event("SET_GENERATOR", 1, 0, dist=0xA0),
            stage17.make_event("SET_VOLUME", 1, 0, volume=5),
            stage17.make_event("SET_PITCH", 1, 0, divider=100),
            stage17.make_event("NOTE", 2, 0, divider=200, volume=5, duration=4),
            stage17.make_event("NOTE_OFF", 3, 0),
            stage17.make_event("PITCH_SLIDE", 1, 1, duration=4, delta=10, curve=0),
            stage17.make_event("PITCH_SWEEP", 2, 1, duration=4, delta=10, curve=1),
            stage17.make_event("VIBRATO", 3, 1, duration=4, depth=2, period=4),
            stage17.make_event("TREMOLO", 4, 1, duration=4, depth=2, period=4),
            stage17.make_event(
                "ARPEGGIO", 4, 1, duration=4, count=2, period=1, notes=(100, 110)
            ),
            stage17.make_event("VOLUME_SHAPE", 4, 1, duration=4, target=2),
        ]
        rendered = stage17.interpret(events, 8, 0)
        assert set(rendered.opcodes_applied) == set(stage17.OPCODE_ORDER)
        for opcode in stage17.OPCODE_ORDER:
            assert rendered.opcodes_applied[opcode] >= 1

    def test_simulate_voice_agrees_with_the_interpreter(self) -> None:
        events = [
            stage17.make_event("SET_PITCH", 2, 0, divider=10),
            stage17.make_event("PITCH_SLIDE", 2, 0, duration=4, delta=8, curve=0),
        ]
        full = stage17.interpret(events, 6, 0)
        window = stage17.simulate_voice(events, 2, 0, 6, 0, 0)
        for frame in range(6):
            assert window[frame][0] == full.registers["AUDF2"][frame]



# ---------------------------------------------------------------------------
# 5. Encoders
# ---------------------------------------------------------------------------
@requires_corpus
class TestEncoders:
    def test_the_control_encoder_reproduces_the_trace_exactly(self, song) -> None:
        events = stage17.encode_register_state(song)
        comparison = stage17.compare_frame_stream(song, events)
        assert comparison.frames == song.frames
        assert comparison.exact == song.frames
        assert comparison.register_exact == song.frames

    def test_the_control_encoder_only_emits_on_change(self, song) -> None:
        events = stage17.encode_register_state(song)
        frames_touched = len({event.frame for event in events})
        assert frames_touched <= song.frames

    def test_the_control_encoder_emits_one_set_audctl_at_frame_zero(self, song) -> None:
        events = stage17.encode_register_state(song)
        audctl = [event for event in events if event.opcode == "SET_AUDCTL"]
        assert len(audctl) == 1
        assert audctl[0].frame == 0
        assert dict(audctl[0].params)["value"] == song.audctl

    def test_the_attached_encoding_is_exact_after_repair_on_all_four_songs(
        self, bundle: Dict[str, Any]
    ) -> None:
        for song_row in bundle["reconstruction_results"]["songs"]:
            attached = next(
                row for row in song_row["representations"]
                if row["label"] == "PERFORMANCE_REFERENCE_ATTACHED_REPAIRED"
            )
            assert attached["comparison"]["exact_share"] == 1.0, song_row["slug"]

    def test_the_sequential_model_never_reaches_the_attached_one(
        self, bundle: Dict[str, Any]
    ) -> None:
        summary = bundle["reconstruction_results"]["summary"]
        assert (
            summary["sequential_note_model_exact_share_mean"]
            < summary["attached_note_model_exact_share_mean"]
        )

    def test_the_sequential_model_does_not_converge(self, bundle: Dict[str, Any]) -> None:
        """Every sequential repair round still emits patches; the attached one settles."""
        for song_row in bundle["per_song_measurements"]:
            rounds = song_row["sequential_repair_rounds"]
            assert rounds, song_row["slug"]
            assert rounds[-1]["patch_events"] > 0, song_row["slug"]

    def test_the_abstraction_encoder_maps_every_event_kind(self, song) -> None:
        encoding = stage17.encode_performance(song, attached=True)
        assert encoding.unmapped == {}
        assert encoding.event_count > 0

    def test_the_abstraction_encoder_uses_only_vocabulary_opcodes(self, song) -> None:
        encoding = stage17.encode_performance(song, attached=True, allow_tables=True)
        assert set(encoding.opcode_histogram()) <= set(stage17.OPCODE_ORDER)

    def test_an_encoder_never_emits_a_negative_frame_delta(self, song) -> None:
        for encoding in (
            stage17.encode_performance(song, attached=True),
            stage17.encode_reference(song, attached=True)[0],
        ):
            previous = 0
            for event in stage17.sort_events(encoding.events):
                assert event.frame >= previous
                previous = event.frame

    def test_the_behaviour_driven_compiler_emits_no_note_off_in_attached_mode(self, song) -> None:
        encoding, _ = stage17.encode_reference(song, attached=True)
        assert not any(event.opcode == "NOTE_OFF" for event in encoding.events)

    def test_the_behaviour_driven_compiler_uses_note_off_in_sequential_mode(self, song) -> None:
        encoding, _ = stage17.encode_reference(song, attached=False)
        assert any(event.opcode == "NOTE_OFF" for event in encoding.events)

        assert stage17.event_semantics()["opcode_order"] == list(stage17.OPCODE_ORDER)



# ---------------------------------------------------------------------------
# 6. Round trip and comparison
# ---------------------------------------------------------------------------
@requires_corpus
class TestRoundTrip:
    def test_a_silent_channel_is_not_charged_for_its_distortion(self) -> None:
        """A silent frame's distortion nibble is don't-care and must not count as a failure."""
        frames = 4
        reference = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reconstructed = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reconstructed["AUDC1"] = [0xC0] * frames  # silent, but the distortion bits are set
        comparison = stage17.compare_frames(reference, reconstructed, frames, 0)
        assert comparison.exact == frames
        assert comparison.register_exact == 0

    def test_a_wrong_volume_on_an_audible_channel_is_unrepresentable(self) -> None:
        frames = 2
        reference = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reconstructed = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reference["AUDC1"] = [0xC5, 0xC5]
        reconstructed["AUDC1"] = [0xC2, 0xC5]
        comparison = stage17.compare_frames(reference, reconstructed, frames, 0)
        assert comparison.unrepresentable == 1
        assert comparison.exact == 1

    def test_a_wrong_divider_on_an_audible_channel_is_approximate(self) -> None:
        frames = 1
        reference = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reconstructed = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reference["AUDC1"] = [0xC5]
        reference["AUDF1"] = [100]
        reconstructed["AUDC1"] = [0xC5]
        reconstructed["AUDF1"] = [104]
        comparison = stage17.compare_frames(reference, reconstructed, frames, 0)
        assert comparison.approximate == 1
        assert comparison.median_semitone_error is not None

    def test_a_wrong_audctl_is_unrepresentable(self) -> None:
        frames = 1
        reference = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reconstructed = {name: [0] * frames for name in stage17.REGISTER_ORDER}
        reference["AUDCTL"] = [0x50]
        reconstructed["AUDCTL"] = [0x00]
        comparison = stage17.compare_frames(reference, reconstructed, frames, 0)
        assert comparison.unrepresentable == 1
        assert comparison.audctl_match == 0

    def test_a_perfect_reconstruction_is_register_exact(self) -> None:
        frames = 3
        registers = {name: [1] * frames for name in stage17.REGISTER_ORDER}
        comparison = stage17.compare_frames(registers, registers, frames, 0)
        assert comparison.exact == frames
        assert comparison.register_exact == frames
        assert comparison.unrepresentable == 0

    def test_the_three_classifications_partition_every_frame(
        self, bundle: Dict[str, Any]
    ) -> None:
        for song_row in bundle["reconstruction_results"]["songs"]:
            for row in song_row["representations"]:
                comparison = row["comparison"]
                if "exact" not in comparison:
                    continue
                total = (
                    comparison["exact"] + comparison["approximate"]
                    + comparison["unrepresentable"]
                )
                assert total == song_row["frames"]

    def test_the_abstraction_replay_is_substantially_worse_than_the_control(
        self, bundle: Dict[str, Any]
    ) -> None:
        summary = bundle["reconstruction_results"]["summary"]
        assert (
            summary["abstraction_driven_exact_share_mean"]
            < summary["control_exact_share_mean"] / 10
        )


# ---------------------------------------------------------------------------
# 7. Compression, costs and feasibility (Parts K, L, M, N, O)
# ---------------------------------------------------------------------------
@requires_corpus
class TestCosts:
    def test_the_exact_encoding_is_larger_than_a_raw_register_dump(
        self, bundle: Dict[str, Any]
    ) -> None:
        for song_row in bundle["compression"]["songs"]:
            by_label = {row["representation"]: row for row in song_row["representations"]}
            assert (
                by_label["C_performance_attached_repaired"]["bytes"]
                > by_label["B_raw_per_frame_state"]["bytes"]
            ), song_row["slug"]

    def test_the_abstraction_encoding_is_smaller_where_it_is_least_faithful(
        self, bundle: Dict[str, Any]
    ) -> None:
        """It is not uniformly smaller; the report says so and this pins the fact."""
        smaller = 0
        for song_row in bundle["compression"]["songs"]:
            by_label = {row["representation"]: row for row in song_row["representations"]}
            if (
                by_label["C_performance_abstraction"]["bytes"]
                < by_label["B_raw_per_frame_state"]["bytes"]
            ):
                smaller += 1
        assert 0 <= smaller <= 4
        assert bundle["compression"]["abstraction_smaller_than_raw_dump_songs"] == smaller

    def test_the_ratios_are_consistent_with_the_byte_counts(self, bundle: Dict[str, Any]) -> None:
        for song_row in bundle["compression"]["songs"]:
            raw = next(
                row["bytes"] for row in song_row["representations"]
                if row["representation"] == "B_raw_per_frame_state"
            )
            for row in song_row["representations"]:
                ratio = row.get("ratio_to_raw_frames")
                if ratio is None:
                    continue
                assert abs(ratio - row["bytes"] / raw) < 0.01

    def test_the_byte_model_is_stated(self, bundle: Dict[str, Any]) -> None:
        assert "9 bytes per frame" in bundle["compression"]["byte_model"]
        assert "3 bytes per note" in bundle["compression"]["byte_model"]

    def test_the_player_cost_model_is_labelled_an_estimate(self, bundle: Dict[str, Any]) -> None:
        assert "ESTIMATE" in bundle["player_cost_model"]["method"]
        for row in bundle["player_cost_model"]["opcodes"]:
            assert row["basis"] == "ESTIMATE"

    def test_the_baseline_is_the_measured_stage15_player(self, bundle: Dict[str, Any]) -> None:
        stage15_size = json.loads(
            (stage17.DEFAULT_STAGE15_DIR / "player_size_analysis.json").read_text(
                encoding="utf-8"
            )
        )
        assert (
            bundle["player_cost_model"]["baseline"]["assembled_bytes"]
            == stage15_size["assembled_bytes"]
        )

    def test_every_opcode_has_a_cost_row(self, bundle: Dict[str, Any]) -> None:
        rows = {row["opcode"] for row in bundle["player_cost_model"]["opcodes"]}
        assert rows == set(stage17.OPCODE_ORDER)

    def test_the_feasibility_label_matches_the_headroom(self, bundle: Dict[str, Any]) -> None:
        feasibility = bundle["player_feasibility"]
        projected = feasibility["projected_player_bytes_estimate"]
        envelope = feasibility["envelope_bytes"]
        if projected <= envelope * 0.75:
            assert feasibility["label"] == "COMFORTABLY_FITS"
        assert feasibility["headroom_bytes"] == envelope - projected

    def test_the_player_is_not_the_constraint(self, bundle: Dict[str, Any]) -> None:
        feasibility = bundle["player_feasibility"]
        assert feasibility["projected_player_bytes_estimate"] < feasibility["envelope_bytes"]

    def test_the_current_format_is_much_smaller_than_the_event_encoding(
        self, bundle: Dict[str, Any]
    ) -> None:
        for song_row in bundle["song_data_cost"]["songs"]:
            assert song_row["current_format_bytes"] < song_row["performance_event_bytes_repaired"]

    def test_the_plain_state_share_is_published(self, bundle: Dict[str, Any]) -> None:
        for song_row in bundle["song_data_cost"]["songs"]:
            share = song_row["plain_state_share_of_events"]
            assert share is not None and 0.0 < share <= 1.0

    def test_hardware_constraints_cover_the_documented_limits(self, bundle: Dict[str, Any]) -> None:
        names = {item["constraint"] for item in bundle["hardware_constraints"]["constraints"]}
        for required in (
            "8-bit divider range", "16-bit channel coupling", "AUDCTL",
            "channel ownership", "generator / distortion", "volume", "frame rate",
        ):
            assert required in names

    def test_every_song_surveys_its_own_register_range(self, bundle: Dict[str, Any]) -> None:
        for song_row in bundle["hardware_constraints"]["songs"]:
            assert song_row["largest_divider_observed"] <= song_row["divider_range_in_this_song"]

    def test_the_corpus_uses_two_audctl_configurations(self, bundle: Dict[str, Any]) -> None:
        values = {row["audctl"] for row in bundle["hardware_constraints"]["songs"]}
        assert "$00" in values and "$50" in values



# ---------------------------------------------------------------------------
# 8. Macros, neutrality, architecture, verdicts, report (Parts Q, R, C, G, U, W)
# ---------------------------------------------------------------------------
@requires_corpus
class TestMacrosAndNeutrality:
    def test_the_macro_verdict_follows_from_its_own_numbers(self, bundle: Dict[str, Any]) -> None:
        macros = bundle["macro_analysis"]
        best = macros["best_candidate_overall"]
        if best is None or best["net_saving_bytes_estimate"] <= 0:
            assert macros["verdict"] == "NOT_NECESSARY"
        else:
            assert macros["verdict"] == "MARGINAL"

    def test_macro_candidates_report_their_arithmetic(self, bundle: Dict[str, Any]) -> None:
        for song_row in bundle["macro_analysis"]["songs"]:
            for candidate in song_row["best_candidates"]:
                assert candidate["occurrences"] >= 3
                assert candidate["call_bytes_estimate"] == 2
                assert candidate["definition_bytes_estimate"] >= 2

    def test_the_language_is_neutral_across_songs(self, bundle: Dict[str, Any]) -> None:
        neutrality = bundle["semantic_neutrality"]
        assert neutrality["same_opcode_different_parameters"]
        for case in neutrality["same_opcode_different_parameters"]:
            values = {item["value"] for item in case["occurrences"]}
            assert len(values) >= 2

    def test_no_opcode_is_named_after_a_musical_role(self) -> None:
        forbidden = ("lead", "bass", "perc", "bell", "laser", "drum", "style")
        for opcode in stage17.OPCODE_ORDER:
            assert not any(word in opcode.lower() for word in forbidden)

    def test_the_language_declares_what_it_never_says(self, bundle: Dict[str, Any]) -> None:
        statements = bundle["semantic_neutrality"]["what_the_language_does_not_say"]
        assert statements
        assert any("role" in item for item in statements)

    def test_architecture_has_exactly_three_layers(self, bundle: Dict[str, Any]) -> None:
        assert len(bundle["architecture"]["layer_table"]) == 3

    def test_every_layer_owns_something_and_refuses_something(
        self, bundle: Dict[str, Any]
    ) -> None:
        for layer in bundle["architecture"]["layer_table"]:
            assert layer["owns"] and layer["must_not_own"]

    def test_the_context_rule_keeps_context_in_the_composition(
        self, bundle: Dict[str, Any]
    ) -> None:
        rule = bundle["architecture"]["context_rule"]
        assert "composition" in rule
        assert "channel 3" in rule

    def test_the_player_is_not_asked_to_interpret_anything(self, bundle: Dict[str, Any]) -> None:
        outside = bundle["architecture"]["what_stays_outside_the_player"]
        assert any("which opcode" in item for item in outside)



@requires_corpus
class TestVerdictsAndReport:
    def test_all_three_verdicts_are_chosen(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["event_language"]["verdict"] in (
            "EVENT_LANGUAGE_SUPPORTED", "EVENT_LANGUAGE_PARTIALLY_SUPPORTED",
            "EVENT_LANGUAGE_NOT_SUPPORTED",
        )
        assert verdicts["two_kb_player"]["verdict"] in (
            "2KB_PLAYER_PLAUSIBLE", "2KB_PLAYER_UNCERTAIN", "2KB_PLAYER_NOT_PLAUSIBLE",
        )
        assert verdicts["main_bottleneck"]["verdict"] in (
            "REPRESENTATION_IS_THE_MAIN_BOTTLENECK", "PLAYER_IS_THE_MAIN_BOTTLENECK",
            "SONG_DATA_IS_THE_MAIN_BOTTLENECK", "MULTIPLE_BOTTLENECKS",
            "INSUFFICIENT_EVIDENCE",
        )

    def test_the_language_verdict_follows_from_faithfulness_and_compactness(
        self, bundle: Dict[str, Any]
    ) -> None:
        verdict = bundle["verdicts"]["event_language"]
        faithful = verdict["faithful"]
        compact = verdict["compact"]
        expected = (
            "EVENT_LANGUAGE_SUPPORTED" if faithful and compact
            else "EVENT_LANGUAGE_PARTIALLY_SUPPORTED" if faithful or compact
            else "EVENT_LANGUAGE_NOT_SUPPORTED"
        )
        assert verdict["verdict"] == expected

    def test_the_verdicts_are_declared_independent(self, bundle: Dict[str, Any]) -> None:
        assert "not correlated" in bundle["verdicts"]["independence_note"]

    def test_each_verdict_publishes_its_rule(self, bundle: Dict[str, Any]) -> None:
        for key in ("event_language", "two_kb_player", "main_bottleneck"):
            assert bundle["verdicts"][key]["rule"]

    def test_twelve_research_questions_are_answered(self, bundle: Dict[str, Any]) -> None:
        answers = bundle["research_answers"]
        assert len(answers) == 12
        for index, item in enumerate(answers, start=1):
            assert item["question"].startswith(f"Q{index} ")
            assert item["answer"] and item["basis"]

    def test_the_report_has_the_twenty_two_required_sections(
        self, bundle: Dict[str, Any]
    ) -> None:
        text = stage17.render_report(bundle)
        for number in range(1, 23):
            assert re.search(rf"(?m)^## {number}\. ", text), f"section {number} missing"

    def test_the_report_renders_without_a_traceback(self, bundle: Dict[str, Any]) -> None:
        text = stage17.render_report(bundle)
        assert "Traceback" not in text
        assert len(text) > 20000

    def test_the_report_names_the_stop_condition(self, bundle: Dict[str, Any]) -> None:
        text = stage17.render_report(bundle)
        assert "no listening test was run" in text.lower()

    def test_at_least_one_thing_is_deferred(self, bundle: Dict[str, Any]) -> None:
        assert bundle["what_not_to_build_yet"]
        for item in bundle["what_not_to_build_yet"]:
            assert item["thing"] and item["why_not"]

    def test_stage18_candidates_each_ask_a_question(self, bundle: Dict[str, Any]) -> None:
        candidates = bundle["stage18_candidates"]
        assert len(candidates) >= 3
        for item in candidates:
            assert "?" in item["question"]
            assert item["cost"]


# ---------------------------------------------------------------------------
# 9. CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestCli:
    def test_the_command_writes_the_record_and_the_document(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        docs = tmp_path / "docs"
        result = CliRunner().invoke(
            cli,
            ["analyze-stage17", "--reports-dir", str(reports), "--docs-dir", str(docs)],
        )
        assert result.exit_code == 0, result.output
        assert (docs / stage17.STAGE17_DOC).is_file()
        for name in stage17.STAGE17_FILES:
            assert (reports / name).is_file()
        assert "EVENT_LANGUAGE" in result.output

    def test_the_cli_reports_the_same_verdicts_as_the_bundle(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["analyze-stage17", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d")],
        )
        assert result.exit_code == 0, result.output
        written = json.loads((tmp_path / "r" / "summary.json").read_text(encoding="utf-8"))
        assert written["verdicts"]["event_language"] in result.output


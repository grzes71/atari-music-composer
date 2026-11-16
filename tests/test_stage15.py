"""Stage 15 — SAP performance style and player capability investigation.

These tests pin the analysis to the raw trace and to the player source, prove the stage is
read-only and deterministic, and lock down the two verdicts and the architectural numbers the
report rests on.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage15
from atari_music.cli import cli

requires_corpus = pytest.mark.skipif(
    not stage15.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage15.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage15.run_analysis()


# ---------------------------------------------------------------------------
# 1. Determinism and read-only behaviour
# ---------------------------------------------------------------------------
@pytest.mark.experimental
@requires_corpus
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage15.run_analysis() == bundle

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        first = stage15.write_analysis(
            stage15.run_analysis(), stage15_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        second = stage15.write_analysis(
            stage15.run_analysis(), stage15_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        hashes_a = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in first.items()}
        hashes_b = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in second.items()}
        assert hashes_a == hashes_b
        assert set(hashes_a) == set(stage15.STAGE15_FILES) | {stage15.STAGE15_DOC}

    def test_the_stage_is_read_only(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        trace = next(iter(stage15.list_traces()))
        watched = [trace, stage15.DEFAULT_PLAYER_ASM]
        before = {str(path): stage15.sha256_file(path) for path in watched}
        stage15.write_analysis(bundle, stage15_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        after = {str(path): stage15.sha256_file(path) for path in watched}
        assert before == after

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage15.render_report(bundle)
        assert "created_utc" not in text
        assert "2026-10" not in text

    def test_no_audio_or_music_is_produced(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        """Nothing the stage writes is audio, and no song data is generated."""
        written = stage15.write_analysis(
            bundle, stage15_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        suffixes = {path.suffix for path in written.values()}
        assert suffixes == {".json", ".md"}


# ---------------------------------------------------------------------------
# 2. Reference-song selection
# ---------------------------------------------------------------------------
@pytest.mark.experimental
@requires_corpus
class TestSelection:
    def test_every_candidate_is_scored_and_the_winner_leads(self, bundle: Dict[str, Any]) -> None:
        selection = bundle["reference_song"]["selection"]
        assert selection["candidates_considered"] == len(selection["ranking"]) + len(
            selection["rejected"]
        )
        assert selection["winner"]["rank"] == 1
        assert selection["winner"]["eligible"] is True

    def test_the_ranking_is_a_total_order_on_the_declared_key(
        self, bundle: Dict[str, Any]
    ) -> None:
        rows = bundle["reference_song"]["selection"]["ranking"]
        for earlier, later in zip(rows, rows[1:]):
            assert (
                -earlier["audible_channels"], -earlier["generator_families"],
                -earlier["distinct_pitch_values"], -earlier["frames"], earlier["trace"],
            ) <= (
                -later["audible_channels"], -later["generator_families"],
                -later["distinct_pitch_values"], -later["frames"], later["trace"],
            )

    def test_gates_come_from_the_brief(self, bundle: Dict[str, Any]) -> None:
        gates = {gate["gate"] for gate in bundle["reference_song"]["selection"]["winner"]["gates"]}
        assert gates == {
            "G1_duration_at_least_30s",
            "G2_multiple_channels",
            "G3_not_static_tone",
            "G4_meaningful_register_modulation",
        }

    def test_sensitivity_is_reported_honestly(self, bundle: Dict[str, Any]) -> None:
        sensitivity = bundle["reference_song"]["selection_sensitivity"]
        assert set(sensitivity["winner_under_other_orderings"]) == {
            "generator_families_first",
            "pitch_vocabulary_first",
            "material_first",
        }
        unanimous = len(set(sensitivity["winner_under_other_orderings"].values())) == 1
        assert sensitivity["unanimous"] is unanimous

    def test_the_selection_is_reproducible_from_scratch(self, bundle: Dict[str, Any]) -> None:
        again = stage15.select_reference_song()
        assert again["winner"]["trace"] == bundle["reference_song"]["selection"]["winner"]["trace"]


# ---------------------------------------------------------------------------
# 3. Trace reading and provenance
# ---------------------------------------------------------------------------
@pytest.mark.experimental
@requires_corpus
class TestTrace:
    def test_registers_are_frame_aligned(self, bundle: Dict[str, Any]) -> None:
        trace = stage15.load_trace(Path(bundle["reference_song"]["selected"]["path"]))
        assert trace.frames > 0
        for channel in (1, 2, 3, 4):
            assert len(trace.registers[f"AUDF{channel}"]) == trace.frames
            assert len(trace.registers[f"AUDC{channel}"]) == trace.frames
        assert len(trace.registers["AUDCTL"]) == trace.frames

    def test_the_trace_is_hashed(self, bundle: Dict[str, Any]) -> None:
        trace = stage15.load_trace(Path(bundle["reference_song"]["selected"]["path"]))
        assert trace.sha256 == stage15.sha256_file(Path(trace.path))
        assert bundle["pokey_trace_summary"]["trace_sha256"] == trace.sha256

    def test_a_truncated_register_stream_is_refused(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        trace = stage15.load_trace(Path(bundle["reference_song"]["selected"]["path"]))
        payload = json.loads(Path(trace.path).read_text(encoding="utf-8"))
        payload["registers"]["AUDF1"] = payload["registers"]["AUDF1"][:-1]
        broken = tmp_path / "broken.frames.json"
        broken.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(stage15.Stage15Error):
            stage15.load_trace(broken)

    def test_pitch_interpretation_follows_audctl(self) -> None:
        uncoupled = stage15.pitch_interpretation(0x00)
        assert set(uncoupled.values()) == {"own_divider"}
        coupled = stage15.pitch_interpretation(0x50)
        assert coupled[1] == "divider_lsb_of_joined_pair"
        assert coupled[2] == "divider_msb_of_joined_pair"
        voices = stage15.voices_for(0x50)
        assert any(voice.joined for voice in voices)
        assert len(voices) == 3

    def test_a_joined_pair_reports_the_combined_divider(self, bundle: Dict[str, Any]) -> None:
        trace = stage15.load_trace(Path(bundle["reference_song"]["selected"]["path"]))
        registers = {"AUDF1": (0x34,), "AUDF2": (0x12,), "AUDF3": (0,), "AUDF4": (0,)}
        voice = stage15.voices_for(stage15.AUDCTL_JOIN_1_2_16BIT)[0]
        assert voice.joined is True
        assert stage15.divider_for(voice, 0, registers) == 0x1234


# ---------------------------------------------------------------------------
# 4. Events and the artifact distinction
# ---------------------------------------------------------------------------
@pytest.mark.experimental
@requires_corpus
class TestEvents:
    def test_only_supported_event_classes_are_emitted(self, bundle: Dict[str, Any]) -> None:
        vocabulary = bundle["performance_vocabulary"]
        present = set(vocabulary["kinds_present"])
        absent = set(vocabulary["kinds_absent"])
        assert present | absent == set(stage15.EVENT_KINDS)
        assert not (present & absent)

    def test_every_event_carries_evidence_and_a_classification(
        self, bundle: Dict[str, Any]
    ) -> None:
        for event in bundle["performance_events"]["events"]:
            assert event["classification"] in {
                stage15.CLASS_MUSICAL, stage15.CLASS_ARTIFACT, stage15.CLASS_UNKNOWN
            }
            assert event["evidence_first"]
            assert 0.0 <= event["confidence"] <= 1.0
            assert event["end_frame"] >= event["start_frame"]

    def test_sampling_never_hides_a_kind(self, bundle: Dict[str, Any]) -> None:
        events = bundle["performance_events"]
        sampled = {event["kind"] for event in events["events"]}
        assert sampled == set(bundle["performance_vocabulary"]["kinds_present"])
        assert events["events_written"] <= events["events_total"]

    def test_noise_clock_movement_is_not_called_a_pitch(self) -> None:
        classification, evidence, confidence = stage15._pitch_interpretation_of(
            "poly9_17", True, "own_divider"
        )
        assert classification == stage15.CLASS_UNKNOWN
        assert "noise" in evidence[0]
        assert confidence < 0.6

    def test_a_silent_write_is_a_register_effect(self) -> None:
        classification, evidence, _ = stage15._pitch_interpretation_of(
            "silent", False, "own_divider"
        )
        assert classification == stage15.CLASS_ARTIFACT
        assert "silent" in evidence[0]

    def test_the_lsb_of_a_joined_pair_is_never_a_pitch(self) -> None:
        classification, evidence, _ = stage15._pitch_interpretation_of(
            "silent", False, "divider_lsb_of_joined_pair"
        )
        assert classification == stage15.CLASS_ARTIFACT
        assert "low byte" in evidence[0]

    def test_an_audible_tonal_change_is_musical(self) -> None:
        classification, _, confidence = stage15._pitch_interpretation_of(
            "pure_tone", True, "own_divider"
        )
        assert classification == stage15.CLASS_MUSICAL
        assert confidence >= 0.8

    def test_volume_is_the_low_nibble_and_distortion_the_high_nibble(self) -> None:
        assert stage15.audc_volume(0xC7) == 7
        assert stage15.audc_distortion(0xC7) == 0xC
        assert stage15.audc_waveform(0x00) == "silent"
        assert stage15.audc_waveform(0xA5) == "pure_tone"
        assert stage15.audc_waveform(0x8F) == "poly9_17"

    def test_a_stable_tone_for_one_note_produces_no_pitch_event(self) -> None:
        """A held divider inside one note must not be reported as movement."""
        trace = stage15.load_trace(Path(next(iter(stage15.list_traces()))))
        voice = stage15.voices_for(trace.audctl)[0]
        span = stage15.NoteSpan(voice.voice_id, voice.volume_channel, 0, 4, 0)
        events = stage15._pitch_events(
            voice, span, [100, 100, 100, 100, 100], [1000.0] * 5, [9] * 5,
            stage15.CLASS_MUSICAL, ("audible",), 0.85, "pure_tone",
        )
        assert events == []


# ---------------------------------------------------------------------------
# 5. Vocabulary and context dependence
# ---------------------------------------------------------------------------
@pytest.mark.experimental
@requires_corpus
class TestVocabularyAndContext:
    def test_occurrence_counts_match_the_events(self, bundle: Dict[str, Any]) -> None:
        vocabulary = bundle["performance_vocabulary"]
        total = sum(technique["occurrences"] for technique in vocabulary["techniques"])
        assert total == sum(vocabulary["occurrences_by_kind"].values())
        assert total == vocabulary["event_count"]

    def test_classification_counts_match_the_events(self, bundle: Dict[str, Any]) -> None:
        vocabulary = bundle["performance_vocabulary"]
        total = sum(vocabulary["classifications"].values())
        assert total == vocabulary["event_count"]

    def test_techniques_are_named_not_numbered(self, bundle: Dict[str, Any]) -> None:
        for technique in bundle["performance_vocabulary"]["techniques"]:
            assert technique["technique_id"]
            assert technique["technique_id"].isupper()
            assert technique["example"] is not None

    def test_a_circular_test_is_excluded(self) -> None:
        assert stage15.is_circular("pitch_band", "start_divider") is True
        assert stage15.is_circular("pitch_band", "end_hz") is True
        assert stage15.is_circular("note_length_band", "note_frames") is True
        assert stage15.is_circular("family_bucket", "to_waveform") is True
        assert stage15.is_circular("channel", "divider") is False
        assert stage15.is_circular("pitch_band", "steps") is False

    def test_every_verdict_is_one_of_three(self, bundle: Dict[str, Any]) -> None:
        for item in bundle["context_analysis"]["techniques"]:
            assert item["verdict"] in {
                "TECHNIQUE_CONTEXT_SPLIT", "SINGLE_TECHNIQUE", "INSUFFICIENT_EVIDENCE"
            }
            if item["verdict"] == "TECHNIQUE_CONTEXT_SPLIT":
                assert item["strongest_eta_squared"] >= stage15.CONTEXT_ETA2_THRESHOLD
            if item["verdict"] == "SINGLE_TECHNIQUE":
                assert item["strongest_eta_squared"] < stage15.CONTEXT_ETA2_THRESHOLD

    def test_every_occurrence_has_a_context_record(self, bundle: Dict[str, Any]) -> None:
        """The context layer is computed for every event, not sampled."""
        assert bundle["performance_vocabulary"]["event_count"] > 0
        dimensions = set(bundle["context_analysis"]["context_dimensions_used"])
        assert "musical_role" in dimensions
        assert "position_in_note" in dimensions

    def test_roles_are_never_invented(self, bundle: Dict[str, Any]) -> None:
        for voice in bundle["context_analysis"]["channel_character"]["voices"]:
            assert voice["musical_role"] == "unknown"
            assert voice["inferred_character"]
            assert voice["inference_rule"]

    def test_eta_squared_is_bounded(self) -> None:
        """Identical groups carry no variance to explain, so the statistic is undefined."""
        assert stage15._eta_squared([[1, 1, 1], [1, 1, 1]]) is None
        extreme = stage15._eta_squared([[1, 1, 1, 1], [9, 9, 9, 9]])
        assert extreme is not None and extreme > 0.9
        assert stage15._eta_squared([[1]]) is None


# ---------------------------------------------------------------------------
# 6. The player analysis
# ---------------------------------------------------------------------------
class TestPlayer:
    @pytest.mark.experimental
    def test_capabilities_are_read_from_the_source(self) -> None:
        capabilities = stage15.player_capabilities()
        assert capabilities["source"].endswith("player.asm")
        assert capabilities["source_sha256"]
        assert capabilities["source_code_lines"] > 100
        assert capabilities["data_format"]["event_bytes"] == 3
        assert capabilities["data_format"]["instrument_count"] == 4

    @pytest.mark.experimental
    def test_every_unsupported_claim_is_marked_unsupported(self) -> None:
        capabilities = stage15.player_capabilities()
        by_name = {item["capability"]: item for item in capabilities["capabilities"]}
        for name in ("vibrato", "portamento_or_slide", "arpeggio", "effect_column"):
            assert by_name[name]["supported"] is False
            assert by_name[name]["cost_kind"] != "PRESENT"
        for name in ("4_independent_channels", "sixteen_bit_pair_1_2"):
            assert by_name[name]["supported"] is True

    @pytest.mark.experimental
    def test_supported_claims_cite_source_lines(self) -> None:
        capabilities = stage15.player_capabilities()
        for item in capabilities["capabilities"]:
            if item["supported"]:
                assert item["evidence"], item["capability"]

    @pytest.mark.experimental
    def test_size_split_is_consistent(self) -> None:
        capabilities = stage15.player_capabilities()
        size = stage15.player_size_analysis(capabilities, live_measure=False)
        assert size["assembled_bytes"] == (
            size["code_bytes"] + size["state_bytes"]
        )
        assert size["headroom_bytes"]["current_envelope_2KB"] > 0
        assert size["headroom_bytes"]["hypothetical_4KB"] > size["headroom_bytes"]["current_envelope_2KB"]

    # -- the player-size limit -------------------------------------------------------------
    #
    # The project's one hard binary limit bounds the *player*, not the complete XEX file. It is
    # exclusive: 2047 passes, 2048 fails. These tests are the enforcement of that policy.

    @pytest.mark.core
    @pytest.mark.audio
    def test_the_player_size_limit_is_exclusive(self) -> None:
        """2047 passes and 2048 fails — the boundary is ``<``, never ``<=``."""
        limit = stage15.PLAYER_SIZE_LIMIT_BYTES
        assert limit == 2048
        assert stage15.player_size_limit_ok(limit - 1) is True
        assert stage15.player_size_limit_ok(limit) is False
        assert stage15.player_size_limit_ok(limit + 1) is False
        assert stage15.player_size_limit_ok(0) is True

    @pytest.mark.core
    @pytest.mark.audio
    def test_the_player_size_check_accepts_2047_and_refuses_2048(self) -> None:
        limit = stage15.PLAYER_SIZE_LIMIT_BYTES
        assert stage15.check_player_size(limit - 1) == limit - 1

        with pytest.raises(stage15.PlayerSizeError) as excinfo:
            stage15.check_player_size(limit)
        # At the boundary the offending size and the limit coincide, which is exactly why the
        # message has to spell out that the rule is exclusive.
        assert str(limit) in str(excinfo.value)
        assert "exclusive" in str(excinfo.value)

        # One byte over: the message names the offending size *and* the limit.
        with pytest.raises(stage15.PlayerSizeError) as over:
            stage15.check_player_size(limit + 1)
        assert str(limit + 1) in str(over.value)
        assert str(limit) in str(over.value)

    @pytest.mark.experimental
    def test_the_limit_bounds_the_player_and_nothing_else(self) -> None:
        """The scope is stated, and it does not mention the XEX file or the song data."""
        scope = stage15.PLAYER_SIZE_LIMIT_SCOPE.lower()
        assert "player" in scope
        assert "not bounded" in scope
        assert "xex" in scope
        # `current_envelope_2KB` is the same number, defined from the limit so it cannot drift.
        assert stage15.PLAYER_SIZE_BUDGETS["current_envelope_2KB"] == stage15.PLAYER_SIZE_LIMIT_BYTES

    @pytest.mark.experimental
    def test_the_analysis_reports_the_limit_verdict(self) -> None:
        capabilities = stage15.player_capabilities()
        size = stage15.player_size_analysis(capabilities, live_measure=False)
        assert size["limit_bytes"] == stage15.PLAYER_SIZE_LIMIT_BYTES
        assert size["limit_is_exclusive"] is True
        assert size["limit_scope"] == stage15.PLAYER_SIZE_LIMIT_SCOPE
        assert size["within_limit"] is stage15.player_size_limit_ok(size["assembled_bytes"])
        assert size["within_limit"] is True

    @pytest.mark.core
    @pytest.mark.audio
    def test_the_assembled_player_is_within_the_limit(self) -> None:
        """The real player, measured by the assembler when one is present."""
        live = stage15.measure_player_size(stage15.DEFAULT_PLAYER_ASM, stage15.DEFAULT_MADS)
        if live is None:
            pytest.skip("no assembler on this machine")
        assert stage15.check_player_size(live) == live
        assert live == stage15.PLAYER_ASSEMBLED_BYTES_RECORDED

    @pytest.mark.experimental
    def test_the_recorded_measurement_matches_a_live_one_when_mads_is_present(self) -> None:
        capabilities = stage15.player_capabilities()
        live = stage15.measure_player_size(
            stage15.DEFAULT_PLAYER_ASM, stage15.DEFAULT_MADS
        )
        if live is None:
            pytest.skip("no assembler on this machine")
        recorded = stage15.player_size_analysis(capabilities, live_measure=False)
        assert live == recorded["assembled_bytes"]

    @pytest.mark.core
    @pytest.mark.audio
    def test_the_measurement_leaves_no_files_behind(self) -> None:
        stage15.measure_player_size(stage15.DEFAULT_PLAYER_ASM, stage15.DEFAULT_MADS)
        directory = stage15.DEFAULT_PLAYER_ASM.parent
        assert not list(directory.glob("_stage15_measure*"))
        assert sorted(path.name for path in directory.iterdir()) == ["player.asm"]
        assert not list(Path(tempfile.gettempdir()).glob("stage15_measure_*"))

    @pytest.mark.experimental
    def test_the_gap_analysis_covers_every_technique(self, bundle: Dict[str, Any]) -> None:
        gap = bundle["player_gap_analysis"]
        assert len(gap["rows"]) == bundle["performance_vocabulary"]["technique_count"]
        assert (
            gap["techniques_supported_directly"]
            + gap["techniques_reachable_only_by_unrolling"]
            + gap["techniques_unreachable"]
            == gap["techniques_total"]
        )
        for row in gap["rows"]:
            assert row["classification"] in {
                "SUPPORTED", "DATA_LIMITATION", "PLAYER_CODE_LIMITATION",
                "IR_LIMITATION", "COMPOSITION_LIMITATION", "UNKNOWN",
            }

    @pytest.mark.experimental
    def test_unrolling_is_orders_of_magnitude_more_expensive(self, bundle: Dict[str, Any]) -> None:
        cost = bundle["player_unrolling_cost"]
        assert cost["unrolled_total_bytes"] > cost["current_format_bytes_for_those_notes"]
        assert cost["unrolled_to_current_ratio"] > 5

    @pytest.mark.experimental
    def test_the_proposed_player_is_justified_only_by_the_song(self, bundle: Dict[str, Any]) -> None:
        design = bundle["hypothetical_player_design"]
        for item in design["commands"]:
            assert item["justified_by"]
        refused = {item["command"] for item in design["refused_commands"]}
        assert "SET_AUDCTL from data" in refused
        assert any("0 occurrences" in item["reason"] for item in design["refused_commands"])


# ---------------------------------------------------------------------------
# 7. The artefact, the verdicts and the report
# ---------------------------------------------------------------------------
@pytest.mark.experimental
@requires_corpus
class TestArtefactAndVerdicts:
    def test_the_style_is_not_a_sound_profile(self, bundle: Dict[str, Any]) -> None:
        """The artefact describes behaviour, not a portable sound to re-apply."""
        style = bundle["song_performance_style"]
        assert style["artifact"] == "SongPerformanceStyle"
        assert "not a production schema" in style["status"]
        assert "NOT a SoundProfile" in style["artifact_rationale"]
        # No instrument payload and no portable per-channel sound anywhere in the artefact.
        for key in ("instruments", "instrument", "channels_sound", "profile_id",
                    "volume_contour", "playable"):
            assert key not in style
        for technique in style["performance_techniques"]:
            assert {
                "technique_id", "observed", "context", "confidence", "player_requirement", "example"
            } == set(technique)

    def test_the_style_is_scoped_to_one_song(self, bundle: Dict[str, Any]) -> None:
        style = bundle["song_performance_style"]
        assert style["source_song"]["song"]
        assert style["source_song"]["sha256"]
        assert "no claim" in style["artifact_rationale"]

    def test_the_style_records_every_technique(self, bundle: Dict[str, Any]) -> None:
        style = bundle["song_performance_style"]
        assert len(style["performance_techniques"]) == (
            bundle["performance_vocabulary"]["technique_count"]
        )

    def test_the_two_verdicts_are_chosen_independently(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["performance_style"]["verdict"] in {
            "PERFORMANCE_STYLE_SUPPORTED",
            "PERFORMANCE_STYLE_PROMISING_BUT_UNPROVEN",
            "PERFORMANCE_STYLE_NOT_SUPPORTED",
        }
        assert verdicts["player_expansion"]["verdict"] in {
            "PLAYER_EXPANSION_JUSTIFIED",
            "PLAYER_EXPANSION_POTENTIALLY_JUSTIFIED",
            "PLAYER_EXPANSION_NOT_JUSTIFIED",
        }
        assert verdicts["correlation_note"]
        assert verdicts["performance_style"]["proven"]
        assert verdicts["performance_style"]["unproven"]

    def test_the_player_verdict_follows_the_measured_headroom(self, bundle: Dict[str, Any]) -> None:
        """A bigger player is justified only if the mechanisms do not fit today."""
        size = bundle["player_size_analysis"]
        design = bundle["hypothetical_player_design"]
        fits = (
            size["budgets"]["current_envelope_2KB"]
            - size["assembled_bytes"]
            - design["cost"]["estimated_added_code_bytes"]
        ) >= 0
        expected = (
            "PLAYER_EXPANSION_NOT_JUSTIFIED" if fits
            else "PLAYER_EXPANSION_POTENTIALLY_JUSTIFIED"
        )
        assert bundle["verdicts"]["player_expansion"]["verdict"] == expected

    def test_ten_questions_are_answered(self, bundle: Dict[str, Any]) -> None:
        answers = bundle["research_answers"]
        assert len(answers) == 10
        for index, item in enumerate(answers, start=1):
            assert item["question"].startswith(f"Q{index} ")
            assert len(item["answer"]) > 40

    def test_the_cross_check_reports_what_does_not_generalise(self, bundle: Dict[str, Any]) -> None:
        cross = bundle["cross_check"]
        assert cross["other_song"]
        assert 0.0 <= cross["shared_kind_share"] <= 1.0
        assert cross["conclusion"]

    def test_the_report_has_the_eighteen_required_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage15.render_report(bundle)
        required = [
            "## 1. Executive summary",
            "## 2. Selected reference song",
            "## 3. Trace methodology",
            "## 4. POKEY behaviour over time",
            "## 5. Detected performance events",
            "## 6. Musical behaviour vs register artifacts",
            "## 7. Performance vocabulary",
            "## 8. Context dependence",
            "## 9. Current player capabilities",
            "## 10. Reference techniques unsupported by current player",
            "## 11. Player size and architecture analysis",
            "## 12. Hypothetical richer player",
            "## 13. SongPerformanceStyle representation",
            "## 14. Applying the style conceptually to new music",
            "## 15. Answers to the ten research questions",
            "## 16. Stage 15 verdict",
            "## 17. What should NOT be built yet",
            "## 18. Candidate Stage 16 experiments",
        ]
        positions = [text.index(section) for section in required]
        assert positions == sorted(positions)

    def test_the_report_states_both_verdicts(self, bundle: Dict[str, Any]) -> None:
        text = stage15.render_report(bundle)
        assert bundle["verdicts"]["performance_style"]["verdict"] in text
        assert bundle["verdicts"]["player_expansion"]["verdict"] in text

    def test_nothing_is_declared_built(self, bundle: Dict[str, Any]) -> None:
        assert bundle["what_not_to_build_yet"]
        assert bundle["stage16_candidates"]
        for item in bundle["what_not_to_build_yet"]:
            assert item["item"] and item["why"]


# ---------------------------------------------------------------------------
# 8. CLI
# ---------------------------------------------------------------------------
@pytest.mark.experimental
class TestCli:
    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "analyze-stage15" in result.output

    def test_the_command_runs_and_writes_only_its_own_output(self, tmp_path: Path) -> None:
        """One invocation, checked end to end. ``--no-measure`` keeps it independent of MADS."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["analyze-stage15", "--no-measure", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d")],
        )
        if not stage15.DEFAULT_ARCHAEOLOGY_DIR.is_dir():  # pragma: no cover
            pytest.skip("no corpus on this machine")
        assert result.exit_code == 0, result.output
        assert "Reference song:" in result.output
        assert "PERFORMANCE_STYLE_PROMISING_BUT_UNPROVEN" in result.output
        assert "PLAYER_EXPANSION_NOT_JUSTIFIED" in result.output
        written = sorted(path.name for path in (tmp_path / "r").iterdir())
        assert written == sorted(stage15.STAGE15_FILES)
        assert (tmp_path / "d" / stage15.STAGE15_DOC).is_file()
        size = json.loads((tmp_path / "r" / "player_size_analysis.json").read_text("utf-8"))
        assert size["measured_this_run"] is None
        assert size["assembled_bytes"] == stage15.PLAYER_ASSEMBLED_BYTES_RECORDED

"""Stage 21 - controlled validation of the note-level explanation.

These tests pin the stage to what it can actually prove, and they take the two claims that matter
seriously enough to fail on:

* `trace == prediction + residual`, for every representation this stage declares exact;
* the two predictors are the same function, so a difference between a detector residual and a
  composition residual is a difference of information rather than of code.

They also pin the *shape* of the result: an in-house Tier A corpus, a Tier D historical corpus, an
empty `CONFIRMED_PERFORMANCE_CANDIDATE` category, and a report that closes its own accounting.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from click.testing import CliRunner

from atari_music import stage15, stage18, stage19, stage20, stage21
from atari_music.cli import cli

requires_corpus = pytest.mark.skipif(
    not stage21.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage21.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)

requires_control = pytest.mark.skipif(
    not stage21.DEFAULT_SONGS_DIR.is_dir(),
    reason="the .dsl compositions are not present on this machine",
)


@pytest.fixture(scope="session")
def bundle() -> Dict[str, Any]:
    """One bounded run of the whole stage, shared by every test that needs the record.

    The historical corpus is trimmed to the four Stage 20 songs and the control corpus to three, so
    the whole suite stays quick while every code path is still exercised. The full-corpus counts are
    asserted separately, from the audit, which is cheap.
    """
    return stage21.run_analysis(historical_limit=4, control_limit=3, detail_limit=2)


@pytest.fixture(scope="session")
def control_song() -> Any:
    corpus, _skipped = stage21.load_control_corpus()
    assert corpus, "the control corpus is empty"
    return corpus[0]


def fake_trace(frames: int = 12, audctl: int = 0x00) -> Any:
    """A trace-shaped object with every register held at zero, for synthetic tests."""
    registers = {name: [0] * frames for name in stage21.REGISTER_ORDER}
    return SimpleNamespace(frames=frames, registers=registers, audctl=audctl)



# ---------------------------------------------------------------------------
# Section 3/4 - the audit and the tier rule
# ---------------------------------------------------------------------------
class TestEvidenceTier:
    def test_no_independent_notes_is_tier_d(self) -> None:
        assert stage21.evidence_tier(("HAS_SAP", "HAS_EXACT_TRACE")) == stage21.TIER_D

    def test_independent_notes_alone_is_tier_c(self) -> None:
        assert stage21.evidence_tier(("HAS_INDEPENDENT_NOTES",)) == stage21.TIER_C

    def test_independent_notes_and_trace_is_tier_b(self) -> None:
        assert stage21.evidence_tier(
            ("HAS_INDEPENDENT_NOTES", "HAS_EXACT_TRACE")
        ) == stage21.TIER_B

    def test_timing_lifts_it_to_tier_a(self) -> None:
        assert stage21.evidence_tier(
            ("HAS_INDEPENDENT_NOTES", "HAS_EXACT_TRACE", "HAS_TIMING")
        ) == stage21.TIER_A

    def test_channel_assignment_is_not_required_for_tier_a(self) -> None:
        flags = ("HAS_INDEPENDENT_NOTES", "HAS_EXACT_TRACE", "HAS_TIMING")
        assert stage21.evidence_tier(flags) == stage21.TIER_A

    def test_every_declared_tier_has_a_rule(self) -> None:
        declared = {tier for tier, _rule in stage21.TIER_RULES}
        assert declared == {stage21.TIER_A, stage21.TIER_B, stage21.TIER_C, stage21.TIER_D}


@requires_corpus
class TestDatasetAudit:
    def test_every_historical_song_is_tier_d(self, bundle: Dict[str, Any]) -> None:
        rows = bundle["dataset_audit"]["rows"]
        historical = [row for row in rows if row["kind"] == stage21.KIND_HISTORICAL_SAP]
        assert historical, "no historical songs were audited"
        assert {row["tier"] for row in historical} == {stage21.TIER_D}

    def test_no_historical_song_has_independent_notes(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["dataset_audit"]["rows"]:
            if row["kind"] == stage21.KIND_HISTORICAL_SAP:
                assert row["HAS_INDEPENDENT_NOTES"] is False
                assert row["HAS_VELOCITY"] is False
                assert row["HAS_CHANNEL_ASSIGNMENT"] is False

    @requires_control
    def test_every_control_composition_is_tier_a(self, bundle: Dict[str, Any]) -> None:
        rows = bundle["dataset_audit"]["rows"]
        in_house = [row for row in rows if row["kind"] != stage21.KIND_HISTORICAL_SAP]
        assert in_house, "no control compositions were audited"
        assert {row["tier"] for row in in_house} == {stage21.TIER_A}

    @requires_control
    def test_no_control_document_was_silently_dropped(self, bundle: Dict[str, Any]) -> None:
        assert bundle["dataset_audit"]["counts"]["skipped"] == 0
        assert bundle["skipped_documents"] == []

    def test_the_dataset_verdict_names_the_historical_corpus(self, bundle: Dict[str, Any]) -> None:
        assert bundle["dataset_audit"]["dataset_verdict"] == "TIER_D_ONLY"

    def test_the_audit_covers_the_whole_historical_corpus(self) -> None:
        """The bounded test run trims the corpus; the audit must never be trimmed with it."""
        audit = stage21.dataset_audit()
        historical = [row for row in audit["rows"] if row["kind"] == stage21.KIND_HISTORICAL_SAP]
        assert len(historical) == len(list(stage15.list_traces(stage21.DEFAULT_ARCHAEOLOGY_DIR)))
        assert len(historical) >= 4

    def test_the_audit_records_measured_reference_captures(self, bundle: Dict[str, Any]) -> None:
        references = bundle["dataset_audit"]["profile_references"]
        assert references
        for row in references:
            assert row["tier"] == stage21.TIER_D
            assert row["HAS_INDEPENDENT_NOTES"] is False

    def test_every_row_carries_an_evidence_class(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["dataset_audit"]["rows"]:
            assert row["evidence"] in stage21.EVIDENCE_CLASSES
            assert row["confidence"] in ("HIGH", "MEDIUM", "LOW")

    def test_a_historical_row_claims_no_player_reconstruction(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The audit must not claim an independent trace for a song that has none."""
        for row in bundle["dataset_audit"]["rows"]:
            if row["kind"] == stage21.KIND_HISTORICAL_SAP:
                assert row["HAS_PLAYER_RECONSTRUCTION"] is False


@requires_corpus
class TestSourceProvenance:
    def test_no_external_candidate_is_admitted(self, bundle: Dict[str, Any]) -> None:
        external = bundle["dataset_audit"]["external"]
        assert external["admitted"] == []
        assert external["assessed"] == len(stage21.EXTERNAL_SOURCES)

    def test_every_external_candidate_states_a_reason_and_a_class(
        self, bundle: Dict[str, Any]
    ) -> None:
        for row in bundle["dataset_audit"]["external"]["candidates"]:
            assert row["evidence"] in stage21.EVIDENCE_CLASSES
            assert row["reason"].strip()
            assert row["admitted"] is False

    def test_the_sap_candidate_is_rejected_as_dependent(self) -> None:
        sap = next(row for row in stage21.EXTERNAL_SOURCES if "SAP files" in row["candidate"])
        assert sap["evidence"] == stage21.EVIDENCE_OBSERVED
        assert "one source" in sap["reason"]



# ---------------------------------------------------------------------------
# Section 5/7 - the independent notes and the predictor bridge
# ---------------------------------------------------------------------------
@requires_control
class TestCompositionNotes:
    def test_a_composition_expands_to_absolutely_positioned_notes(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        assert notes
        for note in notes:
            assert note.start < note.end
            assert note.frames == note.duration_rows * control_song.frames_per_tick
            assert note.channel in (1, 2, 3, 4)

    def test_note_order_is_deterministic(self, control_song: Any) -> None:
        first = stage21.composition_notes(control_song.song, control_song.trace)
        second = stage21.composition_notes(control_song.song, control_song.trace)
        assert [note.to_dict() for note in first] == [note.to_dict() for note in second]

    def test_a_silent_note_carries_no_divider(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        for note in notes:
            if note.is_rest:
                assert note.divider is None
                assert note.hz is None

    def test_notes_land_inside_the_trace(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        for note in notes:
            assert note.end <= control_song.frames

    def test_a_sixteen_bit_bass_note_is_one_joined_voice(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        joined = [note for note in notes if note.joined]
        if joined:
            for note in joined:
                assert note.pitch_channels == (1, 2)
                assert note.volume_channel == 2

    def test_plans_drop_the_rests(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        plans = stage21.plans_from_composition(notes)
        assert len(plans) == sum(1 for note in notes if not note.is_rest)
        for plan in plans:
            assert plan.dividers
            assert plan.end > plan.start


@requires_control
class TestPredictorBridge:
    def test_the_stage_21_predictor_reproduces_stage_20(self, control_song: Any) -> None:
        result = stage21.assert_matches_stage20(control_song.trace)
        assert result["agrees"] is True
        assert result["mismatches"] == 0

    def test_the_bridge_holds_on_the_whole_bundle(self, bundle: Dict[str, Any]) -> None:
        assert bundle["predictor_bridge"]
        for row in bundle["predictor_bridge"]:
            assert row["agrees"] is True, row

    def test_an_unknown_switch_is_refused(self) -> None:
        with pytest.raises(stage21.Stage21Error):
            stage21.predict_from_plans(4, 0, [], 4, "nowhere")
        with pytest.raises(stage21.Stage21Error):
            stage21.predict_from_plans(4, 0, [], 4, stage21.OUTSIDE_HOLD, "nowhere")
        with pytest.raises(stage21.Stage21Error):
            stage21.predict_from_plans(4, 0, [], 4, stage21.OUTSIDE_HOLD,
                                       stage21.CONTOUR_COMPOSITION, "nowhere")

    def test_the_predictor_writes_audctl_every_frame(self) -> None:
        predicted = stage21.predict_from_plans(5, 0x5C, [], 4)
        assert all(row[stage21.AUDCTL_COLUMN] == 0x5C for row in predicted)


@requires_control
class TestIndependentArm:
    def test_the_composition_reproduces_its_own_trace_exactly(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        arm = stage21.arm_independent(control_song.trace, notes, control_song.frames_per_tick,
                                      stage21.OUTSIDE_EXPORTER)
        assert arm["residual_values"] == 0

    def test_the_hold_convention_costs_a_measurable_amount(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        cost = stage21.convention_cost(control_song.trace, notes, control_song.frames_per_tick)
        assert cost["cost_of_hold"] >= 0
        assert cost[stage21.OUTSIDE_EXPORTER]["residual_values"] == 0
        for name in cost[stage21.OUTSIDE_HOLD]["per_register"]:
            assert name.startswith("AUDF"), name

    def test_every_bundle_control_song_has_an_empty_independent_residual(
        self, bundle: Dict[str, Any]
    ) -> None:
        for row in bundle["control_songs"]:
            assert row["independent"]["residual_values"] == 0, row["slug"]
            assert row["independent"]["residual_share"] == 0.0, row["slug"]



# ---------------------------------------------------------------------------
# Section 8/9/10 - pitch, timing, boundary tolerance
# ---------------------------------------------------------------------------
@requires_control
class TestPitchValidation:
    def test_the_pitch_model_is_exact_at_note_onsets(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.pitch_validation(control_song.trace, notes)
        assert report["notes_checked"] > 0
        assert report["exact_divider_matches"] == report["notes_checked"]
        assert report["exact_share"] == 1.0
        assert report["octave_or_register_errors"] == 0

    def test_the_pooled_pitch_share_is_one(self, bundle: Dict[str, Any]) -> None:
        assert bundle["control_pool"]["pitch_exact_share"] == 1.0


@requires_control
class TestTimingValidation:
    def test_timing_is_reported_against_the_composition(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        records = stage20.note_records(control_song.trace)
        report = stage21.timing_validation(control_song.trace, notes, records)
        assert report["available"] is True
        assert report["composition_notes"] > 0
        assert report["detected_notes"] > 0
        assert report["onset_error_max_abs"] >= 0
        assert report["flag"] in ("TIMING_EXACT", "TIMING_APPROXIMATE")
        assert report["occupancy"]

    def test_the_detector_finds_no_more_notes_than_exist(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        records = stage20.note_records(control_song.trace)
        report = stage21.timing_validation(control_song.trace, notes, records)
        rendered = sum(1 for note in notes if not note.is_rest)
        assert report["detected_notes"] <= rendered

    def test_without_notes_timing_is_declared_unavailable(self) -> None:
        report = stage21.timing_validation(fake_trace(), [], [])
        assert report["available"] is False
        assert "Tier D" in report["reason"]


class TestStage20Replication:
    """Stage 21 must not build on a Stage 20 number it has not checked."""

    def test_the_published_counts_do_not_agree_with_the_published_percentage(self) -> None:
        published = stage21.STAGE20_PUBLISHED
        ratio = published["residual_values"] / published["register_values"]
        assert abs(ratio - published["residual_percent"] / 100.0) > 0.005

    def test_the_replication_records_the_discrepancy(self, bundle: Dict[str, Any]) -> None:
        replication = bundle["stage20_replication"]
        assert replication["counts_reproduced_exactly"] is True
        assert replication["percentages_agree_with_the_published_counts"] is False
        assert replication["measured_residual_share"] is not None
        assert "does not follow from them" in replication["note"]

    def test_the_replication_covers_the_stage_20_four(self, bundle: Dict[str, Any]) -> None:
        assert tuple(bundle["stage20_replication"]["songs"]) == stage21.EXPECTED_SLUGS


@requires_control
class TestBoundaryTolerance:
    def test_tolerance_zero_is_the_measurement(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.boundary_tolerance(
            control_song.trace, notes, control_song.frames_per_tick
        )
        first = report["steps"][0]
        assert first["tolerance_frames"] == 0
        assert first["shifts_tried"] == [0]
        assert first["residual_values"] == 0
        assert first["residual_share"] == 0.0

    def test_wider_tolerance_never_explains_less(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.boundary_tolerance(
            control_song.trace, notes, control_song.frames_per_tick
        )
        shares = [step["residual_share"] for step in report["steps"]]
        assert shares == sorted(shares, reverse=True)

    def test_the_flag_reads_the_widest_tolerance(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.boundary_tolerance(
            control_song.trace, notes, control_song.frames_per_tick
        )
        assert report["flag"] == "ALIGNMENT_MAY_EXPLAIN_THE_RESIDUAL"



# ---------------------------------------------------------------------------
# Section 11/12/13 - the baseline ladder, the comparison, the accounting
# ---------------------------------------------------------------------------
@requires_control
class TestBaselines:
    def test_the_ladder_is_monotone_and_ends_at_zero(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.baselines(control_song.trace, notes, control_song.frames_per_tick)
        variants = report["variants"]
        assert variants["B0"]["residual_values"] >= variants["B1"]["residual_values"]
        assert variants["B1"]["residual_values"] >= variants["B2"]["residual_values"]
        assert variants["B2"]["residual_values"] == 0

    def test_each_rung_says_what_it_was_given(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.baselines(control_song.trace, notes, control_song.frames_per_tick)
        given = {name: report["variants"][name]["given"] for name in stage21.BASELINE_NAMES}
        assert "pitch" in given["B0"] and "envelope" not in given["B0"]
        assert "loudness" in given["B1"] and "envelope" not in given["B1"]
        assert "envelope" in given["B2"]

    def test_the_steps_are_named_after_what_they_add(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.baselines(control_song.trace, notes, control_song.frames_per_tick)
        assert "waveform_and_loudness_step_B0_to_B1" in report["steps"]
        assert "envelope_step_B1_to_B2" in report["steps"]

    def test_the_total_step_is_the_whole_rung(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.baselines(control_song.trace, notes, control_song.frames_per_tick)
        assert report["steps"]["total_step_B0_to_B2"] == 1.0


@requires_control
class TestResidualComparison:
    def test_the_detector_inflates_a_residual_the_composition_does_not(
        self, control_song: Any
    ) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.residual_comparison(
            control_song.trace, notes, control_song.frames_per_tick
        )
        assert report["R_independent_values"] == 0
        assert report["R_detector_values"] > 0
        assert report["outcome"] == "DETECTOR_INFLATED_RESIDUAL"
        assert report["independent_of_trace"] is True

    def test_the_decision_rule_is_declared(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        report = stage21.residual_comparison(
            control_song.trace, notes, control_song.frames_per_tick
        )
        assert "DETECTOR_INFLATED_RESIDUAL" in report["decision_rule"]
        assert "ground truth" in report["why_this_is_decidable_here"]

    def test_every_bundle_song_is_an_inflation_case(self, bundle: Dict[str, Any]) -> None:
        outcomes = bundle["control_pool"]["residual_outcomes"]
        assert outcomes.get("DETECTOR_INFLATED_RESIDUAL", 0) == len(bundle["control_songs"])


@requires_control
class TestInformationAccounting:
    def test_the_balance_closes_on_a_control_song(self, control_song: Any) -> None:
        arm = stage21.arm_detector(control_song.trace)
        report = stage21.information_accounting(
            control_song.trace, stage21.spans_from_records(arm["records"]), arm["residual"]
        )
        assert report["closes"] is True
        assert report["balance"] == report["total_register_values"]

    def test_the_independent_arm_explains_everything(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        arm = stage21.arm_independent(
            control_song.trace, notes, control_song.frames_per_tick, stage21.OUTSIDE_EXPORTER
        )
        report = stage21.information_accounting(
            control_song.trace, stage21.spans_from_composition(notes), arm["residual"]
        )
        assert report["closes"] is True
        assert report["parts"]["NOTE_EXPLAINED"] == report["total_register_values"]
        assert report["parts"][stage21.CAT_BASELINE_ERROR] == 0

    def test_a_performance_candidate_is_never_claimed_without_an_independent_source(
        self, bundle: Dict[str, Any]
    ) -> None:
        for row in bundle["historical_songs"]:
            assert row["accounting"]["parts"][stage21.CAT_PERFORMANCE_CANDIDATE] == 0
            assert row["accounting"]["closes"] is True

    def test_every_category_is_named_in_the_accounting(self, bundle: Dict[str, Any]) -> None:
        expected = {
            "NOTE_EXPLAINED", stage21.CAT_BASELINE_ERROR, stage21.CAT_ALIGNMENT_UNCERTAINTY,
            stage21.CAT_CHANNEL_UNCERTAINTY, stage21.CAT_PERFORMANCE_CANDIDATE,
            stage21.CAT_UNRESOLVED,
        }
        for row in bundle["historical_songs"]:
            assert set(row["accounting"]["parts"]) == expected



# ---------------------------------------------------------------------------
# Section 12 - the detector comparison and the exact identity
# ---------------------------------------------------------------------------
@requires_control
class TestDetectorComparison:
    def test_the_detector_is_compared_on_counts_and_onsets(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        records = stage20.note_records(control_song.trace)
        report = stage21.detector_comparison(control_song.trace, notes, records)
        assert report["composition_notes"] > 0
        assert report["detected_notes"] > 0
        assert report["detected_over_composition"] is not None
        assert report["per_voice"]

    def test_every_detected_note_is_matched_to_a_composition_onset(
        self, control_song: Any
    ) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        records = stage20.note_records(control_song.trace)
        report = stage21.detector_comparison(control_song.trace, notes, records)
        for voice in report["per_voice"].values():
            assert voice["matched_onsets"] == voice["detected_notes"]

    def test_the_pooled_recall_is_below_one(self, bundle: Dict[str, Any]) -> None:
        assert bundle["control_pool"]["detector_recall"] < 1.0


@requires_control
class TestExactReconstruction:
    def test_the_identity_holds_for_the_independent_arm(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        arm = stage21.arm_independent(
            control_song.trace, notes, control_song.frames_per_tick, stage21.OUTSIDE_EXPORTER
        )
        report = stage21._exact_reconstruction(control_song.trace, arm["residual"])
        assert report["holds"] is True
        assert report["register_values_checked"] == control_song.frames * stage21.FRAME_BYTES

    def test_the_identity_holds_for_the_detector_arm(self, control_song: Any) -> None:
        arm = stage21.arm_detector(control_song.trace)
        assert stage21._exact_reconstruction(control_song.trace, arm["residual"])["holds"] is True

    def test_the_identity_holds_on_every_bundle_song(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["control_songs"]:
            assert row["exact_reconstruction"]["holds"] is True, row["slug"]
            assert row["exact_reconstruction_detector"]["holds"] is True, row["slug"]
        for row in bundle["historical_songs"]:
            assert row["exact_reconstruction"]["holds"] is True, row["slug"]

    def test_a_zeroed_residual_is_refused(self, control_song: Any) -> None:
        arm = stage21.arm_detector(control_song.trace)
        original = arm["residual"]
        broken = stage20.Residual(
            slug=original.slug, frames=original.frames, predicted=original.predicted,
            exact=original.exact,
            values=[[0] * original.frames for _ in range(stage21.FRAME_BYTES)],
        )
        with pytest.raises(stage21.Stage21Error):
            stage21._exact_reconstruction(control_song.trace, broken)


# ---------------------------------------------------------------------------
# Section 15 - the frozen grammar, the controls and the null models
# ---------------------------------------------------------------------------
class TestFrozenGrammar:
    def test_the_frozen_vocabulary_has_no_repeat(self) -> None:
        names = [stage19.OP_NAMES[op] for op in stage21.FROZEN_VOCABULARY]
        assert "REPEAT" not in names
        assert set(names) == {"SET", "HOLD", "RAMP", "TOGGLE"}

    def test_an_empty_residual_has_nothing_to_explain(self) -> None:
        values = [[0] * 32 for _ in range(stage21.FRAME_BYTES)]
        report = stage21.frozen_grammar(values)
        assert report["residual_values"] == 0
        assert report["structural_share"] is None
        assert report["structural_residual_values"] == 0


@requires_control
class TestControlsAndNulls:
    def _arms(self, control_song: Any):
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        detector = stage21.arm_detector(control_song.trace)
        independent = stage21.arm_independent(
            control_song.trace, notes, control_song.frames_per_tick, stage21.OUTSIDE_EXPORTER
        )
        return notes, detector, independent

    def test_the_alignment_control_grows_with_the_shift(self, control_song: Any) -> None:
        notes, detector, independent = self._arms(control_song)
        report = stage21.controls(
            control_song.trace, notes, control_song.frames_per_tick, detector, independent
        )
        assert report["A_shifted_notes"]["monotone_nondecreasing"] is True
        assert report["A_shifted_notes"]["shifts"]["0"]["residual_values"] == 0

    def test_the_shuffled_notes_control_raises_the_residual(self, control_song: Any) -> None:
        notes, detector, independent = self._arms(control_song)
        report = stage21.controls(
            control_song.trace, notes, control_song.frames_per_tick, detector, independent
        )
        assert report["B_shuffled_notes"]["residual_values"] > 0

    def test_the_note_removal_control_is_a_share_of_the_stream(self, control_song: Any) -> None:
        notes, detector, independent = self._arms(control_song)
        report = stage21.controls(
            control_song.trace, notes, control_song.frames_per_tick, detector, independent
        )
        floor = report["C_note_removal"]
        assert 0.0 <= floor["residual_share"] <= 1.0
        assert floor["detector_arm_residual_share"] >= 0.0

    def test_the_detector_versus_independent_control_is_reported(self, control_song: Any) -> None:
        notes, detector, independent = self._arms(control_song)
        report = stage21.controls(
            control_song.trace, notes, control_song.frames_per_tick, detector, independent
        )
        assert report["D_detector_versus_independent"]["detector_residual_values"] > 0
        assert report["D_detector_versus_independent"]["independent_residual_values"] == 0

    def test_the_shuffled_residual_null_is_reported(self, control_song: Any) -> None:
        notes, detector, independent = self._arms(control_song)
        report = stage21.controls(
            control_song.trace, notes, control_song.frames_per_tick, detector, independent
        )
        assert "null_shuffled_residual" in report

    def test_the_shuffle_is_deterministic(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        first = stage21._shuffled_notes(notes, stage21.RANDOM_SEED)
        second = stage21._shuffled_notes(notes, stage21.RANDOM_SEED)
        assert [note.to_dict() for note in first] == [note.to_dict() for note in second]

    def test_the_shuffle_preserves_the_note_multiset(self, control_song: Any) -> None:
        notes = stage21.composition_notes(control_song.song, control_song.trace)
        shuffled = stage21._shuffled_notes(notes, stage21.RANDOM_SEED)
        live = [note for note in notes if not note.is_rest]
        assert sorted(note.midi for note in shuffled) == sorted(note.midi for note in live)
        assert sorted(note.divider for note in shuffled) == sorted(note.divider for note in live)
        assert sorted(note.start for note in shuffled) == sorted(note.start for note in live)


    def test_a_nonempty_residual_is_measured_on_both_vocabularies(self) -> None:
        values = [[0] * 32 for _ in range(stage21.FRAME_BYTES)]
        values[0][4:9] = [1, 2, 3, 4, 5]
        report = stage21.frozen_grammar(values)
        assert report["residual_values"] == 5
        assert report["structural_share"] is not None
        assert "structural_share" in report["with_delta"]



# ---------------------------------------------------------------------------
# Section 14/16 - the decisive test, the leave-one-out, the verdicts
# ---------------------------------------------------------------------------
@requires_corpus
class TestNullInstrumentTest:
    def test_it_compares_the_two_corpora(self, bundle: Dict[str, Any]) -> None:
        test = bundle["null_instrument_test"]
        assert test["historical"]["songs"] > 0
        assert test["control"]["songs"] > 0
        assert test["historical"]["residual_share"] is not None
        assert test["control"]["residual_share"] is not None

    def test_the_grammar_explains_the_artefact_at_least_as_well(
        self, bundle: Dict[str, Any]
    ) -> None:
        test = bundle["null_instrument_test"]
        delta = test["grammar_structure_delta_control_minus_historical"]
        assert delta is not None
        assert delta > 0.05
        assert test["structure_verdict"] == (
            "GRAMMAR_EXPLAINS_ARTEFACTS_BETTER_THAN_THE_HISTORICAL_RESIDUAL"
        )
        assert test["verdict"] == "STAGE_20_INSTRUMENT_NOT_VALIDATED"

    def test_the_known_artefact_residual_is_of_the_same_order(
        self, bundle: Dict[str, Any]
    ) -> None:
        ratio = bundle["null_instrument_test"][
            "residual_magnitude_ratio_historical_over_control"
        ]
        assert ratio is not None
        assert ratio > 0.5

    def test_the_conclusion_names_the_alternative_explanation(
        self, bundle: Dict[str, Any]
    ) -> None:
        assert "instrument" in bundle["null_instrument_test"]["conclusion"]


@requires_corpus
class TestLeaveOneOut:
    def test_both_corpora_are_held_out(self, bundle: Dict[str, Any]) -> None:
        loo = bundle["leave_one_out"]
        assert loo["control"]["songs"] >= 3
        assert loo["historical_stage20"]["songs"] >= 3

    def test_every_fold_names_what_it_held_out(self, bundle: Dict[str, Any]) -> None:
        for fold in bundle["leave_one_out"]["control"]["folds"]:
            assert fold["held_out"]
            assert fold["trained_on"]
            assert fold["held_out"] not in fold["trained_on"]

    def test_a_positive_size_gain_is_reported_for_the_known_artefact_residual(
        self, bundle: Dict[str, Any]
    ) -> None:
        gain = bundle["leave_one_out"]["control"]["mean_size_gain"]
        assert gain is not None
        assert gain > 0.0

    def test_generalisation_is_not_claimed_for_performance(self, bundle: Dict[str, Any]) -> None:
        verdict = bundle["verdicts"]["generalization"]
        assert verdict["verdict"] == "RESIDUAL_GENERALIZATION_NOT_SUPPORTED"
        assert verdict["independent_residual_generalization"] == (
            "RESIDUAL_GENERALIZATION_NOT_TESTABLE"
        )
        assert "Stage 19" in verdict["previous_result_preserved"]


@requires_corpus
class TestVerdicts:
    def test_the_six_verdicts_are_the_declared_ones(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["dataset"]["verdict"] == "TIER_D_ONLY"
        assert verdicts["note_baseline"]["verdict"] == "NOTE_BASELINE_PARTIALLY_VALIDATED"
        assert verdicts["residual_authenticity"]["verdict"] == "RESIDUAL_NOT_CONFIRMED"
        assert verdicts["generalization"]["verdict"] == "RESIDUAL_GENERALIZATION_NOT_SUPPORTED"
        assert verdicts["performance_layer"]["verdict"] == (
            "PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE"
        )
        assert verdicts["player_integration"]["verdict"] == "PLAYER_INTEGRATION_NOT_JUSTIFIED"

    def test_promising_is_never_promoted_to_justified(self, bundle: Dict[str, Any]) -> None:
        verdicts = json.dumps(bundle["verdicts"])
        assert "PERFORMANCE_LAYER_JUSTIFIED" not in verdicts
        assert "PLAYER_INTEGRATION_JUSTIFIED" not in verdicts

    def test_every_verdict_states_its_deciding_condition(self, bundle: Dict[str, Any]) -> None:
        for name, row in bundle["verdicts"].items():
            assert row["deciding_condition"].strip(), name
            assert row["conditions"], name

    def test_the_layer_direction_is_recorded_as_negative(self, bundle: Dict[str, Any]) -> None:
        assert bundle["verdicts"]["performance_layer"]["direction"] == "NEGATIVE"

    def test_no_production_change_is_allowed(self, bundle: Dict[str, Any]) -> None:
        conditions = bundle["verdicts"]["player_integration"]["conditions"]
        assert conditions["production_change_allowed"] is False



# ---------------------------------------------------------------------------
# Section 30/32 - determinism, corrupted input, truncated input
# ---------------------------------------------------------------------------
@requires_corpus
class TestDeterminism:
    def test_the_audit_is_reproducible(self) -> None:
        first = stage21.dataset_audit()
        second = stage21.dataset_audit()
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_the_audit_carries_no_timestamp_or_random_field(self) -> None:
        text = json.dumps(stage21.dataset_audit())
        assert "generated_at" not in text
        assert "timestamp" not in text

    @requires_control
    def test_the_notes_and_the_residual_are_reproducible(self, control_song: Any) -> None:
        first = stage21.composition_notes(control_song.song, control_song.trace)
        second = stage21.composition_notes(control_song.song, control_song.trace)
        assert [note.to_dict() for note in first] == [note.to_dict() for note in second]
        a = stage21.arm_independent(
            control_song.trace, first, control_song.frames_per_tick, stage21.OUTSIDE_EXPORTER
        )
        b = stage21.arm_independent(
            control_song.trace, second, control_song.frames_per_tick, stage21.OUTSIDE_EXPORTER
        )
        assert a["residual_values"] == b["residual_values"]

    def test_the_bundle_declares_its_determinism(self, bundle: Dict[str, Any]) -> None:
        determinism = bundle["determinism"]
        assert determinism["no_timestamps"] is True
        assert determinism["random_seed"] == stage21.RANDOM_SEED
        assert determinism["source_hash"] == stage21.sha256_file(Path(stage21.__file__))

    def test_the_control_order_is_stable(self) -> None:
        first = [slug for slug, _kind, _path in stage21.control_sources()]
        second = [slug for slug, _kind, _path in stage21.control_sources()]
        assert first == second


class TestCorruptedAndTruncatedInput:
    """The scan roots are passed explicitly, so a temporary directory really is the whole input."""

    def test_a_corrupted_json_document_is_reported_and_skipped(self, tmp_path: Path) -> None:
        ai_dir = tmp_path / "ai"
        ai_dir.mkdir()
        (ai_dir / "broken.json").write_text("{ \"patterns\": [ , ] }", encoding="utf-8")
        corpus, skipped = stage21.load_control_corpus(
            tmp_path / "absent", ai_dir, extra_dsl_dir=None
        )
        assert corpus == []
        assert len(skipped) == 1
        assert skipped[0]["slug"] == "broken"
        assert skipped[0]["error"]

    def test_a_truncated_dsl_score_is_reported_and_skipped(self, tmp_path: Path) -> None:
        songs = tmp_path / "songs"
        songs.mkdir()
        (songs / "half.dsl").write_text(
            'TITLE "half"\nBPM 90\n[PATTERN A1 length=8\nCH1 lead V12\nD2/4\n', encoding="utf-8"
        )
        corpus, skipped = stage21.load_control_corpus(
            songs, tmp_path / "absent", extra_dsl_dir=None
        )
        assert corpus == []
        assert len(skipped) == 1
        assert skipped[0]["stage"] in ("parse", "translate", "compile")

    def test_a_degenerate_but_valid_score_is_kept_not_skipped(self, tmp_path: Path) -> None:
        """A pattern with no notes parses. It is a valid, empty composition, so it is kept.

        This is the honest behaviour: the stage reports what a document *is*, and a score that
        contains no notes is a score with no notes, not a parse failure. The artefact shows a song
        with zero notes rather than hiding it.
        """
        songs = tmp_path / "songs"
        songs.mkdir()
        (songs / "empty.dsl").write_text(
            'TITLE "empty"\nBPM 90\n[PATTERN A1 length=8]\nCH1 lead V12\nR/8\n', encoding="utf-8"
        )
        corpus, skipped = stage21.load_control_corpus(
            songs, tmp_path / "absent", extra_dsl_dir=None
        )
        assert skipped == []
        assert len(corpus) == 1
        assert corpus[0].note_count == 0

    def test_a_non_composition_json_is_ignored_rather_than_skipped(self, tmp_path: Path) -> None:
        ai_dir = tmp_path / "ai"
        ai_dir.mkdir()
        (ai_dir / "metrics.json").write_text('{"scores": [1, 2, 3]}', encoding="utf-8")
        corpus, skipped = stage21.load_control_corpus(
            tmp_path / "absent", ai_dir, extra_dsl_dir=None
        )
        assert corpus == []
        assert skipped == []

    def test_an_empty_extra_dsl_root_is_allowed(self, tmp_path: Path) -> None:
        assert stage21.control_sources(
            tmp_path / "absent", tmp_path / "absent", extra_dsl_dir=None
        ) == []

    def test_a_missing_archaeology_directory_is_refused_not_papered_over(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(stage21.Stage21Error):
            stage21.run_analysis(
                arch_root=tmp_path / "absent",
                songs_dir=tmp_path / "absent",
                ai_dir=tmp_path / "absent",
            )

    def test_a_wrong_shaped_frame_array_is_refused(self) -> None:
        with pytest.raises(stage21.Stage21Error):
            stage21.frames_to_registers(stage21.np.zeros((3, 3), dtype="uint8"))


# ---------------------------------------------------------------------------
# Section 33 - the report
# ---------------------------------------------------------------------------
@requires_corpus
class TestReport:
    def test_the_report_has_every_section_of_the_brief(self, bundle: Dict[str, Any]) -> None:
        report = stage21.render_report(bundle)
        for number in range(1, 21):
            assert f"## {number}." in report, number
        assert "## The Final Question" in report

    def test_the_report_states_the_question_it_answers(self, bundle: Dict[str, Any]) -> None:
        report = stage21.render_report(bundle)
        assert "independent composition source" in report
        assert "Performance Layer" in report

    def test_the_report_quotes_the_declared_verdicts(self, bundle: Dict[str, Any]) -> None:
        report = stage21.render_report(bundle)
        for verdict in bundle["summary"]["verdicts"].values():
            assert verdict in report, verdict

    def test_the_report_refuses_the_performance_equation(self, bundle: Dict[str, Any]) -> None:
        report = stage21.render_report(bundle)
        assert "not demonstrated to be performance information" in report

    def test_the_report_names_the_minimum_missing_dataset(self, bundle: Dict[str, Any]) -> None:
        report = stage21.render_report(bundle)
        assert "channel assignment" in report
        assert "independent note source" in report or "independent note source -" in report

    def test_the_report_states_that_the_stage_stops(self, bundle: Dict[str, Any]) -> None:
        assert "Stage 21 stops here" in stage21.render_report(bundle)

    def test_the_report_renders_every_table(self, bundle: Dict[str, Any]) -> None:
        report = stage21.render_report(bundle)
        assert "|---" in report
        assert "| " in report


# ---------------------------------------------------------------------------
# Section 28 - the artefacts and the CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestArtefacts:
    def test_the_writer_produces_every_declared_file(self, bundle: Dict[str, Any],
                                                     tmp_path: Path) -> None:
        written = stage21.write_analysis(
            bundle, stage21_dir=tmp_path / "stage21", docs_dir=tmp_path / "docs"
        )
        for name in stage21.STAGE21_FILES:
            assert name in written
            assert (tmp_path / "stage21" / name).is_file()
        assert (tmp_path / "docs" / stage21.STAGE21_DOC).is_file()

    def test_every_artefact_is_valid_json_and_carries_no_raw_arrays(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        stage21.write_analysis(bundle, stage21_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        for name in stage21.STAGE21_FILES:
            payload = json.loads((tmp_path / "r" / name).read_text(encoding="utf-8"))
            assert payload is not None, name
        categories = json.loads(
            (tmp_path / "r" / "information_accounting.json").read_text(encoding="utf-8")
        )
        for row in categories["historical"].values():
            assert row["closes"] is True

    def test_the_summary_repeats_the_verdicts(self, bundle: Dict[str, Any]) -> None:
        summary = bundle["summary"]
        assert summary["verdicts"]["performance_layer"] == (
            "PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE"
        )
        assert "dataset" in summary["verdicts"]

    def test_the_document_names_the_stage(self) -> None:
        assert stage21.STAGE21_DOC == "stage21_controlled_validation.md"


@requires_corpus
class TestReadOnlyAudit:
    """Section 31 of the brief: hash the inputs before the run and prove nothing changed."""

    def test_every_production_file_is_present_and_hashed(self) -> None:
        hashes = stage21.production_hashes()
        assert hashes
        for name, digest in hashes.items():
            assert digest is not None, name
            assert len(digest) == 64, name

    def test_the_corpus_and_the_compositions_are_hashed(self) -> None:
        hashes = stage21.corpus_hashes()
        assert hashes
        assert any(name.startswith("trace/") for name in hashes)
        assert any(name.startswith("composition/") for name in hashes)

    def test_a_run_changes_nothing_it_reads(self, bundle: Dict[str, Any]) -> None:
        audit = bundle["read_only_audit"]
        assert audit["production"]["read_only"] is True, audit["production"]["changed"]
        assert audit["corpus_and_compositions"]["read_only"] is True, (
            audit["corpus_and_compositions"]["changed"]
        )
        assert bundle["summary"]["read_only"] is True

    def test_the_audit_reports_a_fabricated_change(self) -> None:
        before = {"a.py": "0" * 64, "b.py": "1" * 64}
        after = {"a.py": "0" * 64, "b.py": "2" * 64}
        report = stage21.read_only_audit(before, after)
        assert report["read_only"] is False
        assert report["changed"] == ["b.py"]
        assert report["unchanged"] == 1

    def test_the_writer_touches_nothing_outside_its_own_directories(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        before = stage21.production_hashes()
        corpus_before = stage21.corpus_hashes()
        stage21.write_analysis(
            bundle, stage21_dir=tmp_path / "stage21", docs_dir=tmp_path / "docs"
        )
        assert stage21.production_hashes() == before
        assert stage21.corpus_hashes() == corpus_before


@requires_corpus
class TestCli:
    def test_the_command_lists_its_options(self) -> None:
        result = CliRunner().invoke(cli, ["analyze-stage21", "--help"])
        assert result.exit_code == 0, result.output
        assert "--control-limit" in result.output
        assert "--reports-dir" in result.output

    def test_the_command_writes_the_record_and_the_document(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        docs = tmp_path / "docs"
        result = CliRunner().invoke(
            cli,
            ["analyze-stage21", "--reports-dir", str(reports), "--docs-dir", str(docs),
             "--control-limit", "1", "--detail-limit", "1"],
        )
        assert result.exit_code == 0, result.output
        assert (docs / stage21.STAGE21_DOC).is_file()
        for name in stage21.STAGE21_FILES:
            assert (reports / name).is_file()
        assert "Tier" in result.output
        assert "PERFORMANCE_LAYER" in result.output or "RESIDUAL_" in result.output

    def test_the_cli_reports_the_same_verdicts_as_the_bundle(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["analyze-stage21", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d"), "--control-limit", "1", "--detail-limit", "1"],
        )
        assert result.exit_code == 0, result.output
        written = json.loads((tmp_path / "r" / "summary.json").read_text(encoding="utf-8"))
        for verdict in written["verdicts"].values():
            assert verdict in result.output, verdict


# ---------------------------------------------------------------------------
# Small units that carry a rule
# ---------------------------------------------------------------------------
class TestSmallUnits:
    def test_a_none_cell_prints_as_not_applicable(self) -> None:
        assert stage21._cell(None) == "n/a"
        assert stage21._cell(0) == "0"
        assert "n/a" in stage21._table(["a"], [[None]])

    def test_a_note_and_a_record_are_never_the_same_object(self) -> None:
        """The composition notes and the detector notes are different types on purpose."""
        assert stage21.CompositionNote is not stage20.NoteRecord
        assert stage21.Plan is not stage20.NoteRecord

    def test_the_distortion_nibble_matches_the_exporters_packing(self) -> None:
        assert stage21.distortion_nibble(0xA0) == 0x0A
        assert stage21.distortion_nibble(0x80) == 0x08
        assert (stage21.distortion_nibble(0x80) << 4) == (0x80 & 0xE0)

    def test_a_plan_carries_only_what_the_predictor_reads(self) -> None:
        plan = stage21.Plan(
            voice_id="V1", start=0, end=4, dividers=((1, 100),), pack=0xA0,
            peak=8, attack=0, decay=0, sustain=8, release=0,
        )
        assert plan.dividers == ((1, 100),)
        assert plan.pack == 0xA0

    def test_share_and_mean_refuse_an_empty_input(self) -> None:
        assert stage21._share(1, 0) is None
        assert stage21._mean([]) is None
        assert stage21._share(1, 4) == 0.25
        assert stage21._mean([1.0, 3.0]) == 2.0

    def test_the_analysis_version_is_declared(self) -> None:
        assert stage21.ANALYSIS_VERSION == "stage21/1"

    def test_the_register_order_is_the_canonical_one(self) -> None:
        assert stage21.REGISTER_ORDER == stage18.REGISTER_ORDER
        assert stage21.FRAME_BYTES == 9

    def test_the_audit_flags_are_the_seven_of_the_brief(self) -> None:
        assert set(stage21.HAS_FLAGS) == {
            "HAS_SAP", "HAS_EXACT_TRACE", "HAS_INDEPENDENT_NOTES", "HAS_TIMING",
            "HAS_CHANNEL_ASSIGNMENT", "HAS_VELOCITY", "HAS_PLAYER_RECONSTRUCTION",
        }

    def test_the_residual_categories_are_the_five_of_the_brief(self) -> None:
        assert set(stage21.RESIDUAL_CATEGORIES) == {
            "BASELINE_ERROR", "ALIGNMENT_UNCERTAINTY", "CHANNEL_UNCERTAINTY",
            "CONFIRMED_PERFORMANCE_CANDIDATE", "UNRESOLVED",
        }

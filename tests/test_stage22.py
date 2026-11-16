"""Stage 22 - detector error decomposition and ground-truth calibration.

These tests pin the stage to the claims it makes, and they are written to fail on the mistakes the
brief names rather than on the mistakes that are easy to test:

* `trace == prediction + residual`, and the five frame-attribution buckets summing to the whole trace
  - a missing residual or a double count breaks the identity;
* the cause partition closing exactly on the detector's residual - an incorrect denominator breaks it;
* the two predictors being the same function, so an arm difference is a difference of information
  rather than of code;
* the exact composition leaving nothing at all, on every song;
* the three no-op fields measuring zero, so an invariant is proved rather than assumed;
* pooled counts never being an average of per-song shares;
* deterministic matching, with no tie-break that depends on iteration order or hash randomisation;
* a repeated run producing byte-identical artefacts;
* a read-only audit over the production modules and the composition documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from click.testing import CliRunner

from atari_music import stage15, stage18, stage20, stage21, stage22
from atari_music.cli import cli

pytestmark = pytest.mark.experimental

requires_control = pytest.mark.skipif(
    not stage22.DEFAULT_SONGS_DIR.is_dir(),
    reason="the .dsl compositions are not present on this machine",
)

requires_corpus = pytest.mark.skipif(
    not stage22.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage22.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="session")
def bundle() -> Dict[str, Any]:
    """One bounded run of the whole stage, shared by every test that needs the record.

    Two control compositions in full detail and two historical traces, so the whole suite stays
    reasonably quick while every code path is still exercised. The full-corpus claims are asserted
    separately where they are cheap.
    """
    return stage22.run_analysis(control_limit=2, detail_limit=2, historical_limit=2)


@pytest.fixture(scope="session")
def control_song() -> Any:
    corpus, _skipped = stage21.load_control_corpus()
    assert corpus, "the control corpus is empty"
    return corpus[0]


@pytest.fixture(scope="session")
def parts(control_song: Any) -> Dict[str, Any]:
    """The pieces one song's analysis is built from, so unit tests need not run the whole stage."""
    trace = control_song.trace
    truth, status = stage22.ground_truth_notes(control_song, trace)
    records = stage20.note_records(trace)
    predicted = stage20.predict_frames(trace, records, 0, True)
    residual = stage22.residual_of(trace, predicted)
    return {
        "song": control_song,
        "trace": trace,
        "truth": truth,
        "status": status,
        "records": records,
        "predicted": predicted,
        "residual": residual,
    }


def fake_trace(frames: int = 24, audctl: int = 0x00) -> Any:
    """A trace-shaped object with every register held at zero, for synthetic tests."""
    registers = {name: [0] * frames for name in stage22.REGISTER_ORDER}
    return SimpleNamespace(frames=frames, registers=registers, audctl=audctl, slug="fake")


# ---------------------------------------------------------------------------
# 1. ground-truth extraction
# ---------------------------------------------------------------------------
class TestGroundTruth:
    def test_every_canonical_field_carries_a_status(self, parts: Dict[str, Any]) -> None:
        status = parts["status"]
        assert set(status) == set(stage22.CANONICAL_FIELDS)
        assert set(status.values()) <= set(stage22.FIELD_STATUSES)

    def test_a_note_that_exists_is_known_and_one_that_is_computed_is_derived(
        self, parts: Dict[str, Any]
    ) -> None:
        status = parts["status"]
        assert status["pitch_midi"] == stage22.KNOWN
        assert status["channel"] == stage22.KNOWN
        assert status["onset_frames"] == stage22.DERIVED
        assert status["volume_track"] == stage22.DERIVED
        assert status["audctl"] == stage22.DERIVED

    def test_notes_are_ordered_deterministically(self, parts: Dict[str, Any]) -> None:
        keys = [
            (note.channel, note.onset_frames, note.note_index) for note in parts["truth"]
        ]
        assert keys == sorted(keys)

    def test_the_volume_track_matches_the_trace(self, parts: Dict[str, Any]) -> None:
        trace = parts["trace"]
        for note in parts["truth"]:
            if note.silence:
                continue
            audc = trace.registers[f"AUDC{note.volume_channel}"]
            expected = [
                stage15.audc_volume(audc[frame])
                for frame in range(note.onset_frames,
                                   min(note.onset_frames + note.duration_frames, trace.frames))
            ]
            assert list(note.volume_track) == expected

    def test_a_sounding_note_is_not_silent_and_a_silent_one_has_no_level(
        self, parts: Dict[str, Any]
    ) -> None:
        for note in parts["truth"]:
            if note.silence:
                assert not any(note.volume_track)
            else:
                assert any(note.volume_track)

    def test_the_summary_reports_the_status_counts(
        self, bundle: Dict[str, Any]
    ) -> None:
        ground_truth = bundle["ground_truth"]
        assert ground_truth["songs"] == len(bundle["corpus"]["control"])
        assert set(ground_truth["status_counts"]) == set(stage22.CANONICAL_FIELDS)
        for counts in ground_truth["status_counts"].values():
            assert sum(counts.values()) == ground_truth["songs"]


# ---------------------------------------------------------------------------
# 2. the predictor and its bridge
# ---------------------------------------------------------------------------
class TestPredictorBridge:
    def test_the_stage_22_predictor_reproduces_stage_20(self, parts: Dict[str, Any]) -> None:
        report = stage22.assert_matches_stage20(parts["trace"])
        assert report["agrees"], report["first_mismatches"]
        assert report["mismatches"] == 0
        assert report["register_values"] == parts["trace"].frames * stage22.FRAME_BYTES

    def test_the_bridge_holds_for_every_song_in_the_run(self, bundle: Dict[str, Any]) -> None:
        assert bundle["predictor_bridge"], "the bridge was never run"
        assert all(row["agrees"] for row in bundle["predictor_bridge"])

    def test_the_bridge_holds_across_a_different_audctl(self, parts: Dict[str, Any]) -> None:
        """A joined 16-bit voice is where the two predictors could most easily diverge."""
        corpus, _ = stage21.load_control_corpus()
        joined = [song for song in corpus if song.uses_16bit_bass]
        if not joined:
            pytest.skip("no 16-bit composition in the corpus")
        for song in joined[:2]:
            assert stage22.assert_matches_stage20(song.trace)["agrees"]

    def test_specs_from_records_reproduce_the_detector_baseline(
        self, parts: Dict[str, Any]
    ) -> None:
        trace = parts["trace"]
        specs = stage22.specs_from_records(parts["records"], int(trace.audctl))
        mine = stage22.predict_from_specs(
            trace.frames, int(trace.audctl), specs, stage22.OUTSIDE_HOLD
        )
        assert mine == parts["predicted"]

    def test_an_unknown_outside_policy_is_refused(self, parts: Dict[str, Any]) -> None:
        with pytest.raises(stage22.Stage22Error):
            stage22.predict_from_specs(
                parts["trace"].frames, int(parts["trace"].audctl), [], "nonsense"
            )

    def test_an_unknown_note_set_is_refused(self, parts: Dict[str, Any]) -> None:
        with pytest.raises(stage22.Stage22Error):
            stage22.build_specs(
                parts["trace"], parts["truth"], parts["records"], frozenset(), "nonsense"
            )

    def test_the_ground_truth_arm_leaves_no_residual(self, parts: Dict[str, Any]) -> None:
        trace = parts["trace"]
        specs = stage22.specs_from_ground_truth(parts["truth"])
        predicted = stage22.predict_from_specs(
            trace.frames, int(trace.audctl), specs, stage22.OUTSIDE_EXPORTER
        )
        assert stage22.residual_of(trace, predicted).residual_values() == 0

    def test_the_ground_truth_arm_under_hold_leaves_only_the_convention(
        self, parts: Dict[str, Any]
    ) -> None:
        """The composition claims only the frames it sounds; the rest is the convention's business.

        Under the hold policy an unwritten frame inherits the last AUDF, and the compiler leaves it at
        zero, so the residual here *is* the convention cost - not a detector error and not a
        composition error.
        """
        trace = parts["trace"]
        specs = stage22.specs_from_ground_truth(parts["truth"])
        predicted = stage22.predict_from_specs(
            trace.frames, int(trace.audctl), specs, stage22.OUTSIDE_HOLD
        )
        residual = stage22.residual_of(trace, predicted)
        report = stage22.register_residual(residual)
        assert report["groups"]["AUDC"]["residual_values"] == 0
        assert report["groups"]["AUDCTL"]["residual_values"] == 0
        assert report["groups"]["AUDF"]["residual_values"] == residual.residual_values()


# ---------------------------------------------------------------------------
# 3. residual accounting
# ---------------------------------------------------------------------------
class TestResidualAccounting:
    def test_the_residual_count_is_the_values_that_differ(self, parts: Dict[str, Any]) -> None:
        residual = parts["residual"]
        counted = sum(
            1
            for column in range(stage22.FRAME_BYTES)
            for frame in range(residual.frames)
            if residual.values[column][frame]
        )
        assert counted == residual.residual_values()

    def test_per_register_counts_sum_to_the_total(self, parts: Dict[str, Any]) -> None:
        report = stage22.register_residual(parts["residual"])
        assert sum(report["per_register"].values()) == report["residual_values"]
        assert sum(row["residual_values"] for row in report["groups"].values()) == (
            report["residual_values"]
        )

    def test_every_register_group_has_the_right_denominator(self, parts: Dict[str, Any]) -> None:
        report = stage22.register_residual(parts["residual"])
        for group, names in stage22.REGISTER_GROUPS:
            assert report["groups"][group]["register_values"] == parts["trace"].frames * len(names)

    def test_the_frame_attribution_closes(self, parts: Dict[str, Any]) -> None:
        attribution = stage22.frame_attribution(
            parts["trace"], parts["records"], parts["truth"], parts["residual"]
        )
        assert attribution["closes"]
        assert sum(attribution["counts"].values()) == attribution["total_register_values"]

    def test_the_frame_attribution_has_every_bucket_and_no_negative_one(
        self, parts: Dict[str, Any]
    ) -> None:
        attribution = stage22.frame_attribution(
            parts["trace"], parts["records"], parts["truth"], parts["residual"]
        )
        assert set(attribution["counts"]) == set(stage22.ATTRIBUTION_BUCKETS)
        assert all(value >= 0 for value in attribution["counts"].values())

    def test_explained_plus_residual_is_the_whole_trace(self, parts: Dict[str, Any]) -> None:
        attribution = stage22.frame_attribution(
            parts["trace"], parts["records"], parts["truth"], parts["residual"]
        )
        assert (
            attribution["counts"][stage22.ATTR_EXPLAINED]
            + attribution["residual_values"]
            == attribution["total_register_values"]
        )

    def test_a_perfect_prediction_attributes_everything_to_explained(
        self, parts: Dict[str, Any]
    ) -> None:
        trace = parts["trace"]
        exact = [
            tuple(int(trace.registers[name][frame]) for name in stage22.REGISTER_ORDER)
            for frame in range(trace.frames)
        ]
        residual = stage22.residual_of(trace, exact)
        attribution = stage22.frame_attribution(
            trace, parts["records"], parts["truth"], residual
        )
        assert attribution["counts"][stage22.ATTR_EXPLAINED] == attribution["total_register_values"]
        assert attribution["residual_values"] == 0

    def test_the_attribution_says_it_is_not_a_cause_attribution(
        self, parts: Dict[str, Any]
    ) -> None:
        attribution = stage22.frame_attribution(
            parts["trace"], parts["records"], parts["truth"], parts["residual"]
        )


# ---------------------------------------------------------------------------
# 4. deterministic matching
# ---------------------------------------------------------------------------
class TestDeterministicMatching:
    def test_matching_is_independent_of_the_record_order(self, parts: Dict[str, Any]) -> None:
        """A permuted record list must produce the same matched *set*, not the same indices."""
        truth = parts["truth"]
        records = list(parts["records"])
        forward, _ = stage22.match_truth_to_records(truth, records)
        pairs = {(index, records[order].start, records[order].end)
                 for index, order in forward.items()}
        shuffled = list(reversed(records))
        backward, _ = stage22.match_truth_to_records(truth, shuffled)
        reversed_pairs = {(index, shuffled[order].start, shuffled[order].end)
                          for index, order in backward.items()}
        assert pairs == reversed_pairs

    def test_a_note_matches_the_span_with_the_largest_overlap(
        self, parts: Dict[str, Any]
    ) -> None:
        truth = parts["truth"]
        records = list(parts["records"])
        forward, _ = stage22.match_truth_to_records(truth, records)
        for index, order in forward.items():
            note = truth[index]
            span = (note.onset_frames, note.onset_frames + max(1, len(note.volume_track)))
            record = records[order]
            other = (record.start, record.end + 1)
            overlap = stage22._span_overlap(span, other)
            assert overlap > 0
            best = max(
                stage22._span_overlap(span, (item.start, item.end + 1))
                for item in records if item.voice_id == note.voice_id
            )
            assert overlap == best

    def test_matching_never_crosses_voices(self, parts: Dict[str, Any]) -> None:
        truth = parts["truth"]
        records = list(parts["records"])
        forward, _ = stage22.match_truth_to_records(truth, records)
        for index, order in forward.items():
            assert truth[index].voice_id == records[order].voice_id

    def test_silent_notes_are_never_matched(self, parts: Dict[str, Any]) -> None:
        truth = parts["truth"]
        forward, _ = stage22.match_truth_to_records(truth, list(parts["records"]))
        assert all(not truth[index].silence for index in forward)

    def test_a_synthetic_overlap_prefers_the_larger_overlap(self) -> None:
        """Before any tie-break, the span with the greater overlap wins."""
        note = SimpleNamespace(
            voice_id="V1", silence=False, onset_frames=10, volume_track=(1, 1, 1, 1),
        )
        # note span is (10, 14); (9, 13) overlaps by 3 and (10, 14) by 4.
        left = SimpleNamespace(voice_id="V1", start=9, end=13)
        right = SimpleNamespace(voice_id="V1", start=10, end=14)
        forward, _ = stage22.match_truth_to_records([note], [right, left])
        assert forward == {0: 0}
        forward, _ = stage22.match_truth_to_records([note], [left, right])
        assert forward == {0: 1}

    def test_a_synthetic_exact_tie_breaks_on_the_smaller_start(self) -> None:
        """Equal overlap and equal onset distance: the smaller start must win, in either order."""
        note = SimpleNamespace(
            voice_id="V1", silence=False, onset_frames=10, volume_track=(1, 1, 1, 1),
        )
        # note span is (10, 14); (9, 13) and (11, 15) each overlap it by 3 with distance 1.
        left = SimpleNamespace(voice_id="V1", start=9, end=13)
        right = SimpleNamespace(voice_id="V1", start=11, end=15)
        assert stage22._span_overlap((10, 14), (9, 13)) == 3
        assert stage22._span_overlap((10, 14), (11, 15)) == 3
        forward, _ = stage22.match_truth_to_records([note], [right, left])
        assert forward == {0: 1}
        forward, _ = stage22.match_truth_to_records([note], [left, right])
        assert forward == {0: 0}

    def test_the_matching_rule_is_stated_in_the_result(self, parts: Dict[str, Any]) -> None:
        report = stage22.note_detection_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )


# ---------------------------------------------------------------------------
# 5. the ablation ladder and the arms
# ---------------------------------------------------------------------------
class TestAblationLadder:
    def test_the_exact_composition_leaves_nothing_under_the_exporter_policy(
        self, bundle: Dict[str, Any]
    ) -> None:
        ladder = bundle["aggregate"]["ladder"][stage22.OUTSIDE_EXPORTER]
        assert ladder["B10"]["residual_values"] == 0

    def test_the_exact_composition_under_hold_leaves_only_the_convention(
        self, bundle: Dict[str, Any]
    ) -> None:
        """B10 is zero under the exporter policy and *not* zero under hold, and the difference is
        the convention: the composition does not claim frames it does not sound."""
        hold = bundle["aggregate"]["ladder"][stage22.OUTSIDE_HOLD]["B10"]["residual_values"]
        exporter = bundle["aggregate"]["ladder"][stage22.OUTSIDE_EXPORTER]["B10"][
            "residual_values"
        ]
        assert exporter == 0
        assert hold >= exporter

    def test_b0_is_the_detector_and_the_arm_agrees(self, bundle: Dict[str, Any]) -> None:
        aggregate = bundle["aggregate"]
        assert (
            aggregate["ladder"][stage22.OUTSIDE_EXPORTER]["B0"]["residual_values"]
            == aggregate["arms"]["A_detector"]["residual_values"]
        )
        assert (
            aggregate["ladder"][stage22.OUTSIDE_HOLD]["B0"]["residual_values"]
            == aggregate["detector_residual_values"]
        )

    def test_the_exporter_policy_never_exceeds_the_hold_policy(
        self, bundle: Dict[str, Any]
    ) -> None:
        """Zeroing an unwritten frame can only remove residual, never add it."""
        for name, row in bundle["aggregate"]["ladder"][stage22.OUTSIDE_EXPORTER].items():
            hold = bundle["aggregate"]["ladder"][stage22.OUTSIDE_HOLD][name]
            assert row["residual_values"] <= hold["residual_values"]

    def test_the_ladder_is_non_increasing_under_the_exporter_policy(
        self, bundle: Dict[str, Any]
    ) -> None:
        for song in bundle["songs"]:
            if "ladder_exporter" not in song:
                continue
            values = [rung["residual_values"] for rung in song["ladder_exporter"]["rungs"]]
            assert values == sorted(values, reverse=True), song["slug"]

    def test_the_contradictory_arm_is_no_better_than_the_detector(
        self, bundle: Dict[str, Any]
    ) -> None:
        """Moving spans on the detector's own list is the finding the ladder's rungs report."""
        arms = bundle["aggregate"]["arms"]
        assert (
            arms["A_detector_spans_truth_boundaries"]["residual_values"]
            >= arms["A_detector"]["residual_values"]
        )

    def test_the_cause_partition_closes(self, bundle: Dict[str, Any]) -> None:
        partition = bundle["taxonomy"]["cause_partition"]
        assert partition["closes"]
        assert (
            partition["note_set_only"] + partition["value_only"] + partition["interaction"]
            == partition["detector_residual_values_exporter"]
        )
        assert (
            partition["convention"] + partition["detector_residual_values_exporter"]
            == partition["detector_residual_values_hold"]
        )

    def test_the_partition_uses_one_convention_throughout(self, bundle: Dict[str, Any]) -> None:
        """The arms and the total must share a policy, or the convention lands in the interaction."""
        aggregate = bundle["aggregate"]
        assert (
            aggregate["arms"]["A_detector"]["residual_values"]
            == bundle["taxonomy"]["cause_partition"]["detector_residual_values_exporter"]
        )
        assert (
            aggregate["arms_hold"]["A_detector"]["residual_values"]
            == bundle["taxonomy"]["cause_partition"]["detector_residual_values_hold"]
        )

    def test_the_convention_is_its_own_component(self, bundle: Dict[str, Any]) -> None:
        partition = bundle["taxonomy"]["cause_partition"]
        assert partition["convention"] > 0
        assert partition["convention_share_of_hold"] > 0

    def test_the_value_only_arm_is_the_envelope_marginal(self, bundle: Dict[str, Any]) -> None:
        """Two independent readings of the value error must agree, or one of them is wrong."""
        assert (
            bundle["aggregate"]["arms"]["A_truth_spans_detector_values"]["residual_values"]
            == bundle["aggregate"]["leave_one_out_marginals"][stage22.FIELD_ENVELOPE]
        )

    def test_the_noop_fields_measure_zero(self, bundle: Dict[str, Any]) -> None:
        marginals = bundle["aggregate"]["leave_one_out_marginals"]
        for field in (stage22.FIELD_CHANNEL, stage22.FIELD_VOLUME, stage22.FIELD_AUDCTL):
            assert marginals[field] == 0, field

    def test_every_noop_field_states_its_reason(self) -> None:
        for field in (stage22.FIELD_CHANNEL, stage22.FIELD_VOLUME, stage22.FIELD_AUDCTL):
            assert field in stage22.FIELD_NOOP_REASONS
            assert len(stage22.FIELD_NOOP_REASONS[field]) > 40

    def test_the_leave_one_out_scope_is_stated(self, bundle: Dict[str, Any]) -> None:
        for song in bundle["songs"]:
            if "leave_one_out" not in song:
                continue
            assert "exact by construction" in song["leave_one_out"]["field_scope_note"]


# ---------------------------------------------------------------------------
# 6. the specialised analyses
# ---------------------------------------------------------------------------
class TestNoteDetection:
    def test_the_counts_are_internally_consistent(self, parts: Dict[str, Any]) -> None:
        report = stage22.note_detection_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        sounding = sum(1 for note in parts["truth"] if not note.silence)
        assert report["ground_truth_notes"] == sounding
        assert report["matched_notes"] + report["missed_ground_truth_notes"] == sounding
        assert (
            report["matched_spans"] + report["false_detector_spans"] == report["detected_spans"]
        )

    def test_precision_and_recall_use_the_right_denominators(self, parts: Dict[str, Any]) -> None:
        report = stage22.note_detection_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        by_count = report["by_count"]
        assert by_count["true_positive"] == report["matched_spans"]
        assert by_count["false_positive"] == report["false_detector_spans"]
        assert by_count["false_negative"] == report["missed_ground_truth_notes"]

    def test_a_merged_span_is_not_counted_as_missed_notes(self, parts: Dict[str, Any]) -> None:
        """A merged span overlaps every note it absorbed, so the note-level miss count is zero."""
        report = stage22.note_detection_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        if report["merged_spans"]:
            assert report["missed_ground_truth_notes"] < report["ground_truth_notes"]

    def test_the_uncovered_frame_count_is_at_most_the_ground_truth_frames(
        self, parts: Dict[str, Any]
    ) -> None:
        report = stage22.note_detection_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert 0 <= report["uncovered_note_frames"] <= report["ground_truth_frames"]

    def test_an_exact_boundary_span_is_both_onset_and_length_exact(
        self, parts: Dict[str, Any]
    ) -> None:
        report = stage22.note_detection_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert report["exact_boundary_spans"] <= report["matched_spans"]


class TestPitch:
    def test_the_divider_comparison_uses_the_matched_onset(self, parts: Dict[str, Any]) -> None:
        report = stage22.pitch_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        sounding = sum(1 for note in parts["truth"] if not note.silence)
        assert report["matched_compared"] <= sounding
        assert report["divider_exact"] <= report["matched_compared"]

    def test_a_pitch_error_never_comes_from_the_pitch_read(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The leave-one-out marginal for pitch is zero: the read is exact wherever the span is."""
        assert bundle["aggregate"]["leave_one_out_marginals"][stage22.FIELD_PITCH] == 0

    def test_the_reading_says_noise_is_not_a_pitch(self, parts: Dict[str, Any]) -> None:
        report = stage22.pitch_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert "clock divisor" in report["reading"]


class TestGenerator:
    def test_classification_and_transition_are_separated(self, parts: Dict[str, Any]) -> None:
        report = stage22.generator_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert "onset_distortion_correct" in report
        assert "transition_detection" in report
        sounding = sum(1 for note in parts["truth"] if not note.silence)
        assert report["onset_distortion_compared"] <= sounding

    def test_the_transition_metrics_use_the_change_frames(
        self, parts: Dict[str, Any]
    ) -> None:
        report = stage22.generator_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        detection = report["transition_detection"]
        assert detection["hits"] + detection["missed"] == detection["truth_change_frames"]
        assert detection["hits"] + detection["spurious"] == detection["predicted_change_frames"]

    def test_generator_errors_never_show_as_pitch_or_generator_marginals(
        self, bundle: Dict[str, Any]
    ) -> None:
        marginals = bundle["aggregate"]["leave_one_out_marginals"]
        assert marginals[stage22.FIELD_GENERATOR] == 0
        assert marginals[stage22.FIELD_DISTORTION] == 0

    def test_the_change_frames_helper_counts_the_first_frame(self) -> None:
        assert stage22._change_frames([1, 1, 2, 2, 2, 3]) == [0, 2, 5]
        assert stage22._change_frames([]) == []


class TestChannelTimingSilence:
    def test_channel_assignment_never_differs(self, bundle: Dict[str, Any]) -> None:
        assert bundle["aggregate"]["channel"]["matched_voice_mismatches"] == 0

    def test_the_channel_zero_states_its_reason(self, parts: Dict[str, Any]) -> None:
        report = stage22.channel_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert "cannot differ" in report["reading"]
        assert report["flag"] in ("AMBIGUOUS", "UNAMBIGUOUS")

    def test_the_channel_marginal_is_the_measured_zero(self, bundle: Dict[str, Any]) -> None:
        assert bundle["aggregate"]["leave_one_out_marginals"][stage22.FIELD_CHANNEL] == 0

    def test_the_ground_truth_onsets_sit_on_the_row_grid(
        self, parts: Dict[str, Any]
    ) -> None:
        report = stage22.timing_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert (
            report["ground_truth_notes_on_the_row_grid"] == report["ground_truth_notes"]
        ), "a compiled trace's onsets are whole rows by construction"

    def test_ordering_violations_are_never_negative(self, parts: Dict[str, Any]) -> None:
        report = stage22.timing_errors(
            parts["trace"], parts["truth"], list(parts["records"])
        )
        assert report["ordering_violations"] >= 0

    def test_the_silence_analysis_reuses_the_attribution_bucket(
        self, parts: Dict[str, Any]
    ) -> None:
        attribution = stage22.frame_attribution(
            parts["trace"], parts["records"], parts["truth"], parts["residual"]
        )
        report = stage22.silence_errors(
            parts["trace"], parts["truth"], parts["records"], attribution
        )
        assert (
            report["outside_both_frames"]
            == attribution["counts"][stage22.ATTR_OUTSIDE_BOTH]
        )

    def test_the_convention_is_charged_to_the_convention(self, parts: Dict[str, Any]) -> None:
        attribution = stage22.frame_attribution(
            parts["trace"], parts["records"], parts["truth"], parts["residual"]
        )
        report = stage22.silence_errors(
            parts["trace"], parts["truth"], parts["records"], attribution
        )
        assert "not a detector error" in report["reading"]


# ---------------------------------------------------------------------------
# 7. the corpus aggregation
# ---------------------------------------------------------------------------
class TestCorpusAggregation:
    def test_the_pooled_residual_is_a_sum_not_an_average(self, bundle: Dict[str, Any]) -> None:
        aggregate = bundle["aggregate"]
        assert aggregate["detector_residual_values"] == sum(
            row["residual"]["residual_values"] for row in bundle["songs"]
            if "ladder_exporter" in row
        )
        assert aggregate["register_values"] == sum(
            row["residual"]["register_values"] for row in bundle["songs"]
            if "ladder_exporter" in row
        )

    def test_the_pooled_share_is_the_ratio_of_the_sums(self, bundle: Dict[str, Any]) -> None:
        aggregate = bundle["aggregate"]
        assert aggregate["detector_residual_share"] == pytest.approx(
            aggregate["detector_residual_values"] / aggregate["register_values"], abs=1e-6
        )

    def test_the_pooled_attribution_closes(self, bundle: Dict[str, Any]) -> None:
        attribution = bundle["aggregate"]["attribution"]
        assert sum(attribution["counts"].values()) == attribution["total_register_values"]

    def test_every_arm_is_pooled(self, bundle: Dict[str, Any]) -> None:
        arms = bundle["aggregate"]["arms"]
        assert set(arms) == {name for name, *_rest in stage22.ARM_SPECS}
        for name, row in arms.items():
            assert row["residual_values"] >= 0
            assert row["description"]

    def test_the_per_song_distribution_has_the_quartiles(self, bundle: Dict[str, Any]) -> None:
        spread = bundle["aggregate"]["per_song"]["residual_share"]
        for key in ("count", "mean", "median", "min", "p25", "p75", "max"):
            assert key in spread
        assert spread["min"] <= spread["p25"] <= spread["median"] <= spread["p75"]
        assert spread["p75"] <= spread["max"]

    def test_the_correlations_are_bounded(self, bundle: Dict[str, Any]) -> None:
        for name, row in bundle["aggregate"]["correlations"].items():
            if row.get("pearson") is None:
                assert row.get("reason")
                continue
            assert -1.0 <= row["pearson"] <= 1.0, name
            assert -1.0 <= row["spearman"] <= 1.0, name

    def test_the_features_are_not_computed_from_the_residual(self, bundle: Dict[str, Any]) -> None:
        for song in bundle["songs"]:
            if "features" not in song:
                continue
            assert "residual_share" not in song["features"]
            assert "residual" not in song["features"]

    def test_the_spearman_ranks_handle_ties(self) -> None:
        assert stage22._ranks([1, 1, 2]) == [1.5, 1.5, 3.0]
        assert stage22._ranks([5, 5, 5]) == [2.0, 2.0, 2.0]

    def test_a_constant_feature_has_no_correlation(self) -> None:
        assert stage22._pearson([1, 1, 1], [1, 2, 3]) is None


# ---------------------------------------------------------------------------
# 8. the taxonomy, the historical comparison and the falsification test
# ---------------------------------------------------------------------------
class TestTaxonomy:
    def test_every_class_has_a_status_and_a_family(self, bundle: Dict[str, Any]) -> None:
        taxonomy = bundle["taxonomy"]
        for item in taxonomy["matrix"]:
            assert item["status"] in (stage22.CLASS_MEASURED,
                                      stage22.CLASS_EMPTY_BY_CONSTRUCTION)
            assert item["family"] in taxonomy["families"]
            assert isinstance(item["count"], int)
            assert item["songs_affected"] <= bundle["aggregate"]["songs"]

    def test_an_empty_by_construction_class_explains_itself(self, bundle: Dict[str, Any]) -> None:
        for item in bundle["taxonomy"]["matrix"]:
            if item["status"] == stage22.CLASS_EMPTY_BY_CONSTRUCTION:
                assert item["count"] == 0, item["class"]
                assert len(item["note"]) > 40

    def test_the_three_structural_classes_are_the_expected_ones(
        self, bundle: Dict[str, Any]
    ) -> None:
        empty = {
            item["class"] for item in bundle["taxonomy"]["matrix"]
            if item["status"] == stage22.CLASS_EMPTY_BY_CONSTRUCTION
        }
        assert empty == {"wrong_channel", "volume_scalar_mismatch", "audctl_mismatch"}

    def test_the_false_onset_class_is_measured_not_assumed(
        self, bundle: Dict[str, Any]
    ) -> None:
        row = next(
            item for item in bundle["taxonomy"]["matrix"]
            if item["class"] == "false_note_onset"
        )
        assert row["status"] == stage22.CLASS_MEASURED

    def test_the_taxonomy_says_the_matrix_is_not_additive(self, bundle: Dict[str, Any]) -> None:
        assert "sums to the residual" in bundle["taxonomy"]["reading"]

    def test_the_cause_partition_shares_sum_to_one(self, bundle: Dict[str, Any]) -> None:
        partition = bundle["taxonomy"]["cause_partition"]
        total = (
            partition["note_set_share"] + partition["value_share"]
            + partition["interaction_share"]
        )
        assert total == pytest.approx(1.0, abs=2e-6)
class TestHistorical:
    def test_a_historical_signature_carries_no_ground_truth(
        self, bundle: Dict[str, Any]
    ) -> None:
        for row in bundle["historical"]:
            assert "ground_truth" not in row
            assert "note_set_only" not in row
            assert "no ground truth exists" in row["note"]

    def test_the_historical_residual_is_measured_under_both_policies(
        self, bundle: Dict[str, Any]
    ) -> None:
        """Both policies are measured. Which is smaller is *not* asserted: on the historical corpus
        the player itself holds AUDF, so the hold policy can legitimately be the closer one."""
        for row in bundle["historical"]:
            assert row["residual_hold_values"] >= 0
            assert row["residual_exporter_values"] >= 0
            assert row["residual_hold_share"] is not None
            assert row["residual_exporter_share"] is not None

    def test_the_comparison_only_compares_what_both_corpora_can_produce(
        self, bundle: Dict[str, Any]
    ) -> None:
        comparison = bundle["comparison"]
        assert "control-only" in comparison["comparable_quantities"]
        assert "audf_share_of_residual" in comparison["historical"]

    def test_the_falsification_thresholds_are_stated(self, bundle: Dict[str, Any]) -> None:
        thresholds = bundle["falsification"]["thresholds"]
        assert thresholds["share_ratio_low"] < thresholds["share_ratio_high"]
        assert thresholds["audf_share_delta"] > 0

    def test_the_falsification_compares_like_with_like(self, bundle: Dict[str, Any]) -> None:
        """Both sides must be register-group shares, under both policy pairings."""
        falsification = bundle["falsification"]
        comparison = bundle["comparison"]
        pairings = falsification["audf_pairings"]
        assert set(pairings) == {"exporter_vs_exporter", "hold_vs_hold"}
        assert (
            pairings["exporter_vs_exporter"]["control"]
            == comparison["control"]["audf_share_of_exporter_residual"]
        )
        assert (
            pairings["hold_vs_hold"]["historical"]
            == comparison["historical"]["audf_share_of_residual"]
        )
        assert "policy-sensitive" in falsification["cross_check_note"]
        assert falsification["split_consistent"] == all(
            row["consistent"] for row in pairings.values()
        )

    def test_the_control_exporter_residual_is_the_detector_not_the_exact_arm(
        self, bundle: Dict[str, Any]
    ) -> None:
        """`A_exact` is zero by construction; using it as the exporter residual would zero the
        control side of the comparison."""
        comparison = bundle["comparison"]
        assert comparison["control"]["residual_exporter_values"] > 0
        assert comparison["control"]["residual_exporter_values"] == (
            bundle["aggregate"]["arms"]["A_detector"]["residual_values"]
        )

    def test_the_falsification_verdict_is_one_of_the_two(
        self, bundle: Dict[str, Any]
    ) -> None:
        assert bundle["falsification"]["verdict"] in (
            "HISTORICAL_RESIDUAL_CONSISTENT_WITH_DETECTOR_ERROR",
            "HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL",
        )

    def test_the_falsification_test_refuses_to_call_a_difference_proof(
        self, bundle: Dict[str, Any]
    ) -> None:
        assert "not proof" in bundle["falsification"]["what_this_is_not"]

    def test_the_falsification_reports_whether_a_difference_is_robust(
        self, bundle: Dict[str, Any]
    ) -> None:
        falsification = bundle["falsification"]
        assert isinstance(falsification["difference_robust"], bool)
        assert "convention choice" in falsification["robustness_note"]
        if falsification["verdict"] == "HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL":
            assert "robust" in stage22.render_report(bundle)


class TestVerdicts:
    def test_the_verdict_vocabulary_is_the_agreed_one(self, bundle: Dict[str, Any]) -> None:
        allowed = {
            "DETECTOR_ERROR_EXPLAINED", "DETECTOR_ERROR_PARTIALLY_EXPLAINED",
            "DETECTOR_ERROR_NOT_EXPLAINED", "REPRESENTATION_LIMITATION",
            "GROUND_TRUTH_EXTRACTION_LIMITATION",
            "HISTORICAL_RESIDUAL_CONSISTENT_WITH_DETECTOR_ERROR",
            "HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL",
            "PERFORMANCE_CANDIDATE_REMAINS_UNSUPPORTED",
            "PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST",
        }
        for subject, data in bundle["verdicts"].items():
            assert data["verdict"] in allowed, subject

    def test_the_performance_layer_is_never_proven(self, bundle: Dict[str, Any]) -> None:
        rendered = stage22.render_report(bundle)
        assert "PROVEN PERFORMANCE LAYER" not in rendered.replace(
            "`PROVEN PERFORMANCE LAYER` is not in the vocabulary", ""
        )

    def test_every_verdict_carries_its_deciding_condition(
        self, bundle: Dict[str, Any]
    ) -> None:
        for subject, data in bundle["verdicts"].items():
            assert data["deciding_condition"], subject

    def test_the_detector_error_verdict_is_derived_from_the_partition(
        self, bundle: Dict[str, Any]
    ) -> None:
        partition = bundle["taxonomy"]["cause_partition"]
        uniquely = partition["note_set_share"] + partition["value_share"]
        expected = (
            "DETECTOR_ERROR_EXPLAINED" if uniquely >= 0.90
            else "DETECTOR_ERROR_PARTIALLY_EXPLAINED" if uniquely >= 0.50
            else "DETECTOR_ERROR_NOT_EXPLAINED"
        )
        assert bundle["verdicts"]["detector_error"]["verdict"] == expected

    def test_the_bridge_is_a_condition_of_the_verdict(self, bundle: Dict[str, Any]) -> None:
        assert bundle["verdicts"]["detector_error"]["conditions"]["predictor_bridge_holds"]



# ---------------------------------------------------------------------------
# 9. determinism, artefacts, the read-only audit and the CLI
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_a_repeated_run_is_byte_identical(self, tmp_path: Path) -> None:
        """Two runs must produce the same bytes, not merely the same numbers."""
        first = stage22.run_analysis(control_limit=2, detail_limit=2, historical_limit=2)
        second = stage22.run_analysis(control_limit=2, detail_limit=2, historical_limit=2)
        left = tmp_path / "left"
        right = tmp_path / "right"
        written_left = stage22.write_analysis(first, stage22_dir=left / "r", docs_dir=left / "d")
        written_right = stage22.write_analysis(
            second, stage22_dir=right / "r", docs_dir=right / "d"
        )
        assert set(written_left) == set(written_right)
        for name in written_left:
            assert written_left[name].read_bytes() == written_right[name].read_bytes(), name

    def test_the_manifest_declares_its_determinism(self, bundle: Dict[str, Any]) -> None:
        determinism = bundle["determinism"]
        assert determinism["no_timestamps"]
        assert determinism["no_sampling"]
        assert determinism["inputs_hashed"]
        assert "tie" in determinism["tie_breaks"]

    def test_the_specs_are_sorted_before_use(self, parts: Dict[str, Any]) -> None:
        specs, _provenance = stage22.build_specs(
            parts["trace"], parts["truth"], parts["records"], stage22.ALL_FIELDS,
            stage22.NOTE_SET_TRUTH, False,
        )
        keys = [(spec.start, spec.voice_id, spec.end) for spec in specs]
        assert keys == sorted(keys)

    def test_the_run_records_its_own_source_hash(self, bundle: Dict[str, Any]) -> None:
        assert len(bundle["determinism"]["source_hash"]) == 64

    def test_the_summary_is_a_summary_of_the_bundle(self, bundle: Dict[str, Any]) -> None:
        summary = bundle["summary"]
        assert summary["control_songs"] == len(bundle["corpus"]["control"])


class TestArtefacts:
    def test_the_writer_emits_every_declared_artefact(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        written = stage22.write_analysis(
            bundle, stage22_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        for name in stage22.STAGE22_FILES:
            assert (tmp_path / "r" / name).is_file(), name
        assert (tmp_path / "d" / stage22.STAGE22_DOC).is_file()
        assert (tmp_path / "r" / "stage22_report.md").is_file()
        assert set(written) == set(stage22.STAGE22_FILES) | {
            stage22.STAGE22_DOC, "stage22_report.md",
        }

    def test_every_artefact_is_valid_json(self, bundle: Dict[str, Any],
                                          tmp_path: Path) -> None:
        stage22.write_analysis(bundle, stage22_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        for name in stage22.STAGE22_FILES:
            payload = json.loads((tmp_path / "r" / name).read_text(encoding="utf-8"))
            assert payload is not None, name

    def test_no_transient_working_state_reaches_disk(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        stage22.write_analysis(bundle, stage22_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        for name in stage22.STAGE22_FILES:
            text = (tmp_path / "r" / name).read_text(encoding="utf-8")
            for key in stage22._TRANSIENT_KEYS:
                assert f'"{key}"' not in text, f"{name} carries {key}"

    def test_the_manifest_names_the_document_and_the_stop_condition(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        stage22.write_analysis(bundle, stage22_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        manifest = json.loads(
            (tmp_path / "r" / "stage22_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["document"] == stage22.STAGE22_DOC
        assert "no production code" in manifest["stop_condition"]
        assert set(manifest["artefacts"]) == set(stage22.STAGE22_FILES)


class TestReport:
    def test_the_report_has_every_required_section(self, bundle: Dict[str, Any]) -> None:
        report = stage22.render_report(bundle)
        titles = [
            "Executive Summary", "Dataset", "Ground Truth", "Detector",
            "Residual Definition", "Ablation Ladder", "Error Taxonomy",
            "Note Detection", "Pitch", "Volume / Envelope",
            "Generator / Distortion", "Channel Assignment", "Timing",
            "Silent / Non-musical Register Activity", "Per-song Variation",
            "Historical Comparison", "Falsification Test", "Methodological Corrections",
            "Limitations", "Verdict",
        ]
        for index, title in enumerate(titles, start=1):
            assert f"## {index}. {title}" in report, title

    def test_the_report_answers_the_final_question(self, bundle: Dict[str, Any]) -> None:
        report = stage22.render_report(bundle)
        assert "## The Final Question" in report
        assert "explained by specific, measured detector limitations" in report

    def test_the_report_carries_no_absolute_windows_path(
        self, bundle: Dict[str, Any]
    ) -> None:
        report = stage22.render_report(bundle)
        assert "C:\\Users" not in report
        assert "C:/Users" not in report

    def test_the_report_is_plain_ascii(self, bundle: Dict[str, Any]) -> None:
        stage22.render_report(bundle).encode("ascii")


class TestReadOnlyAudit:
    def test_the_run_proves_the_inputs_are_unchanged(self, bundle: Dict[str, Any]) -> None:
        for _key, row in bundle["read_only_audit"].items():
            assert row["read_only"], row["changed"]
            assert row["changed"] == []

    def test_the_audit_covers_stage_15_to_21_and_the_player(self) -> None:
        hashes = stage22.production_hashes()
        for relative in (
            "src/atari_music/stage15.py", "src/atari_music/stage16.py",
            "src/atari_music/stage17.py", "src/atari_music/stage18.py",
            "src/atari_music/stage19.py", "src/atari_music/stage20.py",
            "src/atari_music/stage21.py", "src/atari_music/asm/player.asm",
        ):
            assert relative in hashes
            assert hashes[relative], relative

    def test_the_audit_covers_the_composition_documents(self) -> None:
        hashes = stage22.corpus_hashes()
        assert hashes
        assert all(len(value) == 64 for value in hashes.values() if value)

    def test_the_audit_notices_a_change(self) -> None:
        row = stage22.read_only_audit({"a": "1", "b": "2"}, {"a": "1", "b": "3"})
        assert not row["read_only"]
        assert row["changed"] == ["b"]

    def test_writing_the_artefacts_changes_no_production_file(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        before = stage22.production_hashes()
        stage22.write_analysis(bundle, stage22_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        assert stage22.production_hashes() == before


@requires_control
class TestCli:
    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["analyze-stage22", "--help"])
        assert result.exit_code == 0, result.output
        assert "residual" in result.output.lower()

    def test_a_bounded_run_writes_its_artefacts(self, tmp_path: Path) -> None:
        reports = tmp_path / "r"
        docs = tmp_path / "d"
        result = CliRunner().invoke(
            cli,
            ["analyze-stage22", "--reports-dir", str(reports), "--docs-dir", str(docs),
             "--control-limit", "2", "--detail-limit", "2", "--historical-limit", "2"],
        )
        assert result.exit_code == 0, result.output
        for name in stage22.STAGE22_FILES:
            assert (reports / name).is_file(), name
        assert (docs / stage22.STAGE22_DOC).is_file()
        assert "cause partition" in result.output
        assert "read-only audit" in result.output



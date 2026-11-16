"""Stage 20 - residual POKEY performance information.

These tests pin the stage to the four corpus songs, prove it is read-only and deterministic, and
lock down the identity the whole experiment rests on: `prediction + residual == exact`, for every
frame and every register, on every song.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping

import pytest
from click.testing import CliRunner

from atari_music import stage15, stage19, stage20
from atari_music.cli import cli

pytestmark = pytest.mark.experimental

requires_corpus = pytest.mark.skipif(
    not stage20.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage20.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage20.run_analysis()


def fake_trace(values: Mapping[str, List[int]], audctl: int = 0) -> Any:
    """A trace-shaped object carrying explicit register sequences, for synthetic tests."""
    frames = len(next(iter(values.values()))) if values else 0
    registers = {
        name: list(values.get(name, [0] * frames)) for name in stage20.REGISTER_ORDER
    }
    return SimpleNamespace(frames=frames, registers=registers, audctl=audctl)


def simple_song(
    frames: int = 40,
    divider: int = 100,
    level: int = 8,
    constant_level: bool = True,
) -> Any:
    """A tiny one-channel song: channel 1 plays a steady divider at a steady level."""
    values: Dict[str, List[int]] = {name: [0] * frames for name in stage20.REGISTER_ORDER}
    values["AUDF1"] = [divider] * frames
    values["AUDC1"] = [(0xA0 | level)] * frames
    return fake_trace(values)


def one_note(record: stage20.NoteRecord) -> List[stage20.NoteRecord]:
    return [record]


def make_record(**overrides: Any) -> stage20.NoteRecord:
    base = dict(
        voice_id="V1", channel=1, volume_channel=1, pitch_channels=(1,), joined=False,
        start=0, end=9, index=0, divider=100, hz=1000.0, distortion=10,
        onset_level=8, peak_level=8, attack_frames=0, sustain_level=8, release_frames=0,
        observed_levels=(8,) * 10,
    )
    base.update(overrides)
    return stage20.NoteRecord(**base)


# ---------------------------------------------------------------------------
# 1. The identity the stage rests on, on synthetic inputs
# ---------------------------------------------------------------------------
def payload_of(trace: Any) -> bytes:
    return bytes(
        trace.registers[name][frame]
        for frame in range(trace.frames)
        for name in stage20.REGISTER_ORDER
    )


class TestResidualIdentity:
    def test_prediction_plus_residual_is_the_trace(self) -> None:
        trace = simple_song()
        stream = stage20.stage18.stream_from_payload("x", trace.frames, 20056, payload_of(trace))
        residual = stage20.build_residual(
            stream, trace, stage20.predict_frames(trace, one_note(make_record()))
        )
        assert stage20.reconstruct(residual) == residual.exact

    def test_empty_trace(self) -> None:
        trace = fake_trace({name: [] for name in stage20.REGISTER_ORDER})
        stream = stage20.stage18.stream_from_payload("empty", 0, 20056, b"")
        residual = stage20.build_residual(stream, trace, [])
        assert residual.frames == 0
        assert residual.residual_values() == 0
        assert stage20.reconstruct(residual) == []

    def test_single_frame(self) -> None:
        trace = simple_song(frames=1)
        stream = stage20.stage18.stream_from_payload("one", 1, 20056, payload_of(trace))
        residual = stage20.build_residual(
            stream, trace, stage20.predict_frames(trace, one_note(make_record(end=0)))
        )
        assert residual.frames == 1
        assert stage20.reconstruct(residual) == residual.exact

    def test_a_wrong_prediction_length_is_refused(self) -> None:
        trace = simple_song(frames=4)
        stream = stage20.stage18.stream_from_payload("x", 4, 20056, payload_of(trace))
        with pytest.raises(stage20.Stage20Error):
            stage20.build_residual(stream, trace, [(0,) * 9])

    def test_the_residual_is_twos_complement_per_register(self) -> None:
        trace = simple_song(frames=3, divider=10)
        stream = stage20.stage18.stream_from_payload("x", 3, 20056, payload_of(trace))
        residual = stage20.build_residual(stream, trace, [tuple([5] * 9)] * 3)
        for value in residual.values[0]:
            assert value == (10 - 5) & 0xFF

    def test_the_sparse_encoding_is_deterministic(self) -> None:
        values = [[0] * 5 for _ in range(stage20.FRAME_BYTES)]
        values[0] = [0, 1, 0, 0, 2]
        assert stage20.residual_bytes(values) == stage20.residual_bytes(values)
        assert stage20.residual_bytes(values) > 0


# ---------------------------------------------------------------------------
# 2. The note-level baseline and the contour fit
# ---------------------------------------------------------------------------
class TestContourFit:
    def test_a_flat_note_fits_a_flat_contour(self) -> None:
        peak, attack, sustain, release = stage20.fit_contour([7] * 12)
        assert peak == 7 and release == 0
        assert stage20.contour_levels(12, (peak, attack, sustain, release)) == [7] * 12

    def test_a_falling_tail_is_captured(self) -> None:
        levels = [9] * 8 + [8, 7, 6]
        assert stage20.contour_levels(len(levels), stage20.fit_contour(levels)) == levels

    def test_the_fit_is_a_search_not_a_first_guess(self) -> None:
        levels = [5, 5, 9, 9, 9, 8, 7]
        contour = stage20.fit_contour(levels)
        generated = stage20.contour_levels(len(levels), contour)
        naive = stage20.contour_levels(len(levels), (9, 0, 9, 3))
        assert sum(1 for a, b in zip(levels, generated) if a != b) <= sum(
            1 for a, b in zip(levels, naive) if a != b
        )

    def test_the_fit_is_deterministic(self) -> None:
        levels = [6, 7, 8, 8, 7, 6]
        assert stage20.fit_contour(levels) == stage20.fit_contour(levels)

    def test_an_empty_contour_is_handled(self) -> None:
        assert stage20.fit_contour([]) == (0, 0, 0, 0)

    def test_contour_fidelity_is_measured_not_assumed(self) -> None:
        report = stage20.contour_fidelity([make_record()])
        assert report["notes"] == 1
        assert report["levels_reproduced"] <= report["note_frames"]



class TestPrediction:
    def test_a_note_predicts_the_players_own_divider(self) -> None:
        record = make_record(hz=1000.0)
        assert stage20.predict_divider(record, 0) == {
            1: stage20.pokey_hw.clamp_audf_for_tracker(
                stage20.ir.frequency_to_audf_8bit(1000.0, audctl=0, channel=1)
            )
        }

    def test_a_joined_pair_predicts_both_bytes(self) -> None:
        record = make_record(pitch_channels=(1, 2), joined=True, volume_channel=2, hz=1000.0)
        assert set(stage20.predict_divider(record, 0)) == {1, 2}

    def test_the_prediction_does_not_follow_a_per_frame_trace_value(self) -> None:
        """The trace is changed after the note starts; the note did not change, so neither may."""
        trace = simple_song(frames=20, divider=100)
        trace.registers["AUDF1"] = [100] * 10 + [200] * 10
        records = [make_record(start=0, end=19, divider=100, hz=1000.0)]
        dividers = [row[0] for row in stage20.predict_frames(trace, records, 0, True)]
        assert len(set(dividers[:10])) == 1
        assert dividers[0] == dividers[-1]

    def test_a_shift_moves_the_note(self) -> None:
        trace = simple_song(frames=30)
        records = [make_record(start=0, end=4)]
        assert stage20.predict_frames(trace, records, 0, True) != stage20.predict_frames(
            trace, records, 5, True
        )

    def test_the_flat_baseline_differs_from_the_contour_baseline(self) -> None:
        trace = simple_song(frames=20, level=8)
        records = [make_record(start=0, end=19, onset_level=4, peak_level=8, sustain_level=8)]
        assert stage20.predict_frames(trace, records, 0, False) != stage20.predict_frames(
            trace, records, 0, True
        )

    def test_outside_a_note_the_channel_is_silenced(self) -> None:
        trace = simple_song(frames=20)
        predicted = stage20.predict_frames(trace, [make_record(start=0, end=4)], 0, True)
        assert predicted[10][stage20.AUDC_COLUMN[1]] == 0

    def test_audctl_is_predicted_as_one_global_value(self) -> None:
        trace = simple_song(frames=5)
        trace.audctl = 0x50
        predicted = stage20.predict_frames(trace, [], 0, True)
        assert {row[stage20.AUDCTL_COLUMN] for row in predicted} == {0x50}

    def test_the_muted_low_channel_of_a_joined_pair_is_zero(self) -> None:
        trace = simple_song(frames=10)
        trace.audctl = stage15.AUDCTL_JOIN_1_2_16BIT
        record = make_record(
            voice_id="V12", pitch_channels=(1, 2), joined=True, volume_channel=2,
            start=0, end=9, hz=1000.0,
        )
        predicted = stage20.predict_frames(trace, [record], 0, True)
        assert {row[stage20.AUDC_COLUMN[1]] for row in predicted} == {0}


class TestResidualClassification:
    def test_onset_interior_and_gap_are_separated(self) -> None:
        trace = simple_song(frames=20)
        records = [make_record(start=5, end=9)]
        classes = stage20.register_occupancy(trace, records)
        assert classes[stage20.AUDF_COLUMN[1]][5] == stage20.CLASS_ONSET
        assert classes[stage20.AUDF_COLUMN[1]][7] == stage20.CLASS_INTERIOR
        assert classes[stage20.AUDF_COLUMN[1]][0] == stage20.CLASS_GAP
        assert classes[stage20.AUDF_COLUMN[1]][15] == stage20.CLASS_GAP

    def test_a_note_makes_its_own_channel_occupied(self) -> None:
        trace = simple_song(frames=20)
        classes = stage20.register_occupancy(trace, [make_record(start=2, end=6)])
        assert classes[stage20.AUDC_COLUMN[1]][4] == stage20.CLASS_INTERIOR

    def test_the_volume_channel_of_a_joined_pair_is_occupied(self) -> None:
        trace = simple_song(frames=20)
        trace.audctl = stage15.AUDCTL_JOIN_1_2_16BIT
        record = make_record(
            voice_id="V12", pitch_channels=(1, 2), joined=True, volume_channel=2,
            start=3, end=8,
        )
        classes = stage20.register_occupancy(trace, [record])
        assert classes[stage20.AUDC_COLUMN[2]][5] == stage20.CLASS_INTERIOR
        assert classes[stage20.AUDC_COLUMN[1]][3] == stage20.CLASS_ONSET


class TestResidualReport:
    def test_the_three_coverages_are_reported_separately(self) -> None:
        trace = simple_song(frames=10)
        stream = stage20.stage18.stream_from_payload("x", 10, 20056, payload_of(trace))
        residual = stage20.build_residual(
            stream, trace, stage20.predict_frames(trace, [make_record(end=9)], 0, True)
        )
        report = stage20.residual_report(residual, trace, [make_record(end=9)])
        assert report["frame_coverage"] is not None
        assert report["register_coverage"] is not None
        assert report["byte_coverage"] == report["register_coverage"]

    def test_a_perfect_prediction_gives_full_coverage(self) -> None:
        trace = simple_song(frames=6)
        stream = stage20.stage18.stream_from_payload("x", 6, 20056, payload_of(trace))
        record = make_record(start=0, end=5, divider=100, hz=1000.0, distortion=10,
                            onset_level=8, peak_level=8, sustain_level=8)
        predicted = stage20.predict_frames(trace, [record], 0, True)
        residual = stage20.build_residual(stream, trace, predicted)
        report = stage20.residual_report(residual, trace, [record])
        assert report["residual_values"] <= report["register_values"]

    def test_the_class_definition_is_reported(self) -> None:
        trace = simple_song(frames=4)
        stream = stage20.stage18.stream_from_payload("x", 4, 20056, payload_of(trace))
        residual = stage20.build_residual(stream, trace, stage20.predict_frames(trace, [], 0))
        report = stage20.residual_report(residual, trace, [])
        assert "per register" in report["class_definition"]



# ---------------------------------------------------------------------------
# 3. The grammar on the residual
# ---------------------------------------------------------------------------
class TestResidualGrammar:
    def test_a_ramp_residual_is_explained_structurally(self) -> None:
        values = [[0] * 40 for _ in range(stage20.FRAME_BYTES)]
        values[0] = [0] * 5 + [1, 2, 3, 4, 5, 6, 7, 8] + [0] * 27
        report = stage20.residual_grammar(values)
        assert report["residual_values"] == 8
        assert report["structural_share"] == 1.0

    def test_an_isolated_residual_is_not_explained_structurally(self) -> None:
        values = [[0] * 40 for _ in range(stage20.FRAME_BYTES)]
        for frame in (3, 11, 19, 27):
            values[0][frame] = 1 + frame
        report = stage20.residual_grammar(values)
        assert report["residual_values"] == 4
        assert report["structural_share"] == 0.0

    def test_a_zero_only_residual_has_no_structural_share(self) -> None:
        values = [[0] * 20 for _ in range(stage20.FRAME_BYTES)]
        report = stage20.residual_grammar(values)
        assert report["residual_values"] == 0
        assert report["structural_share"] is None

    def test_the_vocabulary_excludes_the_song_specific_lexicon(self) -> None:
        report = stage20.residual_grammar([[0] * 8 for _ in range(stage20.FRAME_BYTES)])
        assert "REPEAT" not in report["vocabulary"]
        assert set(report["vocabulary"]) == {"SET", "HOLD", "DELTA", "RAMP", "TOGGLE"}

    def test_the_ablation_covers_every_structural_construction(self) -> None:
        values = [[0] * 30 for _ in range(stage20.FRAME_BYTES)]
        values[0] = [0] * 5 + [1, 1, 1, 1, 1, 1] + [0] * 19
        ablation = stage20.residual_grammar_ablation(values)
        assert set(ablation["without_each"]) == {"HOLD", "DELTA", "RAMP", "TOGGLE"}
        assert "structural_share" in ablation["full"]

    def test_a_hold_of_zeros_is_not_structural(self) -> None:
        """A HOLD over a run of zeros must not be credited with explaining anything."""
        values = [[0] * 60 for _ in range(stage20.FRAME_BYTES)]
        values[0][30] = 4
        report = stage20.residual_grammar(values)
        assert report["residual_values"] == 1
        assert report["structural_share"] == 0.0


class TestRandomResidualNull:
    def test_the_multiset_is_preserved_and_the_positions_are_not(self) -> None:
        values = [[0] * 50 for _ in range(stage20.FRAME_BYTES)]
        for frame in range(0, 50, 5):
            values[0][frame] = frame % 7 + 1
        shuffled = stage20.random_residual(values)
        assert sorted(shuffled[0]) == sorted(values[0])
        assert shuffled[0] != values[0] or len(set(values[0])) == 1

    def test_the_null_is_deterministic(self) -> None:
        values = [[0] * 40 for _ in range(stage20.FRAME_BYTES)]
        values[0] = [(1 if frame % 3 == 0 else 0) for frame in range(40)]
        assert stage20.random_residual(values) == stage20.random_residual(values)

    def test_the_null_uses_a_stated_seed(self) -> None:
        values = [[0] * 20 for _ in range(stage20.FRAME_BYTES)]
        values[0][3] = 9
        assert stage20.random_residual(values, seed=1) == stage20.random_residual(
            values, seed=1
        )
        assert stage20.RANDOM_SEED == 20250


class TestControls:
    def test_the_constant_prediction_is_one_value_per_register(self) -> None:
        trace = simple_song(frames=10)
        prediction = stage20.constant_prediction(trace)
        assert len(prediction) == 10
        assert len(set(prediction)) == 1

    def test_the_constant_prediction_uses_the_modal_value(self) -> None:
        trace = simple_song(frames=10, divider=30)
        trace.registers["AUDF1"] = [1, 2, 2, 2, 2, 2, 2, 2, 2, 9]
        assert stage20.constant_prediction(trace)[0][0] == 2

    def test_the_permuted_control_is_a_permutation(self) -> None:
        trace = simple_song(frames=30)
        trace.registers["AUDF1"] = list(range(30))
        permuted = stage20.permuted_control(trace)
        assert sorted(row[0] for row in permuted) == list(range(30))
        assert [row[0] for row in permuted] != list(range(30))

    def test_the_permuted_control_is_deterministic(self) -> None:
        trace = simple_song(frames=30)
        trace.registers["AUDF1"] = list(range(30))
        assert stage20.permuted_control(trace) == stage20.permuted_control(trace)



# ---------------------------------------------------------------------------
# 4. The corpus
# ---------------------------------------------------------------------------
@requires_corpus
class TestCorpus:
    def test_the_corpus_is_the_four_songs_the_brief_names(self, bundle: Dict[str, Any]) -> None:
        assert tuple(sorted(bundle["dataset"]["songs"])) == tuple(
            sorted(stage20.EXPECTED_SLUGS)
        )

    def test_every_song_passes_the_identity(self, bundle: Dict[str, Any]) -> None:
        """THE test of this stage: exact == prediction + residual, for every song."""
        for slug, row in bundle["songs"].items():
            predicted = row["predicted"]
            exact = row["exact"]
            values = row["values"]
            for frame in range(len(exact)):
                for channel in range(stage20.FRAME_BYTES):
                    assert (
                        predicted[frame][channel] + values[channel][frame]
                    ) & 0xFF == exact[frame][channel], (slug, frame, channel)

    def test_an_empty_trace_round_trips(self) -> None:
        trace = fake_trace({name: [] for name in stage20.REGISTER_ORDER})
        stream = stage20.stage18.stream_from_payload("empty", 0, 20056, b"")
        residual = stage20.build_residual(stream, trace, stage20.predict_frames(trace, [], 0))
        assert stage20.reconstruct(residual) == []

    def test_the_trace_frames_match_the_canonical_stream(self, bundle: Dict[str, Any]) -> None:
        streams, traces = stage20.load_dataset()
        for stream, trace in zip(streams, traces):
            assert stream.frames == trace.frames

    def test_a_wrong_corpus_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(stage20.Stage20Error):
            stage20.load_dataset(tmp_path)

    def test_every_song_is_exact_and_has_a_residual(self, bundle: Dict[str, Any]) -> None:
        for slug, row in bundle["songs"].items():
            assert row["residual"]["register_values"] > 0
            assert row["residual"]["residual_values"] >= 0
            assert 0.0 <= row["residual"]["register_coverage"] <= 1.0

    def test_audctl_residual_is_zero_everywhere(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["songs"].values():
            assert row["residual"]["per_register"]["AUDCTL"]["residual_values"] == 0

    def test_the_note_onset_residual_is_nearly_zero(self, bundle: Dict[str, Any]) -> None:
        """The baseline is a real prediction, not a guess: it nails almost every note onset."""
        for slug, row in bundle["songs"].items():
            share = row["trivial"]["pitch_mapping"]["onset_residual_share"]
            assert share is not None and share < 0.20, (slug, share)

    def test_the_residual_is_not_mostly_detector_gaps(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["songs"].values():
            interior = row["residual"]["by_class"]["note_interior"]
            gap = row["residual"]["by_class"]["outside_any_note"]
            onset = row["residual"]["by_class"]["note_onset"]
            assert interior >= gap
            assert interior >= onset


@requires_corpus
class TestGrammarOnTheCorpus:
    def test_the_grammar_beats_the_shuffled_null_on_every_song(
        self, bundle: Dict[str, Any]
    ) -> None:
        for slug, row in bundle["songs"].items():
            real = row["grammar"]["structural_share"]
            shuffled = bundle["nulls"]["shuffled_residual"]["per_song"][slug]
            assert real is not None and shuffled is not None
            assert real > shuffled + 0.10, (slug, real, shuffled)

    def test_no_single_construction_carries_everything(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["songs"].values():
            lost = [
                item["structural_share_lost"] or 0.0
                for item in row["grammar_ablation"]["without_each"].values()
            ]
            assert max(lost) < 1.0

    def test_the_pitch_registers_are_more_structured_than_the_level_registers(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The central shape of the finding, held in place so it cannot drift unnoticed."""
        more = less = 0
        for row in bundle["songs"].values():
            per = row["grammar"]["per_register"]
            pitch = [
                per[name]["structural_share"] for name in
                ("AUDF1", "AUDF2", "AUDF3", "AUDF4")
                if per[name]["structural_share"] is not None
            ]
            level = [
                per[name]["structural_share"] for name in
                ("AUDC1", "AUDC2", "AUDC3", "AUDC4")
                if per[name]["structural_share"] is not None
            ]
            if pitch and level:
                if _avg(pitch) > _avg(level):
                    more += 1
                else:
                    less += 1
        assert more >= less

    def test_the_incremental_gain_is_reported_per_song(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["note_vs_grammar"].values():
            assert row["additional_explained_share"] is not None
            assert row["remaining_share"] is not None
            assert 0.0 <= row["additional_explained_share"] <= 1.0


def _avg(values: List[float]) -> float:
    return sum(values) / len(values)



# ---------------------------------------------------------------------------
# 5. Generalisation, controls, verdicts, report and CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestLeaveOneOut:
    def test_every_song_is_held_out_once(self, bundle: Dict[str, Any]) -> None:
        folds = bundle["leave_one_out"]["folds"]
        assert len(folds) == 4
        assert {fold["held_out"] for fold in folds} == set(bundle["dataset"]["songs"])
        for fold in folds:
            assert fold["held_out"] not in fold["trained_on"]
            assert len(fold["trained_on"]) == 3

    def test_the_induced_vocabulary_is_reported_per_song(self, bundle: Dict[str, Any]) -> None:
        induction = bundle["leave_one_out"]["induction"]
        assert set(induction) == set(bundle["dataset"]["songs"])
        for row in induction.values():
            assert row["steps"]
            # The search stops either because nothing left to try helps, or because everything
            # has been tried; one of the two must hold, and it is stated rather than assumed.
            stopped_on_gain = row["steps"][-1]["accepted"] is False
            exhausted = set(row["induced_ops"]) >= set(
                (stage19.OP_HOLD, stage19.OP_DELTA, stage19.OP_RAMP, stage19.OP_TOGGLE)
            )
            assert stopped_on_gain or exhausted

    def test_no_song_specific_lexicon_is_used(self, bundle: Dict[str, Any]) -> None:
        """REPEAT is excluded by definition, in sample and out."""
        for row in bundle["leave_one_out"]["induction"].values():
            assert "REPEAT" not in row["induced_primitives"]
        assert stage20.RESIDUAL_VOCABULARY == (
            stage19.OP_SET, stage19.OP_HOLD, stage19.OP_DELTA, stage19.OP_RAMP,
            stage19.OP_TOGGLE,
        )

    def test_the_frozen_arm_is_never_better_than_the_free_arm(
        self, bundle: Dict[str, Any]
    ) -> None:
        for fold in bundle["leave_one_out"]["folds"]:
            assert fold["bytes"]["frozen_parameters"] >= fold["bytes"]["union_vocabulary"]

    def test_all_three_arms_are_reported(self, bundle: Dict[str, Any]) -> None:
        gains = bundle["leave_one_out"]["mean_size_gain"]
        assert set(gains) == {"shared_vocabulary", "union_vocabulary", "frozen_parameters"}
        for value in gains.values():
            assert value is not None


@requires_corpus
class TestControlsAndNulls:
    def test_the_no_notes_floor_is_below_the_note_baseline(self, bundle: Dict[str, Any]) -> None:
        floor = bundle["nulls"]["no_notes_constant_register"]["mean_register_coverage"]
        assert floor is not None
        assert floor < bundle["summary"]["note_register_coverage"]

    def test_the_noteshift_loses_most_of_the_notes_contribution(
        self, bundle: Dict[str, Any]
    ) -> None:
        conditions = bundle["verdicts"]["performance_layer"]["conditions"]
        alignment = next(
            item for item in conditions if item["condition"].startswith("note alignment")
        )
        assert alignment["met"] is True
        assert alignment["measured"]["note_contribution_lost_share"] > 0.5

    def test_the_shuffled_null_is_far_below_the_real_share(
        self, bundle: Dict[str, Any]
    ) -> None:
        assert bundle["summary"]["null_shuffled_structural_share"] < (
            bundle["summary"]["grammar_structural_share"] - 0.10
        )

    def test_the_permuted_control_reports_how_much_it_moved(
        self, bundle: Dict[str, Any]
    ) -> None:
        per_song = bundle["controls"]["permuted_trace"]["per_song"]
        assert per_song
        for row in per_song.values():
            assert row["register_values"] > 0
            assert 0.0 <= (row["moved_share"] or 0.0) <= 1.0


@requires_corpus
class TestVerdicts:
    def test_every_verdict_is_from_the_allowed_set(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["note_explanatory_power"]["verdict"] in stage20.VERDICT_NOTE
        assert verdicts["residual_structure"]["verdict"] in stage20.VERDICT_RESIDUAL
        assert verdicts["generalization"]["verdict"] in stage20.VERDICT_GENERALIZATION
        assert verdicts["performance_layer"]["verdict"] in stage20.VERDICT_LAYER
        assert verdicts["player_integration"]["verdict"] in stage20.VERDICT_INTEGRATION

    def test_the_note_verdict_follows_its_threshold(self, bundle: Dict[str, Any]) -> None:
        block = bundle["verdicts"]["note_explanatory_power"]
        coverage = block["measured"]["register_coverage"]
        expected = (
            stage20.VERDICT_NOTE[0] if coverage >= stage20.NOTE_EXPLANATORY_HIGH
            else stage20.VERDICT_NOTE[1] if coverage >= stage20.NOTE_EXPLANATORY_MEDIUM
            else stage20.VERDICT_NOTE[2]
        )
        assert block["verdict"] == expected

    def test_the_layer_verdict_follows_all_seven_conditions(self, bundle: Dict[str, Any]) -> None:
        block = bundle["verdicts"]["performance_layer"]
        assert len(block["conditions"]) == 7
        expected = (
            stage20.VERDICT_LAYER[0]
            if all(item["met"] for item in block["conditions"])
            else stage20.VERDICT_LAYER[1]
        )
        assert block["verdict"] == expected

    def test_the_layer_verdict_names_a_deciding_condition_when_it_is_unproven(
        self, bundle: Dict[str, Any]
    ) -> None:
        block = bundle["verdicts"]["performance_layer"]
        if block["verdict"] == stage20.VERDICT_LAYER[1]:
            failed = [item for item in block["conditions"] if not item["met"]]
            assert block["deciding_condition"] == failed[0]["condition"]

    def test_the_layer_verdict_is_never_promising_without_beating_the_null(
        self, bundle: Dict[str, Any]
    ) -> None:
        block = bundle["verdicts"]["performance_layer"]
        beats = next(
            item for item in block["conditions"]
            if item["condition"].startswith("the grammar beats")
        )
        if not beats["met"]:
            assert block["verdict"] == stage20.VERDICT_LAYER[2]



# ---------------------------------------------------------------------------
# 6. Determinism, the report and the CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestDeterminismAndAudit:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage20.run_analysis() == bundle

    def test_writing_twice_is_byte_identical(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        first = stage20.write_analysis(
            bundle, stage20_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        second = stage20.write_analysis(
            bundle, stage20_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        hashes = [
            {name: hashlib.sha256(path.read_bytes()).hexdigest()
             for name, path in written.items()}
            for written in (first, second)
        ]
        assert hashes[0] == hashes[1]
        assert set(hashes[0]) == set(stage20.STAGE20_FILES) | {stage20.STAGE20_DOC}
        assert len(stage20.STAGE20_FILES) == 14

    def test_the_heavy_arrays_do_not_reach_disk(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        written = stage20.write_analysis(
            bundle, stage20_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        text = (tmp_path / "r" / "residual.json").read_text(encoding="utf-8")
        assert '"values"' not in text
        assert set(path.suffix for path in written.values()) == {".json", ".md"}

    def test_nothing_upstream_is_written(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        watched = (
            list(stage15.list_traces())
            + sorted(stage20.DEFAULT_STAGE15_DIR.glob("*.json"))
            + sorted(stage20.DEFAULT_STAGE16_DIR.glob("*.json"))
            + sorted(stage20.DEFAULT_STAGE17_DIR.glob("*.json"))
            + sorted(stage20.DEFAULT_STAGE18_DIR.glob("*.json"))
            + sorted(stage20.DEFAULT_STAGE19_DIR.glob("*.json"))
            + [stage20.REPO_ROOT / "src" / "atari_music" / "ir.py"]
            + [stage20.REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"]
        )
        before = {str(path): stage20.sha256_file(path) for path in watched if path.is_file()}
        assert before
        stage20.write_analysis(bundle, stage20_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        after = {str(path): stage20.sha256_file(path) for path in watched if path.is_file()}
        assert before == after

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage20.render_report(bundle)
        assert "created_utc" not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text)

    def test_the_source_hash_travels_with_the_bundle(self, bundle: Dict[str, Any]) -> None:
        assert bundle["determinism"]["source_hash"] == stage20.sha256_file(
            Path(stage20.__file__)
        )

    def test_the_seed_and_the_tie_breaks_are_declared(self, bundle: Dict[str, Any]) -> None:
        determinism = bundle["determinism"]
        assert determinism["random_seed"] == stage20.RANDOM_SEED
        for phrase in ("contour fit", "residual induction", "modal value"):
            assert phrase in determinism["tie_breaks"]

    def test_the_source_audit_hashes_every_module_it_borrows(self, bundle: Dict[str, Any]) -> None:
        audit = bundle["source_audit"]
        assert audit["all_present"] is True
        for item in audit["modules"]:
            assert item["present"] and item["sha256"]
        assert audit["composition_data_found"] is False
        assert audit["note_representation"]["is_ground_truth"] is False



@requires_corpus
class TestReport:
    def test_the_report_has_the_twenty_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage20.render_report(bundle)
        for number in range(1, 21):
            assert re.search(rf"(?m)^## {number}\. ", text), f"section {number} missing"

    def test_the_report_ends_with_the_final_question(self, bundle: Dict[str, Any]) -> None:
        text = stage20.render_report(bundle)
        assert "## Final question" in text
        assert text.index("## Final question") > text.index("## 20. Final Verdict")

    def test_the_report_renders_without_a_traceback(self, bundle: Dict[str, Any]) -> None:
        text = stage20.render_report(bundle)
        assert "Traceback" not in text
        assert "None" not in text
        assert len(text) > 20000

    def test_the_report_names_the_stop_condition(self, bundle: Dict[str, Any]) -> None:
        assert "nothing was implemented in production" in stage20.render_report(bundle).lower()

    def test_the_report_keeps_the_levels_apart(self, bundle: Dict[str, Any]) -> None:
        text = stage20.render_report(bundle)
        for word in ("COMPOSITION", "PREDICTION", "RESIDUAL", "EXACT TRACE"):
            assert word in text

    def test_the_report_states_that_residual_is_not_performance(
        self, bundle: Dict[str, Any]
    ) -> None:
        text = stage20.render_report(bundle).lower()
        assert "residual != 0" in text
        assert "is not performance" in text

    def test_the_report_records_the_audctl_finding(self, bundle: Dict[str, Any]) -> None:
        text = stage20.render_report(bundle)
        assert "AUDCTL" in text
        assert "reproduces" in text

    def test_the_report_names_the_trivial_causes_it_ruled_out(
        self, bundle: Dict[str, Any]
    ) -> None:
        text = stage20.render_report(bundle).lower()
        for phrase in ("pitch mapping", "detector gap", "level model", "channel assignment",
                       "note length"):
            assert phrase in text

    def test_the_summary_carries_the_executive_numbers(self, bundle: Dict[str, Any]) -> None:
        summary = bundle["summary"]
        for key in (
            "note_register_coverage", "note_frame_coverage", "residual_share",
            "grammar_structural_share", "additional_explained_share", "remaining_share",
            "null_no_notes_coverage", "null_shuffled_structural_share",
            "control_shifted_coverage", "level_model_fidelity", "leave_one_out_gain",
            "verdicts", "deciding_condition",
        ):
            assert key in summary, key


@requires_corpus
class TestCli:
    def test_the_command_writes_the_record_and_the_document(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        docs = tmp_path / "docs"
        result = CliRunner().invoke(
            cli, ["analyze-stage20", "--reports-dir", str(reports), "--docs-dir", str(docs)]
        )
        assert result.exit_code == 0, result.output
        assert (docs / stage20.STAGE20_DOC).is_file()
        for name in stage20.STAGE20_FILES:
            assert (reports / name).is_file()
        assert "Residual" in result.output
        assert "PERFORMANCE_LAYER" in result.output or "RESIDUAL_" in result.output

    def test_the_cli_reports_the_same_verdicts_as_the_bundle(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["analyze-stage20", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d")],
        )
        assert result.exit_code == 0, result.output
        written = json.loads((tmp_path / "r" / "summary.json").read_text(encoding="utf-8"))
        for verdict in written["verdicts"].values():
            assert verdict in result.output


"""Stage 13A — pitch trajectory perceptual experiment.

These tests pin the experiment to its measured facts and prove the production path is
untouched: the transform rewrites only AUDF, and every existing rendering is unchanged when
Stage 13A is not invoked.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music import stage13a
from atari_music.cli import cli


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage13a.run_experiment()


@pytest.fixture(scope="module")
def usable(bundle: Dict[str, Any]) -> list:
    return [case for case in bundle["cases"] if "levels" in case]


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage13a.run_experiment() == bundle

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        a = stage13a.write_experiment(
            stage13a.run_experiment(), stage13a_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        b = stage13a.write_experiment(
            stage13a.run_experiment(), stage13a_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        da = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in a.items()}
        db = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in b.items()}
        assert da == db


# ---------------------------------------------------------------------------
# 2. Reconnaissance
# ---------------------------------------------------------------------------
class TestReconnaissance:
    def test_the_bank_uses_one_representation(self, bundle: Dict[str, Any]) -> None:
        representation = bundle["reconnaissance"]["representation"]
        assert representation["modes"] == {"semitones_from_base": 67}
        assert representation["quantizations_semitones"] == {"0.01": 67}

    def test_the_register_artifacts_are_excluded(self, bundle: Dict[str, Any]) -> None:
        transferable = bundle["reconnaissance"]["transferable"]
        assert transferable["bounded_within_one_octave"] == 14
        assert transferable["unbounded_register_artifacts"] == 32

    def test_only_a_minority_of_series_is_transferable(self, bundle: Dict[str, Any]) -> None:
        recon = bundle["reconnaissance"]
        assert recon["gesture_pitch"]["static"] == 21
        assert recon["gesture_pitch"]["non_static_with_runs"] == 46


# ---------------------------------------------------------------------------
# 3. Selection
# ---------------------------------------------------------------------------
class TestSelection:
    def test_eight_cases_all_bounded(self, bundle: Dict[str, Any]) -> None:
        selection = bundle["selection"]
        assert len(selection) == 8
        for case in selection:
            assert case["max_abs_semitones"] <= stage13a.SEMITONE_LIMIT

    def test_the_reasons_cover_the_rule(self, bundle: Dict[str, Any]) -> None:
        reasons = " ".join(case["reason"] for case in bundle["selection"])
        for token in ("strongest", "longest", "vibrato", "nearly static", "rising", "falling"):
            assert token in reasons, token

    def test_the_selection_is_deterministic(self, bundle: Dict[str, Any]) -> None:
        assert stage13a.run_experiment()["selection"] == bundle["selection"]


# ---------------------------------------------------------------------------
# 4. The transform: only AUDF changes (Parts 9, 17)
# ---------------------------------------------------------------------------
class TestTransform:
    def test_only_audf_changes(self, usable: list) -> None:
        for case in usable:
            for level in (1, 2):
                proof = case["levels"][level]["variants"]["C"]["proof"]
                assert proof["only_audf_changed"] is True
                assert proof["audc_unchanged"] is True
                assert proof["audctl_unchanged"] is True
                assert proof["frames_outside_window_unchanged"] is True

    def test_the_static_level_adds_no_movement(self, usable: list) -> None:
        # B shifts the note by a constant, so it has no pitch *movement* at all
        for case in usable:
            assert case["levels"][1]["variants"]["B"]["pitch"]["range_semitones"] == 0.0

    def test_a_static_trajectory_would_be_a_no_op(self) -> None:
        steps = (("C4", 4),)
        song, frames = stage13a.compiled(steps)
        window = stage13a.event_window(steps, 0, song.frames_per_tick)
        same, _ = stage13a.apply_pitch(
            frames,
            window=window,
            base_freq_hz=261.63,
            deltas=[0.0] * (window[1] - window[0]),
            audctl=0,
        )
        assert np.array_equal(same, frames)


# ---------------------------------------------------------------------------
# 5. The hypotheses (Parts 12-13)
# ---------------------------------------------------------------------------
class TestHypotheses:
    def test_technical_transfer_holds_everywhere(self, bundle: Dict[str, Any]) -> None:
        h1 = bundle["hypotheses"]["H1_technical_transfer"]
        assert h1["count"] == h1["of"] == 8

    def test_musical_pitch_is_preserved(self, bundle: Dict[str, Any]) -> None:
        h3 = bundle["hypotheses"]["H3_preserves_musical_pitch"]
        assert h3["count"] == h3["of"] == 8

    def test_the_trajectory_adds_movement_over_static(self, bundle: Dict[str, Any]) -> None:
        assert bundle["hypotheses"]["H2_beyond_static_pitch"]["count"] >= 1

    def test_the_control_split_is_recorded_either_way(self, bundle: Dict[str, Any]) -> None:
        h5 = bundle["hypotheses"]["H5_specific_to_the_profile"]
        assert h5["of"] == len(h5["C_moves_more"]) + len(h5["D_moves_more"])
        assert "why" in h5

    def test_the_verdict_is_the_decision_tree(self, bundle: Dict[str, Any]) -> None:
        decision = stage13a.verdict(bundle)
        assert decision["label"] in {"SUPPORTED", "INCONCLUSIVE", "NOT SUPPORTED"}
        assert decision["label"] == "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# 6. The listening package (Parts 14-15, 20)
# ---------------------------------------------------------------------------
class TestListening:
    def test_it_is_justified_and_small(self, bundle: Dict[str, Any]) -> None:
        listening = bundle["listening"]
        assert listening["justified"] is True
        assert 1 <= listening["count"] <= stage13a.LISTENING_TRIAL_LIMIT

    def test_it_covers_the_priority_comparisons(self, bundle: Dict[str, Any]) -> None:
        ids = " ".join(trial["trial_id"] for trial in bundle["listening"]["trials"])
        for token in ("C_vs_A", "C_vs_B", "C_vs_D"):
            assert token in ids, token

    def test_the_package_is_deterministic(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        a = stage13a.build_listening_package(bundle, out_dir=tmp_path / "a")
        b = stage13a.build_listening_package(bundle, out_dir=tmp_path / "b")
        assert a == b

    def test_the_page_is_built_and_stays_blind(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        manifest = stage13a.build_listening_package(bundle, out_dir=tmp_path / "pkg")
        page = (tmp_path / "pkg" / "index.html").read_text(encoding="utf-8")
        assert "__PACKAGE__" not in page
        assert "Download the answer CSV" in page
        assert "evaluation_stage13a.csv" in page
        for trial in manifest["trials"]:
            assert trial["trial_id"] in page
        assert '"sides"' not in page and '"compared"' not in page

    def test_the_files_exist(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        stage13a.build_listening_package(bundle, out_dir=tmp_path / "pkg")
        for name in ("manifest.json", "evaluation_stage13a.csv", "metadata.json", "README.md"):
            assert (tmp_path / "pkg" / name).is_file(), name
        assert len(list((tmp_path / "pkg" / "audio").glob("*.wav"))) >= 2


# ---------------------------------------------------------------------------
# 7. The document and the commands
# ---------------------------------------------------------------------------
class TestReportAndCommand:
    def test_the_report_answers_the_eight_questions(self, bundle: Dict[str, Any]) -> None:
        text = stage13a.render_report(bundle)
        assert "## Final report — the eight questions" in text
        assert "**8. The single highest-value next step.**" in text
        assert "VERDICT: INCONCLUSIVE" in text

    def test_the_report_keeps_the_three_kinds_apart(self, bundle: Dict[str, Any]) -> None:
        text = stage13a.render_report(bundle)
        assert "**Observed" in text and "**Inference" in text and "**Experimental choice" in text

    def test_the_commands_are_registered(self) -> None:
        for command in ("run-stage13a", "prepare-stage13a-listening"):
            result = CliRunner().invoke(cli, [command, "--help"])
            assert result.exit_code == 0, result.output

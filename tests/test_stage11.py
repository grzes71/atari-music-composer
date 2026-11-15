"""Stage 11A — the perceptual synthesis.

These tests do not re-derive the numbers; they pin the synthesis to the published artefacts
it reads, and they prove the output is deterministic (so a re-run cannot silently change the
document). Nothing here renders audio or writes into the repository.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage11a
from atari_music.cli import cli


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage11a.build_synthesis()


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_builds_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage11a.build_synthesis() == bundle

    def test_no_wall_clock_leaks_into_the_record(self, bundle: Dict[str, Any]) -> None:
        text = stage11a._dumps(bundle)
        assert "created_utc" not in text
        assert "generated" not in text and "timestamp" not in text

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        a = stage11a.write_synthesis(
            stage11a.build_synthesis(), stage11_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        b = stage11a.write_synthesis(
            stage11a.build_synthesis(), stage11_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        digests_a = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in a.items()}
        digests_b = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in b.items()}
        assert digests_a == digests_b
        assert len(digests_a) >= 11


# ---------------------------------------------------------------------------
# 2. A3 — the representation gap, pinned to Stage 9E
# ---------------------------------------------------------------------------
class TestRepresentationGap:
    def test_counts_are_the_published_ones(self, bundle: Dict[str, Any]) -> None:
        gap = bundle["representation_gap"]
        assert gap["leaf_paths_total"] == 232
        assert gap["read_by_binding_count"] == 13
        assert gap["counts"] == {"USED": 28, "IGNORED": 74, "PLAYER_ONLY": 21, "UNREPRESENTABLE": 109}

    def test_first_loss_is_the_binding(self, bundle: Dict[str, Any]) -> None:
        gap = bundle["representation_gap"]
        assert "_rebuild_song" in gap["first_information_loss"]
        assert gap["loss_points"]["l1_first_loss"]["classified_as"] == "representation gap"

    def test_the_renderer_is_not_the_loss(self, bundle: Dict[str, Any]) -> None:
        assert bundle["representation_gap"]["loss_points"]["l3_no_gap"]["classification"] == "no gap"

    def test_gesture_is_lost(self, bundle: Dict[str, Any]) -> None:
        lost = bundle["representation_gap"]["gesture_lost_by_binding"]
        assert lost == {
            "control_state": "lost",
            "modulation": "lost",
            "pitch": "lost",
            "timing": "lost",
            "volume": "lost",
        }


# ---------------------------------------------------------------------------
# 3. A4 — the collapse
# ---------------------------------------------------------------------------
class TestCollapse:
    def test_the_collapse_numbers(self, bundle: Dict[str, Any]) -> None:
        coll = bundle["collapse"]
        assert coll["profiles_probed"] == 61
        assert coll["distinct_audio_signals"] == 37
        assert coll["redundant_profiles"] == 24
        assert coll["groups"] == 6
        assert coll["largest_group"] == 10

    def test_every_group_is_a_representation_duplicate(self, bundle: Dict[str, Any]) -> None:
        coll = bundle["collapse"]
        assert coll["classification_counts"] == {"representation_duplicate": 6}
        assert coll["first_divergence_counts"] == {"bound_ir": 6}

    def test_the_audio_measurement_agrees(self, bundle: Dict[str, Any]) -> None:
        assert bundle["collapse"]["agrees_with_the_audio_only_measurement"] is True


# ---------------------------------------------------------------------------
# 4. A5 / A6 — the two answer sheets, decoded
# ---------------------------------------------------------------------------
class TestListeningReevaluation:
    def test_stage10a_primary_and_control(self, bundle: Dict[str, Any]) -> None:
        a = bundle["stage10a"]
        assert a["answered"] == 18
        assert a["primary"] == {"default": 4, "old": 2, "new": 2, "none": 4, "n": 12, "other": 6}
        assert a["control"] == {"default": 4, "old": 1, "new": 0, "none": 1, "n": 6, "other": 5}

    def test_stage10b_split_by_level(self, bundle: Dict[str, Any]) -> None:
        b = bundle["stage10b"]
        assert b["answered"] == 18
        assert b["profile_level_b_vs_c"]["none"] == 8
        assert b["profile_level_b_vs_c"]["c"] == 0
        assert b["song_level_b_vs_c"] == {"c": 1, "other": 2, "none": 3, "heard": 3, "n": 6}

    def test_stage10b_perceptibility(self, bundle: Dict[str, Any]) -> None:
        b = bundle["stage10b"]
        assert b["audibility"]["heard"] == 7
        assert b["audibility"]["neither"] == 11


# ---------------------------------------------------------------------------
# 5. A1 / A2 / A7 — the matrix, the classes, the ranking
# ---------------------------------------------------------------------------
class TestSynthesisContent:
    def test_every_matrix_row_has_provenance(self, bundle: Dict[str, Any]) -> None:
        rows = bundle["evidence_matrix"]
        assert len(rows) == 9
        for row in rows:
            assert row["provenance"], row["feature"]

    def test_pitch_trajectory_is_not_used_by_the_binding(self, bundle: Dict[str, Any]) -> None:
        row = next(r for r in bundle["evidence_matrix"] if r["feature"] == "pitch trajectory")
        assert row["used_by_binding"] == "no"
        assert row["perceptual_experiment"].startswith("not tested")

    def test_volume_contour_is_negative_evidence(self, bundle: Dict[str, Any]) -> None:
        row = next(r for r in bundle["feature_classification"] if r["feature"] == "volume contour")
        assert row["class"] == "negative evidence"

    def test_pitch_ranks_first(self, bundle: Dict[str, Any]) -> None:
        ranking = bundle["hypothesis_ranking"]
        assert ranking[0]["rank"] == 1
        assert "pitch trajectory" in ranking[0]["dimension"]

    def test_the_report_keeps_the_three_kinds_apart(self, bundle: Dict[str, Any]) -> None:
        text = stage11a.render_report(bundle)
        assert "**Observed" in text
        assert "**Inference" in text
        assert "**Experimental choice" in text

    def test_the_report_has_the_expected_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage11a.render_report(bundle)
        for index in range(1, 11):
            assert f"## A{index}. " in text, index

    def test_the_report_states_the_go_no_go(self, bundle: Dict[str, Any]) -> None:
        assert "PROCEED" in stage11a.render_report(bundle)


# ---------------------------------------------------------------------------
# 6. The producer evidence (skipped when the producer repository is absent)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not stage11a.DEFAULT_ARCHAEOLOGY_DIR.is_dir(), reason="producer repository not present"
)
class TestProducerEvidence:
    def test_the_bandwidth_sign_flip_is_visible(self, bundle: Dict[str, Any]) -> None:
        ev = bundle["perceptual_evidence"]
        seven_b = {
            entry["label"]: entry["spearman_rho"]
            for entry in ev["seven_b"]["strongest_usefulness_predictors"]
        }
        assert seven_b["spectral bandwidth (Hz) vs usefulness"] == -0.4401
        nine_d = {(row["metric"], row["scale"]): row["spearman"] for row in ev["nine_d"]["table"]}
        assert nine_d[("bandwidth_hz", "usefulness")] == 0.6596

    def test_the_listener_vocabulary_is_read(self, bundle: Dict[str, Any]) -> None:
        vocab = {
            entry["term"]: entry["comments"]
            for entry in bundle["perceptual_evidence"]["seven_b"]["vocabulary"]
        }
        assert vocab["percussion-like"] == 12
        assert vocab["rising"] >= 1


# ---------------------------------------------------------------------------
# 7. The command
# ---------------------------------------------------------------------------
class TestTheCommand:
    def test_it_is_registered_and_documents_itself(self) -> None:
        result = CliRunner().invoke(cli, ["synthesize-stage11a", "--help"])
        assert result.exit_code == 0, result.output
        assert "Stage 11A" in result.output


# ===========================================================================
# Stage 11B — the controlled spectral experiment
# ===========================================================================
from atari_music import stage11b  # noqa: E402


@pytest.fixture(scope="module")
def experiment() -> Dict[str, Any]:
    return stage11b.run_experiment()


class TestSelection:
    def test_it_picks_eight_distinct_sounds(self, experiment: Dict[str, Any]) -> None:
        selection = experiment["selection"]
        assert len(selection) == 8
        ids = [entry["profile_id"] for entry in selection]
        assert len(set(ids)) == 8

    def test_one_per_duplicate_group(self, experiment: Dict[str, Any]) -> None:
        groups = [entry["duplicate_group"] for entry in experiment["selection"] if entry["duplicate_group"] is not None]
        assert len(groups) == len(set(groups))

    def test_every_selection_is_renderable(self, experiment: Dict[str, Any]) -> None:
        bank = stage11b.load_sound_profile_bank(stage11b.DEFAULT_BANK_DIR)
        for entry in experiment["selection"]:
            assert bank.get(entry["profile_id"]).renderable

    def test_the_selection_is_deterministic(self, experiment: Dict[str, Any]) -> None:
        again = stage11b.run_experiment()
        assert again["selection"] == experiment["selection"]


class TestAblation:
    def test_the_baseline_reproduces_the_unbound_render(self, experiment: Dict[str, Any]) -> None:
        for record in experiment["profiles"]:
            assert record["baseline_reproduction_check"] is True, record["profile_id"]

    def test_every_variant_was_rendered(self, experiment: Dict[str, Any]) -> None:
        for record in experiment["profiles"]:
            assert set(record["variants"]) == set(stage11b.VARIANT_ORDER)
            for variant in record["variants"].values():
                assert variant["pcm_sha256"]

    def test_full_is_the_stage9e_six_scalars(self, experiment: Dict[str, Any]) -> None:
        # 'full' reverts nothing, so its song is the bound song; its spectrum must differ from
        # the baseline for at least the profiles the listener can hear a generator change on.
        differing = [
            record
            for record in experiment["profiles"]
            if record["variants"]["full"]["pcm_sha256"]
            != record["variants"]["baseline"]["pcm_sha256"]
        ]
        assert differing

    def test_the_run_is_deterministic(self, experiment: Dict[str, Any]) -> None:
        assert stage11b.run_experiment() == experiment


class TestClassification:
    def test_every_profile_is_classified(self, experiment: Dict[str, Any]) -> None:
        allowed = {"EXPRESSIBLE", "PARTIALLY_EXPRESSIBLE", "NOT_EXPRESSIBLE", "UNTESTED"}
        for record in experiment["profiles"]:
            assert record["classification"]["expressibility"] in allowed

    def test_the_counts_add_up(self, experiment: Dict[str, Any]) -> None:
        counts = experiment["summary"]["expressibility_counts"]
        assert sum(counts.values()) == 8

    def test_the_generator_dominates_the_ablation(self, experiment: Dict[str, Any]) -> None:
        best = experiment["summary"]["best_single_feature_counts"]
        assert best.get("generator", 0) >= 1

    def test_no_listening_package_is_claimed(self, experiment: Dict[str, Any]) -> None:
        assert experiment["listening"]["justified"] is False


class TestReproducibility:
    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        a = stage11b.write_experiment(
            stage11b.run_experiment(), stage11_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        b = stage11b.write_experiment(
            stage11b.run_experiment(), stage11_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        digests_a = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in a.items()}
        digests_b = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in b.items()}
        assert digests_a == digests_b

    def test_the_document_answers_the_eight_questions(self, experiment: Dict[str, Any]) -> None:
        text = stage11b.render_report(experiment)
        assert "## Final report — the eight questions" in text
        assert "highest-value next engineering step" in text
        assert "**1. What does the existing evidence say?**" in text

    def test_the_document_keeps_the_three_kinds_apart(self, experiment: Dict[str, Any]) -> None:
        text = stage11b.render_report(experiment)
        assert "**Observed" in text
        assert "**Inference" in text
        assert "**Experimental choice" in text

    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["run-stage11b", "--help"])
        assert result.exit_code == 0, result.output
        assert "spectral" in result.output.lower()

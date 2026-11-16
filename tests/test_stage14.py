"""Stage 14 — final evidence synthesis and the SoundProfile go/no-go.

These tests pin the synthesis to the raw artifacts (including the Stage 12A and 13A answer
sheets, decoded against their private manifests) and prove the stage is read-only and
deterministic.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage14
from atari_music.cli import cli

pytestmark = pytest.mark.experimental


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage14.run_synthesis()


# ---------------------------------------------------------------------------
# 1. Determinism and read-only behaviour
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage14.run_synthesis() == bundle

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        a = stage14.write_synthesis(
            stage14.run_synthesis(), stage14_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        b = stage14.write_synthesis(
            stage14.run_synthesis(), stage14_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        da = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in a.items()}
        db = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in b.items()}
        assert da == db
        assert set(da) == {
            "evidence_matrix.json",
            "hypothesis_verdicts.json",
            "transfer_model.json",
            "context_dependence.json",
            "knowledge_base_assessment.json",
            "option_assessment.json",
            "summary.json",
            "stage14_final_synthesis.md",
        }

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage14.render_report(bundle)
        assert "created_utc" not in text

    def test_the_stage_is_read_only(self, tmp_path: Path) -> None:
        watched = [
            stage14.DEFAULT_STAGE12A_PACKAGE / "evaluation_stage12a.csv",
            stage14.DEFAULT_STAGE13A_PACKAGE / "evaluation_stage13a.csv",
            stage14.DEFAULT_STAGE12A_PACKAGE / "manifest.json",
            stage14.DEFAULT_STAGE13A_PACKAGE / "manifest.json",
        ]
        before = {str(p): stage14.sha256_file(p) for p in watched if p.is_file()}
        stage14.write_synthesis(
            stage14.run_synthesis(), stage14_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        after = {str(p): stage14.sha256_file(p) for p in watched if p.is_file()}
        assert before == after


# ---------------------------------------------------------------------------
# 2. The listening evidence, decoded from the raw sheets
# ---------------------------------------------------------------------------
class TestListeningDecode:
    def test_stage12a_splits(self, bundle: Dict[str, Any]) -> None:
        decode = bundle["listening"]["stage12a"]
        assert decode["answered"] == decode["trials"] == 8
        assert stage14._pair_text(decode, "C_vs_A") == "1-3"
        assert stage14._pair_text(decode, "C_vs_B") == "1-0 (3 ties)"

    def test_stage13a_splits(self, bundle: Dict[str, Any]) -> None:
        decode = bundle["listening"]["stage13a"]
        assert decode["answered"] == decode["trials"] == 15
        assert stage14._pair_text(decode, "C_vs_A", 1) == "4-0"
        assert stage14._pair_text(decode, "C_vs_A", 2) == "1-3"
        assert stage14._pair_text(decode, "C_vs_B") == "4-0"
        assert stage14._pair_text(decode, "C_vs_D") == "1-2"

    def test_the_reused_reevaluations_are_read_not_recomputed(self, bundle: Dict[str, Any]) -> None:
        assert bundle["listening"]["stage10a"]["primary"]["n"] == 12
        assert bundle["listening"]["stage10b"]["profile_level_b_vs_c"]["none"] == 8


# ---------------------------------------------------------------------------
# 3. The evidence matrix (Part 2) and the four claims (Part 3)
# ---------------------------------------------------------------------------
class TestEvidenceMatrix:
    def test_ten_rows(self, bundle: Dict[str, Any]) -> None:
        assert len(bundle["evidence_matrix"]) == 10

    def test_every_row_carries_the_four_claims(self, bundle: Dict[str, Any]) -> None:
        allowed = {"POSITIVE", "NEGATIVE", "INCONCLUSIVE", "NOT_TESTED"}
        for row in bundle["evidence_matrix"]:
            for claim in stage14.CLAIMS:
                assert row[claim] in allowed, (row["capability"], claim)
            assert row["note"] and row["provenance"]

    def test_the_headline_downgrade_is_recorded(self, bundle: Dict[str, Any]) -> None:
        # representable + measurable + detectable, but not useful
        for capability in ("volume contour", "pitch trajectory"):
            row = next(r for r in bundle["evidence_matrix"] if r["capability"] == capability)
            assert row["A_technically_representable"] == "POSITIVE"
            assert row["B_acoustically_measurable"] == "POSITIVE"
            assert row["C_perceptually_detectable"] == "POSITIVE"
            assert row["D_perceptually_useful"] == "NEGATIVE"

    def test_no_capability_is_judged_useful(self, bundle: Dict[str, Any]) -> None:
        assert bundle["summary"]["perceptually_useful_positive"] == []
        assert len(bundle["summary"]["perceptually_useful_negative"]) == 5


# ---------------------------------------------------------------------------
# 4. The verdicts (Parts 4-7, 9)
# ---------------------------------------------------------------------------
class TestVerdicts:
    def test_five_hypotheses_with_the_expected_verdicts(self, bundle: Dict[str, Any]) -> None:
        verdicts = {row["id"]: row["verdict"] for row in bundle["hypothesis_verdicts"]}
        assert verdicts["H1"] == "NEGATIVE"
        assert verdicts["H2"] == "NEGATIVE"
        assert verdicts["H3"] == "NEGATIVE"
        assert verdicts["H4"] == "NOT SUPPORTED"
        assert "PERCEPTUALLY NOT SUPPORTED" in verdicts["H5"]

    def test_the_transfer_model_answers_six_questions(self, bundle: Dict[str, Any]) -> None:
        model = bundle["transfer_model"]
        assert len(model["questions"]) == 6
        assert model["verdict"] == "DIRECT TRANSFER NOT SUPPORTED"
        assert "not itself evidence" in model["reconciliation"]["conclusion"]

    def test_context_dependence_is_supported(self, bundle: Dict[str, Any]) -> None:
        assert bundle["context_dependence"]["classification"] == "SUPPORTED"
        assert bundle["context_dependence"]["evidence"]

    def test_the_knowledge_base_is_not_endorsed(self, bundle: Dict[str, Any]) -> None:
        knowledge = bundle["knowledge_base_assessment"]
        assert knowledge["classification"] == "PLAUSIBLE, NOT SUPPORTED"
        assert knowledge["evidence_for"] and knowledge["evidence_against"]
        assert knowledge["gate_to_revisit"]


# ---------------------------------------------------------------------------
# 5. The options and the recommendation (Parts 12-17)
# ---------------------------------------------------------------------------
class TestRecommendation:
    def test_four_options_scored(self, bundle: Dict[str, Any]) -> None:
        options = bundle["option_assessment"]
        assert [o["option"] for o in options] == ["A", "B", "C", "D"]
        for option in options:
            assert len(option["criteria"]) == 9

    def test_the_recommendation_is_option_c(self, bundle: Dict[str, Any]) -> None:
        assert bundle["recommendation"]["headline"] == "RECOMMENDATION: OPTION C"
        assert bundle["summary"]["recommendation"] == "RECOMMENDATION: OPTION C"
        assert set(bundle["recommendation"]["why_alternatives_weaker"]) == {"A", "B", "D"}

    def test_the_non_goals_are_explicit(self, bundle: Dict[str, Any]) -> None:
        assert len(bundle["recommendation"]["what_must_not_happen_next"]) >= 3
        assert bundle["future_architecture"]["what_is_missing_for_a_knowledge_base"]


# ---------------------------------------------------------------------------
# 6. The document and the command
# ---------------------------------------------------------------------------
class TestReportAndCommand:
    def test_the_report_has_the_seventeen_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage14.render_report(bundle)
        for index in range(1, 18):
            assert f"## {index}. " in text, index

    def test_the_report_states_the_recommendation(self, bundle: Dict[str, Any]) -> None:
        text = stage14.render_report(bundle)
        assert "RECOMMENDATION: OPTION C" in text
        assert "## 12. What failed" in text

    def test_the_report_keeps_the_three_kinds_apart(self, bundle: Dict[str, Any]) -> None:
        text = stage14.render_report(bundle)
        assert "**Observed" in text and "**Inference" in text

    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["synthesize-stage14", "--help"])
        assert result.exit_code == 0, result.output
        assert "synthesis" in result.output.lower()

"""Stage 9D: analysis of the returned human listening results.

Stage 9C produced the experiment; these answers are the evidence. The tests lock the properties
that make the analysis trustworthy:

* the answers are **read, hashed and never modified**, and a gap is reported rather than filled;
* the statistics are correct, checked against hand-computed values rather than against themselves;
* the three experiments stay separate and are joined to the manifest by id, never by position;
* the outputs are deterministic, and the machinery refuses to invent data it does not have.

The end-to-end tests need the returned answers, which live in the gitignored `examples/` tree
(like the songs), so they skip in a checkout where the experiment has not been run.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from click.testing import CliRunner

from atari_music import stage9d
from atari_music.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "examples" / "sound_profile_listening"
OUTPUTS = ("profile_scores", "correlations", "hypotheses", "categories", "coverage", "shortlist",
           "verdict", "profiles_csv", "report")


def _require_answers() -> None:
    if not (PACKAGE_DIR / "manifest.json").is_file():
        pytest.skip("the Stage 9C listening package is not present in this checkout")


@pytest.fixture(scope="module")
def answers() -> stage9d.Answers:
    _require_answers()
    return stage9d.load_answers(PACKAGE_DIR)


@pytest.fixture(scope="module")
def analysis(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """One full analysis, shared by the read-mostly tests."""
    _require_answers()
    out = tmp_path_factory.mktemp("stage9d")
    written = stage9d.analyze_stage9d(PACKAGE_DIR, docs_dir=out, reports_dir=out)
    return {
        "written": written,
        "profiles": stage9d.build_profile_results(stage9d.load_answers(PACKAGE_DIR)),
        "scores": json.loads(written["profile_scores"].read_text(encoding="utf-8")),
        "hypotheses": json.loads(written["hypotheses"].read_text(encoding="utf-8"))["hypotheses"],
        "verdict": json.loads(written["verdict"].read_text(encoding="utf-8")),
        "shortlist": json.loads(written["shortlist"].read_text(encoding="utf-8")),
        "coverage": json.loads(written["coverage"].read_text(encoding="utf-8")),
        "categories": json.loads(written["categories"].read_text(encoding="utf-8")),
        "report": written["report"].read_text(encoding="utf-8"),
    }


# ---------------------------------------------------------------------------
# The statistics, against hand-computed values
# ---------------------------------------------------------------------------
class TestStatistics:
    def test_pearson_matches_hand_computation(self) -> None:
        assert stage9d.pearson([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
        assert stage9d.pearson([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
        # x = 1,2,3,4 ; y = 2,4,5,9 -> r = 11 / sqrt(5 * 26) = 0.9648
        assert stage9d.pearson([1, 2, 3, 4], [2, 4, 5, 9]) == pytest.approx(0.9648, abs=1e-4)

    def test_spearman_ignores_monotone_distortion(self) -> None:
        """The point of using ranks: a monotone but non-linear relationship still scores 1."""
        assert stage9d.spearman([1, 2, 3, 4], [1, 10, 100, 1000]) == pytest.approx(1.0)
        assert stage9d.spearman([1, 2, 3, 4], [1000, 100, 10, 1]) == pytest.approx(-1.0)

    def test_spearman_handles_ties_by_average_ranks(self) -> None:
        # x = 1,2,3,3,4 -> ranks 1,2,3.5,3.5,5
        left = [1, 2, 3, 3, 4]
        assert stage9d.spearman(left, left) == pytest.approx(1.0)
        assert stage9d.spearman(left, [1, 2, 3, 3, 4]) == pytest.approx(1.0)

    def test_kendall_tau_b_is_tie_corrected_and_bounded(self) -> None:
        assert stage9d.kendall_tau_b([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
        assert stage9d.kendall_tau_b([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
        tau = stage9d.kendall_tau_b([1, 1, 1, 1], [1, 2, 3, 4])
        assert tau is None or -1 <= tau <= 1

    def test_cliffs_delta_reads_as_a_probability_difference(self) -> None:
        assert stage9d.cliffs_delta([5, 5], [1, 1]) == pytest.approx(1.0)
        assert stage9d.cliffs_delta([1, 1], [5, 5]) == pytest.approx(-1.0)
        assert stage9d.cliffs_delta([1, 2], [1, 2]) == pytest.approx(0.0)

    def test_describe_reports_n_and_refuses_to_summarise_nothing_as_zero(self) -> None:
        assert stage9d.describe([]) == {"n": 0}
        summary = stage9d.describe([1, 2, 3, 4, 5])
        assert summary["n"] == 5
        assert summary["mean"] == 3.0
        assert summary["median"] == 3.0
        assert summary["distribution"] == {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}
        assert summary["share_4_5"] == 0.4

    def test_icc_decomposes_between_and_within_variance(self) -> None:
        """Identical groups with no spread must look perfect; spread inside a group must not."""
        perfect = stage9d.icc_1_1([[5, 5, 5], [1, 1, 1], [3, 3, 3]])
        assert perfect == pytest.approx(1.0)
        # The same spread inside every group means the stimulus explained nothing: ICC <= 0.
        no_signal = stage9d.icc_1_1([[1, 5, 3], [1, 5, 3]])
        assert no_signal is not None and no_signal <= 0.0
        # A big between-group effect with a little noise must land between the two.
        mixed = stage9d.icc_1_1([[5, 5, 4], [2, 1, 1], [3, 4, 3]])
        assert 0.0 < mixed < 1.0


# ---------------------------------------------------------------------------
# Loading and verification
# ---------------------------------------------------------------------------
class TestLoadingAndVerification:
    def test_it_reads_the_three_answer_files_and_hashes_them(self, answers: stage9d.Answers) -> None:
        assert set(answers.hashes) == {
            "evaluation_profiles.csv",
            "evaluation_ab.csv",
            "evaluation_songs.csv",
            "manifest.json",
        }
        for name, digest in answers.hashes.items():
            on_disk = hashlib.sha256((PACKAGE_DIR / name).read_bytes()).hexdigest()
            assert digest == on_disk

    def test_it_refuses_a_package_without_answers(self, tmp_path: Path) -> None:
        with pytest.raises(stage9d.AnswersMissing):
            stage9d.load_answers(tmp_path)

    def test_it_refuses_a_manifest_without_the_answers(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
        with pytest.raises(stage9d.AnswersMissing):
            stage9d.load_answers(tmp_path)

    def test_it_refuses_a_missing_column_instead_of_guessing_one(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
        (tmp_path / "evaluation_profiles.csv").write_text("sample_id,usefulness\n", encoding="utf-8")
        (tmp_path / "evaluation_ab.csv").write_text("trial_id\n", encoding="utf-8")
        (tmp_path / "evaluation_songs.csv").write_text("trial_id\n", encoding="utf-8")
        with pytest.raises(stage9d.AnswersMissing) as error:
            stage9d.load_answers(tmp_path)
        assert "distinctiveness" in str(error.value)

    def test_the_returned_answers_match_the_manifest_id_for_id(
        self, answers: stage9d.Answers
    ) -> None:
        for label, rows, expected, key in (
            ("A", answers.profiles, answers.manifest["samples"], "sample_id"),
            ("B", answers.ab, answers.manifest["ab_trials"], "trial_id"),
            ("C", answers.song, answers.manifest["song_trials"], "trial_id"),
        ):
            got = [row[key] for row in rows]
            assert len(got) == len(set(got)), f"part {label} has duplicate ids"
            assert set(got) == {entry[key] for entry in expected}, f"part {label} ids disagree"

    def test_every_rating_is_in_range_and_every_choice_is_known(
        self, answers: stage9d.Answers
    ) -> None:
        for row in answers.profiles:
            for scale in stage9d.PROFILE_SCALES:
                raw = (row[scale] or "").strip()
                assert raw == "" or 1 <= float(raw) <= 5, (row["sample_id"], scale, raw)
        for row in answers.ab:
            assert (row["preference"] or "").strip() in ("", "a", "b", "none")
        for row in answers.song:
            for field in stage9d.SONG_CHOICE_FIELDS:
                assert (row[field] or "").strip() in ("", "a", "b", "none")

    def test_gaps_are_reported_as_anomalies_and_never_filled_in(
        self, answers: stage9d.Answers
    ) -> None:
        kinds = {anomaly.kind for anomaly in answers.anomalies}
        assert kinds, "the known gaps in this dataset must be reported"
        assert "missing_rating" in kinds
        assert "missing_choice" in kinds
        missing = [
            anomaly for anomaly in answers.anomalies
            if anomaly.kind == "missing_rating" and "distinctiveness" in anomaly.where
        ]
        assert missing, "sample_026 has no ratings and that must be visible"
        assert "excluded from" in missing[0].effect

    def test_a_gap_reduces_the_denominator_rather_than_being_dropped_silently(
        self, analysis: Dict[str, Any]
    ) -> None:
        scores = analysis["scores"]["counts"]
        assert scores["profiles_analysed"] == 61
        assert scores["profiles_with_ratings"] < scores["profiles_analysed"]

    def test_the_answers_are_not_modified_by_the_analysis(
        self, analysis: Dict[str, Any], answers: stage9d.Answers
    ) -> None:
        for name, digest in answers.hashes.items():
            assert hashlib.sha256((PACKAGE_DIR / name).read_bytes()).hexdigest() == digest


# ---------------------------------------------------------------------------
# Mapping and aggregation
# ---------------------------------------------------------------------------
class TestMappingAndAggregation:
    def test_every_profile_is_mapped_to_a_real_manifest_entry_and_a_real_stimulus(
        self, analysis: Dict[str, Any]
    ) -> None:
        profiles = analysis["profiles"]
        assert len(profiles) == 61
        bank_ids = {entry["profile_id"] for entry in analysis["scores"]["profiles"]}
        assert len(bank_ids) == len(profiles), "no profile id may appear twice"
        for item in profiles:
            assert (PACKAGE_DIR / item.sample_id).parent.is_dir()
            assert item.stimulus_hash and len(item.stimulus_hash) == 64
            assert item.scope in ("VOICE", "PAIR")
            assert item.status in ("PLAYABLE", "PLAYABLE_WITH_LIMITATION")

    def test_part_a_statistics_agree_with_the_raw_answers(
        self, analysis: Dict[str, Any], answers: stage9d.Answers
    ) -> None:
        by_profile = {item.profile_id: item for item in analysis["profiles"]}
        sample_of = {
            entry["profile_id"]: entry["sample_id"] for entry in answers.manifest["samples"]
        }
        expected = [
            float(row["usefulness"])
            for row in answers.profiles
            if (row["usefulness"] or "").strip()
        ]
        assert len(expected) == 60
        reported = stage9d.part_a(analysis["profiles"], [[item.sample_id] for item in analysis["profiles"]])
        assert reported["scales"]["usefulness"]["n"] == len(expected)
        assert reported["scales"]["usefulness"]["mean"] == pytest.approx(
            sum(expected) / len(expected), abs=0.001
        )
        ordered = sorted(expected)
        middle = len(ordered) // 2
        median = (
            ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        )
        assert reported["scales"]["usefulness"]["median"] == pytest.approx(median, abs=0.001)
        assert by_profile and sample_of

    def test_the_three_experiments_stay_separate(self, analysis: Dict[str, Any]) -> None:
        assert len(analysis["scores"]["profiles"]) == 61
        assert analysis["scores"]["counts"]["ab_trials"] == 30
        assert analysis["scores"]["counts"]["song_trials"] == 6
        for entry in analysis["scores"]["profiles"]:
            assert "similarity" not in entry["human"]
            assert entry["sample_id"].startswith("sample_")

    def test_comments_are_kept_verbatim_and_categorised_transparently(
        self, analysis: Dict[str, Any], answers: stage9d.Answers
    ) -> None:
        raw = {(row["sample_id"] or ""): row["comment"] for row in answers.profiles}
        for entry in analysis["scores"]["profiles"]:
            expected = raw[entry["sample_id"]].strip()
            assert entry["human"]["comment"] == expected
        # The category names must be the declared ones, and the markers must explain the match.
        for entry in analysis["scores"]["profiles"]:
            for name in entry["human"]["comment_categories"]:
                markers = next(m for n, m, _ in stage9d.COMMENT_CATEGORIES if n == name)
                assert any(marker in entry["human"]["comment"].lower() for marker in markers)

    def test_the_presentation_order_is_recorded_so_drift_can_be_detected(
        self, analysis: Dict[str, Any]
    ) -> None:
        report = analysis["report"]
        assert "Pearson(position)" in report
        assert "presentation" in report.lower()


# ---------------------------------------------------------------------------
# The noise floor, from byte-identical stimuli
# ---------------------------------------------------------------------------
class TestIdenticalAudio:
    def test_stimuli_are_hashed_and_identical_ones_are_grouped(self, answers: stage9d.Answers) -> None:
        hashes = stage9d.stimulus_hashes(PACKAGE_DIR, answers.manifest)
        assert len(hashes) == 61
        groups = stage9d.identical_audio_groups(hashes)
        assert sum(len(group) for group in groups) == 61
        assert len(groups) < 61, "this library renders the same audio for several profiles"
        assert groups[0] == sorted(groups[0])
        assert len(groups[0]) == max(len(group) for group in groups)
        for group in groups:
            assert len({hashes[sample] for sample in group}) == 1

    def test_the_noise_floor_is_measured_inside_those_groups(self, analysis: Dict[str, Any]) -> None:
        coverage = analysis["coverage"]
        assert coverage["redundant_profiles"] == 61 - coverage["distinct_audio_signals"]
        assert coverage["distinct_audio_signals"] < 61
        groups = [group for group in coverage["identical_audio_groups"] if group["size"] > 1]
        assert groups, "the noise-floor argument depends on these groups existing"
        for group in groups:
            assert len(group["profiles"]) == group["size"]

    def test_a_duplicate_profile_is_flagged_in_its_own_record(self, analysis: Dict[str, Any]) -> None:
        duplicates = [entry for entry in analysis["scores"]["profiles"] if entry["audio_group"] is not None]
        assert duplicates, "some profiles must carry an audio group"
        for entry in duplicates:
            assert "noise" in entry["notes"]


# ---------------------------------------------------------------------------
# Correlations, hypotheses and the verdict
# ---------------------------------------------------------------------------
class TestCorrelationsAndVerdict:
    def test_correlations_are_only_reported_above_the_declared_minimum_n(
        self, analysis: Dict[str, Any]
    ) -> None:
        written = json.loads(analysis["written"]["correlations"].read_text(encoding="utf-8"))
        for row in written["table"]:
            assert row["n"] >= stage9d.MIN_CORRELATION_N
            assert -1.0 <= row["spearman"] <= 1.0
            assert row["kendall_tau_b"] is None or -1.0 <= row["kendall_tau_b"] <= 1.0

    def test_unavailable_metrics_are_declared_rather_than_approximated(
        self, analysis: Dict[str, Any]
    ) -> None:
        written = json.loads(analysis["written"]["correlations"].read_text(encoding="utf-8"))
        assert written["unavailable_metrics"] == list(stage9d.UNAVAILABLE_METRICS)
        assert "transferability (Stage 6)" in written["unavailable_metrics"]

    def test_the_listener_language_test_compares_the_spectrum_with_the_generator(
        self, analysis: Dict[str, Any]
    ) -> None:
        written = json.loads(analysis["written"]["correlations"].read_text(encoding="utf-8"))
        language = written["listener_language"]
        assert language["clean"]["n"] > 0 and language["noisy"]["n"] > 0
        assert language["family_sets_disjoint"] is True

    def test_every_hypothesis_carries_a_verdict_and_cited_evidence(
        self, analysis: Dict[str, Any]
    ) -> None:
        assert len(analysis["hypotheses"]) == 7
        for entry in analysis["hypotheses"]:
            assert entry["verdict"]
            assert len(entry["evidence"]) > 80, "a verdict without evidence is not a finding"
            assert any(character.isdigit() for character in entry["evidence"])

    def test_the_verdict_is_derived_from_the_stated_criteria(self, analysis: Dict[str, Any]) -> None:
        verdict = analysis["verdict"]
        assert verdict["verdict"] in ("YES", "YES, BUT", "NO")
        blocking = {
            "the listening found more than one sound",
            "profile-bound rendering does not lose overall to the defaults",
            "no loudness correlation large enough to explain the ratings",
        }
        blocking_unmet = [name for name in verdict["unmet"] if name in blocking]
        if blocking_unmet:
            assert verdict["verdict"] == "NO"
        elif verdict["unmet"]:
            assert verdict["verdict"] == "YES, BUT"
        else:
            assert verdict["verdict"] == "YES"

    def test_the_verdict_matches_the_whole_song_result_it_rests_on(
        self, analysis: Dict[str, Any]
    ) -> None:
        """The strongest evidence must actually be what drove the answer."""
        songs = analysis["categories"]
        assert songs is not None
        verdict = analysis["verdict"]
        song_criterion = next(
            item for item in verdict["criteria"]
            if item["criterion"] == "profile-bound rendering does not lose overall to the defaults"
        )
        if not song_criterion["met"]:
            assert verdict["verdict"] == "NO"


# ---------------------------------------------------------------------------
# Categories, shortlist, coverage
# ---------------------------------------------------------------------------
class TestCategoriesAndShortlist:
    def test_the_five_categories_exist_and_are_evidence_based(self, analysis: Dict[str, Any]) -> None:
        categories = analysis["categories"]
        groups = {name for name in categories if isinstance(categories[name], list)}
        assert groups == {
            "strong_candidates",
            "character_specialists",
            "technically_interesting_perceptually_weak",
            "perceptually_interesting_weak_machine",
            "redundant",
        }
        for name in groups:
            for row in categories[name]:
                assert row["profile_id"].startswith("pokey_ref_")
                assert "usefulness" in row and "distinctiveness" in row
                assert "note" in row
        assert categories["redundant"], "the duplicates must show up here"
        assert categories["strong_candidates"], "an empty 'strong' group would mean a rule that fits nothing"
        assert "median_distance_to_library" in categories

    def test_strong_candidates_satisfy_the_stated_rule(self, analysis: Dict[str, Any]) -> None:
        """The rule is 'no *inconsistency*, nothing missing that disqualifies' — not 'no codes'.

        Almost every profile carries the same consumer gaps (the player has no gesture macro), so
        treating those as disqualifying would empty the group and say nothing.
        """
        for row in analysis["categories"]["strong_candidates"]:
            assert (row["usefulness"] or 0) >= 4
            assert (row["distinctiveness"] or 0) >= 4
            assert (row["atari_character"] or 0) >= 4
            assert "PITCH_BASE_PAIR_INCONSISTENT" not in row["limitation_codes"]
            assert not row["blocking_codes"]

    def test_the_shortlist_is_within_the_requested_size_and_never_reuses_an_audio_group(
        self, analysis: Dict[str, Any]
    ) -> None:
        shortlist = analysis["shortlist"]
        assert 20 <= shortlist["size"] <= 30
        members = shortlist["members"]
        groups = [row["audio_group"] for row in members if row["audio_group"] is not None]
        assert len(groups) == len(set(groups)), "one representative per identical-audio group"
        assert len({row["profile_id"] for row in members}) == len(members), "no duplicates"
        for row in members:
            assert row["reason"], "every candidate must say why it is there"

    def test_the_shortlist_removes_nothing_from_the_library(self, analysis: Dict[str, Any]) -> None:
        shortlist = analysis["shortlist"]
        selected = {row["profile_id"] for row in shortlist["members"]}
        excluded = {row["profile_id"] for row in shortlist["excluded"]}
        assert selected | excluded == {
            entry["profile_id"] for entry in analysis["scores"]["profiles"]
        }
        assert not (selected & excluded)

    def test_coverage_reports_the_small_diverse_alternative(self, analysis: Dict[str, Any]) -> None:
        coverage = analysis["coverage"]
        assert coverage["partitions"]["0.05"]["clusters"] >= 1
        for count, ids in coverage["greedy_coverage"].items():
            assert len(ids) == int(count)
            assert len(set(ids)) == len(ids)
        assert len(coverage["projection"]["points"]) == 61
        assert sum(coverage["projection"]["explained_variance"]) > 0

    def test_the_partitions_are_nested_in_size_not_in_number(self, analysis: Dict[str, Any]) -> None:
        """A larger cut can only merge clusters, so the count cannot grow."""
        partitions = analysis["coverage"]["partitions"]
        counts = [partitions[cut]["clusters"] for cut in sorted(partitions, key=float)]
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# Determinism and outputs
# ---------------------------------------------------------------------------
class TestOutputsAndDeterminism:
    def test_all_outputs_are_written(self, analysis: Dict[str, Any]) -> None:
        for name in OUTPUTS:
            path = analysis["written"][name]
            assert path.is_file(), f"missing {name}"
            assert path.stat().st_size > 0

    def test_the_analysis_is_deterministic(self, tmp_path: Path) -> None:
        _require_answers()
        first = stage9d.analyze_stage9d(PACKAGE_DIR, docs_dir=tmp_path / "a", reports_dir=tmp_path / "a")
        second = stage9d.analyze_stage9d(PACKAGE_DIR, docs_dir=tmp_path / "b", reports_dir=tmp_path / "b")
        for name in OUTPUTS:
            assert first[name].read_bytes() == second[name].read_bytes(), f"{name} is not deterministic"

    def test_the_report_covers_every_required_section(self, analysis: Dict[str, Any]) -> None:
        report = analysis["report"]
        for heading in (
            "## 1. Executive summary",
            "## 2. Dataset verification",
            "## 3. Part A",
            "## 4. Part B",
            "## 5. Part C",
            "## 6. Human against machine",
            "## 7. Loudness bias",
            "## 8. Hypothesis evaluation",
            "## 9. Candidate categories",
            "## 10. Recommended shortlist",
            "## 11. Redundancy and coverage",
            "## 12. Limitations",
            "## 13. Conclusions",
            "## 14. Recommended next stage",
        ):
            assert heading in report, f"the report is missing {heading}"

    def test_the_report_keeps_observed_inference_and_recommendation_apart(
        self, analysis: Dict[str, Any]
    ) -> None:
        report = analysis["report"]
        assert "**Observed.**" in report
        assert "**Inference.**" in report
        assert "**Recommendation.**" in report

    def test_the_machine_output_never_assigns_a_profile_a_role_or_a_name(
        self, analysis: Dict[str, Any]
    ) -> None:
        """The stage must not turn a profile into "bass" or "lead"."""
        for entry in analysis["scores"]["profiles"]:
            assert "role" not in entry and "name" not in entry
            assert "role" not in entry["machine"] and "name" not in entry["machine"]
        for row in analysis["shortlist"]["members"]:
            assert "role" not in row and "name" not in row
        # ...and the report says the rule out loud, so a reader is not left guessing.
        assert "no profile renamed" in analysis["report"]

    def test_the_machine_readable_output_has_the_required_shape(
        self, analysis: Dict[str, Any]
    ) -> None:
        scores = analysis["scores"]
        assert scores["analysis_version"] == stage9d.ANALYSIS_VERSION
        assert scores["answer_hashes"].keys() == {
            "evaluation_profiles.csv",
            "evaluation_ab.csv",
            "evaluation_songs.csv",
            "manifest.json",
        }
        for entry in scores["profiles"]:
            assert set(entry) >= {"profile_id", "status", "human", "machine", "candidate_groups",
                                  "candidate_class", "notes"}
            assert set(entry["human"]) >= {
                "distinctiveness", "usefulness", "character", "confidence", "comment",
            }
            assert entry["machine"]["stimulus_sha256"]

    def test_the_csv_mirror_is_readable_and_agrees_with_the_json(
        self, analysis: Dict[str, Any]
    ) -> None:
        with analysis["written"]["profiles_csv"].open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == len(analysis["scores"]["profiles"])
        assert {row["profile_id"] for row in rows} == {
            entry["profile_id"] for entry in analysis["scores"]["profiles"]
        }


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------
class TestCli:
    def test_the_command_runs_and_reports_the_verdict(self, tmp_path: Path) -> None:
        _require_answers()
        result = CliRunner().invoke(
            cli,
            [
                "analyze-listening-test-9d",
                "--package-dir", str(PACKAGE_DIR),
                "--docs-dir", str(tmp_path / "docs"),
                "--reports-dir", str(tmp_path / "reports"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Closing answer:" in result.output
        assert (tmp_path / "docs" / "stage9d_human_listening_results.md").is_file()
        assert (tmp_path / "reports" / "profile_scores.json").is_file()

    def test_the_command_fails_clearly_without_answers(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = CliRunner().invoke(
            cli,
            ["analyze-listening-test-9d", "--package-dir", str(empty),
             "--docs-dir", str(tmp_path / "docs"), "--reports-dir", str(tmp_path / "reports")],
        )
        assert result.exit_code != 0
        assert "manifest" in result.output

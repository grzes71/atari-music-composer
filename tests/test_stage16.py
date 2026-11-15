"""Stage 16 — cross-song generalisation of the Stage 15 performance style.

These tests pin the analysis to the four songs and the Stage 15 record, prove it is read-only
and deterministic, and lock down the distinctions the brief insists on: schema versus
technique versus context versus parameter generalisation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage15
from atari_music import stage16
from atari_music.cli import cli

requires_corpus = pytest.mark.skipif(
    not stage16.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage16.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)


@pytest.fixture(scope="module")
def bundle() -> Dict[str, Any]:
    return stage16.run_analysis()


# ---------------------------------------------------------------------------
# 1. Determinism and read-only behaviour
# ---------------------------------------------------------------------------
@requires_corpus
class TestDeterminism:
    def test_two_runs_are_equal(self, bundle: Dict[str, Any]) -> None:
        assert stage16.run_analysis() == bundle

    def test_writing_twice_is_byte_identical(self, tmp_path: Path) -> None:
        first = stage16.write_analysis(
            stage16.run_analysis(), stage16_dir=tmp_path / "a", docs_dir=tmp_path / "a"
        )
        second = stage16.write_analysis(
            stage16.run_analysis(), stage16_dir=tmp_path / "b", docs_dir=tmp_path / "b"
        )
        hashes_a = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in first.items()}
        hashes_b = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in second.items()}
        assert hashes_a == hashes_b
        assert set(hashes_a) == set(stage16.STAGE16_FILES) | {stage16.STAGE16_DOC}

    def test_nothing_upstream_is_written(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        """The corpus traces and every Stage 15 artefact must be untouched."""
        watched = list(stage15.list_traces()) + sorted(
            (stage16.DEFAULT_STAGE15_DIR).glob("*.json")
        )
        before = {str(path): stage16.sha256_file(path) for path in watched if path.is_file()}
        assert before, "expected some upstream artefacts to watch"
        stage16.write_analysis(bundle, stage16_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        after = {str(path): stage16.sha256_file(path) for path in watched if path.is_file()}
        assert before == after

    def test_no_timestamp_leaks(self, bundle: Dict[str, Any]) -> None:
        text = stage16.render_report(bundle)
        assert "created_utc" not in text

    def test_no_audio_or_music_is_produced(self, bundle: Dict[str, Any], tmp_path: Path) -> None:
        written = stage16.write_analysis(
            bundle, stage16_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        assert {path.suffix for path in written.values()} == {".json", ".md"}


# ---------------------------------------------------------------------------
# 2. Song selection (Part A)
# ---------------------------------------------------------------------------
@requires_corpus
class TestSongSelection:
    def test_the_stage15_pair_comes_from_the_stage15_artifact(
        self, bundle: Dict[str, Any]
    ) -> None:
        pair = bundle["song_selection"]["stage15_pair"]
        assert pair["recovered_from_artifact"] is True
        assert pair["source"].endswith("reference_song.json")
        assert pair["reference"] == stage16.SONG_A_SLUG
        record = json.loads(Path(pair["source"]).read_text(encoding="utf-8"))
        assert pair["runner_up"] == record["selection"]["runner_up"]["trace"]
        assert pair["reference"] == record["selection"]["winner"]["trace"]

    def test_the_stage15_selection_file_is_the_one_that_was_hashed(
        self, bundle: Dict[str, Any]
    ) -> None:
        pair = bundle["song_selection"]["stage15_pair"]
        assert pair["source_sha256"] == stage16.sha256_file(Path(pair["source"]))

    def test_four_songs_are_chosen_and_the_seeds_are_kept(self, bundle: Dict[str, Any]) -> None:
        chosen = bundle["song_selection"]["chosen"]
        assert len(chosen) == 4
        assert chosen[:2] == [
            bundle["song_selection"]["stage15_pair"]["reference"],
            bundle["song_selection"]["stage15_pair"]["runner_up"],
        ]

    def test_selection_is_greedy_farthest_first(self) -> None:
        candidates = stage16.corpus_candidates()
        seeds = [candidates[0].slug, candidates[1].slug]
        result = stage16.select_diverse_songs(candidates, seeds, count=2)
        vectors = {candidate.slug: candidate.vector() for candidate in candidates}
        ranges = {
            axis: max(v[axis] for v in vectors.values()) - min(v[axis] for v in vectors.values())
            for axis in stage16.DIVERSITY_NUMERIC_AXES
        }
        chosen = result["chosen"]
        for index in range(2, len(chosen)):
            picked = chosen[index]
            nearest = min(
                stage16.diversity_distance(vectors[picked], vectors[other], ranges)
                for other in chosen[:index]
            )
            for candidate in candidates:
                if candidate.slug in chosen[: index + 1]:
                    continue
                other_nearest = min(
                    stage16.diversity_distance(vectors[candidate.slug], vectors[other], ranges)
                    for other in chosen[:index]
                )
                assert other_nearest <= nearest + 1e-9

    def test_selection_is_reproducible(self, bundle: Dict[str, Any]) -> None:
        again = stage16.select_diverse_songs(
            stage16.corpus_candidates(),
            [bundle["song_selection"]["stage15_pair"]["reference"],
             bundle["song_selection"]["stage15_pair"]["runner_up"]],
            count=2,
        )
        assert again["chosen"] == bundle["song_selection"]["chosen"]

    def test_an_unknown_seed_is_refused(self) -> None:
        with pytest.raises(stage16.Stage16Error):
            stage16.select_diverse_songs(
                stage16.corpus_candidates(), ["no_such_song__sub0"], count=1
            )

    def test_the_diversity_rule_and_its_sensitivity_are_published(
        self, bundle: Dict[str, Any]
    ) -> None:
        selection = bundle["song_selection"]
        assert "farthest-first" in selection["rule"]
        assert selection["author_weight_sensitivity"]["chosen"]
        assert "note" in selection["author_weight_sensitivity"]
        assert len(selection["candidates"]) >= 4


# ---------------------------------------------------------------------------
# 3. Reuse of Stage 15 (Part B) and the per-song summaries (Part C)
# ---------------------------------------------------------------------------
@requires_corpus
class TestReuseAndSummaries:
    def test_song_analysis_reuses_stage15(self, bundle: Dict[str, Any]) -> None:
        """The pipeline must be Stage 15's, not a second implementation."""
        assert bundle["style_model"]["provenance"]["song_analysis_module"] == "atari_music.stage15"
        assert (
            bundle["style_model"]["provenance"]["song_analysis_version"]
            == stage15.ANALYSIS_VERSION
        )

    def test_analysis_matches_stage15_on_the_reference_song(self) -> None:
        """Running stage16's per-song analysis on song A must reproduce Stage 15's own numbers."""
        candidates = {candidate.slug: candidate for candidate in stage16.corpus_candidates()}
        analysis = stage16.analyse_song(candidates[stage16.SONG_A_SLUG])
        stage15_summary = json.loads(
            (stage16.DEFAULT_STAGE15_DIR / "summary.json").read_text(encoding="utf-8")
        )
        assert analysis.event_count == stage15_summary["events"]["total"]
        assert len(analysis.indexes_by_technique) == stage15_summary["events"]["techniques"]
        assert analysis.vocabulary["classifications"] == stage15_summary["events"]["classifications"]

    def test_the_heuristics_are_stage15s(self, bundle: Dict[str, Any]) -> None:
        """Only note-length and density banding differ, and that is documented."""
        assert stage15.NOTE_SPLIT_SEMITONES == 4.0
        assert stage15.NOTE_MIN_FRAMES == 3
        assert stage16.note_length_band(3) == "short_1_3_frames"
        assert stage16.note_length_band(12) == "medium_4_12_frames"
        assert stage16.note_length_band(13) == "long_13_plus_frames"
        assert stage16.note_length_band(None) == "outside_note"
        assert stage16.density_band(0) == "sparse_0_2"
        assert stage16.density_band(99) == "dense_7_plus"
        assert stage16.company_band(0) == "alone"
        assert stage16.company_band(3) == "full"

    def test_every_song_is_summarised_with_normalised_measures(
        self, bundle: Dict[str, Any]
    ) -> None:
        songs = bundle["song_summaries"]["songs"]
        assert len(songs) == 4
        for song in songs:
            assert song["events"] > 0
            assert song["events_per_second"] > 0
            assert song["events_per_audible_channel_second"] > 0
            assert song["trace_sha256"]
            assert song["generator_distribution"]
            assert song["classifications"]

    def test_the_summaries_agree_with_the_technique_matrix(self, bundle: Dict[str, Any]) -> None:
        matrix = {row["technique_id"]: row for row in bundle["technique_overlap"]["matrix"]}
        for song in bundle["song_summaries"]["songs"]:
            total = sum(
                item["occurrences"] for item in song["techniques_per_1000_events"]
            )
            assert total == song["events"]
            for item in song["techniques_per_1000_events"]:
                assert (
                    matrix[item["technique_id"]]["songs"][song["slug"]]["occurrences"]
                    == item["occurrences"]
                )


# ---------------------------------------------------------------------------
# 4. Vocabulary overlap (Part D) and context generalisation (Part E)
# ---------------------------------------------------------------------------
@requires_corpus
class TestOverlapAndContext:
    def test_overlap_measures_are_bounded_and_pairwise_complete(
        self, bundle: Dict[str, Any]
    ) -> None:
        overlap = bundle["technique_overlap"]
        assert len(overlap["pairwise"]) == 6
        for pair in overlap["pairwise"]:
            for key in ("technique_jaccard", "technique_ruzicka_on_shares",
                        "event_class_jaccard"):
                assert 0.0 <= pair[key] <= 1.0
        assert overlap["summary"]["techniques_in_union"] == len(overlap["matrix"])

    def test_ruzicka_never_exceeds_jaccard_here(self, bundle: Dict[str, Any]) -> None:
        """Share weighting can only lower similarity when one song leans on a shared technique."""
        for pair in bundle["technique_overlap"]["pairwise"]:
            assert pair["technique_ruzicka_on_shares"] <= pair["technique_jaccard"] + 1e-9

    def test_format_counts_match_the_matrix(self, bundle: Dict[str, Any]) -> None:
        matrix = bundle["technique_overlap"]["matrix"]
        songs = bundle["technique_overlap"]["songs"]
        assert bundle["technique_overlap"]["summary"]["techniques_in_all_songs"] == sum(
            1 for row in matrix if all(row["songs"][slug]["occurrences"] > 0 for slug in songs)
        )
        assert bundle["technique_overlap"]["summary"]["techniques_in_one_song_only"] == sum(
            1 for row in matrix
            if sum(1 for slug in songs if row["songs"][slug]["occurrences"] > 0) == 1
        )

    def test_context_verdicts_are_decidable_or_explicitly_not(self, bundle: Dict[str, Any]) -> None:
        allowed = {
            "SAME_CONTEXT", "MOSTLY_SAME_CONTEXT", "MIXED_CONTEXT",
            "MOSTLY_DIFFERENT_CONTEXT", "DIFFERENT_CONTEXT", "NO_DECIDABLE_CONTEXT",
        }
        for row in bundle["context_generalization"]["techniques"]:
            assert row["overall_verdict"] in allowed
            assert row["dimensions_agreeing"] + row["dimensions_disagreeing"] <= (
                row["decidable_dimensions"]
            )
            for factor in stage16.PORTABLE_CONTEXT_FACTORS:
                assert row["factors"][factor]["verdict"] in {
                    "SAME_CONTEXT", "DIFFERENT_CONTEXT", "DIFFUSE_CONTEXT"
                }

    def test_a_context_verdict_follows_the_dominance_rule(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["context_generalization"]["techniques"]:
            for factor in stage16.PORTABLE_CONTEXT_FACTORS:
                entry = row["factors"][factor]
                concentrated = entry["concentrated_in_every_song"]
                shares = [value for value in entry["dominant_shares"].values() if value is not None]
                assert concentrated == all(
                    value >= stage16.CONTEXT_DOMINANCE_MIN for value in shares
                )
                if not concentrated:
                    assert entry["verdict"] == "DIFFUSE_CONTEXT"

    def test_song_local_dimensions_are_excluded(self, bundle: Dict[str, Any]) -> None:
        method = bundle["context_generalization"]["method"]
        assert set(method["song_local_factors_excluded"]) == set(
            stage16.SONG_LOCAL_CONTEXT_FACTORS
        )
        for name in method["song_local_factors_excluded"]:
            assert name not in method["portable_factors"]
        for row in bundle["context_generalization"]["by_factor"]:
            assert row["factor"] in stage16.PORTABLE_CONTEXT_FACTORS

    def test_factor_rows_cover_every_portable_dimension(self, bundle: Dict[str, Any]) -> None:
        factors = {row["factor"] for row in bundle["context_generalization"]["by_factor"]}
        assert factors == set(stage16.PORTABLE_CONTEXT_FACTORS)


# ---------------------------------------------------------------------------
# 5. Parameter generalisation (report 8) and leave-one-song-out (Part F)
# ---------------------------------------------------------------------------
@requires_corpus
class TestParametersAndLoo:
    def test_parameters_are_compared_like_for_like(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["parameter_generalization"]["techniques"]:
            for parameter in row["numeric_parameters"]:
                for pair in parameter["pairwise"]:
                    assert 0.0 <= pair["support_overlap"] <= 1.0
                    assert 0.0 <= pair["core_overlap"] <= 1.0
            for parameter in row["categorical_parameters"]:
                assert 0.0 <= parameter["median_overlap"] <= 1.0

    def test_parameter_verdicts_follow_their_threshold(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["parameter_generalization"]["techniques"]:
            if row["verdict"] == "PARAMETERS_GENERALISE":
                assert row["same_share"] >= 0.5
            if row["verdict"] == "PARAMETERS_SONG_SPECIFIC":
                assert row["same_share"] < 0.5

    def test_index_like_parameters_are_excluded_from_coverage(self) -> None:
        """A coverage test over note_index would be meaningless."""
        for name in ("note_index", "beat_index", "start_frame", "end_frame"):
            assert name in stage15.INDEX_LIKE_PARAMETERS

    def test_loo_trains_on_the_others(self, bundle: Dict[str, Any]) -> None:
        songs = {song["slug"] for song in bundle["song_summaries"]["songs"]}
        for fold in bundle["loo_results"]["folds"]:
            assert set(fold["train_songs"]) == songs - {fold["test_song"]}
            assert len(fold["train_songs"]) == 3

    def test_coverage_layers_are_ordered_and_bounded(self, bundle: Dict[str, Any]) -> None:
        for fold in bundle["loo_results"]["folds"]:
            for key in ("technique_coverage_events", "context_coverage_core_signature",
                        "parameter_coverage_in_support", "parameter_coverage_in_core",
                        "unknown_share", "context_dominant_match_core_mean"):
                assert 0.0 <= fold[key] <= 1.0
            assert fold["context_coverage_basis"]
            assert fold["parameter_coverage_basis"]
            # unknown share is the complement of technique coverage
            assert abs(fold["unknown_share"] - (1.0 - fold["technique_coverage_events"])) < 1e-6

    def test_context_coverage_is_reported_as_conditional(self, bundle: Dict[str, Any]) -> None:
        for fold in bundle["loo_results"]["folds"]:
            assert "conditional on" in fold["context_coverage_basis"]
            assert "conditional on" in fold["parameter_coverage_basis"]
            assert "prediction" in fold["context_coverage_core_signature_meaning"]

    def test_representativeness_uses_every_song_as_a_sole_reference(
        self, bundle: Dict[str, Any]
    ) -> None:
        representativeness = bundle["loo_results"]["representativeness"]
        songs = {song["slug"] for song in bundle["song_summaries"]["songs"]}
        assert {row["reference_song"] for row in representativeness["experiments"]} == songs
        for row in representativeness["experiments"]:
            assert len(row["folds"]) == 3
        assert representativeness["best_single_reference"] in songs
        assert representativeness["worst_single_reference"] in songs

    def test_representativeness_is_reported_not_assumed(self, bundle: Dict[str, Any]) -> None:
        answer = bundle["loo_results"]["representativeness"]["answer"]
        assert "single training song" in answer
        assert bundle["research_answers"][4]["question"].startswith("Q5")
        assert bundle["research_answers"][4]["answer"]


# ---------------------------------------------------------------------------
# 6. Universality (Part H), ambiguity (Part J), models (Part O), verdicts
# ---------------------------------------------------------------------------
@requires_corpus
class TestUniversalityAmbiguityAndVerdicts:
    def test_every_technique_gets_exactly_one_verdict(self, bundle: Dict[str, Any]) -> None:
        report = bundle["universality"]
        seen = (
            report["universal"] + report["common"] + report["song_specific"] + report["unknown"]
        )
        assert sorted(seen) == sorted(row["technique_id"] for row in report["techniques"])
        assert len(seen) == len(set(seen))

    def test_universal_needs_evidence_in_the_required_number_of_songs(
        self, bundle: Dict[str, Any]
    ) -> None:
        report = bundle["universality"]
        by_technique = {row["technique_id"]: row for row in report["techniques"]}
        for name in report["universal"]:
            row = by_technique[name]
            assert row["songs_with_evidence_count"] >= row["required_for_universal"]
            assert row["context_verdict"] in ("SAME_CONTEXT", "MOSTLY_SAME_CONTEXT")
            assert row["parameter_verdict"] == "PARAMETERS_GENERALISE"

    def test_low_level_universality_is_flagged(self, bundle: Dict[str, Any]) -> None:
        """The brief's trap: a universal schema is not a universal style."""
        report = bundle["universality"]
        by_technique = {row["technique_id"]: row for row in report["techniques"]}
        for name in report["universal_non_low_level"]:
            assert by_technique[name]["low_level"] is False
        assert set(report["universal_non_low_level"]).issubset(set(report["universal"]))
        for name in stage16.LOW_LEVEL_TECHNIQUES:
            if name in by_technique:
                assert by_technique[name]["low_level"] is True

    def test_song_specific_means_one_song(self, bundle: Dict[str, Any]) -> None:
        by_technique = {row["technique_id"]: row for row in bundle["universality"]["techniques"]}
        for name in bundle["universality"]["song_specific"]:
            assert by_technique[name]["songs_with_evidence_count"] == 1

    def test_ambiguity_reports_real_conflicts(self, bundle: Dict[str, Any]) -> None:
        ambiguity = bundle["ambiguity"]
        for row in ambiguity["same_technique_different_context"]:
            assert row["overall_verdict"] in ("DIFFERENT_CONTEXT", "MOSTLY_DIFFERENT_CONTEXT")
            assert row["conflicting_factors"]
            for factor, detail in row["conflicting_factors"].items():
                assert len(set(detail["songs"].values())) > 1
            for example in row["examples"]:
                assert example["example_event"]["evidence"]

    def test_a_generator_shift_is_reported_with_its_song_map(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["ambiguity"]["same_event_kind_different_generator"]:
            assert len(set(row["dominant_generator_by_song"].values())) > 1
            assert row["distributions"]

    def test_the_generalisation_levels_are_judged_separately(self, bundle: Dict[str, Any]) -> None:
        levels = bundle["generalization_levels"]["levels"]
        assert {row["level"] for row in levels} == {
            "SCHEMA_GENERALISATION", "TECHNIQUE_GENERALISATION",
            "CONTEXT_GENERALISATION", "PARAMETER_GENERALISATION",
        }
        for row in levels:
            assert isinstance(row["supported"], bool)
            assert row["value"] is None or 0.0 <= row["value"] <= 1.0
        assert bundle["generalization_levels"]["why_separate"]

    def test_the_model_verdict_follows_the_stated_rule(self, bundle: Dict[str, Any]) -> None:
        models = bundle["model_comparison"]
        conditions = models["model_a_conditions"]
        if all(conditions.values()):
            assert models["model"] == "UNIVERSAL_STYLE_MODEL_SUPPORTED"
        elif all(models["model_c_conditions"].values()):
            assert models["model"] == "MOSTLY_SONG_SPECIFIC_MODEL_SUPPORTED"
        else:
            assert models["model"] in (
                "VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED", "INSUFFICIENT_EVIDENCE"
            )

    def test_the_two_verdicts_are_independent(self, bundle: Dict[str, Any]) -> None:
        verdicts = bundle["verdicts"]
        assert verdicts["generalization"]["verdict"] in {
            "GENERALIZATION_SUPPORTED", "GENERALIZATION_PARTIALLY_SUPPORTED",
            "GENERALIZATION_NOT_SUPPORTED",
        }
        assert verdicts["model"]["verdict"] in {
            "UNIVERSAL_STYLE_MODEL_SUPPORTED", "VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED",
            "MOSTLY_SONG_SPECIFIC_MODEL_SUPPORTED", "INSUFFICIENT_EVIDENCE",
        }
        assert verdicts["independence_note"]

    def test_no_aggregate_score_is_offered(self, bundle: Dict[str, Any]) -> None:
        vector = bundle["transferability_vector"]
        assert set(vector["vector"]) == {
            "technique_coverage", "context_coverage", "parameter_coverage",
            "semantic_stability", "cross_song_consistency", "unknown_behaviour",
        }
        assert "aggregate" not in vector
        assert "no aggregate score" in vector["why_no_aggregate_score"].lower() or (
            "The vector is the result" in vector["why_no_aggregate_score"]
        )
        assert "A weighted total" in vector["why_no_aggregate_score"]

    def test_the_reused_analysis_is_deterministic_between_processes(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The one cross-process guarantee this stage depends on, proven by re-running it."""
        import subprocess
        import sys

        script = (
            "import json,sys;"
            "sys.path.insert(0, r'" + str(stage16.REPO_ROOT / "src") + "');"
            "from atari_music import stage15, stage16;"
            "c={x.slug:x for x in stage16.corpus_candidates()};"
            "a=stage16.analyse_song(c[stage16.SONG_A_SLUG]);"
            "print(json.dumps([a.event_count, len(a.indexes_by_technique),"
            " {k: v for k, v in sorted(a.vocabulary['classifications'].items())}]))"
        )
        runs = {
            subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True, check=True
            ).stdout.strip()
            for _ in range(2)
        }
        assert len(runs) == 1, f"analysis differed between processes: {runs}"
        payload = json.loads(next(iter(runs)))
        assert payload[0] == bundle["song_summaries"]["songs"][0]["events"]

    def test_the_determinism_fix_is_disclosed(self, bundle: Dict[str, Any]) -> None:
        assert "tie-break" in bundle["determinism_fix_note"]
        assert "regenerated" in bundle["determinism_fix_note"]
        assert "defect found in the reused analysis" in stage16.render_report(bundle)


# ---------------------------------------------------------------------------
# 7. The style model, player implications, the report and the CLI
# ---------------------------------------------------------------------------
@requires_corpus
class TestModelPlayerReportAndCli:
    def test_the_style_model_is_research_not_production(self, bundle: Dict[str, Any]) -> None:
        style = bundle["style_model"]
        assert style["artifact"] == "CrossSongPerformanceStyle"
        assert "research-only" in style["status"]
        assert "not a SoundProfile" in style["status"]
        assert style["provenance"]["songs"]
        assert style["belongs_in_the_style"]["common_techniques"]
        assert style["must_stay_attached_to_the_source_song"]
        for key in ("instruments", "instrument", "profile_id", "playable"):
            assert key not in style

    def test_every_song_carries_its_provenance(self, bundle: Dict[str, Any]) -> None:
        for song in bundle["style_model"]["provenance"]["songs"]:
            assert song["trace_sha256"]
            assert song["slug"]

    def test_player_implications_reuse_stage15_mechanisms(self, bundle: Dict[str, Any]) -> None:
        player = bundle["player_implications"]
        for row in player["techniques"]:
            assert row["stage15_mechanism"]
            assert row["conceptual_command"]
            if row["low_level"]:
                assert row["technique_id"] not in player["common_techniques"]
        assert player["minimal_command_set"]
        assert "nothing about player size" not in player["answer"]
        assert player["ambiguity_pressure"] == len(
            bundle["ambiguity"]["same_technique_different_context"]
        )

    def test_the_report_has_the_nineteen_required_sections(self, bundle: Dict[str, Any]) -> None:
        text = stage16.render_report(bundle)
        required = [
            "## 1. Executive summary",
            "## 2. Research question",
            "## 3. Input songs and deterministic selection",
            "## 4. Analysis methodology",
            "## 5. Per-song event and technique overview",
            "## 6. Technique vocabulary overlap",
            "## 7. Context generalisation",
            "## 8. Parameter generalisation",
            "## 9. Leave-one-song-out results",
            "## 10. Universal vs common vs song-specific techniques",
            "## 11. Ambiguous low-level behaviours",
            "## 12. Cross-song style model",
            '## 13. Alternative "vocabulary + grammar" model',
            "## 14. Player implications",
            "## 15. Answers to the research questions",
            "## 16. Limitations",
            "## 17. Stage 16 verdict",
            "## 18. What should NOT be built yet",
            "## 19. Candidate Stage 17 experiments",
        ]
        positions = [text.index(section) for section in required]
        assert positions == sorted(positions)

    def test_the_report_states_both_verdicts(self, bundle: Dict[str, Any]) -> None:
        text = stage16.render_report(bundle)
        assert bundle["verdicts"]["generalization"]["verdict"] in text
        assert bundle["verdicts"]["model"]["verdict"] in text

    def test_twelve_questions_are_answered(self, bundle: Dict[str, Any]) -> None:
        answers = bundle["research_answers"]
        assert len(answers) == 12
        for index, item in enumerate(answers, start=1):
            assert item["question"].startswith(f"Q{index} ")
            assert len(item["answer"]) > 40

    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "analyze-stage16" in result.output

    def test_the_command_runs_and_writes_only_its_own_output(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["analyze-stage16", "--reports-dir", str(tmp_path / "r"),
             "--docs-dir", str(tmp_path / "d")],
        )
        if not stage16.DEFAULT_ARCHAEOLOGY_DIR.is_dir():  # pragma: no cover
            pytest.skip("no corpus on this machine")
        assert result.exit_code == 0, result.output
        assert "Songs:" in result.output
        assert "Leave-one-song-out:" in result.output
        written = sorted(path.name for path in (tmp_path / "r").iterdir())
        assert written == sorted(stage16.STAGE16_FILES)
        assert (tmp_path / "d" / stage16.STAGE16_DOC).is_file()
        summary = json.loads((tmp_path / "r" / "summary.json").read_text(encoding="utf-8"))
        assert summary["verdicts"]["generalization"]["verdict"]

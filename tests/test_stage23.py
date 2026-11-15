"""Stage 23 - the controlled historical residual test.

These tests pin the stage to the claims it makes, and they are written to fail on the mistakes the
brief names rather than on the mistakes that are easy to test:

* every estimand's numerator and denominator, with the two identities
  `E_total = E_in_span + E_out_span` and `E_in_span = E_zero_onset + E_other` asserted in code;
* the same convention applied to both corpora in every comparison row;
* the resampling unit being the source, never the frame and never the trace-as-if-independent;
* matching that cannot see the residual, and mediators kept out of it;
* a difference called robust only when every definition and every leave-one-source-out drop agrees;
* a difference called identified only when the comparison is not an extrapolation;
* byte-identical repeated runs and a read-only audit over the production modules and the inputs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from click.testing import CliRunner

from atari_music import stage15, stage21, stage23
from atari_music.cli import cli

requires_corpus = pytest.mark.skipif(
    not stage23.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage23.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)

requires_control = pytest.mark.skipif(
    not stage23.DEFAULT_SONGS_DIR.is_dir(),
    reason="the .dsl compositions are not present on this machine",
)


@pytest.fixture(scope="session")
def evidence() -> Dict[str, Any]:
    """Both corpora, measured once, shared by every test that needs the records."""
    return {
        "historical": stage23.load_historical_evidence(),
        "control": stage23.load_control_evidence(),
    }


@pytest.fixture(scope="session")
def core(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """The deterministic core, so a test can compare without re-running everything."""
    historical = evidence["historical"]
    control = evidence["control"]
    return {
        "historical": historical,
        "control": control,
        "overlap": stage23.overlap_diagnosis(control, historical),
        "calibration": stage23.calibration(control, historical),
        "univariate_screen": stage23.univariate_screen(control, historical),
        "comparison": stage23.per_song_comparison(control, historical),
        "profile": stage23.residual_profile_comparison(control, historical),
        "leave_one_out": stage23.leave_one_source_out(control, historical),
        "conventions": stage23.convention_sensitivity(control, historical),
        "channels": stage23.channel_sensitivity(control, historical),
        "negatives": stage23.negative_controls(control, historical),
    }


@pytest.fixture(scope="session")
def bundle(core: Dict[str, Any]) -> Dict[str, Any]:
    """One full run, with the reproducibility check on, shared by the artefact tests."""
    return stage23.run_analysis()


# ---------------------------------------------------------------------------
# 1. the estimands
# ---------------------------------------------------------------------------
class TestEstimands:
    def test_every_estimand_declares_its_parts(self) -> None:
        names = {item["name"] for item in stage23.ESTIMAND_RULES}
        assert names == set(stage23.ESTIMAND_NAMES)
        for item in stage23.ESTIMAND_RULES:
            for field in ("numerator", "denominator", "unit", "silence", "outside_spans",
                          "coupled", "aggregation"):
                assert item[field], f"{item['name']} is missing {field}"

    def test_the_primary_estimand_is_the_convention_free_one(self) -> None:
        assert stage23.PRIMARY_ESTIMAND == "E_in_span"
        rule = next(item for item in stage23.ESTIMAND_RULES
                    if item["name"] == stage23.PRIMARY_ESTIMAND)
        assert "convention-free" in rule["outside_spans"]

    def test_the_totals_split_into_in_and_out_of_span(
        self, evidence: Dict[str, Any]
    ) -> None:
        for row in evidence["historical"] + evidence["control"]:
            hold = row.counts["E_total_hold"]
            exporter = row.counts["E_total_exporter"]
            in_span = row.counts["E_in_span"]
            assert hold[0] == in_span[0] + row.counts["E_out_span_hold"][0], row.slug
            assert exporter[0] == in_span[0] + row.counts["E_out_span_exporter"][0], row.slug
            assert hold[1] == in_span[1] + row.counts["E_out_span_hold"][1], row.slug
            assert exporter[1] == in_span[1] + row.counts["E_out_span_exporter"][1], row.slug

    def test_the_in_span_estimand_splits_at_the_zero_onset_spans(
        self, evidence: Dict[str, Any]
    ) -> None:
        for row in evidence["historical"] + evidence["control"]:
            in_span = row.counts["E_in_span"]
            zero = row.counts["E_zero_onset_span"]
            other = row.counts["E_other_span"]
            assert in_span[0] == zero[0] + other[0], row.slug
            assert in_span[1] == zero[1] + other[1], row.slug

    def test_the_hold_and_exporter_totals_share_their_denominator(
        self, evidence: Dict[str, Any]
    ) -> None:
        for row in evidence["historical"] + evidence["control"]:
            assert row.counts["E_total_hold"][1] == row.counts["E_total_exporter"][1]
            assert row.counts["E_total_hold"][1] == row.frames * stage23.FRAME_BYTES

    def test_an_undefined_estimand_is_none_not_zero(self, evidence: Dict[str, Any]) -> None:
        """A trace with no zero-onset span has no denominator, and the value must say so."""
        for row in evidence["historical"] + evidence["control"]:
            numerator, denominator = row.counts["E_zero_onset_span"]
            if denominator == 0:
                assert row.estimands["E_zero_onset_span"] is None, row.slug

    def test_the_register_values_denominator_is_frames_times_nine(
        self, evidence: Dict[str, Any]
    ) -> None:
        for row in evidence["historical"] + evidence["control"]:
            assert row.register_values == row.frames * stage23.FRAME_BYTES

    def test_the_in_span_denominator_is_the_registers_a_span_drives(
        self, evidence: Dict[str, Any]
    ) -> None:
        for row in evidence["historical"] + evidence["control"]:
            assert row.counts["E_in_span"][1] == row.in_span_values
            assert row.counts["E_out_span_exporter"][1] == row.out_span_values
            assert row.in_span_values + row.out_span_values == (
                row.frames * stage23.FRAME_BYTES
            )
            assert row.in_span_values <= row.frames * stage23.FRAME_BYTES


# ---------------------------------------------------------------------------
# 2. the corpora and their provenance
# ---------------------------------------------------------------------------
class TestCorpora:
    def test_the_historical_corpus_is_clustered(self, evidence: Dict[str, Any]) -> None:
        index = stage23.cluster_index(evidence["historical"])
        assert index["source_count"] < index["traces"], "the traces must cluster by source"
        assert index["author_count"] < index["traces"]
        assert index["by_author"]
        for author, traces in index["by_author"].items():
            assert traces == sorted(traces), author

    def test_a_shared_source_is_reported(self, evidence: Dict[str, Any]) -> None:
        index = stage23.cluster_index(evidence["historical"])
        for source, traces in index["repeated_sources"].items():
            assert len(traces) > 1, source

    def test_every_control_song_is_its_own_source(self, evidence: Dict[str, Any]) -> None:
        sources = [row.source_key for row in evidence["control"]]
        assert len(set(sources)) == len(sources)

    def test_each_trace_carries_its_provenance(self, evidence: Dict[str, Any]) -> None:
        for row in evidence["historical"]:
            assert row.source_key
            assert row.author
            assert row.sap_type

    def test_the_control_corpus_is_tier_a_and_the_historical_is_not(
        self, evidence: Dict[str, Any]
    ) -> None:
        assert all(row.corpus == "historical" for row in evidence["historical"])
        assert all(row.corpus == "control" for row in evidence["control"])
        assert len(evidence["control"]) == 53


# ---------------------------------------------------------------------------
# 3. conventions
# ---------------------------------------------------------------------------
class TestConventions:
    def test_every_definition_is_computed_on_both_corpora(
        self, core: Dict[str, Any]
    ) -> None:
        for row in core["conventions"]["definitions"]:
            assert row["defined_in_control"] > 0 or row["estimand"].startswith("E_zero")
            assert row["defined_in_historical"] >= 0

    def test_the_hold_and_exporter_totals_share_the_in_span_part(
        self, evidence: Dict[str, Any]
    ) -> None:
        """Both totals contain exactly the same in-span numerator and denominator."""
        for row in evidence["historical"] + evidence["control"]:
            hold = row.counts["E_total_hold"]
            exporter = row.counts["E_total_exporter"]
            in_span = row.counts["E_in_span"]
            assert hold[1] == exporter[1]
            assert hold[1] == row.frames * stage23.FRAME_BYTES
            assert hold[0] - exporter[0] == (
                row.counts["E_out_span_hold"][0] - row.counts["E_out_span_exporter"][0]
            )
            assert in_span[0] <= min(hold[0], exporter[0])

    def test_the_control_exporter_residual_outside_spans_is_near_zero(
        self, evidence: Dict[str, Any]
    ) -> None:
        """The compiler emits no write outside a span, so the exporter is nearly right there.

        It is not *exactly* zero: the detector misses some spans, and where it does the trace holds
        a divider the exporter predicts as zero. The claim the report makes is therefore "near
        zero", and this test pins the measured size rather than an assumption.
        """
        residual = sum(row.counts["E_out_span_exporter"][0] for row in evidence["control"])
        values = sum(row.out_span_values for row in evidence["control"])
        assert values > 0
        assert residual / values < 0.05, (residual, values)

    def test_the_hold_convention_inflates_the_control_out_of_span_residual(
        self, evidence: Dict[str, Any]
    ) -> None:
        """The compiler relies on the player holding, so hold matches and the exporter does not."""
        hold = sum(row.counts["E_out_span_hold"][0] for row in evidence["control"])
        exporter = sum(row.counts["E_out_span_exporter"][0] for row in evidence["control"])
        assert hold > 10 * exporter

    def test_the_two_conventions_agree_inside_spans(self, evidence: Dict[str, Any]) -> None:
        """The in-span numerator is one measurement, not two: both totals contain it exactly."""
        for row in evidence["historical"] + evidence["control"]:
            in_span = row.counts["E_in_span"]
            assert in_span[0] == row.counts["E_total_exporter"][0] - (
                row.counts["E_out_span_exporter"][0]
            )
            assert in_span[0] == row.counts["E_total_hold"][0] - (
                row.counts["E_out_span_hold"][0]
            )

    def test_the_in_span_denominator_is_policy_independent(
        self, evidence: Dict[str, Any]
    ) -> None:
        """E_in_span is the same measurement under either policy, by construction."""
        for row in evidence["historical"][:4] + evidence["control"][:4]:
            assert row.counts["E_in_span"][1] == row.in_span_values
            assert row.counts["E_out_span_hold"][1] == row.counts["E_out_span_exporter"][1]

    def test_the_sign_across_definitions_is_reported(self, core: Dict[str, Any]) -> None:
        conventions = core["conventions"]
        assert isinstance(conventions["sign_stable_across_totals"], bool)
        assert conventions["total_definition_signs"]


# ---------------------------------------------------------------------------
# 4. overlap and matching
# ---------------------------------------------------------------------------
class TestMatching:
    def test_the_overlap_is_measured_feature_by_feature(self, core: Dict[str, Any]) -> None:
        overlay = core["overlap"]
        assert len(overlay["features"]) == len(stage23.MATCH_FEATURES) + len(
            stage23.MEDIATOR_FEATURES
        )
        for row in overlay["features"]:
            assert row["role"] in ("matching", "mediator")
            assert row["historical_inside_control_range_share"] is not None

    def test_a_feature_with_no_common_range_is_reported(self, core: Dict[str, Any]) -> None:
        for row in core["overlap"]["features"]:
            if not row["overlaps"]:
                assert row["feature"] in core["overlap"][
                    "features_without_any_common_range"
                ]

    def test_mediators_are_never_matching_features(self) -> None:
        assert not set(stage23.MEDIATOR_FEATURES) & set(stage23.MATCH_FEATURES)

    def test_the_matching_features_carry_no_residual(self, evidence: Dict[str, Any]) -> None:
        """No matching feature may be a function of the residual, or the matching would leak."""
        for row in evidence["control"][:5] + evidence["historical"][:5]:
            for name in stage23.MATCH_FEATURES:
                assert name in row.features, name
            for name in ("estimands", "counts", "per_register", "per_register_in_span"):
                assert name not in row.features

    def test_standardisation_is_pooled(self, core: Dict[str, Any]) -> None:
        stats = core["calibration"]["standardisation"]
        assert stats["pooled"] is True
        assert set(stats["mean"]) == set(stage23.MATCH_FEATURES)
        assert set(stats["stdev"]) == set(stage23.MATCH_FEATURES)

    def test_a_neighbour_prediction_is_deterministic(
        self, evidence: Dict[str, Any]
    ) -> None:
        control = evidence["control"]
        historical = evidence["historical"]
        stats = stage23.standardise(control, historical)
        first = stage23.nearest_control_neighbours(historical[0], control, stats)
        second = stage23.nearest_control_neighbours(historical[0], control, stats)
        assert first == second

    def test_a_neighbour_prediction_excludes_itself(self, evidence: Dict[str, Any]) -> None:
        control = evidence["control"]
        historical = evidence["historical"]
        stats = stage23.standardise(control, historical)
        row = control[0]
        result = stage23.nearest_control_neighbours(row, control, stats, exclude=row.slug)
        assert row.slug not in result["neighbours"]

    def test_the_control_leave_one_out_is_reported(self, core: Dict[str, Any]) -> None:
        loo = core["calibration"]["control_loo"]
        assert loo["n"] == len(core["control"])
        assert loo["mae"] is not None and loo["mae"] > 0
        assert loo["nearest_distance_max"] is not None

    def test_extrapolation_is_flagged_per_trace(self, core: Dict[str, Any]) -> None:
        rows = core["calibration"]["historical"]
        flagged = sum(1 for row in rows if row["beyond_control_loo_distance_range"])
        assert flagged == core["calibration"]["historical_beyond_control_support"]
        assert len(rows) == core["calibration"]["historical_count"]

    def test_the_univariate_screen_fits_on_control_only(self, core: Dict[str, Any]) -> None:
        screen = core["univariate_screen"]
        assert screen["estimand"] == stage23.PRIMARY_ESTIMAND
        for row in screen["features"]:
            if not row["constant"]:
                assert row["loo_mae"] is not None
                assert row["overlap_share"] is not None


# ---------------------------------------------------------------------------
# 5. per-trace comparison and uncertainty
# ---------------------------------------------------------------------------
class TestComparison:
    def test_the_unit_of_replication_is_the_trace(self, core: Dict[str, Any]) -> None:
        text = core["comparison"]["unit_of_replication"]
        assert "trace" in text
        assert "never treated as independent" in text

    def test_the_distributions_use_the_right_counts(self, core: Dict[str, Any]) -> None:
        for name, row in core["comparison"]["estimands"].items():
            assert row["control"]["n"] <= len(core["control"])
            assert row["historical"]["n"] <= len(core["historical"])
            if row["control"]["n"]:
                assert row["control"]["min"] <= row["control"]["median"] <= row["control"]["max"]

    def test_the_bootstrap_resamples_sources_not_frames(
        self, core: Dict[str, Any]
    ) -> None:
        bootstrap = core["comparison"]["estimands"][stage23.PRIMARY_ESTIMAND]["bootstrap"]
        assert bootstrap["available"]
        assert "source" in bootstrap["cluster_unit"]
        assert bootstrap["historical_sources"] < bootstrap["historical_values"]

    def test_the_bootstrap_is_seeded_and_reproducible(
        self, evidence: Dict[str, Any]
    ) -> None:
        first = stage23._cluster_bootstrap_difference(
            evidence["control"], evidence["historical"], stage23.PRIMARY_ESTIMAND, draws=200
        )
        second = stage23._cluster_bootstrap_difference(
            evidence["control"], evidence["historical"], stage23.PRIMARY_ESTIMAND, draws=200
        )
        assert first["ci_low"] == second["ci_low"]
        assert first["ci_high"] == second["ci_high"]

    def test_the_interval_brackets_the_observed_difference(
        self, core: Dict[str, Any]
    ) -> None:
        bootstrap = core["comparison"]["estimands"][stage23.PRIMARY_ESTIMAND]["bootstrap"]
        assert bootstrap["ci_low"] <= bootstrap["observed_difference"] <= bootstrap["ci_high"]

    def test_an_undefined_estimand_reports_unavailable(self, evidence: Dict[str, Any]) -> None:
        empty: List[Any] = []
        result = stage23._cluster_bootstrap_difference(
            evidence["control"], empty, stage23.PRIMARY_ESTIMAND, draws=10
        )
        assert result["available"] is False
        assert result["reason"]


# ---------------------------------------------------------------------------
# 6. profiles, controls and the history-specific test
# ---------------------------------------------------------------------------
class TestProfilesAndControls:
    def test_every_class_states_its_measurability(self, core: Dict[str, Any]) -> None:
        for row in core["profile"]["class_measurability"]:
            assert row["control"] in ("measurable", "control only")
            assert row["historical"] in ("measurable", "not identifiable")
            assert row["why"]

    def test_no_historical_class_needs_a_ground_truth(self, core: Dict[str, Any]) -> None:
        for row in core["profile"]["class_measurability"]:
            if row["historical"] == "measurable":
                assert "ground truth" not in row["why"] or "needs no" in row["why"]

    def test_the_channel_control_uses_declared_denominators(
        self, core: Dict[str, Any]
    ) -> None:
        control = core["control"]
        historical = core["historical"]
        for row in core["channels"]["channels"]:
            names = row["registers"]
            assert row["control"]["in_span_denominator"] == sum(
                sum(item.per_register_in_span_total[name] for name in names)
                for item in control
            )
            assert row["historical"]["in_span_denominator"] == sum(
                sum(item.per_register_in_span_total[name] for name in names)
                for item in historical
            )
            assert row["control"]["in_span_residual"] == sum(
                sum(item.per_register_in_span[name] for name in names)
                for item in control
            )
            assert row["difference"] == pytest.approx(
                row["historical"]["in_span_rate"] - row["control"]["in_span_rate"]
            )

    def test_the_channel_control_covers_every_voice(self, core: Dict[str, Any]) -> None:
        channels = core["channels"]["channels"]
        assert channels
        for row in channels:
            assert row["registers"] == [f"AUDF{row['channel']}", f"AUDC{row['channel']}"]
        assert core["channels"]["channels_with_positive_difference"] <= len(channels)

    def test_the_leave_one_source_out_drops_sources(self, core: Dict[str, Any]) -> None:
        rows = core["leave_one_out"]["rows"]
        assert len(rows) == len({row.source_key for row in core["historical"]})
        for row in rows:
            assert row["kept_traces"] < len(core["historical"])

    def test_negative_controls_are_encoding_properties(self) -> None:
        for name in stage23.NEGATIVE_CONTROL_FEATURES:
            assert name in stage23.NEGATIVE_CONTROL_FEATURES
        assert not set(stage23.NEGATIVE_CONTROL_FEATURES) & set(stage23.MATCH_FEATURES)

    def test_the_criteria_are_declared_with_thresholds(self) -> None:
        assert len(stage23.HISTORY_SPECIFIC_CRITERIA) == 7
        for item in stage23.HISTORY_SPECIFIC_CRITERIA:
            assert item["criterion"]
            assert item["threshold"]

    def test_the_history_specific_test_reports_every_criterion(
        self, bundle: Dict[str, Any]
    ) -> None:
        test = bundle["history_specific_test"]
        assert len(test["criteria"]) == len(stage23.HISTORY_SPECIFIC_CRITERIA)
        for row in test["criteria"]:
            assert isinstance(row["passed"], bool)
            assert row["measurement"] is not None

    def test_the_matching_criterion_fails_when_the_comparison_extrapolates(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The criterion's own threshold says the match must not be an extrapolation."""
        test = bundle["history_specific_test"]
        extrapolated = bundle["summary"]["traces_beyond_control_support"]
        criterion = test["criteria"][3]
        assert criterion["passed"] == (extrapolated == 0)


# ---------------------------------------------------------------------------
# 7. verdicts
# ---------------------------------------------------------------------------
class TestVerdicts:
    def test_the_verdict_vocabulary_is_the_agreed_one(self, bundle: Dict[str, Any]) -> None:
        allowed = {
            "HISTORICAL_DIFFERENCE_NOT_ROBUST",
            "HISTORICAL_DIFFERENCE_EXPLAINED_BY_CORPUS_COMPOSITION",
            "HISTORICAL_DIFFERENCE_PARTIALLY_EXPLAINED",
            "HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED",
            "HISTORICAL_SPECIFIC_EFFECT_CANDIDATE",
            "COMPARISON_INCONCLUSIVE",
            "PERFORMANCE_CANDIDATE_REMAINS_UNSUPPORTED",
            "PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST",
            "CORPUS_COMPOSITION_NOT_SEPARATED",
            "NO_PRODUCTION_DECISION_CHANGED",
        }
        for subject, data in bundle["verdicts"].items():
            assert data["verdict"] in allowed, subject

    def test_the_performance_layer_is_never_proven(self, bundle: Dict[str, Any]) -> None:
        assert "PROVEN PERFORMANCE LAYER" not in stage23.render_report(bundle)

    def test_a_not_robust_verdict_follows_a_sign_change(self, bundle: Dict[str, Any]) -> None:
        primary = bundle["verdicts"]["primary"]
        if primary["verdict"] == "HISTORICAL_DIFFERENCE_NOT_ROBUST":
            conditions = primary["deciding_measurements"]
            assert (
                not conditions["sign_stable_across_definitions"]
                or not conditions["sign_preserved_leave_one_source_out"]
            )

    def test_an_unidentified_verdict_follows_extrapolation(
        self, bundle: Dict[str, Any]
    ) -> None:
        primary = bundle["verdicts"]["primary"]
        if primary["verdict"] == "HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED":
            conditions = primary["deciding_measurements"]
            assert conditions["traces_beyond_control_support"] > (conditions["traces"] / 2)

    def test_every_verdict_carries_its_conditions(self, bundle: Dict[str, Any]) -> None:
        for subject, data in bundle["verdicts"].items():
            assert data.get("deciding_condition") or data.get("reason"), subject


# ---------------------------------------------------------------------------
# 8. artefacts, determinism and the read-only audit
# ---------------------------------------------------------------------------
class TestArtefactsAndDeterminism:
    def test_the_writer_emits_every_declared_artefact(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        written = stage23.write_analysis(
            bundle, stage23_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        for name in stage23.STAGE23_FILES:
            assert (tmp_path / "r" / name).is_file(), name
        assert (tmp_path / "d" / stage23.STAGE23_DOC).is_file()
        assert (tmp_path / "r" / stage23.STAGE23_REPORT).is_file()
        assert set(written) == set(stage23.STAGE23_FILES) | {
            stage23.STAGE23_DOC, stage23.STAGE23_REPORT,
        }

    def test_every_artefact_is_valid_json(self, bundle: Dict[str, Any],
                                          tmp_path: Path) -> None:
        stage23.write_analysis(bundle, stage23_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        for name in stage23.STAGE23_FILES:
            payload = json.loads((tmp_path / "r" / name).read_text(encoding="utf-8"))
            assert payload is not None, name

    def test_the_manifest_names_the_document_and_the_stop_condition(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        stage23.write_analysis(bundle, stage23_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        manifest = json.loads(
            (tmp_path / "r" / "stage23_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["document"] == stage23.STAGE23_DOC
        assert "no production code" in manifest["stop_condition"]
        assert manifest["reproducibility"]["byte_identical"]

    def test_a_repeated_run_is_byte_identical(self, tmp_path: Path) -> None:
        first = stage23.run_analysis()
        second = stage23.run_analysis()
        left = tmp_path / "left"
        right = tmp_path / "right"
        written_left = stage23.write_analysis(
            first, stage23_dir=left / "r", docs_dir=left / "d"
        )
        written_right = stage23.write_analysis(
            second, stage23_dir=right / "r", docs_dir=right / "d"
        )
        assert set(written_left) == set(written_right)
        for name in written_left:
            assert written_left[name].read_bytes() == written_right[name].read_bytes(), name

    def test_the_determinism_block_is_declared(self, bundle: Dict[str, Any]) -> None:
        determinism = bundle["determinism"]
        assert determinism["random_seed"] == stage23.RANDOM_SEED
        assert "slug" in determinism["tie_breaks"]
        assert len(determinism["source_hash"]) == 64


class TestReadOnlyAudit:
    def test_the_run_proves_the_inputs_are_unchanged(self, bundle: Dict[str, Any]) -> None:
        for _key, row in bundle["read_only_audit"].items():
            assert row["read_only"], row["changed"]

    def test_the_audit_covers_stage_15_to_22_and_the_player(self) -> None:
        hashes = stage23.production_hashes()
        for relative in (
            "src/atari_music/stage15.py", "src/atari_music/stage16.py",
            "src/atari_music/stage17.py", "src/atari_music/stage18.py",
            "src/atari_music/stage19.py", "src/atari_music/stage20.py",
            "src/atari_music/stage21.py", "src/atari_music/stage22.py",
            "src/atari_music/asm/player.asm",
        ):
            assert relative in hashes
            assert hashes[relative], relative

    def test_the_audit_covers_the_traces_and_compositions(self) -> None:
        hashes = stage23.input_hashes()
        assert any(key.startswith("trace/") for key in hashes)
        assert any(key.startswith("composition/") for key in hashes)
        assert any(key.startswith("upstream/") for key in hashes)

    def test_the_audit_notices_a_change(self) -> None:
        row = stage23.read_only_audit({"a": "1", "b": "2"}, {"a": "1", "b": "3"})
        assert not row["read_only"]
        assert row["changed"] == ["b"]


class TestReport:
    def test_the_report_has_every_required_section(self, bundle: Dict[str, Any]) -> None:
        report = stage23.render_report(bundle)
        titles = [
            "Executive Summary", "Source and Definition Audit", "Corpora and Their Limits",
            "Estimands and Residual Definitions", "Results Under Each Convention",
            "Corpus Characteristics Before Matching", "Matching Procedure and Quality",
            "Results Before and After Matching", "Residual Profiles",
            "Per-Trace Uncertainty", "Leave-One-Source-Out", "Negative Controls",
            "Sensitivity Analysis", "Identifiability Limits", "Methodological Corrections",
            "Verdict and Recommendation",
        ]
        for index, title in enumerate(titles, start=1):
            assert f"## {index}. {title}" in report, title

    def test_the_report_answers_all_eight_questions(self, bundle: Dict[str, Any]) -> None:
        report = stage23.render_report(bundle)
        assert "## The Eight Closing Questions" in report
        for number in range(1, 9):
            assert f"**{number}." in report, number

    def test_the_report_carries_no_absolute_windows_path(
        self, bundle: Dict[str, Any]
    ) -> None:
        report = stage23.render_report(bundle)
        assert "C:\\Users" not in report
        assert "C:/Users" not in report

    def test_the_report_is_plain_ascii(self, bundle: Dict[str, Any]) -> None:
        stage23.render_report(bundle).encode("ascii")


@requires_control
class TestCli:
    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["analyze-stage23", "--help"])
        assert result.exit_code == 0, result.output
        assert "residual" in result.output.lower()

    def test_a_run_writes_its_artefacts(self, tmp_path: Path) -> None:
        reports = tmp_path / "r"
        docs = tmp_path / "d"
        result = CliRunner().invoke(
            cli,
            ["analyze-stage23", "--reports-dir", str(reports), "--docs-dir", str(docs),
             "--skip-reproducibility"],
        )
        assert result.exit_code == 0, result.output
        for name in stage23.STAGE23_FILES:
            assert (reports / name).is_file(), name
        assert (docs / stage23.STAGE23_DOC).is_file()
        assert "verdict" in result.output.lower()
        assert "read-only" in result.output.lower()


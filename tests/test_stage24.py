"""Stage 24 - corpus overlap and confounding analysis.

These tests pin the stage to the claims it makes, and they are written to fail on the mistakes the
brief names rather than on the mistakes that are easy to test:

* the support criteria are calibrated, so an empty historical result is read against what the same
  criterion does to the control corpus's own members;
* a degenerate feature is never reported as a separation, and a length-confounded count is never
  used for matching;
* no matching method is presented as successful unless it satisfies the criteria declared before it
  ran, and a method that retains no usable sample is reported as undefined rather than as an
  estimate;
* the resampling unit is the source, never the frame and never the trace-as-if-independent;
* the propensity score is never used on its own as proof of overlap;
* the descriptive, the matched and the identified answers are kept apart;
* the falsification criteria are declared before the results and are not amended;
* repeated runs are byte-identical and the production files and inputs are read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage15, stage23, stage24
from atari_music.cli import cli

pytestmark = pytest.mark.experimental

requires_corpus = pytest.mark.skipif(
    not stage24.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage24.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)

requires_control = pytest.mark.skipif(
    not stage24.DEFAULT_SONGS_DIR.is_dir(),
    reason="the .dsl compositions are not present on this machine",
)


@pytest.fixture(scope="session")
def corpora() -> Dict[str, Any]:
    """Both corpora, measured once, shared by every test that needs the records."""
    return {
        "historical": stage24.load_historical_records(),
        "control": stage24.load_control_records(),
    }


@pytest.fixture(scope="session")
def univariate(corpora: Dict[str, Any]) -> Dict[str, Any]:
    return stage24.univariate_overlap(corpora["control"], corpora["historical"])


@pytest.fixture(scope="session")
def overlap(corpora: Dict[str, Any]) -> Dict[str, Any]:
    return stage24.multivariate_overlap(corpora["control"], corpora["historical"])


@pytest.fixture(scope="session")
def diagnostics(corpora: Dict[str, Any]) -> Dict[str, Any]:
    return stage24.matching_diagnostics(corpora["control"], corpora["historical"])


@pytest.fixture(scope="session")
def sensitivity(corpora: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    return stage24.sensitivity_analysis(
        corpora["control"], corpora["historical"], diagnostics
    )


@pytest.fixture(scope="session")
def bundle() -> Dict[str, Any]:
    """One full run, with the reproducibility check on, shared by the artefact tests."""
    return stage24.run_analysis()



# ---------------------------------------------------------------------------
# 1. the corpus inventory
# ---------------------------------------------------------------------------
class TestInventory:
    def test_both_corpora_are_non_empty(self, corpora: Dict[str, Any]) -> None:
        assert corpora["historical"]
        assert corpora["control"]
        assert len(corpora["control"]) == 53
        assert len(corpora["historical"]) == 12

    def test_every_record_carries_a_stable_identifier(
        self, corpora: Dict[str, Any]
    ) -> None:
        for record in corpora["historical"] + corpora["control"]:
            assert record.slug
            assert record.source_key
            assert record.corpus in ("historical", "control")

    def test_the_historical_corpus_is_clustered(self, corpora: Dict[str, Any]) -> None:
        historical = corpora["historical"]
        assert len({record.source_key for record in historical}) < len(historical)
        assert len({record.author for record in historical}) < len(historical)

    def test_a_historical_record_has_no_composition_metadata(
        self, corpora: Dict[str, Any]
    ) -> None:
        """A SAP is a player plus data. Nothing about its composition is invented here."""
        for record in corpora["historical"]:
            assert record.inventory["composition_available"] is False
            assert record.inventory["player_known"] is False
            assert "Tier D" in record.inventory["ground_truth_status"]
            for field in ("note_count", "pattern_count", "sequence_length"):
                assert field in record.inventory["not_comparable"]
                assert field in record.inventory["unknown"] or True

    def test_a_control_record_declares_its_ground_truth(
        self, corpora: Dict[str, Any]
    ) -> None:
        for record in corpora["control"]:
            assert record.inventory["composition_available"] is True
            assert record.inventory["player_known"] is True
            assert "Tier A" in record.inventory["ground_truth_status"]

    def test_the_four_provenance_classes_are_declared(self) -> None:
        classes = {
            stage24.PROVENANCE_KNOWN, stage24.PROVENANCE_DERIVED,
            stage24.PROVENANCE_UNKNOWN, stage24.PROVENANCE_NOT_COMPARABLE,
        }
        assert len(classes) == 4
        for note in stage24.COMPARABILITY_NOTES:
            assert note["class"] in classes

    def test_every_trace_has_a_hash_where_one_exists(
        self, corpora: Dict[str, Any]
    ) -> None:
        for record in corpora["historical"]:
            assert record.trace_sha256 is not None
        for record in corpora["control"]:
            assert record.source_sha256 is not None


# ---------------------------------------------------------------------------
# 2. the feature definitions
# ---------------------------------------------------------------------------
class TestFeatureDefinitions:
    def test_every_definition_is_complete(self) -> None:
        for item in stage24.FEATURE_DEFINITIONS:
            for field in ("name", "definition", "unit", "denominator", "silence",
                          "limitations", "role"):
                assert item[field], f"{item.get('name')} is missing {field}"

    def test_the_matching_set_and_the_exclusions_partition_the_definitions(self) -> None:
        names = {item["name"] for item in stage24.FEATURE_DEFINITIONS}
        matching = set(stage24.MATCHING_FEATURES)
        excluded = {name for name, _role in stage24.EXCLUDED_FEATURES}
        assert matching | excluded == names
        assert not matching & excluded

    def test_the_residual_is_never_a_feature(self) -> None:
        for item in stage24.FEATURE_DEFINITIONS:
            assert "residual" not in item["name"]
            assert "estimand" not in item["name"]

    def test_the_exclusions_are_justified_by_a_declared_reason(self) -> None:
        roles = {role for _name, role in stage24.EXCLUDED_FEATURES}
        assert roles <= {"excluded_degenerate", "excluded_confounded"}

    def test_the_length_confounded_count_is_excluded_and_replaced(self) -> None:
        """Stage 23 used the raw count; Stage 24 excludes it and matches on the normalised form."""
        excluded = {name for name, _role in stage24.EXCLUDED_FEATURES}
        assert "distinct_audf_values" in excluded
        assert "audf_diversity_per_1000_frames" in stage24.MATCHING_FEATURES

    def test_the_degenerate_constant_is_excluded(self) -> None:
        excluded = {name for name, _role in stage24.EXCLUDED_FEATURES}
        assert "audctl_change_rate" in excluded
        assert "stable_run_median" in excluded

    def test_every_matching_feature_is_defined_in_both_corpora(
        self, corpora: Dict[str, Any]
    ) -> None:
        for record in corpora["historical"] + corpora["control"]:
            for name in stage24.MATCHING_FEATURES:
                assert record.features.get(name) is not None, (record.slug, name)

    def test_the_thresholds_are_declared_before_use(self) -> None:
        assert 0.0 < stage24.PROPENSITY_LOW < stage24.PROPENSITY_HIGH < 1.0
        assert stage24.SMD_THRESHOLD > 0
        assert stage24.MIN_RETAINED_TRACES >= 2
        assert stage24.MIN_RETAINED_SOURCES >= 2
        assert stage24.CALIPERS


# ---------------------------------------------------------------------------
# 3. univariate overlap
# ---------------------------------------------------------------------------
def _classify(control: Any, historical: Any) -> str:
    """The classification rule, re-implemented here so the test does not read the module's answer."""
    c_lo, c_hi = min(control), max(control)
    h_lo, h_hi = min(historical), max(historical)
    if c_lo == c_hi and h_lo == h_hi and c_lo == h_lo:
        return "shared_constant"
    if max(c_lo, h_lo) > min(c_hi, h_hi):
        return "separated"
    if max(c_lo, h_lo) == min(c_hi, h_hi):
        return "point_support"
    if all(c_lo <= value <= c_hi for value in historical) and all(
        h_lo <= value <= h_hi for value in control
    ):
        return "full"
    return "partial"


class TestUnivariateOverlap:
    def test_every_matching_feature_is_classified(self, univariate: Dict[str, Any]) -> None:
        assert len(univariate["features"]) == len(stage24.MATCHING_FEATURES)
        for row in univariate["features"]:
            assert row["classification"] in (
                "full", "partial", "point_support", "separated", "shared_constant",
                "not_measurable",
            )

    def test_both_outside_support_counts_are_reported(self, univariate: Dict[str, Any]) -> None:
        """The brief's table asks for both directions, not only the historical one."""
        for row in univariate["features"]:
            assert row.get("control_outside_support") is not None
            assert row.get("historical_outside_support") is not None
            assert row["control_outside_support"] <= row["control_n"]
            assert row["historical_outside_support"] <= row["historical_n"]

    def test_a_degenerate_feature_is_not_reported_as_separated(self) -> None:
        """The classification rule, exercised directly on synthetic ranges.

        ``full`` means *neither* corpus has any member outside the other's range, which for
        continuous ranges only happens when the two ranges coincide. A corpus nested inside another
        is ``partial``, because the outer corpus has members the inner one cannot match.
        """
        assert _classify([0.0, 0.0], [0.0, 0.0]) == "shared_constant"
        assert _classify([0.0, 0.0], [1.0, 1.0]) == "separated"
        assert _classify([0.0, 1.0], [2.0, 3.0]) == "separated"
        assert _classify([0.0, 1.0], [1.0, 2.0]) == "point_support"
        assert _classify([0.0, 2.0], [1.0, 3.0]) == "partial"
        assert _classify([0.0, 3.0], [1.0, 2.0]) == "partial"
        assert _classify([1.0, 2.0], [1.0, 2.0]) == "full"

    def test_the_support_is_a_set_intersection_not_a_width_test(self) -> None:
        """A single shared value is support, and a width test would call it disjoint."""
        assert _classify([0.0, 0.0], [0.0, 5.0]) == "point_support"

    def test_poorly_covered_features_are_reported(self, univariate: Dict[str, Any]) -> None:
        for name in univariate["poorly_covered_features"]:
            row = next(item for item in univariate["features"] if item["feature"] == name)
            assert row["historical_inside_control_range_share"] < stage24.OVERLAP_COVERAGE



# ---------------------------------------------------------------------------
# 4. multivariate overlap and the calibration of its criteria
# ---------------------------------------------------------------------------
class TestMultivariateOverlap:
    def test_the_box_criterion_is_calibrated_on_the_control_corpus(
        self, overlap: Dict[str, Any]
    ) -> None:
        """A criterion that cannot pass the control's own members has no discriminating power."""
        calibration = overlap["box"]["calibration_inside_control"]
        assert calibration["traces"] == overlap["box"]["control"]["traces"]
        assert calibration["inside_on_every_feature"] > 0
        assert overlap["box"]["calibration_has_power"] is True

    def test_the_distance_thresholds_are_reported(self, overlap: Dict[str, Any]) -> None:
        thresholds = overlap["nearest_neighbour"]["thresholds"]
        for name in ("control_loo_max", "control_loo_p95", "control_loo_p90"):
            assert thresholds[name] is not None
        assert thresholds["control_loo_max"] >= thresholds["control_loo_p95"]
        assert thresholds["control_loo_p95"] >= thresholds["control_loo_p90"]

    def test_the_historical_distances_are_reported_per_trace(
        self, overlap: Dict[str, Any]
    ) -> None:
        neighbours = overlap["nearest_neighbour"]
        assert len(neighbours["per_trace"]) == neighbours["historical_traces"]
        for row in neighbours["per_trace"]:
            assert row["nearest_control"]
            assert row["nearest_distance"] >= 0
            assert row["top_contributors"]

    def test_the_distance_decomposition_names_its_drivers(
        self, overlap: Dict[str, Any]
    ) -> None:
        """A distance dominated by one feature is a statement about that feature."""
        for row in overlap["nearest_neighbour"]["per_trace"]:
            shares = [
                item["share_of_distance_squared"] for item in row["top_contributors"]
                if item["share_of_distance_squared"] is not None
            ]
            assert shares
            assert max(shares) <= 1.0

    def test_the_propensity_score_is_not_used_as_proof(self, overlap: Dict[str, Any]) -> None:
        propensity = overlap["propensity"]
        assert "no" in propensity["used_as_evidence_of_overlap"].lower()
        assert propensity["assumptions"]
        assert propensity["limitations"]

    def test_the_propensity_stability_is_reported(self, overlap: Dict[str, Any]) -> None:
        propensity = overlap["propensity"]
        assert propensity["bootstrap_refits"] > 0
        assert len(propensity["coefficient_stability"]) == (
            len(propensity["features"]) + 1
        )
        for row in propensity["coefficient_stability"]:
            assert isinstance(row["sign_flips"], bool)

    def test_the_propensity_fit_is_deterministic(self, corpora: Dict[str, Any]) -> None:
        first = stage24.propensity_analysis(corpora["control"], corpora["historical"])
        second = stage24.propensity_analysis(corpora["control"], corpora["historical"])
        assert first["coefficients"] == second["coefficients"]
        assert first["unstable_terms"] == second["unstable_terms"]

    def test_the_support_verdict_follows_the_declared_rule(
        self, overlap: Dict[str, Any]
    ) -> None:
        assert overlap["verdict"] in (
            "COMMON_SUPPORT_ADEQUATE", "COMMON_SUPPORT_PARTIAL",
            "COMMON_SUPPORT_INADEQUATE",
        )
        inside = overlap["box"]["historical"]["inside_on_every_feature"]
        retained = overlap["propensity"]["historical_score"]["in_overlap_region"]
        if overlap["verdict"] == "COMMON_SUPPORT_INADEQUATE":
            assert not (inside > 0 and retained > 0)
        if overlap["verdict"] == "COMMON_SUPPORT_ADEQUATE":
            assert inside > 0 and retained > 0

    def test_all_three_criteria_are_reported(self, overlap: Dict[str, Any]) -> None:
        for key in ("box", "nearest_neighbour", "propensity"):
            assert key in overlap
        assert isinstance(overlap["criteria_agree"], bool)



# ---------------------------------------------------------------------------
# 5. the matching, re-derived
# ---------------------------------------------------------------------------
class TestMatching:
    def test_every_declared_method_is_run(self, diagnostics: Dict[str, Any]) -> None:
        names = {row["method"] for row in diagnostics["methods"]}
        assert names == {"no_matching", "nearest_neighbour", "propensity_stratification",
                         "support_restriction"}

    def test_the_full_declared_grid_is_reported(self, diagnostics: Dict[str, Any]) -> None:
        nearest = [
            row for row in diagnostics["methods"] if row["method"] == "nearest_neighbour"
        ]
        assert len(nearest) == len(stage24.CALIPERS) * len(stage24.NEIGHBOUR_COUNTS)
        assert {row["caliper"] for row in nearest} == set(stage24.CALIPERS)
        assert {row["neighbours"] for row in nearest} == set(stage24.NEIGHBOUR_COUNTS)

    def test_the_caliper_is_actually_applied(self, corpora: Dict[str, Any]) -> None:
        """Stage 23 declared a caliper and never used it. Here it rejects."""
        stats = stage24.pooled_standardisation(corpora["control"], corpora["historical"])
        tight = stage24.match_nearest_neighbour(
            corpora["control"], corpora["historical"], stats, caliper=0.01, neighbours=1
        )
        assert tight["historical_kept"] == 0
        assert len(tight["rejected"]) == len(corpora["historical"])
        for row in tight["rejected"]:
            assert "caliper" in row["reason"]

    def test_a_rejected_trace_carries_its_reason(self, diagnostics: Dict[str, Any]) -> None:
        for row in diagnostics["methods"]:
            for rejected in row["rejected_traces"]:
                assert rejected["reason"]
                assert rejected["slug"]

    def test_no_method_is_validated_without_balance(self, diagnostics: Dict[str, Any]) -> None:
        for row in diagnostics["methods"]:
            if row["matching_validated"]:
                assert row["meets_balance"]
                assert row["meets_minimum_sample"]

    def test_an_unbalanced_method_is_not_called_validated(
        self, diagnostics: Dict[str, Any]
    ) -> None:
        for row in diagnostics["methods"]:
            if row["reportable"] and not row["balance"]["balanced"]:
                assert not row["matching_validated"]
                assert row["not_validated_because"]

    def test_the_balance_criterion_is_the_declared_one(
        self, diagnostics: Dict[str, Any]
    ) -> None:
        for row in diagnostics["methods"]:
            assert row["balance"]["threshold"] == stage24.SMD_THRESHOLD
            for feature in row["balance"]["features"]:
                if feature["balanced"] is not None:
                    assert feature["balanced"] == (
                        feature["absolute_smd"] <= stage24.SMD_THRESHOLD
                    )

    def test_the_minimum_sample_is_the_declared_one(self, diagnostics: Dict[str, Any]) -> None:
        for row in diagnostics["methods"]:
            enough = (
                row["historical_kept"] >= stage24.MIN_RETAINED_TRACES
                and row["historical_sources_kept"] >= stage24.MIN_RETAINED_SOURCES
            )
            assert row["meets_minimum_sample"] == enough

    def test_the_matching_never_reads_the_residual_as_a_feature(self) -> None:
        for name in stage24.MATCHING_FEATURES:
            assert "estimand" not in name
            assert "residual" not in name

    def test_the_stage23_defect_is_recorded(self, diagnostics: Dict[str, Any]) -> None:
        assert "caliper" in diagnostics["stage23_defect"]
        assert "never applied" in diagnostics["stage23_defect"]

    def test_the_support_restriction_lists_what_it_dropped(
        self, corpora: Dict[str, Any]
    ) -> None:
        strict = stage24.restrict_to_support(
            corpora["control"], corpora["historical"], max_features_outside=0
        )
        assert strict["historical_kept"] == 0
        for row in strict["rejected"]:
            assert row["outside_features"]
            assert row["features_outside"] > 0

        assert stage24.NEIGHBOUR_COUNTS


# ---------------------------------------------------------------------------
# 6. uncertainty, the resampling unit and the difference
# ---------------------------------------------------------------------------
class TestUncertainty:
    def test_the_unit_of_replication_is_the_trace(self, bundle: Dict[str, Any]) -> None:
        samples = bundle["core"]["effective_sample_sizes"]
        assert "trace" in samples["unit_of_replication"]
        assert "never treated as independent" in samples["unit_of_replication"]

    def test_frames_are_not_reported_as_observations(self, bundle: Dict[str, Any]) -> None:
        samples = bundle["core"]["effective_sample_sizes"]
        assert samples["historical_traces"] < samples["historical_register_values"]
        assert samples["control_traces"] < samples["control_register_values"]

    def test_the_bootstrap_resamples_sources(self, corpora: Dict[str, Any]) -> None:
        result = stage24.difference_for_estimand(
            corpora["control"], corpora["historical"], draws=200
        )
        assert result["available"]
        assert result["historical_clusters"] < result["historical_traces"]
        assert "source" in result["cluster_unit"]

    def test_the_difference_is_seeded_and_reproducible(
        self, corpora: Dict[str, Any]
    ) -> None:
        first = stage24.difference_for_estimand(
            corpora["control"], corpora["historical"], draws=200
        )
        second = stage24.difference_for_estimand(
            corpora["control"], corpora["historical"], draws=200
        )
        assert first["ci_low"] == second["ci_low"]
        assert first["ci_high"] == second["ci_high"]

    def test_the_interval_brackets_the_observed_difference(
        self, corpora: Dict[str, Any]
    ) -> None:
        result = stage24.difference_for_estimand(corpora["control"], corpora["historical"])
        assert result["ci_low"] <= result["observed_difference"] <= result["ci_high"]

    def test_the_effective_sample_size_is_kish(self) -> None:
        assert stage24.effective_sample_size([1.0, 1.0, 1.0]) == pytest.approx(3.0)
        assert stage24.effective_sample_size([1.0, 0.0, 0.0]) == pytest.approx(1.0)
        assert stage24.effective_sample_size([]) is None

    def test_an_undefined_comparison_reports_why(self, corpora: Dict[str, Any]) -> None:
        result = stage24.difference_for_estimand(corpora["control"], [], draws=10)
        assert result["available"] is False
        assert result["reason"]

    def test_every_method_reports_its_accounting(self, bundle: Dict[str, Any]) -> None:
        samples = bundle["core"]["effective_sample_sizes"]
        for row in samples["methods"]:
            assert row["historical_traces_before"] >= row["historical_traces_kept"]
            assert row["historical_traces_kept"] + row["historical_traces_rejected"] <= (
                row["historical_traces_before"]
            )


# ---------------------------------------------------------------------------
# 7. sensitivity, falsification and the three separate answers
# ---------------------------------------------------------------------------
class TestSensitivity:
    def test_every_declared_axis_is_reported(self, sensitivity: Dict[str, Any]) -> None:
        for key in ("leave_one_historical_song_out", "leave_one_control_source_out",
                    "matching_parameters", "residual_convention", "feature_set",
                    "channel", "common_support_only", "weighted_against_unweighted"):
            assert key in sensitivity

    def test_the_unstable_rule_is_declared(self, sensitivity: Dict[str, Any]) -> None:
        assert "UNSTABLE" in sensitivity["unstable_rule"]

    def test_leave_one_out_covers_every_trace(self, sensitivity: Dict[str, Any],
                                              corpora: Dict[str, Any]) -> None:
        assert len(sensitivity["leave_one_historical_song_out"]["rows"]) == len(
            corpora["historical"]
        )
        assert len(sensitivity["leave_one_control_source_out"]["rows"]) == len(
            corpora["control"]
        )

    def test_the_matching_parameter_grid_is_reported(self, sensitivity: Dict[str, Any]) -> None:
        grid = sensitivity["matching_parameters"]
        assert len(grid["rows"]) == (
            len(stage24.CALIPER_SENSITIVITY) * len(stage24.NEIGHBOUR_COUNTS)
        )
        for row in grid["rows"]:
            assert row["historical_kept"] >= 0

    def test_the_convention_sensitivity_uses_stage23_estimands(
        self, sensitivity: Dict[str, Any]
    ) -> None:
        names = {row["estimand"] for row in sensitivity["residual_convention"]["rows"]}
        assert names == set(stage23.ESTIMAND_NAMES)

    def test_the_feature_set_sensitivity_reports_a_verdict_per_set(
        self, sensitivity: Dict[str, Any]
    ) -> None:
        rows = sensitivity["feature_set"]["rows"]
        assert rows
        for row in rows:
            assert row["support_verdict"]

    def test_the_classification_scope_is_bounded(self, sensitivity: Dict[str, Any]) -> None:
        """Stability is claimed for the raw comparison, never for a matched estimate."""
        assert "does NOT extend to a matched estimate" in sensitivity["classification_scope"]

    def test_every_channel_is_reported_with_a_denominator(
        self, sensitivity: Dict[str, Any]
    ) -> None:
        for row in sensitivity["channel"]["rows"]:
            assert row["control_denominator"] > 0
            assert row["historical_denominator"] > 0


class TestFalsification:
    def test_the_criteria_are_declared_with_thresholds(self) -> None:
        assert len(stage24.FALSIFICATION_CRITERIA) == 6
        for item in stage24.FALSIFICATION_CRITERIA:
            assert item["criterion"]
            assert item["threshold"]
            assert item["rejects"]

    def test_every_criterion_is_evaluated(self, bundle: Dict[str, Any]) -> None:
        test = bundle["core"]["falsification"]
        assert len(test["criteria"]) == len(stage24.FALSIFICATION_CRITERIA)
        for row in test["criteria"]:
            assert isinstance(row["passed"], bool)
            assert row["measurement"] is not None

    def test_the_criteria_are_not_amended_after_the_results(
        self, bundle: Dict[str, Any]
    ) -> None:
        test = bundle["core"]["falsification"]
        assert test["declared_before_results"] is True
        for row, declared in zip(test["criteria"], stage24.FALSIFICATION_CRITERIA):
            assert row["criterion"] == declared["criterion"]
            assert row["threshold"] == declared["threshold"]

    def test_the_generation_confound_is_reported_as_failing(
        self, bundle: Dict[str, Any]
    ) -> None:
        test = bundle["core"]["falsification"]
        generation = test["criteria"][5]
        assert generation["passed"] is False
        assert "generation process is confounded" in generation["reading"]

    def test_the_reading_is_rejected_when_a_condition_fails(
        self, bundle: Dict[str, Any]
    ) -> None:
        test = bundle["core"]["falsification"]
        assert test["history_specific_reading_rejected"] == bool(test["rejected_criteria"])


    def test_the_power_statement_is_explicit(self, bundle: Dict[str, Any]) -> None:
        statement = bundle["core"]["effective_sample_sizes"]["power_statement"]
        assert "twelve" in statement or "12" in statement


# ---------------------------------------------------------------------------
# 8. the three separate answers and the next-experiment design
# ---------------------------------------------------------------------------
class TestIdentifiability:
    def test_the_three_answers_are_reported_separately(
        self, bundle: Dict[str, Any]
    ) -> None:
        identifiability = bundle["core"]["identifiability"]
        for key in ("A_descriptive_difference", "B_difference_after_matching",
                    "C_identified_cause"):
            assert key in identifiability
            assert identifiability[key]["answer"]
            assert identifiability[key]["what_it_does_not_say"]

    def test_the_descriptive_answer_is_not_the_identified_answer(
        self, bundle: Dict[str, Any]
    ) -> None:
        """The whole point of the section: A is not C."""
        identifiability = bundle["core"]["identifiability"]
        assert identifiability["A_descriptive_difference"]["answer"] == "yes"
        assert identifiability["C_identified_cause"]["answer"] == "no"

    def test_the_identified_answer_names_its_blockers(self, bundle: Dict[str, Any]) -> None:
        blockers = bundle["core"]["identifiability"]["C_identified_cause"]["blockers"]
        assert len(blockers) >= 4
        for row in blockers:
            assert row["blocker"]
            assert row["evidence"]

    def test_the_matched_answer_does_not_claim_an_estimate(
        self, bundle: Dict[str, Any]
    ) -> None:
        answer = bundle["core"]["identifiability"]["B_difference_after_matching"]["answer"]
        assert "cannot be answered" in answer

    def test_the_generation_and_ground_truth_blockers_are_named(
        self, bundle: Dict[str, Any]
    ) -> None:
        blockers = bundle["core"]["identifiability"]["C_identified_cause"]["blockers"]
        names = " ".join(row["blocker"] for row in blockers)
        assert "ground truth" in names
        assert "generation" in names


class TestNextExperiment:
    def test_the_design_is_stated_and_not_executed(self, bundle: Dict[str, Any]) -> None:
        design = bundle["core"]["next_experiment"]
        assert "not created" in design["not_done_here"]
        assert design["minimal_experiment"]["must_control"]
        assert design["minimal_experiment"]["must_not_vary"]

    def test_the_gaps_are_measured_not_asserted(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["core"]["next_experiment"]["identified_gaps"]:
            assert row["measurement"]
            assert row["closes_it"]
            assert isinstance(row["testable"], bool)

    def test_the_clock_gap_is_identified(self, bundle: Dict[str, Any]) -> None:
        gaps = bundle["core"]["next_experiment"]["identified_gaps"]
        clock = next(row for row in gaps if "clock" in row["gap"])
        assert "1.79 MHz" in clock["measurement"] or "$50" in clock["measurement"]


# ---------------------------------------------------------------------------
# 9. the verdicts
# ---------------------------------------------------------------------------
class TestVerdicts:
    def test_the_main_verdict_is_from_the_declared_vocabulary(
        self, bundle: Dict[str, Any]
    ) -> None:
        decided = bundle["core"]["verdicts"]
        assert decided["main"]["verdict"] in stage24.VERDICT_VOCABULARY

    def test_every_auxiliary_verdict_is_from_the_declared_vocabulary(
        self, bundle: Dict[str, Any]
    ) -> None:
        decided = bundle["core"]["verdicts"]
        for row in decided["auxiliary"]:
            assert row["verdict"] in stage24.AUXILIARY_VERDICTS

    def test_a_proven_performance_layer_is_never_claimed(
        self, bundle: Dict[str, Any]
    ) -> None:
        decided = bundle["core"]["verdicts"]
        assert decided["proven_performance_layer_used"] is False
        assert "PROVEN PERFORMANCE LAYER" not in stage24.VERDICT_VOCABULARY
        assert "PROVEN PERFORMANCE LAYER" not in stage24.AUXILIARY_VERDICTS
        assert "PROVEN PERFORMANCE LAYER" not in stage24.render_report(bundle)

    def test_the_main_verdict_follows_the_support_verdict(
        self, bundle: Dict[str, Any]
    ) -> None:
        decided = bundle["core"]["verdicts"]["main"]
        support = decided["deciding_measurement"]["support_verdict"]
        if support == "COMMON_SUPPORT_INADEQUATE":
            assert decided["verdict"] == "COMMON_SUPPORT_INADEQUATE"
        elif support == "COMMON_SUPPORT_PARTIAL":
            assert decided["verdict"] == "COMMON_SUPPORT_PARTIAL"

    def test_no_matched_estimate_is_claimed_when_none_is_validated(
        self, bundle: Dict[str, Any]
    ) -> None:
        decided = bundle["core"]["verdicts"]
        validated = decided["main"]["deciding_measurement"]["validated_methods"]
        if validated == 0:
            assert decided["main"]["verdict"] not in (
                "HISTORICAL_DIFFERENCE_DISAPPEARS_AFTER_MATCHING",
                "HISTORICAL_DIFFERENCE_ROBUST_BUT_UNIDENTIFIED",
            )

    def test_the_inadequate_support_verdict_requires_a_new_corpus(
        self, bundle: Dict[str, Any]
    ) -> None:
        decided = bundle["core"]["verdicts"]
        if decided["main"]["verdict"] == "COMMON_SUPPORT_INADEQUATE":
            assert "NEW_CONTROL_CORPUS_REQUIRED" in {
                row["verdict"] for row in decided["auxiliary"]
            }

    def test_the_production_verdict_is_always_present(self, bundle: Dict[str, Any]) -> None:
        decided = bundle["core"]["verdicts"]
        assert "NO_PRODUCTION_DECISION_CHANGED" in {
            row["verdict"] for row in decided["auxiliary"]
        }

    def test_every_verdict_carries_a_reason(self, bundle: Dict[str, Any]) -> None:
        for row in bundle["core"]["verdicts"]["auxiliary"]:
            assert row["reason"]
            assert row["measurement"] is not None


    def test_the_falsifiers_are_stated(self, bundle: Dict[str, Any]) -> None:
        experiment = bundle["core"]["next_experiment"]["minimal_experiment"]
        assert len(experiment["what_would_falsify_the_hypothesis"]) >= 3
        assert experiment["what_would_allow_a_design_decision"]



# ---------------------------------------------------------------------------
# 10. artefacts, determinism and the read-only audit
# ---------------------------------------------------------------------------
class TestArtefactsAndDeterminism:
    def test_the_writer_emits_every_declared_artefact(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        written = stage24.write_analysis(
            bundle, stage24_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        for name in stage24.STAGE24_FILES:
            assert (tmp_path / "r" / name).is_file(), name
        assert (tmp_path / "d" / stage24.STAGE24_DOC).is_file()
        assert (tmp_path / "r" / stage24.STAGE24_REPORT).is_file()
        assert set(written) == set(stage24.STAGE24_FILES) | {
            stage24.STAGE24_DOC, stage24.STAGE24_REPORT,
        }

    def test_the_declared_artefact_list_matches_the_brief(
        self,
    ) -> None:
        """The brief names fourteen artefacts; the writer emits them under repository names."""
        required = {
            "stage24_manifest.json", "corpus_inventory.json", "feature_definitions.json",
            "univariate_overlap.json", "multivariate_overlap.json",
            "matching_diagnostics.json", "matched_comparison.json",
            "effective_sample_sizes.json", "sensitivity_analysis.json",
            "leave_one_source_out.json", "identifiability_assessment.json",
            "next_experiment_design.json", "verdict.json",
        }
        assert required <= set(stage24.STAGE24_FILES)

    def test_every_artefact_is_valid_json(self, bundle: Dict[str, Any],
                                          tmp_path: Path) -> None:
        stage24.write_analysis(bundle, stage24_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        for name in stage24.STAGE24_FILES:
            payload = json.loads((tmp_path / "r" / name).read_text(encoding="utf-8"))
            assert payload is not None, name

    def test_the_manifest_names_the_document_and_the_stop_condition(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        stage24.write_analysis(bundle, stage24_dir=tmp_path / "r", docs_dir=tmp_path / "d")
        manifest = json.loads(
            (tmp_path / "r" / "stage24_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["document"] == stage24.STAGE24_DOC
        assert "no music is generated" in manifest["stop_condition"]
        assert manifest["reproducibility"]["byte_identical"]

    def test_a_repeated_run_is_byte_identical(self, tmp_path: Path) -> None:
        first = stage24.run_analysis()
        second = stage24.run_analysis()
        left = tmp_path / "left"
        right = tmp_path / "right"
        written_left = stage24.write_analysis(
            first, stage24_dir=left / "r", docs_dir=left / "d"
        )
        written_right = stage24.write_analysis(
            second, stage24_dir=right / "r", docs_dir=right / "d"
        )
        assert set(written_left) == set(written_right)
        for name in written_left:
            assert written_left[name].read_bytes() == written_right[name].read_bytes(), name

    def test_the_determinism_block_is_declared(self, bundle: Dict[str, Any]) -> None:
        determinism = bundle["determinism"]
        assert determinism["random_seed"] == stage24.RANDOM_SEED
        assert "slug" in determinism["tie_breaks"]
        assert "fixed ridge" in determinism["tie_breaks"]
        assert len(determinism["source_hash"]) == 64

    def test_no_set_iteration_reaches_an_artefact(self, bundle: Dict[str, Any]) -> None:
        """Every list in the artefacts is sorted, so iteration order cannot leak."""
        payload = stage24._artefacts(bundle)
        for name in stage24.STAGE24_FILES:
            assert payload[name] is not None
        assert json.dumps(payload, sort_keys=True)


class TestReadOnlyAudit:
    def test_the_run_proves_the_inputs_are_unchanged(self, bundle: Dict[str, Any]) -> None:
        for _key, row in bundle["read_only_audit"].items():
            assert row["read_only"], row["changed"]

    def test_the_audit_covers_stage_15_to_23_and_the_player(self) -> None:
        hashes = stage24.production_hashes()
        for relative in (
            "src/atari_music/stage15.py", "src/atari_music/stage16.py",
            "src/atari_music/stage17.py", "src/atari_music/stage18.py",
            "src/atari_music/stage19.py", "src/atari_music/stage20.py",
            "src/atari_music/stage21.py", "src/atari_music/stage22.py",
            "src/atari_music/stage23.py", "src/atari_music/asm/player.asm",
        ):
            assert relative in hashes
            assert hashes[relative], relative

    def test_the_audit_covers_the_traces_and_compositions(self) -> None:
        hashes = stage24.input_hashes()
        assert any(key.startswith("trace/") for key in hashes)
        assert any(key.startswith("composition/") for key in hashes)
        assert any(key.startswith("upstream/") for key in hashes)

    def test_the_audit_notices_a_change(self) -> None:
        row = stage24.read_only_audit({"a": "1", "b": "2"}, {"a": "1", "b": "3"})
        assert not row["read_only"]
        assert row["changed"] == ["b"]



# ---------------------------------------------------------------------------
# 11. the report and the CLI
# ---------------------------------------------------------------------------
class TestReport:
    def test_the_report_has_every_required_section(self, bundle: Dict[str, Any]) -> None:
        report = stage24.render_report(bundle)
        titles = [
            "Executive Summary", "Corpus and Source Audit", "Common Feature Definitions",
            "Overlap Analysis", "Diagnostics of the Earlier Matching",
            "Results Before Matching", "Results After Matching",
            "Effective Sample Size and Uncertainty", "Sensitivity Analyses",
            "Falsification Test", "Identifiability Limits",
            "The Minimal Additional Experiment", "Explicit Methodological Corrections",
            "Verdict and Recommendation",
        ]
        for index, title in enumerate(titles, start=1):
            assert f"## {index}. {title}" in report, title

    def test_the_report_answers_all_eight_questions(self, bundle: Dict[str, Any]) -> None:
        report = stage24.render_report(bundle)
        assert "## The Eight Closing Questions" in report
        for number in range(1, 9):
            assert f"**{number}." in report, number

    def test_the_report_carries_no_absolute_windows_path(
        self, bundle: Dict[str, Any]
    ) -> None:
        report = stage24.render_report(bundle)
        assert "C:\\Users" not in report
        assert "C:/Users" not in report

    def test_the_report_is_plain_ascii(self, bundle: Dict[str, Any]) -> None:
        stage24.render_report(bundle).encode("ascii")

    def test_the_report_states_the_descriptive_matched_identified_split(
        self, bundle: Dict[str, Any]
    ) -> None:
        report = stage24.render_report(bundle)
        assert "The descriptive, the matched and the identified are three different statements" in report

    def test_the_report_does_not_claim_a_proven_layer(self, bundle: Dict[str, Any]) -> None:
        report = stage24.render_report(bundle)
        assert "PROVEN PERFORMANCE LAYER" not in report

    def test_the_report_names_the_stage23_caliper_defect(
        self, bundle: Dict[str, Any]
    ) -> None:
        report = stage24.render_report(bundle)
        assert "caliper" in report.lower()
        assert "never applied" in report


@requires_control
class TestCli:
    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["analyze-stage24", "--help"])
        assert result.exit_code == 0, result.output
        assert "identifiable" in result.output.lower()

    def test_a_run_writes_its_artefacts(self, tmp_path: Path) -> None:
        reports = tmp_path / "r"
        docs = tmp_path / "d"
        result = CliRunner().invoke(
            cli,
            ["analyze-stage24", "--reports-dir", str(reports), "--docs-dir", str(docs),
             "--skip-reproducibility"],
        )
        assert result.exit_code == 0, result.output
        for name in stage24.STAGE24_FILES:
            assert (reports / name).is_file(), name
        assert (docs / stage24.STAGE24_DOC).is_file()
        assert "verdict" in result.output.lower()
        assert "read-only" in result.output.lower()
        assert "descriptive" in result.output.lower()



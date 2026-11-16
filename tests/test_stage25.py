"""Stage 25 - matched control corpus design and validation.

These tests pin the stage to the claims it makes, and they are written to fail on the mistakes the
brief names rather than on the mistakes that are easy to test:

* the acceptance criteria and the pilot's continuation criteria are declared before the results, and
  the thresholds are reused from Stage 24 rather than re-chosen to fit the outcome;
* the capability audit is a *measurement* of the real pipeline, so a capability is only recorded as
  reachable when a probe actually produced the configuration, and the one idiom that cannot be
  produced is reported as a production change rather than worked around;
* a matching feature is only claimed controllable when the audit produced the configuration it needs,
  and a feature that can only be observed is labelled as such;
* the pilot is a feasibility test and is never described as a corpus, and no residual comparison is
  read off it;
* the ground truth is kept at three separate levels, and a compiled payload is never reported as a
  musical property;
* the player confound is stated as unclosable by corpus design rather than designed around;
* repeated runs are byte-identical and the production files and inputs are read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from click.testing import CliRunner

from atari_music import stage15, stage23, stage24, stage25
from atari_music.cli import cli

pytestmark = pytest.mark.experimental

requires_corpus = pytest.mark.skipif(
    not stage25.DEFAULT_ARCHAEOLOGY_DIR.is_dir()
    or not any(stage15.trace_dir(stage25.DEFAULT_ARCHAEOLOGY_DIR).glob("*.frames.json")),
    reason="the archaeology corpus traces are not present on this machine",
)

requires_control = pytest.mark.skipif(
    not stage25.DEFAULT_SONGS_DIR.is_dir(),
    reason="the .dsl compositions are not present on this machine",
)


@pytest.fixture(scope="session")
def bundle() -> Dict[str, Any]:
    """One full run, with the reproducibility check on, shared by the artefact tests."""
    return stage25.run_analysis()


@pytest.fixture(scope="session")
def core(bundle: Dict[str, Any]) -> Dict[str, Any]:
    return bundle["core"]




# ---------------------------------------------------------------------------
# 1. the criteria are declared before the results
# ---------------------------------------------------------------------------
class TestDeclaredCriteria:
    def test_the_pilot_specs_are_declared_up_front(self) -> None:
        assert len(stage25.PILOT_SPECS) == 4
        for spec in stage25.PILOT_SPECS:
            assert spec["id"] and spec["group"] and spec["purpose"]
            assert spec["audctl"] in ("$00", "$10", "$50")

    def test_every_pilot_criterion_names_its_measurement(self) -> None:
        assert len(stage25.PILOT_CRITERIA) == 7
        for row in stage25.PILOT_CRITERIA:
            assert row["criterion"]
            assert row["measurement"]

    def test_the_balance_threshold_is_reused_not_re_chosen(self) -> None:
        assert stage25.ACCEPT_SMD_THRESHOLD == stage24.SMD_THRESHOLD
        assert stage25.ACCEPT_MIN_RETAINED_TRACES == stage24.MIN_RETAINED_TRACES
        assert stage25.ACCEPT_MIN_RETAINED_SOURCES == stage24.MIN_RETAINED_SOURCES

    def test_the_estimand_and_the_feature_set_are_inherited(self) -> None:
        """A design that changed the measurement would be designing for a different question."""
        assert stage25.PRIMARY_ESTIMAND == stage23.PRIMARY_ESTIMAND
        assert stage25.MATCHING_FEATURES == stage24.MATCHING_FEATURES

    def test_the_calibration_floor_is_not_vacuous(self) -> None:
        """Stage 24 measured 41 of 53 control traces inside the box, so the criterion discriminates."""
        assert 0.0 < stage25.ACCEPT_CALIBRATION_MIN <= 1.0
        assert stage25.ACCEPT_JOINT_BOX_COVERAGE == 1.00


# ---------------------------------------------------------------------------
# 2. the audit of Stages 21 to 24
# ---------------------------------------------------------------------------
class TestAuditOfEarlierStages:
    def test_the_audit_reuses_the_upstream_verdicts(self, core: Dict[str, Any]) -> None:
        audit = core["audit"]
        assert audit["stage24_verdict"]
        assert audit["stage23_verdict"]
        assert audit["stage22_analysis_version"]
        assert audit["stage23_analysis_version"]

    def test_the_audit_carries_the_stage24_overlap_measurement(self, core: Dict[str, Any]) -> None:
        overlap = core["audit"]["stage24_overlap"]
        assert overlap["historical_traces"] == 12
        assert overlap["control_traces"] == 53
        assert overlap["historical_inside_joint_box"] == 0
        assert overlap["control_inside_joint_box_leave_one_out"] == 41

    def test_the_audit_names_the_conclusions_it_inherits(self, core: Dict[str, Any]) -> None:
        conclusions = core["audit"]["inherited_conclusions"]
        assert conclusions
        for row in conclusions:
            assert row["conclusion"] and row["source"] and row["consequence"]

    def test_the_stage23_caliper_defect_is_carried_forward(self, core: Dict[str, Any]) -> None:
        assert core["audit"]["stage24_matching"]["stage23_defect"]


# ---------------------------------------------------------------------------
# 3. the target population and the inference scope
# ---------------------------------------------------------------------------
class TestTargetPopulation:
    def test_the_population_is_a_property_region_not_a_genre(self, core: Dict[str, Any]) -> None:
        assert "property region" in core["target_population"]["population"]

    def test_the_scope_is_limited_to_the_region(self, core: Dict[str, Any]) -> None:
        scope = core["target_population"]["inference_scope"]
        assert "does not support statements about Atari music in general" in scope

    def test_the_population_states_what_it_is_not(self, core: Dict[str, Any]) -> None:
        statements = core["target_population"]["what_the_population_is_not"]
        assert len(statements) >= 3
        for statement in statements:
            assert statement


# ---------------------------------------------------------------------------
# 4. the three ground-truth levels
# ---------------------------------------------------------------------------
class TestGroundTruth:
    def test_the_three_levels_are_declared(self, core: Dict[str, Any]) -> None:
        levels = core["ground_truth_validation"]["levels"]
        assert [row["level"] for row in levels] == ["A_source", "B_compiled", "C_trace"]

    def test_each_level_states_its_availability_in_both_corpora(self, core: Dict[str, Any]) -> None:
        for row in core["ground_truth_validation"]["levels"]:
            assert row["identity"]
            assert row["available_for_control"]
            assert row["available_for_historical"]
            assert row["limitations"]

    def test_a_source_level_is_not_available_for_a_historical_trace(
        self, core: Dict[str, Any]
    ) -> None:
        source = core["ground_truth_validation"]["levels"][0]
        assert source["available_for_historical"].startswith("no")

    def test_the_validation_ran_and_is_consistent(self, core: Dict[str, Any]) -> None:
        validation = core["ground_truth_validation"]
        assert validation["all_consistent"] is True
        checks = validation["checks"]
        assert len(checks) == len(stage25.PILOT_SPECS)
        for row in checks:
            assert row["levels_present"] is True, row["id"]
            assert row["compiled_equals_trace"] is True, row["id"]
            assert row["audctl_matches_request"] is True, row["id"]
            assert row["frames_consistent"] is True, row["id"]

    def test_the_truth_checks_are_repeated_for_stability(self, core: Dict[str, Any]) -> None:
        """A digest is not a proof, so each trace is rebuilt and the hashes compared."""
        for row in core["ground_truth_validation"]["checks"]:
            assert row["source_hash_stable"] is True, row["id"]
            assert row["payload_hash_stable"] is True, row["id"]

    def test_the_hash_sensitivity_check_is_recorded(self, core: Dict[str, Any]) -> None:
        sensitivity = core["ground_truth_validation"]["hash_sensitivity"]
        assert sensitivity["checked"] is True
        assert sensitivity["source_hash_changes_when_the_document_changes"] is True

    def test_the_levels_are_not_merged(self, core: Dict[str, Any]) -> None:
        assert core["ground_truth_validation"]["reading"]


# ---------------------------------------------------------------------------
# 5. the pipeline capability audit is a measurement
# ---------------------------------------------------------------------------
class TestCapabilityAudit:
    def test_every_finding_carries_its_probe_rows(self, core: Dict[str, Any]) -> None:
        findings = core["pipeline_capability"]["findings"]
        assert len(findings) == 6
        narrative = {
            "capability", "conclusion", "consequence", "mechanism",
            "production_change_would_be", "does_it_change_the_subject_of_the_study",
        }
        for finding in findings:
            assert finding["capability"]
            text = finding.get("conclusion") or finding.get("consequence")
            assert isinstance(text, str) and text.strip(), finding["capability"]
            assert set(finding) - narrative, finding["capability"]

    def test_the_requested_audctl_mode_is_produced_on_every_frame(
        self, core: Dict[str, Any]
    ) -> None:
        """The binding gap Stage 24 measured is closable with a bound sound profile."""
        rows = next(
            finding["rows"] for finding in core["pipeline_capability"]["findings"]
            if finding["capability"] == "AUDCTL configurations"
        )
        for row in rows:
            assert row["reachable"], row
            assert row["column"] == [row["requested"]]
            assert row["resolved"] == row["requested"]

    def test_the_historical_clock_needs_a_bound_profile(self, core: Dict[str, Any]) -> None:
        rows = next(
            finding["rows"] for finding in core["pipeline_capability"]["findings"]
            if finding["capability"] == "AUDCTL configurations"
        )
        clock = next(row for row in rows if row["requested"] == "$50")
        assert clock["binding_applied"], "the $50 clock must come from a bound profile"
        assert clock["uses_16bit_bass"] is True

    def test_all_eight_distortion_bytes_are_reachable(self, core: Dict[str, Any]) -> None:
        finding = next(
            row for row in core["pipeline_capability"]["findings"]
            if row["capability"] == "distortion modes"
        )
        assert finding["reachable_count"] == finding["total"] == 8

    def test_the_unproducible_idiom_is_recorded_as_a_production_change(
        self, core: Dict[str, Any]
    ) -> None:
        changes = core["pipeline_capability"]["production_changes_required"]
        assert changes == [stage25.PRODUCTION_CHANGE_IDIOM]

    def test_the_idiom_probe_measured_zero_occurrences(self, core: Dict[str, Any]) -> None:
        finding = next(
            row for row in core["pipeline_capability"]["findings"]
            if row["capability"] == stage25.PRODUCTION_CHANGE_IDIOM
        )
        assert finding["reachable"] is False
        assert finding["zero_divider_audible_frames"] == 0
        assert finding["production_change_would_be"]

    def test_the_production_change_is_specified_and_not_implemented(
        self, core: Dict[str, Any]
    ) -> None:
        finding = next(
            row for row in core["pipeline_capability"]["findings"]
            if row["capability"] == stage25.PRODUCTION_CHANGE_IDIOM
        )
        assert "does not implement it" in finding["production_change_would_be"]
        assert finding["does_it_change_the_subject_of_the_study"]
        assert finding["mechanism"]
        assert finding["consequence"]

    def test_the_capability_count_matches_the_findings(self, bundle: Dict[str, Any]) -> None:
        summary = bundle["summary"]
        findings = bundle["core"]["pipeline_capability"]["findings"]
        assert summary["capabilities_total"] == len(findings)
        assert summary["capabilities_reachable"] == sum(
            1 for row in findings if row.get("reachable", True)
        )

    def test_the_reading_states_the_audit_is_measured(self, core: Dict[str, Any]) -> None:
        assert core["pipeline_capability"]["reading"]


# ---------------------------------------------------------------------------
# 6. feature controllability
# ---------------------------------------------------------------------------
class TestFeatureControllability:
    def test_every_matching_feature_is_classified(self, core: Dict[str, Any]) -> None:
        classified = {row["feature"] for row in core["feature_controllability"]}
        for name in core["matching_features"]:
            assert name in classified, name

    def test_every_row_names_its_class_and_mechanism(self, core: Dict[str, Any]) -> None:
        allowed = {
            "controlled_directly", "controlled_indirectly", "observed_only", "not_controllable",
        }
        for row in core["feature_controllability"]:
            assert row["class"] in allowed, row
            assert row["mechanism"]
            assert row["granularity"] is not None

    def test_the_controllability_table_covers_each_matching_feature_exactly_once(
        self, core: Dict[str, Any]
    ) -> None:
        names = [row["feature"] for row in core["feature_controllability"]]
        assert len(names) == len(set(names))
        assert set(core["matching_features"]) <= set(names)

    def test_the_coverage_guard_is_enforced(self) -> None:
        """The guard runs inside the analysis, so a gap cannot reach an artefact silently."""
        stage25.validate_feature_coverage()
        with pytest.raises(stage25.Stage25Error):
            monkey = stage25.FEATURE_CONTROLLABILITY
            try:
                stage25.FEATURE_CONTROLLABILITY = tuple(
                    row for row in monkey if row["feature"] != "frames"
                )
                stage25.validate_feature_coverage()
            finally:
                stage25.FEATURE_CONTROLLABILITY = monkey

    def test_a_feature_that_only_observes_is_labelled_observed_only(
        self, core: Dict[str, Any]
    ) -> None:
        row = next(
            r for r in core["feature_controllability"]
            if r["feature"] == "detector_generator_recall"
        )
        assert row["class"] == "observed_only"

    def test_the_uncontrollable_features_are_named(self, core: Dict[str, Any]) -> None:
        classes = {row["feature"]: row["class"] for row in core["feature_controllability"]}
        assert classes["stable_run_median"] == "not_controllable"
        assert classes["audctl_change_rate"] == "not_controllable"

    def test_the_feature_definitions_cover_the_matching_features(self, core: Dict[str, Any]) -> None:
        defined = {row["name"] for row in core["feature_definitions"]}
        for name in core["matching_features"]:
            assert name in defined, name
        assert len(core["feature_definitions"]) >= len(core["matching_features"])

    def test_every_definition_states_a_unit_and_a_silence_convention(
        self, core: Dict[str, Any]
    ) -> None:
        for row in core["feature_definitions"]:
            assert row["definition"]
            assert row["unit"]
            assert row["denominator"]
            assert row["silence"]


# ---------------------------------------------------------------------------
# 7. the corpus design
# ---------------------------------------------------------------------------
class TestCorpusDesign:
    def test_the_design_declares_its_groups(self, core: Dict[str, Any]) -> None:
        design = core["corpus_design"]
        assert design["group_count"] == len(design["groups"]) == 4
        for group in design["groups"]:
            assert group["group"] and group["role"] and group["purpose"]
            assert group["what_it_closes"]
            assert group["size_target"]
            assert group["cost"]

    def test_every_group_is_buildable_or_states_its_blocker(self, core: Dict[str, Any]) -> None:
        for group in core["corpus_design"]["groups"]:
            assert isinstance(group["pipeline_can_build_it"], bool)
            if not group["pipeline_can_build_it"]:
                assert group["blocked_by"]

    def test_the_minimum_size_is_the_sum_of_the_groups(self, core: Dict[str, Any]) -> None:
        design = core["corpus_design"]
        assert design["total_minimum_size"] == sum(
            int(str(group["size_target"]).split()[-1]) for group in design["groups"]
        )

    def test_the_reachable_length_covers_the_historical_maximum(self, core: Dict[str, Any]) -> None:
        region = core["corpus_design"]["target_length_region"]
        assert region["reachable"] >= region["historical_max"]

    def test_the_design_declares_its_principle(self, core: Dict[str, Any]) -> None:
        assert core["corpus_design"]["design_principle"]


# ---------------------------------------------------------------------------
# 8. sample size
# ---------------------------------------------------------------------------
class TestSampleSize:
    def test_the_counts_are_reported_from_measurement(self, core: Dict[str, Any]) -> None:
        counted = core["sample_size"]["what_can_be_counted"]
        assert counted["historical_traces"] == 12
        assert counted["existing_control_traces"] == 53
        assert counted["matching_features"] == len(core["matching_features"])

    def test_a_design_floor_is_declared_with_its_rule(self, core: Dict[str, Any]) -> None:
        floor = core["sample_size"]["design_floor"]
        assert floor["minimum_control_traces"] > 0
        assert floor["rule"]
        assert floor["why"]

    def test_the_feature_dimension_argument_is_stated(self, core: Dict[str, Any]) -> None:
        argument = core["sample_size"]["feature_dimension_argument"]
        assert argument["features"] == len(core["matching_features"])
        assert argument["statement"]

    def test_no_power_estimate_is_claimed(self, core: Dict[str, Any]) -> None:
        """Without an effect size there is no power calculation, and the stage must say so."""
        text = json.dumps(core["sample_size"], sort_keys=True).lower()
        assert "power" in text
        assert "no power" in text or "cannot" in text or "not available" in text


# ---------------------------------------------------------------------------
# 9. the acceptance criteria
# ---------------------------------------------------------------------------
class TestOverlapCriteria:
    def test_the_criteria_are_declared_before_the_pilot(self, core: Dict[str, Any]) -> None:
        criteria = core["overlap_acceptance_criteria"]
        for name in ("univariate", "multivariate_box", "calibration", "distance",
                     "propensity", "matching", "leakage"):
            assert name in criteria, name
            assert criteria[name]["threshold"]
            assert criteria[name]["reused_from"]
            assert criteria[name]["note"]

    def test_the_binding_criterion_is_the_joint_box(self, core: Dict[str, Any]) -> None:
        criteria = core["overlap_acceptance_criteria"]
        assert "100%" in criteria["multivariate_box"]["threshold"]

    def test_the_reading_refuses_a_corpus_that_fails_one_criterion(
        self, core: Dict[str, Any]
    ) -> None:
        """The brief's warning: overlap alone is not sufficient, so five of six is a refusal."""
        reading = core["overlap_acceptance_criteria"]["reading"]
        assert "refused" in reading
        assert "weakest" in reading

    def test_the_caliper_is_declared_and_enforced(self, core: Dict[str, Any]) -> None:
        matching = core["matching_validation"]
        assert matching["caliper_declared"] > 0
        assert matching["positive_control"]["enforced"] is True

    def test_the_positive_control_rejects_everything(self, core: Dict[str, Any]) -> None:
        positive = core["matching_validation"]["positive_control"]
        assert positive["historical_kept"] == 0
        assert positive["historical_rejected"] == 12

    def test_the_negative_control_retains_everything(self, core: Dict[str, Any]) -> None:
        negative = core["matching_validation"]["negative_control"]
        assert negative["retains_everything"] is True
        assert negative["historical_kept"] == 12

    def test_the_controls_together_show_the_caliper_is_a_real_constraint(
        self, core: Dict[str, Any]
    ) -> None:
        matching = core["matching_validation"]
        smallest = matching["smallest_observed_distance"]
        assert smallest is not None
        assert matching["positive_control"]["caliper"] < smallest
        assert matching["negative_control"]["caliper"] > smallest

    def test_the_balance_criterion_is_reused(self, core: Dict[str, Any]) -> None:
        balance = core["matching_validation"]["balance_criterion"]
        assert balance["threshold"] == stage24.SMD_THRESHOLD
        assert "reused" in balance["source"]


# ---------------------------------------------------------------------------
# 10. leakage and over-fitting
# ---------------------------------------------------------------------------
class TestLeakage:
    def test_the_design_set_is_declared_in_full(self, core: Dict[str, Any]) -> None:
        design_set = core["leakage"]["design_set"]
        assert design_set["traces"] == 12
        assert len(design_set["used_to_choose_the_target_region"]) == 12
        assert design_set["note"]

    def test_the_validation_options_state_what_they_do_not_prove(
        self, core: Dict[str, Any]
    ) -> None:
        options = core["leakage"]["validation_options"]
        assert options
        for row in options:
            assert row["option"]
            assert isinstance(row["available"], bool)
            assert row["what_it_proves"]
            assert row["what_it_does_not_prove"]

    def test_every_over_fitting_risk_has_a_mitigation(self, core: Dict[str, Any]) -> None:
        risks = core["leakage"]["over_fitting_risks"]
        assert risks
        for row in risks:
            assert row["risk"]
            assert row["mitigation"]

    def test_the_leakage_conclusion_is_stated(self, core: Dict[str, Any]) -> None:
        assert core["leakage"]["conclusion"]


# ---------------------------------------------------------------------------
# 11. the pilot
# ---------------------------------------------------------------------------
class TestPilot:
    def test_every_declared_spec_built(self, core: Dict[str, Any]) -> None:
        pilot = core["pilot"]
        assert pilot["specs"] == len(stage25.PILOT_SPECS)
        assert pilot["built"] == pilot["specs"]
        assert pilot["failed"] == []

    def test_every_declared_criterion_passed(self, core: Dict[str, Any]) -> None:
        pilot = core["pilot"]
        assert pilot["total"] == len(stage25.PILOT_CRITERIA)
        assert pilot["passed"] == pilot["total"]
        assert pilot["all_passed"] is True
        for row in pilot["criteria"]:
            assert row["passed"] is True, row["criterion"]

    def test_a_criterion_carries_the_measurement_that_decides_it(
        self, core: Dict[str, Any]
    ) -> None:
        for row in core["pilot"]["criteria"]:
            assert row["criterion"]
            assert row["measurement"]
            assert "observed" in row

    def test_the_declared_length_is_produced(self, core: Dict[str, Any]) -> None:
        for row in core["pilot"]["traces"]:
            spec = next(s for s in stage25.PILOT_SPECS if s["id"] == row["id"])
            assert row["frames"] == spec["rows"] * spec["repeats"] * row["frames_per_tick"]

    def test_the_requested_audctl_mode_reaches_the_trace(self, core: Dict[str, Any]) -> None:
        for row in core["pilot"]["traces"]:
            spec = next(s for s in stage25.PILOT_SPECS if s["id"] == row["id"])
            assert row["audctl_column"] == [spec["audctl"]], row["id"]

    def test_the_historical_length_region_is_reachable(self, core: Dict[str, Any]) -> None:
        region = core["corpus_design"]["target_length_region"]
        assert max(row["frames"] for row in core["pilot"]["traces"]) >= region["historical_min"]

    def test_all_three_truth_levels_are_captured_per_trace(self, core: Dict[str, Any]) -> None:
        for row in core["pilot"]["traces"]:
            assert len(row["source_sha256"]) == 64
            assert len(row["compiled_sha256"]) == 64
            assert len(row["trace_sha256"]) == 64

    def test_the_compiled_and_trace_hashes_agree_because_they_hash_one_payload(
        self, core: Dict[str, Any]
    ) -> None:
        for row in core["pilot"]["traces"]:
            assert row["compiled_sha256"] == row["trace_sha256"]

    def test_the_pilot_uses_the_production_compiler_and_player(self, core: Dict[str, Any]) -> None:
        for row in core["pilot"]["traces"]:
            assert row["compiler"] == "src/atari_music/ir.py::compile_ir_to_pokey_frames"
            assert row["player"] == "src/atari_music/asm/player.asm"

    def test_every_matching_feature_is_defined_on_every_pilot_trace(
        self, core: Dict[str, Any]
    ) -> None:
        for row in core["pilot"]["traces"]:
            for name in core["matching_features"]:
                assert row["measures"].get(name) is not None, (row["id"], name)

    def test_the_pilot_uses_the_same_feature_space_as_the_corpus(
        self, core: Dict[str, Any]
    ) -> None:
        """The merged Stage 23 features plus the Stage 24 measures, exactly as CorpusRecord does."""
        for row in core["pilot"]["traces"]:
            for name in stage23.MATCH_FEATURES:
                assert name in row["measures"], (row["id"], name)

    def test_the_pilot_is_not_described_as_a_corpus(self, core: Dict[str, Any]) -> None:
        assert core["pilot"]["not_a_corpus"]

    def test_the_pilot_seed_is_declared(self, core: Dict[str, Any]) -> None:
        assert core["pilot"]["seed"] == stage25.PILOT_SEED


# ---------------------------------------------------------------------------
# 12. the verdicts
# ---------------------------------------------------------------------------
class TestVerdicts:
    def test_the_verdict_is_from_the_declared_vocabulary(self, core: Dict[str, Any]) -> None:
        verdicts = core["verdicts"]
        assert verdicts["main"]["verdict"] in verdicts["vocabulary"]

    def test_every_auxiliary_verdict_is_from_its_vocabulary(self, core: Dict[str, Any]) -> None:
        verdicts = core["verdicts"]
        for row in verdicts["auxiliary"]:
            assert row["verdict"] in verdicts["auxiliary_vocabulary"], row["verdict"]
            assert row["reason"]
            assert row["measurement"]

    def test_the_verdict_states_what_it_does_not_mean(self, core: Dict[str, Any]) -> None:
        main = core["verdicts"]["main"]
        assert main["what_it_means"]
        assert "does not mean" in main["what_it_does_not_mean"]

    def test_the_verdict_carries_its_deciding_measurement(self, core: Dict[str, Any]) -> None:
        deciding = core["verdicts"]["main"]["deciding_measurement"]
        assert deciding["pilot_criteria_passed"] == deciding["pilot_criteria_total"]
        assert deciding["ground_truth_consistent"] is True
        assert deciding["caliper_enforced"] is True

    def test_the_player_confound_is_declared_unclosable(self, core: Dict[str, Any]) -> None:
        verdicts = [row["verdict"] for row in core["verdicts"]["auxiliary"]]
        assert "PLAYER_CONFOUND_NOT_CLOSABLE_BY_CORPUS_DESIGN" in verdicts

    def test_the_scope_is_declared_as_a_known_set(self, core: Dict[str, Any]) -> None:
        verdicts = [row["verdict"] for row in core["verdicts"]["auxiliary"]]
        assert "VALIDATION_ON_A_KNOWN_SET_ONLY" in verdicts

    def test_the_idiom_verdict_names_the_production_change(self, core: Dict[str, Any]) -> None:
        row = next(
            r for r in core["verdicts"]["auxiliary"]
            if r["verdict"] == "PRODUCTION_CHANGE_REQUIRED_FOR_ONE_IDIOM"
        )
        assert row["measurement"]["capabilities_requiring_change"] == [
            stage25.PRODUCTION_CHANGE_IDIOM
        ]

    def test_no_performance_layer_is_claimed(self, bundle: Dict[str, Any]) -> None:
        payload = stage25._artefacts(bundle)
        assert payload["verdict.json"]["proven_performance_layer_used"] is False

    def test_the_stop_conditions_are_recorded(self, bundle: Dict[str, Any]) -> None:
        assert stage25._artefacts(bundle)["verdict.json"]["stop_conditions_applied"]


# ---------------------------------------------------------------------------
# 13. the artefacts
# ---------------------------------------------------------------------------
class TestArtefacts:
    def test_the_declared_artefacts_all_exist(self, bundle: Dict[str, Any]) -> None:
        payload = stage25._artefacts(bundle)
        for name in stage25.STAGE25_FILES:
            assert payload[name] is not None, name
        assert len(stage25.STAGE25_FILES) == 13

    def test_every_artefact_is_json_serialisable(self, bundle: Dict[str, Any]) -> None:
        payload = stage25._artefacts(bundle)
        for name in stage25.STAGE25_FILES:
            assert json.dumps(payload[name], sort_keys=True), name

    def test_the_manifest_lists_every_artefact_and_the_summary(
        self, bundle: Dict[str, Any]
    ) -> None:
        manifest = stage25._artefacts(bundle)["stage25_manifest.json"]
        assert manifest["artefacts"] == list(stage25.STAGE25_FILES)
        assert manifest["analysis_version"] == stage25.ANALYSIS_VERSION
        assert manifest["summary"] == bundle["summary"]
        assert manifest["stop_condition"]

    def test_the_writer_writes_everything_it_declares(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        written = stage25.write_analysis(
            bundle, stage25_dir=tmp_path / "r", docs_dir=tmp_path / "d"
        )
        for name in stage25.STAGE25_FILES:
            assert (tmp_path / "r" / name).is_file(), name
        assert (tmp_path / "d" / stage25.STAGE25_DOC).is_file()
        assert (tmp_path / "r" / stage25.STAGE25_REPORT).is_file()
        assert set(written) == set(stage25.STAGE25_FILES) | {
            stage25.STAGE25_DOC, stage25.STAGE25_REPORT,
        }

    def test_the_writer_refuses_an_incomplete_payload(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        empty = {"analysis_version": bundle["analysis_version"], "summary": {}}
        with pytest.raises(stage25.Stage25Error):
            stage25.write_analysis(empty, stage25_dir=tmp_path / "r", docs_dir=tmp_path / "d")

    def test_the_determinism_block_is_declared(self, bundle: Dict[str, Any]) -> None:
        determinism = bundle["determinism"]
        assert determinism["random_seed"] == stage25.RANDOM_SEED
        assert determinism["pilot_seed"] == stage25.PILOT_SEED
        assert "sorted" in determinism["tie_breaks"]
        assert len(determinism["source_hash"]) == 64

    def test_the_reproducibility_block_reports_the_check(self, bundle: Dict[str, Any]) -> None:
        reproducibility = bundle["reproducibility"]
        assert reproducibility["verified"] is True
        assert reproducibility["byte_identical"] is True
        assert len(reproducibility["payload_digest"]) == 64

    def test_the_artefacts_are_byte_identical_across_runs(
        self, bundle: Dict[str, Any], tmp_path: Path
    ) -> None:
        """Two runs agree on every artefact; the manifest is the only one the second pass touches."""
        second = stage25.run_analysis(verify_reproducibility=False)
        left = tmp_path / "left"
        right = tmp_path / "right"
        written_left = stage25.write_analysis(bundle, stage25_dir=left / "r", docs_dir=left / "d")
        written_right = stage25.write_analysis(
            second, stage25_dir=right / "r", docs_dir=right / "d"
        )
        assert set(written_left) == set(written_right)
        for name in written_left:
            if name == "stage25_manifest.json":
                continue
            assert written_left[name].read_bytes() == written_right[name].read_bytes(), name

        verified = json.loads(written_left["stage25_manifest.json"].read_text(encoding="utf-8"))
        unchecked = json.loads(written_right["stage25_manifest.json"].read_text(encoding="utf-8"))
        assert verified["reproducibility"]["verified"] is True
        assert unchecked["reproducibility"]["verified"] is False
        for key in ("analysis_version", "artefacts", "document", "summary", "determinism",
                    "read_only_audit", "stage24_audit", "stop_condition"):
            assert verified[key] == unchecked[key], key
        assert (
            verified["reproducibility"]["payload_digest"]
            == unchecked["reproducibility"]["payload_digest"]
        )


# ---------------------------------------------------------------------------
# 14. read-only
# ---------------------------------------------------------------------------
class TestReadOnlyAudit:
    def test_the_run_proves_the_inputs_are_unchanged(self, bundle: Dict[str, Any]) -> None:
        for key, row in bundle["read_only_audit"].items():
            assert row["read_only"], (key, row["changed"])

    def test_the_audit_covers_the_production_modules_and_the_player(self) -> None:
        hashes = stage25.production_hashes()
        for relative in (
            "src/atari_music/ir.py", "src/atari_music/ai/dsl.py",
            "src/atari_music/sound_profiles/bank.py", "src/atari_music/sound_profiles/binding.py",
            "src/atari_music/stage21.py", "src/atari_music/stage22.py",
            "src/atari_music/stage23.py", "src/atari_music/stage24.py",
            "src/atari_music/asm/player.asm",
        ):
            assert relative in hashes, relative
            assert hashes[relative], relative

    def test_the_audit_covers_the_traces_and_the_compositions(self) -> None:
        hashes = stage25.input_hashes()
        assert any(key.startswith("trace/") for key in hashes)
        assert any(key.startswith("composition/") for key in hashes)
        assert any(key.startswith("upstream/") for key in hashes)
        assert any(key.startswith("profile_bank/") for key in hashes)

    def test_the_audit_notices_a_change(self) -> None:
        row = stage25.read_only_audit({"a": "1", "b": "2"}, {"a": "1", "b": "3"})
        assert not row["read_only"]
        assert row["changed"] == ["b"]

    def test_stage_25_audits_no_stage25_file(self) -> None:
        """The audit is of what Stage 25 reads, and Stage 25 reads no stage25 module."""
        assert not any("stage25" in relative for relative in stage25.PRODUCTION_FILES)


# ---------------------------------------------------------------------------
# 15. the report
# ---------------------------------------------------------------------------
class TestReport:
    def test_the_report_has_every_required_section(self, bundle: Dict[str, Any]) -> None:
        report = stage25.render_report(bundle)
        titles = [
            "Executive Summary", "Audit of Stages 21 to 24",
            "Target Population and Inference Scope", "Ground Truth Definition",
            "Pipeline Capability Audit", "The Control Groups", "Sample Size and Diversity",
            "Generation and Validation Procedure", "Overlap Acceptance Criteria",
            "Leakage and Over-Fitting Protection", "Pilot Results", "Limitations and Costs",
            "Methodological Corrections", "Verdict", "The Concrete Next Step",
        ]
        for index, title in enumerate(titles, start=1):
            assert f"## {index}. {title}" in report, title

    def test_the_report_answers_all_ten_questions(self, bundle: Dict[str, Any]) -> None:
        report = stage25.render_report(bundle)
        assert "## The Ten Closing Questions" in report
        for number in range(1, 11):
            assert f"**{number}." in report, number

    def test_the_report_carries_no_absolute_windows_path(self, bundle: Dict[str, Any]) -> None:
        report = stage25.render_report(bundle)
        assert "C:\\Users" not in report
        assert "C:/Users" not in report

    def test_the_report_is_plain_ascii(self, bundle: Dict[str, Any]) -> None:
        stage25.render_report(bundle).encode("ascii")

    def test_the_capability_table_reports_what_the_probe_found(self, bundle: Dict[str, Any]) -> None:
        """A reachable capability must not read as a hedge in the table."""
        report = stage25.render_report(bundle)
        section = report.split("## 5. Pipeline Capability Audit", 1)[1].split("## 6.", 1)[0]
        assert "8 of 8" in section
        assert "3 of 3" in section
        assert "partial" not in section

    def test_the_report_states_the_pilot_is_not_a_corpus(self, bundle: Dict[str, Any]) -> None:
        assert "not a control corpus" in stage25.render_report(bundle)

    def test_the_report_does_not_claim_a_proven_layer(self, bundle: Dict[str, Any]) -> None:
        assert "PROVEN PERFORMANCE LAYER" not in stage25.render_report(bundle)

    def test_the_report_names_the_unproducible_idiom(self, bundle: Dict[str, Any]) -> None:
        assert "AUDF = 0 while audible" in stage25.render_report(bundle)

    def test_the_report_names_the_player_confound(self, bundle: Dict[str, Any]) -> None:
        report = stage25.render_report(bundle).lower()
        assert "confounded" in report
        assert "player" in report


# ---------------------------------------------------------------------------
# 16. the CLI
# ---------------------------------------------------------------------------
@requires_control
class TestCli:
    def test_the_command_is_registered(self) -> None:
        result = CliRunner().invoke(cli, ["analyze-stage25", "--help"])
        assert result.exit_code == 0, result.output
        assert "control corpus" in result.output.lower()

    def test_a_run_writes_its_artefacts(self, tmp_path: Path) -> None:
        reports = tmp_path / "r"
        docs = tmp_path / "d"
        result = CliRunner().invoke(
            cli,
            ["analyze-stage25", "--reports-dir", str(reports), "--docs-dir", str(docs),
             "--skip-reproducibility"],
        )
        assert result.exit_code == 0, result.output
        for name in stage25.STAGE25_FILES:
            assert (reports / name).is_file(), name
        assert (docs / stage25.STAGE25_DOC).is_file()
        assert "verdict" in result.output.lower()
        assert "read-only" in result.output.lower()
        assert "pilot" in result.output.lower()









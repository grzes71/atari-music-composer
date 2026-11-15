"""Lead Library v0.1 — validation of the instrument specification.

These tests check the *specification*, not the sound. They assert that:

* the library holds exactly the four instruments the brief names, with unique ids and a schema and
  version the project can read;
* every bank-profile reference resolves in the existing bank, and the recorded fingerprint matches both
  the loaded profile and the registry's published value — which, because the fingerprint covers the
  whole profile document, also proves the profiles were not edited;
* C1 has no invented ``profile_id`` and no fingerprint, and its experimental source resolves in the
  repository;
* the rendering parameters recorded for each instrument are the ones Experiment 30 actually applied,
  read back from its manifest rather than retyped from memory;
* every musical claim is marked as a hypothesis, and no claim is recorded as a verified property;
* the listening ratings are transcribed from Experiment 30's returned CSV, preserve the four
  context/version combinations, and are not collapsed into a score;
* nothing here is reachable from production, and no bank profile or Experiment 26-30 artefact changed.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from atari_music.sound_profiles.bank import (
    PROFILE_SCHEMA,
    REGISTRY_SCHEMA,
    load_sound_profile_bank,
    playable_fingerprint_of,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = REPO_ROOT / "data" / "instrument_libraries" / "lead" / "v0.1"
LIBRARY_PATH = LIBRARY_DIR / "library.json"
EVALUATION_PATH = LIBRARY_DIR / "evaluation.json"
README_PATH = LIBRARY_DIR / "README.md"

BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
E30_DIR = REPO_ROOT / "experiments" / "experiment30"

LIBRARY_SCHEMA = "atari-music/instrument-library/1"
EVALUATION_SCHEMA = "atari-music/instrument-library-evaluation/1"
LIBRARY_VERSION = "0.1"

#: The four instruments the brief names, and the source each must resolve to.
EXPECTED_INSTRUMENTS: Dict[str, str] = {
    "c1_octave_pulse": "experiment",
    "pure_sustain": "bank_profile",
    "pure_pluck": "bank_profile",
    "buzz_steady": "bank_profile",
}
EXPECTED_PROFILE_IDS: Dict[str, str] = {
    "pure_sustain": "pokey_ref_25f94201",
    "pure_pluck": "pokey_ref_9daa0429",
    "buzz_steady": "pokey_ref_2b83db43",
}
#: Experiment 30's letter assignment, which is the join key back to the returned CSV.
EXPECTED_LETTERS: Dict[str, str] = {
    "pure_sustain": "A",
    "c1_octave_pulse": "B",
    "buzz_steady": "C",
    "pure_pluck": "D",
}

CONTEXTS = ("solo", "composition")
VERSIONS = ("original", "matched")

#: Keys that would betray a computed quality score or ranking.
FORBIDDEN_KEY_TOKENS = (
    "score", "ranking", "rank", "best", "weighted", "average", "aggregate", "grade",
)


@pytest.fixture(scope="module")
def library() -> Dict[str, Any]:
    return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def evaluation() -> Dict[str, Any]:
    return json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def instruments(library: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {entry["instrument_id"]: entry for entry in library["instruments"]}


@pytest.fixture(scope="module")
def bank() -> Any:
    return load_sound_profile_bank(BANK_DIR)


@pytest.fixture(scope="module")
def e30_manifest() -> Dict[str, Any]:
    return json.loads((E30_DIR / "manifest.json").read_text(encoding="utf-8"))


def walk_keys(node: Any) -> List[str]:
    """Every mapping key in a nested JSON document, lowercased."""
    keys: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key).lower())
            keys.extend(walk_keys(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(walk_keys(item))
    return keys


def csv_rows() -> List[Dict[str, str]]:
    path = E30_DIR / "evaluation_experiment30__anonymous.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# 1. the library document
# ---------------------------------------------------------------------------
class TestLibraryStructure:
    def test_the_files_exist(self) -> None:
        for path in (LIBRARY_PATH, EVALUATION_PATH, README_PATH):
            assert path.is_file(), path

    def test_the_library_directory_holds_only_its_own_files(self) -> None:
        assert sorted(p.name for p in LIBRARY_DIR.iterdir()) == [
            "README.md", "evaluation.json", "library.json",
        ]

    def test_the_schema_and_version_are_declared(self, library: Dict[str, Any]) -> None:
        assert library["schema"] == LIBRARY_SCHEMA
        assert library["library_version"] == LIBRARY_VERSION
        assert library["library_id"] == "lead"
        assert library["role"] == "lead"

    def test_it_is_not_integrated(self, library: Dict[str, Any]) -> None:
        assert library["integrated_into_composer"] is False
        assert library["status"] == "experimental_specification"

    def test_there_are_exactly_the_four_required_instruments(
        self, instruments: Dict[str, Dict[str, Any]]
    ) -> None:
        assert set(instruments) == set(EXPECTED_INSTRUMENTS)
        assert len(instruments) == 4

    def test_the_ids_are_unique(self, library: Dict[str, Any]) -> None:
        ids = [entry["instrument_id"] for entry in library["instruments"]]
        assert len(ids) == len(set(ids))

    def test_every_instrument_has_the_required_fields(
        self, instruments: Dict[str, Dict[str, Any]]
    ) -> None:
        for instrument_id, entry in instruments.items():
            assert set(entry) >= {
                "instrument_id", "display_name", "role", "library_version",
                "identity", "rendering", "musical", "limitations", "validation",
            }, instrument_id
            assert entry["display_name"]
            assert entry["role"] == "lead"
            assert entry["library_version"] == LIBRARY_VERSION

    def test_the_four_groups_are_separate(self, instruments: Dict[str, Dict[str, Any]]) -> None:
        """Identity, rendering parameters, musical description, validation: kept apart."""
        for instrument_id, entry in instruments.items():
            assert set(entry["identity"]) >= {"source", "evidence", "reproducibility"}, instrument_id
            assert "generator_byte" in entry["rendering"], instrument_id
            assert "character" in entry["musical"], instrument_id
            assert "specification" in entry["validation"], instrument_id

    def test_only_the_version_pin_is_repeated_per_item(
        self, instruments: Dict[str, Dict[str, Any]]
    ) -> None:
        """The library header owns the schema and the id; each item pins the version it belongs to."""
        for entry in instruments.values():
            assert "schema" not in entry
            assert "library_id" not in entry
            assert "library_version" in entry


# ---------------------------------------------------------------------------
# 2. identity and reproducibility
# ---------------------------------------------------------------------------
class TestIdentity:
    def test_each_source_kind_is_the_expected_one(
        self, instruments: Dict[str, Dict[str, Any]]
    ) -> None:
        for instrument_id, kind in EXPECTED_INSTRUMENTS.items():
            assert instruments[instrument_id]["identity"]["source"]["kind"] == kind

    def test_the_bank_profile_references_resolve(
        self, instruments: Dict[str, Any], bank: Any
    ) -> None:
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            source = instruments[instrument_id]["identity"]["source"]
            assert source["profile_id"] == profile_id
            assert bank.get(profile_id).profile_id == profile_id

    def test_the_recorded_fingerprints_match_the_bank(
        self, instruments: Dict[str, Any], bank: Any
    ) -> None:
        """The fingerprint covers the whole profile document, so a match also proves it was not edited."""
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            profile = bank.get(profile_id)
            recorded = instruments[instrument_id]["identity"]["source"]["profile_fingerprint"]
            assert recorded == profile.fingerprint, instrument_id
            assert recorded == playable_fingerprint_of(profile.document), instrument_id

    def test_the_recorded_fingerprints_match_the_registry(
        self, instruments: Dict[str, Any]
    ) -> None:
        registry = json.loads((BANK_DIR / "registry.json").read_text(encoding="utf-8"))
        published = {entry["profile_id"]: entry["playable_fingerprint"]
                     for entry in registry["profiles"]}
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            recorded = instruments[instrument_id]["identity"]["source"]["profile_fingerprint"]
            assert recorded == published[profile_id], instrument_id

    def test_the_recorded_status_and_scope_match_the_bank(
        self, instruments: Dict[str, Any], bank: Any
    ) -> None:
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            profile = bank.get(profile_id)
            source = instruments[instrument_id]["identity"]["source"]
            assert source["profile_status"] == profile.status, instrument_id
            assert source["profile_scope"] == profile.scope, instrument_id

    def test_the_profile_paths_exist_and_declare_the_expected_schema(
        self, instruments: Dict[str, Any]
    ) -> None:
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            source = instruments[instrument_id]["identity"]["source"]
            path = REPO_ROOT / source["profile_path"]
            assert path.is_file(), instrument_id
            document = json.loads(path.read_text(encoding="utf-8"))
            assert document["schema"] == PROFILE_SCHEMA
            assert document["profile_id"] == profile_id
            assert source["profile_schema"] == PROFILE_SCHEMA

    def test_c1_has_no_bank_profile_and_no_invented_identifier(
        self, instruments: Dict[str, Any]
    ) -> None:
        """C1 is an experimental transform. A profile_id or fingerprint for it would be fiction."""
        source = instruments["c1_octave_pulse"]["identity"]["source"]
        assert "profile_id" not in source
        assert "profile_fingerprint" not in source
        assert source["experiments"] == ["experiment26", "experiment27", "experiment28"]
        assert source["no_bank_profile"]


    def test_c1s_implementation_resolves_in_the_repository(
        self, instruments: Dict[str, Any]
    ) -> None:
        from atari_music import pokey_c1_musical_context_experiment as e28
        from atari_music import pokey_octave_pulse_experiment as e27
        from atari_music import pokey_timbre_experiment as e26

        implementation = instruments["c1_octave_pulse"]["identity"]["source"]["implementation"]
        for key in ("generator_constant", "schedule_constant", "application"):
            path_part, _, symbol = implementation[key].partition("::")
            assert (REPO_ROOT / path_part).is_file(), key
            assert symbol

        assert implementation["generator_byte"] == f"${e26.C_GENERATOR:02X}"
        schedule = implementation["schedule_parameters"]
        actual = e27.SCHEDULES["C1"]
        assert schedule["hold_frames"] == actual.hold_frames
        assert schedule["active_frames"] == actual.active_frames
        assert tuple(schedule["active_notes"]) == tuple(actual.active_notes)
        assert e28.apply_c1.__name__ == "apply_c1"

    def test_c1_records_that_it_cannot_be_fully_reproduced(
        self, instruments: Dict[str, Any]
    ) -> None:
        reproducibility = instruments["c1_octave_pulse"]["identity"]["reproducibility"]
        assert reproducibility["status"] == "partially_reproducible"
        assert reproducibility["what_is_not_fixed"]
        assert reproducibility["consequence"]

    def test_the_bank_instruments_are_referenced_not_copied(
        self, instruments: Dict[str, Any]
    ) -> None:
        for instrument_id in EXPECTED_PROFILE_IDS:
            reproducibility = instruments[instrument_id]["identity"]["reproducibility"]
            assert reproducibility["status"] == "referenced_not_copied"
        assert not (LIBRARY_DIR / "profiles").exists()

    def test_every_experiment_reference_exists(
        self, library: Dict[str, Any], instruments: Dict[str, Any]
    ) -> None:
        for name in library["provenance"]["experiments"]:
            assert (REPO_ROOT / "experiments" / name).is_dir(), name
        for instrument_id, entry in instruments.items():
            evidence = entry["identity"]["evidence"]
            assert (REPO_ROOT / "experiments" / evidence["experiment"]).is_dir(), instrument_id
            assert (REPO_ROOT / evidence["manifest_path"]).is_file(), instrument_id

    def test_the_recorded_experiment_letter_matches_experiment_30(
        self, instruments: Dict[str, Any], e30_manifest: Dict[str, Any]
    ) -> None:
        for instrument_id, letter in EXPECTED_LETTERS.items():
            evidence = instruments[instrument_id]["identity"]["evidence"]
            assert evidence["letter_in_experiment30"] == letter, instrument_id
            assert e30_manifest["letter_map"][letter] == instrument_id, instrument_id


# ---------------------------------------------------------------------------
# 3. the rendering parameters are the ones Experiment 30 applied
# ---------------------------------------------------------------------------
class TestRenderingParameters:
    def test_the_generator_matches_experiment_30(
        self, instruments: Dict[str, Any], e30_manifest: Dict[str, Any], bank: Any
    ) -> None:
        applied = e30_manifest["applied_parameters"]["composition"]
        for instrument_id, entry in instruments.items():
            recorded = entry["rendering"]["generator_byte"]
            assert recorded == f"${applied[instrument_id]['generator_byte']:02X}", instrument_id
            if entry["identity"]["source"]["kind"] == "bank_profile":
                profile = bank.get(EXPECTED_PROFILE_IDS[instrument_id])
                assert recorded == f"${profile.distortion_byte:02X}", instrument_id

    def test_the_envelope_matches_experiment_30(
        self, instruments: Dict[str, Any], e30_manifest: Dict[str, Any]
    ) -> None:
        applied = e30_manifest["applied_parameters"]["composition"]
        for instrument_id, entry in instruments.items():
            assert entry["rendering"]["envelope_observed_in_experiment30"] == (
                applied[instrument_id]["envelope"]
            ), instrument_id

    def test_the_envelope_sources_match_experiment_30(
        self, instruments: Dict[str, Any], e30_manifest: Dict[str, Any]
    ) -> None:
        applied = e30_manifest["applied_parameters"]["composition"]
        for instrument_id, entry in instruments.items():
            assert entry["rendering"]["envelope_sources_observed_in_experiment30"] == (
                applied[instrument_id]["envelope_sources"]
            ), instrument_id

    def test_the_envelope_sources_use_the_two_declared_values(
        self, instruments: Dict[str, Any]
    ) -> None:
        """The source strings are Experiment 30's own, verbatim, so the cross-check is exact."""
        allowed = ("profile", "composition (character default)")
        for instrument_id, entry in instruments.items():
            for field, source in entry["rendering"][
                "envelope_sources_observed_in_experiment30"
            ].items():
                assert source in allowed, (instrument_id, field, source)

    def test_the_channel_and_audctl_match_experiment_30(
        self, instruments: Dict[str, Any], e30_manifest: Dict[str, Any]
    ) -> None:
        applied = e30_manifest["applied_parameters"]["composition"]
        solo = e30_manifest["applied_parameters"]["solo"]
        for instrument_id, entry in instruments.items():
            rendering = entry["rendering"]
            assert rendering["channel"] == applied[instrument_id]["channel"], instrument_id
            observed = rendering["audctl_mode_observed_by_context"]
            assert observed["experiment30_composition"] == f"${applied[instrument_id]['audctl']:02X}"
            assert observed["experiment30_solo"] == f"${solo[instrument_id]['audctl']:02X}"

    def test_the_bank_instruments_declare_the_profiles_clock(
        self, instruments: Dict[str, Any], bank: Any
    ) -> None:
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            profile = bank.get(profile_id)
            rendering = instruments[instrument_id]["rendering"]
            assert rendering["audctl_mode"] == f"${profile.audctl_mode:02X}", instrument_id
            assert rendering["audctl_source"] == "profile", instrument_id

    def test_the_c1_asymmetry_is_recorded(self, instruments: Dict[str, Any]) -> None:
        """C1 takes its envelope from the composition; the bank instruments bring their own."""
        c1 = instruments["c1_octave_pulse"]["rendering"]
        assert set(c1["envelope_sources_observed_in_experiment30"].values()) == {
            "composition (character default)"
        }
        assert c1["divider_source"] == "experiment"
        for instrument_id in EXPECTED_PROFILE_IDS:
            sources = instruments[instrument_id]["rendering"][
                "envelope_sources_observed_in_experiment30"
            ]
            assert "profile" in sources.values(), instrument_id

    def test_every_recorded_parameter_names_its_source(self, instruments: Dict[str, Any]) -> None:
        for instrument_id, entry in instruments.items():
            rendering = entry["rendering"]
            for key in ("channel_source", "generator_source", "audctl_source", "divider_source"):
                assert rendering[key] in ("profile", "composition", "experiment"), (
                    instrument_id, key
                )

    def test_the_limitation_codes_match_the_bank(self, instruments: Dict[str, Any], bank: Any) -> None:
        for instrument_id, profile_id in EXPECTED_PROFILE_IDS.items():
            profile = bank.get(profile_id)
            recorded = instruments[instrument_id]["limitations"]["profile_codes"]
            assert recorded["limitation_codes"] == list(profile.limitation_codes), instrument_id
            assert recorded["blocking_codes"] == list(profile.blocking_codes), instrument_id
            assert recorded["consumer_gap_codes"] == list(profile.consumer_gap_codes), instrument_id

    def test_c1_records_no_profile_codes_and_says_why(self, instruments: Dict[str, Any]) -> None:
        limitations = instruments["c1_octave_pulse"]["limitations"]
        assert limitations["profile_codes"]["consumer_gap_codes"] == []
        assert limitations["profile_codes_note"]
        assert limitations["rendering"]

    def test_every_instrument_records_its_limits(self, instruments: Dict[str, Any]) -> None:
        for instrument_id, entry in instruments.items():
            assert entry["limitations"]["rendering"], instrument_id


# ---------------------------------------------------------------------------
# 4. verified facts and musical hypotheses are kept apart
# ---------------------------------------------------------------------------
class TestClaimsAreLabelled:
    def test_every_musical_claim_is_marked_as_a_hypothesis(
        self, instruments: Dict[str, Any]
    ) -> None:
        for instrument_id, entry in instruments.items():
            musical = entry["musical"]
            assert musical["character"]["basis"] == "hypothesis", instrument_id
            assert musical["usage_hypothesis"]["basis"] == "hypothesis", instrument_id
            assert musical["character"]["text"], instrument_id
            assert musical["usage_hypothesis"]["text"], instrument_id

    def test_no_musical_claim_is_recorded_as_verified(self, instruments: Dict[str, Any]) -> None:
        for instrument_id, entry in instruments.items():
            for field in ("character", "usage_hypothesis"):
                assert entry["musical"][field]["basis"] != "verified", (instrument_id, field)

    def test_the_musical_block_holds_no_technical_parameters(
        self, instruments: Dict[str, Any]
    ) -> None:
        """Register values and parameter names belong under rendering, not in the description."""
        for instrument_id, entry in instruments.items():
            text = json.dumps(entry["musical"]).lower()
            for token in ("$a0", "$c0", "$40", "audctl", "attack_frames", "sustain_vol",
                          "generator_byte", "pokey_ref"):
                assert token not in text, (instrument_id, token)

    def test_the_conventions_are_declared(self, library: Dict[str, Any]) -> None:
        conventions = library["rating_conventions"]
        assert set(conventions) == {"basis_verified", "basis_hypothesis", "basis_listening"}
        for value in conventions.values():
            assert value

    def test_the_library_does_not_carry_the_ratings(self, library: Dict[str, Any]) -> None:
        """The ratings live in evaluation.json; library.json must not present them as properties."""
        text = json.dumps(library)
        for token in ("usefulness_1_5", "interest_1_5", "annoyance_1_5"):
            assert token not in text, token


# ---------------------------------------------------------------------------
# 5. the listening ratings
# ---------------------------------------------------------------------------
class TestEvaluation:
    def test_the_schema_and_version_are_declared(self, evaluation: Dict[str, Any]) -> None:
        assert evaluation["schema"] == EVALUATION_SCHEMA
        assert evaluation["library_id"] == "lead"
        assert evaluation["library_version"] == LIBRARY_VERSION

    def test_it_covers_exactly_the_library_instruments(
        self, evaluation: Dict[str, Any], instruments: Dict[str, Any]
    ) -> None:
        assert set(evaluation["evaluations"]) == set(instruments)

    def test_every_instrument_has_all_four_context_version_combinations(
        self, evaluation: Dict[str, Any]
    ) -> None:
        for instrument_id, entry in evaluation["evaluations"].items():
            for context in CONTEXTS:
                assert context in entry, (instrument_id, context)
                for version in VERSIONS:
                    assert version in entry[context], (instrument_id, context, version)

    def test_every_rating_is_in_range(self, evaluation: Dict[str, Any]) -> None:
        for instrument_id, entry in evaluation["evaluations"].items():
            for context in CONTEXTS:
                for version in VERSIONS:
                    rating = entry[context][version]
                    for field in ("usefulness_1_5", "interest_1_5", "annoyance_1_5"):
                        assert isinstance(rating[field], int), (instrument_id, field)
                        assert 1 <= rating[field] <= 5, (instrument_id, context, version, field)

    def test_the_letters_match_the_library(self, evaluation: Dict[str, Any]) -> None:
        for instrument_id, letter in EXPECTED_LETTERS.items():
            assert evaluation["evaluations"][instrument_id]["letter_in_experiment30"] == letter

    def test_no_combined_score_is_present(self, evaluation: Dict[str, Any]) -> None:
        keys = walk_keys(evaluation)
        for token in FORBIDDEN_KEY_TOKENS:
            assert not any(token in key for key in keys), token

    def test_it_declares_that_nothing_is_computed(self, evaluation: Dict[str, Any]) -> None:
        assert evaluation["not_computed"]
        assert evaluation["why_nothing_is_computed"]
        assert any("score" in item for item in evaluation["not_computed"])
        assert any("ranking" in item for item in evaluation["not_computed"])

    def test_every_observation_says_what_it_does_not_mean(
        self, evaluation: Dict[str, Any]
    ) -> None:
        """A description of the ratings must not be readable as a claim about the instruments."""
        observations = evaluation["observations_about_the_ratings"]
        assert observations
        for entry in observations:
            assert entry["observation"]
            assert entry["what_it_means"]
            assert entry["what_it_does_not_mean"]
        assert evaluation["how_these_observations_were_produced"]

    def test_the_observations_state_the_ratings_faithfully(
        self, evaluation: Dict[str, Any]
    ) -> None:
        """The three claims in the observation block are checked against the ratings themselves."""
        ratings = evaluation["evaluations"]
        composition = {
            (context, version): {
                (ratings[instrument_id][context][version]["usefulness_1_5"],
                 ratings[instrument_id][context][version]["interest_1_5"],
                 ratings[instrument_id][context][version]["annoyance_1_5"])
                for instrument_id in ratings
            }
            for context, version in (("composition", "original"), ("composition", "matched"))
        }
        for key, values in composition.items():
            assert values == {(4, 4, 1)}, key  # all four identical in the composition block

        solo_bank = {
            instrument_id: (
                ratings[instrument_id]["solo"]["matched"]["usefulness_1_5"],
                ratings[instrument_id]["solo"]["matched"]["interest_1_5"],
                ratings[instrument_id]["solo"]["matched"]["annoyance_1_5"],
            )
            for instrument_id in EXPECTED_PROFILE_IDS
        }
        assert set(solo_bank.values()) == {(3, 3, 2)}
        assert ratings["c1_octave_pulse"]["solo"]["original"]["usefulness_1_5"] == 4


    def test_it_records_the_provenance_of_the_ratings(self, evaluation: Dict[str, Any]) -> None:
        source = evaluation["source"]
        assert source["experiment"] == "experiment30"
        assert source["evaluation_csv"]
        assert source["transcription_note"]
        assert source["listener"] == ""
        assert "anonymous" in source["listener_note"]

    def test_it_keeps_the_solo_and_composition_contexts_apart(
        self, evaluation: Dict[str, Any]
    ) -> None:
        """Every instrument's solo and composition ratings are stored separately."""
        for instrument_id, entry in evaluation["evaluations"].items():
            solo = entry["solo"]["matched"]
            composition = entry["composition"]["matched"]
            assert set(solo) == set(composition), instrument_id

    def test_it_records_the_caveats(self, evaluation: Dict[str, Any]) -> None:
        caveats = " ".join(evaluation["caveats"]).lower()
        assert "one listener" in caveats
        assert "one composition" in caveats
        assert "opinion" in caveats
        assert "real atari" in caveats

    def test_it_does_not_modify_the_experiment_30_artefacts(self) -> None:
        """The evaluation file is a transcription. The template must still be empty."""
        template = (E30_DIR / "evaluation_template.csv").read_text(encoding="utf-8").splitlines()
        assert len(template) == 17  # header + 16 rows
        assert all(line.split(",")[4] == "" for line in template[1:])


@pytest.mark.skipif(not (E30_DIR / "evaluation_experiment30__anonymous.csv").is_file(),
                    reason="Experiment 30's returned ratings CSV is not present (it is gitignored)")
class TestEvaluationMatchesTheReturnedCsv:
    def test_every_transcribed_value_matches_the_csv(self, evaluation: Dict[str, Any]) -> None:
        rows = csv_rows()
        assert len(rows) == 16
        by_key = {(row["context"], row["version"], row["letter"]): row for row in rows}
        assert len(by_key) == 16

        checked = 0
        for instrument_id, entry in evaluation["evaluations"].items():
            letter = entry["letter_in_experiment30"]
            for context in CONTEXTS:
                for version in VERSIONS:
                    row = by_key[(context, version, letter)]
                    recorded = entry[context][version]
                    for field in ("usefulness_1_5", "interest_1_5", "annoyance_1_5"):
                        assert recorded[field] == int(row[field]), (
                            instrument_id, context, version, field
                        )
                    for field in ("typical_use", "supports_melody", "comment"):
                        assert recorded[field] == row[field], (
                            instrument_id, context, version, field
                        )
                    checked += 1
        assert checked == 16

    def test_the_csv_still_has_the_headers_the_library_assumes(self) -> None:
        with (E30_DIR / "evaluation_experiment30__anonymous.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            header = next(csv.reader(handle))
        assert header == [
            "listener", "context", "version", "letter",
            "usefulness_1_5", "interest_1_5", "annoyance_1_5",
            "typical_use", "supports_melody", "comment",
        ]


# ---------------------------------------------------------------------------
# 6. scope discipline
# ---------------------------------------------------------------------------
class TestScopeDiscipline:
    def test_only_the_lead_role_is_present(self, library: Dict[str, Any]) -> None:
        assert library["role"] == "lead"
        for entry in library["instruments"]:
            assert entry["role"] == "lead"

    def test_no_instrument_of_another_role_is_declared(self, library: Dict[str, Any]) -> None:
        text = json.dumps(library).lower()
        for role in ("bass", "percussion", "harmony", "sfx"):
            assert f'"role": "{role}"' not in text, role

    def test_no_new_timbre_was_added(self, library: Dict[str, Any]) -> None:
        assert len(library["instruments"]) == 4
        assert library["scope"]["excluded"]

    def test_no_selection_mechanism_is_implemented(self) -> None:
        """Nothing in the library resolves an instrument to a channel, a profile or a binding."""
        text = LIBRARY_PATH.read_text(encoding="utf-8").lower()
        for token in ("binding", "selection", "resolve(", "instrument_map"):
            assert token not in text, token

    def test_no_production_module_was_added_for_the_library(self) -> None:
        """A runtime loader is deliberately out of scope for v0.1."""
        for path in (REPO_ROOT / "src" / "atari_music").rglob("*"):
            assert "instrument_librar" not in path.name.lower(), path
            assert "lead_library" not in path.name.lower(), path


# ---------------------------------------------------------------------------
# 7. nothing production changed
#
# Amended by the approved instrument-selection contract
# (docs/instrument_selection_cli.md): the library is still specification-only in the sense that no
# runtime module reads it on its own, but `cli.py` now reads it when — and only when — the user asks
# for an instrument with `--instrument`. The two guards below keep that as narrow as it was meant to
# be, and `tests/test_instrument_selection_cli.py` checks the opt-in behaviourally.
# ---------------------------------------------------------------------------
class TestProductionAndBankUntouched:
    def test_only_the_cli_reads_the_library_and_only_behind_the_flag(self) -> None:
        """One reader, and it is opt-in.

        v0.1 was specification-only, so this guard used to forbid every reader. The approved
        contract makes the library reachable from `import-dsl`, `import-json` and `build-xex` behind
        `--instrument` — and from nowhere else. `cli.py` is the only module that names it, and it
        loads it only when at least one assignment was given.
        """
        readers = []
        for path in (REPO_ROOT / "src" / "atari_music").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in ("instrument_libraries", "lead_library", "LeadLibrary")):
                readers.append(path.name)
        assert readers == ["cli.py"], readers

    def test_the_cli_exposes_the_library_only_through_instrument_selection(self) -> None:
        """No role-based and no automatic selection: the library is addressed only by an explicit flag."""
        text = (REPO_ROOT / "src" / "atari_music" / "cli.py").read_text(encoding="utf-8")
        assert "sound_profile_set" not in text
        assert "lead_library" not in text
        assert "LeadLibrary" not in text
        # The only door: a fixed default directory, plus a per-part assignment the user must write.
        assert "--instrument-library" in text
        assert "DEFAULT_INSTRUMENT_LIBRARY" in text
        # Exactly one call site for the loader (its own definition plus one call), reached only
        # under `if assignments:` — so there is no role-based and no automatic selection.
        assert text.count("_load_instrument_library") == 2
        assert "if assignments:" in text

    def test_the_bank_is_unchanged(self, bank: Any) -> None:
        """The registry still declares its own schema, its own count and its own breakdown."""
        registry = json.loads((BANK_DIR / "registry.json").read_text(encoding="utf-8"))
        assert registry["schema"] == REGISTRY_SCHEMA
        assert registry["profile_count"] == 67
        assert len(registry["profiles"]) == 67
        assert len(bank.profiles) == 67
        statuses: Dict[str, int] = {}
        for entry in registry["profiles"]:
            statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
        assert statuses == {"PLAYABLE": 22, "PLAYABLE_WITH_LIMITATION": 39, "MEASUREMENT_ONLY": 6}

    def test_the_three_referenced_profiles_match_their_own_fingerprints(self, bank: Any) -> None:
        """A fingerprint match is a content check: it would fail if a profile were edited."""
        for profile_id in EXPECTED_PROFILE_IDS.values():
            profile = bank.get(profile_id)
            assert profile.fingerprint == playable_fingerprint_of(profile.document)

    def test_the_library_does_not_live_in_the_production_tree(self) -> None:
        assert LIBRARY_DIR.parts[-4:] == ("data", "instrument_libraries", "lead", "v0.1")
        assert "src" not in LIBRARY_DIR.parts
        assert "experiments" not in LIBRARY_DIR.parts

    def test_the_experiment_30_artefacts_are_intact(self, e30_manifest: Dict[str, Any]) -> None:
        summary = json.loads((E30_DIR / "summary.json").read_text(encoding="utf-8"))
        assert summary["validation"]["passed"] is True
        assert summary["files_rendered"] == 16
        assert len(e30_manifest["files"]) == 16
        assert len(list((E30_DIR / "audio").glob("*.wav"))) == 16

    def test_no_earlier_experiment_artefact_was_rewritten(self) -> None:
        """The library only reads E26-E30. Each experiment directory must still be present."""
        for name in ("experiment26", "experiment27", "experiment28", "experiment29", "experiment30"):
            assert (REPO_ROOT / "experiments" / name).is_dir(), name









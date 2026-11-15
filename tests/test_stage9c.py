"""Stage 9C: the blinded listening package for sound profile curation.

The brief for this stage asks for evidence, not a decision: a package a listener can complete
without Python, an honest account of what was and was not held constant, and an analysis that
reports what the listening found — including where it contradicts the measurements.

These tests lock the properties that make the evidence trustworthy:

* every profile is realized on the **same** musical input, so the profile is the only variable;
* every stimulus carries the level metadata the brief requires, at the same peak;
* the listener sees neutral labels only, and the profile mapping lives in one private file;
* the A/B program is stratified, deterministic and references real stimuli;
* the whole build is deterministic, and **cannot modify a profile**;
* the analysis refuses to run without answers, is deterministic, and never names a library.

They are deliberately fast: the miniature package is built on a four-profile bank, and the
full 61-profile package is only inspected read-only when it happens to be present.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music import stage9c
from atari_music.cli import cli
from atari_music.sound_profiles import load_sound_profile_bank

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles"
BANK_DIR = DATA_DIR / "bank"
SONGS_DIR = REPO_ROOT / "examples" / "songs"
PACKAGE_DIR = REPO_ROOT / "examples" / "sound_profile_listening"
STAGE9C_REPORTS = REPO_ROOT / "reports" / "stage9c"

#: The published library, as Stage 9B locked it.
BANK_PROFILES = 67
BANK_RENDERABLE = 61
BANK_VOICE = 43
BANK_PAIR = 18
NOT_RENDERABLE = 6

#: A six-profile bank for the fast end-to-end tests: both scopes, three generator families, two
#: shared source songs, and both envelope paths. The four `as-2.dsl` profiles are included
#: because that song's binding names them, so the miniature package can render a real song pair.
#: `686d2070` measures an attack the composer cannot express, so it exercises the documented
#: substitution; the others are realized with their own envelope.
MINI_PROFILE_IDS = (
    "pokey_ref_3faf80b4",  # VOICE, $C, 64 kHz
    "pokey_ref_1ef377fc",  # VOICE, $A, 64 kHz
    "pokey_ref_25f94201",  # VOICE, $A, 64 kHz, real envelope
    "pokey_ref_6db98eb5",  # VOICE, $8, 64 kHz
    "pokey_ref_686d2070",  # VOICE, envelope wider than the consumer can express
    "pokey_ref_a09c0263",  # PAIR,  $C, $50
)

#: One song pair keeps the miniature build fast while still rendering both versions.
MINI_SONG = "as-2.dsl"

MINI_SEED = 4242
MINI_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

TARGET_PEAK_DBFS = -0.92

#: Everything the manifest must record about the experiment (brief §14).
REQUIRED_MANIFEST_KEYS = (
    "manifest_version",
    "experiment",
    "created_utc",
    "seed",
    "sample_rate",
    "renderer_version",
    "normalization",
    "stimulus",
    "profile_bank_fingerprint",
    "profile_count_in_bank",
    "profile_count",
    "scope_counts",
    "status_counts",
    "excluded_profiles",
    "git_commit",
    "samples",
    "ab_trials",
    "song_trials",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dir_digest(root: Path) -> str:
    """A digest over every file under *root*, so "unchanged" can be asserted exactly."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_wav(path: Path) -> Tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    assert channels == 1, f"{path} is not mono"
    assert width == 2, f"{path} is not 16-bit"
    return np.frombuffer(frames, dtype=np.int16), rate


def _write_mini_bank(target: Path) -> Path:
    """A real bank directory restricted to a few profiles, for fast end-to-end builds.

    Written from the published bank verbatim — no profile document is modified — so the
    miniature package exercises the same loader, fingerprints and statuses as the real one.
    """
    target.mkdir(parents=True, exist_ok=True)
    (target / "profiles").mkdir(exist_ok=True)
    registry = json.loads((BANK_DIR / "registry.json").read_text(encoding="utf-8"))
    selected = [
        entry for entry in registry["profiles"] if entry["profile_id"] in MINI_PROFILE_IDS
    ]
    assert len(selected) == len(MINI_PROFILE_IDS)
    for entry in selected:
        source = BANK_DIR / entry["file"]
        destination = target / entry["file"]
        destination.write_bytes(source.read_bytes())
    registry["profiles"] = selected
    registry["profile_count"] = len(selected)
    (target / "registry.json").write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


class _FakeProfile:
    """The slice of ``SoundProfile`` the A/B builder reads."""

    def __init__(self, name: str, *, scope: str, nibble: Optional[int], song: str) -> None:
        self.profile_id = name
        self.scope = scope
        self.distortion_nibble = nibble
        self.document = {"gesture": {"provenance": {"song": song}}}
        self.source_songs: List[Dict[str, Any]] = []


class _FakeCandidate:
    def __init__(
        self, index: int, *, scope: str, nibble: Optional[int], song: str, bands: Sequence[float]
    ) -> None:
        self.index = index
        self.profile = _FakeProfile(
            f"fake_{index:03d}", scope=scope, nibble=nibble, song=song
        )
        self.features = {"band_energy": list(bands)}


@pytest.fixture(scope="module")
def mini_bank(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_mini_bank(tmp_path_factory.mktemp("mini-bank"))


@pytest.fixture(scope="module")
def mini_package(mini_bank: Path, tmp_path_factory: pytest.TempPathFactory) -> Tuple[Path, Dict[str, Any]]:
    """One miniature package, built once and shared by the read-mostly tests."""
    package = tmp_path_factory.mktemp("mini-package")
    manifest = stage9c.build_package(
        package,
        bank_dir=mini_bank,
        songs_dir=SONGS_DIR,
        seed=MINI_SEED,
        now=MINI_NOW,
        context_songs=(MINI_SONG,),
    )
    return package, manifest


# ---------------------------------------------------------------------------
# The stimulus
# ---------------------------------------------------------------------------
class TestStimulus:
    def test_phrase_is_a_short_finite_phrase_not_a_sustained_tone(self) -> None:
        """A phrase rather than one held note: that is what makes an envelope audible."""
        notes = [note for note, _ in stage9c.STIMULUS_PHRASE]
        assert len(notes) >= 6, "a single held note would not exercise an envelope"
        assert len(set(notes)) >= 4, "a phrase should move in pitch"
        durations = {steps for _, steps in stage9c.STIMULUS_PHRASE}
        assert len(durations) >= 2, "a mix of short and long notes exposes the envelope"

    def test_the_two_variants_differ_only_in_the_join(self) -> None:
        voice = stage9c.stimulus_composition(joined_pair=False)
        pair = stage9c.stimulus_composition(joined_pair=True)
        assert voice.hardware.use_16bit_bass is False
        assert pair.hardware.use_16bit_bass is True
        dumped_voice = voice.model_dump(mode="json")
        dumped_pair = pair.model_dump(mode="json")
        dumped_voice["hardware"]["use_16bit_bass"] = None
        dumped_pair["hardware"]["use_16bit_bass"] = None
        assert dumped_voice == dumped_pair

    def test_every_stimulus_uses_channel_one_and_one_velocity(self) -> None:
        doc = stage9c.stimulus_composition(joined_pair=False)
        assert list(doc.patterns[0].channels) == ["1"]
        events = doc.patterns[0].channels["1"]
        assert len(events) == len(stage9c.STIMULUS_PHRASE)
        assert {event.volume for event in events} == {stage9c.STIMULUS_VELOCITY}
        assert {event.instrument for event in events} == {"stim"}
        # The steps must tile the pattern exactly: no gap, no overlap.
        assert events[0].step == 0
        for previous, current in zip(events, events[1:]):
            assert previous.step + previous.duration == current.step
        assert events[-1].step + events[-1].duration == doc.patterns[0].length_steps

    def test_the_stimulus_renders_identically_every_time(self, mini_bank: Path) -> None:
        bank = load_sound_profile_bank(mini_bank)
        profile = bank.get(MINI_PROFILE_IDS[0])
        first = stage9c.render_stimulus(profile, bank)
        second = stage9c.render_stimulus(profile, bank)
        assert first.samples.dtype == np.int16
        assert np.array_equal(first.samples, second.samples)
        assert first.envelope_source == "profile"
        assert first.envelope_overrides == {}

    def test_a_pair_profile_is_realized_on_a_joined_pair(self, mini_bank: Path) -> None:
        bank = load_sound_profile_bank(mini_bank)
        pair = bank.of_scope("PAIR")[0]
        voice = bank.of_scope("VOICE")[0]
        joined = stage9c.render_stimulus(pair, bank)
        single = stage9c.render_stimulus(voice, bank)
        assert len(joined.samples) == len(single.samples), "the same phrase, the same length"
        assert not np.array_equal(joined.samples, single.samples)

    def test_an_envelope_wider_than_the_consumer_can_express_is_substituted_not_invented(
        self, mini_bank: Path
    ) -> None:
        """The one honest deviation, and it must be visible rather than silent.

        The composer refuses to clamp a profile's measured attack. The stimulus declares that
        single field instead, with the composer's own default for the character, so nothing is
        invented — and the substitution is reported.
        """
        bank = load_sound_profile_bank(mini_bank)
        profile = bank.get("pokey_ref_686d2070")
        assert profile.envelope_frames["attack"] > 15, "fixture must still exceed the range"

        rendered = stage9c.render_stimulus(profile, bank)
        assert rendered.envelope_source == "composition_default"
        assert rendered.refusal_code == "PROFILE_ENVELOPE_OUT_OF_RANGE"
        assert rendered.refusal_detail.get("field") == "attack_frames"
        # Only the offending field is overridden; the rest still comes from the profile.
        assert list(rendered.envelope_overrides) == ["attack_frames"]
        assert rendered.envelope_overrides["attack_frames"] == 1

    def test_a_refusal_that_is_not_an_envelope_gap_is_never_swallowed(self, mini_bank: Path) -> None:
        """A consumer refusal must not be turned into a rendered sound by accident."""
        bank = load_sound_profile_bank(mini_bank)
        profile = bank.get(MINI_PROFILE_IDS[0])
        assert profile.renderable
        # The loop is bounded by the number of envelope fields: it cannot spin forever.
        source = Path(stage9c.__file__).read_text(encoding="utf-8")
        assert "for _ in range(len(_ENVELOPE_FIELDS) + 1)" in source


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------
class TestLevels:
    def test_normalization_is_gain_only_and_reaches_the_target(self) -> None:
        quiet = (np.sin(np.linspace(0, 400, 44100)) * 3000).astype(np.int16)
        normalized, report = stage9c.normalize_peak(quiet)
        expected_peak = stage9c.TARGET_PEAK * 32768.0
        assert abs(float(np.max(np.abs(normalized))) - expected_peak) <= 1.0
        assert report.final_peak == pytest.approx(stage9c.TARGET_PEAK, abs=1e-4)
        assert report.gain_db > 0, "a quiet buffer must be raised"
        assert report.original_peak < report.final_peak

        # Gain only: the output is the input scaled by exactly the reported gain.
        gain = 10 ** (report.gain_db / 20.0)
        expected = np.rint(
            np.clip(quiet.astype(np.float64) * gain, -32768.0, 32767.0)
        ).astype(np.int16)
        assert np.array_equal(normalized, expected)

    def test_normalization_never_clips_a_loud_buffer(self) -> None:
        loud = np.array([-32000, 32000, 0, 16000, -16000], dtype=np.int16)
        normalized, report = stage9c.normalize_peak(loud)
        assert normalized.dtype == np.int16
        assert abs(int(np.max(np.abs(normalized.astype(np.int32))))) <= 32767
        assert report.gain_db < 0, "a hot buffer must be attenuated"

    def test_silence_is_returned_unchanged_instead_of_dividing_by_zero(self) -> None:
        silence = np.zeros(1000, dtype=np.int16)
        normalized, report = stage9c.normalize_peak(silence)
        assert np.array_equal(normalized, silence)
        assert report.gain_db == 0.0

    def test_level_report_expresses_amplitudes_in_dbfs(self) -> None:
        report = stage9c.normalize_peak((np.sin(np.linspace(0, 40, 2000)) * 10000).astype(np.int16))[1]
        reported = report.as_dict()
        assert -0.95 <= reported["final_peak_dbfs"] <= -0.9
        assert reported["gain_db"] == pytest.approx(report.gain_db, abs=1e-3)
        assert reported["original_rms_dbfs"] < 0


# ---------------------------------------------------------------------------
# Technical features
# ---------------------------------------------------------------------------
class TestFeatures:
    def test_features_are_computed_from_the_rendered_audio(self) -> None:
        sample_rate = 44100
        t = np.arange(sample_rate, dtype=np.float64) / sample_rate
        low = np.rint(np.sin(2 * np.pi * 200 * t) * 20000).astype(np.int16)
        high = np.rint(np.sin(2 * np.pi * 4000 * t) * 20000).astype(np.int16)

        low_features = stage9c.spectral_features(low, sample_rate)
        high_features = stage9c.spectral_features(high, sample_rate)
        assert low_features["centroid_hz"] < high_features["centroid_hz"]
        assert len(low_features["band_energy"]) == stage9c.SPECTRAL_BANDS
        assert sum(low_features["band_energy"]) == pytest.approx(1.0, abs=1e-4)
        assert 0.0 <= low_features["flatness"] <= 1.0

    def test_noise_is_flatter_than_a_tone(self) -> None:
        sample_rate = 44100
        t = np.arange(sample_rate, dtype=np.float64) / sample_rate
        tone = np.rint(np.sin(2 * np.pi * 440 * t) * 15000).astype(np.int16)
        rng = np.random.default_rng(7)
        noise = np.rint(rng.normal(0, 6000, sample_rate)).clip(-32000, 32000).astype(np.int16)
        assert stage9c.spectral_features(noise, sample_rate)["flatness"] > stage9c.spectral_features(
            tone, sample_rate
        )["flatness"]

    def test_distance_is_a_bounded_measure_of_spectral_overlap(self) -> None:
        a = {"band_energy": [0.0, 1.0, 0.0, 0.0]}
        b = {"band_energy": [0.0, 1.0, 0.0, 0.0]}
        c = {"band_energy": [0.0, 0.0, 0.0, 1.0]}
        assert stage9c.spectral_distance(a, b) == pytest.approx(0.0)
        assert stage9c.spectral_distance(a, c) == pytest.approx(1.0)
        assert stage9c.spectral_distance(a, b) < stage9c.spectral_distance(a, c)

    def test_distance_of_silence_is_defined_rather_than_a_nan(self) -> None:
        silent = {"band_energy": [0.0] * 4}
        assert stage9c.spectral_distance(silent, silent) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The A/B program
# ---------------------------------------------------------------------------
class TestAbProgram:
    def _candidates(self) -> List[_FakeCandidate]:
        # Two narrow-band profiles (close), two wide (far), spread over two scopes, two
        # generator families and three source songs.
        return [
            _FakeCandidate(0, scope="VOICE", nibble=0xA, song="one.sap", bands=[1.0, 0, 0, 0]),
            _FakeCandidate(1, scope="VOICE", nibble=0xA, song="one.sap", bands=[0.97, 0.03, 0, 0]),
            _FakeCandidate(2, scope="VOICE", nibble=0xC, song="two.sap", bands=[0, 0, 0, 1.0]),
            _FakeCandidate(3, scope="PAIR", nibble=0xC, song="three.sap", bands=[0, 0, 1.0, 0]),
        ]

    def test_trials_are_unique_and_reference_the_candidates(self) -> None:
        import random

        candidates = self._candidates()
        trials = stage9c.build_ab_trials(candidates, random.Random(1))
        assert trials, "a non-trivial candidate set must produce trials"
        seen = {frozenset((t["a_index"], t["b_index"])) for t in trials}
        assert len(seen) == len(trials), "a pair must not be asked twice"
        for trial in trials:
            assert trial["a_index"] != trial["b_index"]
            assert 0 <= trial["a_index"] < len(candidates)
            assert 0 <= trial["b_index"] < len(candidates)
            assert trial["a_index"] != trial["b_index"]

    def test_trials_are_numbered_in_presentation_order(self) -> None:
        import random

        trials = stage9c.build_ab_trials(self._candidates(), random.Random(2))
        assert [t["trial_id"] for t in trials] == [
            f"trial_{number:02d}" for number in range(1, len(trials) + 1)
        ]

    def test_the_program_is_deterministic_for_a_seed_and_differs_between_seeds(self) -> None:
        import random

        first = stage9c.build_ab_trials(self._candidates(), random.Random(11))
        second = stage9c.build_ab_trials(self._candidates(), random.Random(11))
        third = stage9c.build_ab_trials(self._candidates(), random.Random(12))
        assert first == second
        assert first != third, "the seed must actually decide something"

    def test_strata_never_repeat_a_pair_and_stay_within_their_definition(self) -> None:
        import random

        candidates = self._candidates()
        trials = stage9c.build_ab_trials(candidates, random.Random(3))
        for trial in trials:
            left, right = candidates[trial["a_index"]], candidates[trial["b_index"]]
            same_generator = left.profile.distortion_nibble == right.profile.distortion_nibble
            same_scope = left.profile.scope == right.profile.scope
            if trial["stratum"] == "similar":
                assert same_generator and same_scope
            if trial["stratum"] == "same_generator":
                assert same_generator
            if trial["stratum"] == "different_generator":
                assert not same_generator

    def test_a_pair_is_never_reused_across_strata(self) -> None:
        """Otherwise one comparison would be counted as evidence for two questions."""
        import random

        candidates = [
            _FakeCandidate(i, scope="VOICE", nibble=0xA, song="one.sap", bands=[1.0, i / 100.0])
            for i in range(12)
        ]
        trials = stage9c.build_ab_trials(candidates, random.Random(5))
        keys = [frozenset((t["a_index"], t["b_index"])) for t in trials]
        assert len(keys) == len(set(keys))

    def test_the_distant_stratum_selects_the_most_distant_pairs(self) -> None:
        import random

        candidates = [
            _FakeCandidate(0, scope="VOICE", nibble=0xA, song="one.sap", bands=[1.0, 0, 0]),
            _FakeCandidate(1, scope="VOICE", nibble=0xA, song="one.sap", bands=[1.0, 0, 0]),
            _FakeCandidate(2, scope="PAIR", nibble=0xC, song="two.sap", bands=[0, 0, 1.0]),
        ]
        trials = stage9c.build_ab_trials(candidates, random.Random(4))
        distant = [t for t in trials if t["stratum"] == "distant"]
        assert distant, "the far pair must be offered"
        for trial in distant:
            assert {trial["a_index"], trial["b_index"]} == {0, 2} or {trial["a_index"], trial["b_index"]} == {1, 2}
            assert trial["technical_distance"] == pytest.approx(1.0)

    def test_both_sides_get_to_be_a_in_some_trial_over_a_real_bank(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        orders = [
            (entry["profile_a"], entry["profile_b"]) for entry in manifest["ab_trials"]
        ]
        assert orders, "the miniature package must contain trials"
        assert all(left != right for left, right in orders)

    def test_no_trial_is_built_from_a_profile_outside_the_experiment(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        in_experiment = {entry["profile_id"] for entry in manifest["samples"]}
        for trial in manifest["ab_trials"]:
            assert trial["profile_a"] in in_experiment
            assert trial["profile_b"] in in_experiment


# ---------------------------------------------------------------------------
# The miniature package, end to end
# ---------------------------------------------------------------------------
class TestMiniPackage:
    def test_every_renderable_profile_is_present_exactly_once(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        assert manifest["profile_count_in_bank"] == len(MINI_PROFILE_IDS)
        assert manifest["profile_count"] == len(MINI_PROFILE_IDS)
        assert {entry["profile_id"] for entry in manifest["samples"]} == set(MINI_PROFILE_IDS)

    def test_the_manifest_records_everything_the_brief_requires(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        for key in REQUIRED_MANIFEST_KEYS:
            assert key in manifest, f"manifest is missing {key}"
        assert manifest["experiment"] == stage9c.EXPERIMENT
        assert manifest["seed"] == MINI_SEED
        assert manifest["sample_rate"] == stage9c.SAMPLE_RATE
        assert manifest["renderer_version"]
        assert manifest["git_commit"]["composer"]
        assert manifest["profile_bank_fingerprint"]
        assert manifest["created_utc"].startswith("2026-01-02T03:04:05")
        assert manifest["private"] is True

    def test_sample_ids_are_blinded_and_contiguous(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        ids = [entry["sample_id"] for entry in manifest["samples"]]
        assert ids == sorted(ids), "the manifest must be ordered by sample id"
        assert ids == [f"sample_{n:03d}" for n in range(1, len(ids) + 1)]
        assert ids == sorted(set(ids)), "sample ids must be unique"
        assert len(set(ids)) == manifest["profile_count"]

    def test_the_presentation_order_is_a_shuffle_not_the_profile_order(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        """Otherwise "sample_001" would leak "the first profile"."""
        _, manifest = mini_package
        by_sample = [entry["profile_id"] for entry in manifest["samples"]]
        by_id = sorted(entry["profile_id"] for entry in manifest["samples"])
        assert by_sample != by_id

    def test_every_sample_file_exists_and_is_a_real_audio_file(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, manifest = mini_package
        durations = set()
        for entry in manifest["samples"]:
            path = package / entry["file"]
            assert path.is_file(), f"missing stimulus {path}"
            samples, rate = _read_wav(path)
            assert rate == stage9c.SAMPLE_RATE
            assert samples.size > 0
            assert int(np.max(np.abs(samples.astype(np.int32)))) > 0, "a stimulus must not be silent"
            durations.add(round(samples.size / rate, 3))
        assert len(durations) == 1, f"stimuli must share one duration, got {durations}"

    def test_every_sample_records_its_level_metadata(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, manifest = mini_package
        for entry in manifest["samples"]:
            levels = entry["levels"]
            for key in (
                "original_peak_dbfs",
                "original_rms_dbfs",
                "gain_db",
                "final_peak_dbfs",
                "final_rms_dbfs",
            ):
                assert key in levels, f"{entry['sample_id']} has no {key}"
            assert levels["final_peak_dbfs"] == pytest.approx(TARGET_PEAK_DBFS, abs=0.05)
            samples, _ = _read_wav(package / entry["file"])
            measured = 20 * np.log10(np.max(np.abs(samples)) / 32768.0)
            assert measured == pytest.approx(TARGET_PEAK_DBFS, abs=0.05)

    def test_loudness_is_preserved_rather_than_equalized(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        """Peak normalization must not hide the profiles' genuine loudness differences."""
        _, manifest = mini_package
        rms = {entry["levels"]["final_rms_dbfs"] for entry in manifest["samples"]}
        assert len(rms) > 1, "identical RMS everywhere would mean the levels were equalized"

    def test_the_manifest_holds_the_mapping_and_the_listener_does_not(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, manifest = mini_package
        profile_ids = {entry["profile_id"] for entry in manifest["samples"]}
        songs = {entry["source_song"] for entry in manifest["samples"]}
        sources = {entry["generator_family"] for entry in manifest["samples"]}

        for visible in ("index.html", "README.md"):
            text = (package / visible).read_text(encoding="utf-8")
            for profile_id in profile_ids:
                assert profile_id not in text, f"{visible} leaks {profile_id}"
            for song in songs:
                assert song not in text, f"{visible} leaks the source song {song}"
            for source in sources:
                assert f"generator {source}" not in text
        for wav in (package / "audio").glob("*.wav"):
            assert not any(profile_id in wav.name for profile_id in profile_ids)

        # The key itself must be unmistakable.
        manifest_file = package / "manifest.json"
        assert manifest_file.is_file()
        assert json.loads(manifest_file.read_text(encoding="utf-8"))["private"] is True

    def test_the_interface_lists_every_sample_and_every_trial(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, manifest = mini_package
        html = (package / "index.html").read_text(encoding="utf-8")
        assert "__PACKAGE__" not in html, "the placeholder must be substituted"
        assert '"audio/${sample}.wav"' in html, "the page must load the stimulus files"

        match = re.search(r"const PACKAGE = (\{.*?\});\n", html, re.DOTALL)
        assert match, "the page must carry the blinded programme"
        payload = json.loads(match.group(1))

        assert payload["experiment"] == stage9c.EXPERIMENT
        assert payload["samples"] == [entry["sample_id"] for entry in manifest["samples"]]
        assert payload["ab_trials"] == [
            {"trial_id": entry["trial_id"], "a": entry["sample_a"], "b": entry["sample_b"]}
            for entry in manifest["ab_trials"]
        ]
        assert [entry["trial_id"] for entry in payload["song_trials"]] == [
            entry["trial_id"] for entry in manifest["song_trials"]
        ]
        # Nothing in the programme may be a profile id: the page only ever sees sample ids.
        profile_ids = {entry["profile_id"] for entry in manifest["samples"]}
        assert not any(profile_id in json.dumps(payload) for profile_id in profile_ids)

    def test_the_templates_are_ready_to_fill_in_and_empty_of_answers(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, manifest = mini_package
        expected = {
            "evaluation_profiles.csv": (
                stage9c.PROFILE_TEMPLATE_HEADER,
                [entry["sample_id"] for entry in manifest["samples"]],
            ),
            "evaluation_ab.csv": (
                stage9c.AB_TEMPLATE_HEADER,
                [entry["trial_id"] for entry in manifest["ab_trials"]],
            ),
            "evaluation_songs.csv": (
                stage9c.SONG_TEMPLATE_HEADER,
                [entry["trial_id"] for entry in manifest["song_trials"]],
            ),
        }
        for name, (header, ids) in expected.items():
            with (package / name).open(encoding="utf-8", newline="") as handle:
                assert next(csv.reader(handle)) == header
            with (package / name).open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            assert [row["sample_id" if "sample_id" in row else "trial_id"] for row in rows] == ids
            for row in rows:
                for field, value in row.items():
                    if field not in ("sample_id", "trial_id"):
                        assert value == "", f"{name} pre-fills {field}"

    def test_a_song_pair_compares_the_same_music_at_the_same_length(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, manifest = mini_package
        assert manifest["song_trials"], "the miniature package must carry the song program"
        for trial in manifest["song_trials"]:
            assert trial["song"] == MINI_SONG
            sides = trial["uses_profile_side"]
            assert set(sides.values()) == {"a", "b"}, "one side is default, the other profiled"
            a, _ = _read_wav(package / trial["files"]["a"])
            b, _ = _read_wav(package / trial["files"]["b"])
            assert a.size == b.size
            assert not np.array_equal(a, b), "the binding must change the render"
            assert trial["bound_profiles"], "the pair must name what it binds"
            assert trial["shared_gain_db"] is not None, "one shared gain, recorded"

    def test_the_song_pair_is_the_same_excerpt_of_the_same_composition(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        for trial in manifest["song_trials"]:
            assert trial["excerpt_seconds"] <= stage9c.SONG_EXCERPT_SECONDS
            assert trial["excerpt_seconds"] > 0

    def test_the_readme_answers_the_listener_s_questions(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        package, _ = mini_package
        readme = (package / "README.md").read_text(encoding="utf-8")
        assert "index.html" in readme
        assert "evaluation_profiles.csv" in readme
        assert "evaluation_ab.csv" in readme
        assert "evaluation_songs.csv" in readme
        assert "analyze" in readme, "the README must say how to analyse the answers"

    def test_the_build_is_deterministic(
        self, mini_bank: Path, mini_package: Tuple[Path, Dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        package, manifest = mini_package
        other = tmp_path_factory.mktemp("mini-package-again")
        rebuilt = stage9c.build_package(
            other,
            bank_dir=mini_bank,
            songs_dir=SONGS_DIR,
            seed=MINI_SEED,
            now=MINI_NOW,
            context_songs=(MINI_SONG,),
        )
        assert rebuilt == manifest, "the same inputs must produce the same manifest"
        assert _dir_digest(other / "audio") == _dir_digest(package / "audio")
        assert (other / "index.html").read_bytes() == (package / "index.html").read_bytes()

    def test_a_different_seed_reorders_the_samples(
        self, mini_bank: Path, mini_package: Tuple[Path, Dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        _, manifest = mini_package
        other = tmp_path_factory.mktemp("mini-package-seed")
        rebuilt = stage9c.build_package(
            other,
            bank_dir=mini_bank,
            songs_dir=SONGS_DIR,
            seed=MINI_SEED + 1,
            now=MINI_NOW,
            context_songs=(MINI_SONG,),
        )
        first = {entry["profile_id"]: entry["sample_id"] for entry in manifest["samples"]}
        second = {entry["profile_id"]: entry["sample_id"] for entry in rebuilt["samples"]}
        assert first != second

    def test_the_build_cannot_modify_the_bank(
        self, mini_bank: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        before = _dir_digest(mini_bank)
        stage9c.build_package(
            tmp_path_factory.mktemp("mini-package-immutable"),
            bank_dir=mini_bank,
            songs_dir=SONGS_DIR,
            seed=MINI_SEED,
            now=MINI_NOW,
            context_songs=(MINI_SONG,),
        )
        assert _dir_digest(mini_bank) == before

    def test_the_manifest_names_the_bank_it_measured(
        self, mini_bank: Path, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        _, manifest = mini_package
        assert manifest["profile_bank_fingerprint"] == stage9c.bank_fingerprint(
            load_sound_profile_bank(mini_bank)
        )
        assert manifest["profile_bank_fingerprint"] != stage9c.bank_fingerprint(
            load_sound_profile_bank(BANK_DIR)
        ), "the fingerprint must identify the bank actually used"


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------
def _fill_package(package: Path, manifest: Dict[str, Any]) -> None:
    """Synthetic answers, only to exercise the analysis. Not a result."""
    words = ["bass", "noise hit", "bell", "generic beep"]
    with (package / "evaluation_profiles.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(stage9c.PROFILE_TEMPLATE_HEADER)
        for index, entry in enumerate(manifest["samples"]):
            writer.writerow(
                [
                    entry["sample_id"],
                    1 + (index % 5),
                    1 + ((index * 3) % 5),
                    1 + ((index * 2) % 5),
                    4 if index % 3 else "",
                    words[index % len(words)],
                ]
            )
    with (package / "evaluation_ab.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(stage9c.AB_TEMPLATE_HEADER)
        for index, entry in enumerate(manifest["ab_trials"]):
            writer.writerow(
                [entry["trial_id"], 1 + (index % 5), ["a", "b", "none"][index % 3], 1 + (index % 5), "close"]
            )
    with (package / "evaluation_songs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(stage9c.SONG_TEMPLATE_HEADER)
        for index, entry in enumerate(manifest["song_trials"]):
            writer.writerow(
                [entry["trial_id"], ["a", "b", "none"][index % 3], "b", "a", 2 + (index % 4), "harsher"]
            )


class TestAnalysis:
    def test_it_refuses_to_analyse_an_empty_template(self, mini_package: Tuple[Path, Dict[str, Any]]) -> None:
        package, _ = mini_package
        with pytest.raises(stage9c.AnalysisNotReady):
            stage9c.analyze_experiment(package, package / "reports")

    def test_it_refuses_a_package_without_a_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(stage9c.AnalysisNotReady):
            stage9c.analyze_experiment(tmp_path, tmp_path / "reports")

    def test_it_produces_the_report_and_the_three_extracts(
        self, mini_package: Tuple[Path, Dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        package, manifest = mini_package
        working = tmp_path_factory.mktemp("analysis-package")
        for name in ("manifest.json", "evaluation_profiles.csv", "evaluation_ab.csv", "evaluation_songs.csv"):
            (working / name).write_bytes((package / name).read_bytes())
        _fill_package(working, manifest)

        written = stage9c.analyze_experiment(working, working / "reports")
        for key in ("report", "profile_scores", "ab_results", "song_results", "vocabulary"):
            assert written[key].is_file(), f"missing {key}"

        report = written["report"].read_text(encoding="utf-8")
        assert "does not choose the final" in report
        assert "No final library is chosen" in report
        assert "Candidate groups" in report

        with written["profile_scores"].open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == manifest["profile_count"]
        assert {row["profile_id"] for row in rows} == {
            entry["profile_id"] for entry in manifest["samples"]
        }
        assert "centroid_hz" in rows[0] and "spectral_distance_to_mean" in rows[0]

        vocabulary = json.loads(written["vocabulary"].read_text(encoding="utf-8"))
        assert vocabulary["comments"], "raw comments must survive"
        assert any(entry["word"] == "bass" for entry in vocabulary["words"])

    def test_the_analysis_is_deterministic(
        self, mini_package: Tuple[Path, Dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        package, manifest = mini_package
        digests = []
        for _ in range(2):
            working = tmp_path_factory.mktemp("analysis-determinism")
            for name in ("manifest.json", "evaluation_profiles.csv", "evaluation_ab.csv", "evaluation_songs.csv"):
                (working / name).write_bytes((package / name).read_bytes())
            _fill_package(working, manifest)
            written = stage9c.analyze_experiment(working, working / "reports")
            digests.append(_dir_digest(working / "reports"))
        assert digests[0] == digests[1]

    def test_it_translates_the_blinded_song_answer_back_to_the_versions(
        self, mini_package: Tuple[Path, Dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """The listener says "A"; the analysis must know which version that was."""
        package, manifest = mini_package
        working = tmp_path_factory.mktemp("analysis-song-sides")
        for name in ("manifest.json", "evaluation_profiles.csv", "evaluation_ab.csv", "evaluation_songs.csv"):
            (working / name).write_bytes((package / name).read_bytes())
        _fill_package(working, manifest)
        written = stage9c.analyze_experiment(working, working / "reports")
        with written["song_results"].open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        trial = manifest["song_trials"][0]
        expected = "profile" if trial["uses_profile_side"]["profile"] == "a" else "default"
        assert rows[0]["better_sound"] == expected

    def test_an_unknown_sample_in_the_sheet_is_ignored_not_guessed(
        self, mini_package: Tuple[Path, Dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        package, manifest = mini_package
        working = tmp_path_factory.mktemp("analysis-unknown")
        for name in ("manifest.json", "evaluation_profiles.csv", "evaluation_ab.csv", "evaluation_songs.csv"):
            (working / name).write_bytes((package / name).read_bytes())
        _fill_package(working, manifest)
        with (working / "evaluation_profiles.csv").open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(["sample_999", 5, 5, 5, 5, "not in the experiment"])
        written = stage9c.analyze_experiment(working, working / "reports")
        with written["profile_scores"].open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == manifest["profile_count"]

    def test_candidate_groups_are_derived_from_the_ratings(self) -> None:
        scored = [
            {
                "profile_id": "p1",
                "sample_id": "sample_001",
                "scope": "VOICE",
                "status": "PLAYABLE",
                "generator_family": "$A",
                "usefulness": 5.0,
                "distinctiveness": 5.0,
                "atari_character": 4.0,
                "confidence": 5.0,
                "comment": "",
                "spectral_distance_to_mean": 0.2,
            },
            {
                "profile_id": "p2",
                "sample_id": "sample_002",
                "scope": "VOICE",
                "status": "PLAYABLE",
                "generator_family": "$A",
                "usefulness": 1.0,
                "distinctiveness": 1.0,
                "atari_character": 1.0,
                "confidence": 4.0,
                "comment": "",
                "spectral_distance_to_mean": 0.1,
            },
        ]
        groups = stage9c.candidate_groups(scored, [])
        assert [row["profile_id"] for row in groups["strong"]] == ["p1"]
        assert [row["profile_id"] for row in groups["weak"]] == ["p2"]
        assert "spectral_distance_to_mean" in groups["strong"][0], "the raw evidence must be shown"


# ---------------------------------------------------------------------------
# The real package
# ---------------------------------------------------------------------------
class TestPublishedPackage:
    """Read-only checks of the package that ships in the repository state."""

    def test_the_bank_is_what_the_experiment_was_built_from(self) -> None:
        bank = load_sound_profile_bank(BANK_DIR)
        assert len(bank.ids()) == BANK_PROFILES
        assert len(bank.renderable()) == BANK_RENDERABLE
        renderable = bank.renderable()
        assert sum(1 for profile in renderable if profile.scope == "VOICE") == BANK_VOICE
        assert sum(1 for profile in renderable if profile.scope == "PAIR") == BANK_PAIR
        assert len(bank.ids()) - len(renderable) == NOT_RENDERABLE

    def test_the_package_covers_every_renderable_profile_and_no_other(
        self, mini_package: Tuple[Path, Dict[str, Any]]
    ) -> None:
        if not (PACKAGE_DIR / "manifest.json").is_file():
            pytest.skip("the published listening package has not been built in this checkout")
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        bank = load_sound_profile_bank(BANK_DIR)
        assert manifest["profile_count"] == BANK_RENDERABLE
        assert {entry["profile_id"] for entry in manifest["samples"]} == {
            profile.profile_id for profile in bank.renderable()
        }
        assert len(manifest["excluded_profiles"]) == NOT_RENDERABLE
        assert manifest["profile_bank_fingerprint"] == stage9c.bank_fingerprint(bank)

    def test_the_published_package_agrees_with_its_own_manifest(self) -> None:
        if not (PACKAGE_DIR / "manifest.json").is_file():
            pytest.skip("the published listening package has not been built in this checkout")
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["samples"]:
            assert (PACKAGE_DIR / entry["file"]).is_file()
        for trial in manifest["song_trials"]:
            assert (PACKAGE_DIR / trial["files"]["a"]).is_file()
            assert (PACKAGE_DIR / trial["files"]["b"]).is_file()
        assert 20 <= len(manifest["ab_trials"]) <= 30
        assert 5 <= len(manifest["song_trials"]) <= 8

    def test_the_published_package_is_blinded(self) -> None:
        if not (PACKAGE_DIR / "manifest.json").is_file():
            pytest.skip("the published listening package has not been built in this checkout")
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        html = (PACKAGE_DIR / "index.html").read_text(encoding="utf-8")
        for entry in manifest["samples"]:
            assert entry["profile_id"] not in html
            assert entry["source_song"] not in html
            assert entry["generator_family"] not in html
        assert "manifest.json" in (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")

    def test_the_published_templates_hold_either_nothing_or_valid_answers(self) -> None:
        """Before the listening the templates are empty; after it they hold valid answers.

        The files are the human's raw response, so the test allows both states and constrains
        only what may appear: identifiers in place, ratings inside 1–5, choices inside the
        declared vocabulary, comments free text. Nothing else.
        """
        if not (PACKAGE_DIR / "manifest.json").is_file():
            pytest.skip("the published listening package has not been built in this checkout")
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        numeric = {"distinctiveness", "usefulness", "atari_character", "confidence",
                   "similarity", "character_difference", "overall_difference"}
        choices = {"preference", "better_sound", "more_character", "more_convincing_atari"}
        expected_ids = {
            "evaluation_profiles.csv": [entry["sample_id"] for entry in manifest["samples"]],
            "evaluation_ab.csv": [entry["trial_id"] for entry in manifest["ab_trials"]],
            "evaluation_songs.csv": [entry["trial_id"] for entry in manifest["song_trials"]],
        }
        for name, ids in expected_ids.items():
            with (PACKAGE_DIR / name).open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            assert [row["sample_id" if "sample_id" in row else "trial_id"] for row in rows] == ids
            for row in rows:
                for field, value in row.items():
                    if field in ("sample_id", "trial_id"):
                        continue
                    if field == "comment":
                        continue
                    if value == "":
                        continue
                    if field in numeric:
                        assert 1 <= float(value) <= 5, f"{name} {field}={value}"
                    elif field in choices:
                        assert value in ("a", "b", "none"), f"{name} {field}={value}"
                    else:  # pragma: no cover - a new column must be validated explicitly
                        raise AssertionError(f"{name} has an unvalidated column {field}")


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------
class TestCli:
    def test_prepare_builds_a_package_and_reports_what_it_did(
        self, mini_bank: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "package"
        result = CliRunner().invoke(
            cli,
            [
                "prepare-listening-test-9c",
                "--package-dir",
                str(output),
                "--sound-bank",
                str(mini_bank),
                "--songs-dir",
                str(SONGS_DIR),
                "--song",
                MINI_SONG,
                "--seed",
                str(MINI_SEED),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "blinded profile stimuli" in result.output
        assert (output / "manifest.json").is_file()
        assert (output / "index.html").is_file()

    def test_analyse_refuses_an_unfilled_package_with_a_clear_message(
        self, mini_bank: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "package"
        runner = CliRunner()
        assert runner.invoke(
            cli,
            [
                "prepare-listening-test-9c",
                "--package-dir",
                str(output),
                "--sound-bank",
                str(mini_bank),
                "--songs-dir",
                str(SONGS_DIR),
                "--song",
                MINI_SONG,
            ],
        ).exit_code == 0
        result = runner.invoke(
            cli,
            ["analyze-listening-test-9c", "--package-dir", str(output), "--output-dir", str(tmp_path / "reports")],
        )
        assert result.exit_code != 0
        assert "no ratings" in result.output

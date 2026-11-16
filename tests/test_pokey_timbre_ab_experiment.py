"""Experiment 30 — the A/B evaluation of four POKEY timbres.

These tests check the *experiment*, not the sound. Specifically:

* the loudness meter is a real BS.1770-4 implementation — it reproduces the standard's published
  48 kHz coefficients and its calibration point (a −20 dBFS 997 Hz sine reads −20.0 LUFS);
* the four variants of each context have the baseline's frame count and the baseline's note grid, and
  differ **only** in the melodic channel's AUDF/AUDC columns;
* each variant's AUDC generator nibble is the candidate's own, so nothing was silently substituted;
* the original set keeps different peaks (nothing normalised per file) and the matched set really is
  matched, measured on the delivered files, with no clipping anywhere;
* the page shows only letters, and no candidate name appears outside the reveal block;
* the CSV template's headers are the headers the page downloads;
* the output is deterministic and no production file is touched.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from atari_music import ir
from atari_music import pokey_timbre_ab_experiment as e30
from atari_music.sound_profiles.bank import load_sound_profile_bank

pytestmark = pytest.mark.experimental

DELIVERED = e30.DEFAULT_OUTPUT_DIR

EXPERIMENT_MODULES = {
    "pokey_timbre_ab_experiment.py",
    "pokey_timbre_library_experiment.py",
    "pokey_timbre_experiment.py",
    "pokey_octave_pulse_experiment.py",
    "pokey_c1_musical_context_experiment.py",
}


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_wav(path: Path) -> Tuple[Any, np.ndarray]:
    with wave.open(str(path), "rb") as handle:
        params = handle.getparams()
        raw = handle.readframes(handle.getnframes())
    return params, np.frombuffer(raw, dtype=np.int16)


def read_float(path: Path) -> np.ndarray:
    _params, samples = read_wav(path)
    return samples.astype(np.float64) / 32767.0


@pytest.fixture(scope="module")
def bank() -> Any:
    return load_sound_profile_bank(e30.DEFAULT_BANK_DIR)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    return e30.render_all(tmp_path_factory.mktemp("experiment30"))


@pytest.fixture(scope="module")
def summary(rendered: Dict[str, Any]) -> Dict[str, Any]:
    return e30.build_summary(rendered)


# ---------------------------------------------------------------------------
# 1. the loudness meter
# ---------------------------------------------------------------------------
class TestLoudnessImplementation:
    def test_the_filters_reproduce_the_standards_published_coefficients(self) -> None:
        """BS.1770-4 Table 1, at 48 kHz. This is what makes it an implementation of the standard."""
        shelf_b, shelf_a = e30.high_shelf_coefficients(48000.0)
        hp_b, hp_a = e30.high_pass_coefficients(48000.0)
        assert np.max(np.abs(shelf_b - e30.BS1770_TABLE1_48K["shelf_b"])) < 1e-12
        assert np.max(np.abs(shelf_a - e30.BS1770_TABLE1_48K["shelf_a"])) < 1e-12
        assert np.max(np.abs(hp_b - e30.BS1770_TABLE1_48K["highpass_b"])) < 1e-12
        assert np.max(np.abs(hp_a - e30.BS1770_TABLE1_48K["highpass_a"])) < 1e-12

    def test_the_meter_reads_the_standards_calibration_point(self) -> None:
        """A 997 Hz sine at −20 dBFS **RMS** must read −20.0 LUFS: the K-weighting's +0.694 dB at
        997 Hz cancels the −0.691 offset, which is what the offset is for."""
        rate = 48000
        t = np.arange(rate * 3) / rate
        unit = np.sin(2 * np.pi * 997.0 * t)
        # amplitude 1.0 is an RMS of −3.01 dBFS, so it reads ≈ −3.01 LUFS
        assert e30.integrated_loudness(unit, rate) == pytest.approx(-3.01, abs=0.02)
        # an RMS of −20 dBFS is an amplitude of sqrt(2)·0.1
        assert e30.integrated_loudness(unit * math.sqrt(2.0) * 0.1, rate) == pytest.approx(
            -20.0, abs=0.02
        )

    def test_a_level_change_is_reported_as_a_level_change(self) -> None:
        rate = 44100
        t = np.arange(rate * 2) / rate
        sine = np.sin(2 * np.pi * 997.0 * t)
        loud = e30.integrated_loudness(sine, rate)
        quiet = e30.integrated_loudness(sine * 0.5, rate)
        assert loud - quiet == pytest.approx(20 * math.log10(2.0), abs=0.01)

    def test_the_shelf_has_the_expected_shape(self) -> None:
        """+4 dB plateau well above the corner, and near 0 dB well below it."""
        rate = 44100.0
        b, a = e30.high_shelf_coefficients(rate)

        def gain_db(frequency: float) -> float:
            z = np.exp(-2j * np.pi * frequency / rate)
            return 20 * math.log10(abs((b[0] + b[1] * z + b[2] * z * z)
                                       / (a[0] + a[1] * z + a[2] * z * z)))

        assert gain_db(20.0) == pytest.approx(0.0, abs=0.01)
        assert gain_db(10000.0) == pytest.approx(e30.SHELF_GAIN_DB, abs=0.05)

    def test_gating_is_applied(self) -> None:
        """A quiet tail below the relative gate must not pull the reading down."""
        rate = 44100
        t = np.arange(rate * 4) / rate
        tone = np.sin(2 * np.pi * 997.0 * t)
        loud_part = tone * 0.5
        quiet_tail = tone * 0.5 * 1e-4
        gated = e30.integrated_loudness(np.concatenate([loud_part, quiet_tail]), rate)
        assert gated == pytest.approx(e30.integrated_loudness(loud_part, rate), abs=0.5)

    def test_a_clip_shorter_than_one_block_still_measures(self) -> None:
        rate = 44100
        t = np.arange(int(rate * 0.2)) / rate
        short = np.sin(2 * np.pi * 997.0 * t) * 0.1
        assert math.isfinite(e30.integrated_loudness(short, rate))
        assert e30.measure_level(short, rate)["lufs_gated"] is False
        assert e30.measure_level(np.concatenate([short, short, short]), rate)["lufs_gated"] is True

    def test_silence_has_no_loudness(self) -> None:
        assert e30.integrated_loudness(np.zeros(44100), 44100) == float("-inf")
        with pytest.raises(ValueError):
            e30.gain_for_loudness(np.zeros(44100), -20.0, 44100)

    def test_peak_and_rms_are_plain_measurements(self) -> None:
        signal = np.array([0.0, 0.5, -1.0, 0.25])
        assert e30.peak_of(signal) == pytest.approx(1.0)
        assert e30.rms_of(signal) == pytest.approx(math.sqrt((0.0 + 0.25 + 1.0 + 0.0625) / 4))
        assert e30.dbfs(1.0) == pytest.approx(0.0)
        assert e30.dbfs(0.0) == float("-inf")


# ---------------------------------------------------------------------------
# 2. the four candidates and their letters
# ---------------------------------------------------------------------------
class TestCandidates:
    def test_there_are_four_named_candidates(self) -> None:
        assert e30.candidate_names() == (
            "c1_octave_pulse", "pure_sustain", "pure_pluck", "buzz_steady",
        )

    def test_the_bank_profiles_are_the_ones_the_brief_names(self) -> None:
        assert e30.candidate_by_name("pure_sustain")["profile_id"] == "pokey_ref_25f94201"
        assert e30.candidate_by_name("pure_pluck")["profile_id"] == "pokey_ref_9daa0429"
        assert e30.candidate_by_name("buzz_steady")["profile_id"] == "pokey_ref_2b83db43"

    def test_every_bank_profile_exists_and_is_renderable(self, bank: Any) -> None:
        for candidate in e30.CANDIDATES:
            if candidate["kind"] == "bank":
                assert bank.get(str(candidate["profile_id"])).renderable

    def test_the_letter_map_covers_every_candidate_exactly_once(self) -> None:
        mapping = e30.letter_map()
        assert sorted(mapping) == list(e30.LETTERS)
        assert sorted(mapping.values()) == sorted(e30.candidate_names())

    def test_the_letter_map_is_deterministic_and_does_not_put_c1_first(self) -> None:
        assert e30.letter_map() == e30.letter_map()
        assert e30.letter_map()["A"] != "c1_octave_pulse"
        assert e30.candidate_letter("c1_octave_pulse") in e30.LETTERS

    def test_an_unknown_candidate_is_refused(self) -> None:
        with pytest.raises(KeyError):
            e30.candidate_by_name("not_a_candidate")
        with pytest.raises(KeyError):
            e30.candidate_letter("not_a_candidate")


# ---------------------------------------------------------------------------
# 3. the two contexts
# ---------------------------------------------------------------------------
class TestContexts:
    def test_the_solo_figure_is_the_documented_length(self) -> None:
        baseline = e30.baseline_stream(e30.CONTEXT_SOLO)
        assert baseline.shape[0] == 450  # 90 rows x 5 frames per tick = 9.0 s
        assert e30.context_song(e30.CONTEXT_SOLO).frames_per_tick == 5

    def test_the_composition_is_the_shared_example_unchanged(self) -> None:
        assert e30.context_source(e30.CONTEXT_COMPOSITION) == (
            "examples/songs/Vaults-of-Nhyrmeth.dsl"
        )
        assert hashlib.sha256(e30.DEFAULT_COMPOSITION.read_bytes()).hexdigest() == (
            e30.COMPOSITION_SHA256
        )
        baseline = e30.baseline_stream(e30.CONTEXT_COMPOSITION)
        assert baseline.shape[0] == 2280
        assert e30.context_song(e30.CONTEXT_COMPOSITION).uses_16bit_bass is True

    def test_the_solo_figure_spans_a_useful_pitch_range(self) -> None:
        spans = e30.e28.channel_note_spans(e30.context_song(e30.CONTEXT_SOLO), e30.MELODIC_CHANNEL)
        pitches = [span["midi"] for span in spans if not span["is_rest"]]
        assert min(pitches) == 57  # A-3
        assert max(pitches) == 74  # D-5
        assert len(pitches) == 16
        assert any(span["is_rest"] for span in spans)

    def test_the_composition_has_all_three_parts(self) -> None:
        song = e30.context_song(e30.CONTEXT_COMPOSITION)
        names = {instrument.name.lower() for instrument in song.instruments}
        assert {"bass", "lead", "perc"} <= names

    def test_the_candidate_plays_on_the_melodic_channel_only(self, rendered: Dict[str, Any]) -> None:
        """CH1 is silent by design: the 16-bit bass puts its AUDC on CH2, the pair's MSB."""
        for record in rendered["records"]:
            if record["context"] == e30.CONTEXT_COMPOSITION:
                assert record["audible_channels"] == [2, 3, 4]
            else:
                assert record["audible_channels"] == [3]


# ---------------------------------------------------------------------------
# 4. the variants change only what they should
# ---------------------------------------------------------------------------
class TestVariants:
    def test_every_candidate_renders_in_both_contexts(self, rendered: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            for candidate in e30.candidate_names():
                stream = rendered["streams"][e30.clip_key(context, candidate)]
                assert stream.shape == rendered["baselines"][context].shape

    def test_only_the_melodic_channels_columns_differ(self, rendered: Dict[str, Any]) -> None:
        allowed = {ir.audf_column(e30.MELODIC_CHANNEL), ir.audc_column(e30.MELODIC_CHANNEL)}
        for context in e30.CONTEXT_ORDER:
            for candidate in e30.candidate_names():
                difference = rendered["differences"][context][candidate]
                assert difference["same_shape"] is True
                assert set(difference["changed_columns"]) <= allowed, (context, candidate)

    def test_the_bass_and_percussion_columns_are_byte_identical(
        self, rendered: Dict[str, Any]
    ) -> None:
        context = e30.CONTEXT_COMPOSITION
        baseline = rendered["baselines"][context]
        untouched = [column for column in range(baseline.shape[1])
                     if column not in (ir.audf_column(3), ir.audc_column(3))]
        for candidate in e30.candidate_names():
            stream = rendered["streams"][e30.clip_key(context, candidate)]
            assert np.array_equal(baseline[:, untouched], stream[:, untouched]), candidate

    def test_the_generator_is_the_candidates_own(self, rendered: Dict[str, Any], bank: Any) -> None:
        for context in e30.CONTEXT_ORDER:
            for candidate in e30.candidate_names():
                entry = e30.candidate_by_name(candidate)
                got = int(rendered["parameters"][context][candidate]["generator_byte"]) & 0xE0
                want = 0x40 if entry["kind"] == "experiment" else int(
                    bank.get(str(entry["profile_id"])).distortion_byte
                )
                assert got == want, (context, candidate)

    def test_the_octave_pulse_variant_moves_the_divider(self, rendered: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            difference = rendered["differences"][context]["c1_octave_pulse"]
            assert ir.audf_column(e30.MELODIC_CHANNEL) in difference["changed_columns"]
            assert difference["changed_frames"] > 0

    def test_the_bank_variants_leave_the_divider_alone(self, rendered: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            for candidate in ("pure_sustain", "pure_pluck", "buzz_steady"):
                difference = rendered["differences"][context][candidate]
                assert ir.audf_column(e30.MELODIC_CHANNEL) not in difference["changed_columns"]

    def test_audctl_is_unchanged(self, rendered: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            want = int(ir.resolve_audctl_mode(e30.context_song(context)))
            for candidate in e30.candidate_names():
                assert rendered["parameters"][context][candidate]["audctl"] == want

    def test_the_applied_envelope_is_read_back_from_the_renderer(self, rendered: Dict[str, Any]) -> None:
        """Each variant's actual envelope, and where each field came from.

        Zero is a legitimate envelope value (a profile can have no decay), so this checks for a
        recorded integer rather than for a non-zero one.
        """
        for context in e30.CONTEXT_ORDER:
            for candidate in e30.candidate_names():
                parameters = rendered["parameters"][context][candidate]
                assert set(parameters["envelope"]) == {
                    "attack_frames", "decay_frames", "release_frames", "sustain_vol"
                }
                assert set(parameters["envelope_sources"]) == set(parameters["envelope"])
                for field, value in parameters["envelope"].items():
                    assert isinstance(value, int), (candidate, field)
                    assert 0 <= value <= 15, (candidate, field, value)

    def test_the_c1_asymmetry_is_recorded_not_hidden(self, rendered: Dict[str, Any]) -> None:
        """C1 keeps the composition's articulation; the bank profiles bring their own."""
        for context in e30.CONTEXT_ORDER:
            c1 = rendered["parameters"][context]["c1_octave_pulse"]
            assert all("default" in source for source in c1["envelope_sources"].values())
            for candidate in ("pure_sustain", "pure_pluck", "buzz_steady"):
                sources = rendered["parameters"][context][candidate]["envelope_sources"]
                assert any(source == "profile" for source in sources.values()), candidate

    def test_the_profiles_fingerprint_is_recorded(self, rendered: Dict[str, Any], bank: Any) -> None:
        for context in e30.CONTEXT_ORDER:
            for candidate in ("pure_sustain", "pure_pluck", "buzz_steady"):
                profile_id = e30.candidate_by_name(candidate)["profile_id"]
                parameters = rendered["parameters"][context][candidate]
                assert parameters["profile_id"] == profile_id
                assert parameters["profile_fingerprint"] == bank.get(str(profile_id)).fingerprint

    def test_no_clip_is_silent(self, rendered: Dict[str, Any]) -> None:
        for key, buffer in rendered["raw"].items():
            assert float(np.max(np.abs(buffer))) > 0.5, key


# ---------------------------------------------------------------------------
# 5. the level policy
# ---------------------------------------------------------------------------
class TestLevelPolicy:
    def test_the_original_set_uses_one_gain_per_context(self, rendered: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            rows = [record for record in rendered["records"]
                    if record["context"] == context and record["version"] == e30.VERSION_ORIGINAL]
            assert len({record["gain"] for record in rows}) == 1
            gain = rows[0]["gain"]
            loudest = max(rendered["plan"]["levels"][e30.clip_key(context, candidate)]["peak"]
                          for candidate in e30.candidate_names())
            assert gain == pytest.approx(e30.TARGET_PEAK / loudest)

    def test_the_original_set_is_not_normalised_per_file(self, rendered: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            rows = [record for record in rendered["records"]
                    if record["context"] == context and record["version"] == e30.VERSION_ORIGINAL]
            assert len({record["after_measured"]["peak"] for record in rows}) > 1

    def test_the_original_wavs_are_the_raw_render_times_the_shared_gain(
        self, rendered: Dict[str, Any]
    ) -> None:
        for record in rendered["records"]:
            if record["version"] != e30.VERSION_ORIGINAL:
                continue
            key = e30.clip_key(record["context"], record["candidate"])
            expected = e30.e26.to_int16(rendered["raw"][key], record["gain"])
            _params, actual = read_wav(rendered["audio_dir"] / record["file"])
            assert np.array_equal(actual, expected), record["file"]

    def test_the_matched_set_is_matched(self, rendered: Dict[str, Any], summary: Dict[str, Any]) -> None:
        matched = [record for record in rendered["records"]
                   if record["version"] == e30.VERSION_MATCHED]
        values = [record["after_measured"]["lufs"] for record in matched]
        assert max(values) - min(values) <= 0.1
        assert summary["validation"]["passed"] is True

    def test_the_matched_target_is_reached_by_every_clip(self, rendered: Dict[str, Any]) -> None:
        target = rendered["plan"]["matched_target_lufs"]
        for record in rendered["records"]:
            if record["version"] == e30.VERSION_MATCHED:
                assert record["after_measured"]["lufs"] == pytest.approx(target, abs=0.05)

    def test_nothing_clips_in_either_set(self, rendered: Dict[str, Any]) -> None:
        for record in rendered["records"]:
            assert record["after_measured"]["peak"] <= 1.0, record["file"]

    def test_the_peak_ceiling_is_respected(self, rendered: Dict[str, Any]) -> None:
        for record in rendered["records"]:
            if record["version"] == e30.VERSION_MATCHED:
                assert record["after_measured"]["peak"] <= e30.MATCHED_PEAK_CEILING + 1e-6

    def test_the_limiting_clip_is_identified(self, rendered: Dict[str, Any]) -> None:
        plan = rendered["plan"]
        if plan["matched_target_capped_by"] == "the peak ceiling":
            key = plan["matched_target_limited_by"]
            assert key in plan["loudness_ceiling_lufs"]
            assert plan["loudness_ceiling_lufs"][key] == min(plan["loudness_ceiling_lufs"].values())
            assert plan["matched_target_lufs"] == pytest.approx(
                plan["loudness_ceiling_lufs"][key], abs=1e-4
            )

    def test_matching_changes_only_the_gain(self, rendered: Dict[str, Any]) -> None:
        """The matched file is the same raw buffer, scaled — not re-rendered or reshaped."""
        for record in rendered["records"]:
            if record["version"] != e30.VERSION_MATCHED:
                continue
            key = e30.clip_key(record["context"], record["candidate"])
            expected = e30.e26.to_int16(rendered["raw"][key], record["gain"])
            _params, actual = read_wav(rendered["audio_dir"] / record["file"])
            assert np.array_equal(actual, expected), record["file"]

    def test_the_delivered_loudness_matches_the_prediction(self, rendered: Dict[str, Any]) -> None:
        """A linear gain shifts LUFS by 20·log10(gain), which is what the prediction assumes."""
        for record in rendered["records"]:
            if record["version"] != e30.VERSION_MATCHED:
                continue
            assert record["after_measured"]["lufs"] == pytest.approx(
                record["after_predicted_lufs"], abs=0.05
            ), record["file"]

    def test_the_measured_spread_is_smaller_than_the_original(self, summary: Dict[str, Any]) -> None:
        before = summary["level_results"]["before_matching"]["lufs_spread"]
        after = summary["level_results"]["matched"]["lufs_spread"]
        assert after < before / 100.0
        assert before > 6.0

    def test_per_context_spreads_are_reported(self, summary: Dict[str, Any]) -> None:
        for context in e30.CONTEXT_ORDER:
            entry = summary["level_results"]["original"]["per_context"][context]
            assert entry["lufs_spread"] > 0.0
            assert entry["lufs_max"] > entry["lufs_min"]


# ---------------------------------------------------------------------------
# 6. the delivered files
# ---------------------------------------------------------------------------
class TestDeliveredFiles:
    def test_there_are_sixteen_files_with_the_expected_names(self, rendered: Dict[str, Any]) -> None:
        expected = {
            f"{context}_{version}_{letter}.wav"
            for context in e30.CONTEXT_ORDER
            for version in e30.VERSION_ORDER
            for letter in e30.LETTERS
        }
        actual = {path.name for path in rendered["audio_dir"].glob("*.wav")}
        assert actual == expected
        assert len(rendered["records"]) == 16

    def test_every_file_has_the_expected_format_and_duration(self, rendered: Dict[str, Any]) -> None:
        for record in rendered["records"]:
            params, samples = read_wav(rendered["audio_dir"] / record["file"])
            assert params.nchannels == 1, record["file"]
            assert params.sampwidth == 2, record["file"]
            assert params.framerate == e30.SAMPLE_RATE, record["file"]
            assert params.nframes == record["samples"], record["file"]
            assert samples.dtype == np.int16
            expected_frames = rendered["baselines"][record["context"]].shape[0]
            assert record["frames"] == expected_frames
            assert record["samples"] == expected_frames * int(e30.SAMPLE_RATE / e30.FRAME_RATE_HZ)

    def test_the_two_versions_of_a_clip_have_the_same_length(self, rendered: Dict[str, Any]) -> None:
        lengths: Dict[Tuple[str, str], set] = {}
        for record in rendered["records"]:
            lengths.setdefault((record["context"], record["letter"]), set()).add(record["samples"])
        for key, values in lengths.items():
            assert len(values) == 1, key

    def test_the_gain_of_every_file_is_published(self, rendered: Dict[str, Any]) -> None:
        for record in rendered["records"]:
            assert record["gain"] > 0.0
            assert record["gain_dbfs"] < 1.0


# ---------------------------------------------------------------------------
# 7. the manifest
# ---------------------------------------------------------------------------
class TestManifest:
    def test_it_maps_every_file_to_a_candidate_context_and_version(
        self, rendered: Dict[str, Any]
    ) -> None:
        manifest = e30.build_manifest(rendered)
        keys = [f"{row['context']}|{row['version']}|{row['letter']}"
                for row in manifest["files"]]
        assert len(keys) == len(set(keys)) == 16
        for row in manifest["files"]:
            assert row["candidate"] in e30.candidate_names()
            assert row["context"] in e30.CONTEXT_ORDER
            assert row["version"] in e30.VERSION_ORDER
            assert row["letter"] in e30.LETTERS
            assert row["file"] == f"{row['context']}_{row['version']}_{row['letter']}.wav"

    def test_it_carries_the_letter_map_and_the_applied_parameters(self, rendered: Dict[str, Any]) -> None:
        manifest = e30.build_manifest(rendered)
        assert manifest["letter_map"] == e30.letter_map()
        for context in e30.CONTEXT_ORDER:
            for candidate in e30.candidate_names():
                parameters = manifest["applied_parameters"][context][candidate]
                assert "generator_byte" in parameters
                assert "envelope" in parameters
                assert "audctl" in parameters

    def test_it_records_the_level_policy(self, rendered: Dict[str, Any]) -> None:
        manifest = e30.build_manifest(rendered)
        policy = manifest["level_policy"]
        assert policy["original"]["per_file_normalisation"] is False
        assert set(policy["original"]["shared_gain_per_context"]) == set(e30.CONTEXT_ORDER)
        assert policy["matched"]["target_lufs"] == rendered["plan"]["matched_target_lufs"]
        assert len(policy["matched"]["gains"]) == 8

    def test_it_is_json_serialisable_and_private(self, rendered: Dict[str, Any]) -> None:
        manifest = e30.build_manifest(rendered)
        assert json.loads(json.dumps(manifest)) == manifest
        assert manifest["private"] is True
        assert "PARTIALLY blinded" in manifest["blinding"]["honest_note"]

    def test_the_summary_records_the_validation(self, rendered: Dict[str, Any]) -> None:
        summary = e30.build_summary(rendered)
        assert json.loads(json.dumps(summary)) == summary
        assert summary["validation"]["passed"] is True
        assert summary["validation"]["failed"] == []
        assert len(summary["validation"]["checks"]) >= 9
        assert all(check["passed"] for check in summary["validation"]["checks"])


# ---------------------------------------------------------------------------
# 8. the listening page
# ---------------------------------------------------------------------------
class TestListeningPage:
    def test_the_page_is_complete(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        assert "__PACKAGE__" not in page and "__TITLE__" not in page
        assert page.startswith("<!DOCTYPE html>")
        assert page.rstrip().endswith("</html>")
        assert page.split("<script>", 1)[0].count("<audio") == 0

    def test_the_static_markup_names_no_candidate(self) -> None:
        for candidate in e30.candidate_names():
            assert candidate not in e30._PAGE_HEAD
        assert "pokey_ref_" not in e30._PAGE_HEAD

    def test_no_candidate_name_appears_outside_the_reveal_block(
        self, rendered: Dict[str, Any]
    ) -> None:
        """The names are embedded only so the reveal button can work without a server.

        Everything visible before the reveal — the markup and the rendering script — must be
        candidate-free, and that is what this checks by cutting the embedded package out.
        """
        page = rendered["page_path"].read_text(encoding="utf-8")
        match = re.search(r"const PACKAGE = (\{.*?\});\n", page, re.S)
        assert match
        outside = page[:match.start(1)] + page[match.end(1):]
        for candidate in e30.candidate_names():
            assert candidate not in outside, candidate
        for candidate in e30.CANDIDATES:
            if candidate["profile_id"]:
                assert candidate["profile_id"] not in outside, candidate["profile_id"]

    def test_the_reveal_block_carries_the_names_and_the_sources(self, rendered: Dict[str, Any]) -> None:
        package = e30.build_listening_package(rendered)
        assert sorted(package["reveal"]) == list(e30.LETTERS)
        for letter, entry in package["reveal"].items():
            assert entry["name"] == e30.letter_map()[letter]
            assert entry["source"]
            assert entry["generator"]

    def test_the_page_shows_letters_not_names(self, rendered: Dict[str, Any]) -> None:
        package = e30.build_listening_package(rendered)
        assert package["letters"] == list(e30.LETTERS)
        for block in package["blocks"]:
            assert block["context"] in e30.CONTEXT_ORDER
        assert "candidate" not in json.dumps(package["files"])

    def test_every_file_the_page_references_exists(self, rendered: Dict[str, Any]) -> None:
        package = e30.build_listening_package(rendered)
        assert len(package["files"]) == 16
        for key, filename in package["files"].items():
            assert (rendered["audio_dir"] / filename).is_file(), key

    def test_both_contexts_and_both_versions_are_presented(self, rendered: Dict[str, Any]) -> None:
        package = e30.build_listening_package(rendered)
        assert [block["context"] for block in package["blocks"]] == list(e30.CONTEXT_ORDER)
        assert package["versions"] == list(e30.VERSION_ORDER)

    def test_the_script_parses(self, rendered: Dict[str, Any]) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not available to syntax-check the page")
        page = rendered["page_path"].read_text(encoding="utf-8")
        body = page.split("<script>", 1)[1]
        chunks = [chunk.split("</script>")[0] for chunk in body.split("<script>")]
        assert len(chunks) == 2
        for index, chunk in enumerate(chunks):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as handle:
                handle.write(chunk)
                script_path = Path(handle.name)
            try:
                result = subprocess.run([node, "--check", str(script_path)],
                                        capture_output=True, text=True)
            finally:
                script_path.unlink()
            assert result.returncode == 0, (index, result.stderr)

    def test_the_page_does_not_upload_anything(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        for token in ("fetch(", "XMLHttpRequest", "navigator.sendBeacon", "WebSocket"):
            assert token not in page, token
        assert "localStorage" in page

    def test_the_page_exports_the_fields_the_template_uses(self, rendered: Dict[str, Any]) -> None:
        package = e30.build_listening_package(rendered)
        assert package["fields"] == list(e30.EVALUATION_FIELDS)
        page = rendered["page_path"].read_text(encoding="utf-8")
        assert "PACKAGE.fields" in page
        assert "csvEscape" in page


# ---------------------------------------------------------------------------
# 9. the evaluation template
# ---------------------------------------------------------------------------
class TestEvaluationTemplate:
    def test_the_headers_match_the_page(self, rendered: Dict[str, Any]) -> None:
        package = e30.build_listening_package(rendered)
        with (rendered["output_dir"] / e30.EVALUATION_CSV).open(
            encoding="utf-8", newline=""
        ) as handle:
            header = next(csv.reader(handle))
        assert header == list(package["fields"]) == list(e30.EVALUATION_FIELDS)

    def test_it_has_one_row_per_delivered_file(self, rendered: Dict[str, Any]) -> None:
        with (rendered["output_dir"] / e30.EVALUATION_CSV).open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 16
        assert sorted({row["context"] for row in rows}) == sorted(e30.CONTEXT_ORDER)
        assert sorted({row["version"] for row in rows}) == sorted(e30.VERSION_ORDER)
        assert sorted({row["letter"] for row in rows}) == list(e30.LETTERS)
        assert all(row["usefulness_1_5"] == "" for row in rows)

    def test_the_form_covers_everything_the_brief_asks_for(self) -> None:
        fields = set(e30.EVALUATION_FIELDS)
        assert {"usefulness_1_5", "interest_1_5", "annoyance_1_5"} <= fields
        assert {"typical_use", "supports_melody", "comment"} <= fields
        assert [scale["field"] for scale in e30.EVALUATION_SCALES] == [
            "usefulness_1_5", "interest_1_5", "annoyance_1_5",
        ]
        for scale in e30.EVALUATION_SCALES:
            assert len(scale["labels"]) == 5
        assert len(e30.TYPICAL_USE_CHOICES) >= 4
        assert len(e30.SUPPORTS_MELODY_CHOICES) >= 3

    def test_no_automatic_score_is_computed(self) -> None:
        """The brief forbids an arbitrary weighted 'best instrument'; the experiment must not emit one."""
        source = Path(e30.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("best_instrument", "overall_score", "weighted_score", "ranking"):
            assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# 10. determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_two_runs_produce_identical_bytes(self, tmp_path: Path) -> None:
        first = e30.render_all(tmp_path / "one")
        second = e30.render_all(tmp_path / "two")
        for record in first["records"]:
            name = record["file"]
            assert file_hash(first["audio_dir"] / name) == file_hash(second["audio_dir"] / name), name
        for name in ("manifest.json", "summary.json", "README.md", "index.html",
                     e30.EVALUATION_CSV):
            assert file_hash(first["output_dir"] / name) == file_hash(
                second["output_dir"] / name
            ), name
        assert first["plan"]["matched_target_lufs"] == second["plan"]["matched_target_lufs"]
        assert first["plan"]["original_gains"] == second["plan"]["original_gains"]

    def test_the_contexts_are_compiled_once_and_reused(self) -> None:
        assert e30.compile_context(e30.CONTEXT_SOLO) is e30.compile_context(e30.CONTEXT_SOLO)
        assert e30.compile_context(e30.CONTEXT_COMPOSITION) is e30.compile_context(
            e30.CONTEXT_COMPOSITION
        )


# ---------------------------------------------------------------------------
# 11. nothing production changed
# ---------------------------------------------------------------------------
class TestProductionUntouched:
    def test_the_experiment_module_is_not_imported_by_production(self) -> None:
        sources = [
            path for path in (e30.REPO_ROOT / "src" / "atari_music").rglob("*.py")
            if path.name not in EXPERIMENT_MODULES
        ]
        assert sources
        for path in sources:
            assert "pokey_timbre_ab_experiment" not in path.read_text(encoding="utf-8"), path

    def test_the_cli_does_not_expose_the_experiment(self) -> None:
        text = (e30.REPO_ROOT / "src" / "atari_music" / "cli.py").read_text(encoding="utf-8")
        assert "timbre_ab" not in text
        assert "experiment30" not in text

    def test_no_candidate_is_registered_as_an_instrument(self) -> None:
        for name in ("ir.py", "pokey_synth.py", "ai/dsl.py", "ai/client.py"):
            text = (e30.REPO_ROOT / "src" / "atari_music" / name).read_text(encoding="utf-8")
            for candidate in e30.candidate_names():
                assert candidate not in text, (name, candidate)

    def test_the_bank_profiles_are_not_modified(self, bank: Any) -> None:
        for candidate in e30.CANDIDATES:
            if candidate["kind"] != "bank":
                continue
            profile = bank.get(str(candidate["profile_id"]))
            assert profile.status in ("PLAYABLE", "PLAYABLE_WITH_LIMITATION")
            assert profile.document["schema"] == "pokey-playable-sound-profile-1.0"

    def test_the_page_references_no_production_module(self, rendered: Dict[str, Any]) -> None:
        page = rendered["page_path"].read_text(encoding="utf-8")
        assert "atari_music" not in page

    def test_the_earlier_experiments_artefacts_are_untouched(self) -> None:
        """E26-E29 artefacts must not have been rewritten by this experiment."""
        for directory in ("experiment26", "experiment27", "experiment28", "experiment29"):
            path = e30.REPO_ROOT / "experiments" / directory
            if not path.is_dir():
                continue
            assert path.is_dir()
        # the experiment writes only under its own output directory
        assert e30.DEFAULT_OUTPUT_DIR.name == "experiment30"


# ---------------------------------------------------------------------------
# 12. the delivered artefacts, when they have been generated
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not (DELIVERED / "summary.json").is_file(),
                    reason="experiment30 has not been generated here")
class TestDeliveredArtefacts:
    def test_the_required_files_are_present(self) -> None:
        for name in ("README.md", "manifest.json", "summary.json", "index.html",
                     e30.EVALUATION_CSV):
            assert (DELIVERED / name).is_file(), name
        audio = sorted((DELIVERED / "audio").glob("*.wav"))
        assert len(audio) == 16

    def test_the_delivered_summary_passed_validation(self) -> None:
        summary = json.loads((DELIVERED / "summary.json").read_text(encoding="utf-8"))
        assert summary["validation"]["passed"] is True
        assert summary["validation"]["failed"] == []
        assert summary["files_rendered"] == 16
        assert summary["production_untouched"] == e30.PRODUCTION_STATEMENT

    def test_the_delivered_matched_set_is_matched(self) -> None:
        summary = json.loads((DELIVERED / "summary.json").read_text(encoding="utf-8"))
        matched = [row for row in summary["measurements"] if row["version"] == "matched"]
        values = [row["after_measured"]["lufs"] for row in matched]
        assert len(matched) == 8
        assert max(values) - min(values) <= 0.1
        assert max(row["after_measured"]["peak"] for row in summary["measurements"]) <= 1.0

    def test_the_delivered_page_is_blinded_before_the_reveal(self) -> None:
        page = (DELIVERED / "index.html").read_text(encoding="utf-8")
        match = re.search(r"const PACKAGE = (\{.*?\});\n", page, re.S)
        assert match
        outside = page[:match.start(1)] + page[match.end(1):]
        for candidate in e30.candidate_names():
            assert candidate not in outside

    def test_the_delivered_readme_states_the_limits(self) -> None:
        note = (DELIVERED / "README.md").read_text(encoding="utf-8")
        assert "index.html" in note
        assert "manifest.json" in note
        assert "LUFS" in note
        assert "not proof" in note

    def test_the_delivered_manifest_maps_every_file(self) -> None:
        manifest = json.loads((DELIVERED / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["files"]) == 16
        assert manifest["letter_map"] == e30.letter_map()
        assert manifest["private"] is True









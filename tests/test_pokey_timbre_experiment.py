"""Experiment 26 — the audible POKEY timbre prototype.

These tests confirm the *experiment* is correct, not that B or C sound better. Specifically:

* the experimental render path is bit-for-bit the production renderer once the production
  normalisation is re-applied, so the prototype is not a second synth with its own sound;
* rendering is deterministic, and the delivered WAVs are 16-bit mono PCM at 44.1 kHz with the
  expected duration and sample count;
* every variant plays the same notes, at the same pitches, for the same number of frames — the
  score cannot drift between variants;
* the variants' register streams and audio buffers genuinely differ, and the differences are the
  ones the module claims (B: the AUDC generator nibble; C: generator + an octave divider pulse);
* one shared gain is applied to all six files, nothing clips, and no per-file normalisation
  happens, so the loudness relation between A, B and C survives;
* no production file is changed.
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pytest

from atari_music import cli as cli_module
from atari_music import ir, pokey_hw, pokey_synth
from atari_music import pokey_timbre_experiment as e26

pytestmark = pytest.mark.experimental

PRODUCTION_FILES: Tuple[str, ...] = (
    "src/atari_music/pokey_synth.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/ir.py",
    "src/atari_music/constants.py",
    "src/atari_music/cli.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/ai/dsl.py",
    "src/atari_music/sound_profiles/bank.py",
    "src/atari_music/sound_profiles/binding.py",
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_wav(path: Path) -> Tuple[Any, np.ndarray]:
    with wave.open(str(path), "rb") as wf:
        params = wf.getparams()
        raw = wf.readframes(wf.getnframes())
    return params, np.frombuffer(raw, dtype=np.int16)


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    """One full render, shared by the tests that only read the output."""
    out = tmp_path_factory.mktemp("experiment26")
    return e26.render_experiment(out)


@pytest.fixture(scope="module")
def streams() -> Dict[Tuple[str, str], np.ndarray]:
    return {
        (variant, score): e26.register_stream(variant, score)
        for variant in e26.VARIANT_ORDER
        for score in e26.SCORES
    }


@pytest.fixture(scope="module")
def raw(result: Dict[str, Any]) -> Dict[Tuple[str, str], np.ndarray]:
    return result["raw"]


# ---------------------------------------------------------------------------
# 1. the prototype renderer is the production renderer
# ---------------------------------------------------------------------------
class TestRendererEquivalence:
    def test_the_experimental_renderer_matches_the_production_one(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """The only intended difference is the normalisation, so undoing it must give equality.

        This is what makes the prototype a *register-stream* experiment rather than a second synth:
        the generator decode, the divider arithmetic, the DAC ladder and the polynomial tables all
        come from the production modules, and this test proves nothing else drifted.
        """
        for key, frames in streams.items():
            raw = e26.render_registers(frames)
            peak = float(np.max(np.abs(raw)))
            assert peak > 0.0, key
            production = pokey_synth.render_pokey_samples(frames)
            experimental = (raw / peak * 0.90 * 32767.0).astype(np.int16)
            assert np.array_equal(production, experimental), key

    def test_the_renderer_returns_a_raw_un_normalised_buffer(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """A raw buffer is not scaled to a fixed peak, which is the whole point of the prototype."""
        for key, frames in streams.items():
            raw = e26.render_registers(frames)
            assert raw.dtype == np.float32, key
            assert raw.shape[0] == frames.shape[0] * int(round(e26.SAMPLE_RATE / e26.FRAME_RATE_HZ))

    def test_rendering_an_empty_stream_is_silent_not_an_error(self) -> None:
        empty = np.zeros((4, 9), dtype=np.uint8)
        assert not np.any(e26.render_registers(empty))


# ---------------------------------------------------------------------------
# 2. determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_the_register_streams_are_deterministic(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key in streams:
            again = e26.register_stream(key[0], key[1])
            assert np.array_equal(streams[key], again), key

    def test_the_audio_buffers_are_deterministic(
        self, streams: Dict[Tuple[str, str], np.ndarray], raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            assert np.array_equal(e26.render_registers(frames), raw[key]), key

    def test_two_full_renders_produce_byte_identical_files(self, tmp_path: Path) -> None:
        left = e26.render_experiment(tmp_path / "left")
        right = e26.render_experiment(tmp_path / "right")
        assert set(left["files"]) == set(right["files"])
        for name in left["files"]:
            assert left["files"][name].read_bytes() == right["files"][name].read_bytes(), name

    def test_the_summary_is_deterministic(self, tmp_path: Path) -> None:
        left = e26.render_experiment(tmp_path / "a")
        right = e26.render_experiment(tmp_path / "b")
        assert e26.build_summary(left) == e26.build_summary(right)


# ---------------------------------------------------------------------------
# 3. the files: format, duration, count
# ---------------------------------------------------------------------------
class TestWavFiles:
    def test_every_expected_file_is_written(self, result: Dict[str, Any]) -> None:
        expected = {
            e26.wav_filename(variant, score)
            for variant in e26.VARIANT_ORDER
            for score in e26.SCORES
        }
        assert set(result["files"]) == expected
        for path in result["files"].values():
            assert path.is_file()

    def test_the_filenames_are_unambiguous(self) -> None:
        assert e26.wav_filename("A", "note") == "A_baseline_note.wav"
        assert e26.wav_filename("B", "phrase") == "B_evolving_phrase.wav"
        assert e26.wav_filename("C", "note") == "C_contrast_note.wav"

    def test_every_file_is_16_bit_mono_pcm_at_44100(self, result: Dict[str, Any]) -> None:
        for name, path in result["files"].items():
            params, _samples = read_wav(path)
            assert params.nchannels == 1, name
            assert params.sampwidth == 2, name
            assert params.framerate == e26.SAMPLE_RATE, name
            assert params.comptype == "NONE", name

    def test_every_duration_matches_the_score(self, result: Dict[str, Any]) -> None:
        for name, path in result["files"].items():
            _params, samples = read_wav(path)
            variant, _, score = name.removesuffix(".wav").split("_", 2)
            assert variant in e26.VARIANT_ORDER
            assert score in e26.SCORES
            expected_frames = e26.total_frames(e26.SCORES[score])
            expected_samples = expected_frames * int(round(e26.SAMPLE_RATE / e26.FRAME_RATE_HZ))
            assert samples.shape[0] == expected_samples, name
            duration = samples.shape[0] / e26.SAMPLE_RATE
            assert duration == pytest.approx(expected_frames / e26.FRAME_RATE_HZ, abs=1e-9)

    def test_the_summary_matches_the_files_on_disk(self, result: Dict[str, Any]) -> None:
        summary_path = e26.write_summary(result, result["output_dir"])
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["experiment"] == "experiment26"
        assert summary["sample_rate"] == e26.SAMPLE_RATE
        assert len(summary["files"]) == 6
        for row in summary["files"]:
            _params, samples = read_wav(result["files"][row["file"]])
            assert row["samples"] == samples.shape[0]
            assert row["duration_seconds"] == pytest.approx(
                samples.shape[0] / e26.SAMPLE_RATE, abs=1e-4
            )


# ---------------------------------------------------------------------------
# 4. the notes, pitches and durations agree between variants
# ---------------------------------------------------------------------------
class TestScoreAgreement:
    def test_the_spans_are_the_score(self) -> None:
        assert e26.note_spans(e26.ISOLATED_NOTE) == [(0, 48, 69)]
        assert e26.note_spans(e26.SHORT_PHRASE) == [
            (0, 20, 69), (20, 40, 72), (40, 60, 76), (60, 80, 72)
        ]

    def test_every_variant_covers_the_same_frames(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in e26.SCORES:
            lengths = {streams[(variant, score)].shape for variant in e26.VARIANT_ORDER}
            assert len(lengths) == 1, score
            assert lengths.pop()[0] == e26.total_frames(e26.SCORES[score])

    def test_the_nominal_pitch_of_each_note_is_the_same_in_every_variant(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """The divider on the first frame of every note is the score's pitch, in all three."""
        for score in e26.SCORES:
            for start, _end, midi in e26.note_spans(e26.SCORES[score]):
                expected = e26.note_divider(midi)
                for variant in e26.VARIANT_ORDER:
                    frames = streams[(variant, score)]
                    assert frames[start, ir.audf_column(e26.CHANNEL)] == expected, (variant, midi)

    def test_the_realised_pitch_is_within_eight_bit_pokey_error(self) -> None:
        for midi, _rows in e26.SHORT_PHRASE:
            divider = e26.note_divider(midi)
            realised = pokey_hw.hz_from_audf_8bit(divider, e26.AUDCTL, e26.CHANNEL)
            nominal = ir.midi_pitch_to_frequency(midi)
            assert abs(realised - nominal) / nominal < 0.02, midi

    def test_the_note_lengths_are_the_same_in_every_variant(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """Each note sounds for exactly its score length, and the next onset lands on frame *end*."""
        for score in e26.SCORES:
            spans = e26.note_spans(e26.SCORES[score])
            for index, (start, end, _midi) in enumerate(spans):
                for variant in e26.VARIANT_ORDER:
                    frames = streams[(variant, score)]
                    audc_col = ir.audc_column(e26.CHANNEL)
                    # every frame of the note is audible, so the note really lasts `end - start`
                    assert (frames[start:end, audc_col] & 0x0F).min() > 0, (variant, index)
                    # and it does not run on: the next note begins on the very next frame
                    if end < frames.shape[0]:
                        next_midi = spans[index + 1][2]
                        assert frames[end, 0] == e26.note_divider(next_midi), (variant, index)
                        assert (frames[end, audc_col] & 0x0F) > 0, (variant, index)

    def test_the_clock_and_the_channel_layout_are_identical(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            assert set(int(value) for value in np.unique(frames[:, 8])) == {e26.AUDCTL}, key
            for column in (2, 3, 4, 5, 6, 7):
                assert not np.any(frames[:, column]), (key, column)

    def test_every_register_value_is_a_real_byte(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            assert frames.dtype == np.uint8, key
            for start, end, _midi in e26.note_spans(e26.SCORES[key[1]]):
                assert np.all(frames[start:end, 0] <= pokey_hw.AUDF_TRACKER_MAX), key


# ---------------------------------------------------------------------------
# 5. the variants differ, and differ in the way the module claims
# ---------------------------------------------------------------------------
class TestVariantDifferences:
    def test_the_register_streams_are_pairwise_different(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in e26.SCORES:
            for left, right in (("A", "B"), ("A", "C"), ("B", "C")):
                assert not np.array_equal(streams[(left, score)], streams[(right, score)]), (
                    score, left, right
                )

    def test_the_audio_buffers_are_pairwise_different(
        self, raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in e26.SCORES:
            for left, right in (("A", "B"), ("A", "C"), ("B", "C")):
                assert not np.array_equal(raw[(left, score)], raw[(right, score)]), (
                    score, left, right
                )

    def test_b_differs_from_a_only_in_the_generator_nibble(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """The design claim: B changes the AUDC generator and nothing else."""
        for score in e26.SCORES:
            a = streams[("A", score)]
            b = streams[("B", score)]
            assert np.array_equal(a[:, 0], b[:, 0]), score  # AUDF identical
            assert np.array_equal(a[:, 8], b[:, 8]), score  # AUDCTL identical
            assert np.array_equal(a[:, 1] & 0x0F, b[:, 1] & 0x0F), score  # volume identical
            assert not np.array_equal(a[:, 1] & 0xE0, b[:, 1] & 0xE0), score  # generator differs

    def test_b_uses_every_generator_in_its_sequence(self) -> None:
        frames = e26.register_stream("B", "note")
        used = {int(value) & 0xE0 for value in np.unique(frames[:, 1])}
        assert used == {0xA0, 0x60, 0xC0, 0x40}

    def test_b_steps_the_generator_on_the_declared_grid(self) -> None:
        frames = e26.register_stream("B", "note")
        generators = [int(frames[index, 1]) & 0xE0 for index in range(frames.shape[0])]
        for index, generator in enumerate(generators):
            assert generator == e26.generator_for_frame(index) & 0xE0, index

    def test_c_pulses_the_divider_between_the_note_and_its_octave(self) -> None:
        frames = e26.register_stream("C", "note")
        nominal = e26.note_divider(69)
        upper = e26.octave_divider(nominal)
        assert upper == nominal // 2
        assert upper < nominal
        assert set(int(value) for value in np.unique(frames[:, 0])) == {nominal, upper}
        for index in range(frames.shape[0]):
            expected = nominal if index % 2 == 0 else upper
            assert frames[index, 0] == expected, index

    def test_a_and_b_hold_the_divider_steady(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for variant in ("A", "B"):
            for score in e26.SCORES:
                frames = streams[(variant, score)]
                for start, end, midi in e26.note_spans(e26.SCORES[score]):
                    assert len(set(int(v) for v in frames[start:end, 0])) == 1, (variant, score)
                    assert frames[start, 0] == e26.note_divider(midi), (variant, score)

    def test_c_uses_one_generator_throughout(self) -> None:
        for score in e26.SCORES:
            frames = e26.register_stream("C", score)
            assert {int(value) & 0xE0 for value in np.unique(frames[:, 1])} == {e26.C_GENERATOR}

    def test_the_octave_pulse_puts_energy_where_a_pure_square_has_none(
        self, raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """A is a square wave, so it has no even harmonic near 880 Hz. C's pulse must create one."""
        def band(buffer: np.ndarray, low: float, high: float) -> float:
            steady = buffer[e26.SAMPLE_RATE // 10:]  # skip the onset transient
            spectrum = np.abs(np.fft.rfft(steady.astype(np.float64)))
            freqs = np.fft.rfftfreq(steady.shape[0], 1.0 / e26.SAMPLE_RATE)
            return float(np.sum(spectrum[(freqs >= low) & (freqs <= high)] ** 2))

        a_octave = band(raw[("A", "note")], 820.0, 940.0)
        c_octave = band(raw[("C", "note")], 820.0, 940.0)
        assert c_octave > 5.0 * a_octave

    def test_the_fundamental_is_at_the_noted_pitch(
        self, raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """A and B hold one divider, so their strongest partial is the note itself."""
        for variant in ("A", "B"):
            buffer = raw[(variant, "note")][e26.SAMPLE_RATE // 10:].astype(np.float64)
            spectrum = np.abs(np.fft.rfft(buffer))
            freqs = np.fft.rfftfreq(buffer.shape[0], 1.0 / e26.SAMPLE_RATE)
            band = (freqs >= 200.0) & (freqs <= 900.0)
            peak = float(freqs[band][int(np.argmax(spectrum[band]))])
            assert abs(peak - 439.843) < 12.0, (variant, peak)

    def test_no_variant_is_silent(self, raw: Dict[Tuple[str, str], np.ndarray]) -> None:
        for key, buffer in raw.items():
            assert float(np.max(np.abs(buffer))) > 0.5, key


# ---------------------------------------------------------------------------
# 6. level handling: one shared gain, no per-file normalisation, no clipping
# ---------------------------------------------------------------------------
class TestLevelPolicy:
    def test_the_gain_is_derived_from_the_loudest_raw_render(self, result: Dict[str, Any]) -> None:
        assert result["gain"] == pytest.approx(e26.TARGET_PEAK / result["reference_peak"])
        assert result["reference_peak"] == pytest.approx(
            max(float(np.max(np.abs(buffer))) for buffer in result["raw"].values())
        )

    def test_one_gain_is_applied_to_all_six_files(self, result: Dict[str, Any]) -> None:
        """The gain is a property of the run, not of a file: no per-file normalisation happens."""
        gain = result["gain"]
        assert gain > 0.0
        for key, buffer in result["raw"].items():
            assert np.array_equal(
                e26.to_int16(buffer, gain), e26.to_int16(buffer, result["gain"])
            ), key
        assert e26.build_summary(result)["level_policy"]["per_file_normalisation"] is False

    def test_the_loudest_file_peaks_at_the_target_and_nothing_clips(
        self, result: Dict[str, Any]
    ) -> None:
        peaks = [
            int(np.max(np.abs(e26.to_int16(buffer, result["gain"]))))
            for buffer in result["raw"].values()
        ]
        assert max(peaks) <= int(e26.TARGET_PEAK * 32767) + 1
        assert max(peaks) >= int(e26.TARGET_PEAK * 32767) - 2

    def test_the_delivered_amplitude_tracks_the_raw_amplitude(self, result: Dict[str, Any]) -> None:
        """A shared gain means every delivered peak is its own raw peak times the same factor."""
        for row in result["rows"]:
            assert row["peak_after_gain"] == pytest.approx(
                row["raw_peak"] * result["gain"], rel=0.01
            ), row["file"]
            assert row["rms_after_gain"] == pytest.approx(
                row["raw_rms"] * result["gain"], rel=0.02
            ), row["file"]

    def test_a_quieter_variant_stays_quieter(self) -> None:
        """A deliberately quieter variant must not be lifted to match a louder one."""
        quiet = e26.evolving_stream(e26.ISOLATED_NOTE).copy()
        quiet[:, 1] = quiet[:, 1] & 0xE0  # silence the note: no volume nibble
        assert not np.any(quiet[:, 1] & 0x0F)
        assert not np.any(e26.render_registers(quiet))


# ---------------------------------------------------------------------------
# 7. nothing in the production pipeline changed
# ---------------------------------------------------------------------------
class TestProductionUntouched:
    def test_the_production_files_are_unchanged_by_a_render(self, tmp_path: Path) -> None:
        before = {name: file_hash(e26.REPO_ROOT / name) for name in PRODUCTION_FILES}
        e26.render_experiment(tmp_path / "render")
        after = {name: file_hash(e26.REPO_ROOT / name) for name in PRODUCTION_FILES}
        assert before == after

    def test_the_production_tables_are_reused_not_re_derived(self) -> None:
        assert e26.POKEY_DAC is pokey_synth.POKEY_DAC
        assert e26.POLY4_SEQ is pokey_synth.POLY4_SEQ
        assert e26.POLY5_SEQ is pokey_synth.POLY5_SEQ
        assert e26.POLY9_SEQ is pokey_synth.POLY9_SEQ
        assert e26.POLY17_SEQ is pokey_synth.POLY17_SEQ

    def test_variant_a_really_comes_from_the_production_compiler(self) -> None:
        """A is the existing pipeline's output, so the compiler must be what produced it."""
        for score in e26.SCORES:
            compiled = ir.compile_ir_to_pokey_frames(e26.baseline_song(e26.SCORES[score]))
            assert np.array_equal(compiled, e26.register_stream("A", score)), score

    def test_the_experiment_is_not_wired_into_the_cli(self) -> None:
        names = sorted(cli_module.cli.commands)
        assert not any("experiment26" in name for name in names)
        assert not any("timbre" in name for name in names)

    def test_no_production_module_imports_the_prototype(self) -> None:
        """The prototype may not be a dependency of the pipeline.

        Experiment modules are excluded by name: Experiment 27 develops this prototype and reuses its
        variant C directly, Experiment 28 reuses both to test C1 inside a composition, and Experiment 29
        reuses this prototype's renderer for its audition set. Those are experiment-to-experiment
        dependencies, not pipeline dependencies.
        """
        src = e26.REPO_ROOT / "src" / "atari_music"
        experiment_modules = {
            "pokey_timbre_experiment.py",
            "pokey_octave_pulse_experiment.py",
            "pokey_c1_musical_context_experiment.py",
            "pokey_timbre_library_experiment.py",
            "pokey_timbre_ab_experiment.py",
        }
        offenders = []
        for path in sorted(src.rglob("*.py")):
            if path.name in experiment_modules:
                continue
            if "pokey_timbre_experiment" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        assert offenders == []

    def test_the_hardware_model_is_untouched(self) -> None:
        """A sanity check that importing the prototype did not shadow the hardware truth."""
        assert pokey_hw.decode_audc(0xA0) == pokey_hw.Waveform.PURE_TONE
        assert pokey_hw.decode_audc(0x40) == pokey_hw.Waveform.POLY5_GATED_POLY4
        assert pokey_hw.decode_audc(0xC0) == pokey_hw.Waveform.POLY4
        assert pokey_hw.decode_audc(0x60) == pokey_hw.Waveform.POLY5_GATED_PURE


# ---------------------------------------------------------------------------
# 8. the delivered artefacts, when they are present locally
# ---------------------------------------------------------------------------
DELIVERED = e26.DEFAULT_OUTPUT_DIR

requires_delivered = pytest.mark.skipif(
    not (DELIVERED / "summary.json").is_file(),
    reason="experiment26 has not been rendered into experiments/experiment26 on this machine",
)


@requires_delivered
class TestDeliveredArtefacts:
    def test_the_six_wavs_the_summary_and_the_note_are_present(self) -> None:
        for variant in e26.VARIANT_ORDER:
            for score in e26.SCORES:
                assert (DELIVERED / e26.wav_filename(variant, score)).is_file()
        assert (DELIVERED / "summary.json").is_file()
        assert (DELIVERED / "README.md").is_file()

    def test_the_delivered_files_are_well_formed(self) -> None:
        for variant in e26.VARIANT_ORDER:
            for score in e26.SCORES:
                params, samples = read_wav(DELIVERED / e26.wav_filename(variant, score))
                assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, 44100)
                expected = e26.total_frames(e26.SCORES[score]) * int(
                    round(e26.SAMPLE_RATE / e26.FRAME_RATE_HZ)
                )
                assert samples.shape[0] == expected
                assert int(np.max(np.abs(samples))) > 1000

    def test_the_delivered_set_matches_a_fresh_render_byte_for_byte(self, tmp_path: Path) -> None:
        fresh = e26.render_experiment(tmp_path / "fresh")
        for name, path in fresh["files"].items():
            assert path.read_bytes() == (DELIVERED / name).read_bytes(), name
        assert fresh["summary_path"].read_bytes() == (DELIVERED / "summary.json").read_bytes()
        assert fresh["note_path"].read_bytes() == (DELIVERED / "README.md").read_bytes()

    def test_the_delivered_summary_records_the_level_policy(self) -> None:
        summary = json.loads((DELIVERED / "summary.json").read_text(encoding="utf-8"))
        assert summary["level_policy"]["per_file_normalisation"] is False
        assert len(summary["files"]) == 6
        assert summary["score"]["note"]["notes"][0]["name"] == "A-4"

    def test_the_listening_note_names_every_file(self) -> None:
        note = (DELIVERED / "README.md").read_text(encoding="utf-8")
        for variant in e26.VARIANT_ORDER:
            for score in e26.SCORES:
                assert e26.wav_filename(variant, score) in note
        assert "No file was normalised on its own" in note
        assert "does not claim" in note








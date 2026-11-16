"""Experiment 27 — musical characterisation of the POKEY octave-pulse timbre.

These tests confirm the *experiment*, not the sound. Specifically:

* C1 really is Experiment 26's variant C — taken from that module and, in the delivered set,
  byte-identical to the file that was listened to — and the generic schedule path reproduces it;
* each of C2, C3 and C4 moves exactly **one** field of the pulse schedule and leaves the generator,
  the volume, the note grid, the channel and AUDCTL alone, so no comparison changes two things;
* the AUDF byte of every frame matches the declared schedule, checked against an independent
  restatement of the parameters rather than against the code that wrote the stream;
* no other register is touched, and no variant writes a divider the mechanism cannot justify;
* rendering is deterministic, the WAVs are 16-bit mono PCM at 44.1 kHz with the right duration, and
  one shared gain is applied to all twelve files with no per-file normalisation;
* no production file, and no Experiment 26 file, is changed.
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from atari_music import cli as cli_module
from atari_music import pokey_octave_pulse_experiment as e27
from atari_music import pokey_synth, pokey_timbre_experiment as e26

pytestmark = pytest.mark.experimental

#: Every production file the experiment must leave alone, plus Experiment 26's module, which it
#: depends on and therefore must not modify.
UNTOUCHED_FILES: Tuple[str, ...] = (
    "src/atari_music/pokey_synth.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/ir.py",
    "src/atari_music/constants.py",
    "src/atari_music/cli.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/ai/dsl.py",
    "src/atari_music/sound_profiles/bank.py",
    "src/atari_music/sound_profiles/binding.py",
    "src/atari_music/pokey_timbre_experiment.py",
)

DELIVERED = e27.DEFAULT_OUTPUT_DIR
DELIVERED_E26 = e26.DEFAULT_OUTPUT_DIR


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_wav(path: Path) -> Tuple[Any, np.ndarray]:
    with wave.open(str(path), "rb") as wf:
        params = wf.getparams()
        raw = wf.readframes(wf.getnframes())
    return params, np.frombuffer(raw, dtype=np.int16)


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    out = tmp_path_factory.mktemp("experiment27")
    return e27.render_experiment(out)


@pytest.fixture(scope="module")
def streams() -> Dict[Tuple[str, str], np.ndarray]:
    return {
        (variant, score): e27.variant_stream(variant, score)
        for variant in e27.VARIANT_ORDER
        for score in e27.SCORES
    }


@pytest.fixture(scope="module")
def raw(result: Dict[str, Any]) -> Dict[Tuple[str, str], np.ndarray]:
    return result["raw"]


# ---------------------------------------------------------------------------
# 1. C1 is Experiment 26's variant C, not a reconstruction
# ---------------------------------------------------------------------------
class TestBaselineIsTheRealVariantC:
    def test_c1_is_experiment_26s_contrast_stream(self) -> None:
        for score in e27.SCORES:
            assert np.array_equal(
                e27.variant_stream("C1", score), e26.contrast_stream(e27.SCORES[score])
            ), score

    def test_c1_is_unchanged_when_experiment_26s_stream_changes(self) -> None:
        """C1 must come from the other module, not from a copy of its output."""
        assert e27.c1_stream is not e26.contrast_stream
        assert np.array_equal(
            e27.c1_stream(e27.ISOLATED_NOTE), e26.contrast_stream(e27.ISOLATED_NOTE)
        )

    def test_the_generic_schedule_path_reproduces_c1(self) -> None:
        """What licenses C2–C4 as the same mechanism with one parameter moved."""
        for score in e27.SCORES:
            assert np.array_equal(
                e27.scheduled_stream(e27.SCORES[score], e27.SCHEDULES["C1"]),
                e26.contrast_stream(e27.SCORES[score]),
            ), score

    def test_c1_uses_experiment_26s_generator_and_volume(self) -> None:
        assert e27.SCHEDULES["C1"].hold_frames == 1
        assert e27.SCHEDULES["C1"].active_frames is None
        assert e27.SCHEDULES["C1"].active_notes == ()
        assert e27.SCHEDULES["C1"].alternation_hz == 25.0

    @pytest.mark.skipif(
        not (DELIVERED_E26 / "C_contrast_note.wav").is_file(),
        reason="Experiment 26 has not been rendered on this machine",
    )
    def test_the_delivered_c1_is_byte_identical_to_experiment_26s_c(self, result: Dict[str, Any]) -> None:
        """Same register stream and same shared gain, so the file must be the listened artefact."""
        pairs = (
            ("C1_pulse1_note.wav", "C_contrast_note.wav"),
            ("C1_pulse1_phrase.wav", "C_contrast_phrase.wav"),
        )
        for mine, theirs in pairs:
            assert (
                result["files"][mine].read_bytes()
                == (DELIVERED_E26 / theirs).read_bytes()
            ), mine


# ---------------------------------------------------------------------------
# 2. determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_the_streams_are_deterministic(self, streams: Dict[Tuple[str, str], np.ndarray]) -> None:
        for key in streams:
            assert np.array_equal(streams[key], e27.variant_stream(key[0], key[1])), key

    def test_the_buffers_are_deterministic(
        self, streams: Dict[Tuple[str, str], np.ndarray], raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            assert np.array_equal(e26.render_registers(frames), raw[key]), key

    def test_two_renders_produce_byte_identical_files(self, tmp_path: Path) -> None:
        left = e27.render_experiment(tmp_path / "left")
        right = e27.render_experiment(tmp_path / "right")
        assert set(left["files"]) == set(right["files"])
        for name in left["files"]:
            assert left["files"][name].read_bytes() == right["files"][name].read_bytes(), name
        assert left["summary_path"].read_bytes() == right["summary_path"].read_bytes()
        assert left["note_path"].read_bytes() == right["note_path"].read_bytes()

    def test_the_summary_is_deterministic(self, tmp_path: Path) -> None:
        left = e27.render_experiment(tmp_path / "a")
        right = e27.render_experiment(tmp_path / "b")
        assert e27.build_summary(left) == e27.build_summary(right)


# ---------------------------------------------------------------------------
# 3. the files: format, duration, count
# ---------------------------------------------------------------------------
class TestWavFiles:
    def test_every_expected_file_is_written(self, result: Dict[str, Any]) -> None:
        expected = {
            e27.wav_filename(variant, score)
            for variant in e27.VARIANT_ORDER
            for score in e27.SCORES
        }
        assert set(result["files"]) == expected
        assert len(expected) == 12
        for path in result["files"].values():
            assert path.is_file()

    def test_the_filenames_are_unambiguous(self) -> None:
        assert e27.wav_filename("C1", "note") == "C1_pulse1_note.wav"
        assert e27.wav_filename("C2", "phrase") == "C2_pulse4_phrase.wav"
        assert e27.wav_filename("C3", "phrase_low") == "C3_onset_phrase_low.wav"
        assert e27.wav_filename("C4", "phrase") == "C4_selected_phrase.wav"

    def test_every_file_is_16_bit_mono_pcm_at_44100(self, result: Dict[str, Any]) -> None:
        for name, path in result["files"].items():
            params, _samples = read_wav(path)
            assert params.nchannels == 1, name
            assert params.sampwidth == 2, name
            assert params.framerate == e27.SAMPLE_RATE, name
            assert params.comptype == "NONE", name

    def test_every_duration_matches_the_score(self, result: Dict[str, Any]) -> None:
        for name, path in result["files"].items():
            _params, samples = read_wav(path)
            score = name.removesuffix(".wav").split("_", 2)[2]
            assert score in e27.SCORES
            frames = e26.total_frames(e27.SCORES[score])
            expected = frames * int(round(e27.SAMPLE_RATE / e27.FRAME_RATE_HZ))
            assert samples.shape[0] == expected, name
            assert samples.shape[0] / e27.SAMPLE_RATE == pytest.approx(
                frames / e27.FRAME_RATE_HZ, abs=1e-9
            )


# ---------------------------------------------------------------------------
# 4. the score and the basic parameters agree between variants
# ---------------------------------------------------------------------------
class TestScoreAgreement:
    def test_the_score_grid_is_the_one_experiment_26_used(self) -> None:
        assert e27.ISOLATED_NOTE == e26.ISOLATED_NOTE
        assert e27.SHORT_PHRASE == e26.SHORT_PHRASE
        assert e26.note_spans(e27.ISOLATED_NOTE) == [(0, 48, 69)]
        assert e26.note_spans(e27.SHORT_PHRASE) == [
            (0, 20, 69), (20, 40, 72), (40, 60, 76), (60, 80, 72)
        ]
        assert e26.note_spans(e27.LOW_PHRASE) == [
            (0, 20, 57), (20, 40, 60), (40, 60, 64), (60, 80, 60)
        ]

    def test_every_variant_covers_the_same_frames(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in e27.SCORES:
            shapes = {streams[(variant, score)].shape for variant in e27.VARIANT_ORDER}
            assert len(shapes) == 1, score
            assert shapes.pop()[0] == e26.total_frames(e27.SCORES[score])

    def test_the_nominal_pitch_of_every_note_is_the_same_in_every_variant(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """Every note *starts* on its own nominal divider in all four variants."""
        for score in e27.SCORES:
            for start, _end, midi in e26.note_spans(e27.SCORES[score]):
                expected = e26.note_divider(midi)
                for variant in e27.VARIANT_ORDER:
                    assert (
                        streams[(variant, score)][start, e26.ir.audf_column(e27.CHANNEL)]
                        == expected
                    ), (variant, score, midi)

    def test_the_channel_clock_and_note_boundaries_are_identical(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            assert set(int(value) for value in np.unique(frames[:, 8])) == {e27.AUDCTL}, key
            for start, end, _midi in e26.note_spans(e27.SCORES[key[1]]):
                assert (frames[start:end, 1] & 0x0F).min() > 0, key

    def test_the_dividers_are_the_expected_pokey_values(self) -> None:
        assert e26.note_divider(69) == 71
        assert e26.note_divider(72) == 60
        assert e26.note_divider(76) == 47
        assert e26.note_divider(57) == 143
        assert e26.note_divider(60) == 120
        assert e26.note_divider(64) == 95


# ---------------------------------------------------------------------------
# 5. the divider is exactly what each schedule says it is
# ---------------------------------------------------------------------------
class TestDividers:
    def test_every_frame_matches_the_declared_schedule(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """Checked against an independent restatement of the parameters, not against the writer."""
        for variant in e27.VARIANT_ORDER:
            for score in e27.SCORES:
                expected = e27.expected_dividers(variant, score)
                actual = [int(value) for value in streams[(variant, score)][:, 0]]
                assert actual == expected, (variant, score)

    def test_every_variant_only_ever_uses_n_or_its_octave(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            allowed = set()
            for _start, _end, midi in e26.note_spans(e27.SCORES[key[1]]):
                nominal = e26.note_divider(midi)
                allowed |= {nominal, e26.octave_divider(nominal)}
            assert set(int(v) for v in np.unique(frames[:, 0])) <= allowed, key

    def test_the_octave_up_divider_is_n_over_two(self) -> None:
        for midi, _rows in e27.SHORT_PHRASE + e27.LOW_PHRASE:
            nominal = e26.note_divider(midi)
            assert e26.octave_divider(nominal) == nominal // 2
            assert e26.octave_divider(nominal) < nominal

    def test_c1_alternates_every_frame(self, streams: Dict[Tuple[str, str], np.ndarray]) -> None:
        frames = streams[("C1", "note")]
        nominal = e26.note_divider(69)
        upper = e26.octave_divider(nominal)
        for offset in range(frames.shape[0]):
            assert frames[offset, 0] == (nominal if offset % 2 == 0 else upper), offset
        assert e27.divider_switches(frames) == frames.shape[0] - 1

    def test_c2_holds_each_divider_for_four_frames(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        frames = streams[("C2", "note")]
        nominal = e26.note_divider(69)
        upper = e26.octave_divider(nominal)
        for offset in range(frames.shape[0]):
            assert frames[offset, 0] == (nominal if (offset // 4) % 2 == 0 else upper), offset
        assert e27.SCHEDULES["C2"].alternation_hz == pytest.approx(6.25)

    def test_c3_pulses_only_for_the_first_eight_frames(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        frames = streams[("C3", "note")]
        nominal = e26.note_divider(69)
        upper = e26.octave_divider(nominal)
        for offset in range(8):
            assert frames[offset, 0] == (nominal if offset % 2 == 0 else upper), offset
        assert set(int(v) for v in frames[8:, 0]) == {nominal}
        assert e27.divider_switches(frames) == 8

    def test_c4_pulses_only_the_selected_notes(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        frames = streams[("C4", "phrase")]
        for note_index, (start, end, midi) in enumerate(e26.note_spans(e27.SHORT_PHRASE)):
            nominal = e26.note_divider(midi)
            column = {int(value) for value in frames[start:end, 0]}
            if note_index in e27.SCHEDULES["C4"].active_notes:
                assert column == {nominal, e26.octave_divider(nominal)}, note_index
            else:
                assert column == {nominal}, note_index

    def test_c4_reduces_to_c1_on_a_single_note(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """The only note is note 0, which C4 selects, so the two agree by construction."""
        assert np.array_equal(streams[("C4", "note")], streams[("C1", "note")])

    def test_the_low_phrases_octave_up_dividers_are_the_high_phrases_fundamentals(self) -> None:
        """A-3→71, C-4→60, E-4→47: the low octave pulse lands on the high phrase's own pitches."""
        assert [e26.octave_divider(e26.note_divider(midi)) for midi, _r in e27.LOW_PHRASE] == [
            71, 60, 47, 60
        ]


# ---------------------------------------------------------------------------
# 6. nothing else in the register stream moves
# ---------------------------------------------------------------------------
class TestNoUnintendedRegisterChanges:
    def test_the_spare_channels_stay_silent(self, streams: Dict[Tuple[str, str], np.ndarray]) -> None:
        for key, frames in streams.items():
            for column in (2, 3, 4, 5, 6, 7):
                assert not np.any(frames[:, column]), (key, column)

    def test_audctl_is_constant_and_identical_in_every_variant(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for key, frames in streams.items():
            assert set(int(v) for v in np.unique(frames[:, 8])) == {e27.AUDCTL}, key

    def test_the_generator_nibble_is_experiment_26s_in_every_variant(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        expected = e26.C_GENERATOR & 0xE0
        for key, frames in streams.items():
            assert {int(v) & 0xE0 for v in np.unique(frames[:, 1])} == {expected}, key

    def test_the_volume_is_the_plucked_shape_in_every_variant(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """The schedule must not touch the volume: AUDC's low nibble is C1's shape everywhere."""
        for key, frames in streams.items():
            for start, end, _midi in e26.note_spans(e27.SCORES[key[1]]):
                expected = e26.plucked_volume_shape(end - start)
                actual = [int(v) & 0x0F for v in frames[start:end, 1]]
                assert actual == expected, (key, start)

    def test_only_channel_1_audf_and_audc_differ_between_variants(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in e27.SCORES:
            reference = streams[("C1", score)]
            for variant in ("C2", "C3", "C4"):
                other = streams[(variant, score)]
                for column in (1, 2, 3, 4, 5, 6, 7, 8):
                    assert np.array_equal(reference[:, column], other[:, column]), (
                        score, variant, column
                    )

    def test_every_register_value_is_encodable(self, streams: Dict[Tuple[str, str], np.ndarray]) -> None:
        for key, frames in streams.items():
            assert frames.dtype == np.uint8, key
            for start, end, _midi in e26.note_spans(e27.SCORES[key[1]]):
                assert np.all(frames[start:end, 0] <= e26.pokey_hw.AUDF_TRACKER_MAX), key
                assert np.all(frames[start:end, 0] >= e26.pokey_hw.AUDF_MIN), key


# ---------------------------------------------------------------------------
# 7. one parameter at a time
# ---------------------------------------------------------------------------
class TestOneParameterAtATime:
    def test_c2_moves_only_the_hold_length(self) -> None:
        c1, c2 = e27.SCHEDULES["C1"], e27.SCHEDULES["C2"]
        assert c2.hold_frames != c1.hold_frames
        assert c2.active_frames == c1.active_frames
        assert c2.active_notes == c1.active_notes

    def test_c3_moves_only_the_active_duration(self) -> None:
        c1, c3 = e27.SCHEDULES["C1"], e27.SCHEDULES["C3"]
        assert c3.active_frames != c1.active_frames
        assert c3.hold_frames == c1.hold_frames
        assert c3.active_notes == c1.active_notes

    def test_c4_moves_only_the_selected_notes(self) -> None:
        c1, c4 = e27.SCHEDULES["C1"], e27.SCHEDULES["C4"]
        assert c4.active_notes != c1.active_notes
        assert c4.hold_frames == c1.hold_frames
        assert c4.active_frames == c1.active_frames

    def test_each_variant_differs_from_c1_only_in_the_divider_column(
        self, streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in e27.SCORES:
            reference = streams[("C1", score)]
            for variant in ("C2", "C3", "C4"):
                other = streams[(variant, score)]
                if np.array_equal(reference, other):
                    # C4 selects note 0 and the single-note score contains only note 0, so C4 *is*
                    # C1 there. That equality is a consequence of the parameterisation and is
                    # asserted on its own; it is not a defect.
                    assert (variant, score) == ("C4", "note"), (score, variant)
                    continue
                changed = {
                    column
                    for column in range(9)
                    if not np.array_equal(reference[:, column], other[:, column])
                }
                assert changed <= {0}, (score, variant, changed)

    def test_the_pulse_rates_are_derived_from_the_hold_length(self) -> None:
        assert e27.SCHEDULES["C1"].alternation_hz == pytest.approx(25.0)
        assert e27.SCHEDULES["C2"].alternation_hz == pytest.approx(6.25)
        assert e27.SCHEDULES["C3"].alternation_hz == pytest.approx(25.0)
        assert e27.SCHEDULES["C4"].alternation_hz == pytest.approx(25.0)

    def test_the_schedule_rejects_an_impossible_hold(self) -> None:
        with pytest.raises(ValueError):
            e27.PulseSchedule(hold_frames=0)
        with pytest.raises(ValueError):
            e27.PulseSchedule(hold_frames=1, active_frames=-1)


# ---------------------------------------------------------------------------
# 8. the variants genuinely differ, in audio as well as in registers
# ---------------------------------------------------------------------------
class TestVariantDifferences:
    def test_the_buffers_are_pairwise_different_for_the_phrases(
        self, raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        for score in ("phrase", "phrase_low"):
            for left in e27.VARIANT_ORDER:
                for right in e27.VARIANT_ORDER:
                    if left >= right:
                        continue
                    assert not np.array_equal(raw[(left, score)], raw[(right, score)]), (
                        score, left, right
                    )

    def test_c4_is_identical_to_c1_on_the_single_note(
        self, raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """A documented consequence of the parameterisation, not an accident."""
        assert np.array_equal(raw[("C4", "note")], raw[("C1", "note")])

    def test_the_divider_switch_counts_match_the_schedules(
        self, result: Dict[str, Any]
    ) -> None:
        counts = {(row["variant"], row["score"]): row["divider_switches"] for row in result["rows"]}
        assert counts[("C1", "note")] == 47
        assert counts[("C2", "note")] == 11
        assert counts[("C3", "note")] == 8
        assert counts[("C4", "note")] == 47
        assert counts[("C1", "phrase")] == 79
        assert counts[("C4", "phrase")] == 41

    def test_c3_settles_after_the_pulse(
        self, raw: Dict[Tuple[str, str], np.ndarray], streams: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """After frame 8 C3's divider stops moving, so its tail is not C1's tail."""
        frames = streams[("C3", "note")]
        assert set(int(v) for v in frames[8:, 0]) == {e26.note_divider(69)}
        onset = int(e27.SAMPLE_RATE * 8 / e27.FRAME_RATE_HZ)
        assert not np.array_equal(raw[("C3", "note")][onset:], raw[("C1", "note")][onset:])

    def test_no_variant_is_silent(self, raw: Dict[Tuple[str, str], np.ndarray]) -> None:
        for key, buffer in raw.items():
            assert float(np.max(np.abs(buffer))) > 0.5, key

    def test_the_pulse_puts_octave_energy_where_a_constant_divider_has_less(
        self, raw: Dict[Tuple[str, str], np.ndarray]
    ) -> None:
        """Measured against a plain reference: the same generator with no pulse at all."""

        def band(buffer: np.ndarray, low: float, high: float) -> float:
            steady = buffer[e27.SAMPLE_RATE // 10:].astype(np.float64)
            spectrum = np.abs(np.fft.rfft(steady))
            freqs = np.fft.rfftfreq(steady.shape[0], 1.0 / e27.SAMPLE_RATE)
            return float(np.sum(spectrum[(freqs >= low) & (freqs <= high)] ** 2))

        # A schedule that selects no note: same generator, same volume, divider held constant.
        plain_schedule = e27.PulseSchedule(hold_frames=1, active_notes=(-1,))
        plain = e26.render_registers(
            e27.scheduled_stream(e27.SCORES["phrase_low"], plain_schedule)
        )
        # The low phrase's octave-up dividers are 71/60/47, i.e. 440/519/660 Hz, and its own
        # fundamentals are 220/260/330 Hz. The pulse must move energy into the upper band.
        plain_ratio = band(plain, 420.0, 700.0) / band(plain, 200.0, 340.0)
        for variant in e27.VARIANT_ORDER:
            ratio = band(raw[(variant, "phrase_low")], 420.0, 700.0) / band(
                raw[(variant, "phrase_low")], 200.0, 340.0
            )
            assert ratio > plain_ratio, variant



# ---------------------------------------------------------------------------
# 9. level policy — one shared gain, no per-file normalisation
# ---------------------------------------------------------------------------
class TestLevelPolicy:
    def test_the_gain_is_derived_from_the_loudest_raw_render(self, result: Dict[str, Any]) -> None:
        assert result["gain"] == pytest.approx(e27.TARGET_PEAK / result["reference_peak"])
        assert result["reference_peak"] == pytest.approx(
            max(float(np.max(np.abs(buffer))) for buffer in result["raw"].values())
        )

    def test_the_gain_is_experiment_26s_gain(self, result: Dict[str, Any]) -> None:
        """Same generator, same volume, same reference peak, so the files are comparable."""
        assert result["gain"] == pytest.approx(0.45)
        assert e26.TARGET_PEAK == e27.TARGET_PEAK

    def test_nothing_clips(self, result: Dict[str, Any]) -> None:
        for row in result["rows"]:
            assert row["peak_after_gain"] <= e27.TARGET_PEAK + 1e-3, row["file"]

    def test_no_file_is_normalised_on_its_own(self, result: Dict[str, Any]) -> None:
        for row in result["rows"]:
            assert row["peak_after_gain"] == pytest.approx(
                row["raw_peak"] * result["gain"], rel=0.01
            ), row["file"]
            assert row["rms_after_gain"] == pytest.approx(
                row["raw_rms"] * result["gain"], rel=0.02
            ), row["file"]
        assert e27.build_summary(result)["level_policy"]["per_file_normalisation"] is False

    def test_the_summary_records_the_limitations(self, result: Dict[str, Any]) -> None:
        summary = e27.build_summary(result)
        assert summary["limitations"] == list(e27.LIMITATIONS)
        assert any("20 ms" in item for item in summary["limitations"])
        assert any("poly5 gate" in item for item in summary["limitations"])


# ---------------------------------------------------------------------------
# 10. nothing outside the experiment changed
# ---------------------------------------------------------------------------
class TestProductionUntouched:
    def test_no_production_or_experiment_26_file_changes_during_a_render(
        self, tmp_path: Path
    ) -> None:
        before = {name: file_hash(e27.REPO_ROOT / name) for name in UNTOUCHED_FILES}
        e27.render_experiment(tmp_path / "render")
        after = {name: file_hash(e27.REPO_ROOT / name) for name in UNTOUCHED_FILES}
        assert before == after

    def test_the_renderer_and_tables_are_experiment_26s(self) -> None:
        assert e27.e26 is e26
        assert e27.e26.POKEY_DAC is pokey_synth.POKEY_DAC
        assert e27.e26.render_registers is e26.render_registers
        assert e27.e26.to_int16 is e26.to_int16

    def test_the_generator_and_volume_are_experiment_26s_constants(self) -> None:
        assert e27.e26.C_GENERATOR == 0x40
        assert e27.e26.C_SUSTAIN_VOL == 12
        assert e27.e26.plucked_volume_shape(20) == e26.plucked_volume_shape(20)

    def test_the_experiment_is_not_wired_into_the_cli(self) -> None:
        names = sorted(cli_module.cli.commands)
        assert not any("experiment27" in name for name in names)
        assert not any("octave_pulse" in name for name in names)
        assert not any("timbre" in name for name in names)

    def test_no_production_module_imports_the_experiment(self) -> None:
        """No production module may depend on an experiment.

        Experiment 28 reuses this module's C1 schedule on purpose and Experiment 29 reuses its variant C
        through Experiment 28, so experiment modules are excluded by name — that is an
        experiment-to-experiment dependency, not a pipeline one.
        """
        src = e27.REPO_ROOT / "src" / "atari_music"
        experiment_modules = {
            "pokey_octave_pulse_experiment.py",
            "pokey_timbre_experiment.py",
            "pokey_c1_musical_context_experiment.py",
            "pokey_timbre_library_experiment.py",
            "pokey_timbre_ab_experiment.py",
        }
        offenders = []
        for path in sorted(src.rglob("*.py")):
            if path.name in experiment_modules:
                continue
            if "pokey_octave_pulse_experiment" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        assert offenders == []

    def test_the_hardware_model_is_untouched(self) -> None:
        assert e26.pokey_hw.decode_audc(0x40) == e26.pokey_hw.Waveform.POLY5_GATED_POLY4
        assert e26.pokey_hw.decode_audc(0xA0) == e26.pokey_hw.Waveform.PURE_TONE


# ---------------------------------------------------------------------------
# 11. the delivered artefacts, when they are present locally
# ---------------------------------------------------------------------------
requires_delivered = pytest.mark.skipif(
    not (DELIVERED / "summary.json").is_file(),
    reason="experiment27 has not been rendered into experiments/experiment27 on this machine",
)


@requires_delivered
class TestDeliveredArtefacts:
    def test_the_twelve_wavs_the_summary_and_the_note_are_present(self) -> None:
        for variant in e27.VARIANT_ORDER:
            for score in e27.SCORES:
                assert (DELIVERED / e27.wav_filename(variant, score)).is_file()
        assert (DELIVERED / "summary.json").is_file()
        assert (DELIVERED / "README.md").is_file()

    def test_the_delivered_files_are_well_formed(self) -> None:
        for variant in e27.VARIANT_ORDER:
            for score in e27.SCORES:
                params, samples = read_wav(DELIVERED / e27.wav_filename(variant, score))
                assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, 44100)
                frames = e26.total_frames(e27.SCORES[score])
                assert samples.shape[0] == frames * int(
                    round(e27.SAMPLE_RATE / e27.FRAME_RATE_HZ)
                )
                assert int(np.max(np.abs(samples))) > 1000

    def test_the_delivered_set_matches_a_fresh_render_byte_for_byte(self, tmp_path: Path) -> None:
        fresh = e27.render_experiment(tmp_path / "fresh")
        for name, path in fresh["files"].items():
            assert path.read_bytes() == (DELIVERED / name).read_bytes(), name
        assert fresh["summary_path"].read_bytes() == (DELIVERED / "summary.json").read_bytes()
        assert fresh["note_path"].read_bytes() == (DELIVERED / "README.md").read_bytes()

    def test_the_delivered_summary_records_the_parameter_table(self) -> None:
        summary = json.loads((DELIVERED / "summary.json").read_text(encoding="utf-8"))
        assert summary["experiment"] == "experiment27"
        assert summary["baseline"]["variant"] == "C1"
        assert "contrast_stream" in summary["baseline"]["source"]
        assert summary["level_policy"]["per_file_normalisation"] is False
        assert len(summary["files"]) == 12
        assert sorted(summary["variants"]) == ["C1", "C2", "C3", "C4"]
        assert summary["variants"]["C2"]["hold_frames"] == 4
        assert summary["variants"]["C3"]["active_frames"] == 8
        assert summary["variants"]["C4"]["active_notes"] == [0, 2]

    def test_the_listening_note_names_every_file_and_the_limitations(self) -> None:
        note = (DELIVERED / "README.md").read_text(encoding="utf-8")
        for variant in e27.VARIANT_ORDER:
            for score in e27.SCORES:
                assert e27.wav_filename(variant, score) in note
        assert "does not pick a winner" in note
        assert "20 ms" in note
        assert "No file was normalised on its own" in note







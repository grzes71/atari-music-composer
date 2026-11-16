"""Experiment 28 — the C1 octave-pulse timbre inside a real game-tune composition.

These tests check that the A/B is *controlled*, not that B sounds good. Specifically:

* A is the production compiler's own output, unmodified, and both variants come from one compilation;
* B changes channel 3 only, and only its AUDF and AUDC columns — channels 1, 2 and 4 and AUDCTL are
  byte-identical frame for frame;
* the note grid the transform uses is the compiler's own grid: same onsets, same pitches, same
  durations, same total length;
* the register change is the C1 schedule: generator ``$40`` on every sounding lead frame and the
  divider alternating ``N`` / ``N // 2`` every frame, restarting at each note onset;
* the volume nibble is untouched, so articulation is not a confound;
* rendering is deterministic, one shared gain is applied to both files with no per-file
  normalisation, and nothing clips;
* no production file is changed and no production module depends on the experiment.
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
from atari_music import ir
from atari_music import pokey_c1_musical_context_experiment as e28
from atari_music import pokey_octave_pulse_experiment as e27
from atari_music import pokey_timbre_experiment as e26

pytestmark = pytest.mark.experimental

PRODUCTION_FILES: Tuple[str, ...] = (
    "src/atari_music/ir.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/pokey_synth.py",
    "src/atari_music/constants.py",
    "src/atari_music/cli.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/ai/dsl.py",
    "src/atari_music/ai/client.py",
    "src/atari_music/sound_profiles/bank.py",
    "src/atari_music/sound_profiles/binding.py",
    "examples/songs/Vaults-of-Nhyrmeth.dsl",
)

DELIVERED = e28.DEFAULT_OUTPUT_DIR


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_wav(path: Path) -> Tuple[Any, np.ndarray]:
    with wave.open(str(path), "rb") as wf:
        params = wf.getparams()
        raw = wf.readframes(wf.getnframes())
    return params, np.frombuffer(raw, dtype=np.int16)


@pytest.fixture(scope="module")
def song() -> ir.IRSong:
    return e28.load_song()


@pytest.fixture(scope="module")
def streams(song: ir.IRSong) -> Tuple[np.ndarray, np.ndarray]:
    baseline = e28.baseline_stream(song)
    return baseline, e28.apply_c1(baseline, song)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    return e28.render_pair(tmp_path_factory.mktemp("experiment28"))


# ---------------------------------------------------------------------------
# 1. the composition
# ---------------------------------------------------------------------------
class TestComposition:
    def test_the_documented_example_composition_is_used(self) -> None:
        assert e28.DEFAULT_COMPOSITION.is_file()
        assert e28.DEFAULT_COMPOSITION.name == "Vaults-of-Nhyrmeth.dsl"
        text = e28.DEFAULT_COMPOSITION.read_text(encoding="utf-8")
        assert 'TITLE "Vaults of Nhyrmeth"' in text
        assert 'AUTHOR "POKEY Composer"' in text

    def test_it_has_a_melody_a_bass_and_percussion(self, song: ir.IRSong) -> None:
        roles = {inst.role for inst in song.instruments}
        assert {"bass", "melody", "percussion"} <= roles
        channels = {channel for pattern in song.patterns for channel in pattern.tracks}
        assert {1, 3, 4} <= channels

    def test_the_frame_count_is_what_the_compiler_produces(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, _variant = streams
        assert e28.song_total_frames(song) == baseline.shape[0] == 2280
        assert baseline.shape == (2280, 9)

    def test_compilation_is_deterministic(self, song: ir.IRSong) -> None:
        assert np.array_equal(e28.baseline_stream(song), e28.baseline_stream(song))

    def test_a_is_the_production_compilers_output_unmodified(self, song: ir.IRSong) -> None:
        assert np.array_equal(e28.baseline_stream(song), np.asarray(ir.compile_ir_to_pokey_frames(song)))


# ---------------------------------------------------------------------------
# 2. the note grid is the compiler's own grid
# ---------------------------------------------------------------------------
class TestNoteGrid:
    def test_the_spans_cover_the_whole_stream(self, song: ir.IRSong) -> None:
        spans = e28.channel_note_spans(song, e28.MELODIC_CHANNEL)
        assert spans
        assert all(0 <= span["start"] < span["end"] <= 2280 for span in spans)
        assert all(span["frames"] == span["end"] - span["start"] for span in spans)

    def test_the_spans_are_ordered_and_do_not_overlap(self, song: ir.IRSong) -> None:
        spans = e28.channel_note_spans(song, e28.MELODIC_CHANNEL)
        for previous, current in zip(spans, spans[1:]):
            assert current["start"] >= previous["end"], (previous, current)

    def test_every_note_length_is_a_whole_number_of_rows(self, song: ir.IRSong) -> None:
        for span in e28.channel_note_spans(song, e28.MELODIC_CHANNEL):
            assert span["frames"] % song.frames_per_tick == 0
            assert span["frames"] >= song.frames_per_tick

    def test_the_baseline_divider_equals_the_nominal_divider_for_every_note(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        """The transform's ``N`` is the value the production compiler actually wrote."""
        baseline, _variant = streams
        column = ir.audf_column(e28.MELODIC_CHANNEL)
        for span in e28.channel_note_spans(song, e28.MELODIC_CHANNEL):
            if span["is_rest"]:
                continue
            expected = e26.note_divider(int(span["midi"]))
            values = {int(v) for v in baseline[span["start"]:span["end"], column]}
            assert values == {expected}, (span["index"], span["midi"], values)

    def test_the_baseline_divider_is_constant_inside_a_note(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, _variant = streams
        column = ir.audf_column(e28.MELODIC_CHANNEL)
        for span in e28.channel_note_spans(song, e28.MELODIC_CHANNEL):
            if span["is_rest"]:
                continue
            assert len({int(v) for v in baseline[span["start"]:span["end"], column]}) == 1

    def test_every_sounding_frame_lies_inside_a_non_rest_span(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, _variant = streams
        audc_col = ir.audc_column(e28.MELODIC_CHANNEL)
        sounding = {f for f in range(baseline.shape[0]) if baseline[f, audc_col] & 0x0F}
        covered = set()
        for span in e28.channel_note_spans(song, e28.MELODIC_CHANNEL):
            if not span["is_rest"]:
                covered |= set(range(span["start"], span["end"]))
        assert sounding <= covered
        assert sounding

    def test_the_target_channel_is_the_lead(self, song: ir.IRSong) -> None:
        assert e28.MELODIC_CHANNEL == 3
        lead = next(inst for inst in song.instruments if inst.role == "melody")
        assert lead.name == "Lead"
        assert e28.channel_note_spans(song, e28.MELODIC_CHANNEL)


# ---------------------------------------------------------------------------
# 3. only the intended registers changed
# ---------------------------------------------------------------------------
class TestUnchangedRegisters:
    def test_the_streams_have_the_same_shape(self, streams: Tuple[np.ndarray, np.ndarray]) -> None:
        baseline, variant = streams
        assert baseline.shape == variant.shape == (2280, 9)

    def test_only_audf3_and_audc3_differ(self, streams: Tuple[np.ndarray, np.ndarray]) -> None:
        baseline, variant = streams
        differing = {int(c) for c in np.unique(np.nonzero(baseline != variant)[1])}
        assert differing == {ir.audf_column(3), ir.audc_column(3)} == {4, 5}

    def test_channels_1_2_and_4_are_byte_identical(
        self, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        for channel in (1, 2, 4):
            for column in (ir.audf_column(channel), ir.audc_column(channel)):
                assert np.array_equal(baseline[:, column], variant[:, column]), (channel, column)

    def test_audctl_is_byte_identical(self, streams: Tuple[np.ndarray, np.ndarray]) -> None:
        baseline, variant = streams
        assert np.array_equal(baseline[:, 8], variant[:, 8])
        assert set(int(v) for v in np.unique(baseline[:, 8])) == {0x10}

    def test_exactly_the_sounding_lead_frames_differ(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        """Every sounding lead frame changes (the generator), and no other frame does."""
        baseline, variant = streams
        audc_col = ir.audc_column(3)
        sounding = {f for f in range(baseline.shape[0]) if baseline[f, audc_col] & 0x0F}
        differing = {f for f in range(baseline.shape[0]) if not np.array_equal(baseline[f], variant[f])}
        assert differing == sounding
        assert len(differing) == 2220

    def test_a_rest_is_left_completely_untouched(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        rests = [span for span in e28.channel_note_spans(song, 3) if span["is_rest"]]
        if not rests:
            pytest.skip("this composition has no rests on the lead")
        for span in rests:
            assert np.array_equal(
                baseline[span["start"]:span["end"]], variant[span["start"]:span["end"]]
            ), span["index"]

    def test_the_difference_report_matches_reality(self, streams: Tuple[np.ndarray, np.ndarray]) -> None:
        baseline, variant = streams
        report = e28.stream_differences(baseline, variant)
        assert report["same_shape"] is True
        assert report["frames"] == 2280
        assert report["columns_differing"] == [4, 5]
        assert report["frames_differing"] == 2220
        assert report["frames_differing_per_column"]["4"] > 0
        assert report["frames_differing_per_column"]["5"] == 2220
        for column in ("0", "1", "2", "3", "6", "7", "8"):
            assert report["frames_differing_per_column"][column] == 0, column


# ---------------------------------------------------------------------------
# 4. the change is the C1 schedule, and the volume is untouched
# ---------------------------------------------------------------------------
class TestC1Schedule:
    def test_the_generator_is_c1s_on_every_changed_frame(
        self, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        audc_col = ir.audc_column(3)
        changed = [f for f in range(baseline.shape[0]) if baseline[f, audc_col] != variant[f, audc_col]]
        assert changed
        for frame in changed:
            assert int(variant[frame, audc_col]) & 0xE0 == e26.C_GENERATOR & 0xE0 == 0x40, frame
            assert int(baseline[frame, audc_col]) & 0xE0 == 0xA0, frame

    def test_the_volume_nibble_is_never_changed(self, streams: Tuple[np.ndarray, np.ndarray]) -> None:
        """Articulation is held fixed, so the A/B difference is timbre and not dynamics."""
        baseline, variant = streams
        audc_col = ir.audc_column(3)
        assert np.array_equal(baseline[:, audc_col] & 0x0F, variant[:, audc_col] & 0x0F)

    def test_the_divider_alternates_n_and_n_over_two_every_frame(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        column = ir.audf_column(3)
        schedule = e27.SCHEDULES["C1"]
        for span in e28.channel_note_spans(song, 3):
            if span["is_rest"]:
                continue
            nominal = e26.note_divider(int(span["midi"]))
            upper = e26.octave_divider(nominal)
            for offset in range(span["frames"]):
                frame = span["start"] + offset
                expected = schedule.divider_for_frame(nominal, upper, offset, span["index"])
                assert int(variant[frame, column]) == expected, (span["index"], offset)

    def test_the_alternation_restarts_at_every_note_onset(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        """Note 2 onwards begins on the nominal divider, not wherever the previous note stopped."""
        baseline, variant = streams
        column = ir.audf_column(3)
        for span in e28.channel_note_spans(song, 3):
            if span["is_rest"]:
                continue
            assert int(variant[span["start"], column]) == e26.note_divider(int(span["midi"]))

    def test_the_octave_value_is_the_nominal_divider_halved(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        column = ir.audf_column(3)
        for span in e28.channel_note_spans(song, 3):
            if span["is_rest"]:
                continue
            nominal = e26.note_divider(int(span["midi"]))
            values = {int(v) for v in variant[span["start"]:span["end"], column]}
            assert values <= {nominal, nominal // 2}, (span["index"], values)
            if span["frames"] >= 2:
                assert values == {nominal, nominal // 2}, (span["index"], values)

    def test_silent_frames_keep_the_baseline_registers(
        self, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        audf_col, audc_col = ir.audf_column(3), ir.audc_column(3)
        for frame in range(baseline.shape[0]):
            if baseline[frame, audc_col] & 0x0F == 0:
                assert baseline[frame, audf_col] == variant[frame, audf_col], frame
                assert baseline[frame, audc_col] == variant[frame, audc_col], frame

    def test_the_effect_reuses_experiment_27s_schedule_object(self) -> None:
        """The alternation is not re-implemented here: it is Experiment 27's own schedule."""
        assert e27.SCHEDULES["C1"].hold_frames == 1
        assert e27.SCHEDULES["C1"].active_frames is None
        assert e27.SCHEDULES["C1"].active_notes == ()
        assert e27.SCHEDULES["C1"].alternation_hz == 25.0
        assert e26.C_GENERATOR == 0x40

    def test_the_octave_divider_is_experiment_27s(self) -> None:
        for nominal in (35, 47, 53, 71, 107, 120):
            assert e26.octave_divider(nominal) == nominal // 2

    def test_every_register_value_stays_encodable(self, streams: Tuple[np.ndarray, np.ndarray]) -> None:
        baseline, variant = streams
        assert variant.dtype == np.uint8
        for frame in range(variant.shape[0]):
            assert int(variant[frame, ir.audf_column(3)]) <= e26.pokey_hw.AUDF_TRACKER_MAX


# ---------------------------------------------------------------------------
# 5. determinism and the delivered audio
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_the_transform_is_deterministic(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, variant = streams
        assert np.array_equal(e28.apply_c1(baseline, song), variant)

    def test_the_transform_does_not_mutate_its_input(
        self, song: ir.IRSong, streams: Tuple[np.ndarray, np.ndarray]
    ) -> None:
        baseline, _variant = streams
        original = baseline.copy()
        e28.apply_c1(baseline, song)
        assert np.array_equal(baseline, original)

    def test_two_renders_produce_byte_identical_files(self, tmp_path: Path) -> None:
        left = e28.render_pair(tmp_path / "left")
        right = e28.render_pair(tmp_path / "right")
        for name in (e28.BASELINE_WAV, e28.C1_WAV):
            assert left["files"][name].read_bytes() == right["files"][name].read_bytes(), name
        assert left["summary_path"].read_bytes() == right["summary_path"].read_bytes()
        assert left["note_path"].read_bytes() == right["note_path"].read_bytes()

    def test_the_summary_is_deterministic(self, tmp_path: Path) -> None:
        left = e28.render_pair(tmp_path / "a")
        right = e28.render_pair(tmp_path / "b")
        assert e28.build_summary(left) == e28.build_summary(right)


class TestAudio:
    def test_both_files_exist_with_the_expected_names(self, rendered: Dict[str, Any]) -> None:
        assert set(rendered["files"]) == {e28.BASELINE_WAV, e28.C1_WAV}
        assert (rendered["output_dir"] / "summary.json").is_file()
        assert (rendered["output_dir"] / "README.md").is_file()

    def test_both_files_are_16_bit_mono_pcm_at_44100(self, rendered: Dict[str, Any]) -> None:
        for path in rendered["files"].values():
            params, _samples = read_wav(path)
            assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, 44100)

    def test_both_files_have_the_same_duration(self, rendered: Dict[str, Any]) -> None:
        lengths = {read_wav(path)[1].shape[0] for path in rendered["files"].values()}
        assert len(lengths) == 1
        assert lengths.pop() == 2280 * int(round(e28.SAMPLE_RATE / e28.FRAME_RATE_HZ))

    def test_the_two_files_differ(self, rendered: Dict[str, Any]) -> None:
        a = (rendered["output_dir"] / e28.BASELINE_WAV).read_bytes()
        b = (rendered["output_dir"] / e28.C1_WAV).read_bytes()
        assert a != b
        _params, samples_a = read_wav(rendered["files"][e28.BASELINE_WAV])
        _params, samples_b = read_wav(rendered["files"][e28.C1_WAV])
        assert not np.array_equal(samples_a, samples_b)
        assert np.count_nonzero(samples_a != samples_b) > samples_a.shape[0] // 2

    def test_one_shared_gain_is_applied_to_both(self, rendered: Dict[str, Any]) -> None:
        summary = e28.build_summary(rendered)
        assert summary["level_policy"]["per_file_normalisation"] is False
        assert rendered["gain"] == pytest.approx(e28.TARGET_PEAK / rendered["reference_peak"])
        for row in summary["measurements"]:
            assert row["peak_after_gain"] == pytest.approx(
                row["raw_peak"] * rendered["gain"], rel=0.01
            ), row["file"]

    def test_nothing_clips(self, rendered: Dict[str, Any]) -> None:
        summary = e28.build_summary(rendered)
        for row in summary["measurements"]:
            assert row["peak_after_gain"] <= e28.TARGET_PEAK + 1e-3, row["file"]

    def test_the_two_files_are_close_in_loudness(self, rendered: Dict[str, Any]) -> None:
        """A large level gap would make the comparison about loudness rather than timbre."""
        summary = e28.build_summary(rendered)
        a, b = summary["measurements"]
        ratio = a["rms_after_gain"] / b["rms_after_gain"]
        assert 0.9 < ratio < 1.1, (a["rms_after_gain"], b["rms_after_gain"])

    def test_neither_file_is_silent(self, rendered: Dict[str, Any]) -> None:
        for path in rendered["files"].values():
            _params, samples = read_wav(path)
            assert int(np.max(np.abs(samples))) > 1000

    def test_the_summary_records_the_limitations_and_the_volume_policy(
        self, rendered: Dict[str, Any]
    ) -> None:
        summary = e28.build_summary(rendered)
        assert summary["limitations"] == list(e28.LIMITATIONS)
        assert any("poly5 gate" in item for item in summary["limitations"])
        assert "NOT changed" in summary["c1_effect"]["volume"]
        assert summary["differences"]["columns_differing"] == [4, 5]
        assert summary["not_claimed"]


# ---------------------------------------------------------------------------
# 6. nothing outside the experiment changed
# ---------------------------------------------------------------------------
class TestProductionUntouched:
    def test_a_render_changes_no_production_file(self, tmp_path: Path) -> None:
        before = {name: file_hash(e28.REPO_ROOT / name) for name in PRODUCTION_FILES}
        e28.render_pair(tmp_path / "render")
        after = {name: file_hash(e28.REPO_ROOT / name) for name in PRODUCTION_FILES}
        assert before == after

    def test_the_renderer_and_tables_are_experiment_26s(self) -> None:
        assert e28.e26 is e26
        assert e28.e26.render_registers is e26.render_registers
        assert e28.e26.to_int16 is e26.to_int16
        assert e28.e26.write_wav is e26.write_wav
        assert e28.e26.note_divider is e26.note_divider
        assert e28.e26.octave_divider is e26.octave_divider

    def test_the_experiment_is_not_wired_into_the_cli(self) -> None:
        names = sorted(cli_module.cli.commands)
        assert not any("experiment28" in name for name in names)
        assert not any("c1" in name for name in names)
        assert not any("timbre" in name for name in names)
        assert not any("octave_pulse" in name for name in names)

    def test_no_production_module_imports_the_experiment(self) -> None:
        src = e28.REPO_ROOT / "src" / "atari_music"
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
            text = path.read_text(encoding="utf-8")
            if "pokey_c1_musical_context_experiment" in text:
                offenders.append(path.name)
        assert offenders == []

    def test_c1_is_reachable_only_through_the_versioned_format(self) -> None:
        """The E28 experiment stays outside production; C1 lives in the data format instead.

        This guard used to assert that no production module mentioned the timbre by name, because
        C1 existed only as an experiment. The approved C1 player extension deliberately changes
        that: C1 is now a descriptor in the song data format
        (``pokey_hw.MODULATION_OCTAVE_PULSE``) that ``ir.py``, ``mads_exporter.py`` and
        ``player.asm`` realize. What must still hold -- and is what this guard now checks -- is
        that no production module reaches the *experiment*: the experiment modules are never
        imported, and nothing in production is named after them.
        """
        src = e28.REPO_ROOT / "src" / "atari_music"
        experiment_modules = (
            "pokey_c1_musical_context_experiment",
            "pokey_octave_pulse_experiment",
            "pokey_timbre_experiment",
            "pokey_timbre_library_experiment",
            "pokey_timbre_ab_experiment",
        )
        offenders = []
        for path in sorted(src.rglob("*.py")):
            if path.name in {f"{name}.py" for name in experiment_modules}:
                continue
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in experiment_modules):
                offenders.append(path.name)
        assert offenders == []

        # The production side of C1 is the format's own descriptor, not a private spelling of it.
        hardware = (src / "pokey_hw.py").read_text(encoding="utf-8")
        assert "MODULATION_OCTAVE_PULSE = 1" in hardware
        assert "MODULATION_NONE = 0" in hardware

    def test_the_composition_document_is_not_modified(self) -> None:
        text = e28.DEFAULT_COMPOSITION.read_text(encoding="utf-8")
        assert 'TITLE "Vaults of Nhyrmeth"' in text
        assert "[PATTERN A3 length=64]" in text


# ---------------------------------------------------------------------------
# 7. the delivered artefacts, when they are present locally
# ---------------------------------------------------------------------------
requires_delivered = pytest.mark.skipif(
    not (DELIVERED / "summary.json").is_file(),
    reason="experiment28 has not been rendered into experiments/experiment28 on this machine",
)


@requires_delivered
class TestDeliveredArtefacts:
    def test_the_required_files_are_present(self) -> None:
        for name in (e28.BASELINE_WAV, e28.C1_WAV, "README.md", "summary.json"):
            assert (DELIVERED / name).is_file(), name

    def test_the_delivered_files_are_well_formed(self) -> None:
        for name in (e28.BASELINE_WAV, e28.C1_WAV):
            params, samples = read_wav(DELIVERED / name)
            assert (params.nchannels, params.sampwidth, params.framerate) == (1, 2, 44100)
            assert samples.shape[0] == 2280 * int(round(e28.SAMPLE_RATE / e28.FRAME_RATE_HZ))
            assert int(np.max(np.abs(samples))) > 1000

    def test_the_delivered_set_matches_a_fresh_render_byte_for_byte(self, tmp_path: Path) -> None:
        fresh = e28.render_pair(tmp_path / "fresh")
        for name in (e28.BASELINE_WAV, e28.C1_WAV):
            assert (DELIVERED / name).read_bytes() == fresh["files"][name].read_bytes(), name
        assert (DELIVERED / "summary.json").read_bytes() == fresh["summary_path"].read_bytes()
        assert (DELIVERED / "README.md").read_bytes() == fresh["note_path"].read_bytes()

    def test_the_delivered_summary_records_the_control(self) -> None:
        summary = json.loads((DELIVERED / "summary.json").read_text(encoding="utf-8"))
        assert summary["experiment"] == "experiment28"
        assert summary["composition"]["title"] == "Vaults of Nhyrmeth"
        assert summary["target"]["channel"] == 3
        assert summary["differences"]["columns_differing"] == [4, 5]
        assert summary["level_policy"]["per_file_normalisation"] is False
        assert len(summary["measurements"]) == 2

    def test_the_listening_note_names_both_files(self) -> None:
        note = (DELIVERED / "README.md").read_text(encoding="utf-8")
        assert e28.BASELINE_WAV in note
        assert e28.C1_WAV in note
        assert "does not show" in note






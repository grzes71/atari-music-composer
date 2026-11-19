"""Regression and POKEY hardware verification tests for ``lead_c1_octave_pulse``."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
import wave

import numpy as np
import pytest

from atari_music import frame_simulator, ir, pokey_hw, pokey_synth
from atari_music.constants import DISTORTION_PURE_TONE
from atari_music.instruments import load_instrument_catalog
from atari_music.ir import IREnvelope, IRInstrument, IRNote, IRPattern, IRSong
from atari_music.mads_exporter import ModulationNotExpressibleError, export_mads_asm
from atari_music.studio import (
    ExportService,
    InstrumentService,
    StudioArrangementConfig,
    XexExportOptions,
    load_studio_composition,
)
from tests.conftest import require_local_artifact
from tests.test_pokey_hardware_synthesis import _render_via_asap
from tests.test_xex_e2e_py65 import run_xex_in_py65

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS_EXE = REPO_ROOT / "tools" / "mads" / "mads.exe"
ASAPCONV_EXE = REPO_ROOT / "tools" / "asap_all" / "asapconv.exe"
PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"

SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 882


def _build_c1_solo_song(
    midis: Sequence[int],
    *,
    duration_ticks: int = 8,
    frames_per_tick: int = 4,
    channel: int = 1,
) -> IRSong:
    """Build a minimal deterministic single-instrument song using ``lead_c1_octave_pulse``."""
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("lead_c1_octave_pulse")
    inst = IRInstrument.from_catalog_profile(0, prof, beh)
    notes = [
        IRNote(
            pitch=ir.midi_to_note_name(m),
            midi_pitch=m,
            duration=duration_ticks,
            volume=15,
            instrument_id=0,
            channel_role="melody",
        )
        for m in midis
    ]
    total_rows = duration_ticks * len(midis)
    return IRSong(
        title="C1 Octave Pulse Solo",
        tempo_bpm=125,
        frames_per_tick=frames_per_tick,
        instruments=[inst],
        patterns=[IRPattern(id=0, name="Solo", rows=total_rows, tracks={channel: notes})],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )


def _measure_note_spectrum(
    samples: np.ndarray, target_hz: float, sr: int = SAMPLE_RATE
) -> Tuple[float, float, float, float, float]:
    """Return ``(rms, dom_hz, harm_ratio, min_oct_cents, oct2_ratio)`` for one note slice."""
    x = samples.astype(np.float64) - float(np.mean(samples))
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 1e-6:
        return 0.0, 0.0, 0.0, 9999.0, 0.0

    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec[:3] = 0.0
    dom_hz = float(freqs[int(np.argmax(spec))])

    power = spec[3:] ** 2 + 1e-18
    total_power = float(np.sum(power))
    f_bins = freqs[3:]

    harm_power = 0.0
    for h in range(1, 9):
        hf = target_hz * h
        bw = max(32.0, hf * 0.04)
        harm_power += float(np.sum(power[np.abs(f_bins - hf) <= bw]))
    harm_ratio = harm_power / total_power

    oct2_bw = max(32.0, (2.0 * target_hz) * 0.04)
    oct2_power = float(np.sum(power[np.abs(f_bins - 2.0 * target_hz) <= oct2_bw]))
    oct2_ratio = oct2_power / total_power

    min_oct_cents = min(
        abs(1200.0 * math.log2(dom_hz / (target_hz * mult))) for mult in (1.0, 2.0)
    )
    return rms, dom_hz, harm_ratio, min_oct_cents, oct2_ratio


def test_lead_c1_octave_pulse_catalog_definition_uses_pure_tone_and_preserves_contract() -> None:
    """Catalog profile must use $A0 pure tone on 8-bit 64 kHz hardware with C1 octave pulse."""
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("lead_c1_octave_pulse")

    assert prof.base_distortion == DISTORTION_PURE_TONE
    assert prof.waveform_family == "pure"
    assert prof.hardware_constraints.divider_mode == "8bit"
    assert prof.hardware_constraints.preferred_clock_hz == "64khz"
    assert prof.hardware_constraints.required_audctl_bits == 0
    assert prof.hardware_constraints.channels_allowed == (1, 2, 3, 4)
    assert prof.hardware_constraints.midi_range == (48, 91)

    assert beh is not None
    assert beh.behavior_id == "beh_octave_pulse_v1"
    assert beh.modulation_mode == "octave_pulse"
    assert beh.required_runtime_tier == "core_v1"


def test_lead_c1_octave_pulse_ch1_ch2_register_sequence_and_xex_v2_py65_parity(
    tmp_path: Path,
) -> None:
    """Verify CH1/CH2 8-bit registers, rests, transitions, 16-bit refusal, and XEX v2 py65 parity."""
    require_local_artifact(MADS_EXE)
    require_local_artifact(PLAYER_ASM)

    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("lead_c1_octave_pulse")
    c1_inst = IRInstrument.from_catalog_profile(0, prof, beh)

    ch1_midis = [60, 64, 67, 72]
    ch2_spec: List[int | None] = [67, None, 69, 72]
    dur_ticks = 8
    fpt = 4
    frames_per_event = dur_ticks * fpt
    num_frames = frames_per_event * len(ch1_midis)

    ch1_notes = [
        IRNote(
            pitch=ir.midi_to_note_name(m),
            midi_pitch=m,
            duration=dur_ticks,
            volume=15,
            instrument_id=0,
            channel_role="melody",
        )
        for m in ch1_midis
    ]
    ch2_notes = [
        IRNote(is_rest=True, duration=dur_ticks, volume=0, instrument_id=0, channel_role="melody")
        if m is None
        else IRNote(
            pitch=ir.midi_to_note_name(m),
            midi_pitch=m,
            duration=dur_ticks,
            volume=15,
            instrument_id=0,
            channel_role="melody",
        )
        for m in ch2_spec
    ]

    song = IRSong(
        title="C1 CH1+CH2 Independent",
        tempo_bpm=125,
        frames_per_tick=fpt,
        instruments=[c1_inst],
        patterns=[IRPattern(id=0, name="P0", rows=32, tracks={1: ch1_notes, 2: ch2_notes})],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )

    ir_path = tmp_path / "c1_ch12.json"
    song.to_json_file(ir_path)
    state = load_studio_composition(ir_path)
    exporter = ExportService(InstrumentService())
    xex_path = tmp_path / "c1_ch12.xex"
    export_res = exporter.export_xex(
        state,
        StudioArrangementConfig(target_backend="xex_v2", player_version="v2"),
        XexExportOptions(
            output_path=xex_path,
            keep_asm=True,
            mads_bin=MADS_EXE,
            player_asm=PLAYER_ASM,
        ),
    )
    assert export_res.format_version == 2

    run = run_xex_in_py65(xex_path, num_frames=num_frames)
    assert run.illegal_writes == []

    v1_frames = ir.compile_ir_to_pokey_frames(song)
    v2_sim_frames = frame_simulator.simulate_ir_song_frames(song, num_frames=num_frames, format_version=2)
    assert np.array_equal(run.pokey_frames, v2_sim_frames)
    assert np.array_equal(run.pokey_frames, v1_frames)

    # AUDCTL ($D208) remains $00 across every frame in 8-bit mode.
    assert set(int(v) for v in run.pokey_frames[:, 8]) == {0x00}

    expected_vols = pokey_hw.player_envelope_volumes(
        frames_per_event,
        fpt,
        15,
        prof.envelope.attack_frames,
        prof.envelope.decay_frames,
        prof.envelope.sustain_vol,
        prof.envelope.release_frames,
    )
    assert expected_vols[:5] == [15, 14, 12, 10, 8]
    assert expected_vols[-2:] == [7, 6]

    # Verify CH1 notes: $A0 distortion, exact ADSR, and N <-> N//2 resetting cleanly per note.
    for note_idx, midi in enumerate(ch1_midis):
        nom = pokey_hw.clamp_audf_for_tracker(
            pokey_hw.audf_from_hz_8bit(ir.midi_pitch_to_frequency(midi))
        )
        base_f = note_idx * frames_per_event
        for f_off in range(frames_per_event):
            f = base_f + f_off
            assert int(run.pokey_frames[f, 0]) == (nom if f_off % 2 == 0 else nom // 2)
            assert int(run.pokey_frames[f, 1]) == (DISTORTION_PURE_TONE | expected_vols[f_off])

    # Verify CH2 notes + rest isolation (frames 32..63 completely silent, post-rest restarts on N).
    for ev_idx, maybe_midi in enumerate(ch2_spec):
        base_f = ev_idx * frames_per_event
        if maybe_midi is None:
            for f_off in range(frames_per_event):
                f = base_f + f_off
                assert int(run.pokey_frames[f, 2]) == 0x00
                assert int(run.pokey_frames[f, 3]) == 0x00
        else:
            nom = pokey_hw.clamp_audf_for_tracker(
                pokey_hw.audf_from_hz_8bit(ir.midi_pitch_to_frequency(maybe_midi))
            )
            for f_off in range(frames_per_event):
                f = base_f + f_off
                assert int(run.pokey_frames[f, 2]) == (nom if f_off % 2 == 0 else nom // 2)
                assert int(run.pokey_frames[f, 3]) == (DISTORTION_PURE_TONE | expected_vols[f_off])

    # Verify joined 16-bit CH1+CH2 pair with MOD_OCTAVE_PULSE is explicitly refused in XEX v2.
    bad_16bit_song = song.model_copy(update={"uses_16bit_bass": True})
    with pytest.raises(ModulationNotExpressibleError):
        export_mads_asm(bad_16bit_song, format_version=2)


def test_lead_c1_octave_pulse_wav_preview_tracks_melodic_pitch_without_noise(
    tmp_path: Path,
) -> None:
    """Verify pokey_synth WAV preview renders clear melodic pitch and preserves 2x octave energy."""
    test_midis = [60, 64, 67, 69, 72, 84]  # includes C5 (N//2=30) & C6 (N=29, N//2=14)
    dur_ticks = 8
    fpt = 4
    frames_per_note = dur_ticks * fpt
    num_frames = frames_per_note * len(test_midis)

    song = _build_c1_solo_song(test_midis, duration_ticks=dur_ticks, frames_per_tick=fpt)
    frames = frame_simulator.simulate_ir_song_frames(song, num_frames=num_frames, format_version=2)
    wav_path = tmp_path / "c1_preview.wav"
    pokey_synth.render_pokey_to_wav(frames, wav_path, sample_rate=SAMPLE_RATE)

    with wave.open(str(wav_path), "rb") as wf:
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

    for idx, midi in enumerate(test_midis):
        f0 = idx * frames_per_note
        f1 = f0 + frames_per_note
        seg = pcm[(f0 + 4) * SAMPLES_PER_FRAME : (f1 - 2) * SAMPLES_PER_FRAME]
        target_hz = float(ir.midi_pitch_to_frequency(midi))
        rms, dom_hz, harm_ratio, min_oct_cents, _ = _measure_note_spectrum(seg, target_hz)

        assert rms > 1000.0, f"MIDI {midi} stalled/silent: rms={rms:.1f}"
        assert harm_ratio >= 0.45, (
            f"MIDI {midi} ({target_hz:.1f}Hz) noisy/unpitched: harm_ratio={harm_ratio:.3f}, dom={dom_hz:.1f}Hz"
        )
        assert min_oct_cents <= 150.0, (
            f"MIDI {midi} ({target_hz:.1f}Hz) off-pitch: dom={dom_hz:.1f}Hz ({min_oct_cents:.1f}c from f0/2f0)"
        )

    # Compare A4 (MIDI 69) against static square baseline ``lead_pure_sustain``:
    # C1 octave pulse must contribute >= 15% energy near 2*f0 (880 Hz), unlike pure square (< 2%).
    cat = load_instrument_catalog()
    pure_prof, pure_beh = cat.resolve_profile_behavior("lead_pure_sustain")
    pure_song = IRSong(
        title="Baseline Pure A4",
        tempo_bpm=125,
        frames_per_tick=fpt,
        instruments=[IRInstrument.from_catalog_profile(0, pure_prof, pure_beh)],
        patterns=[
            IRPattern(
                id=0,
                name="P0",
                rows=dur_ticks,
                tracks={
                    1: [
                        IRNote(
                            pitch="A-4",
                            midi_pitch=69,
                            duration=dur_ticks,
                            volume=15,
                            instrument_id=0,
                            channel_role="melody",
                        )
                    ]
                },
            )
        ],
        sequence=[0],
        uses_16bit_bass=False,
    )
    a4_c1_samples = pokey_synth.render_pokey_samples(
        frames[3 * frames_per_note : 4 * frames_per_note], sample_rate=SAMPLE_RATE
    )
    a4_pure_samples = pokey_synth.render_pokey_samples(
        ir.compile_ir_to_pokey_frames(pure_song), sample_rate=SAMPLE_RATE
    )
    _, _, _, _, c1_oct2 = _measure_note_spectrum(
        a4_c1_samples[6 * SAMPLES_PER_FRAME : (frames_per_note - 2) * SAMPLES_PER_FRAME], 440.0
    )
    _, _, _, _, pure_oct2 = _measure_note_spectrum(
        a4_pure_samples[6 * SAMPLES_PER_FRAME : (frames_per_note - 2) * SAMPLES_PER_FRAME], 440.0
    )
    assert c1_oct2 >= 0.15
    assert pure_oct2 < 0.02


@pytest.mark.skipif(
    not (MADS_EXE.is_file() and ASAPCONV_EXE.is_file()),
    reason="MADS or ASAP tools not installed in tools/",
)
def test_lead_c1_octave_pulse_asap_real_pokey_melodic_pitch_verification() -> None:
    """Verify real POKEY silicon emulation via ASAP 8.0.0 produces clean melodic C1 playback."""
    test_midis = [60, 64, 67, 69, 72, 84]
    dur_ticks = 8
    fpt = 4
    frames_per_note = dur_ticks * fpt
    num_frames = frames_per_note * len(test_midis)

    song = _build_c1_solo_song(test_midis, duration_ticks=dur_ticks, frames_per_tick=fpt)
    frames = frame_simulator.simulate_ir_song_frames(song, num_frames=num_frames, format_version=2)
    asap_pcm = _render_via_asap(frames)

    for idx, midi in enumerate(test_midis):
        f0 = idx * frames_per_note
        f1 = f0 + frames_per_note
        seg = asap_pcm[(f0 + 4) * SAMPLES_PER_FRAME : (f1 - 2) * SAMPLES_PER_FRAME]
        target_hz = float(ir.midi_pitch_to_frequency(midi))
        rms, dom_hz, harm_ratio, min_oct_cents, _ = _measure_note_spectrum(seg, target_hz)

        assert rms > 1000.0, f"ASAP MIDI {midi} silent: rms={rms:.1f}"
        assert harm_ratio >= 0.50, (
            f"ASAP MIDI {midi} ({target_hz:.1f}Hz) noisy: harm_ratio={harm_ratio:.3f}, dom={dom_hz:.1f}Hz"
        )
        assert min_oct_cents <= 120.0, (
            f"ASAP MIDI {midi} ({target_hz:.1f}Hz) off-pitch: dom={dom_hz:.1f}Hz ({min_oct_cents:.1f}c)"
        )

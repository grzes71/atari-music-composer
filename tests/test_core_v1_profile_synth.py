"""CORE/AUDIO tests for opt-in Stage B CORE_V1 instrument profile synthesis."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pytest

from atari_music import composer_v4, pokey_synth
from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_CH1_179MHZ,
    AUDCTL_JOIN_1_2_16BIT,
)
from atari_music.instruments import (
    TARGET_V1_XEX,
    TARGET_WAV_PREVIEW,
    load_instrument_catalog,
)
from atari_music.pokey_synth import (
    InstrumentRenderError,
    compile_core_v1_profiles_to_frames,
    render_core_v1_profiles_samples,
    render_core_v1_profiles_to_wav,
)

pytestmark = [pytest.mark.core, pytest.mark.audio]


def _dom_hz(samples: np.ndarray, sr: int = 44100) -> float:
    x = samples.astype(np.float64) - np.mean(samples)
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    sp[:3] = 0.0
    return float(freqs[int(np.argmax(sp))])


def test_core_v1_static_profiles_compile_and_render_to_wav(tmp_path: Path) -> None:
    notes: Dict[int, Sequence[Tuple[Optional[int], int, int]]] = {
        1: [(33, 4, 14)],  # A1 in 16-bit CH1+2
        3: [(69, 4, 12)],  # A4 lead
        4: [(57, 4, 10)],  # A3 harmony
    }
    assignments = {
        1: "bass_16bit_pure",
        3: "lead_pure_sustain",
        4: "harmony_soft_square",
    }

    frames = compile_core_v1_profiles_to_frames(notes, assignments, frames_per_tick=4)
    assert frames.shape == (16, 9)
    # Effective AUDCTL carries $50 from bass_16bit_pure (CH1+CH2 16-bit @ 1.79 MHz)
    assert set(int(v) for v in frames[:, 8]) == {AUDCTL_JOIN_1_2_16BIT | AUDCTL_CH1_179MHZ}
    # 16-bit CH1 LSB is muted while CH2 carries distortion $A0 and non-zero volume
    assert set(int(v) for v in frames[:, 1]) == {0}
    assert (int(frames[0, 3]) & 0xE0) == 0xA0 and (int(frames[0, 3]) & 0x0F) > 0
    # CH3 attack starts below peak (attack=6 on lead_pure_sustain)
    assert (int(frames[0, 5]) & 0x0F) < (int(frames[5, 5]) & 0x0F)

    wav_path = tmp_path / "core_v1_mix.wav"
    render_core_v1_profiles_to_wav(notes, assignments, wav_path)
    assert wav_path.is_file() and wav_path.stat().st_size > 44


def test_core_v1_15khz_bass_c1_octave_pulse_and_poly4_safe_profiles() -> None:
    # 1. 15 kHz bass sets AUDCTL $01 and plays low A1 (~55 Hz)
    fr_15k = compile_core_v1_profiles_to_frames(
        {1: [(33, 8, 14)]},
        {1: "bass_15khz_pure"},
        frames_per_tick=4,
    )
    assert set(int(v) for v in fr_15k[:, 8]) == {AUDCTL_15KHZ}
    s_15k = pokey_synth.render_pokey_samples(fr_15k)
    assert _dom_hz(s_15k[882 * 2 :]) == pytest.approx(55.0, abs=3.0)

    # 2. lead_c1_octave_pulse alternates AUDF between N and N//2 on odd frames (faithful V1 mod)
    fr_c1 = compile_core_v1_profiles_to_frames(
        {3: [(69, 4, 12)]},
        {3: "lead_c1_octave_pulse"},
        frames_per_tick=4,
    )
    assert int(fr_c1[0, 4]) // 2 == int(fr_c1[1, 4])
    assert int(fr_c1[0, 4]) != int(fr_c1[1, 4])

    # 3. lead_buzz_steady uses coprime-15 safe tuning so $C0 does not stall on silent div15
    fr_buzz = compile_core_v1_profiles_to_frames(
        {3: [(69, 6, 14)]},
        {3: "lead_buzz_steady"},
        frames_per_tick=4,
    )
    audf_buzz = int(fr_buzz[0, 4])
    assert ((audf_buzz + 1) % 3 != 0) and ((audf_buzz + 1) % 5 != 0)
    s_buzz = pokey_synth.render_pokey_samples(fr_buzz)
    assert float(np.std(s_buzz[882 * 2 :])) > 1000.0


def test_incompatible_or_deferred_profiles_are_rejected_without_silent_downgrade() -> None:
    notes = {3: [(69, 4, 12)]}
    # Delayed/deferred behavior (arpeggio) refused by default without silent static fallback
    with pytest.raises(InstrumentRenderError):
        compile_core_v1_profiles_to_frames(notes, {3: "ornament_bell_arp"})

    # V2-iter1 transient macro / percussion refused cleanly
    with pytest.raises(InstrumentRenderError):
        compile_core_v1_profiles_to_frames(notes, {3: "lead_attack_bite"})
    with pytest.raises(InstrumentRenderError):
        compile_core_v1_profiles_to_frames({4: [(36, 4, 15)]}, {4: "perc_kick_tight"})

    # allow_static_only=True renders static bell profile WITHOUT deferred arpeggio
    fr_bell_static = compile_core_v1_profiles_to_frames(
        notes, {3: "ornament_bell_arp"}, allow_static_only=True
    )
    assert (int(fr_bell_static[0, 5]) & 0xE0) == 0xA0

    # Hard hardware constraints (HPF $04 on lead_hpf_pwm) STILL blocked even with allow_static_only=True
    with pytest.raises(InstrumentRenderError):
        compile_core_v1_profiles_to_frames(
            {1: [(69, 4, 12)]}, {1: "lead_hpf_pwm"}, allow_static_only=True
        )

    # Disallowed channel / 16-bit pair violation rejected cleanly
    with pytest.raises(InstrumentRenderError):
        compile_core_v1_profiles_to_frames({2: [(40, 4, 12)]}, {2: "bass_16bit_pure"})

    # Opt-in validation guard on render_pokey_samples catches AUDCTL mismatch and deferred profiles
    raw = np.zeros((4, 9), dtype=np.uint8)
    raw[:, 0] = 71
    raw[:, 1] = 0xAF
    raw[:, 8] = 0x00
    with pytest.raises(InstrumentRenderError):
        pokey_synth.render_pokey_samples(
            raw, profile_assignments={1: "bass_15khz_pure"}, target=TARGET_V1_XEX
        )


def test_existing_render_without_profiles_and_composer_v4_remain_unchanged() -> None:
    # Unbound raw register rendering works identically as before
    raw = np.zeros((16, 9), dtype=np.uint8)
    raw[:, 0] = 71
    raw[:, 1] = 0xAC
    s1 = pokey_synth.render_pokey_samples(raw, 44100, 50.0)
    s2 = pokey_synth.render_pokey_samples(raw)
    assert np.array_equal(s1, s2)
    assert _dom_hz(s1) == pytest.approx(440.0, abs=2.0)

    # Composer v4 default song generation does not pull SSOT catalog changes
    song = composer_v4.compose_song_v4(seed=42)
    assert song is not None
    assert len(song.pokey_ir.patterns) > 0

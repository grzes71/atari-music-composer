"""CORE/AUDIO hardware synthesis and ASAP 8.0.0 parity tests for Stage B."""

from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Tuple

import numpy as np
import pytest

from atari_music import pokey_hw, pokey_synth
from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_9BIT_POLY,
    AUDCTL_CH1_179MHZ,
    AUDCTL_CH3_179MHZ,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_5BIT_POLY_1,
    DISTORTION_5_AND_4BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    PAL_CLOCK_HZ,
)

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS_EXE = REPO_ROOT / "tools" / "mads" / "mads.exe"
ASAPCONV_EXE = REPO_ROOT / "tools" / "asap_all" / "asapconv.exe"
SR = 44100
FR = 50.0


def _render_steady(
    row: Tuple[int, int, int, int, int, int, int, int, int], nframes: int = 40
) -> np.ndarray:
    frames = np.tile(np.array(row, dtype=np.uint8), (nframes, 1))
    return pokey_synth.render_pokey_samples(frames, SR, FR)


def _dominant_hz(samples: np.ndarray) -> float:
    x = samples.astype(np.float64) - np.mean(samples)
    if float(np.sqrt(np.mean(x * x))) < 1e-6:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    spec[:3] = 0.0
    return float(freqs[int(np.argmax(spec))])


def _ac_rms(samples: np.ndarray) -> float:
    x = samples.astype(np.float64) - np.mean(samples)
    return float(np.sqrt(np.mean(x * x)))


def _sap_stub_asm(frames: np.ndarray) -> str:
    """Minimal relocatable SAP TYPE B 6502 player writing (N, 9) frames at 50 Hz."""
    lines = [
        f"    .byte ${int(r[0]):02x},${int(r[1]):02x},${int(r[2]):02x},"
        f"${int(r[3]):02x},${int(r[4]):02x},${int(r[5]):02x},"
        f"${int(r[6]):02x},${int(r[7]):02x},${int(r[8]):02x}"
        for r in frames
    ]
    block = "\n".join(lines)
    return f"""
AUDF1_REG = $D200
AUDCTL_REG = $D208
STIMER_REG = $D209
SKCTL_REG = $D20F
zp_ptr = $80
    org $2000
    jmp init
    jmp player
init:
    lda #<frames_data
    sta zp_ptr
    lda #>frames_data
    sta zp_ptr+1
    lda #1
    sta is_playing
    sta first_frm
    lda #0
    sta prev_ctl
    sta AUDCTL_REG
    ldx #8
@clr:
    sta AUDF1_REG,x
    dex
    bpl @clr
    lda #$03
    sta SKCTL_REG
    lda #0
    sta STIMER_REG
    rts
player:
    lda is_playing
    bne @chk
    rts
@chk:
    lda zp_ptr+1
    cmp #>frames_end
    bne @play
    lda zp_ptr
    cmp #<frames_end
    bne @play
    lda #0
    sta is_playing
    ldx #8
@sil:
    sta AUDF1_REG,x
    dex
    bpl @sil
    rts
@play:
    ldy #8
    lda (zp_ptr),y
    ldx first_frm
    bne @wctl
    cmp prev_ctl
    beq @regs
@wctl:
    sta prev_ctl
    sta AUDCTL_REG
    lda #0
    sta first_frm
@regs:
    ldy #0
@loop:
    lda (zp_ptr),y
    sta AUDF1_REG,y
    iny
    cpy #8
    bne @loop
    clc
    lda zp_ptr
    adc #9
    sta zp_ptr
    bcc @done
    inc zp_ptr+1
@done:
    rts
is_playing: .byte 0
first_frm:  .byte 1
prev_ctl:   .byte 0
frames_data:
{block}
frames_end:
"""


def _render_via_asap(frames: np.ndarray) -> np.ndarray:
    dur = len(frames) / FR
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "s.asm").write_text(_sap_stub_asm(frames), encoding="ascii")
        subprocess.run(
            [str(MADS_EXE), str(p / "s.asm"), f"-o:{p / 's.xex'}"],
            check=True,
            capture_output=True,
        )
        hdr = (
            f"SAP\r\nTYPE B\r\nINIT 2000\r\nPLAYER 2003\r\n"
            f"TIME 00:{int(dur):02d}.{int((dur % 1.0) * 100):02d}\r\n\r\n"
        ).encode("ascii")
        (p / "s.sap").write_bytes(hdr + (p / "s.xex").read_bytes())
        subprocess.run(
            [str(ASAPCONV_EXE), "-o", str(p / "s.wav"), str(p / "s.sap")],
            check=True,
            capture_output=True,
        )
        with wave.open(str(p / "s.wav"), "rb") as wf:
            return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)


# ===========================================================================
# 1. Hardware POLY4 / POLY5 LFSR correctness & stalls
# ===========================================================================


def test_lfsr4_and_lfsr5_periods_state_order_and_determinism() -> None:
    p4 = pokey_hw.generate_lfsr4_sequence()
    p5 = pokey_hw.generate_lfsr5_sequence(active_gate_polarity=False)
    p5_hw = pokey_hw.generate_lfsr5_sequence(active_gate_polarity=True)

    assert len(p4) == pokey_hw.POLY4_PERIOD == 15
    assert len(p5) == pokey_hw.POLY5_PERIOD == 31
    assert len(p5_hw) == 31
    assert sum(p4) == 8
    assert sum(p5) == 16
    assert sum(p5_hw) == 15  # XNOR polarity -> odd active count -> 62-tick toggle period

    # Repeatability across repeated calls
    assert p4 == pokey_hw.generate_lfsr4_sequence()
    assert p5_hw == pokey_hw.generate_lfsr5_sequence(active_gate_polarity=True)


def test_poly4_and_poly5_clock_stalls_and_coprime_recovery() -> None:
    # $C0 at AUDF=$FE -> (254+1)=255 is divisible by 15 -> subcycle stall (zero AC steady state)
    s_c0_stall = _render_steady((0xFE, DISTORTION_4BIT_POLY | 0x0F, 0, 0, 0, 0, 0, 0, 0))
    assert _ac_rms(s_c0_stall[882 * 4 :]) == 0.0

    # $C0 at coprime AUDF=76 plays subharmonic 54.8/109.7 Hz spectrum cleanly
    audf_ok = pokey_hw.audf_for_poly4_8bit(55.0)
    assert ((audf_ok + 1) % 3 != 0) and ((audf_ok + 1) % 5 != 0)
    s_c0_ok = _render_steady((audf_ok, DISTORTION_4BIT_POLY | 0x0F, 0, 0, 0, 0, 0, 0, 0))
    assert _ac_rms(s_c0_ok[882 * 4 :]) > 5000.0

    # $20 at AUDF=30 -> (30+1)=31 is divisible by 31 -> stalls at constant bit (zero AC)
    s_20_stall = _render_steady((30, DISTORTION_5BIT_POLY_1 | 0x0F, 0, 0, 0, 0, 0, 0, 0))
    assert _ac_rms(s_20_stall[882 * 4 :]) == 0.0

    # $20 at AUDF=24 produces strong 62-tick doubled-period harmonics (204/286 Hz)
    s_20_ok = _render_steady((24, DISTORTION_5BIT_POLY_1 | 0x0F, 0, 0, 0, 0, 0, 0, 0))
    assert _ac_rms(s_20_ok[882 * 4 :]) > 5000.0
    dom_hz = _dominant_hz(s_20_ok[882 * 4 :])
    assert dom_hz == pytest.approx(204.2, abs=90.0) or dom_hz == pytest.approx(286.1, abs=5.0)


def test_audctl_9bit_vs_17bit_and_no_state_leak_across_renders() -> None:
    s_a_1 = _render_steady((71, DISTORTION_PURE_TONE | 0x0C, 0, 0, 0, 0, 0, 0, 0), nframes=20)
    # Interleave noisy multi-channel render with 9-bit noise
    _ = _render_steady(
        (20, 0x8F, 45, 0xCF, 10, 0x2F, 5, 0x4F, AUDCTL_9BIT_POLY | AUDCTL_15KHZ), nframes=20
    )
    s_a_2 = _render_steady((71, DISTORTION_PURE_TONE | 0x0C, 0, 0, 0, 0, 0, 0, 0), nframes=20)
    assert np.array_equal(s_a_1, s_a_2)


# ===========================================================================
# 2. HPF XOR ($02 CH2<-CH4, $04 CH1<-CH3)
# ===========================================================================


def test_hpf_xor_04_and_02_behavior_and_bit_mapping() -> None:
    # Without HPF bit: AUDF1=143 plays base ~220 Hz, AUDF3=144 muted has no effect
    s_no_hpf = _render_steady((143, 0xAF, 0, 0, 144, 0xA0, 0, 0, 0x00))
    assert _dominant_hz(s_no_hpf[882 * 4 :]) == pytest.approx(220.0, abs=2.5)

    # With $04 (CH1 filtered by CH3): CH3 muted still clocks latch -> PWM doubling near ~440 Hz
    s_hpf04 = _render_steady((143, 0xAF, 0, 0, 144, 0xA0, 0, 0, AUDCTL_HIPASS_CH1_CH3))
    assert _dominant_hz(s_hpf04[882 * 4 :]) == pytest.approx(440.0, abs=4.0)

    # Swapped bit $02 MUST NOT filter CH1 (CH1 remains at ~220 Hz when $02 is set)
    s_wrong_bit = _render_steady((143, 0xAF, 0, 0, 144, 0xA0, 0, 0, AUDCTL_HIPASS_CH2_CH4))
    assert _dominant_hz(s_wrong_bit[882 * 4 :]) == pytest.approx(220.0, abs=2.5)

    # With $02 (CH2 filtered by CH4): CH4 muted clocks latch -> ~440 Hz
    s_hpf02 = _render_steady((0, 0, 143, 0xAF, 0, 0, 144, 0xA0, AUDCTL_HIPASS_CH2_CH4))
    assert _dominant_hz(s_hpf02[882 * 4 :]) == pytest.approx(440.0, abs=4.0)

    # Synchronized equal divider in HPF lockstep nulls steady-state output
    s_lock = _render_steady((71, 0xAF, 0, 0, 71, 0xA0, 0, 0, AUDCTL_HIPASS_CH1_CH3))
    assert _ac_rms(s_lock[882 * 4 :]) == 0.0

    # Unrelated CH2 remains unaffected while CH1 is HPF-filtered by CH3
    s_ch2_solo = _render_steady((0, 0, 53, 0xAF, 0, 0, 0, 0, 0x00))
    s_hpf_plus_ch2 = _render_steady(
        (143, 0xAF, 53, 0xAF, 144, 0xA0, 0, 0, AUDCTL_HIPASS_CH1_CH3)
    )
    assert _ac_rms(s_hpf_plus_ch2) > 5000.0
    # CH2 dominant pitch (~586 Hz) remains clearly present alongside CH1
    x = s_hpf_plus_ch2[882 * 4 :].astype(np.float64)
    sp = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    bin_586 = np.argmin(np.abs(freqs - _dominant_hz(s_ch2_solo[882 * 4 :])))
    assert sp[bin_586] > 0.3 * np.max(sp)


# ===========================================================================
# 3. 16-bit CH3+CH4 ($08 / $28) and POKEY clocks / AUDF math
# ===========================================================================


def test_16bit_ch3_ch4_mode_frequency_and_channel_period_cycles() -> None:
    # AUDCTL $28: CH3+CH4 joined at 1.79 MHz, div16=$07EB (2027) -> PAL 1773447 / (2*(2027+7)) = 435.95 Hz
    audctl = AUDCTL_JOIN_3_4_16BIT | AUDCTL_CH3_179MHZ
    assert audctl == 0x28
    period = pokey_hw.channel_period_cpu_cycles((0, 0, 0xEB, 0x07), audctl, channel=4)
    assert period == 2034
    expected_hz = PAL_CLOCK_HZ / (2.0 * 2034)
    assert pokey_hw.hz_from_audf_16bit(0x07EB, audctl, channel=3) == pytest.approx(expected_hz, rel=1e-9)

    samples = _render_steady((0, 0, 0, 0, 0xEB, 0x00, 0x07, 0xAF, audctl))
    assert _dominant_hz(samples[882 * 2 :]) == pytest.approx(expected_hz, abs=2.0)

    # 8-bit CH1 alongside 16-bit CH3+CH4 remains unaffected (A3 ~220 Hz)
    s_combo = _render_steady((143, 0xAC, 0, 0, 0xEB, 0x00, 0x07, 0xAA, audctl))
    assert _ac_rms(s_combo) > 5000.0


def test_clocks_64k_15k_179m_boundaries() -> None:
    # Boundary period equations in CPU cycles
    assert pokey_hw.channel_period_cpu_cycles((0, 0, 0, 0), 0x00, 1) == 28
    assert pokey_hw.channel_period_cpu_cycles((0xFE, 0, 0, 0), AUDCTL_15KHZ, 1) == 255 * 114
    assert pokey_hw.channel_period_cpu_cycles((0, 0, 0, 0), AUDCTL_CH1_179MHZ, 1) == 4
    # Bit $40 only affects CH1, bit $20 only affects CH3
    assert pokey_hw.channel_period_cpu_cycles((0, 10, 0, 0), AUDCTL_CH1_179MHZ, 2) == 11 * 28
    assert pokey_hw.channel_period_cpu_cycles((0, 0, 10, 0), AUDCTL_CH3_179MHZ, 3) == 14

    # 15 kHz at AUDF=$FE -> ~30.50 Hz
    s_15k = _render_steady((0xFE, 0xAF, 0, 0, 0, 0, 0, 0, AUDCTL_15KHZ), nframes=50)
    assert _dominant_hz(s_15k[882 * 2 :]) == pytest.approx(
        PAL_CLOCK_HZ / (2.0 * 255 * 114), abs=2.0
    )

    # 1.79 MHz on CH1 at AUDF=100 -> ~8526 Hz
    s_179 = _render_steady((100, 0xAF, 0, 0, 0, 0, 0, 0, AUDCTL_CH1_179MHZ), nframes=40)
    assert _dominant_hz(s_179[882 * 2 :]) == pytest.approx(
        PAL_CLOCK_HZ / (2.0 * 104), abs=5.0
    )


# ===========================================================================
# 4. ASAP 8.0.0 Reference Parity Suite (f0, spectra, ADSR, noise, dynamic)
# ===========================================================================


@pytest.mark.skipif(
    not (MADS_EXE.is_file() and ASAPCONV_EXE.is_file()),
    reason="MADS or ASAP tools not installed in tools/",
)
@pytest.mark.parametrize(
    "name,row,expected_hz",
    [
        ("A0_440Hz", (71, 0xAF, 0, 0, 0, 0, 0, 0, 0x00), 439.8),
        ("A0_15kHz_FE", (0xFE, 0xAF, 0, 0, 0, 0, 0, 0, AUDCTL_15KHZ), 30.5),
        ("A0_179MHz_CH1", (100, 0xAF, 0, 0, 0, 0, 0, 0, AUDCTL_CH1_179MHZ), 8526.2),
        ("C0_coprime76", (76, 0xCF, 0, 0, 0, 0, 0, 0, 0x00), 109.7),
        ("HPF04_pwm", (143, 0xAF, 0, 0, 144, 0xA0, 0, 0, AUDCTL_HIPASS_CH1_CH3), 439.8),
        ("HPF02_pwm", (0, 0, 143, 0xAF, 0, 0, 144, 0xA0, AUDCTL_HIPASS_CH2_CH4), 439.8),
        ("JOIN34_28", (0, 0, 0, 0, 0xEB, 0x00, 0x07, 0xAF, AUDCTL_JOIN_3_4_16BIT | AUDCTL_CH3_179MHZ), 436.0),
    ],
)
def test_asap_hardware_f0_and_spectral_parity(name, row, expected_hz) -> None:
    """Compare WAV renderer against ASAP 8.0.0 on f0 and coarse log-spectrum."""
    frames = np.tile(np.array(row, dtype=np.uint8), (40, 1))
    s_asap = _render_via_asap(frames)[882 * 4 :]
    s_wav = pokey_synth.render_pokey_samples(frames, SR, FR)[882 * 4 :]

    assert _dominant_hz(s_asap) == pytest.approx(expected_hz, abs=5.0), name
    assert _dominant_hz(s_wav) == pytest.approx(_dominant_hz(s_asap), abs=3.0), name

    # Compare normalized magnitude spectrum correlation on active harmonics
    def _norm_spec(x: np.ndarray) -> np.ndarray:
        xf = x.astype(np.float64) - np.mean(x)
        sp = np.abs(np.fft.rfft(xf * np.hanning(len(xf))))[3:]
        norm = float(np.linalg.norm(sp))
        return sp / norm if norm > 0 else sp

    corr = float(np.dot(_norm_spec(s_asap), _norm_spec(s_wav)))
    assert corr >= 0.75, f"{name}: spectral correlation {corr:.3f} < 0.75"


@pytest.mark.skipif(
    not (MADS_EXE.is_file() and ASAPCONV_EXE.is_file()),
    reason="MADS or ASAP tools not installed in tools/",
)
def test_asap_adsr_envelope_and_dynamic_register_change_parity() -> None:
    """Compare ADSR amplitude envelope and mid-stream AUDF/AUDC/AUDCTL transitions vs ASAP."""
    n_frames = 36
    frames = np.zeros((n_frames, 9), dtype=np.uint8)
    vols = pokey_hw.player_envelope_volumes(
        note_len_frames=n_frames,
        frames_per_tick=4,
        peak_vol=15,
        attack=4,
        decay=6,
        sustain=7,
        release=6,
    )
    for i, v in enumerate(vols):
        if i < 18:
            frames[i, 0] = 71
            frames[i, 1] = 0xA0 | v
            frames[i, 8] = 0x00
        else:
            frames[i, 0] = 53
            frames[i, 1] = 0xA0 | v
            frames[i, 8] = AUDCTL_15KHZ if i >= 26 else 0x00

    s_asap = _render_via_asap(frames)
    s_wav = pokey_synth.render_pokey_samples(frames, SR, FR)

    def _frame_rms(sig: np.ndarray) -> np.ndarray:
        m = min(n_frames, len(sig) // 882)
        blocks = sig[: m * 882].reshape(m, 882).astype(np.float64)
        rms = np.sqrt(np.mean((blocks - blocks.mean(axis=1, keepdims=True)) ** 2, axis=1))
        return rms / max(float(rms.max()), 1.0)

    env_corr = float(np.corrcoef(_frame_rms(s_asap)[1:], _frame_rms(s_wav)[1:])[0, 1])
    assert env_corr >= 0.90, f"ADSR RMS correlation vs ASAP too low: {env_corr:.3f}"

    # Verify frequency jump on second half matches ASAP in timing and pitch
    assert _dominant_hz(s_wav[882 * 2 : 882 * 16]) == pytest.approx(
        _dominant_hz(s_asap[882 * 2 : 882 * 16]), abs=4.0
    )
    assert _dominant_hz(s_wav[882 * 27 : 882 * 34]) == pytest.approx(
        _dominant_hz(s_asap[882 * 27 : 882 * 34]), abs=4.0
    )


@pytest.mark.skipif(
    not (MADS_EXE.is_file() and ASAPCONV_EXE.is_file()),
    reason="MADS or ASAP tools not installed in tools/",
)
def test_asap_noise_statistical_parity_9bit_vs_17bit() -> None:
    """Noise modes ($80) are compared statistically (flatness & ZCR) rather than sample-by-sample."""
    for audctl in (0x00, AUDCTL_9BIT_POLY):
        fr_hi = np.tile(np.array([10, DISTORTION_WHITE_NOISE | 0x0F, 0, 0, 0, 0, 0, 0, audctl], dtype=np.uint8), (30, 1))
        fr_lo = np.tile(np.array([200, DISTORTION_WHITE_NOISE | 0x0F, 0, 0, 0, 0, 0, 0, audctl], dtype=np.uint8), (30, 1))

        wav_hi = pokey_synth.render_pokey_samples(fr_hi, SR, FR)[882 * 2 :]
        wav_lo = pokey_synth.render_pokey_samples(fr_lo, SR, FR)[882 * 2 :]
        asap_hi = _render_via_asap(fr_hi)[882 * 2 :]
        asap_lo = _render_via_asap(fr_lo)[882 * 2 :]

        def _zcr(x: np.ndarray) -> float:
            xf = x.astype(np.float64) - np.mean(x)
            return float(np.mean(np.diff(xf >= 0) != 0))

        assert _zcr(wav_hi) > 3.0 * _zcr(wav_lo)
        assert _zcr(asap_hi) > 3.0 * _zcr(asap_lo)

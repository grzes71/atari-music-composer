"""High-Fidelity Software Synthesizer for Atari POKEY Audio.

Simulates POKEY hardware audio generation directly from a stream of 50 Hz register writes:
- 4 independent monophonic channels
- Distortion modes are decoded by :mod:`atari_music.pokey_hw` (hardware truth):
    * $A0 / $E0: pure tone (PURETONE outranks POLY4, so $E0 == $A0)
    * $C0:       poly4 direct (15-step buzz)
    * $20 / $60: poly5-gated pure tone (buzzy; $60 == $20)
    * $40:       poly5-gated poly4
    * $80:       poly9/poly17 direct — the real ungated noise mode
    * $00:       poly5-gated poly9/poly17
- 16-bit channel pairing (CH1 + CH2 joined in AUDCTL)
- 4-bit non-linear POKEY DAC ladder
- Direct export to standard 16-bit PCM WAV at 44.1 kHz
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple
import wave

import numpy as np

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_9BIT_POLY,
    AUDCTL_JOIN_1_2_16BIT,
)

# 4-bit polynomial sequence (15 states)
POLY4_SEQ = np.array([1, 1, 1, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 0], dtype=np.float32)

# 5-bit polynomial sequence (31 states)
POLY5_SEQ = np.array([
    1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1, 0,
    0, 0, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0
], dtype=np.float32)


def _generate_lfsr17_sequence() -> np.ndarray:
    """Generate 17-bit POKEY LFSR maximal-length bitstream (131071 states, poly: 1 + x^12 + x^17)."""
    state = 0x1FFFF
    bits = np.empty(131071, dtype=np.float32)
    for i in range(131071):
        new_bit = ((state >> 16) ^ (state >> 11)) & 1
        bits[i] = 1.0 if new_bit else -1.0
        state = ((state << 1) | new_bit) & 0x1FFFF
    return bits


def _generate_lfsr9_sequence() -> np.ndarray:
    """Generate 9-bit POKEY LFSR maximal-length bitstream (511 states, poly: 1 + x^4 + x^9)."""
    state = 0x1FF
    bits = np.empty(511, dtype=np.float32)
    for i in range(511):
        new_bit = ((state >> 8) ^ (state >> 3)) & 1
        bits[i] = 1.0 if new_bit else -1.0
        state = ((state << 1) | new_bit) & 0x1FF
    return bits


# Precomputed 17-bit and 9-bit LFSR tables for deterministic hardware noise emulation
POLY17_SEQ = _generate_lfsr17_sequence()
POLY9_SEQ = _generate_lfsr9_sequence()

# POKEY Non-Linear Resistor Ladder DAC (16 volume levels 0..15)
POKEY_DAC = np.array([
    0.0000, 0.0075, 0.0170, 0.0290, 0.0460, 0.0680, 0.0980, 0.1370,
    0.1880, 0.2520, 0.3340, 0.4400, 0.5750, 0.7480, 0.8800, 1.0000
], dtype=np.float32)


def render_pokey_to_wav(
    frames: np.ndarray,
    output_wav_path: Path,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
) -> None:
    """Render (total_frames, 9) POKEY register stream into 44.1 kHz 16-bit WAV."""
    samples = render_pokey_samples(frames, sample_rate, frame_rate_hz)
    
    # Write 16-bit mono PCM WAV
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def render_pokey_samples(
    frames: np.ndarray,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
) -> np.ndarray:
    """Render POKEY registers into float audio buffer, filtered and converted to int16."""
    num_frames = frames.shape[0]
    samples_per_frame = int(round(sample_rate / frame_rate_hz))
    total_samples = num_frames * samples_per_frame

    # Channel mix buffer
    audio_mix = np.zeros(total_samples, dtype=np.float32)

    # Phase tracking per channel to maintain phase continuity across frames
    ch_phases = np.zeros(4, dtype=np.float64)
    ch_lfsr_steps = np.zeros(4, dtype=np.float64)

    for f_idx in range(num_frames):
        f_row = frames[f_idx]
        audctl = int(f_row[8])
        s_start = f_idx * samples_per_frame
        s_end = s_start + samples_per_frame
        t_frame = np.arange(samples_per_frame, dtype=np.float64) / sample_rate

        is_16bit_1_2 = bool(audctl & AUDCTL_JOIN_1_2_16BIT)

        for ch in range(4):
            audf = int(f_row[ch * 2])
            audc = int(f_row[ch * 2 + 1])
            vol = audc & 0x0F

            if vol == 0:
                continue

            # Check 16-bit mode for CH1+CH2
            if is_16bit_1_2 and ch == 0:
                # Channel 1 is the divider low byte; audio is output on CH2
                continue

            if is_16bit_1_2 and ch == 1:
                # 16-bit paired mode (shared POKEY model)
                div16 = int(f_row[0]) + (int(f_row[2]) << 8)
                freq = pokey_hw.hz_from_audf_16bit(div16, audctl)
            else:
                # Standard 8-bit mode (shared POKEY model)
                freq = pokey_hw.hz_from_audf_8bit(audf, audctl, channel=ch + 1)

            freq = max(10.0, min(freq, 20000.0))
            amp = POKEY_DAC[vol]

            waveform = pokey_hw.decode_audc(audc)
            if waveform == pokey_hw.Waveform.VOLUME_ONLY:
                continue

            # Generate waveform based on the generator POKEY actually uses
            delta_phase = 2.0 * math.pi * freq * (samples_per_frame / sample_rate)
            phase_seq = ch_phases[ch] + 2.0 * math.pi * freq * t_frame
            ch_phases[ch] = (ch_phases[ch] + delta_phase) % (2.0 * math.pi)
            poly5_idx = (phase_seq * (31.0 / (2.0 * math.pi))).astype(np.int64) % 31
            poly4_idx = (phase_seq * (15.0 / (2.0 * math.pi))).astype(np.int64) % 15
            use_9bit = bool(audctl & AUDCTL_9BIT_POLY)
            noise_seq = POLY9_SEQ if use_9bit else POLY17_SEQ
            poly_len = 511 if use_9bit else 131071

            if waveform == pokey_hw.Waveform.PURE_TONE:
                wave_samples = np.where(np.sin(phase_seq) >= 0.0, 1.0, -1.0)
            elif waveform == pokey_hw.Waveform.POLY4:
                wave_samples = POLY4_SEQ[poly4_idx] * 2.0 - 1.0
            elif waveform == pokey_hw.Waveform.POLY9_17:
                step_seq = (ch_lfsr_steps[ch] + (2.0 * freq) * t_frame).astype(np.int64)
                wave_samples = noise_seq[step_seq % poly_len]
            elif waveform == pokey_hw.Waveform.POLY5_GATED_PURE:
                wave_samples = POLY5_SEQ[poly5_idx] * 2.0 - 1.0
            elif waveform == pokey_hw.Waveform.POLY5_GATED_POLY4:
                # poly5 gates a sample-and-hold of poly4
                gate = POLY5_SEQ[poly5_idx] > 0.5
                body = POLY4_SEQ[poly4_idx] * 2.0 - 1.0
                src = np.where(gate, np.arange(gate.shape[0]), 0)
                np.maximum.accumulate(src, out=src)
                wave_samples = body[src]
            else:  # POLY5_GATED_POLY9_17
                noise_samples = noise_seq[
                    (ch_lfsr_steps[ch] + (2.0 * freq) * t_frame).astype(np.int64) % poly_len
                ]
                wave_samples = (POLY5_SEQ[poly5_idx] * 2.0 - 1.0) * noise_samples

            if waveform in (pokey_hw.Waveform.POLY9_17, pokey_hw.Waveform.POLY5_GATED_POLY9_17):
                delta_steps = (2.0 * freq) * (samples_per_frame / sample_rate)
                ch_lfsr_steps[ch] = (ch_lfsr_steps[ch] + delta_steps) % poly_len

            audio_mix[s_start:s_end] += wave_samples * amp

    # Apply DC blocking filter (single-pole high pass: y[n] = x[n] - x[n-1] + R * y[n-1])
    # with R ≈ 0.995 (cut-off ~35 Hz)
    dc_blocked = np.zeros_like(audio_mix)
    r = 0.995
    for i in range(1, len(audio_mix)):
        dc_blocked[i] = audio_mix[i] - audio_mix[i - 1] + r * dc_blocked[i - 1]

    # Normalize audio buffer
    peak = np.max(np.abs(dc_blocked))
    if peak > 0:
        norm_audio = dc_blocked / peak * 0.90
    else:
        norm_audio = dc_blocked

    # Convert to 16-bit signed PCM
    int16_audio = (norm_audio * 32767.0).astype(np.int16)
    return int16_audio

"""Musical Features Layer (Layer 3).

Interprets POKEY registers into acoustical and musical features:
frequencies, note names, cents deviation, envelopes, and confidence scores.
Strictly separates directly measured physical values from heuristically inferred notes.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

import numpy as np

from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_9BIT_POLY,
    AUDCTL_CH1_179MHZ,
    AUDCTL_CH3_179MHZ,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    NOTE_NAMES,
    PAL_15KHZ_CLOCK,
    PAL_64KHZ_CLOCK,
    PAL_CLOCK_HZ,
)
from atari_music.models import ChannelVoiceState, MusicalFeaturesSummary


def midi_to_note_name(midi_num: int) -> str:
    """Convert integer MIDI note number (e.g. 69) to name ('A4')."""
    octave = (midi_num // 12) - 1
    name = NOTE_NAMES[midi_num % 12]
    return f"{name}{octave}"


def calculate_channel_frequency(
    channel_idx: int,
    audf_val: int,
    audctl_val: int,
    audf_pair_low: Optional[int] = None,
) -> Tuple[Optional[float], float]:
    """Calculate fundamental frequency in Hz for a POKEY channel.
    
    Returns:
        (frequency_hz, confidence_score)
    """
    # 16-bit paired mode: channel 2 (paired with 1) or channel 4 (paired with 3)
    if channel_idx == 2 and (audctl_val & AUDCTL_JOIN_1_2_16BIT) and audf_pair_low is not None:
        div_16 = audf_pair_low + (audf_val << 8)
        if audctl_val & AUDCTL_CH1_179MHZ:
            freq = PAL_CLOCK_HZ / (2.0 * (div_16 + 7))
        else:
            base = PAL_15KHZ_CLOCK if (audctl_val & AUDCTL_15KHZ) else PAL_64KHZ_CLOCK
            freq = base / (2.0 * (div_16 + 2))
        return (freq, 0.99) if 10.0 <= freq <= 20000.0 else (None, 0.0)

    if channel_idx == 4 and (audctl_val & AUDCTL_JOIN_3_4_16BIT) and audf_pair_low is not None:
        div_16 = audf_pair_low + (audf_val << 8)
        base = PAL_15KHZ_CLOCK if (audctl_val & AUDCTL_15KHZ) else PAL_64KHZ_CLOCK
        freq = base / (2.0 * (div_16 + 2))
        return (freq, 0.99) if 10.0 <= freq <= 20000.0 else (None, 0.0)

    # 8-bit modes
    if channel_idx == 1 and (audctl_val & AUDCTL_CH1_179MHZ):
        freq = PAL_CLOCK_HZ / (2.0 * (audf_val + 4))
        return (freq, 0.98) if 10.0 <= freq <= 20000.0 else (None, 0.0)

    if channel_idx == 3 and (audctl_val & AUDCTL_CH3_179MHZ):
        freq = PAL_CLOCK_HZ / (2.0 * (audf_val + 4))
        return (freq, 0.98) if 10.0 <= freq <= 20000.0 else (None, 0.0)

    base = PAL_15KHZ_CLOCK if (audctl_val & AUDCTL_15KHZ) else PAL_64KHZ_CLOCK
    freq = base / (2.0 * (audf_val + 1))
    return (freq, 0.95) if 10.0 <= freq <= 20000.0 else (None, 0.0)


def frequency_to_musical_pitch(freq_hz: Optional[float], distortion: int) -> Tuple[Optional[str], float, Optional[float], Optional[float]]:
    """Convert Hz frequency to pitch name, confidence, exact MIDI number, and cents deviation."""
    if freq_hz is None or freq_hz <= 15.0 or freq_hz > 18000.0:
        return None, 0.0, None, None

    # Noise modes do not have musical pitches
    if distortion in (DISTORTION_WHITE_NOISE, 0x80, 0x00):
        return None, 0.0, None, None

    # Calculate fractional MIDI pitch: A4 (69) = 440 Hz
    exact_midi = 69.0 + 12.0 * math.log2(freq_hz / 440.0)
    nearest_midi = int(round(exact_midi))
    cents_dev = (exact_midi - nearest_midi) * 100.0
    abs_cents = abs(cents_dev)

    # Pure tone ($A0) has highest tuning precision
    if distortion == DISTORTION_PURE_TONE:
        if abs_cents <= 15.0:
            conf = 0.95
        elif abs_cents <= 30.0:
            conf = 0.82
        elif abs_cents <= 45.0:
            conf = 0.65
        else:
            conf = 0.40  # Microtonal slide
    else:
        # Pitched polyphonic distortion modes ($20, $40, $60, $C0)
        conf = 0.60 if abs_cents <= 25.0 else 0.40

    if 12 <= nearest_midi <= 127:
        note_name = midi_to_note_name(nearest_midi)
        return note_name, conf, round(exact_midi, 2), round(cents_dev, 1)

    return None, 0.0, None, None


def interpret_voice_state(
    channel_idx: int,
    pokey_idx: int,
    audf: int,
    audc: int,
    audctl: int,
    audf_pair_low: Optional[int] = None,
) -> ChannelVoiceState:
    """Build full musical interpretation for a single channel state."""
    volume = audc & 0x0F
    distortion = audc & 0xE0
    volume_only = bool(audc & 0x10)
    is_active = (volume > 0)

    # Check if channel is 16-bit partner
    is_16bit_high = False
    if channel_idx == 1 and (audctl & AUDCTL_JOIN_1_2_16BIT):
        is_16bit_high = True  # Silent control channel
    elif channel_idx == 3 and (audctl & AUDCTL_JOIN_3_4_16BIT):
        is_16bit_high = True

    is_noise = distortion == DISTORTION_WHITE_NOISE or volume_only

    if not is_active or is_16bit_high:
        return ChannelVoiceState(
            channel=channel_idx,
            pokey=pokey_idx,
            audf=audf,
            audc=audc,
            volume=volume,
            distortion=distortion,
            volume_only=volume_only,
            is_active=False,
            is_16bit_high=is_16bit_high,
            is_noise=is_noise,
        )

    freq_hz, freq_conf = calculate_channel_frequency(channel_idx, audf, audctl, audf_pair_low)
    note_name, note_conf, midi_pitch, cents = frequency_to_musical_pitch(freq_hz, distortion)

    return ChannelVoiceState(
        channel=channel_idx,
        pokey=pokey_idx,
        audf=audf,
        audc=audc,
        volume=volume,
        distortion=distortion,
        volume_only=volume_only,
        is_active=is_active,
        frequency_hz=round(freq_hz, 2) if freq_hz else None,
        frequency_confidence=freq_conf,
        note=note_name,
        note_confidence=note_conf,
        midi_pitch=midi_pitch,
        cents_deviation=cents,
        is_16bit_high=is_16bit_high,
        is_noise=is_noise,
    )


def estimate_tempo_from_onsets(onset_times_sec: List[float]) -> Tuple[Optional[float], float]:
    """Estimate musical tempo (BPM) from Inter-Onset Intervals (IOI)."""
    if len(onset_times_sec) < 10:
        return None, 0.0

    diffs = np.diff(onset_times_sec)
    # Filter reasonable note interval bounds (e.g. 0.04s to 2.0s)
    valid_diffs = diffs[(diffs >= 0.04) & (diffs <= 2.0)]
    if len(valid_diffs) < 8:
        return None, 0.0

    # Quantize to 20ms steps and find dominant interval
    quantized = np.round(valid_diffs * 50.0) / 50.0
    counter = Counter(quantized)
    common_intervals = counter.most_common(5)

    for interval_sec, count in common_intervals:
        if interval_sec <= 0.04:
            continue
        # Check BPM equivalent for 16th, 8th, or quarter note
        for mult in [1.0, 2.0, 4.0]:
            quarter_sec = interval_sec * mult
            bpm = 60.0 / quarter_sec
            if 70.0 <= bpm <= 190.0:
                conf = min(0.92, round(count / len(valid_diffs) + 0.4, 2))
                return round(bpm, 1), conf

    return None, 0.0


def summarize_musical_features(
    frames_voices: List[List[ChannelVoiceState]],
    audctls: List[int],
) -> MusicalFeaturesSummary:
    """Compute global musical features summary across all song frames."""
    distortions_set = set()
    audctl_set = set(audctls)
    unique_pitches = set()
    pitch_counts: Counter[str] = Counter()
    onset_times: List[float] = []

    channels_active_mask = [False] * 8
    max_simultaneous = 0
    fast_audc_changes = 0

    uses_16bit = False
    uses_15khz = False
    uses_179mhz = False
    uses_highpass = False
    uses_9bit = False
    uses_vol_only = False

    midi_values_sequence: List[int] = []

    for ctl in audctl_set:
        if ctl & (AUDCTL_JOIN_1_2_16BIT | AUDCTL_JOIN_3_4_16BIT):
            uses_16bit = True
        if ctl & AUDCTL_15KHZ:
            uses_15khz = True
        if ctl & (AUDCTL_CH1_179MHZ | AUDCTL_CH3_179MHZ):
            uses_179mhz = True
        if ctl & (AUDCTL_HIPASS_CH1_CH3 | AUDCTL_HIPASS_CH2_CH4):
            uses_highpass = True
        if ctl & AUDCTL_9BIT_POLY:
            uses_9bit = True

    prev_audc = [-1] * 8

    for frame_idx, voices in enumerate(frames_voices):
        active_in_frame = 0
        for v in voices:
            idx = v.pokey * 4 + (v.channel - 1)
            if v.is_active:
                distortions_set.add(v.distortion)
                if v.volume_only:
                    uses_vol_only = True
                channels_active_mask[idx] = True
                active_in_frame += 1

                if v.note and v.note_confidence >= 0.70:
                    unique_pitches.add(v.note)
                    pitch_counts[v.note] += 1
                    if v.midi_pitch:
                        midi_values_sequence.append(int(round(v.midi_pitch)))

                # Check onset
                if prev_audc[idx] == 0:
                    onset_times.append(frame_idx * 0.02)

            # Rapid volume modulation tracking
            if prev_audc[idx] != -1 and abs((v.audc & 0x0F) - (prev_audc[idx] & 0x0F)) >= 3:
                fast_audc_changes += 1

            prev_audc[idx] = v.audc

        if active_in_frame > max_simultaneous:
            max_simultaneous = active_in_frame

    # Pitch range and melody intervals
    lowest_note = None
    highest_note = None
    pitch_range = None
    step_leap_ratio = None

    if midi_values_sequence:
        min_midi = min(midi_values_sequence)
        max_midi = max(midi_values_sequence)
        pitch_range = float(max_midi - min_midi)
        lowest_note = midi_to_note_name(min_midi)
        highest_note = midi_to_note_name(max_midi)

        # Interval step vs leap calculation
        steps = 0
        leaps = 0
        for i in range(len(midi_values_sequence) - 1):
            diff = abs(midi_values_sequence[i + 1] - midi_values_sequence[i])
            if 1 <= diff <= 2:
                steps += 1
            elif diff >= 3:
                leaps += 1
        if (steps + leaps) > 0:
            step_leap_ratio = round(steps / (steps + leaps), 2)

    tempo, tempo_conf = estimate_tempo_from_onsets(onset_times)

    return MusicalFeaturesSummary(
        channels_used_count=sum(1 for m in channels_active_mask if m),
        max_simultaneous_voices=max_simultaneous,
        distortions_used=sorted(distortions_set),
        audctl_values_used=sorted(audctl_set),
        uses_16bit=uses_16bit,
        uses_15khz=uses_15khz,
        uses_179mhz=uses_179mhz,
        uses_highpass=uses_highpass,
        uses_9bit_poly=uses_9bit,
        uses_volume_only_digi=uses_vol_only,
        uses_ultrasound=False,
        fast_audc_change_count=fast_audc_changes,
        unique_frequencies_count=len(unique_pitches),
        pitch_range_semitones=pitch_range,
        lowest_note=lowest_note,
        highest_note=highest_note,
        most_frequent_notes=pitch_counts.most_common(5),
        step_vs_leap_ratio=step_leap_ratio,
        estimated_tempo_bpm=tempo,
        tempo_confidence=tempo_conf,
    )

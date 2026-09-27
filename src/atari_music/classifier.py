"""POKEY Channel Role Classifier.

Classifies channel musical roles into:
melody, bass, percussion, arpeggio, sound_effect, digi_sample, unknown
using acoustic, temporal, and register context.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Optional, Tuple

import numpy as np

from atari_music.constants import (
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    DISTORTION_4BIT_POLY,
)
from atari_music.models import ChannelVoiceState


ROLE_MELODY = "melody"
ROLE_BASS = "bass"
ROLE_PERCUSSION = "percussion"
ROLE_ARPEGGIO = "arpeggio"
ROLE_SOUND_EFFECT = "sound_effect"
ROLE_DIGI_SAMPLE = "digi_sample"
ROLE_UNKNOWN = "unknown"

ALL_ROLES = [
    ROLE_BASS,
    ROLE_MELODY,
    ROLE_PERCUSSION,
    ROLE_ARPEGGIO,
    ROLE_SOUND_EFFECT,
    ROLE_DIGI_SAMPLE,
    ROLE_UNKNOWN,
]


def classify_channel_activity(
    channel_timeline: List[ChannelVoiceState],
    channel_idx: int,
    is_16bit_paired: bool = False,
) -> Tuple[str, float]:
    """Classify the primary musical role of a channel across a song.
    
    Returns:
        (role_name, confidence_score)
    """
    active_states = [s for s in channel_timeline if s.is_active]
    if not active_states:
        return ROLE_UNKNOWN, 1.0

    total_active_frames = len(active_states)
    total_frames = len(channel_timeline)
    active_ratio = total_active_frames / max(total_frames, 1)

    # Count distortions
    dist_counts = Counter(s.distortion for s in active_states)
    pure_tone_count = dist_counts.get(DISTORTION_PURE_TONE, 0)
    noise_count = dist_counts.get(DISTORTION_WHITE_NOISE, 0)
    poly4_count = dist_counts.get(DISTORTION_4BIT_POLY, 0)
    vol_only_count = sum(1 for s in active_states if s.volume_only)

    # 1. Check Digi / Sample (DAC volume-only mode)
    if vol_only_count / total_active_frames >= 0.35:
        conf = min(0.95, round(vol_only_count / total_active_frames, 2))
        return ROLE_DIGI_SAMPLE, conf

    # 2. Check Percussion (White Noise $E0 dominance or rapid decay bursts)
    if noise_count / total_active_frames >= 0.40:
        conf = min(0.95, round(noise_count / total_active_frames, 2))
        return ROLE_PERCUSSION, conf

    # 3. Check 16-bit or low register Bass
    midi_pitches = [s.midi_pitch for s in active_states if s.midi_pitch is not None]
    avg_pitch = np.mean(midi_pitches) if midi_pitches else 60.0

    if is_16bit_paired or (avg_pitch < 50.0 and (pure_tone_count + poly4_count) / total_active_frames >= 0.50):
        # MIDI < 50 is below D3 (sub-bass / bass range: C1 to D3)
        conf = 0.95 if is_16bit_paired else 0.85
        return ROLE_BASS, conf

    # 4. Check Arpeggio (rapid pitch alternation every 1-2 frames)
    pitch_change_intervals = []
    curr_pitch = None
    curr_len = 0
    for s in active_states:
        p = s.midi_pitch
        if p != curr_pitch:
            if curr_len > 0:
                pitch_change_intervals.append(curr_len)
            curr_pitch = p
            curr_len = 1
        else:
            curr_len += 1

    if pitch_change_intervals:
        avg_note_len = np.mean(pitch_change_intervals)
        # Fast chiptune arpeggios typically have note lengths of 1, 2, or 3 frames (20-60 ms)
        if avg_note_len <= 3.2 and len(pitch_change_intervals) >= 20:
            return ROLE_ARPEGGIO, 0.88

    # 5. Check Melody (moderate to high register, sustained notes, pure tone or lead poly)
    if (pure_tone_count + poly4_count) / total_active_frames >= 0.55:
        if 48.0 <= avg_pitch <= 96.0:  # C3 to C7
            conf = 0.90 if pure_tone_count / total_active_frames >= 0.60 else 0.80
            return ROLE_MELODY, conf

    # 6. Check Sound Effect (sparse activity, extreme pitch variance or very low confidence)
    low_conf_count = sum(1 for s in active_states if s.note_confidence <= 0.45)
    if low_conf_count / total_active_frames >= 0.60 or active_ratio <= 0.08:
        return ROLE_SOUND_EFFECT, 0.75

    return ROLE_UNKNOWN, 0.40

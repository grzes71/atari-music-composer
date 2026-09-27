"""Pattern Discovery, Music Categorization, and Memory Footprint Analysis.

Analyzes repetition ratios, discovers recurring motifs, classifies music types,
and computes memory footprint estimations for Atari 8-bit RAM constraints.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from atari_music.models import (
    ChannelVoiceState,
    MusicalFeaturesSummary,
    RawDumpMeta,
    RepetitionAndMemory,
)


def categorize_music_type(
    meta: RawDumpMeta,
    features: MusicalFeaturesSummary,
) -> Tuple[str, List[str]]:
    """Classify piece into technical/musical category and compile descriptive feature flags."""
    flags: List[str] = []

    if meta.is_stereo:
        flags.append("STEREO")
    if meta.playback_rate_hz >= 180.0:
        flags.append("FASTPLAY_200HZ_OR_MORE")
    elif meta.playback_rate_hz >= 90.0:
        flags.append("FASTPLAY_100HZ")

    if features.uses_16bit:
        flags.append("16BIT_TUNING")
    if features.uses_15khz:
        flags.append("15KHZ_CLOCK")
    if features.uses_highpass:
        flags.append("HIGHPASS_FILTER")
    if features.uses_9bit_poly:
        flags.append("9BIT_POLY")
    if features.uses_volume_only_digi:
        flags.append("DIGI_SAMPLE")
    if "Ultrasound" in meta.features_detected:
        flags.append("ULTRASOUND")

    # Category determination
    if meta.is_stereo:
        category = "stereo"
    elif features.uses_volume_only_digi or meta.playback_rate_hz >= 300.0:
        category = "digi_sample"
    elif features.unique_frequencies_count == 0 and features.channels_used_count > 0:
        category = "percussion_noise"
    elif features.unique_frequencies_count >= 5 and 0xA0 in features.distortions_used:
        if features.uses_16bit or features.uses_highpass or features.fast_audc_change_count > 50:
            category = "hybrid"
        else:
            category = "standard_melody"
    else:
        category = "hybrid"

    return category, flags


def analyze_pattern_repetition(
    frames_voices: List[List[ChannelVoiceState]],
    bar_frames: int = 16,
) -> Tuple[int, int, float, List[int], Optional[str]]:
    """Segment timeline into bar windows, compute pattern repetition ratio and motifs."""
    total_frames = len(frames_voices)
    if total_frames < bar_frames:
        return 0, 0, 0.0, [], None

    total_bars = total_frames // bar_frames
    bar_signatures: List[int] = []

    for b in range(total_bars):
        start = b * bar_frames
        end = start + bar_frames
        # Hash signature of active voice channels and note values in this window
        tokens = []
        for f in range(start, end):
            for v in frames_voices[f]:
                if v.is_active:
                    tokens.append((v.channel, v.volume, v.audf, v.distortion))
        bar_signatures.append(hash(tuple(tokens)))

    unique_patterns = len(set(bar_signatures))
    repetition_ratio = round(1.0 - (unique_patterns / max(total_bars, 1)), 3)

    # Detect repeating motif lengths (e.g. 2, 4, 8 bars)
    repeating_lengths: List[int] = []
    for length in [2, 4, 8]:
        if total_bars >= length * 2:
            matches = 0
            for i in range(total_bars - length):
                if bar_signatures[i : i + length] == bar_signatures[i + length : i + length * 2]:
                    matches += 1
            if matches >= 1:
                repeating_lengths.append(length)

    # Simple formal structure heuristic (A/B/A/B)
    detected_form = None
    if total_bars >= 4:
        p_a = bar_signatures[0]
        p_b = bar_signatures[1]
        if total_bars >= 4 and bar_signatures[2] == p_a and bar_signatures[3] == p_b:
            detected_form = "A-B-A-B"
        elif total_bars >= 4 and bar_signatures[0] == bar_signatures[1]:
            detected_form = "A-A-B-B"
        elif repetition_ratio >= 0.50:
            detected_form = "Cyclic / Loop Motif"

    return unique_patterns, total_bars, max(repetition_ratio, 0.0), repeating_lengths, detected_form


def estimate_memory_footprint(
    raw_sap_file_bytes: int,
    total_events_count: int,
    unique_patterns: int,
    total_bars: int,
) -> Tuple[int, int, int, int]:
    """Estimate memory footprint for raw events and optimized 6502 Atari tracker playback."""
    # Event stream: 4 bytes per event (16-bit time offset + 8-bit reg + 8-bit val)
    event_stream_bytes = total_events_count * 4

    # Tracker pattern format (like RMT/CMC):
    # Pattern length: 16 lines * ~2 bytes per channel * 4 channels = ~128 bytes per unique pattern
    # Sequence order table: 1 byte per bar
    deduplicated_bytes = (unique_patterns * 128) + total_bars

    # Estimated RAM for Atari 8-bit:
    # 6502 player routine (~1500 bytes) + track pattern data + zero page tables (128 bytes)
    estimated_player_ram = 1500 + deduplicated_bytes + 128

    return raw_sap_file_bytes, event_stream_bytes, deduplicated_bytes, estimated_player_ram


def run_repetition_and_memory_analysis(
    meta: RawDumpMeta,
    features: MusicalFeaturesSummary,
    frames_voices: List[List[ChannelVoiceState]],
    total_events_count: int,
    raw_sap_file_bytes: int,
) -> RepetitionAndMemory:
    """Run complete structural, repetition, and memory footprint analysis."""
    category, flags = categorize_music_type(meta, features)
    unique_pats, total_bars, rep_ratio, motif_lens, form = analyze_pattern_repetition(frames_voices)
    raw_b, event_b, dedup_b, ram_b = estimate_memory_footprint(
        raw_sap_file_bytes, total_events_count, unique_pats, total_bars
    )

    return RepetitionAndMemory(
        music_category=category,
        flags=flags,
        unique_patterns_count=unique_pats,
        total_bars_detected=total_bars,
        repetition_ratio=rep_ratio,
        repeating_motif_lengths=motif_lens,
        detected_form=form,
        raw_sap_bytes=raw_b,
        event_stream_bytes=event_b,
        deduplicated_pattern_bytes=dedup_b,
        estimated_atari_player_ram_bytes=ram_b,
    )

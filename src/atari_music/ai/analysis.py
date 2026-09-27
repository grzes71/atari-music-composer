"""Musical Quality, Diversity, and POKEY Runtime Analysis Engine.

Provides deep structural, melodic, harmonic, rhythmic, and hardware diagnostics
for AI-generated compositions, as well as deterministic composition fingerprinting.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from atari_music.ai.composition import map_instrument_character
from atari_music.ai.schema import AICompositionDoc, AIPatternChannelEvent
from atari_music.ai.validation import normalize_channel_idx
from atari_music.constants import (
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    DISTORTION_4BIT_POLY,
    DISTORTION_DESCRIPTIONS,
)
from atari_music.ir import (
    frequency_to_audf_8bit,
    frequency_to_audf_16bit,
    midi_pitch_to_frequency,
    note_name_to_midi,
)


# =============================================================================
# Analysis Metric Models
# =============================================================================

class RhythmMetrics(BaseModel):
    """Detailed rhythmic structure metrics."""
    total_notes: int = Field(description="Total non-rest note events across the piece")
    total_active_steps: int = Field(description="Total sequence steps where at least one channel sounds")
    note_density: float = Field(description="Average notes per second across the duration")
    avg_note_length: float = Field(description="Average note duration in steps")
    note_length_distribution: Dict[int, int] = Field(default_factory=dict, description="Histogram of note duration in steps")
    channel_activity: Dict[int, Dict[str, Any]] = Field(default_factory=dict, description="Per-channel note count and active steps")
    rest_ratio: float = Field(description="Ratio of completely silent steps across the piece (0.0 to 1.0)")
    rhythmic_repetition: float = Field(description="Degree of rhythmic pattern repetition (0.0 to 1.0)")


class MelodyMetrics(BaseModel):
    """Melodic motion and interval grammar metrics."""
    min_pitch: Optional[int] = Field(default=None, description="Lowest MIDI pitch in melodic channels")
    max_pitch: Optional[int] = Field(default=None, description="Highest MIDI pitch in melodic channels")
    pitch_range_semitones: int = Field(default=0, description="Pitch range in semitones (max - min)")
    mean_pitch: Optional[float] = Field(default=None, description="Average MIDI pitch")
    unique_pitches_count: int = Field(default=0, description="Number of distinct pitches used")
    pitch_classes_count: int = Field(default=0, description="Number of distinct pitch classes used (0..11)")
    semitone_steps_count: int = Field(default=0, description="Count of half-step (1 semitone) intervals")
    larger_leaps_count: int = Field(default=0, description="Count of melodic leaps (> 2 semitones)")
    max_interval: int = Field(default=0, description="Largest melodic interval in semitones")
    mean_interval: float = Field(default=0.0, description="Average melodic interval in semitones")
    melodic_direction: str = Field(default="static", description="'ascending', 'descending', 'balanced', or 'static'")
    stepwise_vs_leap_ratio: float = Field(default=0.0, description="Ratio of stepwise motion (1-2 semitones) vs leaps")


class HarmonyMetrics(BaseModel):
    """Vertical channel interaction and harmonic interval metrics."""
    sounding_chords_count: int = Field(default=0, description="Steps where 2+ pitched notes sound simultaneously")
    sounding_intervals: Dict[int, int] = Field(default_factory=dict, description="Distribution of interval classes 0..6")
    unisons_count: int = Field(default=0, description="Sounding unisons and octaves (IC 0)")
    fifths_count: int = Field(default=0, description="Sounding fifths and fourths (IC 5)")
    octaves_count: int = Field(default=0, description="Pure octave intervals (delta = 12, 24, ...)")
    dissonant_intervals_count: int = Field(default=0, description="Dissonant intervals (m2, M2, M7, tritone: IC 1, 2, 6)")
    consonant_intervals_count: int = Field(default=0, description="Consonant intervals (unison, 3rds, 4ths, 5ths, 6ths: IC 0, 3, 4, 5)")
    consonance_ratio: float = Field(default=1.0, description="Consonant intervals / total sounding intervals")


class StructureMetrics(BaseModel):
    """Macro-structural metrics."""
    pattern_count: int = Field(description="Number of distinct patterns defined")
    pattern_lengths: Dict[str, int] = Field(default_factory=dict, description="Length in steps per pattern")
    sequence_length: int = Field(description="Total length of the piece in steps")
    sequence_pattern_count: int = Field(description="Total patterns in playback sequence")
    pattern_repetition_count: int = Field(description="Number of pattern repetitions in sequence")
    loop_point: int = Field(description="Sequence index for looping")
    repetition_ratio: float = Field(description="Proportion of repeated patterns in sequence (0.0 to 1.0)")
    duration_seconds: float = Field(description="Estimated playback duration in seconds on PAL (50 Hz)")


class PokeyMetrics(BaseModel):
    """Atari POKEY hardware and register utilization diagnostics."""
    channel_utilization: Dict[int, Dict[str, Any]] = Field(default_factory=dict, description="Active step count and percentage per POKEY channel")
    uses_16bit_bass: bool = Field(description="Whether 16-bit bass mode is enabled")
    bass_16bit_channel_usage: str = Field(description="Status of Ch1/Ch2 pairing in 16-bit bass mode")
    volume_distribution: Dict[int, int] = Field(default_factory=dict, description="Distribution of volume levels (0..15)")
    distortion_distribution: Dict[str, int] = Field(default_factory=dict, description="Distribution of POKEY distortion types")
    instrument_changes_count: int = Field(default=0, description="Number of instrument changes within tracks")
    frequency_changes_count: int = Field(default=0, description="Number of frequency register updates")
    audf_frequency_range: Dict[str, Any] = Field(default_factory=dict, description="Min/max AUDF register values and frequencies in Hz")
    extreme_register_values: List[str] = Field(default_factory=list, description="Diagnostic warnings on extreme register writes")
    warnings: List[str] = Field(default_factory=list, description="Player and hardware warnings")


class CompositionAnalysisReport(BaseModel):
    """Consolidated musical and hardware analysis report."""
    fingerprint: str = Field(description="Canonical SHA-256 fingerprint of the composition")
    rhythm: RhythmMetrics
    melody: MelodyMetrics
    harmony: HarmonyMetrics
    structure: StructureMetrics
    pokey: PokeyMetrics
    summary: Dict[str, Any] = Field(default_factory=dict, description="Executive summary of key metrics")


# =============================================================================
# Deterministic Composition Fingerprint
# =============================================================================

def composition_fingerprint(doc: AICompositionDoc) -> str:
    """Compute a deterministic, canonical SHA-256 fingerprint for a composition.

    The fingerprint is invariant to JSON formatting, whitespace, and key order,
    but sensitive to any difference in notes, timing, channels, instruments,
    parameters, or sequence structure.
    """
    # 1. Canonical metadata and hardware
    canonical_meta = {
        "bpm": doc.metadata.bpm,
        "key": (doc.metadata.key or "").strip().upper(),
        "mode": (doc.metadata.mode or "").strip().lower(),
        "channels": doc.hardware.channels,
        "use_16bit_bass": bool(doc.hardware.use_16bit_bass),
        "loop_point": doc.loop_point,
    }

    # 2. Canonical instruments (sorted by id)
    canonical_insts = []
    for inst in sorted(doc.instruments, key=lambda i: i.id):
        dist, env, role = map_instrument_character(inst, doc.hardware.use_16bit_bass)
        canonical_insts.append({
            "id": inst.id,
            "character": (inst.character or "").strip().lower(),
            "distortion": dist,
            "role": role.value,
            "attack": env.attack_frames,
            "decay": env.decay_frames,
            "sustain": env.sustain_vol,
            "release": env.release_frames,
        })

    # 3. Canonical patterns (sorted by id)
    canonical_patterns = []
    for pat in sorted(doc.patterns, key=lambda p: p.id):
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        can_channels: Dict[int, List[Dict[str, Any]]] = {ch: [] for ch in range(1, 5)}

        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            for ev in ev_list:
                # Normalize note pitch
                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                midi_val = None if is_rest else note_name_to_midi(str(ev.note))
                can_channels[ch_idx].append({
                    "step": ev.step,
                    "midi": midi_val,
                    "dur": ev.duration,
                    "vol": ev.volume if ev.volume is not None else 14,
                    "inst": ev.instrument,
                })

        # Sort channel events by step
        for ch_idx in range(1, 5):
            can_channels[ch_idx].sort(key=lambda e: (e["step"], e["midi"] or -1))

        canonical_patterns.append({
            "id": pat.id,
            "length_steps": pat.length_steps,
            "channels": {str(ch): can_channels[ch] for ch in range(1, 5)},
        })

    # 4. Canonical structure
    canonical_doc = {
        "meta": canonical_meta,
        "instruments": canonical_insts,
        "patterns": canonical_patterns,
        "sequence": list(doc.sequence),
    }

    raw_bytes = json.dumps(canonical_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


# =============================================================================
# Helper: Expand Sequence into Linear Step Timeline
# =============================================================================

def _expand_sequence_timeline(
    doc: AICompositionDoc,
) -> Tuple[int, Dict[int, List[Optional[Tuple[Optional[int], int, str, int]]]]]:
    """Expand pattern sequence into a linear step-by-step timeline per channel (1..4).

    Returns
    -------
    total_steps : int
    timeline : Dict[int, List[Optional[Tuple[Optional[int], int, str, int]]]]
        Per channel (1..4), a list of length `total_steps`.
        Each entry is either None (silent) or (midi_pitch, volume, instrument_id, remaining_duration).
    """
    pat_map = {p.id: p for p in doc.patterns}
    total_steps = sum(pat_map[pid].length_steps for pid in doc.sequence if pid in pat_map)

    timeline: Dict[int, List[Optional[Tuple[Optional[int], int, str, int]]]] = {
        ch: [None] * total_steps for ch in range(1, 5)
    }

    current_step_offset = 0
    for pid in doc.sequence:
        pat = pat_map.get(pid)
        if not pat:
            continue

        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            for ev in ev_list:
                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                midi_val = None if is_rest else note_name_to_midi(str(ev.note))
                vol = ev.volume if ev.volume is not None else 14
                inst_str = ev.instrument

                start = current_step_offset + ev.step
                end = min(total_steps, start + ev.duration)
                for t in range(start, end):
                    rem_dur = end - t
                    timeline[ch_idx][t] = (midi_val, vol, inst_str, rem_dur)

        current_step_offset += pat.length_steps

    return total_steps, timeline


def calculate_bpm_frames_per_tick(bpm: int) -> int:
    """Determine POKEY 50 Hz VBLANK frames per tick from BPM."""
    if bpm <= 80:
        return 6
    elif bpm <= 110:
        return 5
    elif bpm <= 145:
        return 4
    else:
        return 3


def calculate_composition_duration(doc: AICompositionDoc) -> float:
    """Calculate the exact ground-truth playback duration in seconds for one full sequence playthrough on PAL (50 Hz).
    
    Ground-truth formula:
    actual_duration = (sum(pattern_lengths_in_sequence) * frames_per_tick) / 50.0
    """
    pat_map = {p.id: p.length_steps for p in doc.patterns}
    total_steps = sum(pat_map.get(pid, 0) for pid in doc.sequence)
    if total_steps == 0:
        return 0.0
    frames_per_tick = calculate_bpm_frames_per_tick(doc.metadata.bpm)
    return (total_steps * frames_per_tick) / 50.0


def calculate_loop_duration(doc: AICompositionDoc) -> float:
    """Calculate playback duration in seconds of the looped section (from loop_point to sequence end)."""
    pat_map = {p.id: p.length_steps for p in doc.patterns}
    seq_len = len(doc.sequence)
    loop_idx = max(0, min(doc.loop_point, seq_len - 1)) if seq_len > 0 else 0
    loop_steps = sum(pat_map.get(doc.sequence[i], 0) for i in range(loop_idx, seq_len))
    frames_per_tick = calculate_bpm_frames_per_tick(doc.metadata.bpm)
    return (loop_steps * frames_per_tick) / 50.0


def verify_duration_invariant(
    doc: AICompositionDoc,
    min_seconds: float = 60.0,
    max_seconds: float = 120.0,
    tolerance_percent: float = 25.0,
) -> Dict[str, Any]:
    """Verify runtime duration against target range and declared metadata.
    
    Parameters
    ----------
    doc : AICompositionDoc
        The composition document to verify.
    min_seconds : float, default=60.0
        Minimum allowable actual runtime duration.
    max_seconds : float, default=120.0
        Maximum allowable actual runtime duration.
    tolerance_percent : float, default=25.0
        Maximum allowable percentage discrepancy between declared and calculated duration.
        
    Returns
    -------
    Dict[str, Any]
        Dictionary with actual_duration_seconds, declared_duration_seconds,
        difference_seconds, difference_percent, in_target_range, matches_declared, status.
    """
    actual_s = calculate_composition_duration(doc)
    declared_s = doc.metadata.duration_seconds
    in_range = min_seconds <= actual_s <= max_seconds
    
    if declared_s is not None and declared_s > 0:
        diff_s = actual_s - declared_s
        diff_pct = (abs(diff_s) / declared_s) * 100.0
        matches_declared = diff_pct <= tolerance_percent
    else:
        diff_s = 0.0
        diff_pct = 0.0
        matches_declared = True

    status = "PASS" if (in_range and matches_declared) else "FAIL"

    return {
        "actual_duration_seconds": round(actual_s, 2),
        "declared_duration_seconds": round(declared_s, 2) if declared_s is not None else None,
        "difference_seconds": round(diff_s, 2),
        "difference_percent": round(diff_pct, 1),
        "in_target_range": in_range,
        "matches_declared": matches_declared,
        "status": status,
    }


# =============================================================================
# Analysis Engine
# =============================================================================

def analyze_composition(doc: AICompositionDoc) -> CompositionAnalysisReport:
    """Perform a comprehensive musical, harmonic, and POKEY hardware analysis of a composition."""
    # 0. Fingerprint
    fp = composition_fingerprint(doc)

    # Calculate frames_per_tick based on BPM
    frames_per_tick = calculate_bpm_frames_per_tick(doc.metadata.bpm)

    # Expand linear timeline
    total_steps, timeline = _expand_sequence_timeline(doc)
    duration_s = (total_steps * frames_per_tick) / 50.0 if total_steps > 0 else 0.0

    # -------------------------------------------------------------------------
    # 1. Rhythm Analysis
    # -------------------------------------------------------------------------
    all_notes: List[Tuple[int, int]] = []  # (duration, volume)
    channel_notes_count: Dict[int, int] = {ch: 0 for ch in range(1, 5)}
    channel_active_steps: Dict[int, int] = {ch: 0 for ch in range(1, 5)}
    note_durations_hist: Dict[int, int] = {}

    pat_map = {p.id: p for p in doc.patterns}
    for pid in doc.sequence:
        pat = pat_map.get(pid)
        if not pat:
            continue
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            for ev in ev_list:
                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                if not is_rest:
                    channel_notes_count[ch_idx] += 1
                    all_notes.append((ev.duration, ev.volume or 14))
                    note_durations_hist[ev.duration] = note_durations_hist.get(ev.duration, 0) + 1

    # Count active steps per channel from timeline
    active_steps_global = 0
    for t in range(total_steps):
        step_active = False
        for ch in range(1, 5):
            entry = timeline[ch][t]
            if entry is not None and (entry[0] is not None or entry[1] > 0):
                channel_active_steps[ch] += 1
                step_active = True
        if step_active:
            active_steps_global += 1

    total_notes_count = len(all_notes)
    avg_note_length = (sum(d for d, _ in all_notes) / total_notes_count) if total_notes_count > 0 else 0.0
    note_density = (total_notes_count / duration_s) if duration_s > 0 else 0.0
    rest_ratio = 1.0 - (active_steps_global / total_steps) if total_steps > 0 else 1.0

    channel_activity: Dict[int, Dict[str, Any]] = {}
    for ch in range(1, 5):
        ratio = (channel_active_steps[ch] / total_steps) if total_steps > 0 else 0.0
        channel_activity[ch] = {
            "notes_count": channel_notes_count[ch],
            "active_steps": channel_active_steps[ch],
            "activity_ratio": round(ratio, 4),
        }

    # Rhythmic repetition: compare sequence pattern rhythm fingerprints
    seq_patterns = [pid for pid in doc.sequence if pid in pat_map]
    if len(seq_patterns) > 1:
        unique_patterns_in_seq = len(set(seq_patterns))
        rhythmic_repetition = 1.0 - (unique_patterns_in_seq / len(seq_patterns))
    else:
        rhythmic_repetition = 1.0 if len(seq_patterns) == 1 else 0.0

    rhythm = RhythmMetrics(
        total_notes=total_notes_count,
        total_active_steps=active_steps_global,
        note_density=round(note_density, 2),
        avg_note_length=round(avg_note_length, 2),
        note_length_distribution=dict(sorted(note_durations_hist.items())),
        channel_activity=channel_activity,
        rest_ratio=round(rest_ratio, 4),
        rhythmic_repetition=round(rhythmic_repetition, 4),
    )

    # -------------------------------------------------------------------------
    # 2. Melody Analysis (Melodic / Pitched Channels)
    # -------------------------------------------------------------------------
    all_pitches: List[int] = []
    melodic_intervals: List[int] = []

    # Map instruments to role
    inst_role_map = {}
    for inst in doc.instruments:
        _, _, r = map_instrument_character(inst, doc.hardware.use_16bit_bass)
        inst_role_map[inst.id] = r.value

    # Extract ordered pitches from channels
    for pid in doc.sequence:
        pat = pat_map.get(pid)
        if not pat:
            continue
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            sorted_evs = sorted(ev_list, key=lambda e: e.step)
            prev_pitch: Optional[int] = None
            for ev in sorted_evs:
                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                if is_rest:
                    continue
                midi_val = note_name_to_midi(str(ev.note))
                if midi_val is not None:
                    all_pitches.append(midi_val)
                    if prev_pitch is not None:
                        diff = midi_val - prev_pitch
                        melodic_intervals.append(diff)
                    prev_pitch = midi_val

    if all_pitches:
        min_p = min(all_pitches)
        max_p = max(all_pitches)
        range_semitones = max_p - min_p
        mean_p = sum(all_pitches) / len(all_pitches)
        unique_pitches = len(set(all_pitches))
        unique_pitch_classes = len(set(p % 12 for p in all_pitches))
    else:
        min_p = max_p = mean_p = None
        range_semitones = 0
        unique_pitches = unique_pitch_classes = 0

    if melodic_intervals:
        abs_intervals = [abs(i) for i in melodic_intervals]
        semitone_steps = sum(1 for i in abs_intervals if i == 1)
        stepwise_count = sum(1 for i in abs_intervals if i in (1, 2))
        larger_leaps = sum(1 for i in abs_intervals if i > 2)
        max_inter = max(abs_intervals)
        mean_inter = sum(abs_intervals) / len(abs_intervals)
        stepwise_ratio = stepwise_count / len(abs_intervals)

        net_motion = sum(melodic_intervals)
        if net_motion > 2:
            direction = "ascending"
        elif net_motion < -2:
            direction = "descending"
        else:
            direction = "balanced"
    else:
        semitone_steps = larger_leaps = max_inter = 0
        mean_inter = stepwise_ratio = 0.0
        direction = "static"

    melody = MelodyMetrics(
        min_pitch=min_p,
        max_pitch=max_p,
        pitch_range_semitones=range_semitones,
        mean_pitch=round(mean_p, 2) if mean_p is not None else None,
        unique_pitches_count=unique_pitches,
        pitch_classes_count=unique_pitch_classes,
        semitone_steps_count=semitone_steps,
        larger_leaps_count=larger_leaps,
        max_interval=max_inter,
        mean_interval=round(mean_inter, 2),
        melodic_direction=direction,
        stepwise_vs_leap_ratio=round(stepwise_ratio, 4),
    )

    # -------------------------------------------------------------------------
    # 3. Harmony & Channel Interaction Analysis
    # -------------------------------------------------------------------------
    sounding_chords = 0
    interval_classes: Dict[int, int] = {i: 0 for i in range(7)}
    unisons_count = 0
    fifths_count = 0
    octaves_count = 0
    dissonant_count = 0
    consonant_count = 0

    for t in range(total_steps):
        pitches_at_t = []
        for ch in range(1, 5):
            entry = timeline[ch][t]
            if entry is not None and entry[0] is not None:
                pitches_at_t.append(entry[0])

        if len(pitches_at_t) >= 2:
            sounding_chords += 1
            for i in range(len(pitches_at_t)):
                for j in range(i + 1, len(pitches_at_t)):
                    delta = abs(pitches_at_t[i] - pitches_at_t[j])
                    semitone_mod = delta % 12
                    ic = semitone_mod if semitone_mod <= 6 else 12 - semitone_mod
                    interval_classes[ic] = interval_classes.get(ic, 0) + 1

                    if delta == 0:
                        unisons_count += 1
                    elif delta % 12 == 0:
                        octaves_count += 1

                    if semitone_mod == 7 or semitone_mod == 5:
                        fifths_count += 1

                    # Dissonant: m2, M2, M7, tritone (ic 1, 2, 6)
                    if ic in (1, 2, 6):
                        dissonant_count += 1
                    else:
                        consonant_count += 1

    total_harmonic_intervals = dissonant_count + consonant_count
    consonance_ratio = (consonant_count / total_harmonic_intervals) if total_harmonic_intervals > 0 else 1.0

    harmony = HarmonyMetrics(
        sounding_chords_count=sounding_chords,
        sounding_intervals=dict(sorted(interval_classes.items())),
        unisons_count=unisons_count,
        fifths_count=fifths_count,
        octaves_count=octaves_count,
        dissonant_intervals_count=dissonant_count,
        consonant_intervals_count=consonant_count,
        consonance_ratio=round(consonance_ratio, 4),
    )

    # -------------------------------------------------------------------------
    # 4. Structure Metrics
    # -------------------------------------------------------------------------
    pat_lengths = {p.id: p.length_steps for p in doc.patterns}
    seq_count = len(doc.sequence)
    unique_seq = len(set(doc.sequence))
    repetition_ratio = 1.0 - (unique_seq / seq_count) if seq_count > 0 else 0.0

    structure = StructureMetrics(
        pattern_count=len(doc.patterns),
        pattern_lengths=pat_lengths,
        sequence_length=total_steps,
        sequence_pattern_count=seq_count,
        pattern_repetition_count=seq_count - unique_seq,
        loop_point=doc.loop_point,
        repetition_ratio=round(repetition_ratio, 4),
        duration_seconds=round(duration_s, 2),
    )

    # -------------------------------------------------------------------------
    # 5. POKEY-specific & Hardware Verification
    # -------------------------------------------------------------------------
    volume_dist: Dict[int, int] = {}
    dist_dist: Dict[str, int] = {}
    inst_changes = 0
    freq_changes = 0
    audf_values: List[int] = []
    extreme_registers: List[str] = []
    warnings: List[str] = []

    # Check 16-bit bass pairing
    uses_16bit = doc.hardware.use_16bit_bass
    if uses_16bit:
        # Check if Ch2 contains notes
        ch2_active = any(timeline[2][t] is not None for t in range(total_steps))
        if ch2_active:
            bass_16_status = "WARNING: Ch2 contains events while 16-bit bass is enabled"
            warnings.append("Channel 2 contains events but is hardware slave to Channel 1 in 16-bit bass mode")
        else:
            bass_16_status = "Valid coupling: Ch1 controls low divider, Ch2 slave"
    else:
        bass_16_status = "Standard 4-channel independent 8-bit mode"

    # Analyze volume, distortion, AUDF registers
    inst_map = {inst.id: inst for inst in doc.instruments}
    prev_inst_per_ch: Dict[int, Optional[str]] = {ch: None for ch in range(1, 5)}
    prev_pitch_per_ch: Dict[int, Optional[int]] = {ch: None for ch in range(1, 5)}

    for pid in doc.sequence:
        pat = pat_map.get(pid)
        if not pat:
            continue
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            sorted_evs = sorted(ev_list, key=lambda e: e.step)
            for ev in sorted_evs:
                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")

                # Instrument changes
                if prev_inst_per_ch[ch_idx] is not None and prev_inst_per_ch[ch_idx] != ev.instrument:
                    inst_changes += 1
                prev_inst_per_ch[ch_idx] = ev.instrument

                # Volume distribution
                vol = ev.volume if ev.volume is not None else 14
                volume_dist[vol] = volume_dist.get(vol, 0) + 1

                # Distortion
                inst_obj = inst_map.get(ev.instrument)
                dist_val = inst_obj.distortion if (inst_obj and inst_obj.distortion is not None) else (
                    DISTORTION_PURE_TONE if (not uses_16bit or ch_idx != 1) else DISTORTION_PURE_TONE
                )
                dist_name = DISTORTION_DESCRIPTIONS.get(dist_val, f"${dist_val:02X}")
                dist_dist[dist_name] = dist_dist.get(dist_name, 0) + 1

                # Pitch / AUDF
                if not is_rest:
                    midi_val = note_name_to_midi(str(ev.note))
                    if midi_val is not None:
                        if prev_pitch_per_ch[ch_idx] != midi_val:
                            freq_changes += 1
                        prev_pitch_per_ch[ch_idx] = midi_val

                        freq = midi_pitch_to_frequency(midi_val)
                        if uses_16bit and ch_idx == 1:
                            low_d, hi_d = frequency_to_audf_16bit(freq)
                            audf_values.extend([low_d, hi_d])
                        else:
                            audf_8 = frequency_to_audf_8bit(freq)
                            audf_values.append(audf_8)

                            if audf_8 == 0:
                                extreme_registers.append(f"Ch{ch_idx} extreme high freq AUDF=0 for note {ev.note}")
                            elif audf_8 >= 254:
                                extreme_registers.append(f"Ch{ch_idx} extreme low freq AUDF={audf_8} for note {ev.note}")

                # Check duration limits for 6502 player
                if ev.duration > 254:
                    warnings.append(f"Note duration {ev.duration} exceeds 6502 player 8-bit tick register limit (254)")

    audf_summary: Dict[str, Any] = {}
    if audf_values:
        min_audf = min(audf_values)
        max_audf = max(audf_values)
        audf_summary = {
            "min_audf": min_audf,
            "max_audf": max_audf,
            "min_frequency_hz": round(midi_pitch_to_frequency(min(all_pitches)), 1) if all_pitches else None,
            "max_frequency_hz": round(midi_pitch_to_frequency(max(all_pitches)), 1) if all_pitches else None,
        }

    pokey = PokeyMetrics(
        channel_utilization=channel_activity,
        uses_16bit_bass=uses_16bit,
        bass_16bit_channel_usage=bass_16_status,
        volume_distribution=dict(sorted(volume_dist.items())),
        distortion_distribution=dist_dist,
        instrument_changes_count=inst_changes,
        frequency_changes_count=freq_changes,
        audf_frequency_range=audf_summary,
        extreme_register_values=extreme_registers,
        warnings=warnings,
    )

    # -------------------------------------------------------------------------
    # 6. Executive Summary
    # -------------------------------------------------------------------------
    summary = {
        "title": doc.metadata.title,
        "style": doc.intent.style if doc.intent and doc.intent.style else "N/A",
        "bpm": doc.metadata.bpm,
        "duration_seconds": round(duration_s, 2),
        "total_notes": total_notes_count,
        "note_density": round(note_density, 2),
        "pitch_range_semitones": range_semitones,
        "mean_interval": round(mean_inter, 2),
        "stepwise_ratio": round(stepwise_ratio, 4),
        "consonance_ratio": round(consonance_ratio, 4),
        "rest_ratio": round(rest_ratio, 4),
        "repetition_ratio": round(repetition_ratio, 4),
        "fingerprint": fp,
        "warnings_count": len(warnings),
    }

    return CompositionAnalysisReport(
        fingerprint=fp,
        rhythm=rhythm,
        melody=melody,
        harmony=harmony,
        structure=structure,
        pokey=pokey,
        summary=summary,
    )

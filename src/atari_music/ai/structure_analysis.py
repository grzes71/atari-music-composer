"""Musical Structure, Repetition, Variation, and Form Analysis Engine.

Provides mathematically rigorous, objective metrics for evaluating whether
Atari POKEY music compositions exhibit true macro-structural variety or
are short motifs stretched through repetitive looping.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from atari_music.ai.schema import AICompositionDoc, AIPatternDef
from atari_music.ai.validation import normalize_channel_idx
from atari_music.ir import note_name_to_midi


# =============================================================================
# Structure Analysis Models
# =============================================================================

class PatternComparison(BaseModel):
    """Pairwise pattern musical similarity and distance."""
    pattern_id_a: str
    pattern_id_b: str
    is_identical: bool = Field(description="True if notes and timing across all 4 channels are 100% identical")
    similarity: float = Field(description="Normalized musical similarity score (0.0 = completely disjoint, 1.0 = identical)")
    distance: float = Field(description="Musical distance (1.0 - similarity)")
    relationship: str = Field(description="'identical', 'near_variation', 'related', or 'distinct'")


class MusicalFormAnalysis(BaseModel):
    """Formal sequence layout and archetype classification."""
    pattern_labels: Dict[str, str] = Field(description="Assigned theme/section label for each pattern ID")
    formal_sequence: List[str] = Field(description="Sequence of formal section labels (e.g. ['INTRO', 'A', 'A\'', 'B', ...])")
    compact_form: str = Field(description="Human-readable condensed form summary (e.g. 'INTRO - 2x A - B - A\' - OUTRO')")
    unique_sections_count: int = Field(description="Number of distinct formal sections identified")
    archetype: str = Field(description="Classified musical form archetype (Rondo, Strophic, Framed Episodic, etc.)")


class DetailedStructureMetrics(BaseModel):
    """Complete structural and repetition diagnostics for a single composition."""
    title: str
    bpm: int
    duration_seconds: float
    
    # 1. Basic Structure
    pattern_count: int = Field(description="Number of pattern definitions in document")
    pattern_lengths: Dict[str, int] = Field(description="Length in steps of each defined pattern")
    sequence_length: int = Field(description="Number of pattern instances in the playback sequence")
    total_steps: int = Field(description="Total playback duration in sequencer steps")
    pattern_occurrences: Dict[str, int] = Field(description="Count of occurrences for each pattern ID in sequence")
    repetition_ratio: float = Field(description="1.0 - (unique_patterns_in_seq / sequence_length)")
    unique_pattern_ratio: float = Field(default=0.0, description="unique_patterns_in_seq / sequence_length")

    # 2. Sequence Graph & Transitions
    unique_transitions_count: int = Field(description="Number of distinct pattern -> pattern transitions")
    unique_transitions: List[Tuple[str, str]] = Field(description="List of distinct pattern bigrams")
    transition_entropy: float = Field(description="Shannon entropy of sequence transitions in bits")
    transition_fill_count: int = Field(default=0, description="Count of short transition/fill patterns (<=16 steps or tagged as fill/trans)")

    # 3. Subsequence & Macro Repetition
    longest_repeated_subsequence_len: int = Field(description="Length (in patterns) of the longest repeating contiguous block")
    longest_repeated_subsequence: List[str] = Field(description="The longest repeating contiguous pattern block")
    longest_repeated_subsequence_count: int = Field(description="Occurrences of the longest repeating block")
    repeated_subsequences_coverage_pct: float = Field(description="Percentage of sequence positions covered by repeating blocks of length >= 2")

    # 4. Musical (Note-Level) Distinctness & Variations
    distinct_musical_patterns_count: int = Field(description="Count of truly distinct musical patterns (identical patterns merged)")
    near_identical_patterns_count: int = Field(description="Number of patterns that are minor variations of another (similarity >= 0.80)")
    near_identical_pairs: List[Tuple[str, str, float]] = Field(default_factory=list, description="Pairs of patterns with similarity >= 0.80")
    material_reuse_ratio: float = Field(description="Fraction of total playback steps that re-use already heard musical material (0.0 to 1.0)")
    variation_count: int = Field(default=0, description="Number of identified thematic variations")
    variation_ratio: float = Field(default=0.0, description="Fraction of defined patterns that are variations: variation_count / pattern_count")
    variation_pairs: List[Tuple[str, str, float]] = Field(default_factory=list, description="Pairs of (variation_id, base_id, similarity)")
    variation_similarity: float = Field(default=0.0, description="Average similarity of variation pairs")

    # 5. Texture & Channel Activity
    texture_changes_count: int = Field(default=0, description="Number of times active channel set changes between consecutive patterns in sequence")
    active_channels_distribution: Dict[str, int] = Field(default_factory=dict, description="Distribution of patterns by active channel count")

    # 6. Domain Diversities & Novelty
    melodic_diversity: float = Field(description="Normalized pitch entropy and range score (0.0 to 1.0)")
    rhythmic_diversity: float = Field(description="Normalized duration and onset distribution entropy (0.0 to 1.0)")
    harmonic_diversity: float = Field(description="Normalized sounding interval class entropy (0.0 to 1.0)")
    structural_novelty: float = Field(default=0.0, description="Proportion of sequence steps after halfway point introducing new patterns or variations")

    # 7. Form
    sections_count: int = Field(default=0, description="Total planned or deduced formal sections")
    form: MusicalFormAnalysis


# =============================================================================
# Helper: Pattern Step Extraction
# =============================================================================

def extract_pattern_channel_steps(pat: AIPatternDef) -> Dict[int, List[Optional[Tuple[Optional[int], int, bool]]]]:
    """Extract step-by-step array of (midi_pitch, volume, is_onset) per channel (1..4)."""
    length = pat.length_steps
    res: Dict[int, List[Optional[Tuple[Optional[int], int, bool]]]] = {ch: [None] * length for ch in range(1, 5)}
    has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())

    for ch_key, ev_list in pat.channels.items():
        ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
        if ch_idx not in res:
            continue
        for ev in ev_list:
            step = ev.step
            dur = ev.duration
            vol = ev.volume if ev.volume is not None else 14
            is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
            midi = None if is_rest else note_name_to_midi(str(ev.note))
            for s in range(step, min(length, step + dur)):
                res[ch_idx][s] = (midi, vol, (s == step))
    return res


# =============================================================================
# Pairwise Pattern Musical Comparison
# =============================================================================

def compare_patterns(p1: AIPatternDef, p2: AIPatternDef) -> PatternComparison:
    """Compute musical similarity and distance between two pattern definitions."""
    l1 = p1.length_steps
    l2 = p2.length_steps
    min_l = min(l1, l2)
    max_l = max(l1, l2)

    c1 = extract_pattern_channel_steps(p1)
    c2 = extract_pattern_channel_steps(p2)

    ch_scores: List[float] = []

    for ch in range(1, 5):
        has_c1 = any(x is not None for x in c1[ch])
        has_c2 = any(x is not None for x in c2[ch])

        if not has_c1 and not has_c2:
            # Both channels silent across whole pattern -> ignore
            continue
        elif not has_c1 or not has_c2:
            # Texture mismatch (one active, one completely silent)
            ch_scores.append(0.0)
            continue

        # Both channels have notes: compare step by step
        step_scores: List[float] = []
        for s in range(min_l):
            v1, v2 = c1[ch][s], c2[ch][s]
            if v1 is None and v2 is None:
                step_scores.append(1.0)
            elif v1 is None or v2 is None:
                step_scores.append(0.0)
            else:
                m1, vol1, o1 = v1
                m2, vol2, o2 = v2
                r_match = 1.0 if o1 == o2 else 0.5
                if m1 == m2:
                    p_match = 1.0
                elif m1 is None or m2 is None:
                    p_match = 0.0
                elif abs(m1 - m2) in (12, 24):
                    p_match = 0.5  # Octave transposition
                else:
                    p_match = 0.0
                step_scores.append(0.65 * p_match + 0.35 * r_match)

        if max_l > min_l:
            step_scores.extend([0.0] * (max_l - min_l))

        ch_scores.append(sum(step_scores) / max_l)

    if not ch_scores:
        sim = 1.0
    else:
        sim = sum(ch_scores) / len(ch_scores)

    is_id = (l1 == l2) and (c1 == c2)
    sim = 1.0 if is_id else round(sim, 4)
    dist = round(1.0 - sim, 4)

    if is_id:
        rel = "identical"
    elif sim >= 0.82:
        rel = "near_variation"
    elif sim >= 0.60:
        rel = "related"
    else:
        rel = "distinct"

    return PatternComparison(
        pattern_id_a=p1.id,
        pattern_id_b=p2.id,
        is_identical=is_id,
        similarity=sim,
        distance=dist,
        relationship=rel,
    )


# =============================================================================
# Subsequence Pattern Repetition Detection
# =============================================================================

def find_repeated_subsequences(seq: List[str]) -> Dict[str, Any]:
    """Find repeated contiguous pattern subsequences (length >= 2) and coverage."""
    n = len(seq)
    if n < 4:
        return {
            "longest_subsequence": [],
            "longest_subsequence_len": 0,
            "longest_subsequence_count": 0,
            "repeated_blocks_coverage_pct": 0.0,
        }

    repeats: Dict[Tuple[str, ...], List[int]] = {}
    for k in range(2, n // 2 + 1):
        for i in range(n - k + 1):
            sub = tuple(seq[i:i+k])
            if sub not in repeats:
                repeats[sub] = []
            repeats[sub].append(i)

    actual_repeats = {k: v for k, v in repeats.items() if len(v) >= 2}

    if not actual_repeats:
        longest: Tuple[str, ...] = ()
        longest_len = 0
        longest_count = 0
    else:
        longest = max(actual_repeats.keys(), key=lambda k: (len(k), len(actual_repeats[k])))
        longest_len = len(longest)
        longest_count = len(actual_repeats[longest])

    covered_indices: Set[int] = set()
    for sub, idx_list in actual_repeats.items():
        k = len(sub)
        for start_idx in idx_list:
            for pos in range(start_idx, start_idx + k):
                covered_indices.add(pos)

    coverage_pct = round(len(covered_indices) / n * 100.0, 2)

    return {
        "longest_subsequence": list(longest),
        "longest_subsequence_len": longest_len,
        "longest_subsequence_count": longest_count,
        "repeated_blocks_coverage_pct": coverage_pct,
    }


# =============================================================================
# Material Reuse Ratio
# =============================================================================

def calculate_material_reuse_ratio(
    doc: AICompositionDoc,
    comparisons: Dict[Tuple[str, str], PatternComparison],
) -> float:
    """Calculate the proportion of playback time reusing already introduced material.

    For each sequence position i (from 1 to N-1), compare pattern S[i] against
    all previous patterns S[0..i-1]:
    - If S[i] is identical to an earlier pattern: 1.0 reuse.
    - If S[i] is a near-variation (sim >= 0.80): reuse weight = sim.
    - If S[i] is new (max sim < 0.80): 0.0 reuse.
    Returns weighted average across all sequence steps.
    """
    pat_map = {p.id: p for p in doc.patterns}
    seq = doc.sequence
    if len(seq) <= 1:
        return 0.0

    total_steps = sum(pat_map[pid].length_steps for pid in seq if pid in pat_map)
    if total_steps == 0:
        return 0.0

    reused_step_weight = 0.0
    seen_patterns: Set[str] = set()

    for i, pid in enumerate(seq):
        p_len = pat_map[pid].length_steps if pid in pat_map else 32
        if i == 0:
            seen_patterns.add(pid)
            continue  # The very first pattern is 100% newly introduced material

        # Check maximum similarity with any earlier pattern in seen_patterns
        max_sim = 0.0
        for prev_pid in seen_patterns:
            if pid == prev_pid:
                max_sim = 1.0
                break
            pair = (pid, prev_pid) if (pid, prev_pid) in comparisons else (prev_pid, pid)
            if pair in comparisons:
                cmp_res = comparisons[pair]
                if cmp_res.similarity > max_sim:
                    max_sim = cmp_res.similarity

        if max_sim == 1.0:
            weight = 1.0
        elif max_sim >= 0.80:
            weight = max_sim
        else:
            weight = 0.0  # Novel thematic section

        reused_step_weight += p_len * weight
        seen_patterns.add(pid)

    return round(reused_step_weight / total_steps, 4)


# =============================================================================
# Automatic Musical Form Deduction
# =============================================================================

def deduce_musical_form(
    doc: AICompositionDoc,
    comparisons: Dict[Tuple[str, str], PatternComparison],
) -> MusicalFormAnalysis:
    """Deduce human-readable musical form (e.g. INTRO - A - A' - B - A - OUTRO)."""
    patterns = {p.id: p for p in doc.patterns}
    seq = doc.sequence
    n = len(seq)

    # Note count per pattern to distinguish intro / outro textures
    p_notes_count = {
        pid: sum(len(evs) for evs in pat.channels.values())
        for pid, pat in patterns.items()
    }
    avg_notes = sum(p_notes_count.values()) / max(1, len(p_notes_count))

    theme_letters = ["A", "B", "C", "D", "E", "F", "G"]
    theme_idx = 0
    assigned_labels: Dict[str, str] = {}
    theme_representatives: Dict[str, str] = {}

    for i, pid in enumerate(seq):
        if pid in assigned_labels:
            continue

        # Intro detection (first position, sparse or labeled 'in...')
        if i == 0 and (pid.lower().startswith("in") or p_notes_count.get(pid, 0) < avg_notes * 0.7):
            assigned_labels[pid] = "INTRO"
            theme_representatives["INTRO"] = pid
            continue

        # Outro detection (near end, sparse or labeled 'out...')
        if i >= n - 2 and (pid.lower().startswith("out") or p_notes_count.get(pid, 0) < avg_notes * 0.7):
            assigned_labels[pid] = "OUTRO"
            theme_representatives["OUTRO"] = pid
            continue

        # Check similarity to existing theme representatives
        matched_theme: Optional[str] = None
        best_sim = 0.0
        for t_label, rep_pid in theme_representatives.items():
            if t_label in ("INTRO", "OUTRO"):
                continue
            pair = (pid, rep_pid) if (pid, rep_pid) in comparisons else (rep_pid, pid)
            if pair in comparisons:
                cmp_res = comparisons[pair]
                if cmp_res.is_identical:
                    matched_theme = t_label
                    best_sim = 1.0
                    break
                elif cmp_res.similarity >= 0.82 and cmp_res.similarity > best_sim:
                    matched_theme = t_label + "'"
                    best_sim = cmp_res.similarity

        if matched_theme:
            assigned_labels[pid] = matched_theme
        else:
            letter = theme_letters[theme_idx % len(theme_letters)]
            theme_idx += 1
            assigned_labels[pid] = letter
            theme_representatives[letter] = pid

    formal_sequence = [assigned_labels.get(pid, pid) for pid in seq]

    # Compact form summary
    compressed = []
    curr = formal_sequence[0] if formal_sequence else ""
    count = 1
    for item in formal_sequence[1:]:
        if item == curr:
            count += 1
        else:
            compressed.append(f"{count}x {curr}" if count > 1 else curr)
            curr = item
            count = 1
    if curr:
        compressed.append(f"{count}x {curr}" if count > 1 else curr)

    compact_form = " - ".join(compressed)
    unique_sections = list(dict.fromkeys(formal_sequence))

    # Form Archetype
    if formal_sequence.count("A") >= 4 and ("B" in formal_sequence or "C" in formal_sequence):
        archetype = "Rondo-like Episodic (A-B-A-C...)"
    elif len(unique_sections) <= 2:
        archetype = "Strophic / Iterative Loop"
    elif "INTRO" in formal_sequence and "OUTRO" in formal_sequence:
        archetype = "Framed Episodic (Intro - Themes - Outro)"
    elif "A" in formal_sequence and "B" in formal_sequence and "C" not in formal_sequence:
        archetype = "Binary / Dual Theme"
    else:
        archetype = "Multi-Thematic Chain"

    return MusicalFormAnalysis(
        pattern_labels=assigned_labels,
        formal_sequence=formal_sequence,
        compact_form=compact_form,
        unique_sections_count=len(unique_sections),
        archetype=archetype,
    )


# =============================================================================
# Domain Diversity Metrics (Melodic, Rhythmic, Harmonic)
# =============================================================================

def calculate_domain_diversities(doc: AICompositionDoc) -> Tuple[float, float, float]:
    """Calculate normalized melodic, rhythmic, and harmonic diversity scores in [0.0, 1.0]."""
    all_pitches: List[int] = []
    all_durations: List[int] = []
    all_sounding_intervals: List[int] = []

    for pat in doc.patterns:
        channel_steps = extract_pattern_channel_steps(pat)
        # 1. Notes & Rhythms
        for ch in range(1, 5):
            for ev in pat.channels.get(str(ch), []) + pat.channels.get(ch, []):
                dur = ev.duration
                all_durations.append(dur)
                is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                if not is_rest:
                    midi = note_name_to_midi(str(ev.note))
                    if midi is not None:
                        all_pitches.append(midi)

        # 2. Vertical Chords / Intervals
        for s in range(pat.length_steps):
            active_pitches = [
                channel_steps[c][s][0]
                for c in range(1, 5)
                if channel_steps[c][s] is not None and channel_steps[c][s][0] is not None
            ]
            if len(active_pitches) >= 2:
                for i in range(len(active_pitches)):
                    for j in range(i + 1, len(active_pitches)):
                        ic = abs(active_pitches[i] - active_pitches[j]) % 12
                        all_sounding_intervals.append(min(ic, 12 - ic))

    # Melodic Diversity: Shannon entropy of pitch distribution + range factor
    if not all_pitches:
        melodic_div = 0.0
    else:
        pitch_counts: Dict[int, int] = {}
        for p in all_pitches:
            pitch_counts[p] = pitch_counts.get(p, 0) + 1
        n_p = len(all_pitches)
        h_pitch = -sum((c / n_p) * math.log2(c / n_p) for c in pitch_counts.values())
        max_h = math.log2(max(2, len(pitch_counts)))
        entropy_score = (h_pitch / max_h) if max_h > 0 else 0.0
        pitch_range = max(all_pitches) - min(all_pitches)
        range_score = min(1.0, pitch_range / 36.0)  # 3 octaves saturated
        melodic_div = round(0.65 * entropy_score + 0.35 * range_score, 4)

    # Rhythmic Diversity: Shannon entropy of duration distribution
    if not all_durations:
        rhythmic_div = 0.0
    else:
        dur_counts: Dict[int, int] = {}
        for d in all_durations:
            dur_counts[d] = dur_counts.get(d, 0) + 1
        n_d = len(all_durations)
        h_dur = -sum((c / n_d) * math.log2(c / n_d) for c in dur_counts.values())
        max_h_dur = math.log2(max(2, len(dur_counts)))
        dur_score = (h_dur / max_h_dur) if max_h_dur > 0 else 0.0
        variety_factor = min(1.0, len(dur_counts) / 5.0)  # 5+ distinct duration values
        rhythmic_div = round(0.70 * dur_score + 0.30 * variety_factor, 4)

    # Harmonic Diversity: Shannon entropy of interval classes 0..6
    if not all_sounding_intervals:
        harmonic_div = 0.0
    else:
        ic_counts: Dict[int, int] = {}
        for ic in all_sounding_intervals:
            ic_counts[ic] = ic_counts.get(ic, 0) + 1
        n_ic = len(all_sounding_intervals)
        h_ic = -sum((c / n_ic) * math.log2(c / n_ic) for c in ic_counts.values())
        max_h_ic = math.log2(7)  # 7 interval classes (0..6)
        harmonic_div = round(min(1.0, h_ic / max_h_ic), 4)

    return melodic_div, rhythmic_div, harmonic_div


# =============================================================================
# Main Analysis Function
# =============================================================================

def analyze_composition_structure(doc: AICompositionDoc) -> DetailedStructureMetrics:
    """Perform comprehensive structural and repetition quality analysis on a composition."""
    patterns = {p.id: p for p in doc.patterns}
    seq = list(doc.sequence)
    seq_len = len(seq)

    # 1. Basic Structure
    p_lengths = {p.id: p.length_steps for p in doc.patterns}
    total_steps = sum(p_lengths.get(pid, 32) for pid in seq)
    pattern_occ: Dict[str, int] = {}
    for pid in seq:
        pattern_occ[pid] = pattern_occ.get(pid, 0) + 1

    unique_patterns_in_seq = len(pattern_occ)
    repetition_ratio = round(1.0 - (unique_patterns_in_seq / seq_len), 4) if seq_len > 0 else 0.0
    unique_pattern_ratio = round(unique_patterns_in_seq / max(1, seq_len), 4) if seq_len > 0 else 0.0

    # 2. Pairwise Pattern Comparisons & Variation Detection
    pat_list = doc.patterns
    comparisons: Dict[Tuple[str, str], PatternComparison] = {}
    near_identical_pairs: List[Tuple[str, str, float]] = []
    identical_pairs: List[Tuple[str, str]] = []
    variation_patterns: Set[str] = set()
    variation_pairs_list: List[Tuple[str, str, float]] = []

    # Check explicit variation declarations first
    for p in doc.patterns:
        if getattr(p, "variation_of", None) and p.variation_of in patterns:
            variation_patterns.add(p.id)

    for i in range(len(pat_list)):
        for j in range(i + 1, len(pat_list)):
            p1, p2 = pat_list[i], pat_list[j]
            cmp_res = compare_patterns(p1, p2)
            comparisons[(p1.id, p2.id)] = cmp_res
            comparisons[(p2.id, p1.id)] = cmp_res

            if cmp_res.is_identical:
                identical_pairs.append((p1.id, p2.id))
            elif cmp_res.similarity >= 0.80:
                near_identical_pairs.append((p1.id, p2.id, cmp_res.similarity))

            # Variation detection: thematic kinship (0.70 <= sim < 0.99)
            if 0.70 <= cmp_res.similarity < 0.99:
                p1_is_var = getattr(p1, "variation_of", None) == p2.id or any(s in p1.id.lower() for s in ("var", "2", "'"))
                p2_is_var = getattr(p2, "variation_of", None) == p1.id or any(s in p2.id.lower() for s in ("var", "2", "'"))
                var_id = p2.id if (p2_is_var or not p1_is_var) else p1.id
                base_id = p1.id if var_id == p2.id else p2.id
                variation_patterns.add(var_id)
                variation_pairs_list.append((var_id, base_id, cmp_res.similarity))

    distinct_musical_patterns_count = len(doc.patterns) - len(identical_pairs)
    near_identical_patterns_count = len(near_identical_pairs)
    variation_count = len(variation_patterns)
    variation_ratio = round(variation_count / max(1, len(doc.patterns)), 4)
    variation_similarity = (
        round(sum(p[2] for p in variation_pairs_list) / len(variation_pairs_list), 4)
        if variation_pairs_list else 0.0
    )

    # 3. Transitions & Fills
    unique_trans_set: Set[Tuple[str, str]] = set()
    trans_counts: Dict[Tuple[str, str], int] = {}
    for i in range(seq_len - 1):
        bigram = (seq[i], seq[i+1])
        unique_trans_set.add(bigram)
        trans_counts[bigram] = trans_counts.get(bigram, 0) + 1

    n_trans = max(1, seq_len - 1)
    trans_entropy = -sum((cnt / n_trans) * math.log2(cnt / n_trans) for cnt in trans_counts.values())

    # Detect Transition / Fill patterns
    has_long_patterns = any(p.length_steps >= 32 for p in doc.patterns)
    fill_patterns: Set[str] = set()
    for p in doc.patterns:
        role = getattr(p, "role", None)
        if role in ("fill", "transition"):
            fill_patterns.add(p.id)
        elif any(p.id.lower().startswith(prefix) for prefix in ("fill", "trans", "pass", "run")):
            fill_patterns.add(p.id)
        elif has_long_patterns and p.length_steps <= 16:
            fill_patterns.add(p.id)
    transition_fill_count = len(fill_patterns)

    # 4. Texture & Channel Activity
    pat_active_channels: Dict[str, Set[int]] = {}
    active_dist: Dict[str, int] = {"1_ch": 0, "2_ch": 0, "3_ch": 0, "4_ch": 0}

    for p in doc.patterns:
        active_set: Set[int] = set()
        has_zero = any(str(k).strip() == "0" for k in p.channels.keys())
        for ch_k, evs in p.channels.items():
            ch_idx = normalize_channel_idx(ch_k, has_zero)
            for ev in evs:
                if ev.note is not None and str(ev.note).upper() not in ("---", "REST", "OFF", "SIL", ""):
                    active_set.add(ch_idx)
                    break
        pat_active_channels[p.id] = active_set
        act_cnt = min(4, max(1, len(active_set)))
        key = f"{act_cnt}_ch"
        active_dist[key] = active_dist.get(key, 0) + 1

    texture_changes = 0
    for i in range(seq_len - 1):
        if pat_active_channels.get(seq[i], set()) != pat_active_channels.get(seq[i+1], set()):
            texture_changes += 1

    # 5. Subsequences & Material Reuse
    subseq_data = find_repeated_subsequences(seq)
    material_reuse_ratio = calculate_material_reuse_ratio(doc, comparisons)

    # 6. Domain Diversities & Structural Novelty
    mel_div, rhythm_div, harm_div = calculate_domain_diversities(doc)

    midpoint = seq_len // 2
    seen_first_half = set(seq[:midpoint])
    second_half = seq[midpoint:]
    novel_second_half = sum(
        1 for p in second_half
        if (p not in seen_first_half) or (p in variation_patterns) or (p in fill_patterns)
    )
    structural_novelty = round(novel_second_half / max(1, len(second_half)), 4) if second_half else 0.0

    # 7. Form Deduction & Sections
    form_res = deduce_musical_form(doc, comparisons)
    if doc.form_plan and doc.form_plan.sections:
        sections_count = len(doc.form_plan.sections)
    else:
        sections_count = form_res.unique_sections_count

    # Calculate actual runtime duration
    from atari_music.ai.analysis import calculate_composition_duration
    dur_sec = calculate_composition_duration(doc)

    return DetailedStructureMetrics(
        title=doc.metadata.title or "Untitled",
        bpm=doc.metadata.bpm,
        duration_seconds=round(dur_sec, 2),
        pattern_count=len(doc.patterns),
        pattern_lengths=p_lengths,
        sequence_length=seq_len,
        total_steps=total_steps,
        pattern_occurrences=pattern_occ,
        repetition_ratio=repetition_ratio,
        unique_pattern_ratio=unique_pattern_ratio,
        unique_transitions_count=len(unique_trans_set),
        unique_transitions=sorted(list(unique_trans_set)),
        transition_entropy=round(trans_entropy, 3),
        transition_fill_count=transition_fill_count,
        longest_repeated_subsequence_len=subseq_data["longest_subsequence_len"],
        longest_repeated_subsequence=subseq_data["longest_subsequence"],
        longest_repeated_subsequence_count=subseq_data["longest_subsequence_count"],
        repeated_subsequences_coverage_pct=subseq_data["repeated_blocks_coverage_pct"],
        distinct_musical_patterns_count=distinct_musical_patterns_count,
        near_identical_patterns_count=near_identical_patterns_count,
        near_identical_pairs=near_identical_pairs,
        material_reuse_ratio=material_reuse_ratio,
        variation_count=variation_count,
        variation_ratio=variation_ratio,
        variation_pairs=variation_pairs_list,
        variation_similarity=variation_similarity,
        texture_changes_count=texture_changes,
        active_channels_distribution=active_dist,
        melodic_diversity=mel_div,
        rhythmic_diversity=rhythm_div,
        harmonic_diversity=harm_div,
        structural_novelty=structural_novelty,
        sections_count=sections_count,
        form=form_res,
    )

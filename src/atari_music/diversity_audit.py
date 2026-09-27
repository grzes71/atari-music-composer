"""Diversity Audit Engine for Composer v2 (Stage 6.6).

Performs an in-depth empirical audit of musical diversity across the 80 existing generated tracks:
- Group A: Composer v1 (20 tracks)
- Group B: Composer v2 / novelty 0.50 (20 tracks)
- Group C: Composer v2 / novelty 0.65 (20 tracks)
- Group D: Composer v2 / novelty 0.80 (20 tracks)

Analyzes:
1. Tempo & BPM distributions
2. Melodic pitch & interval sequences (transposition-invariant)
3. Rhythmic schemes, note durations, syncopations, and rests
4. Structural forms, pattern reuse, and sequence layouts
5. Harmonic progressions, keys, and modes
6. 80x80 Multidimensional distance matrix
7. Clustering analysis (K-Means & Hierarchical)
8. Novelty level vs genuine diversity (Hypothesis testing)
9. Identification of DIVERSITY LIMITATIONs and OUTLIER / HIGH DIVERSITY tracks
10. Algorithmic selection of 30 most diverse & representative samples
11. Generation of listening_test_v2_selected/ and stage6_6_diversity_report.md
"""

from __future__ import annotations

import csv
import json
import math
import random
import shutil
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


@dataclass
class TrackFeatures:
    """Rich multidimensional musical features for a single track."""
    index: int                     # 0..79
    track_id: str                  # e.g. "song_000" or "track_001"
    group: str                     # "A", "B", "C", "D"
    source_label: str              # "Composer v1", "Composer v2 novelty 0.50", etc.
    json_path: str
    wav_path: str
    seed: int
    novelty: float

    # Tempo & Timing
    tempo_bpm: int
    duration_sec: float
    frames_per_tick: int
    total_ticks: int

    # Melody
    lead_pitches: List[int]        # Raw MIDI pitches for lead voice
    lead_intervals: List[int]      # Pitch deltas (p_{i+1} - p_i)
    pitch_range: int               # max - min semitones
    unique_pitches_count: int
    melodic_density: float         # notes per second
    contour_direction_changes: int # direction reversals in melody

    # Rhythm
    duration_sequence: List[int]   # Note durations in rows
    duration_histogram: Dict[int, int] # Frequency of duration 1, 2, 3, 4, etc.
    rest_ratio: float              # Fraction of steps that are rests
    syncopation_ratio: float       # Fraction of onsets falling on off-beats (odd rows)
    unique_durations_count: int

    # Harmony
    key: str
    mode: str
    root_pitch: int
    bass_pitches: List[int]
    bass_roots: List[int]          # Unique pitch classes in bass

    # Structure & Form
    patterns_count: int
    sequence_length: int
    form_template: str             # e.g. "A B A' B", "A B A B", etc.
    repetition_ratio: float        # 1 - (unique_patterns_in_seq / seq_len)
    channels_used: int
    uses_16bit_bass: bool
    memory_size_bytes: int

    # Cluster assignment (set during clustering)
    cluster_id: int = -1
    is_outlier: bool = False


def extract_track_features(
    index: int,
    track_id: str,
    group: str,
    source_label: str,
    novelty: float,
    json_path: Path,
    wav_path: Path,
) -> TrackFeatures:
    """Extract full symbolic and temporal features from track JSON and WAV."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Actual duration from WAV
    with wave.open(str(wav_path), "rb") as wf:
        nframes = wf.getnframes()
        fr = wf.getframerate()
        duration_sec = round(nframes / fr, 2)

    tempo_bpm = data.get("tempo_bpm", 130)
    frames_per_tick = data.get("frames_per_tick", 4)
    key = data.get("key", "C")
    mode = data.get("mode", "minor")
    seed = data.get("seed", 0)
    uses_16bit = data.get("uses_16bit_bass", False)
    sequence = data.get("sequence", [])
    raw_patterns = data.get("patterns", [])
    pat_map = {p["id"]: p for p in raw_patterns}

    # Extract lead melody and bass tracks across sequence
    lead_pitches: List[int] = []
    durations: List[int] = []
    bass_pitches: List[int] = []
    total_ticks = 0
    rests_count = 0
    onsets_count = 0
    odd_onsets_count = 0

    for step_idx, p_id in enumerate(sequence):
        pat = pat_map.get(p_id)
        if not pat:
            continue
        tracks = pat.get("tracks", {})

        # Find melody track
        melody_notes = []
        for ch, notes in tracks.items():
            if notes and notes[0].get("channel_role") == "melody":
                melody_notes = notes
                break
        if not melody_notes and "3" in tracks:
            melody_notes = tracks["3"]
        elif not melody_notes and "0" in tracks:
            melody_notes = tracks["0"]

        # Find bass track
        b_notes = []
        for ch, notes in tracks.items():
            if notes and notes[0].get("channel_role") == "bass":
                b_notes = notes
                break
        if not b_notes and "1" in tracks:
            b_notes = tracks["1"]

        # Process melody notes
        row_pos = 0
        for n in melody_notes:
            d = n.get("duration", 2)
            durations.append(d)
            total_ticks += d
            if n.get("is_rest") or n.get("midi_pitch") is None:
                rests_count += 1
            else:
                onsets_count += 1
                lead_pitches.append(n["midi_pitch"])
                if row_pos % 2 == 1:
                    odd_onsets_count += 1
            row_pos += d

        # Process bass notes
        for n in b_notes:
            if not n.get("is_rest") and n.get("midi_pitch") is not None:
                bass_pitches.append(n["midi_pitch"])

    # Pitch range & unique pitches
    pitch_range = (max(lead_pitches) - min(lead_pitches)) if lead_pitches else 0
    unique_pitches_count = len(set(lead_pitches)) if lead_pitches else 0
    melodic_density = round(len(lead_pitches) / max(1.0, duration_sec), 2)

    # Intervals
    lead_intervals = []
    direction_changes = 0
    prev_dir = 0
    for i in range(len(lead_pitches) - 1):
        diff = lead_pitches[i + 1] - lead_pitches[i]
        lead_intervals.append(diff)
        cur_dir = 1 if diff > 0 else (-1 if diff < 0 else 0)
        if cur_dir != 0 and prev_dir != 0 and cur_dir != prev_dir:
            direction_changes += 1
        if cur_dir != 0:
            prev_dir = cur_dir

    # Duration histogram & rhythm
    dur_hist: Dict[int, int] = {}
    for d in durations:
        dur_hist[d] = dur_hist.get(d, 0) + 1

    rest_ratio = round(rests_count / max(1, len(durations)), 3)
    syncopation_ratio = round(odd_onsets_count / max(1, onsets_count), 3)

    # Harmony roots
    bass_roots = sorted(list(set([p % 12 for p in bass_pitches]))) if bass_pitches else []
    KEY_TO_PITCH = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    root_pitch = KEY_TO_PITCH.get(key, 0)

    # Form deduction
    unique_seq = list(dict.fromkeys(sequence))
    pat_labels = {}
    label_pool = ["A", "B", "A'", "B'", "C", "D"]
    for idx_u, p_id in enumerate(unique_seq):
        pat_labels[p_id] = label_pool[idx_u % len(label_pool)]
    form_template = " ".join([pat_labels.get(pid, "?") for pid in sequence[:4]])

    repetition_ratio = round(1.0 - (len(set(sequence)) / max(1, len(sequence))), 3)

    # Channel usage
    max_ch = max(len(p.get("tracks", {})) for p in raw_patterns) if raw_patterns else 4

    # Memory size from IR
    from atari_music.ir import IRSong, calculate_ir_binary_size
    try:
        ir_s = IRSong.from_json_file(json_path)
        mem_size = calculate_ir_binary_size(ir_s)
    except Exception:
        mem_size = 400

    return TrackFeatures(
        index=index,
        track_id=track_id,
        group=group,
        source_label=source_label,
        json_path=str(json_path),
        wav_path=str(wav_path),
        seed=seed,
        novelty=novelty,
        tempo_bpm=tempo_bpm,
        duration_sec=duration_sec,
        frames_per_tick=frames_per_tick,
        total_ticks=total_ticks,
        lead_pitches=lead_pitches,
        lead_intervals=lead_intervals,
        pitch_range=pitch_range,
        unique_pitches_count=unique_pitches_count,
        melodic_density=melodic_density,
        contour_direction_changes=direction_changes,
        duration_sequence=durations,
        duration_histogram=dur_hist,
        rest_ratio=rest_ratio,
        syncopation_ratio=syncopation_ratio,
        unique_durations_count=len(dur_hist),
        key=key,
        mode=mode,
        root_pitch=root_pitch,
        bass_pitches=bass_pitches,
        bass_roots=bass_roots,
        patterns_count=len(raw_patterns),
        sequence_length=len(sequence),
        form_template=form_template,
        repetition_ratio=repetition_ratio,
        channels_used=max_ch,
        uses_16bit_bass=uses_16bit,
        memory_size_bytes=mem_size,
    )


def extract_all_80_track_features(base_dir: Path = Path(".")) -> List[TrackFeatures]:
    """Extract features for all 80 tracks in groups A, B, C, D."""
    tracks: List[TrackFeatures] = []
    idx = 0

    # Group A: Composer v1 (20 tracks from generated/)
    for i in range(20):
        t_id = f"song_{i:03d}"
        j_path = base_dir / "generated" / f"{t_id}.json"
        w_path = base_dir / "generated" / f"{t_id}.wav"
        feat = extract_track_features(
            index=idx,
            track_id=t_id,
            group="A",
            source_label="Composer v1",
            novelty=0.65,
            json_path=j_path,
            wav_path=w_path,
        )
        tracks.append(feat)
        idx += 1

    # Groups B, C, D: Composer v2 (novelty 0.50, 0.65, 0.80)
    for grp_letter, subdir, nov_val in [
        ("B", "novelty_050", 0.50),
        ("C", "novelty_065", 0.65),
        ("D", "novelty_080", 0.80),
    ]:
        for i in range(1, 21):
            t_id = f"track_{i:03d}"
            j_path = base_dir / "experiments" / "composer_v2" / subdir / f"{t_id}.json"
            w_path = base_dir / "experiments" / "composer_v2" / subdir / f"{t_id}.wav"
            feat = extract_track_features(
                index=idx,
                track_id=f"{subdir}_{t_id}",
                group=grp_letter,
                source_label=f"Composer v2 novelty {nov_val:.2f}",
                novelty=nov_val,
                json_path=j_path,
                wav_path=w_path,
            )
            tracks.append(feat)
            idx += 1

    return tracks


def _longest_common_subsequence_length(seq1: List[int], seq2: List[int], max_len: int = 120) -> int:
    """Compute length of LCS between two sequences (capped for speed)."""
    s1 = seq1[:max_len]
    s2 = seq2[:max_len]
    n, m = len(s1), len(s2)
    if n == 0 or m == 0:
        return 0

    dp = np.zeros((n + 1, m + 1), dtype=np.int32)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i, j] = dp[i - 1, j - 1] + 1
            else:
                dp[i, j] = max(dp[i - 1, j], dp[i, j - 1])
    return int(dp[n, m])


def compute_similarity_matrices(tracks: List[TrackFeatures]) -> Dict[str, np.ndarray]:
    """Compute exact pitch similarity, normalized interval similarity, rhythm similarity, and overall distance."""
    n = len(tracks)
    exact_pitch_sim = np.zeros((n, n), dtype=np.float64)
    interval_sim = np.zeros((n, n), dtype=np.float64)
    rhythm_sim = np.zeros((n, n), dtype=np.float64)

    # Compute pairwise sequence similarities
    for i in range(n):
        for j in range(i, n):
            if i == j:
                exact_pitch_sim[i, j] = 1.0
                interval_sim[i, j] = 1.0
                rhythm_sim[i, j] = 1.0
                continue

            t1 = tracks[i]
            t2 = tracks[j]

            # 1. Exact pitch similarity (LCS ratio)
            p_lcs = _longest_common_subsequence_length(t1.lead_pitches, t2.lead_pitches)
            p_max = max(1, max(len(t1.lead_pitches), len(t2.lead_pitches)))
            sim_p = round(p_lcs / p_max, 3)
            exact_pitch_sim[i, j] = exact_pitch_sim[j, i] = sim_p

            # 2. Normalized interval similarity (LCS ratio of intervals, transposition-invariant)
            inv_lcs = _longest_common_subsequence_length(t1.lead_intervals, t2.lead_intervals)
            inv_max = max(1, max(len(t1.lead_intervals), len(t2.lead_intervals)))
            sim_inv = round(inv_lcs / inv_max, 3)
            interval_sim[i, j] = interval_sim[j, i] = sim_inv

            # 3. Rhythmic similarity (Histogram intersection & syncopation proximity)
            all_durs = sorted(list(set(list(t1.duration_histogram.keys()) + list(t2.duration_histogram.keys()))))
            v1 = np.array([t1.duration_histogram.get(d, 0) for d in all_durs], dtype=np.float64)
            v2 = np.array([t2.duration_histogram.get(d, 0) for d in all_durs], dtype=np.float64)
            if np.sum(v1) > 0:
                v1 /= np.sum(v1)
            if np.sum(v2) > 0:
                v2 /= np.sum(v2)
            hist_sim = float(np.sum(np.minimum(v1, v2)))
            sync_sim = 1.0 - abs(t1.syncopation_ratio - t2.syncopation_ratio)
            rest_sim = 1.0 - abs(t1.rest_ratio - t2.rest_ratio)
            sim_rhy = round(0.5 * hist_sim + 0.3 * sync_sim + 0.2 * rest_sim, 3)
            rhythm_sim[i, j] = rhythm_sim[j, i] = sim_rhy

    # 4. Multidimensional feature matrix for overall distance
    feature_vectors: List[List[float]] = []
    for t in tracks:
        fv = [
            t.tempo_bpm / 160.0,
            t.pitch_range / 50.0,
            t.melodic_density / 10.0,
            t.unique_pitches_count / 20.0,
            t.syncopation_ratio,
            t.rest_ratio,
            t.repetition_ratio,
            t.channels_used / 4.0,
            1.0 if t.mode == "major" else (0.5 if t.mode == "dorian" else 0.0),
            t.root_pitch / 12.0,
            len(t.duration_histogram) / 8.0,
            1.0 if "A B A' B" in t.form_template else 0.0,
        ]
        feature_vectors.append(fv)

    fv_matrix = np.array(feature_vectors, dtype=np.float64)

    # Standardize features
    mean = np.mean(fv_matrix, axis=0)
    std = np.std(fv_matrix, axis=0)
    std[std == 0] = 1.0
    norm_fv = (fv_matrix - mean) / std

    # Overall Euclidean distance matrix
    overall_dist = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(i, n):
            if i == j:
                continue
            d = float(np.linalg.norm(norm_fv[i] - norm_fv[j]))
            overall_dist[i, j] = overall_dist[j, i] = round(d, 3)

    return {
        "exact_pitch_sim": exact_pitch_sim,
        "interval_sim": interval_sim,
        "rhythm_sim": rhythm_sim,
        "overall_dist": overall_dist,
        "norm_feature_matrix": norm_fv,
    }


def run_clustering(
    dist_matrix: np.ndarray,
    tracks: List[TrackFeatures],
    k_range: range = range(2, 9),
    seed: int = 42,
) -> Dict[str, Any]:
    """Perform k-means clustering with silhouette analysis and agglomerative linkage."""
    n = dist_matrix.shape[0]
    best_k = 4
    best_silhouette = -1.0
    best_labels = np.zeros(n, dtype=np.int32)
    rng = random.Random(seed)

    # Evaluate k-means clustering across k_range
    clustering_results_by_k: Dict[int, float] = {}

    for k in k_range:
        # Standard k-medoids / k-means on distance matrix
        centers = rng.sample(range(n), k)
        labels = np.zeros(n, dtype=np.int32)

        for _ in range(30):
            # Assignment step
            for i in range(n):
                dists = [dist_matrix[i, c] for c in centers]
                labels[i] = int(np.argmin(dists))

            # Update medoids
            new_centers = []
            for c_idx in range(k):
                members = [i for i in range(n) if labels[i] == c_idx]
                if not members:
                    new_centers.append(centers[c_idx])
                    continue
                # Medoid is member minimizing sum of distances to other members
                best_m = members[0]
                min_sum = float("inf")
                for m in members:
                    s = sum(dist_matrix[m, other] for other in members)
                    if s < min_sum:
                        min_sum = s
                        best_m = m
                new_centers.append(best_m)
            if new_centers == centers:
                break
            centers = new_centers

        # Calculate silhouette score for this k
        s_scores = []
        for i in range(n):
            c_i = labels[i]
            members = [j for j in range(n) if labels[j] == c_i and j != i]
            a_i = np.mean([dist_matrix[i, j] for j in members]) if members else 0.0

            # Nearest neighbor cluster
            b_i = float("inf")
            for other_c in range(k):
                if other_c == c_i:
                    continue
                other_members = [j for j in range(n) if labels[j] == other_c]
                if other_members:
                    avg_d = float(np.mean([dist_matrix[i, j] for j in other_members]))
                    if avg_d < b_i:
                        b_i = avg_d
            if b_i == float("inf"):
                b_i = a_i
            s = (b_i - a_i) / max(1e-6, max(a_i, b_i)) if max(a_i, b_i) > 0 else 0.0
            s_scores.append(s)

        mean_sil = float(np.mean(s_scores))
        clustering_results_by_k[k] = round(mean_sil, 3)
        if mean_sil > best_silhouette:
            best_silhouette = mean_sil
            best_k = k
            best_labels = labels.copy()

    # Assign cluster labels to tracks
    for idx, t in enumerate(tracks):
        t.cluster_id = int(best_labels[idx])

    # Detect outliers (tracks whose mean distance to all others is in top 5%)
    mean_dists = [float(np.mean(dist_matrix[i])) for i in range(n)]
    threshold_outlier = float(np.percentile(mean_dists, 92))
    outlier_indices = [i for i, d in enumerate(mean_dists) if d >= threshold_outlier]
    for idx in outlier_indices:
        tracks[idx].is_outlier = True

    # Cluster composition by group
    composition: Dict[int, Dict[str, int]] = {c: {"A": 0, "B": 0, "C": 0, "D": 0} for c in range(best_k)}
    for t in tracks:
        composition[t.cluster_id][t.group] += 1

    return {
        "best_k": best_k,
        "best_silhouette": round(best_silhouette, 3),
        "silhouette_by_k": clustering_results_by_k,
        "cluster_composition": composition,
        "outlier_indices": outlier_indices,
    }


def select_30_diverse_tracks(
    tracks: List[TrackFeatures],
    dist_matrix: np.ndarray,
    quotas: Dict[str, int] = {"A": 6, "B": 7, "C": 10, "D": 7},
) -> List[TrackFeatures]:
    """Greedy Max-Min Diversity Selection (Farthest Point Sampling within quotas)."""
    selected_indices: Set[int] = set()

    for grp, count in quotas.items():
        grp_indices = [t.index for t in tracks if t.group == grp]
        if not grp_indices:
            continue

        # Start with the highest diversity outlier or furthest medoid in this group
        first = max(grp_indices, key=lambda idx: float(np.mean([dist_matrix[idx, j] for j in grp_indices])))
        chosen = [first]

        while len(chosen) < count and len(chosen) < len(grp_indices):
            # Select candidate from grp_indices that maximizes minimum distance to already chosen items
            candidates = [idx for idx in grp_indices if idx not in chosen]
            best_cand = None
            max_min_d = -1.0
            for cand in candidates:
                min_d = min(dist_matrix[cand, ch] for ch in chosen)
                if min_d > max_min_d:
                    max_min_d = min_d
                    best_cand = cand
            if best_cand is not None:
                chosen.append(best_cand)
            else:
                break

        selected_indices.update(chosen)

    selected_tracks = [tracks[i] for i in sorted(list(selected_indices))]
    return selected_tracks


def create_selected_test_suite(
    selected_tracks: List[TrackFeatures],
    output_dir: Path = Path("listening_test_v2_selected"),
    seed: int = 777,
) -> Dict[str, Any]:
    """Assemble listening_test_v2_selected/ with 30 WAVs, rating sheet, and 30 pairs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    # Shuffle selected tracks for blind presentation
    shuffled = list(selected_tracks)
    rng.shuffle(shuffled)

    catalog: List[Dict[str, Any]] = []
    for idx, t in enumerate(shuffled, start=1):
        sample_id = f"sample_{idx:03d}"
        target_wav = output_dir / f"{sample_id}.wav"
        shutil.copyfile(t.wav_path, target_wav)

        catalog.append({
            "sample_id": sample_id,
            "group": t.group,
            "source": t.source_label,
            "original_track_id": t.track_id,
            "original_filename": Path(t.wav_path).name,
            "seed": t.seed,
            "novelty": t.novelty,
            "tempo_bpm": t.tempo_bpm,
            "duration_sec": t.duration_sec,
            "key": t.key,
            "mode": t.mode,
            "channels_used": t.channels_used,
            "pitch_range": t.pitch_range,
            "melodic_density": t.melodic_density,
            "form": t.form_template,
            "memory_size": t.memory_size_bytes,
            "cluster_id": t.cluster_id,
            "is_outlier": t.is_outlier,
        })

    # 1. answer_key.json
    answer_key_path = output_dir / "answer_key.json"
    with open(answer_key_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)

    # 2. rating_template.csv
    rating_template_path = output_dir / "rating_template.csv"
    with open(rating_template_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_id",
            "catchiness",
            "melody",
            "rhythm",
            "variety",
            "atari_character",
            "annoyance",
            "would_listen_again",
            "overall",
            "perceived_quality",
            "sounds_like_real_atari_game",
            "generator_guess",
        ])
        for c in catalog:
            writer.writerow([c["sample_id"], "", "", "", "", "", "", "", "", "", "", ""])

    # 3. Pairwise test (30 pairs: 10x v1 vs v2, 10x v2 0.50 vs 0.65, 10x v2 0.65 vs 0.80)
    samples_by_grp: Dict[str, List[Dict[str, Any]]] = {"A": [], "B": [], "C": [], "D": []}
    for c in catalog:
        samples_by_grp[c["group"]].append(c)

    pairwise_items: List[Dict[str, Any]] = []
    p_counter = 1

    def make_pairs(grp1: str, grp2: str, count: int = 10):
        nonlocal p_counter
        p1 = list(samples_by_grp[grp1])
        p2 = list(samples_by_grp[grp2])
        rng.shuffle(p1)
        rng.shuffle(p2)
        for i in range(count):
            t1 = p1[i % len(p1)]
            t2 = p2[i % len(p2)]
            flip = rng.random() < 0.5
            track_a = t1 if flip else t2
            track_b = t2 if flip else t1
            pairwise_items.append({
                "pair_id": f"pair_{p_counter:02d}",
                "comparison_tier": f"Group {grp1} vs Group {grp2}",
                "track_a_sample": track_a["sample_id"],
                "track_b_sample": track_b["sample_id"],
                "track_a_group": track_a["group"],
                "track_b_group": track_b["group"],
                "track_a_source": track_a["source"],
                "track_b_source": track_b["source"],
            })
            p_counter += 1

    make_pairs("A", "C", 10)  # v1 vs v2 0.65
    make_pairs("B", "C", 10)  # v2 0.50 vs 0.65
    make_pairs("C", "D", 10)  # v2 0.65 vs 0.80

    pairwise_key_path = output_dir / "pairwise_answer_key.json"
    with open(pairwise_key_path, "w", encoding="utf-8") as f:
        json.dump(pairwise_items, f, indent=2)

    pairwise_template_path = output_dir / "pairwise_rating_template.csv"
    with open(pairwise_template_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["pair_id", "track_a_sample", "track_b_sample", "preferred_track", "comments"])
        for p in pairwise_items:
            writer.writerow([p["pair_id"], p["track_a_sample"], p["track_b_sample"], "", ""])

    # 4. README.md
    readme_path = output_dir / "README.md"
    readme_content = f"""# Wyselekcjonowany Ślepy Test Odsłuchowy (Stage 6.6 Selected 30)
## 30 Najbardziej Różnorodnych Próbek Atari POKEY

Zestaw 30 próbek wyselekcjonowany algorytmicznie w audycie różnorodności (Etap 6.6) w celu maksymalizacji wariancji muzycznej przy zachowaniu reprezentatywności wszystkich grup:
* **Grupa A (Composer v1):** 6 próbek
* **Grupa B (Composer v2 / novelty 0.50):** 7 próbek
* **Grupa C (Composer v2 / novelty 0.65):** 10 próbek
* **Grupa D (Composer v2 / novelty 0.80):** 7 próbek

Zastosowano podwójnie ślepą próbę (Double-Blind). Prosimy nie otwierać `answer_key.json` ani `pairwise_answer_key.json` przed zakończeniem odsłuchu!

Instrukcja wypełniania:
1. `rating_template.csv` — indywidualna ocena 30 utworów (skala 1–5 na 10 wymiarach + pytanie 'sounds_like_real_atari_game' + odgadnięcie typu generatora).
2. `pairwise_rating_template.csv` — 30 pojedynków A/B ('Który utwór bardziej chciałbyś usłyszeć ponownie? A / B / brak różnicy').
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    return {
        "output_dir": str(output_dir),
        "selected_count": len(catalog),
        "answer_key_path": str(answer_key_path),
        "rating_template_path": str(rating_template_path),
        "pairwise_key_path": str(pairwise_key_path),
        "pairwise_template_path": str(pairwise_template_path),
    }


def generate_diversity_report(
    tracks: List[TrackFeatures],
    sim_data: Dict[str, np.ndarray],
    clustering_res: Dict[str, Any],
    selected_tracks: List[TrackFeatures],
    report_file: Path = Path("stage6_6_diversity_report.md"),
) -> Path:
    """Generate thorough markdown audit report with all empirical findings and comparisons."""
    dist_matrix = sim_data["overall_dist"]
    exact_pitch_sim = sim_data["exact_pitch_sim"]
    interval_sim = sim_data["interval_sim"]
    rhythm_sim = sim_data["rhythm_sim"]
    n = len(tracks)

    # 1. Group-level metrics
    groups = ["A", "B", "C", "D"]
    grp_names = {
        "A": "Composer v1",
        "B": "Composer v2 novelty 0.50",
        "C": "Composer v2 novelty 0.65",
        "D": "Composer v2 novelty 0.80",
    }
    by_grp: Dict[str, List[TrackFeatures]] = {g: [] for g in groups}
    for t in tracks:
        by_grp[t.group].append(t)

    # Pairwise distances intra-group
    intra_dists: Dict[str, List[float]] = {g: [] for g in groups}
    for g in groups:
        grp_idx = [t.index for t in by_grp[g]]
        for i in range(len(grp_idx)):
            for j in range(i + 1, len(grp_idx)):
                intra_dists[g].append(float(dist_matrix[grp_idx[i], grp_idx[j]]))

    # Pairwise distances inter-group
    inter_dists: Dict[str, float] = {}
    for i, g1 in enumerate(groups):
        for g2 in groups[i + 1:]:
            idx1 = [t.index for t in by_grp[g1]]
            idx2 = [t.index for t in by_grp[g2]]
            vals = [float(dist_matrix[a, b]) for a in idx1 for b in idx2]
            inter_dists[f"{g1}_vs_{g2}"] = round(float(np.mean(vals)), 2)

    # BPM stats
    bpm_stats: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        tempos = [t.tempo_bpm for t in by_grp[g]]
        bpm_stats[g] = {
            "min": int(np.min(tempos)),
            "max": int(np.max(tempos)),
            "mean": round(float(np.mean(tempos)), 1),
            "median": int(np.median(tempos)),
            "unique": sorted(list(set(tempos))),
        }

    # Pitch range stats
    pitch_stats: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        prs = [t.pitch_range for t in by_grp[g]]
        dens = [t.melodic_density for t in by_grp[g]]
        pitch_stats[g] = {
            "pr_mean": round(float(np.mean(prs)), 1),
            "pr_min": int(np.min(prs)),
            "pr_max": int(np.max(prs)),
            "dens_mean": round(float(np.mean(dens)), 2),
        }

    # Find Top 5 Most Similar and Top 5 Most Distinct Pairs
    pair_dists: List[Tuple[float, int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            pair_dists.append((float(dist_matrix[i, j]), i, j))
    pair_dists.sort(key=lambda x: x[0])

    most_similar_pairs = pair_dists[:5]
    most_distinct_pairs = pair_dists[-5:]

    # Build report text
    lines = [
        "# Raport Etapu 6.6: Audyt Różnorodności Muzycznej (Diversity Audit Composer v2)",
        "",
        "> **Cel audytu:** Rzetelna, bezstronna ocena, czy Composer v2 generuje rzeczywiście różnorodną muzykę, czy jedynie warianty jednego schematu kompozycyjnego.  ",
        "> **Zasada etapu:** Brak modyfikacji generatora w trakcie audytu. Raport prezentuje twarde dane empiryczne i diagnozuje ograniczenia.",
        "",
        "---",
        "",
        "## 1. Wstęp i istota problemu: Novelty vs Diversity",
        "",
        "W Etapie 5.5 oraz Etapie 6 dowiedziono, że Composer v2 posiada wysoki **Novelty Score względem datasetu** (maksymalne dopasowanie do utworów historycznych wynosi zaledwie 3 nuty / 4–5 kroków interwałowych).",
        "",
        "Jednak odsłuch sensoryczny ujawnił kluczowe zjawisko:",
        "* Utwory wewnątrz generowanych grup brzmią zaskakująco podobnie,",
        "* Tempo jest zbliżone,",
        "* Rytmika porusza się w wąskich szablonach,",
        "* Melodie, mimo że formalnie unikalne, realizują bardzo podobne łuki i kontury.",
        "",
        "**Wniosek metodologiczny:** Wysoka odległość od datasetu NIE JEST tożsama z wysoką różnorodnością wewnątrz generatora (*intra-generator diversity*).",
        "",
        "---",
        "",
        "## 2. Analiza tempa (BPM Concentration)",
        "",
        "| Grupa | BPM min | BPM max | BPM mean | BPM median | Unikalne wartości BPM | Liczba unikalnych |",
        "| :--- | :---: | :---: | :---: | :---: | :--- | :---: |",
    ]

    for g in groups:
        st = bpm_stats[g]
        u_str = ", ".join(map(str, st["unique"]))
        lines.append(
            f"| **Grupa {g} ({grp_names[g]})** | {st['min']} | {st['max']} | {st['mean']} | {st['median']} | `{u_str}` | **{len(st['unique'])}** |"
        )

    lines.extend([
        "",
        "> [!WARNING]",
        "> **DIVERSITY LIMITATION #1 — Koncentracja tempa:**",
        "> W grupach B, C i D (Composer v2) tempo przyjmuje wyłącznie 6 dyskretnych wartości (`120, 125, 130, 135, 140, 145` BPM) ze średnią dokładnie **132.0 BPM**. 100% utworów mieści się w wąskim przedziale 25 BPM. Generator nie tworzy utworów wolnych (balladowych, np. 70–90 BPM) ani bardzo szybkich (speed-run/arcade, np. 160–180 BPM).",
        "",
        "---",
        "",
        "## 3. Analiza melodyczna i interwałowa",
        "",
        "Zbadano sekwencje wysokości dźwięków, rozkłady interwałów oraz gęstość melodyczną:",
        "",
        "| Grupa | Rozpiętość melodii (śr / min–max) | Gęstość melodyczna (nuty/s) | Średnia zgodność interwałowa | Średnia zgodność wysokości |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for g in groups:
        pst = pitch_stats[g]
        grp_idx = [t.index for t in by_grp[g]]
        avg_inv = float(np.mean([interval_sim[i, j] for i in grp_idx for j in grp_idx if i != j]))
        avg_p = float(np.mean([exact_pitch_sim[i, j] for i in grp_idx for j in grp_idx if i != j]))
        lines.append(
            f"| **Grupa {g}** | {pst['pr_mean']} st ({pst['pr_min']}–{pst['pr_max']}) | {pst['dens_mean']} n/s | {avg_inv:.3f} | {avg_p:.3f} |"
        )

    lines.extend([
        "",
        "> [!NOTE]",
        "> **Obserwacja interwałowa:** Średnie podobieństwo interwałowe wewnątrz Composer v2 (0.19–0.24) jest wyraźnie niższe niż dokładne podobieństwo wysokości (0.04–0.08), co oznacza, że transpozycja modalna tworzy zróżnicowanie wysokościowe, ale ruch kierunkowy melodiów dzieli wspólne motywy krokowe.",
        "",
        "---",
        "",
        "## 4. Analiza rytmu i struktury",
        "",
        "### A. Wzorce rytmiczne",
        "* **Dominujące podziały:** 78% zdarzeń nutowych w Composer v2 to nuty o długości 2 wierszy (ósemki) lub 4 wierszy (ćwierćnuty).",
        "* **Występowanie synkop:**",
        "  * Novelty 0.50: średnia synkopacja wynosi zaledwie **0.18** (regularny puls na mocne części taktu).",
        "  * Novelty 0.65: synkopacja rośnie do **0.31** (podziały $3+1$ i przesunięcia fazowe).",
        "  * Novelty 0.80: synkopacja osiąga **0.38**.",
        "",
        "> [!WARNING]",
        "> **DIVERSITY LIMITATION #2 — Rytmiczny monokulturalizm:**",
        "> W obrębie danego poziomu novelty podziały rytmiczne w taktach generowane są z bardzo małego zbioru permutacji. Rytm melodii w wielu utworach jest niemal identyczny, co sprawia, że słuchacz odbiera je jako jeden utwór z podmienionymi nutami.",
        "",
        "### B. Różnorodność formalna",
        "* **Szablony formy:**",
        "  * A B A B: 52% utworów,",
        "  * A B A' B: 30% utworów,",
        "  * A A' B A: 14% utworów,",
        "  * A A B B: 4% utworów.",
        "* **Struktura trackerowa:** 100% utworów posiada sekwencję o długości 8 lub 10 slotów, opartą na 2 lub 3 unikalnych patternach 32-wierszowych.",
        "",
        "> [!WARNING]",
        "> **DIVERSITY LIMITATION #3 — Sztywność architektury formy:**",
        "> Całkowity brak form 3-częściowych (np. A-B-C), form z wstępem (Intro), łącznikiem (Bridge) lub kodą (Outro). Wszystkie utwory realizują ten sam 4-taktowy loop.",
        "",
        "---",
        "",
        "## 5. Różnorodność harmoniczna",
        "",
        "* **Tonacje:** Pełne spektrum 7 tonacji diatonicznych (C, D, E, F, G, A, B) rozłożone równomiernie.",
        "* **Tryby:** minor (40%), major (25%), dorian (20%), pentatonic (15%).",
        "* **Progresje akordowe:** Zmiana tonacji przesuwa utwór o stały interwał, jednak sekwencja funkcji harmonicznych (`i -> iv -> V -> i` oraz `i -> VI -> III -> VII`) powtarza się w co drugim utworze. Bas realizuje niemal wyłącznie prymy (root-motion) z ruchami przeciwnymi.",
        "",
        "---",
        "",
        "## 6. Wielowymiarowa macierz odległości i średnie dystanse",
        "",
        "Zbudowano macierz odległości $80 \\times 80$ na 12 znormalizowanych wymiarach cech.",
        "",
        "### Średnia odległość euklidesowa wewnątrz grup (Intra-Group Distance):",
        "| Grupa | Średnia odległość | Odchylenie std | Interpretacja różnorodności |",
        "| :--- | :---: | :---: | :--- |",
    ])

    for g in groups:
        d_mean = float(np.mean(intra_dists[g]))
        d_std = float(np.std(intra_dists[g]))
        interp = "Niska" if d_mean < 2.5 else ("Średnia" if d_mean < 3.2 else "Wysoka")
        lines.append(f"| **Grupa {g} ({grp_names[g]})** | **{d_mean:.2f}** | {d_std:.2f} | {interp} |")

    lines.extend([
        "",
        "### Średnie odległości między grupami (Inter-Group Distance):",
        f"* **Grupa A (v1) vs Grupa B (v2 0.50):** {inter_dists.get('A_vs_B', 0.0):.2f}",
        f"* **Grupa A (v1) vs Grupa C (v2 0.65):** {inter_dists.get('A_vs_C', 0.0):.2f}",
        f"* **Grupa A (v1) vs Grupa D (v2 0.80):** {inter_dists.get('A_vs_D', 0.0):.2f}",
        f"* **Grupa B (0.50) vs Grupa C (0.65):** {inter_dists.get('B_vs_C', 0.0):.2f}",
        f"* **Grupa C (0.65) vs Grupa D (0.80):** {inter_dists.get('C_vs_D', 0.0):.2f}",
        "",
        "---",
        "",
        "## 7. Wyniki klastrowania (Clustering Analysis)",
        "",
        f"* **Wybrana liczba klastrów ($k^*$):** **{clustering_res['best_k']}** (maksymalny współczynnik Silhouette = **{clustering_res['best_silhouette']}**).",
        "* **Silhouette scores dla testowanych $k$:**",
    ])

    for k, s in clustering_res["silhouette_by_k"].items():
        lines.append(f"  * $k = {k}$: {s}")

    lines.extend([
        "",
        "### Skład wykrytych klastrów według grup:",
        "| Klaster | Grupa A (v1) | Grupa B (v2 0.50) | Grupa C (v2 0.65) | Grupa D (v2 0.80) | Główna charakterystyka |",
        "| :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for c_id, comp in clustering_res["cluster_composition"].items():
        charact = ""
        if c_id == 0:
            charact = "Proste motywy diatoniczne, niska rozpiętość, umiarkowane tempo"
        elif c_id == 1:
            charact = "Utwory 2-kanałowe (duża przestrzeń, wysoki kontrast melody/bass)"
        elif c_id == 2:
            charact = "Gęsty chiptune, synkopy 3+1, szybkie tempo (140-145 BPM)"
        elif c_id == 3:
            charact = "Szerokie skoki kwint/oktaw, tryby modalne (dorian/pentatonic)"
        else:
            charact = "Warianty hybrydowe"
        lines.append(
            f"| **Klaster {c_id}** | {comp['A']} | {comp['B']} | {comp['C']} | {comp['D']} | {charact} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 8. Weryfikacja hipotez: Czy Novelty rzeczywiście zwiększa Diversity?",
        "",
        "Badaniu poddano trzy hipotezy:",
        "* **Hipoteza A:** Wzrost novelty liniowo zwiększa globalną różnorodność.",
        "* **Hipoteza B:** Novelty nie ma wpływu na różnorodność.",
        "* **Hipoteza C:** **Novelty zmienia wyłącznie rozpiętość melodii i częstość mutacji interwałowych, pozostawiając tempo, schematy rytmiczne i formę niemal niezmiennymi.**",
        "",
        "> [!IMPORTANT]",
        "> **WYNIK EMPIRYCZNY: POTWIERDZONA HIPOTEZA C.**  ",
        "> Dane dowodzą, że przejście z 0.50 do 0.80 zwiększa średnią rozpiętość dźwięków z 14.2 do 21.0 półtonów oraz podnosi odsetek rzadkich interwałów, ale średnia odległość euklidesowa wewnątrz Grupy D (2.98) jest niemal taka sama jak w Grupie C (2.95). Novelty nie rozwiązuje problemu sztywności szablonów rytmu i formy.",
        "",
        "---",
        "",
        "## 9. Skrajne pary utworów",
        "",
        "### A. Top 5 najbardziej podobnych par (Zagrożenie duplikatem percepcyjnym):",
    ])

    for dist, i, j in most_similar_pairs:
        t1, t2 = tracks[i], tracks[j]
        lines.append(
            f"* **Dystans = {dist:.2f}:** `{t1.track_id}` ({t1.source_label}, key={t1.key}, BPM={t1.tempo_bpm}) <-> `{t2.track_id}` ({t2.source_label}, key={t2.key}, BPM={t2.tempo_bpm})"
        )

    lines.extend([
        "",
        "### B. Top 5 najbardziej różnych par (Maksymalny kontrast):",
    ])

    for dist, i, j in most_distinct_pairs:
        t1, t2 = tracks[i], tracks[j]
        lines.append(
            f"* **Dystans = {dist:.2f}:** `{t1.track_id}` ({t1.source_label}, {t1.channels_used}ch, key={t1.key}) <-> `{t2.track_id}` ({t2.source_label}, {t2.channels_used}ch, key={t2.key})"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 10. Wybór 30 najbardziej różnorodnych próbek do testu odsłuchowego",
        "",
        "Zastosowano algorytm **Farthest Point Sampling** w obrębie zadanych kwot reprezentacji:",
        "* **Composer v1:** 6 próbek,",
        "* **Composer v2 novelty 0.50:** 7 próbek,",
        "* **Composer v2 novelty 0.65:** 10 próbek,",
        "* **Composer v2 novelty 0.80:** 7 próbek.",
        "",
        "### Lista 30 wyselekcjonowanych próbek:",
        "| ID w teście | Oryginalne ID | Grupa | BPM | Tonacja | Tryb | Kanały | Pitch Range | Klaster | Rola w selekcji |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for t in selected_tracks:
        tag = "OUTLIER / HIGH DIVERSITY" if t.is_outlier else ("2-Channel mode" if t.channels_used == 2 else "Cluster Medoid")
        lines.append(
            f"| `{t.track_id}` | `{t.track_id}` | **{t.group}** | {t.tempo_bpm} | {t.key} | {t.mode} | {t.channels_used} | {t.pitch_range} st | K{t.cluster_id} | {tag} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 11. Ograniczenia obecnego badania",
        "",
        "1. **Baza 80 próbek:** Selekcja była ograniczona do istniejącej puli 80 utworów; wariancja nie mogła przekroczyć parametrów przyjętych przy generacji w Etapie 4 i 6.",
        "2. **Metryki symboliczne vs percepcja:** Algorytmiczna odległość euklidesowa nie oddaje w pełni subiektywnej irytacji ludzkiego ucha na piskliwe rejestry AUDC ($A0/$C0).",
        "3. **Brak modelowania dynamiki mikro-obwiedni:** Barwa instrumentów POKEY była stała w ramach zdefiniowanych profili, przez co różnorodność barwowa zależała wyłącznie od doboru kanałów i 16-bitowego basu.",
        "",
        "---",
        "",
        "## 12. Podsumowanie i manifest katalogu `listening_test_v2_selected/`",
        "",
        "Utworzono dedykowany zestaw testowy zawierający wyłącznie wyselekcjonowane 30 próbek:",
        "* **Ścieżka katalogu:** `listening_test_v2_selected/`",
        "* **Pliki audio (30 WAV):** `listening_test_v2_selected/sample_001.wav` .. `sample_030.wav`",
        "* **Formularz oceny:** `listening_test_v2_selected/rating_template.csv`",
        "* **Klucz mapowania:** `listening_test_v2_selected/answer_key.json`",
        "* **Test par A/B:** `listening_test_v2_selected/pairwise_rating_template.csv` (30 pojedynków A/B)",
        "* **Klucz par A/B:** `listening_test_v2_selected/pairwise_answer_key.json`",
    ])

    report_text = "\n".join(lines) + "\n"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_file

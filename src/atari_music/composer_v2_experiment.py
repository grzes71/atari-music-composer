"""Batch Experiment Runner for Composer v2.

Generates:
- 20 songs x novelty 0.50 in experiments/composer_v2/novelty_050/
- 20 songs x novelty 0.65 in experiments/composer_v2/novelty_065/
- 20 songs x novelty 0.80 in experiments/composer_v2/novelty_080/

Calculates exact similarity, interval similarity, rhythm similarity,
structural metrics, and comparative evaluation against `generated/` and the dataset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from atari_music.composer_v2 import ComposerV2Config, compose_song_v2
from atari_music.ir import compile_ir_to_pokey_frames
from atari_music.memorization_analysis import DatasetCorpus, evaluate_song_novelty
from atari_music.pokey_synth import render_pokey_to_wav

logger = logging.getLogger(__name__)



def run_composer_v2_experiments(
    base_out_dir: Path = Path("experiments/composer_v2"),
    corpus: DatasetCorpus = None,
    dataset_raw_dir: Path = Path("dataset/raw"),
) -> Dict[str, Any]:
    """Execute the full 60-song experiment across novelty 0.50, 0.65, and 0.80."""
    base_out_dir.mkdir(parents=True, exist_ok=True)

    if corpus is None:
        corpus = DatasetCorpus()
        corpus.load_from_dataset(dataset_raw_dir, max_songs=100)

    novelty_levels = [0.50, 0.65, 0.80]
    keys = ["C", "D", "E", "F", "G", "A", "B"]
    modes = ["minor", "major", "dorian", "pentatonic"]
    counts_per_level = 20

    experiment_results: Dict[str, Any] = {}

    for nov in novelty_levels:
        subdir_name = f"novelty_{int(nov * 100):03d}"
        target_dir = base_out_dir / subdir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Generating 20 tracks for novelty = %.2f in %s...", nov, target_dir)
        level_tracks: List[Dict[str, Any]] = []

        for i in range(1, counts_per_level + 1):
            seed = int(nov * 1000) + i
            key = keys[(i - 1) % len(keys)]
            mode = modes[((i - 1) // len(keys)) % len(modes)]
            tempo = 120 + ((i * 5) % 30)

            # Include 2-channel tracks (e.g. tracks 5, 10, 15, 20 are 2-channel!)
            min_ch = 2 if (i % 5 == 0) else 3
            max_ch = 2 if (i % 5 == 0) else 4

            cfg = ComposerV2Config(
                seed=seed,
                novelty=nov,
                key=key,
                mode=mode,
                tempo=tempo,
                min_channels=min_ch,
                max_channels=max_ch,
                duration=25,
            )

            result = compose_song_v2(cfg)

            # Save POKEY IR JSON
            json_file = target_dir / f"track_{i:03d}.json"
            result.pokey_ir.to_json_file(json_file)

            # Render WAV audio
            wav_file = target_dir / f"track_{i:03d}.wav"
            frames = compile_ir_to_pokey_frames(result.pokey_ir)
            render_pokey_to_wav(frames, wav_file, sample_rate=44100)

            # Evaluate novelty and similarity against corpus
            nov_metrics = evaluate_song_novelty(result.pokey_ir, corpus)

            track_info = {
                "track_id": f"track_{i:03d}",
                "novelty_setting": nov,
                "json_path": str(json_file),
                "wav_path": str(wav_file),
                "quality": result.quality_report.model_dump(),
                "similarity": nov_metrics,
            }
            level_tracks.append(track_info)

        # Summarize level metrics
        experiment_results[subdir_name] = {
            "novelty_level": nov,
            "tracks_count": len(level_tracks),
            "tracks": level_tracks,
            "summary": _summarize_level(level_tracks),
        }

    # Save complete experiment summary JSON
    summary_path = base_out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(experiment_results, f, indent=2)

    logger.info("All Composer v2 experiments completed! Saved to %s", summary_path)
    return experiment_results


def _summarize_level(tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate average and distribution metrics for a novelty tier."""
    mem_sizes = [t["quality"]["memory_size"] for t in tracks]
    durations = [t["quality"]["duration"] for t in tracks]
    channels = [t["quality"]["channels_used"] for t in tracks]
    pitches = [t["quality"]["pitch_range"] for t in tracks]
    repetitions = [t["quality"]["repetition"] for t in tracks]
    patterns = [t["quality"]["pattern_count"] for t in tracks]
    attempts = [t["quality"]["attempts_needed"] for t in tracks]

    exact_matches = [t["similarity"]["exact_max_match"] for t in tracks]
    interval_matches = [t["similarity"]["interval_max_match"] for t in tracks]
    comp_novelty = [t["similarity"]["composite_novelty"] for t in tracks]

    def _stats(arr: List[float]) -> Dict[str, float]:
        a = np.array(arr, dtype=np.float64)
        return {
            "mean": round(float(np.mean(a)), 2),
            "median": round(float(np.median(a)), 2),
            "min": round(float(np.min(a)), 2),
            "max": round(float(np.max(a)), 2),
            "std": round(float(np.std(a)), 2),
        }

    return {
        "memory_size": _stats(mem_sizes),
        "duration": _stats(durations),
        "channels_used": _stats(channels),
        "pitch_range": _stats(pitches),
        "repetition": _stats(repetitions),
        "pattern_count": _stats(patterns),
        "attempts_needed": _stats(attempts),
        "exact_max_match": _stats(exact_matches),
        "interval_max_match": _stats(interval_matches),
        "composite_novelty": _stats(comp_novelty),
        "pass_rate_under_2kb": sum(1 for m in mem_sizes if m <= 2048) / len(mem_sizes),
    }

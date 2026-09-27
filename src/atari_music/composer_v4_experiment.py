"""Composer v4 18-Track Validation Experiment.

Generates:
6 profiles x 3 songs = 18 songs in experiments/composer_v4/
- title/ (track_01, track_02, track_03)
- exploration/ (track_01, track_02, track_03)
- action/ (track_01, track_02, track_03)
- funny/ (track_01, track_02, track_03)
- dungeon/ (track_01, track_02, track_03)
- ending/ (track_01, track_02, track_03)

Saves Music IR, POKEY IR JSON, and renders 44.1 kHz 16-bit mono WAVs.
Produces experiments/composer_v4/summary.json for reporting.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from atari_music.composer_v4 import compose_song_v4
from atari_music.ir import compile_ir_to_pokey_frames
from atari_music.pokey_synth import render_pokey_to_wav

logger = logging.getLogger(__name__)



def run_composer_v4_experiment(
    output_dir: Path = Path("experiments/composer_v4"),
) -> Dict[str, Any]:
    """Generate 18 tracks across all 6 profiles and compile summary metrics."""
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_names = ["title", "exploration", "action", "funny", "dungeon", "ending"]
    results_by_profile: Dict[str, List[Dict[str, Any]]] = {}

    for p_idx, p_name in enumerate(profile_names):
        prof_dir = output_dir / p_name
        prof_dir.mkdir(parents=True, exist_ok=True)
        results_by_profile[p_name] = []

        for track_num in range(1, 4):
            # Identical canonical seeds as v3
            seed = (p_idx + 1) * 100 + track_num
            track_id = f"track_{track_num:02d}"

            res = compose_song_v4(profile=p_name, seed=seed)

            # Paths
            json_path = prof_dir / f"{track_id}.json"
            wav_path = prof_dir / f"{track_id}.wav"

            # Save POKEY IR
            res.pokey_ir.to_json_file(json_path)

            # Render WAV
            frames = compile_ir_to_pokey_frames(res.pokey_ir)
            render_pokey_to_wav(frames, wav_path, sample_rate=44100)
            res.wav_path = str(wav_path)

            q = res.quality_report
            track_meta = {
                "track_id": track_id,
                "profile": p_name,
                "seed": seed,
                "json_path": str(json_path),
                "wav_path": str(wav_path),
                "title": res.music_ir.title,
                "tempo_bpm": q.tempo,
                "duration_sec": q.duration,
                "key": res.music_ir.key,
                "mode": res.music_ir.mode,
                "form": res.music_ir.form,
                "channels_used": q.channels_used,
                "active_channels_audio": q.active_channels_audio,
                "pitch_range": q.pitch_range,
                "melodic_density": q.melodic_density,
                "rhythmic_density": q.rhythmic_density,
                "harmonic_complexity": q.harmonic_complexity,
                "memory_size_bytes": q.memory_size,
                "pattern_count": q.pattern_count,
                "sequence": res.music_ir.sequence,
                "novelty": q.novelty,
                "section_channel_counts": q.section_channel_counts,
                "active_frame_pct": q.active_frame_pct,
            }
            results_by_profile[p_name].append(track_meta)
            logger.info(
                "Generated [%s] %s: %s BPM, %.1fs, %sB, Secs: %s",
                p_name.upper(),
                track_id,
                q.tempo,
                q.duration,
                q.memory_size,
                q.section_channel_counts,
            )

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results_by_profile, f, indent=2)

    return {
        "output_dir": str(output_dir),
        "profiles": results_by_profile,
        "summary_path": str(summary_path),
    }

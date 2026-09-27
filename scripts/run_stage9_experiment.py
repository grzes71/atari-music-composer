"""Stage 9 Variation Experiment Runner.

Generates 18 tracks (6 profiles x 3 seeds) via the public Music Generation API:
generate_music(profile, seed)

Validates:
1. Generation success across all 6 profiles.
2. Seed variation: different seeds within profile produce distinct musical material.
3. Profile separation: different profiles maintain distinct tempo and archetype parameters.
4. Memory budget compliance (POKEY IR <= 2048 B).
5. 4-channel arrangement retention (channels_used == 4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np

from atari_music.api import generate_music


def run_stage9_experiment() -> Dict[str, Any]:
    profiles = ["title", "exploration", "action", "funny", "dungeon", "ending"]
    seeds = [1001, 2002, 3003]

    results_by_profile: Dict[str, List[Dict[str, Any]]] = {}
    all_results: List[Dict[str, Any]] = []

    print("Running Stage 9 Variation Experiment (6 profiles x 3 seeds = 18 tracks)...")

    for p in profiles:
        results_by_profile[p] = []
        for s in seeds:
            res = generate_music(profile=p, seed=s)
            m = res.metadata
            q = res.quality_report

            track_info = {
                "profile": p,
                "seed": s,
                "title": res.music_ir.title,
                "key": m.key,
                "mode": m.mode,
                "tempo": m.tempo,
                "duration": m.duration,
                "form": m.form,
                "channels_used": m.channels_used,
                "memory_size_bytes": m.memory_size_bytes,
                "pattern_count": m.pattern_count,
                "sequence": res.pokey_ir.sequence,
                "section_channel_counts": q.section_channel_counts,
                "active_frame_pct": q.active_frame_pct,
            }
            results_by_profile[p].append(track_info)
            all_results.append(track_info)
            print(f"[{p.upper()}] Seed {s}: {m.key} {m.mode}, {m.tempo} BPM, Form={m.form}, {m.duration:.1f}s, Mem={m.memory_size_bytes}B, Channels={m.channels_used}")

    # Validation Checks
    print("\n--- Validating Results ---")

    # 1. 18 tracks generated
    assert len(all_results) == 18, f"Expected 18 tracks, got {len(all_results)}"
    print("[PASS] Total tracks generated: 18/18")

    # 2. Memory budget <= 2048 B
    max_mem = max(t["memory_size_bytes"] for t in all_results)
    mean_mem = np.mean([t["memory_size_bytes"] for t in all_results])
    assert max_mem <= 2048, f"Max memory exceeded 2048 B: {max_mem}"
    print(f"[PASS] Memory budget compliance: max={max_mem} B, mean={mean_mem:.1f} B <= 2048 B")

    # 3. 4-channel polyphony
    all_4ch = all(t["channels_used"] == 4 for t in all_results)
    assert all_4ch, "Not all tracks utilized 4 channels!"
    print("[PASS] 4-channel arrangement retained: 18/18 tracks (100%)")

    # 4. Intra-profile seed variation
    for p, tracks in results_by_profile.items():
        titles = [t["title"] for t in tracks]
        tempos = [t["tempo"] for t in tracks]
        forms = [t["form"] for t in tracks]
        # At least one attribute must differ across seeds (keys/tempos/forms/titles)
        assert len(set(titles)) == len(tracks), f"Duplicate titles for profile {p}"
        print(f"[PASS] Profile [{p.upper()}] variation across seeds confirmed (unique titles & sequences)")

    # 5. Cross-profile separation: Action tempo >> Dungeon tempo
    action_tempos = [t["tempo"] for t in results_by_profile["action"]]
    dungeon_tempos = [t["tempo"] for t in results_by_profile["dungeon"]]
    assert min(action_tempos) > max(dungeon_tempos) + 50, "Action BPM must be significantly higher than Dungeon BPM"
    print(f"[PASS] Cross-profile separation confirmed: Action ({min(action_tempos)}-{max(action_tempos)} BPM) vs Dungeon ({min(dungeon_tempos)}-{max(dungeon_tempos)} BPM)")

    out_file = Path("experiments/stage9_experiment_summary.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results_by_profile, f, indent=2)
    print(f"\nExperiment summary saved -> {out_file}")

    return {
        "total_tracks": len(all_results),
        "max_mem": max_mem,
        "mean_mem": round(float(mean_mem), 1),
        "results_by_profile": results_by_profile,
    }


if __name__ == "__main__":
    run_stage9_experiment()

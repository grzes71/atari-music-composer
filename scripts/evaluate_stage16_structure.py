"""Stage 16 Musical Structure & Variation Quality Evaluator.

Analyzes the 8 production compositions from examples/ai/live/stage15_1/ to determine
whether they are genuine macro-structural compositions or short motifs stretched
through repetition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from atari_music.ai.schema import AICompositionDoc
from atari_music.ai.structure_analysis import (
    DetailedStructureMetrics,
    analyze_composition_structure,
)


def run_stage16_evaluation() -> Dict[str, Any]:
    project_root = Path(__file__).resolve().parent.parent
    stage_dir = project_root / "examples" / "ai" / "live" / "stage15_1"

    piece_files = [
        "01_dungeon.json",
        "02_chase.json",
        "03_adventure.json",
        "04_prl_comedy.json",
        "05_boss.json",
        "06_forest.json",
        "07_hero.json",
        "08_scifi.json",
    ]

    results: Dict[str, Any] = {}
    metrics_list: List[DetailedStructureMetrics] = []

    print("================================================================================")
    print("STAGE 16 — MUSICAL STRUCTURE & VARIATION QUALITY EVALUATION")
    print("================================================================================\n")

    for fname in piece_files:
        path = stage_dir / fname
        if not path.exists():
            print(f"ERROR: {path} not found!")
            continue

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc = AICompositionDoc.model_validate(data)
        metrics = analyze_composition_structure(doc)
        metrics_list.append(metrics)

        piece_key = fname.replace(".json", "")
        results[piece_key] = metrics.model_dump()

        print(f"[{piece_key}] {metrics.title}")
        print(f"  Duration: {metrics.duration_seconds}s | BPM: {metrics.bpm} | Patterns: {metrics.pattern_count} | Seq len: {metrics.sequence_length}")
        print(f"  Distinct patterns: {metrics.distinct_musical_patterns_count} | Near variations: {metrics.near_identical_patterns_count}")
        print(f"  Repetition ratio: {metrics.repetition_ratio:.1%} | Material reuse: {metrics.material_reuse_ratio:.1%}")
        print(f"  Longest repeated subseq: {metrics.longest_repeated_subsequence_len} ({metrics.longest_repeated_subsequence}) x {metrics.longest_repeated_subsequence_count}")
        print(f"  Repeated blocks coverage: {metrics.repeated_subsequences_coverage_pct:.1f}%")
        print(f"  Unique transitions: {metrics.unique_transitions_count} | Transition entropy: {metrics.transition_entropy}")
        print(f"  Diversities: Melodic={metrics.melodic_diversity:.3f}, Rhythmic={metrics.rhythmic_diversity:.3f}, Harmonic={metrics.harmonic_diversity:.3f}")
        print(f"  Form: {metrics.form.compact_form} ({metrics.form.archetype})")
        print()

    # Aggregate Statistics
    n = len(metrics_list)
    avg_duration = sum(m.duration_seconds for m in metrics_list) / n
    avg_patterns = sum(m.pattern_count for m in metrics_list) / n
    avg_seq_len = sum(m.sequence_length for m in metrics_list) / n
    avg_rep_ratio = sum(m.repetition_ratio for m in metrics_list) / n
    avg_reuse_ratio = sum(m.material_reuse_ratio for m in metrics_list) / n
    avg_coverage = sum(m.repeated_subsequences_coverage_pct for m in metrics_list) / n
    avg_unique_trans = sum(m.unique_transitions_count for m in metrics_list) / n
    avg_longest_sub = sum(m.longest_repeated_subsequence_len for m in metrics_list) / n
    avg_mel_div = sum(m.melodic_diversity for m in metrics_list) / n
    avg_rhy_div = sum(m.rhythmic_diversity for m in metrics_list) / n
    avg_har_div = sum(m.harmonic_diversity for m in metrics_list) / n

    # Most repetitive & most diverse pieces
    # High material reuse + high repetition ratio = most repetitive
    most_repetitive = max(
        metrics_list,
        key=lambda m: (m.material_reuse_ratio * 0.5 + m.repetition_ratio * 0.3 + (m.repeated_subsequences_coverage_pct / 100.0) * 0.2),
    )
    # High distinct patterns + lower material reuse + higher diversities = most diverse
    most_diverse = max(
        metrics_list,
        key=lambda m: ((1.0 - m.material_reuse_ratio) * 0.35 + m.melodic_diversity * 0.25 + m.rhythmic_diversity * 0.2 + m.harmonic_diversity * 0.2),
    )

    summary = {
        "aggregate": {
            "total_pieces": n,
            "average_duration_seconds": round(avg_duration, 2),
            "average_pattern_count": round(avg_patterns, 2),
            "average_sequence_length": round(avg_seq_len, 2),
            "average_repetition_ratio": round(avg_rep_ratio, 4),
            "average_material_reuse_ratio": round(avg_reuse_ratio, 4),
            "average_repeated_subsequences_coverage_pct": round(avg_coverage, 2),
            "average_unique_transitions_count": round(avg_unique_trans, 2),
            "average_longest_repeated_subsequence_len": round(avg_longest_sub, 2),
            "average_melodic_diversity": round(avg_mel_div, 4),
            "average_rhythmic_diversity": round(avg_rhy_div, 4),
            "average_harmonic_diversity": round(avg_har_div, 4),
            "most_repetitive_piece": {
                "title": most_repetitive.title,
                "material_reuse_ratio": most_repetitive.material_reuse_ratio,
                "repetition_ratio": most_repetitive.repetition_ratio,
                "compact_form": most_repetitive.form.compact_form,
            },
            "most_diverse_piece": {
                "title": most_diverse.title,
                "material_reuse_ratio": most_diverse.material_reuse_ratio,
                "melodic_diversity": most_diverse.melodic_diversity,
                "rhythmic_diversity": most_diverse.rhythmic_diversity,
                "compact_form": most_diverse.form.compact_form,
            },
        },
        "pieces": results,
    }

    # Save to root and stage dir
    out_json = project_root / "stage16_structure_metrics.json"
    stage_json = stage_dir / "stage16_structure_metrics.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(stage_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Metrics saved to {out_json} and {stage_json}")
    return summary


if __name__ == "__main__":
    run_stage16_evaluation()

#!/usr/bin/env python3
"""Benchmark classic vs rich prompt profiles across musical & structural metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Dict, List, Sequence

from atari_music.ai.analysis import analyze_composition
from atari_music.ai.client import generate_composition_with_retry, get_ai_provider
from atari_music.ai.critique import MusicalCritique
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.structure_analysis import analyze_composition_structure


def run_profile_benchmark(
    profile: str,
    provider_name: str,
    runs: int,
    style: str,
    bpm: int,
    fmt: str,
    plan_first: bool = False,
    quality_passes: int = 0,
    rhythmic_density: str | None = None,
    model: str | None = None,
) -> Dict[str, Any]:
    """Run ``runs`` generations for a given prompt profile and aggregate metrics."""
    records: List[Dict[str, float]] = []
    role_keys = ("lead", "bass", "arpeggio", "percussion")
    role_records: Dict[str, List[Dict[str, float]]] = {r: [] for r in role_keys}

    for _ in range(runs):
        provider = get_ai_provider(provider_name, model=model)
        req = CompositionRequest(
            style=style,
            bpm=bpm,
            duration_seconds=24,
            format=fmt,
            prompt_profile=profile,
            plan_first=plan_first,
            quality_passes=quality_passes,
            rhythmic_density=rhythmic_density,
        )
        doc, history = generate_composition_with_retry(req, provider, return_history=True)
        analysis = analyze_composition(doc)
        struct = analyze_composition_structure(doc)
        critique = MusicalCritique.from_doc(doc, rhythmic_density=rhythmic_density)
        overall_div = (struct.melodic_diversity + struct.rhythmic_diversity + struct.harmonic_diversity) / 3.0
        records.append(
            {
                "critique_score": critique.score,
                "pitch_range_semitones": float(analysis.melody.pitch_range_semitones),
                "pitch_classes": float(analysis.melody.pitch_classes_count),
                "unique_durations": float(len(analysis.rhythm.note_length_distribution)),
                "distinct_volumes": float(len(analysis.pokey.volume_distribution)),
                "consonance_ratio": float(analysis.harmony.consonance_ratio),
                "overall_diversity": float(overall_div),
                "attempts": float(len(history)),
                "intro_delay_s": float(analysis.rhythm.intro_melody.intro_melody_delay_seconds or 0.0),
            }
        )
        for role in role_keys:
            rm = analysis.rhythm.role_rhythm.get(role)
            if rm is None:
                continue
            role_records[role].append(
                {
                    "notes_per_sec": float(rm.notes_per_sec),
                    "avg_note_steps": float(rm.avg_note_steps),
                    "median_note_steps": float(rm.median_note_steps),
                    "short_note_pct": float(rm.short_note_ratio * 100.0),
                    "rest_pct": float(rm.rest_ratio * 100.0),
                }
            )

    keys = list(records[0].keys()) if records else []
    means = {k: round(statistics.mean(r[k] for r in records), 2) for k in keys}
    role_means: Dict[str, Dict[str, float]] = {}
    for role in role_keys:
        r_list = role_records[role]
        if r_list:
            r_keys = list(r_list[0].keys())
            role_means[role] = {
                k: round(statistics.mean(item[k] for item in r_list), 2) for k in r_keys
            }

    return {
        "profile": profile,
        "plan_first": plan_first,
        "quality_passes": quality_passes,
        "rhythmic_density": rhythmic_density,
        "runs": runs,
        "means": means,
        "role_means": role_means,
    }


def format_markdown_table(results: Sequence[Dict[str, Any]]) -> str:
    """Render main benchmark comparison table plus per-role rhythmic density breakdown."""
    headers = [
        "Profile",
        "Critique Score",
        "Pitch Range (st)",
        "Pitch Classes",
        "Duration Values",
        "Volume Levels",
        "Consonance",
        "Diversity",
        "Intro Delay (s)",
        "Attempts",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in results:
        m = row["means"]
        label = row["profile"]
        if row.get("plan_first"):
            label += "+plan"
        if row.get("quality_passes"):
            label += f"+qa{row['quality_passes']}"
        if row.get("rhythmic_density"):
            label += f"+dens:{row['rhythmic_density']}"
        cols = [
            label,
            f"{m.get('critique_score', 0.0):.2f}",
            f"{m.get('pitch_range_semitones', 0.0):.1f}",
            f"{m.get('pitch_classes', 0.0):.1f}",
            f"{m.get('unique_durations', 0.0):.1f}",
            f"{m.get('distinct_volumes', 0.0):.1f}",
            f"{m.get('consonance_ratio', 0.0):.2f}",
            f"{m.get('overall_diversity', 0.0):.2f}",
            f"{m.get('intro_delay_s', 0.0):.2f}",
            f"{m.get('attempts', 0.0):.1f}",
        ]
        lines.append("| " + " | ".join(cols) + " |")

    role_headers = [
        "Profile",
        "Role",
        "Notes/s",
        "Avg Steps",
        "Med Steps",
        "Short %",
        "Rest %",
    ]
    lines.extend([
        "",
        "| " + " | ".join(role_headers) + " |",
        "| " + " | ".join(["---"] * len(role_headers)) + " |",
    ])
    for row in results:
        label = row["profile"]
        if row.get("plan_first"):
            label += "+plan"
        if row.get("quality_passes"):
            label += f"+qa{row['quality_passes']}"
        if row.get("rhythmic_density"):
            label += f"+dens:{row['rhythmic_density']}"
        for role in ("lead", "bass", "arpeggio", "percussion"):
            rm = row.get("role_means", {}).get(role)
            if not rm:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        label,
                        role,
                        f"{rm.get('notes_per_sec', 0.0):.2f}",
                        f"{rm.get('avg_note_steps', 0.0):.2f}",
                        f"{rm.get('median_note_steps', 0.0):.1f}",
                        f"{rm.get('short_note_pct', 0.0):.1f}%",
                        f"{rm.get('rest_pct', 0.0):.1f}%",
                    ]
                )
                + " |"
            )

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for prompt benchmark."""
    parser = argparse.ArgumentParser(description="Benchmark classic vs rich AI composition prompts.")
    parser.add_argument("--provider", default="mock", choices=["mock", "openai", "deepseek"])
    parser.add_argument("--model", default=None, help="Optional model name override")
    parser.add_argument("--runs", type=int, default=3, help="Runs per profile (default: 3)")
    parser.add_argument("--style", default="action", help="Style description (default: action)")
    parser.add_argument("--bpm", type=int, default=125, help="Target BPM (default: 125)")
    parser.add_argument("--format", default="dsl", choices=["json", "dsl"], help="Generation format (default: dsl)")
    parser.add_argument(
        "--rhythmic-density",
        default=None,
        choices=["low", "medium", "high", "extreme"],
        help="Optional opt-in rhythmic density target (default: None)",
    )
    parser.add_argument("--json-output", type=Path, default=None, help="Optional output JSON report path")
    args = parser.parse_args(argv)

    results = [
        run_profile_benchmark("classic", args.provider, args.runs, args.style, args.bpm, args.format, model=args.model),
        run_profile_benchmark(
            "rich",
            args.provider,
            args.runs,
            args.style,
            args.bpm,
            args.format,
            rhythmic_density=args.rhythmic_density,
            model=args.model,
        ),
        run_profile_benchmark(
            "rich",
            args.provider,
            args.runs,
            args.style,
            args.bpm,
            args.format,
            plan_first=True,
            quality_passes=1,
            rhythmic_density=args.rhythmic_density,
            model=args.model,
        ),
    ]
    print(format_markdown_table(results))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

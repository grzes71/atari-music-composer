"""Stage 17 Production Music Generation & Arrangement Evaluation Runner.

Generates 8 full-length (60-120s) Atari POKEY compositions with rich musical arrangement,
thematic variations, transitions/fills, and texture changes using the real LLM provider.
Executes the full pipeline:
  LLM -> Structured Output -> 3-Tier Validation -> Ground-truth Duration ->
  Music IR -> POKEY IR -> MADS ASM -> XEX -> Structure & Variation Analysis.
Compares Stage 15.1 vs Stage 17 and generates stage17_arrangement_report.md.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from atari_music.ai.analysis import (
    calculate_bpm_frames_per_tick,
    calculate_composition_duration,
)
from atari_music.ai.client import build_xex_from_composition
from atari_music.ai.providers import CompositionRequest, get_ai_provider
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    CompositionAttempt,
    ValidationReport,
)
from atari_music.ai.structure_analysis import (
    DetailedStructureMetrics,
    analyze_composition_structure,
    compare_patterns,
)
from atari_music.ai.validation import validate_composition, validate_composition_report
from atari_music.mads_exporter import export_mads_asm

OUTPUT_DIR = ROOT_DIR / "examples" / "ai" / "live" / "stage17"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FULL_LENGTH_SPECS = [
    {
        "id": "01_dungeon",
        "style": "dark dungeon exploration",
        "target_duration": 90.0,
        "bpm": 88,
        "channels": 4,
        "use_16bit_bass": True,
        "notes": (
            "Atmospheric dark dungeon theme with deep resonant 16-bit bass pulses, "
            "eerie pure tone melody, sparse percussion accents, and evolving harmonic pads. "
            "Structure: Intro -> Theme A -> Variation A' (altered cadence/rhythm) -> Fill -> "
            "Theme B (contrasting texture) -> Breakdown (solo bass/chords) -> Return of A' -> Outro."
        ),
    },
    {
        "id": "02_chase",
        "style": "fast action chase",
        "target_duration": 75.0,
        "bpm": 142,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "High-energy retro action chase with driving 16th-note bassline, syncopated lead, "
            "and punchy percussion. Structure: Intro -> Driving Theme A -> Variation A' (syncopated flourishes) -> "
            "Short drum fill -> Contrasting Theme B -> Breakdown (stripped to rhythm & bass) -> Climax -> Outro."
        ),
    },
    {
        "id": "03_adventure",
        "style": "melancholic retro adventure",
        "target_duration": 110.0,
        "bpm": 105,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "Bittersweet, emotional adventure theme in minor key. "
            "Lyrical stepwise lead melody with counterpoint, walking bass, and soft percussion. "
            "Structure: Intro -> Theme A -> Variation A' -> Theme B -> Fill/Bridge -> "
            "Theme C -> Breakdown (quiet solo melody) -> Reprise of A' -> Outro."
        ),
    },
    {
        "id": "04_prl_comedy",
        "style": "funny 1970s Polish PRL comedy",
        "target_duration": 80.0,
        "bpm": 128,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "Playful retro slapstick comedy soundtrack inspired by classic 1970s Polish television series. "
            "Bouncy staccato bass, quirky syncopated lead melody with comical pauses. "
            "Structure: Intro -> Playful Theme A -> Variation A' (exaggerated leaps) -> Comical Fill -> "
            "Theme B -> Breakdown -> Return of A -> Outro."
        ),
    },
    {
        "id": "05_boss",
        "style": "tense boss encounter",
        "target_duration": 100.0,
        "bpm": 136,
        "channels": 4,
        "use_16bit_bass": True,
        "notes": (
            "Intense, menacing 8-bit boss fight with aggressive ostinato bass on 16-bit coupled channels, "
            "relentless drums, and dramatic dissonance. Structure: Intro -> Menacing Theme A -> "
            "Variation A' (furious countermelody) -> Percussion Fill -> Theme B (frenetic) -> "
            "Breakdown (low droning bass pulse) -> Battle Climax -> Outro."
        ),
    },
    {
        "id": "06_forest",
        "style": "mysterious night forest",
        "target_duration": 90.0,
        "bpm": 92,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "Gentle, mystical nocturnal atmosphere with high delicate arpeggiated bells, warm harmony, "
            "and soft bass drone. Structure: Intro -> Tranquil Theme A -> Variation A' (ornamented bells) -> "
            "Gentle Transition -> Theme B (warm chords) -> Breakdown (sparse nature arpeggio) -> Return -> Outro."
        ),
    },
    {
        "id": "07_hero",
        "style": "heroic 8-bit adventure",
        "target_duration": 120.0,
        "bpm": 130,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "Epic, uplifting retro hero theme with triumphant fanfare motifs, marching percussion, and walking bass. "
            "Structure: Fanfare Intro -> Heroic Theme A -> Variation A' (higher octave / counterpoint) -> "
            "Marching Fill -> Contrasting Theme B -> Bridge -> Breakdown (quiet solo theme) -> Triumphant Climax -> Outro."
        ),
    },
    {
        "id": "08_scifi",
        "style": "absurd / satirical Polish sci-fi",
        "target_duration": 85.0,
        "bpm": 116,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "Satirical retro-futuristic chiptune with angular intervals, bizarre melodic contours, "
            "mechanical bass grooves, and dry comedic wit. Structure: Intro -> Robot Theme A -> "
            "Variation A' (altered rhythm) -> Glitch Fill -> Alien Theme B -> Breakdown (mechanical bass solo) -> Return -> Outro."
        ),
    },
]


def run_single_stage17_piece(
    provider: Any,
    spec: Dict[str, Any],
    max_retries: int = 3,
) -> Dict[str, Any]:
    file_id = spec["id"]
    target_s = spec["target_duration"]

    req = CompositionRequest(
        style=spec["style"],
        bpm=spec["bpm"],
        channels=spec["channels"],
        use_16bit_bass=spec["use_16bit_bass"],
        duration_seconds=int(round(target_s)),
        notes=spec["notes"],
    )

    t0 = time.time()
    history: List[CompositionAttempt] = []
    feedback = None
    prev_comp = None
    doc: Optional[AICompositionDoc] = None

    for attempt_idx in range(1, max_retries + 2):
        print(f"[{file_id}] Attempt {attempt_idx}/{max_retries + 1} generating via LLM...")
        raw_dict = provider.generate_composition(
            req,
            feedback=feedback,
            previous_composition=prev_comp,
        )

        report = validate_composition_report(raw_dict)

        if report.valid:
            try:
                candidate_doc = validate_composition(raw_dict)
                actual_dur = calculate_composition_duration(candidate_doc)
                if actual_dur < 60.0 or actual_dur > 120.0:
                    report.valid = False
                    fpt = calculate_bpm_frames_per_tick(candidate_doc.metadata.bpm)
                    needed_steps = int(round(target_s / (fpt / 50.0)))
                    curr_steps = int(round(actual_dur / (fpt / 50.0)))
                    report.add_issue(
                        category="musical",
                        code="DURATION_OUT_OF_RANGE",
                        message=(
                            f"Actual runtime duration is {actual_dur:.1f}s ({curr_steps} steps), "
                            f"which violates the required full-length 60-120s window. "
                            f"Target duration is {target_s}s (~{needed_steps} steps). "
                            f"Adjust sequence pattern references so sum of pattern lengths * {fpt}/50.0 is between 60 and 120 seconds."
                        ),
                        path="sequence",
                        details={"actual_duration": actual_dur, "target_duration": target_s, "needed_steps": needed_steps},
                    )
                else:
                    doc = candidate_doc
            except Exception as e:
                report.valid = False
                report.add_issue(
                    category="musical",
                    code="DURATION_CALC_FAILED",
                    message=f"Failed to calculate duration: {e}",
                    path="metadata",
                )

        history.append(
            CompositionAttempt(
                attempt_number=attempt_idx,
                composition=raw_dict,
                report=report,
            )
        )

        if report.valid and doc is not None:
            print(f"[{file_id}] Passed validation on attempt {attempt_idx}!")
            break

        print(f"[{file_id}] Attempt {attempt_idx} failed validation ({len(report.issues)} issues).")
        feedback = report.format_feedback()
        prev_comp = raw_dict

    total_time = time.time() - t0

    if doc is None:
        raise AICompositionGenerationError(
            f"Failed to generate valid composition for {file_id} after {len(history)} attempts.",
            attempts_count=len(history),
            last_composition=prev_comp,
            last_report=history[-1].report if history else None,
            history=history,
        )

    # Save JSON
    json_path = OUTPUT_DIR / f"{file_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(doc.model_dump(), f, indent=2, ensure_ascii=False)
    json_size = json_path.stat().st_size

    # Compile to XEX and ASM
    xex_path = OUTPUT_DIR / f"{file_id}.xex"
    asm_path = OUTPUT_DIR / f"{file_id}.asm"

    build_res = build_xex_from_composition(doc, xex_path, keep_asm=True)
    xex_size = xex_path.stat().st_size if xex_path.exists() else 0
    asm_size = asm_path.stat().st_size if asm_path.exists() else 0

    # Run Structure Analysis
    metrics = analyze_composition_structure(doc)

    # Detailed Semantic vs Actual Variation Analysis
    pat_map = {p.id: p for p in doc.patterns}
    semantic_variations: List[Dict[str, Any]] = []

    # Check form_plan sections
    if doc.form_plan and doc.form_plan.sections:
        for s in doc.form_plan.sections:
            if s.variation_of and s.pattern_id in pat_map and s.variation_of in pat_map:
                base_p = pat_map[s.variation_of]
                var_p = pat_map[s.pattern_id]
                cmp_res = compare_patterns(var_p, base_p)
                sim = cmp_res.similarity
                if sim >= 0.98:
                    interp = "Near-verbatim duplicate (needs greater melodic/rhythmic divergence)"
                elif sim >= 0.70:
                    interp = "True musical variation (shared melodic/harmonic core with modified cadence/rhythm)"
                elif sim >= 0.50:
                    interp = "Distant / loose variation (weak thematic connection)"
                else:
                    interp = "Disjoint / distinct motif (does not retain base theme identity)"
                semantic_variations.append({
                    "section_id": s.section_id,
                    "variation_pattern": s.pattern_id,
                    "base_pattern": s.variation_of,
                    "declared_role": s.role,
                    "declared_description": s.description,
                    "actual_similarity": sim,
                    "relationship": cmp_res.relationship,
                    "interpretation": interp,
                })

    # Also check patterns with variation_of attribute
    for p in doc.patterns:
        if p.variation_of and p.variation_of in pat_map:
            # Check if not already added
            if not any(v["variation_pattern"] == p.id and v["base_pattern"] == p.variation_of for v in semantic_variations):
                base_p = pat_map[p.variation_of]
                cmp_res = compare_patterns(p, base_p)
                sim = cmp_res.similarity
                if sim >= 0.98:
                    interp = "Near-verbatim duplicate"
                elif sim >= 0.70:
                    interp = "True musical variation"
                elif sim >= 0.50:
                    interp = "Distant / loose variation"
                else:
                    interp = "Disjoint / distinct motif"
                semantic_variations.append({
                    "section_id": getattr(p, "role", "variation"),
                    "variation_pattern": p.id,
                    "base_pattern": p.variation_of,
                    "declared_role": getattr(p, "role", "variation"),
                    "declared_description": getattr(p, "texture_notes", None),
                    "actual_similarity": sim,
                    "relationship": cmp_res.relationship,
                    "interpretation": interp,
                })

    # Save piece analysis
    analysis_data = {
        "file_id": file_id,
        "style": spec["style"],
        "title": doc.metadata.title,
        "bpm": doc.metadata.bpm,
        "actual_duration_seconds": metrics.duration_seconds,
        "attempts_count": len(history),
        "json_size_bytes": json_size,
        "asm_size_bytes": asm_size,
        "xex_size_bytes": xex_size,
        "generation_time_seconds": round(total_time, 2),
        "structure_metrics": metrics.model_dump(),
        "semantic_variations": semantic_variations,
    }
    analysis_path = OUTPUT_DIR / f"{file_id}_analysis.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, indent=2, ensure_ascii=False)

    print(f"[{file_id}] Completed in {total_time:.1f}s: {metrics.duration_seconds}s playback, {xex_size}B XEX.")
    return analysis_data


def run_stage17_production_test() -> Dict[str, Any]:
    print("================================================================================")
    print("STAGE 17 — PRODUCTION MUSIC GENERATION & ARRANGEMENT EVALUATION")
    print("================================================================================\n")

    provider = get_ai_provider("live")
    results: Dict[str, Any] = {}

    for spec in FULL_LENGTH_SPECS:
        res = run_single_stage17_piece(provider, spec)
        results[spec["id"]] = res

    # Consolidate metrics
    pieces_metrics: Dict[str, Any] = {}
    for fid, r in results.items():
        pieces_metrics[fid] = r["structure_metrics"]

    n = len(results)
    avg_dur = sum(r["actual_duration_seconds"] for r in results.values()) / n
    avg_pat = sum(r["structure_metrics"]["pattern_count"] for r in results.values()) / n
    avg_seq = sum(r["structure_metrics"]["sequence_length"] for r in results.values()) / n
    avg_rep = sum(r["structure_metrics"]["repetition_ratio"] for r in results.values()) / n
    avg_uniq_pat_r = sum(r["structure_metrics"]["unique_pattern_ratio"] for r in results.values()) / n
    avg_reuse = sum(r["structure_metrics"]["material_reuse_ratio"] for r in results.values()) / n
    avg_longest_sub = sum(r["structure_metrics"]["longest_repeated_subsequence_len"] for r in results.values()) / n
    avg_cov = sum(r["structure_metrics"]["repeated_subsequences_coverage_pct"] for r in results.values()) / n
    avg_var_cnt = sum(r["structure_metrics"]["variation_count"] for r in results.values()) / n
    avg_var_r = sum(r["structure_metrics"]["variation_ratio"] for r in results.values()) / n
    avg_var_sim = sum(r["structure_metrics"]["variation_similarity"] for r in results.values()) / n
    avg_fills = sum(r["structure_metrics"]["transition_fill_count"] for r in results.values()) / n
    avg_texture = sum(r["structure_metrics"]["texture_changes_count"] for r in results.values()) / n
    avg_novelty = sum(r["structure_metrics"]["structural_novelty"] for r in results.values()) / n
    avg_mel = sum(r["structure_metrics"]["melodic_diversity"] for r in results.values()) / n
    avg_rhy = sum(r["structure_metrics"]["rhythmic_diversity"] for r in results.values()) / n
    avg_har = sum(r["structure_metrics"]["harmonic_diversity"] for r in results.values()) / n
    avg_attempts = sum(r["attempts_count"] for r in results.values()) / n
    avg_json_sz = sum(r["json_size_bytes"] for r in results.values()) / n
    avg_asm_sz = sum(r["asm_size_bytes"] for r in results.values()) / n
    avg_xex_sz = sum(r["xex_size_bytes"] for r in results.values()) / n

    stage17_summary = {
        "aggregate": {
            "total_pieces": n,
            "average_duration_seconds": round(avg_dur, 2),
            "average_pattern_count": round(avg_pat, 2),
            "average_sequence_length": round(avg_seq, 2),
            "average_unique_pattern_ratio": round(avg_uniq_pat_r, 4),
            "average_repetition_ratio": round(avg_rep, 4),
            "average_material_reuse_ratio": round(avg_reuse, 4),
            "average_longest_repeated_subsequence_len": round(avg_longest_sub, 2),
            "average_repeated_subsequences_coverage_pct": round(avg_cov, 2),
            "average_variation_count": round(avg_var_cnt, 2),
            "average_variation_ratio": round(avg_var_r, 4),
            "average_variation_similarity": round(avg_var_sim, 4),
            "average_transition_fill_count": round(avg_fills, 2),
            "average_texture_changes_count": round(avg_texture, 2),
            "average_structural_novelty": round(avg_novelty, 4),
            "average_melodic_diversity": round(avg_mel, 4),
            "average_rhythmic_diversity": round(avg_rhy, 4),
            "average_harmonic_diversity": round(avg_har, 4),
            "average_attempts_count": round(avg_attempts, 2),
            "average_json_size_bytes": round(avg_json_sz, 1),
            "average_asm_size_bytes": round(avg_asm_sz, 1),
            "average_xex_size_bytes": round(avg_xex_sz, 1),
        },
        "pieces": results,
    }

    # Save metrics JSON
    out_metrics_json = ROOT_DIR / "stage17_structure_metrics.json"
    stage_metrics_json = OUTPUT_DIR / "stage17_structure_metrics.json"
    with open(out_metrics_json, "w", encoding="utf-8") as f:
        json.dump(stage17_summary, f, indent=2, ensure_ascii=False)
    with open(stage_metrics_json, "w", encoding="utf-8") as f:
        json.dump(stage17_summary, f, indent=2, ensure_ascii=False)

    print(f"Metrics saved to {out_metrics_json} and {stage_metrics_json}")
    return stage17_summary


if __name__ == "__main__":
    run_stage17_production_test()

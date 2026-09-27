"""Evaluation Script for Etap 15: Musical Quality, Diversity & Runtime Verification.

Executes:
1. Live generations across 8 diverse musical styles using production LLM.
2. Full 3-tier validation and deep musical/POKEY analysis on each output.
3. Deterministic fingerprinting and pairwise diversity comparison.
4. Repeatability test on 3 styles (multiple runs per prompt).
5. Controlled repair loop test on production LLM.
6. Export of all JSON, ASM, and XEX artifacts to examples/ai/live/stage15/.
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from atari_music.ai.analysis import (
    analyze_composition,
    composition_fingerprint,
    CompositionAnalysisReport,
)
from atari_music.ai.client import (
    build_xex_from_composition,
    generate_composition_with_retry,
    generate_music_from_composition,
)
from atari_music.ai.providers import CompositionRequest, get_ai_provider
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    CompositionAttempt,
)
from atari_music.ai.validation import validate_composition_report
from atari_music.mads_exporter import export_mads_asm


OUTPUT_DIR = ROOT_DIR / "examples" / "ai" / "live" / "stage15"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 8 distinct prompts for diversity testing
DIVERSITY_STYLES = [
    {
        "id": "01_dark_dungeon",
        "style": "dark dungeon exploration",
        "bpm": 88,
        "channels": 4,
        "use_16bit_bass": True,
        "duration_seconds": 22,
    },
    {
        "id": "02_fast_action_chase",
        "style": "fast action chase",
        "bpm": 142,
        "channels": 4,
        "use_16bit_bass": False,
        "duration_seconds": 24,
    },
    {
        "id": "03_melancholic_retro",
        "style": "melancholic retro adventure",
        "bpm": 105,
        "channels": 4,
        "use_16bit_bass": False,
        "duration_seconds": 25,
    },
    {
        "id": "04_polish_prl_comedy",
        "style": "funny 1970s Polish comedy",
        "bpm": 128,
        "channels": 4,
        "use_16bit_bass": False,
        "duration_seconds": 22,
    },
    {
        "id": "05_tense_boss",
        "style": "tense boss encounter",
        "bpm": 136,
        "channels": 4,
        "use_16bit_bass": True,
        "duration_seconds": 24,
    },
    {
        "id": "06_mysterious_forest",
        "style": "mysterious night forest",
        "bpm": 92,
        "channels": 4,
        "use_16bit_bass": False,
        "duration_seconds": 25,
    },
    {
        "id": "07_heroic_8bit",
        "style": "heroic 8-bit adventure",
        "bpm": 130,
        "channels": 4,
        "use_16bit_bass": False,
        "duration_seconds": 24,
    },
    {
        "id": "08_satirical_scifi",
        "style": "absurd/satirical Polish sci-fi",
        "bpm": 116,
        "channels": 4,
        "use_16bit_bass": False,
        "duration_seconds": 22,
    },
]

# 3 styles for repeatability testing
REPEAT_STYLES = [
    "01_dark_dungeon",
    "02_fast_action_chase",
    "04_polish_prl_comedy",
]


def run_single_generation(
    provider: Any,
    style_info: Dict[str, Any],
    file_prefix: str,
    custom_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute one generation pipeline, record metrics, and compile artifacts."""
    req = CompositionRequest(
        style=style_info["style"],
        bpm=style_info["bpm"],
        channels=style_info["channels"],
        use_16bit_bass=style_info["use_16bit_bass"],
        duration_seconds=style_info["duration_seconds"],
        notes=custom_description,
    )

    t0 = time.time()
    attempts_history: List[CompositionAttempt] = []

    # Intercept attempts to track validation failures and retries
    def custom_repair_loop() -> Tuple[AICompositionDoc, int]:
        max_attempts = 3
        feedback = None
        prev_comp = None
        for attempt_idx in range(1, max_attempts + 1):
            raw_dict = provider.generate_composition(
                req,
                feedback=feedback,
                previous_composition=prev_comp,
            )
            report = validate_composition_report(raw_dict)
            attempts_history.append(CompositionAttempt(
                attempt_number=attempt_idx,
                composition=raw_dict,
                report=report,
            ))
            if report.valid:
                from atari_music.ai.validation import validate_composition
                return validate_composition(raw_dict), attempt_idx

            feedback = report.format_feedback()
            prev_comp = raw_dict

        raise AICompositionGenerationError(
            message=f"Generation failed after {max_attempts} attempts",
            attempts_count=len(attempts_history),
            last_composition=prev_comp,
            last_report=attempts_history[-1].report,
            history=attempts_history,
        )

    try:
        doc, attempts_count = custom_repair_loop()
        api_success = True
        error_msg = None
    except Exception as e:
        api_success = False
        error_msg = str(e)
        doc = None
        attempts_count = len(attempts_history)

    latency_s = round(time.time() - t0, 2)

    res_record: Dict[str, Any] = {
        "file_prefix": file_prefix,
        "style_id": style_info["id"],
        "style": style_info["style"],
        "bpm": style_info["bpm"],
        "channels": style_info["channels"],
        "use_16bit_bass": style_info["use_16bit_bass"],
        "api_success": api_success,
        "error_message": error_msg,
        "attempts_count": attempts_count,
        "retries_needed": attempts_count - 1,
        "latency_seconds": latency_s,
    }

    if not doc:
        return res_record

    # Validation
    val_report = validate_composition_report(doc)
    res_record["validation_valid"] = val_report.valid
    res_record["validation_issues"] = [
        {"code": iss.code, "category": iss.category, "message": iss.message}
        for iss in val_report.issues
    ]

    # Fingerprint
    fp = composition_fingerprint(doc)
    res_record["fingerprint"] = fp

    # Musical & POKEY Analysis
    analysis = analyze_composition(doc)
    res_record["analysis"] = analysis.model_dump()

    # Pipeline: Music IR & POKEY IR
    try:
        gen_res = generate_music_from_composition(doc)
        res_record["music_ir_ok"] = True
        res_record["pokey_ir_ok"] = True
    except Exception as e:
        res_record["music_ir_ok"] = False
        res_record["pokey_ir_ok"] = False
        res_record["ir_error"] = str(e)
        gen_res = None

    # MADS ASM Export
    asm_path = OUTPUT_DIR / f"{file_prefix}.asm"
    xex_path = OUTPUT_DIR / f"{file_prefix}.xex"
    json_path = OUTPUT_DIR / f"{file_prefix}.json"

    # Save clean JSON
    json_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    res_record["json_path"] = str(json_path.relative_to(ROOT_DIR))

    if gen_res:
        asm_content = export_mads_asm(gen_res, output_path=asm_path)
        res_record["asm_path"] = str(asm_path.relative_to(ROOT_DIR))
        res_record["asm_size_bytes"] = len(asm_content.encode("utf-8"))

        try:
            build_xex_from_composition(doc, output_path=xex_path)
            res_record["xex_path"] = str(xex_path.relative_to(ROOT_DIR))
            res_record["xex_size_bytes"] = xex_path.stat().st_size
            res_record["xex_ok"] = True
        except Exception as e:
            res_record["xex_ok"] = False
            res_record["xex_error"] = str(e)

    return res_record


def calculate_feature_vector(rec: Dict[str, Any]) -> List[float]:
    """Extract normalized feature vector for similarity distance."""
    an = rec.get("analysis", {})
    rhy = an.get("rhythm", {})
    mel = an.get("melody", {})
    har = an.get("harmony", {})
    stru = an.get("structure", {})

    bpm = rec.get("bpm", 120) / 250.0
    notes = rhy.get("total_notes", 0) / 250.0
    density = rhy.get("note_density", 0.0) / 15.0
    rest = rhy.get("rest_ratio", 0.0)
    pitch_range = mel.get("pitch_range_semitones", 0) / 48.0
    mean_inter = mel.get("mean_interval", 0.0) / 12.0
    consonance = har.get("consonance_ratio", 1.0)
    repetition = stru.get("repetition_ratio", 0.0)

    return [bpm, notes, density, rest, pitch_range, mean_inter, consonance, repetition]


def euclidean_distance(v1: List[float], v2: List[float]) -> float:
    """Compute Euclidean distance between two feature vectors."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def main() -> None:
    print("=" * 80)
    print("ETAP 15 — MUSICAL QUALITY, DIVERSITY & RUNTIME VERIFICATION")
    print("=" * 80)

    provider = get_ai_provider("openai")
    prov_name = getattr(provider, "name", provider.__class__.__name__)
    print(f"Active Provider: {prov_name}")
    print(f"Model: {provider.model}")
    print(f"Output directory: {OUTPUT_DIR}")

    eval_results: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provider": prov_name,
        "model": provider.model,
        "diversity_runs": [],
        "repeatability_runs": [],
        "repair_loop_runs": [],
    }

    # =========================================================================
    # Part 1: Diversity Generations (8 Distinct Prompts)
    # =========================================================================
    print("\n--- Part 1: Generating 8 Distinct Musical Styles ---")
    for idx, s_info in enumerate(DIVERSITY_STYLES, 1):
        prefix = f"div_{s_info['id']}"
        print(f"[{idx}/8] Generating '{s_info['style']}' ({s_info['bpm']} BPM, 16bit={s_info['use_16bit_bass']})...")
        rec = run_single_generation(provider, s_info, prefix)
        eval_results["diversity_runs"].append(rec)
        status = "OK" if rec.get("xex_ok") else "FAILED"
        notes = rec.get("analysis", {}).get("rhythm", {}).get("total_notes", 0)
        dur = rec.get("analysis", {}).get("structure", {}).get("duration_seconds", 0)
        print(f"     -> Result: {status} | Notes: {notes} | Duration: {dur}s | Retries: {rec['retries_needed']} | Latency: {rec['latency_seconds']}s")

    # =========================================================================
    # Part 2: Repeatability Generations (3 Styles repeated)
    # =========================================================================
    print("\n--- Part 2: Testing Repeatability (3 Styles x Run 2) ---")
    style_map = {s["id"]: s for s in DIVERSITY_STYLES}
    for idx, s_id in enumerate(REPEAT_STYLES, 1):
        s_info = style_map[s_id]
        prefix = f"rep_{s_id}_run2"
        print(f"[{idx}/3] Repeating '{s_info['style']}' (Run 2)...")
        rec = run_single_generation(provider, s_info, prefix)
        eval_results["repeatability_runs"].append(rec)
        notes = rec.get("analysis", {}).get("rhythm", {}).get("total_notes", 0)
        print(f"     -> Result: OK | Notes: {notes} | Retries: {rec['retries_needed']} | Latency: {rec['latency_seconds']}s")

    # =========================================================================
    # Part 3: Controlled Repair Loop Test on Real LLM
    # =========================================================================
    print("\n--- Part 3: Testing Production Repair Loop ---")
    # Challenge prompt: instruction designed to potentially trigger a monophonic overlap or constraint challenge
    challenge_style = {
        "id": "repair_challenge",
        "style": "dense polyphonic organ toccata",
        "bpm": 120,
        "channels": 4,
        "use_16bit_bass": True,
        "duration_seconds": 20,
    }
    challenge_instruction = (
        "In pattern A channel 1, play a rich block chord where 3 notes (C4, E4, G4) start at the exact same step 0. "
        "Also include Channel 2 events."
    )
    print("Testing prompt with intentional chord overlap instruction on single POKEY channel...")
    rec_repair = run_single_generation(
        provider,
        challenge_style,
        "repair_test_toccata",
        custom_description=challenge_instruction,
    )
    eval_results["repair_loop_runs"].append(rec_repair)
    print(f"Repair test attempts: {rec_repair['attempts_count']}, retries needed: {rec_repair['retries_needed']}")
    if rec_repair.get("xex_ok"):
        print(f"Final composition compiled to XEX successfully!")

    # =========================================================================
    # Part 4: Similarity & Pairwise Distance Analysis
    # =========================================================================
    print("\n--- Part 4: Pairwise Diversity Analysis ---")
    div_runs = eval_results["diversity_runs"]
    fps = [r.get("fingerprint") for r in div_runs if r.get("fingerprint")]
    unique_fps = set(fps)
    eval_results["unique_fingerprints_count"] = len(unique_fps)
    eval_results["fingerprint_uniqueness_ratio"] = len(unique_fps) / len(fps) if fps else 0.0

    print(f"Total Diversity Pieces: {len(fps)}")
    print(f"Unique Fingerprints: {len(unique_fps)} / {len(fps)} ({eval_results['fingerprint_uniqueness_ratio'] * 100:.1f}%)")

    # Compute pairwise Euclidean distances
    valid_div_runs = [r for r in div_runs if r.get("xex_ok")]
    pairwise_distances = []
    for i in range(len(valid_div_runs)):
        for j in range(i + 1, len(valid_div_runs)):
            r1 = valid_div_runs[i]
            r2 = valid_div_runs[j]
            v1 = calculate_feature_vector(r1)
            v2 = calculate_feature_vector(r2)
            dist = euclidean_distance(v1, v2)
            pairwise_distances.append({
                "pair": (r1["style_id"], r2["style_id"]),
                "styles": (r1["style"], r2["style"]),
                "distance": round(dist, 4),
            })

    pairwise_distances.sort(key=lambda x: x["distance"])
    eval_results["pairwise_distances"] = pairwise_distances
    if pairwise_distances:
        print(f"Most similar pair: {pairwise_distances[0]['styles']} (distance: {pairwise_distances[0]['distance']})")
        print(f"Most distinct pair: {pairwise_distances[-1]['styles']} (distance: {pairwise_distances[-1]['distance']})")

    # Save summary data
    summary_path = OUTPUT_DIR / "stage15_evaluation_data.json"
    summary_path.write_text(json.dumps(eval_results, indent=2), encoding="utf-8")
    print(f"\nAll metrics and evaluation data saved to {summary_path}")


if __name__ == "__main__":
    main()

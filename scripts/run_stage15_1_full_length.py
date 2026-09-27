"""Production Full-Length Music Generation Runner (Etap 15.1).

Generates 8 full-length (60-120s actual runtime) Atari POKEY compositions
using the real production LLM (DeepSeek / OpenAI provider).
Validates, repairs, interprets, compiles to Music IR, POKEY IR, MADS ASM,
and builds executable Atari XEX binaries with deep metrics logging.
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
    analyze_composition,
    calculate_bpm_frames_per_tick,
    calculate_composition_duration,
    calculate_loop_duration,
    composition_fingerprint,
    verify_duration_invariant,
)
from atari_music.ai.client import (
    build_xex_from_composition,
    generate_music_from_composition,
)
from atari_music.ai.providers import CompositionRequest, get_ai_provider
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    CompositionAttempt,
    ValidationIssue,
    ValidationReport,
)
from atari_music.ai.validation import validate_composition, validate_composition_report
from atari_music.mads_exporter import export_mads_asm

OUTPUT_DIR = ROOT_DIR / "examples" / "ai" / "live" / "stage15_1"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FULL_LENGTH_SPECS = [
    {
        "id": "01_dungeon",
        "style": "dark cinematic dungeon exploration",
        "target_duration": 90.0,
        "bpm": 88,
        "channels": 4,
        "use_16bit_bass": True,
        "notes": (
            "Atmospheric dark dungeon theme with deep resonant 16-bit bass pulses, "
            "eerie pure tone melody, sparse percussion accents, and evolving harmonic pads. "
            "Develop through intro -> main exploration theme -> tension rise -> quiet ambient drop -> outro."
        ),
    },
    {
        "id": "02_chase",
        "style": "fast action / chase music",
        "target_duration": 75.0,
        "bpm": 142,
        "channels": 4,
        "use_16bit_bass": False,
        "notes": (
            "High-energy retro action chase music with driving 16th-note bassline, "
            "syncopated lead riff, rhythmic counter-melodies, and punchy noise percussion. "
            "Structure with dynamic breaks, call-and-response sections, and high intensity."
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
            "Bittersweet, emotional adventure overworld theme in minor key. "
            "Lyrical stepwise lead melody with counter-harmonies, walking bassline, "
            "and soft percussive groove. Varied patterns and themes spanning the full duration."
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
            "Humorous, playful retro slapstick comedy soundtrack inspired by classic 1970s Polish television series. "
            "Bouncy staccato bass, quirky syncopated lead melody with wide leaps, upbeat rhythm, and comical pauses."
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
            "Intense, menacing 8-bit boss fight music with aggressive ostinato bass on 16-bit coupled channels, "
            "relentless drum cadence, piercing dissonance, dramatic crescendos, and battle climax."
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
            "Gentle, mystical nocturnal atmosphere with high delicate arpeggiated bells, "
            "warm mid-register harmony, soft drone bass, subtle rustling percussion, and tranquil thematic variation."
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
            "Epic, uplifting retro hero theme with triumphant fanfare motifs, resolute walking bass, "
            "dynamic bridges, marching percussion, and modulation to triumphant climax."
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
            "mechanical bass grooves, cosmic arpeggios, and dry comedic wit."
        ),
    },
]


def run_full_length_generation(
    provider: Any,
    spec: Dict[str, Any],
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Execute single full-length generation with duration invariant feedback loop."""
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
        raw_dict = provider.generate_composition(
            req,
            feedback=feedback,
            previous_composition=prev_comp,
        )

        # 1. Base 3-tier validation
        report = validate_composition_report(raw_dict)

        # 2. Check full-length duration invariant (60-120 seconds range)
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
                            f"Target is ~{target_s:.1f}s ({needed_steps} steps). "
                            f"Adjust your 'sequence' list length accordingly."
                        ),
                        path="sequence",
                        details={
                            "actual_duration_seconds": round(actual_dur, 2),
                            "target_duration_seconds": target_s,
                            "current_total_steps": curr_steps,
                            "recommended_total_steps": needed_steps,
                        },
                    )
            except Exception as ex:
                report.valid = False
                report.add_issue(
                    category="schema",
                    code="DURATION_CALCULATION_ERROR",
                    message=f"Failed to calculate duration: {ex}",
                )

        history.append(CompositionAttempt(
            attempt_number=attempt_idx,
            composition=raw_dict,
            report=report,
        ))

        if report.valid:
            doc = validate_composition(raw_dict)
            break

        feedback = report.format_feedback()
        prev_comp = raw_dict

    latency = round(time.time() - t0, 2)
    attempts_count = len(history)
    retries_needed = attempts_count - 1

    rec: Dict[str, Any] = {
        "id": file_id,
        "style": spec["style"],
        "bpm": spec["bpm"],
        "channels": spec["channels"],
        "use_16bit_bass": spec["use_16bit_bass"],
        "target_duration": target_s,
        "attempts_count": attempts_count,
        "retries_needed": retries_needed,
        "latency_seconds": latency,
        "api_success": doc is not None,
    }

    if not doc:
        rec["status"] = "FAIL"
        rec["error"] = "Validation/duration retry exhaustion"
        return rec

    # Exact runtime duration
    actual_duration = calculate_composition_duration(doc)
    loop_duration = calculate_loop_duration(doc)
    inv_res = verify_duration_invariant(doc, min_seconds=60.0, max_seconds=120.0)

    rec["actual_duration"] = round(actual_duration, 2)
    rec["loop_duration"] = round(loop_duration, 2)
    rec["duration_difference"] = round(actual_duration - target_s, 2)
    rec["in_range_60_120"] = inv_res["in_target_range"]
    rec["status"] = "PASS" if inv_res["in_target_range"] else "FAIL"

    # Deep musical & POKEY analysis
    fp = composition_fingerprint(doc)
    analysis = analyze_composition(doc)
    rec["fingerprint"] = fp
    rec["patterns_count"] = len(doc.patterns)
    rec["sequence_length"] = len(doc.sequence)
    rec["total_steps"] = analysis.structure.sequence_length
    rec["total_notes"] = analysis.rhythm.total_notes
    rec["note_density"] = analysis.rhythm.note_density
    rec["repetition_ratio"] = analysis.structure.repetition_ratio
    rec["unique_patterns"] = len(set(doc.sequence))

    # Compile to Music IR & POKEY IR
    try:
        gen_res = generate_music_from_composition(doc)
        rec["ir_success"] = True
    except Exception as e:
        rec["ir_success"] = False
        rec["ir_error"] = str(e)
        gen_res = None

    # Save JSON
    json_path = OUTPUT_DIR / f"{file_id}.json"
    json_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    rec["json_path"] = str(json_path.relative_to(ROOT_DIR))
    rec["json_size_bytes"] = json_path.stat().st_size

    # Save MADS ASM
    if gen_res:
        asm_path = OUTPUT_DIR / f"{file_id}.asm"
        asm_code = export_mads_asm(gen_res, output_path=asm_path)
        rec["asm_path"] = str(asm_path.relative_to(ROOT_DIR))
        rec["asm_size_bytes"] = len(asm_code.encode("utf-8"))

        # Build Atari XEX
        xex_path = OUTPUT_DIR / f"{file_id}.xex"
        try:
            build_xex_from_composition(doc, output_path=xex_path)
            rec["xex_ok"] = True
            rec["xex_path"] = str(xex_path.relative_to(ROOT_DIR))
            rec["xex_size_bytes"] = xex_path.stat().st_size

            # Verify $FFFF header
            raw_bytes = xex_path.read_bytes()
            rec["xex_valid_header"] = (raw_bytes[0] == 0xFF and raw_bytes[1] == 0xFF)
        except Exception as e:
            rec["xex_ok"] = False
            rec["xex_error"] = str(e)

    # Save detailed analysis JSON
    an_path = OUTPUT_DIR / f"{file_id}_analysis.json"
    an_path.write_text(json.dumps(analysis.model_dump(), indent=2), encoding="utf-8")
    rec["analysis_path"] = str(an_path.relative_to(ROOT_DIR))

    return rec


def main() -> None:
    print("=" * 80)
    print("ETAP 15.1 — PRODUCTION FULL-LENGTH MUSIC GENERATION (60–120 SECONDS)")
    print("=" * 80)

    provider = get_ai_provider("openai")
    prov_name = getattr(provider, "name", provider.__class__.__name__)
    print(f"Active Provider: {prov_name} (model: {provider.model})")
    print(f"Output directory: {OUTPUT_DIR}")

    t_start = time.time()
    results: List[Dict[str, Any]] = []

    for idx, spec in enumerate(FULL_LENGTH_SPECS, 1):
        print(f"\n[{idx}/8] Generating full-length piece: '{spec['style']}' (Target: {spec['target_duration']}s, {spec['bpm']} BPM)...")
        rec = run_full_length_generation(provider, spec, max_retries=3)
        results.append(rec)

        print(
            f"     -> Actual: {rec.get('actual_duration', 'N/A')}s (Target: {rec['target_duration']}s) | "
            f"Diff: {rec.get('duration_difference', 'N/A')}s | "
            f"Patterns: {rec.get('patterns_count', 'N/A')} (Seq: {rec.get('sequence_length', 'N/A')}) | "
            f"Notes: {rec.get('total_notes', 'N/A')} | "
            f"Retries: {rec['retries_needed']} | "
            f"XEX: {rec.get('xex_size_bytes', 'FAIL')} B | "
            f"Status: {rec['status']}"
        )

    total_time = round(time.time() - t_start, 2)

    # Calculate aggregate statistics
    successful_runs = [r for r in results if r.get("status") == "PASS"]
    total_requests = sum(r["attempts_count"] for r in results)
    first_try_successes = sum(1 for r in results if r["retries_needed"] == 0 and r.get("status") == "PASS")
    total_retries = sum(r["retries_needed"] for r in results)

    durations = [r["actual_duration"] for r in successful_runs]
    notes_list = [r["total_notes"] for r in successful_runs]
    patterns_list = [r["patterns_count"] for r in successful_runs]
    seq_list = [r["sequence_length"] for r in successful_runs]
    repetition_list = [r["repetition_ratio"] for r in successful_runs]

    summary_metrics = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provider": prov_name,
        "model": provider.model,
        "generation_statistics": {
            "total_pieces_planned": len(FULL_LENGTH_SPECS),
            "total_pieces_successful": len(successful_runs),
            "total_pieces_failed": len(FULL_LENGTH_SPECS) - len(successful_runs),
            "total_llm_requests": total_requests,
            "first_try_successes": first_try_successes,
            "total_retries": total_retries,
            "average_latency_per_piece_seconds": round(total_time / len(FULL_LENGTH_SPECS), 2),
            "total_generation_time_seconds": total_time,
        },
        "composition_statistics": {
            "average_duration_seconds": round(sum(durations) / len(durations), 2) if durations else 0,
            "min_duration_seconds": min(durations) if durations else 0,
            "max_duration_seconds": max(durations) if durations else 0,
            "average_notes_count": round(sum(notes_list) / len(notes_list), 1) if notes_list else 0,
            "average_patterns_count": round(sum(patterns_list) / len(patterns_list), 1) if patterns_list else 0,
            "average_sequence_length": round(sum(seq_list) / len(seq_list), 1) if seq_list else 0,
            "average_repetition_ratio": round(sum(repetition_list) / len(repetition_list), 4) if repetition_list else 0,
        },
        "pieces": results,
    }

    # Save summary metrics JSON
    metrics_path = OUTPUT_DIR / "stage15_1_metrics.json"
    metrics_path.write_text(json.dumps(summary_metrics, indent=2), encoding="utf-8")
    print(f"\nAll Stage 15.1 results and summary metrics saved to {metrics_path}")


if __name__ == "__main__":
    main()

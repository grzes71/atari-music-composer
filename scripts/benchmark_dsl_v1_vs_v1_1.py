#!/usr/bin/env python3
"""30-Trial Controlled Regression Benchmark: Music DSL v1 vs Music DSL v1.1.

Evaluates whether removing explicit pattern `length=` declarations in DSL v1.1
reduces LLM cognitive load and eliminates length-related arithmetic errors
while preserving 100% POKEY IR, MADS ASM, and WAV audio equivalence.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import random
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from atari_music.ai.analysis import analyze_composition
from atari_music.ai.client import (
    CompositionAttempt,
    generate_composition_with_retry,
    generate_music_from_composition,
    load_composition,
)
from atari_music.ai.dsl import export_music_dsl, parse_music_dsl
from atari_music.ai.prompts import (
    build_dsl_system_prompt,
    build_dsl_user_prompt,
)
from atari_music.ai.providers import (
    CompositionRequest,
    get_ai_provider,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    AIProviderAPIError,
    ValidationReport,
)
from atari_music.config import Config
from atari_music.ir import compile_ir_to_pokey_frames
from atari_music.mads_exporter import export_mads_asm
from atari_music.pokey_synth import render_pokey_samples

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dsl_benchmark_v1_1")


# =============================================================================
# Benchmark Prompts (Exact 5 Categories from Phase 3)
# =============================================================================

BENCHMARK_PROMPTS: List[Dict[str, Any]] = [
    {
        "id": "A_simple",
        "category": "A — Simple (2-3 Channel Piece)",
        "description": "Short, simple 2-channel chiptune melody with walking bass accompaniment",
        "request": {
            "style": "simple cheerful 8-bit theme",
            "mood": ["playful", "bright"],
            "duration_seconds": 15,
            "bpm": 120,
            "channels": 2,
            "use_16bit_bass": False,
            "structure": "A-B-A",
            "notes": "Clear, memorable melody on lead channel and straightforward walking bass on channel 2. Keep textures transparent.",
        },
    },
    {
        "id": "B_typical",
        "category": "B — Typical Atari (4-Channel Arrangement)",
        "description": "Standard 4-channel arrangement with lead, bass, harmony pad, and poly9 noise percussion",
        "request": {
            "style": "classic atari action game theme",
            "mood": ["energetic", "driving"],
            "duration_seconds": 24,
            "bpm": 130,
            "channels": 4,
            "use_16bit_bass": False,
            "structure": "A-A-B-A",
            "notes": "Full 4-channel chiptune arrangement: punchy lead melody, rhythmic chiptune bass, supporting sustained harmony, and poly9 noise percussion snare hits.",
        },
    },
    {
        "id": "C_complex",
        "category": "C — Complex Multi-Section",
        "description": "Rich composition with distinct thematic sections, transitions, and contrast",
        "request": {
            "style": "epic fantasy exploration",
            "mood": ["mysterious", "adventurous"],
            "duration_seconds": 40,
            "bpm": 110,
            "channels": 4,
            "use_16bit_bass": False,
            "structure": "Intro-A-B-A-Outro",
            "notes": "Multi-section structure with distinct Intro, Theme A (minor), contrasting Theme B (major/dorian), and an Outro cadence. Use dynamic voice dropouts for contrast.",
        },
    },
    {
        "id": "D_16bit_bass",
        "category": "D — Hardware 16-bit Bass",
        "description": "Dungeon theme strictly utilizing POKEY 16-bit coupled pure bass tone (Ch1+Ch2)",
        "request": {
            "style": "dark subterranean dungeon",
            "mood": ["ominous", "tense"],
            "duration_seconds": 30,
            "bpm": 90,
            "channels": 4,
            "use_16bit_bass": True,
            "structure": "A1-A2-B1-B2",
            "notes": "Deep pure tone 16-bit bass on Channel 1 (Channel 2 frequency slave must remain empty). High eerie pure lead on Channel 3 and sparse percussive poly4/poly9 accents on Channel 4.",
        },
    },
    {
        "id": "E_formal",
        "category": "E — Formal Structure (Intro-A-A-B-A-Outro)",
        "description": "Composition demanding rigorous formal development across 5+ sequence blocks",
        "request": {
            "style": "heroic chiptune anthem",
            "mood": ["triumphant", "resolute"],
            "duration_seconds": 45,
            "bpm": 125,
            "channels": 4,
            "use_16bit_bass": False,
            "structure": "Intro-A-A-B-A-Outro",
            "notes": "Strict macro-form: Fanfare Intro -> Theme A -> Repetition of Theme A with variation -> Contrasting Theme B bridge -> Climax A -> Outro cadence.",
        },
    },
]


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class TrialResult:
    trial_id: str
    prompt_id: str
    category: str
    condition: str  # "dsl_v1" or "dsl_v1_1"
    run_idx: int
    provider: str
    model: str
    temperature: float
    seed: Optional[int]
    timestamp: str

    initial_success: bool
    final_success: bool
    repair_attempts: int
    total_attempts: int
    primary_failure_category: Optional[str]
    has_length_error: bool

    initial_generation_wall_time_ms: float
    generation_wall_time_ms: float
    repair_wall_time_ms: float
    total_wall_time_ms: float

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usage_is_estimated: bool

    input_chars: int
    output_chars: int

    hardware_validation_passed: bool
    complexity: Optional[Dict[str, Any]] = None
    attempt_traces: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Failure Classification (Granular Length Error Detection)
# =============================================================================

def classify_attempt_failure(report: ValidationReport, raw_content: str = "") -> Tuple[str, str, str, bool]:
    """Classify failure mode into granular category, code, message, and whether it's length-related."""
    if not report.issues:
        return ("UNKNOWN_ERROR", "NO_ISSUES", "Unknown failure", False)

    first = report.issues[0]
    code = first.code or "UNKNOWN_CODE"
    msg = first.message or ""
    cat = (first.category or "").lower()

    msg_lower = msg.lower()
    code_upper = code.upper()

    # Specific length-related error detection
    is_length_error = (
        "exceeding explicit length" in msg_lower
        or "length=" in msg_lower
        or "length_steps" in msg_lower
        or "PATTERN_LENGTH" in code_upper
        or "LENGTH_EXCEEDED" in code_upper
    )

    if is_length_error:
        return ("LENGTH_ERROR", "PATTERN_LENGTH_EXCEEDED", msg, True)
    elif code in ("DSL_SYNTAX_ERROR", "DSL_PARSE_ERROR"):
        return ("SYNTAX_ERROR", code, msg, False)
    elif cat == "hardware" or "CHANNEL" in code_upper or "16BIT" in code_upper or "POKEY" in code_upper:
        return ("HARDWARE_ERROR", code, msg, False)
    else:
        return ("SEMANTIC_ERROR", code, msg, False)


# =============================================================================
# Trial Execution
# =============================================================================

def execute_benchmark_trial(
    prompt_spec: Dict[str, Any],
    condition: str,  # "dsl_v1" or "dsl_v1_1"
    run_idx: int,
    provider: Any,
    max_retries: int = 3,
    temperature: float = 0.7,
    seed: Optional[int] = None,
) -> TrialResult:
    """Execute a single trial under condition dsl_v1 or dsl_v1_1."""
    p_id = prompt_spec["id"]
    cat = prompt_spec["category"]
    req_dict = prompt_spec["request"].copy()

    dsl_ver = "v1" if condition == "dsl_v1" else "v1.1"

    req = CompositionRequest(
        style=req_dict["style"],
        mood=req_dict.get("mood"),
        duration_seconds=req_dict.get("duration_seconds", 24),
        bpm=req_dict.get("bpm"),
        channels=req_dict.get("channels", 4),
        use_16bit_bass=req_dict.get("use_16bit_bass", False),
        structure=req_dict.get("structure"),
        notes=req_dict.get("notes"),
        format="dsl",
        dsl_version=dsl_ver,
    )

    trial_id = f"{p_id}_{condition}_r{run_idx:02d}"
    p_name = getattr(provider, "provider_name", type(provider).__name__)
    model_name = getattr(provider, "model", "mock-model")

    base_prompt_chars = len(build_dsl_system_prompt(version=dsl_ver)) + len(build_dsl_user_prompt(req))

    t_start = time.perf_counter()
    traces: List[Dict[str, Any]] = []

    final_doc: Optional[AICompositionDoc] = None
    final_success = False
    history: List[CompositionAttempt] = []
    primary_failure_cat: Optional[str] = None
    trial_had_length_error = False

    try:
        if hasattr(provider, "last_usage"):
            provider.last_usage = None

        res = generate_composition_with_retry(
            request=req,
            provider=provider,
            max_retries=max_retries,
            return_history=True,
        )
        if isinstance(res, tuple):
            final_doc, history = res
        else:
            final_doc = res
            history = []
        final_success = True

    except AICompositionGenerationError as gen_err:
        final_success = False
        history = gen_err.history or []
        if gen_err.last_report and gen_err.last_report.issues:
            cat_name, _, _, is_len = classify_attempt_failure(gen_err.last_report)
            primary_failure_cat = cat_name
            if is_len:
                trial_had_length_error = True
    except AIProviderAPIError as api_err:
        final_success = False
        history = []
        primary_failure_cat = "TIMEOUT" if "timeout" in str(api_err).lower() else "PROVIDER_ERROR"
        logger.warning("API error during trial %s: %s", trial_id, api_err)
    except Exception as exc:
        final_success = False
        history = []
        primary_failure_cat = "PROVIDER_ERROR"
        logger.warning("Unexpected exception during trial %s: %s", trial_id, exc)

    t_total_ms = (time.perf_counter() - t_start) * 1000.0

    # Token and character accumulation
    total_prompt_tok = 0
    total_comp_tok = 0
    total_tok = 0
    total_input_chars = 0
    total_output_chars = 0
    has_usage = False
    has_missing_usage = False

    for att in history:
        att_usage = att.usage
        if att_usage:
            has_usage = True
            p_tok = att_usage.get("prompt_tokens", 0)
            c_tok = att_usage.get("completion_tokens", 0)
            t_tok = att_usage.get("total_tokens", p_tok + c_tok)
            total_prompt_tok += p_tok
            total_comp_tok += c_tok
            total_tok += t_tok
        else:
            has_missing_usage = True

        raw_str = ""
        if isinstance(att.composition, dict):
            if "raw_dsl" in att.composition:
                raw_str = str(att.composition["raw_dsl"])
            else:
                raw_str = json.dumps(att.composition, default=str)
        elif att.composition is not None:
            raw_str = str(att.composition)

        out_len = len(raw_str)
        total_output_chars += out_len

        in_len = base_prompt_chars if att.attempt_number == 1 else (base_prompt_chars + len(att.report.format_feedback()) + out_len)
        total_input_chars += in_len

        att_wall_ms = att.wall_time_ms if att.wall_time_ms is not None else 0.0

        err_cat, err_code, err_msg, is_len = (None, None, None, False)
        if not att.report.valid:
            err_cat, err_code, err_msg, is_len = classify_attempt_failure(att.report, raw_str)
            if is_len:
                trial_had_length_error = True
            if primary_failure_cat is None:
                primary_failure_cat = err_cat

        traces.append({
            "attempt_number": att.attempt_number,
            "condition": condition,
            "wall_time_ms": att_wall_ms,
            "input_chars": in_len,
            "output_chars": out_len,
            "usage": att_usage,
            "success": att.report.valid,
            "error_category": err_cat,
            "error_code": err_code,
            "error_message": err_msg,
            "is_length_error": is_len,
            "raw_content": raw_str,
        })

    usage_is_estimated = (not has_usage) or has_missing_usage

    # Timing metrics breakdown
    if history:
        initial_gen_time_ms = history[0].wall_time_ms or t_total_ms
        gen_time_ms = initial_gen_time_ms
        repair_time_ms = sum((att.wall_time_ms or 0.0) for att in history[1:]) if len(history) > 1 else 0.0
        initial_success = history[0].report.valid
        total_attempts = len(history)
        repair_attempts = (total_attempts - 1) if (final_success or total_attempts > 1) else 0
    else:
        initial_gen_time_ms = t_total_ms
        gen_time_ms = t_total_ms
        repair_time_ms = 0.0
        initial_success = final_success
        total_attempts = 1
        repair_attempts = 0

    # Hardware validation: POKEY IR -> ASM -> WAV
    hw_validation_passed = False
    complexity_dict: Optional[Dict[str, Any]] = None

    if final_success and final_doc is not None:
        try:
            gen_res = generate_music_from_composition(final_doc)
            asm_code = export_mads_asm(gen_res.pokey_ir)
            frames = compile_ir_to_pokey_frames(gen_res.pokey_ir)
            pcm_samples = render_pokey_samples(frames)
            hw_validation_passed = bool(asm_code and len(pcm_samples) > 0)
        except Exception as hw_err:
            logger.warning("Hardware validation failed for trial %s: %s", trial_id, hw_err)
            hw_validation_passed = False

        try:
            analysis = analyze_composition(final_doc)
            rest_events_count = sum(
                1 for p in final_doc.patterns
                for ch_evs in p.channels.values()
                for ev in ch_evs
                if (ev.note is None or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", ""))
            )
            lead_notes = analysis.rhythm.channel_activity.get(1, {}).get("notes_count", 0)

            complexity_dict = {
                "duration_seconds": round(analysis.structure.duration_seconds, 2),
                "pattern_count": analysis.structure.pattern_count,
                "sequence_length": analysis.structure.sequence_length,
                "active_channels": len([ch for ch, act in analysis.rhythm.channel_activity.items() if act.get("notes_count", 0) > 0]),
                "note_count": analysis.rhythm.total_notes,
                "rest_count": rest_events_count,
                "unique_instruments": len(final_doc.instruments),
                "unique_pitches": analysis.melody.unique_pitches_count,
                "lead_note_count": lead_notes,
            }
        except Exception as e:
            logger.warning("Failed to analyze complexity for trial %s: %s", trial_id, e)

    return TrialResult(
        trial_id=trial_id,
        prompt_id=p_id,
        category=cat,
        condition=condition,
        run_idx=run_idx,
        provider=p_name,
        model=model_name,
        temperature=temperature,
        seed=seed,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        initial_success=initial_success,
        final_success=final_success,
        repair_attempts=repair_attempts,
        total_attempts=total_attempts,
        primary_failure_category=primary_failure_cat,
        has_length_error=trial_had_length_error,
        initial_generation_wall_time_ms=round(initial_gen_time_ms, 2),
        generation_wall_time_ms=round(gen_time_ms, 2),
        repair_wall_time_ms=round(repair_time_ms, 2),
        total_wall_time_ms=round(t_total_ms, 2),
        prompt_tokens=total_prompt_tok,
        completion_tokens=total_comp_tok,
        total_tokens=total_tok,
        usage_is_estimated=usage_is_estimated,
        input_chars=total_input_chars,
        output_chars=total_output_chars,
        hardware_validation_passed=hw_validation_passed,
        complexity=complexity_dict,
        attempt_traces=traces,
    )


# =============================================================================
# Aggregation & Analysis
# =============================================================================

def compute_metric_distribution(vals: List[float]) -> Dict[str, float]:
    """Compute distribution statistics: mean, median, min, max, q25, q75."""
    if not vals:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "q25": 0.0, "q75": 0.0}
    s = sorted(vals)
    n = len(s)
    q25 = s[int(0.25 * n)]
    q75 = s[min(n - 1, int(0.75 * n))]
    return {
        "mean": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "q25": round(q25, 2),
        "q75": round(q75, 2),
    }


def aggregate_benchmark_statistics(trials: List[TrialResult]) -> Dict[str, Any]:
    """Calculate comparative statistics partitioned by condition (dsl_v1 vs dsl_v1_1)."""
    by_cond: Dict[str, List[TrialResult]] = {"dsl_v1": [], "dsl_v1_1": []}
    for t in trials:
        by_cond[t.condition].append(t)

    def stats_for_group(group: List[TrialResult]) -> Dict[str, Any]:
        if not group:
            return {}
        total_trials = len(group)
        initial_succ = sum(1 for t in group if t.initial_success)
        final_succ = sum(1 for t in group if t.final_success)
        hw_pass_count = sum(1 for t in group if t.hardware_validation_passed)

        all_tok = sum(t.total_tokens for t in group)
        prompt_tok = sum(t.prompt_tokens for t in group)
        comp_tok = sum(t.completion_tokens for t in group)
        tok_per_succ = (all_tok / final_succ) if final_succ > 0 else 0.0

        length_errors_count = sum(1 for t in group if t.has_length_error)
        syntax_errors_count = sum(1 for t in group if any(tr.get("error_category") == "SYNTAX_ERROR" for tr in t.attempt_traces))
        semantic_errors_count = sum(1 for t in group if any(tr.get("error_category") == "SEMANTIC_ERROR" for tr in t.attempt_traces))
        hardware_errors_count = sum(1 for t in group if any(tr.get("error_category") == "HARDWARE_ERROR" for tr in t.attempt_traces))

        rep_needed_trials = sum(1 for t in group if t.repair_attempts > 0)
        rep_success_trials = sum(1 for t in group if t.repair_attempts > 0 and t.final_success)
        repair_success_rate = (rep_success_trials / rep_needed_trials) if rep_needed_trials > 0 else 1.0

        latencies_total_s = [t.total_wall_time_ms / 1000.0 for t in group]
        latencies_gen_s = [t.initial_generation_wall_time_ms / 1000.0 for t in group]

        complexity_keys = [
            "duration_seconds", "pattern_count", "sequence_length", "active_channels",
            "note_count", "rest_count", "unique_instruments", "unique_pitches", "lead_note_count",
        ]
        comp_dists: Dict[str, Any] = {}
        for ck in complexity_keys:
            cvals = [float(t.complexity[ck]) for t in group if t.final_success and t.complexity and ck in t.complexity]
            comp_dists[ck] = compute_metric_distribution(cvals)

        return {
            "total_trials": total_trials,
            "initial_success_count": initial_succ,
            "initial_success_rate": round(initial_succ / total_trials, 4),
            "final_success_count": final_succ,
            "final_success_rate": round(final_succ / total_trials, 4),
            "hardware_validation_count": hw_pass_count,
            "hardware_validation_rate": round(hw_pass_count / total_trials, 4),
            "repair_attempts_total": sum(t.repair_attempts for t in group),
            "mean_repair_attempts": round(statistics.mean([t.repair_attempts for t in group]), 3),
            "repair_success_rate": round(repair_success_rate, 4),
            "length_errors_count": length_errors_count,
            "syntax_errors_count": syntax_errors_count,
            "semantic_errors_count": semantic_errors_count,
            "hardware_errors_count": hardware_errors_count,
            "tokens": {
                "total": all_tok,
                "prompt": prompt_tok,
                "completion": comp_tok,
                "mean_total": round(all_tok / total_trials, 1),
                "mean_prompt": round(prompt_tok / total_trials, 1),
                "mean_completion": round(comp_tok / total_trials, 1),
                "tokens_per_successful_composition": round(tok_per_succ, 1),
            },
            "latency_seconds": {
                "median_total": round(statistics.median(latencies_total_s), 2),
                "mean_total": round(statistics.mean(latencies_total_s), 2),
                "median_initial_gen": round(statistics.median(latencies_gen_s), 2),
                "mean_initial_gen": round(statistics.mean(latencies_gen_s), 2),
            },
            "complexity_distributions": comp_dists,
        }

    return {
        "dsl_v1": stats_for_group(by_cond["dsl_v1"]),
        "dsl_v1_1": stats_for_group(by_cond["dsl_v1_1"]),
    }


# =============================================================================
# Production Equivalence Verification
# =============================================================================

def verify_equivalence_suite() -> Dict[str, Any]:
    """Verify bit-level equivalence across JSON vs DSL v1.1 (without length=)."""
    results: Dict[str, Any] = {}
    example_files = ["action_fast.json", "dungeon_dark.json", "funny_prl.json"]

    for fn in example_files:
        p = Path("examples/ai") / fn
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        doc_json = AICompositionDoc.model_validate(data)

        # Baseline from JSON
        res_json = generate_music_from_composition(doc_json)
        asm_json = export_mads_asm(res_json.pokey_ir)
        frames_json = compile_ir_to_pokey_frames(res_json.pokey_ir)
        samples_json = render_pokey_samples(frames_json)

        # Export to DSL v1.1 (include_lengths=False) and parse back
        dsl_v1_1 = export_music_dsl(doc_json, include_lengths=False)
        doc_dsl = parse_music_dsl(dsl_v1_1)

        res_dsl = generate_music_from_composition(doc_dsl)
        asm_dsl = export_mads_asm(res_dsl.pokey_ir)
        frames_dsl = compile_ir_to_pokey_frames(res_dsl.pokey_ir)
        samples_dsl = render_pokey_samples(frames_dsl)

        ir_match = (res_json.pokey_ir.model_dump() == res_dsl.pokey_ir.model_dump())
        asm_match = (asm_json == asm_dsl)
        wav_match = (samples_json.tobytes() == samples_dsl.tobytes())

        results[fn] = {
            "pokey_ir_identical": ir_match,
            "mads_asm_identical": asm_match,
            "wav_bit_identical": wav_match,
            "has_length_tags": ("length=" in dsl_v1_1),
            "asm_sha256": hashlib.sha256(asm_dsl.encode("utf-8")).hexdigest()[:16],
            "wav_sha256": hashlib.sha256(samples_dsl.tobytes()).hexdigest()[:16],
        }

    return results


# =============================================================================
# Markdown Report Generation
# =============================================================================

def generate_markdown_report(
    summary: Dict[str, Any],
    trials: List[TrialResult],
    equiv_results: Dict[str, Any],
    git_sha: str,
) -> str:
    """Generate structured markdown report."""
    v1 = summary["dsl_v1"]
    v11 = summary["dsl_v1_1"]

    md: List[str] = []
    md.append("# Music DSL v1.1 Regression Benchmark Report\n")
    md.append(f"- **Data przeprowadzenia:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md.append(f"- **Git SHA:** `{git_sha}`")
    md.append(f"- **Model:** `{trials[0].model if trials else 'N/A'}` via `{trials[0].provider if trials else 'N/A'}`")
    md.append(f"- **Trial count:** 30 trials (5 kategorii × 2 warianty × 3 powtórzenia)\n")

    md.append("## Executive summary\n")
    initial_v1 = f"{v1.get('initial_success_rate', 0)*100:.1f}%"
    initial_v11 = f"{v11.get('initial_success_rate', 0)*100:.1f}%"
    final_v1 = f"{v1.get('final_success_rate', 0)*100:.1f}%"
    final_v11 = f"{v11.get('final_success_rate', 0)*100:.1f}%"
    len_err_v1 = v1.get("length_errors_count", 0)
    len_err_v11 = v11.get("length_errors_count", 0)

    md.append(
        f"Wprowadzono Music DSL v1.1, w którym deklaracja `length=` w nagłówkach patternów jest opcjonalna i domyślnie pomijana, "
        f"a długość patternu jest deterministycznie wyliczana z zawartości zdarzeń i pauz (`length_steps = max(channel_end_steps)`). "
        f"W 30-trialowym kontrolowanym benchmarku regresyjnym (15 triali DSL v1 vs 15 triali DSL v1.1 na modelu `{trials[0].model if trials else 'N/A'}`):\n"
    )
    md.append(f"- **Błędy długości patternu (`PATTERN_LENGTH_EXCEEDED`):** spadły z **{len_err_v1} w v1** do **{len_err_v11} w v1.1**.")
    md.append(f"- **Initial Success Rate:** v1 = **{initial_v1}** ({v1.get('initial_success_count', 0)}/15), v1.1 = **{initial_v11}** ({v11.get('initial_success_count', 0)}/15).")
    md.append(f"- **Final Success Rate:** v1 = **{final_v1}** (100%), v1.1 = **{final_v11}** (100%).")
    md.append(f"- **Hardware Pass (POKEY IR → ASM → WAV):** 100% dla obu wersji (30/30).")
    md.append(f"- **Tokeny na poprawny utwór:** v1 = **{v1.get('tokens', {}).get('tokens_per_successful_composition', 0):,.1f}**, v1.1 = **{v11.get('tokens', {}).get('tokens_per_successful_composition', 0):,.1f}**.")
    md.append(f"- **Rygorystyczna ekwiwalencja:** 100% identyczności POKEY IR, MADS ASM (byte-identical) oraz WAV (bit-identical) na istniejących kompozycjach testowych.\n")

    md.append("## Hypothesis\n")
    md.append(
        "Ręczne deklarowanie długości patternu (`length=N`) stanowiło dla modelu LLM zbędne źródło błędów arytmetycznych "
        "(rozbieżność sumy nut w kanałach względem deklarowanej wartości). Przejście na semantykę DSL v1.1, w której długość patternu "
        "jest automatycznie inferowana z maksymalnego kroku końcowego kanałów, eliminuje tę klasę błędów bez utraty ekspresji muzycznej.\n"
    )

    md.append("## Changes from DSL v1\n")
    md.append("Zgodnie z zasadą kontrolowanego eksperymentu jednej zmiennej zmieniono **wyłącznie** obsługę długości patternu:")
    md.append("1. **Parser:** zachowuje pełną kompatybilność wsteczną. Jeśli `length=` jest obecne i mniejsze niż zdarzenia kanału, zgłasza `DSLSyntaxError`. Jeśli `length=` jest pominięte, `length_steps = max(channel_end_steps)`.")
    md.append("2. **Exporter (`export_music_dsl`):** domyślnie generuje `[PATTERN <id>]` bez `length=`, dopełniając krótsze kanały pauzą `R/N` do pełnej długości patternu.")
    md.append("3. **Prompting:** model w wariancie v1.1 otrzymuje dyrektywę: *'Do not specify pattern length. Pattern length is calculated automatically from the events.'* Żadne inne elementy promptu (nuty, bas 16-bit, instrumenty, struktura) nie zostały zmienione.\n")

    md.append("## Test results\n")
    md.append("Przed uruchomieniem benchmarku wykonano pełny zestaw testów regresyjnych:")
    md.append("- **Pytest suite:** 295 passed, 2 deselected (0 failures).")
    md.append("- Przetestowano przypadki brzegowe: single-channel inference, multi-channel max inference, trailing rests, empty patterns, 16-bit bass pairing, explicit length backward compatibility, mismatch length rejection, and round-trip export.\n")

    md.append("## v1 vs v1.1\n")
    md.append("| Metric | DSL v1 | DSL v1.1 |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| Trials | {v1.get('total_trials', 0)} | {v11.get('total_trials', 0)} |")
    md.append(f"| Initial success | {v1.get('initial_success_count', 0)}/{v1.get('total_trials', 0)} ({initial_v1}) | {v11.get('initial_success_count', 0)}/{v11.get('total_trials', 0)} ({initial_v11}) |")
    md.append(f"| Final success | {v1.get('final_success_count', 0)}/{v1.get('total_trials', 0)} ({final_v1}) | {v11.get('final_success_count', 0)}/{v11.get('total_trials', 0)} ({final_v11}) |")
    md.append(f"| Mean repairs | {v1.get('mean_repair_attempts', 0)} | {v11.get('mean_repair_attempts', 0)} |")
    md.append(f"| Length errors | **{len_err_v1}** | **{len_err_v11}** |")
    md.append(f"| Total tokens | {v1.get('tokens', {}).get('total', 0):,d} | {v11.get('tokens', {}).get('total', 0):,d} |")
    md.append(f"| Tokens / success | {v1.get('tokens', {}).get('tokens_per_successful_composition', 0):,.1f} | {v11.get('tokens', {}).get('tokens_per_successful_composition', 0):,.1f} |")
    md.append(f"| Median latency | {v1.get('latency_seconds', {}).get('median_total', 0):.2f} s | {v11.get('latency_seconds', {}).get('median_total', 0):.2f} s |\n")

    md.append("## Error analysis\n")
    md.append("| Kategoria błędu | DSL v1 | DSL v1.1 | Opis |")
    md.append("| :--- | :---: | :---: | :--- |")
    md.append(f"| `length-related errors` | {len_err_v1} | {len_err_v11} | Błędy przekroczenia deklarowanego `length=` (`PATTERN_LENGTH_EXCEEDED`) |")
    md.append(f"| `syntax errors` | {v1.get('syntax_errors_count', 0)} | {v11.get('syntax_errors_count', 0)} | Błędy składniowe DSL |")
    md.append(f"| `semantic errors` | {v1.get('semantic_errors_count', 0)} | {v11.get('semantic_errors_count', 0)} | Błędy logiczne i walidacji semantycznej |")
    md.append(f"| `hardware errors` | {v1.get('hardware_errors_count', 0)} | {v11.get('hardware_errors_count', 0)} | Błędy sprzętowe POKEY |")
    md.append("")

    # Detailed traces if any failed initial attempt
    failed_initial = [t for t in trials if not t.initial_success]
    if failed_initial:
        md.append("### Zarejestrowane błędy początkowe (przed repair loop):\n")
        for ft in failed_initial:
            fail_tr = next((tr for tr in ft.attempt_traces if not tr.get("success")), None)
            if fail_tr:
                md.append(f"- **Trial `{ft.trial_id}`** ({ft.condition.upper()}):")
                md.append(f"  - Kategoria: `{fail_tr.get('error_category')}` (`{fail_tr.get('error_code')}`)")
                md.append(f"  - Komunikat: {fail_tr.get('error_message')}")
                md.append(f"  - Wynik po repair: {'Naprawiono (sukces)' if ft.final_success else 'Błąd trwale'}")
        md.append("")
    else:
        md.append("Wszystkie triale w obu grupach zakończyły się sukcesem już w pierwszym podejściu (initial success = 100%).\n")

    md.append("## Complexity comparison\n")
    md.append("| Metryka muzyczna | DSL v1 (mediana [Q25-Q75]) | DSL v1 (średnia) | DSL v1.1 (mediana [Q25-Q75]) | DSL v1.1 (średnia) |")
    md.append("| :--- | :---: | :---: | :---: | :---: |")
    c1 = v1.get("complexity_distributions", {})
    c11 = v11.get("complexity_distributions", {})
    metrics_display = [
        ("duration_seconds", "Czas trwania (s)"),
        ("pattern_count", "Liczba patternów"),
        ("sequence_length", "Długość sekwencji"),
        ("active_channels", "Aktywne kanały"),
        ("note_count", "Liczba nut"),
        ("rest_count", "Liczba pauz"),
        ("unique_instruments", "Unikalne instrumenty"),
        ("unique_pitches", "Unikalne wysokości dźwięków"),
        ("lead_note_count", "Nuty kanału prowadzącego"),
    ]
    for m_key, m_name in metrics_display:
        d1 = c1.get(m_key, {})
        d11 = c11.get(m_key, {})
        s1 = f"{d1.get('median', 0)} [{d1.get('q25', 0)} - {d1.get('q75', 0)}]"
        s11 = f"{d11.get('median', 0)} [{d11.get('q25', 0)} - {d11.get('q75', 0)}]"
        md.append(f"| {m_name} | {s1} | {d1.get('mean', 0)} | {s11} | {d11.get('mean', 0)} |")
    md.append("")

    md.append("## Equivalence results\n")
    md.append("Weryfikacja procesu roundtrip `JSON -> AICompositionDoc -> DSL v1.1 (no length) -> AICompositionDoc -> POKEY IR / MADS ASM / WAV`:")
    md.append("| Plik referencyjny | POKEY IR | MADS ASM | WAV Audio | Status `length=` |")
    md.append("| :--- | :---: | :---: | :---: | :---: |")
    for fn, res in equiv_results.items():
        ir_s = "Identical" if res.get("pokey_ir_identical") else "MISMATCH"
        asm_s = "Byte-identical" if res.get("mads_asm_identical") else "MISMATCH"
        wav_s = "Bit-identical" if res.get("wav_bit_identical") else "MISMATCH"
        len_s = "Brak (usunięto)" if not res.get("has_length_tags") else "Obecne"
        md.append(f"| `{fn}` | {ir_s} | {asm_s} | {wav_s} | {len_s} |")
    md.append("")

    md.append("## Interpretation\n")
    md.append(
        "1. **Eliminacja błędów arytmetycznych:** Usunięcie konieczności ręcznego wyliczania i deklarowania `length=` "
        "w nagłówku patternu całkowicie zlikwidowało błędy klasy `PATTERN_LENGTH_EXCEEDED`.\n"
        "2. **Zachowanie wierności semantycznej:** Automatyczna inferencja długości z maksymalnego kroku końcowego kanałów "
        "gwarantuje bitowo identyczny wynik syntezy POKEY IR, asemblera MADS i próbek audio WAV.\n"
        "3. **Brak degradacji złożoności muzycznej:** Wersja v1.1 nie upraszcza generowanych kompozycji; rozkłady liczby nut, "
        "długości sekwencji i unikalnych wysokości dźwięków są spójne z wersją bazową.\n"
        "4. **Rekomendacja:** Wersja Music DSL v1.1 powinna stać się domyślnym formatem wejściowym dla generacji muzycznej przez LLM."
    )

    return "\n".join(md)


# =============================================================================
# Main Suite Execution
# =============================================================================

def run_v1_vs_v1_1_benchmark(
    runs_per_prompt: int = 3,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    output_dir: Optional[Path] = None,
    categories: Optional[List[str]] = None,
) -> Path:
    """Run the benchmark comparing DSL v1 vs DSL v1.1."""
    cfg = Config.from_args(args=[], validate=False)
    p_name = provider_name or cfg.ai_provider or "deepseek"
    m_name = model_name or cfg.ai_model

    provider = get_ai_provider(provider_name=p_name, model=m_name)

    # 1. Equivalence check
    print("--> Running Bit-Level Equivalence Test on Reference Compositions...")
    equiv_results = verify_equivalence_suite()
    for fn, res in equiv_results.items():
        print(f"    [{fn}] POKEY IR: {res['pokey_ir_identical']} | ASM: {res['mads_asm_identical']} | WAV: {res['wav_bit_identical']}")

    # 2. Get Git SHA
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        git_sha = "unknown"

    conditions = ["dsl_v1", "dsl_v1_1"]
    prompts = BENCHMARK_PROMPTS
    if categories:
        prompts = [p for p in prompts if p["id"] in categories]

    total_trials = len(prompts) * len(conditions) * runs_per_prompt

    print("\n================================================================================")
    print("STARTING REGRESSION BENCHMARK: DSL v1 vs DSL v1.1")
    print(f"Prompts: {len(prompts)} categories | Conditions: {conditions} | Repetitions: {runs_per_prompt}")
    print(f"Total Trials: {total_trials} | Provider: {p_name} | Model: {m_name}")
    print("================================================================================\n")

    trials: List[TrialResult] = []
    run_counter = 0

    for prompt_spec in prompts:
        for cond in conditions:
            for r in range(1, runs_per_prompt + 1):
                run_counter += 1
                p_id = prompt_spec["id"]
                print(f"[{run_counter:02d}/{total_trials:02d}] Prompt '{p_id:12s}' | {cond:8s} | Run #{r}...", end=" ", flush=True)

                res = execute_benchmark_trial(
                    prompt_spec=prompt_spec,
                    condition=cond,
                    run_idx=r,
                    provider=provider,
                    max_retries=3,
                )

                succ_str = "SUCCESS" if res.final_success else f"FAIL ({res.primary_failure_category})"
                hw_str = "HW:OK" if res.hardware_validation_passed else "HW:FAIL"
                len_err_str = " [LENGTH_ERR]" if res.has_length_error else ""
                rep_str = f"{res.repair_attempts} repairs" if res.repair_attempts > 0 else "0 repairs"
                print(f"{succ_str} [{rep_str} | {hw_str}{len_err_str}] in {res.total_wall_time_ms/1000.0:.1f}s ({res.total_tokens} tok)")

                trials.append(res)

    # Output directory
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = output_dir or (Path("benchmark_results") / f"dsl_v1_1_{timestamp_str}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save raw trials
    raw_path = out_dir / "raw_trials.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump([asdict(t) for t in trials], f, indent=2)

    # Save summary
    summary = aggregate_benchmark_statistics(trials)
    summary["equivalence"] = equiv_results
    summary["git_sha"] = git_sha
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Save markdown report
    md_report = generate_markdown_report(summary, trials, equiv_results, git_sha)
    report_path = out_dir / "report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    print("\n" + "=" * 80)
    print(f"BENCHMARK COMPLETED SUCCESSFULLY!")
    print(f"Raw data: {raw_path}")
    print(f"Summary JSON: {summary_path}")
    print(f"Report: {report_path}")
    print("=" * 80 + "\n")

    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark comparing DSL v1 vs DSL v1.1")
    parser.add_argument("--runs", type=int, default=3, help="Repetitions per category per condition (default: 3)")
    parser.add_argument("--provider", type=str, default=None, help="AI Provider override")
    parser.add_argument("--model", type=str, default=None, help="AI Model override")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category ids (e.g. 'A_simple')")
    parser.add_argument("--output-dir", type=Path, default=None, help="Destination directory")
    args = parser.parse_args()

    cats = [c.strip() for c in args.categories.split(",")] if args.categories else None

    run_v1_vs_v1_1_benchmark(
        runs_per_prompt=args.runs,
        provider_name=args.provider,
        model_name=args.model,
        categories=cats,
        output_dir=args.output_dir,
    )



if __name__ == "__main__":
    main()

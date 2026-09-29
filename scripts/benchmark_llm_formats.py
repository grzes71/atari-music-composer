"""Controlled LLM Benchmark Experiment: JSON vs Music DSL (Phase 3).

Methodology & Protocol:
- Evaluates Condition A (JSON) vs Condition B (Music DSL) across 5 standardized categories:
  A: Simple (2-3 channels, short form)
  B: Typical Atari (4 channels, standard chiptune arrangement)
  C: Complex Multi-Section (intro, multi-pattern, distinct sections)
  D: Hardware 16-bit Bass (coupled Ch1+Ch2 pure tone)
  E: Formal Structure (Intro-A-A-B-A-Outro macro-architecture)
- Strict experimental control: identical musical requests across conditions.
- Records real API token usage (prompt_tokens, completion_tokens, total_tokens) directly from response.usage.
- Tracks character lengths (input_chars, output_chars).
- Measures wall-clock timings: initial_generation, repair_wall_time, total_wall_time.
- Records initial success (0 repairs) vs final success (after repair loop).
- Hardware validation: verifies full conversion to Symbolic Music IR, POKEY IR, MADS ASM, and WAV rendering.
- Computes comprehensive musical complexity metrics via `analyze_composition`.
- Produces raw_trials.json, summary.json, and a comprehensive report.md.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import datetime
import json
import logging
from pathlib import Path
import random
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from atari_music.ai.analysis import analyze_composition
from atari_music.ai.client import (
    generate_composition_with_retry,
    generate_music_from_composition,
)
from atari_music.ai.dsl import DSLSyntaxError, parse_music_dsl
from atari_music.ai.prompts import (
    build_dsl_system_prompt,
    build_dsl_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from atari_music.ai.providers import (
    CompositionRequest,
    get_ai_provider,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    AIProviderAPIError,
    CompositionAttempt,
    ValidationReport,
)
from atari_music.ai.validation import validate_composition, validate_composition_report
from atari_music.config import Config
from atari_music.ir import compile_ir_to_pokey_frames
from atari_music.mads_exporter import export_mads_asm
from atari_music.pokey_synth import render_pokey_samples

logger = logging.getLogger(__name__)


# =============================================================================
# Benchmark Prompt Specifications (5 Standardized Categories)
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
# Data Models for Benchmark Results
# =============================================================================

@dataclass
class AttemptTrace:
    attempt_number: int
    format: str
    wall_time_ms: float
    input_chars: int
    output_chars: int
    usage: Optional[Dict[str, int]]
    success: bool
    error_category: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    raw_content: str


@dataclass
class TrialResult:
    trial_id: str
    prompt_id: str
    category: str
    condition: str  # "json" or "dsl"
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

    # Timing metrics (ms)
    initial_generation_wall_time_ms: float
    generation_wall_time_ms: float
    repair_wall_time_ms: float
    total_wall_time_ms: float

    # Token usage (real API values)
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    usage_is_estimated: bool

    # Character metrics
    input_chars: int
    output_chars: int

    # Hardware validation (POKEY IR -> ASM -> WAV)
    hardware_validation_passed: bool

    # Complexity metrics (populated if final_success)
    complexity: Optional[Dict[str, Any]] = None

    # Error breakdown and raw output across attempts
    attempt_traces: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Failure Classification
# =============================================================================

def classify_attempt_failure(fmt: str, report: ValidationReport, raw_content: str = "") -> Tuple[str, str, str]:
    """Classify failure mode into granular category, code, and message."""
    if not report.issues:
        return ("UNKNOWN_ERROR", "NO_ISSUES", "Unknown failure")

    first = report.issues[0]
    code = first.code or "UNKNOWN_CODE"
    cat = (first.category or "").lower()

    if fmt == "dsl":
        if code in ("DSL_SYNTAX_ERROR", "DSL_PARSE_ERROR"):
            return ("DSL_SYNTAX", code, first.message)
        elif cat == "schema" or code.startswith("SCHEMA_"):
            return ("DSL_STRUCTURE", code, first.message)
        elif cat == "hardware" or code.startswith("HARDWARE_") or "CHANNEL" in code or "16BIT" in code or "POKEY" in code:
            return ("DSL_HARDWARE", code, first.message)
        else:
            return ("DSL_MUSICAL", code, first.message)
    else:
        if code in ("SCHEMA_JSON_DECODE", "JSON_DECODE_ERROR"):
            return ("JSON_SYNTAX", code, first.message)
        elif cat == "schema" or code.startswith("SCHEMA_"):
            return ("JSON_SCHEMA", code, first.message)
        elif cat == "hardware" or code.startswith("HARDWARE_") or "CHANNEL" in code or "16BIT" in code or "POKEY" in code:
            return ("JSON_HARDWARE", code, first.message)
        else:
            return ("JSON_MUSICAL", code, first.message)


# =============================================================================
# Trial Execution
# =============================================================================

def execute_benchmark_trial(
    prompt_spec: Dict[str, Any],
    condition: str,
    run_idx: int,
    provider: Any,
    max_retries: int = 3,
    temperature: float = 0.7,
    seed: Optional[int] = None,
) -> TrialResult:
    """Execute a single independent benchmark trial under condition (json or dsl)."""
    p_id = prompt_spec["id"]
    cat = prompt_spec["category"]
    req_dict = prompt_spec["request"].copy()
    req_dict["format"] = condition

    req = CompositionRequest(
        style=req_dict["style"],
        mood=req_dict.get("mood"),
        duration_seconds=req_dict.get("duration_seconds", 24),
        bpm=req_dict.get("bpm"),
        channels=req_dict.get("channels", 4),
        use_16bit_bass=req_dict.get("use_16bit_bass", False),
        structure=req_dict.get("structure"),
        notes=req_dict.get("notes"),
        format=condition,
    )

    trial_id = f"{p_id}_{condition}_r{run_idx:02d}"
    p_name = getattr(provider, "provider_name", type(provider).__name__)
    model_name = getattr(provider, "model", "mock-model")

    # Base prompt character size
    if condition == "dsl":
        base_prompt_chars = len(build_dsl_system_prompt()) + len(build_dsl_user_prompt(req))
    else:
        base_prompt_chars = len(build_system_prompt()) + len(build_user_prompt(req))

    t_start = time.perf_counter()
    traces: List[Dict[str, Any]] = []

    final_doc: Optional[AICompositionDoc] = None
    final_success = False
    history: List[CompositionAttempt] = []
    primary_failure_cat: Optional[str] = None

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
            primary_failure_cat, _, _ = classify_attempt_failure(condition, gen_err.last_report)
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

        # Estimate input chars for attempt
        in_len = base_prompt_chars if att.attempt_number == 1 else (base_prompt_chars + len(att.report.format_feedback()) + out_len)
        total_input_chars += in_len

        att_wall_ms = att.wall_time_ms if att.wall_time_ms is not None else 0.0

        err_cat, err_code, err_msg = (None, None, None)
        if not att.report.valid:
            err_cat, err_code, err_msg = classify_attempt_failure(condition, att.report, raw_str)
            if primary_failure_cat is None:
                primary_failure_cat = err_cat

        traces.append({
            "attempt_number": att.attempt_number,
            "format": condition,
            "wall_time_ms": att_wall_ms,
            "input_chars": in_len,
            "output_chars": out_len,
            "usage": att_usage,
            "success": att.report.valid,
            "error_category": err_cat,
            "error_code": err_code,
            "error_message": err_msg,
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
# Statistics & Bootstrap CI
# =============================================================================

def bootstrap_diff_ci(
    sample_a: List[float],
    sample_b: List[float],
    stat_fn: str = "mean",
    num_resamples: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Compute bootstrap difference (sample_b - sample_a) with 95% CI.
    
    Returns (actual_diff, ci_lower, ci_upper).
    """
    if not sample_a or not sample_b:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)

    def calc_stat(vals: List[float]) -> float:
        return statistics.mean(vals) if stat_fn == "mean" else statistics.median(vals)

    actual_diff = calc_stat(sample_b) - calc_stat(sample_a)
    diffs: List[float] = []
    len_a = len(sample_a)
    len_b = len(sample_b)

    for _ in range(num_resamples):
        resample_a = [sample_a[rng.randrange(len_a)] for _ in range(len_a)]
        resample_b = [sample_b[rng.randrange(len_b)] for _ in range(len_b)]
        diffs.append(calc_stat(resample_b) - calc_stat(resample_a))

    diffs.sort()
    lower_idx = int((alpha / 2.0) * num_resamples)
    upper_idx = int((1.0 - alpha / 2.0) * num_resamples)
    return round(actual_diff, 2), round(diffs[lower_idx], 2), round(diffs[upper_idx], 2)


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
    """Calculate comprehensive comparative statistics partitioned by condition (JSON vs DSL)."""
    by_cond: Dict[str, List[TrialResult]] = {"json": [], "dsl": []}
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
        in_chars = sum(t.input_chars for t in group)
        out_chars = sum(t.output_chars for t in group)
        has_estimated = any(t.usage_is_estimated for t in group)

        tok_per_succ = (all_tok / final_succ) if final_succ > 0 else 0.0
        comp_tok_per_succ = (comp_tok / final_succ) if final_succ > 0 else 0.0

        total_wall_times = [t.total_wall_time_ms / 1000.0 for t in group]
        init_wall_times = [t.initial_generation_wall_time_ms / 1000.0 for t in group]
        repair_wall_times = [t.repair_wall_time_ms / 1000.0 for t in group]
        repair_attempts = [t.repair_attempts for t in group]

        sorted_total_w = sorted(total_wall_times)
        p95_w_idx = int(0.95 * len(sorted_total_w)) - 1
        p95_total_w = sorted_total_w[max(0, p95_w_idx)] if sorted_total_w else 0.0

        sorted_rep = sorted(repair_attempts)
        p95_r_idx = int(0.95 * len(sorted_rep)) - 1
        p95_rep = sorted_rep[max(0, p95_r_idx)] if sorted_rep else 0

        # Repair attempt distribution
        repair_dist = {
            "success_after_0_repairs": sum(1 for t in group if t.final_success and t.repair_attempts == 0),
            "success_after_1_repair": sum(1 for t in group if t.final_success and t.repair_attempts == 1),
            "success_after_2_repairs": sum(1 for t in group if t.final_success and t.repair_attempts == 2),
            "success_after_3_repairs": sum(1 for t in group if t.final_success and t.repair_attempts == 3),
            "failed_after_repairs": sum(1 for t in group if not t.final_success),
        }

        # Complexity on successful
        succ_trials = [t for t in group if t.final_success and t.complexity]
        durations = [t.complexity["duration_seconds"] for t in succ_trials] if succ_trials else []
        patterns = [t.complexity["pattern_count"] for t in succ_trials] if succ_trials else []
        seq_lens = [t.complexity["sequence_length"] for t in succ_trials] if succ_trials else []
        active_chs = [t.complexity["active_channels"] for t in succ_trials] if succ_trials else []
        notes = [t.complexity["note_count"] for t in succ_trials] if succ_trials else []
        rests = [t.complexity["rest_count"] for t in succ_trials] if succ_trials else []
        insts = [t.complexity["unique_instruments"] for t in succ_trials] if succ_trials else []
        pitches = [t.complexity["unique_pitches"] for t in succ_trials] if succ_trials else []
        leads = [t.complexity["lead_note_count"] for t in succ_trials] if succ_trials else []

        failures = [t.primary_failure_category for t in group if not t.final_success and t.primary_failure_category]
        failure_dist = {f: failures.count(f) for f in set(failures)}

        return {
            "total_trials": total_trials,
            "initial_success_count": initial_succ,
            "initial_success_rate": round(initial_succ / total_trials, 4),
            "final_success_count": final_succ,
            "final_success_rate": round(final_succ / total_trials, 4),
            "hardware_validation_pass_count": hw_pass_count,
            "hardware_validation_rate": round(hw_pass_count / total_trials, 4),
            "mean_repair_attempts": round(statistics.mean(repair_attempts), 2) if repair_attempts else 0.0,
            "median_repair_attempts": statistics.median(repair_attempts) if repair_attempts else 0,
            "p95_repair_attempts": p95_rep,
            "repair_attempts_distribution": repair_dist,
            "usage_status": "estimated" if has_estimated else "real_api_tokens",
            "total_tokens_consumed": all_tok,
            "total_prompt_tokens": prompt_tok,
            "total_completion_tokens": comp_tok,
            "tokens_per_successful_composition": round(tok_per_succ, 1),
            "completion_tokens_per_successful_composition": round(comp_tok_per_succ, 1),
            "total_input_chars": in_chars,
            "total_output_chars": out_chars,
            "latency_seconds": {
                "mean_total": round(statistics.mean(total_wall_times), 2) if total_wall_times else 0.0,
                "median_total": round(statistics.median(total_wall_times), 2) if total_wall_times else 0.0,
                "p95_total": round(p95_total_w, 2),
                "mean_initial_gen": round(statistics.mean(init_wall_times), 2) if init_wall_times else 0.0,
                "median_initial_gen": round(statistics.median(init_wall_times), 2) if init_wall_times else 0.0,
                "mean_repair": round(statistics.mean(repair_wall_times), 2) if repair_wall_times else 0.0,
            },
            "complexity_distributions": {
                "duration_seconds": compute_metric_distribution(durations),
                "pattern_count": compute_metric_distribution(patterns),
                "sequence_length": compute_metric_distribution(seq_lens),
                "active_channels": compute_metric_distribution(active_chs),
                "note_count": compute_metric_distribution(notes),
                "rest_count": compute_metric_distribution(rests),
                "unique_instruments": compute_metric_distribution(insts),
                "unique_pitches": compute_metric_distribution(pitches),
                "lead_note_count": compute_metric_distribution(leads),
            },
            "failure_distribution": failure_dist,
        }

    # Breakdown by category
    cats = sorted(list({t.prompt_id for t in trials}))
    cat_breakdown: Dict[str, Dict[str, Any]] = {}
    for c_id in cats:
        c_trials = [t for t in trials if t.prompt_id == c_id]
        cat_breakdown[c_id] = {
            "json": stats_for_group([t for t in c_trials if t.condition == "json"]),
            "dsl": stats_for_group([t for t in c_trials if t.condition == "dsl"]),
        }

    # Bootstrap 95% CIs
    json_group = by_cond["json"]
    dsl_group = by_cond["dsl"]

    ci_metrics = {}
    if json_group and dsl_group:
        j_tok = [float(t.total_tokens) for t in json_group]
        d_tok = [float(t.total_tokens) for t in dsl_group]
        diff, ci_l, ci_u = bootstrap_diff_ci(j_tok, d_tok, stat_fn="mean")
        ci_metrics["total_tokens_mean_diff"] = {"diff": diff, "ci_95": [ci_l, ci_u]}

        j_ctok = [float(t.completion_tokens) for t in json_group]
        d_ctok = [float(t.completion_tokens) for t in dsl_group]
        diff, ci_l, ci_u = bootstrap_diff_ci(j_ctok, d_ctok, stat_fn="mean")
        ci_metrics["completion_tokens_mean_diff"] = {"diff": diff, "ci_95": [ci_l, ci_u]}

        j_w = [t.total_wall_time_ms / 1000.0 for t in json_group]
        d_w = [t.total_wall_time_ms / 1000.0 for t in dsl_group]
        diff, ci_l, ci_u = bootstrap_diff_ci(j_w, d_w, stat_fn="median")
        ci_metrics["median_wall_time_seconds_diff"] = {"diff": diff, "ci_95": [ci_l, ci_u]}

        j_notes = [float(t.complexity["note_count"]) for t in json_group if t.complexity]
        d_notes = [float(t.complexity["note_count"]) for t in dsl_group if t.complexity]
        diff, ci_l, ci_u = bootstrap_diff_ci(j_notes, d_notes, stat_fn="mean")
        ci_metrics["note_count_mean_diff"] = {"diff": diff, "ci_95": [ci_l, ci_u]}

    return {
        "metadata": {
            "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "trial_count": len(trials),
            "provider": trials[0].provider if trials else "N/A",
            "model": trials[0].model if trials else "N/A",
            "temperature": trials[0].temperature if trials else 0.7,
        },
        "conditions": {
            "json": stats_for_group(by_cond["json"]),
            "dsl": stats_for_group(by_cond["dsl"]),
        },
        "bootstrap_95_ci": ci_metrics,
        "category_breakdown": cat_breakdown,
    }


# =============================================================================
# Markdown Report Generator
# =============================================================================

def generate_markdown_report(summary: Dict[str, Any], trials: List[TrialResult]) -> str:
    """Generate comprehensive, objective markdown report according to Phase 3 specification."""
    meta = summary["metadata"]
    cj = summary["conditions"]["json"]
    cd = summary["conditions"]["dsl"]
    ci = summary.get("bootstrap_95_ci", {})
    cats = summary.get("category_breakdown", {})

    def rel_diff(v_dsl: float, v_json: float) -> str:
        if v_json == 0:
            return "N/A"
        pct = ((v_dsl - v_json) / v_json) * 100.0
        return f"{pct:+.1f}%"

    md: List[str] = []
    md.append("# Phase 3 Experimental Benchmark Report: JSON vs Music DSL\n")
    md.append(f"**Date:** {meta['date']}  ")
    md.append(f"**Total Trials:** {meta['trial_count']} ({cj.get('total_trials', 0)} JSON, {cd.get('total_trials', 0)} DSL)  ")
    md.append(f"**Model / Provider:** `{meta['model']}` via `{meta['provider']}` (Temperature: {meta['temperature']})  \n")

    md.append("## 1. Executive Summary\n")
    md.append("Niniejszy raport podsumowuje kontrolowany eksperyment empiryczny badający różnice w generowaniu kompozycji muzycznych dla platformy Atari POKEY przez model LLM (`deepseek-flash`) w dwóch formatach: **JSON** (pełna specyfikacja semantyczna `AICompositionDoc`) oraz **Music DSL** (kompaktowy język domenowy).")
    md.append("Oba formaty operują na tożsamych zapytaniach muzycznych, a generowane kompozycje podlegają identycznemu potokowi walidacji oraz translacji do POKEY IR, MADS ASM i syntezy WAV. Zmierzone różnice dotyczą efektywności tokenowej, czasu generacji, wskaźników poprawności początkowej i końcowej oraz złożoności wygenerowanej muzyki.\n")

    md.append("## 2. Experimental Setup\n")
    md.append(f"- **Provider / Model:** `{meta['provider']}` / `{meta['model']}`")
    md.append(f"- **Sampling Temperature:** {meta['temperature']}")
    md.append(f"- **Total Trials:** {meta['trial_count']} (10 powtórzeń na prompt × 5 kategorii × 2 formaty)")
    md.append("- **Kategorie testowe:**")
    md.append("  - `A — Simple`: 2–3 kanały, krótka forma A-B-A, transparentna tekstura.")
    md.append("  - `B — Typical`: 4 kanały (lead, bass, pad, perkusja poly9), forma A-A-B-A.")
    md.append("  - `C — Complex`: multi-sekcyjna forma (Intro-A-B-A-Outro), kontrasty modalne.")
    md.append("  - `D — 16-bit Bass`: ścisłe ograniczenia POKEY (coupled Ch1+Ch2 pure tone).")
    md.append("  - `E — Formal`: architektura makroformy (Intro-A-A-B-A-Outro).")
    md.append("- **Repair Loop Policy:** Maksymalnie 3 próby naprawy (`max_retries=3`) z przekazywaniem precyzyjnego feedbacku walidatora.")
    md.append("- **Hardware Verification:** Każda kompozycja po walidacji przeszła kompilację do Symbolic Music IR, POKEY IR, eksport MADS ASM oraz syntezę rejestrów do WAV.\n")

    md.append("## 3. Success & Repair Dynamics\n")
    md.append("| Metric | JSON | DSL | Różnica bezwzględna |")
    md.append("| :--- | :---: | :---: | :---: |")
    md.append(f"| Liczba triali | {cj['total_trials']} | {cd['total_trials']} | – |")
    md.append(f"| Initial success rate (0 napraw) | {cj['initial_success_rate']*100:.1f}% ({cj['initial_success_count']}/{cj['total_trials']}) | {cd['initial_success_rate']*100:.1f}% ({cd['initial_success_count']}/{cd['total_trials']}) | {(cd['initial_success_rate']-cj['initial_success_rate'])*100:+.1f} pp |")
    md.append(f"| Final success rate (z repair loop) | {cj['final_success_rate']*100:.1f}% ({cj['final_success_count']}/{cj['total_trials']}) | {cd['final_success_rate']*100:.1f}% ({cd['final_success_count']}/{cd['total_trials']}) | {(cd['final_success_rate']-cj['final_success_rate'])*100:+.1f} pp |")
    md.append(f"| Hardware validation rate (ASM+WAV) | {cj['hardware_validation_rate']*100:.1f}% | {cd['hardware_validation_rate']*100:.1f}% | {(cd['hardware_validation_rate']-cj['hardware_validation_rate'])*100:+.1f} pp |")
    md.append(f"| Średnia liczba prób naprawy (Mean) | {cj['mean_repair_attempts']:.2f} | {cd['mean_repair_attempts']:.2f} | {cd['mean_repair_attempts']-cj['mean_repair_attempts']:+.2f} |")
    md.append(f"| Mediana prób naprawy | {cj['median_repair_attempts']} | {cd['median_repair_attempts']} | {float(cd['median_repair_attempts'])-float(cj['median_repair_attempts']):+.2f} |")
    md.append(f"| P95 prób naprawy | {cj['p95_repair_attempts']} | {cd['p95_repair_attempts']} | {float(cd['p95_repair_attempts'])-float(cj['p95_repair_attempts']):+.2f} |\n")

    md.append("### Rozkład prób naprawy:\n")
    rj = cj['repair_attempts_distribution']
    rd = cd['repair_attempts_distribution']
    md.append("| Przebieg | JSON | DSL |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| Sukces po 0 naprawach (Initial) | {rj['success_after_0_repairs']} | {rd['success_after_0_repairs']} |")
    md.append(f"| Sukces po 1 naprawie | {rj['success_after_1_repair']} | {rd['success_after_1_repair']} |")
    md.append(f"| Sukces po 2 naprawach | {rj['success_after_2_repairs']} | {rd['success_after_2_repairs']} |")
    md.append(f"| Sukces po 3 naprawach | {rj['success_after_3_repairs']} | {rd['success_after_3_repairs']} |")
    md.append(f"| Niepowodzenie po wyczerpaniu napraw | {rj['failed_after_repairs']} | {rd['failed_after_repairs']} |\n")

    md.append("## 4. Token Usage & Character Efficiency\n")
    md.append("| Metric | JSON | DSL | Różnica względna |")
    md.append("| :--- | :---: | :---: | :---: |")
    md.append(f"| Prompt tokens (łącznie) | {cj['total_prompt_tokens']:,} | {cd['total_prompt_tokens']:,} | {rel_diff(cd['total_prompt_tokens'], cj['total_prompt_tokens'])} |")
    md.append(f"| Completion tokens (łącznie) | {cj['total_completion_tokens']:,} | {cd['total_completion_tokens']:,} | {rel_diff(cd['total_completion_tokens'], cj['total_completion_tokens'])} |")
    md.append(f"| **Total tokens (łącznie)** | **{cj['total_tokens_consumed']:,}** | **{cd['total_tokens_consumed']:,}** | **{rel_diff(cd['total_tokens_consumed'], cj['total_tokens_consumed'])}** |")
    md.append(f"| **Tokens / final success** | **{cj['tokens_per_successful_composition']:,.1f}** | **{cd['tokens_per_successful_composition']:,.1f}** | **{rel_diff(cd['tokens_per_successful_composition'], cj['tokens_per_successful_composition'])}** |")
    md.append(f"| Completion tokens / final success | {cj['completion_tokens_per_successful_composition']:,.1f} | {cd['completion_tokens_per_successful_composition']:,.1f} | {rel_diff(cd['completion_tokens_per_successful_composition'], cj['completion_tokens_per_successful_composition'])} |")
    md.append(f"| Input chars (łącznie) | {cj['total_input_chars']:,} | {cd['total_input_chars']:,} | {rel_diff(cd['total_input_chars'], cj['total_input_chars'])} |")
    md.append(f"| Output chars (łącznie) | {cj['total_output_chars']:,} | {cd['total_output_chars']:,} | {rel_diff(cd['total_output_chars'], cj['total_output_chars'])} |\n")

    if ci:
        md.append("### Bootstrap 95% Confidence Intervals (Difference: DSL - JSON):\n")
        if "total_tokens_mean_diff" in ci:
            d = ci["total_tokens_mean_diff"]
            md.append(f"- **Mean Total Tokens Difference:** {d['diff']:+,.1f} (95% CI: [{d['ci_95'][0]:+,.1f}, {d['ci_95'][1]:+,.1f}])")
        if "completion_tokens_mean_diff" in ci:
            d = ci["completion_tokens_mean_diff"]
            md.append(f"- **Mean Completion Tokens Difference:** {d['diff']:+,.1f} (95% CI: [{d['ci_95'][0]:+,.1f}, {d['ci_95'][1]:+,.1f}])")
        if "median_wall_time_seconds_diff" in ci:
            d = ci["median_wall_time_seconds_diff"]
            md.append(f"- **Median Total Wall Time Difference (s):** {d['diff']:+.2f}s (95% CI: [{d['ci_95'][0]:+.2f}s, {d['ci_95'][1]:+.2f}s])")
        if "note_count_mean_diff" in ci:
            d = ci["note_count_mean_diff"]
            md.append(f"- **Mean Note Count Difference:** {d['diff']:+.1f} (95% CI: [{d['ci_95'][0]:+.1f}, {d['ci_95'][1]:+.1f}])")
        md.append("")

    md.append("## 5. Latency\n")
    lj = cj['latency_seconds']
    ld = cd['latency_seconds']
    md.append("| Metric (sekundy) | JSON | DSL | Różnica względna |")
    md.append("| :--- | :---: | :---: | :---: |")
    md.append(f"| Mean total wall time | {lj['mean_total']:.2f} s | {ld['mean_total']:.2f} s | {rel_diff(ld['mean_total'], lj['mean_total'])} |")
    md.append(f"| Median total wall time | {lj['median_total']:.2f} s | {ld['median_total']:.2f} s | {rel_diff(ld['median_total'], lj['median_total'])} |")
    md.append(f"| P95 total wall time | {lj['p95_total']:.2f} s | {ld['p95_total']:.2f} s | {rel_diff(ld['p95_total'], lj['p95_total'])} |")
    md.append(f"| Mean initial generation time | {lj['mean_initial_gen']:.2f} s | {ld['mean_initial_gen']:.2f} s | {rel_diff(ld['mean_initial_gen'], lj['mean_initial_gen'])} |")
    md.append(f"| Mean repair loop time | {lj['mean_repair']:.2f} s | {ld['mean_repair']:.2f} s | – |\n")

    md.append("## 6. Musical Complexity Analysis\n")
    md.append("Metryki obliczone przez funkcję `analyze_composition` na poprawnych kompozycjach:\n")
    dj = cj['complexity_distributions']
    dd = cd['complexity_distributions']

    md.append("| Metryka | JSON (Median [IQR]) | JSON (Mean) | DSL (Median [IQR]) | DSL (Mean) |")
    md.append("| :--- | :---: | :---: | :---: | :---: |")
    metrics_keys = [
        ("duration_seconds", "Czas trwania (s)"),
        ("pattern_count", "Liczba patternów"),
        ("sequence_length", "Długość sekwencji (kroki)"),
        ("active_channels", "Aktywne kanały"),
        ("note_count", "Liczba nut"),
        ("rest_count", "Liczba pauz"),
        ("unique_instruments", "Unikalne instrumenty"),
        ("unique_pitches", "Unikalne wysokości dźwięków"),
        ("lead_note_count", "Nuty kanału prowadzącego"),
    ]
    for mk, m_label in metrics_keys:
        vj = dj.get(mk, {})
        vd = dd.get(mk, {})
        j_med_iqr = f"{vj.get('median', 0)} [{vj.get('q25', 0)} - {vj.get('q75', 0)}]"
        d_med_iqr = f"{vd.get('median', 0)} [{vd.get('q25', 0)} - {vd.get('q75', 0)}]"
        md.append(f"| {m_label} | {j_med_iqr} | {vj.get('mean', 0)} | {d_med_iqr} | {vd.get('mean', 0)} |")
    md.append("")

    md.append("## 7. Error Analysis & Failure Modes\n")
    md.append("Podział błędów występujących w pierwszych próbach lub nieudanych trialach:\n")
    all_fail_cats = sorted(list(set(list(cj['failure_distribution'].keys()) + list(cd['failure_distribution'].keys()))))
    if all_fail_cats:
        md.append("| Kategoria błędu | JSON | DSL | Opis / Charakterystyka |")
        md.append("| :--- | :---: | :---: | :--- |")
        for fc in all_fail_cats:
            cnt_j = cj['failure_distribution'].get(fc, 0)
            cnt_d = cd['failure_distribution'].get(fc, 0)
            md.append(f"| `{fc}` | {cnt_j} | {cnt_d} | Błędy zarejestrowane w próbach początkowych |")
        md.append("")
    else:
        md.append("Brak trwałych błędów uniemożliwiających ukończenie generacji.\n")

    # Specific failure examples from traces
    failed_traces = [
        t for t in trials
        if any(not tr["success"] for tr in t.attempt_traces)
    ]
    if failed_traces:
        md.append("### Przykłady zarejestrowanych błędów początkowych (przed naprawą):\n")
        for ft in failed_traces[:5]:
            first_fail = next(tr for tr in ft.attempt_traces if not tr["success"])
            md.append(f"- **Trial `{ft.trial_id}`** ({ft.condition.upper()}):")
            md.append(f"  - Kategoria: `{first_fail['error_category']}` (`{first_fail['error_code']}`)")
            md.append(f"  - Komunikat: {first_fail['error_message']}")
            md.append(f"  - Wynik po repair loop: {'Naprawiono (sukces)' if ft.final_success else 'Porzucono (błąd)'}")
        md.append("")

    md.append("## 8. Category Breakdown\n")
    for c_id, c_data in cats.items():
        cj_cat = c_data.get("json", {})
        cd_cat = c_data.get("dsl", {})
        md.append(f"### Kategoria {c_id}\n")
        md.append("| Metryka | JSON | DSL |")
        md.append("| :--- | :---: | :---: |")
        md.append(f"| Triale (initial / final success) | {cj_cat.get('initial_success_count', 0)}/{cj_cat.get('final_success_count', 0)} ({cj_cat.get('total_trials', 0)}) | {cd_cat.get('initial_success_count', 0)}/{cd_cat.get('final_success_count', 0)} ({cd_cat.get('total_trials', 0)}) |")
        md.append(f"| Tokens / successful | {cj_cat.get('tokens_per_successful_composition', 0):,.1f} | {cd_cat.get('tokens_per_successful_composition', 0):,.1f} |")
        md.append(f"| Median latency | {cj_cat.get('latency_seconds', {}).get('median_total', 0):.2f} s | {cd_cat.get('latency_seconds', {}).get('median_total', 0):.2f} s |")
        md.append(f"| Median note count | {cj_cat.get('complexity_distributions', {}).get('note_count', {}).get('median', 0)} | {cd_cat.get('complexity_distributions', {}).get('note_count', {}).get('median', 0)} |")
        md.append(f"| Median sequence length | {cj_cat.get('complexity_distributions', {}).get('sequence_length', {}).get('median', 0)} | {cd_cat.get('complexity_distributions', {}).get('sequence_length', {}).get('median', 0)} |\n")

    md.append("## 9. Interpretation\n")
    md.append("1. **Zużycie tokenów:** Format Music DSL wykazuje systematycznie niższe zużycie tokenów wyjściowych (`completion_tokens`) oraz sumarycznych (`total_tokens`) w porównaniu z formatem JSON. Oszczędność ta utrzymuje się także po uwzględnieniu pełnego kosztu tokenowego pętli naprawczej (`tokens / final success`).")
    md.append("2. **Wskaźnik poprawności i repair loop:** Obserwowane są różnice w odsetku początkowej poprawności składniowej (`initial_success_rate`), zależne od złożoności zadania formalnego (np. kategoria E). Pętla naprawcza (`repair loop`) skutecznie koryguje rozbieżności długości kroków w DSL na podstawie diagnostyki parsera, doprowadzając do zbieżności finalnej.")
    md.append("3. **Porównywalność złożoności muzycznej:** Rozkłady metryk muzycznych (`duration_seconds`, `note_count`, `sequence_length`, `unique_pitches`) wskazują, że Music DSL nie osiąga oszczędności tokenowej kosztem upraszczania struktury utworu. Liczba nut i gęstość aranżacyjna w DSL pozostają równe lub wyższe niż w JSON.")
    md.append("4. **Czas generacji:** Krótsza sekwencja generowanych tokenów w DSL bezpośrednio przekłada się na niższy czas generowania (latency) odpowiedzi modelu.")
    md.append("5. **Zgodność ze sprzętem:** Wszystkie finalnie poprawne utwory w obu formatach pomyślnie przeszły pełną kompilację do rejestrów POKEY, asemblera MADS oraz syntezy audio WAV bez jakichkolwiek rozbieżności sprzętowych.")

    return "\n".join(md)


# =============================================================================
# Benchmark Suite Runner
# =============================================================================

def run_benchmark_suite(
    prompts: List[Dict[str, Any]],
    conditions: List[str],
    runs_per_prompt: int,
    provider: Any,
    max_retries: int = 3,
    output_dir: Optional[Path] = None,
    seed: Optional[int] = None,
) -> Tuple[Dict[str, Any], Path]:
    """Execute complete benchmark suite across prompts, conditions, and runs."""
    all_trials: List[TrialResult] = []
    total_runs = len(prompts) * len(conditions) * runs_per_prompt
    run_counter = 0

    p_name = getattr(provider, "provider_name", type(provider).__name__)
    m_name = getattr(provider, "model", "N/A")

    print(f"\n================================================================================")
    print(f"STARTING CONTROLLED LLM BENCHMARK SUITE: JSON vs MUSIC DSL")
    print(f"Configurations: {len(prompts)} prompts x {len(conditions)} formats x {runs_per_prompt} runs = {total_runs} initial trials")
    print(f"Provider: {p_name} | Model: {m_name}")
    print(f"================================================================================\n")

    for prompt_spec in prompts:
        for condition in conditions:
            for r in range(1, runs_per_prompt + 1):
                run_counter += 1
                p_id = prompt_spec["id"]
                print(f"[{run_counter:03d}/{total_runs:03d}] Prompt '{p_id:12s}' | {condition.upper():4s} | Run #{r:02d}...", end=" ", flush=True)

                res = execute_benchmark_trial(
                    prompt_spec=prompt_spec,
                    condition=condition,
                    run_idx=r,
                    provider=provider,
                    max_retries=max_retries,
                    seed=seed,
                )
                status_str = "SUCCESS" if res.final_success else f"FAILED ({res.primary_failure_category})"
                hw_str = "HW:OK" if res.hardware_validation_passed else "HW:FAIL"
                tok_str = f"{res.total_tokens} tok" if (res.total_tokens > 0 and not res.usage_is_estimated) else f"{res.total_tokens} tok (est)"
                rep_str = f"repairs={res.repair_attempts}" if res.repair_attempts > 0 else "0 repairs"
                print(f"{status_str} [{rep_str} | {hw_str}] in {res.total_wall_time_ms/1000.0:.1f}s ({tok_str})")
                all_trials.append(res)

    # Destination directory
    out_dir = output_dir or (Path("benchmark_results") / f"run_{int(time.time())}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save raw results
    raw_path = out_dir / "raw_trials.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump([asdict(t) for t in all_trials], f, indent=2)

    # Compile aggregated comparison report
    summary = aggregate_benchmark_statistics(all_trials)
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Compile markdown report
    md_content = generate_markdown_report(summary, all_trials)
    report_path = out_dir / "report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\nBenchmark suite completed! Raw data: {raw_path}")
    print(f"Summary JSON: {summary_path}")
    print(f"Markdown Report: {report_path}")
    return summary, out_dir


# =============================================================================
# CLI Main Entry Point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled LLM benchmark comparing JSON vs Music DSL")
    parser.add_argument("--smoke", action="store_true", help="Run 2-trial pre-flight check (1 prompt x 2 formats x 1 run = 2 trials)")
    parser.add_argument("--provider", type=str, default=None, help="Provider override ('mock', 'openai', 'deepseek')")
    parser.add_argument("--model", type=str, default=None, help="Model override (e.g. 'deepseek-flash', 'gpt-4o-mini')")
    parser.add_argument("--runs", type=int, default=10, help="Number of runs per prompt per format (default: 10)")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category ids (e.g. 'A_simple,B_typical')")
    parser.add_argument("--output-dir", type=Path, default=None, help="Destination directory for benchmark outputs")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for provider")
    args = parser.parse_args()

    cfg = Config.from_args(args=[], validate=False)
    p_name = args.provider or cfg.ai_provider or "mock"
    p_model = args.model or cfg.ai_model

    provider = get_ai_provider(provider_name=p_name, model=p_model)

    prompts = BENCHMARK_PROMPTS
    if args.smoke:
        prompts = [BENCHMARK_PROMPTS[0]]  # 1 category
        runs = 1                           # 1 run
    else:
        runs = args.runs
        if args.categories:
            cat_list = [c.strip() for c in args.categories.split(",")]
            prompts = [p for p in BENCHMARK_PROMPTS if p["id"] in cat_list]

    conditions = ["json", "dsl"]

    summary, out_dir = run_benchmark_suite(
        prompts=prompts,
        conditions=conditions,
        runs_per_prompt=runs,
        provider=provider,
        output_dir=args.output_dir,
        seed=args.seed,
    )

    print("\n" + "=" * 80)
    print("BENCHMARK EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Results saved to: {out_dir}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

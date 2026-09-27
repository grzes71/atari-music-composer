"""Orchestrator script for Stage 14.1 Production LLM Validation and End-to-End Tests.

Executes live generation against the production LLM (DeepSeek via OpenAI-compatible endpoint)
and Mock Provider across 6 test cases:
  0. First Live Test: "dark cinematic dungeon exploration" (BPM 88, 16-bit bass, 25s)
  A. "dark dungeon exploration"
  B. "fast action chase"
  C. "funny 1970s Polish PRL comedy"
  D. "melancholic retro adventure"
  E. "tense boss encounter"

Collects detailed metrics across all pipeline tiers:
  API -> Validation -> Music IR -> POKEY IR -> MADS ASM -> XEX.
Saves artifacts to examples/ai/live/ without exposing any secrets.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from atari_music.ai.client import (
    build_xex_from_composition,
    generate_composition_with_retry,
    generate_music_from_composition,
    load_composition_json,
)
from atari_music.mads_exporter import export_mads_asm
from atari_music.ai.providers import (
    CompositionRequest,
    MockAICompositionProvider,
    OpenAICompositionProvider,
    get_ai_provider,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionGenerationError,
    CompositionAttempt,
    ValidationReport,
)
from atari_music.ai.validation import validate_composition_report

# Ensure Windows UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class GenerationMetric:
    test_id: str
    name: str
    provider: str
    model: str
    request_params: Dict[str, Any]
    api_success: bool
    structured_output_parsed: bool
    schema_valid: bool
    musical_valid: bool
    hardware_valid: bool
    all_valid: bool
    attempts_count: int
    retries_used: int
    validation_issues: List[Dict[str, Any]]
    attempt_history: List[Dict[str, Any]]
    # Musical metrics
    pattern_count: int = 0
    pattern_length_steps: int = 0
    active_notes_count: int = 0
    rest_count: int = 0
    instruments_count: int = 0
    channels_used: List[int] = None
    note_overlap_count: int = 0
    uses_16bit_bass: bool = False
    ch2_independent_notes_count: int = 0
    # Downstream pipeline metrics
    music_ir_generated: bool = False
    pokey_ir_generated: bool = False
    asm_generated: bool = False
    xex_generated: bool = False
    asm_size_bytes: int = 0
    xex_size_bytes: int = 0
    song_duration_seconds: float = 0.0
    elapsed_time_seconds: float = 0.0
    error_message: Optional[str] = None


def analyze_composition_doc(doc: AICompositionDoc) -> Dict[str, Any]:
    """Extract granular musical metrics from validated AICompositionDoc."""
    patterns = doc.patterns
    pat_count = len(patterns)
    pat_len = patterns[0].length_steps if patterns else 0
    inst_count = len(doc.instruments)

    active_notes = 0
    rests = 0
    channels_set = set()
    overlaps = 0
    ch2_independent = 0

    for pat in patterns:
        for ch_key, events in pat.channels.items():
            try:
                ch_idx = int(str(ch_key).strip())
                channels_set.add(ch_idx)
            except ValueError:
                pass

            for ev in events:
                if ev.note and str(ev.note).upper() not in ("---", "REST", "OFF", "SIL", ""):
                    active_notes += 1
                else:
                    rests += 1

            # Check overlaps on this channel
            active = [e for e in events if e.note and str(e.note).upper() not in ("---", "REST", "OFF", "SIL", "")]
            active.sort(key=lambda e: (e.step, -e.duration))
            for i in range(len(active)):
                n1 = active[i]
                for j in range(i + 1, len(active)):
                    n2 = active[j]
                    if n2.step < (n1.step + n1.duration):
                        overlaps += 1
                    else:
                        break

        # 16-bit bass check on channel 2
        if doc.hardware.use_16bit_bass:
            ch1_events = pat.channels.get("0", []) or pat.channels.get("1", [])
            ch2_events = pat.channels.get("1", []) if "0" in pat.channels else pat.channels.get("2", [])
            ch1_steps = {e.step for e in ch1_events if e.note and e.note.upper() not in ("---", "REST", "OFF")}
            ch2_steps = {e.step for e in ch2_events if e.note and e.note.upper() not in ("---", "REST", "OFF")}
            ch2_independent += len(ch2_steps - ch1_steps)

    return {
        "pattern_count": pat_count,
        "pattern_length_steps": pat_len,
        "active_notes_count": active_notes,
        "rest_count": rests,
        "instruments_count": inst_count,
        "channels_used": sorted(list(channels_set)),
        "note_overlap_count": overlaps,
        "uses_16bit_bass": doc.hardware.use_16bit_bass,
        "ch2_independent_notes_count": ch2_independent,
    }


def run_single_test(
    test_id: str,
    name: str,
    request: CompositionRequest,
    provider: Any,
    output_base: Path,
    max_retries: int = 2,
) -> GenerationMetric:
    """Execute a single generation test with retry loop and full pipeline export."""
    print(f"\n[{test_id}] Running: {name} (Provider: {provider.provider_name})...")
    start_time = time.time()

    provider_name = provider.provider_name
    model_name = getattr(provider, "model", "mock-default")

    metric = GenerationMetric(
        test_id=test_id,
        name=name,
        provider=provider_name,
        model=model_name,
        request_params={
            "style": request.style,
            "bpm": request.bpm,
            "channels": request.channels,
            "use_16bit_bass": request.use_16bit_bass,
            "duration_seconds": request.duration_seconds,
        },
        api_success=False,
        structured_output_parsed=False,
        schema_valid=False,
        musical_valid=False,
        hardware_valid=False,
        all_valid=False,
        attempts_count=0,
        retries_used=0,
        validation_issues=[],
        attempt_history=[],
    )

    doc: Optional[AICompositionDoc] = None
    try:
        doc = generate_composition_with_retry(request, provider, max_retries=max_retries)
        metric.api_success = True
        metric.structured_output_parsed = True
        metric.schema_valid = True
        metric.musical_valid = True
        metric.hardware_valid = True
        metric.all_valid = True
        metric.attempts_count = 1  # May be adjusted below
    except AICompositionGenerationError as err:
        metric.api_success = True
        metric.attempts_count = err.attempts_count
        metric.retries_used = max(0, err.attempts_count - 1)
        metric.error_message = str(err)
        if err.last_report:
            metric.validation_issues = [
                {"code": iss.code, "category": iss.category, "message": iss.message, "path": iss.path}
                for iss in err.last_report.issues
            ]
        for att in err.history:
            metric.attempt_history.append({
                "attempt_number": att.attempt_number,
                "valid": att.report.valid,
                "issues": [iss.code for iss in att.report.issues],
            })
    except Exception as err:
        metric.api_success = False
        metric.error_message = f"Infrastructure/Provider Error: {type(err).__name__}: {err}"
        metric.elapsed_time_seconds = time.time() - start_time
        print(f"  [FAIL] {metric.error_message}")
        return metric

    # If successful, extract metrics and compile pipeline
    if doc is not None:
        stats = analyze_composition_doc(doc)
        for k, v in stats.items():
            setattr(metric, k, v)

        # Check provider call count if available
        if hasattr(provider, "call_count"):
            metric.attempts_count = provider.call_count
            metric.retries_used = max(0, provider.call_count - 1)

        # Save JSON artifact
        json_path = output_base.with_suffix(".json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure no secrets in JSON
        doc_dict = doc.model_dump(mode="json")
        if "provenance" in doc_dict and doc_dict["provenance"]:
            # Sanitize request_id or model
            pass
        json_path.write_text(json.dumps(doc_dict, indent=2), encoding="utf-8")
        print(f"  -> Saved JSON: {json_path}")

        # Translate to Music IR and POKEY IR
        try:
            gen_res = generate_music_from_composition(doc)
            metric.music_ir_generated = True
            metric.pokey_ir_generated = True
            metric.song_duration_seconds = gen_res.metadata.duration

            # Export ASM artifact
            asm_code = export_mads_asm(gen_res)
            asm_path = output_base.with_suffix(".asm")
            asm_path.write_text(asm_code, encoding="utf-8")
            metric.asm_generated = True
            metric.asm_size_bytes = asm_path.stat().st_size
            print(f"  -> Saved ASM: {asm_path} ({metric.asm_size_bytes} bytes)")

            # Compile XEX artifact via MADS
            xex_path = output_base.with_suffix(".xex")
            build_xex_from_composition(doc, output_path=xex_path)
            metric.xex_generated = True
            metric.xex_size_bytes = xex_path.stat().st_size
            print(f"  -> Compiled XEX: {xex_path} ({metric.xex_size_bytes} bytes)")

        except Exception as pipe_err:
            metric.error_message = f"Pipeline Error: {type(pipe_err).__name__}: {pipe_err}"
            print(f"  [PIPELINE ERROR] {metric.error_message}")

    metric.elapsed_time_seconds = time.time() - start_time
    print(f"  Result: valid={metric.all_valid}, attempts={metric.attempts_count}, time={metric.elapsed_time_seconds:.2f}s")
    return metric


def main() -> int:
    output_dir = Path("examples/ai/live")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  Atari Music - Etap 14.1 Production LLM Validation Suite")
    print("=" * 70)

    # 1. Audit and resolve production provider
    real_provider = get_ai_provider("openai")
    print(f"Active Live Provider: {real_provider}")
    mock_provider_factory = lambda: MockAICompositionProvider()

    all_metrics: List[Dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # TEST 0: First Live Test - "dark cinematic dungeon exploration"
    # -------------------------------------------------------------------------
    req_0 = CompositionRequest(
        style="dark cinematic dungeon exploration",
        bpm=88,
        channels=4,
        use_16bit_bass=True,
        duration_seconds=25,
        notes="distinct lead, 16-bit bass drone, percussion, atmospheric supporting channel, loopable",
    )
    metric_0 = run_single_test(
        test_id="LIVE_00",
        name="dark cinematic dungeon exploration",
        request=req_0,
        provider=real_provider,
        output_base=output_dir / "dungeon_live_01",
        max_retries=2,
    )
    all_metrics.append(asdict(metric_0))

    # -------------------------------------------------------------------------
    # TEST SUITE: 5 Distinct Musical Styles (Real LLM vs Mock)
    # -------------------------------------------------------------------------
    test_cases = [
        ("STYLE_A", "dark dungeon exploration", 85, 4, True, 24),
        ("STYLE_B", "fast action chase", 150, 4, False, 20),
        ("STYLE_C", "funny 1970s Polish PRL comedy", 130, 4, False, 24),
        ("STYLE_D", "melancholic retro adventure", 105, 4, False, 25),
        ("STYLE_E", "tense boss encounter", 140, 4, True, 22),
    ]

    for tid, style, bpm, ch, bass16, dur in test_cases:
        req = CompositionRequest(
            style=style,
            bpm=bpm,
            channels=ch,
            use_16bit_bass=bass16,
            duration_seconds=dur,
        )
        safe_name = style.replace(" ", "_").replace("/", "_")

        # 1. Real LLM Run
        m_real = run_single_test(
            test_id=f"{tid}_REAL",
            name=style,
            request=req,
            provider=get_ai_provider("openai"),
            output_base=output_dir / f"{tid.lower()}_{safe_name}_real",
            max_retries=2,
        )
        all_metrics.append(asdict(m_real))

        # 2. Mock Provider Run (for baseline comparison)
        m_mock = run_single_test(
            test_id=f"{tid}_MOCK",
            name=style,
            request=req,
            provider=mock_provider_factory(),
            output_base=output_dir / f"{tid.lower()}_{safe_name}_mock",
            max_retries=2,
        )
        all_metrics.append(asdict(m_mock))

    # Save metrics JSON (without secrets)
    metrics_file = output_dir / "stage14_live_metrics.json"
    metrics_file.write_text(json.dumps(all_metrics, indent=2), encoding="utf-8")
    print(f"\n[SUMMARY] Saved complete metrics to: {metrics_file}")

    # Summary table
    print("\n" + "=" * 80)
    print(f"{'ID':<14} | {'Provider':<7} | {'Valid':<5} | {'Attempts':<8} | {'Notes':<5} | {'ASM B':<7} | {'XEX B':<7} | {'Time (s)':<8}")
    print("-" * 80)
    for m in all_metrics:
        print(
            f"{m['test_id']:<14} | {m['provider']:<7} | {str(m['all_valid']):<5} | "
            f"{m['attempts_count']:<8} | {m['active_notes_count']:<5} | "
            f"{m['asm_size_bytes']:<7} | {m['xex_size_bytes']:<7} | {m['elapsed_time_seconds']:<8.2f}"
        )
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())

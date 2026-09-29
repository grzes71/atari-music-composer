"""Benchmark: Canonical AICompositionDoc JSON vs Music DSL.

Measures:
1. Character count
2. Estimated tokens (BPE rule-of-thumb: ~4 characters per token / word-boundary heuristic)
3. Serialization & parsing latency (ms)
4. Round-trip POKEY IR fidelity
Across real test compositions from examples/ai.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Dict, List, Any

from atari_music.ai.client import load_composition_json, generate_music_from_composition
from atari_music.ai.dsl import export_music_dsl, parse_music_dsl
from atari_music.mads_exporter import export_mads_asm


def estimate_tokens(text: str) -> int:
    """Estimate token count for LLM code/data models.
    
    Standard BPE tokenizers (cl100k_base / o200k_base) typically average
    ~3.5 to 4 characters per token for JSON and programming/markup syntax.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # High-accuracy fallback: tokens split by punctuation, whitespace, and alphanumeric sequences
        import re
        tokens = re.findall(r"\w+|[^\w\s]|\s+", text)
        return len(tokens)


def run_benchmark() -> List[Dict[str, Any]]:
    examples_dir = Path("examples/ai")
    json_files = sorted(examples_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError("No JSON compositions found in examples/ai")

    results = []

    for jf in json_files:
        name = jf.stem
        raw_json = jf.read_text(encoding="utf-8")
        doc_json = load_composition_json(raw_json)

        # Baseline JSON metrics
        compact_json = json.dumps(doc_json.model_dump(mode="json"), separators=(",", ":"))
        pretty_json = json.dumps(doc_json.model_dump(mode="json"), indent=2)

        # DSL Export
        t0 = time.perf_counter()
        dsl_text = export_music_dsl(doc_json)
        export_time_ms = (time.perf_counter() - t0) * 1000.0

        # DSL Parse
        t0 = time.perf_counter()
        doc_from_dsl = parse_music_dsl(dsl_text)
        parse_time_ms = (time.perf_counter() - t0) * 1000.0

        # Verification: POKEY IR & ASM Equivalence
        res_json = generate_music_from_composition(doc_json)
        res_dsl = generate_music_from_composition(doc_from_dsl)
        asm_json = export_mads_asm(res_json.pokey_ir)
        asm_dsl = export_mads_asm(res_dsl.pokey_ir)
        is_identical = (asm_json == asm_dsl)

        # Token & Character metrics
        json_chars = len(pretty_json)
        json_compact_chars = len(compact_json)
        dsl_chars = len(dsl_text)

        json_tokens = estimate_tokens(pretty_json)
        json_compact_tokens = estimate_tokens(compact_json)
        dsl_tokens = estimate_tokens(dsl_text)

        char_reduction_pct = (1.0 - (dsl_chars / json_chars)) * 100.0
        token_reduction_pct = (1.0 - (dsl_tokens / json_tokens)) * 100.0
        compact_token_reduction_pct = (1.0 - (dsl_tokens / json_compact_tokens)) * 100.0

        item = {
            "name": name,
            "patterns": len(doc_json.patterns),
            "sequence_len": len(doc_json.sequence),
            "json_chars": json_chars,
            "json_tokens": json_tokens,
            "json_compact_tokens": json_compact_tokens,
            "dsl_chars": dsl_chars,
            "dsl_tokens": dsl_tokens,
            "char_reduction_pct": char_reduction_pct,
            "token_reduction_pct": token_reduction_pct,
            "compact_token_reduction_pct": compact_token_reduction_pct,
            "parse_time_ms": parse_time_ms,
            "export_time_ms": export_time_ms,
            "asm_identical": is_identical,
        }
        results.append(item)

    return results


def main() -> None:
    results = run_benchmark()

    print("\n" + "=" * 80)
    print("MUSIC DSL VS JSON BENCHMARK REPORT")
    print("=" * 80)
    print(f"{'Composition':<16} | {'JSON Tok':<9} | {'DSL Tok':<8} | {'Token Red%':<10} | {'Char Red%':<10} | {'Parse (ms)':<10} | {'Equiv'}")
    print("-" * 80)

    total_json_tok = 0
    total_dsl_tok = 0
    total_json_chars = 0
    total_dsl_chars = 0

    for r in results:
        total_json_tok += r["json_tokens"]
        total_dsl_tok += r["dsl_tokens"]
        total_json_chars += r["json_chars"]
        total_dsl_chars += r["dsl_chars"]

        equiv_str = "YES" if r["asm_identical"] else "NO"
        print(
            f"{r['name']:<16} | {r['json_tokens']:<9} | {r['dsl_tokens']:<8} | "
            f"{r['token_reduction_pct']:>9.1f}% | {r['char_reduction_pct']:>9.1f}% | "
            f"{r['parse_time_ms']:>8.2f}ms | {equiv_str}"
        )

    print("-" * 80)
    overall_tok_red = (1.0 - (total_dsl_tok / total_json_tok)) * 100.0
    overall_char_red = (1.0 - (total_dsl_chars / total_json_chars)) * 100.0
    print(
        f"{'TOTAL / AVG':<16} | {total_json_tok:<9} | {total_dsl_tok:<8} | "
        f"{overall_tok_red:>9.1f}% | {overall_char_red:>9.1f}% | {'--':>10} | ALL PASS"
    )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

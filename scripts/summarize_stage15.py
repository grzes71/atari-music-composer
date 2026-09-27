import json
from pathlib import Path

p = Path("examples/ai/live/stage15/stage15_evaluation_data.json")
data = json.loads(p.read_text(encoding="utf-8"))

print("## Tabela Zbiorcza Kompozycji (Diversity Runs)")
print("| ID | Styl | Valid | Att | Nuty | Ch | Pat | Czas (s) | Gęstość (n/s) | Pitch Rng (st) | Avg Int (st) | REST % | Repet % | ASM (B) | XEX (B) | Fingerprint (skrót) |")
print("|---|---|:---:|:---:|---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")

for r in data["diversity_runs"]:
    an = r.get("analysis", {})
    rhy = an.get("rhythm", {})
    mel = an.get("melody", {})
    har = an.get("harmony", {})
    st = an.get("structure", {})
    
    val_str = "TAK" if r.get("validation_valid") else "NIE"
    att = r.get("attempts_count", 1)
    notes = rhy.get("total_notes", 0)
    ch = r.get("channels", 4)
    pat = st.get("pattern_count", 0)
    dur = st.get("duration_seconds", 0.0)
    dens = rhy.get("note_density", 0.0)
    prng = mel.get("pitch_range_semitones", 0)
    aint = mel.get("mean_interval", 0.0)
    rest_pct = f"{rhy.get('rest_ratio', 0.0)*100:.1f}%"
    rep_pct = f"{st.get('repetition_ratio', 0.0)*100:.1f}%"
    asm_sz = r.get("asm_size_bytes", 0)
    xex_sz = r.get("xex_size_bytes", 0)
    fp = r.get("fingerprint", "")[:12] + "..."
    
    print(f"| `{r['style_id']}` | {r['style']} | {val_str} | {att} | {notes} | {ch} | {pat} | {dur}s | {dens} | {prng} | {aint} | {rest_pct} | {rep_pct} | {asm_sz} | {xex_sz} | `{fp}` |")

print("\n## Tabela Testu Powtarzalności (Repeatability Test)")
print("| Styl | Run 1 Nuty | Run 2 Nuty | Run 1 Czas | Run 2 Czas | Run 1 Pitch Rng | Run 2 Pitch Rng | Run 1 FP | Run 2 FP | Identyczne FP? |")
print("|---|---:|---:|---:|---:|---:|---:|---|---|:---:|")

div_map = {r["style_id"]: r for r in data["diversity_runs"]}
for r2 in data["repeatability_runs"]:
    sid = r2["style_id"]
    r1 = div_map[sid]
    an1 = r1.get("analysis", {})
    an2 = r2.get("analysis", {})
    
    n1 = an1.get("rhythm", {}).get("total_notes", 0)
    n2 = an2.get("rhythm", {}).get("total_notes", 0)
    d1 = an1.get("structure", {}).get("duration_seconds", 0.0)
    d2 = an2.get("structure", {}).get("duration_seconds", 0.0)
    p1 = an1.get("melody", {}).get("pitch_range_semitones", 0)
    p2 = an2.get("melody", {}).get("pitch_range_semitones", 0)
    fp1 = r1.get("fingerprint", "")[:8] + "..."
    fp2 = r2.get("fingerprint", "")[:8] + "..."
    same = "TAK" if r1.get("fingerprint") == r2.get("fingerprint") else "NIE (stochastyczny)"
    print(f"| {r1['style']} | {n1} | {n2} | {d1}s | {d2}s | {p1} | {p2} | `{fp1}` | `{fp2}` | {same} |")

print("\n## Test Repair Loop")
for r in data["repair_loop_runs"]:
    print(f"- Style ID: `{r['style_id']}` ({r['style']})")
    print(f"- Attempts count: {r['attempts_count']}")
    print(f"- Retries needed: {r['retries_needed']}")
    print(f"- Validation valid on final attempt: {r.get('validation_valid')}")
    print(f"- ASM size: {r.get('asm_size_bytes')} B")
    print(f"- XEX size: {r.get('xex_size_bytes')} B")
    print(f"- XEX compiled successfully: {r.get('xex_ok')}")

print("\n## Retries in Diversity Runs")
for r in data["diversity_runs"]:
    if r.get("retries_needed", 0) > 0:
        print(f"- Style `{r['style_id']}` required {r['retries_needed']} retry.")



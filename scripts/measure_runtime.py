"""Benchmark and memory measurement for MADS Player and Music Data."""

import subprocess
from pathlib import Path
import json

from atari_music.api import generate_music
from atari_music.mads_exporter import export_mads_asm

def measure_player_code_size() -> int:
    mads_exe = Path("tools/mads/mads.exe")
    # Compile player alone with dummy song
    src = """
    org $6000
player_start:
    icl '../player.asm'
player_end:
"""
    asm_p = Path("experiments/measure_player.asm")
    asm_p.write_text(src, encoding="utf-8")
    bin_p = Path("experiments/measure_player.bin")
    res = subprocess.run([str(mads_exe), str(asm_p), f"-b:$6000", f"-o:{bin_p}"], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout
    return bin_p.stat().st_size

def measure_song_data_size(song_asm_path: Path) -> int:
    mads_exe = Path("tools/mads/mads.exe")
    # Use forward slashes for MADS icl
    rel_path = song_asm_path.as_posix()
    src = f"""
    org $8000
    icl '../{rel_path}'
"""
    asm_p = Path("experiments/measure_song.asm")
    asm_p.write_text(src, encoding="utf-8")
    bin_p = Path("experiments/measure_song.bin")
    res = subprocess.run([str(mads_exe), str(asm_p), f"-b:$8000", f"-o:{bin_p}"], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr or res.stdout
    return bin_p.stat().st_size

def run_benchmarks():
    out_dir = Path("experiments/mads_player_builds")
    out_dir.mkdir(parents=True, exist_ok=True)
    mads_exe = Path("tools/mads/mads.exe")

    player_size = measure_player_code_size()
    print(f"=== PLAYER CODE SIZE: {player_size} bytes ===")

    profiles = ["title", "exploration", "action", "funny", "dungeon", "ending"]
    report_data = []

    for p in profiles:
        res = generate_music(profile=p, seed=42)
        song_asm_path = out_dir / f"{p}_data.asm"
        export_mads_asm(res, song_asm_path)
        data_size = measure_song_data_size(song_asm_path)

        # Build full executable XEX
        harness_src = f"""
    org $6000
main:
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    jsr music_update
    rts

    icl '../../player.asm'
    icl '{song_asm_path.name}'

    run main
"""
        harness_asm = out_dir / f"{p}_run.asm"
        harness_asm.write_text(harness_src, encoding="utf-8")
        xex_path = out_dir / f"{p}_player.xex"

        comp_res = subprocess.run([str(mads_exe), str(harness_asm), f"-o:{xex_path}"], capture_output=True, text=True)
        assert comp_res.returncode == 0, f"Build failed for {p}: {comp_res.stderr or comp_res.stdout}"
        total_xex_size = xex_path.stat().st_size

        entry = {
            "profile": p,
            "tempo_bpm": res.metadata.tempo,
            "duration_sec": res.metadata.duration,
            "patterns": res.metadata.pattern_count,
            "sequence_len": res.metadata.sequence_length,
            "music_data_size_bytes": data_size,
            "player_code_size_bytes": player_size,
            "total_xex_size_bytes": total_xex_size,
            "xex_path": str(xex_path),
        }
        report_data.append(entry)
        print(f"[{p.upper()}] Data: {data_size} B | Player: {player_size} B | Total XEX: {total_xex_size} B | Patterns: {res.metadata.pattern_count}")

    with open(out_dir / "benchmark_summary.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    return report_data

if __name__ == "__main__":
    run_benchmarks()

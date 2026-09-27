"""Build and validate standalone Atari XEX executables for Stage 11 manual testing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from atari_music.api import MusicGenerationResult, generate_music
from atari_music.mads_exporter import export_mads_asm

ROOT_DIR = Path(__file__).resolve().parent.parent
MADS_EXE = ROOT_DIR / "tools" / "mads" / "mads.exe"
OUTPUT_DIR = ROOT_DIR / "stage11_xex"

CONFIGS = [
    {"profile": "title", "seed": 101, "uses_16bit_bass": False},
    {"profile": "exploration", "seed": 201, "uses_16bit_bass": False},
    {"profile": "action", "seed": 301, "uses_16bit_bass": False},
    {"profile": "funny", "seed": 401, "uses_16bit_bass": False},
    {"profile": "dungeon", "seed": 501, "uses_16bit_bass": True},
    {"profile": "ending", "seed": 601, "uses_16bit_bass": False},
]


def generate_harness_asm(profile: str, seed: int, song_asm: str) -> str:
    """Generate self-contained ASM containing harness, player, and song data."""
    header = f"""; =============================================================================
; Atari 800 XL / 65 XE Standalone Music Player & Test Harness
; Profile: {profile.upper()} | Seed: {seed}
; Auto-generated for ETAP 11 manual listening test
; =============================================================================

    org $4000

harness_start:
    ; 1. Standard Atari System Setup
    cli                         ; Ensure CPU interrupts enabled
    lda #$40
    sta $D40E                   ; NMIEN: Enable VBLANK NMI

    ; 2. Initialize Music Player with Song Data
    ldx #<song_data
    ldy #>song_data
    jsr music_init

    ; 3. Start Playback
    jsr music_play

    ; 4. Main Playback Loop (synchronized to PAL ~50 Hz VBLANK)
main_loop:
    ; Wait for VBLANK frame tick via OS real-time clock (RTCLOK+2 at $14)
    lda $14
@wait_vblank:
    cmp $14
    beq @wait_vblank

    ; Check keyboard for Space / keypress to toggle Pause / Mute
    lda $02FC                   ; CH (internal key code register)
    cmp #$FF
    beq @no_key

    ; Key was pressed: clear key latch
    pha
    lda #$FF
    sta $02FC
    pla

    ; Toggle playback: if playing -> stop; if stopped -> resume play
    jsr music_is_playing
    bne @do_stop
    jsr music_play
    jmp @no_key

@do_stop:
    jsr music_stop

@no_key:
    ; Call frame update routine (executes once per frame)
    jsr music_update

    jmp main_loop

harness_end:

; =============================================================================
; 6502 Relocatable Music Player
; =============================================================================
player_start:
    icl '../player.asm'
player_end:

; =============================================================================
; Song Music Data
; =============================================================================
{song_asm}
song_data_end:

; =============================================================================
; MADS Execution Entry Point
; =============================================================================
    run harness_start
"""
    return header


def parse_mads_symbols(lab_file: Path) -> Dict[str, int]:
    """Parse symbol values from MADS .lab symbol file."""
    symbols: Dict[str, int] = {}
    if not lab_file.exists():
        return symbols

    for line in lab_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or "=" in line:
            continue
        # Format: BANK_HEX  VALUE_HEX  LABEL_NAME (e.g. 00  4000  HARNESS_START)
        parts = line.split()
        if len(parts) >= 3:
            val_str = parts[1]
            sym_name = parts[2]
            try:
                symbols[sym_name.lower()] = int(val_str, 16)
            except ValueError:
                pass
        elif len(parts) == 2:
            sym_name = parts[0]
            val_str = parts[1]
            try:
                symbols[sym_name.lower()] = int(val_str, 16)
            except ValueError:
                pass
    return symbols


def build_stage11_package() -> List[Dict[str, Any]]:
    """Build all 6 standalone XEX files and collect metrics."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_results: List[Dict[str, Any]] = []

    for cfg in CONFIGS:
        prof = cfg["profile"]
        seed = cfg["seed"]
        use_16 = cfg["uses_16bit_bass"]

        print(f"--> Generating music for {prof.upper()} (seed={seed}, 16bit={use_16})...")
        res = generate_music(
            profile=prof,
            seed=seed,
            uses_16bit_bass=use_16,
        )

        song_asm = export_mads_asm(res)
        harness_asm = generate_harness_asm(prof, seed, song_asm)

        asm_file = OUTPUT_DIR / f"{prof}.asm"
        xex_file = OUTPUT_DIR / f"{prof}.xex"
        lab_file = OUTPUT_DIR / f"{prof}.lab"
        lst_file = OUTPUT_DIR / f"{prof}.lst"

        asm_file.write_text(harness_asm, encoding="utf-8")

        # Compile with MADS
        cmd = [
            str(MADS_EXE),
            str(asm_file),
            f"-o:{xex_file}",
            f"-t:{lab_file}",
            f"-l:{lst_file}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, f"MADS failed for {prof}:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"

        symbols = parse_mads_symbols(lab_file)
        xex_size = xex_file.stat().st_size

        # Extract address ranges
        harness_start = symbols.get("harness_start", 0x4000)
        harness_end = symbols.get("harness_end", 0x4030)
        player_start = symbols.get("player_start", harness_end)
        player_end = symbols.get("player_end", 0x4360)
        song_start = symbols.get("song_data", player_end)
        song_end = symbols.get("song_data_end", song_start)

        zp_base = symbols.get("player_zp_base", 0x80)

        # RAM state variables (from music_playing to ch_rel + 4)
        ram_start = symbols.get("music_playing", player_start)
        ram_end = symbols.get("ch_rel", ram_start) + 4
        ram_size = ram_end - ram_start

        harness_size = harness_end - harness_start
        player_code_size = (ram_start - player_start)  # Pure executable instructions
        player_total_size = player_end - player_start
        song_size = song_end - song_start

        info = {
            "profile": prof.upper(),
            "seed": seed,
            "tempo": res.metadata.tempo,
            "key": f"{res.metadata.key} {res.metadata.mode}",
            "duration": res.metadata.duration,
            "channels": res.metadata.channels_used,
            "uses_16bit_bass": res.metadata.uses_16bit_bass,
            "sequence_len": res.metadata.sequence_length,
            "patterns": res.metadata.pattern_count,
            "xex_size": xex_size,
            "harness": {
                "start": f"${harness_start:04X}",
                "end": f"${harness_end:04X}",
                "size": harness_size,
            },
            "player": {
                "start": f"${player_start:04X}",
                "end": f"${player_end:04X}",
                "total_size": player_total_size,
                "code_size": player_code_size,
            },
            "music_data": {
                "start": f"${song_start:04X}",
                "end": f"${song_end:04X}",
                "size": song_size,
            },
            "zero_page": {
                "start": f"${zp_base:02X}",
                "end": f"${zp_base + 9:02X}",
                "size": 10,
            },
            "ram_variables": {
                "start": f"${ram_start:04X}",
                "end": f"${ram_end:04X}",
                "size": ram_size,
            },
            "asm_file": f"{prof}.asm",
            "xex_file": f"{prof}.xex",
        }
        summary_results.append(info)
        print(f"[OK] {prof.upper()}: XEX={xex_size} B, Player={player_total_size} B, Song={song_size} B -> {xex_file}")

    # Remove temporary listing and label files if desired, or keep lab
    for ext in ("*.lst", "*.lab"):
        for f in OUTPUT_DIR.glob(ext):
            f.unlink()

    return summary_results


if __name__ == "__main__":
    results = build_stage11_package()
    print("\nSummary Results:")
    print(json.dumps(results, indent=2))

# Atari XEX v1/v2 End-to-End Verification & Hardware Safety Guide

This document describes how production-generated `.xex` binaries (`Studio ExportService` → `build_xex_from_result()` → `MADS` → `xex_layout` → `player_budget`) are verified across `py65`, optional full-system `AltirraSDL` (`AltirraBridge`), and manual Atari XL/XE hardware testing.

---

## 1. End-to-End Production XEX Verification in `py65` (`tests/test_xex_e2e_py65.py`)

### How It Works

Unlike isolated player unit tests that assemble synthetic `JSR music_init` / `JSR music_update` stubs, `tests/test_xex_e2e_py65.py` executes the **exact `.xex` file** written by the production export pipeline:

1. **Production export:** Builds real v1 and v2 `.xex` files through `Studio ExportService.export_xex()` → `build_xex_from_result()` → `tools/mads/mads.exe`.
2. **Static container & budget checks:** Validates framing (`$FF $FF`), user RAM bounds (`$0400–$BFFF`), disjoint segments, and `RUNAD` via `xex_layout.validate_xex_layout()`, plus `player_budget.check_player_size()` (`1,785 B < 2,048 B`).
3. **Atari DOS binary loading (`run_xex_in_py65`):**
   - Loads every segment payload into `py65` `ObservableMemory` at its exact load address.
   - Executes any `INITAD` (`$02E2–$02E3`) vector immediately before subsequent segments, then clears `INITAD`.
   - Enters execution directly at the XEX `RUNAD` (`$02E0–$02E1`) entry point (`$6000` by default).
4. **Harness & VBLANK simulation:**
   - Seeds `SAVMSC` (`$58/$59 = $BC40`, 960 B Graphics 0 screen RAM), `CH` (`$02FC = $FF`), and `RTCLOK` (`$14 = 0`).
   - Observes reads of `$14`; when the real harness enters `@wait_vblank: cmp $14 / beq @wait_vblank`, captures the committed POKEY snapshot (`$D200–$D208`) and 960-byte screen RAM snapshot, optionally injects a scheduled Atari key code into `$02FC`, and increments `$14`.
   - Monitors writes to `$C000–$FFFF` to assert zero illegal writes outside permitted GTIA (`$D017`, `$D018`, `$D01A`), POKEY (`$D200–$D208`), and ANTIC (`$D40E`) registers.
   - Enforces bounded cycle limits (`max_init_cycles`, `max_frame_cycles`, `max_total_cycles`) to catch hangs or invalid `RUNAD` vectors cleanly.

### What `py65` Verifies vs. Does Not Verify

| Verified by `py65` E2E | Not Verified by `py65` |
| :--- | :--- |
| Real DOS XEX segment loading, `INITAD`/`RUNAD` execution | Real Atari OS ROM cold boot, DOS 2.5 / SDX loader edge cases |
| Bit-exact `$D200–$D208` POKEY register parity vs. `frame_simulator.py` (v1, v2 8-bit, v2 16-bit `$50`) | Real POKEY silicon analog mixing / speaker audio output |
| Harness `init_screen_layout` + `update_screen_ui` writing Graphics 0 screen RAM (`TITLE`, `[PLAYING]`/`[PAUSED ]`, VU bars using `ch_out_vol,x` including v2 macro `vol_override`) | Real ANTIC Display List DMA & scanline cycle stealing |
| Real `$02FC` keyboard decoding (`1–4` channel mute/unmute, `Space` pause/resume) | Real POKEY keyboard matrix IRQ / debounce hardware |
| Zero illegal writes to `$C000–$FFFF` and bounded 6502 execution cycles | Real NTSC/PAL TV timing jitter and physical XL/XE hardware quirks |

---

## 2. Optional Full-System Emulator Verification (`tests/test_xex_altirra.py`)

`tests/test_xex_altirra.py` boots actual production v1, v2 8-bit, and v2 16-bit (`.xex`) binaries inside a real **AltirraSDL** Atari 800XL (PAL 50 Hz) emulator over **AltirraBridge**.

### Prerequisites

- Bundled MADS (`tools/mads/mads.exe`) and `src/atari_music/asm/player.asm`.
- Built `AltirraBridgeServer` or `AltirraSDL` executable with `--bridge` support (auto-discovered on `PATH`, via sibling `../AltirraSDL/build/...`, or via `ALTIRRA_SDL_BIN`).
- `altirra_bridge` Python SDK (installed in environment, auto-discovered in `../AltirraSDL/src/AltirraSDL/AltirraBridge/sdk/python`, or via `ALTIRRA_BRIDGE_SDK`).

### Running Locally

Normal offline CORE / CI runs (`pytest` or `pytest -m "core and not live"`) **never** launch the emulator because the suite carries `@pytest.mark.live` and `@pytest.mark.emulator` (and skips cleanly when AltirraSDL/SDK is unavailable).

To run the Altirra verification suite explicitly:

```powershell
# Optional: persist captured Atari screenshots
$env:ALTIRRA_ARTIFACT_DIR = ".\altirra_artifacts"
.venv\Scripts\pytest.exe -m emulator -o addopts="--strict-markers" -v
```

### Scope & Audio Capture Limitation

- **Verified in AltirraSDL (PAL 800XL):** DOS XEX loading via `RUNAD`, live ANTIC Mode 2 screen output (`screen_text()` + PNG `screenshot()`), PAL 50 Hz `RTCLOK` progression, hardware POKEY write traces (`pokey_trace_start`/`read`), `AUDCTL` and `audio_state()` channel output (including `join_1_2` for 16-bit `$50` bass), and live Atari keyboard injection (`1–4` channel mute/unmute, `Space` pause/resume + POKEY silence).
- **Audio limitation:** `AltirraBridge` v1 exposes POKEY register traces and decoded `audio_state()`, not raw PCM waveform capture. Rendered PCM audio output of compiled v1/v2 `player.asm` is separately verified via ASAP 8.0.0 (`asapconv.exe`) in `tests/test_stage_c_player_v2_parity.py`.

---

## 3. Hardware & Memory Safety Audit (Atari XL/XE PAL 50 Hz)

### Hardware Registers & OS Shadows Used by Harness + Player

| Address | Symbol / Role | Access | Notes |
| :--- | :--- | :--- | :--- |
| `$D200–$D207` | `AUDF1–4`, `AUDC1–4` (POKEY) | Write (`player.asm`) | Silenced on `music_init` / `music_stop`; written once per PAL VBLANK frame in `write_pokey_registers`. |
| `$D208` | `AUDCTL` (POKEY) | Write (`player.asm`) | Set from song header (`$00`, `$01`, `$10`, `$50`, etc.); cleared to `$00` on silence. |
| `$D40E` | `NMIEN` (ANTIC) | Write (`harness_start`) | Written `$40` (enables VBI NMI, disables DLI). Safe for standalone XEX; games using DLI must NOT use the standalone harness `NMIEN` write. |
| `$D017`, `$D018`, `$D01A` | `COLPF1`, `COLPF2`, `COLBK` (GTIA) | Write (`init_screen_layout`) | Immediate color writes paired with OS shadows (`$02C5`, `$02C6`, `$02C8`) so colors persist across OS VBI shadow refresh. |
| `$02C5`, `$02C6`, `$02C8` | `COLOR1`, `COLOR2`, `COLOR4` | Write (`init_screen_layout`) | Standard OS Graphics 0 luminance/background/border shadows. |
| `$02FC` | `CH` (OS keyboard shadow) | Read/Write (`main_loop`) | Polled each frame; cleared to `$FF` after reading; masked `& $3F` for `'1'` (`$1F`), `'2'` (`$1E`), `'3'` (`$1A`), `'4'` (`$18`), `'Space'` (`$21`). |
| `$14` | `RTCLOK` low byte | Read (`main_loop`) | Polled in `@wait_vblank` to synchronize `music_update` to OS VBI (50 Hz on PAL). |
| `$58/$59` | `SAVMSC` (OS screen RAM ptr) | Read (`harness_start`, `init_screen_layout`, `update_screen_ui`, `get_cell_ptr`) | Guarded by `lda $59 / beq` so UI is skipped if screen is disabled. |

### Memory Layout & Safety Findings

1. **Default Segment Placement (`$6000` player+harness, `$8000` song data):**
   - Assembled `player.asm` = **1,785 B** (includes 147 B BSS `music_playing..tmp_m_audf`; 262 B headroom under exclusive `< 2,048 B` budget).
   - Standalone harness + UI + `player.asm` occupies roughly `$6000–$6980` (~2.4 KB), leaving >5.5 KB gap before default `$8000` song data.
   - Song data at `$8000` stays below BASIC ROM (`$A000`) for all songs up to 8,192 bytes (typical songs are 0.2–2 KB).
2. **BASIC ROM (`$A000–$BFFF`) Requirement:**
   - `xex_layout.py` permits user RAM up to `$BFFF` (OS-enabled model). On stock Atari 600XL/800XL/65XE/130XE hardware, `$A000–$BFFF` is shadowed by internal Atari BASIC ROM unless BASIC is disabled (hold **`OPTION`** during cold boot or load from a DOS/menu that clears `PORTB` bit 1). Do not place segments in `$A000–$BFFF` if BASIC remains enabled.
3. **Zero Page (`PLAYER_ZP_BASE`, default `$80`, allowed `$80–$F2`):**
   - `player.asm` uses 10 bytes (`PLAYER_ZP_BASE + 0..9`, `$80–$89`).
   - Standalone harness uses 4 additional bytes (`PLAYER_ZP_BASE + 10..13`, `$8A–$8D`: `zp_scr_ptr`, `zp_str_ptr`).
   - Strictly inside Atari user Zero Page (`$80–$FF`), never touching OS Zero Page (`$00–$7F`).
4. **Harness Screen-Pointer Edge Observations (Non-blocking on standard 64 KB XL/XE):**
   - `init_screen_layout` clears 768 bytes (`3 × 256 B`, covering rows 0–19 of the 24-row Graphics 0 screen); rows 20–23 (below the UI footer on row 15) are not cleared if DOS left text at the bottom of the screen.
   - `get_cell_ptr` executes `tya / clc / adc $58 / adc screen_row_lo,x`. On standard 64 KB XL/XE Graphics 0 (`SAVMSC = $BC40`), `Y <= 11`, so `Y + $40 <= $4B` never carries. On unusual screen alignments with `$58 >= $F5`, the first `adc $58` could set Carry before `adc screen_row_lo,x` (adding 1 to the low byte instead of the high byte).
5. **PAL 50 Hz Timing & Game-Integration CPU Budget:**
   - Player tempo (`frames_per_tick`), ADSR frame counts, transient macro durations, pitch envelopes, and harness clock (`cmp #50`) assume **PAL 50 Hz** VBLANK (running on NTSC 60 Hz plays ~20% faster).
   - Measured `py65` `music_update` CPU cost: v1 avg `~809` cycles (max `1,524`); v2 steady 4-ch macro+pitch `1,117–2,572` cycles; v2 worst-case 4-ch simultaneous `PROGRAM_CHANGE` + macro + pitch `5,577` cycles (~15.7% of one PAL frame's ~35,568 cycles). In games with heavy DMA/DLI, call `music_update` in deferred VBI or main loop rather than an immediate VBI before display setup.

---

## 4. Manual Verification Procedure on Real Atari XL/XE Hardware

Use this checklist when testing exported `.xex` files on physical Atari 800XL / 65XE / 130XE (PAL) hardware:

1. **Preparation:** Copy a v1 `.xex` and a v2 `.xex` (both 8-bit and 16-bit `$50` bass if applicable) to SD/CF/SIO media (FujiNet, SIO2SD, AVGCart, Side3, or DOS 2.5 ATR).
2. **Boot Configuration:** Boot a **PAL** Atari XL/XE with **BASIC disabled** (hold `OPTION` on power-on, or use a loader/DOS that disables BASIC automatically).
3. **Launch XEX:** Load the `.xex` file from your DOS / cartridge menu.
   - Verify the screen switches cleanly to dark green (`$C4`) with bright white text (`$0E`), header `ATARI POKEY MUSIC PLAYER`, matching `TITLE:` and `TEMPO:`, and `STATUS: [PLAYING]`.
4. **Audio & Visual Playback Check:**
   - Confirm clean POKEY playback at expected PAL tempo with no clicks, hangs, or silent channels (note: on 16-bit `$50` bass songs, CH1 is the muted low-byte frequency slave and CH2 carries the audible bass).
   - Confirm `TIME:` advances 1 second every 50 PAL frames, `STEP:` increments across sequence steps and loops cleanly, and all active channel VU bars animate smoothly (including sharp peaks on v2 percussion/macro hits).
5. **Keyboard Controls Check:**
   - Press `1`, `2`, `3`, `4` individually: verify each channel toggles `ON` ↔ `OFF`, mutes audibly, and zeros its VU bar, then restores cleanly on the second press.
   - Press `Space`: verify `STATUS:` changes to `[PAUSED ]` and POKEY silences completely; press `Space` again to verify `[PLAYING]` resumes cleanly.
6. **Long-Run Stability:** Let the song loop for at least 2 full cycles and verify no timing drift, display corruption, or crash.

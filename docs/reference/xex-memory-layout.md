# XEX Memory Layout Validation

**Status:** implemented. `src/atari_music/xex_layout.py`, wired into
`atari_music.ai.client.build_xex_from_composition` and surfaced by `atari-music build-xex`.

## 1. Why this exists

Until 2026-10-09 the build policed one number: the complete `.xex` file had to be under 2048
bytes. That rule was a proxy for the *player* size limit, and the C1 per-channel modulation
made the proxy wrong — valid executables started being rejected for their song data
(`HISTORY.md`, 2026-10-09). The rule was removed and replaced by the rule it stood in for:
**the assembled player must be strictly smaller than 2048 bytes**.

Removing the file-size check left the pipeline with no check on where a binary actually
loads. A build could put the song data on top of the player, or place code inside the OS
ROM, and still report success. This is that check. It judges **address ranges**, never the
file size.

## 2. What the assembler actually emits

The generated assembly has two `org` blocks — the player's (harness + screen UI + `player.asm`)
and, when a music address is requested, the song data's — followed by `run harness_start`.
MADS turns that into a container with one segment per `org` plus the DOS RUN vector:

```text
$FF $FF  start_lo start_hi end_lo end_hi  <end-start+1 bytes>   ; first segment, marked
         start_lo start_hi end_lo end_hi  <end-start+1 bytes>   ; later segments, bare
```

A real build (`dungeon_dark`, player `$6000`, music `$8000`) measures:

| segment | range | bytes |
| :--- | :--- | ---: |
| player (harness + UI + player code) | `$6000-$6775` | 1910 |
| song data | `$8000-$808E` | 143 |
| DOS RUN vector | `$02E0-$02E1` | 2 |

Three facts make the walk deterministic rather than a scan, and all three are pinned by
tests:

1. `$FF $FF` is a marker before the **first** block, not a per-block command byte
   (`atari8bit/system/storage` §7.4). MADS emits it once; later segments are bare headers.
   A file that repeats it is also accepted, because the format reference allows both.
2. The end address is **inclusive**, so a segment's payload length is implied by its declared
   range.
3. Because of (2) the next header is always exactly where the previous payload ended — a
   payload containing `$FF $FF` cannot be mistaken for a header.

## 3. The memory policy

A user load segment must lie entirely inside **`$0400-$BFFF`**. Each bound is a project rule,
not a generic Atari map:

| region | verdict | evidence |
| :--- | :--- | :--- |
| `$0000-$00FF` zero page | refused | `atari8bit/system/memory-map/base-map.md`; the player reserves `PLAYER_ZP_BASE + 0..9` (default `$80-$89`, `AGENTS.md` §4) |
| `$0100-$01FF` hardware stack | refused | same map |
| `$0200-$02FF` DOS control block | refused | same map |
| `$0300-$03FF` OS vectors and shadows | refused | the harness writes `$02C6`/`$02C8`/`$02FC` and the loader writes the RUN vector `$02E0/$02E1`; IOCBs at `$0340-$03BF` |
| **`$0400-$BFFF`** | **permitted** | free RAM under the project's OS-enabled loading model |
| `$A000-$BFFF` BASIC ROM window | **permitted on purpose** | the project relocates there (`scripts/verify_stage11_runtime.py`); `AGENTS.md` §3.1 states no bound below `$BFFF` |
| `$C000-$CFFF` OS kernel ROM | refused | `AGENTS.md` §3.1: must never be used as RAM |
| `$D000-$DFFF` hardware registers | refused | `AGENTS.md` §3.1 — including the POKEY registers the player itself writes |
| `$E000-$FFFF` OS ROM | refused | `AGENTS.md` §3.1: "All user code, graphics, data, and tables MUST end at or below `$BFFF`" |
| `$02E0-$02E1` / `$02E2-$02E3` RUN/INIT vector | **exempt** | loader protocol emitted by `run`/`ini`, not user data |

Two further rules:

* **No two segments may claim the same memory.** The loader writes segments in file order, so
  the later one silently destroys the earlier one. This is the hazard `AGENTS.md` §3.3 names —
  "`org` directives … must be kept in strictly ascending memory order without location counter
  backtracking to prevent XEX segment overwrites during boot loading". An overwrite *is* an
  overlap, so overlap is what is checked; a descending but **disjoint** layout causes no
  overwrite and is accepted.
* **The player must be strictly smaller than 2048 bytes** — the project's one hard byte limit,
  unchanged, enforced through `player_budget.check_player_size` in the same validation step.

The model is OS-enabled: the generated harness reads RTCLOK `$14` and the SAVMSC shadow `$58/$59`
and writes the COLOR1/COLOR2/COLOR4 shadows (`$02C5`/`$02C6`/`$02C8`), GTIA immediate registers
(`$D017`/`$D018`/`$D01A`), `NMIEN` (`$D40E`), and `CH` (`$02FC`), and the executable is loaded by
DOS and entered through `RUNAD` (`$02E0/$02E1`). There is no banked or self-modifying loader in
this pipeline, so no exceptional region is claimed.

> **Stock XL/XE BASIC ROM Note (`$A000-$BFFF`):** Permitting `$A000-$BFFF` in `xex_layout.py` does
> not mean BASIC ROM is automatically disabled on a real Atari XL/XE. Default builds load player +
> harness at `$6000` and song data at `$8000` (staying safely below `$A000` for songs under 8 KB).
> Whenever a build places segments inside `$A000-$BFFF`, the Atari must be booted with BASIC
> disabled (hold `OPTION` on cold boot, or run under a DOS/loader that disables BASIC via `PORTB`
> bit 1). See [xex-verification.md](xex-verification.md) for the full hardware safety audit.

## 4. What a bad layout looks like

```text
XEX layout error: the song data at $6000-$608E (143 bytes) overlaps the player (harness +
player code) at $6000-$6775 (1910 bytes); they both claim $6000-$608E. The loader writes
segments in file order, so the later one silently destroys the earlier one. Player and song
data must occupy disjoint ranges.
```

```text
XEX layout error: the player (harness + player code) at $C000-$C775 (1910 bytes) loads
outside the permitted user RAM region. user code and data must load inside $0400-$BFFF:
$03FF and below is zero page, the hardware stack and the DOS/OS vectors this binary itself
uses, and $C000 and above is OS kernel ROM, hardware registers and OS ROM. Choose a
player/music address whose whole range fits inside $0400-$BFFF.
```

Every message names the segment, its range and the reason. The build raises
`xex_layout.XexLayoutError` (a `ValueError`); `atari-music build-xex` reports it as a plain
CLI error. **A failed build removes the binary it just wrote**, so nothing that cannot be
loaded is left looking runnable; the generated `.asm` beside it is kept, because that is what
makes the failure debuggable.

## 5. What is *not* validated

Stated so the gap is visible rather than assumed closed:

* **Song data is not checked for internal correctness** — only for where it lands.
* **Zero page is reserved, not allocated.** The validator keeps load segments out of
  `$0000-$03FF`, which covers `PLAYER_ZP_BASE` for every legal `--zp-base`; it does not check
  that two players in one image would agree about it, because there is only ever one player.
* **The RUN vector is not required to be present.** A container without it would load but not
  start; the pipeline always emits `run`, and this validator does not add a rule the assembler
  already guarantees.
* **No runtime check inside `xex_layout.py`.** This module is a static judgement about a file.
  Runtime execution of production-generated `.xex` files is covered separately by
  `tests/test_xex_e2e_py65.py` (CPU + POKEY `$D200-$D208` parity, `INITAD`/`RUNAD`, `SAVMSC` VU
  meters, keyboard `$02FC`, and OS ROM write guards) and optional full-system emulator tests in
  `tests/test_xex_altirra.py` (see [xex-verification.md](xex-verification.md)).

## 6. Where it lives

| file | role |
| :--- | :--- |
| `src/atari_music/xex_layout.py` | the parser, the policy constants and the validator |
| `src/atari_music/ai/client.py` | calls it on every build (`_validate_built_xex`) |
| `src/atari_music/cli.py` | turns the error into a clean CLI message |
| `src/atari_music/player_budget.py` | owns the `< 2048 B` player-size limit enforced in the same step |
| `tests/test_xex_layout.py` | container, policy, overlap, size and CLI coverage |
| `tests/test_xex_e2e_py65.py` | end-to-end production XEX execution and `$D200-$D208` parity in `py65` |
| `tests/test_xex_altirra.py` | optional full-system AltirraSDL PAL 800XL verification (`-m emulator`) |

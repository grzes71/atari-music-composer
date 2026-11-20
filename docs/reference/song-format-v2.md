# SONG_FORMAT_VERSION = 2 Binary & MADS Format Specification

Scope: Stage C Iteration 1 (`MAX_V2_INSTRUMENTS = 32`, `MAX_V2_MACRO_STEPS = 8`, `OPCODE_PROGRAM_CHANGE = $01`).

## 1. Song Header (`6 B`)

Compatible with format v1:

| Offset | Size | Field | Notes |
| --- | --- | --- | --- |
| `$00` | `1` | `frames_per_tick` | `1..255` |
| `$01` | `1` | `audctl_mode` | `AUDCTL` flags written by `player.asm` |
| `$02` | `2` | `instruments_ptr` | Word pointer to `*_instruments` |
| `$04` | `2` | `sequence_ptr` | Word pointer to `*_sequence` |

## 2. Instruments Table (`*_instruments`) — Header + SoA

Format version `2` sits at offset `$00` (v1 uses `$01`, legacy v0 uses generator multiple of `$20`).

| Offset | Size | Field | Notes |
| --- | --- | --- | --- |
| `$00` | `1` | `format_version` | Must equal `2` |
| `$01` | `1` | `instrument_count` | `N` in `1..32` |
| `$02` | `4` | `initial_ch_inst[0..3]` | Initial instrument indices (`0..N-1`) for CH1..CH4 |
| `$06` | `2` | `macros_ptr` | Word pointer to `*_macros` directory |

Immediately after byte `$07` follow `10` contiguous Structure-of-Arrays (SoA) rows of length `N` bytes each (stride `N` between rows, `inst_idx` in `0..N-1`):

| Row | Label suffix | Semantics |
| --- | --- | --- |
| `0` | `*_inst_dist` | Base `AUDC` distortion (`$00..$E0`, masked `& $E0`) |
| `1` | `*_inst_att` | Envelope attack duration (`0..255` frames) |
| `2` | `*_inst_dec` | Envelope decay duration (`0..255` frames) |
| `3` | `*_inst_sus` | Envelope sustain volume (`0..15`) |
| `4` | `*_inst_rel` | Envelope release duration (`0..255` frames) |
| `5` | `*_inst_flags` | Bit `0` (`$01`): `INST_FLAG_MOD_OCTAVE_PULSE` |
| `6` | `*_inst_macro_off` | Byte offset (`0, 2, 4, ...`) into `macros_ptr` directory, or `$FF` (`MACRO_NO_OFFSET`) |
| `7` | `*_inst_p_start` | Signed int8 initial `AUDF` pitch delta (`-127..127`) |
| `8` | `*_inst_p_dur` | Pitch envelope active frames (`0..15`; `0` disables pitch envelope) |
| `9` | `*_inst_p_step` | Signed int8 per-frame pitch step delta (`-16..16`) |

## 3. Shared Macro Directory & Pool (`*_macros`)

- Directory contains one `.word` pointer per deduplicated macro (`2` bytes/entry). When no instrument uses an active macro, a dummy `.word $0000` is emitted.
- Each macro entry consists of `1..8` fixed `4`-byte step records terminated by a `1`-byte `$00` (`MACRO_END_MARKER`):

| Offset | Size | Field | Encoding |
| --- | --- | --- | --- |
| `+0` | `1` | `frames_per_step` | `1..255` (`$00` reserved strictly as end marker) |
| `+1` | `1` | `flags` | Bit 0 (`$01`): `MACRO_FLAG_AUDF_FIXED` (else signed offset); Bit 1 (`$02`): `MACRO_FLAG_USE_STEP_DIST`; Bit 2 (`$04`): `MACRO_FLAG_USE_VOL_OVERRIDE` |
| `+2` | `1` | `audc_byte` | `(dist & $E0) | (vol_override & $0F)` |
| `+3` | `1` | `audf_byte` | Unsigned `$00..$FE` when `fixed`, signed int8 offset when `offset` |

## 4. Sequence & Channel Event Streams

- `*_sequence`: `.word` pointers to `*_pat_<id>_tracks`, terminated by `.word $FFFF` (loops back to index `0`).
- `*_pat_<id>_tracks`: `4` `.word` pointers (`CH1..CH4`) to track byte streams.
- Track byte stream grammar (endian-independent byte sequence terminated by `$FF`):
  - `$FF`: end of pattern track for this channel.
  - `b0 == $00` and `b1 == $00`: **4-byte extended command**:
    `[$00, $00, opcode, param]` (`opcode = $01` -> `OPCODE_PROGRAM_CHANGE`, `param = inst_idx` in `0..N-1`). Executes in `0` VBI ticks immediately before subsequent notes/rests.
  - Otherwise (`(b0, b1) != ($00, $00)` and `b0 != $FF`): **3-byte note/rest**:
    `[audf, duration_ticks, volume]` (`audf` `$00` = rest or `$01..$FE` note divider, `duration_ticks` `1..255`, `volume` `0..15`).

## 5. Validation & Known Limits

1. **Exporter-Side Strict Validation (`validate_v2_track_bytes`, `_validate_and_build_v2_tables`)**:
   - Enforces non-empty tracks ending with `$FF`, no bytes after `$FF`, no truncated 3-byte/4-byte records, valid opcodes (`$01`), in-bounds `param` (`0..N-1`), `<= 4` (`MAX_V2_CONSECUTIVE_COMMANDS`) consecutive commands before a note/rest, and at least one note/rest event per track.
   - `SONG_FORMAT_VERSION = 1` remains the default in `export_mads_asm()` and explicitly raises `FormatVersionError` when given v2 features (`> 4` instruments, active `is_v2` macros, `pitch_envelope`, `pending_program_changes`, `initial_channel_instruments`).
2. **Player Runtime Guards (`src/atari_music/asm/player.asm`)**:
   - Refuses unsupported `format_version`, out-of-range `inst_count` (`0` or `> 32`), invalid `initial_ch_inst`, invalid opcodes, or out-of-bounds `PROGRAM_CHANGE` targets by muting cleanly.
   - Enforces `MAX_V2_PARSE_COMMANDS = 8` per tick fetch to avoid infinite command loops in corrupt streams (inserts a 1-tick rest if exceeded).
3. **Header Byte-Length Limitation (Intentional Scope)**:
   - Track headers do not store an explicit stream byte length (`byte_len`). Corrupt memory missing `$FF` terminators relies on exporter validation and the runtime command cap rather than a per-track length bound.

## 6. Observed Resource & Timing Profile (`player.asm` v2, Stage C Iter 1)

Measured with MADS (`tools/mads/mads.exe`) and `py65`:

- **Code size (ROM)**: `1785 B` (`263 B` headroom under `2048 B` limit)
- **Zero Page**: `10 B` (`$80..$89`; zero collision with screen pointers `$8A..$8D`)
- **BSS RAM**: `147 B` (`music_playing..tmp_m_audf`)
- **VBI CPU cycles (`py65`)**:
  - Format v1 baseline (`action`, seed=42): `min=490`, `avg=808.8`, `max=1524`
  - Format v2 tick 0 (4-channel note fetch + macro/pitch init): `5315`
  - Format v2 steady active (4-channel active macros + pitch envelopes): `1117..2572`
  - Format v2 simultaneous 4-channel `PROGRAM_CHANGE` + macro + pitch: `5577`

## 7. Runtime Capability Contracts & Deferred Features

- **Implemented targets (`src/atari_music/instruments/runtime.py`)**:
  - `TARGET_V1_XEX` (`xex_v1`, v1, `{core_v1}`, `is_implemented=True`)
  - `TARGET_V2_ITER1_XEX` (`xex_v2`, v2, `{core_v1, core_v2_iter1}`, `is_implemented=True`)
  - `TARGET_WAV_V1_PREVIEW` (`wav`, v1, `{core_v1, wav_only}`, `is_implemented=True`)
  - `TARGET_WAV_PREVIEW` (`wav`, v2, `{core_v1, core_v2_iter1, wav_only}`, `is_implemented=True`; preview-only features remain blocked for XEX export)
- **Planned / Unimplemented targets**:
  - `TARGET_SAP_V1_PLANNED` and `TARGET_SAP_V2_ITER1_PLANNED` (`asap`, `is_implemented=False`) — emit `TARGET_NOT_IMPLEMENTED` warnings because CORE has no built-in SAP exporter.
- **Deferred features (blocked on v2 Iter 1)**:
  - `core_v2_iter2` (delayed vibrato, arpeggios, pitch slides), `experimental_deferred` (HPF XOR PWM `$02/$04`), 16-bit `CH3+CH4` (`$08`), and `wav_only` per-frame `volume_contour` during XEX export.
  - When `arrange_ir_song()` promotes a legacy v1 song to v2 because another channel uses v2 features, legacy `vibrato_depth`/`vibrato_speed` on untouched v1 channels is cleared with an explicit `LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION` warning diagnostic naming the affected channel, parameters, and reason (legacy vibrato is preserved untouched whenever the arrangement stays in v1).


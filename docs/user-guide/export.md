# Export & Atari Playback

Every composition — procedural, AI-generated, or imported — can be exported along three paths that are
kept bit-consistent with each other by shared hardware semantics (`pokey_hw.py`) and the frame simulator
oracle. This page summarizes what each artifact is; binary/assembly details live in the
[Reference](#reference-links) pages.

## WAV synthesis (`pokey_synth.py` / `pokey_hw.py`)

The software synthesizer renders 50 Hz PAL POKEY register frames directly to 16-bit PCM mono 44.1 kHz
`.wav`:

* the non-linear POKEY resistor-ladder DAC (`POKEY_DAC`),
* hardware-accurate `POLY4` (15-step, including modulo-3/5 stalls), `POLY5` (31-step XNOR gate),
  `POLY9` (511-step), and `POLY17` (131071-step) LFSRs,
* digital high-pass filter XOR latches (`AUDCTL $02` = HPF CH2 by CH4, `$04` = HPF CH1 by CH3),
* 16-bit channel joining (`AUDCTL $10` = CH1+CH2, `$08` = CH3+CH4).

Songs using v2 features (`song_requires_v2()`) automatically render through
`simulate_ir_song_frames(..., format_version=2)`, so WAV previews faithfully reflect transient macros,
pitch envelopes, and `PROGRAM_CHANGE` transitions. This is what makes an offline WAV a trustworthy
preview of what `player.asm` will play on hardware.

## MADS export (`mads_exporter.py`)

`export-mads` converts an existing **POKEY IR JSON** (`IRSong`) — not an `AICompositionDoc` — into
relocatable MADS assembly data (for canonical JSON use `import-json`/`arrange` first):

```bash
python -m atari_music compose --profile title --seed 101 --output-json title_ir.json
python -m atari_music export-mads title_ir.json -o title_data.asm --format-version auto
```

The exporter emits Structure-of-Arrays (SoA) tables for efficient MOS 6502 indexing (`LDA table,X`):

* **Format v1** (`SONG_FORMAT_VERSION = 1`, default) — up to 4 static channel-instrument records with
  ADSR envelopes and `MOD_OCTAVE_PULSE` modulation.
* **Format v2** (`SONG_FORMAT_VERSION_V2 = 2`) — up to 32 instruments
  (`MAX_V2_INSTRUMENTS = 32`), a deduplicated shared macro directory (1–8 steps of 4 bytes),
  signed 8-bit pitch envelopes, `CH1..CH4` initial assignment, and 4-byte `OPCODE_PROGRAM_CHANGE`
  (`$00, $00, $01, inst_idx`) events. Full layout: [Song Format v2](../reference/song-format-v2.md).

`--player-version auto` (default) keeps v1 whenever the song fits it and only selects v2 when required;
`v1` raises `FormatVersionError` instead of silently dropping v2 features.

## Atari XEX binaries & enforced hardware constraints

`build-xex` compiles a composition (**JSON or Music DSL**) plus the bundled relocatable player into a
standalone `.xex` executable with an interactive playback screen (`ANTIC` Mode 2 time display,
4-channel VU meters, per-channel key mute on `1`–`4`, pause on `Space`):

```bash
python -m atari_music build-xex examples/songs/Vaults-of-Nhyrmeth.dsl --format dsl -o vaults.xex
```

Defaults and relocations — `--player-address 0x6000`, `--music-address 0x8000`, `--zp-base 0x80`
(the player reserves only 10 Zero Page bytes, `$80..$89`, keeping screen pointers at `$8A..$8D` separate).

Hard guarantees, enforced per build ([`xex_layout.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/xex_layout.py),
[`player_budget.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/player_budget.py),
[spec](../reference/xex-memory-layout.md)):

* **Player budget** — `player.asm` code + BSS state must measure < 2048 bytes:
  `atari_music.player_budget.measure_player_size` currently reports **1785 bytes** (263 bytes
  headroom). The complete `.xex` file has no 2 KB cap.
* **Memory segment bounds** — every user load segment must lie strictly within `$0400–$BFFF`
  (`$A000–$BFFF` is allowed intentionally; OS kernel `$C000–$CFFF`, hardware I/O `$D000–$DFFF`,
  OS ROM `$E000–$FFFF`, Zero Page, stack, and OS vectors are forbidden).
* **Disjoint segments** — overlapping XEX segments are rejected immediately
  (`xex_layout.validate_xex_file`).
* **CPU discipline** — the player uses official MOS 6502 opcodes only.

## Verification chain

Exports are verified end-to-end (see [XEX Verification](../reference/xex-verification.md)):

1. **`py65` E2E** — `tests/test_xex_e2e_py65.py` boots the exact production `.xex` in a 6502 CPU
   emulator, asserts bit-exact `$D200–$D208` POKEY register parity against `frame_simulator.py`,
   checks the on-screen harness, and monitors for illegal writes/cycle overruns.
2. **Optional Altirra** — `tests/test_xex_altirra.py` boots real v1/v2 binaries inside
   `AltirraSDL` (PAL Atari 800XL) via `AltirraBridge` when the emulator is available locally.
3. **Manual hardware checklist** — the verification spec also documents a real XL/XE checklist.

## Legacy export paths

* **Sound-profile banks** — `--sound-bank DIRECTORY` / `--profile-bindings FILE` (see
  [Sound Profile Integration](../reference/profile-integration.md)).
* **Lead Library v0.1** — `--instrument PART=INSTRUMENT_ID` / `--instrument-library DIRECTORY` (see
  [Legacy Lead Library CLI](../reference/instrument-selection-cli.md)).

## Reference links

* [Song Format v2 specification](../reference/song-format-v2.md) — binary & MADS layout, opcodes,
  validation limits, measured player resource profile.
* [XEX Memory Layout](../reference/xex-memory-layout.md) — container parsing, `$0400–$BFFF` bounds,
  2 KB player rule.
* [XEX Verification](../reference/xex-verification.md) — py65/Altirra/hardware verification guide.

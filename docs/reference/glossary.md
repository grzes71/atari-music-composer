# Glossary

Hardware, format, and project terms used across the documentation.

## Hardware & POKEY

| Term | Meaning |
| --- | --- |
| **POKEY** | The Atari 8-bit sound chip: 4 audio channels, register file `AUDF1..AUDF4`, `AUDC1..AUDC4`, `AUDCTL` at `$D200–$D208`, plus keyboard/serial functions (unused here) |
| **PAL** | The 50 Hz TV standard targeted by this project (Europe); the timing frame for register updates. NTSC (60 Hz) is not targeted — see [limitations](limitations.md) |
| **VBLANK / frame** | One video frame (50 per second on PAL); the player updates POKEY registers once per frame, hence all timing is quantized to 1/50 s |
| **AUDF** | Audio frequency register: the 8-bit divider that, together with the channel clock, sets the pitch |
| **AUDC** | Audio control register: bits 4–7 select the distortion/generator, bits 0–3 the volume (0–15) |
| **AUDCTL** | Global audio control byte: clock selection, high-pass filters, 16-bit joins, 9-bit poly |
| **LFSR** | Linear-feedback shift register; POKEY's noise/polynomial generators (`POLY4`, `POLY5`, `POLY9`, `POLY17` with 15/31/511/131071-step sequences respectively) |
| **Distortion** | The `AUDC` generator selection. `$A0`/`$E0` are pure square; `$C0` poly4 buzz; `$80` the only true ungated noise; `$00/$20/$40/$60` are poly5-gated variants |
| **HPF XOR latch** | POKEY's digital high-pass: `AUDCTL $02` filters CH2 against CH4, `$04` filters CH1 against CH3 |
| **16-bit join** | Joining two channels into one 16-bit divider for deep bass notes: `$10` joins CH1 (master) + CH2 (slave), `$08` joins CH3 + CH4; the slave channel must be empty |
| **DAC ladder** | POKEY's non-linear resistor-ladder output; the WAV renderer reproduces it instead of a linear conversion |
| **`AUDCTL` bits** | `$01` 15 kHz clock · `$02` HPF CH2←CH4 · `$04` HPF CH1←CH3 · `$08` join CH3+CH4 · `$10` join CH1+CH2 · `$20` CH3 1.79 MHz · `$40` CH1 1.79 MHz · `$80` 9-bit poly noise |

## Atari & 6502 terms

| Term | Meaning |
| --- | --- |
| **MOS 6502** | The Atari's CPU; the project limits itself to the official 6502 instruction set (no 65C02/65816) |
| **MADS** | Macro Assembler / DevpacStn-compatible 6502 cross-assembler ([mads.atari8.info](http://mads.atari8.info/)); compiles the exported music data + `player.asm` into binaries |
| **XEX** | Atari DOS executable container: segment records (`$FFFF`, start, end, payload…), optional `INITAD`/`RUNAD` vectors; load segments must fit `$0400–$BFFF` here |
| **Zero Page (ZP)** | Page-zero RAM addresses used for the player's hot state; the player reserves 10 bytes from `--zp-base` (`$80..$89` by default) |
| **ANTIC / GTIA** | The display hardware; the built-in playback screen uses ANTIC Mode 2 text with GTIA-level color rules |
| **py65** | A 6502 CPU emulator for Python, used for register-parity tests of real built `.xex` files |
| **AltirraSDL / AltirraBridge** | Full-system Atari emulation used by optional emulator tests |
| **ASAP** | (SAP-capable Atari audio library) used locally to render/compare real POKEY audio in research/regression suites |

## Project terms

| Term | Meaning |
| --- | --- |
| **Composer v4** | The current procedural, seeded 4-channel composition engine behind `compose` |
| **`AICompositionDoc`** | The canonical, SSOT composition document (schema in `ai/schema.py`, `"format": "atari-music-composition"`); the only interchange format for compositions |
| **Music DSL** | compact, LLM-friendly textual frontend that compiles losslessly into `AICompositionDoc`; specified [here](music-dsl.md) |
| **Music IR / `MusicSong`** | Symbolic intermediate representation (`music_ir.py`) before hardware decisions |
| **POKEY IR / `IRSong`** | Hardware-compiled IR (`ir.py`): divider parameters, resolved instruments, program changes; the pivot artifact both renderers derive from |
| **SSOT** | Single Source of Truth — a deliberate redundancy-avoidance stance: one validity source for hardware semantics (`pokey_hw.py`), one for instruments (`catalog.json`), one for compositions (`AICompositionDoc`) |
| **Instrument catalog** | `data/instruments/catalog.json` (schema `atari-music/instrument-catalog/1`): 16 curated profiles + behaviors with hard hardware constraints |
| **`POKEYRuntime`** | The stateless checker that validates instrument *sets* (channel locks, clock compatibility, 16-bit pairing, target tiers) |
| **Runtime tier** | Capability class of an instrument: `core_v1`, `core_v2_iter1`, `core_v2_iter2` (deferred), `experimental_deferred`, `wav_only` |
| **Behavior** | Time-varying aspect of an instrument: static v1, `octave_pulse` modulation, transient macros, and/or pitch envelopes |
| **Arrangement** | Re-voicing an existing composition (channel instruments, program-change policy) without touching notes; guaranteed fingerprint-identical musical content |
| **Song Format v1 / v2** | The binary song data formats the 6502 player consumes; v2 adds 32-instrument tables, shared macro directory, pitch envelopes, and `PROGRAM_CHANGE` ([spec](song-format-v2.md)) |
| **`PROGRAM_CHANGE`** | Mid-song instrument switch event (opcode `$01` in format v2), scheduled at 0 ticks |
| **Player budget** | The `player.asm` code + BSS size limit `< 2048 B` enforced at build time (currently 1785 B) |
| **Frame simulator** | Python oracle of the v1/v2 50 Hz state machines; the parity reference for both WAV rendering and `py65` player tests |
| **Musical fingerprint** | SHA-256 over all musical content (notes, rests, durations, volumes, tempo, patterns, sequence) — identical across arrangements of one composition |
| **Target** | Export capability set: `xex_v1`, `xex_v2`, `wav` (implemented); `asap` (declared, not implemented) |
| **Stages 9–25 / Experiments 26–30** | The staged research programme preserved in the [Research](../research/index.md) section |
| **Sound profile bank** | Stage 9 external POKEY "sound archaeology" register-frame profiles bindable via `--sound-bank`/`--profile-bindings` (see [integration](profile-integration.md)) |


# Atari Music Composer

A Python toolchain and relocatable MOS 6502 audio driver for composing, validating, arranging, synthesizing, and compiling multi-channel music for **Atari 8-bit computers (Atari 800 XL / 65 XE, PAL 50 Hz)** equipped with the **POKEY** sound chip.

This site is the project's central documentation. The sources are maintained in the
[`docs/`](https://github.com/grzes71/atari-music-composer/tree/main/docs) directory together with
[`mkdocs.yml`](https://github.com/grzes71/atari-music-composer/blob/main/mkdocs.yml); the site is rebuilt
and published automatically by the
[Docs workflow](https://github.com/grzes71/atari-music-composer/actions/workflows/docs.yml) on every push
to `main` that touches documentation.

## What it does

The system separates **musical composition** (notes, rhythm, form, harmony) from **hardware instrument
realization** (waveforms, envelopes, transient macros, pitch envelopes, and `AUDCTL` clock/filter routing).
A single composition can be re-arranged across multiple POKEY instrumentations and exported to WAV
previews and standalone Atari `.xex` executables — without re-invoking AI and without modifying the
musical content.

Core capabilities:

* **Procedural composition (`compose`)** — deterministic 4-channel Composer v4 across six stylistic
  profiles (`title`, `exploration`, `action`, `funny`, `dungeon`, `ending`) with bass lines, counterpoint,
  percussion/ornamentation, and optional `CH1+CH2` 16-bit bass coupling.
* **AI-assisted composition (`ai-compose`)** — LLM providers (OpenAI / DeepSeek, or an offline
  deterministic mock) emit a canonical composition document in JSON or a compact Music DSL, validated by
  a 3-tier validator (schema, musical grammar, POKEY hardware rules) with an automatic repair loop.
* **SSOT instrument catalog** — curated, hardware-validated POKEY instrument definitions
  ([`data/instruments/catalog.json`](https://github.com/grzes71/atari-music-composer/blob/main/data/instruments/catalog.json))
  with stateless channel/clock-conflict checking.
* **Decoupled arrangement (`arrange`)** — re-assign POKEY channel instruments on existing JSON
  compositions and export WAV, MADS ASM, and Atari XEX without touching notes.
* **Atari Music Composer Studio** — optional PySide6 desktop application for opening compositions,
  inspecting/reassigning instruments, A/B comparing renditions, and exporting validated `.xex` builds.
* **Hardware-accurate audio** — a frame-accurate Python WAV renderer plus a relocatable pure MOS 6502
  player (`player.asm`) supporting legacy v1 and macro-enabled v2 song formats.

## Supported hardware

| Topic | Constraint |
| --- | --- |
| Sound chip | POKEY — 4 monophonic channels, `AUDF1..AUDF4`, `AUDC1..AUDC4`, `AUDCTL` (`$D200–$D208`) |
| Frame timing | PAL VBLANK, 50 Hz register frames |
| Base clocks | 64 kHz (`PAL/28` ≈ 63921 Hz), 15 kHz (`PAL/114` ≈ 15696 Hz); 1.79 MHz available for CH1/CH3 |
| Target machine | Atari 800 XL / 65 XE — official MOS 6502 instruction set only (no 65C02/65816) |
| Player budget | < 2048 bytes of player code + state (measured: 1785 B) |
| XEX memory bounds | All load segments strictly within `$0400–$BFFF`, mutually disjoint |

See the [Glossary](reference/glossary.md) and [Technical Limitations](reference/limitations.md) for the
full picture, and the [Architecture](architecture/overview.md) section for how the constraints shaped
the design.

## Where to go next

| I want to… | Read |
| --- | --- |
| Install the toolchain and configure an AI provider | [Installation](getting-started/installation.md) |
| Generate my first song (WAV / JSON / XEX) | [Your First Composition](getting-started/first-composition.md) |
| Use the CLI day to day | [User Guide](user-guide/workflow.md) and [CLI Reference](reference/cli.md) |
| Understand instrument selection and the catalog | [Instruments](user-guide/instruments.md) |
| Understand the runtime and the 6502 player | [Architecture](architecture/overview.md) |
| Contribute, run tests, or add instruments | [Development](development/environment.md) |
| Study the research history of the project | [Research Programme](research/index.md) |

## Project status and limitations

* The **CORE production pipeline** (`compose`, `ai-compose`, `arrange`, `list-instruments`,
  `inspect-instrument`, `validate-instruments`, `import-json`, `import-dsl`, `export-mads`, `build-xex`,
  `analyze`) is covered by offline regression tests (`pytest -m "core and not live"`).
* The many **research stage commands** visible in `atari-music --help` (`analyze-stage15`…
  `analyze-stage25`, listening-test preparation, etc.) are experimental research tooling, kept separate
  from the production workflow.
* The catalog currently holds **16 curated instruments**: 8 `core_v1` profiles (ADSR / octave pulse),
  6 `core_v2_iter1` profiles (transient macros and pitch envelopes), and 2 explicitly **deferred**
  experimental profiles. Deferred features (`core_v2_iter2`, 16-bit `CH3+CH4`, built-in SAP export) are
  intentionally blocked rather than silently unavailable — see
  [Technical Limitations](reference/limitations.md).
* Only PAL 50 Hz timing is targeted. Compiling `.xex` binaries requires the external
  [MADS](http://mads.atari8.info/) assembler (see [Installation](getting-started/installation.md)).

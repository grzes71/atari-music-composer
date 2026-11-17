# Atari 8-bit POKEY Music Engine & Toolkit

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform: Atari 8-bit](https://img.shields.io/badge/platform-Atari%20800%20XL%20%2F%2065%20XE-red.svg)](https://en.wikipedia.org/wiki/Atari_8-bit_family)
[![Assembler: MADS](https://img.shields.io/badge/assembler-MADS-green.svg)](http://mads.atari8.info/)
[![CPU: MOS 6502](https://img.shields.io/badge/cpu-MOS%206502-orange.svg)](https://en.wikipedia.org/wiki/MOS_Technology_6502)

A Python toolchain and relocatable MOS 6502 audio driver for composing, validating, arranging, synthesizing, and compiling multi-channel music for **Atari 8-bit computers (Atari 800 XL / 65 XE, PAL 50 Hz)** equipped with the **POKEY** sound chip.

The system separates **musical composition** (notes, rhythm, form, harmony) from **hardware instrument realization** (waveforms, envelopes, transient macros, pitch envelopes, and `AUDCTL` clock/filter routing), allowing a single composition to be synthesized to WAV and compiled into standalone Atari `.xex` executables across multiple instrumentation arrangements without re-invoking AI.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Installation and Configuration](#installation-and-configuration)
3. [CLI Reference](#cli-reference)
4. [Composition Formats](#composition-formats)
5. [Instrument System](#instrument-system)
6. [Arrangement Workflow](#arrangement-workflow)
7. [Export and Atari Playback](#export-and-atari-playback)
8. [Architecture and Development](#architecture-and-development)
9. [Related Documentation](#related-documentation)

---

## Project Overview

Atari Music Composer targets the 4-channel monophonic **POKEY** chip (`AUDF1..AUDF4`, `AUDC1..AUDC4`, `AUDCTL`) running at PAL VBLANK timing (50 Hz frames):

```text
  Procedural Composer v4                 AI LLM Composer (OpenAI / DeepSeek / Mock)
  (atari-music compose)                  (atari-music ai-compose --format json|dsl)
            │                                      │ JSON            │ Music DSL
            │                                      ▼                 ▼
            │                            AICompositionDoc v1 ◄── parse_music_dsl()
            │                            (3-tier validation & LLM repair loop)
            │                                      │
            └──────────────────┬───────────────────┘
                               ▼
                     Symbolic Music IR / POKEY IR (IRSong)
                               │
                               ├──► atari-music arrange (optional, zero AI calls;
                               │    assigns SSOT catalog instruments & policies)
                               ▼
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   Software POKEY Synth (Python)     MADS Exporter (SoA: Format v1 or v2)
   Hardware LFSR, 16-bit & HPF XOR             │
              │                                 ▼
              ▼                        player.asm (MOS 6502) + MADS
         44.1 kHz WAV                    Relocatable Atari XEX Binary
```

### Core Capabilities

* **Procedural Composition (`Composer v4`)**: Generates deterministic 4-channel pieces across 6 canonical profiles (`title`, `exploration`, `action`, `funny`, `dungeon`, `ending`) with bass lines, counterpoint, percussion/ornamentation, and optional `CH1+CH2` 16-bit bass coupling.
* **AI-Assisted Composition (`ai-compose`)**: Uses `OpenAICompositionProvider` (supporting OpenAI, DeepSeek, or compatible endpoints) or a local deterministic `mock` provider to output canonical `AICompositionDoc` JSON or compact **Music DSL**, backed by a 3-tier validator (schema, musical grammar, POKEY hardware rules) and an automatic repair loop.
* **SSOT Instrument Catalog & `POKEYRuntime`**: Curated instrument definitions and time-varying behaviors stored in [data/instruments/catalog.json](data/instruments/catalog.json) with stateless hardware/channel conflict checking.
* **Decoupled Arrangement (`arrange`)**: Re-assigns POKEY channel instruments on existing JSON compositions (`AICompositionDoc` or `IRSong`) and exports WAV, MADS ASM, and Atari XEX outputs without modifying musical content or calling AI again.
* **Hardware-Accurate Audio Preview & 6502 Playback**: Frame-accurate Python WAV renderer and a relocatable pure MOS 6502 player (`src/atari_music/asm/player.asm` / `player.asm`) supporting both legacy v1 and macro-enabled v2 song formats.

> **Stability note:** The CORE production pipeline (`compose`, `ai-compose`, `arrange`, `list-instruments`, `inspect-instrument`, `validate-instruments`, `import-json`, `import-dsl`, `export-mads`, `build-xex`, `analyze`) is covered by offline regression tests (`-m "core and not live"`). Research stage commands (`prepare-listening-test-9c`, `analyze-stage15`..`analyze-stage25`, etc.) and external archaeology sound-profile benchmarks are experimental research tools and are kept separate from the production workflow.

---

## Installation and Configuration

### System Requirements

* **Python `>= 3.10`**
* **OS:** Windows, Linux, or macOS
* **MADS Assembler:** Required only when compiling `.xex` binaries or running 6502 size/parity checks. Windows includes `tools/mads/mads.exe` in the repository; on Linux/macOS provide `mads` on `PATH` or pass `--mads PATH`.

### Python Environment Setup

```bash
cd atari-music

# Create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install the package in editable mode
pip install -e .
```

If you plan to use live AI generation (`openai` or `deepseek` providers) or run 6502 CPU emulation tests, ensure those optional runtime tools are also installed in your environment:

```bash
pip install openai py65
```

### Dependencies

Core package dependencies declared in [pyproject.toml](pyproject.toml) and [requirements.txt](requirements.txt):

* `pydantic >= 2.0.0` — schema models and validation (`AICompositionDoc`, `InstrumentCatalogDocument`, `IRSong`)
* `numpy >= 1.24.0` — hardware POKEY audio synthesis buffers
* `click >= 8.0.0` — CLI commands
* `matplotlib >= 3.7.0` — visualization and analysis plots
* `pytest >= 7.0.0` — automated test runner
* `python-dotenv >= 1.0.0` — `.env` configuration loading

Optional/developer packages in `pyproject.toml` (`[project.optional-dependencies].dev`) and runtime integrations:

* `openai` — required at runtime only when calling live LLM endpoints (`AIProviderDependencyError` is raised if missing)
* `py65` — required for 6502 CPU emulation parity tests
* `build`, `python-semantic-release` — packaging/release extras

### AI Provider & `.env` Configuration

Configuration uses a 4-level priority chain in [src/atari_music/config.py](src/atari_music/config.py) (highest to lowest):

1. Explicit CLI flags (e.g., `--provider`, `--model`, `--env-file`)
2. System environment variables
3. `.env` file values (default `.env`, or custom path via `--env-file PATH`)
4. Code defaults (`AI_PROVIDER=deepseek`, `AI_BASE_URL=https://api.deepseek.com`, `AI_MODEL=deepseek-flash`)

Copy [.env.example](.env.example) to `.env` and fill in your credentials locally (`.env` is gitignored — never commit real keys):

```env
# Supported CLI providers: deepseek, openai, mock
AI_PROVIDER=deepseek
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-flash
LOG_LEVEL=INFO
```

#### Supported AI Providers & Legacy Env Fallbacks

| Provider | How it is selected | Endpoint / Client | Notes |
|---|---|---|---|
| `deepseek` | Default, or `--provider deepseek` / `AI_PROVIDER=deepseek` | `OpenAICompositionProvider` (default `https://api.deepseek.com`, model `deepseek-flash`) | Uses OpenAI-compatible Chat Completions API |
| `openai` | `--provider openai` / `AI_PROVIDER=openai` | `OpenAICompositionProvider` (uses `AI_BASE_URL` / `OPENAI_BASE_URL` and `AI_MODEL` / `OPENAI_MODEL`) | Works with OpenAI or any OpenAI-compatible URL |
| `mock` | `--provider mock` / `AI_PROVIDER=mock` | `MockAICompositionProvider` | Offline deterministic mock; no API key or network needed |

* **Backward-compatible env variables:** When `AI_*` variables are unset, `Config` and `OpenAICompositionProvider` automatically fall back to `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`, `DEEPSEEK_BASE_URL` / `OPENAI_BASE_URL`, `DEEPSEEK_MODEL` / `OPENAI_MODEL`, and `DEEPSEEK_PROVIDER`.
* **Secret safety:** API keys are masked in diagnostics (`Config.masked_api_key()` / logging secret filter) and are never written into exported JSON, `.asm`, `.xex`, or test-suite manifests. Placeholder values such as `your_api_key_here` are rejected when invoking live API requests.

---

## CLI Reference

Run commands either via the installed entry point `atari-music` or via module invocation `python -m atari_music`.

### Global Options

```bash
python -m atari_music [OPTIONS] COMMAND [ARGS]...
```

* `-v, --version`: Show package version and exit (`0.8.0`).
* `--env-file FILE`: Path to custom `.env` file (default `.env`).
* `--log-level [debug|info|warning|error|critical]`: Override log level.
* `--help`: Show all available commands (legacy and research subcommands are kept for backward compatibility).

---

### `compose`

Generate procedural 4-channel POKEY music via the public Music Generation API (`Composer v4`).

* **Options:**
  * `-p, --profile TEXT`: Stylistic profile (`title`, `exploration`, `action`, `funny`, `dungeon`, `ending`).
  * `-s, --seed INTEGER`: Deterministic RNG seed.
  * `-k, --key TEXT`: Root pitch class (`C`, `D`, `E`, `F`, `G`, `A`, `B`, including sharps/flats supported by `VALID_ROOT_KEYS`).
  * `-t, --tempo INTEGER`: Tempo in BPM (`50..240`).
  * `-l, --length [short|medium|long]`: Target song duration bucket.
  * `--intensity FLOAT`, `-v, --variation FLOAT`: Musical expression controls (`0.0..1.0`).
  * `--channel-instrument CH=INSTRUMENT_ID`: Repeatable opt-in SSOT catalog override per channel (`1..4` or role alias).
  * `--program-change CH@TARGET[:NOTE]=INSTRUMENT_ID`: Schedule mid-song instrument switch (e.g., `3@B=lead_attack_bite` or `4@1:2=perc_snare_crisp`).
  * `--instrument-catalog FILE`: Custom catalog JSON path (default `data/instruments/catalog.json`).
  * `--player-version [auto|v1|v2]`: Target MADS export version (`auto` preserves v1 unless v2 features are used).
  * `--output-json PATH`, `--output-wav PATH`, `--output-asm PATH`: Output artifacts.
* **Inputs / Outputs:** Procedural parameters -> POKEY IR JSON, 44.1 kHz WAV, and/or MADS `.asm`.

```bash
# Legacy procedural v1 composition (unchanged default behavior)
python -m atari_music compose --profile action --seed 301 --output-wav action.wav --output-asm action.asm

# Opt-in SSOT instrument assignment + mid-song PROGRAM_CHANGE (exports Format v2)
python -m atari_music compose --profile exploration --seed 201 \
  --channel-instrument 1=bass_poly4_punch \
  --channel-instrument 3=lead_pure_sustain \
  --program-change 3@1:0=lead_attack_bite \
  --output-json explore_v2.json --output-wav explore_v2.wav --output-asm explore_v2.asm
```

---

### `ai-compose`

Generate a declarative composition (`AICompositionDoc` JSON or Music DSL) using an AI provider (`openai`, `deepseek`, or offline `mock`), validated and optionally repaired up to `--max-retries` times.

* **Options:**
  * `--style TEXT`: Musical style prompt (default `"dark dungeon exploration"`).
  * `-m, --mood TEXT`: Repeatable mood keyword.
  * `--duration FLOAT`, `--bpm INTEGER`, `--channels INTEGER` (`1..4`), `--structure TEXT` (default `"A-B-A"`).
  * `--use-16bit-bass / --no-16bit-bass`: Enable `CH1+CH2` 16-bit bass coupling.
  * `--format [json|dsl]`: LLM output format (`json` default, or `dsl`).
  * `--provider [mock|openai|deepseek]`: Override `AI_PROVIDER`.
  * `--model TEXT`: Override AI model name.
  * `--env-file FILE`: Override `.env` file path.
  * `--max-retries INTEGER`: Validation repair retries (default `3`).
  * `--channel-instrument CH=INSTRUMENT_ID`: Explicit SSOT catalog instrument assignment per channel (`1..4` or role).
  * `--use-instrument-catalog / --no-use-instrument-catalog`: Opt-in exposure of SSOT catalog instruments & behaviors to the AI composer.
  * `--instrument-catalog FILE`, `--player-version [auto|v1|v2]`.
  * `--output-ir PATH`, `--output-asm PATH`, `--output-wav PATH`, `-o, --output PATH` (omitted or `-` writes to stdout).
* **Inputs / Outputs:** Prompt parameters -> canonical JSON (`atari-music-composition`) or `.dsl` text, plus optional POKEY IR JSON / WAV / ASM.

```bash
# Offline deterministic mock producing canonical AI composition JSON
python -m atari_music ai-compose --provider mock --style "dark dungeon exploration" -m dark --duration 24 -o composition.json

# Generate compact Music DSL with catalog awareness enabled
python -m atari_music ai-compose --provider mock --format dsl --use-instrument-catalog -o composition.dsl
```

---

### `arrange`

Re-arrange an existing **JSON** composition (`AICompositionDoc` or POKEY IR `IRSong`) with new POKEY channel instruments without calling AI.

* **Required Argument:**
  * `INPUT_COMPOSITION`: Path to an existing composition JSON or POKEY IR JSON file (see [Arrangement Workflow](#arrangement-workflow) for `.dsl` conversion).
* **Options:**
  * `--channel-instrument CH=INSTRUMENT_ID`: Repeatable channel or role assignment (`1..4` or alias; unassigned channels keep their existing realization).
  * `--program-change-policy [preserve|replace|remove]`: Controls existing `PROGRAM_CHANGE` events on overridden channels (default `preserve`).
  * `--instrument-catalog FILE`: Custom SSOT catalog JSON path (default `data/instruments/catalog.json`).
  * `--player-version [auto|v1|v2]`: Format target for MADS/XEX output (default `auto`).
  * `--output-json`, `--output-ir PATH`: Save arranged POKEY IR JSON (`IRSong`).
  * `--output-wav PATH`: Render 44.1 kHz WAV audio.
  * `--output-asm PATH`: Export MADS assembly file.
  * `-o, --output-xex PATH`: Compile standalone Atari XEX binary.
  * `--player-address TEXT` (default `0x6000`), `--music-address TEXT` (default `0x8000`), `--zp-base TEXT` (default `0x80`), `--mads PATH` (default `tools/mads/mads.exe`), `--player-asm PATH`.
* **Inputs / Outputs:** Existing JSON composition -> arranged POKEY IR JSON, WAV, MADS ASM, and/or XEX (input file is never altered).

```bash
python -m atari_music arrange examples/ai/dungeon_dark.json \
  --channel-instrument 1=bass_16bit_pure \
  --channel-instrument 3=lead_attack_bite \
  --program-change-policy replace \
  --output-json output/arranged_ir.json \
  --output-wav output/arranged.wav \
  -o output/arranged.xex
```

---

### `list-instruments`

List curated instruments defined in the SSOT catalog (`data/instruments/catalog.json`) along with compatibility for a chosen target backend.

* **Options:**
  * `--instrument-catalog, --catalog FILE`: Catalog path (default `data/instruments/catalog.json`).
  * `--family [lead|bass|pad|harmony|percussion|fx]`: Filter by family.
  * `--role [melody|bass|harmony|rhythm|percussion]`: Filter by intended role.
  * `--target [xex_v2|xex_v1|wav]`: Report compatibility against backend (`xex_v2` default).
  * `--json`: Emit machine-readable JSON.

```bash
python -m atari_music list-instruments --target xex_v2 --family bass
```

---

### `inspect-instrument`

Display complete hardware constraints, ADSR envelope, `runtime_tier`, behavior (transient macro / pitch envelope / modulation), provenance, and target compatibility (`xex_v1`, `xex_v2`, `wav`) for one instrument.

* **Required Argument:** `INSTRUMENT_ID`
* **Options:** `--instrument-catalog, --catalog FILE`, `--json`.

```bash
python -m atari_music inspect-instrument lead_attack_bite
```

---

### `validate-instruments`

Validate catalog JSON schema (`atari-music/instrument-catalog/1`), cross-field hardware rules (`divider_mode` vs `required_audctl_bits`, macro limits), behavior links, and provenance.

* **Options:** `--instrument-catalog, --catalog FILE`.

```bash
python -m atari_music validate-instruments
```

---

### `export-mads`

Convert an existing **POKEY IR JSON** (`IRSong`) directly into relocatable MADS assembly data.

* **Required Argument:** `INPUT_JSON` (POKEY IR JSON; note: for `AICompositionDoc` JSON use `import-json` or `arrange`).
* **Options:**
  * `-o, --output-asm PATH` *(required)*: Destination `.asm` path.
  * `--player-version, --format-version [auto|v1|v2]`: Target MADS export format (`auto` preserves v1 when sufficient; selects v2 when v2 features are present).

```bash
python -m atari_music compose --profile title --seed 101 --output-json title_ir.json
python -m atari_music export-mads title_ir.json -o title_data.asm --format-version auto
```

---

### `build-xex`

Compile an AI composition (**JSON or Music DSL**) directly into a relocatable standalone Atari `.xex` executable with interactive playback screen (`ANTIC Mode 2` time display + 4-channel VU meters + key mute toggle).

* **Required Argument:** `COMPOSITION_FILE`
* **Options:**
  * `-o, --output PATH`: Output `.xex` path.
  * `--format [json|dsl]`: Input format (default `json` or inferred from `.dsl` extension).
  * `--player-address TEXT` (default `0x6000`), `--music-address TEXT` (default `0x8000`), `--zp-base TEXT` (default `0x80`).
  * `--mads PATH`, `--player-asm PATH`.
  * `--player-version [auto|v1|v2]`: MADS export format version.
  * **Legacy compatibility options (preserved):** `--instrument PART=INSTRUMENT_ID` (`Lead Library v0.1`), `--instrument-library DIRECTORY`, `--sound-bank DIRECTORY`, `--profile-bindings FILE`.

```bash
python -m atari_music build-xex examples/songs/Vaults-of-Nhyrmeth.dsl --format dsl -o vaults.xex
```

---

### Additional Supporting Commands (`import-json`, `import-dsl`, `analyze`)

* **`import-json COMPOSITION_JSON`**: Validate an `AICompositionDoc` JSON document and export `--output-wav`, `--output-asm`, and/or `--output-ir` (supports `--player-version`, `--instrument`, `--sound-bank`, `--profile-bindings`).
* **`import-dsl COMPOSITION_DSL`**: Validate a Music DSL file and convert it to canonical `--output-json`, POKEY IR (`--output-ir`), `--output-wav`, and/or `--output-asm` (supports `--player-version`, `--instrument`, `--sound-bank`, `--profile-bindings`).
* **`analyze COMPOSITION_JSON`**: Compute musical metrics (rhythm, melody, harmony), POKEY hardware utilization, duration, SHA-256 fingerprint, and macro-structure (`-s, --structure`, `--json`, `-o, --output-json`).

```bash
# Convert Music DSL into canonical JSON, WAV, and MADS ASM
python -m atari_music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl \
  --output-json vaults.json --output-wav vaults.wav --output-asm vaults.asm

# Structural and hardware report
python -m atari_music analyze examples/ai/dungeon_dark.json --structure
```

---

## Composition Formats

Atari Music Composer uses three distinct representations across its pipeline:

1. **Canonical AI Composition JSON (`AICompositionDoc` v1, `"format": "atari-music-composition"`)**:
   - The Single Source of Truth schema (`src/atari_music/ai/schema.py`) containing `metadata`, `hardware` (`channels`, `use_16bit_bass`), `instruments` (semantic `character` plus optional `catalog_id` / envelope fields), `patterns` (monophonic step events per channel `"0".."3"` or `"1".."4"`), `sequence`, and `loop_point`.
2. **POKEY IR JSON (`IRSong`)**:
   - Hardware-compiled intermediate representation (`src/atari_music/ir.py`) emitted by `compose --output-json`, `import-json --output-ir`, `import-dsl --output-ir`, `ai-compose --output-ir`, and `arrange --output-json`. Stores hardware divider parameters, resolved `IRInstrument` tables (v1 envelopes/modulation or v2 transient macros & pitch envelopes), `initial_channel_instruments`, and per-note `pending_program_changes`.
3. **Music DSL (`.dsl`)**:
   - Compact, line-oriented plain-text representation designed to minimize LLM token usage while mapping losslessly into `AICompositionDoc`. Measured at **49.4% fewer LLM tokens** than JSON in empirical 100-trial runs (`benchmark_results/run_1790692314/report.md`, and ~83% fewer raw tokenizer tokens on static examples in [docs/music_dsl.md](docs/music_dsl.md)).

### How Music DSL Differs from JSON

* **Syntax & size:** Plain directives and whitespace-separated note tokens (`PITCH/DURATION[:VOL]`) instead of nested JSON objects per note.
* **Lossless compiler:** `parse_music_dsl()` ([src/atari_music/ai/dsl.py](src/atari_music/ai/dsl.py)) compiles `.dsl` directly into `AICompositionDoc` (reporting exact line/column `DSLSyntaxError` messages) and runs the same 3-tier validator. `export_music_dsl()` serializes `AICompositionDoc` back to `.dsl`.
* **Current DSL v1 scope limits:** DSL syntax supports header directives (`TITLE`, `AUTHOR`, `KEY`, `MODE`, `BPM`, `CHANNELS`, `BASS 16BIT`, `LOOP`, `SEQUENCE`), `INSTRUMENT <id> character=<role> [dist=$XX] [att=N] [dec=N] [sus=N] [rel=N] [name="..."]`, `[PATTERN <id> length=N role=...]`, `CH1..CH4 <inst> V<vol>`, `<pitch>/<dur>[:<vol>]`, and rests (`R/<dur>` or `-/<dur>`). Comments start with `#` (keeping `#` inside pitches such as `C#4/4`). DSL does not natively encode Stage C/D `catalog_id` fields or `PROGRAM_CHANGE` events.

### Generating, Loading, and Using DSL with `arrange`

* **Generate a `.dsl` composition:** `python -m atari_music ai-compose --format dsl -o song.dsl` (or Python `export_music_dsl(doc)`).
* **Load and process an existing `.dsl`:** `import-dsl song.dsl ...` or `build-xex song.dsl --format dsl ...` (or Python `load_composition_dsl()` / `generate_music_from_dsl()`).
* **Can `.dsl` be passed directly to `arrange`?** **No.** Verified in `src/atari_music/api.py` (`_load_song_input_for_arrange()`), `arrange` parses **JSON only** (`AICompositionDoc` JSON or `IRSong` JSON). Convert `.dsl` to JSON first:
  ```bash
  python -m atari_music import-dsl song.dsl --output-json song.json
  python -m atari_music arrange song.json --channel-instrument 3=lead_attack_bite --output-wav out.wav -o out.xex
  ```

### Realistic Music DSL Example

Excerpt adapted from [examples/songs/Vaults-of-Nhyrmeth.dsl](examples/songs/Vaults-of-Nhyrmeth.dsl):

```dsl
TITLE "Vaults of Nhyrmeth"
AUTHOR "POKEY Composer"
KEY D
MODE MINOR
BPM 90
BASS 16BIT

SEQUENCE A1 B1 A1

INSTRUMENT bass character=bass
INSTRUMENT lead character=bright_lead
INSTRUMENT perc character=percussion

[PATTERN A1 length=16]
CH1 bass V13
D2/4 D2/2 D2/2 D2/4 F2/4
CH3 lead V14
D4/6 E4/2 F4/4 G4/4
CH4 perc V11
C3/2 R/2 C4/2 R/2 C3/2 C3/2 C4/2 R/2
```

When `BASS 16BIT` is active, POKEY joins `CH1` (master) and `CH2` (slave divider) via `AUDCTL=$10`; `CH2` must remain empty or validation rejects with `BASS16_CHANNEL_CONFLICT`.

---

## Instrument System

Stages A–E introduced an opt-in, hardware-validated instrument architecture layered cleanly alongside legacy rendering.

### SSOT Catalog (`data/instruments/catalog.json`)

Validated by [src/atari_music/instruments/catalog.py](src/atari_music/instruments/catalog.py) (`atari-music/instrument-catalog/1`, catalog `0.1.0`), the SSOT catalog currently holds **16 curated instrument profiles** and **10 behaviors**:

* **8 `core_v1` profiles (`[OK]` on `xex_v1`, `xex_v2`, and `wav`):** Static ADSR or `octave_pulse` modulation — `lead_pure_sustain`, `lead_pure_pluck`, `lead_c1_octave_pulse`, `lead_buzz_steady`, `bass_16bit_pure`, `bass_15khz_pure`, `bass_16bit_poly5_growl`, `harmony_soft_square`.
* **6 `core_v2_iter1` profiles (`[OK]` on `xex_v2`, rendered in WAV via v2 frame simulation):** Multi-step 50 Hz transient macros and pitch envelopes — `lead_attack_bite`, `bass_poly4_punch`, `perc_kick_tight`, `perc_snare_crisp`, `perc_hihat_closed`, `perc_tom_pitched`.
* **2 `experimental_deferred` profiles (`[DEFERRED_FEATURE]` across targets):** `lead_hpf_pwm` (HPF XOR PWM) and `ornament_bell_arp` (arpeggio ornament), kept explicitly out of stable export until a later v2 iteration.

### Listing, Inspecting, and Validating Instruments

```bash
python -m atari_music list-instruments --target xex_v2
python -m atari_music inspect-instrument perc_kick_tight
python -m atari_music validate-instruments
```

### Channel Assignment, Program Changes, and Player Versions

* **Channel & role assignment (`--channel-instrument CH=INSTRUMENT_ID`):** Maps channel numbers `1..4` or case-insensitive role aliases (`bass`->1; `harmony`/`counter`/`pad`->2; `lead`/`melody`->3; `perc`/`percussion`/`drums`/`rhythm`->4). `POKEYRuntime` (`src/atari_music/instruments/runtime.py`) enforces `channels_allowed`, clock compatibility (`64khz`, `15khz`, `1.79mhz`), 16-bit pair locks (`16bit_ch12`, `16bit_ch34`), and target tiers without silent fallbacks.
* **Mid-song switches (`PROGRAM_CHANGE`):** `compose --program-change CH@TARGET[:NOTE]=INSTRUMENT_ID` (and catalog-enabled `ai-compose --use-instrument-catalog`) emits 0-tick `PROGRAM_CHANGE` opcodes (`$01`) supported by `SONG_FORMAT_VERSION = 2`.
* **Player version selection (`--player-version [auto|v1|v2]`):**
  * `auto` (default): keeps `SONG_FORMAT_VERSION = 1` whenever v1 covers the song (`<= 4` channel instruments, no active v2 macros, pitch envelopes, or `PROGRAM_CHANGE` events), switching to `2` only when required.
  * `v1`: strictly exports Format v1 and raises `FormatVersionError` if v2 features are present.
  * `v2`: explicitly exports Format v2.

### Creating vs Re-arranging a Composition

| Aspect | Composition (`compose` / `ai-compose`) | Arrangement (`arrange`) |
|---|---|---|
| Who chooses notes, durations, tempo, patterns, sequence? | Procedural engine or AI LLM | **Preserved verbatim** (read-only; never modified) |
| Calls AI provider? | Yes (`ai-compose` unless `--provider mock`) | **Never** (offline, deterministic) |
| Modifies channel instrumentation / `PROGRAM_CHANGE` policy? | Initial defaults + optional flags | **Primary purpose** (`--channel-instrument`, `--program-change-policy`) |
| Input format | Prompts / CLI parameters | Saved `AICompositionDoc` JSON or `IRSong` JSON |

### Backward Compatibility

Existing songs without `--channel-instrument` or `--use-instrument-catalog` behave identically to pre-Stage-A releases and continue exporting `SONG_FORMAT_VERSION = 1`. Legacy sound profile banks (`--sound-bank` / `--profile-bindings` documented in [docs/profile_integration.md](docs/profile_integration.md)) and Lead Library v0.1 (`--instrument PART=ID` on `import-json`, `import-dsl`, `build-xex`) remain functional.

---

## Arrangement Workflow

The Stage E arrangement workflow lets you compose once with AI (or procedurally), save the composition as JSON, and iterate quickly on POKEY instrumentation while comparing WAV and XEX outputs with zero additional AI calls:

1. **Generate or obtain one composition** (`ai-compose`, `compose`, or `import-dsl`).
2. **Save it as JSON** (`composition.json` or POKEY IR JSON).
3. **Create multiple arrangements** using `atari-music arrange` with different `--channel-instrument` assignments.
4. **Export each arrangement** directly to `--output-json`, `--output-wav`, `--output-asm`, and/or `-o / --output-xex`.
5. **Compare results cleanly**: `composition.json` is never modified, and every arranged output shares the identical `composition_musical_fingerprint()` over all notes, rests, durations, volumes, tempo, patterns, and sequence.

### Handling Existing Switch Events (`--program-change-policy`)

On channels **not** overridden by `--channel-instrument`, existing instruments and `PROGRAM_CHANGE` events remain untouched. On overridden channels:

* `preserve` *(default)*: Replaces notes using the channel's initial instrument while keeping secondary instruments and `PROGRAM_CHANGE` transitions intact.
* `replace`: Reassigns all notes on the overridden channel to the new instrument and rewrites existing `PROGRAM_CHANGE` switch targets on that channel to the new instrument.
* `remove`: Reassigns all notes on the overridden channel to the new instrument and strips all `PROGRAM_CHANGE` events on that channel.

### Verified Multi-Variant Examples

#### Example 1: Compose once (AI/Mock JSON) -> Arrange twice to WAV + XEX

```bash
# Step 1: Generate the source composition JSON ONCE
python -m atari_music ai-compose --provider mock --use-instrument-catalog \
  --style "dark dungeon exploration" --duration 20 -o output/source_composition.json

# Step 2a: Variant A — 15 kHz square bass + tight kick + bite lead (leaves original untouched)
python -m atari_music arrange output/source_composition.json \
  --channel-instrument 1=bass_15khz_pure \
  --channel-instrument 2=harmony_soft_square \
  --channel-instrument 3=lead_attack_bite \
  --channel-instrument 4=perc_kick_tight \
  --program-change-policy replace \
  --output-json output/variant_a_ir.json \
  --output-wav output/variant_a.wav \
  -o output/variant_a.xex

# Step 2b: Variant B — Poly4 gritty bass + crisp snare + pure sustain lead (zero AI calls)
python -m atari_music arrange output/source_composition.json \
  --channel-instrument 1=bass_poly4_punch \
  --channel-instrument 2=harmony_soft_square \
  --channel-instrument 3=lead_pure_sustain \
  --channel-instrument 4=perc_snare_crisp \
  --program-change-policy replace \
  --output-json output/variant_b_ir.json \
  --output-wav output/variant_b.wav \
  -o output/variant_b.xex
```

#### Example 2: Arrange an existing Music DSL song by converting to JSON first

```bash
# Step 1: Convert Music DSL to canonical JSON without altering notes
python -m atari_music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl --output-json output/vaults.json

# Step 2: Re-arrange CH1 (16-bit pure bass) and CH4 (pitched tom) -> WAV + ASM + XEX
# (Note: CH2 stays unassigned because BASS 16BIT pairs CH1+CH2)
python -m atari_music arrange output/vaults.json \
  --channel-instrument 1=bass_16bit_pure \
  --channel-instrument 3=lead_pure_pluck \
  --channel-instrument 4=perc_tom_pitched \
  --program-change-policy remove \
  --output-wav output/vaults_pluck.wav \
  --output-asm output/vaults_pluck.asm \
  -o output/vaults_pluck.xex
```

### Automated Suite Runner (`scripts/generate_instrument_test_suite.py`)

For batch validation against a real `.env` AI provider (`openai` or `deepseek`), [scripts/generate_instrument_test_suite.py](scripts/generate_instrument_test_suite.py) generates 4 styles (`dark`, `action`, `mystery`, `experimental`) once each and renders 3 curated arrangements per style (12 WAV + 12 XEX + `manifest.json`) with musical fingerprint checks:

```bash
# Preview planned commands without invoking subprocesses or touching disk
python scripts/generate_instrument_test_suite.py --dry-run

# Run full suite (requires real provider in .env; refuses overwriting without --force)
python scripts/generate_instrument_test_suite.py --output-dir output/instrument_tests
```

### Smart Batch Arrangement Runner (`generate_arrangements.py`)

For arranging any single `.dsl` or JSON composition (`AICompositionDoc` or POKEY IR `IRSong`), [generate_arrangements.py](generate_arrangements.py) replaces the legacy 8-bit/16-bit PowerShell wrappers with one adaptive Python pipeline:

1. Queries `atari-music.exe list-instruments --target xex_v2 --json` for compatible SSOT catalog instruments.
2. Converts `.dsl` inputs automatically via `atari-music.exe import-dsl` into a temporary JSON file.
3. Detects 16-bit (`CH1+CH2` joined) vs. 8-bit bass and analyzes each active channel's role (`bass`, `melody`, `harmony`, `percussion`), MIDI span, note duration, short-note ratio, and pitch diversity.
4. Scores and ranks compatible instrument combinations (generating numbered `01_...`..`06_...` `v2` variants plus the `v1` `vanilla` baseline) into `.wav` and `.xex` outputs, and records full scoring rationale and executed commands in `arrangements.log`:

```bash
# Preview matched channels, candidate scores, and planned outputs without rendering
python generate_arrangements.py -i examples/songs/wybierak-2.dsl -o output/wybierak2 --dry-run

# Render ranked arrangements (.wav + .xex) + arrangements.log
python generate_arrangements.py -i examples/songs/wybierak-2.dsl -o output/wybierak2 -m tools/mads/mads.exe
```

---

## Export and Atari Playback

### WAV Synthesis (`pokey_synth.py` / `pokey_hw.py`)

* Renders 50 Hz PAL POKEY register frames directly to 16-bit PCM mono 44.1 kHz `.wav` using the non-linear POKEY resistor-ladder DAC (`POKEY_DAC`), hardware-accurate `POLY4` (15-step, including modulo-3/5 stalls), `POLY5` (31-step XNOR gate), `POLY9` (511-step), and `POLY17` (131071-step) LFSRs, digital HPF XOR latches (`AUDCTL $02` CH2-by-CH4 and `$04` CH1-by-CH3), and 16-bit channel joining (`$10` CH1+CH2, `$08` CH3+CH4).
* Songs using v2 features (`song_requires_v2()`) automatically render through `simulate_ir_song_frames(..., format_version=2)` so WAV previews reflect transient macros, pitch envelopes, and `PROGRAM_CHANGE` transitions accurately.

### MADS Export & Player Versions (`mads_exporter.py` & `player.asm`)

* Exports Structure-of-Arrays (SoA) data tables for MOS 6502 indexing (`LDA table,X`).
* **Format v1 (`SONG_FORMAT_VERSION = 1`)**: Default format; 6-byte static channel instrument records supporting ADSR envelopes and `MOD_OCTAVE_PULSE`.
* **Format v2 (`SONG_FORMAT_VERSION_V2 = 2`)**: Supports up to `32` instruments (`MAX_V2_INSTRUMENTS = 32`), deduplicated shared macro directory (`1..8` steps of 4 bytes per step), signed 8-bit pitch envelopes, `CH1..CH4` initial assignment, and 4-byte `OPCODE_PROGRAM_CHANGE` (`$00, $00, $01, inst_idx`) events. See full binary specification in [docs/SONG_FORMAT_V2.md](docs/SONG_FORMAT_V2.md).

### Atari XEX Binaries & Enforced Hardware Constraints

* Compiled via MADS into standalone executables featuring PAL 50 Hz `RTCLOK` (`$14`) sync, ANTIC Mode 2 real-time clock + 4-channel horizontal VU display, and keyboard mute/resume toggle (`CH` `$02FC`).
* **Relocatability:** User addresses default to `--player-address 0x6000`, `--music-address 0x8000`, and `--zp-base 0x80`. The player reserves 10 Zero Page bytes (`PLAYER_ZP_BASE + 0..9`, `$80..$89` by default, keeping screen display pointers at `$8A..$8D` separate).
* **CPU instruction set:** Official MOS 6502 opcodes only (no 65C02/65816 instructions).
* **Hard size and layout enforcement ([src/atari_music/xex_layout.py](src/atari_music/xex_layout.py), [docs/xex_memory_layout.md](docs/xex_memory_layout.md)):**
  * **Player budget limit (`< 2048 bytes`):** Measured via `atari_music.stage15.measure_player_size` (`src/atari_music/asm/player.asm`, code + BSS state) at **1785 bytes** (`263 bytes` headroom under `2048 B`). The complete `.xex` file itself has no 2 KB cap.
  * **Memory segment bounds:** All user load segments must lie strictly within **`$0400–$BFFF`** (`$A000–$BFFF` allowed intentionally; OS kernel `$C000–$CFFF`, hardware I/O `$D000–$DFFF`, OS ROM `$E000–$FFFF`, Zero Page, stack, and OS vectors are forbidden).
  * **Disjoint segments:** Overlapping XEX segments are rejected immediately (`xex_layout.validate_xex_file`).

Pre-built v1 listening demos remain available in [stage11_xex/](stage11_xex/) (see [stage11_xex/README.md](stage11_xex/README.md) and [stage11_xex/memory_map.md](stage11_xex/memory_map.md)).

---

## Architecture and Development

### Core Module Overview

```text
src/atari_music/
├── api.py                   # Public facade: generate_music(), arrange_song(), MusicGenerationResult
├── cli.py                   # Click CLI entrypoint (atari-music / python -m atari_music)
├── config.py                # 4-tier .env / env / CLI config resolution & secret masking
├── composer_v4.py           # Procedural 4-channel Composer v4 (profiles, counterpoint, bass, rhythm)
├── music_ir.py              # Symbolic Music IR (MusicSong)
├── ir.py                    # Hardware POKEY IR (IRSong), v1/v2 frame sizing & stream planning
├── frame_simulator.py       # Python frame oracle implementing v1 & v2 50 Hz state machines
├── pokey_hw.py              # Hardware-exact POKEY LFSRs, clocks & envelope state machine
├── pokey_synth.py           # 44.1 kHz WAV renderer (LFSRs, HPF XOR, 16-bit joining, DAC)
├── mads_exporter.py         # Relocatable SoA MADS exporter (Format v1 & Format v2 + validator)
├── xex_layout.py            # XEX parser and $0400-$BFFF disjoint segment layout verifier
├── asm/player.asm           # Relocatable MOS 6502 player (v1 + v2 macro & pitch engines)
├── instruments/             # Stage A-E SSOT instrument architecture
│   ├── models.py            # Pydantic v2 InstrumentProfile, InstrumentBehavior, HardwareConstraints
│   ├── catalog.py           # InstrumentCatalog loader & integrity validator (data/instruments/catalog.json)
│   ├── runtime.py           # Stateless POKEYRuntime capability & AUDCTL conflict checker
│   └── planner.py           # Channel assignment, PROGRAM_CHANGE policy, v1/v2 resolution, arrange_ir_song
├── ai/                      # AI composition & analysis layer
│   ├── schema.py            # AICompositionDoc v1 schema & ValidationReport
│   ├── dsl.py               # Lossless Music DSL parser & serializer
│   ├── validation.py        # 3-tier validator (schema, musical rules, hardware constraints)
│   ├── composition.py       # AICompositionDoc -> MusicSong / IRSong compiler
│   ├── client.py            # AI retry/repair loop, composition loaders & build_xex_from_result()
│   ├── analysis.py          # Musical/hardware metrics & SHA-256 composition_fingerprint()
│   ├── structure_analysis.py# Repetition ratio, motif reuse & formal structure deduction
│   └── providers/           # MockAICompositionProvider & OpenAICompositionProvider
└── sound_profiles/          # Legacy/research Stage 9 SoundProfileBank & binding loader
```

### Python API Example (Compose, Arrange, and Build XEX)

```python
from atari_music.api import arrange_song, generate_music

# 1. Procedural v1 generation
song = generate_music(profile="dungeon", seed=501, length="short")
song.render_wav("output/dungeon_v1.wav")

# 2. Re-arrange with SSOT catalog instruments (returns new result; leaves original intact)
arranged = arrange_song(
    song,
    channel_instruments={
        1: "bass_16bit_pure",
        3: "lead_attack_bite",
        4: "perc_kick_tight",
    },
    program_change_policy="replace",
)
arranged.render_wav("output/dungeon_v2.wav")
arranged.build_xex("output/dungeon_v2.xex")
```

### Development & Test Suites

Tests in `tests/` follow strict marker classification verified by `scripts/verify_test_classification.py` (`core`, `audio`, `experimental`, `legacy`, `live`). By default (`pyproject.toml`), `pytest` excludes `live` tests (`addopts = "--strict-markers -m 'not live'"`).

```bash
# Verify test marker classification integrity
python scripts/verify_test_classification.py

# Run all offline CORE production tests (architecture boundaries, IR, exporters, py65, CLI)
pytest -m "core and not live" -q

# Run fast POKEY / IR / MADS / player.asm / XEX regression subset
pytest -m "audio and not live" -q

# Stage C/D/E + test suite generator tests specifically
pytest tests/test_stage_c_player_v2_parity.py tests/test_stage_d_integration.py tests/test_stage_e_arrangement.py tests/test_generate_instrument_test_suite.py -v
```

---

## Related Documentation

* [docs/SONG_FORMAT_V2.md](docs/SONG_FORMAT_V2.md) — Stage C binary & MADS `SONG_FORMAT_VERSION = 2` specification and measured 6502 player resource/cycle profile
* [docs/music_dsl.md](docs/music_dsl.md) — Formal EBNF grammar, semantics, and benchmarks for Music DSL
* [docs/xex_memory_layout.md](docs/xex_memory_layout.md) — XEX container parsing, `$0400–$BFFF` memory bounds, and `< 2048 B` player rule
* [docs/profile_integration.md](docs/profile_integration.md) — External POKEY Sound Archaeology profile binding (`--sound-bank` / `--profile-bindings`)
* [docs/instrument_selection_cli.md](docs/instrument_selection_cli.md) — Legacy Lead Library v0.1 (`--instrument PART=ID`) specification
* [docs/stage14_final_synthesis.md](docs/stage14_final_synthesis.md) — Research synthesis motivating curated instrument catalogs and macros
* [STAGE3_INSTRUMENT_DESIGN.md](STAGE3_INSTRUMENT_DESIGN.md) — Architecture design specification for the Stage A–E Instrument System
* [HISTORY.md](HISTORY.md) — Detailed technical changelog across stages

# CLI Reference

Run commands either via the installed entry point `atari-music` or via module invocation
`python -m atari_music`. All examples use the module form so they work on any platform without a
`Scripts/` directory on `PATH`.

## Global options

```text
python -m atari_music [OPTIONS] COMMAND [ARGS]...
```

| Option | Meaning |
| --- | --- |
| `-v, --version` | Show package version and exit |
| `--env-file FILE` | Path to custom `.env` configuration file (default `.env`) |
| `--log-level [debug\|info\|warning\|error\|critical]` | Override log level |
| `--help` | List all commands (research/legacy subcommands included) |

## `compose`

Generate procedural 4-channel POKEY music via the public Music Generation API (Composer v4).

| Option | Meaning |
| --- | --- |
| `-p, --profile TEXT` | Stylistic profile: `title`, `exploration`, `action`, `funny`, `dungeon`, `ending` |
| `-s, --seed INTEGER` | Deterministic RNG seed |
| `-k, --key TEXT` | Root key (`C`, `D`, `E`, `F`, `G`, `A`, `B`) |
| `-t, --tempo INTEGER` | Tempo in BPM (`50..240`) |
| `-l, --length [short\|medium\|long]` | Duration intent |
| `--intensity FLOAT` | Expected intensity (0.0–1.0) |
| `-v, --variation FLOAT` | Motivic variation level (0.0–1.0) |
| `--channel-instrument CH=ID` | Assign SSOT catalog instrument to channel or role (repeatable) |
| `--program-change CH@TARGET[:NOTE]=ID` | Schedule mid-song `PROGRAM_CHANGE` |
| `--instrument-catalog FILE` | Catalog path (default `src/atari_music/instruments/catalog.json`) |
| `--player-version [auto\|v1\|v2]` | Target player format version (default `auto`) |
| `--output-json PATH` | POKEY IR JSON output |
| `--output-wav PATH` | 44.1 kHz WAV output |
| `--output-asm PATH` | MADS assembly output |

```bash
python -m atari_music compose --profile title --seed 101 --output-json title_ir.json --output-wav title.wav
```

## `ai-compose`

Generate a valid AI composition (JSON or Music DSL) using an AI provider — full description in
[AI-Assisted Composition](../user-guide/ai-composition.md).

| Option group | Options |
| --- | --- |
| Musical intent | `--style`, `-m, --mood` (repeatable), `--duration`, `--bpm`, `--key`, `--mode`, `--notes`, `--structure` |
| Hardware | `--channels`, `--use-16bit-bass / --no-16bit-bass` |
| Format & outputs | `--format [json\|dsl]`, `-o/--output` (omitted or `-` writes to stdout), `--output-ir`, `--output-asm`, `--output-wav` |
| Prompting | `--prompt-profile [classic\|rich]`, `--tempo-grid [describe\|exact]`, `--temperature`, `--plan-first/--no-plan-first`, `--rhythmic-density [low\|medium\|high\|extreme]`, `--quality-passes` |
| Robustness | `--max-retries` (validation repair attempts, default 3) |
| Instruments | `--channel-instrument CH=ID`, `--use-instrument-catalog/--no-use-instrument-catalog`, `--instrument-catalog FILE`, `--player-version [auto\|v1\|v2]` |
| Provider & config | `--provider [mock\|openai\|deepseek]`, `--model`, `--env-file`, `--log-level` |

```bash
python -m atari_music ai-compose --provider mock --style "dark dungeon exploration" -m dark \
  --duration 24 -o composition.json
```

## `arrange`

Re-arrange an existing **JSON** composition (`AICompositionDoc` or POKEY IR `IRSong`) with new POKEY
channel instruments without calling AI — full description in [Arrangement](../user-guide/arrangement.md).

| Option | Meaning |
| --- | --- |
| `INPUT_COMPOSITION` (argument) | Existing composition JSON (`.dsl` inputs must be converted with `import-dsl` first) |
| `--channel-instrument CH=ID` | Repeatable channel (1–4) or role assignment |
| `--program-change-policy [preserve\|replace\|remove]` | Existing `PROGRAM_CHANGE` handling on overridden channels (default `preserve`) |
| `--instrument-catalog FILE` | Catalog path |
| `--player-version [auto\|v1\|v2]` | Format target for MADS/XEX output (default `auto`) |
| `--output-json`, `--output-ir PATH` | Arranged POKEY IR JSON |
| `--output-wav PATH` | WAV render |
| `--output-asm PATH` | MADS assembly |
| `-o, --output-xex PATH` | Atari XEX binary |
| `--player-address`, `--music-address`, `--zp-base`, `--mads`, `--player-asm` | XEX relocation/toolchain options (defaults `0x6000`, `0x8000`, `0x80`) |

```bash
python -m atari_music arrange examples/ai/dungeon_dark.json \
  --channel-instrument 1=bass_16bit_pure \
  --channel-instrument 3=lead_attack_bite \
  --program-change-policy replace \
  --output-json output/arranged_ir.json --output-wav output/arranged.wav -o output/arranged.xex
```

## `list-instruments`

List curated SSOT catalog instruments along with compatibility for a chosen target backend.

| Option | Meaning |
| --- | --- |
| `--instrument-catalog`, `--catalog FILE` | Catalog path (default `src/atari_music/instruments/catalog.json`) |
| `--family [lead\|bass\|pad\|harmony\|percussion\|fx]` | Filter by family |
| `--role [melody\|bass\|harmony\|rhythm\|percussion]` | Filter by intended role |
| `--target [xex_v2\|xex_v1\|wav]` | Target compatibility report (default `xex_v2`) |
| `--json` | Emit machine-readable JSON |

```bash
python -m atari_music list-instruments --target xex_v2 --family bass
```

## `inspect-instrument`

Display complete hardware constraints, ADSR envelope, `runtime_tier`, behavior (transient macro /
pitch envelope / modulation), provenance, and target compatibility (`xex_v1`, `xex_v2`, `wav`) for one
instrument.

| Option | Meaning |
| --- | --- |
| `INSTRUMENT_ID` (argument) | Catalog instrument id |
| `--instrument-catalog`, `--catalog FILE` | Catalog path |
| `--json` | Machine-readable JSON |

```bash
python -m atari_music inspect-instrument lead_attack_bite
```

## `validate-instruments`

Validate the catalog JSON schema (`atari-music/instrument-catalog/1`), cross-field hardware rules
(`divider_mode` vs `required_audctl_bits`, macro limits), behavior links, and provenance.

| Option | Meaning |
| --- | --- |
| `--instrument-catalog`, `--catalog FILE` | Catalog path |

```bash
python -m atari_music validate-instruments
```

## `export-mads`

Convert an existing **POKEY IR JSON** (`IRSong`) directly into relocatable MADS assembly data. Note:
for `AICompositionDoc` JSON use `import-json` or `arrange` instead.

| Option | Meaning |
| --- | --- |
| `INPUT_JSON` (argument) | POKEY IR JSON |
| `-o, --output-asm PATH` (required) | Destination `.asm` path |
| `--player-version`, `--format-version [auto\|v1\|v2]` | Target MADS format (`auto` preserves v1 when sufficient) |

```bash
python -m atari_music compose --profile title --seed 101 --output-json title_ir.json
python -m atari_music export-mads title_ir.json -o title_data.asm --format-version auto
```

## `build-xex`

Compile an AI composition (**JSON or Music DSL**) directly into a relocatable standalone Atari `.xex`
executable with the interactive playback screen (ANTIC Mode 2 time display, 4-channel VU meters,
key mute toggle).

| Option | Meaning |
| --- | --- |
| `COMPOSITION_FILE` (argument) | Input composition (`.json` or `.dsl`) |
| `-o, --output PATH` | Output `.xex` path |
| `--format [json\|dsl]` | Input format (default `json`, or inferred from `.dsl` extension) |
| `--player-address TEXT` | Relocatable player address (default `0x6000`) |
| `--music-address TEXT` | Relocatable music data address (default `0x8000`) |
| `--zp-base TEXT` | Zero-page base address (default `0x80`, reserves `$80..$89`) |
| `--mads PATH` | Path to `mads.exe` |
| `--player-asm PATH` | Explicit path to `player.asm` (defaults to current dir or repository root) |
| `--player-version [auto\|v1\|v2]` | MADS export format version |
| `--sound-bank DIRECTORY` | Legacy: POKEY sound profile bank (`registry.json` + `profiles/`) |
| `--profile-bindings FILE` | Legacy: composition-instrument → profile-id binding |
| `--instrument PART=INSTRUMENT_ID` | Legacy: Lead Library assignment (repeatable) |
| `--instrument-library DIRECTORY` | Legacy Lead Library directory (default `data/instrument_libraries/lead/v0.1`) |

```bash
python -m atari_music build-xex examples/songs/Vaults-of-Nhyrmeth.dsl --format dsl -o vaults.xex
```

## `import-json` / `import-dsl`

Validate an existing composition and convert/render it:

* **`import-json COMPOSITION_JSON`** — validate an `AICompositionDoc` JSON and export
  `--output-wav`, `--output-asm`, and/or `--output-ir` (supports `--player-version`, `--instrument`,
  `--sound-bank`, `--profile-bindings`).
* **`import-dsl COMPOSITION_DSL`** — validate a Music DSL file and convert it to canonical
  `--output-json`, POKEY IR (`--output-ir`), `--output-wav`, and/or `--output-asm` (same legacy options).

```bash
# Convert Music DSL into canonical JSON, WAV, and MADS ASM in one step
python -m atari_music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl \
  --output-json vaults.json --output-wav vaults.wav --output-asm vaults_data.asm

# Structural and hardware report with deduced form
python -m atari_music analyze examples/ai/dungeon_dark.json --structure
```

## `analyze`

Compute musical metrics (rhythm, melody, harmony), POKEY hardware utilization, duration, SHA-256
fingerprint, and macro-structure.

| Option | Meaning |
| --- | --- |
| `COMPOSITION_JSON` (argument) | Input composition JSON |
| `-s, --structure` | Add repetition ratio, motif reuse, and deduced form |
| `--json` | Emit machine-readable JSON |
| `-o, --output-json PATH` | Write the JSON report to a file |

## Research & experimental commands

The remaining commands visible in `atari-music --help` — `prepare-listening-test-9c`,
`analyze-listening-test-9c/9d/9e`, `prepare-rebinding-10a`, `prepare-volume-contour-10b`,
`analyze-volume-contour-10b`, `run-stage11b`, `synthesize-stage11a`, `run-stage12a`,
`run-stage13a`, `synthesize-stage14`, `prepare-stage12a-listening`,
`prepare-stage13a-listening`, and `analyze-stage15` … `analyze-stage25` — are **experimental research
tooling** belonging to the [research programme](../research/index.md). They depend on locally generated
research datasets and are deliberately not part of the production pipeline; their flags are documented
in the corresponding research documents rather than here.


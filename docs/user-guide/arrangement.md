# Arrangement

Arrangement is the project's *composition-free* sound-design loop: re-assign the POKEY instruments of an
existing composition, render it, and listen — as many times as you like. Its two hard guarantees are:

1. **The musical content is preserved verbatim.** Notes, rests, durations, volumes, tempo, patterns,
   and sequence are read-only for `arrange`. Every arrangement of a composition shares the identical
   `composition_musical_fingerprint()`, so you can compare variants meaningfully.
2. **Zero AI calls.** Arrangement is offline and deterministic, which makes iterating on instrumentation
   essentially free.

## Command reference

```text
python -m atari_music arrange [OPTIONS] INPUT_COMPOSITION
```

| Option | Meaning |
| --- | --- |
| `INPUT_COMPOSITION` (argument) | `AICompositionDoc` JSON or POKEY IR (`IRSong`) JSON. Not `.dsl` — convert first (see below) |
| `--channel-instrument CH=ID` | Repeatable channel (1–4) or role-alias assignment; unassigned channels keep their current realization |
| `--program-change-policy [preserve\|replace\|remove]` | Handling of existing `PROGRAM_CHANGE` events on overridden channels (default `preserve`) |
| `--instrument-catalog FILE` | Catalog path (default `src/atari_music/instruments/catalog.json`) |
| `--player-version [auto\|v1\|v2]` | Target format for MADS/XEX output (default `auto`) |
| `--output-json` / `--output-ir PATH` | Output arranged POKEY IR JSON |
| `--output-wav PATH` | Render 44.1 kHz WAV |
| `--output-asm PATH` | Export MADS assembly |
| `-o, --output-xex PATH` | Compile a standalone Atari XEX binary |
| `--player-address`, `--music-address`, `--zp-base`, `--mads`, `--player-asm` | XEX compilation options (defaults `0x6000`, `0x8000`, `0x80`, MADS lookup, bundled `player.asm`) |

The input file is never modified.

| Aspect | Composition (`compose` / `ai-compose`) | Arrangement (`arrange`) |
| --- | --- | --- |
| Who chooses notes, durations, tempo, patterns, sequence? | Procedural engine or AI LLM | **Preserved verbatim** (read-only) |
| Calls the AI provider? | Yes (`ai-compose`, unless `--provider mock`) | **Never** (offline, deterministic) |
| Modifies channel instrumentation / `PROGRAM_CHANGE` policy? | Initial defaults + optional flags | **Primary purpose** |
| Input format | Prompts / CLI parameters | Saved `AICompositionDoc` or `IRSong` JSON |

## `--program-change-policy` in detail

On channels **not** overridden by `--channel-instrument`, existing instruments and `PROGRAM_CHANGE`
events remain untouched. On overridden channels:

* **`preserve` (default)** — replaces notes using the channel's initial instrument while keeping
  secondary instruments and `PROGRAM_CHANGE` transitions intact.
* **`replace`** — reassigns all notes on the channel to the new instrument and rewrites existing
  `PROGRAM_CHANGE` switch targets to the new instrument.
* **`remove`** — reassigns all notes on the channel to the new instrument and strips all
  `PROGRAM_CHANGE` events on that channel.

## Worked examples

### Compose once, arrange twice

```bash
# Step 1: generate the source composition JSON ONCE (mock provider, catalog-aware)
python -m atari_music ai-compose --provider mock --use-instrument-catalog \
  --style "dark dungeon exploration" --duration 20 -o output/source_composition.json

# Step 2a: Variant A — 15 kHz square bass + tight kick + bite lead
python -m atari_music arrange output/source_composition.json \
  --channel-instrument 1=bass_15khz_pure \
  --channel-instrument 2=harmony_soft_square \
  --channel-instrument 3=lead_attack_bite \
  --channel-instrument 4=perc_kick_tight \
  --program-change-policy replace \
  --output-json output/variant_a_ir.json --output-wav output/variant_a.wav -o output/variant_a.xex

# Step 2b: Variant B — poly4 bass + crisp snare + pure sustain lead (zero AI calls)
python -m atari_music arrange output/source_composition.json \
  --channel-instrument 1=bass_poly4_punch \
  --channel-instrument 2=harmony_soft_square \
  --channel-instrument 3=lead_pure_sustain \
  --channel-instrument 4=perc_snare_crisp \
  --program-change-policy replace \
  --output-json output/variant_b_ir.json --output-wav output/variant_b.wav -o output/variant_b.xex
```

### Arrange an existing Music DSL song

`arrange` accepts JSON only; convert the `.dsl` first (the notes are not altered):

```bash
python -m atari_music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl --output-json output/vaults.json

python -m atari_music arrange output/vaults.json \
  --channel-instrument 1=bass_16bit_pure \
  --channel-instrument 3=lead_pure_pluck \
  --channel-instrument 4=perc_tom_pitched \
  --program-change-policy remove \
  --output-wav output/vaults_pluck.wav --output-asm output/vaults_pluck.asm -o output/vaults_pluck.xex
```

!!! note "16-bit bass pairing"
    With `BASS 16BIT` the song joins `CH1` (master) with `CH2` (slave divider) via `AUDCTL=$10`, so
    `CH2` must stay unassigned — `POKEYRuntime` rejects conflicting assignments loudly.

## Batch runners

* **[`generate_arrangements.py`](https://github.com/grzes71/atari-music-composer/blob/main/generate_arrangements.py)** —
  adaptive batch pipeline for any single `.dsl` or JSON composition: queries compatible catalog
  instruments (`list-instruments --target xex_v2 --json`), converts `.dsl` automatically, detects 16-bit
  vs. 8-bit bass, analyzes each active channel's role, scores and ranks instrument combinations, and
  renders numbered `v2` variants plus the `v1` `vanilla` baseline to `.wav` and `.xex`, recording scoring
  rationale and executed commands in `arrangements.log`:

  ```bash
  python generate_arrangements.py -i examples/songs/wybierak-2.dsl -o output/wybierak2 --dry-run
  python generate_arrangements.py -i examples/songs/wybierak-2.dsl -o output/wybierak2 -m tools/mads/mads.exe
  ```

* **[`scripts/generate_instrument_test_suite.py`](https://github.com/grzes71/atari-music-composer/blob/main/scripts/generate_instrument_test_suite.py)** —
  batch validation against a real `.env` provider: generates 4 styles once each and renders 3 curated
  arrangements per style (12 WAV + 12 XEX + `manifest.json`) with musical fingerprint checks:

  ```bash
  python scripts/generate_instrument_test_suite.py --dry-run
  python scripts/generate_instrument_test_suite.py --output-dir output/instrument_tests
  ```

## Studio alternative

The [Studio GUI](studio.md) performs the same loop interactively — per-channel catalog assignment with
live diagnostics, A/B comparison of two arrangements, and validated XEX export.


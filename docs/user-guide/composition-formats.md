# Composition Formats

Atari Music Composer uses three representations across its pipeline. All of them describe the same
musical content at different levels of abstraction, and conversion between them is lossless.

| Format | Role | Where it is produced/consumed |
| --- | --- | --- |
| `AICompositionDoc` JSON (`"format": "atari-music-composition"`, v1) | **Canonical, Single Source of Truth** — notes, rhythm, form, semantic instruments | `ai-compose`, `import-dsl`, `import-json`, consumed by `compose`-time validation and `arrange` |
| POKEY IR JSON (`IRSong`) | **Hardware-compiled** intermediate — divider parameters, resolved `IRInstrument` tables, `program_change` events | `compose --output-json`, `import-json/import-dsl --output-ir`, `ai-compose --output-ir`, `arrange --output-json/-ir`, `export-mads` input |
| Music DSL (`.dsl`, v1/`v1.1`) | Compact plain-text frontend for humans and LLMs | `ai-compose --format dsl`, `import-dsl`, `build-xex --format dsl` |

## AICompositionDoc JSON

The schema SSOT is
[`src/atari_music/ai/schema.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/ai/schema.py).
A document contains `format`, `version`, `metadata`, `hardware` (`channels`, `use_16bit_bass`),
`instruments` (a semantic `character` such as `bass` or `dark_lead` plus optional `catalog_id` /
envelope fields), `patterns` (a list of patterns, each holding monophonic step events keyed by channel
`"0"`..`"3"`), `sequence`, and `loop_point`. Abridged excerpt from
[`examples/ai/dungeon_dark.json`](https://github.com/grzes71/atari-music-composer/blob/main/examples/ai/dungeon_dark.json):

```json
{
  "format": "atari-music-composition",
  "version": 1,
  "metadata": { "title": "AI Dark dungeon Journey", "key": "A", "mode": "dorian", "bpm": 88 },
  "hardware": { "channels": 4, "use_16bit_bass": true },
  "instruments": [
    { "id": "lead", "name": "Mystic Flute", "character": "dark_lead" },
    { "id": "bass", "name": "16-Bit Deep Drone", "character": "bass" }
  ],
  "patterns": [
    {
      "id": "A",
      "length_steps": 16,
      "channels": {
        "0": [ { "step": 0, "note": "A1", "instrument": "bass", "duration": 8, "volume": 14 } ],
        "1": [],
        "2": [ { "step": 0, "note": "A3", "instrument": "lead", "duration": 4, "volume": 13 } ],
        "3": []
      }
    }
  ],
  "sequence": ["A", "A", "B", "A"],
  "loop_point": 0
}
```

## POKEY IR JSON (`IRSong`)

Emitted by `compose --output-json`, `import-json --output-ir`, `import-dsl --output-ir`,
`ai-compose --output-ir`, and `arrange --output-json`. It stores hardware divider parameters, resolved
instrument tables (`IRInstrument`, v1 envelopes/modulation or v2 transient macros & pitch envelopes),
`initial_channel_instruments`, and per-note `pending_program_changes`. This is the format `export-mads`
consumes, and the format the frame simulator, WAV renderer, and the MADS exporter agree on.

## Music DSL

A compact, line-oriented plain text designed to minimize LLM token usage while mapping losslessly into
`AICompositionDoc` (see the [formal grammar and semantics](../reference/music-dsl.md)). Excerpt adapted
from [`examples/songs/Vaults-of-Nhyrmeth.dsl`](https://github.com/grzes71/atari-music-composer/blob/main/examples/songs/Vaults-of-Nhyrmeth.dsl):

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

When `BASS 16BIT` is active, POKEY joins `CH1` (master) and `CH2` (slave divider) via `AUDCTL=$10`;
`CH2` must remain empty or validation rejects the document with `BASS16_CHANNEL_CONFLICT`.

### How Music DSL differs from JSON

* **Syntax & size** — plain directives and whitespace-separated note tokens
  (`PITCH/DURATION[:VOL]`) instead of nested JSON objects per note.
* **Lossless compiler** — `parse_music_dsl()` compiles `.dsl` directly into `AICompositionDoc` (with
  exact line/column `DSLSyntaxError` messages) and runs the same 3-tier validator;
  `export_music_dsl()` serializes a document back to `.dsl`.
* **Scope limits** — supported directives are `TITLE`, `AUTHOR`, `KEY`, `MODE`, `BPM`, `CHANNELS`,
  `BASS 16BIT`, `LOOP`, `SEQUENCE`, `INSTRUMENT <id> character=<role> [dist=$XX] [att=N] [dec=N]
  [sus=N] [rel=N] [name="..."]`, optional `[PATTERN <id> length=N role=...]`, `CH1..CH4 <inst> V<vol>`,
  note tokens `<pitch>/<dur>[:<vol>]`, and rests (`R/<dur>` or `-/<dur>`). Comments start with `#`
  (keeping `#` inside pitches such as `C#4/4`). The DSL does **not** natively encode `catalog_id`
  fields or `PROGRAM_CHANGE` events.

## Converting between formats

```bash
# DSL -> canonical JSON (+ IR / WAV / ASM in one step)
python -m atari_music import-dsl song.dsl --output-json song.json --output-ir song_ir.json --output-wav song.wav

# JSON -> IR + WAV (validates the document first)
python -m atari_music import-json song.json --output-ir song_ir.json --output-wav song.wav

# IR JSON -> MADS assembly (export-mads takes IRSong only)
python -m atari_music export-mads song_ir.json -o song_data.asm --format-version auto
```

!!! note "`arrange` accepts JSON only"
    `arrange` parses `AICompositionDoc` JSON or `IRSong` JSON. Convert `.dsl` first:

    ```bash
    python -m atari_music import-dsl song.dsl --output-json song.json
    python -m atari_music arrange song.json --channel-instrument 3=lead_attack_bite \
      --output-wav out.wav -o out.xex
    ```

## Exported song binary formats

The MADS assembly and `.xex` produced on top of the IR use the binary song formats **v1** (legacy,
static per-channel instruments) and **v2** (32 instruments, transient macros, pitch envelopes,
`PROGRAM_CHANGE`). The layout, opcode grammar, and measured player resource profile are specified in
the [Song Format v2 specification](../reference/song-format-v2.md).

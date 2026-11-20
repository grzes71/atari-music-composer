# Music DSL (Domain-Specific Language) for Atari 8-bit / POKEY

## 1. Overview & Purpose

**Music DSL** is an optional, ultra-compact textual frontend designed primarily for Large Language Models (LLMs) and human composers creating chiptune music for the Atari 8-bit platform (POKEY chip).

### Canonical Architecture
The canonical format and Single Source of Truth (SSOT) of the system remains `AICompositionDoc` (and its JSON serialization). Music DSL is purely an alternative input representation:

```text
LLM
 ├── JSON ───────────────┐
 │                       │
 └── Music DSL ── parser ┤
                         ↓
                 AICompositionDoc
                         ↓
                 3-Tier Validation
                         ↓
                 Symbolic Music IR
                         ↓
                    POKEY IR
                    ↙        ↘
                  WAV        ASM/XEX
```

Music DSL does **not** create a second musical model or alternative IR. It parses directly into `AICompositionDoc`, passing through the exact same 3-tier validation (Schema, Musical Grammar, Hardware Constraints) and rendering pipeline.

---

## 2. Full V1 Formal Grammar

```ebnf
document       = { global_entry | instrument_def | pattern_def } ;

global_entry   = title_dir
               | author_dir
               | key_dir
               | mode_dir
               | bpm_dir
               | channels_dir
               | bass16_dir
               | loop_dir
               | sequence_dir ;

title_dir      = "TITLE" string ;
author_dir     = "AUTHOR" string ;
key_dir        = "KEY" pitch_class ;
mode_dir       = "MODE" mode_name ;
bpm_dir        = "BPM" integer ;
channels_dir   = "CHANNELS" integer ;
bass16_dir     = "BASS" "16BIT" ;
loop_dir       = "LOOP" integer ;
sequence_dir   = "SEQUENCE" { identifier } ;

instrument_def = "INSTRUMENT" identifier { param_pair } ;
param_pair     = ( "character" | "dist" | "att" | "dec" | "sus" | "rel" | "name" ) "=" value ;

pattern_def    = pattern_hdr { channel_block } ;
pattern_hdr    = "[PATTERN" identifier [ pattern_param ] "]" ;
pattern_param  = ( "length=" | "len=" | "length_steps=" ) integer
               | "role=" identifier ;

channel_block  = channel_hdr { note_token } ;
channel_hdr    = ( "CH1" | "CH2" | "CH3" | "CH4" ) [ identifier ] [ "V" integer ] ;

note_token     = ( pitch | "R" | "-" ) "/" duration [ ":" volume ] ;
pitch          = ( "C".."B" ) [ "#" | "B" ] integer ;
duration       = integer ;  (* steps >= 1 *)
volume         = integer ;  (* 0..15 *)
```

### Directives Reference
* `TITLE <string>`: Composition title (quoted or unquoted).
* `AUTHOR <string>`: Author attribution.
* `KEY <C|D|E|F|G|A|B|F#|Bb...>`: Root key signature.
* `MODE <minor|major|dorian|mixolydian...>`: Musical mode.
* `BPM <integer>`: Target tempo (40..250).
* `CHANNELS <1..4>`: Active hardware channel limit (typically 4).
* `BASS 16BIT`: Enables 16-bit pure tone bass coupling on Ch1 (master) + Ch2 (slave).
* `LOOP <integer>`: Sequence index to loop back to (0-indexed).
* `SEQUENCE <id1> <id2> ...`: Ordered playback sequence of pattern IDs.
* `INSTRUMENT <id> character=<role> [dist=$XX] [att=N] [dec=N] [sus=N] [rel=N] [name="..."]`: Defines or overrides custom timbre and ADSR envelope.
* `[PATTERN <id> [length=N] [role=theme|contrast|fill]]`: Declares a pattern block.
* `CH<1..4> [role] [V<vol>]`: Channel header setting the active channel, instrument timbre, and default volume (0..15).
* `<pitch>/<duration>[:<accent_vol>]`: Note event (e.g. `C4/4`, `D#2/8:15`).
* `R/<duration>` or `-/<duration>`: Rest (silence) event.

---

## 3. Semantics & Timing Rules

1. **Step Calculation**:
   - Consecutive notes within a channel block play back-to-back.
   - The parser tracks a monotonic cursor: `current_step += note.duration`.
   - Rests advance the step cursor without creating active sounding events.

2. **Pattern Length Determination**:
   - If `length=N` is explicitly specified on `[PATTERN <id> length=N]`, that length is enforced. Note events exceeding `N` raise a syntax error.
   - If omitted, pattern length is determined deterministically as:
     $$\text{length\_steps} = \max(\text{channel\_durations})$$
     If all channels are silent, defaults to 16.
   - No heuristic rounding is applied.

3. **Rest vs Note-Off vs Volume 0**:
   - `R/<dur>` and `-/<dur>` advance the timeline without emitting note triggers.
   - At the POKEY IR / player level, this leaves the channel silent (volume 0, no AUDF frequency written).

4. **16-bit Bass Coupling**:
   - When `BASS 16BIT` is declared, `use_16bit_bass` is set to `True`.
   - In hardware, CH1 (POKEY Channel 0) and CH2 (POKEY Channel 1) are paired into a single 16-bit frequency generator.
   - All bass notes must be written to `CH1`.
   - `CH2` acts as the hardware frequency slave and must remain empty. If notes are placed on `CH2`, the 3-tier validator rejects the document with `BASS16_CHANNEL_CONFLICT`.

5. **Channel Numbering**:
   - DSL uses user-friendly 1-based indexing: `CH1`, `CH2`, `CH3`, `CH4`.
   - This maps directly to POKEY hardware channels 0, 1, 2, 3 internally.

6. **Comments**:
   - Comments begin with `#` preceded by whitespace or at the start of a line.
   - Embedded `#` within pitch notations (e.g. `C#4/4`, `F#2/8`) are preserved as musical sharps.

---

## 4. Complete Example

```dsl
TITLE "Vaults of Nhyrmeth"
AUTHOR "AI Composer"
KEY D
MODE MINOR
BPM 90
CHANNELS 4
BASS 16BIT
LOOP 0

SEQUENCE A1 A2 B1 B2 A1 A2

[PATTERN A1 role=theme]
CH1 BASS V14
D2/8 F2/8 C2/8 D2/8 A2/8 Bb2/8 A2/8 D2/8

CH3 LEAD V13
D4/4 F4/4 A4/6 G4/2 F4/4 E4/4 D4/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4

[PATTERN A2 role=theme]
CH1 BASS V14
D2/8 F2/8 C2/8 D2/8 Bb2/8 C3/8 A2/8 D2/8

CH3 LEAD V13
D4/4 F4/4 A4/4 D5/4 C5/4 Bb4/4 A4/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4

[PATTERN B1 role=contrast]
CH1 BASS V14
G2/8 Bb2/8 F2/8 G2/8 D2/8 F2/8 C2/8 G2/8

CH3 LEAD V13
G4/4 Bb4/4 D5/4 G5/4 F5/4 D5/4 C5/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4

[PATTERN B2 role=contrast]
CH1 BASS V14
A2/8 C3/8 G2/8 A2/8 F2/8 G2/8 E2/8 D2/8

CH3 LEAD V13
A4/4 C5/4 E5/4 A5/4 G5/4 E5/4 D5/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4
```

---

## 5. Mapping DSL to `AICompositionDoc`

| DSL Directive / Syntax | `AICompositionDoc` Target Field |
| :--- | :--- |
| `TITLE "..."` | `doc.metadata.title` |
| `AUTHOR "..."` | `doc.metadata.author` |
| `KEY <key>` | `doc.metadata.key` |
| `MODE <mode>` | `doc.metadata.mode` |
| `BPM <bpm>` | `doc.metadata.bpm` |
| `CHANNELS <n>` | `doc.hardware.channels` |
| `BASS 16BIT` | `doc.hardware.use_16bit_bass = True` |
| `LOOP <idx>` | `doc.loop_point` |
| `SEQUENCE <id...>` | `doc.sequence` |
| `INSTRUMENT <id> ...` | `doc.instruments[i]` (`AIInstrumentDef`) |
| `[PATTERN <id> length=N role=R]` | `AIPatternDef(id=id, length_steps=N, role=R)` |
| `CH<1..4> <inst> V<vol>` | Pattern track channel key `"1"`..`"4"`, instrument ID, default volume |
| `<pitch>/<dur>[:<vol>]` | `AIPatternChannelEvent(step, note, duration, volume, instrument)` |
| `R/<dur>` or `-/<dur>` | Step cursor offset (no sounding event) |

---

## 6. Python API

```python
from atari_music.ai.dsl import parse_music_dsl, export_music_dsl, DSLSyntaxError
from atari_music.ai.client import load_composition, generate_music_from_dsl

# 1. Parse DSL directly into canonical doc (passes 3-tier validation)
doc = parse_music_dsl(dsl_text)

# 2. Serialize canonical doc back to DSL
exported_text = export_music_dsl(doc)

# 3. Polymorphic loader (accepts .json, .dsl, path, or string)
doc = load_composition("my_track.dsl")

# 4. End-to-end rendering directly from DSL
res = generate_music_from_dsl(dsl_text)
res.render_wav("track.wav")
```

---

## 7. CLI Usage

All existing JSON commands remain 100% backwards-compatible. DSL support is added via explicit flags:

### Generate Music via LLM in DSL format
```bash
# Generate plain text Music DSL
atari-music ai-compose --provider mock --format dsl -o composition.dsl

# Default is still json:
atari-music ai-compose --provider mock -o composition.json
```

### Import and Render from DSL or JSON
```bash
# Dedicated command for Music DSL (validates, outputs WAV / ASM / IR and optionally canonical JSON):
atari-music import-dsl composition.dsl --output-wav track.wav --output-asm track.asm --output-json canonical.json

# Dedicated command for canonical JSON:
atari-music import-json composition.json --output-wav track.wav --output-asm track.asm

# Directly compile to Atari XEX executable (supports explicit --format [json|dsl]):
atari-music build-xex composition.dsl --format dsl --output track.xex
atari-music build-xex composition.json --format json --output track.xex
```

---

## 8. Benchmark: JSON vs Music DSL

Measured on real production compositions (`examples/ai/`):

| Composition | Canonical JSON (Chars / Est. Tokens) | Music DSL (Chars / Est. Tokens) | Token Reduction | Parse Time | ASM & POKEY IR Equivalence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `action_fast` | 8,445 chars / 2,778 tok | 769 chars / 442 tok | **84.1%** | 0.79 ms | **100% IDENTICAL** |
| `dungeon_dark` | 4,383 chars / 1,630 tok | 512 chars / 268 tok | **83.6%** | 0.36 ms | **100% IDENTICAL** |
| `funny_prl` | 5,553 chars / 1,955 tok | 632 chars / 358 tok | **81.7%** | 0.53 ms | **100% IDENTICAL** |
| **TOTAL / AVG** | **18,381 chars / 6,363 tok** | **1,913 chars / 1,068 tok** | **83.2%** | **< 1.0 ms** | **ALL PASS** |

*Note: Token counts measured with standard OpenAI `cl100k_base` BPE tokenizer boundaries.*

---

## 9. Limitations & Explicit Scope Boundaries (V1)

To guarantee 100% determinism and avoid unstable heuristics, V1 establishes strict boundaries:

1. **No Music Macros / Transposition**:
   - Constructs like `MOTIF HERO: ...` or `TRANSPOSE +2` are deferred to V2.
2. **No Dynamic Mid-Channel Instrument Switching**:
   - POKEY hardware requires one waveform timbre per channel. Switching instruments mid-channel is illegal in both JSON and DSL.
3. **Canonical SSOT Remains JSON**:
   - `AICompositionDoc` is the single source of truth. DSL is exclusively an opt-in frontend for prompt economy and LLM context window optimization.

# Procedural Composition

The `compose` command drives **Composer v4**, the deterministic procedural engine behind the public
Music Generation API (`atari_music.api.generate_music`). Given the same inputs it produces the same
song — no AI, no network, no randomness beyond the seeded RNG.

## The six canonical profiles

| Profile | Intended use |
| --- | --- |
| `title` | Title screens / signature themes |
| `exploration` | Ambient, exploratory game scenes |
| `action` | Fast-paced gameplay |
| `funny` | Comedic, light-hearted moods |
| `dungeon` | Dark, tense atmospheres |
| `ending` | Resolution / credit sequences |

## Command reference

```text
python -m atari_music compose [OPTIONS]
```

| Option | Meaning |
| --- | --- |
| `-p, --profile TEXT` | Stylistic profile: `title`, `exploration`, `action`, `funny`, `dungeon`, `ending` |
| `-s, --seed INTEGER` | Deterministic RNG seed |
| `-k, --key TEXT` | Root key (`C`, `D`, `E`, `F`, `G`, `A`, `B`) |
| `-t, --tempo INTEGER` | Tempo in BPM (`50..240`) |
| `-l, --length [short\|medium\|long]` | Duration intent |
| `--intensity FLOAT` | Expected intensity (0.0–1.0) |
| `-v, --variation FLOAT` | Motivic variation level (0.0–1.0) |
| `--channel-instrument CH=ID` | Assign SSOT catalog instruments (see [Instruments](instruments.md)) |
| `--program-change CH@TARGET[:NOTE]=ID` | Schedule mid-song instrument switches |
| `--instrument-catalog FILE` | SSOT catalog path (default `src/atari_music/instruments/catalog.json`) |
| `--player-version [auto\|v1\|v2]` | Target player format for MADS export & validation |
| `--output-json PATH` | POKEY IR JSON output |
| `--output-wav PATH` | 44.1 kHz WAV output |
| `--output-asm PATH` | MADS assembly output |

## Example session

```bash
# A short dungeon piece, fully deterministic
python -m atari_music compose --profile dungeon --seed 501 --length short \
  --output-json output/first/first.json --output-wav output/first/first.wav

# Catalog-aware composition: v2 instruments assigned per channel from the start
python -m atari_music compose --profile action --seed 9001 --tempo 140 \
  --channel-instrument 1=bass_poly4_punch \
  --channel-instrument 3=lead_attack_bite \
  --channel-instrument 4=perc_kick_tight \
  --output-json output/action_ir.json --output-wav output/action.wav -o output/action.xex
```

Reported example output for the first command:

```text
Generated [DUNGEON]: 'ComposerV4 [DUNGEON] #501 (A dorian)' (Seed: 501)
Key: A dorian, Tempo: 85 BPM, Form: A A' B A, Dur: 12.8s, Mem: 389 B, Channels: 4, Format: v1
```

## What the engine produces

Composer v4 generates a 4-channel piece with bass lines, counterpoint, and percussion/ornamentation,
and can join `CH1` (master) + `CH2` (slave divider) for 16-bit bass (`AUDCTL=$10`). The result is
compiled into the symbolic Music IR and the hardware POKEY IR (`IRSong`), from which the WAV renderer
and the MADS/XES exporters work. The engine composes music only — the concrete POKEY realization is
selected by instrument assignment. See the [pipeline architecture](../architecture/pipeline.md) for
details.

## Python API

The CLI is a thin wrapper over the stable facade in
[`atari_music.api`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/api.py):

```python
from atari_music.api import generate_music

song = generate_music(profile="dungeon", seed=501, length="short")
song.render_wav("output/dungeon.wav")
```

and, using the same facade, arrange the generated result without mutating it:

```python
from atari_music.api import arrange_song, generate_music

song = generate_music(profile="dungeon", seed=501)
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

Rejected parameters raise validation errors instead of degrading silently; `MusicGenerationResult`
carries rich metadata (profile, seed, tempo, key, mode, duration) alongside the render/export methods.

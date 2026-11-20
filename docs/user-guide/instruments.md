# Instruments

The instrument system is the project's answer to the core POKEY problem: with only four monophonic
channels and a handful of distortion modes, *timbre quality comes from disciplined hardware use* —
validated ADSR envelopes, clock/filter routing, transient macros, and pitch envelopes — not from
improvisation. All instrument knowledge therefore lives in one curated place: the **SSOT catalog**.

## The SSOT catalog

Instruments are defined in
[`data/instruments/catalog.json`](https://github.com/grzes71/atari-music-composer/blob/main/data/instruments/catalog.json)
(schema `atari-music/instrument-catalog/1`, catalog version `0.1.0`), validated by
[`src/atari_music/instruments/catalog.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/instruments/catalog.py).
It currently holds **16 curated instrument profiles** and **10 behaviors**:

| Tier | Meaning | Instruments |
| --- | --- | --- |
| `core_v1` | Static ADSR or `octave_pulse` modulation — `[OK]` on `xex_v1`, `xex_v2`, and `wav` | `lead_pure_sustain`, `lead_pure_pluck`, `lead_c1_octave_pulse`, `lead_buzz_steady`, `bass_16bit_pure`, `bass_15khz_pure`, `bass_16bit_poly5_growl`, `harmony_soft_square` |
| `core_v2_iter1` | Multi-step 50 Hz transient macros and pitch envelopes — `[OK]` on `xex_v2` and `wav` (WAV via v2 frame simulation) | `lead_attack_bite`, `bass_poly4_punch`, `perc_kick_tight`, `perc_snare_crisp`, `perc_hihat_closed`, `perc_tom_pitched` |
| `experimental_deferred` | Explicitly blocked (`[DEFERRED_FEATURE]`) on all export targets | `lead_hpf_pwm` (HPF XOR PWM), `ornament_bell_arp` (arpeggio ornament) |

Every profile declares a `family` (`lead`, `bass`, `pad`, `harmony`, `percussion`, `fx`), intended
roles, a base distortion, an ADSR `envelope`, a `waveform_family`, hard
`hardware_constraints` (divider mode, required/forbidden `AUDCTL` bits, MIDI range, allowed channels),
a `behavior_id`, and provenance (source profile/bank, fingerprint, validation status). The JSON
structure is documented in [Adding New Instruments](../development/adding-instruments.md).

## CLI tools for the catalog

```bash
python -m atari_music list-instruments --target xex_v2      # + --family bass / --role / --json
python -m atari_music inspect-instrument perc_kick_tight    # full constraints, envelope, behavior, provenance
python -m atari_music validate-instruments                   # schema + cross-field hardware rules + behavior links
```

## Assigning instruments to channels

`--channel-instrument CH=INSTRUMENT_ID` (repeatable) maps a channel number `1..4` *or* a case-insensitive
role alias to a catalog instrument:

| Alias | Channel |
| --- | --- |
| `bass` | 1 |
| `harmony` / `counter` / `pad` | 2 |
| `lead` / `melody` | 3 |
| `perc` / `percussion` / `drums` / `rhythm` | 4 |

This works on `compose`, `ai-compose`, and `arrange`; channels you do not assign keep their existing
realization. `POKEYRuntime`
([`src/atari_music/instruments/runtime.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/instruments/runtime.py))
enforces `channels_allowed`, clock compatibility (`64khz`, `15khz`, `1.79mhz`), 16-bit pair locks
(`16bit_ch12`, `16bit_ch34`), and target tiers **without silent fallbacks** — a conflicting assignment
fails loudly instead of degrading the sound. For example, assigning an instrument to `CH2` of a
`BASS 16BIT` song (joined `CH1+CH2`) is rejected.

## Mid-song instrument switches (`PROGRAM_CHANGE`)

`compose --program-change CH@TARGET[:NOTE]=INSTRUMENT_ID` schedules a 0-tick instrument switch
(opcode `$01`, supported by `SONG_FORMAT_VERSION = 2`). Example: `3@B=lead_attack_bite` switches `CH3`
at pattern `B`; `4@1:2=perc_snare_crisp` switches `CH4` two steps into pattern `1`. Catalog-aware AI
generation (`ai-compose --use-instrument-catalog`) can emit the same events model-side. See
[Arrangement](arrangement.md) for the `--program-change-policy` handling of existing switches.

## Player format versions

`--player-version [auto|v1|v2]` selects the binary song format:

* **`auto` (default)** — keeps `SONG_FORMAT_VERSION = 1` whenever the song fits v1 (≤ 4 channel
  instruments, no v2 macros, pitch envelopes, or `PROGRAM_CHANGE` events), and switches to `2` only when
  required.
* **`v1`** — strictly exports Format v1; raises `FormatVersionError` if v2 features are present.
* **`v2`** — explicitly exports Format v2.

The binary layout is specified in the [Song Format v2 specification](../reference/song-format-v2.md).

## Legacy instrument paths

Two pre-catalog mechanisms remain functional for backward compatibility:

* **Sound-profile banks** — `--sound-bank DIRECTORY` / `--profile-bindings FILE` bind externally analyzed
  POKEY sound archaeology profiles to composition instruments; see
  [Sound Profile Integration](../reference/profile-integration.md).
* **Lead Library v0.1** — `--instrument PART=INSTRUMENT_ID` / `--instrument-library DIRECTORY` on
  `import-json`, `import-dsl`, and `build-xex`; see the
  [Legacy Lead Library CLI](../reference/instrument-selection-cli.md).

The Studio GUI provides the same catalog assignment with live compatibility diagnostics — see
[Studio](studio.md).

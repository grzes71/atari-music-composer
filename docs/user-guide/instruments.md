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
It currently holds **20 curated instrument profiles** and **14 behaviors**:

| Tier | Meaning | Instruments |
| --- | --- | --- |
| `core_v1` | Static ADSR or `octave_pulse` modulation — `[OK]` on `xex_v1`, `xex_v2`, and `wav` | `lead_pure_sustain`, `lead_pure_pluck`, `lead_c1_octave_pulse`, `lead_buzz_steady`, `bass_16bit_pure`, `bass_15khz_pure`, `bass_16bit_poly5_growl`, `harmony_soft_square` |
| `core_v2_iter1` | Multi-step 50 Hz transient macros and pitch envelopes — `[OK]` on `xex_v2` and `wav` (WAV via v2 frame simulation) | `lead_attack_bite`, `bass_poly4_punch`, `perc_kick_tight`, `perc_snare_crisp`, `perc_hihat_closed`, `rhytmizer_closed_hihat`, `cmc_hihat_open`, `cmc_kick_stopa`, `cmc_tom_ltom`, `perc_tom_pitched` |
| `experimental_deferred` | Explicitly blocked (`[DEFERRED_FEATURE]`) on all export targets | `lead_hpf_pwm` (HPF XOR PWM), `ornament_bell_arp` (arpeggio ornament) |

Every profile declares a `family` (`lead`, `bass`, `pad`, `harmony`, `percussion`, `fx`), intended
roles, a base distortion, an ADSR `envelope`, a `waveform_family`, hard
`hardware_constraints` (divider mode, required/forbidden `AUDCTL` bits, MIDI range, allowed channels),
a `behavior_id`, and provenance (source profile/bank, fingerprint, validation status). The JSON
structure is documented in [Adding New Instruments](../development/adding-instruments.md).

!!! note "Rhytmizer Closed Hi-Hat (`rhytmizer_closed_hihat`)"
    `rhytmizer_closed_hihat` is a 50 Hz PAL VBI single-channel adaptation of the Closed Hi-Hat from
    *Rhytmizer* (MUNSIE, 1986), not a bit-exact reproduction of the original 140 Hz two-channel routine.
    It is the **default percussion instrument for new format v2 compositions** across Composer v4,
    AI generation, and CLI (resolved from the SSOT catalog unless explicitly overridden; format v1 and
    existing saved compositions keep their static/original percussion defaults). It **requires player
    format v2** (`SONG_FORMAT_VERSION = 2` / `xex_v2`), uses a fixed transient macro volume of `4`
    (`F0`: `AUDF=$00`, `AUDC=$84` poly17 noise; `F1+`: volume `0`), can be assigned to any single
    channel `CH1..CH4`, and is **incompatible with the 15 kHz base clock** (`AUDCTL=$01`,
    `forbidden_audctl_bits = $01`).

!!! note "CMC+ Open Hi-Hat (`cmc_hihat_open`)"
    `cmc_hihat_open` is an additional, complementary Open Hi-Hat adapted from *Chaos Music Composer
    Plus* (1993) preset **#59 `hihat op`** via a 5-step v2 transient macro (`F0..F4`: `AUDF=$3F`,
    `AUDC=$86, $84, $82, $81, $81` poly17 noise; `F5+`: volume `0`). Like `rhytmizer_closed_hihat`, it
    **requires player format v2** (`core_v2_iter1` / `xex_v2`), can be assigned to any single channel
    `CH1..CH4`, and is **incompatible with the 15 kHz base clock** (`forbidden_audctl_bits = $01`),
    while leaving `rhytmizer_closed_hihat` unchanged as the default v2 percussion instrument. It
    achieves exact 50 Hz POKEY register-frame parity against original CMC+ `#59`; minor acoustic
    differences can occur from poly17 LFSR phase variance across ASAP renders, and the internal
    `pokey_synth` WAV preview exhibits a shorter `-20 dB` envelope span than ASAP 8.0.0 XEX playback.

!!! note "CMC+ Kick Stopa (`cmc_kick_stopa`)"
    `cmc_kick_stopa` is a punchy single-channel kick adapted from *Chaos Music Composer Plus* (1993)
    preset **#46 `stopa`** via a 4-step v2 transient macro (`F0`: `AUDF=$5A, AUDC=$0D` poly5+17 attack;
    `F1`: `AUDF=$2F, AUDC=$AE` pure thump; `F2`: `AUDF=$2F, AUDC=$A6`; `F3+`: volume `0`). It
    **requires player format v2** (`core_v2_iter1` / `xex_v2`), works on any single channel
    `CH1..CH4`, is **incompatible with the 15 kHz base clock** (`forbidden_audctl_bits = $01`), and
    achieves exact `16/16` POKEY register-frame parity against original CMC+ `#46`. Internal
    `pokey_synth` WAV previews normalize peak output to `0.90` and reflect `POKEY_DAC` + DC-blocking
    filter behavior (`-20 dB` span `37 ms` vs. ASAP 8.0.0 `49–65 ms`).

!!! note "CMC+ Low Tom (`cmc_tom_ltom`)"
    `cmc_tom_ltom` is a single-channel click-attack low tom adapted from *Chaos Music Composer Plus*
    (1993) preset **#45 `l_tom`** via a 6-step v2 transient macro (`F0`: `AUDF=$01, AUDC=$88` poly17
    click; `F1..F4`: `AUDF=$80..$83`, `AUDC=$A4..$A1` downward pure-tone pitch sweep; `F5+`:
    volume `0`). It **requires player format v2** (`core_v2_iter1` / `xex_v2`), works on any single
    channel `CH1..CH4`, is **incompatible with the 15 kHz base clock** (`forbidden_audctl_bits = $01`),
    and achieves exact `16/16` POKEY register-frame parity against original CMC+ `#45`. Internal
    `pokey_synth` WAV previews match the `247.6 Hz` tom body fundamental (`F1..F4`) while
    exhibiting higher spectral centroid and shorter `-20 dB` span (`60 ms` vs. ASAP `92–96 ms`) due
    to `POKEY_DAC` weighting and DC-blocker behavior.

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

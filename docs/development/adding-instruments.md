# Adding New Instruments

Instruments live in exactly one place —
[`data/instruments/catalog.json`](https://github.com/grzes71/atari-music-composer/blob/main/data/instruments/catalog.json)
(schema `atari-music/instrument-catalog/1`) — so adding one is a data change plus validation, not a
code change. This page is the practical checklist.

## 1. Model the profile

A catalog entry (`InstrumentProfile`, see
[`instruments/models.py`](https://github.com/grzes71/atari-music-composer/blob/main/src/atari_music/instruments/models.py))
looks like this (the `lead_pure_sustain` entry, abridged):

```json
{
  "instrument_id": "lead_pure_sustain",
  "display_name": "Pure Sustain Lead",
  "version": "1.0",
  "family": "lead",
  "intended_roles": ["melody"],
  "base_distortion": 160,
  "envelope": {
    "attack_frames": 6, "decay_frames": 0,
    "sustain_vol": 10, "release_frames": 2, "peak_vol": 15
  },
  "waveform_family": "pure",
  "hardware_constraints": {
    "divider_mode": "8bit",
    "preferred_clock_hz": "64khz",
    "required_audctl_bits": 0,
    "forbidden_audctl_bits": 0,
    "poly4_safe_tuning": false,
    "midi_range": [48, 96],
    "channels_allowed": [1, 2, 3, 4]
  },
  "behavior_id": "beh_static_v1",
  "provenance": {
    "source_kind": "sound_profile_bank",
    "profile_id": "pokey_ref_25f94201",
    "validation_status": "PLAYABLE",
    "notes": "..."
  }
}
```

Field constraints to respect:

* `instrument_id` must match `^[a-z][a-z0-9_]*$`; `family` is one of `lead`, `bass`, `pad`, `harmony`,
  `percussion`, `fx`; `intended_roles` from `melody`, `bass`, `harmony`, `rhythm`, `percussion`.
* `base_distortion` is the `AUDC` generator nibble: one of `$00`, `$20`, `$40`, `$60`, `$80`, `$A0`,
  `$C0`, `$E0` (see the [distortion table](../architecture/audio-engine.md#distortion-decoding-audc-bits-57)
  for audibly identical pairs — e.g. use `$A0`, not `$E0`, to signal intent).
* `envelope` is a static linear 4-phase ADSR matching `player.asm`: `attack/decay/release` ≤ 255
  frames, `sustain_vol` 0–15, `peak_vol` 1–15.
* `hardware_constraints.divider_mode` is one of `8bit`, `16bit_ch12` (requires
  `AUDCTL $10`, CH2 empty), `16bit_ch34` (requires `$08`, CH4 empty); `required_audctl_bits` /
  `forbidden_audctl_bits` are hard masks (0–255).
* `hardware_constraints.midi_range` bounds the playable span; `channels_allowed` restricts placement;
  `poly4_safe_tuning` marks whether the divider math is trustworthy under `POLY4` gating at the
  targeted clock.
* `provenance.source_kind` is one of `curated_preset`, `sound_profile_bank`, `sound_design_demo`.

## 2. Pick (or define) a behavior

`behavior_id` links the profile to time-varying machinery. Existing behaviors cover: static v1,
octave-pulse modulation, and `core_v2_iter1` transient macros and/or pitch envelopes (kick, snare,
hi-hat, tom, bass sub-punch, attack bite, …). A v2 behavior step is bound by the format:
**1–8 steps per macro**, each 4 bytes (`duration_frames` 1–255, distortion nibble, `audf`
fixed/offset, volume), and the exporter enforces them (see
[Song Format v2](../reference/song-format-v2.md)). A couple of behaviors in the catalog also declare a
`pitch_envelope` (`start_audf_delta`, `duration_frames`, `step_delta`) of ≤ 15 frames.

If your sound needs a brand-new behavior, add a `behaviors` entry and set its
`required_runtime_tier` to the lowest tier that can actually realize it:

| Tier | Requires |
| --- | --- |
| `core_v1` | static ADSR / octave pulse only |
| `core_v2_iter1` | transient macros and pitch envelopes (XEX v2 + WAV) |
| `wav_only` | preview-only sounds that the 6502 player cannot express |
| `experimental_deferred` / `core_v2_iter2` | **blocked on all targets** — declare this only when the capability is intentionally not shipped yet |

Do not claim `core_v1` for a sound that needs macros — the runtime gating is per-tier and the studio
checks delegate to it.

## 3. Validate and register

```bash
python -m atari_music validate-instruments        # schema + cross-field hardware rules + behavior links
python -m atari_music list-instruments            # confirm it appears across targets
python -m atari_music inspect-instrument <id>     # full constraint dump
```

`validate-instruments` fails on unknown behavior links, mismatched `divider_mode` ↔
`required_audctl_bits`, macro step limits, and provenance gaps — fix everything it reports rather than
loosening the validator.

## 4. Prove it end-to-end

* Render it: `python -m atari_music arrange song.json --channel-instrument CH=<id> --output-wav x.wav`.
* Listen. If the research program applies to your sound family, consider the perceptual/curated
  timbre methodology from the [timbre experiments](../research/experiment29_curated_timbre_candidates.md).
* On Windows with MADS available, also boot the result in `py65` through the existing e2e suite with a
  regression test that pins your instrument's register output (see
  `tests/test_lead_c1_octave_pulse_regression.py` for the pattern: catalog contract, bit-exact
  `$D200–$D208` parity, WAV melodic checks, and — with a local ASAP — real POKEY silicon comparison).
* Add/extend tests in `tests/test_instrument_catalog.py` for catalog-level invariants.

## 5. Documentation

If the instrument is user-visible, mention it in the context of the [instruments page](../user-guide/instruments.md)
tiers table and, when it introduces a new technique, in the relevant architecture page. Catalog
versioning: bump `catalog_version` when the set of profiles changes meaningfully.

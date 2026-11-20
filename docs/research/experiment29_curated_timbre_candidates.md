# Experiment 29 — a curated candidate library of POKEY timbres

**Status:** delivered, awaiting listening. No production behaviour was changed and no candidate has
been registered as an instrument.

The problem this addresses is the one the project started with: individual notes in generated music
sound too simple. Experiment 28 showed that one experimental timbre (C1) survives being put into a
real composition. This experiment does not invent another timbre. It screens the project's **existing
bank of 67 extracted sound profiles**, picks a small set that is plausibly *different from each other*,
renders them on one identical note grid, and hands the owner a blind page to audition.

**Stop condition:** the audition set. Which candidates deserve to become instruments is the owner's
listening decision, not this report's conclusion.

---

## 1. The bank, verified

Located by inspection, not assumed: `tests/data/sound_profiles/bank/registry.json` plus
`profiles/pokey_ref_*.json`, read through the existing loader
(`atari_music.sound_profiles.bank.load_sound_profile_bank`). Schema
`pokey-sound-profile-registry-1.0`, 67 profiles.

The historical classifications the brief quotes were **re-derived from the repository** and match:

| dimension | values |
|---|---|
| profile type | `VOICE` 49, `PAIR` 18 |
| published status | `PLAYABLE` 22, `PLAYABLE_WITH_LIMITATION` 39, `MEASUREMENT_ONLY` 6 |
| renderable (`status in RENDERABLE_STATUSES`) | 61 |
| generator nibble | `$0` 7, `$6` 1, `$8` 19, `$A` 24, `$C` 16 |
| AUDCTL | `$00` 45 (64 kHz, 8-bit voice), `$50` 22 (joined 1+2, 1.79 MHz, 16-bit) |
| measured envelope shape | tremolo 23, unknown 38, sustained 3, swell 2, plucked 1 |
| carries a measured **pitch** gesture | 46 |
| carries a measured **distortion** gesture | 22 |
| carries a measured **volume** contour | 58 |

Every profile is recorded in `experiments/experiment29/candidates.json` with the fields the loader
actually exposes: id, type, status, generator, AUDCTL/clock/coupling, channel requirements, pitch
evidence, volume and envelope, measured gestures, limitation codes and source songs.

### Which measured properties the engine cannot reproduce

Read from `sound_profiles/binding.py`. `apply_profile_binding` writes exactly five things onto an
`IRSong` instrument: `distortion`, `envelope`, `audctl`, `is_16bit` and — opt-in — `volume_contour`.
It never changes a pitch, a duration, a rest, a velocity or a role.

| measured property | reaches the sound? | why not, where it does not |
|---|---|---|
| `distortion` (AUDC generator nibble) | **yes** | — |
| `envelope` frames + sustain level | **yes**, when the composition leaves them open | — |
| `audctl` clock/coupling | **yes** | — |
| `is_16bit` / `uses_16bit_bass` | **yes** | — |
| `volume_contour` | opt-in, **off here** | off by default in production, and `mads_exporter` refuses to export a song while one is set |
| `gesture.pitch.runs` | **no** | `IRNote.slide_semitones` / `arpeggio_offsets` / `IRInstrument.vibrato_*` are reserved and never rendered; the player sets AUDC once per channel |
| `gesture.control_state.runs` | **no** | `_render_note_to_frames` writes one constant generator for the whole note |
| `envelope.shape` label | **no** | it labels the contour; only the four frame counts reach the render |
| `pitch.base_hz` / `base_divider` | **no** | evidence about the source; the note supplies the pitch and the profile supplies the clock |
| `pitch.range_semitones` | **no** | the played range is the composition's |
| high-pass clocking (AUDCTL bits 1–2) | **no** | not implemented by the WAV renderer |
| any joined pair other than 1+2 | **no** | the composer's only joined-pair layout is 1+2 |

**Consequence for selection.** Two profiles that differ only in `pitch.base_hz`, measured range or
gesture data **render identically** here. So diversity was judged on the audibly-relevant tuple —
`(distortion nibble, AUDCTL, attack, decay, release, sustain level)`. Among the 61 renderable profiles
there are **37 distinct tuples**; the largest identical group is 10. That is the real diversity the
bank offers, and it is what the shortlist draws on.

### Feasibility verdicts

`faithful` 7 (measured envelope, no unreproducible gesture), `limited` 54, `unusable` 6. "Limited" is
the normal case and is not a defect: 46 profiles carry a pitch gesture and 38 have no measured
envelope, so the composer's default articulation is used for them.

**No production code was changed to make an unsupported profile look playable.**

---

## 2. The shortlist

Twelve candidates: eleven bank profiles plus the C1 reference. The C1 reference is not a bank profile —
it is Experiment 26/27 variant C, reused through Experiment 28's `apply_c1` rather than reconstructed.

| candidate | source | type | status | generator | clock | envelope (a/d/r/sus) | ch | note RMS | note clip | limit codes |
|---|---|---|---|---|---|---|---|---|---|---|
| `c1_octave_pulse` | Experiment 27/28 variant C | VOICE | — | `$40` + octave pulse | 64 kHz, 8-bit | a1 d3 r2 s13 (default) | 3 | 0.3768 | clip_03 | 0 |
| `pure_sustain` | `pokey_ref_25f94201` | VOICE | PLAYABLE | `$A0` | 64 kHz, 8-bit | a6 d0 r— s10 | 3 | 0.1705 | clip_11 | 1 |
| `pure_pluck` | `pokey_ref_9daa0429` | VOICE | PLAYABLE | `$A0` | 64 kHz, 8-bit | a0 d6 r2 s3 | 3 | 0.0691 | clip_06 | 2 |
| `pure_swell` | `pokey_ref_048db11d` | VOICE | PLAYABLE | `$A0` | 64 kHz, 8-bit | a12 d0 r1 s10 | 3 | 0.1650 | clip_05 | 2 |
| `buzz_steady` | `pokey_ref_2b83db43` | VOICE | PLAYABLE_WITH_LIMITATION | `$C0` | 64 kHz, 8-bit | a0 d0 r5 s9 | 3 | 0.1264 | clip_09 | 3 |
| `buzz_swell` | `pokey_ref_0bd72343` | VOICE | PLAYABLE_WITH_LIMITATION | `$C0` | 64 kHz, 8-bit | a12 d0 r— s12 | 3 | 0.2583 | clip_10 | 2 |
| `noise_hit` | `pokey_ref_2de893a6` | VOICE | PLAYABLE | `$80` | 64 kHz, 8-bit | a0 d6 r2 s2 | 3 | 0.0458 | clip_04 | 2 |
| `noise_swell` | `pokey_ref_914c63ec` | VOICE | PLAYABLE | `$80` | 64 kHz, 8-bit | a6 d0 r— s12 | 3 | 0.2586 | clip_01 | 2 |
| `gated_noise` | `pokey_ref_c0b97138` | VOICE | PLAYABLE_WITH_LIMITATION | `$00` | 64 kHz, 8-bit | a0 d4 r1 s2 | 3 | 0.0688 | clip_12 | 4 |
| `reedy` | `pokey_ref_1efd9336` | VOICE | PLAYABLE_WITH_LIMITATION | `$60` | 64 kHz, 8-bit | not measured | 3 | 0.3777 | clip_02 | 3 |
| `pair_noise` | `pokey_ref_050170ef` | PAIR | PLAYABLE | `$80` | 1.79 MHz, 16-bit pair 1+2 | a0 d4 r6 s6 | 2 | 0.0577 | clip_08 | 2 |
| `pair_buzz` | `pokey_ref_331fbbd7` | PAIR | PLAYABLE | `$C0` | 1.79 MHz, 16-bit pair 1+2 | a0 d3 r2 s2 | 2 | 0.0678 | clip_07 | 2 |

"Limit codes" is the count of published limitation + consumer-gap codes, recorded for transparency;
`GESTURE_NOT_RENDERABLE_BY_CONSUMER` appears on 60 of the 67 profiles, so it does not discriminate.

`ch` is the channel the clip actually sounds on: **3** for a VOICE profile, **2** for a PAIR profile
(the audible member of the joined pair, which occupies CH1+CH2). A profile's own `audible_channel`
field records the channel of its *source recording* and is not used — that is the `binding.py`
contract: the profile supplies the clock, the composition supplies the channel.

The full rationale for each candidate — why it was selected, what makes it audibly different, its
hypothesised musical role, its compromises and why it deserves an audition despite them — is in
`candidates.json` (`shortlist`). The generator byte names are the AUDC distortion families:

| byte | family | in this set |
|---|---|---|
| `$00` | poly5-gated poly9/17 — gated noise | `gated_noise` |
| `$40` | poly5-gated poly4 — gated ring | `c1_octave_pulse` (not in the bank) |
| `$60` | poly5-gated pure — reedy | `reedy` |
| `$80` | poly9/17 direct — ungated noise | `noise_hit`, `noise_swell`, `pair_noise` |
| `$A0` | pure tone — square | `pure_sustain`, `pure_pluck`, `pure_swell` |
| `$C0` | poly4 direct — buzz | `buzz_steady`, `buzz_swell`, `pair_buzz` |

Six of the six generator families the project can currently realize are represented. `$40` is absent
from the bank entirely, which is why C1 is genuinely a new timbre rather than a re-parameterisation.

### Why the other 55 profiles were not selected

Facts, then judgement:

* **6 `MEASUREMENT_ONLY` profiles** — the publishing audit says they describe no sound (`volume.peak_level` 0). Excluded by the bank's own verdict; the binding would refuse them.
* **The rest are largely near-duplicates on the axes that reach the render.** The largest single identical tuple covers 10 `$A`/`$00` profiles, and there are only 37 distinct tuples across 61 renderable profiles. Selecting more would have produced different *names* for the same *sound*, which the brief forbids.
* **Articulation variants were picked one per family, not all of them.** `$A0` has nine PLAYABLE profiles with distinct envelopes; three were kept because they differ in the way a musician would notice — steady, plucked, swelling. The other six differ only in decay/release frame counts of 1–2 frames and were dropped as sub-perceptual.
* **Better-supported profiles won ties.** Where two share a generator and a similar envelope, `PLAYABLE` beat `PLAYABLE_WITH_LIMITATION`, and a measured envelope beat an unmeasured one.
* **The `$C`/`$00` family has no `PLAYABLE` member at all** — all four are `PLAYABLE_WITH_LIMITATION`. One was kept (`buzz_steady`) because poly4 is a whole generator family and dropping it would leave the buzz character unheard.
* **`gated_noise` and `reedy` are the weakest-supported candidates** and are included deliberately: each is the only representative of its generator family (`$00` has no PLAYABLE member; `$60` has exactly one member in the whole bank). Both have unmeasured envelopes, so the composer's default articulation is used and the generator is the whole of the profile's contribution. They are here so those families can be *rejected by listening* rather than discarded unexamined.
* **Profile IDs were preserved exactly.** No source profile was renamed and nothing in the bank was modified.

### Two shortlisted profiles were refused, and were replaced rather than clamped

| profile | generator | measured attack | outcome |
|---|---|---|---|
| `pokey_ref_d172d15e` | `$A0` | **42 frames** | `PROFILE_ENVELOPE_OUT_OF_RANGE` |
| `pokey_ref_686d2070` | `$80` | **25 frames** | `PROFILE_ENVELOPE_OUT_OF_RANGE` |

`IREnvelope.attack_frames` is bounded to 0..15 and `_plan_envelope` raises rather than truncating. Both
are `PLAYABLE` and were shortlisted as the bank's two slowest attacks. They were **replaced** by
`pure_swell` (attack 12, the longest expressible in `$A0`) and `noise_swell` (attack 6, the longest
expressible in `$80`) — not clamped, and not rendered with a substitute envelope. The refusals are
recorded under `refused_profiles`, and the test suite re-runs the refusal live.

This is a real limit on the bank: **the project's two most interesting slow attacks cannot currently
be rendered at all.**

---

## 3. The test grid

Identical to Experiments 26/27/28, so a candidate can be compared directly against the C1 reference the
owner has already heard.

| group | notes | rows | frames | seconds |
|---|---|---|---|---|
| `note` | a single held A-4 | 12 | 48 | 0.96 |
| `phrase` | A-4, C-5, E-5, C-5 — 5 rows each | 20 | 80 | 1.60 |
| `phrase_low` | the same phrase an octave lower | 20 | 80 | 1.60 |

`BPM 125` gives `frames_per_tick = 4`, so one row is 20 ms. Every candidate plays the same pitches with
the same onsets and the same durations.

**No rests were added.** The brief allows them "where useful", but changing the grid would have broken
comparability with the C1 reference the owner already judged, and the phrase's 5-row notes already
restart often enough to expose attack and decay. The single held note covers the sustained case.

All clips are 44 100 Hz, 16-bit, mono.

---

## 4. Rendering policy and gain

### Rendering

* **Bank candidates** go through the production path, unmodified:
  `load_composition_dsl` → `generate_music_from_composition` → `apply_profile_binding` →
  `ir.compile_ir_to_pokey_frames` → Experiment 26's `render_registers`. Nothing is substituted,
  repaired or re-implemented.
* **C1** is the production compile of the same grid with Experiment 28's `apply_c1` applied to CH3, so
  the octave-pulse effect is Experiment 27's own register generation. It is the only candidate produced
  by a post-compile transform rather than a binding, and that difference is stated rather than hidden.
* **`volume_contour` is OFF.** It is opt-in, off by default in production, and `mads_exporter` refuses
  to export a song while one is set — so a timbre that *depended* on its contour could not ship. The 58
  profiles that carry a contour are recorded as carrying one; none of them is exercised here.
* **A VOICE candidate plays on CH3; a PAIR candidate plays on CH1+CH2 with `BASS 16BIT`.** That
  difference is the profile's channel requirement, not a rendering choice, and both forms are a single
  voice with identical notes.

### Gain

One shared gain, Experiment 26's policy unchanged: every clip is rendered raw, **one** gain is derived
from the single loudest of the 36 raw renders (reference peak `1.76`), and that gain (`0.51136364`) is
applied to all 36. **No clip is normalised on its own.** The loudest clip peaks at the target 0.90 and
nothing clips.

The resulting loudness spread is large and is published rather than flattened:

> **18.3 dB between the quietest and the loudest clip** (`noise_hit` 0.0458 → `reedy` 0.3777).

That comes from the profiles' own measured envelopes: a percussive profile decaying to sustain 2 is
quiet most of the time, a sustained one is loud throughout. It is real information about using these as
a library *together* — they are not level-matched — so the per-clip RMS is in `manifest.json`, in the
listening README, and the page tells the listener to expect it. This is the one respect in which the
audition is inconvenient: a listener may need to adjust volume between clips.

---

## 5. The listening interface

`experiments/experiment29/listening/index.html` — one file, no server needed, no network access
(verified: no `fetch`, `XMLHttpRequest`, `sendBeacon` or `WebSocket` anywhere in it).

* one card per clip, labelled with a neutral clip id only;
* grouped by test figure, so equivalent material is compared side by side;
* **1–5 ratings** for musical usefulness, character interest and annoyance, each with end labels;
* one question per clip: *a musical instrument / both / an effect / a fault*;
* one preference question per group (*which would you actually use*, *which is least usable*), plus a
  group comment;
* one whole-set question (is the library diverse enough) plus a comment;
* CSV export with correctly quoted and escaped fields, `localStorage` persistence, and a reset button.

The candidate order is **shuffled inside each group** with a seeded RNG (`SEED = 29`); the three groups
therefore have three different orders, and no candidate sits in the same position in two groups. The
clip → candidate mapping is in `manifest.json` and nowhere else.

### Blinding, honestly

**This is partially blinded, not fully blind.** The page's questions are family-neutral and the page
contains no candidate name, no profile id and no generator byte (verified by test). But:

* the clip count reveals how many candidates there are;
* `manifest.json` maps every clip, and the README describes the sound families and roles — a listener
  who reads either before answering is no longer blind;
* `phrase_low` is an octave below `phrase`, so the pitch content is known.

What *is* hidden is the one thing that matters: which sound is which candidate, and which is C1.

### The exact clip → candidate mapping

| group `note` | | group `phrase` | | group `phrase_low` | |
|---|---|---|---|---|---|
| clip_01 | `noise_swell` | clip_13 | `pair_noise` | clip_25 | `c1_octave_pulse` |
| clip_02 | `reedy` | clip_14 | `c1_octave_pulse` | clip_26 | `reedy` |
| clip_03 | `c1_octave_pulse` | clip_15 | `gated_noise` | clip_27 | `pair_noise` |
| clip_04 | `noise_hit` | clip_16 | `noise_hit` | clip_28 | `pure_sustain` |
| clip_05 | `pure_swell` | clip_17 | `buzz_steady` | clip_29 | `buzz_steady` |
| clip_06 | `pure_pluck` | clip_18 | `pure_pluck` | clip_30 | `pair_buzz` |
| clip_07 | `pair_buzz` | clip_19 | `reedy` | clip_31 | `buzz_swell` |
| clip_08 | `pair_noise` | clip_20 | `pair_buzz` | clip_32 | `gated_noise` |
| clip_09 | `buzz_steady` | clip_21 | `buzz_swell` | clip_33 | `noise_hit` |
| clip_10 | `buzz_swell` | clip_22 | `pure_swell` | clip_34 | `pure_swell` |
| clip_11 | `pure_sustain` | clip_23 | `noise_swell` | clip_35 | `pure_pluck` |
| clip_12 | `gated_noise` | clip_24 | `pure_sustain` | clip_36 | `noise_swell` |

The C1 reference is `clip_03` (note), `clip_14` (phrase) and `clip_25` (phrase_low). **Do not read this
table before answering.**

---

## 6. Reproducing

```bash
# render the 36 clips, the page, the manifest, the reports and the CSV templates
python -m atari_music.pokey_timbre_library_experiment

# the tests
python -m pytest tests/test_pokey_timbre_library_experiment.py -q

# the regression sweep for the earlier experiments
python -m pytest tests/test_pokey_timbre_experiment.py tests/test_pokey_octave_pulse_experiment.py \
                 tests/test_experiment27_listening_page.py \
                 tests/test_pokey_c1_musical_context_experiment.py -q

# audition it
python -m http.server 8734 --directory experiments/experiment29/listening
# then open http://localhost:8734/
```

Output is deterministic: the same command reproduces all 36 WAVs and all four documents byte for byte
(asserted by `TestDeterminism::test_two_runs_produce_identical_bytes`).

### Artefacts

| path | what it is |
|---|---|
| `experiments/experiment29/manifest.json` | the machine record **and the clip → candidate key** |
| `experiments/experiment29/candidates.json` | the 67-profile inventory plus the shortlist rationale |
| `experiments/experiment29/README.md` | the listener-facing instructions |
| `experiments/experiment29/listening/index.html` | the audition page |
| `experiments/experiment29/listening/audio/clip_01..36.wav` | the clips |
| `experiments/experiment29/listening/evaluation_experiment29_clips.csv` | the per-clip answer template |
| `experiments/experiment29/listening/evaluation_experiment29_summary.csv` | the per-listener template |
| `src/atari_music/pokey_timbre_library_experiment.py` | the experiment code |
| `tests/test_pokey_timbre_library_experiment.py` | the tests |
| `docs/experiment29_curated_timbre_candidates.md` | this report |

---

## 7. Tests and validation

```
python -m pytest tests/test_pokey_timbre_library_experiment.py -q
# 73 passed

python -m pytest tests/test_pokey_timbre_experiment.py tests/test_pokey_octave_pulse_experiment.py \
                 tests/test_experiment27_listening_page.py \
                 tests/test_pokey_c1_musical_context_experiment.py \
                 tests/test_pokey_timbre_library_experiment.py -q
# 267 passed

python -m pytest tests -q
# 2010 passed, 2 deselected
```

The E26–E28 guards needed a test-only change, exactly as they did when Experiment 28 was added: their
"no production module imports the prototype / the experiment" tests exclude experiment modules by name,
and Experiment 29 reuses E26's renderer and E28's `apply_c1` by design. Four exclusion sets gained
`pokey_timbre_library_experiment.py`; no assertion was weakened and no production file was touched.

What the suite pins, beyond the obvious:

| area | what is asserted |
|---|---|
| inventory | 67 rows; `VOICE` 49 / `PAIR` 18; `PLAYABLE` 22 / `PLAYABLE_WITH_LIMITATION` 39 / `MEASUREMENT_ONLY` 6; 61 renderable; 37 distinct audible signatures; every row carries every declared field |
| selection | 12 unique candidates; 11 distinct profile ids; C1 present as the reference; every bank candidate renderable; ≥5 generator families and both hardware configurations covered; every candidate documents all nine rationale fields |
| refusal | the two refused profiles are **re-run live** through the production binding and must still raise `PROFILE_ENVELOPE_OUT_OF_RANGE`; they are absent from the shortlist; all 6 `MEASUREMENT_ONLY` profiles are excluded |
| clip plan | 36 clips; deterministic; 12 candidates per group; three distinct orderings |
| rendering | every clip is the grid length; **the AUDC generator nibble equals the profile's `distortion_byte` exactly**; the AUDCTL byte equals the profile's `audctl_mode`; VOICE on CH3 with AUDCTL `$00`; PAIR on CH2 with AUDCTL `$50`; C1 uses `$40` and more than one divider; no clip silent |
| no substitution | the stream's generator is compared for equality, so a fallback generator would fail |
| no contour | every bound instrument's `volume_contour` is `None` |
| gain | the WAV bytes equal `to_int16(raw, shared_gain)` for **every** clip; the gain is the loudest raw render; the loudest clip reaches the target peak; peaks differ (so nothing was normalised per file); the 18.3 dB spread and the per-candidate RMS table are present in the README |
| blinding | the page contains no candidate name, no profile id and no generator byte; the embedded package has exactly the keys `audio`/`clip`/`score`; the mapping appears only in the manifest; both CSV templates are candidate-free |
| page | complete document; 3 scales + 1 choice per clip; 2 group questions; 1 overall question; **both `<script>` blocks pass `node --check`**; no network API present; `localStorage` present |
| templates | headers equal the page's `clip_fields` / `summary_fields`; 36 clip rows in plan order; one blank summary row |
| determinism | two independent renders give byte-identical WAVs, manifest, candidates, README and page |
| production untouched | no non-experiment module under `src/atari_music` mentions the experiment; the CLI mentions neither `timbre_library` nor `experiment29`; `ir.py` contains no candidate name; the page references no production module |

The regression sweep for the earlier experiments was run too and is unchanged.

**Passing tests are not evidence of good sound.** Nothing in the suite evaluates timbre — by design.
The only claim the tests support is that the comparison is *controlled and honest*: same notes, same
gain, the profile's own parameters, nothing substituted, the mapping hidden.

---

## 8. Known limitations and unresolved questions

**Limitations**

1. **The shortlist is a selection on the fields that reach the render, not on listening.** That the twelve are audibly distinct is the hypothesis the page tests, not a finding. Two candidates with different generators might still sound alike; two `$A0` candidates might sound more alike than their envelope numbers suggest.
2. **The engine renders much less than the bank measures.** A profile's measured pitch gesture, measured distortion changes and measured volume contour are all dropped or not applied. A candidate can therefore sound considerably plainer here than the recording it came from — this is the single biggest gap between the bank and the audition.
3. **The volume contour is off**, so a candidate whose character lived mostly in its contour will sound weaker here than in its source.
4. **The project's two slowest attacks cannot be rendered at all** (42 and 25 frames vs the composer's 15-frame field). They were replaced, not clamped.
5. **A PAIR candidate occupies both channels of pair 1+2**, so no two PAIR candidates could sound at once. That is a real constraint on a library built from these.
6. **A VOICE and a PAIR candidate are not interchangeable** — they need different AUDCTL, so a composition cannot use both without the 16-bit flag being on for the whole song.
7. **An 18.3 dB loudness spread** means the audition is not level-matched; a listener may need to adjust volume, which is a known bias risk.
8. **Three short test figures are not music.** Experiment 28 exists precisely because a timbre that survives an isolated figure can still fail in a tune.
9. **One listener, one session.** Any preference is preliminary.
10. **Partially blinded** (see §5).

**Unresolved questions this experiment deliberately does not answer**

* Which candidates are audibly distinct — only listening can say.
* Whether any candidate is worth registering as an instrument. Instrument registration is a separate,
  explicitly-scoped decision that this experiment does not begin.
* Whether C1's success in Experiment 28 extends to any of the bank candidates in a real composition.
  The bank candidates were never put into one; that would be a further experiment.
* Whether the 18.3 dB spread is a property of the profiles or of the envelope mapping — a profile's
  *measured* source loudness and its *rendered* loudness are not the same thing, and that gap is not
  analysed here.

---

## 9. Hard constraints — confirmation

| constraint | status |
|---|---|
| no change to production DSL, IR, compiler, exporter, 6502 player or CLI | **met** — no production file edited; asserted by test |
| candidates not registered as production instruments | **met** — no instrument list, table or enum mentions them |
| no new production instrument-mapping system | **met** — the shortlist is a module constant, not a mapping |
| no change to instrument identifiers or volume parameter semantics | **met** |
| no SAP archaeology, no new broad research stage | **met** — the bank was read, not re-measured |
| no arbitrary C1 variants | **met** — C1 appears once, as the reference |
| not all 67 profiles auditioned before screening | **met** — 61 assessed, 12 selected, 55 excluded with reasons |
| no unsupported pitch gesture implemented by silently changing the sound | **met** — refused profiles were replaced, not repaired |
| unrelated code untouched | **met** |
| reproducible and isolated | **met** — one command, byte-identical output, no production import |

**Stopping here.** The audition set is delivered and the owner can now choose which sounds deserve
further development. No candidate has been integrated, no instrument has been registered, and
Experiment 30 has not been started.







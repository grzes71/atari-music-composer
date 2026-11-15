# Experiment 30 — a musical A/B evaluation of four POKEY timbres

**Status:** delivered, awaiting the listening verdict. No production behaviour changed, no candidate
registered as an instrument, no bank profile modified, no E26–E29 artefact touched.

Experiment 29 screened twelve candidates and handed over a blind page. This experiment takes the four
worth a closer look, puts them into **two contexts** on the **same notes**, and — because Experiment 29
showed an 18.3 dB level spread that could easily have driven the ratings by itself — delivers each clip
in **two loudness versions**, so the timbre question is separated from the loudness question.

**Stop condition:** the audition set. Which of these four belongs in a library is your listening
decision, and this report deliberately does not make it for you.

---

## 1. What you listen to, and in what order

**Open `experiments/experiment30/index.html` in a browser.** No server is needed. Nothing is uploaded;
answers stay in the browser until you download them.

Listen in this order:

| # | files | why |
|---|---|---|
| 1 | `audio/solo_matched_*.wav` (4) | the timbre on its own, loudness already equalised — the cleanest read on character |
| 2 | `audio/solo_original_*.wav` (4) | the same four at their natural levels, so you can see whether the level changed your mind |
| 3 | `audio/composition_matched_*.wav` (4) | the same timbres on a real tune, loudness equalised |
| 4 | `audio/composition_original_*.wav` (4) | the same, at natural levels |

The page presents them as two blocks (Solo, Composition) with four cards each, labelled **A–D**, and
two players per card. Judge the **matched** row first; the original row is there to test whether the
level is doing the talking.

**The letters**

| letter | candidate | source |
|---|---|---|
| **A** | `pure_sustain` | bank profile `pokey_ref_25f94201` |
| **B** | `c1_octave_pulse` | Experiment 26/27 variant C, applied through Experiment 28's `apply_c1` |
| **C** | `buzz_steady` | bank profile `pokey_ref_2b83db43` |
| **D** | `pure_pluck` | bank profile `pokey_ref_9daa0429` |

The letters come from a seeded shuffle (`SEED = 30`), so they carry no ordering information — C1 is not
"A". **Do not read this table before listening.**

---

## 2. The composition and the part

**Composition:** `examples/songs/Vaults-of-Nhyrmeth.dsl`, unchanged — pinned by SHA-256
`cb93bef054afbea9b7b4e96528d7ba41aa26b0472783b2e3c7f83f52b419ad36`, asserted in the test suite and in
validation check 8.

Why this one: it is the project's own documented example and a test fixture, so its provenance is
internal rather than a copied commercial melody. It has a recognisable lead melody, a 16-bit bass and
percussion, at 90 BPM over 2280 frames (45.6 s) — dense enough to be a real tune, open enough that a
timbre change on the lead is audible.

**Part: CH3, the lead.** It is the only melodic part, it is a single 8-bit voice so a candidate is the
whole of its sound, and it sits above the 16-bit bass and the noise percussion rather than under them,
so a timbre change does not need the part to be made louder to be heard.

**Why the bass was left alone.** None of the four candidates is a PAIR profile, so touching CH1+CH2
would have changed the arrangement — a 16-bit configuration swap — for no reason. The 16-bit bass, the
percussion, the tempo, the structure and the length are identical in all four variants, and that is
asserted at register level, not merely claimed.

**A detail that made this possible.** The DSL declares its instruments by `character` only:

```
INSTRUMENT bass character=bass
INSTRUMENT lead character=bright_lead
INSTRUMENT perc character=percussion
```

No explicit `distortion=`, no explicit envelope. `binding.py` refuses a *partial* override ("a profile
is one coherent register configuration, so a partial override is refused rather than merged"), so if
the DSL had pinned the generator, `buzz_steady` (`$C0`) would have been refused outright and
`pure_sustain`/`pure_pluck` could not have brought their envelopes. Nothing in the composition was
edited to make this work.

### The solo figure

A dedicated 90-row figure at the same tempo (450 frames = 9.0 s):

```
A4/20  R/2  D4/6 E4/2 F4/4 G4/4 A4/8 D5/4 C5/4 Bb4/6 C5/2  A4/4 F4/4 G4/4  A4/4 D4/4 A3/8
```

A held A-4 for 2.0 s (single-note character and the whole envelope shape), a rest so the release is
audible rather than cut off, then **the composition's own opening lead motif**, a short descent, and a
tail to A-3. Range A-3 to D-5 — 17 semitones — so both the single sound and the behaviour under pitch
change can be judged. Using the composition's own motif lets you carry an impression from the solo
block straight into the composition block.

---

## 3. The four variants, and exactly what was applied

Read back from the same objects the renderer consumes, so this table cannot claim a parameter the
renderer never saw. All four play on **CH3**; AUDCTL is `$10` in the composition and `$00` in the solo,
in every variant.

| candidate | generator | attack | decay | release | sustain | envelope source | profile |
|---|---|---|---|---|---|---|---|
| `pure_sustain` | `$A0` | 6 | 0 | 2 | 10 | profile (release: composition default) | `pokey_ref_25f94201` |
| `pure_pluck` | `$A0` | 0 | 6 | 2 | 3 | profile | `pokey_ref_9daa0429` |
| `buzz_steady` | `$C0` | 0 | 0 | 5 | 9 | profile | `pokey_ref_2b83db43` |
| `c1_octave_pulse` | `$40` + pulse | 1 | 3 | 2 | 13 | **composition default** | — |

### The one honest asymmetry

The three bank profiles bring their **own measured envelope** — the composition leaves those fields
open, so the profile supplies them. C1 does not: `apply_c1` is a post-compile register transform that
keeps the composition's articulation and changes only the generator and the divider.

So "the timbre" of a bank variant includes its articulation, and C1's does not. That is what each
candidate actually *is*, it is recorded field by field in `manifest.json`
(`applied_parameters.*.envelope_sources`), and the test suite pins it
(`test_the_c1_asymmetry_is_recorded_not_hidden`). It is not hidden, but it is a real difference between
the variants and you should know about it while listening.

Also worth stating: `pure_sustain`'s profile does not measure a release frame, so that one field falls
back to the composition's default. The table shows it.

### Register-level proof that only the lead changed

| context | candidate | frames changed | columns changed |
|---|---|---|---|
| solo | `pure_sustain` | 440 / 450 | **AUDC3 only** |
| solo | `pure_pluck` | 424 / 450 | **AUDC3 only** |
| solo | `buzz_steady` | 440 / 450 | **AUDC3 only** |
| solo | `c1_octave_pulse` | 440 / 450 | **AUDF3 + AUDC3** |
| composition | `pure_sustain` | 2220 / 2280 | **AUDC3 only** |
| composition | `pure_pluck` | 2121 / 2280 | **AUDC3 only** |
| composition | `buzz_steady` | 2220 / 2280 | **AUDC3 only** |
| composition | `c1_octave_pulse` | 2220 / 2280 | **AUDF3 + AUDC3** |

Every other column — CH1/CH2 (the 16-bit bass), CH4 (percussion), the AUDCTL byte, and every frame
outside the lead's sounding notes — is **byte-identical** to the baseline. Rests and zero-volume frames
are untouched. The three bank variants leave the divider alone; only C1 moves it, which is what the
octave pulse is.

---

## 4. How the loudness was equalised

### The measurement

No loudness library is installed (no `pyloudnorm`, no `scipy`, no `soundfile` — only numpy), so the
matching target is an in-repo implementation of **ITU-R BS.1770-4 K-weighted integrated loudness
(LUFS)**: the high-shelf pre-filter and the RLB high-pass from their analog prototypes, 400 ms blocks
at 75 % overlap, absolute gating at −70 LUFS and relative gating at −10 LU.

It is not an approximation, and that is verified rather than asserted:

* the coefficients reproduce **BS.1770-4 Table 1's published 48 kHz values** to 1e-12;
* the meter reads a 997 Hz sine at **−20 dBFS RMS as −20.0 LUFS** — the standard's own calibration
  point, which holds because the K-weighting's +0.694 dB at 997 Hz cancels the −0.691 offset;
* a level change of ×0.5 reads as exactly −6.02 LU.

All three are asserted in `tests/test_pokey_timbre_ab_experiment.py`.

Plain **RMS and sample peak are also published for every file** in `summary.json` and
`manifest.json`, so nothing rests on the LUFS figure alone. Sample peak is used for the ceiling, not
true peak — no oversampling is done — and that is stated as a limitation.

### The two sets

**Original** — one shared gain per context, from the loudest raw render in that context. No clip is
normalised on its own, so the loudness relation between the four timbres survives. Two gains rather
than one because the composition sums three voices and the solo is one, and the two blocks are listened
to separately; a single gain across both would have pushed the solo block ~6 dB down for no
informational gain.

**Matched** — one gain per clip, bringing all eight to a single measured loudness. The target is the
median clip loudness, **capped by the loudest level any clip can reach without its peak crossing
0.90**. That cap is what guarantees no clipping.

Matching is a **scalar gain on the rendered audio**. No envelope, pitch, rhythm or generator parameter
is touched — asserted by `test_matching_changes_only_the_gain`, which checks that the delivered WAV
equals the raw buffer times the published gain, bit for bit.

### Why the matched set is quieter than you might expect

The cap is set by one clip: **`solo:pure_pluck`** (letter **D** in the solo block). It is intrinsically
peaky — a sharp attack over a low sustain, so its transients reach full scale while its average level
stays low. Matching it *up* to the others would have clipped it. So the whole matched set sits at
−19.65 LUFS and **you will need to raise the volume** for those files. That is the price of matching
without limiting or compressing, which this experiment does not do.

---

## 5. Levels before and after

### Before any matching — the raw renders

| clip | peak | LUFS | RMS dBFS | ceiling at peak 0.90 |
|---|---|---|---|---|
| `composition:c1_octave_pulse` | 2.9185 | −0.42 | −1.86 | −10.64 |
| `composition:pure_sustain` | 2.3256 | −6.77 | −5.67 | −15.02 |
| `composition:buzz_steady` | 2.9715 | −7.29 | −6.60 | −17.67 |
| `composition:pure_pluck` | 3.0191 | −8.58 | −6.98 | −19.09 |
| `solo:c1_octave_pulse` | 1.7600 | −1.01 | −3.03 | −6.83 |
| `solo:pure_sustain` | 1.1358 | −9.81 | −9.77 | −11.83 |
| `solo:buzz_steady` | 1.7600 | −10.93 | −12.76 | −16.75 |
| `solo:pure_pluck` | 1.7600 | −13.82 | −15.49 | **−19.65 ← the cap** |

Spread across all eight: **13.40 LU**. Within a context — the number you actually experience, because
you listen block by block: **12.82 LU solo**, **8.15 LU in the composition**.

That is a huge spread, and it is the same phenomenon Experiment 29 found: `pure_pluck` is 12.8 LU
quieter than C1 in the solo block at the same peak. Without the matched set, this experiment would have
been measuring loudness, not timbre.

### After — measured on the delivered files

| file | gain | dB | LUFS | peak | RMS dBFS |
|---|---|---|---|---|---|
| `solo_original_A` | 0.511364 | −5.83 | −15.63 | 0.5808 | −15.60 |
| `solo_original_B` | 0.511364 | −5.83 | −6.83 | 0.9000 | −8.85 |
| `solo_original_C` | 0.511364 | −5.83 | −16.76 | 0.9000 | −18.58 |
| `solo_original_D` | 0.511364 | −5.83 | −19.65 | 0.9000 | −21.32 |
| `solo_matched_A` | 0.322077 | −9.84 | −19.65 | 0.3658 | −19.61 |
| `solo_matched_B` | 0.116915 | −18.64 | −19.65 | 0.2058 | −21.67 |
| `solo_matched_C` | 0.366492 | −8.72 | −19.65 | 0.6450 | −21.48 |
| `solo_matched_D` | 0.511364 | −5.83 | −19.65 | 0.9000 | −21.32 |
| `composition_original_A` | 0.298098 | −10.51 | −17.28 | 0.6932 | −16.18 |
| `composition_original_B` | 0.298098 | −10.51 | −10.93 | 0.8700 | −12.37 |
| `composition_original_C` | 0.298098 | −10.51 | −17.80 | 0.8858 | −17.12 |
| `composition_original_D` | 0.298098 | −10.51 | −19.09 | 0.9000 | −17.49 |
| `composition_matched_A` | 0.227075 | −12.88 | −19.65 | 0.5281 | −18.55 |
| `composition_matched_B` | 0.109310 | −19.23 | −19.65 | 0.3190 | −21.09 |
| `composition_matched_C` | 0.241074 | −12.36 | −19.65 | 0.7163 | −18.96 |
| `composition_matched_D` | 0.279479 | −11.07 | −19.65 | 0.8438 | −18.05 |

* matched target: **−19.6475 LUFS**, capped by the peak ceiling, limited by `solo:pure_pluck`
* matched spread across all eight: **0.0011 LU** (int16 quantisation only)
* loudest peak anywhere: **0.899991** — nothing clips, in either set
* original gains: solo `0.5113636393`, composition `0.2980976856`

**What LUFS matching does not fix.** It equalises *measured* loudness, not *perceived* loudness. A poly4
buzz and a clean square at the same LUFS can still seem unequal. Where that happens, trust your ears and
say so in the comment field.

---

## 6. The listening page and the evaluation form

`experiments/experiment30/index.html` — one file, no server, no network access (verified: no `fetch`,
`XMLHttpRequest`, `sendBeacon` or `WebSocket` anywhere in it).

* two clearly separated blocks, **Solo** and **Composition**;
* four cards per block, labelled **A–D**, each with an **original** and a **matched** player;
* per row: 1–5 ratings for **Przydatność**, **Zainteresowanie** and **Uciążliwość**, a typical-use
  choice (melodia / bas / perkusja / efekt / inne), a "does the melody still work" choice, and a comment;
* a **reveal button** that shows the candidate names, their sources and their generators — after the
  ratings are downloaded;
* CSV export with correctly quoted and escaped fields, `localStorage` persistence, and a reset button.

`experiments/experiment30/evaluation_template.csv` is the empty template, with exactly the headers the
page downloads. **No automatic score is computed** — the brief forbids an arbitrary weighted "best
instrument", and a test asserts the module contains no such thing. The choice is yours.

### Blinding, honestly

**Partially blinded, not fully blind:**

* the page shows letters only, and the names appear in the page source solely inside the reveal block —
  a test cuts that block out and asserts no candidate name or profile id survives outside it;
* **but the same letter means the same timbre in both blocks**, so once you have heard the solo block
  you can already tell which composition variant is which. The composition block is not independently
  blind. That is a deliberate trade: consistent letters make the solo-to-mix comparison possible, which
  is the point of the experiment;
* a listener who opens the page source, or `manifest.json`, or this report, before answering is no
  longer blind at all;
* the octave-pulse reference (B) is audibly unlike the other three, so "which one is C1" is guessable
  from the sound alone.

---

## 7. Reproducing

```bash
# render the 16 clips, the page, the manifest, the summary and the CSV template
python -m atari_music.pokey_timbre_ab_experiment

# the tests
python -m pytest tests/test_pokey_timbre_ab_experiment.py -q

# the regression sweep for the earlier experiments
python -m pytest tests/test_pokey_timbre_experiment.py tests/test_pokey_octave_pulse_experiment.py \
                 tests/test_experiment27_listening_page.py \
                 tests/test_pokey_c1_musical_context_experiment.py \
                 tests/test_pokey_timbre_library_experiment.py \
                 tests/test_pokey_timbre_ab_experiment.py -q

# audition it
python -m http.server 8735 --directory experiments/experiment30
# then open http://localhost:8735/
```

Output is deterministic: the same command reproduces all 16 WAVs and all five documents byte for byte
(`TestDeterminism::test_two_runs_produce_identical_bytes`).

### Artefacts

| path | what it is |
|---|---|
| `experiments/experiment30/index.html` | the listening page — **the only file you need to open** |
| `experiments/experiment30/audio/*.wav` | 16 files: 2 contexts × 2 loudness versions × 4 letters |
| `experiments/experiment30/evaluation_template.csv` | the empty rating template |
| `experiments/experiment30/manifest.json` | every file mapped to candidate, context, version and applied parameters — **the answer key** |
| `experiments/experiment30/summary.json` | measurements and the technical validation result |
| `experiments/experiment30/README.md` | the listener-facing instructions |
| `src/atari_music/pokey_timbre_ab_experiment.py` | the experiment code |
| `tests/test_pokey_timbre_ab_experiment.py` | the tests |
| `docs/experiment30_timbre_ab_evaluation.md` | this report |

---

## 8. Tests and validation

```
python -m pytest tests/test_pokey_timbre_ab_experiment.py -q
# 79 passed

python -m pytest tests/test_pokey_timbre_experiment.py tests/test_pokey_octave_pulse_experiment.py \
                 tests/test_experiment27_listening_page.py \
                 tests/test_pokey_c1_musical_context_experiment.py \
                 tests/test_pokey_timbre_library_experiment.py \
                 tests/test_pokey_timbre_ab_experiment.py -q
# 346 passed
python -m pytest tests -q
# 2089 passed, 2 deselected
```

The E26–E29 guards needed a test-only change again, exactly as when E28 and E29 were added: their "no
production module imports an experiment" tests exclude experiment modules **by name**, and this module
imports E26's renderer and E28's `apply_c1` by design. Five enumerated sets gained
`pokey_timbre_ab_experiment.py`. No assertion was weakened and no production file was touched.

### The ten validation checks, all passing

| check | result |
|---|---|
| every variant has the baseline's frame count | pass — 2 contexts × 4 candidates |
| the melodic note grid (start, end, midi) is identical in every variant | pass — computed with `e28.channel_note_spans`, the compiler's own arithmetic |
| only the melodic channel's AUDF and AUDC columns differ from the baseline | pass — allowed columns [4, 5]; offenders none |
| AUDCTL is the baseline's in every variant | pass — composition `$10`, solo `$00` |
| every variant's AUDC generator nibble is the candidate's own | pass — `buzz_steady=$C0`, `c1_octave_pulse=$40`, `pure_pluck=$A0`, `pure_sustain=$A0` |
| no delivered file clips | pass — 16 files, offenders none |
| the matched set is level-matched to within 0.1 LU | pass — measured spread 0.0011 LU |
| the original set keeps different peaks (nothing normalised per file) | pass — solo 2 distinct peaks, composition 4 |
| `examples/songs/Vaults-of-Nhyrmeth.dsl` is unchanged | pass — sha256 `cb93bef054afbea9…` |
| the manifest maps every file exactly once | pass — 16 records |

Beyond the checks, the suite also pins:

* **the loudness meter is the standard**, not a plausible filter: published 48 kHz coefficients to
  1e-12, the −20 dBFS/997 Hz calibration point, exact −6.02 LU for a ×0.5 change, the +4 dB shelf
  plateau, gating, short-clip fallback and silence;
* **the bass and percussion columns are byte-identical** across all four composition variants, compared
  column by column rather than via the changed-column summary;
* **matching changes only the gain**: each delivered matched WAV equals the raw buffer times the
  published gain, bit for bit;
* **the measured loudness matches the prediction** (`lufs + 20·log10(gain)`) to 0.05 LU, which is what
  justifies predicting the original set's loudness analytically;
* **the C1 asymmetry is recorded**: C1's envelope sources are all "composition default", each bank
  profile's include "profile";
* **the page leaks nothing before the reveal**, both `<script>` blocks pass `node --check`, no network
  API is present, and the template headers equal the page's export headers;
* **no automatic score exists** anywhere in the module;
* **two runs are byte-identical** across all 16 WAVs and all five documents.

**Passing tests are not evidence of good sound.** Nothing in the suite evaluates timbre. The only claim
the tests support is that the comparison is *controlled and honest*: same notes, same structure, the
candidate's own parameters, one thing changed, loudness separated out, and the mapping hidden.

---

## 9. Technical limitations

1. **The C1 asymmetry** (§3). C1 keeps the composition's articulation while the bank profiles bring
   their own, so a bank variant's "timbre" includes its envelope and C1's does not. Recorded per field;
   not hidden.
2. **LUFS matching is not perceived-loudness matching.** It equalises a K-weighted measurement. A poly4
   buzz and a clean square at equal LUFS can still seem unequal.
3. **Sample peak, not true peak.** No oversampling, so inter-sample peaks are not measured. The 0.90
   ceiling leaves enough headroom that this cannot clip here, but the number is not a true-peak number.
4. **The matched set is quiet (−19.65 LUFS)**, because one clip (`solo:pure_pluck`) is intrinsically
   peaky and caps the achievable level. You will need to raise the volume. Limiting or compressing to
   avoid this would have changed the timbre, which is exactly what must not happen.
5. **Synthetic renders.** These are the POKEY register model, not hardware. That a timbre sounds good
   here does not prove the same sound is reachable on a real Atari, and nothing here is exported to a
   player.
6. **One part, one channel.** Only CH3 changes. A timbre can work on a lead and fail on a bass or in a
   denser mix; this experiment cannot say anything about that.
7. **The four candidates are a selection**, made in Experiment 29 from twelve. This experiment does not
   re-open that selection, and a good result here does not mean the other eight are worse.
8. **Partially blinded** (§6).
9. **One listener, one session.** Any preference is preliminary.

### One observation about the test guards

The "no production module imports an experiment" guard in the earlier suites excludes experiment modules
by an **enumerated list**, so each new experiment needs the same edit in five files. It would be more
robust to exclude by the pattern that defines an experiment module (`*_experiment.py`) — that is exactly
what the guard means, it cannot be bypassed by forgetting an edit, and it cannot hide a production
import. I did not change it, because touching five existing test files' logic is a larger change than
this task warrants. Worth doing separately.

---

## 10. Hard constraints — confirmation

| constraint | status |
|---|---|
| no change to the production DSL, IR, compiler, MADS exporter or 6502 player | **met** — no production file edited |
| no integration of new instruments into the production Composer | **met** — no instrument list, table or enum mentions them |
| no change to the bank profiles | **met** — the loader is used read-only; asserted by test |
| no further SAP archaeology | **met** — the bank was read, not re-measured |
| no additional candidates without a concrete reason | **met** — exactly the four the brief names |
| metadata differences not treated as proof of audible differences | **met** — the report claims nothing about audible distinctness |
| no synthetic render presented as proof of hardware behaviour | **met** — stated as limitation 5 |
| no E26–E29 artefact modified | **met** — only E26/E27/E28/E29 *test* files gained one name in an exclusion list |
| experimental implementation isolated from production code | **met** — one new module under `src/atari_music/`, imported by nothing |

---

## 11. Decision questions for you

After listening, please answer these four. The page collects the per-clip ratings; these are the
questions the ratings cannot answer on their own.

1. **Which timbre works best solo?** On the held note and the melodic figure, with loudness equalised —
   which one would you reach for first?
2. **Which works best in the composition?** The same question on the real tune, where the lead has to
   sit above a 16-bit bass and percussion.
3. **Which are worth keeping in a first library?** You do not have to pick one. Say which of A–D earn a
   place, and whether the answer differs between "solo" and "in a tune".
4. **Does any of them need more work?** For example a timbre whose character is right but whose attack,
   sustain or level needs adjusting — or one that only failed because of a limitation listed in §9.

Two optional extras that would help a follow-up: did the **original vs matched** pair change your answer
for any candidate (which, and how), and did any candidate sound like a fault rather than an instrument?

**No candidate has been integrated. Nothing is registered as an instrument. Experiment 31 has not been
started.** The next step is yours.






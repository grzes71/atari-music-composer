# Stage 10B — volume contour: the listening verdict

**VERDICT: NEGATIVE**

This report resolves the verdict that `stage10b_volume_contour_experiment.md` deliberately left
open. That report proved the *mechanical* claim — the measured contour transfers, it is the only
thing that changes, and it is inert when the feature is off — and, with nothing yet heard, closed
on `INCONCLUSIVE`; it was right to do so. The blinded sheet has since been filled in, and this
report reads it. No profile, fingerprint, schema, binding, composition, renderer, player, DSL,
composer, generator or exporter was touched, and nothing here is a production recommendation.

| | |
| :--- | :--- |
| experiment | `stage10b`, renderer `0.5.2` |
| preparation report | `docs/stage10b_volume_contour_experiment.md` (kept as written) |
| answer sheet | `examples/sound_profile_volume_contour_10b/evaluation_volume_contour_10b.csv` — 18 of 18 rows |
| machine record | `reports/stage10b/answers.json` (counts) · `reports/stage10b/listening.json` (decoded) |
| verdict | **NEGATIVE** |

## 1. The question this report answers

Stage 10B asks two things: whether the archeology's measured volume contour can be transferred into
the render, and whether that transfer makes the sound better. The preparation report answered the
first. The second was left to one blinded listening session, and the rule it fixed *before* the
listening is the rule applied here, unchanged:

| label | the stage's own condition |
| :--- | :--- |
| POSITIVE | the contour is **both audible and preferred** |
| NEGATIVE | the contour is **audible and rejected** |
| INCONCLUSIVE | the evidence is **missing or mixed** |

The comparison is B-vs-C: the same binding with and without the transferred contour. The four
A-vs-C pairs are the **control** — the contour against the composer's own default instrument — and
are reported separately because they are not evidence about the contour.

## 2. Dataset verification

**Observed.** The analysis reads exactly two files — the answer sheet and the package's private
key — and hashes them so the run is reproducible from the same bytes:

| file | sha256 |
| :--- | :--- |
| `evaluation_volume_contour_10b.csv` | `638dc932ca50884eb845b747486dbdd0e94f35796dd5015bd3ccca3bd6b080c7` |
| `manifest.json` | `04d7319f995262ded1bef418248168424725858e2634b557aa656dac272af2cf` |

| check | result |
| :--- | :--- |
| rows carrying an answer | **18 of 18** |
| ids agree with the private key | yes — set-for-set, no unknown id, no duplicate |
| choices / difference values | every choice in `a`/`b`/`none`; every difference inside 1–5 |
| raw answers modified | **no** — read only; only whitespace is trimmed |

**Observed.** The counting step is `python -m atari_music.cli analyze-volume-contour-10b`, which
writes `reports/stage10b/answers.json`. The per-trial decode in `reports/stage10b/listening.json`
is a pure function of the two files above; it makes no judgement of its own.

## 3. The counts, against the private key

**Observed.** "C" is the side that carries the contour. The two `_current_vs_contour` kinds are the
primary B-vs-C experiment; the two `_default_vs_contour` kinds are the A-vs-C control.

| trial kind | n | C chosen | other side | no clear difference |
| :--- | ---: | ---: | ---: | ---: |
| `profile_current_vs_contour` (B-vs-C) | 8 | 0 | 0 | 8 |
| `song_current_vs_contour` (B-vs-C) | 6 | 1 | 2 | 3 |
| **primary B-vs-C, total** | **14** | **1** | **2** | **11** |
| `profile_default_vs_contour` (A-vs-C) | 2 | 0 | 0 | 2 |
| `song_default_vs_contour` (A-vs-C) | 2 | 0 | 2 | 0 |
| **control A-vs-C, total** | **4** | **0** | **2** | **2** |

**Observed.** Perceptibility — "does either side change noticeably *during* a note?":

| | heard | neither |
| :--- | ---: | ---: |
| all 18 pairs | **7** | **11** |

**Observed.** Reported difference (1–5): values `1×8, 2×4, 3×5, 4×1`; **median 2**.

**Observed.** The two song controls are the only pairs where a *side* was preferred and the pair
was *not* asked about the contour: on both, the listener chose the composer's **DEFAULT**
(`song_01_t1`, `song_02_t1`). That replicates the Stage 9C/10A finding that a profile-bound render
loses to the composer's own instrument, and it is reported here only so the control is not read as a
contour result.

## 4. Every answer, decoded

**Observed.** The full decode, from `reports/stage10b/listening.json`. "Movement heard" is the
listener's own perceptibility answer, with the side it named resolved through the private key.

| trial | kind | subject | side chosen | movement heard | diff |
| :--- | :--- | :--- | :--- | :--- | ---: |
| `prof_01_t1` | A-vs-C | `pokey_ref_25f94201` | — | no | 1 |
| `prof_01_t2` | B-vs-C | `pokey_ref_25f94201` | — | no | 1 |
| `prof_02_t1` | B-vs-C | `pokey_ref_d172d15e` | — | **yes — C** | 3 |
| `prof_02_t2` | A-vs-C | `pokey_ref_d172d15e` | — | **yes — C** | 2 |
| `prof_03_t1` | B-vs-C | `pokey_ref_959628d6` | — | no | 1 |
| `prof_04_t1` | B-vs-C | `pokey_ref_9daa0429` | — | no | 1 |
| `prof_05_t1` | B-vs-C | `pokey_ref_c6eca16a` | — | no | 1 |
| `prof_06_t1` | B-vs-C | `pokey_ref_048db11d` | — | no | 1 |
| `prof_07_t1` | B-vs-C | `pokey_ref_686d2070` | — | no | 1 |
| `prof_08_t1` | B-vs-C | `pokey_ref_3c36e574` | — | **yes — C** | 2 |
| `song_01_t1` | A-vs-C | `Vaults-of-Nhyrmeth.dsl` | **DEFAULT** | no | 4 |
| `song_01_t2` | B-vs-C | `Vaults-of-Nhyrmeth.dsl` | **C** | yes — both | 3 |
| `song_02_t1` | A-vs-C | `as-1.dsl` | **DEFAULT** | yes — C | 3 |
| `song_02_t2` | B-vs-C | `as-1.dsl` | **B (no contour)** | yes — both | 3 |
| `song_03_t1` | B-vs-C | `dziki2.json` | **B (no contour)** | yes — both | 3 |
| `song_04_t1` | B-vs-C | `as-2.dsl` | — | no | 2 |
| `song_05_t1` | B-vs-C | `funky.json` | — | no | 2 |
| `song_06_t1` | B-vs-C | `koval.json` | — | no | 1 |

**Observed.** In every one of the four trials where movement was heard on a *single* named side,
that side was **C** — the side carrying the contour. On the other three audible trials the listener
reported "both". The perceptibility question therefore never once attributed the movement to the
wrong side.

## 5. What was audible — the decisive finding

**Observed.**

* On the isolated-profile B-vs-C pairs the contour was audible in only **2 of 8** — `prof_02_t1`
  and `prof_08_t1`, both heard on the **C** side — and reported as "neither" in the other **6**.
  Including the two profile controls, **3 of 10** profile pairs were audible.
* On the songs it was audible in **3 of 6** B-vs-C pairs and in **1 of 2** controls.
* Overall **7 of 18** pairs were heard to change during a note.

**Observed.** The two audible profiles are the two whose transferred contours move the level the
furthest and longest: `pokey_ref_d172d15e` — the widest span in the tested set, measured level 2..11
over 45 frames (mean 10.8 → 3.0) — and `pokey_ref_3c36e574`, the longest gesture, 150 frames
(12.9 → 10.0). The six inaudible profiles are narrower and shorter.

**Inference.** Audibility tracks how much of the level range, over how long, the measurement actually
uses — not whether the mapping is correct, which the preparation report proved frame-for-frame. Two
profiles is far too few to make that a rule, and one counter-example sits next to it: `pokey_ref_048db11d`
(`prof_06`) drops the mean level by more than `pokey_ref_3c36e574` does, yet `prof_06` was inaudible.
So the honest statement is narrow: on this listener's report the transfer reached the ear on the deep,
wide, long contours and not on the shallower ones, and no single number predicts it cleanly.

**Inference.** This is the decisive finding for the verdict. The mapping is faithful and the *shape*
is real (preparation report §8); what failed is perceptibility — on the class the mapping was designed
around, a single sustained note carrying one slow measured swell, the contour reached the ear in only
a quarter of the trials.

## 6. What was preferred — the contour's own evidence

**Observed.** Restricted to the seven pairs in which the contour was audible, so that a preference
could be *about* the contour:

| | C preferred | other preferred | no clear difference |
| :--- | ---: | ---: | ---: |
| the 7 audible pairs | **1** | **3** | **3** |

**Observed.** On the 14 primary B-vs-C pairs (heard or not): C **1**, the no-contour side **2**, no
clear difference **11**.

**Inference.** The direction is negative and it does not depend on reading the inaudible pairs as
evidence: among the pairs where the contour was unmistakably present, it was rejected (3) more often
than it was preferred (1). The single win — `song_01_t2` — is one pair on the same material where the
other two audible pairs preferred no contour.

## 7. Observation, inference, choice

**Observed** (measurements and the artefacts' own content): the sheet's 18 rows and their hashes;
the counts per kind; the perceptibility answers and the side they name; the reported differences;
the fact that the two A-vs-C song controls both chose the composer's default.

**Inference** (what follows): the contour reached the ear on the deepest, widest, longest contours —
two of the eight sustained single-note profiles and three of the six whole songs — and nowhere else;
where it was audible it was not preferred; the control reproduces the known default-over-profile
result rather than speaking to the contour.

**Experimental choice** (nothing forces it): the three-label rule and its thresholds; treating the
A-vs-C pairs as controls rather than as evidence; reading "no clear difference" as *no preference*
rather than as a rejection; and calling the *whole* stage NEGATIVE when its own per-trial condition
is "audible and rejected" and most trials were inaudible. Each is argued in §8 so it can be
contested.

## 8. The verdict

**Experimental choice.** The three labels are applied exactly as the preparation report fixed them —
before any answer existed — and the whole stage is read against the question it asked: *does
transferring the contour make the sound better?*

**Observed.** POSITIVE is excluded by the rule and needs no argument: the condition is *both audible
and preferred*, and the contour was preferred once in fourteen primary pairs and once against three
rejections in the audible subset.

**Inference.** INCONCLUSIVE is excluded because its condition — evidence that is *missing or mixed* —
is not met. The evidence is complete (18 of 18 pairs, the perceptibility question answered on every
one), and it does not reverse by slice: the contour wins no majority in any cut of the data —
1–2–11 on the primary pairs, 1–3–3 on the audible ones, 0–8 on the isolated profiles. Its single win
is offset by two losses on the same material.

**Experimental choice.** The one genuinely contestable step is this: the stage's NEGATIVE condition
is "audible **and** rejected", yet most trials were *inaudible*. This report still returns NEGATIVE,
on the ground that the stage's question is about a perceptual feature, and a feature that its own
dedicated test could not reach the ear with, and that was not preferred where it did reach it, has
not succeeded. INCONCLUSIVE would treat the inaudible trials as missing data; they are not missing —
"inaudible" is a result about the feature itself, not a gap in the evidence. A reader who disagrees
should read this as the *decidable* label whose condition is satisfied wherever audibility existed,
not as a claim that every trial rejected the contour.

> **VERDICT: NEGATIVE.**

Measured against the bank, the mapping and this session, the volume-contour transfer did not make the
rendered sounds better. It was audible in only 2 of the 8 isolated-profile pairs and 3 of the 6
whole-song pairs, and wherever it was audible it was rejected (3) more often than preferred (1).

**Inference — what this does not settle.** The verdict is *that* the transfer did not help, not *why*.
Three readings remain, and the data does not choose between them:

| reading | what would support it |
| :--- | :--- |
| the mapping is right, the material is wrong | the transfer is faithful (it is), but most of the bank's *transferable* contours are too shallow to be heard on one held note — only two of the eight tested were |
| the swell is not the interesting part of the measurement | the audible cases were the *deepest* contours; what a listener would notice — fast tremolo, gating — is exactly what 10B refused or the frame grid cannot carry |
| the transfer works but sounds worse | where the contour was audible it was rejected, so making it *more* audible is not obviously the fix |

Separating these is the work of a later stage, not this one.

## 9. Limitations

* **One listener, one session.** Every answer is a single observation; nothing here is a population
  estimate, and there is no inter-listener agreement to report.
* **Small n.** 14 primary pairs, of which only 5 were audible — the audible-subset tallies (1–3–3) are
  directions, not rates. Six songs are not a population.
* **The tested set is one class, not the whole bank.** The isolated profiles are the swell/step class
  only: the gating contours (the deepest, most mobile) and the tremolo class were refused or exceeded
  the frame grid (§6/§12 of the preparation report). The profile result is a statement about that
  class, not about the mechanism's ceiling.
* **Song contours are decimated.** Their 18–42 Hz source changes exceed the 50 Hz frame grid, so
  variant C is a weakened reading of the measurement; the song result is a result about the
  *decimated* transfer.
* **Anchoring cannot be excluded.** Variant B was Stage 10A's binding, heard minutes earlier in the
  previous package.
* **"No clear difference" is not a rejection.** It is counted as *no preference*: a listener who could
  not hear a difference cannot express one, and this report does not turn that into a vote against
  the contour.
* **The controls are a sanity check, not contour evidence.** Their two DEFAULT wins (§3) reproduce the
  earlier default-over-profile result and say nothing about the contour.

## 10. STOP condition

**STOP.** The listening verdict is recorded, and nothing follows from it in this stage:

* no change to the library, the bank, any profile, fingerprint, schema or binding;
* no change to the volume-contour mapping, `IRInstrument.volume_contour`, the frame compiler or the
  renderer;
* no change to the DSL, the composer, the generator, the player or the MADS/XEX exporter — `build-xex`
  still refuses a contoured song rather than diverging from the WAV;
* no promotion of the feature into the authoring path;
* the answer sheet, the listening package and the preparation report are left as they were
  (hashes in §2).

Waiting for the brief's next instruction. The questions the verdict raises — a policy for gating
contours, testing the tremolo class, and whether a *more audible* contour is wanted at all — are
named here, not started.

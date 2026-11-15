# Stage 13A — pitch trajectory perceptual experiment

**VERDICT: INCONCLUSIVE**

Does the temporal pitch behaviour measured inside a real POKEY sound contain transferable information that improves a new Composer-generated sound? This experiment answers the technical half exactly and prepares the perceptual half. The production IR, player and renderer are untouched: the trajectory is applied as an offline rewrite of one note's AUDF column.

* experiment: `stage13a` (`stage13a/1`)
* variants: A STATIC · B PROFILE_STATIC · C PROFILE_TRAJECTORY · D CONTROL_TRAJECTORY
* cases: **8** usable of 8 (0 technical failures)
* bounded trajectories in the bank: **14** of 46 non-static series
* listening package: **prepared** (15 trials)

**Observed / Inference / Experimental choice** are kept apart throughout.

## 1. Reconnaissance (Part 1)

**Observed.** 67 profiles. Representation: `semitones_from_base` ×67; unit `semitones_relative_to_base_hz` ×67; quantization 0.01 semitones ×67.

**Observed.** Gesture pitch: **21** static, **46** non-static with runs; behaviours drifting ×2, static ×22, stepped ×40, vibrato ×3; directions falling ×16, mixed ×20, rising ×10, static ×21.

**Observed — the finding that shapes the whole stage.** Only **14** of the non-static series stay within one octave of their base; **32** leave it, by up to 96 semitones. Those excursions are divider/pair register artifacts, not pitch, so they are excluded from case selection. (Context: the binding reads 13 of 232 documented paths and never reads gesture.pitch (Stage 9E): pitch is carried by the profile and used by nothing.)

## 2. What "pitch trajectory" means here (Parts 2, 5)

**Experimental choice.** The trajectory is the profile's `gesture.pitch.runs`, expanded verbatim to one semitone delta per VBL frame, and re-based on the Composer's note with the representation Stage 5 validated: `hz = base_hz * 2 ** (delta / 12)`. The note's own pitch is the base, so a static series is an exact no-op and the movement is *inside* the note. Nothing is stretched or truncated: the note is made `3 * ceil(frames / 3)` frames long (the finest grid the Composer offers) so it covers the series, and any remainder holds the last value.

```text
static      C4 --------------- C4        (variant A / B)
trajectory  C4 -> +d1 -> +d2 -> +d3     (variant C / D, one delta per frame)
```

## 3. Test material (Parts 7-8, 14)

**Experimental choice.** Cases were chosen by a rule stated in `stage13a.select_cases` before any audio was inspected: strongest, longest, vibrato, near-static, rising, falling, shortest, and one more for coverage — all bounded. One instrument (`bright_lead`), one velocity, one tempo, one channel and one renderer for every variant of every case.

| case | profile | scope | frames | max|Δ| st | changes | behaviour / direction | why |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| pitch_01 | pokey_ref_0a53188c | VOICE | 150 | 9.89 | 20 | stepped / mixed | strongest measured pitch movement |
| pitch_02 | pokey_ref_3c36e574 | PAIR | 150 | 2.99 | 1 | drifting / rising | longest trajectory |
| pitch_03 | pokey_ref_25f94201 | VOICE | 89 | 0.57 | 44 | vibrato / mixed | vibrato-like behaviour |
| pitch_04 | pokey_ref_ef214010 | VOICE | 34 | 0.32 | 27 | vibrato / mixed | nearly static (smallest non-zero excursion) |
| pitch_05 | pokey_ref_7611576e | VOICE | 11 | 4.15 | 9 | stepped / rising | rising direction |
| pitch_06 | pokey_ref_0657f037 | VOICE | 7 | 4.98 | 5 | stepped / falling | falling direction |
| pitch_07 | pokey_ref_a8c81a84 | VOICE | 5 | 5.51 | 3 | stepped / falling | shortest trajectory |
| pitch_08 | pokey_ref_2de893a6 | VOICE | 7 | 4.54 | 6 | stepped / falling | next by id (family coverage) |

## 4. The variants (Parts 3-4, 6)

| variant | pitch used | everything else |
| :--- | :--- | :--- |
| A STATIC | the Composer's note pitch | unchanged |
| B PROFILE_STATIC | the trajectory's time-mean delta, held constant | unchanged |
| C PROFILE_TRAJECTORY | the profile's measured per-frame delta | unchanged |
| D CONTROL_TRAJECTORY | another profile's measured delta (donor) | unchanged |

**Experimental choice.** B is the profile's *static pitch level* — the only static pitch a profile offers a consumer, since `base_hz` is a reference the binding deliberately does not apply. C minus B therefore isolates the *movement* from the *level*. D is a real donor trajectory, accepted only when it is within 2 semitones of range, half the frame count and 3 changes of the tested one; otherwise the branch is recorded unavailable rather than filled with something arbitrary.

**Observed.** No defensible control exists for `pitch_01`, `pitch_03`, `pitch_04`.

## 5. Frame-level proof (Part 17)

**Observed.** For every case and level the only POKEY column that changes is AUDF1; AUDC, AUDCTL and every frame outside the tested note are byte-identical to A. That is the proof that the only variable is pitch/divider behaviour.

| case | level | changed frames | first | columns | AUDC unchanged | AUDCTL unchanged | outside unchanged |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| pitch_01 | 1 | 108 | 6 | AUDF1 | True | True | True |
| pitch_01 | 2 | 108 | 18 | AUDF1 | True | True | True |
| pitch_02 | 1 | 10 | 140 | AUDF1 | True | True | True |
| pitch_02 | 2 | 10 | 152 | AUDF1 | True | True | True |
| pitch_03 | 1 | 66 | 2 | AUDF1 | True | True | True |
| pitch_03 | 2 | 66 | 14 | AUDF1 | True | True | True |
| pitch_04 | 1 | 29 | 1 | AUDF1 | True | True | True |
| pitch_04 | 2 | 29 | 13 | AUDF1 | True | True | True |
| pitch_05 | 1 | 6 | 1 | AUDF1 | True | True | True |
| pitch_05 | 2 | 6 | 13 | AUDF1 | True | True | True |
| pitch_06 | 1 | 6 | 1 | AUDF1 | True | True | True |
| pitch_06 | 2 | 6 | 13 | AUDF1 | True | True | True |
| pitch_07 | 1 | 4 | 2 | AUDF1 | True | True | True |
| pitch_07 | 2 | 4 | 14 | AUDF1 | True | True | True |
| pitch_08 | 1 | 8 | 1 | AUDF1 | True | True | True |
| pitch_08 | 2 | 8 | 13 | AUDF1 | True | True | True |

## 6. Quantitative analysis (Part 10)

**Observed.** Applied pitch (exact, from the frames) and the audio descriptors measured on the *tested note* with a short-time pitch tracker. `spread` is the standard deviation of the tracked fundamental, in semitones; A and B are 0 by construction.

| case | level | applied range st | applied RMS st | changes | rate Hz | A spread st | C spread st | C−A |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| pitch_01 | 1 | 9.89 | 4.4527 | 20 | 6.6667 | 0.0 | 3.3479 | 3.3479 |
| pitch_01 | 2 | 9.89 | 4.4527 | 20 | 6.6667 | 0.0 | 3.3264 | 3.3264 |
| pitch_02 | 1 | 2.99 | 0.772 | 1 | 0.3333 | 0.0 | 0.726 | 0.726 |
| pitch_02 | 2 | 2.99 | 0.772 | 1 | 0.3333 | 0.0 | 0.7492 | 0.7492 |
| pitch_03 | 1 | 0.57 | 0.3491 | 44 | 24.7191 | 0.0 | 0.2171 | 0.2171 |
| pitch_03 | 2 | 0.57 | 0.3491 | 44 | 24.7191 | 0.0 | 0.2256 | 0.2256 |
| pitch_04 | 1 | 0.43 | 0.1865 | 27 | 39.7059 | 0.0 | 0.1384 | 0.1384 |
| pitch_04 | 2 | 0.43 | 0.1865 | 27 | 39.7059 | 0.0 | 0.1615 | 0.1615 |
| pitch_05 | 1 | 4.15 | 2.7979 | 9 | 40.9091 | 0.0 | 19.3331 | 19.3331 |
| pitch_05 | 2 | 4.15 | 2.7979 | 9 | 40.9091 | 0.0 | 1.4721 | 1.4721 |
| pitch_06 | 1 | 4.98 | 3.7645 | 5 | 35.7143 | 0.0 | 20.7844 | 20.7844 |
| pitch_06 | 2 | 4.98 | 3.7645 | 5 | 35.7143 | 0.0 | 17.7784 | 17.7784 |
| pitch_07 | 1 | 5.51 | 3.1439 | 3 | 30.0 | 0.0 | 2.2507 | 2.2507 |
| pitch_07 | 2 | 5.51 | 3.1439 | 3 | 30.0 | 0.0 | 2.234 | 2.234 |
| pitch_08 | 1 | 4.54 | 2.7975 | 6 | 42.8571 | 0.0 | 1.6611 | 1.6611 |
| pitch_08 | 2 | 4.54 | 2.7975 | 6 | 42.8571 | 0.0 | 1.5866 | 1.5866 |

## 7. Reference comparison (Part 11)

**Observed.** The source reference's short-time centroid spread against A's and C's, where a reference exists. The question is whether C reproduces a temporal aspect of the reference that A cannot.

| case | profile | reference centroid std Hz | A centroid std Hz | C centroid std Hz | C − A Hz |
| :--- | :--- | :--- | :--- | :--- | :--- |
| pitch_01 | pokey_ref_0a53188c | 577.316 | 33.22 | 586.703 | 553.483 |
| pitch_02 | pokey_ref_3c36e574 | 140.221 | 33.22 | 35.259 | 2.039 |
| pitch_03 | pokey_ref_25f94201 | 387.347 | 10.084 | 94.672 | 84.588 |
| pitch_05 | pokey_ref_7611576e | 1518.334 | 96.634 | 24.837 | -71.797 |
| pitch_06 | pokey_ref_0657f037 | 61.489 | 25.262 | 8.234 | -17.028 |
| pitch_08 | pokey_ref_2de893a6 | 327.877 | 25.262 | 38.326 | 13.064 |

## 8. Ablation (Part 12) and the control (Part 13)

**Observed.** H2 — C adds measurable pitch movement over the static profile level B — holds in **6 of 8** cases (threshold 0.5 semitones). Because B holds one constant delta, the audio-side C−B and C−A numbers are equal.

**Observed — the control that matters.** Where a donor exists (5 cases): the profile's own trajectory moved the measured pitch further in **3** (pitch_05, pitch_06, pitch_07), the donor's in **2** (pitch_02, pitch_08), and **0** were indistinguishable.

**Inference.** A mixed split means generic pitch movement explains the measured effect as well as the profile's own trajectory does: the *movement* is real, but this experiment finds no evidence that the archaeology-derived shape carries unique information.

## 9. Listening (Parts 14-15)

**Experimental choice.** The trajectory is technically transferred and changes the measured pitch in at least one case, so a blind static-vs-trajectory comparison tests a real distinction. Package: **prepared** (15 trials). Each trial asks which side is preferred, which is more convincing as Atari music, how confident the answer is, how different the two sides are, and which side (if either) has pitch movement or a more expressive character — never which side carries the profile.

| trial | kind |
| :--- | :--- |
| pitch_01_L1_C_vs_A | isolated: trajectory vs static |
| pitch_01_L1_C_vs_B | isolated: trajectory vs profile static level |
| pitch_01_L2_C_vs_A | phrase: trajectory vs static |
| pitch_07_L1_C_vs_A | isolated: trajectory vs static |
| pitch_07_L1_C_vs_B | isolated: trajectory vs profile static level |
| pitch_07_L2_C_vs_A | phrase: trajectory vs static |
| pitch_07_L1_C_vs_D | isolated: profile trajectory vs donor control |
| pitch_06_L1_C_vs_A | isolated: trajectory vs static |
| pitch_06_L1_C_vs_B | isolated: trajectory vs profile static level |
| pitch_06_L2_C_vs_A | phrase: trajectory vs static |
| pitch_06_L1_C_vs_D | isolated: profile trajectory vs donor control |
| pitch_08_L1_C_vs_A | isolated: trajectory vs static |
| pitch_08_L1_C_vs_B | isolated: trajectory vs profile static level |
| pitch_08_L2_C_vs_A | phrase: trajectory vs static |
| pitch_08_L1_C_vs_D | isolated: profile trajectory vs donor control |

## 10. Reproducibility

Every number is a pure function of the bank and the archaeology reference WAVs below (SHA-256); there is no timestamp in any artefact and the case list is fixed in source.

```json
{
  "archaeology/pokey_ref_0657f037/reference_replay.wav": "bbb9ffdac6be1f17060c57f161ef217b0eac3bd969e9aac474a4f6ba3fe99060",
  "archaeology/pokey_ref_0a53188c/reference_replay.wav": "5300587212e6b260b5631f4bbe0005840adc92544a55c6cf43bfbb4b73ac0d2c",
  "archaeology/pokey_ref_25f94201/reference_replay.wav": "4544eb1d91c1c7efe750672935d5943fb3fcd0cfdc1b04d49e5a536c6ef23c6a",
  "archaeology/pokey_ref_2de893a6/reference_replay.wav": "6ceb3436200a4bf75341a5ce12168cbd9b6fe45c199c15e94207573e342aaebe",
  "archaeology/pokey_ref_3c36e574/reference_replay.wav": "98382edbc60b3ba502f272e8a6913f0a95b7002a56f3b742558b4b408d88120b",
  "archaeology/pokey_ref_7611576e/reference_replay.wav": "8e7779ffcd06cce472d7fbdfaee4e5f4909842fa54681176fd368b89f839d849",
  "bank/profiles/pokey_ref_0657f037.json": "d33d5f97f948a75eeb08d7008084d9910a43bae729d4f18361d2be53b2b3c01e",
  "bank/profiles/pokey_ref_0a53188c.json": "1399a7a7623e8a4ba4fad892cc31e0d554bef73d9ecab5b96bc2669768a7186a",
  "bank/profiles/pokey_ref_25f94201.json": "a75e3d8d74a937a6b5302406c4a489da0c3d3a44f51ed7a0229816f19c135d5f",
  "bank/profiles/pokey_ref_2de893a6.json": "5772ebb947d1200286e75823e00dd45547ef815031484c8dc8a11678d1f660f2",
  "bank/profiles/pokey_ref_3c36e574.json": "037b713bd74be2884483ddf88e02e4e86fcec76ba9db98ad6270b160d6c88e42",
  "bank/profiles/pokey_ref_5ee9c1a8.json": "77af597c73cfe8c2867dc3eb489fb1719066c639dbf8d0ea5ca937fea57cb580",
  "bank/profiles/pokey_ref_7611576e.json": "5088ee3b798032f0f8dbc9f5710bce062e9be1410444e330e59a42b6a226a56b",
  "bank/profiles/pokey_ref_a8c81a84.json": "31f7c44a3bbe0a76a477d5cc8f8b1aadfa99d177eabdb00165bc8edb6d2dc9ea",
  "bank/profiles/pokey_ref_d9bef36c.json": "42ebed12a5d758c1545062ef118c92f749409f2b692f9cca46d688b322430e66",
  "bank/profiles/pokey_ref_ed07bb73.json": "3cba27a67491ffaeabdc3c8053acc67f1fe0dae75b9585e3265205e89a58752f",
  "bank/profiles/pokey_ref_ef214010.json": "166643f72eddc854ad76ac7626acdbca80b6745ce238ec85d165af2bc76fec23",
  "bank/registry.json": "b78faec3738cc127d21ae571f526f5761a4292f302eb07de7ba08794746a81fb"
}
```

## Final report — the eight questions

**1. Is profile-derived pitch trajectory technically transferable?** **Yes.** H1 holds in 8 of 8 cases: the trajectory is re-based on the Composer's note in the Stage-5 representation and reaches the register frames exactly, changing only AUDF.

**2. Does it add information beyond static profile pitch?** **Yes.** H2 holds in 6 of 8 cases. B (the static level) adds no measurable pitch movement at all, so C − B is the whole trajectory.

**3. Does it preserve the musical pitch of the Composer?** **Yes.** H3 holds in 8 of 8 cases: the series starts at the note's own pitch, stays within one octave of it, AUDC and AUDCTL are untouched, and every frame outside the note is byte-identical to the static render.

**4. Does it reproduce an aspect of the reference that static misses?** **Partly.** C's centroid spread is closer to the source reference's than A's in 4 of 6 reference-bearing cases (against: pitch_05, pitch_06).

**5. Is the effect specific to the profile trajectory?** **Not established.** Where a donor control exists the split is 3 to 2: a similar trajectory taken from a different profile moves the measured pitch about as much.

**6. Is the effect perceptually audible?** **Prepared, not yet measured.** The blind package (15 trials: isolated C-vs-A, isolated C-vs-B, phrase-level C-vs-A and C-vs-D controls) is built; its result is unknown.

**7. Is it musically useful rather than merely detectable?** **Unknown.** Detectable: yes. Characteristic of the profile: not shown (question 5). Useful: only a listener can say, and the brief's rule forbids declaring it on technical grounds alone.

**8. The single highest-value next step.** **Run the prepared blind listening package (C vs A, C vs B, C vs D).** The mechanics are settled and the ablation is clean; what the decision tree still needs is whether a listener hears and prefers the movement — and whether the profile's own trajectory is distinguishable from a generic one. If the listener cannot tell C from D, the conclusion is already visible in the measurement: generic pitch movement, not the profile, is what is audible.

### Verdict

**INCONCLUSIVE.** The technical effect is clean and measurable, but where a donor control exists the profile's own trajectory does not move the measured pitch further than a similar trajectory from another profile (a mixed split), and the blind listening is not run.

The decision tree's `SUPPORTED` branch additionally requires a perceptually meaningful difference and, preferably, that C beat the generic control D — and the quantitative half of that (C vs D) is already mixed. `INCONCLUSIVE` is therefore the honest label today, with the listening package as the evidence that would move it.


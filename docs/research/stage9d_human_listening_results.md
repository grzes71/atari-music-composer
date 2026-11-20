# Stage 9D — human listening results

What the real listening test of the 61 renderable POKEY sound profiles showed, and whether
the evidence justifies moving to a production selection.

| | |
| :--- | :--- |
| experiment | Stage 9C blinded listening package |
| profiles in the library | 67 |
| profiles analysed | 61 (60 with ratings) |
| distinct audio signals they produce | **37** |
| A/B trials answered | 30 |
| song pairs answered | 6 |
| anomaly records | 6 |
| verdict | **NO** |

---

## 1. Executive summary

**Observed.**

* The 61 renderable profiles produce only **37 distinct audio signals**. 24 profiles are byte-identical to another profile in the library, in groups as large as 10.
* Mean usefulness 3.4, mean distinctiveness 3.1, mean Atari character 3.583 (n=60).
* The same sound, presented twice under two labels, still drew distinctiveness ratings up to 2 points apart (mean within-group range 0.833, ICC(1,1) 0.7287) — the listener was reliable, but not to the point where a one-point difference between profiles means anything.
* A/B: 7 A, 10 B, 12 no preference; median similarity 2.0, median character difference 3.0. Machine distance against perceived similarity: rho = **-0.6628** (n=30).
* Songs: **the default won** — profile-bound 0, default 5, ties 1 of 6. On the single question "which sounds better" the tally was 0 for the profile version and 5 for the default.
* The listener's vocabulary is dominated by "lead" (40 of 61 comments) — a direct consequence of the single melodic stimulus.

**Inference.**

* The library is **much smaller than it looks**: as a source of *distinct sounds* it offers 37, not 61. The redundancy is not a perception artefact; it is in the rendered audio, because these profiles differ in measured pitch/volume gesture behaviour that the player cannot currently render.
* The spectral distance metric behaves as designed on similarity (rho -0.6628, -0.5215 without the identical pairs), so the machine model of *timbre distance* is not broken. Its blind spot is measurable and it is **level**: the distance normalises the spectrum, so a profile that sustains 10 dB lower looks identical to one that does not, and the level gap predicts the similarity rating about as well (rho -0.547).
* **The whole-song comparison is the decisive negative result.** Binding profiles to real songs made them worse for this listener in 5 of 6 comparisons, unanimously on all three questions, with the profile-bound render never winning one.

**Recommendation.**

* **Do not** select a production library from this data yet. The isolated stimuli are Atari-like and useful, and the metric story is now understood, but the integration path that was actually tested — these bindings, on these six songs — loses to the composer's own defaults. The verdict is **NO**, and §14 says what to fix first.

## 2. Dataset verification

**Observed.** The analysis read exactly three answer files and the experiment manifest, and
hashed them so the run can be reproduced from the same bytes:

| file | sha256 (first 16) |
| :--- | :--- |
| `evaluation_ab.csv` | `6a3cfbe13174f9df` |
| `evaluation_profiles.csv` | `a6e37579152cf05b` |
| `evaluation_songs.csv` | `1e72c113c5b6ae76` |
| `manifest.json` | `d3c220fd033eddfb` |

| check | result |
| :--- | :--- |
| part A rows | 61 of 61 expected |
| part B rows | 30 of 30 expected |
| part C rows | 6 of 6 expected |
| ids agree with the private manifest | yes, set-for-set, no duplicates, no unknown ids |
| numeric ranges | every value inside 1–5; every choice inside a/b/none |
| raw answers modified | **no** — read-only; only whitespace is trimmed for matching |

Anomalies found in the returned data (reported, never repaired):

| kind | where | detail | effect on the analysis |
| :--- | :--- | :--- | :--- |
| `missing_rating` | part A.distinctiveness | no value for 1 row(s): ['sample_026'] | excluded from the distinctiveness statistics; the denominator is reported |
| `missing_rating` | part A.usefulness | no value for 1 row(s): ['sample_026'] | excluded from the usefulness statistics; the denominator is reported |
| `missing_rating` | part A.atari_character | no value for 1 row(s): ['sample_026'] | excluded from the atari_character statistics; the denominator is reported |
| `missing_rating` | part A.confidence | no value for 1 row(s): ['sample_026'] | excluded from the confidence statistics; the denominator is reported |
| `missing_choice` | part B.preference | no preference recorded for ['trial_20'] | counted as 'not stated'; it is not read as 'no preference' |
| `whitespace` | answers | values with leading/trailing spaces: [('sample_049', 'comment', 'crackling/bass/perc? ')] | kept verbatim; only used trimmed for matching |

**Inference.** The dataset is complete enough to analyse as a whole. The two gaps are
single fields, so every statistic below states its own n rather than assuming 61.

## 3. Part A — the profiles heard one at a time

**Observed.**

| scale | n | mean | median | stdev | min | max | share 4–5 | share 1–2 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| distinctiveness | 60 | 3.1 | 3.0 | 0.896 | 1 | 5 | 33% | 17% |
| usefulness | 60 | 3.4 | 3.5 | 0.669 | 2 | 4 | 50% | 10% |
| atari_character | 60 | 3.583 | 3.0 | 0.869 | 2 | 5 | 47% | 7% |
| confidence | 60 | 3.45 | 3.0 | 0.622 | 2 | 5 | 42% | 2% |

Score distributions:

| score | distinctiveness | usefulness | Atari character | confidence |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 0 | 0 | 0 |
| 2 | 5 | 6 | 4 | 1 |
| 3 | 30 | 24 | 28 | 34 |
| 4 | 19 | 30 | 17 | 22 |
| 5 | 1 | 0 | 11 | 3 |

### 3.1 Distinctiveness against usefulness

| quadrant | n | profiles |
| :--- | ---: | :--- |
| distinctive (≥4) **and** useful (≥4) | 9 | pokey_ref_0657f037, pokey_ref_089a0846, pokey_ref_2b83db43, pokey_ref_3faf80b4, pokey_ref_5ee9c1a8, pokey_ref_689d3402, pokey_ref_7611576e, pokey_ref_e913803e, pokey_ref_ed07bb73 |
| distinctive (≥4) but not useful (<4) | 11 | pokey_ref_0bd72343, pokey_ref_331fbbd7, pokey_ref_3627798b, pokey_ref_9daa0429, pokey_ref_a68743ad, pokey_ref_af009fe0, pokey_ref_b1b73fa2, pokey_ref_c0b97138, pokey_ref_c25e268b, pokey_ref_c53d7640, pokey_ref_db7fe434 |
| useful (≥4) but not distinctive (<4) | 21 | pokey_ref_048db11d, pokey_ref_0a53188c, pokey_ref_1ef377fc, pokey_ref_23665c4f, pokey_ref_275b992a, pokey_ref_3658a088, pokey_ref_6ad0e843, pokey_ref_80d1ce25, pokey_ref_953311ef, pokey_ref_9a86568a, pokey_ref_a09c0263, pokey_ref_ad730372, pokey_ref_c2983132, pokey_ref_c321892f, pokey_ref_c6eca16a, pokey_ref_d172d15e, pokey_ref_e4e5235f, pokey_ref_e86c9631, pokey_ref_ef214010, pokey_ref_f3e3c618, pokey_ref_feb29c1f |
| neither (both <4) | 19 | pokey_ref_050170ef, pokey_ref_1bed70f4, pokey_ref_1e9be30a, pokey_ref_1efd9336, pokey_ref_25f94201, pokey_ref_2de893a6, pokey_ref_3c36e574, pokey_ref_568403b4, pokey_ref_686d2070, pokey_ref_6db98eb5, pokey_ref_714607ba, pokey_ref_7983ed84, pokey_ref_9098232a, pokey_ref_914c63ec, pokey_ref_959628d6, pokey_ref_9a42d6fe, pokey_ref_a8c81a84, pokey_ref_cb9b6db2, pokey_ref_f022d673 |

### 3.2 Does Atari character predict anything?

| metric | scale | n | Spearman |
| :--- | :--- | ---: | ---: |
| bandwidth_hz | usefulness | 60 | 0.6596 |
| flatness | distinctiveness | 60 | 0.5002 |
| spectral_distance_to_library | usefulness | 60 | -0.4926 |
| rolloff_hz | usefulness | 60 | 0.4145 |
| bandwidth_hz | distinctiveness | 60 | -0.3755 |
| spectral_distance_to_library | distinctiveness | 60 | 0.3321 |

Atari character against usefulness: rho = 0.5746 (n=60).

### 3.3 Confidence, and a session effect that matters more

| band | n | distinctiveness (mean/median) | usefulness (mean/median) |
| :--- | ---: | :--- | :--- |
| low (1-2) | 1 | 4.0 / 4.0 | 2.0 / 2.0 |
| medium (3) | 34 | 3.206 / 3.0 | 3.176 / 3.0 |
| high (4-5) | 25 | 2.92 / 3.0 | 3.76 / 4.0 |

The samples were presented in a seeded shuffle, so position is not a property of the sound.
Correlating each scale with the position in the session:

| scale | n | Pearson(position) | Spearman(position) | mean first half | mean second half |
| :--- | ---: | ---: | ---: | ---: | ---: |
| distinctiveness | 60 | 0.0079 | -0.0814 | 3.1 | 3.1 |
| usefulness | 60 | -0.0269 | -0.0895 | 3.4 | 3.4 |
| atari_character | 60 | -0.3672 | -0.3696 | 3.9 | 3.2667 |
| confidence | 60 | -0.4723 | -0.4713 | 3.6333 | 3.2667 |

### 3.4 The listener's own vocabulary

The README suggested bass, drum, snare, bell, noise, laser, repeating. The listener used lead_tonal (40), percussive_noisy (21), loud (13), clean (10), short_transient (5), artefact (3), interesting (3).
Categories below are read out of the answers, with the markers shown so the grouping can be
checked rather than trusted:

| category | markers | n | members |
| :--- | :--- | ---: | :--- |
| lead_tonal (a sustained melodic tone) | lead, tone | 40 | sample_040, sample_014, sample_009, sample_031, sample_052, sample_025, sample_057, sample_004, sample_005, sample_001 (+30) |
| percussive_noisy (noise-like, percussive or bass-register) | bass, perc, nois, crackl, rustl, beat | 21 | sample_053, sample_056, sample_051, sample_010, sample_041, sample_016, sample_006, sample_058, sample_044, sample_046 (+11) |
| clean (described as clean or clear) | clean, clear | 10 | sample_025, sample_004, sample_061, sample_038, sample_008, sample_011, sample_012, sample_035, sample_015, sample_037 |
| loud (heard as loud) | loud, lound | 13 | sample_022, sample_023, sample_017, sample_054, sample_055, sample_043, sample_036, sample_034, sample_050, sample_032 (+3) |
| short_transient (heard as short) | short | 5 | sample_001, sample_021, sample_022, sample_013, sample_028 |
| artefact (carries an audible break/artefact) | break | 3 | sample_040, sample_004, sample_026 |
| interesting (explicitly called interesting) | interesting | 3 | sample_036, sample_032, sample_039 |

**Inference.** The vocabulary is dominated by *lead* because the stimulus is one melodic
phrase in the lead register: the experiment could not present a profile as percussion or as
a bass line, so "this sounds like a lead" is partly a property of the stimulus. The
clean/noisy distinction is more informative, and §6 shows it tracks the generator family
rather than the spectrum.

### 3.5 The noise floor: what the same sound scored twice

Some profiles render to **byte-identical** audio, so the same sound was presented under
different sample ids. Any difference in its ratings is the listener's own inconsistency:

| scale | groups | ratings inside | mean within-group range | max range | ICC(1,1) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| distinctiveness | 6 | 30 | 0.833 | 2.0 | 0.7287 |
| usefulness | 6 | 30 | 0.333 | 1.0 | 0.7604 |
| atari_character | 6 | 30 | 0.5 | 1.0 | 0.9153 |
| confidence | 6 | 30 | 1.0 | 2.0 | 0.3505 |

Groups of identical audio:

| size | samples | profiles |
| ---: | :--- | :--- |
| 10 | sample_003, sample_005, sample_008, sample_012, sample_015, sample_025, sample_029, sample_031, sample_035, sample_037 | pokey_ref_80d1ce25, pokey_ref_275b992a, pokey_ref_9098232a, pokey_ref_ad730372, pokey_ref_e86c9631, pokey_ref_1ef377fc, pokey_ref_e4e5235f, pokey_ref_0a53188c, pokey_ref_c321892f, pokey_ref_ef214010 |
| 6 | sample_009, sample_039, sample_043, sample_050, sample_055, sample_059 | pokey_ref_089a0846, pokey_ref_ed07bb73, pokey_ref_a09c0263, pokey_ref_c2983132, pokey_ref_9a86568a, pokey_ref_3c36e574 |
| 4 | sample_016, sample_046, sample_051, sample_058 | pokey_ref_568403b4, pokey_ref_7983ed84, pokey_ref_1e9be30a, pokey_ref_6db98eb5 |
| 4 | sample_017, sample_023, sample_033, sample_038 | pokey_ref_5ee9c1a8, pokey_ref_3faf80b4, pokey_ref_feb29c1f, pokey_ref_689d3402 |
| 3 | sample_027, sample_044, sample_056 | pokey_ref_cb9b6db2, pokey_ref_714607ba, pokey_ref_1bed70f4 |
| 3 | sample_032, sample_034, sample_045 | pokey_ref_c53d7640, pokey_ref_c25e268b, pokey_ref_af009fe0 |

**Inference.** The listener was *reliable*: with the same sound presented twice, the agreement
measures give ICC(1,1) atari_character 0.9153, usefulness 0.7604, distinctiveness 0.7287. Two consequences follow, both of which constrain the reading of §3.

* The scales that describe the sound are trustworthy enough to compare **groups** of profiles, not to order them finely: the same sound was still rated up to 2 point(s) apart on distinctiveness, so a one-point difference between two profiles is within the noise.
* Confidence behaves as a *self-report about the judgement*, not as a property of the sound (ICC(1,1) 0.3505), and it drifts through the session (§3.3). It is useful for spotting where the listener hesitated; it is not evidence about a profile.

## 4. Part B — profile against profile

**Observed.**

Preferences: A 7, B 10, no preference 12, not stated 1.

| view | trials | median similarity | median character difference |
| :--- | ---: | ---: | ---: |
| all trials | 30 | 2.0 | 3.0 |
| byte-identical audio pairs | 3 | 5.0 | 1.0 |
| distinct-audio pairs | 27 | 2.0 | 4.0 |

By stratum:

| stratum | trials | median similarity | decided | no preference |
| :--- | ---: | ---: | ---: | ---: |
| cross_song | 5 | 2.0 | 4 | 0 |
| different_generator | 4 | 2.0 | 3 | 1 |
| distant | 6 | 2.0 | 4 | 2 |
| same_generator | 4 | 2.0 | 1 | 3 |
| same_source_song | 5 | 2.0 | 4 | 1 |
| similar | 6 | 3.5 | 1 | 5 |

Most-preferred profiles (times chosen as the preferred side):

| profile | wins | sample | scope | generator | usefulness | distinctiveness |
| :--- | ---: | :--- | :--- | :--- | ---: | ---: |
| pokey_ref_1ef377fc | 2 | sample_025 | VOICE | `$A` | 4.0 | 2.0 |
| pokey_ref_953311ef | 1 | sample_011 | VOICE | `$A` | 4.0 | 3.0 |
| pokey_ref_c2983132 | 1 | sample_050 | PAIR | `$C` | 4.0 | 3.0 |
| pokey_ref_689d3402 | 1 | sample_038 | VOICE | `$C` | 4.0 | 4.0 |
| pokey_ref_275b992a | 1 | sample_005 | VOICE | `$A` | 4.0 | 1.0 |
| pokey_ref_feb29c1f | 1 | sample_033 | VOICE | `$C` | 4.0 | 3.0 |
| pokey_ref_3658a088 | 1 | sample_061 | PAIR | `$A` | 4.0 | 3.0 |
| pokey_ref_1efd9336 | 1 | sample_057 | VOICE | `$6` | 3.0 | 3.0 |

Machine distance against perceived similarity:

* Spearman rho = **-0.6628** (n=30)
* Pearson r = -0.5258

Pairs the metric called nearly identical but the listener called different — with the
difference the metric cannot see attached:

| trial | technical distance | similarity | A | B | same generator | same scope | |Δ RMS| dB |
| :--- | ---: | ---: | :--- | :--- | :--- | :--- | ---: |
| trial_06 | 0.003 | 2 | pokey_ref_db7fe434 (PAIR) | pokey_ref_714607ba (PAIR) | yes | yes | 10.68 |
| trial_13 | 0.014 | 2 | pokey_ref_3658a088 (PAIR) | pokey_ref_e913803e (VOICE) | yes | no | 11.868 |
| trial_14 | 0.005 | 2 | pokey_ref_d9bef36c (VOICE) | pokey_ref_1ef377fc (VOICE) | yes | yes | 7.449 |
| trial_15 | 0.006 | 2 | pokey_ref_1efd9336 (VOICE) | pokey_ref_af009fe0 (VOICE) | no | yes | 0.007 |
| trial_18 | 0.001 | 2 | pokey_ref_c0b97138 (VOICE) | pokey_ref_af009fe0 (VOICE) | yes | yes | 11.199 |
| trial_26 | 0.003 | 2 | pokey_ref_db7fe434 (PAIR) | pokey_ref_7983ed84 (VOICE) | yes | no | 10.681 |

What predicted the similarity rating, over all 30 trials:

| difference between the two stimuli | n | Spearman vs similarity |
| :--- | ---: | ---: |
| centroid_gap_hz | 30 | -0.6882 |
| technical_distance | 30 | -0.6628 |
| same_generator | 30 | -0.5993 |
| level_gap_db | 30 | -0.547 |
| flatness_gap | 30 | -0.5125 |
| same_scope | 30 | -0.308 |

In the 12 non-identical pairs the metric called nearly identical (distance ≤ 0.02), |Δ RMS| spans 0.007–11.868 dB (median 7.936); of those, the 6 rated similarity ≤ 2 differ by 7–12 dB except one (trial_15) which is level-matched and differs in generator instead. In the byte-identical pairs the level gap is 0–0 dB — the distance cannot tell those two situations apart, because it is computed on a normalised spectrum.

**Inference.** The A/B experiment answers the redundancy question directly: the library does
contain clearly different sounds, and the metric ranks them roughly as the listener did
(rho -0.6628). Two of the listener's cues are measurable and one of them the
distance discards by construction:

* **pitch/centroid difference** is the single best predictor of similarity (-0.6882);
* **level difference** is a close second and is *invisible* to the distance — a pair that sustains 12 dB apart and a pair that is byte-identical both score ≈ 0.00;
* the listener's *character* language (clean versus noisy) follows the generator family
  rather than the spectrum, which is what a POKEY-literate listener keys on.

That is a correctable defect in the metric, not a perceptual mystery.

## 5. Part C — whole songs

**Observed.**

| question | profile version | default version | no preference |
| :--- | ---: | ---: | ---: |
| better sound | 0 | 5 | 1 |
| more character | 0 | 5 | 1 |
| more convincing atari | 0 | 5 | 1 |

Overall difference: median 3.5, range 1–5.

| pair | song | profile votes | default votes | outcome | overall difference |
| :--- | :--- | ---: | ---: | :--- | ---: |
| song_01 | Vaults-of-Nhyrmeth.dsl | 0 | 3 | default | 3.0 |
| song_02 | as-1.dsl | 0 | 3 | default | 3.0 |
| song_03 | dziki2.json | 0 | 3 | default | 4.0 |
| song_04 | as-2.dsl | 0 | 0 | tie | 1.0 |
| song_05 | funky.json | 0 | 3 | default | 4.0 |
| song_06 | koval.json | 0 | 3 | default | 5.0 |

Six pairs cannot support a population claim, and the split (0–5) is reported as a description of these six songs only.

**Inference.** This is the most consequential result in the stage, and the least ambiguous:
the listener preferred the composer's **own** default instruments in 5 of 6 songs,
unanimously on all three questions, with the profile-bound render winning none. The reported
overall difference is large (median 3.5), so this is not a
tie-break among near-identical renders: binding these profiles audibly changed the music, and
changed it for the worse. Whatever the profiles are good at in isolation, the integration path
tested here degrades a real piece.

Two candidate explanations that this experiment cannot separate, both worth testing next:
the bindings chose profiles by generator family rather than by the listening evidence, and the
bound profiles were mostly the *louder, noisier* family the listener rated as merely average;
and the default character instruments may already be better tuned to the player's envelopes
than a profile measured from unrelated material is.

## 6. Human against machine

**Observed.** Rank correlations between every available machine metric and every rating
(only rows with n ≥ 8):

| metric | scale | n | Spearman | Kendall tau-b | Pearson |
| :--- | :--- | ---: | ---: | ---: | ---: |
| bandwidth_hz | atari_character | 60 | 0.6817 | 0.532 | 0.5483 |
| bandwidth_hz | usefulness | 60 | 0.6596 | 0.5104 | 0.6488 |
| spectral_distance_to_library | atari_character | 60 | -0.6533 | -0.4768 | -0.703 |
| bandwidth_hz | confidence | 60 | 0.5031 | 0.4031 | 0.4694 |
| flatness | distinctiveness | 60 | 0.5002 | 0.3713 | 0.552 |
| spectral_distance_to_library | usefulness | 60 | -0.4926 | -0.3814 | -0.4429 |
| rolloff_hz | usefulness | 60 | 0.4145 | 0.3062 | 0.5255 |
| bandwidth_hz | distinctiveness | 60 | -0.3755 | -0.2744 | -0.2274 |
| spectral_distance_to_library | distinctiveness | 60 | 0.3321 | 0.2477 | 0.4915 |
| spectral_distance_to_library | confidence | 60 | -0.3208 | -0.2551 | -0.3327 |
| centroid_hz | usefulness | 60 | 0.3133 | 0.2222 | 0.4171 |
| divider_bits | confidence | 60 | -0.291 | -0.1854 | -0.3006 |
| envelope_confidence | usefulness | 60 | -0.2873 | -0.2008 | -0.3205 |
| centroid_hz | distinctiveness | 60 | 0.2723 | 0.1902 | 0.1567 |
| divider_bits | atari_character | 60 | -0.2692 | -0.1872 | -0.2742 |
| envelope_confidence | confidence | 60 | -0.2555 | -0.1779 | -0.2453 |
| final_rms_dbfs | usefulness | 60 | 0.2541 | 0.2007 | 0.2384 |
| envelope_confidence | distinctiveness | 60 | 0.2443 | 0.1786 | 0.2362 |
| final_rms_dbfs | confidence | 60 | 0.2381 | 0.1853 | 0.24 |
| flatness | usefulness | 60 | 0.2302 | 0.1549 | -0.0375 |
| rolloff_hz | distinctiveness | 60 | 0.212 | 0.1281 | 0.0232 |
| rolloff_hz | confidence | 60 | 0.1991 | 0.15 | 0.3509 |
| divider_bits | distinctiveness | 60 | 0.1865 | 0.1285 | 0.2128 |
| centroid_hz | confidence | 60 | 0.1735 | 0.1298 | 0.252 |
| flatness | atari_character | 60 | -0.1697 | -0.1648 | -0.4521 |
| envelope_confidence | atari_character | 60 | -0.1529 | -0.1153 | -0.1789 |
| divider_bits | usefulness | 60 | -0.133 | -0.0867 | -0.1206 |
| final_rms_dbfs | distinctiveness | 60 | -0.1272 | -0.116 | -0.3155 |
| flatness | confidence | 60 | 0.0771 | 0.0513 | -0.0749 |
| rolloff_hz | atari_character | 60 | 0.0452 | 0.0692 | 0.2613 |
| final_rms_dbfs | atari_character | 60 | 0.0346 | 0.0277 | 0.1732 |
| centroid_hz | atari_character | 60 | -0.0321 | -0.0047 | 0.0784 |

Ordinal group comparisons (Cliff's delta, −1…+1):

| split | scale | Cliff's delta |
| :--- | :--- | ---: |
| PAIR vs VOICE | distinctiveness | 0.2156 |
| PAIR vs VOICE | usefulness | -0.1508 |
| PAIR vs VOICE | atari_character | -0.3161 |
| PAIR vs VOICE | confidence | -0.3214 |
| first vs last generator family (alphabetical) | distinctiveness | 0.5312 |
| first vs last generator family (alphabetical) | usefulness | -0.7656 |
| first vs last generator family (alphabetical) | atari_character | -0.8281 |
| first vs last generator family (alphabetical) | confidence | -0.1875 |
| PLAYABLE_WITH_LIMITATION vs PLAYABLE | distinctiveness | 0.1245 |
| PLAYABLE_WITH_LIMITATION vs PLAYABLE | usefulness | -0.4029 |
| PLAYABLE_WITH_LIMITATION vs PLAYABLE | atari_character | -0.2698 |
| PLAYABLE_WITH_LIMITATION vs PLAYABLE | confidence | -0.3162 |

Listener language against the spectrum:

| listener said | n | median flatness | median centroid | generator families |
| :--- | ---: | ---: | ---: | :--- |
| clean | 10 | 0.5099 | 6048.218 | `$A`, `$C` |
| noisy | 21 | 0.497 | 4143.769 | `$0`, `$8` |

Cliff's delta on flatness, clean versus noisy: 0.619. Family sets disjoint: yes.

Not available in the Stage 9C manifest, so not analysed: `transferability (Stage 6)`, `Stage 7B perceptual metrics`, `control stability`, `profile distance (Stage 6 definition)`, `envelope similarity`.

**Inference.** The band-energy distance tracks perceived similarity well (rho -0.6628 in §4) — the machine model is not broken — but it is computed on a normalised spectrum, so it is blind to the one difference the listener used repeatedly and explicitly: **level**. Separately, the listener's clean/noisy vocabulary is explained by the *generator identity* rather than by any spectral summary, which is what a POKEY-literate listener would be expected to key on. A correlation here describes association only, never causation.

## 7. Loudness bias

**Observed.** The stimuli share a peak, not an RMS; the measured RMS range across the
library is 12.522 dB.

| scale | n | Spearman vs RMS | Pearson vs RMS |
| :--- | ---: | ---: | ---: |
| usefulness | 60 | 0.2541 | 0.2384 |
| confidence | 60 | 0.2381 | 0.24 |
| distinctiveness | 60 | -0.1272 | -0.3155 |
| atari_character | 60 | 0.0346 | 0.1732 |

Matched-level sensitivity check (within ±2 dB of the median level, n=34):

* distinctiveness mean 2.941, median 3.0
* usefulness mean 3.529, median 4.0
* Atari character mean 3.706, median 3.5
* distinctiveness inside versus outside the band, Cliff's delta: -0.2251

In the A/B trials, the preferred side was the louder one 12 times, the quieter one 1 times; 4 trial(s) were level-matched and 13 had no stated preference.

**Inference.** Loudness is *not* the explanation for the ratings, but it is not nothing
either — see the numbers above rather than a summary word. No correction is applied to the
answers: reweighting them would replace the listener's judgement with the analyst's.

## 8. Hypothesis evaluation

| # | hypothesis | verdict | evidence |
| :--- | :--- | :--- | :--- |
| H1 | Machine-level spectral distance predicts perceptual distinctiveness. | **partially supported** | the two halves disagree, so the verdict is split. Against the A/B similarity ratings the distance behaves as designed: rho=-0.6628 over n=30 trials (-0.5215 with the byte-identical pairs removed), i.e. greater spectral distance went with lower similarity. Against Part A distinctiveness it barely matters: rho=0.3321. And inside byte-identical stimuli the listener still spread distinctiveness by 0.833 points on average, which limits how fine a distinction that scale can support. |
| H2 | Spectral fidelity predicts perceptual similarity. | **supported, with two measured blind spots** | rho(distance, similarity) = -0.6628 (n=30) is the strongest machine-human relationship in this dataset, and it survives removing the byte-identical pairs (-0.5215). It is not the listener's only cue, and the two the distance misses are named: pitch/centroid gap predicts similarity better than the distance itself (-0.6882 against -0.6628), and the level gap (-0.547) is invisible to a distance computed on a normalised spectrum: the 12 non-identical pairs it calls nearly identical span 0.007–11.868 dB of level difference, while the byte-identical pairs span 0–0 dB. The listener's vocabulary for timbre also follows the generator family rather than the spectrum: clean n=10, noisy n=21, disjoint family sets. |
| H3 | More distinctive profiles are more useful for the Composer. | **not supported** | usefulness against distinctiveness gives rho=-0.2382 (n=60); the quadrant counts are 9 both, 11 distinctive but not useful (usefulness < 4), and 21 useful but not distinctive (distinctiveness < 4). If anything the relationship runs the other way, weakly. |
| H4 | Some profiles are technically similar but perceptually clearly different. | **confirmed** | 6 pair(s) with a technical distance of 0.02 or less were rated similarity 2 ("quite different"), and none of them is a byte-identical pair. Five of the six differ in level by 7–12 dB (their |ΔRMS| spans 0.007–11.868 dB, median 7.936, against 0–0 dB for the pairs that really are the same sound); the sixth (trial_15) is level-matched and differs in generator, at a spectral distance of 0.006. The distance is computed on a *normalized* spectrum, so a profile that sustains far lower looks identical to one that does not — and the listener, correctly, did not agree. |
| H5 | Some profiles are technically different but perceptually redundant. | **confirmed, on different grounds than expected** | not through the spectral metric: 0 trial(s) with a technical distance of 0.10 or more were called similar. Through the *audio*, decisively: 24 of the 61 profiles render byte-identical output to another profile, so the library contains entire families of profiles that cannot be told apart because they are the same signal. |
| H6 | Profile-bound rendering can improve a real Composer piece. | **falsified for these six songs** | the default Composer instruments won 5 of 6 whole-song comparisons and the profile-bound render won 0; on all three questions the tally was 0–5 for the profile version, with one tie and a median overall difference of 3.5. Six songs prove nothing about the population of songs, but five unanimous losses are not a null result either, and nothing here supports shipping the library as it stands. |
| H7 | The most useful profiles are not necessarily the most distinctive ones. | **supported** | 21 profile(s) were useful without being distinctive against 11 the other way round, and the two scales correlate negatively (rho=-0.2382). The loudness check adds strongest: usefulness rho=0.2541 with n=60. |

## 9. Candidate categories

Experimental groupings from the stated rules. **None is a selection**, and each member
carries its raw numbers so the rule can be changed and re-applied.

### A — Strong candidates (5)

_Rule:_ distinctiveness ≥ 4, usefulness ≥ 4, Atari character ≥ 4, no `PITCH_BASE_PAIR_INCONSISTENT` limitation and nothing blocking (measured-but-missing codes do not disqualify: they mean the archaeology knew less, not that the profile is wrong)

| profile | sample | scope | gen | usefulness | distinctiveness | Atari | audio group | comment |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| pokey_ref_0657f037 | sample_014 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | — | nice mid-len lead sound |
| pokey_ref_089a0846 | sample_009 | PAIR | `$C` | 4.0 | 4.0 | 4.0 | 1 | nice atari lead tone |
| pokey_ref_5ee9c1a8 | sample_017 | VOICE | `$C` | 4.0 | 4.0 | 4.0 | 3 | loud atari-like lead sound |
| pokey_ref_7611576e | sample_013 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | — | nice short lead-like sound |
| pokey_ref_e913803e | sample_028 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | — | short nice lead-like sound |

### B — Character specialists (21)

_Rule:_ described by the listener with words other than "lead"

| profile | sample | scope | gen | usefulness | distinctiveness | Atari | audio group | comment |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| pokey_ref_23665c4f | sample_010 | VOICE | `$8` | 4.0 | 3.0 | 4.0 | — | perc? |
| pokey_ref_c25e268b | sample_034 | VOICE | `$0` | 3.0 | 5.0 | 2.0 | 5 | very loud crackling sound |
| pokey_ref_af009fe0 | sample_045 | VOICE | `$0` | 3.0 | 4.0 | 2.0 | 5 | rustling sound |
| pokey_ref_c53d7640 | sample_032 | VOICE | `$0` | 3.0 | 4.0 | 2.0 | 5 | interesting loud crackling sound |
| pokey_ref_050170ef | sample_053 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | — | perc/bass? |
| pokey_ref_1bed70f4 | sample_056 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 4 | noise/bass? |
| pokey_ref_1e9be30a | sample_051 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | noisy bass/perc? |
| pokey_ref_568403b4 | sample_016 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | noisy bass/perc? |
| pokey_ref_6db98eb5 | sample_058 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | bass/perc? |
| pokey_ref_714607ba | sample_044 | PAIR | `$8` | 3.0 | 3.0 | 4.0 | 4 | bass? |
| pokey_ref_7983ed84 | sample_046 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | bass? |
| pokey_ref_914c63ec | sample_007 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | — | noise (bass?) |
| pokey_ref_9a42d6fe | sample_060 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | — | bass/perc? |
| pokey_ref_a8c81a84 | sample_019 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | — | noisy bass? |
| pokey_ref_cb9b6db2 | sample_027 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 4 | noisy (bass?) |
| pokey_ref_f022d673 | sample_049 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | — | crackling/bass/perc? |
| pokey_ref_a68743ad | sample_024 | PAIR | `$8` | 2.0 | 4.0 | 3.0 | — | noise/bass? |
| pokey_ref_c0b97138 | sample_002 | VOICE | `$0` | 2.0 | 4.0 | 3.0 | — | beat with noise in background |
| pokey_ref_db7fe434 | sample_030 | PAIR | `$8` | 2.0 | 4.0 | 2.0 | — | crackling sound |
| pokey_ref_2de893a6 | sample_041 | VOICE | `$8` | 2.0 | 3.0 | 3.0 | — | noisy bass/perc? |
| pokey_ref_686d2070 | sample_006 | VOICE | `$8` | 2.0 | 3.0 | 4.0 | — | noise (bass?) |

### C — Technically interesting, perceptually weak (20)

_Rule:_ at or above the library's median spectral distance from everything else, while rated ≤ 3 on usefulness

| profile | sample | scope | gen | usefulness | distinctiveness | Atari | audio group | comment |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| pokey_ref_c25e268b | sample_034 | VOICE | `$0` | 3.0 | 5.0 | 2.0 | 5 | very loud crackling sound |
| pokey_ref_331fbbd7 | sample_021 | PAIR | `$C` | 3.0 | 4.0 | 3.0 | — | short lead tone |
| pokey_ref_3627798b | sample_022 | PAIR | `$C` | 3.0 | 4.0 | 3.0 | — | short loud lead tone |
| pokey_ref_af009fe0 | sample_045 | VOICE | `$0` | 3.0 | 4.0 | 2.0 | 5 | rustling sound |
| pokey_ref_b1b73fa2 | sample_036 | PAIR | `$C` | 3.0 | 4.0 | 3.0 | — | interesting loud lead tone |
| pokey_ref_c53d7640 | sample_032 | VOICE | `$0` | 3.0 | 4.0 | 2.0 | 5 | interesting loud crackling sound |
| pokey_ref_1bed70f4 | sample_056 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 4 | noise/bass? |
| pokey_ref_1e9be30a | sample_051 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | noisy bass/perc? |
| pokey_ref_1efd9336 | sample_057 | VOICE | `$6` | 3.0 | 3.0 | 3.0 | — | atari-like lead sound |
| pokey_ref_3c36e574 | sample_059 | PAIR | `$C` | 3.0 | 3.0 | 4.0 | 1 | atari-like lead sound |
| pokey_ref_568403b4 | sample_016 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | noisy bass/perc? |
| pokey_ref_6db98eb5 | sample_058 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | bass/perc? |
| pokey_ref_714607ba | sample_044 | PAIR | `$8` | 3.0 | 3.0 | 4.0 | 4 | bass? |
| pokey_ref_7983ed84 | sample_046 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | bass? |
| pokey_ref_914c63ec | sample_007 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | — | noise (bass?) |
| pokey_ref_9a42d6fe | sample_060 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | — | bass/perc? |
| pokey_ref_cb9b6db2 | sample_027 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 4 | noisy (bass?) |
| pokey_ref_f022d673 | sample_049 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | — | crackling/bass/perc? |
| pokey_ref_c0b97138 | sample_002 | VOICE | `$0` | 2.0 | 4.0 | 3.0 | — | beat with noise in background |
| pokey_ref_686d2070 | sample_006 | VOICE | `$8` | 2.0 | 3.0 | 4.0 | — | noise (bass?) |

### D — Perceptually interesting despite weak machine metrics (11)

_Rule:_ usefulness ≥ 4 and distinctiveness ≥ 3 while sitting at or below the median spectral distance — liked despite looking unremarkable to the metric

| profile | sample | scope | gen | usefulness | distinctiveness | Atari | audio group | comment |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| pokey_ref_0657f037 | sample_014 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | — | nice mid-len lead sound |
| pokey_ref_2b83db43 | sample_001 | VOICE | `$C` | 4.0 | 4.0 | 4.0 | — | short atari lead tone |
| pokey_ref_7611576e | sample_013 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | — | nice short lead-like sound |
| pokey_ref_e913803e | sample_028 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | — | short nice lead-like sound |
| pokey_ref_23665c4f | sample_010 | VOICE | `$8` | 4.0 | 3.0 | 4.0 | — | perc? |
| pokey_ref_3658a088 | sample_061 | PAIR | `$A` | 4.0 | 3.0 | 4.0 | — | clean atari-like lead sound |
| pokey_ref_6ad0e843 | sample_042 | VOICE | `$A` | 4.0 | 3.0 | 4.0 | — | nice lead sound |
| pokey_ref_953311ef | sample_011 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | — | clean atari lead tone |
| pokey_ref_ad730372 | sample_012 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | 0 | very clean atari lead tone |
| pokey_ref_c6eca16a | sample_047 | VOICE | `$A` | 4.0 | 3.0 | 4.0 | — | atari-like lead sound |
| pokey_ref_e86c9631 | sample_015 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | 0 | clean atari lead tone |

### E — Redundant profiles (30)

_Rule:_ renders byte-identical audio to at least one other profile

| profile | sample | scope | gen | usefulness | distinctiveness | Atari | audio group | comment |
| :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| pokey_ref_089a0846 | sample_009 | PAIR | `$C` | 4.0 | 4.0 | 4.0 | 1 | nice atari lead tone |
| pokey_ref_3faf80b4 | sample_023 | VOICE | `$C` | 4.0 | 4.0 | 3.0 | 3 | louder lead nice tone |
| pokey_ref_5ee9c1a8 | sample_017 | VOICE | `$C` | 4.0 | 4.0 | 4.0 | 3 | loud atari-like lead sound |
| pokey_ref_689d3402 | sample_038 | VOICE | `$C` | 4.0 | 4.0 | 3.0 | 3 | less clean atari-like lead sound |
| pokey_ref_ed07bb73 | sample_039 | PAIR | `$C` | 4.0 | 4.0 | 3.0 | 1 | interesting loud lead sound |
| pokey_ref_9a86568a | sample_055 | PAIR | `$C` | 4.0 | 3.0 | 4.0 | 1 | loud lead atari-like sound |
| pokey_ref_a09c0263 | sample_043 | PAIR | `$C` | 4.0 | 3.0 | 3.0 | 1 | lound lead sound |
| pokey_ref_ad730372 | sample_012 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | 0 | very clean atari lead tone |
| pokey_ref_c2983132 | sample_050 | PAIR | `$C` | 4.0 | 3.0 | 3.0 | 1 | atari lound lead sound |
| pokey_ref_e86c9631 | sample_015 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | 0 | clean atari lead tone |
| pokey_ref_feb29c1f | sample_033 | VOICE | `$C` | 4.0 | 3.0 | 3.0 | 3 | nice loud lead tone |
| pokey_ref_0a53188c | sample_031 | VOICE | `$A` | 4.0 | 2.0 | 5.0 | 0 | nice atari-like lead tone |
| pokey_ref_1ef377fc | sample_025 | VOICE | `$A` | 4.0 | 2.0 | 5.0 | 0 | typica clear atari-like nice lead sound |
| pokey_ref_80d1ce25 | sample_003 | VOICE | `$A` | 4.0 | 2.0 | 5.0 | 0 | typical atari lead tone |
| pokey_ref_e4e5235f | sample_029 | VOICE | `$A` | 4.0 | 2.0 | 5.0 | 0 | nice atari-like lead tone |
| pokey_ref_275b992a | sample_005 | VOICE | `$A` | 4.0 | 1.0 | 5.0 | 0 | typical atari lead tone |
| pokey_ref_c321892f | sample_035 | VOICE | `$A` | 4.0 | 1.0 | 5.0 | 0 | clean atari-like lead tone |
| pokey_ref_ef214010 | sample_037 | VOICE | `$A` | 4.0 | 1.0 | 5.0 | 0 | almost clean atari-like lead sound |
| pokey_ref_c25e268b | sample_034 | VOICE | `$0` | 3.0 | 5.0 | 2.0 | 5 | very loud crackling sound |
| pokey_ref_af009fe0 | sample_045 | VOICE | `$0` | 3.0 | 4.0 | 2.0 | 5 | rustling sound |
| pokey_ref_c53d7640 | sample_032 | VOICE | `$0` | 3.0 | 4.0 | 2.0 | 5 | interesting loud crackling sound |
| pokey_ref_1bed70f4 | sample_056 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 4 | noise/bass? |
| pokey_ref_1e9be30a | sample_051 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | noisy bass/perc? |
| pokey_ref_3c36e574 | sample_059 | PAIR | `$C` | 3.0 | 3.0 | 4.0 | 1 | atari-like lead sound |
| pokey_ref_568403b4 | sample_016 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | noisy bass/perc? |
| pokey_ref_6db98eb5 | sample_058 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | bass/perc? |
| pokey_ref_714607ba | sample_044 | PAIR | `$8` | 3.0 | 3.0 | 4.0 | 4 | bass? |
| pokey_ref_7983ed84 | sample_046 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 2 | bass? |
| pokey_ref_cb9b6db2 | sample_027 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 4 | noisy (bass?) |
| pokey_ref_9098232a | sample_008 | VOICE | `$A` | 3.0 | 1.0 | 5.0 | 0 | clear atari lead tone |

## 10. Recommended shortlist

**25 candidates.** Rule: one representative per identically-rendering group (its best-rated member), then the most useful of what remains; the whole 61-profile library is kept untouched

| # | profile | sample | scope | gen | usefulness | distinctiveness | Atari | confidence | why it is here |
| ---: | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- |
| 1 | pokey_ref_0657f037 | sample_014 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | 4.0 | renders audio no other profile produces |
| 2 | pokey_ref_089a0846 | sample_009 | PAIR | `$C` | 4.0 | 4.0 | 4.0 | 4.0 | leads an identically-rendering group of 6 (usefulness 3-4 inside the group): the other members add no sound, and this one is the best rated of them |
| 3 | pokey_ref_2b83db43 | sample_001 | VOICE | `$C` | 4.0 | 4.0 | 4.0 | 4.0 | renders audio no other profile produces |
| 4 | pokey_ref_5ee9c1a8 | sample_017 | VOICE | `$C` | 4.0 | 4.0 | 4.0 | 4.0 | leads an identically-rendering group of 4 (usefulness 4-4 inside the group): the other members add no sound, and this one is the best rated of them |
| 5 | pokey_ref_7611576e | sample_013 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | 4.0 | renders audio no other profile produces |
| 6 | pokey_ref_e913803e | sample_028 | VOICE | `$A` | 4.0 | 4.0 | 4.0 | 4.0 | renders audio no other profile produces |
| 7 | pokey_ref_953311ef | sample_011 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | 5.0 | renders audio no other profile produces |
| 8 | pokey_ref_ad730372 | sample_012 | VOICE | `$A` | 4.0 | 3.0 | 5.0 | 4.0 | leads an identically-rendering group of 10 (usefulness 3-4 inside the group): the other members add no sound, and this one is the best rated of them |
| 9 | pokey_ref_23665c4f | sample_010 | VOICE | `$8` | 4.0 | 3.0 | 4.0 | 3.0 | renders audio no other profile produces |
| 10 | pokey_ref_3658a088 | sample_061 | PAIR | `$A` | 4.0 | 3.0 | 4.0 | 3.0 | renders audio no other profile produces |
| 11 | pokey_ref_6ad0e843 | sample_042 | VOICE | `$A` | 4.0 | 3.0 | 4.0 | 3.0 | renders audio no other profile produces |
| 12 | pokey_ref_c6eca16a | sample_047 | VOICE | `$A` | 4.0 | 3.0 | 4.0 | 3.0 | renders audio no other profile produces |
| 13 | pokey_ref_f3e3c618 | sample_048 | PAIR | `$C` | 4.0 | 3.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 14 | pokey_ref_048db11d | sample_040 | VOICE | `$A` | 4.0 | 2.0 | 4.0 | 3.0 | renders audio no other profile produces |
| 15 | pokey_ref_d172d15e | sample_020 | VOICE | `$A` | 4.0 | 1.0 | 4.0 | 4.0 | renders audio no other profile produces |
| 16 | pokey_ref_c25e268b | sample_034 | VOICE | `$0` | 3.0 | 5.0 | 2.0 | 4.0 | leads an identically-rendering group of 3 (usefulness 3-3 inside the group): the other members add no sound, and this one is the best rated of them |
| 17 | pokey_ref_0bd72343 | sample_052 | VOICE | `$C` | 3.0 | 4.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 18 | pokey_ref_331fbbd7 | sample_021 | PAIR | `$C` | 3.0 | 4.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 19 | pokey_ref_3627798b | sample_022 | PAIR | `$C` | 3.0 | 4.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 20 | pokey_ref_9daa0429 | sample_018 | VOICE | `$A` | 3.0 | 4.0 | 3.0 | 4.0 | renders audio no other profile produces |
| 21 | pokey_ref_b1b73fa2 | sample_036 | PAIR | `$C` | 3.0 | 4.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 22 | pokey_ref_050170ef | sample_053 | PAIR | `$8` | 3.0 | 3.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 23 | pokey_ref_1efd9336 | sample_057 | VOICE | `$6` | 3.0 | 3.0 | 3.0 | 3.0 | renders audio no other profile produces |
| 24 | pokey_ref_568403b4 | sample_016 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 3.0 | leads an identically-rendering group of 4 (usefulness 3-3 inside the group): the other members add no sound, and this one is the best rated of them |
| 25 | pokey_ref_914c63ec | sample_007 | VOICE | `$8` | 3.0 | 3.0 | 3.0 | 3.0 | renders audio no other profile produces |

A purely diversity-driven alternative, chosen greedily to maximise the minimum distance
between members (same machine space, no ratings involved):

* 20: pokey_ref_c0b97138, pokey_ref_914c63ec, pokey_ref_3658a088, pokey_ref_0bd72343, pokey_ref_e913803e, pokey_ref_1efd9336, pokey_ref_0657f037, pokey_ref_db7fe434, pokey_ref_331fbbd7, pokey_ref_2de893a6, pokey_ref_048db11d, pokey_ref_a8c81a84, pokey_ref_6ad0e843, pokey_ref_f3e3c618, pokey_ref_9daa0429, pokey_ref_af009fe0, pokey_ref_25f94201, pokey_ref_a68743ad, pokey_ref_959628d6, pokey_ref_050170ef
* 25: pokey_ref_c0b97138, pokey_ref_914c63ec, pokey_ref_3658a088, pokey_ref_0bd72343, pokey_ref_e913803e, pokey_ref_1efd9336, pokey_ref_0657f037, pokey_ref_db7fe434, pokey_ref_331fbbd7, pokey_ref_2de893a6, pokey_ref_048db11d, pokey_ref_a8c81a84, pokey_ref_6ad0e843, pokey_ref_f3e3c618, pokey_ref_9daa0429, pokey_ref_af009fe0, pokey_ref_25f94201, pokey_ref_a68743ad, pokey_ref_959628d6, pokey_ref_050170ef, pokey_ref_089a0846, pokey_ref_c6eca16a, pokey_ref_b1b73fa2, pokey_ref_d172d15e, pokey_ref_7611576e
* 30: pokey_ref_c0b97138, pokey_ref_914c63ec, pokey_ref_3658a088, pokey_ref_0bd72343, pokey_ref_e913803e, pokey_ref_1efd9336, pokey_ref_0657f037, pokey_ref_db7fe434, pokey_ref_331fbbd7, pokey_ref_2de893a6, pokey_ref_048db11d, pokey_ref_a8c81a84, pokey_ref_6ad0e843, pokey_ref_f3e3c618, pokey_ref_9daa0429, pokey_ref_af009fe0, pokey_ref_25f94201, pokey_ref_a68743ad, pokey_ref_959628d6, pokey_ref_050170ef, pokey_ref_089a0846, pokey_ref_c6eca16a, pokey_ref_b1b73fa2, pokey_ref_d172d15e, pokey_ref_7611576e, pokey_ref_9a42d6fe, pokey_ref_3faf80b4, pokey_ref_d9bef36c, pokey_ref_23665c4f, pokey_ref_2b83db43

## 11. Redundancy and coverage

**Observed.** Clustering the profiles by their spectral band energies (average linkage over
the same distance the A/B programme used):

| cut | clusters | sizes |
| :--- | ---: | :--- |
| 0.02 | 4 | [23, 17, 16, 5] |
| 0.05 | 3 | [23, 21, 17] |
| 0.10 | 2 | [40, 21] |

Two-dimensional principal projection of the band energies explains 64.6% and 26.9% of the variance; coordinates are in `reports/stage9d/coverage.json`.

* 37 distinct audio signals from 61 profiles
* 24 profiles are duplicates of another profile's audio

**Inference.** The perceptual space the *player* can currently reach is far smaller than the
profile count suggests, and it is occupied unevenly: a large block of noise/bass-like
profiles around 4.1 kHz centroid with flatness ≈ 0.50, a smaller block of pure-tone-like
profiles around 6.0 kHz, and few isolated sounds. A small library therefore needs one member
from each occupied region — not the top N by any single rating.

## 12. Limitations

* **One listener, one session.** Every rating is a single observation by a single person
  with prior knowledge of the Atari sound world. There is no inter-listener agreement to
  report, so nothing here is a population estimate.
* **The stimulus shapes the vocabulary.** One melodic phrase on one channel means the
  experiment could not present a profile as percussion or as a bass line, and "lead"
  dominates the comments (40 of 61).
* **A session effect is present.** Atari character and confidence correlate negatively with
  presentation position (see §3.3), so the later part of the session was rated with less
  discrimination.
* **Gestures are not rendered.** Profiles measured with a pitch/volume contour were heard as
  static tones; their real character is not what was judged.
* **Distinctiveness is reliable but coarse.** The listener was consistent about the same
  sound (ICC(1,1) 0.7287), yet the same sound still drew ratings up to
  2 points apart, so only group-level
  differences on that scale should be read.
* **Six songs.** Part C is a description of six pieces, not a result about the integration.
* **No Stage 6/7B metrics are available** in the manifest, so the transferability and
  perceptual-metric hypotheses cannot be tested here.

### A defect in Stage 9C, recorded rather than corrected

The listening experiment deliberately renders every profile through one musical stimulus, and
that stimulus is chosen to keep the profile as the only variable. The consequence, visible for
the first time in these results, is that 24 of 61 profiles
produce audio **identical to another profile's**, so the experiment spent part of the
listener's attention comparing a sound with itself under two labels. Stage 9C's manifest
recorded the renderings faithfully — the duplicates are visible in it as equal feature
vectors — but did not report the duplication as a property of the *library*, which it is. No
historical data was modified; the finding is recorded here and used in §10 and §11, and it is
the main reason this report does not read Part A as a ranking.

## 13. Conclusions

**Observed.** The library's 61 renderable profiles make 37 distinct sounds under a fixed musical input; means are 3.4 (usefulness), 3.1 (distinctiveness), 3.583 (Atari character); the spectral distance predicts perceived similarity between isolated sounds (rho -0.6628) while being blind to level; and on whole songs the profile-bound render lost to the composer's defaults 5–0 with one tie.

**Inference.** Two different answers, and they must not be averaged into one:

1. **As isolated sounds, the profiles work.** The listener consistently found them Atari-like
   and useful, and the machine distance agrees with the listener about similarity. But what
   the experiment had to listen to was one melodic phrase, and 24 of the 61 profiles render
   audio identical to another profile's — so the library's *audible* size is roughly 37, not 61.
2. **As a way to make a song better, this integration failed the test it was built for.** Six
   songs, one unanimous direction. A profile measured from a classic tune is not automatically
   a better instrument for a new tune than the composer's own defaults, and the bindings in
   `examples/songs/` were chosen by generator family rather than by any listening evidence.

**Recommendation.** Do not select a production palette from this evidence. Fix the two things
that the data now names — the metric's level blindness and the integration's binding strategy —
and re-run a whole-song comparison before returning to selection.

### What the data does *not* allow us to say

* that any profile is good or bad as an instrument: the ratings are one listener's, on one
  stimulus, and a one-point difference is inside that listener's own repeatability;
* that profile-bound rendering in general is worse than the defaults: six songs, six bindings,
  one listener;
* that the machine metrics are useless: the distance tracked similarity strongly, and the
  failure is specific and named (level).

## 14. Recommended next stage

The whole-song result, not the profile ratings, decides what comes next. Two defects are now
named and testable, and both should be fixed **before** any selection:

1. **The similarity metric is blind to level.** It normalises the spectrum, so two profiles
   whose sustain differs by 10 dB score as nearly identical. Add the level/RMS term (and, if
   it helps, the envelope) to the distance and re-check §4's table; the listener's own
   ratings already show level is part of what they hear.
2. **The bindings were chosen by generator family, not by evidence.** The picks in
   `examples/songs/` ignored the listening results entirely, and five of six songs got worse.
   Re-bind the same songs using the shortlist in §10 — one representative per audio group,
   preferring the profiles this listener rated useful — and repeat **only** the Part C
   comparison. That is a small, cheap, decisive experiment.

Then, and only then:

3. Select the production palette from the audio groups (not from profile ids), one member
   each, and publish it as a curation document over the existing bank — no profile renamed,
   altered or removed.

Proposed shape of that next stage: Stage 9E, in two steps and in this order: (1) fix the metrics and the bindings — add the level/RMS term the similarity distance is blind to, and re-bind the six songs from the listening evidence instead of by generator family; (2) repeat ONLY the whole-song comparison, and select the palette only if the profile-bound render stops losing to the defaults. Selection itself must work on audio groups rather than profile ids and must publish a curation document over the existing bank — no profile renamed, none deleted.

### Closing answer

> Is there enough evidence to move to selecting a small production POKEY sound profile library?

**NO**

* the library separates into usable groups at a small spectral cut — met (3 groups at cut 0.05)
* the listening found more than one sound — met (37 distinct audio signals cover 61 profiles)
* redundancy is limited enough that a shortlist is not arbitrary — met (39% of profiles share their audio with another profile)
* profile-bound rendering does not lose overall to the defaults — **not met** (profile won 0, default won 5 of 6 songs)
* no loudness correlation large enough to explain the ratings — met (largest |rho| against RMS is 0.25)
* a spectral metric predicts what the listener heard — met (rho(distance, similarity) = -0.6628)

Not met: profile-bound rendering does not lose overall to the defaults.

The isolated-sound evidence is *usable*; the whole-song evidence is *negative*. Selecting now
would mean choosing a palette on the strength of 3.2-second audio samples while the one test
that used real music says the result got worse — which is exactly the reasoning this stage was
asked to resist.

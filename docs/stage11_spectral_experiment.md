# Stage 11B — controlled spectral experiment

Can the *existing* POKEY renderer reproduce the spectral character the archaeology measured, and which single profile feature moves the rendered spectrum furthest toward the reference? This experiment answers that with the renderer unchanged: a common test signal, six controlled variants per profile, and spectral features computed on the audio.

* experiment: `stage11b` (`stage11b/1`)
* profiles selected: **8** distinct-audio representatives
* expressibility: **5 PARTIALLY_EXPRESSIBLE**, **3 UNTESTED**
* best single feature: audctl (1), envelope (1), generator (3)
* blind listening package: **not prepared**

## B1. The selected sounds

**Observed.** One representative of every duplicate group (so no two selections render identical audio) plus isolated singletons, spanning the generator families and both scopes. Selection rationale is per row.

| profile | scope | distortion | family | category | rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| pokey_ref_050170ef | PAIR | $8 | poly9/17 direct (noise) | noisy / percussive | renders audio no other profile produces (isolated singleton) |
| pokey_ref_0657f037 | VOICE | $A | pure tone | clean tonal | renders audio no other profile produces (isolated singleton) |
| pokey_ref_089a0846 | PAIR | $C | poly4 direct | 16-bit coupled (bass-register) | one representative of duplicate group 1 |
| pokey_ref_0bd72343 | VOICE | $C | poly4 direct | clean tonal | renders audio no other profile produces (isolated singleton) |
| pokey_ref_1efd9336 | VOICE | $6 | poly5-gated pure (buzz) | buzzy / gated poly | renders audio no other profile produces (isolated singleton) |
| pokey_ref_2de893a6 | VOICE | $8 | poly9/17 direct (noise) | noisy / percussive | renders audio no other profile produces (isolated singleton) |
| pokey_ref_3658a088 | PAIR | $A | pure tone | 16-bit coupled (bass-register) | renders audio no other profile produces (isolated singleton) |
| pokey_ref_af009fe0 | VOICE | $0 | poly5-gated poly9/17 (noise) | noisy / percussive | one representative of duplicate group 5 |

## B2. The common test signal

**Observed.** One `C4` note held for 20 steps on POKEY channel 1 at 44100 Hz, identical for every profile; the existing frame compiler and synthesiser, unchanged. The synthesiser normalizes every buffer to a 0.90 peak, so the variants are level-matched by construction..

## B3. The controlled variants

**Experimental choice.** Every variant is the same note with a different subset of the profile's *representable* facts applied — the composer's own instrument for the rest:

```text
baseline  -> the composer's own instrument, no profile
generator -> + the profile's distortion nibble
envelope  -> + the profile's four-number ADSR
audctl    -> + the profile's AUDCTL and 16-bit coupling
generator_envelope -> + distortion and ADSR together
full      -> + everything the binding writes (the Stage 9E six scalars)
```

All five features are expressible by the current renderer, so no variant is marked NOT EXPRESSIBLE; a feature the renderer *cannot* express (pitch trajectory, a per-frame divider macro) is simply not part of this ablation and is listed in §B9.

## B4 / B5. Spectral descriptors, and the distance to the reference

**Observed.** `centroid`/`bandwidth`/`flatness` are the Stage 9C descriptors, computed on the rendered audio; the reference column is the same descriptor computed on the archaeology's own `reference_replay.wav`. `dist` is 1 - cosine of the band-energy vectors (0 = identical distribution). A smaller distance is closer to the measured character.

| profile | scope | ref centroid | base centroid | full centroid | ref bandwidth | base bandwidth | full bandwidth | base dist | full dist |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| pokey_ref_050170ef | PAIR | 5703 | 5579 | 3922 | 6034 | 6380 | 5632 | 0.2452 | 0.1703 |
| pokey_ref_0657f037 | VOICE | 4754 | 5579 | 5546 | 5973 | 6380 | 6368 | 0.2228 | 0.2192 |
| pokey_ref_089a0846 | PAIR | 5761 | 5579 | 6641 | 6119 | 6380 | 6428 | 0.2337 | 0.0592 |
| pokey_ref_0bd72343 | VOICE | — | 5579 | 6230 | — | 6380 | 6275 | — | — |
| pokey_ref_1efd9336 | VOICE | — | 5579 | 7018 | — | 6380 | 6240 | — | — |
| pokey_ref_2de893a6 | VOICE | 5300 | 5579 | 3764 | 6114 | 6380 | 5552 | 0.1699 | 0.0752 |
| pokey_ref_3658a088 | PAIR | 9654 | 5579 | 5973 | 6620 | 6380 | 6539 | 0.3224 | 0.2836 |
| pokey_ref_af009fe0 | VOICE | — | 5579 | 6520 | — | 6380 | 6057 | — | — |

## B6. Controlled ablation — which feature moves the spectrum

**Observed.** The change in distance to the reference when each single feature is applied alone (negative = moves *toward* the reference). The last column names the single feature that moves furthest.

| profile | Δ generator | Δ envelope | Δ audctl | Δ full | best single feature |
| :--- | :--- | :--- | :--- | :--- | :--- |
| pokey_ref_050170ef | -0.0745 | -0.0042 | -0.0165 | -0.0749 | generator |
| pokey_ref_0657f037 | 0.0000 | -0.0036 | 0.0000 | -0.0036 | envelope |
| pokey_ref_089a0846 | -0.1722 | 0.0000 | -0.0181 | -0.1745 | generator |
| pokey_ref_0bd72343 | — | — | — | — | — |
| pokey_ref_1efd9336 | — | — | — | — | — |
| pokey_ref_2de893a6 | -0.0992 | -0.0115 | 0.0000 | -0.0947 | generator |
| pokey_ref_3658a088 | 0.0000 | 0.0000 | -0.0388 | -0.0388 | audctl |
| pokey_ref_af009fe0 | — | — | — | — | — |

## B7. The listener's vocabulary against the measured structure

**Inference.** The ablation shows the spectral axis the renderer already reproduces is the *generator*: applying the profile's distortion nibble is normally the single feature that moves the band-energy distribution most. That is the same axis the listener's own words track — Stage 9D found the clean/noisy families disjoint (clean centroid median 6018 Hz, noisy 4135 Hz) and that `same_generator` predicts a heard difference at rho -0.5993. The listener's *rising* vocabulary is pitch, which this renderer cannot express.

## B8. Renderer capability — per selected sound

**Observed.** EXPRESSIBLE/PARTIALLY_EXPRESSIBLE/NOT_EXPRESSIBLE is decided by whether the representable profile moves the render toward its reference, and by how much residual is left (thresholds in `spectral_summary.json`, named as experimental choices).

| profile | scope | classification | improvement | why |
| :--- | :--- | :--- | :--- | :--- |
| pokey_ref_050170ef | PAIR | PARTIALLY_EXPRESSIBLE | 0.074864 | the representable profile moves the spectrum toward the reference but a residual band-energy difference remains |
| pokey_ref_0657f037 | VOICE | PARTIALLY_EXPRESSIBLE | 0.003647 | the representable profile moves the spectrum toward the reference but a residual band-energy difference remains |
| pokey_ref_089a0846 | PAIR | PARTIALLY_EXPRESSIBLE | 0.174491 | the representable profile moves the spectrum toward the reference but a residual band-energy difference remains |
| pokey_ref_0bd72343 | VOICE | UNTESTED | — | no archaeology reference replay exists for this profile, so the render cannot be compared against the measured character; the ablation is still reported |
| pokey_ref_1efd9336 | VOICE | UNTESTED | — | no archaeology reference replay exists for this profile, so the render cannot be compared against the measured character; the ablation is still reported |
| pokey_ref_2de893a6 | VOICE | PARTIALLY_EXPRESSIBLE | 0.094708 | the representable profile moves the spectrum toward the reference but a residual band-energy difference remains |
| pokey_ref_3658a088 | PAIR | PARTIALLY_EXPRESSIBLE | 0.038798 | the representable profile moves the spectrum toward the reference but a residual band-energy difference remains |
| pokey_ref_af009fe0 | VOICE | UNTESTED | — | no archaeology reference replay exists for this profile, so the render cannot be compared against the measured character; the ablation is still reported |

## B9. Capabilities observed but not implemented

**Observed, not implemented.** The experiment confirms the renderer expresses the five facts it is asked to (distortion, envelope, AUDCTL, coupling). The capabilities it cannot express, found earlier and unchanged here, remain:

```text
observed capability        required representation              current limitation
pitch trajectory           per-frame divider macro              player holds one divider per row
dynamic distortion         per-frame AUDC generator change      player sets AUDC once per channel
intra-note volume shape    per-frame volume macro (Stage 10B)   player recomputes ADSR only
```

None is implemented; each needs a player/IR change and would fail the Stage 11 rule against changing the renderer to perform an experiment.

## B10. Listening package

**Experimental choice.** no render comes within the match threshold of its reference, so the analysis makes no spectral claim a listener could be asked to hear; the axes that move materially (generator, coupling) are already known audible.
 A blind package is therefore **not** prepared: the brief says to prepare one only if the quantitative analysis identifies a meaningful spectral hypothesis, and this one does not — the renderer already reaches the generator axis, and where it cannot reach the reference it is because the missing information is temporal, which a level-matched A/B of the *existing* renderer could not demonstrate.

## B11. Reproducibility

Every number above is a pure function of the profiles, the bank, the Stage 9E duplicate groups and the archaeology reference WAVs below (SHA-256); there is no timestamp in any artefact, the selection is `sorted` on every axis, and the synthesiser's own normalization makes the variants level-matched by construction. Re-running writes byte-identical files.

```json
{
  "archaeology/pokey_ref_050170ef/reference_replay.wav": "cb7e5beca55aae682af44e0e41194427e6599d573ba4bdca0c7cd372e768ea38",
  "archaeology/pokey_ref_0657f037/reference_replay.wav": "bbb9ffdac6be1f17060c57f161ef217b0eac3bd969e9aac474a4f6ba3fe99060",
  "archaeology/pokey_ref_089a0846/reference_replay.wav": "aecbedf0940a55f91f72e7fea9b50296bf2592667646294b04e42863f237ddb6",
  "archaeology/pokey_ref_2de893a6/reference_replay.wav": "6ceb3436200a4bf75341a5ce12168cbd9b6fe45c199c15e94207573e342aaebe",
  "archaeology/pokey_ref_3658a088/reference_replay.wav": "9efa6b44963f7b8b36f4a54e4b6cb9587bd74e2680dfaaf2dc4fc2ef04332653",
  "bank/registry.json": "b78faec3738cc127d21ae571f526f5761a4292f302eb07de7ba08794746a81fb",
  "reports/stage9e/duplicate_groups.json": "65742bff0633cd62e42f8c3b1c69438fe1f6538f064d00f48a0925e8ae422a46"
}
```

## Final report — the eight questions

**1. What does the existing evidence say?** Not what was hoped. The binding reads 13 of 232 documented leaf paths; the first loss is at the binding boundary; 24 of 61 renderable profiles collapse into 6 duplicate audio groups; and binding profiles to real songs has lost to the composer's own defaults in every listening test so far (Stage 9D 5-0; Stage 10A; Stage 10B's controls).

**2. Which features are demonstrably perceptually useful?** *Strong:* the generator family (9D `same_generator` vs similarity -0.5993; disjoint clean/noisy families; the listener's own vocabulary). *Weak:* envelope and AUDCTL alone — they change the WAV but have never been heard in isolation. *Inconclusive:* the spectral descriptors (the bandwidth/usefulness correlation flips sign between the two datasets). *Negative:* the volume contour (Stage 10B). *Not tested:* pitch trajectory.

**3. Why do the profiles collapse?** Representation, at the PlayableSoundProfile -> POKEY IR boundary: the binding carries six scalars, so profiles that share them render identically however much they differ in the measured gesture. It is not a renderer limit — the audio is a pure function of the register frames the binding does write.

**4. Is volume contour worth pursuing?** No. It is expressible, changes the waveform, and was rejected (Stage 10B: 8/8 profile pairs 'no clear difference', song-level C 1-2-3, verdict NEGATIVE).

**5. Is pitch trajectory worth pursuing?** It is the largest untested representable gap and the listener has a word for it ('rising'), but no preference evidence exists and its per-frame form is not expressible by the current player. It is worth *investigating*, not yet worth implementing.

**6. Is spectral/timbral representation the strongest remaining hypothesis?** **Inconclusive, leaning no.** The renderer already reproduces the dominant audible spectral axis (the generator), the descriptor-level correlation with usefulness is unstable, and the largest measured gap is temporal. The spectral hypothesis is not supported as *the* bottleneck.

**7. Can the current renderer reproduce the important spectral characteristics?** See §B8 for the per-sound classification. The generator axis is EXPRESSIBLE, the coupled and envelope facts are EXPRESSIBLE, and where a reference is not reached it is because the information that would reach it is temporal — the *profile* cannot express it, not the *waveform*.

**8. The single highest-value next engineering step.** **Improve profile representation — change *how* a bound profile is applied, not what else it stores.** The measured cause of the whole failure is that the binding *replaces* the composer's tuned generator, envelope and clock wholesale (Stage 9E Q5/Q6), which is why the composer's own instruments keep winning. The next step is to make a profile decorate the composer's instrument — contribute its measured spectral character — rather than substitute for it, and to test that with one whole-song listening comparison. Nothing else in this stage's evidence has the same reach, and it needs no new profile field.


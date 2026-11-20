# Stage 14 — final evidence synthesis and SoundProfile go/no-go

**RECOMMENDATION: OPTION C**

An analysis-only close of the transfer hypothesis. Nothing is rendered, nothing is changed, and no new listening is asked for; the evidence is Stages 7B through 13A, including the Stage 12A and 13A answer sheets, which are decoded here for the first time.

## 1. Executive conclusion

**Inference.** Archaeology-derived SoundProfiles contain real, correctly measured information, and that information can be transferred into the Composer's renderer frame-exactly. It is **not** context-independent enough to improve a new composition: in five independent listening experiments across four stages the profile-derived side was level with or behind the Composer's own sound, and the two newest experiments used controls (a byte-identical baseline, a donor trajectory from another profile) that could not have favoured the Composer by construction.

This is not a claim that the profiles are worthless, that the renderer is inadequate, or that the representation is wrong. It is the narrower, supported claim that the measured properties are largely properties of the *interaction* the archaeology recorded, not portable instrument characteristics.

| | |
| :--- | :--- |
| capability rows judged | 10 |
| judged NEGATIVE on perceptual usefulness | 5 — volume contour, pitch trajectory, profile replacement (the binding as it stands), profile decoration (keep the Composer instrument, take the generator), direct profile rebinding (evidence-chosen assignment) |
| judged POSITIVE on perceptual usefulness | none |
| direct profile transfer | **DIRECT TRANSFER NOT SUPPORTED** |
| context dependence | **SUPPORTED** |
| sound-design knowledge base | **PLAUSIBLE, NOT SUPPORTED** |
| recommendation | **RECOMMENDATION: OPTION C** |

## 2. Evidence base

**Observed.** Every artefact below was read directly rather than summarised, and hashed so the synthesis is reproducible:

```json
{
  "archaeology/reports/stage7b/human_evaluation_summary.json": "4f655a0add8eaca0f7e15b1900e59efd300372c61416b7cdb3c6616ed38b5a01",
  "archaeology/reports/stage8c/playability_audit.json": "0169755549e69252c6524e3093d0e447409b4f6fb18f076312eacf978c9d1b44",
  "examples/stage12a_listening/evaluation_stage12a.csv": "80f201f9e284ca5b13909feb8536d12f73e1c4a7ab095d7ebacd5aaf0d185469",
  "examples/stage12a_listening/manifest.json": "34f061b24fdcff7cf31b4a75004977d7eb6e7bccab8ad6b00e35a3c482ee3f9c",
  "examples/stage13a_listening/evaluation_stage13a.csv": "02fbd7bd2cc9624c803283bab9d7bf7cad812dad626469e479107cd1458368f5",
  "examples/stage13a_listening/manifest.json": "020679b96d1805526495556858898940f6d689b0f7f541db7e8797cc026549eb",
  "reports/stage11/collapse.json": "0bc110b556843245edb929097c89c6f962c236650deac16732cbf972458f2853",
  "reports/stage11/feature_classification.json": "f5086a93d276d02ea7ea9cf3264bb1b436bb22c460bb2122f85e855d386ef7de",
  "reports/stage11/go_no_go.json": "c456c2cacf0904e9a5829cd3c5fe5a5f07b0ce72763db9de85335a54d727ba65",
  "reports/stage11/hypothesis_ranking.json": "e007555afabc8c4275c57bfc474f239f0562b9f61e05b9d3c99dcbae37e6cadc",
  "reports/stage11/representation_gap.json": "92ba5fbf6fdcabb41ca9047deed7e85d1ac91c5e7d35ff737056e777f2cdd75a",
  "reports/stage11/spectral_summary.json": "8f2a78e56118a557bc189b65d894ea5cf38cabba5ec3785cd80969fbe74e7209",
  "reports/stage11/stage10a_reevaluation.json": "aa19be27ddd844a7d4d2d87432096acbbbe4db52d8ae9fd6eef54f0cb9e06a4a",
  "reports/stage11/stage10b_reevaluation.json": "62940d4cf2aab06fb56c3a7fe8ff952dbf8c72e6f556ea883ae3e0e0d07ea95d",
  "reports/stage12a/hypotheses.json": "8a6263e5ba478840e5e962efad61764434c94e4f359f90d2ad1675cb93eb5865",
  "reports/stage12a/summary.json": "6d55a3cc327b8c82235cc002ca713ef3123e4f35ed286374487fd353519dd4ce",
  "reports/stage13a/hypotheses.json": "bf0be3235d61fb8aa80952f3fead6b245b884abf762a413564889ed75a37a5c0",
  "reports/stage13a/listening.json": "40ff539fe2f69fc9ebc94cbdf2efd2540f646a564a22a78f9a1c50f2a29b9ce3",
  "reports/stage13a/reconnaissance.json": "78c64ec41e66ddc36ad9cdfc98f891e45758e158cc67828f908257939360e0a1",
  "reports/stage13a/selection.json": "da8844d09f0a834f090d324a66c6c56b413866343b4d5e8eb5b7c6a549d0fc58",
  "reports/stage9d/correlations.json": "c9bd2495031bb5d044752f0ac5477cf3a5cd3ce9a35ef54c6b6f95512b655afd",
  "reports/stage9d/coverage.json": "726bfa7086ed2faca5d449a705a5817afdd8b171d8022e0fb0bd76e26f02e39c",
  "reports/stage9d/verdict.json": "d73e06ac78e55e4746a0db0b4c08685918dde58bcc43c8032dc67750891c3dd1",
  "reports/stage9e/duplicate_groups.json": "65742bff0633cd62e42f8c3b1c69438fe1f6538f064d00f48a0925e8ae422a46",
  "reports/stage9e/information_loss.json": "c7fd034f9748e4fe8cc63bd459aba675d847fb669994c0e84844739ee349fef0",
  "reports/stage9e/pipeline_fields.json": "f556147e0d84a2f302ab821a89513bfa25d982ab6da2dd8070d71bc12b3ae5c1"
}
```

| stage | what it contributed | trials | key measurement |
| :--- | :--- | :--- | :--- |
| 7B | candidate usefulness, distinctiveness, fidelity, vocabulary | 20 candidates | fidelity vs similarity rho 0.5426 |
| 9D | profile rendering, profile- and song-level listening | 60 ratings, 30 A/B, 6 songs | 37 distinct signals of 61 |
| 9E | representation gap | none | 13 of 232 paths read, first divergence bound_ir |
| 10A | evidence-chosen re-binding | 18 pairs | NEW 2 of 12 |
| 10B | volume contour | 18 pairs | profile 0-0-8, song 1-2-3 |
| 11 | synthesis and controlled spectral ablation | none | generator dominates the ablation; 5 PARTIALLY_EXPRESSIBLE, 3 UNTESTED |
| 12A | decoration versus replacement | 8 pairs | C-vs-A 1-3, C-vs-B 1-0 (3 ties) |
| 13A | pitch trajectory | 15 pairs | isolated 4-0, phrase 1-3, donor 1-2 |

## 3. Master evidence matrix

Four claims, kept apart deliberately: **A** technically representable, **B** acoustically measurable, **C** perceptually detectable, **D** perceptually useful. A capability can be A-B-C and still fail D — which is what the evidence shows.

| capability | A | B | C | D | evidence strength | verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| generator / distortion | POSITIVE | POSITIVE | POSITIVE | INCONCLUSIVE | STRONG (detection), NONE (preference) | SUPPORTED as a perceptual axis; preference untested |
| static envelope (ADSR) | POSITIVE | POSITIVE | NOT_TESTED | NOT_TESTED | WEAK | NOT_TESTED in isolation |
| AUDCTL / clock | POSITIVE | POSITIVE | NOT_TESTED | NOT_TESTED | WEAK | NOT_TESTED in isolation |
| 16-bit coupling | POSITIVE | POSITIVE | INCONCLUSIVE | INCONCLUSIVE | WEAK | INCONCLUSIVE |
| volume contour | POSITIVE | POSITIVE | POSITIVE | NEGATIVE | MODERATE (detection), STRONG (negative preference) | NEGATIVE |
| pitch trajectory | POSITIVE | POSITIVE | POSITIVE | NEGATIVE | STRONG (detection), STRONG (negative in context) | NEGATIVE in context |
| spectral structure (centroid / bandwidth / descriptors) | NEGATIVE | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | WEAK (unstable sign) | INCONCLUSIVE, leaning negative |
| profile replacement (the binding as it stands) | POSITIVE | POSITIVE | POSITIVE | NEGATIVE | STRONG (negative) | NEGATIVE |
| profile decoration (keep the Composer instrument, take the generator) | POSITIVE | POSITIVE | POSITIVE | NEGATIVE | STRONG (negative) | NEGATIVE |
| direct profile rebinding (evidence-chosen assignment) | POSITIVE | POSITIVE | POSITIVE | NEGATIVE | MODERATE (negative) | NEGATIVE |

**Observed.** The number behind each row:

* **generator / distortion** — read by the binding and the frame compiler; 9D `same_generator` vs similarity rho -0.5993 and disjoint clean/noisy families make it the axis the listener keys on, but no experiment varied the generator alone and asked for a preference _(stage9e/pipeline_fields.json; stage9d/correlations.json)_
* **static envelope (ADSR)** — the four-number player state machine; 9E measured `envelope.decay_frames` as inert, and Stage 12A changed the envelope in 3 of 6 cases with no preference test _(stage9e/information_loss.json (L2); stage12a/summary.json)_
* **AUDCTL / clock** — one song-global byte; 9E measured the AUDCTL column as audible for PAIR and inert for VOICE; Stage 12A classified it GLOBAL_CONSTRAINT, not decorative _(stage9e/pipeline_fields.json; reports/stage12a/summary.json)_
* **16-bit coupling** — 18 of 61 renderable profiles are PAIR; 9D `same_scope` vs similarity is only -0.308, the weakest of its six cues, and Stage 13A's donor control was a coupled trajectory that the listener preferred 2-1 where it was audible _(stage9d/correlations.json; stage13a listening sheet)_
* **volume contour** — transferred frame-for-frame and heard in 7 of 18 pairs; profile-level 0-0-8, whole-song 1-2-3, resolved verdict NEGATIVE (Stage 10B) _(stage10b_reevaluation.json; docs/stage10b_volume_contour_listening.md)_
* **pitch trajectory** — 8 of 8 technically transferred, 6 of 8 measurably beyond static pitch; in the blind sheet the isolated pairs preferred it 4-0 and it was heard as `modulated` against a `clean tone`, but the phrase pairs preferred the static side — and the profile's own trajectory lost the donor control 1-2 _(stage13a/hypotheses.json; stage13a listening sheet)_
* **spectral structure (centroid / bandwidth / descriptors)** — not a field of PlayableSoundProfile 1.0; the descriptor named `spectral bandwidth (Hz)` correlates with usefulness at -0.4401 in Stage 7B and +0.6338 in Stage 9D; Stage 11B found the generator already carries the audible spectral axis _(stage7b/human_evaluation_summary.json; stage9d/correlations.json; stage11/spectral_summary.json)_
* **profile replacement (the binding as it stands)** — 9D preferred the Composer's own instruments 5-0 (one tie) on six songs, unanimously on all three questions _(stage9d_human_listening_results.md)_
* **profile decoration (keep the Composer instrument, take the generator)** — mechanical H1 3/6 and H2 4/6; in the blind sheet decoration lost to the Composer baseline 1-3 and drew 1-0 (3 ties) against replacement _(stage12a/summary.json; stage12a listening sheet)_
* **direct profile rebinding (evidence-chosen assignment)** — NEW won 2 of 12 primary pairs (other side 6, ties 4); the control put the Composer default over the old binding 4-1 _(stage11/stage10a_reevaluation.json)_

## 4. Direct profile transfer verdict

**DIRECT TRANSFER NOT SUPPORTED.**

**Observed — the representation finding, and why it matters.** Stage 9E: 232 documented leaf paths, 13 read by the binding, first divergence at `bound_ir`, 24 of 61 profiles collapsing into 6 representation-duplicate audio groups. It proved the library's *audible size* is set by six scalars rather than by the 232 paths the archaeology measured — a real, measured architectural fact, and the reason whole families of profiles render identically.

**Observed — reconciled with the later experiments.** Later stages repaired parts of that loss deliberately and measured the result. Volume contour (10B) and pitch trajectory (13A) are exactly the information Stage 9E said was discarded: both were transferred, both reached the audio, and neither survived a listening comparison. Decoration (12A) kept the Composer's tuning and still lost to the Composer's plain sound.

**Inference.** Representation loss was real. Fixing representation loss is not itself evidence that the recovered information is desirable in a new composition.

| question | answer | evidence |
| :--- | :--- | :--- |
| 1. Does the profile contain transferable information? | YES | a profile is self-sufficient and renders without the trace (Stages 3-4); 8 of 8 pitch trajectories transferred frame-exactly; the contour transferred frame-for-frame (10B). |
| 2. Is that information independent of the original musical context? | NOT ESTABLISHED — the evidence points the other way | the same trajectory that was preferred on an isolated note was rejected on the same note inside a phrase: 4-0 isolated versus 1-3 in a phrase, where the listener called it 'not harmonized' and 'broken'. |
| 3. Does transferring it improve new music? | NO | 9D 5-0 to the Composer's defaults; 10A re-binding down 2-6 with a default-winning control; 10B whole-song 1-2-3; 12A decoration down 1-3. |
| 4. Does it preserve musical character? | LESS WELL THAN THE COMPOSER'S OWN INSTRUMENTS | replacement overwrites the character-derived envelope and clock (9E L1); the listener's own words were 'clean', 'harmonized' and 'typical Atari tone' for the Composer side. |
| 5. Does the listener prefer it? | NO — in every whole-song comparison | 9D 0-5-1, 10A, 10B 1-2-3, 12A, 13A phrase 1-3. The only wins for a profile-derived feature are the isolated pitch trials and one 10B song pair. |
| 6. Is the benefit reproducible? | THERE IS NO BENEFIT TO REPRODUCE | what replicates is the failure: independent listening experiments across five stages converge on the same direction, which is itself a reproducible result. |

## 5. Profile replacement verdict

**Profiles should replace the Composer's instruments** — stages 9D, 10A.

**Observed.** 9D: the profile-bound render lost 5-0 (one tie) to the Composer's own instruments, unanimously on all three questions. 10A: the evidence-chosen re-binding won 2 of 12 primary pairs against 6 for the other side and 4 ties, and its control put the Composer default over the old binding 4-1.

**Inference.** `NEGATIVE` (confidence: STRONG). Two independent listening experiments, one with a byte-identical control, both put the profile-bound side last.

## 6. Profile decoration verdict

**Profiles should decorate the Composer's instruments** — stages 12A.

**Observed.** Mechanically plausible — H1 (decoration keeps the Composer's envelope and clock) 3 of 6, H2 (it still changes the sound) 4 of 6, and the frame proof shows only the intended columns changed. Perceptually negative: against the Composer baseline the decoration won 1-3; against replacement it won 1-0 (3 ties).

**Inference.** `NEGATIVE` (confidence: STRONG). The mechanism worked exactly as designed and the listener still preferred what it replaced.

## 7. Volume contour verdict

**The volume contour is an important missing profile capability** — stages 10B.

**Observed.** Transfers frame-for-frame and is audible — heard in 7 of 18 pairs and every single-side answer named the contour side. Profile-level B-vs-C 0-0-8; whole-song 1-2-3. Resolved verdict NEGATIVE.

**Inference.** `NEGATIVE` (confidence: STRONG). The isolated and whole-song results are reported separately and neither favours the contour.

## 8. Spectral/timbral verdict

**Spectral/timbral information is the main missing dimension** — stages 11A, 11B.

**Observed.** Stage 11A found it inconclusive, leaning negative: the renderer already reproduces the dominant audible spectral axis (the generator), and the descriptor named `spectral bandwidth (Hz)` flips sign between datasets (-0.4401 in 7B, +0.6338 in 9D). Stage 11B confirmed the generator dominates the ablation and classified the renders as 5 PARTIALLY_EXPRESSIBLE, 3 UNTESTED with the best single feature audctl (1), envelope (1), generator (3).

**Inference.** `NOT SUPPORTED` (confidence: MODERATE). The axis that mattered was already expressible, and the finer descriptors are unstable predictors.

## 9. Pitch trajectory verdict

**Pitch trajectory is the key missing transferable capability** — stages 13A.

**Observed.** Reconnaissance: 46 non-static trajectories, of which only 14 are musically bounded — 32 carry ±60–96 semitone divider/pair register artifacts. Technical: transfer 8 of 8, measurable movement beyond static pitch 6 of 8, reference improvement 4 of 6. Perceptual: the isolated pairs preferred the trajectory 4-0 and heard it as `modulated` against a `clean tone`; the phrase pairs preferred the static side 1-3; and the profile's own trajectory lost the donor control 1-2.

**Inference.** `ACOUSTICALLY SUPPORTED, PERCEPTUALLY NOT SUPPORTED` (confidence: STRONG). Pitch movement is audible and transferable, but archaeology-derived pitch movement is not useful: it is rejected in musical context and is not distinguishable from a trajectory taken from another profile.


## 10. Context-dependence assessment

**Hypothesis.** Many measured properties of a historical sound are not independent instrument characteristics but properties of the interaction between a timbre, pitch, melody, rhythm, envelope and musical context.

**Classification: `SUPPORTED`** (confidence: STRONG).

| observation | measurement | source |
| :--- | :--- | :--- |
| The same pitch trajectory, applied to the same note, is preferred on its own and rejected inside a phrase. | isolated 4-0 for the trajectory; phrase 1-3 | Stage 13A listening sheet, both levels |
| A trajectory taken from a different profile performs at least as well as the profile's own. | profile-vs-donor 1-2 | Stage 13A donor control |
| Profiles cluster by generator family rather than by anything musical, and the clusters are what the listener hears. | 9D clean vs noisy families disjoint; same_generator vs similarity rho -0.5993 | Stage 9D correlations |
| Percussive behaviour, 'repetition' and 'faster' are properties of the arrangement, not of any field the renderer reads. | 7B 'repetition' 11 comments; the profile's timing series is never read | Stage 7B vocabulary; Stage 9E field census |

**Experimental choice / caveat.** This is not proof. It is the best-supported explanation of five negative transfer results, and it is called SUPPORTED only because a direct, controlled contrast (isolated versus phrase, profile versus donor) points at the context rather than at the profile.

## 11. What worked

**Observed.** Research *infrastructure* that succeeded, kept apart from perceptual transfer:

| item | kind | evidence |
| :--- | :--- | :--- |
| POKEY trace extraction and register-level analysis | infrastructure | SAP corpus -> traces -> segments, reproducible across stages |
| deterministic SoundProfile generation | infrastructure | schema 2.0 with a content fingerprint; byte-identical rebuilds |
| PlayableSoundProfile + registry as a portable artifact | infrastructure | self-sufficient documents that render without the corpus |
| playability audit | infrastructure | 22 PLAYABLE + 39 PLAYABLE_WITH_LIMITATION + 6 MEASUREMENT_ONLY of 67, with per-profile reasons |
| renderer / binding diagnostics | infrastructure | 9E's field census (13 of 232 read) and the frame-column perturbation proof |
| identifying and excluding pitch register artifacts | finding | 32 of 46 non-static trajectories leave a one-octave musical bound |
| the generator family as the audible spectral axis | finding | 7B and 9D agree; the 9D families are disjoint; 11B shows the generator dominates the ablation |
| exact, deterministic transfer of a measured contour and trajectory into the frame stream | finding | 10B frame-for-frame volume; 13A 8 of 8 AUDF-only |
| the listener's ratings are stable enough to compare groups | finding | 9D ICC(1,1) 0.73-0.92 on the same sound presented twice |

**Inference.** The project built a working measurement and publication pipeline. What it did not build is a transfer that a listener prefers — those are different claims and only the first is established.

## 12. What failed

**Observed.** Recorded here so the knowledge is not lost. Every one of these is a negative result that a later stage must not quietly re-run as if it were untested.

| attempt | stage | result |
| :--- | :--- | :--- |
| Direct profile replacement (the binding as it stands) | 9D | the Composer's own instruments won 5-0 on six songs, unanimously on all three questions |
| Evidence-chosen profile rebinding | 10A | NEW won 2 of 12 primary pairs; the control put the Composer default over the old binding 4-1 |
| Volume-contour transfer | 10B | profile-level 0-0-8 and whole-song 1-2-3; resolved verdict NEGATIVE |
| Profile decoration (keep the Composer instrument, take the generator) | 12A | mechanically sound (H1 3/6, H2 4/6) but the listener preferred the Composer baseline, and drew no win against replacement |
| Pitch trajectory as a transferable feature | 13A | transferred 8/8 and audible, preferred 4-0 in isolation, but rejected 1-3 inside a phrase and beaten 1-2 by a donor trajectory from another profile |

## 13. SoundProfile vs sound-design knowledge

**Question.** Does the evidence justify converting Sound Archaeology from a profile-transfer system into a sound-design knowledge system?

**Observed — evidence for.**

* The generator family is the one relationship that replicates across independent ratings and stages: 7B and 9D both put it first, and 9D measured the clean and noisy families as disjoint (same_generator vs similarity rho -0.5993).
* The listener's own vocabulary (lead_tonal, percussive_noisy, clean, loud) is a real, repeated description of that axis.
* The corpus supplies measurable configuration conventions: every VOICE profile is AUDCTL $00, every PAIR profile is $50, and the audit classified 22 PLAYABLE plus 39 PLAYABLE_WITH_LIMITATION of 67.
* Percussion <-> noise and lead/bass <-> tone are cross-checked by the corpus itself: the Composer's own character map already encodes the same pairing.

**Observed — evidence against.**

* 24 of 61 renderable profiles are audio-duplicates, so the corpus is far smaller than its file count suggests.
* The Stage 13A context contrast shows a measured property can reverse between isolated and musical use, which is fatal to a rule that says 'this feature means this'.
* The corpus carries no semantic labels: no field says a sound is a kick, a snare or a bass, and 9E's finding is precisely that the musical meaning was not recorded.
* The one descriptor that looked like a general rule (spectral bandwidth vs usefulness) flips sign between the two datasets (-0.4401 in 7B, +0.6338 in 9D).
* Every perceptual datapoint in the project comes from one listener in a handful of sessions.

**Inference.** NOT YET. The generator-family relationship is real, but the Composer's own character-to-distortion map already encodes it, so a knowledge base built on today's evidence would mostly restate an existing production rule. Everything else the corpus measures is context-bound and unlabelled.

**Classification: `PLAUSIBLE, NOT SUPPORTED`.**

**The gate that would have to be passed before this is revisited:**

* semantic labelling of a sample of segments (what a human says the sound *is*), not a new metric
* evidence that a measured feature predicts a labelled category across independent songs
* a second listener, so a rule is not one person's vocabulary

## 14. Architectural options

**Observed.** Scored qualitatively against the brief's nine criteria; no weighted total is computed, because the weights would be arbitrary.

| option | direction | empirical | perceptual | complexity | overfit risk | musical intent | composer fit | investment | reproducible | future research |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| A | Continue direct SoundProfile transfer | NONE | NONE | MODERATE | STRONG | WEAK | MODERATE | MODERATE | STRONG | WEAK |
| B | Stop direct transfer; use the archaeology as a sound-design knowledge base | WEAK | MODERATE | MODERATE | STRONG | MODERATE | STRONG | MODERATE | MODERATE | MODERATE |
| C | Keep the profiles as a validated reference / research artifact | STRONG | MODERATE | NONE | NONE | STRONG | STRONG | STRONG | STRONG | MODERATE |
| D | Abandon the SoundProfile direction entirely | WEAK | MODERATE | NONE | NONE | STRONG | STRONG | NONE | STRONG | WEAK |

* **A — Continue direct SoundProfile transfer** (`archaeology -> playable profile -> new composition`): five independent listening experiments, including byte-identical and donor controls, put the profile-derived side last in every whole-song comparison.
* **B — Stop direct transfer; use the archaeology as a sound-design knowledge base** (`archaeology -> rules / priors -> Composer`): the one relationship with real support (generator family) is already a rule in the Composer's character map, and the corpus has no semantic labels to build more from.
* **C — Keep the profiles as a validated reference / research artifact** (`archaeology -> SoundProfile library -> analysis, visualisation, research`): the extraction, fingerprinting, audit and rendering pipeline all work and are reproducible; it is the *transfer* that failed, not the archaeology.
* **D — Abandon the SoundProfile direction entirely** (`stop the line`): it discards a working, reproducible measurement pipeline whose only failure is the last mile; A's failure is not a reason to burn the dataset.

## 15. Final recommendation

> **RECOMMENDATION: OPTION C**

Keep the SoundProfile work as a validated reference and research artifact. Stop developing direct profile transfer; do not, on this evidence, convert the corpus into a sound-design rules engine.

**Why the evidence supports it.**

* Direct transfer is not supported in the only terms that matter: five independent listening experiments across four stages put the profile-derived side level with or behind the Composer's own sound, including two controls that could not have favoured the Composer by construction.
* The mechanism is not the problem: contours and trajectories transfer frame-exactly, and the representation loss diagnosed in 9E was repaired deliberately in 10B and 13A. The information is real, measured and faithfully carried — it simply does not survive the move into a new musical context.
* The knowledge-base alternative is attractive but unevidenced: the one replicated relationship (generator family) is already a production rule, and the corpus has no semantic labels, so a rules engine would be built on one listener's vocabulary.
* The archaeology itself is a genuine asset: reproducible extraction, fingerprints, a per-profile playability audit and a working renderer path.

**Why the alternatives are weaker.**

* **A** — no empirical or perceptual support remains; continuing would mean re-running experiments that have already failed four times
* **B** — the evidence is plausible but not sufficient; adopting it now would be choosing the more interesting project over the measured result
* **D** — it discards a working measurement pipeline whose only failure is the last mile

## 16. What happens next

* Freeze the profiles, the schemas, the fingerprints and the audit as a published reference library, with the existing reports as its documentation.
* Publish this synthesis as the closing record of the transfer hypothesis, so the result is not lost.
* If the knowledge direction is ever revisited, go through the explicit gate in `knowledge_base_assessment.gate_to_revisit`: semantic labels and a second listener first, not a rules engine first.

**The research artifact this preserves, and what it still lacks:**

| layer | status | where |
| :--- | :--- | :--- |
| raw POKEY traces | exists | the producer's corpus |
| SoundSegment / SoundFingerprint | exists | producer reports/segments.jsonl and fingerprints.jsonl |
| SoundProfile / PlayableSoundProfile | exists | schema 2.0 / 1.0 with content fingerprints |
| playability audit | exists | producer reports/stage8c/playability_audit.json |
| Composer binding | exists, experimental and off by default | sound_profiles/binding.py, unchanged |

Still missing before a knowledge base could be justified:

* semantic labels on segments (what a sound *is*, not what it measures)
* a second listener, so the vocabulary is not one person's
* evidence that a measured feature predicts a labelled category across independent songs

## 17. Explicit non-goals

* no further transfer mechanism (a new contour, trajectory, modulation or spectral channel) without evidence that was missing before
* no production binding change, no DSL change, no new profile field
* no automatic conversion of the corpus into rules, thresholds or recommendations
* no profile-driven default in the Composer
* no re-running of the completed listening experiments to look for a friendlier reading

Also explicitly out of scope for this stage: implementing any option, changing any schema, composer or renderer file, and running another listening experiment.

### Reproducibility

This document and the seven `reports/stage14/*.json` records are a pure function of the artefacts hashed in §2. There is no timestamp, no sampling and no dependence on directory iteration order; two consecutive runs are byte-identical, and no existing artefact is modified by running or reading this stage.


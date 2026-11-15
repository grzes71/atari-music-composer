# Stage 25 - Matched Control Corpus Design and Validation

Stage 24 ended with `COMMON_SUPPORT_INADEQUATE`: **0 of 12** historical traces lie inside the control corpus's joint feature box, against **41 of 53** control traces under the same leave-one-out test. That is a statement about the corpora, not about the music, and Stage 25 is the response to it.

**The headline.** The pipeline can build the corpus the design needs. A bound sound profile declaring `audctl_mode = $50` produces a trace whose AUDCTL column is `$50` on every frame; all eight POKEY distortion bytes are reachable; and composition length reaches 23040 frames against a historical maximum of 19008. So the two structural gaps Stage 24 measured - the clock and the length - are **closable with documents and a profile, and no production change is required for them**.

**The pilot.** 4 of 4 declared compositions built, and **7 of 7** continuation criteria passed. The ground truth is preserved at three levels: **True**. The declared caliper is enforced: **True**, and it retains everything above the observed distance range: **True**.

**One capability is missing.** A historical player idiom - a zero divider on an audible frame - cannot be expressed through the Music DSL or the IR, so the compiler cannot produce it. That is the only production change the audit identifies, and it is specified rather than implemented.

**Verdict: `PILOT_FEASIBILITY_CONFIRMED`.** The design is specified, the mechanics are proven, and the conditions for an honest comparison are reachable. The corpus is not built, the comparison is not supported yet, and the generator confound survives every corpus design.

Analysis and design only, with a deliberately minimal pilot. No production file is modified, no corpus is committed, no music is released and Stage 26 is not begun. Analysis version `stage25/1`.

Artefacts: `target_population.json`, `feature_specification.json`, `pipeline_capability_audit.json`, `corpus_design.json`, `sample_size_rationale.json`, `overlap_acceptance_criteria.json`, `pilot_results.json`, `ground_truth_validation.json`, `matching_validation.json`, `leakage_assessment.json`, `next_step_recommendation.json`, `verdict.json`, `stage25_manifest.json`.

## 1. Executive Summary

| question | answer |
|---|---|
| Can the pipeline build the required corpus? | **Yes, with one exception.** 4 of 6 probed capabilities are reachable |
| Which configuration was the binding gap? | The 1.79 MHz clock: reachable through a bound profile, no production change |
| What can the pipeline not produce? | A zero divider on an audible frame, the historical players' between-note pulse |
| How large must the corpus be? | **At least 48** compositions across four groups; a design floor of 24 control traces |
| Did the pilot meet its criteria? | **7 of 7** - all |
| Is the ground truth preserved? | **True** at three levels: source, compiled, trace |
| Is the caliper enforced? | **True** - a caliper of 0.01 rejects everything, 1000.0 retains everything |
| Can the result generalize beyond the twelve traces? | **No.** Every historical trace informed the design, so this is a validation on a known set |
| Verdict | **PILOT_FEASIBILITY_CONFIRMED** |
| Auxiliary verdicts | `PRODUCTION_CHANGE_REQUIRED_FOR_ONE_IDIOM`, `PLAYER_CONFOUND_NOT_CLOSABLE_BY_CORPUS_DESIGN`, `VALIDATION_ON_A_KNOWN_SET_ONLY`, `GROUND_TRUTH_PRESERVED_AT_THREE_LEVELS`, `MATCHING_CALIPER_VALIDATED`, `NO_PRODUCTION_DECISION_CHANGED` |
| Reproducibility | **True** - the core was run twice and the digests matched |
| Read-only audit | **True** - 211 production and input artefacts hashed before and after the run, none changed |

**The design is the deliverable, not the corpus.** Stage 25 specifies what a control corpus must contain, proves the pipeline can produce it, and declares the criteria that will decide whether it worked. It does not build it, and it does not run a residual comparison on the pilot.

**Two things no corpus can fix.** The historical traces come from unknown third-party players and the controls from one known compiler and player, so a residual difference is confounded with the generator. And with twelve historical traces against twenty-one matching features there is less than one trace per feature, so no model of the historical side can be estimated however large the control side becomes.

## 2. Audit of Stages 21 to 24

The brief's rule is that the artefacts win over any summary, including this one. Every figure below is read from the artefact that owns it:

| quantity | value | source |
|---|---|---|
| Stage 21 analysis version | n/a | reports/stage21/summary.json |
| Stage 22 analysis version | stage22/1 | reports/stage22/stage22_manifest.json |
| Stage 23 analysis version | stage23/1 | reports/stage23/stage23_manifest.json |
| Stage 23 verdict | HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED | reports/stage23/verdict.json |
| Stage 24 verdict | COMMON_SUPPORT_INADEQUATE | reports/stage24/verdict.json |
| historical traces inside the joint box | 0 | reports/stage24/multivariate_overlap.json |
| control traces inside the joint box, leave-one-out | 41 | reports/stage24/multivariate_overlap.json |
| matching methods reportable / validated | 3 / 0 | reports/stage24/matching_diagnostics.json |
| historical AUDCTL | {'$00': 1, '$50': 11} | reports/stage24/corpus_inventory.json |
| control AUDCTL | {'$00': 31, '$10': 22} | reports/stage24/corpus_inventory.json |

### What each conclusion forces

| conclusion | source | consequence for Stage 25 |
|---|---|---|
| the two corpora share no joint feature range | reports/stage24/multivariate_overlap.json box.historical.inside_on_every_feature | the new corpus must extend the joint range, not only the marginal ranges. A design that matches on one feature at a time repeats Stage 23's mistake |
| the box criterion has discriminating power | reports/stage24/multivariate_overlap.json box.calibration_inside_control | the same calibrated criterion is reused as the acceptance test, so the new corpus is judged by the test that rejected the old one |
| no historical ground truth exists | reports/stage21/evidence_tiers.json and docs/stage21_controlled_validation.md | the control corpus must keep exact source truth, and the historical side stays Tier D. A control corpus cannot create ground truth on the historical side |
| the detector's note-boundary errors are the dominant error class | reports/stage22/residual_taxonomy.json and docs/stage22_detector_error_decomposition.md | the control corpus must let the detector's boundary behaviour be measured, which means spans of controlled length and controlled onset structure |
| the Stage 23 matching never applied its declared caliper | reports/stage24/matching_diagnostics.json stage23_defect | the new design declares its matching rule, tests that the implementation enforces it, and refuses to report a match that fails its own balance criterion |
| the residual difference is measured, stable and unidentified | reports/stage23/verdict.json and reports/stage24/verdict.json | the difference may not be carried forward as a performance-layer effect, and Stage 25 must not treat corpus building as evidence for one |
| the historical traces use AUDCTL $50 and the control corpus does not | reports/stage24/corpus_inventory.json inventory.historical.audctl | the $50 configuration is the first thing the new corpus must cover, and the capability audit must establish whether the pipeline can produce it |

**Stage 23's declared caliper was never applied.** Stage 23 declared CALIPER = 1.0 and never applied it: the neighbour function takes no caliper argument and the constant reached only the artefact. Every historical trace was therefore matched to its nearest control trace however far away that was, which is exactly the extrapolation the caliper was declared to prevent. The balance of the Stage 23 match was never checked either. Both are fixed here, and the effect of the fix is visible: with the caliper applied most of the grid retains nothing.

## 3. Target Population and Inference Scope

**Population.** Atari 8-bit POKEY game-music traces that are observable as a 50 Hz register stream and that lie inside the property region the twelve historical traces occupy.

**Inference scope.** the corpus supports statements about traces in that region. It does not support statements about Atari music in general, about any specific composer, or about any player routine that is not the project's own.

### What the population is not

* all Atari 8-bit music: the historical corpus is twelve traces chosen by availability
* a random sample of composers: three are represented, and one contributes four traces
* a sample of player routines: the routines are unknown and unequally represented
* a statement about 1980s composition practice: one trace is dated 2024

| property | historical | existing control |
|---|---|---|
| traces | 12 | 53 |
| AUDCTL | {'$00': 1, '$50': 11} | {'$00': 31, '$10': 22} |
| frames min | 2048 | 192 |
| frames median | 9833.0000 | 1920.0000 |
| frames max | 19008 | 5952 |

### The structural gaps

| gap | historical | existing control | closable without a production change |
|---|---|---|---|
| POKEY clock configuration | {'$00': 1, '$50': 11} | {'$00': 31, '$10': 22} | True |
| trace length | [2048, 19008] | [192, 5952] | True |

**The population is defined by observable trace properties, not by era or genre.** Era and genre are not recoverable from a register stream, and they are not what the comparison measures. Defining the population any other way would make the claim untestable.

## 4. Ground Truth Definition

Each control example carries three separate representations, and they are never merged:

| level | what it is | identity | control | historical | limitation |
|---|---|---|---|---|---|
| source ground truth | the authored composition document: notes, durations, rests, channel assignment, instrument roles, envelope parameters, distortion per instrument, and the AUDCTL configuration the composition asks for | the document's SHA-256, hashed as text | yes, exactly | no - a SAP is a player plus data | it is the *intent*, not the performance. A note the document declares may be realized differently by the compiler, and a player may add behaviour the document never asked for |
| compiled and player ground truth | the exact frame stream the compiler produced, the resolved AUDCTL byte, the frames_per_tick the tempo mapped to, and the identity of the compiler and player that produced it | the frame payload's SHA-256 plus the resolved configuration | yes, exactly | partially - the trace is observable, the compiler is not | it is one realization. The same document compiled by a different player would give a different stream, and that difference is invisible here |
| exact trace ground truth | the register stream wrapped as a trace, with a deterministic link back to level A and level B | the trace file's SHA-256, and the same payload hashed by the frame stream | yes, exactly | yes, but with no link to a level A or B | a trace is not a composition. Every feature in the matching set is a property of the trace, and none of them is a property of the music the trace came from |

**The five things kept apart.** The source truth is the document; the compiled truth is what the compiler produced; the player's behaviour is what the 6502 routine does with it; the trace is what was observed; and the detector's interpretation is a reading of the trace. Stage 25 never treats the source composition and the exact trace as the same representation, because they are not: a rest in the document is a silent register in the trace, and a note in the document is a span the detector may or may not find.

**What the historical side has.** Only the third level, with no link to a source or a compiled artefact. That asymmetry is permanent: a control corpus cannot create ground truth on the historical side, and no corpus design changes it.

## 5. Pipeline Capability Audit

Every finding is measured by probing the real pipeline, not read from documentation. A capability is claimed because a probe produced it; a gap is claimed because a probe failed with a named exception.

| capability | reachable | conclusion |
|---|---|---|
| distortion modes | 8 of 8 | all eight POKEY distortion bytes are reachable through dist= |
| AUDCTL configurations | 3 of 3 | every probed configuration is reachable and appears in the trace's AUDCTL column on every frame. $00 and $10 are produced by the composer alone; $50 n |
| composition length | measured | length is rows x repetitions x frames_per_tick; 23040 frames is reachable, against a historical maximum of 19008 |
| sound profile bank | measured | the repository bank holds 18 renderable $50 profiles, so the historical clock is a binding choice rather than a code change |
| AUDF = 0 while audible (the between-note pulse idiom) | False | the idiom cannot be reproduced, so any corpus built with the current compiler is systematically free of it. Stage 23 measured it in 38.1% of historica |
| mid-song AUDCTL change | False | not needed: no historical trace has one either. Stage 24 measured audctl_change_rate at exactly zero in all 65 traces and excluded it as degenerate |

**BPM to frames_per_tick.** BPM <= 80 gives 6, BPM <= 110 gives 5, BPM <= 145 gives 4, BPM <= 250 gives 3. A pattern is bounded at 128 steps, so length is controlled by repeating the sequence rather than by one long pattern.

**Production changes required: ['AUDF = 0 while audible (the between-note pulse idiom)'].**

### The one capability that is missing

**AUDF = 0 while audible (the between-note pulse idiom).** Reachable: **False**.

*Mechanism.* _render_note_to_frames writes AUDF and AUDC together from a note, a note's divider is never zero (the highest representable pitch still yields a non-zero divider), and a rest writes AUDC = 0 and leaves AUDF at the array's initial value of zero. So in a compiled trace AUDF = 0 and 'silent' are the same condition.

*Consequence.* The idiom cannot be reproduced, so any corpus built with the current compiler is systematically free of it. Stage 23 measured it in 38.1% of historical spans and 0.8% of control spans, and Stage 24 classified it as a corpus-composition difference rather than as the cause of the residual.

*The change would be.* A per-note or per-step way to emit a zero divider without silencing the channel. That is a change to the Music IR and to the compiler, so Stage 25 stops at the specification and does not implement it.

*Does it change the subject of the study?* Yes, if the question is whether this idiom carries residual. No, if the question is whether the corpora differ on the matching features, because the idiom is a mediator rather than a matching feature and the primary estimand is convention-free.

| probe measurement | value |
|---|---|
| zero-divider-and-audible frames in the probe | 0 |
| silent register frames in the probe | 208 |

**The pipeline is not modified to close it.** The brief is explicit: document the gap, assess whether a conforming experimental method exists, and leave the decision to the project. Stage 25 stops at the specification.

## 6. The Control Groups

| group | role | size target | necessary | closes | cost |
|---|---|---|---|---|---|
| A_baseline | continuity | at least 12 | True | nothing alone; it stops the new corpus from being a different kind of object | low - the existing pipeline already produces this configuration |
| B_feature_coverage | close the measured structural gaps | at least 24 | True | the joint-support gap, if it is closable at all. This is the group the design exists for | medium - each composition is authored against a declared feature target and validated against the acceptance criteria before it counts |
| C_mechanism_controls | let the detector's behaviour be measured | at least 8 | True | the Stage 22 finding that note-boundary errors dominate. It does not close a support gap; it makes the detector's error attributable inside the new corpus | low - short compositions with one variable each |
| D_pipeline_controls | separate composition from generator | at least 4 | False | partially the generator confound, and only partially: see the leakage section | medium - each pair shares a source document and differs only in the binding, so the difference is a clean contrast |

**Total minimum size: 48** compositions across 4 groups.

**Design principle.** Coverage is targeted on the joint feature vector, not on marginal ranges. Stage 24 showed that univariate overlap held for 21 of 21 features while the joint box was empty, so a design that matched one feature at a time would repeat Stage 23's mistake.

### What the design does not do

* it does not reproduce the zero-divider audible pulse, which the pipeline cannot express
* it does not vary the player, so the generator confound survives
* it does not create ground truth on the historical side

### Which features can be controlled, and how

| class | features |
|---|---|
| controlled_directly | audc_distortion_change_rate, audf_change_rate, audf_diversity_per_1000_frames, clock_179mhz, coupled_16bit, frames, max_simultaneous, mean_simultaneous, noise_active_share, silence_share |
| controlled_indirectly | audc_change_rate, audc_volume_change_rate, audible_share, channel_balance, distinct_audc_values, low_volume_share, mean_audc_run_length, register_change_cooccurrence, register_change_rate |
| observed_only | detector_generator_precision, detector_generator_recall |
| not_controllable | audctl_change_rate, stable_run_median |

**10 features are directly controllable, 9 indirectly, 2 are only observable, and 2 cannot be controlled at all.** The last group is not a failure: those features are degenerate in both corpora, so Stage 24 excluded them from the matching and nothing needs to control them.

### Feature by feature

| feature | class | mechanism | granularity | caveat |
|---|---|---|---|---|
| frames | controlled_directly | rows per pattern (max 128) x the number of sequence repetitions x frames_per_tick, where frames_per_tick follows BPM: <=80 gives 6, <=110 gives 5, <=145 gives 4, else 3 | one frame per step at the slowest tempo | BPM also changes the musical content, so length and tempo are not independent |
| clock_179mhz | controlled_directly | bind a sound profile whose hardware.audctl_mode declares the 0x40 bit; resolve_audctl_mode OR-s it into the frame stream's AUDCTL | the whole trace, since AUDCTL is written once for every frame | the profile must be coherent: a conflicting dist= in the document is refused |
| coupled_16bit | controlled_directly | the DSL's BASS16 directive, or a profile declaring the 0x10 join bit | the whole trace | the join consumes two channels, so it also sets the maximum simultaneity |
| audf_change_rate | controlled_directly | note density and the width of the pitch range; short notes on many pitches | one note | the historical players also pulse AUDF to zero between notes, which raises this feature in a way the compiler cannot reproduce; the two contributions are not separable from the feature value alone |
| audc_change_rate | controlled_indirectly | the per-instrument envelope (att/dec/sus/rel) plus note length and the number of simultaneous voices; the compiler emits one AUDC write per frame from the envelope | one frame, but only through the envelope's shape | an envelope cannot hold a constant level for an arbitrary number of frames and then step: the shape is the player's, not the document's |
| audc_volume_change_rate | controlled_indirectly | the same envelope mechanism, restricted to the volume nibble | one frame via the envelope | the release tail always decays, so a trace cannot end on a held full level |
| audc_distortion_change_rate | controlled_directly | the DSL's dist= parameter on an instrument, or a per-note distortion override; all eight POKEY distortion bytes are accepted | one note | the player sets distortion per span, so a change can only occur at a span onset |
| noise_active_share | controlled_directly | use a noise distortion byte (0x80) on a voice for the desired fraction of notes | one note | the waveform family is read from the distortion nibble, so this is exact |
| silence_share | controlled_directly | the density of rest steps in the pattern | one step | a rest zeroes AUDC and leaves AUDF at the array's initial value, so silence is absolute and a silent frame can never carry a divider |
| low_volume_share | controlled_indirectly | the number of simultaneously active voices per step, via the channel tracks | one step | it is a consequence of voice count, not an independent control |
| register_change_rate | controlled_indirectly | note density and the number of channels carrying notes: a note onset writes AUDF and AUDC, so more onsets mean more register writes per frame | one note, but only jointly across AUDF and AUDC | it counts any register write, so it cannot be moved independently of audf_change_rate and audc_change_rate; a composition cannot raise this feature without raising those |
| register_change_cooccurrence | controlled_indirectly | how many channels change at the same step; aligning note onsets raises it, offsetting them lowers it | one step | it is a property of the alignment, not of any single register |
| mean_simultaneous | controlled_directly | how many CHn tracks carry notes in a pattern, and CHANNELS 1..4 | one step | a joined pair occupies two channels and counts as one voice, so the join lowers it |
| max_simultaneous | controlled_directly | the largest number of CHn tracks sounding at any one step, so it is set by the busiest step in the pattern rather than by the average | one step | a joined pair occupies two channels and counts as one voice, so the join lowers it |
| channel_balance | controlled_indirectly | how evenly the notes are distributed across the active channels | one trace | undefined with no audible voice, and reported as undefined rather than as zero |
| audf_diversity_per_1000_frames | controlled_directly | the number of distinct pitches used, normalised by length | one note | the 1.79 MHz clock widens the representable divider range, so the same melody yields a different value under $50 than under $00. Clock and diversity are therefore not independent controls |
| distinct_audc_values | controlled_indirectly | the number of distinct envelope levels reached across the trace | one frame via the envelope | bounded by the envelope shapes available, so it saturates |
| mean_audc_run_length | controlled_indirectly | note length against the envelope's change rate | one note | a long rest contributes a long silent run and dominates the mean |
| audible_share | controlled_indirectly | the complement of rest density | one step | the compiler's audibility is volume > 0, matching the detector by construction |
| detector_generator_recall | observed_only | not controlled: a property of the detector's segmentation interacting with where distortion changes are placed | n/a | measurable identically on both corpora because the truth is the trace itself, but it cannot be set directly |
| detector_generator_precision | observed_only | as above | n/a | an onset need not be a distortion change, so a low value is expected |
| stable_run_median | not_controllable | not controllable and not needed: Stage 24 measured it at exactly 1.0 in all 65 traces of both corpora, so it is degenerate and carries no information | n/a | with four voices' worth of registers, at least one column changes almost every frame |
| audctl_change_rate | not_controllable | not controllable and not needed: AUDCTL is written once for the whole frame stream, so it is constant in every trace of both corpora. Stage 24 measured it at exactly zero and excluded it as degenerate | n/a | a mid-song AUDCTL change is not expressible, and no historical trace has one either |

**A trace feature is not automatically a composition feature.** The brief warns about this and the table is the response: only the rows marked directly controllable may be targeted by a composition. The rest follow from the compiler, the player or the envelope, and a design that assumed otherwise would be unable to hit its own targets.

## 7. Sample Size and Diversity

### What can be counted

| quantity | value |
|---|---|
| existing_control_traces | 53 |
| historical_authors | 3 |
| historical_sources | 11 |
| historical_traces | 12 |
| matching_features | 21 |

### The design floor

**Rule.** the corpus must retain at least 4 historical traces from 3 sources after a caliper is applied, and supply a distinct partner for each. A 1:1 match therefore needs at least as many control traces as the number of historical traces expected to match.

**Minimum control traces: 24.** 12 historical traces against a candidate corpus of 24 leaves room for a match at roughly 1:2. The existing 53 control traces failed with a corpus of 53, so size alone was never the problem - the configuration was.

### The feature-dimension argument

| quantity | value |
|---|---|
| matching features | 21 |
| historical traces | 12 |
| traces per feature | 0.5714 |

21 matching features against 12 historical traces is fewer than one trace per feature. No distance or propensity model can be estimated from that, which is why Stage 24's propensity score had 16 of 22 coefficients change sign under resampling. Adding control traces does not fix this: the historical side is the binding constraint and it cannot be enlarged without more SAPs.

### What cannot be estimated, and why

| quantity | why it cannot be estimated |
|---|---|
| the between-song variance of the residual in the new corpus | no pilot of the new corpus exists yet |
| the interval width to expect | it depends on the between-source variance, and the historical side has 11 sources. Widening the control side narrows the control term only |
| the power to detect a given effect | the comparison is confounded with the generator, so a power calculation would be a calculation about a quantity that is not identified |

**No power calculation is offered, because none would mean anything.** The comparison is confounded with the generator, so a power figure would describe a quantity that is not identified. The brief asks not to pretend the right sample size is known, and it is not known.

### The staged pilot

| stage | size | purpose | gate |
|---|---|---|---|
| stage_1 | 4 | prove the mechanics: the clock, the length, the truth levels, determinism | every pilot composition compiles; the requested AUDCTL mode appears in the trace; the declared length is produced; the historical length region is reachable; al |
| stage_2 | 12 | measure whether the joint-support gap actually narrows | the box criterion's calibration still passes on the candidate's own members; the joint-box coverage for the historical traces rises above zero; the nearest-neig |
| stage_3 | 48 | the corpus the acceptance criteria are actually evaluated against | every acceptance criterion in section 9 of the report |

The design floor is 24 control traces. The staged pilot is what decides whether that number is achievable, and the brief's instruction is followed: the pilot is not enlarged until the criteria say the earlier stage passed.

## 8. Generation and Validation Procedure

The procedure is deterministic end to end:

```text
Control specification   (a declared dict: audctl, bpm, rows, repeats, distortions)
        |
        v
Source composition      (DSL text generated from the spec, hashed as text)
        |
        v
Compiler / player       (compile_ir_to_pokey_frames, plus a profile binding if $50)
        |
        v
Exact trace             (stage21.build_trace over the compiled payload)
        |
        v
Feature extraction      (stage24.trace_measures)
        |
        v
Overlap diagnostics     (stage24's calibrated criteria)
        |
        v
Ground-truth validation (three levels, hash sensitivity, configuration agreement)
```

### What is recorded for every composition

| field | where it comes from |
|---|---|
| source hash | SHA-256 of the DSL text |
| compiled artefact hash | SHA-256 of the frame payload the compiler produced |
| player and compiler identity | the module path and the player source path |
| configuration | the resolved AUDCTL, frames_per_tick and uses_16bit_bass |
| trace hash | SHA-256 of the same payload, through the trace wrapper |
| feature vector | the 21 matching features plus the mediators |
| generation parameters | the spec dict that produced the document |
| ground-truth status | which of the three levels are present |
| errors and warnings | recorded rather than dropped; a failed spec is a finding |
| determinism | a repeated build compared field by field |

### The round trip

| composition | checks |
|---|---|
| pilot_a_baseline | {"audctl_matches_request": true, "compiled_equals_trace": true, "levels_present": true, "payload_hash_stable": true, "source_hash_stable": true} |
| pilot_b_clock50 | {"audctl_matches_request": true, "compiled_equals_trace": true, "levels_present": true, "payload_hash_stable": true, "source_hash_stable": true} |
| pilot_c_16bit64 | {"audctl_matches_request": true, "compiled_equals_trace": true, "levels_present": true, "payload_hash_stable": true, "source_hash_stable": true} |
| pilot_d_dense_pitch | {"audctl_matches_request": true, "compiled_equals_trace": true, "levels_present": true, "payload_hash_stable": true, "source_hash_stable": true} |

**Hash sensitivity: True.** A digest is not proof of correctness, so the check also mutates the document and confirms the hash changes. Without that, a constant hash would pass every equality test.

**Four compositions are a feasibility test. They are not a control corpus, they are not used to evaluate the acceptance criteria, and no residual comparison is run on them.

## 9. Overlap Acceptance Criteria

Declared before any corpus is built. The brief's warning is followed literally: overlap is not sufficient because a nearest control example could be assigned to every historical trace. These are the tests Stage 24 calibrated, reused unchanged.

| criterion | threshold | reused from | note |
|---|---|---|---|
| calibration | at least 50% of candidate traces inside under leave-one-out | reports/stage24/multivariate_overlap.json box.calibration_inside_control | without this the box test could be refused for having no power, and a corpus would be rejected for the wrong reason |
| distance | at most 0 historical traces beyond the candidate leave-one-out maximum | reports/stage24/multivariate_overlap.json nearest_neighbour | three thresholds are reported (max, p95, p90) so the conclusion does not rest on one. The max is the permissive one and is the acceptance bar |
| leakage | at least one historical source reserved, or the result reported as a validation on a known set rather than as a generalization | new in Stage 25 | see the leakage assessment below |
| matching | at least 4 traces from 3 sources retained, with every |SMD| <= 0.25 | reports/stage24/matching_diagnostics.json | Stage 23 declared a caliper and never applied it. The acceptance test therefore includes a positive control: a caliper of 0.01 must reject every trace, proving the implementation enforces the constraint rather than ignoring it |
| multivariate_box | at least 100% of historical traces inside | reports/stage24/multivariate_overlap.json box | this is the criterion that failed. Stage 24 measured 0 of 12 historical inside and 41 of 53 control inside, so the test discriminates |
| propensity | at least 80% retained in [0.1, 0.9] | reports/stage24/multivariate_overlap.json propensity | the score is a diagnostic, not proof. Stage 24's had 16 of 22 coefficients change sign under resampling, so the candidate must also report its stability, and a score that separates the corpora is a statement about how unlike they are |
| univariate | every matching feature has a non-empty common range | reports/stage24/univariate_overlap.json | Stage 24 already passed this with the length artefact corrected, so it is a necessary condition rather than the binding one |

**All six criteria are evaluated together. A corpus that satisfies five and fails one is refused, because the comparison is only as good as its weakest support dimension.

### Matching validation

| control | caliper | historical kept | historical rejected | expectation | met |
|---|---|---|---|---|---|
| positive | 0.01 | 0 | 12 | retain nothing | True |
| negative | 1000.0 | 12 | 0 | retain everything | True |

**Smallest observed historical-to-control distance: 4.0930.** A caliper below it must retain nothing; if it retained anything the matcher would be ignoring its own constraint, which is exactly the defect Stage 24 found in Stage 23.

**Balance criterion: |SMD| <= 0.25**, reused from Stage 24 rather than re-chosen.

**The positive and negative controls together show the caliper is a real constraint. A matcher that passes both can be trusted to reject an unmatched trace.

## 10. Leakage and Over-Fitting Protection

**Design set.** 12 traces from 11 sources, all of them used to choose the target region. Every available historical trace informed the design; there is no unused one.

### Validation options

| option | available | proves | does not prove | cost or recommendation |
|---|---|---|---|---|
| leave-one-source-out over the historical corpus | True | that a matched result is not driven by a single historical source | that the corpus generalizes to historical traces outside the twelve | report it, but read it as a stability check on the twelve rather than as an estimate of performance on unseen historical material |
| reserve one historical source entirely | True | that a matched result survives on material that did not inform the design | that the held-out source is exchangeable with the others, when four of twelve traces share one author's player routine | reserve the source with the most traces only if the design can tolerate losing them. Otherwise report leave-one-source-out and label the result a validation on a known set |
| acquire new historical SAPs after the corpus is built | True | that a matched result transfers to historical material the design never saw | that the new material is representative: an unrepresentative sample generalizes to itself and to nothing else | the only option that turns the claim from interpolation into generalization, and the strongest reason to build the corpus first and validate later |

### Over-fitting risks and their mitigations

| risk | mitigation |
|---|---|
| designing the corpus against the twelve traces and reporting the fit as general | the report labels the result a validation on a known set, and the verdict vocabulary has no word for generalizing from it |
| choosing features that make the corpora look alike | the feature set is Stage 24's, unchanged, and the acceptance criteria are the tests Stage 24 calibrated. Neither is re-chosen here |
| widening a caliper until a match appears | the caliper grid is declared before the corpus is built, and the acceptance criteria require the balance threshold to be met at every reported setting |
| treating the propensity score's separation as proof of anything | the score is reported with its resampling stability and is never the sole basis for a support verdict |

**Conclusion.** With twelve traces from eleven sources, all of them used for design, a corpus matched to them demonstrates interpolation. The honest claim is that the comparison becomes supported *for these traces*, and generalization needs historical material the project does not have yet.

## 11. Pilot Results

**4 of 4 declared compositions built; 7 of 7 criteria passed.**

| criterion | measurement | passed | observed |
|---|---|---|---|
| every pilot composition compiles | the build raises no exception for any spec | True | {"built": 4, "failed": 0} |
| the requested AUDCTL mode appears in the trace | the trace's AUDCTL column equals the requested mode on every frame | True | {"pilot_a_baseline": ["$00"], "pilot_b_clock50": ["$50"], "pilot_c_16bit64": ["$10"], "pilot_d_dense_pitch": ["$50"]} |
| the declared length is produced | frames equals rows x repeats x frames_per_tick | True | {"pilot_a_baseline": {"expected": 256, "frames": 256}, "pilot_b_clock50": {"expected": 2304, "frames": 2304}, "pilot_c_16bit64": {"expected": 256, "frames": 256}, "pilot_d_dense_pi |
| the historical length region is reachable | at least one pilot trace reaches the historical minimum of 2048 frames | True | {"historical_min": 2048, "max_pilot_frames": 2304} |
| all three ground-truth levels are captured and consistent | the source hash, the compiled hash and the trace hash are all present, and the compiled hash equals the trace hash because they hash the same payload | True | {"pilot_a_baseline": {"compiled": "24501c529e49", "source": "d529da2998af", "trace": "24501c529e49"}, "pilot_b_clock50": {"compiled": "011ef52c9707", "source": "84dbca7fbd88", "tra |
| the build is deterministic | building the same spec twice gives a byte-identical source hash and payload | True | {"checked": true, "frames_match": true, "payload_hash_match": true, "source_hash_match": true, "spec": "pilot_a_baseline"} |
| every matching feature is defined on every pilot trace | no matching feature is undefined for any pilot trace | True | {"pilot_a_baseline": [], "pilot_b_clock50": [], "pilot_c_16bit64": [], "pilot_d_dense_pitch": []} |

### The pilot traces

| id | group | frames | expected | frames/tick | AUDCTL column | 16-bit | spans |
|---|---|---|---|---|---|---|---|
| pilot_a_baseline | A_baseline | 256 | 256 | 4 | ['$00'] | False | 12 |
| pilot_b_clock50 | B_feature_coverage | 2304 | 2304 | 6 | ['$50'] | True | 30 |
| pilot_c_16bit64 | B_feature_coverage | 256 | 256 | 4 | ['$10'] | True | 22 |
| pilot_d_dense_pitch | C_mechanism_controls | 1536 | 1536 | 6 | ['$50'] | True | 20 |

### Their feature vectors

| feature | pilot_a_baseline | pilot_b_clock50 | pilot_c_16bit64 | pilot_d_dense_pitch |
|---|---|---|---|---|
| frames | 256.0000 | 2304.0000 | 256.0000 | 1536.0000 |
| audible_share | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| silence_share | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| low_volume_share | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| register_change_rate | 0.8203 | 0.1936 | 0.8711 | 0.1921 |
| audf_change_rate | 0.1367 | 0.0373 | 0.1875 | 0.0365 |
| audc_change_rate | 0.6836 | 0.1562 | 0.6836 | 0.1556 |
| audc_volume_change_rate | 0.6836 | 0.1562 | 0.6836 | 0.1556 |
| audc_distortion_change_rate | 0.0430 | 0.0074 | 0.0430 | 0.0072 |
| noise_active_share | 0.3750 | 1.0000 | 0.3750 | 1.0000 |
| mean_simultaneous | 2.3750 | 2.3750 | 2.3750 | 2.3750 |
| max_simultaneous | 3.0000 | 3.0000 | 3.0000 | 3.0000 |
| coupled_16bit | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| clock_179mhz | 0.0000 | 1.0000 | 0.0000 | 1.0000 |
| audf_diversity_per_1000_frames | 50.7812 | 10.4167 | 70.3125 | 15.6250 |
| distinct_audc_values | 13.0000 | 16.0000 | 13.0000 | 16.0000 |
| mean_audc_run_length | 5.7207 | 19.0413 | 4.3146 | 19.0413 |
| channel_balance | 1.6842 | 0.7895 | 0.7895 | 0.7895 |
| register_change_cooccurrence | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| detector_generator_recall | 0.6364 | 1.0000 | 1.0000 | 1.0000 |
| detector_generator_precision | 0.8750 | 0.9444 | 0.7857 | 0.9167 |

**The pilot is not evaluated against the acceptance criteria.** Those criteria need a corpus, and four compositions are not one. What the pilot establishes is that the mechanics work: the configuration is reachable, the length is reachable, the truth levels are captured and the build is deterministic.

**No residual comparison is run on the pilot.** Four compositions are a feasibility test. They are not a control corpus, they are not used to evaluate the acceptance criteria, and no residual comparison is run on them.

## 12. Limitations and Costs

### Limitations that no corpus design removes

| limitation | why it survives |
|---|---|
| the generator confound | the historical traces come from unknown third-party players and the controls from one known compiler and player. Only a design that varies the player while holding the music fixed addresses it |
| less than one historical trace per feature | 21 matching features against 12 historical traces. The historical side is the binding constraint and cannot be enlarged without more SAPs |
| no historical ground truth | every historical SAP is Tier D. A control corpus cannot create ground truth on the historical side |
| the zero-divider pulse cannot be reproduced | the Music DSL and the IR have no way to express a zero divider on an audible frame |
| validation is on a known set | all twelve historical traces informed the design, so the first result is an interpolation |

### Costs

| item | cost | why |
|---|---|---|
| authoring the baseline group | low | the existing pipeline already produces the configuration |
| authoring the coverage group | medium | each composition is validated against its feature target before it counts |
| authoring the mechanism controls | low | short compositions with one variable each |
| the pipeline controls | medium | each pair shares a source document and differs only in the binding |
| running the analysis | low | Stage 24's analysis already exists and runs in about a minute |
| validating on new historical material | unknown | depends on what SAPs can be found, which is outside the project's control |

### What the production change would cost

Closing the zero-divider gap means adding a way to emit a zero divider without silencing a channel. That touches the Music IR and the frame compiler, and it would need the player to be checked too, because the idiom is a player behaviour in the historical corpus. Stage 25 specifies it and stops: the brief says not to implement production changes here, and the design does not need this capability for the support question.

## 13. Methodological Corrections

Every problem found while designing this stage, and what was done about it.

**1. The support criteria are the ones that rejected the old corpus.** It would be easy to write acceptance criteria that the existing 53 control compositions already satisfy and then declare the design validated. The criteria here are Stage 24's, unchanged, including the calibration check that makes the box test meaningful. The new corpus will be judged by the test that rejected the old one.

**2. The caliper is tested, not declared.** Stage 24 found that Stage 23 declared `CALIPER = 1.0` and never applied it. So the acceptance criteria include a positive control: a caliper of 0.01 must reject every historical trace, and a caliper of 1000.0 must retain every one. Both hold, which is what makes the enforcement claim checkable.

**3. Capabilities are probed rather than assumed.** The audit builds documents, runs them through the production compiler and inspects the frame stream. A capability is claimed because a probe produced it, and a gap because a probe failed with a named exception. The first version of the distortion probe was itself wrong - it shifted the nibble twice and tested only four of the eight modes - which is exactly why the probe reports the observed AUDC bytes rather than a boolean.

**4. A degenerate feature is not a control target.** `stable_run_median` and `audctl_change_rate` are classified `not_controllable`, and the report says why: they are identical constants in both corpora, so Stage 24 excluded them and nothing needs to control them. Listing them as gaps would have made the design look harder than it is.

**5. The pilot is not a corpus and is not scored as one.** Four compositions cannot evaluate criteria that need a matched comparison. The pilot is scored only against its own feasibility criteria, and the report says so twice so the distinction cannot be lost.

**6. The inference scope is limited in the design, not in a footnote.** Every historical trace informed the design, so the corpus supports interpolation and not generalization. That is stated in the population section, in the leakage section, in the verdict and in the recommendation, because a reader who misses it once should meet it again.

## 14. Verdict

| subject | verdict | deciding measurement |
|---|---|---|
| main | PILOT_FEASIBILITY_CONFIRMED | {"caliper_enforced": true, "capabilities_reachable": 4, "capabilities_total": 6, "design_floor_control_traces": 24, "design_groups_buildable": 4, "ground_truth_consistent": true, "pilot_criteria_passed": 7, "pilot_criteria_total": 7, "production_changes_required": ["AUDF = 0 while audible (the between-note pulse idiom)"]} |
| PRODUCTION_CHANGE_REQUIRED_FOR_ONE_IDIOM | PRODUCTION_CHANGE_REQUIRED_FOR_ONE_IDIOM | One historical player idiom - a zero divider on an audible frame - is not expressible through the Music DSL or the IR, so the compiler cannot produce it. |
| PLAYER_CONFOUND_NOT_CLOSABLE_BY_CORPUS_DESIGN | PLAYER_CONFOUND_NOT_CLOSABLE_BY_CORPUS_DESIGN | The historical traces come from unknown third-party players and the controls from one known compiler and player. No number of new control compositions changes that, and only a design that varies the player while holding the music fixed addresses it. |
| VALIDATION_ON_A_KNOWN_SET_ONLY | VALIDATION_ON_A_KNOWN_SET_ONLY | All twelve historical traces informed the design, so a corpus matched to them demonstrates interpolation rather than generalization. |
| GROUND_TRUTH_PRESERVED_AT_THREE_LEVELS | GROUND_TRUTH_PRESERVED_AT_THREE_LEVELS | Every pilot composition carries a source hash, a compiled payload hash and a trace hash, and the hash responds to a document change. |
| MATCHING_CALIPER_VALIDATED | MATCHING_CALIPER_VALIDATED | The caliper rejects everything below the observed distance range and retains everything above it, so the implementation enforces the constraint Stage 23 declared and never applied. |
| NO_PRODUCTION_DECISION_CHANGED | NO_PRODUCTION_DECISION_CHANGED | Stage 25 designs and pilots. It modifies no detector, compiler, player, exporter or schema, commits no corpus and generates no released music. |

### What `PILOT_FEASIBILITY_CONFIRMED` means

The pipeline can build the corpus the design calls for, the mechanics are proven end to end, and the ground truth is preserved at three levels. What the corpus cannot fix is named rather than designed around.

**What it does not mean.** It does not mean the corpus is built, that the comparison is now supported, or that any residual difference has been explained. It means the conditions for an honest comparison are specified and reachable.

### The STOP conditions

The brief's STOP conditions are applied as written. The pipeline can produce every configuration the design needs except one idiom, so the gap is named rather than worked around. The pilot met its criteria and was **not** enlarged. The inference scope is limited to the known set. No production change is implemented, and Stage 26 is not started.

## 15. The Concrete Next Step

**Build the corpus in three stages, evaluating the declared acceptance criteria at each stage and stopping rather than enlarging if a stage fails.

| stage | size | gate | action |
|---|---|---|---|
| 1 | 4 | the pilot criteria in pilot_results.json | author the four compositions as tracked documents and commit them |
| 2 | 12 | the box criterion's calibration still passes on the candidate's own members, and the historical joint-box coverage rises above zero | author coverage compositions targeting the $50 clock and the historical length region, one feature target per composition, validated before it counts |
| 3 | 48 | every acceptance criterion in overlap_acceptance_criteria.json | complete the corpus, then re-run the Stage 24 analysis against it. Only if every criterion passes may a residual comparison be attempted |

### What must not be done

* do not treat the pilot as a corpus
* do not enlarge the pilot because it failed; diagnose the failure first
* do not run a residual comparison on a corpus that fails an acceptance criterion
* do not change the feature set or the criteria to make a corpus pass
* do not read a matched difference as a performance-layer effect while the generator confound stands

### Production work identified and not done

| field | value |
|---|---|
| change | a way to emit a zero divider on an audible frame, so the between-note pulse idiom can be reproduced |
| does_the_corpus_need_it | not for the support question, which is about the matching features. It is needed only if the question becomes whether that idiom carries residual, and Stage 24 classified the idiom as a mediator rather than as a cause |
| requires | a change to the Music IR and to ir.compile_ir_to_pokey_frames |
| status | specified and not implemented; the decision belongs to the project |

### The generalization requirement

| field | value |
|---|---|
| status | outside the project's control; the corpus should be built first and validated against new material when it exists |
| what_is_needed | historical SAPs that were not used to design the corpus |
| why | with twelve traces from eleven sources, all of them used for design, a corpus matched to them demonstrates interpolation. The honest claim is that the comparison becomes supported *for these traces*, and generalization needs historical material the project does not have yet |

### The decision the project must make

* author the corpus and accept that the first result is an interpolation
* or leave the historical comparison closed, as Stage 24 concluded

**It does not author the corpus, does not modify production, does not start Stage 26 and does not claim the comparison is now supported.

## The Ten Closing Questions

**1. Exactly which region of historical traces do we want to represent?**

**The observable property region the twelve historical traces occupy**, defined by trace properties rather than by era or genre. The corpus supports statements about traces in that region. It does not support statements about Atari music in general, about any specific composer, or about any player routine that is not the project's own.

| property | historical region | reachable by the pipeline |
|---|---|---|
| AUDCTL | {'$00': 1, '$50': 11} | yes, through a bound profile |
| frames | [2048, 19008] | yes, up to 23040 |
| matching features | 21 | design targets each one |

**2. Which features are controllable, and which only observable?**

**10 directly controllable, 9 indirectly, 2 observable only, and 2 not controllable at all.** Section 6 gives the mechanism for each. The last group is degenerate in both corpora, so nothing needs it.

**3. Can the current pipeline build the corpus we need?**

**Yes, with one exception.** 4 of 6 probed capabilities are reachable. The exception is the zero-divider-on-an-audible-frame idiom: **False**. The idiom cannot be reproduced, so any corpus built with the current compiler is systematically free of it. Stage 23 measured it in 38.1% of historical spans and 0.8% of control spans, and Stage 24 classified it as a corpus-composition difference rather than as the cause of the residual.

**4. What size and diversity are justified?**

**At least 48 compositions** across four groups, with a design floor of 24 control traces against the 12 historical ones. 21 matching features against 12 historical traces is fewer than one trace per feature. No distance or propensity model can be estimated from that, which is why Stage 24's propensity score had 16 of 22 coefficients change sign under resampling. Adding control traces does not fix this: the historical side is the binding constraint and it cannot be enlarged without more SAPs.

**5. How will the multivariate overlap be validated?**

**By the calibrated criteria Stage 24 used to reject the old corpus**, unchanged: the joint box test with its control leave-one-out calibration, three distance thresholds, the propensity overlap region with its resampling stability, and a matching caliper whose enforcement is proven by a positive and a negative control. A corpus is refused if any one of them fails.

**6. How will leakage and over-fitting to the 12 SAPs be avoided?**

**It cannot be avoided, so it is declared.** With twelve traces from eleven sources, all of them used for design, a corpus matched to them demonstrates interpolation. The honest claim is that the comparison becomes supported *for these traces*, and generalization needs historical material the project does not have yet. Leave-one-source-out is available as a robustness check, reserving a source costs the largest source is input/Blinkys_Scary_School.sap with 2 traces, so reserving it removes 2 of 12 traces from the desi, and only new historical material would turn interpolation into generalization.

**7. What are the corpus acceptance criteria?**

Six, all declared before the corpus is built: no separated feature, joint-box coverage, box calibration, the distance threshold, the propensity overlap region, and a balanced match under an enforced caliper. Section 9 lists them with their thresholds.

**8. Did the pilot meet them?**

**The pilot is not evaluated against them, by design.** It met **7 of 7** of its own feasibility criteria. The acceptance criteria need a corpus, and four compositions are not one. What the pilot established is that the mechanics work: the clock, the length, the truth levels and determinism.

**9. Which gaps need production changes?**

**One: AUDF = 0 while audible (the between-note pulse idiom).** A per-note or per-step way to emit a zero divider without silencing the channel. That is a change to the Music IR and to the compiler, so Stage 25 stops at the specification and does not implement it. It is not needed for the support question, because the idiom is a mediator rather than a matching feature, and Stage 25 does not implement it.

**10. What is the safest next step?**

**Build the corpus in three stages, gated by the declared criteria, and do not run a residual comparison until every acceptance criterion passes.** The pilot is stage one and it has passed. Section 15 lists what must not be done, including treating the pilot as a corpus and reading a matched difference as a performance-layer effect.

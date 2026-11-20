# Stage 23 - Controlled Historical Residual Test

Stage 22 decomposed the Stage 15 detector's residual on traces whose composition is known, found a difference between the historical and the control corpus, and warned that the difference was **not robust**: it moved with the outside-note convention and a corpus-composition difference would have produced it too. Stage 23 is the controlled test that warning asked for. It does not look for a performance layer; it tries to falsify the difference.

**The headline.** The convention only exists at frames no detected span covers, so restricting the residual to frames *inside* detected spans removes the convention altogether. On that convention-free estimand the control corpus sits at 21.7% and the historical corpus at 37.3% - a difference of **15.5%** with a source-clustered bootstrap interval of [10.2%, 21.9%]. The sign is the same under every residual definition, it survives dropping each SAP source in turn, and it appears on every channel.

**But the comparison is an extrapolation.** The corpora do not occupy the same region of trace-feature space: `audctl_change_rate`, `clock_179mhz`, `distinct_audf_values` have no common range at all, and **11 of 12** historical traces lie beyond the control corpus's own nearest-neighbour distance range. A model fitted on the control corpus and applied to the historical features leaves a gap of 0.1228 against its own leave-one-out error of 0.0593 - far larger than the model's error, but produced by a model asked to predict outside its support.

**Verdict: `HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED`.** The difference is real in this data and robust to every control this stage can apply, but its cause cannot be separated from a property of the trace shapes the control corpus never produces. That is a negative result for the performance layer and a specification for the next experiment.

Analysis only, read-only and additive. No music was generated, no listening test was run, no player was modified, no detector was repaired and no production schema was changed. Analysis version `stage23/1`.

Artefacts: `source_audit.json`, `corpus_comparison.json`, `residual_conventions.json`, `matching_diagnostics.json`, `matched_corpus_comparison.json`, `residual_profile_comparison.json`, `leave_one_song_out.json`, `sensitivity_analysis.json`, `negative_controls.json`, `verdict.json`, `stage23_manifest.json`.

## 1. Executive Summary

| question | answer |
|---|---|
| Is the difference robust to the convention? | **Yes.** The primary estimand excludes the frames where the convention applies, so it cannot move with it. Difference 15.5%. |
| Is the sign the same under every residual definition? | **True** - hold 10.6%, exporter 20.4%, in-span 15.5%, zero-onset-spans removed 8.8%. |
| Does it survive dropping each SAP source? | **True** over 11 sources. |
| Is it spread across channels? | **3 of 4** channels show a positive difference. |
| Does it survive composition matching? | Matched gap 0.1228 against a control leave-one-out error of 0.0593 - but **11 of 12** predictions are extrapolations. |
| Can its cause be identified? | **No.** 3 matching features have no common range, so a corpus-composition explanation cannot be ruled out. |
| Verdict | **HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED**; corpus composition HISTORICAL_DIFFERENCE_EXPLAINED_BY_CORPUS_COMPOSITION; performance candidate PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST |
| Reproducibility | **True** - the deterministic core was run twice and the payload digests matched |
| Read-only audit | **True** - 112 production and input artefacts hashed before and after the run, none changed |
| Atari Music Composer | **NO_PRODUCTION_DECISION_CHANGED** - no production decision is affected by this stage |

**A negative result is a full result, and this one is partly negative.** The difference is not a convention artefact and not a single song's; it is also not identified, and the experiment that would identify it is stated in section 16.

## 2. Source and Definition Audit

The brief's rule is that the artefacts win over any summary, including this one. Every definition this stage relies on is quoted from the stage that owns it:

| definition | owner | source |
|---|---|---|
| residual | stage20.build_residual | docs/stage22_detector_error_decomposition.md section 5 |
| what the historical corpus cannot produce | stage22 | docs/stage22_detector_error_decomposition.md section 16 |

Stage 22's published numbers, read from its own artefacts rather than restated:

| quantity | Stage 22 published |
|---|---|
| control_cause_partition | {'cause_note_set_share': 0.648443, 'cause_value_share': 0.077587, 'cause_interaction_share': 0.27397, 'cause_convention_share_of_hold': 0.302005} |
| control_detector_residual_values | 270701 |
| control_register_values | 1042740 |
| control_residual_share_exporter | 0.181203 |
| control_residual_share_hold | 0.259605 |
| falsification_verdict | HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL |
| historical_residual_share | 0.369975 |

### What the audit changed

| claim | what was measured instead | consequence |
|---|---|---|
| Stage 22 compared the two corpora on the *total* residual share, under two conventions, and reported that the difference was not robust because the AUDF split moved with the convention | the convention only exists at frames no detected span covers. Restricting the residual to frames inside detected spans removes the convention entirely, and the difference is then present under every definition rather than depending on one | the primary estimand of this stage is the in-span residual, which Stage 22 did not report |
| the historical traces are twelve songs | they are twelve traces from eleven SAP files and three composers, and one file contributes two subsongs | every interval here resamples sources rather than traces, and the effective sample is far smaller than twelve |
| Stage 22 compared the corpora on residual shares without checking whether the corpora occupy the same region of trace-feature space | several matching features have no common range at all - the 1.79 MHz clock, the number of distinct AUDF values, the trace length - and most historical traces lie outside the control corpus's support | a matched or regression-adjusted comparison on this corpus pair is an extrapolation, and this stage reports it as one instead of as a control |
| a first reading of the audit took the historical player's AUDF = 0 inter-note pulses to be the mechanism, because the spans that begin on such a pulse carry 39.0% of the historical residual | that 39.0% is a *volume* share, not a rate: those spans are 38.1% of the spans, and their residual rate (0.428) is close to the other spans' (0.352). The idiom changes which frames a span covers, it does not concentrate the error | the idiom is reported as a corpus-composition difference, not as the cause of the residual, and the decomposition is reported with both the rate and the volume |

**What is reused and what is not.** the residual definition, both conventions, the frame attribution buckets and the control-only restriction. These are reused through the Stage 22 functions themselves, never re-implemented. the Stage 22 historical comparison's verdict is treated as a hypothesis to falsify, not as a finding. Its published shares are recomputed here from the traces rather than copied.

## 3. Corpora and Their Limits

| corpus | traces | sources | authors | frames | register values | spans |
|---|---|---|---|---|---|---|
| historical | 12 | 11 | 3 | 127030 | 1143270 | 35902 |
| control | 53 | 53 | 1 | 115860 | 1042740 | 16630 |

**The historical corpus is clustered and small.** 12 traces come from 11 SAP files and 3 composers:

| author | traces |
|---|---|
| Adam Gilmore | 5 |
| David Whittaker | 3 |
| Rob Hubbard | 4 |

One file contributes more than one trace: `input/Blinkys_Scary_School.sap` -> 2 traces. the traces are clustered: eleven SAP sources and three composers for twelve traces. Every interval in this stage resamples sources, never frames and never traces as if they were independent.

**What the historical corpus cannot support.** The Tier D verdict from Stage 21 stands: there is no independent note source for any of these songs, so no note-level ground truth exists and no class that needs one can be measured on them. Section 9 lists which classes that removes.

## 4. Estimands and Residual Definitions

Seven estimands, each declaring its numerator, denominator, unit, silence rule, outside-span rule, coupled-channel rule and aggregation. Declaring them in one table is what stops a denominator from drifting between sections.

| estimand | numerator | denominator | outside spans | aggregation |
|---|---|---|---|---|
| E_total_hold | register values that differ, any frame | frames x 9 | predicted by carrying the last value forward (hold) | per trace; corpus summaries are over traces, never over register values |
| E_total_exporter | register values that differ, any frame | frames x 9 | predicted as zero (the frame compiler's convention) | per trace; corpus summaries are over traces, never over register values |
| E_in_span | register values that differ, at (frame, register) pairs a detected span drives | register values a detected span drives | excluded by construction, which is why this estimand is convention-free | per trace; corpus summaries are over traces, never over register values |
| E_out_span_hold | register values that differ, at (frame, register) pairs no span drives | register values no detected span drives | predicted by carrying the last value forward (hold) | per trace; corpus summaries are over traces, never over register values |
| E_out_span_exporter | register values that differ, at (frame, register) pairs no span drives | register values no detected span drives | predicted as zero (the frame compiler's convention) | per trace; corpus summaries are over traces, never over register values |
| E_zero_onset_span | values that differ, inside spans whose onset reads AUDF = 0 while audible | register values those spans drive | excluded; this is a decomposition of E_in_span, not a rival to it | per trace; corpus summaries are over traces |
| E_other_span | values that differ, inside spans whose onset does not read AUDF = 0 | register values those spans drive | excluded; the rest of E_in_span once the zero-onset spans are removed | per trace; corpus summaries are over traces |

**The primary estimand is `E_in_span`, and it is convention-free by construction.** A register value counts as in-span when a detected span drives *that register* in *that frame*. Inside a span both conventions write the span's own value, so no choice of convention can move the numerator, and the denominator is fixed by the spans. Splitting by frame instead would put one voice's registers into another voice's span, where the conventions genuinely differ, and the identities would then not hold; splitting by register keeps them exact for both policies. That is why `E_in_span`, and not the total, is the headline.

**The conventions disagree about a real but small region, and the disagreement is asymmetric.** The register values no detected span drives are 28.0% of the control corpus's values and 21.9% of the historical corpus's. On the control corpus the hold convention leaves a residual on 29.7% of them and the exporter on 1.6% - the compiler emits no write there and the player holds, so the exporter is nearly right and hold is not. On the historical corpus the two are 32.3% and 37.7%, so neither convention is right there. The convention therefore moves the control corpus's out-of-span residual by a factor of 18.2x and the historical corpus's by only 1.2x

The two totals are reported beside it as a sensitivity axis, and `E_other_span` is the same measurement with the spans that begin on a zero divider removed. Because the exporter convention is nearly right about the control corpus's out-of-span region and wrong about the historical corpus's, the hold total *understates* the difference and the exporter total *overstates* it; `E_in_span` is the only one of the three that is not partly a statement about the convention.

**No percentage is subtracted from another and called a performance excess.** The gap between the corpora is reported as a difference in an estimand, with its uncertainty, and nothing is given a causal reading it has not earned.

## 5. Results Under Each Convention

The same comparison under every definition, computed identically on both corpora. The convention is applied to *both* corpora in each row, so no row compares one corpus's convention with the other's.

| estimand | control mean | historical mean | difference | sign | n control | n historical |
|---|---|---|---|---|---|---|
| E_total_hold | 24.9% | 35.5% | 10.6% | positive | 53 | 12 |
| E_total_exporter | 16.3% | 36.6% | 20.4% | positive | 53 | 12 |
| E_in_span | 21.7% | 37.3% | 15.5% | positive | 53 | 12 |
| E_out_span_hold | 28.2% | 25.7% | -2.5% | negative | 53 | 12 |
| E_out_span_exporter | 1.9% | 30.5% | 28.6% | positive | 53 | 12 |
| E_zero_onset_span | 5.9% | 54.4% | 48.6% | positive | 8 | 11 |
| E_other_span | 21.8% | 30.6% | 8.8% | positive | 53 | 12 |

**The sign is stable across the total definitions: True** (positive). a register value is in-span when a detected span drives that register in that frame, and the hold and exporter conventions write the same value there by construction, so E_in_span cannot be moved by the convention choice. The conventions differ only on register values no span drives, and those are excluded.

**Why this differs from Stage 22's finding.** Stage 22 reported that the difference was not robust because the AUDF *split* moved with the convention. That was true of the split, and it is still true. What changes here is the estimand: restricting the residual to frames inside detected spans removes the frames the convention acts on, so the convention can no longer reach the comparison at all.

## 6. Corpus Characteristics Before Matching

Feature by feature, where the two corpora actually overlap. The *matching* features are pure trace properties; the *mediator* features are kept out of the matching because balancing on a mediator would control away the mechanism under test.

| feature | role | control mean | historical mean | common range | historical inside control range | overlaps |
|---|---|---|---|---|---|---|
| frames | matching | 2186.0377 | 10585.8333 | [2048.0000, 5952.0000] | 8.3% | True |
| audible_share | matching | 0.9889 | 0.9980 | [0.9784, 1.0000] | 100.0% | True |
| register_change_rate | matching | 1.5565 | 2.9703 | [1.8045, 2.6967] | 25.0% | True |
| audf_change_rate | matching | 0.3344 | 1.3970 | [0.6675, 0.9302] | 8.3% | True |
| audc_change_rate | matching | 1.2221 | 1.5734 | [0.6274, 2.1089] | 100.0% | True |
| audctl_change_rate | matching | 0.0000 | 0.0000 | [0.0000, 0.0000] | 100.0% | False |
| audc_volume_change_rate | matching | 1.2216 | 1.5418 | [0.6274, 2.0490] | 100.0% | True |
| audc_distortion_change_rate | matching | 0.1841 | 0.2236 | [0.0044, 0.5141] | 91.7% | True |
| noise_active_share | matching | 0.5064 | 0.2722 | [0.0000, 0.4684] | 100.0% | True |
| max_simultaneous | matching | 3.5472 | 3.0833 | [3.0000, 4.0000] | 100.0% | True |
| mean_simultaneous | matching | 2.7552 | 2.7029 | [2.2188, 3.4174] | 100.0% | True |
| coupled_16bit | matching | 0.4151 | 0.9167 | [0.0000, 1.0000] | 100.0% | True |
| clock_179mhz | matching | 0.0000 | 0.9167 | [0.0000, 0.0000] | 8.3% | False |
| distinct_audf_values | matching | 23.7170 | 122.0000 | none (empty) | 0.0% | False |
| distinct_audc_values | matching | 22.3396 | 28.8333 | [17.0000, 35.0000] | 83.3% | True |
| mean_audc_run_length | matching | 3.1421 | 2.2201 | [1.8750, 4.7790] | 50.0% | True |
| channel_balance | matching | 0.6641 | 0.2941 | [0.0227, 1.0563] | 100.0% | True |
| zero_onset_span_share | mediator | 0.0147 | 0.3077 | [0.0000, 0.3333] | 58.3% | True |
| zero_divider_audible_share | mediator | 0.0240 | 0.1923 | [0.0000, 0.2885] | 75.0% | True |
| span_density | mediator | 0.1436 | 0.2764 | [0.1498, 0.4057] | 91.7% | True |
| mean_span_length | mediator | 28.1364 | 10.7085 | [6.5145, 16.8617] | 100.0% | True |
| median_span_length | mediator | 11.2642 | 5.8333 | [3.0000, 10.0000] | 100.0% | True |
| audf_zero_share | mediator | 0.6165 | 0.2670 | [0.2188, 0.5403] | 66.7% | True |

**Features with no common range at all:** `audctl_change_rate`, `clock_179mhz`, `distinct_audf_values`.

**Matching features covering fewer than half the historical traces:** `audf_change_rate`, `clock_179mhz`, `distinct_audf_values`, `frames`, `register_change_rate`.

the corpora overlap on some features and not on others. The matching features listed above have no common range or cover fewer than half the historical traces, so a matched comparison is an extrapolation for those traces and is reported as one.

## 7. Matching Procedure and Quality

Matching is deterministic: pooled standardisation, Euclidean distance over the matching features, k nearest neighbours, ties broken on the slug. The standardisation uses the mean and standard deviation of the *pooled* corpora, so neither corpus's scale is privileged.

| quantity | value |
|---|---|
| k | 5 |
| matching features | 17 |
| mediator features excluded from matching | 6 |
| control leave-one-out MAE | 0.0593 |
| control leave-one-out RMSE | 0.0735 |
| control leave-one-out bias | -0.0045 |
| control nearest-neighbour distance, median | 1.1200 |
| control nearest-neighbour distance, max | 3.9341 |
| historical traces beyond that range | 11 of 12 |

### The univariate screen

One model per feature, fitted on the control corpus alone, then applied to the historical features. The `gap` column is what the model fails to explain, and the overlap column says whether the prediction was an interpolation at all.

| feature | role | slope | R2 | control LOO MAE | predicted historical mean | gap | overlap |
|---|---|---|---|---|---|---|---|
| audc_change_rate | features | 0.1330 | 0.2861 | 0.0557 | 0.2641 | 0.1084 | 100.0% |
| audc_distortion_change_rate | features | 0.0118 | 0.0004 | 0.0700 | 0.2179 | 0.1546 | 91.7% |
| audc_volume_change_rate | features | 0.1327 | 0.2860 | 0.0557 | 0.2599 | 0.1126 | 100.0% |
| audctl_change_rate | features | n/a | n/a | n/a | n/a | n/a | n/a |
| audf_change_rate | features | 0.1685 | 0.1110 | 0.0642 | 0.3965 | -0.0240 | 8.3% |
| audf_zero_share | mediators | -0.1715 | 0.2080 | 0.0620 | 0.2773 | 0.0952 | 66.7% |
| audible_share | features | 1.1309 | 0.2117 | 0.0603 | 0.2277 | 0.1448 | 100.0% |
| channel_balance | features | -0.1320 | 0.2412 | 0.0611 | 0.2663 | 0.1062 | 100.0% |
| clock_179mhz | features | n/a | n/a | n/a | n/a | n/a | n/a |
| coupled_16bit | features | -0.0315 | 0.0331 | 0.0700 | 0.2016 | 0.1709 | 100.0% |
| distinct_audc_values | features | 0.0023 | 0.0272 | 0.0700 | 0.2324 | 0.1401 | 83.3% |
| distinct_audf_values | features | 0.0048 | 0.1730 | 0.0660 | 0.6863 | -0.3138 | 0.0% |
| frames | features | 0.0000 | 0.1155 | 0.0630 | 0.3524 | 0.0201 | 8.3% |
| max_simultaneous | features | 0.0604 | 0.1245 | 0.0679 | 0.1894 | 0.1831 | 100.0% |
| mean_audc_run_length | features | -0.0372 | 0.1837 | 0.0600 | 0.2517 | 0.1208 | 50.0% |
| mean_simultaneous | features | 0.0958 | 0.3887 | 0.0564 | 0.2124 | 0.1601 | 100.0% |
| mean_span_length | mediators | 0.0007 | 0.0799 | 0.0682 | 0.2047 | 0.1678 | 100.0% |
| median_span_length | mediators | 0.0007 | 0.0115 | 0.0759 | 0.2138 | 0.1588 | 100.0% |
| noise_active_share | features | 0.1930 | 0.2751 | 0.0599 | 0.1722 | 0.2003 | 100.0% |
| register_change_rate | features | 0.0897 | 0.2521 | 0.0572 | 0.3442 | 0.0283 | 25.0% |
| span_density | mediators | 0.0962 | 0.0067 | 0.0697 | 0.2302 | 0.1423 | 91.7% |
| zero_divider_audible_share | mediators | 0.1702 | 0.0153 | 0.0695 | 0.2461 | 0.1264 | 75.0% |
| zero_onset_span_share | mediators | 0.3733 | 0.0506 | 0.0710 | 0.3268 | 0.0457 | 58.3% |

Naive gap 0.1551; the closest any single feature comes to closing it is `frames` at 0.0201. No single trace property explains the difference.

## 8. Results Before and After Matching

### Before matching, per trace

| estimand | control n | control mean | control median | historical n | historical mean | historical median | difference in means | bootstrap interval | excludes zero |
|---|---|---|---|---|---|---|---|---|---|
| E_in_span | 53 | 21.7% | 23.4% | 12 | 37.3% | 36.9% | 15.5% | [10.2%, 21.9%] | True |
| E_other_span | 53 | 21.8% | 23.4% | 12 | 30.6% | 27.9% | 8.8% | [2.7%, 16.3%] | True |
| E_out_span_exporter | 53 | 1.9% | 0.0% | 12 | 30.5% | 32.9% | 28.6% | [20.8%, 36.8%] | True |
| E_out_span_hold | 53 | 28.2% | 29.7% | 12 | 25.7% | 27.5% | -2.5% | [-11.2%, 7.5%] | False |
| E_total_exporter | 53 | 16.3% | 16.8% | 12 | 36.6% | 37.8% | 20.4% | [15.9%, 25.3%] | True |
| E_total_hold | 53 | 24.9% | 25.6% | 12 | 35.5% | 36.4% | 10.6% | [5.8%, 16.0%] | True |
| E_zero_onset_span | 8 | 5.9% | 0.0% | 11 | 54.4% | 65.3% | 48.6% | [28.5%, 67.3%] | True |

the trace. Register values are never treated as independent observations: 1.1 million values from twelve traces are twelve observations, not 1.1 million.

### After matching

| slug | author | actual | predicted | gap | nearest distance | extrapolation |
|---|---|---|---|---|---|---|
| BMX_Simulator__sub0 | David Whittaker | 34.9% | 26.5% | 8.4% | 6.6192 | True |
| Blinkys_Scary_School__sub0 | Adam Gilmore | 25.6% | 19.8% | 5.8% | 4.8086 | True |
| Blinkys_Scary_School__sub3 | Adam Gilmore | 26.9% | 23.2% | 3.7% | 5.3659 | True |
| Draconus_2024__sub0 | Adam Gilmore | 59.1% | 27.2% | 31.9% | 6.1613 | True |
| Extirpator__sub0 | Rob Hubbard | 37.2% | 27.5% | 9.8% | 5.5936 | True |
| International_Karate__sub0 | Rob Hubbard | 40.2% | 27.3% | 12.9% | 5.7398 | True |
| Jet_Set_Willy__sub0 | Rob Hubbard | 36.7% | 25.7% | 10.9% | 5.6341 | True |
| Ninja_Commando__sub0 | Adam Gilmore | 27.8% | 19.9% | 7.9% | 4.3632 | True |
| Panther__sub0 | David Whittaker | 39.5% | 27.3% | 12.2% | 5.8486 | True |
| Red_Max__sub0 | David Whittaker | 43.6% | 27.6% | 15.9% | 7.1484 | True |
| Warhawk__sub0 | Rob Hubbard | 42.7% | 26.9% | 15.8% | 5.8631 | True |
| Zybex__sub4 | Adam Gilmore | 32.8% | 20.6% | 12.2% | 3.6689 | False |

Matched gap mean 0.1228, median 0.1155, range [0.0370, 0.3192]. the gap is judged against the control corpus's own leave-one-out error. A gap far larger than that error is not explained by the matching features; but if the prediction lies beyond the control corpus's own distance range it is an extrapolation, and the gap then cannot be read as an effect estimate.

## 9. Residual Profiles

Which Stage 22 error classes can be measured on which corpus, decided before the comparison so a historical residual is never labelled with a class the trace cannot support:

| class | control | historical | why |
|---|---|---|---|
| AUDF / AUDC split of the residual | measurable | measurable | both are register-group shares of a residual the same detector produced |
| register changes per frame | measurable | measurable | a property of the trace alone |
| stable-state run lengths | measurable | measurable | a property of the trace alone |
| AUDF and AUDC change co-occurrence | measurable | measurable | a property of the trace alone |
| channel activity shares | measurable | measurable | a property of the trace alone |
| generator-transition precision and recall | measurable | measurable | the truth is the trace's own distortion changes, so it needs no ground truth |
| register activity at zero level | measurable | measurable | a property of the trace alone |
| merged spans, missed notes, note recall | control only | not identifiable | it needs a ground-truth note list, and a Tier D SAP has none |
| value reading versus note set | control only | not identifiable | the arm needs the composition's spans, which the historical corpus lacks |
| pitch exactness at a matched onset | control only | not identifiable | it compares the read against the composed pitch |
| frame attribution buckets | control only | not identifiable | three of the five buckets need a ground-truth occupancy |

### Trace-derived profile features, measurable in both

| feature | control mean | historical mean | difference |
|---|---|---|---|
| audc_change_rate | 1.2221 | 1.5734 | 0.3512 |
| audf_audc_co_occurrence_rate | 0.0000 | 0.0000 | 0.0000 |
| audf_change_rate | 0.3344 | 1.3970 | 1.0626 |
| max_audc_run_length | 0.0000 | 0.0000 | 0.0000 |
| mean_audc_run_length | 3.1421 | 2.2201 | -0.9221 |
| p90_audc_run_length | 0.0000 | 0.0000 | 0.0000 |
| zero_level_change_rate | 0.0000 | 0.0000 | 0.0000 |

### Register-group split of the residual

| group | control share of residual | historical share of residual |
|---|---|---|
| AUDC | 35.4% | 48.0% |
| AUDF | 64.6% | 52.0% |

these are properties of the trace and of the detector's output on it. They are not properties of a composition and not evidence of an author's intention, and no historical residual is labelled with a class the trace cannot support.

## 10. Per-Trace Uncertainty

**The unit of replication is the trace, and the interval resamples sources.** The historical corpus holds 12 traces but only 11 SAP files and 3 composers, so an interval that treated the traces as independent would be too narrow. No interval in this stage resamples frames.

| estimand | corpus | n | mean | median | min | p25 | p75 | max | stdev |
|---|---|---|---|---|---|---|---|---|---|
| E_in_span | control | 53 | 21.7% | 23.4% | 2.3% | 17.2% | 27.4% | 39.6% | 0.0860 |
| E_in_span | historical | 12 | 37.3% | 36.9% | 25.6% | 31.6% | 40.8% | 59.1% | 0.0914 |
| E_other_span | control | 53 | 21.8% | 23.4% | 2.3% | 17.2% | 28.1% | 38.7% | 0.0854 |
| E_other_span | historical | 12 | 30.6% | 27.9% | 14.5% | 25.8% | 30.4% | 59.4% | 0.1141 |
| E_out_span_exporter | control | 53 | 1.9% | 0.0% | 0.0% | 0.0% | 1.8% | 11.3% | 0.0332 |
| E_out_span_exporter | historical | 12 | 30.5% | 32.9% | 4.3% | 23.5% | 38.9% | 61.0% | 0.1546 |
| E_out_span_hold | control | 53 | 28.2% | 29.7% | 2.0% | 24.1% | 33.5% | 41.1% | 0.0759 |
| E_out_span_hold | historical | 12 | 25.7% | 27.5% | 3.2% | 13.1% | 33.9% | 61.0% | 0.1632 |
| E_total_exporter | control | 53 | 16.3% | 16.8% | 0.8% | 11.3% | 20.9% | 34.9% | 0.0685 |
| E_total_exporter | historical | 12 | 36.6% | 37.8% | 24.8% | 33.4% | 38.8% | 52.6% | 0.0729 |
| E_total_hold | control | 53 | 24.9% | 25.6% | 10.8% | 21.9% | 28.3% | 36.8% | 0.0536 |
| E_total_hold | historical | 12 | 35.5% | 36.4% | 23.8% | 31.6% | 38.6% | 52.0% | 0.0786 |
| E_zero_onset_span | control | 8 | 5.9% | 0.0% | 0.0% | 0.0% | 1.1% | 42.3% | 0.1481 |
| E_zero_onset_span | historical | 11 | 54.4% | 65.3% | 15.0% | 36.5% | 71.6% | 83.0% | 0.2629 |

**The power limit is stated plainly.** Three composers and eleven files cannot support a precise estimate of a corpus-level difference, and no p-value is reported here because the sample cannot carry one. What is reported is the effect size, its interval, and whether the sign survives every perturbation this stage can apply.

## 11. Leave-One-Source-Out

The unit dropped is the SAP *source*, not the trace: two traces share one file, so dropping a trace would leave its sibling in place and understate the dependence. Full difference 15.5% with interval [10.6%, 21.2%].

| dropped source | dropped traces | kept traces | difference | bootstrap interval | sign preserved |
|---|---|---|---|---|---|
| input/BMX_Simulator.sap | BMX_Simulator__sub0 | 11 | 15.7% | [10.3%, 22.9%] | True |
| input/Blinkys_Scary_School.sap | Blinkys_Scary_School__sub0, Blinkys_Scary_School__sub3 | 10 | 17.7% | [12.9%, 23.2%] | True |
| input/Draconus_2024.sap | Draconus_2024__sub0 | 11 | 13.5% | [9.2%, 18.1%] | True |
| input/Extirpator.sap | Extirpator__sub0 | 11 | 15.5% | [9.6%, 21.3%] | True |
| input/International_Karate.sap | International_Karate__sub0 | 11 | 15.2% | [9.5%, 21.0%] | True |
| input/Jet_Set_Willy.sap | Jet_Set_Willy__sub0 | 11 | 15.6% | [9.6%, 21.4%] | True |
| input/Ninja_Commando.sap | Ninja_Commando__sub0 | 11 | 16.4% | [10.8%, 22.1%] | True |
| input/Panther.sap | Panther__sub0 | 11 | 15.3% | [9.8%, 21.3%] | True |
| input/Red_Max.sap | Red_Max__sub0 | 11 | 14.9% | [9.6%, 21.1%] | True |
| input/Warhawk.sap | Warhawk__sub0 | 11 | 15.0% | [9.6%, 21.2%] | True |
| input/Zybex.sap | Zybex__sub4 | 11 | 15.9% | [10.5%, 22.5%] | True |

Sign preserved in every drop: **True**. Range of the difference across drops: [13.5%, 17.7%]. if the sign survived every drop the conclusion does not rest on a single SAP file; if it did not, the effect is that file's and not the corpus's.

## 12. Negative Controls

Features that should reflect the *encoding* rather than any musical behaviour. If a difference of the same shape and size as the primary estimand appeared here, the primary difference would be a property of comparing two corpora of different shape.

| feature | control mean | historical mean | difference | control constant | historical constant |
|---|---|---|---|---|---|
| register_value_cardinality | 46.0566 | 150.8333 | 104.7767 | False | False |
| audctl_value | 6.6415 | 73.3333 | 66.6918 | False | False |
| frames_per_span_ratio | 10.4167 | 4.0504 | -6.3664 | False | False |
| register_columns_constant_share | 0.8889 | 0.8889 | 0.0000 | True | True |

Primary estimand difference for comparison: **15.5%**. Largest absolute negative-control difference: 104.7767. the negative controls are properties of the encoding. A difference of the same shape and size as the primary estimand would mean the primary difference is a property of comparing two corpora of different shape, and the report says so.

## 13. Sensitivity Analysis

### By convention and definition (controls A and F)

See section 5. The sign is stable across every total definition, and the primary estimand is convention-free by construction.

### By channel (control D)

| channel | registers | control in-span rate | historical in-span rate | difference | control share of residual | historical share of residual |
|---|---|---|---|---|---|---|
| 1 | AUDF1, AUDC1 | 35.7% | 6.3% | -29.3% | 41.2% | 5.4% |
| 2 | AUDF2, AUDC2 | 18.1% | 34.5% | 16.4% | 20.9% | 21.0% |
| 3 | AUDF3, AUDC3 | 30.7% | 57.8% | 27.1% | 33.5% | 34.3% |
| 4 | AUDF4, AUDC4 | 6.0% | 58.7% | 52.8% | 4.3% | 39.3% |

3 of 4 channels show a positive difference; spread across channels: **False**. if the difference appears on every channel it is not one channel's artefact; if it appears on one channel only, the effect is that channel's and the report says so.

### By composition matching (control B)

See sections 7 and 8. The matched gap is far larger than the model's own error, but most predictions are extrapolations, so the matched comparison is reported as an extrapolation rather than as a control.

## 14. Identifiability Limits

**What can be identified and what cannot.** The trace-level estimands are identified: they are properties of a register stream and a detector, both of which exist for both corpora. The *cause* of the difference is not identified, for three reasons that compound:

1. **The corpora do not overlap.** `audctl_change_rate`, `clock_179mhz`, `distinct_audf_values` have no common range, and 11 of 12 historical traces are outside the control corpus's nearest-neighbour distance range. Any adjusted comparison is an extrapolation.

2. **The historical corpus is clustered.** Eleven files and three composers cannot separate a corpus-level effect from a player-routine effect, and the identified idiom is present in all four of one composer's traces and absent from several others.

3. **No historical ground truth exists.** The classes that would say *where* the residual comes from - note set versus value reading, merged versus missed spans - need a composition, and a Tier D SAP has none.


### The pre-declared criteria

| criterion | threshold | passed | measurement |
|---|---|---|---|
| present in more than one trace and more than one source | at least 2 distinct sources contribute | True | {"sources_contributing": 11, "traces": 12} |
| not driven by one trace or one channel | leave-one-source-out keeps the sign | True | {"max_difference_after_drop": 0.17711, "min_difference_after_drop": 0.135183} |
| holds under every residual definition | the sign is the same for all four total estimands | True | {"total_definition_signs": ["positive"]} |
| survives composition matching | the gap stays positive after matching, and the match is not an extrapolation | False | {"matched_gap_mean": 0.122811, "traces": 12, "traces_beyond_control_support": 11} |
| practically significant, not merely non-zero | the effect size is at least 0.05 | True | {"difference_in_means": 0.155086, "threshold": 0.05} |
| not explained by the mechanisms identified in this stage | the gap survives the zero-onset-span decomposition | True | {"difference_after_removing_zero_onset_spans": 0.087537, "difference_before": 0.155086} |
| reproducible | a repeated run produces byte-identical artefacts | True | {"repeated_run_byte_identical": true} |

**6 of 7** criteria met. The gap exceeds the model's own error, but 11 of 12 historical traces lie beyond the control corpus's feature support, so the comparison cannot separate a historical-specific effect from a property of trace shapes the control corpus never produces. Meeting these criteria does not prove a performance layer. It means a residual effect survived the controls and is worth a new experiment.

## 15. Methodological Corrections

Every problem found while building this stage, and what was done about it. Nothing was quietly fixed: a correction that changes a number is stated here.

**1. A first reading of the audit mistook a volume share for a rate.** The spans that begin on a zero divider carry 39.0% of the historical residual, which reads like a mechanism. They are 38.1% of the spans, and their residual *rate* (0.428) is close to the other spans' (0.352). The idiom changes which frames a span covers; it does not concentrate the error. Both the rate and the volume are now reported, and the idiom is classified as a corpus-composition difference rather than as the cause.

**2. The primary estimand was chosen to remove a confound, not to favour a result.** Stage 22's comparison moved with the convention because the convention acts on frames no span covers. Restricting the residual to in-span frames removes it. The choice was made from the definition of the convention, before any of this stage's numbers existed, and the two totals are still reported beside it so a reader can see what the restriction costs.

**3. The interval resamples sources, not traces and not frames.** A naive interval over 1.1 million register values would treat every frame as an independent experiment. The unit here is the SAP source, because two of the twelve traces share a file and the files cluster by composer.

**4. The mediator features are excluded from the matching.** The zero-onset-span share and the span-density features predict the residual, and including them in the matching would balance away the very mechanism the stage is testing. They are reported separately and the code says why.

**5. Stage 22's `A_exact` arm is not used as a residual.** It is zero by construction. The convention comparison here uses the detector's own arm under each policy.

**6. An undefined estimand is reported as undefined, not as zero.** Three historical traces contain no zero-onset span, so `E_zero_onset_span` has no denominator there. Those traces are excluded from that estimand's summary and the count is reported, rather than the value being recorded as zero.

**7. The in-span split had to be per register, not per frame, and the first version was wrong.** The obvious definition of `E_in_span` marks a *frame* as in-span when a detected span covers it. That definition breaks the identities: a frame can be covered by one voice's span while another voice has no span there, and the two conventions genuinely disagree about that other voice's registers. Under the frame-wise definition the two totals no longer summed to the in-span part plus the out-of-span part, and the discrepancy was large - on one historical trace the frame-wise in-span numerator exceeded the hold total for the whole trace. A register value now counts as in-span when a detected span drives *that register* in *that frame*, the identities hold exactly for both policies, and the check is asserted in the code rather than assumed. This changed the headline from 20.2% to 15.5%, so it is reported as a correction and not as a refinement.

**8. A control the stage relied on turned out not to be exact.** The exporter convention predicts zero outside spans, and the first version of this report said the control corpus's out-of-span residual is zero by construction. It is not: it is 1.6% of the control corpus's out-of-span values, because the detector misses some spans and the trace then holds a divider the exporter predicts as zero. The claim is now the measured one, and it is still small enough to carry the argument - but it is stated as a measurement rather than as a property.

### Read-only audit

| audit | files checked | changed | read-only |
|---|---|---|---|
| traces, composition documents and upstream artefacts | 96 | 0 | True |
| production modules, the player source and the profile DSL | 16 | 0 | True |

Stage 15 to 22, the composer, the DSL, the IR, the player and the exporter were read through their hashes and never written. The traces and the composition documents were hashed before and after the run as well.

## 16. Verdict and Recommendation

| subject | verdict | deciding condition |
|---|---|---|
| atari_music_composer_impact | NO_PRODUCTION_DECISION_CHANGED | Stage 23 changes no detector, no compiler, no player and no schema, and it produces no music. Whatever it found is a research result about a measurement instrument, not a change to the composer. |
| corpus_composition | HISTORICAL_DIFFERENCE_EXPLAINED_BY_CORPUS_COMPOSITION | The corpora do not share a feature range on several matching features, so the difference could be a property of the trace shapes the historical corpus happens to have. That is a corpus-composition explanation and it cannot be ruled out here. |
| performance_candidate | PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST | No test here can confirm a performance layer, and none is claimed. The verdict only says whether a new experiment is warranted and what it would have to control. |
| primary | HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED | The difference holds under every definition and survives every leave-one-source-out drop, but most historical traces lie outside the control corpus's feature support, so its cause cannot be separated from a property of trace shape. |

### What the verdict means

**`HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED`.** The difference holds under every definition and survives every leave-one-source-out drop, but most historical traces lie outside the control corpus's feature support, so its cause cannot be separated from a property of trace shape. The difference is not a convention artefact and not one song's, and it is not identified. Calling it a historical-specific effect would overstate what the data can carry; calling it nothing would understate what was measured.

### What would identify it

The blocker is overlap, and overlap is something the project can build. A new experiment would need a control set whose *trace-level* features resemble the historical ones:

1. **Compositions that use the same POKEY configurations.** The historical corpus is dominated by the 16-bit pair at 1.79 MHz; the control corpus never uses that clock. Composing control songs in that configuration closes the largest gap and is a composer feature, not a detector change.

2. **Compositions with comparable register activity.** The historical traces change AUDF roughly four times as often per frame and hold AUDC for shorter runs. Envelopes and pitch activity of that density can be written directly in the DSL.

3. **Traces of comparable length.** The historical traces are five times longer on average; a matched length removes a systematic difference that has nothing to do with music.

4. **Then repeat this stage unchanged.** If the difference survives an *interpolated* comparison - predictions inside the control corpus's own support - it becomes a candidate worth a controlled experiment. If it does not, the difference was trace shape.

**Stage 24 is not implemented here and is not begun.** It is proposed, with its requirements, and the decision belongs to whoever reads this report.

### What does not change

**NO_PRODUCTION_DECISION_CHANGED.** Stage 23 changes no detector, no compiler, no player and no schema, and it produces no music. Whatever it found is a research result about a measurement instrument, not a change to the composer.

## The Eight Closing Questions

**1. Is the historical-control residual difference robust to the choice of convention?**

**Yes.** The primary estimand, `E_in_span`, excludes the register values where the conventions differ, so the convention cannot reach it. The difference is 15.5% and the sign is the same under every total definition (positive). Stage 22's warning was about the *split* of the residual between AUDF and AUDC, which is still convention-sensitive; it was never about whether a difference existed.

**2. Does it survive composition matching?**

**Not testably.** The matched gap is 0.1228 against a control leave-one-out error of 0.0593, so the gap is far larger than the model's error. But 11 of 12 predictions lie beyond the control corpus's own distance range, so the gap is an extrapolation and cannot be read as an effect estimate. A model cannot be asked to predict outside its support and then believed.

**3. Is the result stable when historical traces are dropped?**

**Yes.** Dropping each of the 11 SAP sources in turn keeps the sign in every case (True), with the difference ranging over [13.5%, 17.7%]. The result is not one file's.

**4. Is it spread across traces and channels?**

**Across traces, yes; across channels, yes.** 6 of 7 pre-declared criteria are met and the failing one is the matching criterion. 3 of 4 channels show a positive difference, so it is not one channel's artefact.

**5. Can the known Stage 22 limitations explain it?**

**Partly, and not entirely.** The value-reading limitation is the four-parameter contour, which is a property of the detector and applies to both corpora equally. The zero-onset span idiom was the most promising candidate and it does not concentrate the error: removing those spans leaves a difference of 8.8%. No single trace feature closes the gap either - the closest comes within 0.0201 of the naive 0.1551. 3 of 3 negative controls differ between the corpora, and they are measured on their own scales so they cannot be compared numerically with a residual rate: `register_value_cardinality` 46.0566 against 150.8333, `audctl_value` 6.6415 against 73.3333, `frames_per_span_ratio` 10.4167 against 4.0504. The controls therefore do not clear the difference of an encoding explanation - they show the two corpora differ in encoding at least as much as they differ in residual, which is the corpus-composition reading the verdict already carries.

**6. Can the available data identify its cause?**

**No.** `audctl_change_rate`, `clock_179mhz`, `distinct_audf_values` have no common range between the corpora, so the difference cannot be separated from a property of the trace shapes the historical corpus happens to have. The historical corpus is also clustered by player routine, and no ground truth exists to attribute the residual to a note-level cause.

**7. Is there sufficient reason to design Stage 24?**

**Yes, but only as a new experiment and only on the overlap gap.** The verdict is `HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED` and the performance-candidate verdict is `PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST`. Section 16 lists what Stage 24 would have to control. Stage 24 is not implemented and is not begun here.

**8. Does the result change any decision about Atari Music Composer?**

**No.** `NO_PRODUCTION_DECISION_CHANGED`. No detector was repaired, no compiler, DSL, IR, player or schema was touched, no music was generated and no listening test was run. The result is a statement about a measurement instrument and about what the project's two corpora can and cannot support.

## Final Statement

**The historical-control residual difference is real in this data, robust to every control this stage can apply, and not identified.** Verdict `HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED`. It is not evidence of a performance layer, and it is not dismissed either: it is a precisely stated gap between two corpora that do not overlap, with a stated way to close the overlap.

**Stage 23 stops here.** No further stage is implemented, no music is generated, and no production code is changed.

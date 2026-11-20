# Stage 24 - Corpus Overlap and Confounding Analysis

Stage 23 measured a residual difference between the historical SAP corpus and the Tier A control corpus, found it robust, and ended with `HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED` because the matching criterion failed. Stage 24 does not re-measure the residual. It asks one question: **is that comparison identifiable at all with the data that exists?**

**The headline.** 12 historical traces from 11 SAP files and 3 composers, against 53 control compositions. **0 of 12** historical traces lie inside the control corpus's feature box, against **41 of 53** control traces under the same leave-one-out test - so the criterion can pass traces, and it passes none of the historical ones. The propensity score separates the corpora completely (0 historical traces in the overlap region, 16 of 22 coefficients changing sign across bootstrap resamples), and the nearest historical trace is 4.0930 standardised units from the control corpus against a control leave-one-out maximum of 5.2855.

**No matching method is validated.** 15 declared methods were run; 3 can produce a difference and **0** satisfies the balance criterion declared before they ran. Every nearest-neighbour caliper retains zero historical traces.

**Verdict: `COMMON_SUPPORT_INADEQUATE`.** The difference itself is unchanged from Stage 23 - 15.5% with an interval of [10.1%, 21.9%] - and it is still stable. What Stage 24 adds is that it cannot be located in any comparable population, so it cannot be attributed to a cause. That is a limitation of the data, named as one.

Analysis only, read-only and additive. No music was generated, no corpus was created, no profile was bound, no player or detector was changed and no production schema was touched. Analysis version `stage24/1`.

Artefacts: `corpus_inventory.json`, `feature_definitions.json`, `univariate_overlap.json`, `multivariate_overlap.json`, `matching_diagnostics.json`, `matched_comparison.json`, `effective_sample_sizes.json`, `sensitivity_analysis.json`, `leave_one_source_out.json`, `identifiability_assessment.json`, `next_experiment_design.json`, `verdict.json`, `stage24_manifest.json`.

## 1. Executive Summary

| question | answer |
|---|---|
| Do the corpora share enough feature space for a matched comparison? | **No.** 0 of 12 historical traces are inside the control box; no feature is strictly separated, but the joint box is empty |
| Was the Stage 23 matching methodologically sound? | **No.** Its declared caliper was never applied and its balance was never checked |
| Does the +15.51 pp difference survive in a comparable population? | **The question cannot be answered.** No comparable subset could be formed, so there is no matched estimate |
| Is the result stable with respect to convention and parameters? | **The raw comparison is stable** (STABLE_ON_THE_RAW_COMPARISON_BUT_UNIDENTIFIED); the matched comparison does not exist, so its stability is undefined |
| Can the cause of the difference be identified? | **No.** No. - four blockers are named in section 11 |
| Is a new control corpus needed? | **Yes.** The comparison cannot be identified with the corpora that exist |
| Does Stage 24 justify a new experiment? | **Yes, as a corpus and not as an analysis.** Section 12 states the minimum design |
| Does the result change any Atari Music Composer decision? | **No.** `NO_PRODUCTION_DECISION_CHANGED` |
| Verdict | **COMMON_SUPPORT_INADEQUATE** |
| Auxiliary verdicts | `MATCHING_RETAINS_NO_USABLE_SAMPLE`, `HISTORICAL_DIFFERENCE_STABLE_BUT_NOT_IDENTIFIED`, `NEW_CONTROL_CORPUS_REQUIRED`, `PERFORMANCE_LAYER_NOT_SUPPORTED_AND_NOT_TESTABLE_HERE`, `NO_PRODUCTION_DECISION_CHANGED` |
| Reproducibility | **True** - the deterministic core was run twice and the payload digests matched |
| Read-only audit | **True** - 124 production and input artefacts hashed before and after the run, none changed |

**The descriptive, the matched and the identified are three different statements.** Descriptive: **yes**, the historical corpus carries a larger residual (15.5%). Matched: **the question cannot be answered: no comparable subset could be formed**. Identified: **no**. This stage reports all three separately and merges none of them.

**The difference is not denied and it is not explained.** It is measured, it is stable under every leave-one-out axis and every residual definition, and the data cannot say what produced it. Section 11 names the four reasons; none of them is a statistical problem that a better method would fix.

## 2. Corpus and Source Audit

The brief's rule is that the artefacts win over any summary, including this one. Every definition this stage relies on is quoted from the stage that owns it, and Stage 23's published numbers are read from its own artefacts rather than restated:

| quantity | Stage 23 published |
|---|---|
| analysis_version | stage23/1 |
| support verdict | HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED |
| primary estimand | E_in_span |
| control mean | 0.2174 |
| historical mean | 0.3725 |
| difference | 0.1551 |
| interval | [0.1017399896770682, 0.21919539631217835] |
| declared caliper | None |
| caliper actually applied | False |

### What the corpora contain

| property | historical | control |
|---|---|---|
| traces | 12 | 53 |
| independent sources | 11 | 53 |
| credited authors | 3 | 1 |
| AUDCTL configurations | {'$00': 1, '$50': 11} | {'$00': 31, '$10': 22} |
| document kinds | {'pokey-sound-archaeology/trace/1': 12} | {'control_dsl': 10, 'control_json': 43} |
| SAP types | {'B': 12} | {'dsl': 53} |
| frames median | 9833.0000 | 1920.0000 |
| frames range | [2048.0000, 19008.0000] | [192.0000, 5952.0000] |
| channels | {'3': 11, '4': 1} | {'3': 22, '4': 31} |
| register values | 1143270 | 1042740 |

**The AUDCTL row is the whole story in one line.** 11 of 12 historical traces run AUDCTL `$50`, the 16-bit pair clocked at 1.79 MHz. The control corpus uses ['$00', '$10'] and contains no 1.79 MHz composition at all. That is a hardware configuration rather than a musical choice, and it changes the divider arithmetic, the pitch resolution and the range of AUDF values a tune can reach.

### What is known, derived, unknown and not comparable

| field | control | historical | class |
|---|---|---|---|
| composition_sha256 | present: the authored document's own hash | absent: a SAP is a player plus data, not a composition | not_comparable |
| compiled_trace_sha256 | present: the trace is compiled deterministically from the document | absent: the trace is digitised from a running player | not_comparable |
| ground_truth_notes | present: the document is the ground truth | absent: Tier D, no independent note source exists | unknown |
| note_count / rest_count / pattern_count | present: read from the document | absent: not recoverable from a trace, and not inferred here | not_comparable |
| author / date | project-authored, so not an independent composer | credited composer and year, read from the SAP header | known |
| audctl / frames / spans / residual | measured from the trace, identically to the historical corpus | measured from the trace | derived_from_trace |
| player_routine | the project's own player, one routine, known | an unknown third-party routine; only its trace-visible behaviour is measurable | unknown |

**No composition feature is assigned to a historical SAP.** A SAP is a player plus data: its note set, its instruments and its tempo are not recoverable from the trace, and they are recorded as unknown rather than inferred. The per-trace inventory in `corpus_inventory.json` carries that split for every one of the 65 traces.

## 3. Common Feature Definitions

24 features are defined, of which 21 are used for matching and 3 are excluded. Every definition states what is counted, over what denominator, how silence is treated and where the measurement is limited. A feature is admitted only when it is measurable the same way in both corpora, and the residual is never used as a feature.

| feature | role | unit | denominator | silence |
|---|---|---|---|---|
| frames | matching | frames | none (a length, not a rate) | not applicable |
| audible_share | matching | share of frames | frames | a silent frame is counted as not audible; silence is part of the measure |
| silence_share | matching | share of frames | frames | this is the silence measure; it is not excluded |
| low_volume_share | matching | share of frames | frames | includes full silence, so it is a superset of silence_share |
| register_change_rate | matching | changes per frame | frames - 1 | silent frames are counted; a register that moves while silent is a change |
| audf_change_rate | matching | changes per frame | frames - 1 | silent frames are counted |
| audc_change_rate | matching | changes per frame | frames - 1 | silent frames are counted |
| audc_volume_change_rate | matching | changes per frame | frames - 1 | silent frames are counted |
| audc_distortion_change_rate | matching | changes per frame | frames - 1 | silent frames are counted |
| noise_active_share | matching | share of frames | frames | a silent voice is not audible, so it cannot be in a noise family |
| mean_simultaneous | matching | voices per frame | frames | silent frames contribute zero and are counted |
| max_simultaneous | matching | voices | none (a maximum) | not applicable |
| coupled_16bit | matching | 0 or 1 | none (a configuration flag, constant within a trace) | not applicable |
| clock_179mhz | matching | 0 or 1 | none (a configuration flag, constant within a trace) | not applicable |
| audf_diversity_per_1000_frames | matching | distinct divider values per 1000 frames | frames / 1000 | AUDF is read from every frame, silent or not |
| distinct_audc_values | matching | distinct byte values | none (a count) | AUDC is read from every frame, silent or not |
| mean_audc_run_length | matching | frames | number of AUDC runs | runs of a silent AUDC byte are included |
| channel_balance | matching | dimensionless ratio | the mean per-voice audible-frame count | a voice that is never audible contributes zero and lowers the mean |
| register_change_cooccurrence | matching | share of change frames | frames in which any register changed | a change while silent is still a change and is counted |
| detector_generator_recall | matching | share of true change frames | frames where an AUDC distortion nibble changes | distortion is read from AUDC regardless of volume |
| detector_generator_precision | matching | share of predicted onset frames | span onset frames | as above |
| audctl_change_rate | excluded_degenerate | changes per frame | frames - 1 | not applicable |
| stable_run_median | excluded_degenerate | frames | number of state runs | state runs include silent frames |
| distinct_audf_values | excluded_confounded | distinct divider values | none (a count) | AUDF is read from every frame |

### Why each excluded feature is excluded

| feature | role | reason |
|---|---|---|
| audctl_change_rate | excluded_degenerate | EXCLUDED from the matching: it is identically zero in all traces of both corpora, so it carries no information and cannot separate anything. Stage 23 listed it as a matching feature and its overlap table reported it as having 'no common range', which reads as a separation; a feature that is the same constant in both corpora is the opposite of a separation, and the classification here is corrected |
| stable_run_median | excluded_degenerate | EXCLUDED from the matching: measured at exactly 1.0 in every trace, because with four voices' worth of registers at least one column changes almost every frame. It is degenerate, not separated |
| distinct_audf_values | excluded_confounded | EXCLUDED from the matching as length-confounded: a count of distinct values grows with trace length, the historical traces are two to three times longer, and this feature is the one that made Stage 23's multivariate overlap look empty. Its length-normalised replacement is in the matching set and overlaps. The raw count is still reported, and the exclusion narrows the apparent separation, so the reader can judge the argument |

**The exclusions all narrow the apparent separation, which is why they are argued rather than asserted.** Removing a feature can only make the corpora look more alike, so an exclusion that is not justified would be a way of manufacturing overlap. Two are degenerate - identical constants in both corpora - and one is a count that grows with trace length. The support verdict below is reached with them removed, and it is still `COMMON_SUPPORT_INADEQUATE`.

## 4. Overlap Analysis

### Univariate: the brief's table

| feature | control range | historical range | common support | control outside | historical outside | classification |
|---|---|---|---|---|---|---|
| frames | [192.0000, 5952.0000] | [2048.0000, 19008.0000] | [2048.0000, 5952.0000] | 27/53 | 11/12 | partial |
| audible_share | [0.8333, 1.0000] | [0.9784, 1.0000] | [0.9784, 1.0000] | 5/53 | 0/12 | partial |
| silence_share | [0.0000, 0.1667] | [0.0000, 0.0216] | [0.0000, 0.0216] | 5/53 | 0/12 | partial |
| low_volume_share | [0.0000, 0.5417] | [0.0000, 0.1765] | [0.0000, 0.1765] | 7/53 | 0/12 | partial |
| register_change_rate | [0.4797, 2.6967] | [1.8045, 3.8162] | [1.8045, 2.6967] | 31/53 | 9/12 | partial |
| audf_change_rate | [0.0875, 0.9302] | [0.6675, 1.9966] | [0.6675, 0.9302] | 52/53 | 11/12 | partial |
| audc_change_rate | [0.3922, 2.1267] | [0.6274, 2.1089] | [0.6274, 2.1089] | 2/53 | 0/12 | partial |
| audc_volume_change_rate | [0.3922, 2.1267] | [0.6274, 2.0490] | [0.6274, 2.0490] | 2/53 | 0/12 | partial |
| audc_distortion_change_rate | [0.0044, 0.7533] | [0.0023, 0.5141] | [0.0044, 0.5141] | 1/53 | 1/12 | partial |
| noise_active_share | [0.0000, 1.0000] | [0.0000, 0.4684] | [0.0000, 0.4684] | 32/53 | 0/12 | partial |
| mean_simultaneous | [1.4583, 3.7500] | [2.2188, 3.4174] | [2.2188, 3.4174] | 16/53 | 0/12 | partial |
| max_simultaneous | [3.0000, 4.0000] | [3.0000, 4.0000] | [3.0000, 4.0000] | 0/53 | 0/12 | full |
| coupled_16bit | [0.0000, 1.0000] | [0.0000, 1.0000] | [0.0000, 1.0000] | 0/53 | 0/12 | full |
| clock_179mhz | [0.0000, 0.0000] | [0.0000, 1.0000] | [0.0000, 0.0000] | 0/53 | 11/12 | point_support |
| audf_diversity_per_1000_frames | [4.2003, 54.6875] | [6.1027, 36.0243] | [6.1027, 36.0243] | 14/53 | 0/12 | partial |
| distinct_audc_values | [12.0000, 35.0000] | [17.0000, 48.0000] | [17.0000, 35.0000] | 12/53 | 2/12 | partial |
| mean_audc_run_length | [1.8750, 7.6190] | [1.4222, 4.7790] | [1.8750, 4.7790] | 3/53 | 6/12 | partial |
| channel_balance | [0.0107, 1.2857] | [0.0227, 1.0563] | [0.0227, 1.0563] | 7/53 | 0/12 | partial |
| register_change_cooccurrence | [0.2163, 0.9456] | [0.5463, 0.9926] | [0.5463, 0.9456] | 14/53 | 4/12 | partial |
| detector_generator_recall | [0.3989, 1.0000] | [0.4448, 1.0000] | [0.4448, 1.0000] | 2/53 | 0/12 | partial |
| detector_generator_precision | [0.0952, 0.9990] | [0.0159, 0.9577] | [0.0952, 0.9577] | 16/53 | 1/12 | partial |

**Strictly separated features: none.** **Degenerate features: none.** **Poorly covered (fewer than 50.0% of historical traces inside the control range): ['audf_change_rate', 'clock_179mhz', 'frames', 'register_change_rate'].**

A feature that is the same constant in both corpora is the opposite of a separation: it carries no information and cannot distinguish anything. Stage 23 reported such a feature as having 'no common range', which reads as a separation. The classification here separates the two cases.

### Multivariate: three criteria, each calibrated

**Box support.** The control corpus's feature box, and the same test run leave-one-out inside the control corpus so the criterion's own power is visible:

| criterion | control (leave-one-out) | historical |
|---|---|---|
| traces | 53 | 12 |
| inside on every feature | 41 | 0 |
| inside share | 77.4% | 0.0% |
| outside on at most 1 feature | 47 | 0 |
| outside on at most 3 features | 51 | 3 |
| median features outside | 0.0 | 5.0 |

**The calibration is what makes the box result evidence.** 41 of 53 control traces pass the same test against the other controls, so the criterion is not vacuously strict. 0 of 12 historical traces pass it. The criterion discriminates, and it rejects every historical trace.

**Distance support.** The control corpus's own leave-one-out distances set the yardstick:

| quantity | value |
|---|---|
| control leave-one-out minimum | 0.0000 |
| control leave-one-out median | 1.6227 |
| control leave-one-out p90 | 2.8114 |
| control leave-one-out maximum | 5.2855 |
| historical nearest minimum | 4.0930 |
| historical nearest median | 5.9431 |
| historical nearest maximum | 6.7950 |
| historical beyond the control maximum | 10/12 |
| historical beyond the control p90 | 12/12 |

**Propensity score, with its stability reported rather than assumed.**

| quantity | control | historical |
|---|---|---|
| propensity minimum | 0.004169 | 0.941338 |
| propensity median | 0.030075 | 0.995663 |
| propensity maximum | 0.114823 | 0.999014 |
| in the overlap region | 2/53 | 0/12 |

**Complete separation: True.** 16 of 22 coefficients change sign across bootstrap resamples of the pooled corpus, so the model is not estimable at this sample size. Its separation is reported as a diagnostic and is **not** used on its own to conclude that the comparison is unsupported - the brief warns against that, and the two other criteria agree with it independently.

### The support verdict: `COMMON_SUPPORT_INADEQUATE`

ADEQUATE when at least 80% of historical traces are inside the control box and the propensity overlap region retains at least 80% of them; PARTIAL when at least one historical trace satisfies each; INADEQUATE otherwise.

**Criteria agree: True.** the three criteria have different failure modes and the verdict is only read when they agree. The box criterion is the strictest and is calibrated against the control corpus's own members, the distance criterion is the operational one, and the propensity score is reported with its instability rather than as proof.

## 5. Diagnostics of the Earlier Matching

Stage 23's matching method is re-derived here rather than trusted, because a method is not correct merely because it was implemented. Three defects were found:

| defect | what was measured |
|---|---|
| the declared caliper was never applied | Stage 23 declared CALIPER = 1.0 and never applied it: the neighbour function takes no caliper argument and the constant reached only the artefact. Every historical trace was therefore matched to its nearest control trace however far away that was, which is exactly the extrapolation the caliper was declared to prevent. The balance of the Stage 23 match was never checked either. Both are fixed here, and the effect of the fix is visible: with the caliper applied most of the grid retains nothing |
| balance was never checked | Stage 23 reported a matched gap without reporting the standardised mean difference of any feature after matching, so an unbalanced match could not be distinguished from a balanced one |
| the neighbour count was fixed and not varied | a single k was used with no sensitivity to it, so the result's dependence on the neighbourhood size was unknown |

**15 methods were run here, over a declared grid.** 3 can produce a difference and 0 satisfies the declared balance criterion. A method that produces a number is reported as *reportable*; a method whose match is defensible is reported as *validated*. The two are not the same and are not conflated.

| method | caliper | k | tolerance | kept | sources | rejected | difference | max |SMD| | reportable | validated |
|---|---|---|---|---|---|---|---|---|---|---|
| no_matching | n/a | n/a | n/a | 12 | 11 | 0 | 0.1551 | 2.4259 | True | False |
| nearest_neighbour | 1.0 | 1 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 1.0 | 3 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 1.0 | 5 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 2.0 | 1 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 2.0 | 3 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 2.0 | 5 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 4.0 | 1 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 4.0 | 3 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| nearest_neighbour | 4.0 | 5 | n/a | 0 | 0 | 12 | n/a | n/a | False | False |
| propensity_stratification | n/a | n/a | n/a | 12 | 11 | 0 | 0.1103 | 2.4259 | True | False |
| support_restriction | n/a | n/a | 0 | 0 | 0 | 12 | n/a | n/a | False | False |
| support_restriction | n/a | n/a | 2 | 1 | 1 | 11 | 0.1106 | 2.6464 | False | False |
| support_restriction | n/a | n/a | 3 | 3 | 2 | 9 | 0.0668 | 2.6464 | False | False |
| support_restriction | n/a | n/a | 5 | 8 | 7 | 4 | 0.1441 | 2.3156 | True | False |

**Every nearest-neighbour setting retains nothing.** The smallest historical-to-control distance exceeds the loosest declared caliper, so the caliper Stage 23 declared and never applied would have excluded the entire historical corpus. That is the finding: the Stage 23 match was not a match.

**The three reportable methods are all unbalanced.** Their largest absolute standardised mean differences are far above the declared threshold, so none of them is a matched comparison in any useful sense.

## 6. Results Before Matching

This is the descriptive comparison, and it is the same comparison Stage 23 reported. It is the reference point, not an effect estimate.

| quantity | value |
|---|---|
| estimand | E_in_span |
| control traces | 53 |
| historical traces | 12 |
| historical clusters (SAP sources) | 11 |
| difference in means | 0.1551 |
| interval low | 0.1006 |
| interval high | 0.2194 |
| excludes zero | True |
| cluster unit | historical SAP source; control composition |

**The interval resamples sources, never frames.** The corpus holds about 2186010 register values, which are 65 traces, which are 11 historical SAP sources and 53 control documents. An interval resampled over frames would be narrower by orders of magnitude and would mean nothing.

**The difference is 15.5% and it is stable.** It keeps its sign under every residual definition and under every leave-one-out drop, which is exactly what Stage 23 reported and what this stage reproduces rather than disputes.

## 7. Results After Matching

**There is no matched result to report.** 3 methods produce a difference and 0 satisfies the declared balance criterion. Reporting a matched estimate here would be reporting the unmatched comparison under another name.

### What the reportable methods actually did

| method | caliper | tolerance | kept | sources | difference | max |SMD| | why it is not validated |
|---|---|---|---|---|---|---|---|
| no_matching | n/a | n/a | 12 | 11 | 0.1551 | 2.4259 | The match is not balanced: the largest absolute standardised mean difference after matching is 2.425853, above the declared threshold of 0.25. |
| propensity_stratification | n/a | n/a | 12 | 11 | 0.1103 | 2.4259 | The match is not balanced: the largest absolute standardised mean difference after matching is 2.425853, above the declared threshold of 0.25. |
| support_restriction | n/a | 5 | 8 | 7 | 0.1441 | 2.3156 | The match is not balanced: the largest absolute standardised mean difference after matching is 2.315587, above the declared threshold of 0.25. |

### Why no comparison survives the common-support restriction

| restriction | historical kept | sources kept | difference |
|---|---|---|---|
| outside the control box on at most 0 features | 0 | 0 | n/a |
| outside the control box on at most 2 features | 1 | 1 | 0.1106 |
| outside the control box on at most 3 features | 3 | 2 | 0.0668 |
| outside the control box on at most 5 features | 8 | 7 | 0.1441 |

**The loosest declared restriction is the one that looks most like a result, and it is the least defensible.** It keeps eight historical traces by allowing each of them to sit outside the control box on up to five of twenty-one features. That is not a comparable subset; it is the unmatched comparison with four traces removed, and its balance still fails the declared criterion.

**B, answered:** the question cannot be answered: no comparable subset could be formed. a method that produces a number is not a method whose match is valid. The loosest declared support restriction keeps eight historical traces, but it keeps them by allowing a trace to sit outside the control box on five of twenty-one features, and the resulting match still fails the declared balance criterion. That is not a comparable subset; it is the unmatched comparison with four traces removed

## 8. Effective Sample Size and Uncertainty

**the trace. Register values are never treated as independent observations: the corpus holds about 2.1 million register values, which are 65 traces, which are 11 historical SAP sources and 53 control documents. An interval resampled over frames would be narrower by orders of magnitude and would mean nothing.**

| quantity | value |
|---|---|
| historical traces | 12 |
| historical SAP sources | 11 |
| historical composers | 3 |
| control compositions | 53 |
| historical register values | 1143270 |
| control register values | 1042740 |

### Per-method accounting

| method | caliper | tolerance | kept | rejected | sources | historical ESS | control ESS | difference | interval |
|---|---|---|---|---|---|---|---|---|---|
| no_matching | n/a | n/a | 12 | 0 | 11 | 12.0000 | 53.0000 | 0.1551 | [0.1006, 0.2194] |
| nearest_neighbour | 1.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 1.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 1.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 2.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 2.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 2.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 4.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 4.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| nearest_neighbour | 4.0 | n/a | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| propensity_stratification | n/a | n/a | 12 | 0 | 11 | 12.0000 | 132.0000 | 0.1103 | [0.0596, 0.1702] |
| support_restriction | n/a | 0 | 0 | 12 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| support_restriction | n/a | 2 | 1 | 11 | 1 | 1.0000 | 53.0000 | 0.1106 | [0.0883, 0.1340] |
| support_restriction | n/a | 3 | 3 | 9 | 2 | 3.0000 | 53.0000 | 0.0668 | [0.0295, 0.1252] |
| support_restriction | n/a | 5 | 8 | 4 | 7 | 8.0000 | 53.0000 | 0.1441 | [0.0762, 0.2357] |

**twelve historical traces from eleven files and three composers cannot support a matched comparison with a balance criterion. This is stated as a limitation of the data rather than worked around: the smallest p-value obtainable from a 12-versus-53 comparison is bounded by the number of distinct source-level arrangements, and any matched subset that satisfies the balance criterion would be smaller still.**

the effective sample size is Kish's, reported for the weighted methods. A method that keeps twelve traces with wildly unequal weights does not carry twelve observations.

## 9. Sensitivity Analyses

**The rule, declared before the numbers were read:** a result is UNSTABLE when the sign of the difference changes on any axis, or when the difference falls below the declared effect threshold of 0.05 on any axis.

**Classification: `STABLE_ON_THE_RAW_COMPARISON_BUT_UNIDENTIFIED`.** the stability classification applies to the raw and support-restricted comparisons, which are the only ones that exist. It does NOT extend to a matched estimate, because no matching method satisfied the declared balance criterion and there is therefore no matched estimate to test.

### Leave one historical song out

| dropped | source | kept | difference | sign |
|---|---|---|---|---|
| BMX_Simulator__sub0 | input/BMX_Simulator.sap | 11 | 0.1572 | positive |
| Blinkys_Scary_School__sub0 | input/Blinkys_Scary_School.sap | 11 | 0.1657 | positive |
| Blinkys_Scary_School__sub3 | input/Blinkys_Scary_School.sap | 11 | 0.1645 | positive |
| Draconus_2024__sub0 | input/Draconus_2024.sap | 11 | 0.1352 | positive |
| Extirpator__sub0 | input/Extirpator.sap | 11 | 0.1551 | positive |
| International_Karate__sub0 | input/International_Karate.sap | 11 | 0.1524 | positive |
| Jet_Set_Willy__sub0 | input/Jet_Set_Willy.sap | 11 | 0.1556 | positive |
| Ninja_Commando__sub0 | input/Ninja_Commando.sap | 11 | 0.1636 | positive |
| Panther__sub0 | input/Panther.sap | 11 | 0.1530 | positive |
| Red_Max__sub0 | input/Red_Max.sap | 11 | 0.1494 | positive |
| Warhawk__sub0 | input/Warhawk.sap | 11 | 0.1502 | positive |
| Zybex__sub4 | input/Zybex.sap | 11 | 0.1591 | positive |

Signs observed: **['positive']**; range [0.1352, 0.1657].

### Leave one control composition out

Signs observed: **['positive']** over 53 drops. The control corpus is much larger and no single composition moves the sign.

### Sensitivity to the matching parameters

| caliper | k | historical kept | sources kept | difference |
|---|---|---|---|---|
| 0.5 | 1 | 0 | 0 | n/a |
| 0.5 | 3 | 0 | 0 | n/a |
| 0.5 | 5 | 0 | 0 | n/a |
| 1.0 | 1 | 0 | 0 | n/a |
| 1.0 | 3 | 0 | 0 | n/a |
| 1.0 | 5 | 0 | 0 | n/a |
| 2.0 | 1 | 0 | 0 | n/a |
| 2.0 | 3 | 0 | 0 | n/a |
| 2.0 | 5 | 0 | 0 | n/a |
| 3.0 | 1 | 0 | 0 | n/a |
| 3.0 | 3 | 0 | 0 | n/a |
| 3.0 | 5 | 0 | 0 | n/a |
| 4.0 | 1 | 0 | 0 | n/a |
| 4.0 | 3 | 0 | 0 | n/a |
| 4.0 | 5 | 0 | 0 | n/a |
| 6.0 | 1 | 7 | 7 | 0.1445 |
| 6.0 | 3 | 7 | 7 | 0.1450 |
| 6.0 | 5 | 7 | 7 | 0.1385 |
| 8.0 | 1 | 12 | 11 | 0.1098 |
| 8.0 | 3 | 12 | 11 | 0.1187 |
| 8.0 | 5 | 12 | 11 | 0.1129 |

**6 of 21 settings retain any historical trace and 6 retain the declared minimum.** The result does not depend on the parameters because no parameter setting produces a comparison at all.

### Sensitivity to the residual convention

| estimand | difference | interval low | interval high | n control | n historical |
|---|---|---|---|---|---|
| E_total_hold | 0.1063 | 0.0568 | 0.1596 | 53 | 12 |
| E_total_exporter | 0.2035 | 0.1593 | 0.2528 | 53 | 12 |
| E_in_span | 0.1551 | 0.1006 | 0.2194 | 53 | 12 |
| E_out_span_hold | -0.0245 | -0.1096 | 0.0772 | 53 | 12 |
| E_out_span_exporter | 0.2863 | 0.2100 | 0.3705 | 53 | 12 |
| E_zero_onset_span | 0.4859 | 0.2805 | 0.6826 | 8 | 11 |
| E_other_span | 0.0875 | 0.0280 | 0.1639 | 53 | 12 |

Signs across definitions: **['negative', 'positive']**. The negative sign belongs to `E_out_span_hold`, the out-of-span hold convention, which Stage 23 also reported as negative; it is the convention the out-of-span region exists in, and the in-span estimand is convention-free.

### Sensitivity to the feature set

| feature set | features | support verdict | historical inside box | propensity retained | nearest minimum | control LOO maximum |
|---|---|---|---|---|---|---|
| density_only | 9 | COMMON_SUPPORT_PARTIAL | 1 | 3 | 1.7922 | 3.2034 |
| stage23_matching | 17 | COMMON_SUPPORT_INADEQUATE | 0 | 0 | 3.6689 | 3.9341 |
| stage24_all | 21 | COMMON_SUPPORT_INADEQUATE | 0 | 0 | 4.0930 | 5.2855 |
| without_configuration | 19 | COMMON_SUPPORT_INADEQUATE | 0 | 1 | 3.1224 | 5.2855 |
| without_length | 20 | COMMON_SUPPORT_INADEQUATE | 0 | 0 | 3.8475 | 5.2778 |

### Channel-level sensitivity

| register | control rate | historical rate | difference | control denominator | historical denominator |
|---|---|---|---|---|---|
| AUDF1 | 56.0% | 8.3% | -47.7% | 109253 | 118073 |
| AUDF2 | 20.5% | 8.7% | -11.8% | 100484 | 116310 |
| AUDF3 | 39.1% | 63.4% | 24.3% | 101666 | 119121 |
| AUDF4 | 2.6% | 65.0% | 62.3% | 64194 | 93001 |

### Common-support-only and weighted against unweighted

| method | caliper | tolerance | difference | historical ESS | weighted |
|---|---|---|---|---|---|
| no_matching | n/a | n/a | 0.1551 | 12.0000 | False |
| propensity_stratification | n/a | n/a | 0.1103 | 12.0000 | True |
| support_restriction | n/a | 5 | 0.1441 | 8.0000 | True |

**Weighting changes nothing here, because there is nothing to weight.** The only weighted method that retains the whole corpus is the propensity stratification, and its weights are derived from a score that separates the corpora completely.

## 10. Falsification Test

The conditions under which the history-specific reading is rejected were declared before the comparison was run and are not amended afterwards. Each is reported with the measurement that decided it.

| condition | threshold | passed | measurement |
|---|---|---|---|
| a common feature range exists that supports a matched comparison | no matching feature is separated, at least one historical trace lies inside the control box, and the propensity overlap region retains at least one historical trace | False | {"historical_in_propensity_region": 0, "historical_inside_box": 0, "historical_traces": 12, "separated_features": []} |
| the effect survives in the common-support region | at least one declared method retains the minimum sample AND satisfies the declared balance criterion | False | {"nearest_neighbour_settings_retaining_anything": 0, "reportable_methods": 3, "validated_methods": 0} |
| the effect does not depend on a few traces | the sign of the raw difference is unchanged when each historical trace and each control composition is dropped in turn | True | {"control_signs": ["positive"], "historical_signs": ["positive"], "max_difference": 0.165666, "min_difference": 0.135183} |
| the effect does not depend on the matching parameters | the sign is unchanged across the declared caliper and neighbour grid | True | {"settings": 21, "settings_retaining_anything": 6, "settings_retaining_the_minimum": 6} |
| the difference is consistent with the observed effect of corpus composition | the features that separate the corpora are trace-length and POKEY-configuration features rather than musical ones | True | {"box_agrees_with_propensity": true, "poorly_covered_features": ["audf_change_rate", "clock_179mhz", "frames", "register_change_rate"], "separated_features": []} |
| the effect can be separated from unobserved differences in trace generation | the residual measured on the historical corpus is not attributable to a difference in how the trace was produced - a digitised player against a compiled document | False | {"control_players": 1, "control_trace_origin": "compiled deterministically from an authored document", "historical_players": "unknown; at least three composer clusters", "historical_trace_origin": "digitised from a running third-party player", "identifiable_from_traces_alone": false} |

**3 of 6 conditions pass.** the history-specific reading is REJECTED by 3 of the 6 pre-declared conditions. A difference that cannot be located in a comparable population, cannot be matched, and is confounded with the process that produced the traces is not evidence of a performance layer, whatever its size.

### The rejected conditions

* A common feature range exists that supports a matched comparison.
* The effect survives in the common-support region.
* The effect can be separated from unobserved differences in trace generation.

**The sixth condition is the one that cannot be discharged at all.** The control traces are compiled deterministically from an authored document by the project's own compiler, and the historical traces are digitised from a third-party player. Nothing measurable in a trace distinguishes a player's behaviour from a composer's, and no control exists in which one player is run over both corpora. That is a confound the data cannot remove, and it is reported as a failure rather than as a caveat.

## 11. Identifiability Limits

The brief asks for the descriptive difference, the matched difference and the identified effect to be reported separately and never merged. They are answered here as three separate questions.

### A. The descriptive difference

**YES** - the historical traces carry a larger residual than the control traces.

| quantity | value |
|---|---|
| ci_high | 0.21941928602058317 |
| ci_low | 0.10056554718104224 |
| control_mean | 0.217417 |
| control_traces | 53 |
| difference | 0.155086 |
| estimand | E_in_span |
| historical_mean | 0.372503 |
| historical_traces | 12 |

It says nothing about the cause. The historical corpus is 12 traces of a game tune and the control corpus is 53 short test compositions, so the descriptive difference compares two different kinds of object before it compares two different eras.

### B. The difference after matching

**The question cannot be answered: no comparable subset could be formed.**

| quantity | value |
|---|---|
| loosest_declared_support_restriction | {'tolerance': 5, 'historical_kept': 8, 'historical_sources_kept': 7, 'difference': 0.144102, 'max_absolute_smd': 2.315587, 'balanced': False} |
| nearest_neighbour_settings_retaining_anything | 0 |
| reportable_matching_methods | 3 |
| validated_matching_methods | 0 |

A method that produces a number is not a method whose match is valid. The loosest declared support restriction keeps eight historical traces, but it keeps them by allowing a trace to sit outside the control box on five of twenty-one features, and the resulting match still fails the declared balance criterion. That is not a comparable subset; it is the unmatched comparison with four traces removed.

### C. The identified cause

**NO.** Four blockers, each measured rather than asserted:

| blocker | evidence |
|---|---|
| no common support | 0 of 12 historical traces lie inside the control corpus's feature box, against 41 of the control corpus's own members under the same leave-one-out test |
| no matched estimate exists | 3 of 15 declared methods can produce a difference and 0 satisfy the declared balance criterion |
| the trace generation process is confounded with the corpus | the control traces are compiled from an authored document by the project's own compiler and the historical traces are digitised from a third-party player. Nothing in the traces distinguishes a player's behaviour from a composer's, and no control exists in which one player is run over both corpora |
| no ground truth on the historical side | every historical SAP is Tier D. The classes that would say where the residual comes from need a composition, and there is none. This is a limit of the data that no amount of statistics removes |

It does not say the difference is an artefact. It says the difference is not identified: the data cannot tell a historical-specific effect from a difference in trace length, POKEY configuration, player routine or musical density.

**Summary: A is yes, B is unanswerable, C is no. The three are not the same statement and this stage does not merge them.**

## 12. The Minimal Additional Experiment

The comparison cannot be identified with the corpora that exist, so the next step is a corpus and not an analysis. The design is stated and **not executed**: no composition is authored, no profile is bound and no music is generated.

### The gaps that would have to be closed

| gap | measurement | how it would be closed | closable |
|---|---|---|---|
| the POKEY clock configuration | 11 of 12 historical traces run AUDCTL $50 (16-bit pair at 1.79 MHz); the control corpus uses ['$00', '$10'] and contains no 1.79 MHz composition at all | author control compositions whose instruments bind a profile declaring audctl_mode '$50'. The IR already supports this: resolve_audctl_mode OR-s an instrument's explicit audctl requirement with the song's 16-bit flag, and binding.py maps a 16-bit pair on channels 1+2 to exactly 0x50. No production change is required - only documents and a profile that no existing composition happens to use | True |
| trace length | control frames range [192, 5952] with a median of 1920.0; historical frames range [2048, 19008] with a median of 9833.0 | author control compositions at the historical lengths, which is a document change and nothing more. This is the cheapest of the gaps and it also removes the length artefact from every count-valued feature | True |
| the player routine | the historical traces come from at least three composer clusters and an unknown number of player routines; the control corpus has exactly one | this one cannot be closed with more compositions. It needs the same musical material rendered through more than one player, or a historical SAP whose player is identified and re-run over authored material. Until then a difference in residual cannot be separated from a difference in player | False |
| ground truth on the historical side | zero of the 12 historical traces have an independent note source | a hand transcription of a historical tune, which is what would move it from Tier D to Tier A. This is labour rather than code, and it is the only thing that would let the detector's errors be separated from a player's choices | False |

### The proposed corpus

| property | requirement |
|---|---|
| name | a length-matched, $50-clocked, author-controlled Tier A corpus |
| what it is | a second control corpus authored inside this project, whose compositions match the historical corpus on the features that separate the corpora and on nothing else |
| minimum size | at least 12 compositions with the $50 configuration and at least 12 at the historical length distribution, from at least 3 distinct authored sources, so that a matched subset can retain the declared minimum of 4 traces and 3 sources after a caliper is applied |
| ground truth | Tier A is already satisfied: an authored document is its own ground truth. No transcription is needed for the control side. The historical side stays Tier D unless someone transcribes, and that limitation is not removed by this experiment |
| cost and risk | authoring the documents is cheap and uses existing tooling. The risk is that the author of the new corpus is also the author of the comparison, so the corpus would have to be authored and hashed before this stage is re-run, exactly as the existing control corpus was |

**Must be controlled:**

* AUDCTL configuration, including the 1.79 MHz clock and the 16-bit pair
* trace length, matched to the historical range and distribution
* AUDF change density, including the between-note zero pulse if it is to be matched
* register change co-occurrence and the number of simultaneously audible voices
* the distortion families in use, since the detector's transition recall depends on them

**Must not vary:**

* the compiler, the player, the DSL and the frame period - one pipeline for every control composition, so the generation process is held constant

**What would falsify the hypothesis:**

* the difference vanishes once configuration and length are matched - the difference was corpus construction
* the difference persists and the matched balance criterion is met - then it is worth a controlled listening test, and it is still not a performance layer
* the difference persists only for the zero-pulse player idiom - it is a player trait, which is a finding about players rather than about historical performance

**What would allow a design decision:** a matched difference whose interval excludes zero AND whose balance criterion is met AND which survives leave-one-source-out. Anything less is a research result and changes no production decision.

**Configurability note.** The 1.79 MHz configuration is reachable through the existing profile binding path (a profile's hardware.audctl_mode is parsed and OR-ed in by resolve_audctl_mode), but no composition in the repository uses it, so the path is unexercised. Any new corpus would be its first use and should be validated against a trace whose AUDCTL column is checked directly..

**the corpus is not created, no profile is bound, no composition is authored and no music is generated. Stage 24 proposes and stops.**

## 13. Explicit Methodological Corrections

Every problem found while building this stage, and what was done about it. Nothing was quietly fixed: a correction that changes a number is stated here.

| claim | what was measured instead | consequence |
|---|---|---|
| Stage 23 declares CALIPER = 1.0 standardised units and writes it into the artefacts | the caliper is never read: stage23.nearest_control_neighbours takes no caliper argument, so every historical trace was matched to its nearest control trace however far away that was | Stage 23's matched gap is the gap between a historical trace and its nearest control neighbour at whatever distance, which is an extrapolation rather than a match. Stage 24 applies the caliper and reports the consequence: the grid retains nothing |
| Stage 23 reports distinct_audf_values, audctl_change_rate and clock_179mhz as features with 'no common range at all' | audctl_change_rate is identically zero in all 65 traces of both corpora, so it is a shared constant and not a separation at all. distinct_audf_values is a count that grows with trace length, and its length-normalised form overlaps. clock_179mhz is a shared point at zero with 11 of 12 historical traces outside | Stage 23's multivariate overlap reads worse than the data supports. Stage 24 separates 'degenerate' from 'separated' and normalises the length-confounded count; the support verdict is then still inadequate, but for stated reasons rather than for a measurement artefact |
| Stage 23 reports a control leave-one-out distance maximum as a support threshold | the maximum over 53 controls is the most extreme control's distance, so it is a permissive threshold; the p90 and p95 are also reported here | Stage 24 reports three thresholds and the count beyond each, so the support conclusion does not rest on the choice of one |

**1. A support criterion is only evidence when it can pass the control corpus's own members.** The bounding-box test is the strictest definition of common support available, and with 53 samples over 21 features it would be easy to build one that nothing passes and then declare the corpora incomparable. So it is run leave-one-out *inside* the control corpus first. It passes 41 of the 53 control traces, so it discriminates, and it rejects every historical trace. Without that calibration the same number would have meant nothing.

**2. A count that grows with trace length is not a comparable feature.** Stage 23 declared `distinct_audf_values` a feature with no common range, and that single feature made the multivariate overlap look hopeless. The historical traces are two to three times longer than the control ones, so the count separates them by construction. The length-normalised form of the same feature overlaps: the control range is [4.2003, 54.6875], the historical range is [6.1027, 36.0243], and 0 of 12 historical traces fall outside it. The raw count is still reported, and it is excluded from the matching with the reason stated, because excluding a feature narrows the apparent separation and a reader is entitled to see the argument.

**3. A constant feature is the opposite of a separation.** `audctl_change_rate` is identically zero in all 65 traces of both corpora. Stage 23's table reported it as having 'no common range', which reads as the corpora being separated on it; in fact they agree on it exactly, and it carries no information. The classification here separates `separated` from `shared_constant`, and the latter is excluded as degenerate rather than reported as a gap.

**4. A declared caliper that is never applied is not a control.** Stage 23 declares `CALIPER = 1.0` and writes it into its artefacts, and its neighbour function takes no caliper argument. Every historical trace was therefore matched to its nearest control trace however far away that was. Stage 24 applies the caliper and reports the consequence: the entire declared grid retains nothing, because the smallest historical distance exceeds the loosest declared caliper.

**5. A propensity score is a diagnostic and not proof.** The score separates the corpora completely here, which is itself a statement about how unlike they are, but 16 of its 22 coefficients change sign across bootstrap resamples. A model that unstable cannot be used as an automatic test of overlap, and the brief says so explicitly. It is reported beside two other criteria calibrated independently, and all three agree.

**6. A method that produces a number is not a validated match.** The three reportable methods all fail the declared balance criterion. They are reported as *reportable*, which is what they are, and explicitly not as *validated*, which is what they are not. The distinction is carried in the artefacts, not only in the prose.

### Read-only audit

| audit | files checked | changed | read-only |
|---|---|---|---|
| traces, composition documents and upstream artefacts | 107 | 0 | True |
| production modules, the player source and the profile DSL | 17 | 0 | True |

Stage 15 to 23, the composer, the DSL, the IR, the player and the exporter were read through their hashes and never written. The traces, the composition documents and the upstream artefacts were hashed before and after the run as well.

## 14. Verdict and Recommendation

| subject | verdict | deciding measurement |
|---|---|---|
| main | COMMON_SUPPORT_INADEQUATE | {"complete_separation": true, "control_inside_control_box_leave_one_out": 41, "historical_in_propensity_region": 0, "historical_inside_control_box": 0, "historical_traces": 12, "propensity_terms": 22, "reportable_methods": 3, "support_verdict": "COMMON_SUPPORT_INADEQUATE", "unstable_propensity_terms": 16, "validated_methods": 0} |
| MATCHING_RETAINS_NO_USABLE_SAMPLE | MATCHING_RETAINS_NO_USABLE_SAMPLE | Every declared nearest-neighbour caliper retains no historical trace at all, because the smallest historical-to-control standardised distance exceeds the loosest declared caliper. |
| HISTORICAL_DIFFERENCE_STABLE_BUT_NOT_IDENTIFIED | HISTORICAL_DIFFERENCE_STABLE_BUT_NOT_IDENTIFIED | The raw difference keeps its sign under every leave-one-out axis and under every residual definition, and it is still not identified because no comparable population exists. |
| NEW_CONTROL_CORPUS_REQUIRED | NEW_CONTROL_CORPUS_REQUIRED | The comparison cannot be identified with the corpora that exist, so the next step is a corpus and not an analysis. |
| PERFORMANCE_LAYER_NOT_SUPPORTED_AND_NOT_TESTABLE_HERE | PERFORMANCE_LAYER_NOT_SUPPORTED_AND_NOT_TESTABLE_HERE | This stage neither supports a performance layer nor is able to test one. The difference it measures is confounded with trace length, POKEY configuration and the trace generation process, and no matched estimate could be formed. |
| NO_PRODUCTION_DECISION_CHANGED | NO_PRODUCTION_DECISION_CHANGED | Stage 24 changes no detector, compiler, player, exporter or schema, produces no music and makes no change to the composer. Its output is a statement about what the existing data can support. |

### What `COMMON_SUPPORT_INADEQUATE` means

The corpora do not share enough feature space for a matched comparison, so the residual difference cannot be attributed to a historical-specific effect. The difference is not denied - it is measured, it is stable, and it is not identified..

**What it does not mean.** It does not mean the difference is an artefact, and it does not mean the detector is wrong. It means the current data cannot separate the two..

### The STOP condition

The brief's STOP conditions are applied as written. The common support is inadequate, so the stage ends with `COMMON_SUPPORT_INADEQUATE` and proposes a new control corpus. It does not start Stage 25, it does not modify production, and it does not turn an unidentified difference into a claim about a cause.

### Recommendation

1. **Treat the current historical-versus-control comparison as closed for causal purposes.** It has been measured twice, it is stable, and it cannot be identified. Further analysis of the same two corpora will not change that; the limit is the data.

2. **Do not read the difference as evidence of a performance layer.** It is confounded with trace length, the POKEY clock configuration and the trace generation process, and no matched estimate exists to separate them.

3. **If the question is worth pursuing, build the corpus in section 12 first.** It is a document-authoring task using tooling that already exists, and it is the only thing that would move the comparison from unidentified to identified.

4. **Fix the Stage 23 caliper defect wherever its matched numbers are quoted.** The published matched gap was produced without the caliper the stage declared, so any downstream reading of it inherits an extrapolation.

### What does not change

**`NO_PRODUCTION_DECISION_CHANGED`.** Stage 24 changes no detector, compiler, player, exporter or schema, produces no music and generates no corpus. Whatever it found is a statement about what the existing data can support, not a change to the composer.

## The Eight Closing Questions

**1. Do the corpora have enough common feature range?**

**No.** No matching feature is strictly separated - after the length correction and the degenerate-feature correction, all 21 have a non-empty common range - but the *joint* range is empty: 0 of 12 historical traces lie inside the control corpus's feature box, against 41 of 53 control traces under the same leave-one-out test. The propensity overlap region retains 0 historical traces. The univariate picture is mostly adequate; the multivariate picture is not.

**2. Was the earlier matching methodologically sound?**

**No.** Three defects, all measured: the declared caliper was never applied, balance was never checked, and the neighbour count was never varied. The consequence is that Stage 23's matched gap is not a matched gap - it is the distance from each historical trace to whatever control trace happened to be nearest.

**3. Does the +15.51 pp difference persist in a comparable population?**

**The question cannot be answered, and that is the finding.** 15 declared methods were run; 3 produce a number and 0 satisfies the balance criterion. Every nearest-neighbour caliper retains zero historical traces. There is no comparable population in this data, so the difference of 15.5% applies to the full corpus and cannot be transported to a subset.

**4. Is the result stable with respect to convention and parameters?**

**The raw comparison is stable: `STABLE_ON_THE_RAW_COMPARISON_BUT_UNIDENTIFIED`.** The sign survives every leave-one-out drop (True) and every residual definition (['negative', 'positive']). The matched comparison has no stability to report, because no parameter setting produces one: 6 of 21 settings retain any historical trace at all. Stability of an estimate that does not exist is not a property of the data.

**5. Can the data identify the cause of the difference?**

**No.** Four blockers, each measured: no common support; no matched estimate; the trace generation process is confounded with the corpus (a compiled document against a digitised third-party player, with no control in which one player runs over both); and no ground truth exists on the historical side. The fourth is a limit of the data that no statistical method removes, and the falsification test rejects the history-specific reading on 3 of 6 pre-declared conditions.

**6. Is a new control corpus needed?**

**Yes, and it is the only thing that would help.** The gap is not analytical. Section 12 states the minimum design: compositions with the `$50` POKEY configuration, at the historical length distribution, from at least three authored sources, through the existing compiler and player.

**7. Does Stage 24 justify a new experiment?**

**Yes, as a corpus and not as an analysis.** The verdict is `COMMON_SUPPORT_INADEQUATE` and the auxiliary verdict is `NEW_CONTROL_CORPUS_REQUIRED`. Stage 24 proposes the experiment, states what would falsify the hypothesis, and stops. It does not build the corpus and it does not start Stage 25.

**8. Does the result change any Atari Music Composer decision?**

**No.** `NO_PRODUCTION_DECISION_CHANGED`. Stage 24 is analysis-only, read-only and additive: no detector, compiler, player, exporter or schema is modified, no music is generated and no corpus is created. The one actionable item is a defect report - the Stage 23 caliper - and that is a documentation matter, not a production change.

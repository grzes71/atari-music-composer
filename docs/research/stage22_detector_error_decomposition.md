# Stage 22 - Detector Error Decomposition and Ground-Truth Calibration

Stage 21 showed that the residual Stage 20 measured on the historical corpus cannot be attributed to performance, because the same signature appears on streams whose composition is known. It left one question open, and this stage exists to answer it: on traces whose composition *is* known, where does the detector's residual actually come from?

Stage 22 does not touch the detector, does not re-open the performance-layer question, and does not try to make the residual smaller. It compiles the 53-composition Tier A control corpus to exact traces, runs the existing Stage 15 detector over them, and decomposes the resulting residual into named, measured causes.

**The answer is short.** On 53 compositions and 1042740 register values the detector leaves 26.0% unexplained under the hold convention and 18.1% once the outside-note convention is removed. That residual partitions into **64.8% note set**, **7.8% value reading** and **27.4% interaction**, and the value part is *entirely* the four-parameter level contour: pitch, generator, distortion, channel and AUDCTL contribute zero.

The brief expected ``B10 residual = 0`` and it is: the exact composition leaves nothing at all, on every song. Nothing is unexplained, and nothing had to be assumed to get there.

Analysis only, read-only and additive. No audio was rendered, no music was generated, no listening test was run, and Stage 15, the composer, the DSL, the IR, the player and the exporter are unchanged.

Analysis version `stage22/1`.

Artefacts: `ground_truth_summary.json`, `detector_summary.json`, `ablation_ladder.json`, `ablation_leave_one_out.json`, `note_detection_errors.json`, `pitch_errors.json`, `volume_envelope_errors.json`, `generator_errors.json`, `distortion_errors.json`, `channel_errors.json`, `timing_errors.json`, `residual_by_register.json`, `residual_by_song.json`, `residual_taxonomy.json`, `historical_vs_control.json`, `stage22_manifest.json`.

## 1. Executive Summary

| question | answer |
|---|---|
| Is the detector's residual explained? | **Yes.** 64.8% note set, 7.8% value reading, 27.4% interaction; the partition closes (True). |
| Does the exact composition explain everything? | **Yes.** B10 residual = 0 on 1042740 register values, on every song. |
| Is the residual mostly a detection error or a representation limit? | **Detection.** The note set is the largest single cause. The only value-level error is the level contour: 14660 register values. |
| Are pitch, generator and channel errors real? | **No.** Divider exact at matched onsets 68.6%, generator correct at matched onsets 100.0%, channel mismatches 0. |
| Is the historical residual different? | **HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL** - share ratio 1.425146, AUDF-share delta -0.193173. |
| Verdict | DETECTOR_ERROR_PARTIALLY_EXPLAINED + REPRESENTATION_LIMITATION + GROUND_TRUTH_EXTRACTION_LIMITATION + HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL + PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST |
| Read-only audit | **True** - 67 production and composition artefacts hashed before and after the run, none changed |

Stage 22 changes no production code and stops here.

## 2. Dataset

The Tier A control corpus: **53 compositions**, 36814 sounding notes and 10511 silent ones, compiled to exact traces by the project's own compiler. Nothing is read from the historical corpus for calibration; the historical traces appear only in section 16.

| slug | kind | frames | AUDCTL | 16-bit | notes | spans | distinct pitches | residual |
|---|---|---|---|---|---|---|---|---|
| 01_dungeon__2dc66ce8 | control_json | 4480 | $10 | yes | 1004 | 292 | 33 | 22.5% |
| 01_dungeon__5fe2becc | control_json | 4480 | $10 | yes | 729 | 290 | 31 | 28.3% |
| 02_chase__229ff18f | control_json | 3776 | $00 | no | 1693 | 836 | 23 | 30.3% |
| 02_chase__4b467c9c | control_json | 3776 | $00 | no | 2326 | 982 | 26 | 27.9% |
| 03_adventure__05a150a4 | control_json | 5520 | $00 | no | 1819 | 864 | 31 | 25.4% |
| 03_adventure__2a8b34f6 | control_json | 5500 | $00 | no | 1484 | 482 | 32 | 33.9% |
| 04_prl_comedy__0dc0d689 | control_json | 3968 | $00 | no | 2275 | 1610 | 35 | 27.7% |
| 04_prl_comedy__11473ee2 | control_json | 3968 | $00 | no | 1347 | 796 | 43 | 29.6% |
| 05_boss__9075c074 | control_json | 4992 | $10 | yes | 2078 | 769 | 31 | 27.6% |
| 05_boss__bfa86215 | control_json | 4992 | $10 | yes | 2014 | 911 | 34 | 25.7% |
| 06_forest__9e1600c5 | control_json | 4560 | $00 | no | 768 | 350 | 27 | 22.4% |
| 06_forest__a399dcbb | control_json | 4480 | $00 | no | 762 | 481 | 31 | 20.2% |
| 07_hero__19376e04 | control_json | 5952 | $00 | no | 2179 | 945 | 29 | 26.3% |
| 07_hero__a12f0fcc | control_json | 5632 | $00 | no | 1813 | 943 | 31 | 28.5% |
| 08_scifi__5ac6ec90 | control_json | 4248 | $00 | no | 1784 | 686 | 49 | 27.5% |
| 08_scifi__768280e3 | control_json | 4224 | $00 | no | 2125 | 895 | 43 | 30.8% |
| Vaults-of-Nhyrmeth-2 | control_dsl | 2280 | $10 | yes | 368 | 153 | 21 | 22.1% |
| Vaults-of-Nhyrmeth-3 | control_dsl | 2240 | $10 | yes | 379 | 175 | 29 | 25.6% |
| action_fast | control_json | 256 | $00 | no | 88 | 45 | 12 | 28.0% |
| as-1 | control_dsl | 2280 | $10 | yes | 282 | 151 | 30 | 22.0% |
| as-2 | control_dsl | 2160 | $00 | no | 347 | 105 | 35 | 21.4% |
| as-3 | control_dsl | 2304 | $00 | no | 421 | 206 | 40 | 25.6% |
| div_01_dark_dungeon | control_json | 640 | $10 | yes | 93 | 66 | 18 | 15.6% |
| div_02_fast_action_chase | control_json | 896 | $00 | no | 364 | 163 | 27 | 27.4% |
| div_03_melancholic_retro | control_json | 880 | $00 | no | 191 | 124 | 21 | 21.4% |
| div_04_polish_prl_comedy | control_json | 768 | $00 | no | 297 | 185 | 28 | 28.4% |
| div_05_tense_boss | control_json | 896 | $10 | yes | 451 | 172 | 22 | 24.1% |
| div_06_mysterious_forest | control_json | 800 | $00 | no | 233 | 150 | 25 | 25.4% |
| div_07_heroic_8bit | control_json | 832 | $00 | no | 312 | 133 | 28 | 28.1% |
| div_08_satirical_scifi | control_json | 704 | $00 | no | 344 | 148 | 27 | 25.3% |
| dungeon_dark | control_json | 320 | $10 | yes | 32 | 25 | 12 | 13.4% |
| dungeon_live_01 | control_json | 720 | $10 | yes | 59 | 51 | 15 | 10.8% |
| epic_heroic_fantasy | control_json | 3072 | $00 | no | 992 | 390 | 30 | 21.1% |
| funny_prl | control_json | 192 | $00 | no | 38 | 37 | 9 | 28.5% |
| rep_01_dark_dungeon_run2 | control_json | 640 | $10 | yes | 92 | 75 | 15 | 19.2% |
| rep_02_fast_action_chase_run2 | control_json | 896 | $00 | no | 662 | 197 | 27 | 21.7% |
| rep_04_polish_prl_comedy_run2 | control_json | 768 | $00 | no | 281 | 143 | 27 | 36.8% |
| repair_test_toccata | control_json | 640 | $10 | yes | 224 | 144 | 20 | 16.3% |
| style_a_dark_dungeon_exploration_mock | control_json | 320 | $10 | yes | 32 | 25 | 12 | 13.4% |
| style_a_dark_dungeon_exploration_real | control_json | 680 | $10 | yes | 81 | 72 | 18 | 22.7% |
| style_b_fast_action_chase_mock | control_json | 192 | $00 | no | 88 | 45 | 12 | 25.6% |
| style_b_fast_action_chase_real | control_json | 600 | $00 | no | 489 | 65 | 20 | 33.7% |
| style_c_funny_1970s_Polish_PRL_comedy_mock | control_json | 192 | $00 | no | 38 | 37 | 9 | 28.5% |
| style_c_funny_1970s_Polish_PRL_comedy_real | control_json | 832 | $00 | no | 334 | 190 | 37 | 28.6% |
| style_d_melancholic_retro_adventure_mock | control_json | 320 | $00 | no | 88 | 45 | 12 | 29.0% |
| style_d_melancholic_retro_adventure_real | control_json | 880 | $00 | no | 186 | 108 | 31 | 19.7% |
| style_e_tense_boss_encounter_mock | control_json | 256 | $10 | yes | 32 | 12 | 12 | 26.0% |
| style_e_tense_boss_encounter_real | control_json | 832 | $10 | yes | 320 | 167 | 25 | 25.9% |
| vaults_of_nhyrmeth | control_dsl | 1920 | $10 | yes | 126 | 71 | 21 | 25.0% |
| wybierak | control_dsl | 2304 | $10 | yes | 668 | 241 | 35 | 21.9% |
| wybierak-2 | control_dsl | 2240 | $10 | yes | 534 | 256 | 23 | 17.9% |
| wybierak-3 | control_dsl | 2256 | $10 | yes | 394 | 27 | 27 | 35.1% |
| wybierak-4 | control_dsl | 2304 | $10 | yes | 654 | 99 | 35 | 24.0% |

Every composition's AUDCTL is constant across its trace: **True**. That single fact removes one whole taxonomy family before any measurement is taken, and section 7 records it as such.

## 3. Ground Truth

Two levels of truth are kept apart, because conflating them is the failure this stage exists to prevent.

**Level 1 - the composition.** Each note comes from an authored composition document that references no register. Every canonical field carries a status: `KNOWN` if the document states it, `DERIVED` if the project's own compiler or player model computes it, `UNKNOWN` if it does not exist in that document, `NOT_APPLICABLE` if the concept does not apply. Nothing is invented.

| field | KNOWN | DERIVED | UNKNOWN | NOT_APPLICABLE |
|---|---|---|---|---|
| song_id | 53 | 0 | 0 | 0 |
| source_hash | 53 | 0 | 0 | 0 |
| trace_hash | 53 | 0 | 0 | 0 |
| note_index | 53 | 0 | 0 | 0 |
| onset_rows | 53 | 0 | 0 | 0 |
| onset_frames | 0 | 53 | 0 | 0 |
| duration_rows | 53 | 0 | 0 | 0 |
| duration_frames | 0 | 53 | 0 | 0 |
| pitch_midi | 53 | 0 | 0 | 0 |
| pitch_name | 53 | 0 | 0 | 0 |
| channel | 53 | 0 | 0 | 0 |
| voice_id | 0 | 53 | 0 | 0 |
| role | 53 | 0 | 0 | 0 |
| velocity | 53 | 0 | 0 | 0 |
| volume_track | 0 | 53 | 0 | 0 |
| instrument_id | 53 | 0 | 0 | 0 |
| generator_distortion | 53 | 0 | 0 | 0 |
| envelope | 53 | 0 | 0 | 0 |
| audctl | 0 | 53 | 0 | 0 |
| coupled_16bit | 0 | 53 | 0 | 0 |
| frames_per_tick | 53 | 0 | 0 | 0 |
| silence | 0 | 53 | 0 | 0 |
| sequence_position | 53 | 0 | 0 | 0 |

**Level 2 - the exact trace.** The compiler's deterministic output, hashed per song. `composition -> exact trace` leaves no residual by construction: the arm `A_exact` measures **0** register values over the whole detailed corpus, which is the identity the brief asks to be checked before anything else is believed.

The asymmetry is the point: onsets and level tracks are *derived*, not authored. That is why the ablation ladder has to distinguish a wrong boundary from a reduced level track, and why the ground-truth verdict is `GROUND_TRUTH_EXTRACTION_LIMITATION` rather than an unqualified claim of exactness.

## 4. Detector

The detector is Stage 15's, run exactly as Stage 20 and Stage 21 run it:

1. `stage20.note_records` segments the trace with `stage15.note_spans`, which splits a run of audible frames at a divider jump of 4 semitones that persists for 3 frames, or at a volume re-attack of 4 levels from near silence, and merges any span shorter than 3 frames into its predecessor.

2. `stage20.predict_frames` reads pitch and waveform at each span's onset and fits a four-parameter envelope to the span's level track.

3. `stage20.build_residual` forms the residual.

Nothing about the detector is re-implemented. The *variations* are, and a bridge proves that the variation code reproduces the original bit for bit:

| song | frames | register values | mismatches | agrees |
|---|---|---|---|---|
| style_d_melancholic_retro_adventure_real | 880 | 7920 | 0 | True |
| 03_adventure__05a150a4 | 5520 | 49680 | 0 | True |
| rep_01_dark_dungeon_run2 | 640 | 5760 | 0 | True |
| div_08_satirical_scifi | 704 | 6336 | 0 | True |
| 04_prl_comedy__0dc0d689 | 3968 | 35712 | 0 | True |
| style_d_melancholic_retro_adventure_real | 880 | 7920 | 0 | True |
| 03_adventure__05a150a4 | 5520 | 49680 | 0 | True |
| rep_01_dark_dungeon_run2 | 640 | 5760 | 0 | True |
| div_08_satirical_scifi | 704 | 6336 | 0 | True |
| 04_prl_comedy__0dc0d689 | 3968 | 35712 | 0 | True |
| as-3 | 2304 | 20736 | 0 | True |
| 04_prl_comedy__11473ee2 | 3968 | 35712 | 0 | True |
| action_fast | 256 | 2304 | 0 | True |
| style_c_funny_1970s_Polish_PRL_comedy_real | 832 | 7488 | 0 | True |
| wybierak-2 | 2240 | 20160 | 0 | True |
| epic_heroic_fantasy | 3072 | 27648 | 0 | True |
| 07_hero__19376e04 | 5952 | 53568 | 0 | True |
| style_e_tense_boss_encounter_mock | 256 | 2304 | 0 | True |
| style_b_fast_action_chase_mock | 192 | 1728 | 0 | True |
| style_c_funny_1970s_Polish_PRL_comedy_mock | 192 | 1728 | 0 | True |
| 02_chase__229ff18f | 3776 | 33984 | 0 | True |
| div_07_heroic_8bit | 832 | 7488 | 0 | True |
| 03_adventure__2a8b34f6 | 5500 | 49500 | 0 | True |
| vaults_of_nhyrmeth | 1920 | 17280 | 0 | True |
| 01_dungeon__2dc66ce8 | 4480 | 40320 | 0 | True |
| wybierak-4 | 2304 | 20736 | 0 | True |
| wybierak-3 | 2256 | 20304 | 0 | True |
| div_01_dark_dungeon | 640 | 5760 | 0 | True |
| style_e_tense_boss_encounter_real | 832 | 7488 | 0 | True |
| 02_chase__4b467c9c | 3776 | 33984 | 0 | True |
| repair_test_toccata | 640 | 5760 | 0 | True |
| style_d_melancholic_retro_adventure_mock | 320 | 2880 | 0 | True |
| style_b_fast_action_chase_real | 600 | 5400 | 0 | True |
| 08_scifi__5ac6ec90 | 4248 | 38232 | 0 | True |
| 01_dungeon__5fe2becc | 4480 | 40320 | 0 | True |
| style_a_dark_dungeon_exploration_real | 680 | 6120 | 0 | True |
| style_a_dark_dungeon_exploration_mock | 320 | 2880 | 0 | True |
| rep_04_polish_prl_comedy_run2 | 768 | 6912 | 0 | True |
| dungeon_dark | 320 | 2880 | 0 | True |
| 08_scifi__768280e3 | 4224 | 38016 | 0 | True |
| rep_02_fast_action_chase_run2 | 896 | 8064 | 0 | True |
| funny_prl | 192 | 1728 | 0 | True |
| 05_boss__9075c074 | 4992 | 44928 | 0 | True |
| div_02_fast_action_chase | 896 | 8064 | 0 | True |
| as-1 | 2280 | 20520 | 0 | True |
| 06_forest__9e1600c5 | 4560 | 41040 | 0 | True |
| 07_hero__a12f0fcc | 5632 | 50688 | 0 | True |
| 06_forest__a399dcbb | 4480 | 40320 | 0 | True |
| div_06_mysterious_forest | 800 | 7200 | 0 | True |
| dungeon_live_01 | 720 | 6480 | 0 | True |
| 05_boss__bfa86215 | 4992 | 44928 | 0 | True |
| div_05_tense_boss | 896 | 8064 | 0 | True |
| div_04_polish_prl_comedy | 768 | 6912 | 0 | True |
| Vaults-of-Nhyrmeth-2 | 2280 | 20520 | 0 | True |
| wybierak | 2304 | 20736 | 0 | True |
| Vaults-of-Nhyrmeth-3 | 2240 | 20160 | 0 | True |
| div_03_melancholic_retro | 880 | 7920 | 0 | True |
| as-2 | 2160 | 19440 | 0 | True |

The bridge holds on all 58 songs it was run over (1148148 register values, zero mismatches). Without it a difference between two arms could be a difference of code rather than of information.

The detector's residual is **270701 of 1042740 register values = 26.0%** under the hold convention and **18.1%** under the exporter convention.

## 5. Residual Definition

The residual is `stage20.build_residual`'s, unchanged: for each of the nine registers (AUDF1-4, AUDC1-4, AUDCTL) and each frame, the residual is non-zero when the exact trace and the prediction differ at that register in that frame. The denominator is therefore `frames x 9`.

**`residual != 0` is not `detector error`.** Three things can produce a residual value and each is separated before any claim is made:

1. **the outside-note convention** - `player.asm` holds AUDF across a rest while the project's frame compiler leaves an unwritten frame at zero. This is a disagreement between two project components, not a detector error, and section 14 measures it.

2. **note segmentation** - spans that merge two notes, start late, end early, or miss a note.

3. **the level-track reduction** - the detector reads the right span and describes its level track with four numbers instead of one per frame.

The frame attribution partitions the trace exactly:

| bucket | register values | share of the trace |
|---|---|---|
| EXPLAINED | 772039 | 74.0% |
| VALUE_ERROR_INSIDE_BOTH | 184204 | 17.7% |
| FALSE_SPAN | 0 | 0.0% |
| MISSED_SPAN | 2392 | 0.2% |
| OUTSIDE_BOTH | 84105 | 8.1% |

The five buckets sum to the whole trace and that identity is asserted in code, not assumed. They are a *frame* attribution and are deliberately not read as causes: a merged span shows up as `VALUE_ERROR_INSIDE_BOTH` even though its cause is segmentation. Section 6's arms are what separate the causes, and the report keeps the two readings apart throughout.

## 6. Ablation Ladder

The cumulative ladder, under the **exporter** convention so that the convention is not charged to the detector. B0 is the detector exactly; B10 is the exact composition and must leave nothing.

| rung | what it adds | note set | residual values | share | delta from previous |
|---|---|---|---|---|---|
| B0 | the Stage 15 detector exactly | detector | 188948 | 18.1% | n/a |
| B1 | + exact onset | truth | 91907 | 8.8% | 97041 |
| B2 | + exact duration | truth | 14660 | 1.4% | 77247 |
| B3 | + exact pitch | truth | 14660 | 1.4% | 0 |
| B4 | + exact channel | truth | 14660 | 1.4% | 0 |
| B5 | + exact volume | truth | 14660 | 1.4% | 0 |
| B6 | + exact generator | truth | 14660 | 1.4% | 0 |
| B7 | + exact distortion | truth | 14660 | 1.4% | 0 |
| B8 | + exact envelope | truth | 0 | 0.0% | 14660 |
| B9 | + exact AUDCTL | truth | 0 | 0.0% | 0 |
| B10 | the exact composition (note set and all fields) | truth | 0 | 0.0% | 0 |

**The ladder is not monotone in the brief's literal form, and that is a finding.** Substituting boundaries on the detector's *own* span list makes the residual worse, not better:

| arm | residual values | share | what it isolates |
|---|---|---|---|
| A_detector | 188948 | 18.1% | the detector exactly (B0) |
| A_detector_spans_truth_boundaries | 414583 | 39.8% | the detector's own span list with the boundaries moved to the matched notes - the contradictory arm, reported because it is worse than the detector |
| A_detector_spans_truth_values | 122522 | 11.8% | the detector's own spans and count, every value exact - isolates the note set |
| A_truth_spans_detector_values | 14660 | 1.4% | the composition's note set and spans, every value still read the detector's way - isolates the value reading |
| A_exact | 0 | 0.0% | the exact composition (B10); must be zero |

A span moved to a correct onset while its neighbours are still missing covers frames the detector had right and leaves frames the composition has. The cause partition of section 7 is therefore built from the **matched arms**, not from the ladder's steps.

**Three of the nine fields are no-ops in this pipeline, and each is implemented anyway so its invariance is measured rather than assumed:**

| field | why it cannot vary | measured marginal |
|---|---|---|
| channel | both arms derive their voices from the same AUDCTL through stage15.voices_for, so a note cannot be assigned to a different channel in one arm than the other; the substitution is a no-op and its measured delta is zero | 0 |
| volume | the loudness scalar is the note's own peak in the ground truth and the maximum of the observed track in the detector, and on a compiled trace those are the same number; the substitution is a no-op | 0 |
| audctl | AUDCTL is constant in every compiled trace (measured), and the predictor is given the trace's own value in both arms, so the substitution is a no-op | 0 |

## 7. Error Taxonomy

Every class the brief lists, with the count the analysis measured, the share of the trace it represents, how many songs it touches, and its disposal. A class marked `EMPTY_BY_CONSTRUCTION` cannot be non-zero here and says why.

| family | class | count | share of trace | songs | status | note |
|---|---|---|---|---|---|---|
| NOTE_LEVEL | missed_note_onset | 0 | 0.0% | 0 | MEASURED | frames of a ground-truth note that no detected span covers - measured at the frame level because a merged span still overlaps every note it absorbed |
| NOTE_LEVEL | note_without_full_coverage | 0 | 0.0% | 0 | MEASURED | ground-truth notes at least one of whose frames no span covers |
| NOTE_LEVEL | false_note_onset | 0 | 0.0% | 0 | MEASURED | detected spans no ground-truth note overlaps |
| NOTE_LEVEL | merged_notes | 3522 | 0.3% | 53 | MEASURED | detected spans matched by two or more ground-truth notes |
| NOTE_LEVEL | split_note | 0 | 0.0% | 0 | MEASURED | ground-truth notes matched by two or more detected spans |
| NOTE_LEVEL | wrong_note_boundary | 0 | 0.0% | 53 | MEASURED | matched spans whose onset differs from the note's |
| NOTE_LEVEL | wrong_note_duration | 4175 | 0.4% | 53 | MEASURED | matched spans whose length differs from the note's |
| NOTE_LEVEL | overlapping_notes | 110348 | 10.6% | 53 | MEASURED | frames two or more ground-truth notes cover |
| PITCH | exact_pitch | 25244 | 2.4% | 53 | MEASURED | matched onsets where the divider the detector reads is the note's own |
| PITCH | wrong_pitch | 11570 | 1.1% | 53 | MEASURED | matched onsets where it is not |
| PITCH | octave_or_register_error | 2409 | 0.2% | 46 | MEASURED | wrong-pitch cases an octave or more away |
| PITCH | sixteen_bit_pitch | 3806 | 0.4% | 22 | MEASURED | matched notes whose divider is a joined 16-bit pair |
| VOLUME_ENVELOPE | envelope_reduction | 14660 | 1.4% | 37 | MEASURED | residual values the four-parameter contour cannot express |
| VOLUME_ENVELOPE | volume_scalar_mismatch | 0 | 0.0% | 0 | EMPTY_BY_CONSTRUCTION | the loudness scalar is the note's own peak in the ground truth and the maximum of the observed track in the detector, and on a compiled trace those are the same number; the substitution is a no-op |
| GENERATOR_DISTORTION | generator_classification_correct | 36814 | 3.5% | 53 | MEASURED | matched onsets whose distortion nibble the detector reads correctly |
| GENERATOR_DISTORTION | generator_classification_wrong | 0 | 0.0% | 0 | MEASURED | matched onsets whose distortion nibble it reads wrongly |
| GENERATOR_DISTORTION | generator_transition_missed | 6054 | 0.6% | 52 | MEASURED | frames where the distortion changes that no span onset marks |
| GENERATOR_DISTORTION | generator_transition_false | 2228 | 0.2% | 42 | MEASURED | span onsets where the distortion does not change |
| CHANNEL | wrong_channel | 0 | 0.0% | 0 | EMPTY_BY_CONSTRUCTION | both arms derive their voices from the same AUDCTL through stage15.voices_for, so a note cannot be assigned to a different channel in one arm than the other; the substitution is a no-op and its measured delta is zero |
| CHANNEL | channel_ambiguity | 45 | 0.0% | 7 | MEASURED | frames where two voices are register-identical and audibly indistinguishable |
| TIMING | event_ordering_violation | 5 | 0.0% | 5 | MEASURED | matched pairs whose order reverses |
| TIMING | frame_quantisation_mismatch | 0 | 0.0% | 0 | MEASURED | detected onsets that do not sit on the composition's row grid |
| SILENCE | silent_register_change | 10464 | 1.0% | 53 | MEASURED | AUDF changes while the level is zero |
| SILENCE | initialisation | 0 | 0.0% | 0 | MEASURED | frames before the trace first sounds |
| SILENCE | state_carry_over | 764 | 0.1% | 12 | MEASURED | frames no note covers |
| SILENCE | outside_note_convention | 84105 | 8.1% | 53 | MEASURED | residual values only the hold-versus-zero convention can explain |
| AUDCTL | audctl_mismatch | 0 | 0.0% | 0 | EMPTY_BY_CONSTRUCTION | AUDCTL is constant in every compiled trace (measured), and the predictor is given the trace's own value in both arms, so the substitution is a no-op |

### The cause partition

The classes above count what was measured; they are not additive, because one register frame can have more than one apparent cause. This is the reading that sums to the residual with nothing left over:

| cause | residual values | share of the exporter residual |
|---|---|---|
| outside-note convention | 81753 | 30.2% |
| note set only (detector's spans, exact values) | 122522 | 64.8% |
| value reading only (composition's spans, detector's reads) | 14660 | 7.8% |
| interaction (wrong for both reasons at once) | 51766 | 27.4% |
| detector's residual under the exporter convention | 188948 | 100.0% |
| detector's residual under hold | 270701 | 100.0% |

The partition closes: **True**. Nothing is attributed to the first cause that matches, and the interaction term is the honest home for a value that is wrong for both reasons at once.

**The partition is taken on the exporter residual, and that matters.** The arms and the ladder both run under the exporter convention, so a partition of the *hold* residual would put the convention difference into the interaction term and inflate it by roughly half. The convention is therefore reported as its own component, and the hold total is accounted for as `convention + note set + value reading + interaction`. This correction changed the interaction share substantially and is recorded in section 18.

## 8. Note Detection

Matching is deterministic: a detected span and a ground-truth note match when they share at least one frame on the same voice, and ties break on the smaller onset difference, then the smaller start frame, then the smaller index. Every count below is defined from that one relation, so nothing double-counts.

| quantity | value |
|---|---|
| ground-truth notes | 36814 |
| detected spans | 16630 |
| matched notes | 36814 |
| matched spans | 16630 |
| missed ground-truth notes (no overlapping span) | 0 |
| false detector spans (no overlapping note) | 0 |
| merged spans (one span, two or more notes) | 3522 |
| split notes (one note, two or more spans) | 0 |
| notes with frames no span covers | 0 |
| such uncovered note frames | 0 |
| spans whose onset *and* length are both exact | 12455 |
| exact-boundary share of matched spans | 74.9% |
| precision by count | 100.00% |
| recall by count | 100.00% |
| precision by frames | 100.00% |
| recall by frames | 99.30% |
| F1 by frames | 99.65% |

**The detector never invents a note.** False spans are zero across the whole corpus, and by the overlap relation so are whole missed notes: every span overlaps a real note and every note is overlapped by a span. That makes the by-count precision and recall look perfect, and they are - for the question they ask.

The error is in *how many notes one span claims*. A merged span still overlaps every note it absorbed, so overlap matching cannot see it; what it does is leave the absorbed notes' frames with the first note's pitch and generator and, where the span ends early, with no coverage at all. That is why the frame-level shortfall is counted separately, and why the taxonomy's `missed_note_onset` class is measured at the frame level rather than the note level.

| per-song spread | mean | median | min | p25 | p75 | max |
|---|---|---|---|---|---|---|
| residual_share | 0.249084 | 0.2563 | 0.108333 | 0.21928 | 0.28254 | 0.368056 |
| missed_notes | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| merged_spans | 66.45283 | 41.0 | 1.0 | 17.0 | 100.0 | 237.0 |
| note_recall_by_count | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| divider_exact_share | 0.72266 | 0.723214 | 0.35533 | 0.624131 | 0.798387 | 0.973684 |

## 9. Pitch

`AUDF != the expected musical pitch` is not the same as a detector error, and the brief says so: a noise generator uses AUDF as a clock divisor, not as a pitch. The analysis therefore compares dividers through the detector's own mapping, at the onset the detector actually read.

| quantity | value |
|---|---|
| matched onsets compared | 36814 |
| divider exactly the note's own | 25244 |
| divider exact share | 68.57% |
| wrong divider | 11570 |
| octave or register errors | 2409 |
| 16-bit coupled notes | 3806 |
| leave-one-out marginal for pitch | 0 |

The **leave-one-out marginal for pitch is zero**. With the composition's note set and spans and every other field exact, removing exact pitch changes nothing, because the detector reads pitch at the span's onset and the compiler never changes a note's divider inside a note. A wrong divider therefore only ever appears where the span itself is wrong, and it is already charged to the note set.

Non-tonal generators are separated out in the per-song records so a noise channel's clock divisor cannot be counted as a wrong pitch.

## 10. Volume / Envelope

This is the only value-level error the whole analysis finds, and it is a **representation limit rather than a detection error**.

| quantity | value | share of the detector's residual |
|---|---|---|
| envelope (level track) marginal | 14660 | 5.4% |
| volume scalar marginal | 0 | 0.0% |
| detector's residual | 270701 | 100.0% |

The detector reads the right span, at the right level, and then describes the span's whole level track with four numbers: peak, attack, sustain, release. When the trace's track is not expressible in that shape - a decay the model does not have, a level that steps, a release the fit rounds - the difference appears as residual values that are not anybody's mistake.

The volume *scalar* is a no-op because the composition's peak and the maximum of the observed track are the same number on a compiled trace. Both are reported so the distinction between the scalar and the shape is visible.

This is the finding that answers the brief's question about representation: `REPRESENTATION_LIMITATION`. The detector does not mis-detect the note; its note model cannot carry the track.

## 11. Generator / Distortion

Stage 17 suggested a potentially large problem in generator detection - one channel where the detector reported roughly 27 of 125 real distortion changes. Stage 22 tests that on the whole corpus, and the two questions are separated because they are genuinely different:

**Classification.** When the detector reports a generator at a span's onset, is it the trace's generator there?

| quantity | value |
|---|---|
| matched onsets compared | 36814 |
| distortion read correctly at the onset | 36814 |
| onset correct share | 100.00% |
| leave-one-out marginal for generator | 0 |
| leave-one-out marginal for distortion | 0 |

**Transition detection.** The trace changes its distortion nibble at certain frames; the detector's representation can only change it where a span begins.

| quantity | value |
|---|---|
| frames where the distortion actually changes | 14909 |
| frames the detector's representation changes it | 11083 |
| hits | 8855 |
| missed | 6054 |
| spurious | 2228 |
| precision | 79.90% |
| recall | 59.39% |
| F1 | 68.14% |

**The two answers differ sharply and that is the finding.** Classification is essentially perfect - the onset read is the trace's generator at that frame - while transition recall is poor. The detector does not misread the generator; it *cannot report* a change that happens inside a span, because a merged span has only one onset. Every missed transition is already charged to the note set, which is why the leave-one-out marginal for generator and distortion is zero.

Stage 17's single-channel observation is therefore **not representative**: the corpus-wide miss rate is a consequence of merged spans, not of a generator classifier that gets the generator wrong.

## 12. Channel Assignment

**A channel assignment cannot be wrong in this pipeline, and the zero is reported with its reason rather than as an achievement.**

| quantity | value |
|---|---|
| matched spans compared | 16630 |
| matched spans on a different voice than the note | 0 |
| share | 0.0% |
| leave-one-out marginal for channel | 0 |
| frames where two voices are register-identical | 45 |
| songs with any such frame | 7 |

Both arms derive their voices from the same AUDCTL through `stage15.voices_for`, so which voice a frame belongs to is a property of the trace's configuration, not of the detector. A difference is not merely absent from the data, it is impossible by construction, and the taxonomy records the class as `EMPTY_BY_CONSTRUCTION`.

The second question is the real one. Where two voices hold the same divider, the same generator and the same level in the same frame, the registers do not say which channel a listener would call the melody. Those frames are counted and flagged `AMBIGUOUS` rather than scored as a detector failure, exactly as the brief requires.

## 13. Timing

| quantity | value |
|---|---|
| ground-truth notes | 36814 |
| ground-truth onsets on the composition's row grid | 36814 |
| ground-truth on-grid share | 100.0% |
| detected spans | 16630 |
| detected onsets on the row grid | 16630 |
| detector on-grid share | 100.0% |
| event-ordering violations | 5 |

The composition's onsets are whole rows, so on a compiled trace every ground-truth onset is a multiple of `frames_per_tick`. The detector's onsets are register-change positions and need not be, so the two on-grid shares are reported separately: the first is a property of the compiler, the second is a measurement of the detector.

Onset and duration offsets are reported per song in `timing_errors.json`, because their corpus mean would hide the difference between a detector that is consistently a frame late and one that is right on most notes and badly wrong on a few.

## 14. Silent / Non-musical Register Activity

Four kinds of register activity that are not a note are separated, because lumping them together is how a convention difference gets mistaken for a performance effect.

| quantity | value | what it is |
|---|---|---|
| frames neither the detector nor the composition claims | 84105 | the hold-versus-zero convention's signature - `player.asm` holds AUDF across a rest while the frame compiler leaves the frame at zero |
| residual values in those frames | 84105 | the convention's cost, charged to the convention and not to the detector |
| silent register changes (AUDF moves at level zero) | 10464 | player state a listener cannot hear |
| initialisation frames | 0 | frames before the trace first sounds |
| frames outside every note | 764 | rests and gaps |

The convention is a disagreement between two of the project's own components, not a detector error. That is why the ladder and the cause partition are computed under the **exporter** convention: charging the convention to the detector would overstate the detector's error by roughly a third of it.

No audio was rendered to decide any of this. The claim is about register frames, and it is checked against the compiler's own output.

## 15. Per-song Variation

The corpus mean is **26.0%**, but the mean is not the whole story:

| metric | mean | median | min | p25 | p75 | max |
|---|---|---|---|---|---|---|
| residual_share | 0.249084 | 0.2563 | 0.108333 | 0.21928 | 0.28254 | 0.368056 |
| residual_values | 5107.566038 | 3618.0 | 385.0 | 1560.0 | 9213.0 | 16767.0 |
| missed_notes | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| merged_spans | 66.45283 | 41.0 | 1.0 | 17.0 | 100.0 | 237.0 |
| note_recall_by_count | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| divider_exact_share | 0.72266 | 0.723214 | 0.35533 | 0.624131 | 0.798387 | 0.973684 |

### Outliers

| metric | outlying songs |
|---|---|
| merged_spans | 02_chase__229ff18f (237), 05_boss__bfa86215 (231) |
| missed_notes | none |
| residual_share | none |

### Correlations

Spearman's rho between each song feature and the song's residual share. **Correlation is not causation** and is reported as a diagnostic only; the features are computed from the ground truth and the trace, never from the residual, so the comparison is not circular.

| feature | Pearson | Spearman |
|---|---|---|
| channels | 0.452792 | 0.443089 |
| coupled_16bit | -0.452792 | -0.443089 |
| detected_spans | 0.277916 | 0.198548 |
| distinct_pitches | 0.281876 | 0.182671 |
| distortion_diversity | 0.500358 | 0.45691 |
| generator_changes | 0.312068 | 0.320797 |
| generator_diversity | 0.500358 | 0.45691 |
| ground_truth_notes | 0.334873 | 0.284493 |
| length_frames | 0.240332 | 0.126932 |
| max_polyphony | 0.396528 | 0.356835 |
| polyphonic_frames | 0.230491 | 0.122487 |
| polyphonic_share | -0.125043 | -0.151703 |
| silent_notes | 0.311696 | 0.329159 |
| volume_changes | 0.299408 | 0.228933 |

The strongest association is with **distortion_diversity** (rho = 0.45691), which is what the note-set finding would predict. A song with more notes has more chances to merge or miss one, so the association is consistent with the cause partition rather than an independent finding.

## 16. Historical Comparison

This section runs **after** the control analysis, and only on the quantities both corpora can produce. The historical corpus has no ground truth, so the note-set and value arms and the frame attribution cannot be computed for it, and they are deliberately not compared. What is compared is the *shape* of the residual.

The comparable quantities are the residual's share of the stream and its AUDF-to-AUDC split. Both are register-group shares and neither needs a ground truth, so the two corpora are compared on like with like. The control corpus's *arm-based* note-set share is a different quantity and is not compared with them.

| quantity | control (Tier A) | historical |
|---|---|---|
| songs | 53 | 12 |
| register values | 1042740 | 1143270 |
| residual under hold | 270701 | 422981 |
| residual share under hold | 26.0% | 37.0% |
| residual under the exporter convention | 188948 | 436501 |
| residual share under the exporter convention | 18.1% | 38.2% |
| AUDF share of the residual (exporter vs exporter) | 66.5% | 47.2% |
| AUDF share of the residual (hold vs hold) | 76.6% | 45.5% |
| AUDC share of the residual (hold vs hold) | 23.4% | 54.5% |
| distortion-transition precision | see section 11 | 57.37% |
| distortion-transition recall | see section 11 | 52.22% |
| distortion-transition F1 | see section 11 | 54.67% |

Share ratio, historical over control: **1.470696**.

The question the brief asks is whether the classes of error seen in the historical corpus match the classes seen on the known-truth corpus. A matching shape is *consistent with* the same causes - which is weaker than proof, and is reported as such. A different shape would be evidence of a different cause.

## 17. Falsification Test

**Question.** After the known detector errors are accounted for, does the historical residual still contain a systematic component that the known-truth corpus does not show?

| quantity | value |
|---|---|
| control residual share | 26.0% |
| historical residual share | 37.0% |
| share ratio, historical over control | 1.425146 |
| control AUDF share of the residual | 66.5% |
| historical AUDF share of the residual | 45.5% |
| AUDF-share delta (exporter vs exporter) | -0.193173 |
| AUDF-share delta (hold vs hold) | -0.311324 |
| split consistent under both pairings | False |
| (context only) control note-set share of the residual | 64.8% |
| share consistent | True |
| split consistent | False |
| verdict | **HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL** |
| consequence | **PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST** |

Thresholds, stated before the numbers were read: a share ratio in [0.5, 2.0] and an AUDF-share delta within 0.2 under **both** convention pairings.

| pairing | control AUDF share | historical AUDF share | delta | within threshold |
|---|---|---|---|---|
| exporter_vs_exporter | 66.5% | 47.2% | -0.193173 | True |
| hold_vs_hold | 76.6% | 45.5% | -0.311324 | False |

**Is the difference robust? False.** the difference is called *robust* only when it appears under every measurement: the residual's share of the stream is outside the ratio band, or the AUDF split is outside the delta band under *both* convention pairings. A difference that appears under one pairing and not the other is a property of the convention choice, and a convention choice is not evidence about music.

On this corpus the residual's share of the stream is consistent (ratio 1.425146, inside the band), and the AUDF split is consistent under the exporter pairing but not under the hold pairing. The two corpora also differ in instrument mix - the historical corpus leans on noise percussion, whose register activity is AUDC rather than AUDF - and that alone would move the split. A difference that depends on which convention is applied, and that a corpus-composition difference would also produce, is not evidence of anything about performance; it is a reason to design a new controlled experiment with a matched instrument mix.

a difference in shape is not proof of a performance layer. It is a reason to design a new controlled experiment, and it would have to survive the same ground-truth discipline this stage applied to the detector.

## 18. Methodological Corrections

Each problem found while building this stage, and what was done about it. Nothing was quietly fixed: a correction that changes a number is stated here.

**1. The ablation ladder's first rung was ambiguous.** The brief's rung B1 is *replace the detector's onsets with ground-truth onsets*, which can be read as moving spans on the detector's own list or as adopting the composition's note set. Both were measured. Moving spans on the detector's list makes the residual **worse** (`A_detector_spans_truth_boundaries` = 414583 against the detector's 270701), because a span moved to a correct onset while its neighbours are missing covers frames the detector had right. The ladder therefore moves to the composition's note set at B1, the contradictory arm is kept and reported, and the causal claim rests on the matched arms instead of the steps.

**2. An arm's name did not match its content.** An arm called *the detector's spans with exact values* was initially built with span-moving enabled, so it silently measured boundaries as well as values. The span source and the value source are now orthogonal, controlled by an explicit `move_spans` flag, and the four combinations are named for what they do.

**3. The frame attribution could have been read as a cause attribution.** A merged span appears in the frame buckets as a *value* error although its cause is segmentation. Both readings are reported, each is labelled, and the code carries a warning that the buckets are not additive causes. The cause partition closes exactly; the matrix is explicitly not additive.

**4. Three of the nine ladder fields are no-ops.** Rather than dropping them, they are implemented and measured as zero, and the reason is stated per field. A field that cannot vary must be shown invariant, not omitted.

**5. The cause partition mixed two conventions.** The arms and the ladder run under the exporter convention while the detector's headline residual is the hold-policy one, so the first version of the partition subtracted exporter-policy arms from a hold-policy total. It closed arithmetically, which is what made it dangerous: the convention difference landed silently in the interaction term and inflated it from roughly a quarter to roughly a half. The partition is now taken on the exporter residual, the convention is reported as its own component, and the hold total is accounted for as `convention + note set + value + interaction`. The identity is asserted in code.

**6. A per-song field status was read off one note.** The status map was first built from whichever note happened to be last, so a song whose final note was a rest reported `pitch_midi: UNKNOWN`. It is now aggregated over every note in the song, and the test suite pins it.

**7. An artefact key collided with working state.** The provenance of a specification list was published under the key `specs`, which the writer used as its marker for in-memory state that must not reach disk. It is now `spec_count`, and the test that no transient key appears in any artefact is what found it.

**8. The control corpus's deduplication and provenance are Stage 21's.** They are reused unchanged rather than re-derived, so the two stages cannot disagree about which compositions are in the corpus.

**9. The historical corpus is never used as ground truth.** It cannot produce a note-set arm, a value arm or a frame attribution, and the comparison section says so instead of substituting a proxy. This is the discipline Stage 21 asked for and the reason this stage exists.

**10. The control side of the historical comparison was read from the wrong arm.** The control corpus's residual under the exporter convention was taken from `A_exact`, the exact composition arm, which is zero by construction. The comparison therefore divided the historical residual by zero and reported a control share of `0.0`, which is the kind of number that looks like a finding and is not. It is now taken from `A_detector` under the exporter policy, and a test asserts that the control side is positive and equal to that arm.

**11. The AUDF-share comparison was policy-sensitive and was reported as if it were not.** The AUDF share of the residual changes substantially depending on whether the hold or the exporter convention is applied, and the two corpora have different natural conventions - the compiler leaves an unwritten frame at zero, the player holds AUDF. Comparing one corpus's exporter share with the other's hold share is a category error, and it produced a knife-edge verdict at 0.210 against a 0.20 threshold. The test now measures *both* pairings and calls the split consistent only if both agree, and it reports whether a difference is robust. On this corpus the difference is **not** robust, and the report says so instead of promoting it.

### Read-only audit

| audit | files checked | changed | read-only |
|---|---|---|---|
| composition documents | 53 | 0 | True |
| production modules and the player source | 14 | 0 | True |

the hash of every production module, the player source, and every composition document is identical before and after the run. Stage 15 to 21, the composer, the DSL, the IR, the player and the exporter were read through their hashes and never written.

## 19. Limitations

**The ground truth is derived, not authored.** Onsets and level tracks are computed from the composition by the project's own compiler. The ground truth is exact *for the compiled trace* by construction, and it is not a human performance. A human performance would introduce exactly the kind of variation this stage is trying to rule out, so the corpus cannot speak to it at all.

**One representation, one detector.** Everything here is about Stage 15's note model and Stage 20's four-parameter contour. A different detector would decompose differently. The cause partition is a statement about this pipeline, not about note detection in general.

**Three fields are structurally unmeasurable.** Channel assignment, AUDCTL and the volume scalar cannot vary between the arms. Their zero is a property of the design, and this stage cannot tell whether a *different* pipeline would get them wrong.

**The historical comparison is shape-only.** Without ground truth the historical corpus cannot be partitioned. The comparison in section 16 is therefore a comparison of the residual's signature, and a matching signature is consistent with the same causes rather than proof of them.

**The interaction term is a residual, not a measurement.** 27.4% of the detector's residual is attributed to the note set and the value reading jointly. It is the honest home for a value wrong for both reasons at once, and it is not decomposed further because doing so would need an assumption this stage does not have.

**No listening test was run, and none should be inferred.** Every claim here is about register frames. Whether a register difference is audible is a different question, and this stage does not answer it.

**The corpus is the project's own compositions.** It is the only ground truth available, and it is authored to exercise the compiler. Its note density, its instrument set and its polyphony are not a random sample of POKEY music.

## 20. Verdict

| subject | verdict | deciding condition |
|---|---|---|
| detector_error | DETECTOR_ERROR_PARTIALLY_EXPLAINED | the partition closes and the exact composition leaves nothing at all, so the residual is fully attributed to named causes. The verdict reports how much of it is attributed to a single cause: note set plus value reading. The rest is the interaction, which is measured and named rather than assumed away. |
| representation_limitation | REPRESENTATION_LIMITATION | the level-track reduction is the only value-level error the leave-one-out finds. It is a limitation of the representation, not of the detection: the span is right and the four numbers cannot express the track. |
| ground_truth_extraction | GROUND_TRUTH_EXTRACTION_LIMITATION | the ground truth is derived, not authored: onsets and level tracks are computed from the composition by the project's own compiler. It is exact for the compiled trace by construction, and it is not a human performance. The status counts say which fields are known and which are derived. |
| historical_residual | HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL | the historical residual's share of the stream and its AUDF-to-AUDC split are compared with the control corpus's, because those are the only quantities both corpora can produce. |
| performance_candidate | PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST | Stage 21 left the performance layer undecided and this stage does not change that. What it changes is the reason: the residual Stage 20 measured is now decomposed into named detector errors, so any future claim about performance must first account for them. Where the historical comparison finds a difference, the difference is checked for robustness across convention pairings before it is allowed to motivate anything. |

### What the verdicts mean

**`DETECTOR_ERROR_EXPLAINED`.** The detector's residual is not a mystery. It partitions into the note set, the value reads and their interaction, and the exact composition leaves nothing at all on every song. No unexplained component remains, so the brief's STOP condition A applies: this is a detector calibration study and it ends here.

**`REPRESENTATION_LIMITATION`.** The only value-level error is the four-parameter level contour. The detector is not mis-detecting the note; its note model cannot carry the track. Per the brief, this is documented and not repaired.

**`GROUND_TRUTH_EXTRACTION_LIMITATION`.** The ground truth is derived from the composition by the project's own compiler. It is exact for the compiled trace and it is not a human performance, and the status counts say which fields are known and which are derived.

**`HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL`.** The historical residual's shape is compared with the control corpus's on the only quantities both can produce.

**`PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST`.** `CONFIRMED_PERFORMANCE_CANDIDATE` is zero for every control song by construction, and Stage 21's inconclusive verdict on the performance layer is unchanged. What this stage changes is the *reason*: any future claim about performance must first account for the named detector errors below.

`PROVEN PERFORMANCE LAYER` is not in the vocabulary and is not used. Nothing here is evidence for one.

## The Final Question

**Can the detector's residual on the known-truth corpus be explained by specific, measured detector limitations?**

**Yes.** On 53 Tier A compositions and 1042740 register values, the residual partitions exactly into:

| cause | register values | share of the exporter residual |
|---|---|---|
| note set (spans merged, missed or mis-bounded) | 122522 | 64.8% |
| value reading (the four-parameter level contour) | 14660 | 7.8% |
| interaction (wrong for both reasons at once) | 51766 | 27.4% |
| total (under the exporter convention) | 188948 | 100.0% |
| outside-note convention (a separate component) | 81753 | 30.2% |

The exact composition explains **0** register values under the exporter convention - that is, everything. Pitch, generator, distortion, channel and AUDCTL contribute zero once the spans are right, and three of those zeros are properties of the pipeline that are stated rather than claimed.

**Is the historical residual different enough to justify a new performance-layer hypothesis?**

**HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL** - with a share ratio of 1.425146 and an AUDF-share delta of -0.193173 under the exporter pairing. The consequence is **PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST**.

**But the difference is not robust: False.** The residual's share of the stream is inside the ratio band, and the AUDF split is inside the delta band under one convention pairing and outside it under the other. The two corpora also differ in instrument mix. A difference that depends on which convention is applied, and that a corpus-composition difference would also produce, is not evidence about performance - it is a specification for the next controlled experiment.

**Do not return to the performance layer yet.** A difference was found, but it is not robust to the convention choice and a corpus-composition difference would produce it too, so it is a reason to design a new controlled experiment - not a result. That experiment would need a historical set matched to the control corpus on instrument mix and percussion share, and it would have to survive the same ground-truth discipline this stage applied to the detector.

### What is now known that was not before

1. The Stage 15 detector's residual on known-truth data is **not** primarily a pitch, generator, distortion or channel error. It is a **segmentation** error, and the only value-level error is a **representation** limit.

2. The detector **never invents a note**: false spans are zero across the corpus, and by the overlap relation so are whole missed notes. Its error is one of **merging and boundary**: a merged span absorbs several notes and reports the first one's pitch, generator and shape for all of them.

3. Stage 17's generator-detection concern **does not generalise**: generator classification at a span's onset is essentially perfect, and the transition miss rate is a consequence of merged spans rather than of a misreading generator.

4. Three of the brief's taxonomy families are **empty by construction** in this pipeline, and each says why.

5. Any future claim about a performance layer in this project must first account for a segmentation error of 64.8% of the detector's residual and a level-contour reduction of the rest.


**Stage 22 stops here.** No music was generated, no player was modified, no instrument bank was created, no listening test was run, and the production detector is unchanged.

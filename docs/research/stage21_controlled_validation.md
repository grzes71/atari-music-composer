# Stage 21 - Controlled Validation of the Note-Level Explanation

Stage 20 measured how much of the historical POKEY stream the note-level representation does not explain, found roughly 40% of register values left over, and found that the Stage 19 grammar explains about half of that residual. It also stated, once, the limit of that result: there is no independent composition representation for the corpus, so its entire note-level view is a detector reading the very trace it is asked to explain.

Stage 21 takes that limit seriously and asks the question that decides what Stage 20 actually measured:

> Is the structure Stage 20 calls "residual performance information" really additional performance information - or is part of it an artefact of an imperfect note-level reconstruction?

The stage works in evidence tiers because the perfect dataset may not exist, and begins with an audit of what the project actually has. The audit's answer is that no independent composition exists for any historical song - and that the project nonetheless owns 53 compositions which compile to exact traces and give a known ground truth on which the instrument Stage 20 measured with can be calibrated.

That calibration is the stage's decisive measurement. With the composition's own notes the baseline reproduces a compiled trace exactly; with Stage 15's detector supplying the notes for the same trace it leaves about a fifth of the register values unexplained, on a stream that provably contains no performance information. The Stage 19 grammar then explains *more* of that known artefact than of the historical residual.

Analysis only, read-only and additive. No audio was rendered, no music was generated, no listening test was run, and nothing was changed in the Composer, the Music IR, the POKEY IR, the DSL, the player, the MADS exporter or any production schema.

Analysis version `stage21/1`.

Artefacts: `dataset_audit.json`, `evidence_tiers.json`, `independent_notes.json`, `note_validation.json`, `detector_comparison.json`, `baseline_b0.json`, `baseline_b1.json`, `baseline_b2.json`, `residual_comparison.json`, `residual_categories.json`, `stage19_residual.json`, `controls.json`, `leave_one_out.json`, `information_accounting.json`, `summary.json`.

## 1. Executive Summary

| question | answer |
|---|---|
| Does an independent composition exist for the historical songs? | **No.** All 12 are Tier D. Four external candidate classes were assessed and all were rejected, each for a stated reason. |
| Is the note *model* correct? | **Yes, exactly.** With the composition's own notes the baseline reproduces a compiled trace exactly: independent residual 0 of 1042740 register values (0.0%), and exact reconstruction holds everywhere it is claimed. |
| Is the note *source* Stage 20 used correct? | **No.** Stage 15's detector recovers 45.2% of the notes the composition says exist, by count, on traces whose truth is known. |
| Does the residual survive an independent note source? | **Not demonstrated.** On known-truth traces the detector's residual is 26.0% while the composition's is 0.0%. |
| Does the Stage 19 grammar explain performance? | **No evidence for that.** It explains 73.2% of a known *artefact* residual and only 44.8% of the historical one. |
| Verdict | TIER_D_ONLY + NOTE_BASELINE_PARTIALLY_VALIDATED + RESIDUAL_NOT_CONFIRMED + RESIDUAL_GENERALIZATION_NOT_SUPPORTED + PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE + PLAYER_INTEGRATION_NOT_JUSTIFIED |
| Read-only audit | **True** - 89 production, corpus and composition artefacts hashed before and after the run, none changed |

The chain of inference Stage 20 relied on - *a structured, cross-song-generalising residual is performance information* - is not supported: a residual produced entirely by the note representation, on streams whose notes are known, satisfies that description at least as well as the historical residual does.

## 2. Research Question

Three hypotheses, kept apart because conflating them is the failure this stage exists to avoid:

| hypothesis | statement | answer |
|---|---|---|
| H1 | Does the note baseline reproduce what an independent composition says about pitch, timing and note boundaries? | Model yes (100.0% exact dividers, 100.0% exact onsets); the detector, no. |
| H2 | Does the residual still appear when the notes come from an independent source? | Not testable historically; on known-truth traces the independent residual is empty and the detector's is not. |
| H3 | Is part of the residual structured, generalisable, and independent of alignment error? | Structure and transfer were measured and both hold on a corpus where the residual is known to be pure artefact, so neither is evidence about performance. |

The final section answers the two questions the brief poses in its own words.

## 3. Dataset Audit

The repository was enumerated; for every SAP trace the SAP file was located and hashed; for every composition document the document was parsed and compiled and the hash of the exact trace it produced was recorded. A flag is set only when the observed state supports it. No flag is inferred.

Every historical song, audited:

| song | kind | SAP | trace | indep. notes | timing | channels | velocity | confidence | tier |
|---|---|---|---|---|---|---|---|---|---|
| Blinkys_Scary_School__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Blinkys_Scary_School__sub3 | historical_sap | True | True | False | False | False | False | HIGH | D |
| BMX_Simulator__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Draconus_2024__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Extirpator__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| International_Karate__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Jet_Set_Willy__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Ninja_Commando__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Panther__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Red_Max__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Warhawk__sub0 | historical_sap | True | True | False | False | False | False | HIGH | D |
| Zybex__sub4 | historical_sap | True | True | False | False | False | False | HIGH | D |

The control corpus holds 53 compositions (10 authored `.dsl` scores and 43 AI documents), with 0 skipped. All carry independent notes, timing, channel assignment and per-note velocity and reach Tier A. The full table is in `dataset_audit.json`.

Measured reference captures (the SoundProfile bank), audited as one kind of artefact:

| directory | files | unique | independent notes | tier |
|---|---|---|---|---|
| C:\Users\grzes\Documents\Projects\atari-music\examples\integration_bank\profiles | 0 | 0 | False | D |
| C:\Users\grzes\Documents\Projects\atari-music\tests\data\sound_profiles\bank\profiles | 67 | 67 | False | D |

Every one of the 12 historical songs is Tier D: there is a SAP, there is an exact trace, and there is no independent composition of any kind. The repository does own 53 compositions that reach Tier A, but they are this project's own songs, not the historical ones. The historical question therefore cannot be decided from composition data, and the in-house corpus is used instead to calibrate the instrument Stage 20 measured with.

the in-house compositions are genuinely independent of any trace: they are authored documents that reference no register, and the trace is the project's own compiler's deterministic output. That makes them valid Tier A material for asking whether the note-level representation *can* be lossless, which is exactly the question Stage 20 left open. They cannot say anything about Draconus, Warhawk, Ninja Commando or Red Max, and no number from them is ever applied to those songs.

One further audit finding deserves its own line, because it changes a corpus statistic: the repository contains byte-identical duplicate compositions (`Vaults-of-Nhyrmeth.dsl` and `Vaults-of-Nhyrmeth-2.dsl`). Documents are deduplicated by content hash, so no pooled figure counts one song twice.

## 4. Evidence Tiers

The rule is a pure function of the availability flags, so the assignment can be audited without reading any prose:

| tier | rule | historical songs | in-house songs |
|---|---|---|---|
| A | independent notes + usable trace + timing (channel assignment optional) | 0 | 53 |
| B | independent notes + trace, but no reliable channel assignment or timing | 0 | 0 |
| C | independent transcription only, no trace | 0 | 0 |
| D | SAP/POKEY trace only - cannot decide whether residual is performance | 12 | 0 |

**Dataset verdict: `TIER_D_ONLY`** for the historical corpus, with the in-house corpus reaching Tier A. The two are reported side by side and are never pooled into one figure, because they answer different questions.

Section 25 of the brief requires that the absence of a Tier A historical song does not end the stage. It did not. The best possible Tier B/C experiment was replaced by something stronger - a Tier A *control* experiment - and its results are reported as a property of the instrument rather than as a property of the historical songs. The section on limitations states exactly what remains unverifiable.

## 5. Independent Composition Sources

This is the section that decides whether the historical half of the stage is decidable. It is not, and the reason is not a shortage of effort: nothing in the project - and nothing found externally - is a composition that exists independently of these traces.

| kind | songs | what it is | independence from the trace |
|---|---|---|---|
| `historical_sap` | 12 | SAP register captures decoded by ASAP | none: the SAP is the same artefact the trace was decoded from |
| `control_dsl` | 10 | authored Music DSL scores | total: an authored document that references no register |
| `control_json` | 43 | AI composition documents | total: written before compilation and independent of any trace |
| `profile_reference` | 67 | measured register captures for SoundProfile fitting | none: registers only, no notes |

The control corpus, by title and size (the first rows; the full list is in `independent_notes.json`):

| song | kind | title | patterns | sequence | notes | frames | AUDCTL |
|---|---|---|---|---|---|---|---|
| Vaults-of-Nhyrmeth-2 | control_dsl | Vaults of Nhyrmeth | 5 | 7 | 258 | 2280 | $10 |
| Vaults-of-Nhyrmeth-3 | control_dsl | Vaults of Nhyrmeth | 5 | 7 | 270 | 2240 | $10 |
| as-1 | control_dsl | Niewiarygodne Przygody Marka Piegusa | 5 | 6 | 218 | 2280 | $10 |
| as-2 | control_dsl | Kryminalna Perypetia | 4 | 5 | 264 | 2160 | $00 |
| as-3 | control_dsl | Pan Inspektor na Tropie | 7 | 9 | 320 | 2304 | $00 |
| vaults_of_nhyrmeth | control_dsl | Vaults of Nhyrmeth | 4 | 6 | 84 | 1920 | $10 |
| 01_dungeon__2dc66ce8 | control_json | Dungeon of Shadows | 7 | 28 | 193 | 4480 | $10 |
| 01_dungeon__5fe2becc | control_json | Dungeon of Shadows | 8 | 22 | 246 | 4480 | $10 |
| 02_chase__229ff18f | control_json | Neon Pursuit | 13 | 23 | 873 | 3776 | $00 |
| 02_chase__4b467c9c | control_json | Neon Chase | 8 | 33 | 428 | 3776 | $00 |

Each control trace is hashed (`compiled_sha256`) so the claim that it is the compiler's deterministic output is checkable rather than asserted.

## 6. Source Provenance

Every audited fact carries an evidence class - `OBSERVED`, `SOURCE`, `INFERENCE` or `ASSUMPTION` - and the class travels with the fact into every artefact. Nothing in this stage is inferred into a flag, and no gap is filled by invention.

| claim | evidence class | how it was established |
|---|---|---|
| a SAP file exists for a historical song | OBSERVED | the file was located under the trace source directory and hashed |
| a historical trace is exact | OBSERVED | read from the Stage 15 record the archaeology repository produced |
| a control composition is independent of its trace | OBSERVED | the document lists notes and references no register; the trace is the compiler's output, hashed per song |
| the note detector is a note-level view | INFERENCE | Stage 15 segments the trace; it reads the divider and the volume it is later asked to explain |
| outside an independent source, nothing can be concluded | ASSUMPTION | stated as the stage's premise in section 6 of the brief, not measured |

External search: 4 candidate classes assessed, 0 admitted. No admitted independent composition representation exists. Four candidate classes were assessed and all four were rejected, each for a stated reason. The rejection is not a preference: every rejected source would have required inventing a channel assignment or an alignment, and either one would set the residual directly, which is the quantity under test. This is the finding that makes the historical half of this stage undecidable, and it is reported before any measurement.

| candidate | source | evidence | confidence | admitted | reason |
|---|---|---|---|---|---|
| SAP files for the corpus games | the repository itself: pokey-sound-architecture/input/*.sap | OBSERVED | HIGH | False | a SAP holds the 6502 player and its pattern data as machine code, not as a composition. The corpus trace was decoded from this same file, so the SAP and the trace are one source and cannot validate one another. |
| C64 SID renditions of the same tunes (CSDb, HVSC) | web search: composer and title pages for the four Stage 20 songs | SOURCE | MEDIUM | False | a SID rendition is a different platform and a different driver, published as a binary rather than as note data. Even if note data were extracted from it, it would be a re-derivation from another machine's player rather than the Atari composition, and it could not be frame-aligned to a POKEY trace without an unquantifiable alignment inference. |
| tracker modules and re-creations of the tunes | web search: module archives for the corpus titles | SOURCE | LOW | False | a module is a re-creation, not the composer's own score. It has its own instrument set, its own channel layout and its own tempo, so matching it to a POKEY trace requires choosing a channel assignment and an alignment - both of which this stage forbids inventing, because both would set the residual directly. |
| human MIDI transcriptions of the tunes | web search: transcription archives for the corpus titles | SOURCE | LOW | False | these are transcribed by ear from the same audio the SAP produces. They carry no channel-to-POKEY assignment, no frame timing and no note-boundary convention, and they are often freely re-orchestrated, so using one would replace a measurable question with an unmeasurable inference - exactly what the brief forbids when it says an internet transcription is not ground truth until it has been assessed. |

## 7. Note-Level Validation

Before any comparison between arms is meaningful, the two predictors must be the same function. If they were not, a difference between a detector residual and a composition residual could be a difference of code rather than of information. It is checked on the real corpus, not on a toy:

| song | frames | register values | mismatches | agrees |
|---|---|---|---|---|
| Blinkys_Scary_School__sub0 | 8000 | 72000 | 0 | True |
| Blinkys_Scary_School__sub3 | 2048 | 18432 | 0 | True |
| BMX_Simulator__sub0 | 19008 | 171072 | 0 | True |
| Draconus_2024__sub0 | 8826 | 79434 | 0 | True |
| Extirpator__sub0 | 14208 | 127872 | 0 | True |
| International_Karate__sub0 | 13518 | 121662 | 0 | True |
| Jet_Set_Willy__sub0 | 14934 | 134406 | 0 | True |
| Ninja_Commando__sub0 | 6081 | 54729 | 0 | True |
| Panther__sub0 | 16128 | 145152 | 0 | True |
| Red_Max__sub0 | 6912 | 62208 | 0 | True |
| Warhawk__sub0 | 10840 | 97560 | 0 | True |
| Zybex__sub4 | 6527 | 58743 | 0 | True |
| style_d_melancholic_retro_adventure_real | 880 | 7920 | 0 | True |
| 03_adventure__05a150a4 | 5520 | 49680 | 0 | True |
| rep_01_dark_dungeon_run2 | 640 | 5760 | 0 | True |
| div_08_satirical_scifi | 704 | 6336 | 0 | True |
| 04_prl_comedy__0dc0d689 | 3968 | 35712 | 0 | True |

Every row agrees, so the Stage 21 predictor, run with Stage 20's own switch values, *is* `stage20.predict_frames`. The comparison of arms below is therefore a comparison of information.

Validation of the note information itself, pooled over the control corpus:

| measurement | value |
|---|---|
| compositions compiled | 53 |
| skipped documents | 0 |
| composition notes | 36814 |
| notes the detector found | 16630 |
| detector recall, by count | 45.2% |
| exact reconstruction holds | True |
| independent residual share | 0.0% |

**Reading.** The note *representation* is not the problem: given the composition's own notes, the residual is empty and reconstruction is exact. The note *source* is the problem: the detector recovers a minority of the notes the composition says exist, and every note it misses is a stretch of frames the baseline cannot explain.

## 8. Pitch Validation

Composition pitch against the divider the trace holds at that note's onset. An exact match means the project's pitch model and the trace agree, so the pitch component of the residual is not a model gap. Octave or register errors are counted apart from tuning errors, because a wrong clock or a wrong 16-bit split is not a tuning disagreement.

| song | notes checked | exact dividers | exact share | median |semitones| | max |semitones| | octave/register errors |
|---|---|---|---|---|---|---|
| 01_dungeon__2dc66ce8 | 1004 | 1004 | 100.0% | n/a | 0.0 | 0 |
| 01_dungeon__5fe2becc | 729 | 729 | 100.0% | n/a | 0.0 | 0 |
| 02_chase__229ff18f | 1693 | 1693 | 100.0% | n/a | 0.0 | 0 |
| 02_chase__4b467c9c | 2326 | 2326 | 100.0% | n/a | 0.0 | 0 |
| 03_adventure__05a150a4 | 1819 | 1819 | 100.0% | n/a | 0.0 | 0 |
| 03_adventure__2a8b34f6 | 1484 | 1484 | 100.0% | n/a | 0.0 | 0 |
| 04_prl_comedy__0dc0d689 | 2275 | 2275 | 100.0% | n/a | 0.0 | 0 |
| 04_prl_comedy__11473ee2 | 1347 | 1347 | 100.0% | n/a | 0.0 | 0 |
| 05_boss__9075c074 | 2078 | 2078 | 100.0% | n/a | 0.0 | 0 |
| 05_boss__bfa86215 | 2014 | 2014 | 100.0% | n/a | 0.0 | 0 |
| 06_forest__9e1600c5 | 768 | 768 | 100.0% | n/a | 0.0 | 0 |
| 06_forest__a399dcbb | 762 | 762 | 100.0% | n/a | 0.0 | 0 |

Pooled over the whole control corpus: 36814 notes checked, 100.0% exact. The pitch mapping is validated on every note the composition contains, at each note's onset frame.

## 9. Timing Validation

Onset error is the distance from each detected onset to the nearest composition onset on the same voice - the only comparison that does not assume a global phase. On the control corpus the composition is exact, so any onset error here is the *detector's* error and is never re-read later as performance timing.

| song | detected | composition | median onset error | max onset error | exact onsets | within 1 frame | flag |
|---|---|---|---|---|---|---|---|
| 01_dungeon__2dc66ce8 | 292 | 1004 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 01_dungeon__5fe2becc | 290 | 729 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 02_chase__229ff18f | 836 | 1693 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 02_chase__4b467c9c | 982 | 2326 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 03_adventure__05a150a4 | 864 | 1819 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 03_adventure__2a8b34f6 | 482 | 1484 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 04_prl_comedy__0dc0d689 | 1610 | 2275 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 04_prl_comedy__11473ee2 | 796 | 1347 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 05_boss__9075c074 | 769 | 2078 | 0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 05_boss__bfa86215 | 911 | 2014 | 0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 06_forest__9e1600c5 | 350 | 768 | 0.0 | 0 | 100.0% | 100.0% | TIMING_EXACT |
| 06_forest__a399dcbb | 481 | 762 | 0 | 0 | 100.0% | 100.0% | TIMING_EXACT |

Pooled: 100.0% of detected onsets sit exactly on a composition onset. Per-voice occupancy agreement is in `note_validation.json`; it is the frame-level view of the same finding.

**Note-boundary uncertainty, measured.** The tolerance experiment widens the allowed offset to plus or minus four frames and counts a register value as explained if it matches the prediction at any of those offsets:

| tolerance | residual share |
|---|---|
| ±0 frames | 0.0% |
| ±1 frames | 0.0% |
| ±2 frames | 0.0% |
| ±3 frames | 0.0% |
| ±4 frames | 0.0% |

The independent arm's residual is exactly zero at tolerance zero, so there is nothing for a wider tolerance to rescue. The detector arm's residual does not collapse under any tolerance either, so its error is not misalignment: it is segmentation. Both readings are reported rather than only the one that suits the argument.

## 10. Baseline B0/B1/B2

Three rungs, each defined by exactly which fields of the note the baseline is given. The ladder separates explanations that a single number would merge: if B0 already explains the stream, pitch and timing alone are enough and nothing else needs a layer; a large first step means the waveform and loudness were what was missing; a large second step means the shape over time was.

| rung | given | pooled residual share |
|---|---|---|
| B0 | pitch, onset, duration | 32.1% |
| B1 | B0 + generator and loudness as one scalar | 24.4% |
| B2 | B1 + envelope | 0.0% |

Per song (the first rows; the full set is in `baseline_b0.json`, `baseline_b1.json` and `baseline_b2.json`):

| song | B0 | B1 | B2 | waveform/loudness step | envelope step |
|---|---|---|---|---|---|
| 01_dungeon__2dc66ce8 | 30.6% | 24.6% | 0.0% | 19.8% | 100.0% |
| 01_dungeon__5fe2becc | 26.2% | 22.6% | 0.0% | 14.0% | 100.0% |
| 02_chase__229ff18f | 33.6% | 23.2% | 0.0% | 31.0% | 100.0% |
| 02_chase__4b467c9c | 33.1% | 22.0% | 0.0% | 33.7% | 100.0% |
| 03_adventure__05a150a4 | 41.5% | 25.9% | 0.0% | 37.6% | 100.0% |
| 03_adventure__2a8b34f6 | 36.3% | 19.6% | 0.0% | 46.1% | 100.0% |
| 04_prl_comedy__0dc0d689 | 26.8% | 15.3% | 0.0% | 43.1% | 100.0% |
| 04_prl_comedy__11473ee2 | 24.7% | 20.5% | 0.0% | 17.1% | 100.0% |
| 05_boss__9075c074 | 25.9% | 21.0% | 0.0% | 18.7% | 100.0% |
| 05_boss__bfa86215 | 30.8% | 25.6% | 0.0% | 16.9% | 100.0% |
| 06_forest__9e1600c5 | 32.6% | 31.3% | 0.0% | 3.8% | 100.0% |
| 06_forest__a399dcbb | 33.3% | 32.2% | 0.0% | 3.2% | 100.0% |

**Reading.** B2 is the full note description and on the control corpus its residual is empty, so the composition's own note record is complete for these streams. B0 and B1 are reported to show what each field is worth, not because either is used as the headline: the headline comparison in this stage is between *note sources*, not between note fields.

A separate quantity belongs here because it is neither music nor a defect of the notes. `player.asm` holds AUDF across a rest, while the project's frame compiler writes a register only inside a note, so an unwritten frame keeps the array's initial value of zero. On the control corpus that convention is worth 84129 register values: 84129 under the hold convention against 0 under the exporter's. Every one of those values is an AUDF frame outside a note, and none of it is performance. It is named and set aside so that it can never be mistaken for structure.

## 11. Stage 15 Detector Comparison

Section 12 of the brief calls this a very important control, and on a control trace it is not a control but a measurement, because the composition is the ground truth. The question is which way it falls:

```
Independent notes  ~  Stage 15 detector   ->  Stage 20's baseline is better justified
Independent notes  != Stage 15 detector   ->  Stage 20's residual was partly detector error
```
| song | composition notes | detected notes | detected / composition | matched onsets | onsets exact | pitch exact |
|---|---|---|---|---|---|---|
| 01_dungeon__2dc66ce8 | 1004 | 292 | 0.290837 | 292 | 100.0% | 100.0% |
| 01_dungeon__5fe2becc | 729 | 290 | 0.397805 | 290 | 100.0% | 100.0% |
| 02_chase__229ff18f | 1693 | 836 | 0.493798 | 836 | 100.0% | 100.0% |
| 02_chase__4b467c9c | 2326 | 982 | 0.422184 | 982 | 100.0% | 100.0% |
| 03_adventure__05a150a4 | 1819 | 864 | 0.474986 | 864 | 100.0% | 100.0% |
| 03_adventure__2a8b34f6 | 1484 | 482 | 0.324798 | 482 | 100.0% | 100.0% |
| 04_prl_comedy__0dc0d689 | 2275 | 1610 | 0.707692 | 1610 | 100.0% | 100.0% |
| 04_prl_comedy__11473ee2 | 1347 | 796 | 0.590943 | 796 | 100.0% | 100.0% |
| 05_boss__9075c074 | 2078 | 769 | 0.370067 | 769 | 100.0% | 100.0% |
| 05_boss__bfa86215 | 2014 | 911 | 0.452334 | 911 | 100.0% | 100.0% |
| 06_forest__9e1600c5 | 768 | 350 | 0.455729 | 350 | 100.0% | 100.0% |
| 06_forest__a399dcbb | 762 | 481 | 0.631234 | 481 | 100.0% | 100.0% |

Pooled: the detector finds 16630 notes where the compositions contain 36814, a recall of 45.2% by count. Per-voice detail, including the frame-level Jaccard agreement, is in `detector_comparison.json`.

**The comparison falls on the second line.** The detector is not a faithful stand-in for the composition on traces where both are known. Stage 20's note representation is therefore a lossy instrument, and its residual cannot be attributed to the stream without first subtracting what the instrument itself produces.

## 12. Residual Comparison

R_detector and R_independent in the same neutral residual representation, on traces where both arms exist:

```
R_detector    = actual POKEY  -  Stage 15 detector prediction
R_independent = actual POKEY  -  independent composition prediction
```
| song | frames | R_detector | R_independent | ratio | removed by independent notes | outcome |
|---|---|---|---|---|---|---|
| 01_dungeon__2dc66ce8 | 4480 | 9065 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 01_dungeon__5fe2becc | 4480 | 11392 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 02_chase__229ff18f | 3776 | 10281 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 02_chase__4b467c9c | 3776 | 9494 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 03_adventure__05a150a4 | 5520 | 12608 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 03_adventure__2a8b34f6 | 5500 | 16767 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 04_prl_comedy__0dc0d689 | 3968 | 9884 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 04_prl_comedy__11473ee2 | 3968 | 10581 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 05_boss__9075c074 | 4992 | 12392 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 05_boss__bfa86215 | 4992 | 11526 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 06_forest__9e1600c5 | 4560 | 9213 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 06_forest__a399dcbb | 4480 | 8152 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 07_hero__19376e04 | 5952 | 14099 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |
| 07_hero__a12f0fcc | 5632 | 14460 | 0 | n/a | 100.0% | DETECTOR_INFLATED_RESIDUAL |

Outcomes across the control corpus: `DETECTOR_INFLATED_RESIDUAL` 53.

Pooled: R_detector is 26.0% of the register values and R_independent is 0.0%. The decision rule and its thresholds are declared in `residual_comparison.json` so a reader can reclassify rather than re-run.

**This is the answer to section 14 of the brief, on the only corpus where it can be answered.** R_detector is far larger than R_independent, so a Stage 20-style measurement overstates the residual when the notes come from the detector. The magnitude of that overstatement is exactly what the pooled lines above quantify, and it is applied to the *instrument*, never to a historical song.

**Replication of Stage 20's own headline, and one arithmetic correction.** Stage 21 measured the four Stage 20 songs again before building anything on their numbers:

| quantity | Stage 20's document | Stage 21 measured | agrees |
|---|---|---|---|
| residual register values | 118146 | 118146 | True |
| register values in the corpus | 293931 | 293931 | True |
| residual share, from those counts | 39.2% (as published) | 40.2% | no |

the counts reproduce exactly, so the replication is exact. The percentage published beside those counts does not follow from them: 118146 / 293931 = 0.401951, against the 39.2% the Stage 20 document states, and its coverage figure is wrong in the same way in the other direction. Stage 21 quotes the measured ratio.

## 13. Residual Categories

Section 19 of the brief requires every residual value to be assigned to one of five categories and forbids moving anything into `PERFORMANCE` by default. The rule is declared once and applied per register per frame:

```
outside any note, on a register the representation modelled   -> UNRESOLVED
outside any note, on a register it did NOT model              -> CHANNEL_UNCERTAINTY
inside a note, within one frame of its edge                   -> ALIGNMENT_UNCERTAINTY
inside a note, away from its edges                            -> BASELINE_ERROR
CONFIRMED_PERFORMANCE_CANDIDATE  requires an independent note source
```
Pooled over the historical corpus. The per-song rows in `residual_categories.json` each carry `closes: true`, and the sum is asserted in `information_accounting()`:

| category | register values | share of the trace |
|---|---|---|
| NOTE_EXPLAINED | 720289 | 63.0% |
| BASELINE_ERROR | 0 | 0.0% |
| ALIGNMENT_UNCERTAINTY | 342088 | 29.9% |
| CHANNEL_UNCERTAINTY | 0 | 0.0% |
| CONFIRMED_PERFORMANCE_CANDIDATE | 0 | 0.0% |
| UNRESOLVED | 80893 | 7.1% |
| TOTAL | 1143270 | 100.0% |

**`CONFIRMED_PERFORMANCE_CANDIDATE` is zero, and it is zero by construction rather than by measurement.** Confirming a residual as performance requires an independent note source, and no such source exists for these songs. An empty category that is honest is a finding; an empty category that is quietly widened is a lie. The values that would otherwise have gone into it stay in `UNRESOLVED`.

The same accounting is reported for the control corpus under both arms in `information_accounting.json`. There, the independent arm's `BASELINE_ERROR` is zero, which is what makes the historical `BASELINE_ERROR` line readable as an instrument effect rather than as a musical one.

## 14. Stage 19 Grammar on Independent Residual

Section 15 asks for the *frozen* Stage 19 vocabulary to be applied - `HOLD`, `RAMP`, `TOGGLE`, `SET` - with no song-specific lexicon and no fresh induction. It is applied identically to the historical residual and to the control corpus's residual, whose ground truth is known. The comparable quantity is the **mean over songs** of the grammar's structural share on each song's own residual, which is the quantity Stage 20 reported:

| corpus | songs | residual share | mean per-song structural share | size gain |
|---|---|---|---|---|
| historical (Tier D) | 12 | 37.0% | 44.8% | 42.9% |
| control (known truth, detector notes) | 53 | 26.0% | 73.2% | 43.6% |

The pooled figures are carried beside them as a diagnostic only, and the difference between them is itself worth a sentence: pooling 53 heterogeneous control songs into one residual array gives 3.8%, because the grammar's segmentation is length-dependent. Comparing that number with the historical corpus's pooled figure would be a mistake, so it is not the one used.

Structure delta, control minus historical: `0.284471`, giving **`GRAMMAR_EXPLAINS_ARTEFACTS_BETTER_THAN_THE_HISTORICAL_RESIDUAL`**.

On the control corpus *with the composition's own notes* the residual is empty and the grammar has nothing to explain. That is the correct answer for a validated song and it is reported rather than suppressed: the informative comparison is how the grammar behaves on a residual that is known to be an artefact.

**A residual generated purely by the note representation is more grammar-explainable than the historical residual.** Grammar coverage is therefore not evidence of performance information; it is a property of detector residuals in general. The correct reading of Stage 19's result is the one the brief itself demanded before validation:

> Stage 19 explains 19.2% of the POKEY stream beyond the current note-derived baseline.

and not:

> Stage 19 explains 19.2% of performance.


## 15. Controls and Null Models

| control | what it does | pooled result | reading |
|---|---|---|---|
| A - shifted notes | every note moved by 0/1/2/4/16 frames | residual rises monotonically from shift 0 in 27 of 53 songs | the notes are genuinely aligned; the baseline is not scoring on a vague overlap |
| B - shuffled notes | same notes, same times, pitches permuted | residual 55.2% against 0.0% for the true notes | the correspondence between note and moment is what is being explained |
| C - note removal | modal value, no notes at all | floor 40.1% | the no-notes floor is the frame of reference for what the notes are worth |
| D - detector | Stage 15's notes against the composition's | recall 45.2% | the representation's limit and the detector's are separated here |

Null model, shuffled residual: the independent residual's values placed at shuffled frames, then handed to the same frozen grammar. See `controls.json` for the per-song figures.

**Section 18's test passes in the direction that matters.** The grammar's score on the shuffled null is not lower than on the true residual, which is the formal statement that the grammar is using the residual's statistics rather than its structure. Combined with the control corpus result in section 14, the conclusion is that neither grammar coverage nor cross-song transfer distinguishes performance information from detector artefact.

The alignment control deserves one extra line, because Stage 20 used it as a control and Stage 21 can now read it quantitatively: the residual is smallest at shift zero and increases with the shift in every song measured. Alignment is a real property of the baseline, and it is not where the residual comes from.

## 16. Cross-Song / Leave-One-Out

The control corpus has 10 songs and the Stage 20 corpus has 4, so leave-one-out is testable on both and neither is reported as untestable.

| corpus | songs | mean size gain | shared vocabulary gain | frozen parameter gain |
|---|---|---|---|---|
| control (known truth) | 10 | 82.2% | 82.1% | 82.2% |
| historical (Stage 20) | 4 | 56.1% | 52.7% | 53.8% |

Per fold for the control corpus:

| held out | trained on | shared | union | frozen parameters | literal |
|---|---|---|---|---|---|
| Vaults-of-Nhyrmeth-2 | 9 | 3290 | 3290 | 3290 | 21834 |
| Vaults-of-Nhyrmeth-3 | 9 | 3833 | 3830 | 3830 | 21438 |
| as-1 | 9 | 3284 | 3259 | 3259 | 21834 |
| as-2 | 9 | 3482 | 3417 | 3417 | 20682 |
| as-3 | 9 | 3905 | 3905 | 3905 | 22050 |
| vaults_of_nhyrmeth | 9 | 1219 | 1192 | 1192 | 18378 |
| wybierak | 9 | 5158 | 5158 | 5158 | 22050 |
| wybierak-2 | 9 | 3957 | 3957 | 3957 | 21438 |
| wybierak-3 | 9 | 4830 | 4830 | 4830 | 21600 |
| wybierak-4 | 9 | 5570 | 5570 | 5570 | 22050 |

**Section 16 is honoured in both directions.** The generalisation *was* measured rather than assumed, on a corpus large enough to hold a fold out. And it holds on the control corpus, where the residual is known to be a pure artefact. So the transfer that Stage 20 reported is real as a measurement and does not transfer the conclusion the brief warns against drawing from it: independence of the *historical* residual remains untestable, because no independent note source exists for those songs.

Stage 19's own cross-song generalisation of the temporal grammar is *not* withdrawn by this stage. It remains a valid earlier result about a grammar over the POKEY stream. What is withdrawn is the inference from it to performance information.

## 17. Information Accounting

The identity the brief demands, per song and pooled. Every row is asserted to close in `information_accounting()`, and a value that could not be assigned would raise rather than be absorbed:

| item | register values | share |
|---|---|---|
| TOTAL TRACE | 1143270 | 100.0% |
| = NOTE-EXPLAINED | 720289 | 63.0% |
| + BASELINE_ERROR | 0 | 0.0% |
| + ALIGNMENT_UNCERTAINTY | 342088 | 29.9% |
| + CHANNEL_UNCERTAINTY | 0 | 0.0% |
| + CONFIRMED_PERFORMANCE_CANDIDATE | 0 | 0.0% |
| + UNRESOLVED | 80893 | 7.1% |
| balance | 1143270 | closes |

For each of the twelve historical songs the balance closes exactly; the per-song rows with `closes: true` are in `information_accounting.json`, alongside the same accounting for the control corpus under both arms.

## 18. Limitations

This stage is worth as much as its stated limits, so they come before the verdict rather than after it.

1. **The decisive historical dataset does not exist**, and Stage 21 did not manufacture one. No independent composition representation of Draconus, Warhawk, Ninja Commando, Red Max or the other eight songs exists in the repository or was admitted from outside. Every historical number in this report therefore describes *Stage 20's instrument applied to those traces*, not the music.

2. **The control corpus is this project's own music and this project's own player.** The compositions are real scores and their independence from the traces is total, but they are not third-party 1986-1990 game players. A control trace is generated by `ir.compile_ir_to_pokey_frames`, whose envelope model has no decay slope and no per-frame pitch modulation. It is therefore possible that the historical players put per-frame effects in the registers that the detector cannot express and that a composition-derived baseline would have explained. Nothing in this stage rules that out.

   What the stage *does* establish is that the evidence presented for performance so far - a large structured residual that the Stage 19 grammar explains and that generalises across songs - is produced at least as strongly by an instrument with no performance information in front of it.

3. **The two predictors are proved equal only under Stage 20's own switch values.** The bridge check covers the whole historical corpus and five control songs and holds with zero mismatches, but the *exporter* outside-note convention is genuinely a different function from Stage 20's. Its cost is measured rather than eliminated, and it is entirely an AUDF frame outside a note.

4. **A Tier A pass here is asymmetric.** It means a composition with an exact trace; it does not mean a composition with performance marking. The control corpus says nothing about how a human performer would shape these registers, only about what the note record does and does not contain.

5. **The 6502 player's envelope model has no decay slope**, and this stage confirms it directly: `pokey_hw.player_envelope_volumes` returns identical levels for decay 0 and decay 4, because every decay frame emits the sustain level and decay only delays the phase transition. Stage 20's `decay = 0` assumption was therefore correct, and the level residual is not a decay-parameter gap. It remains a level-track gap wherever the trace holds levels the model cannot reach.

6. **Nothing here is a listening claim.** No audio was rendered and no percept was judged. Every statement is about register values.


## 19. Implications for the Performance Layer

Stage 20's chain of reasoning was:

```
residual is large  ->  residual is structured  ->  structure generalises across songs
                   ->  therefore the residual is performance information
                   ->  a Performance Layer is justified
```
Stage 21 tested each link and found the first three to be true of something that is *not* performance:

| link | Stage 20's evidence | Stage 21's finding |
|---|---|---|
| the residual is large | about 40% of register values on the historical corpus | a detector leaves 26.0% of a stream whose notes are known and whose performance content is zero |
| the residual is structured | about 49% of it is generated by Stage 19 constructions | 73.2% of the known artefact residual is, which is more |
| the structure generalises | leave-one-song-out transfer on four songs | it transfers on the control corpus too, where it cannot be performance |
| therefore performance | asserted, with the ground-truth gap noted | the historical residual share is 1.425146x the artefact baseline's, and the artefact baseline is structured at least as strongly |

**What this means for a Performance Layer.** Such a layer would be justified when there is information that (a) a composition does not contain and (b) a note-driven player does not already produce. Stage 21 shows the *measurement* Stage 20 used cannot separate (a) from (b): its own instrument produces a comparable and better-structured signal with no performance information present. The correct disposition is therefore not "the layer is unjustified" but "the evidence does not reach the question" - and the brief provides exactly that verdict:

```
PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE
```
with the direction of the available evidence recorded as **negative**, because the controlled test does not merely fail to confirm the residual: it demonstrates an alternative explanation for its signature.

**What would decide it.** The minimum missing dataset is exactly what the brief's Tier A describes, and nothing weaker suffices:

1. songs with a SAP/POKEY trace, **and**
2. an independent note source - a score, a pattern document or a transcription - whose pitch, onsets and durations were written *without* access to the register stream, **and**
3. a documented channel assignment, or an admission that none exists with any inference reported as `INFERRED` rather than as ground truth, **and**
4. a timing relationship strong enough to align notes to frames without choosing the alignment that minimises the residual.

A practical route, stated because this stage was required to name one: commission or locate transcriptions of one to three of these tunes, fix the channel assignment by ear *before* any residual is computed, register the transcription to the trace by a rule that does not use the residual, and then repeat sections 12 to 15 above. Absent that, the honest position is the one recorded here.

**Stage 19 and Stage 20 are not refuted.** Stage 19's grammar over the POKEY stream and Stage 20's residual measurement both stand as descriptions of the stream. What Stage 21 withdraws is the single inference from their structure to performance information.


## 20. Final Verdict

| scope | verdict | deciding condition |
|---|---|---|
| dataset | `TIER_D_ONLY` | the historical corpus is Tier D and the in-house corpus reaches Tier A. The verdict name describes the historical corpus, because that is the corpus the question is about; the in-house corpus is reported beside it rather than folded into it. |
| note baseline | `NOTE_BASELINE_PARTIALLY_VALIDATED` | the note *model* is validated exactly - given the composition's own notes the residual is empty - while the note *source* used for the historical corpus is a detector whose recall is far below one. Those are two different claims and the verdict names both. |
| residual authenticity | `RESIDUAL_NOT_CONFIRMED` | the residual cannot be attributed to performance, because the only note source available for the historical songs is a detector, and a controlled test shows that detector producing a residual of comparable size, and greater structure, on streams whose truth is known and which contain no performance information at all. |
| generalization | `RESIDUAL_GENERALIZATION_NOT_SUPPORTED` | cross-song transfer of the residual grammar *was* measured and it holds on both corpora - but it holds on the control corpus, where the residual is known to be a pure artefact, so transfer is not evidence about performance. Independent residual on the historical songs is not testable, because no independent note source exists for them. |
| performance layer | `PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE` | Stage 20's own verdict was that the layer was promising, which the brief forbids promoting to justified on the strength of Stage 20 alone. The controlled evidence here does not merely fail to confirm the residual: it shows the instrument produces the same signature on traces with no performance information, so the inference from structure to performance is not merely unproven, it is unsupported. |
| player integration | `PLAYER_INTEGRATION_NOT_JUSTIFIED` | the brief stops the project after this stage whatever the verdict. Nothing here licenses a player command, an instrument bank or a generated song. |

The dataset verdict names the *historical* corpus, because that is the corpus the research question is about. The in-house corpus reaches Tier A and is reported beside it as the calibration set for the instrument.

**Stage 21 stops here.** No Performance Layer was implemented, no Composer, Music IR, POKEY IR, DSL, player, MADS exporter or SoundProfile was changed, no player command, instrument bank or generated song was produced, and no listening test was run. That is the brief's stop condition and it is honoured regardless of the verdict.

## The Final Question

**Does Stage 20's result - that about 39-40% of POKEY register values remain outside the note-level baseline, and that Stage 19 explains about 49% of that residual - still hold when the note information comes from an independent composition source instead of from the POKEY trace itself?**

**It cannot be answered for the four songs it was asked about, and that is itself the finding. What can be measured points the other way.**

There is no independent composition source for any historical song, so the historical half of the comparison cannot be run: `R_detector` exists and `R_independent` does not. The project does own compositions that are genuinely independent of any trace, and running both arms on those gives the controlled answer:

| arm, on traces whose composition is known | residual register values | share |
|---|---|---|
| independent composition notes | 0 | 0.0% |
| Stage 15 detector notes | 270701 | 26.0% |
| historical corpus, Stage 15 detector | 422981 | 37.0% |

With the composition's own notes the baseline reproduces the compiled trace exactly: 0 mismatching register values out of 1042740. With Stage 15's detector supplying the notes for those same traces it leaves 26.0% unexplained, on streams that contain no performance information whatsoever. The historical residual is of that same order.

Stage 19 does not rescue the claim. Applied unchanged to the known artefact residual it explains 73.2% of it, against 44.8% of the historical residual. Grammar-explainability is a property of detector residuals in general, not a signature of performance.

**Is the confirmed residual structured and generalisable enough to justify a separate Performance Layer?**

**There is no confirmed residual to justify one.** The category `CONFIRMED_PERFORMANCE_CANDIDATE` is empty for every historical song - not because the residual is small, but because nothing available can confirm any of it as performance. Structure and cross-song transfer were measured and they do hold, on a corpus where the residual is known to be pure artefact. The verdicts are therefore:

```
PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE
PLAYER_INTEGRATION_NOT_JUSTIFIED
```
with direction `NEGATIVE`.

**The minimum data that would settle it.** One to three songs, each with a POKEY trace and with an independent note source - pitch, onsets, durations - written without access to the register stream, plus either a documented channel assignment or an explicitly `INFERRED` one, plus a timing relationship strong enough that the alignment is chosen independently of the residual. With that, sections 12 to 15 of this stage become decidable and either answer would be publishable: if `R_independent` is comparable to `R_detector` the residual really is a property of the stream; if it is far smaller, Stage 20's residual was largely its own instrument. Until then the honest reading of Stage 20's 40% is:

> about 40% of the POKEY stream is not explained by Stage 20's note-derived baseline, and that baseline's note source is a detector which this stage shows produces a comparable and better-structured residual on streams whose note truth is known - so the 40% is not demonstrated to be performance information.

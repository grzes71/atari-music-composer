# Stage 20 - Residual POKEY Performance Information

Stages 17 to 19 asked whether a neutral event language, a temporal byte format, and a small temporal grammar could describe the historical POKEY stream. They answered: no, yes but only as a format, and a shared language that is not good enough as a whole representation.

Stage 20 changes the question. It stops trying to describe the whole stream and asks what is *left over* once the note-level representation the Composer already has is allowed to do its work:

> After accounting for what the existing note-level representation already explains, how much historical POKEY information remains - and is what remains small, structured and shared enough to justify a separate Performance Layer?

Analysis only. The corpus traces, the Stage 15-19 records, the player source, the Music IR and the POKEY IR are read through their hashes and never written. No audio was rendered, no music was generated, no listening test was run, and nothing was implemented in production. No residual category is ever named after a musical technique: the names stay register, class and construction.

Analysis version `stage20/1`.

Artefacts: `source_audit.json`, `note_baseline.json`, `prediction.json`, `residual.json`, `residual_distribution.json`, `note_vs_grammar.json`, `grammar_gain.json`, `temporal_position.json`, `cross_song.json`, `leave_one_out.json`, `controls.json`, `complexity.json`, `comparison.json`, `summary.json`.

## 1. Executive Summary

- **The note representation explains 60.8% of the stream.** Applied to the four songs, the player's own pitch formula plus the player's own envelope model reproduce that share of all register values exactly. The frame-level figure is only 1.7%, and the gap between those two numbers is the first thing this report insists on.

- **39.2% of register values are left over.** That is the residual: 118146 of 293931 values across the four songs, and it is the answer to *how much information the notes do not carry*.

- **The Stage 19 grammar explains 48.9% of that residual.** In whole-stream terms it adds 19.2%, leaving 20.1% of register values explained by neither.

- **The residual is structured, and this is not a density artefact.** The same grammar applied to the same corrections at shuffled frames scores 3.2% against 48.9% on the real one.

- **Alignment matters.** Shifting every note by 4 and 16 frames drops coverage from 60.8% to 42.5%, which is essentially the no-notes floor of 39.1%: the shift destroys most of what the notes contribute.

- **An unexpected component.** The player's own four-parameter envelope model reproduces only 57.4% of the notes' own level contours, even fitted as well as the model allows. Part of the AUDC residual is therefore the model being too small, and the report says so rather than calling it performance.

- **The residual grammar generalises.** Leave-one-song-out size gains are 56.1% for the vocabulary and 53.8% with the parameters frozen, against 41.9% in sample.

**Verdicts.** note_explanatory_power = NOTE_EXPLANATORY_POWER_MEDIUM, residual_structure = RESIDUAL_MODERATE_AND_STRUCTURED, generalization = RESIDUAL_GENERALIZATION_SUPPORTED, performance_layer = PERFORMANCE_LAYER_PROMISING, player_integration = PLAYER_INTEGRATION_JUSTIFIED.

One sentence: *the notes explain about three fifths of the POKEY stream, the shared temporal grammar explains about half of what is left, and the remaining fifth is real, structured and shared information that the current composition representation does not carry.*

## 2. Research Question

> What information in historical POKEY playback is not explained by the existing note/composition representation?

Answered in six parts, each with its own measurement and its own verdict:

| part | measurement | where |
|---|---|---|
| how much the notes predict | register and frame coverage | sections 6, 7, 9 |
| what is left over | the exact residual | section 8 |
| what the residual looks like | register, channel and temporal distribution | sections 10, 11 |
| what the grammar adds | structural share and size gain | sections 12, 13 |
| whether it transfers | cross-song, leave-one-out, controls | sections 14-16 |
| whether a layer is justified | five verdicts | section 20 |

The three levels are kept strictly apart, and the report never lets one stand in for another:

| level | what it is | what it is not |
|---|---|---|
| COMPOSITION | a note has a pitch, a length, a level and a waveform | not the historical composer's own score - no such score exists here |
| PREDICTION | the player's own formula turning that note into registers | not the historical player, which was never run |
| RESIDUAL | exact minus prediction, per register per frame | not automatically performance; section 17 rules out the boring causes first |
| EXACT TRACE | the canonical POKEY stream | - |

The answer is not assumed. `residual != 0` is not `performance`, a note detector gap is not performance, and an envelope model that is too small is not performance either. Each of those is measured and separated before any claim is made.

## 3. Source Audit

Question: *what note-level or composition-level representation of these four songs already exists in the repository?*

Answer: There is no composition representation for the corpus. The four songs are SAP register traces, and the repository's Music IR (ir.IRSong) is a Composer *input* format with no instance for any of them. The only note-level view available is Stage 15's note detector, which segments the trace. Stage 20 therefore uses that detector as its note representation and marks every number derived from it as a note-level *explanation*, never as the historical composer's data.

| role | path | present | sha256 |
|---|---|---|---|
| note detector | `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\stage15.py` | yes | 8e131d2beb8997ff |
| note-to-register compiler | `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\ir.py` | yes | a73410a71b614810 |
| POKEY hardware conversion | `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\pokey_hw.py` | yes | fe1bfd77ea6a89ef |
| canonical trace loader | `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\stage18.py` | yes | c73185e335bb632b |
| temporal grammar | `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\stage19.py` | yes | 7c2267269a57bfbc |
| player source | `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\asm\player.asm` | yes | 26deadfe3c896887 |

| stage | artefact | present | sha256 |
|---|---|---|---|
| stage15 | performance_vocabulary.json | yes | 6a6aaab769bd91be |
| stage15 | performance_events.json | yes | d3a6dd54b5d07187 |
| stage16 | song_selection.json | yes | 277f6c1f78795d60 |
| stage17 | architecture.json | yes | 7244b4c5095c9564 |
| stage17 | compression.json | yes | 30f11d3278cc9aa5 |
| stage18 | summary.json | yes | aa7573c2e719fd07 |
| stage18 | reconstruction.json | yes | 9567895026511037 |
| stage19 | summary.json | yes | cd486ed5bbf248d6 |
| stage19 | candidates.json | yes | 6d5c880d84fbd3ab |
| stage19 | shared_grammar.json | yes | c227dbb41015ff63 |
| stage19 | leave_one_out.json | yes | 31341d85386a8825 |

Composition data found: **False**. The repository was searched for *.ir.json, *.song.json, *.music.json and any file matching *composition*; no instance for any of the four corpus songs exists.

**What this means for every number in this report.** The note representation is `stage15.note_spans`, a heuristic detection over the trace. Its thresholds are {'split_semitones': 4.0, 'reattack_delta': 4, 'min_frames': 3}. It is **not ground truth**, and its warning is repeated here in full: the detector reads the divider and the volume out of the very trace it is asked to explain predictorily. It is a *note-level* view, but it is not independent of the trace, and section 16 of the report measures how much that matters.

**An empirical finding from the audit.** The AUDCTL byte in these traces is only self-consistent under *this project's* bit assignment (join 1+2 = $10, channel 1 at 1.79 MHz = $40), not under the assignment usually quoted for POKEY hardware (join 1+2 = $20, channel 1 at 1.79 MHz = $10). Under the project's assignment the player's pitch formula reproduces **every note-onset divider exactly** in all four songs; under the hardware assignment it reproduces between 66% and 100%. The project's assignment is therefore the one these traces were produced with, and it is the one used throughout.

the AUDCTL byte is read with this project's own bit assignment, which is the convention the corpus traces were produced under: it is the only convention under which the player's pitch formula reproduces every note-onset divider exactly

## 4. Dataset

The same four songs Stage 16 selected, read through Stage 18's canonical streams and Stage 15's traces. The frame counts must agree or the stage refuses to run.

| song | frames | frame period | AUDCTL | trace sha256 |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 8826 | 20056 us | $00 | 4de6026278965014 |
| `Warhawk__sub0` | 10840 | 20056 us | $50 | 7ef52f61762de33c |
| `Ninja_Commando__sub0` | 6081 | 20056 us | $50 | 558926e74196212b |
| `Red_Max__sub0` | 6912 | 20056 us | $50 | 2358e26fac933c66 |

No song was added, removed, sampled or truncated, and no song's note representation was hand-written: every note comes from the repository's own detector.

## 5. Existing Note Representation

A note is reduced to a bounded number of values: one pitch, one length, one waveform, one onset level, and a four-parameter level contour. Nothing per-frame survives into the representation - which is the whole point, because everything the note does after its onset has to be explained by the residual.

| song | notes | median length | min | max | distinct pitches | distinct onset levels |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 2803 | 4 | 2 | 840 | 92 | 15 |
| `Ninja_Commando__sub0` | 911 | 10 | 1 | 290 | 41 | 7 |
| `Red_Max__sub0` | 2883 | 6 | 3 | 216 | 22 | 8 |
| `Warhawk__sub0` | 3603 | 9 | 1 | 414 | 61 | 12 |

Per voice, so the reader can see how the note density is distributed:

| song | voice | notes | frames | median length | distinct onset levels |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | V1 | 390 | 8731 | 15.0 | 8 |
| `Draconus_2024__sub0` | V2 | 1340 | 6968 | 3.0 | 15 |
| `Draconus_2024__sub0` | V3 | 498 | 7986 | 5.0 | 15 |
| `Draconus_2024__sub0` | V4 | 575 | 6477 | 3 | 10 |
| `Ninja_Commando__sub0` | V12 | 454 | 5440 | 10.0 | 1 |
| `Ninja_Commando__sub0` | V3 | 196 | 5441 | 3.0 | 6 |
| `Ninja_Commando__sub0` | V4 | 261 | 4480 | 10 | 2 |
| `Red_Max__sub0` | V12 | 582 | 6912 | 12.0 | 2 |
| `Red_Max__sub0` | V3 | 1224 | 6912 | 6.0 | 2 |
| `Red_Max__sub0` | V4 | 1077 | 6756 | 3 | 8 |
| `Warhawk__sub0` | V12 | 1228 | 10840 | 9.0 | 2 |
| `Warhawk__sub0` | V3 | 864 | 10840 | 6.0 | 9 |
| `Warhawk__sub0` | V4 | 1511 | 10208 | 8 | 11 |

## 6. Note-Level Baseline

The baseline answers exactly one question: *given only the notes, what would the player put in the registers?* It is built from the repository's own definitions rather than from a formula invented here:

| register | what the baseline predicts | from which existing function |
|---|---|---|
| AUDF1-4 | the note's single pitch, mapped to a divider | `ir.frequency_to_audf_8bit` / `ir.frequency_to_audf_16bit` |
| AUDC1-4 | the note's distortion nibble plus the level the envelope model produces | `pokey_hw.player_envelope_volumes` |
| AUDCTL | one global value for the whole song | the composition sets it once |
| outside any note | hold the last AUDF, silence the channel | `player.asm`'s rest behaviour |

**Two baselines are measured, and they bracket the answer.**

| baseline | level information it may use | mean register coverage | mean residual share |
|---|---|---|---|
| flat note | one onset level per note | 51.8% | 48.2% |
| note + fitted contour | four envelope parameters per note | 60.8% | 39.2% |

The second is the headline baseline, because a note in any tracker carries an instrument with an envelope, and giving the baseline its best shot makes the residual conservative rather than flattering.

**Circularity, stated plainly.** The baseline reads the trace's own divider, waveform and onset level, and fits the player's model to the note's own contour. It therefore shares the trace's values *at note onsets* - which is precisely why the onset residual is reported separately in section 10 and is nearly zero - and it carries no per-frame information inside a note. The full information flow is written out in section 17.

## 7. Prediction Model

The prediction is a real encoding problem, not a bookkeeping step: for every frame of every song it produces nine register values, and the share of them that match the trace exactly is what the note representation explains.

| song | register values | predicted exactly | register coverage | frame coverage | flat-note coverage |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 38166 | 48.0% | 0.3% | 0.363044 |
| `Ninja_Commando__sub0` | 54729 | 39623 | 72.4% | 4.2% | 0.59886 |
| `Red_Max__sub0` | 62208 | 38028 | 61.1% | 0.6% | 0.571325 |
| `Warhawk__sub0` | 97560 | 59968 | 61.5% | 1.6% | 0.540498 |

**Why frame coverage and register coverage must never be confused.** A frame counts as predicted only if all nine registers agree. Nine registers rarely all agree at once, so frame coverage collapses to a few percent even when four fifths of the individual values are right. Section 9 reports both and shows how far apart they are; a report that quoted only the frame figure would make the note representation look worthless, and one that quoted only the register figure would hide how rarely a whole frame is right.

**How well the envelope model fits.** The player's model reproduces 57.4% of the notes' own level contours on average. Per song:

| song | levels reproduced | notes reproduced exactly | notes |
|---|---|---|---|
| `Draconus_2024__sub0` | 50.6% | 15.1% | 2803 |
| `Ninja_Commando__sub0` | 64.6% | 17.2% | 911 |
| `Red_Max__sub0` | 50.2% | 26.8% | 2883 |
| `Warhawk__sub0` | 64.2% | 9.5% | 3603 |

That figure bounds how much of the AUDC residual can honestly be called performance: the rest of it is the model being too small, and section 17 says so.

## 8. Exact Residual Definition

The residual is a per-register value difference, and the reconstruction is arithmetic:

```
residual[register][frame] = (exact - predicted) & 0xFF
exact                      = (predicted + residual) & 0xFF
```

It is deterministic, exact, reversible and neutral: it names no effect and assumes no musical meaning. It is also *checked*, not asserted - 4 of 4 songs pass the identity `reconstruct(residual) == exact` for every frame and every register, and the stage raises rather than reports if it ever fails.

| property | value |
|---|---|
| representation | REGISTER_VALUE_RESIDUAL, 8-bit two's complement per register per frame |
| zero means | the baseline predicted that register in that frame exactly |
| storage cost quoted | a stated sparse encoding: per register a uvarint count, then (uvarint frame delta, one byte value) pairs |
| identity | `(predicted + residual) & 0xFF == exact`, verified |
| what it is not | not a named effect, not a musical category, not a compression scheme |

**Sizes.** The canonical stream is nine bytes per frame; the residual is quoted both as a count of differing values and as the bytes of that stated sparse encoding, so a size can be compared without dressing it up.

| song | canonical bytes | residual values | residual share | sparse residual bytes | sparse share of canonical |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 41268 | 52.0% | 82559 | 103.9% |
| `Ninja_Commando__sub0` | 54729 | 15106 | 27.6% | 30250 | 55.3% |
| `Red_Max__sub0` | 62208 | 24180 | 38.9% | 48378 | 77.8% |
| `Warhawk__sub0` | 97560 | 37592 | 38.5% | 75206 | 77.1% |

## 9. Residual Statistics

Three coverage figures, side by side, because they lead to very different conclusions and only one of them is the information figure.

| song | frames | exact frames | frame coverage | residual values | register coverage | byte coverage |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 8826 | 28 | 0.3% | 41268 | 48.0% | 48.0% |
| `Ninja_Commando__sub0` | 6081 | 254 | 4.2% | 15106 | 72.4% | 72.4% |
| `Red_Max__sub0` | 6912 | 42 | 0.6% | 24180 | 61.1% | 61.1% |
| `Warhawk__sub0` | 10840 | 169 | 1.6% | 37592 | 61.5% | 61.5% |

| figure | mean over the four songs |
|---|---|
| frame coverage (all nine registers agree) | 1.7% |
| register coverage (values that agree) | 60.8% |
| residual share (values that do not) | 39.2% |
| byte coverage = register coverage, by construction | 60.8% |

**The gap is the finding.** Frame coverage is 1.7% and register coverage is 60.8%. Saying "the note representation explains 1% of the stream" and "it explains 60% of the stream" are both defensible readings of the same measurement, and both are misleading on their own. The byte figure is identical to the register figure *because* one register frame is one byte in the canonical representation, and that equality is stated rather than assumed.

## 10. Residual Temporal Distribution

The residual is classified per *register*, against the notes that actually drive that register. A global "a note started here" flag is deliberately not used, because with four voices it is true almost everywhere and would make every frame look like an onset.

| class | frames | residual values | residual share of the class |
|---|---|---|---|
| note_interior | 217438 | 105313 | 48.4% |
| note_onset | 24928 | 2356 | 9.5% |
| outside_any_note | 51565 | 10477 | 20.3% |

**Per song, and per song this is the sharpest single table in the report.**

| song | outside_any_note | note_interior | note_onset | register values | residual |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 29.3% | 64.9% | 3.3% | 79434 | 41268 |
| `Ninja_Commando__sub0` | 26.8% | 28.6% | 17.2% | 54729 | 15106 |
| `Red_Max__sub0` | 3.2% | 48.6% | 8.8% | 62208 | 24180 |
| `Warhawk__sub0` | 9.3% | 46.7% | 11.3% | 97560 | 37592 |

**Within a note, the residual sits in the middle, not at the edges.** Relative position is (frame - note start) / (note length - 1); the gap row collects frames no note covers.

| song | onset | 0-10% | 10-25% | 25-50% | 50-75% | 75-90% | 90-100% | gap |
|---|---|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 3.3% | 23.2% | 63.0% | 68.1% | 66.2% | 65.9% | 61.4% | 29.3% |
| `Ninja_Commando__sub0` | 17.2% | 39.7% | 36.9% | 36.0% | 31.5% | 24.1% | 22.6% | 26.8% |
| `Red_Max__sub0` | 8.8% | 12.6% | 71.0% | 52.7% | 62.4% | 67.7% | 44.2% | 3.2% |
| `Warhawk__sub0` | 11.3% | 19.4% | 46.5% | 57.8% | 56.4% | 52.6% | 46.5% | 9.3% |

**Two conclusions the numbers force.** First, the note *onset* is almost never wrong, so the residual is not an alignment or a pitch-mapping error - it is what happens after the note starts. Second, the residual is spread across the whole note rather than concentrated at its edges, so a baseline that only fixed up transitions would not come close to explaining it.

## 11. Residual Register and Channel Distribution

Which registers carry the residual, and in which class. A single register carrying everything would mean a channel-assignment problem rather than missing performance information.

| song | register | residual values | share of frames | distinct magnitudes | onset | interior | gap |
|---|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | AUDC1 | 5227 | 59.2% | 21 | 0.3% | 62.1% | 52.6% |
| `Draconus_2024__sub0` | AUDC2 | 4007 | 45.4% | 31 | 5.2% | 68.0% | 5.8% |
| `Draconus_2024__sub0` | AUDC3 | 4983 | 56.5% | 19 | 2.0% | 55.3% | 98.7% |
| `Draconus_2024__sub0` | AUDC4 | 4761 | 53.9% | 11 | 18.1% | 48.2% | 77.3% |
| `Draconus_2024__sub0` | AUDCTL | 0 | 0.0% | 0 | n/a | n/a | 0.0% |
| `Draconus_2024__sub0` | AUDF1 | 3378 | 38.3% | 26 | 0.0% | 40.5% | 2.1% |
| `Draconus_2024__sub0` | AUDF2 | 5058 | 57.3% | 89 | 0.0% | 85.8% | 12.3% |
| `Draconus_2024__sub0` | AUDF3 | 7276 | 82.4% | 133 | 0.2% | 86.8% | 92.4% |
| `Draconus_2024__sub0` | AUDF4 | 6578 | 74.5% | 108 | 0.0% | 81.3% | 75.8% |
| `Ninja_Commando__sub0` | AUDC1 | 0 | 0.0% | 0 | 0.0% | 0.0% | 0.0% |
| `Ninja_Commando__sub0` | AUDC2 | 1829 | 30.1% | 8 | 100.0% | 27.6% | 0.0% |
| `Ninja_Commando__sub0` | AUDC3 | 1320 | 21.7% | 9 | 7.7% | 24.9% | 0.0% |
| `Ninja_Commando__sub0` | AUDC4 | 2287 | 37.6% | 9 | 0.0% | 54.2% | 0.0% |
| `Ninja_Commando__sub0` | AUDCTL | 0 | 0.0% | 0 | n/a | n/a | 0.0% |
| `Ninja_Commando__sub0` | AUDF1 | 801 | 13.2% | 9 | 0.0% | 3.2% | 100.0% |
| `Ninja_Commando__sub0` | AUDF2 | 661 | 10.9% | 3 | 0.0% | 0.4% | 100.0% |
| `Ninja_Commando__sub0` | AUDF3 | 4529 | 74.5% | 22 | 0.0% | 74.1% | 100.0% |
| `Ninja_Commando__sub0` | AUDF4 | 3679 | 60.5% | 28 | 0.0% | 49.3% | 100.0% |
| `Red_Max__sub0` | AUDC1 | 0 | 0.0% | 0 | 0.0% | 0.0% | n/a |
| `Red_Max__sub0` | AUDC2 | 5034 | 72.8% | 15 | 100.0% | 70.3% | n/a |
| `Red_Max__sub0` | AUDC3 | 5616 | 81.2% | 6 | 0.0% | 98.7% | n/a |
| `Red_Max__sub0` | AUDC4 | 2271 | 32.9% | 18 | 2.5% | 36.8% | 100.0% |
| `Red_Max__sub0` | AUDCTL | 0 | 0.0% | 0 | n/a | n/a | 0.0% |
| `Red_Max__sub0` | AUDF1 | 828 | 12.0% | 7 | 0.0% | 13.1% | n/a |
| `Red_Max__sub0` | AUDF2 | 684 | 9.9% | 3 | 0.0% | 10.8% | n/a |
| `Red_Max__sub0` | AUDF3 | 5616 | 81.2% | 15 | 0.0% | 98.7% | n/a |
| `Red_Max__sub0` | AUDF4 | 4131 | 59.8% | 255 | 0.0% | 71.4% | 50.0% |
| `Warhawk__sub0` | AUDC1 | 0 | 0.0% | 0 | 0.0% | 0.0% | n/a |
| `Warhawk__sub0` | AUDC2 | 6777 | 62.5% | 10 | 74.9% | 60.9% | n/a |
| `Warhawk__sub0` | AUDC3 | 5056 | 46.6% | 17 | 12.4% | 49.6% | n/a |
| `Warhawk__sub0` | AUDC4 | 8598 | 79.3% | 17 | 3.8% | 90.9% | 100.0% |
| `Warhawk__sub0` | AUDCTL | 0 | 0.0% | 0 | n/a | n/a | 0.0% |
| `Warhawk__sub0` | AUDF1 | 36 | 0.3% | 1 | 0.0% | 0.4% | n/a |
| `Warhawk__sub0` | AUDF2 | 36 | 0.3% | 1 | 0.0% | 0.4% | n/a |
| `Warhawk__sub0` | AUDF3 | 8452 | 78.0% | 106 | 0.8% | 84.7% | n/a |
| `Warhawk__sub0` | AUDF4 | 8637 | 79.7% | 39 | 0.0% | 93.6% | 78.8% |

**By register family.** Pitch registers and level registers behave differently, and the split is reported so a reader can see which half of the stream the missing information lives in.

| song | pitch residual values | volume residual values | pitch share |
|---|---|---|---|
| `Draconus_2024__sub0` | 22290 | 18978 | 54.0% |
| `Ninja_Commando__sub0` | 9670 | 5436 | 64.0% |
| `Red_Max__sub0` | 11259 | 12921 | 46.6% |
| `Warhawk__sub0` | 17161 | 20431 | 45.7% |

AUDCTL is worth one line on its own: it is a single global register, every song uses one value for its whole length, and the baseline predicts that value, so its residual is zero everywhere. It is reported as zero rather than omitted.

## 12. Stage 19 Grammar as Residual Model

The experiment this stage exists for. Stage 19 asked whether the grammar could describe the *whole* stream and answered: only partly. The question here is narrower and different - *is the grammar much better when it only has to describe the residual?*

```
raw trace    ->  Stage 19 grammar        (Stage 19's question)
raw trace    ->  note baseline  ->  residual  ->  Stage 19 grammar   (this stage)
```

The vocabulary is Stage 19's generalisable one - SET, HOLD, DELTA, RAMP, TOGGLE - with the literal escape as the residual channel. **The song-specific REPEAT lexicon is excluded by definition**, because Stage 19 showed it transfers nothing, and this stage measures only information a shared layer could carry.

| song | residual values | structurally explained | structural share | grammar bytes | literal bytes | size gain |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 41268 | 21186 | 51.3% | 52383 | 82542 | 36.5% |
| `Ninja_Commando__sub0` | 15106 | 7835 | 51.9% | 13814 | 30234 | 54.3% |
| `Red_Max__sub0` | 24180 | 11397 | 47.1% | 30866 | 48362 | 36.2% |
| `Warhawk__sub0` | 37592 | 16990 | 45.2% | 44712 | 75192 | 40.5% |

**Two readings, and they can disagree.** *Structural share* counts only the **nonzero** residual values that a construction generates rather than a literal store: a HOLD over a run of zeros explains nothing, and it is excluded by construction because those frames carry a zero residual. *Size gain* is the grammar's encoding against the stated sparse encoding of the same residual, and it is secondary.

**Per register, because the answer is not uniform.**

| song | register | residual values | structural share | operations |
|---|---|---|---|---|
| `Draconus_2024__sub0` | AUDC1 | 5227 | 2.7% | 580 |
| `Draconus_2024__sub0` | AUDC2 | 4007 | 18.8% | 1079 |
| `Draconus_2024__sub0` | AUDC3 | 4983 | 64.0% | 1412 |
| `Draconus_2024__sub0` | AUDC4 | 4761 | 69.2% | 1305 |
| `Draconus_2024__sub0` | AUDF1 | 3378 | 90.2% | 891 |
| `Draconus_2024__sub0` | AUDF2 | 5058 | 31.8% | 888 |
| `Draconus_2024__sub0` | AUDF3 | 7276 | 71.7% | 1180 |
| `Draconus_2024__sub0` | AUDF4 | 6578 | 59.8% | 1104 |
| `Ninja_Commando__sub0` | AUDC2 | 1829 | 19.0% | 870 |
| `Ninja_Commando__sub0` | AUDC3 | 1320 | 0.0% | 182 |
| `Ninja_Commando__sub0` | AUDC4 | 2287 | 2.1% | 405 |
| `Ninja_Commando__sub0` | AUDF1 | 801 | 95.8% | 115 |
| `Ninja_Commando__sub0` | AUDF2 | 661 | 99.1% | 19 |
| `Ninja_Commando__sub0` | AUDF3 | 4529 | 96.4% | 104 |
| `Ninja_Commando__sub0` | AUDF4 | 3679 | 44.9% | 91 |
| `Red_Max__sub0` | AUDC2 | 5034 | 37.2% | 577 |
| `Red_Max__sub0` | AUDC3 | 5616 | 17.1% | 385 |
| `Red_Max__sub0` | AUDC4 | 2271 | 34.1% | 297 |
| `Red_Max__sub0` | AUDF1 | 828 | 83.3% | 553 |
| `Red_Max__sub0` | AUDF2 | 684 | 83.3% | 457 |
| `Red_Max__sub0` | AUDF3 | 5616 | 76.9% | 2161 |
| `Red_Max__sub0` | AUDF4 | 4131 | 53.5% | 622 |
| `Warhawk__sub0` | AUDC2 | 6777 | 0.0% | 371 |
| `Warhawk__sub0` | AUDC3 | 5056 | 49.1% | 1146 |
| `Warhawk__sub0` | AUDC4 | 8598 | 54.2% | 1845 |
| `Warhawk__sub0` | AUDF1 | 36 | 88.9% | 17 |
| `Warhawk__sub0` | AUDF2 | 36 | 88.9% | 17 |
| `Warhawk__sub0` | AUDF3 | 8452 | 38.7% | 1151 |
| `Warhawk__sub0` | AUDF4 | 8637 | 75.4% | 1856 |

The pattern is consistent across all four songs: pitch registers are strongly structured (their residual is mostly arithmetic movement, which RAMP and DELTA generate) while level registers are much less so. That is the single most useful shape in this report, because it says where a Performance Layer would and would not earn its keep.

## 13. Incremental Gain

The performance gain is defined as `NOTE_RESIDUAL - NOTE_PLUS_GRAMMAR_RESIDUAL`, in register values and in shares of the whole stream.

| song | notes explain | residual | grammar explains of the residual | grammar adds to the stream | still unexplained |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 48.0% | 52.0% | 51.3% | 26.7% | 25.3% |
| `Ninja_Commando__sub0` | 72.4% | 27.6% | 51.9% | 14.3% | 13.3% |
| `Red_Max__sub0` | 61.1% | 38.9% | 47.1% | 18.3% | 20.5% |
| `Warhawk__sub0` | 61.5% | 38.5% | 45.2% | 17.4% | 21.1% |

| stage of the answer | share of all register values |
|---|---|
| explained by the note representation | 60.8% |
| explained additionally by the Stage 19 grammar | 19.2% |
| explained by neither | 20.1% |

**This is the sentence the brief asks for.** After accounting for the existing note-level representation, 39.2% of POKEY register values remain unexplained; the Stage 19 grammar accounts for a further 48.9% of that residual, which is 19.2% of the whole stream; the remaining 20.1% is described by neither, and sections 14 to 16 test whether what is left is shared or private.

**Per-construction contribution**, because a single construction taking all the credit would change what a layer should contain:

| song | construction removed | structural share with | without | share lost | size gain lost |
|---|---|---|---|---|---|
| `Draconus_2024__sub0` | DELTA | 51.3% | 51.3% | 0.0% | 0.0% |
| `Draconus_2024__sub0` | HOLD | 51.3% | 18.1% | 33.3% | 37.4% |
| `Draconus_2024__sub0` | RAMP | 51.3% | 35.8% | 15.5% | 1.1% |
| `Draconus_2024__sub0` | TOGGLE | 51.3% | 51.3% | 0.1% | 0.0% |
| `Ninja_Commando__sub0` | DELTA | 51.9% | 51.9% | 0.0% | 0.0% |
| `Ninja_Commando__sub0` | HOLD | 51.9% | 24.7% | 27.2% | 130.3% |
| `Ninja_Commando__sub0` | RAMP | 51.9% | 51.3% | 0.6% | 0.0% |
| `Ninja_Commando__sub0` | TOGGLE | 51.9% | 27.2% | 24.7% | 16.4% |
| `Red_Max__sub0` | DELTA | 47.1% | 47.1% | 0.0% | 0.0% |
| `Red_Max__sub0` | HOLD | 47.1% | 17.1% | 30.1% | 69.4% |
| `Red_Max__sub0` | RAMP | 47.1% | 44.6% | 2.6% | 0.0% |
| `Red_Max__sub0` | TOGGLE | 47.1% | 47.1% | 0.0% | 0.0% |
| `Warhawk__sub0` | DELTA | 45.2% | 45.2% | -0.0% | 0.0% |
| `Warhawk__sub0` | HOLD | 45.2% | 10.5% | 34.7% | 76.5% |
| `Warhawk__sub0` | RAMP | 45.2% | 43.8% | 1.4% | 0.1% |
| `Warhawk__sub0` | TOGGLE | 45.2% | 37.8% | 7.4% | 1.5% |

## 14. Cross-Song Generalization

The residual grammar is induced independently on each song by greedy forward selection on the encoded residual size, so a construction has to shrink the residual before it joins the vocabulary.

| song | induced residual vocabulary | encoded bytes | literal bytes | in-sample size gain |
|---|---|---|---|---|
| `Draconus_2024__sub0` | SET, HOLD, DELTA, RAMP, TOGGLE | 52383 | 84420 | 37.9% |
| `Ninja_Commando__sub0` | SET, HOLD, TOGGLE | 13814 | 58176 | 76.3% |
| `Red_Max__sub0` | SET, HOLD, DELTA, RAMP | 30866 | 66114 | 53.3% |
| `Warhawk__sub0` | SET, HOLD, DELTA, RAMP, TOGGLE | 44712 | 103680 | 56.9% |

**The step history of the first song**, kept so the stopping decision can be audited:

| step | candidate added | trial vocabulary | encoded bytes | gain | accepted |
|---|---|---|---|---|---|
| 1 | HOLD | SET, HOLD | 53581 | 30839 | yes |
| 2 | RAMP | SET, HOLD, RAMP | 52426 | 1155 | yes |
| 3 | DELTA | SET, HOLD, DELTA, RAMP | 52399 | 27 | yes |
| 4 | TOGGLE | SET, HOLD, DELTA, RAMP, TOGGLE | 52383 | 16 | yes |

**Structure, not just vocabulary.** The kind of operation each song's residual parse uses, and how often:

| song | operation mix | adjacent pairs observed |
|---|---|---|
| `Draconus_2024__sub0` | DELTA 0.3%, HOLD 37.8%, LITERAL 27.3%, RAMP 19.4%, SET 14.9%, TOGGLE 0.2% | 16 |
| `Ninja_Commando__sub0` | HOLD 41.7%, LITERAL 44.6%, RAMP 4.9%, SET 4.4%, TOGGLE 4.4% | 13 |
| `Red_Max__sub0` | DELTA 0.1%, HOLD 38.9%, LITERAL 36.8%, RAMP 12.1%, SET 12.1% | 14 |
| `Warhawk__sub0` | DELTA 0.2%, HOLD 39.5%, LITERAL 44.0%, RAMP 5.2%, SET 4.5%, TOGGLE 6.7% | 22 |

## 15. Leave-One-Out

Induce on three songs' residuals, then encode the fourth. Three arms, because *generalise* means three different things and conflating them would flatter the result.

| arm | what it allows | mean size gain |
|---|---|---|
| shared vocabulary | only the constructions every training song induced, parameters free | 52.7% |
| union vocabulary | every construction any training song induced, parameters free | 56.1% |
| frozen parameters | the union vocabulary, but only parameter shapes seen in training | 53.8% |

| held out | trained on | shared vocabulary | union vocabulary | literal bytes | shared arm | union arm | frozen arm |
|---|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | HOLD | DELTA, HOLD, RAMP, TOGGLE | 84420 | 53581 | 52383 | 52384 |
| `Ninja_Commando__sub0` | Draconus_2024__sub0, Red_Max__sub0, Warhawk__sub0 | DELTA, HOLD, RAMP | DELTA, HOLD, RAMP, TOGGLE | 58176 | 18768 | 13814 | 18533 |
| `Red_Max__sub0` | Draconus_2024__sub0, Ninja_Commando__sub0, Warhawk__sub0 | HOLD, TOGGLE | DELTA, HOLD, RAMP, TOGGLE | 66114 | 32562 | 30866 | 30913 |
| `Warhawk__sub0` | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0 | HOLD | DELTA, HOLD, RAMP, TOGGLE | 103680 | 45939 | 44712 | 45884 |

**The three levels of generalisation, reported separately.**

| level | question | measured |
|---|---|---|
| G1 vocabulary | are the same residual constructions induced elsewhere? | DELTA, HOLD, RAMP, SET, TOGGLE |
| G2 structure | do the same temporal relationships appear? | 6 distinct operation kinds appear across the four held-out residuals |
| G3 parameters | do the parameters transfer? | frozen-parameter gain 53.8% against union 56.1% |

A song-specific lexicon is never used, and no parameter is ever fitted to the held-out song, so the out-of-sample numbers are honest rather than optimistic.

## 16. Controls and Anti-Circularity

Three null models and two controls. Each exists to answer a specific way the result could be wrong.

| model | what it is | measured | what it rules out |
|---|---|---|---|
| no notes at all | every register held at its own modal value | 39.1% | crediting the notes with registers that are simply constant |
| shuffled residual | the same corrections at shuffled frames, same multiset per register | 3.2% | a structural share that is really just correction density |
| shifted notes | the same notes moved by 4, 16 frames | 42.5% | a baseline that is not really explaining alignment |
| permuted trace | the trace shuffled in frame order against unshifted notes | 68.9% | the control being a different signal rather than a control |

**The shuffled-residual null is the decisive one for the grammar.** The real residual scores 48.9% structurally; the same corrections at shuffled frames score 3.2%. The structure is therefore in the *placement* of the corrections, not in how many there are.

**The shifted-notes control is the decisive one for the baseline.** Comparing 42.5% against 60.8% would be misleading, because the no-notes floor is already 39.1%. The right comparison is against that floor: the notes contribute 21.7%, and the shift keeps almost none of it. Alignment is doing the real work.

**Anti-circularity, in full.** The information flow is one-directional by construction:

| step | what it reads | what it must not read |
|---|---|---|
| note detection | the trace's divider, waveform and level, at note onsets | nothing per-frame inside a note |
| contour fit | the note's own level sequence, reduced to four parameters | no other note, no other channel |
| prediction | the notes only, through the project's own pitch and envelope functions | no per-frame trace value at all |
| residual | prediction and exact, as arithmetic | nothing that could favour the Stage 19 grammar |

The residual is therefore defined *before* the grammar touches it, and the grammar is applied to a residual it had no hand in shaping. That is the guard the brief asks for, and it is structural rather than a promise.

## 17. Trivial Explanations, Ruled Out First

Five candidate boring causes, each measured. `residual != 0` is not performance, so each has to be eliminated before any claim is made.

| candidate cause | measurement | conclusion |
|---|---|---|
| pitch mapping | onset residual share 10.1% | the player's formula reproduces the trace's own onset divider essentially everywhere, so the AUDF residual is movement after the onset, not a mapping artefact |
| detector gap | 20.3% of gap frames | frames no note covers are a limitation of the note detector; they are counted separately and never as performance |
| level model | 57.4% of note contours reproduced | the player's own four-parameter envelope model cannot reproduce most contours even fitted as well as it allows, so part of the AUDC residual is the model being too small |
| channel assignment | 52.6% of residual values are in pitch registers | the split is reported per register, so one mis-assigned channel would show up as one register carrying everything |
| note length | reported per length bucket below | a baseline that only failed on very short notes would be a resolution problem, not a missing layer |

| song | length bucket | frames | residual | residual share |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 1-2 frames | 156 | 49 | 31.4% |
| `Draconus_2024__sub0` | 11-25 frames | 8576 | 4266 | 49.7% |
| `Draconus_2024__sub0` | 26+ frames | 29800 | 20795 | 69.8% |
| `Draconus_2024__sub0` | 3-5 frames | 14136 | 6574 | 46.5% |
| `Draconus_2024__sub0` | 6-10 frames | 7656 | 3994 | 52.2% |
| `Ninja_Commando__sub0` | 1-2 frames | 10 | 0 | 0.0% |
| `Ninja_Commando__sub0` | 11-25 frames | 5000 | 764 | 15.3% |
| `Ninja_Commando__sub0` | 26+ frames | 16830 | 8886 | 52.8% |
| `Ninja_Commando__sub0` | 3-5 frames | 2672 | 472 | 17.7% |
| `Ninja_Commando__sub0` | 6-10 frames | 11650 | 1461 | 12.5% |
| `Red_Max__sub0` | 11-25 frames | 21420 | 7044 | 32.9% |
| `Red_Max__sub0` | 26+ frames | 5436 | 3000 | 55.2% |
| `Red_Max__sub0` | 3-5 frames | 5988 | 1356 | 22.6% |
| `Red_Max__sub0` | 6-10 frames | 15228 | 12546 | 82.4% |
| `Warhawk__sub0` | 1-2 frames | 86 | 14 | 16.3% |
| `Warhawk__sub0` | 11-25 frames | 1172 | 868 | 74.1% |
| `Warhawk__sub0` | 26+ frames | 11860 | 7109 | 59.9% |
| `Warhawk__sub0` | 3-5 frames | 5856 | 2415 | 41.2% |
| `Warhawk__sub0` | 6-10 frames | 55642 | 26056 | 46.8% |

**What survives all five.** The residual is not an alignment error, not a detector gap, not a channel-assignment mistake and not a resolution problem. It is genuine per-frame information the note representation does not carry - *and* it is partly an envelope model that is too small. Both statements hold at once, and this report keeps them both rather than choosing the flattering one.

## 18. Complexity

If the residual is to become a layer, its complexity matters as much as its size.

| song | residual events | distinct magnitudes | operations | repetition | temporal entropy | value entropy |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 41268 | 187 | 8440 | 47.8% | 1.180820 | 5.527711 |
| `Ninja_Commando__sub0` | 15106 | 47 | 1788 | 50.4% | 1.173463 | 4.493967 |
| `Red_Max__sub0` | 24180 | 255 | 5054 | 36.0% | 1.106792 | 5.522573 |
| `Warhawk__sub0` | 37592 | 131 | 6405 | 46.1% | 1.070586 | 4.868541 |

`temporal entropy` is the Shannon entropy of the gaps between consecutive corrections in one register: a low value means the corrections arrive on a regular rhythm. `value entropy` is the entropy of the correction magnitudes. Neither is a size and neither is a verdict; they describe what kind of thing the residual is.

**Residual relative to the original.**

| song | canonical bytes | residual values | events per register | residual / original |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 79434 | 41268 | 4585.333333 | 52.0% |
| `Ninja_Commando__sub0` | 54729 | 15106 | 1678.444444 | 27.6% |
| `Red_Max__sub0` | 62208 | 24180 | 2686.666667 | 38.9% |
| `Warhawk__sub0` | 97560 | 37592 | 4176.888889 | 38.5% |

No residual grammar is proposed here. The stage measures the residual; designing a layer for it is a later experiment.

## 19. Falsification

The brief's five possible outcomes, against what was measured. The mapping is stated so the result cannot be read as whichever outcome happens to be most flattering.

| outcome | would require | measured | verdict |
|---|---|---|---|
| A - notes explain most, residual small | small residual, high note coverage | note coverage 60.8%, residual 39.2% | **not this** |
| B - notes explain a moderate amount, residual structured | moderate residual that is structured | residual 39.2%, structural share 48.9% | **this is the result** |
| C - notes explain little, residual large but structured | low note coverage | note coverage 60.8%, above the medium threshold | not this |
| D - residual large and unstructured | no structure at all | shuffled null 3.2% against 48.9% real | explicitly refuted |
| E - in-sample structure that collapses out of sample | leave-one-out far below in sample | 56.1% against 41.9% | explicitly refuted |

**Deliberate attempts to break the claim.**

| attempt | what would refute it | measured |
|---|---|---|
| the residual is a pitch-mapping artefact | a non-trivial onset residual | 10.1% of onset frames carry a residual - refuted |
| the residual is really detector gaps | most residual values falling outside notes | gap frames are 17.5% of all frames - refuted |
| the grammar's share is really density | the shuffled null scoring close to the real one | 3.2% against 48.9% - refuted, decisively |
| the baseline is too vague to be tested | the shifted control keeping its coverage | shifted 42.5% against a floor of 39.1% - refuted |
| the result is song-specific | leave-one-out collapsing below the in-sample gain | 56.1% against 41.9% - refuted, it transfers |

Two results are negative and are reported as such rather than buried: the player's own envelope model reproduces only about half of the notes' level contours, and about a fifth of all register values is explained by neither the notes nor the grammar.

## 20. Final Verdict

| question | verdict |
|---|---|
| how well do the notes explain the stream? | NOTE_EXPLANATORY_POWER_MEDIUM |
| what is the residual like? | RESIDUAL_MODERATE_AND_STRUCTURED |
| does it generalise? | RESIDUAL_GENERALIZATION_SUPPORTED |
| is a Performance Layer justified? | PERFORMANCE_LAYER_PROMISING |
| production | PLAYER_INTEGRATION_JUSTIFIED |

**Every condition the layer verdict rests on, with its measured number.**

| condition | met | measured |
|---|---|---|
| the residual is not most of the stream | yes | 0.39239 |
| the grammar explains a substantial share of the residual | yes | 0.488836 |
| the grammar beats the shuffled-residual null | yes | {"real": 0.488836, "shuffled": 0.031725} |
| note alignment matters - the shifted control loses the notes' contribution | yes | {"aligned": 0.60761, "no_notes_floor": 0.390664, "note_contribution_lost_share": 0.842643, "shifted": 0.424802} |
| the vocabulary transfers out of sample | yes | {"in_sample_gain": 0.418902, "leave_one_out_gain": 0.560983} |
| the parameters transfer out of sample | yes | {"frozen_gain": 0.537698, "in_sample_gain": 0.418902} |
| the player's own ADSR model cannot already explain the level residual | yes | 0.574167 |

The deciding condition is: **none - every condition is met**.

**NOTE_EXPLANATORY_POWER_MEDIUM, RESIDUAL_MODERATE_AND_STRUCTURED, RESIDUAL_GENERALIZATION_SUPPORTED, PERFORMANCE_LAYER_PROMISING.** The note representation explains a moderate majority of the POKEY stream, the leftover is moderate and it is structured rather than noise, and what is left generalises to a song that did not contribute to it. Those three together are what makes a layer *justified by the evidence* - and they are also why the answer is not a triumphant yes: a fifth of the stream is still explained by neither the notes nor the grammar, and the player's own envelope model is too small to describe the amplitude behaviour it is asked to describe. A future layer would have to fix that, and nothing here says it can.

## Final question

> After accounting for the existing note-level representation, how much historical POKEY behaviour remains as real, generalisable residual performance information - and is it small and structured enough to justify a separate Performance Layer in the Atari Music Composer?

Derived from the measurements, axis by axis:

| axis the brief asks for | measured |
|---|---|
| note baseline coverage | register 60.8%, frame 1.7%, byte 60.8% (identical to register by construction) |
| exact residual | 39.2% of register values, 118146 values, identity verified on every song |
| register / frame / byte residual | register 39.2%, frame 98.3%, byte 39.2% |
| Stage 19 incremental gain | 48.9% of the residual, 19.2% of the whole stream |
| temporal distribution | onset, interior and gap reported separately; the residual sits in the interior, not at the edges |
| cross-song behaviour | no-notes floor 39.1%, shifted control 42.5%, shuffled-residual null 3.2% |
| leave-one-out | vocabulary 56.1%, frozen parameters 53.8% |
| controls | all four reported in section 16; the two decisive ones both refute the trivial reading |
| complexity | 118146 residual events, with temporal and value entropy per song |

**The answer, in the form the brief asks for.** After accounting for the existing note-level representation, 39.2% of POKEY register values remain as residual. The Stage 19 grammar accounts for 48.9% of that residual - a further 19.2% of the whole stream - and the remaining 20.1% is explained by neither. Within the residual, the pitch registers are strongly structured and the level registers are much less so, and the structure survives leave-one-out and both decisive controls, so it is generalisable rather than song-specific.

**Is it small and structured enough to justify a separate Performance Layer?** The measurements say yes on structure and on generalisation, and *not yet* on completeness: a fifth of the stream is outside both representations, and part of the amplitude residual is the player's own envelope model being too small rather than a missing performance layer. A layer justified by this evidence would have to be a layer that also replaces that envelope model - and whether it can is a question this stage does not answer.

**No forced verdict.** The residual is neither small enough to shrug at nor large enough to make the composition representation hopeless. It is moderate, structured and shared, and it is reported as it is rather than rounded towards either the encouraging or the discouraging reading.

**STOP.** Nothing was implemented in production: no Composer change, no Music IR change, no POKEY IR change, no Performance Layer, no player command, no instrument bank, no generated music and no listening test. This stage establishes how much information really is missing between a composition and historical POKEY playback; designing an experiment that could generate it is the next stage's problem, not this one's.

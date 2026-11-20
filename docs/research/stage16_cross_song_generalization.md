# Stage 16 — Performance Style Cross-Song Generalization

Analysis only. This stage reuses the Stage 15 song analysis unchanged and aggregates it across four songs. It modifies no production code, generates no music, implements no style, and asks for no listening test.

## 1. Executive summary

| number | value |
|---|---|
| songs analysed | Draconus_2024__sub0, Warhawk__sub0, Ninja_Commando__sub0, Red_Max__sub0 |
| selection rule | greedy max-min (farthest-first) over min-max normalised axes: audible_channels, generator_families, distinct_pitch_values, events_per_second, duration_s numerically, plus author and AUDCTL as categorical axes worth 1.0 each when they differ; ties broken by slug ascending |
| techniques in the union | 16 |
| techniques in all four songs | 12 |
| techniques in one song only | 1 |
| mean pairwise technique Jaccard | 0.861905 |
| mean pairwise Ruzicka (share-weighted) | 0.45579 |
| leave-one-out technique coverage | 1.0 |
| leave-one-out core-context coverage | 0.036782 |
| leave-one-out parameter coverage | 0.973756 |
| universal / common / song-specific | 3 / 9 / 2 |
| generalisation verdict | GENERALIZATION_PARTIALLY_SUPPORTED |
| model verdict | VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED |

**GENERALIZATION_PARTIALLY_SUPPORTED** + **VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED**

| transferability vector (not a score) | value |
|---|---|
| technique_coverage | 1.0 |
| context_coverage | 0.036782 |
| parameter_coverage | 0.973756 |
| semantic_stability | 0.833333 |
| cross_song_consistency | 0.583333 |
| unknown_behaviour | 0.0 |

A weighted total would trade vocabulary overlap against context stability, and those two are the very things this stage must keep apart. A model that names every technique but places them wrongly is not '80% of a style'; it is a failed style with good recall. The vector is the result.

## 2. Research question

Stage 15 concluded that *technique + context* is a better abstraction than a portable instrument, but left one thing untested: whether that description survives leaving the song it was learned from. Stage 14 had already established that a measured behaviour can be real and still not transfer. The question here is narrower and harder:

> Does a context-aware performance style learned from one song contain information that remains valid when analysing a different song?

The experiment is leave-one-song-out. Nothing is predicted about registers; what is measured is how much of a held-out song the other songs can *account for* — its techniques, the contexts those techniques appear in, and the sizes of their parameters. The falsification targets are stated in advance: techniques present in one song only, context relationships that reverse between songs, parameter ranges that do not overlap, and identical register patterns with different musical functions.

## 3. Input songs and deterministic selection

Songs A and B are the Stage 15 reference and runner-up, recovered from the Stage 15 artefact itself (`C:\Users\grzes\Documents\Projects\atari-music\reports\stage15\reference_song.json`, sha256 `eba959d2c834b5c0db74b1258f8346bc19ee90d70c3de4e73542211c35b6183d`). The artefact was present, so nothing was assumed.

greedy max-min (farthest-first) over min-max normalised axes: audible_channels, generator_families, distinct_pitch_values, events_per_second, duration_s numerically, plus author and AUDCTL as categorical axes worth 1.0 each when they differ; ties broken by slug ascending

| picked | min distance to chosen | runner-up | runner-up distance |
|---|---|---|---|
| Ninja_Commando__sub0 | 1.6157 | Red_Max__sub0 | 1.4021 |
| Red_Max__sub0 | 1.4021 | Panther__sub0 | 1.3188 |

| song | title | author | date | AUDCTL | channels | families | pitch values | events | events/s |
|---|---|---|---|---|---|---|---|---|---|
| Blinkys_Scary_School__sub0 | Blinky's Scary School | Adam Gilmore | 1990 | $50 | 3 | 3 | 74 | 7227 | 45.042938 |
| Blinkys_Scary_School__sub3 | Blinky's Scary School | Adam Gilmore | 1990 | $50 | 3 | 3 | 62 | 2833 | 68.972606 |
| BMX_Simulator__sub0 | BMX Simulator | David Whittaker | 1986 | $50 | 3 | 3 | 85 | 22399 | 58.755826 |
| Draconus_2024__sub0 | Draconus 2024 | Adam Gilmore | 2024 | $00 | 4 | 4 | 200 | 13480 | 76.152586 |
| Extirpator__sub0 | Extirpator | Rob Hubbard | 1987 | $50 | 3 | 3 | 127 | 26008 | 91.270995 |
| International_Karate__sub0 | International Karate | Rob Hubbard | 1986 | $50 | 3 | 3 | 97 | 18912 | 69.756364 |
| Jet_Set_Willy__sub0 | Jet Set Willy | Rob Hubbard | 1986 | $50 | 3 | 3 | 105 | 28747 | 95.97877 |
| Ninja_Commando__sub0 | Ninja Commando | Adam Gilmore | 1989 | $50 | 3 | 2 | 55 | 5360 | 43.948914 |
| Panther__sub0 | Panther | David Whittaker | 1987 | $50 | 3 | 3 | 195 | 18592 | 57.478349 |
| Red_Max__sub0 | Red Max | David Whittaker | 1987 | $50 | 3 | 3 | 262 | 14151 | 102.080352 |
| Warhawk__sub0 | Warhawk | Rob Hubbard | 1986 | $50 | 3 | 4 | 106 | 18286 | 84.110116 |
| Zybex__sub4 | Zybex | Adam Gilmore | 1988 | $50 | 3 | 3 | 70 | 5702 | 43.558472 |

The whole corpus is shown, not just the chosen four, so the reader can see what the rule rejected. Sensitivity: weighting the composer axis twice as heavily would select Draconus_2024__sub0, Warhawk__sub0, Red_Max__sub0, Ninja_Commando__sub0, which is reported rather than hidden.

Diversity caveat, stated because it matters: this corpus is twelve subsongs of 1986-1990 British game music plus one 2024 production, and after the two Stage 15 seeds the remaining spread is mostly in duration, event density and pitch vocabulary. Three of the four chosen songs share AUDCTL `$50`, so this stage is **not** a test of cross-configuration generalisation.

## 4. Analysis methodology

The song-level analysis is Stage 15's, unchanged and un-duplicated: the same event extraction, the same technique identity function, the same musical-versus-register classification, the same context dimensions, the same note-segmentation heuristic (`NOTE_SPLIT_SEMITONES`, `NOTE_REATTACK_DELTA`, `NOTE_MIN_FRAMES`), and the same confidence handling. A song's definition does not change because another song behaves differently.

One representation *is* changed, deliberately, and it is named here: Stage 15 banded note length by song-relative tertiles, which means something different in every song, so it cannot be compared across songs. This stage replaces it with absolute bands (((3, 'short_1_3_frames'), (12, 'medium_4_12_frames'))) and adds absolute density bands (((2, 'sparse_0_2'), (6, 'medium_3_6'))). Stage 15's own artefacts are untouched.

| context dimension | portable? | why |
|---|---|---|
| family_bucket | yes | the generator family is a hardware fact, the same in any song |
| position_in_note | yes | start/middle/end of an audible span |
| pitch_band | yes | divider tertile within that voice's own range, so it is relative |
| note_length_band | yes with absolute bands | see above |
| density_band | yes with absolute bands | see above |
| company_band | yes | how many other voices were sounding |
| previous_event_kind / next_event_kind | yes | event classes, which every song has |
| channel | no | channel 2 in one song is not channel 2 in another |
| occurrence_index_band | no | repetition count is a property of one song's form |

Falsification is built into the design rather than added afterwards: the tests look for song-specific techniques, reversed context relationships, disjoint parameter ranges and generator shifts, and each has a section below.

### A defect found in the reused analysis, and fixed

Reusing another stage's analysis means inheriting its determinism. Stage 15's dominant-generator tie-break used set iteration order, which varies with the per-process string hash seed, so its event classifications could differ between processes. The tie-break is now lexicographic and Stage 15's artefacts were regenerated; 10 of 13,480 reference-song events (0.07%) moved between classifications and no Stage 15 conclusion changed.

This is reported rather than quietly corrected because it is a property of Stage 15's method, and the brief requires that a Stage 15 definition is not changed silently. The Stage 15 artefacts on disk were regenerated from the corrected code; the numbers below are all from the corrected analysis.

## 5. Per-song event and technique overview

| song | duration s | frames | events | events/s | techniques | >=20 occ | techniques/s |
|---|---|---|---|---|---|---|---|
| Draconus_2024__sub0 | 177.013029 | 8826 | 13480 | 76.152586 | 16 | 14 | 0.090389 |
| Warhawk__sub0 | 217.405479 | 10840 | 18286 | 84.110116 | 15 | 12 | 0.068996 |
| Ninja_Commando__sub0 | 121.959782 | 6081 | 5360 | 43.948914 | 13 | 10 | 0.106593 |
| Red_Max__sub0 | 138.62609 | 6912 | 14151 | 102.080352 | 13 | 11 | 0.093777 |

Songs differ in length, so raw counts are published next to events/second, events/audible-channel-second and technique occurrences/second. Every comparison that follows uses occurrence shares (a technique's share of a song's events) rather than absolute counts.

| song | generator distribution | channel distribution | position in note |
|---|---|---|---|
| Draconus_2024__sub0 | mixed 0.004674; noise 0.226929; tonal 0.768398 | ch1 0.110831; ch2 0.49503; ch3 0.180638; ch4 0.213501 | end 0.306306; middle 0.100816; outside_note 0.004674; start 0.588205 |
| Warhawk__sub0 | mixed 0.06896; noise 0.216504; tonal 0.714536 | ch1 0.067319; ch2 0.235426; ch3 0.274418; ch4 0.422837 | end 0.225911; middle 0.099694; outside_note 0.06896; start 0.605436 |
| Ninja_Commando__sub0 | mixed 0.061754; tonal 0.938246 | ch1 0.061754; ch2 0.335821; ch3 0.352612; ch4 0.249813 | end 0.267537; middle 0.13806; outside_note 0.061754; start 0.532649 |
| Red_Max__sub0 | mixed 0.050173; noise 0.136527; tonal 0.813299 | ch1 0.049961; ch2 0.174687; ch3 0.432478; ch4 0.342873 | end 0.209243; middle 0.090806; outside_note 0.050173; start 0.649777 |

| song | classifications | classes present | classes absent |
|---|---|---|---|
| Draconus_2024__sub0 | REAL_MUSICAL_BEHAVIOUR 12785; UNKNOWN_REGISTER_PATTERN 632; REGISTER_LEVEL_EFFECT 63 | ARPEGGIO, DISTORTION_CHANGE, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE, PITCH_SWEEP, REGISTER_PATTERN_CHANGE, TREMOLO, VIBRATO, VOLUME_CHANGE, VOLUME_ENVELOPE | AUDCTL_CHANGE, CHANNEL_COUPLING_CHANGE, SIXTEEN_BIT_DISABLE, SIXTEEN_BIT_ENABLE |
| Warhawk__sub0 | REAL_MUSICAL_BEHAVIOUR 16671; REGISTER_LEVEL_EFFECT 1261; UNKNOWN_REGISTER_PATTERN 354 | ARPEGGIO, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE, PITCH_SWEEP, REGISTER_PATTERN_CHANGE, TREMOLO, VIBRATO, VOLUME_CHANGE, VOLUME_ENVELOPE | AUDCTL_CHANGE, CHANNEL_COUPLING_CHANGE, DISTORTION_CHANGE, SIXTEEN_BIT_DISABLE, SIXTEEN_BIT_ENABLE |
| Ninja_Commando__sub0 | REAL_MUSICAL_BEHAVIOUR 5029; REGISTER_LEVEL_EFFECT 331 | ARPEGGIO, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE, PITCH_SWEEP, REGISTER_PATTERN_CHANGE, TREMOLO, VIBRATO, VOLUME_CHANGE, VOLUME_ENVELOPE | AUDCTL_CHANGE, CHANNEL_COUPLING_CHANGE, DISTORTION_CHANGE, GENERATOR_CHANGE, SIXTEEN_BIT_DISABLE, SIXTEEN_BIT_ENABLE |
| Red_Max__sub0 | REAL_MUSICAL_BEHAVIOUR 13441; REGISTER_LEVEL_EFFECT 710 | ARPEGGIO, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE, PITCH_SWEEP, REGISTER_PATTERN_CHANGE, TREMOLO, VOLUME_CHANGE, VOLUME_ENVELOPE | AUDCTL_CHANGE, CHANNEL_COUPLING_CHANGE, DISTORTION_CHANGE, SIXTEEN_BIT_DISABLE, SIXTEEN_BIT_ENABLE, VIBRATO |

## 6. Technique vocabulary overlap

| technique | low level | Draconus_2024__sub0 | Warhawk__sub0 | Ninja_Commando__sub0 | Red_Max__sub0 | songs | >=20 |
|---|---|---|---|---|---|---|---|
| ARPEGGIO | False | 48 | 350 | 35 | 15 | 4 | 3 |
| DISTORTION_CHANGE | False | 24 | 0 | 0 | 0 | 1 | 1 |
| GENERATOR_CHANGE | False | 962 | 2498 | 0 | 1497 | 3 | 3 |
| NOTE_OFF | True | 2803 | 3603 | 911 | 2883 | 4 | 4 |
| NOTE_ON | True | 2803 | 3603 | 911 | 2883 | 4 | 4 |
| PITCH_CHANGE | True | 1332 | 2355 | 1516 | 3189 | 4 | 4 |
| PITCH_SLIDE_FALLING | False | 808 | 392 | 214 | 121 | 4 | 4 |
| PITCH_SLIDE_RISING | False | 1135 | 547 | 228 | 171 | 4 | 4 |
| PITCH_SWEEP_FALLING | False | 6 | 17 | 8 | 6 | 4 | 0 |
| PITCH_SWEEP_RISING | False | 564 | 84 | 8 | 39 | 4 | 3 |
| REGISTER_PATTERN_CHANGE | True | 63 | 1261 | 331 | 710 | 4 | 4 |
| TREMOLO | False | 332 | 954 | 92 | 303 | 4 | 4 |
| VIBRATO | False | 22 | 11 | 14 | 0 | 3 | 1 |
| VOLUME_CHANGE | True | 1858 | 1178 | 430 | 717 | 4 | 4 |
| VOLUME_ENVELOPE_FALLING | False | 719 | 1420 | 662 | 1617 | 4 | 4 |
| VOLUME_ENVELOPE_RISING | False | 1 | 13 | 0 | 0 | 2 | 0 |

| pair | technique Jaccard | Ruzicka on shares | event-class Jaccard | only in the first |
|---|---|---|---|---|
| Draconus_2024__sub0 vs Warhawk__sub0 | 0.9375 | 0.550696 | 0.923077 | DISTORTION_CHANGE |
| Draconus_2024__sub0 vs Ninja_Commando__sub0 | 0.8125 | 0.352088 | 0.846154 | DISTORTION_CHANGE, GENERATOR_CHANGE, VOLUME_ENVELOPE_RISING |
| Draconus_2024__sub0 vs Red_Max__sub0 | 0.8125 | 0.571997 | 0.846154 | DISTORTION_CHANGE, VIBRATO, VOLUME_ENVELOPE_RISING |
| Warhawk__sub0 vs Ninja_Commando__sub0 | 0.866667 | 0.292908 | 0.916667 | GENERATOR_CHANGE, VOLUME_ENVELOPE_RISING |
| Warhawk__sub0 vs Red_Max__sub0 | 0.866667 | 0.679194 | 0.916667 | VIBRATO, VOLUME_ENVELOPE_RISING |
| Ninja_Commando__sub0 vs Red_Max__sub0 | 0.857143 | 0.360884 | 0.833333 | VIBRATO |

| event kind | songs present |
|---|---|
| ARPEGGIO | 4 |
| AUDCTL_CHANGE | 0 |
| CHANNEL_COUPLING_CHANGE | 0 |
| DISTORTION_CHANGE | 1 |
| GENERATOR_CHANGE | 3 |
| NOTE_OFF | 4 |
| NOTE_ON | 4 |
| PITCH_CHANGE | 4 |
| PITCH_SLIDE | 4 |
| PITCH_SWEEP | 4 |
| REGISTER_PATTERN_CHANGE | 4 |
| SIXTEEN_BIT_DISABLE | 0 |
| SIXTEEN_BIT_ENABLE | 0 |
| TREMOLO | 4 |
| VIBRATO | 3 |
| VOLUME_CHANGE | 4 |
| VOLUME_ENVELOPE | 4 |

The event-class row is the number Stage 15 reported as 92% for two songs. It is the weakest measure available, because the detector defines those classes identically everywhere; it is published here so that it is not mistaken for a style result.

Stage 15's two-song figures, for comparison: shared event classes 0.923077, shared technique identifiers 0.9375. This stage's mean pairwise event-class Jaccard across four songs is 0.88141.

## 7. Context generalisation

| context dimension | techniques compared | same-context share | different-context share | no dominant value | decidable share |
|---|---|---|---|---|---|
| family_bucket | 12 | 0.916667 | 0.083333 | 0.0 | 1.0 |
| density_band | 12 | 0.833333 | 0.166667 | 0.0 | 1.0 |
| pitch_band | 12 | 0.5 | 0.5 | 0.0 | 1.0 |
| note_length_band | 12 | 0.416667 | 0.583333 | 0.0 | 1.0 |
| company_band | 12 | 0.083333 | 0.916667 | 0.0 | 1.0 |
| next_event_kind | 12 | 0.333333 | 0.5 | 0.166667 | 0.833333 |
| position_in_note | 12 | 0.666667 | 0.083333 | 0.25 | 0.75 |
| previous_event_kind | 12 | 0.5 | 0.25 | 0.25 | 0.75 |

7 of 12 comparable techniques keep their context across songs (4 of those are not low-level classes) and 2 do not. At the dimension level, 51 of 88 decidable technique-by-dimension tests agree (0.579545). The most portable dimensions are family_bucket, density_band, pitch_band.

| technique | songs | verdict | decidable dimensions | dominant value per song (dimension: values) |
|---|---|---|---|---|
| NOTE_OFF | 4 | MOSTLY_SAME_CONTEXT | 7 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; position_in_note: ['end', 'end', 'end', 'end']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['short_1_3_frames', 'medium_4_12_frames', 'medium_4_12_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; next_event_kind: ['NOTE_ON', 'NOTE_ON', 'NOTE_ON', 'NOTE_ON'] |
| NOTE_ON | 4 | MOSTLY_SAME_CONTEXT | 7 | family_bucket: ['tonal', 'noise', 'tonal', 'tonal']; position_in_note: ['start', 'start', 'start', 'start']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['short_1_3_frames', 'medium_4_12_frames', 'medium_4_12_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; previous_event_kind: ['NOTE_OFF', 'NOTE_OFF', 'NOTE_OFF', 'NOTE_OFF'] |
| PITCH_CHANGE | 4 | MOSTLY_DIFFERENT_CONTEXT | 5 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'mid_divider', 'low_divider_high_pitch']; note_length_band: ['medium_4_12_frames', 'medium_4_12_frames', 'long_13_plus_frames', 'short_1_3_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio'] |
| PITCH_SLIDE_FALLING | 4 | MOSTLY_SAME_CONTEXT | 7 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; pitch_band: ['mid_divider', 'low_divider_high_pitch', 'low_divider_high_pitch', 'mid_divider']; note_length_band: ['long_13_plus_frames', 'long_13_plus_frames', 'long_13_plus_frames', 'long_13_plus_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; previous_event_kind: ['PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE']; next_event_kind: ['PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE'] |
| PITCH_SLIDE_RISING | 4 | MOSTLY_SAME_CONTEXT | 7 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['long_13_plus_frames', 'long_13_plus_frames', 'long_13_plus_frames', 'long_13_plus_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; previous_event_kind: ['PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE']; next_event_kind: ['PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE', 'PITCH_SLIDE'] |
| REGISTER_PATTERN_CHANGE | 4 | MIXED_CONTEXT | 8 | family_bucket: ['mixed', 'mixed', 'mixed', 'mixed']; position_in_note: ['outside_note', 'outside_note', 'outside_note', 'outside_note']; pitch_band: ['low_divider_high_pitch', 'unknown', 'unknown', 'unknown']; note_length_band: ['outside_note', 'outside_note', 'outside_note', 'outside_note']; density_band: ['dense_7_plus', 'medium_3_6', 'medium_3_6', 'medium_3_6']; company_band: ['full', 'full', 'full', 'full']; previous_event_kind: ['NOTE_OFF', 'REGISTER_PATTERN_CHANGE', 'REGISTER_PATTERN_CHANGE', 'REGISTER_PATTERN_CHANGE']; next_event_kind: ['NOTE_ON', 'REGISTER_PATTERN_CHANGE', 'REGISTER_PATTERN_CHANGE', 'REGISTER_PATTERN_CHANGE'] |
| TREMOLO | 4 | MIXED_CONTEXT | 8 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; position_in_note: ['start', 'start', 'start', 'start']; pitch_band: ['mid_divider', 'low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['long_13_plus_frames', 'medium_4_12_frames', 'long_13_plus_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; previous_event_kind: ['NOTE_ON', 'NOTE_ON', 'NOTE_ON', 'NOTE_ON']; next_event_kind: ['PITCH_CHANGE', 'NOTE_OFF', 'NOTE_OFF', 'PITCH_CHANGE'] |
| VOLUME_CHANGE | 4 | MOSTLY_SAME_CONTEXT | 7 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; position_in_note: ['start', 'start', 'start', 'start']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['short_1_3_frames', 'short_1_3_frames', 'medium_4_12_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; next_event_kind: ['NOTE_OFF', 'GENERATOR_CHANGE', 'VOLUME_ENVELOPE', 'VOLUME_ENVELOPE'] |
| VOLUME_ENVELOPE_FALLING | 4 | MIXED_CONTEXT | 8 | family_bucket: ['tonal', 'tonal', 'tonal', 'tonal']; position_in_note: ['start', 'start', 'start', 'start']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch', 'high_divider_low_pitch']; note_length_band: ['medium_4_12_frames', 'medium_4_12_frames', 'medium_4_12_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio', 'trio']; previous_event_kind: ['NOTE_ON', 'PITCH_CHANGE', 'VOLUME_CHANGE', 'GENERATOR_CHANGE']; next_event_kind: ['PITCH_CHANGE', 'GENERATOR_CHANGE', 'NOTE_OFF', 'NOTE_OFF'] |
| ARPEGGIO | 3 | MOSTLY_SAME_CONTEXT | 8 | family_bucket: ['tonal', 'tonal', 'tonal']; position_in_note: ['start', 'start', 'start']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['long_13_plus_frames', 'medium_4_12_frames', 'long_13_plus_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'medium_3_6']; company_band: ['full', 'trio', 'trio']; previous_event_kind: ['NOTE_OFF', 'NOTE_OFF', 'NOTE_OFF']; next_event_kind: ['NOTE_ON', 'NOTE_ON', 'NOTE_ON'] |
| GENERATOR_CHANGE | 3 | MOSTLY_DIFFERENT_CONTEXT | 8 | family_bucket: ['tonal', 'tonal', 'tonal']; position_in_note: ['end', 'start', 'start']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'high_divider_low_pitch']; note_length_band: ['short_1_3_frames', 'medium_4_12_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio']; previous_event_kind: ['VOLUME_CHANGE', 'VOLUME_ENVELOPE', 'PITCH_CHANGE']; next_event_kind: ['NOTE_OFF', 'NOTE_OFF', 'VOLUME_ENVELOPE'] |
| PITCH_SWEEP_RISING | 3 | MOSTLY_SAME_CONTEXT | 8 | family_bucket: ['tonal', 'tonal', 'tonal']; position_in_note: ['start', 'start', 'start']; pitch_band: ['low_divider_high_pitch', 'low_divider_high_pitch', 'low_divider_high_pitch']; note_length_band: ['medium_4_12_frames', 'medium_4_12_frames', 'medium_4_12_frames']; density_band: ['dense_7_plus', 'dense_7_plus', 'dense_7_plus']; company_band: ['full', 'trio', 'trio']; previous_event_kind: ['NOTE_ON', 'NOTE_ON', 'NOTE_ON']; next_event_kind: ['GENERATOR_CHANGE', 'VOLUME_ENVELOPE', 'VOLUME_ENVELOPE'] |

**Context relationships that do not travel:**

| technique | dimension | dominant value per song | median overlap |
|---|---|---|---|
| NOTE_OFF | note_length_band | {'Draconus_2024__sub0': 'short_1_3_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Ninja_Commando__sub0': 'medium_4_12_frames', 'Red_Max__sub0': 'medium_4_12_frames'} | 0.799471 |
| NOTE_OFF | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.63051 |
| NOTE_ON | family_bucket | {'Draconus_2024__sub0': 'tonal', 'Warhawk__sub0': 'noise', 'Ninja_Commando__sub0': 'tonal', 'Red_Max__sub0': 'tonal'} | 0.72856 |
| NOTE_ON | note_length_band | {'Draconus_2024__sub0': 'short_1_3_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Ninja_Commando__sub0': 'medium_4_12_frames', 'Red_Max__sub0': 'medium_4_12_frames'} | 0.799471 |
| NOTE_ON | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.567255 |
| PITCH_CHANGE | pitch_band | {'Draconus_2024__sub0': 'low_divider_high_pitch', 'Warhawk__sub0': 'low_divider_high_pitch', 'Ninja_Commando__sub0': 'mid_divider', 'Red_Max__sub0': 'low_divider_high_pitch'} | 0.743621 |
| PITCH_CHANGE | note_length_band | {'Draconus_2024__sub0': 'medium_4_12_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Ninja_Commando__sub0': 'long_13_plus_frames', 'Red_Max__sub0': 'short_1_3_frames'} | 0.605992 |
| PITCH_CHANGE | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.658407 |
| PITCH_SLIDE_FALLING | pitch_band | {'Draconus_2024__sub0': 'mid_divider', 'Warhawk__sub0': 'low_divider_high_pitch', 'Ninja_Commando__sub0': 'low_divider_high_pitch', 'Red_Max__sub0': 'mid_divider'} | 0.412925 |
| PITCH_SLIDE_FALLING | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.583332 |
| PITCH_SLIDE_RISING | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.62433 |
| REGISTER_PATTERN_CHANGE | pitch_band | {'Draconus_2024__sub0': 'low_divider_high_pitch', 'Warhawk__sub0': 'unknown', 'Ninja_Commando__sub0': 'unknown', 'Red_Max__sub0': 'unknown'} | 0.5 |
| REGISTER_PATTERN_CHANGE | density_band | {'Draconus_2024__sub0': 'dense_7_plus', 'Warhawk__sub0': 'medium_3_6', 'Ninja_Commando__sub0': 'medium_3_6', 'Red_Max__sub0': 'medium_3_6'} | 0.509042 |
| REGISTER_PATTERN_CHANGE | previous_event_kind | {'Draconus_2024__sub0': 'NOTE_OFF', 'Warhawk__sub0': 'REGISTER_PATTERN_CHANGE', 'Ninja_Commando__sub0': 'REGISTER_PATTERN_CHANGE', 'Red_Max__sub0': 'REGISTER_PATTERN_CHANGE'} | 0.494052 |
| REGISTER_PATTERN_CHANGE | next_event_kind | {'Draconus_2024__sub0': 'NOTE_ON', 'Warhawk__sub0': 'REGISTER_PATTERN_CHANGE', 'Ninja_Commando__sub0': 'REGISTER_PATTERN_CHANGE', 'Red_Max__sub0': 'REGISTER_PATTERN_CHANGE'} | 0.500397 |
| TREMOLO | pitch_band | {'Draconus_2024__sub0': 'mid_divider', 'Warhawk__sub0': 'low_divider_high_pitch', 'Ninja_Commando__sub0': 'low_divider_high_pitch', 'Red_Max__sub0': 'low_divider_high_pitch'} | 0.618976 |
| TREMOLO | note_length_band | {'Draconus_2024__sub0': 'long_13_plus_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Ninja_Commando__sub0': 'long_13_plus_frames', 'Red_Max__sub0': 'medium_4_12_frames'} | 0.397969 |
| TREMOLO | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.529898 |
| TREMOLO | next_event_kind | {'Draconus_2024__sub0': 'PITCH_CHANGE', 'Warhawk__sub0': 'NOTE_OFF', 'Ninja_Commando__sub0': 'NOTE_OFF', 'Red_Max__sub0': 'PITCH_CHANGE'} | 0.415914 |
| VOLUME_CHANGE | note_length_band | {'Draconus_2024__sub0': 'short_1_3_frames', 'Warhawk__sub0': 'short_1_3_frames', 'Ninja_Commando__sub0': 'medium_4_12_frames', 'Red_Max__sub0': 'medium_4_12_frames'} | 0.66742 |
| VOLUME_CHANGE | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.541183 |
| VOLUME_CHANGE | next_event_kind | {'Draconus_2024__sub0': 'NOTE_OFF', 'Warhawk__sub0': 'GENERATOR_CHANGE', 'Ninja_Commando__sub0': 'VOLUME_ENVELOPE', 'Red_Max__sub0': 'VOLUME_ENVELOPE'} | 0.483796 |
| VOLUME_ENVELOPE_FALLING | pitch_band | {'Draconus_2024__sub0': 'low_divider_high_pitch', 'Warhawk__sub0': 'low_divider_high_pitch', 'Ninja_Commando__sub0': 'low_divider_high_pitch', 'Red_Max__sub0': 'high_divider_low_pitch'} | 0.67267 |
| VOLUME_ENVELOPE_FALLING | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.564419 |
| VOLUME_ENVELOPE_FALLING | previous_event_kind | {'Draconus_2024__sub0': 'NOTE_ON', 'Warhawk__sub0': 'PITCH_CHANGE', 'Ninja_Commando__sub0': 'VOLUME_CHANGE', 'Red_Max__sub0': 'GENERATOR_CHANGE'} | 0.283768 |
| VOLUME_ENVELOPE_FALLING | next_event_kind | {'Draconus_2024__sub0': 'PITCH_CHANGE', 'Warhawk__sub0': 'GENERATOR_CHANGE', 'Ninja_Commando__sub0': 'NOTE_OFF', 'Red_Max__sub0': 'NOTE_OFF'} | 0.296175 |
| ARPEGGIO | note_length_band | {'Draconus_2024__sub0': 'long_13_plus_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Ninja_Commando__sub0': 'long_13_plus_frames'} | 0.077143 |
| ARPEGGIO | density_band | {'Draconus_2024__sub0': 'dense_7_plus', 'Warhawk__sub0': 'dense_7_plus', 'Ninja_Commando__sub0': 'medium_3_6'} | 0.517143 |
| ARPEGGIO | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Ninja_Commando__sub0': 'trio'} | 0.125 |
| GENERATOR_CHANGE | position_in_note | {'Draconus_2024__sub0': 'end', 'Warhawk__sub0': 'start', 'Red_Max__sub0': 'start'} | 0.494522 |
| GENERATOR_CHANGE | pitch_band | {'Draconus_2024__sub0': 'low_divider_high_pitch', 'Warhawk__sub0': 'low_divider_high_pitch', 'Red_Max__sub0': 'high_divider_low_pitch'} | 0.542749 |
| GENERATOR_CHANGE | note_length_band | {'Draconus_2024__sub0': 'short_1_3_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Red_Max__sub0': 'medium_4_12_frames'} | 0.550529 |
| GENERATOR_CHANGE | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.470894 |
| GENERATOR_CHANGE | previous_event_kind | {'Draconus_2024__sub0': 'VOLUME_CHANGE', 'Warhawk__sub0': 'VOLUME_ENVELOPE', 'Red_Max__sub0': 'PITCH_CHANGE'} | 0.206726 |
| GENERATOR_CHANGE | next_event_kind | {'Draconus_2024__sub0': 'NOTE_OFF', 'Warhawk__sub0': 'NOTE_OFF', 'Red_Max__sub0': 'VOLUME_ENVELOPE'} | 0.255361 |
| PITCH_SWEEP_RISING | company_band | {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Red_Max__sub0': 'trio'} | 0.258865 |
| PITCH_SWEEP_RISING | next_event_kind | {'Draconus_2024__sub0': 'GENERATOR_CHANGE', 'Warhawk__sub0': 'VOLUME_ENVELOPE', 'Red_Max__sub0': 'VOLUME_ENVELOPE'} | 0.430852 |

## 8. Parameter generalisation

7 of 12 techniques with comparable parameters have overlapping ranges across songs; 5 do not.

| technique | songs | comparable parameters | same | share | verdict |
|---|---|---|---|---|---|
| NOTE_OFF | 4 | 5 | 4 | 0.8 | PARAMETERS_GENERALISE |
| NOTE_ON | 4 | 6 | 5 | 0.833333 | PARAMETERS_GENERALISE |
| PITCH_CHANGE | 4 | 15 | 8 | 0.533333 | PARAMETERS_GENERALISE |
| PITCH_SLIDE_FALLING | 4 | 15 | 5 | 0.333333 | PARAMETERS_SONG_SPECIFIC |
| PITCH_SLIDE_RISING | 4 | 15 | 7 | 0.466667 | PARAMETERS_SONG_SPECIFIC |
| REGISTER_PATTERN_CHANGE | 4 | 4 | 2 | 0.5 | PARAMETERS_GENERALISE |
| TREMOLO | 4 | 7 | 2 | 0.285714 | PARAMETERS_SONG_SPECIFIC |
| VOLUME_CHANGE | 4 | 5 | 3 | 0.6 | PARAMETERS_GENERALISE |
| VOLUME_ENVELOPE_FALLING | 4 | 6 | 5 | 0.833333 | PARAMETERS_GENERALISE |
| ARPEGGIO | 3 | 7 | 2 | 0.285714 | PARAMETERS_SONG_SPECIFIC |
| GENERATOR_CHANGE | 3 | 6 | 3 | 0.5 | PARAMETERS_GENERALISE |
| PITCH_SWEEP_RISING | 3 | 15 | 5 | 0.333333 | PARAMETERS_SONG_SPECIFIC |

Numeric parameters across the songs that share the technique:

| technique | parameter | per-song min..max | median support overlap | verdict |
|---|---|---|---|---|
| NOTE_OFF | last_divider | Draconus_2024__sub0: 0.0..251.0; Warhawk__sub0: 0.0..2700.0; Ninja_Commando__sub0: 22.0..1800.0; Red_Max__sub0: 0.0..2700.0 | 0.392871 | DIFFERENT_RANGE |
| NOTE_OFF | last_hz | Draconus_2024__sub0: 125.669..31668.696; Warhawk__sub0: 123.706..31668.696; Ninja_Commando__sub0: 130.862..2194.86; Red_Max__sub0: 130.862..31668.696 | 0.532609 | SAME_RANGE |
| NOTE_OFF | note_frames | Draconus_2024__sub0: 2.0..840.0; Warhawk__sub0: 1.0..414.0; Ninja_Commando__sub0: 1.0..290.0; Red_Max__sub0: 3.0..216.0 | 0.503399 | SAME_RANGE |
| NOTE_OFF | note_index | Draconus_2024__sub0: 0.0..1339.0; Warhawk__sub0: 0.0..1510.0; Ninja_Commando__sub0: 0.0..453.0; Red_Max__sub0: 0.0..1223.0 | 0.590167 | SAME_RANGE |
| NOTE_ON | divider | Draconus_2024__sub0: 0.0..255.0; Warhawk__sub0: 0.0..2700.0; Ninja_Commando__sub0: 22.0..1800.0; Red_Max__sub0: 0.0..2700.0 | 0.393981 | DIFFERENT_RANGE |
| NOTE_ON | hz | Draconus_2024__sub0: 123.706..31668.696; Warhawk__sub0: 123.706..31668.696; Ninja_Commando__sub0: 130.862..2469.982; Red_Max__sub0: 327.567..31668.696 | 0.533845 | SAME_RANGE |
| NOTE_ON | note_frames | Draconus_2024__sub0: 2.0..840.0; Warhawk__sub0: 1.0..414.0; Ninja_Commando__sub0: 1.0..290.0; Red_Max__sub0: 3.0..216.0 | 0.503399 | SAME_RANGE |
| NOTE_ON | note_index | Draconus_2024__sub0: 0.0..1339.0; Warhawk__sub0: 0.0..1510.0; Ninja_Commando__sub0: 0.0..453.0; Red_Max__sub0: 0.0..1223.0 | 0.590167 | SAME_RANGE |
| NOTE_ON | volume | Draconus_2024__sub0: 1.0..15.0; Warhawk__sub0: 1.0..12.0; Ninja_Commando__sub0: 3.0..10.0; Red_Max__sub0: 3.0..10.0 | 0.636364 | SAME_RANGE |
| PITCH_CHANGE | accumulated_distinct_values | Draconus_2024__sub0: 2.0..35.0; Warhawk__sub0: 2.0..22.0; Ninja_Commando__sub0: 2.0..17.0; Red_Max__sub0: 2.0..97.0 | 0.400956 | DIFFERENT_RANGE |
| PITCH_CHANGE | accumulated_excursion_semitones | Draconus_2024__sub0: 0.187..76.98; Warhawk__sub0: 0.068..88.078; Ninja_Commando__sub0: 0.991..10.176; Red_Max__sub0: 0.926..96.0 | 0.456691 | DIFFERENT_RANGE |
| PITCH_CHANGE | accumulated_reversals | Draconus_2024__sub0: 0.0..180.0; Warhawk__sub0: 0.0..100.0; Ninja_Commando__sub0: 0.0..236.0; Red_Max__sub0: 0.0..5.0 | 0.236865 | DIFFERENT_RANGE |
| PITCH_CHANGE | end_divider | Draconus_2024__sub0: 0.0..255.0; Warhawk__sub0: 0.0..1510.0; Ninja_Commando__sub0: 29.0..802.0; Red_Max__sub0: 0.0..1800.0 | 0.35562 | DIFFERENT_RANGE |
| PITCH_CHANGE | end_hz | Draconus_2024__sub0: 123.706..31668.696; Warhawk__sub0: 123.706..31668.696; Ninja_Commando__sub0: 465.716..2194.86; Red_Max__sub0: 123.706..31668.696 | 0.527408 | SAME_RANGE |
| PITCH_CHANGE | interval_semitones | Draconus_2024__sub0: -36.0..76.98; Warhawk__sub0: -88.078..88.078; Ninja_Commando__sub0: -8.009..8.009; Red_Max__sub0: -96.0..57.059 | 0.339876 | DIFFERENT_RANGE |
| PITCH_CHANGE | note_frames | Draconus_2024__sub0: 2.0..840.0; Warhawk__sub0: 2.0..414.0; Ninja_Commando__sub0: 3.0..290.0; Red_Max__sub0: 3.0..133.0 | 0.397722 | DIFFERENT_RANGE |
| PITCH_CHANGE | note_index | Draconus_2024__sub0: 0.0..1339.0; Warhawk__sub0: 0.0..1509.0; Ninja_Commando__sub0: 0.0..434.0; Red_Max__sub0: 0.0..1223.0 | 0.582668 | SAME_RANGE |
| PITCH_CHANGE | peak_volume | Draconus_2024__sub0: 2.0..15.0; Warhawk__sub0: 2.0..12.0; Ninja_Commando__sub0: 3.0..10.0; Red_Max__sub0: 3.0..10.0 | 0.7 | SAME_RANGE |
| PITCH_CHANGE | start_divider | Draconus_2024__sub0: 0.0..255.0; Warhawk__sub0: 0.0..1200.0; Ninja_Commando__sub0: 29.0..900.0; Red_Max__sub0: 0.0..1606.0 | 0.396726 | DIFFERENT_RANGE |
| PITCH_CHANGE | start_hz | Draconus_2024__sub0: 123.706..31668.696; Warhawk__sub0: 123.706..31668.696; Ninja_Commando__sub0: 465.716..1961.778; Red_Max__sub0: 261.725..31668.696 | 0.52163 | SAME_RANGE |
| PITCH_CHANGE | steps | Draconus_2024__sub0: 1.0..1.0; Warhawk__sub0: 1.0..1.0; Ninja_Commando__sub0: 1.0..1.0; Red_Max__sub0: 1.0..1.0 | 1.0 | SAME_RANGE |
| PITCH_SLIDE_FALLING | accumulated_distinct_values | Draconus_2024__sub0: 3.0..35.0; Warhawk__sub0: 3.0..22.0; Ninja_Commando__sub0: 6.0..17.0; Red_Max__sub0: 3.0..97.0 | 0.342088 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | accumulated_excursion_semitones | Draconus_2024__sub0: 0.753..28.291; Warhawk__sub0: 1.992..82.146; Ninja_Commando__sub0: 1.863..8.844; Red_Max__sub0: 7.209..88.604 | 0.24674 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | accumulated_reversals | Draconus_2024__sub0: 0.0..180.0; Warhawk__sub0: 0.0..100.0; Ninja_Commando__sub0: 14.0..78.0; Red_Max__sub0: 0.0..43.0 | 0.400898 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | end_divider | Draconus_2024__sub0: 7.0..241.0; Warhawk__sub0: 0.0..105.0; Ninja_Commando__sub0: 32.0..52.0; Red_Max__sub0: 0.0..134.0 | 0.298557 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | end_hz | Draconus_2024__sub0: 130.862..3958.587; Warhawk__sub0: 298.761..31668.696; Ninja_Commando__sub0: 597.523..959.657; Red_Max__sub0: 234.583..31668.696 | 0.105327 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | interval_semitones | Draconus_2024__sub0: 0.284..28.291; Warhawk__sub0: 0.483..82.146; Ninja_Commando__sub0: 0.641..2.721; Red_Max__sub0: 0.284..71.169 | 0.206981 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | note_frames | Draconus_2024__sub0: 3.0..840.0; Warhawk__sub0: 3.0..414.0; Ninja_Commando__sub0: 50.0..290.0; Red_Max__sub0: 3.0..216.0 | 0.504644 | SAME_RANGE |
| PITCH_SLIDE_FALLING | note_index | Draconus_2024__sub0: 0.0..716.0; Warhawk__sub0: 0.0..501.0; Ninja_Commando__sub0: 0.0..260.0; Red_Max__sub0: 255.0..1075.0 | 0.395983 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | peak_volume | Draconus_2024__sub0: 1.0..13.0; Warhawk__sub0: 9.0..12.0; Ninja_Commando__sub0: 10.0..10.0; Red_Max__sub0: 8.0..10.0 | 0.083334 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | start_divider | Draconus_2024__sub0: 40.0..245.0; Warhawk__sub0: 38.0..114.0; Ninja_Commando__sub0: 36.0..54.0; Red_Max__sub0: 60.0..137.0 | 0.281308 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | start_hz | Draconus_2024__sub0: 128.735..772.407; Warhawk__sub0: 275.38..812.018; Ninja_Commando__sub0: 575.794..855.911; Red_Max__sub0: 229.483..519.159 | 0.412695 | DIFFERENT_RANGE |
| PITCH_SLIDE_FALLING | steps | Draconus_2024__sub0: 2.0..4.0; Warhawk__sub0: 2.0..3.0; Ninja_Commando__sub0: 2.0..3.0; Red_Max__sub0: 2.0..4.0 | 0.5 | SAME_RANGE |
| PITCH_SLIDE_RISING | accumulated_distinct_values | Draconus_2024__sub0: 3.0..35.0; Warhawk__sub0: 3.0..22.0; Ninja_Commando__sub0: 5.0..17.0; Red_Max__sub0: 3.0..97.0 | 0.357713 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | accumulated_excursion_semitones | Draconus_2024__sub0: 0.637..76.98; Warhawk__sub0: 0.825..82.146; Ninja_Commando__sub0: 1.863..10.176; Red_Max__sub0: 7.209..88.604 | 0.45102 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | accumulated_reversals | Draconus_2024__sub0: 0.0..180.0; Warhawk__sub0: 0.0..100.0; Ninja_Commando__sub0: 14.0..236.0; Red_Max__sub0: 0.0..43.0 | 0.397203 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | end_divider | Draconus_2024__sub0: 2.0..251.0; Warhawk__sub0: 38.0..171.0; Ninja_Commando__sub0: 35.0..54.0; Red_Max__sub0: 60.0..137.0 | 0.213442 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | end_hz | Draconus_2024__sub0: 125.669..10556.232; Warhawk__sub0: 184.12..812.018; Ninja_Commando__sub0: 575.794..879.686; Red_Max__sub0: 229.483..519.159 | 0.044666 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | interval_semitones | Draconus_2024__sub0: -26.764..-0.141; Warhawk__sub0: -82.146..-0.483; Ninja_Commando__sub0: -10.176..-0.641; Red_Max__sub0: -83.31..-0.256 | 0.319603 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | note_frames | Draconus_2024__sub0: 3.0..840.0; Warhawk__sub0: 3.0..414.0; Ninja_Commando__sub0: 50.0..290.0; Red_Max__sub0: 3.0..216.0 | 0.504644 | SAME_RANGE |
| PITCH_SLIDE_RISING | note_index | Draconus_2024__sub0: 0.0..1281.0; Warhawk__sub0: 0.0..1508.0; Ninja_Commando__sub0: 0.0..260.0; Red_Max__sub0: 15.0..1222.0 | 0.501682 | SAME_RANGE |
| PITCH_SLIDE_RISING | peak_volume | Draconus_2024__sub0: 3.0..13.0; Warhawk__sub0: 9.0..11.0; Ninja_Commando__sub0: 10.0..10.0; Red_Max__sub0: 10.0..10.0 | 0.0 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | start_divider | Draconus_2024__sub0: 0.0..243.0; Warhawk__sub0: 0.0..163.0; Ninja_Commando__sub0: 29.0..52.0; Red_Max__sub0: 0.0..133.0 | 0.360128 | DIFFERENT_RANGE |
| PITCH_SLIDE_RISING | start_hz | Draconus_2024__sub0: 129.79..31668.696; Warhawk__sub0: 193.102..31668.696; Ninja_Commando__sub0: 597.523..1055.623; Red_Max__sub0: 236.334..31668.696 | 0.505598 | SAME_RANGE |
| PITCH_SLIDE_RISING | steps | Draconus_2024__sub0: 2.0..4.0; Warhawk__sub0: 2.0..4.0; Ninja_Commando__sub0: 2.0..3.0; Red_Max__sub0: 2.0..4.0 | 0.75 | SAME_RANGE |
| REGISTER_PATTERN_CHANGE | audf_writes | Draconus_2024__sub0: 1.0..814.0; Warhawk__sub0: 1.0..7.0; Ninja_Commando__sub0: 1.0..1.0; Red_Max__sub0: 1.0..26.0 | 0.00369 | DIFFERENT_RANGE |
| REGISTER_PATTERN_CHANGE | end_audf | Draconus_2024__sub0: 12.0..245.0; Warhawk__sub0: 8.0..246.0; Ninja_Commando__sub0: 8.0..246.0; Red_Max__sub0: 8.0..247.0 | 0.987404 | SAME_RANGE |
| REGISTER_PATTERN_CHANGE | spans_frames | Draconus_2024__sub0: 1.0..814.0; Warhawk__sub0: 1.0..8.0; Ninja_Commando__sub0: 1.0..1.0; Red_Max__sub0: 1.0..26.0 | 0.004305 | DIFFERENT_RANGE |
| REGISTER_PATTERN_CHANGE | start_audf | Draconus_2024__sub0: 38.0..244.0; Warhawk__sub0: 8.0..246.0; Ninja_Commando__sub0: 8.0..246.0; Red_Max__sub0: 8.0..247.0 | 0.930681 | SAME_RANGE |
| TREMOLO | distinct_levels | Draconus_2024__sub0: 3.0..10.0; Warhawk__sub0: 7.0..7.0; Ninja_Commando__sub0: 4.0..10.0; Red_Max__sub0: 4.0..7.0 | 0.214285 | DIFFERENT_RANGE |
| TREMOLO | max_volume | Draconus_2024__sub0: 4.0..13.0; Warhawk__sub0: 9.0..9.0; Ninja_Commando__sub0: 9.0..10.0; Red_Max__sub0: 8.0..10.0 | 0.055556 | DIFFERENT_RANGE |
| TREMOLO | min_volume | Draconus_2024__sub0: 1.0..7.0; Warhawk__sub0: 2.0..2.0; Ninja_Commando__sub0: 1.0..6.0; Red_Max__sub0: 1.0..6.0 | 0.416666 | DIFFERENT_RANGE |
| TREMOLO | note_index | Draconus_2024__sub0: 0.0..716.0; Warhawk__sub0: 0.0..1225.0; Ninja_Commando__sub0: 0.0..453.0; Red_Max__sub0: 1.0..1075.0 | 0.608586 | SAME_RANGE |
| TREMOLO | reversals | Draconus_2024__sub0: 2.0..97.0; Warhawk__sub0: 2.0..13.0; Ninja_Commando__sub0: 2.0..34.0; Red_Max__sub0: 2.0..10.0 | 0.293421 | DIFFERENT_RANGE |
| TREMOLO | steps | Draconus_2024__sub0: 3.0..202.0; Warhawk__sub0: 7.0..62.0; Ninja_Commando__sub0: 9.0..112.0; Red_Max__sub0: 4.0..29.0 | 0.327846 | DIFFERENT_RANGE |
| VOLUME_CHANGE | end_level | Draconus_2024__sub0: 1.0..15.0; Warhawk__sub0: 1.0..12.0; Ninja_Commando__sub0: 7.0..9.0; Red_Max__sub0: 2.0..10.0 | 0.410714 | DIFFERENT_RANGE |
| VOLUME_CHANGE | note_index | Draconus_2024__sub0: 3.0..1339.0; Warhawk__sub0: 3.0..1510.0; Ninja_Commando__sub0: 0.0..452.0; Red_Max__sub0: 0.0..1223.0 | 0.588765 | SAME_RANGE |
| VOLUME_CHANGE | start_level | Draconus_2024__sub0: 1.0..15.0; Warhawk__sub0: 1.0..12.0; Ninja_Commando__sub0: 8.0..10.0; Red_Max__sub0: 3.0..10.0 | 0.392857 | DIFFERENT_RANGE |
| VOLUME_CHANGE | steps | Draconus_2024__sub0: 1.0..2.0; Warhawk__sub0: 1.0..2.0; Ninja_Commando__sub0: 1.0..1.0; Red_Max__sub0: 1.0..2.0 | 0.5 | SAME_RANGE |
| VOLUME_ENVELOPE_FALLING | end_level | Draconus_2024__sub0: 1.0..9.0; Warhawk__sub0: 1.0..8.0; Ninja_Commando__sub0: 1.0..6.0; Red_Max__sub0: 1.0..6.0 | 0.714286 | SAME_RANGE |
| VOLUME_ENVELOPE_FALLING | note_index | Draconus_2024__sub0: 0.0..1336.0; Warhawk__sub0: 0.0..1506.0; Ninja_Commando__sub0: 0.0..452.0; Red_Max__sub0: 0.0..1221.0 | 0.590472 | SAME_RANGE |
| VOLUME_ENVELOPE_FALLING | start_level | Draconus_2024__sub0: 4.0..15.0; Warhawk__sub0: 5.0..11.0; Ninja_Commando__sub0: 9.0..10.0; Red_Max__sub0: 6.0..10.0 | 0.306818 | DIFFERENT_RANGE |
| VOLUME_ENVELOPE_FALLING | steps | Draconus_2024__sub0: 3.0..10.0; Warhawk__sub0: 3.0..7.0; Ninja_Commando__sub0: 3.0..7.0; Red_Max__sub0: 3.0..9.0 | 0.666667 | SAME_RANGE |
| ARPEGGIO | accumulated_distinct_values | Draconus_2024__sub0: 2.0..6.0; Warhawk__sub0: 2.0..4.0; Ninja_Commando__sub0: 2.0..6.0 | 0.5 | SAME_RANGE |
| ARPEGGIO | accumulated_excursion_semitones | Draconus_2024__sub0: 1.136..22.119; Warhawk__sub0: 1.762..96.0; Ninja_Commando__sub0: 1.863..11.169 | 0.214591 | DIFFERENT_RANGE |
| ARPEGGIO | accumulated_reversals | Draconus_2024__sub0: 2.0..13.0; Warhawk__sub0: 2.0..93.0; Ninja_Commando__sub0: 14.0..237.0 | 0.120879 | DIFFERENT_RANGE |
| ARPEGGIO | note_frames | Draconus_2024__sub0: 24.0..320.0; Warhawk__sub0: 5.0..106.0; Ninja_Commando__sub0: 50.0..241.0 | 0.260317 | DIFFERENT_RANGE |
| ARPEGGIO | note_index | Draconus_2024__sub0: 5.0..488.0; Warhawk__sub0: 5.0..1350.0; Ninja_Commando__sub0: 0.0..251.0 | 0.359108 | DIFFERENT_RANGE |
| ARPEGGIO | steps | Draconus_2024__sub0: 3.0..27.0; Warhawk__sub0: 3.0..94.0; Ninja_Commando__sub0: 27.0..239.0 | 0.263736 | DIFFERENT_RANGE |
| GENERATOR_CHANGE | note_frames | Draconus_2024__sub0: 2.0..7.0; Warhawk__sub0: 3.0..106.0; Red_Max__sub0: 3.0..102.0 | 0.04 | DIFFERENT_RANGE |
| GENERATOR_CHANGE | note_index | Draconus_2024__sub0: 3.0..1305.0; Warhawk__sub0: 0.0..1510.0; Red_Max__sub0: 0.0..1222.0 | 0.862252 | SAME_RANGE |
| PITCH_SWEEP_RISING | accumulated_distinct_values | Draconus_2024__sub0: 3.0..15.0; Warhawk__sub0: 5.0..6.0; Red_Max__sub0: 4.0..90.0 | 0.083333 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | accumulated_excursion_semitones | Draconus_2024__sub0: 3.406..71.52; Warhawk__sub0: 9.462..89.115; Red_Max__sub0: 7.209..88.604 | 0.754842 | SAME_RANGE |
| PITCH_SWEEP_RISING | accumulated_reversals | Draconus_2024__sub0: 0.0..34.0; Warhawk__sub0: 0.0..0.0; Red_Max__sub0: 0.0..43.0 | 0.0 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | end_divider | Draconus_2024__sub0: 25.0..248.0; Warhawk__sub0: 12.0..171.0; Red_Max__sub0: 61.0..166.0 | 0.618644 | SAME_RANGE |
| PITCH_SWEEP_RISING | end_hz | Draconus_2024__sub0: 127.184..1218.027; Warhawk__sub0: 184.12..2436.054; Red_Max__sub0: 189.633..510.785 | 0.294408 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | interval_semitones | Draconus_2024__sub0: -71.52..-3.406; Warhawk__sub0: -89.115..-9.462; Red_Max__sub0: -83.31..-3.125 | 0.849461 | SAME_RANGE |
| PITCH_SWEEP_RISING | note_frames | Draconus_2024__sub0: 4.0..200.0; Warhawk__sub0: 5.0..7.0; Red_Max__sub0: 6.0..216.0 | 0.010204 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | note_index | Draconus_2024__sub0: 3.0..1334.0; Warhawk__sub0: 33.0..1510.0; Red_Max__sub0: 281.0..1062.0 | 0.586777 | SAME_RANGE |
| PITCH_SWEEP_RISING | peak_volume | Draconus_2024__sub0: 1.0..15.0; Warhawk__sub0: 5.0..11.0; Red_Max__sub0: 9.0..10.0 | 0.166667 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | start_divider | Draconus_2024__sub0: 3.0..152.0; Warhawk__sub0: 0.0..10.0; Red_Max__sub0: 0.0..106.0 | 0.09434 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | start_hz | Draconus_2024__sub0: 206.985..7917.174; Warhawk__sub0: 2878.972..31668.696; Red_Max__sub0: 295.969..31668.696 | 0.242237 | DIFFERENT_RANGE |
| PITCH_SWEEP_RISING | steps | Draconus_2024__sub0: 2.0..4.0; Warhawk__sub0: 4.0..5.0; Red_Max__sub0: 2.0..88.0 | 0.011628 | DIFFERENT_RANGE |

## 9. Leave-one-song-out results

leave-one-song-out: for each song, train on the other songs and describe it

| held out | events | technique coverage | core-context coverage | parameter coverage | unknown share | techniques unknown to training |
|---|---|---|---|---|---|---|
| Draconus_2024__sub0 | 13480 | 0.99822 | 0.094456 | 0.881225 | 0.00178 | DISTORTION_CHANGE |
| Warhawk__sub0 | 18286 | 1.0 | 0.04982 | 0.972701 | 0.0 | none |
| Ninja_Commando__sub0 | 5360 | 1.0 | 0.022015 | 0.986569 | 0.0 | none |
| Red_Max__sub0 | 14151 | 1.0 | 0.023744 | 0.974811 | 0.0 | none |

| held out | context coverage by dimension (value was seen) |
|---|---|
| Draconus_2024__sub0 | family_bucket 0.96418; position_in_note 0.982907; pitch_band 0.987961; note_length_band 1.0; density_band 0.99896; company_band 0.427393; previous_event_kind 0.957194; next_event_kind 0.956822 |
| Warhawk__sub0 | family_bucket 0.998852; position_in_note 1.0; pitch_band 0.999836; note_length_band 1.0; density_band 0.999672; company_band 0.999289; previous_event_kind 0.981407; next_event_kind 0.981625 |
| Ninja_Commando__sub0 | family_bucket 1.0; position_in_note 1.0; pitch_band 1.0; note_length_band 1.0; density_band 0.999813; company_band 0.988619; previous_event_kind 0.999254; next_event_kind 0.998507 |
| Red_Max__sub0 | family_bucket 1.0; position_in_note 1.0; pitch_band 0.999788; note_length_band 1.0; density_band 1.0; company_band 1.0; previous_event_kind 0.981556; next_event_kind 0.981697 |

Two context numbers are published because they answer different questions. *Value seen* asks whether the training songs ever used that context value; it is easily satisfied and therefore weak. *Dominant match* asks whether the held-out event's value is the one that dominates that technique in training — a prediction, and the stricter of the two.

| held out | dominant-context match by dimension (mean over core factors) | core three-dimension conjunction |
|---|---|---|
| Draconus_2024__sub0 | 0.767008 | 0.094456 |
| Warhawk__sub0 | 0.813711 | 0.04982 |
| Ninja_Commando__sub0 | 0.741936 | 0.022015 |
| Red_Max__sub0 | 0.822411 | 0.023744 |

| dimension | dominant match rate (first held-out fold) |
|---|---|
| family_bucket | 0.715146 |
| position_in_note | 0.933615 |
| pitch_band | 0.652264 |
| note_length_band | 0.488643 |
| density_band | 0.981883 |
| company_band | 0.137782 |
| previous_event_kind | 0.841076 |
| next_event_kind | 0.415829 |

With three training songs, a held-out song's events are covered at 1.0 at the technique level, 0.036782 at the core-context level and 0.973756 at the parameter-support level — the last two conditional on the technique being known.

Read the layers in order, because they are conditional: context and parameter coverage are measured only over the events whose technique the training songs already knew. The technique figure is printed first for that reason.

**Is one song an unusually good source?** Every song used alone as the whole training set, which is the situation Stage 15 was actually in:

| sole reference | mean technique coverage | mean dominant-context match | mean parameter support coverage |
|---|---|---|---|
| Draconus_2024__sub0 | 1.0 | 0.000307 | 0.922924 |
| Warhawk__sub0 | 0.999407 | 0.037645 | 0.918492 |
| Ninja_Commando__sub0 | 0.894558 | 0.093226 | 0.691879 |
| Red_Max__sub0 | 0.99753 | 0.102634 | 0.872948 |

As a single training song, Draconus_2024__sub0 covers 1.0, Warhawk__sub0 covers 0.999407, Ninja_Commando__sub0 covers 0.894558, Red_Max__sub0 covers 0.99753 of the other songs' events at the technique level.

## 10. Universal vs common vs song-specific techniques

| threshold | value |
|---|---|
| minimum_occurrences_in_song | 20 |
| universal_songs_required | 3 of 4 (UNIVERSAL_SONG_SHARE=0.75) |
| universal_context | context verdict is SAME_CONTEXT or MOSTLY_SAME_CONTEXT (dimension-level agreement, dominance threshold 0.4) |
| universal_parameters | parameter verdict is PARAMETERS_GENERALISE |
| common | evidence in at least two songs but not meeting the UNIVERSAL conditions |
| song_specific | evidence in exactly one song |
| unknown | never reaches the minimum occurrence count in any song |

3 techniques are universal (0 of them not low-level), 9 are common, 2 are song-specific and 2 have too little evidence.

| technique | verdict | songs with evidence | context | parameters | low level | occurrences |
|---|---|---|---|---|---|---|
| ARPEGGIO | COMMON | 3 | MOSTLY_SAME_CONTEXT | PARAMETERS_SONG_SPECIFIC | False | 448 |
| DISTORTION_CHANGE | SONG_SPECIFIC | 1 | NOT_COMPARABLE | NOT_COMPARABLE | False | 24 |
| GENERATOR_CHANGE | COMMON | 3 | MOSTLY_DIFFERENT_CONTEXT | PARAMETERS_GENERALISE | False | 4957 |
| NOTE_OFF | UNIVERSAL | 4 | MOSTLY_SAME_CONTEXT | PARAMETERS_GENERALISE | True | 10200 |
| NOTE_ON | UNIVERSAL | 4 | MOSTLY_SAME_CONTEXT | PARAMETERS_GENERALISE | True | 10200 |
| PITCH_CHANGE | COMMON | 4 | MOSTLY_DIFFERENT_CONTEXT | PARAMETERS_GENERALISE | True | 8392 |
| PITCH_SLIDE_FALLING | COMMON | 4 | MOSTLY_SAME_CONTEXT | PARAMETERS_SONG_SPECIFIC | False | 1535 |
| PITCH_SLIDE_RISING | COMMON | 4 | MOSTLY_SAME_CONTEXT | PARAMETERS_SONG_SPECIFIC | False | 2081 |
| PITCH_SWEEP_FALLING | UNKNOWN | 0 | NOT_COMPARABLE | NOT_COMPARABLE | False | 37 |
| PITCH_SWEEP_RISING | COMMON | 3 | MOSTLY_SAME_CONTEXT | PARAMETERS_SONG_SPECIFIC | False | 695 |
| REGISTER_PATTERN_CHANGE | COMMON | 4 | MIXED_CONTEXT | PARAMETERS_GENERALISE | True | 2365 |
| TREMOLO | COMMON | 4 | MIXED_CONTEXT | PARAMETERS_SONG_SPECIFIC | False | 1681 |
| VIBRATO | SONG_SPECIFIC | 1 | NOT_COMPARABLE | NOT_COMPARABLE | False | 47 |
| VOLUME_CHANGE | UNIVERSAL | 4 | MOSTLY_SAME_CONTEXT | PARAMETERS_GENERALISE | True | 4183 |
| VOLUME_ENVELOPE_FALLING | COMMON | 4 | MIXED_CONTEXT | PARAMETERS_GENERALISE | False | 4418 |
| VOLUME_ENVELOPE_RISING | UNKNOWN | 0 | NOT_COMPARABLE | NOT_COMPARABLE | False | 14 |

A technique that reaches UNIVERSAL only because the detector names it the same way everywhere is the least informative result in this table; that is what the low-level column marks.

## 11. Ambiguous low-level behaviours

Does the same low-level register behaviour carry the same meaning in every song?

2 shared techniques have incompatible dominant contexts; 1 coarse event classes sit on a different generator family depending on the song; 1 techniques change generator family between songs; 2 techniques appear in one song only.

**The same technique name, a different meaning:**

| technique | songs | median overlap | dimensions that disagree |
|---|---|---|---|
| PITCH_CHANGE | 4 | MOSTLY_DIFFERENT_CONTEXT | note_length_band -> {'Draconus_2024__sub0': 'medium_4_12_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Ninja_Commando__sub0': 'long_13_plus_frames', 'Red_Max__sub0': 'short_1_3_frames'}; previous_event_kind -> {'Draconus_2024__sub0': 'VOLUME_CHANGE', 'Warhawk__sub0': 'NOTE_ON', 'Ninja_Commando__sub0': 'PITCH_CHANGE', 'Red_Max__sub0': 'NOTE_ON'}; next_event_kind -> {'Draconus_2024__sub0': 'NOTE_OFF', 'Warhawk__sub0': 'VOLUME_CHANGE', 'Ninja_Commando__sub0': 'PITCH_CHANGE', 'Red_Max__sub0': 'GENERATOR_CHANGE'} |
| GENERATOR_CHANGE | 3 | MOSTLY_DIFFERENT_CONTEXT | position_in_note -> {'Draconus_2024__sub0': 'end', 'Warhawk__sub0': 'start', 'Red_Max__sub0': 'start'}; pitch_band -> {'Draconus_2024__sub0': 'low_divider_high_pitch', 'Warhawk__sub0': 'low_divider_high_pitch', 'Red_Max__sub0': 'high_divider_low_pitch'}; note_length_band -> {'Draconus_2024__sub0': 'short_1_3_frames', 'Warhawk__sub0': 'medium_4_12_frames', 'Red_Max__sub0': 'medium_4_12_frames'}; company_band -> {'Draconus_2024__sub0': 'full', 'Warhawk__sub0': 'trio', 'Red_Max__sub0': 'trio'}; previous_event_kind -> {'Draconus_2024__sub0': 'VOLUME_CHANGE', 'Warhawk__sub0': 'VOLUME_ENVELOPE', 'Red_Max__sub0': 'PITCH_CHANGE'}; next_event_kind -> {'Draconus_2024__sub0': 'NOTE_OFF', 'Warhawk__sub0': 'NOTE_OFF', 'Red_Max__sub0': 'VOLUME_ENVELOPE'} |

Worked example, PITCH_CHANGE: the same detected technique, with the evidence each song supplies for it:

| song | frame | channel | classification | evidence |
|---|---|---|---|---|
| Draconus_2024__sub0 | 40 | 1 | UNKNOWN_REGISTER_PATTERN | generator is unpitched noise (poly9_17): AUDF sets the noise clock, not a pitch |
| Ninja_Commando__sub0 | 161 | 3 | REAL_MUSICAL_BEHAVIOUR | audible tonal voice (pure_tone) whose divider changed while sounding |
| Red_Max__sub0 | 0 | 3 | REAL_MUSICAL_BEHAVIOUR | audible tonal voice (pure_tone) whose divider changed while sounding |

**The same event class, sitting on a different generator:** this is the case where identical low-level arithmetic has a different musical function.

| event kind | dominant generator per song | distributions |
|---|---|---|
| NOTE_ON | {'Draconus_2024__sub0': 'tonal', 'Warhawk__sub0': 'noise', 'Ninja_Commando__sub0': 'tonal', 'Red_Max__sub0': 'tonal'} | Draconus_2024__sub0: {'noise': 0.409204, 'tonal': 0.590796}; Warhawk__sub0: {'noise': 0.542881, 'tonal': 0.457119}; Ninja_Commando__sub0: {'tonal': 1.0}; Red_Max__sub0: {'noise': 0.468262, 'tonal': 0.531738} |

| technique | dominant generator per song |
|---|---|
| NOTE_ON | {'Draconus_2024__sub0': 'tonal', 'Warhawk__sub0': 'noise', 'Ninja_Commando__sub0': 'tonal', 'Red_Max__sub0': 'tonal'} |

Song-specific techniques (present at usable volume in exactly one song): DISTORTION_CHANGE, VIBRATO.

## 12. Cross-song style model

**CrossSongPerformanceStyle** — research-only conceptual model; not a production schema, not a SoundProfile, and not implemented anywhere.

| belongs in the style |  |
|---|---|
| common techniques | ARPEGGIO, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE_FALLING, PITCH_SLIDE_RISING, PITCH_SWEEP_RISING, REGISTER_PATTERN_CHANGE, TREMOLO, VOLUME_CHANGE, VOLUME_ENVELOPE_FALLING |
| context dimensions | family_bucket, density_band, pitch_band, position_in_note, previous_event_kind |
| parameter envelopes | per shared technique, the union of the observed ranges — published as an envelope, never as a value to copy |
| coverage expectation | technique 1.0; core_context 0.036782; parameter_support 0.973756 |

| must stay attached to the source song |  |
|---|---|
| song_specific_techniques | DISTORTION_CHANGE, VIBRATO |
| channel_indices | which channel plays which part is a per-song layout decision |
| absolute_pitch_values | divider values are absolute register settings, not interval relationships |
| temporal_layout | onset grid, section order and repetition counts are per-song |
| generator_configuration | AUDCTL is a whole-song choice in this corpus, so it is a song property rather than a style property |

| common technique | support | context agrees | context disagrees | parameter overlap | share of each song |
|---|---|---|---|---|---|
| ARPEGGIO | Draconus_2024__sub0, Ninja_Commando__sub0, Warhawk__sub0 | family_bucket, position_in_note, pitch_band, previous_event_kind, next_event_kind | note_length_band, density_band, company_band | 0.285714 | Draconus_2024__sub0 0.003561; Warhawk__sub0 0.01914; Ninja_Commando__sub0 0.00653; Red_Max__sub0 0.00106 |
| GENERATOR_CHANGE | Draconus_2024__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, density_band | position_in_note, pitch_band, note_length_band, company_band, previous_event_kind, next_event_kind | 0.5 | Draconus_2024__sub0 0.071365; Warhawk__sub0 0.136607; Ninja_Commando__sub0 None; Red_Max__sub0 0.105788 |
| NOTE_OFF | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, position_in_note, pitch_band, density_band, next_event_kind | note_length_band, company_band, previous_event_kind | 0.8 | Draconus_2024__sub0 0.207938; Warhawk__sub0 0.197036; Ninja_Commando__sub0 0.169963; Red_Max__sub0 0.203731 |
| NOTE_ON | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | position_in_note, pitch_band, density_band, previous_event_kind | family_bucket, note_length_band, company_band, next_event_kind | 0.833333 | Draconus_2024__sub0 0.207938; Warhawk__sub0 0.197036; Ninja_Commando__sub0 0.169963; Red_Max__sub0 0.203731 |
| PITCH_CHANGE | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, density_band | position_in_note, pitch_band, note_length_band, company_band, previous_event_kind, next_event_kind | 0.533333 | Draconus_2024__sub0 0.098813; Warhawk__sub0 0.128787; Ninja_Commando__sub0 0.282836; Red_Max__sub0 0.225355 |
| PITCH_SLIDE_FALLING | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, note_length_band, density_band, previous_event_kind, next_event_kind | position_in_note, pitch_band, company_band | 0.333333 | Draconus_2024__sub0 0.059941; Warhawk__sub0 0.021437; Ninja_Commando__sub0 0.039925; Red_Max__sub0 0.008551 |
| PITCH_SLIDE_RISING | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, pitch_band, note_length_band, density_band, previous_event_kind, next_event_kind | position_in_note, company_band | 0.466667 | Draconus_2024__sub0 0.084199; Warhawk__sub0 0.029914; Ninja_Commando__sub0 0.042537; Red_Max__sub0 0.012084 |
| PITCH_SWEEP_RISING | Draconus_2024__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, position_in_note, pitch_band, note_length_band, density_band, previous_event_kind | company_band, next_event_kind | 0.333333 | Draconus_2024__sub0 0.04184; Warhawk__sub0 0.004594; Ninja_Commando__sub0 0.001493; Red_Max__sub0 0.002756 |
| REGISTER_PATTERN_CHANGE | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, position_in_note, note_length_band, company_band | pitch_band, density_band, previous_event_kind, next_event_kind | 0.5 | Draconus_2024__sub0 0.004674; Warhawk__sub0 0.06896; Ninja_Commando__sub0 0.061754; Red_Max__sub0 0.050173 |
| TREMOLO | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, position_in_note, density_band, previous_event_kind | pitch_band, note_length_band, company_band, next_event_kind | 0.285714 | Draconus_2024__sub0 0.024629; Warhawk__sub0 0.052171; Ninja_Commando__sub0 0.017164; Red_Max__sub0 0.021412 |
| VOLUME_CHANGE | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, position_in_note, pitch_band, density_band | note_length_band, company_band, previous_event_kind, next_event_kind | 0.6 | Draconus_2024__sub0 0.137834; Warhawk__sub0 0.064421; Ninja_Commando__sub0 0.080224; Red_Max__sub0 0.050668 |
| VOLUME_ENVELOPE_FALLING | Draconus_2024__sub0, Ninja_Commando__sub0, Red_Max__sub0, Warhawk__sub0 | family_bucket, position_in_note, note_length_band, density_band | pitch_band, company_band, previous_event_kind, next_event_kind | 0.833333 | Draconus_2024__sub0 0.053338; Warhawk__sub0 0.077655; Ninja_Commando__sub0 0.123507; Red_Max__sub0 0.114268 |

these four songs are not a random sample of Atari music; they are a deterministic diversity selection from a twelve-subsong corpus, so 'cross-song' here means 'across these four'

## 13. Alternative "vocabulary + grammar" model

| model | statement |
|---|---|
| A | one universal Performance Style, applicable as learned |
| B | a shared POKEY performance vocabulary plus a song-specific contextual grammar |
| C | mostly song-specific behaviour with little that transfers |

| evidence | value |
|---|---|
| technique_coverage | 1.0 |
| core_context_coverage | 0.036782 |
| parameter_coverage | 0.973756 |
| song_specific_share | 0.125 |
| semantically_ambiguous_techniques | 2 |
| techniques_with_different_context | 2 |
| vocabulary_overlap_jaccard | 0.861905 |
| vocabulary_overlap_ruzicka | 0.45579 |
| techniques_generalising_parameters | 7 |

| model A condition | met? |
|---|---|
| technique_coverage_at_least_0.90 | True |
| core_context_prediction_at_least_0.50 | False |
| parameter_core_coverage_at_least_0.70 | True |
| song_specific_share_at_most_0.10 | False |
| few_semantically_ambiguous_techniques | False |

| model C condition | met? |
|---|---|
| technique_coverage_below_0.70 | False |
| song_specific_share_above_0.30 | False |

**VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED** — The vocabulary transfers but the grammar does not: identifiers are widely shared (mean Jaccard 0.861905) while core context coverage is 0.036782 and 2 shared techniques sit in different contexts in different songs. That is Model B: a common vocabulary that needs a per-song grammar to mean anything.

| generalisation level | value | threshold | supported | evidence |
|---|---|---|---|---|
| SCHEMA_GENERALISATION | 0.88141 | 0.7 | True | mean pairwise Jaccard over the coarse event-class sets |
| TECHNIQUE_GENERALISATION | 1.0 | 0.9 | True | leave-one-song-out median share of a song's events whose technique is known |
| CONTEXT_GENERALISATION | 0.579545 | 0.6 | False | share of decidable technique-by-dimension context tests that agree across songs, with a leave-one-song-out dominant-context match of 0.790359 and a three-dimension conjunction of 0.036782 |
| PARAMETER_GENERALISATION | 0.583333 | 0.6 | False | share of techniques with comparable parameters whose ranges overlap, with leave-one-song-out support coverage of 0.973756 and core coverage of 0.867923 |

A universal schema is compatible with a song-specific style. One number called 'generalisation' would hide that, so each level is measured and judged on its own with its own threshold.

## 14. Player implications

the common cross-song subset (techniques with evidence in at least two songs, excluding low-level classes), mapped through Stage 15's own mechanism table rather than a new one

The common cross-song behaviour needs 3 conceptual commands: EFFECT id, p1, p2 attached to the preceding note (would be new); SET_GENERATOR audc (would be new); SET_VOLUME level / SHAPE id (would be new). 3 of them do not exist today. 2 techniques are song-specific and would need commands of their own, so a vocabulary sized for the common case would not cover them.

| technique | verdict | songs | stage 15 mechanism | conceptual command | new? |
|---|---|---|---|---|---|
| ARPEGGIO | COMMON | 3 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| DISTORTION_CHANGE | SONG_SPECIFIC | 1 | generator_change_inside_song | SET_GENERATOR audc (would be new) | True |
| GENERATOR_CHANGE | COMMON | 3 | generator_change_inside_song | SET_GENERATOR audc (would be new) | True |
| NOTE_OFF | UNIVERSAL | 4 | 4_independent_channels | NOTE with a duration field (already present) | False |
| NOTE_ON | UNIVERSAL | 4 | 4_independent_channels | NOTE with a duration field (already present) | False |
| PITCH_CHANGE | COMMON | 4 | per_channel_note_duration | NOTE duration in ticks (already present) | False |
| PITCH_SLIDE_FALLING | COMMON | 4 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| PITCH_SLIDE_RISING | COMMON | 4 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| PITCH_SWEEP_FALLING | UNKNOWN | 0 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| PITCH_SWEEP_RISING | COMMON | 3 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| REGISTER_PATTERN_CHANGE | COMMON | 4 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| TREMOLO | COMMON | 4 | per_frame_volume_macro | SET_VOLUME level / SHAPE id (would be new) | True |
| VIBRATO | SONG_SPECIFIC | 1 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| VOLUME_CHANGE | UNIVERSAL | 4 | note_volume_from_data | NOTE volume (already present) | False |
| VOLUME_ENVELOPE_FALLING | COMMON | 4 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |
| VOLUME_ENVELOPE_RISING | UNKNOWN | 0 | effect_column | EFFECT id, p1, p2 attached to the preceding note (would be new) | True |

This says nothing about player size. Stage 15 measured that the mechanisms this behaviour needs already fit the current 2 KB envelope; the constraint there and here is the three-byte event format, which is a data-encoding question.

## 15. Answers to the research questions

**Q1 Does the Performance Technique vocabulary generalise across songs?**

Mostly. The four songs between them use 16 techniques; 12 appear in all four and 1 appear in only one. Mean pairwise Jaccard is 0.861905 and leave-one-song-out technique coverage is 1.0 of events. The inventory transfers; the proportions do not, which is what the Ruzicka figure (0.45579) exposes.

**Q2 Do the same context dimensions remain important across songs?**

Partly. 7 of 12 comparable techniques keep a consistent context; 2 do not. The dimensions that survive best are family_bucket, density_band, pitch_band; the least portable is previous_event_kind. `channel` cannot be tested at all: it is a song-local index.

**Q3 Do technique parameter distributions generalise?**

Only partly. 7 of 12 techniques with comparable parameters have overlapping ranges across songs; 5 do not. Leave-one-song-out parameter-support coverage is 0.973756, which looks high until it is read next to the core-range coverage: a value inside another song's observed span is not the same as a value in the middle of it.

**Q4 How much of a held-out song can be explained by knowledge from other songs?**

With three training songs: 1.0 of events at the technique level, 0.036782 at the core context level and 0.973756 at the parameter level (the last two conditional on the technique being known). Best-covered song Warhawk__sub0 (1.0); worst-covered Draconus_2024__sub0 (0.99822).

**Q5 Is Draconus representative or an outlier?**

As a single training song, Draconus_2024__sub0 covers 1.0, Warhawk__sub0 covers 0.999407, Ninja_Commando__sub0 covers 0.894558, Red_Max__sub0 covers 0.99753 of the other songs' events at the technique level. Best and worst single reference: Draconus_2024__sub0 and Ninja_Commando__sub0. Draconus is the strongest single source on this evidence, but it is one of four and the margin is small, so it is not promoted to a canonical style.

**Q6 Which techniques appear universal?**

Universal: NOTE_OFF, NOTE_ON, VOLUME_CHANGE. Excluding the low-level classes the detector defines identically everywhere, that reduces to: none. This is where a high vocabulary overlap is most misleading, which is why the low-level classes are flagged and counted separately.

**Q7 Which techniques appear song-specific?**

2 techniques reach the evidence threshold in exactly one song: DISTORTION_CHANGE, VIBRATO. Their share of the vocabulary is 0.125.

**Q8 Are low-level POKEY behaviours semantically ambiguous across songs?**

Yes, and this is the strongest negative result in the stage. 2 shared techniques have incompatible dominant contexts; 1 coarse event classes sit on a different generator family depending on the song; 1 techniques change generator family between songs; 2 techniques appear in one song only. The clearest case is a register ramp that reads as a pitch gesture in one song and a noise-clock sweep in another: identical low-level arithmetic, different musical function.

**Q9 Is a universal Performance Style supported?**

GENERALIZATION_PARTIALLY_SUPPORTED: SCHEMA_GENERALISATION=0.88141 (pass at 0.7); TECHNIQUE_GENERALISATION=1.0 (pass at 0.9); CONTEXT_GENERALISATION=0.579545 (fail at 0.6); PARAMETER_GENERALISATION=0.583333 (fail at 0.6). The technique level transfers, the context and parameter levels do not reach the bar, and song-specific techniques remain.

**Q10 Is a shared POKEY vocabulary + song-specific grammar better supported?**

VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED. The vocabulary transfers but the grammar does not: identifiers are widely shared (mean Jaccard 0.861905) while core context coverage is 0.036782 and 2 shared techniques sit in different contexts in different songs. That is Model B: a common vocabulary that needs a per-song grammar to mean anything.

**Q11 What is the minimum event vocabulary needed for the common cross-song behaviour?**

The common cross-song behaviour needs 3 conceptual commands: EFFECT id, p1, p2 attached to the preceding note (would be new); SET_GENERATOR audc (would be new); SET_VOLUME level / SHAPE id (would be new). 3 of them do not exist today. 2 techniques are song-specific and would need commands of their own, so a vocabulary sized for the common case would not cover them. The common subset is 7 techniques: ARPEGGIO, GENERATOR_CHANGE, PITCH_SLIDE_FALLING, PITCH_SLIDE_RISING, PITCH_SWEEP_RISING, TREMOLO, VOLUME_ENVELOPE_FALLING.

**Q12 Does any of this justify modifying the player?**

No. Stage 15 established that the mechanisms this behaviour needs already fit the current 2 KB envelope, and nothing here changes that: the commands the common subset needs are still the same handful of families, and the limit is still the three-byte event format rather than code space. Widening the command set is not justified by a vocabulary that is only partially portable.

## 16. Limitations

| limitation | what it means |
|---|---|
| four songs, not a sample | the corpus is twelve subsongs of 1986-1990 game music plus one 2024 production; four songs chosen for spread are not a random sample of Atari music |
| almost one POKEY configuration | three of the four songs use AUDCTL $50, so nothing here tests cross-configuration generalisation |
| the analysis is reused, so its heuristics are inherited | note boundaries are inferred (4 semitones and 3 frames of persistence, or a 4-level volume re-attack), technique identity is inferred, and the apparent universality of a low-level class is partly an artefact of one detector being used everywhere |
| parameters are compared as ranges | range overlap says two songs use the same span, not that they use it the same way |
| no perceptual evidence | nothing here says any technique is heard as such, and no listening test was run |
| context coverage is conditional | the context and parameter percentages are computed over the events whose technique training already knew, so they are not shares of the whole song |
| three of the four composers are British, 1986-1990 | a shared idiom may be a shared era or a shared platform rather than a shared style |

## 17. Stage 16 verdict

**GENERALIZATION_PARTIALLY_SUPPORTED**

Technique identifiers transfer at 1.0, so the vocabulary is real; context and parameters do not transfer to the same standard, and song-specific techniques remain, so the generalisation is partial rather than complete.

**VOCABULARY_PLUS_GRAMMAR_MODEL_SUPPORTED**

The vocabulary transfers but the grammar does not: identifiers are widely shared (mean Jaccard 0.861905) while core context coverage is 0.036782 and 2 shared techniques sit in different contexts in different songs. That is Model B: a common vocabulary that needs a per-song grammar to mean anything.

The two verdicts come from different tests. The generalisation verdict asks how much of a held-out song the others explain; the model verdict asks which of three architectures that explanation fits. A partial-generalisation result is consistent with more than one model, which is why neither is derived from the other.

## 18. What should NOT be built yet

| not yet | why |
|---|---|
| a universal Performance Style | context and parameters do not transfer to the standard a universal style would require, and song-specific techniques remain |
| a CrossSongPerformanceStyle in production | the model above is an example built from four songs; it is research, not a schema |
| automatic style transfer onto new music | the vocabulary transfers but the grammar does not, so a transfer would be a plausible-sounding misreading rather than a style |
| a style or profile bank | four songs is not a corpus, and one POKEY configuration is not a range |
| new player opcodes or a wider event format | the common subset needs the same command families Stage 15 already identified, and the limit remains the event encoding rather than the player |
| a Composer or DSL change | there is no evidence a listener wants any of this, and the model is only partly portable |
| a listening experiment | forbidden by the stop condition; it is the natural Stage 17 candidate if the question is pursued |

## 19. Candidate Stage 17 experiments

| candidate | question it answers | cost |
|---|---|---|
| repeat the analysis on the whole twelve-subsong corpus | does the vocabulary-plus-grammar split survive a corpus rather than four songs? | analysis only; no production change |
| compare the one AUDCTL $00 song against the eleven at $50 | is generator configuration the variable that drives the context differences? | analysis only |
| a listening test of one technique in two contexts | is a technique heard as the same thing when its context changes? | a blind package, with the Stage 14 lesson applied: vary the context, not the technique |
| write down one song's grammar explicitly | can a song's context rules be expressed at all, let alone reused? | analysis only, and it tests whether a grammar is even expressible |
| test whether the shared vocabulary is era or platform | would 1986-1990 British game music look the same against a different era or region? | needs sources outside the current corpus |

---

Stage 16 analysed four songs, read every input through its hash, and wrote only `reports/stage16/` and this document. No Composer, DSL, IR, player or schema was modified; no music was generated; no listening test was run; no style was implemented. The Stage 15 artefacts were read and not rewritten — with one disclosed exception: the cross-process determinism defect described in section 4 was fixed in Stage 15's own code, and Stage 15's artefacts were then regenerated from the corrected code (a 0.07% shift in event classifications, no change to any Stage 15 finding or verdict).

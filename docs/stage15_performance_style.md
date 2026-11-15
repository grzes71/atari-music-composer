# Stage 15 — SAP Performance Style & Player Capability Investigation

Analysis only. This stage opens a new research branch: it does **not** reopen Stage 14 and does **not** attempt SoundProfile transfer again. Nothing is rendered, generated, or changed; the 6502 player, the IR, the Composer and every schema are untouched.

## 1. Executive summary

| number | value |
|---|---|
| reference song | Draconus 2024 (Draconus_2024.sap sub0) |
| author / date | Adam Gilmore / 2024 |
| selection | rank 1 of 12 eligible; unanimous across orderings: False |
| duration / frames | 177.013029 s / 8826 frames |
| POKEY configuration | AUDCTL $00 — 4 independent 8-bit channels |
| events detected | 13480 |
| techniques extracted | 16 |
| context verdicts | TECHNIQUE_CONTEXT_SPLIT 14, INSUFFICIENT_EVIDENCE 2 |
| player assembled size | 1144 bytes |
| estimated mechanisms | 269 bytes |
| verbose verdict | PERFORMANCE_STYLE_PROMISING_BUT_UNPROVEN |
| player verdict | PLAYER_EXPANSION_NOT_JUSTIFIED |

**PERFORMANCE_STYLE_PROMISING_BUT_UNPROVEN** + **PLAYER_EXPANSION_NOT_JUSTIFIED**

The two verdicts are deliberately not correlated: the style abstraction is the more promising of the two ideas, and it is precisely the one that does NOT argue for a bigger player. What it argues for, if anything, is a wider *event encoding*.

## 2. Selected reference song

deterministic ranking over every corpus subsong on the brief's own preference list (multiple channels, non-trivial POKEY behaviour, meaningful register modulation, enough material). The full table and the ranking under three other orderings are published so the choice can be audited rather than trusted.

| rank | trace | author | date | channels | generator families | distinct audible pitches | frames | AUDCTL |
|---|---|---|---|---|---|---|---|---|
| 1 | Draconus_2024__sub0 | Adam Gilmore | 2024 | 4 | 4 | 200 | 8826 | $00 |
| 2 | Warhawk__sub0 | Rob Hubbard | 1986 | 3 | 4 | 106 | 10840 | $50 |
| 3 | Red_Max__sub0 | David Whittaker | 1987 | 3 | 3 | 262 | 6912 | $50 |
| 4 | Panther__sub0 | David Whittaker | 1987 | 3 | 3 | 195 | 16128 | $50 |
| 5 | Extirpator__sub0 | Rob Hubbard | 1987 | 3 | 3 | 127 | 14208 | $50 |
| 6 | Jet_Set_Willy__sub0 | Rob Hubbard | 1986 | 3 | 3 | 105 | 14934 | $50 |
| 7 | International_Karate__sub0 | Rob Hubbard | 1986 | 3 | 3 | 97 | 13518 | $50 |
| 8 | BMX_Simulator__sub0 | David Whittaker | 1986 | 3 | 3 | 85 | 19008 | $50 |
| 9 | Blinkys_Scary_School__sub0 | Adam Gilmore | 1990 | 3 | 3 | 74 | 8000 | $50 |
| 10 | Zybex__sub4 | Adam Gilmore | 1988 | 3 | 3 | 70 | 6527 | $50 |
| 11 | Blinkys_Scary_School__sub3 | Adam Gilmore | 1990 | 3 | 3 | 62 | 2048 | $50 |
| 12 | Ninja_Commando__sub0 | Adam Gilmore | 1989 | 3 | 2 | 55 | 6081 | $50 |

**Selected:** `Draconus_2024__sub0` — Draconus 2024 by Adam Gilmore (2024).

The choice is not unanimous: ranking pitch vocabulary or raw material first would select a different song. The declared key follows the brief's bullet order and is applied mechanically. The runner-up is carried as a robustness cross-check precisely because the choice is not forced.

| ordering | would select |
|---|---|
| generator_families_first | Draconus_2024__sub0 |
| pitch_vocabulary_first | Red_Max__sub0 |
| material_first | BMX_Simulator__sub0 |

| gate | requirement | measured | passed |
|---|---|---|---|
| G1_duration_at_least_30s | at least 30 seconds | 177.013029 | True |
| G2_multiple_channels | contains multiple channels (>= 2 with audible output) | 4 | True |
| G3_not_static_tone | not merely a simple static-tone tune (>= 2 generator families) | 4 | True |
| G4_meaningful_register_modulation | uses meaningful register modulation (>= 8 distinct audible pitch values) | 200 | True |

Trace provenance: schema `pokey-sound-archaeology/trace/1`, sha256 `4de6026278965014bb30eefed534def9927d66cf80c0c285ba3b302d1444b39c`, backend `asapscan` `7.0.0`.

## 3. Trace methodology

The song is not replayed and no SAP is re-parsed. The stage consumes the corpus' already-published normalised frame dump (`output/traces/*.frames.json`), which ASAP produced and the archaeology pipeline digitised; the file is hashed before it is read so the numbers below cannot come from a different capture than the one reported.

| element | value |
|---|---|
| trace file | C:\Users\grzes\Documents\Projects\pokey-sound-architecture\output\traces\Draconus_2024__sub0.frames.json |
| sha256 | 4de6026278965014bb30eefed534def9927d66cf80c0c285ba3b302d1444b39c |
| frames | 8826 |
| frame period (ms) | 20.055861 |
| nominal frame rate (Hz) | 49.861 |
| backend | asapscan 7.0.0 |
| registers captured | AUDF1-4, AUDC1-4, AUDCTL (one state per VBL) |
| trace notes | trimmed 5 frame(s) beyond the declared duration (177.00s); times are frame-derived (frame_index * measured frame period) |

Everything is frame-quantised: sub-frame register writes are already coalesced by the emulator, so a one-frame event is the smallest thing this analysis can see. Note boundaries are **inferred**, not decoded — see section 7.

## 4. POKEY behaviour over time

| voice | channels | 16-bit pair | audible frames | notes | median note frames | divider range | Hz range | families used |
|---|---|---|---|---|---|---|---|---|
| V1 | [1] | False | 8731 | 390 | 15.0 | 0-242 | 130.323854-31668.696429 | poly4, poly5_gated_poly9_17, poly9_17, pure_tone |
| V2 | [2] | False | 6968 | 1340 | 3.0 | 0-248 | 127.18352-31668.696429 | poly4, poly5_gated_poly9_17, poly9_17, pure_tone |
| V3 | [3] | False | 7986 | 498 | 5.0 | 2-255 | 123.705845-10556.232143 | poly5_gated_poly9_17, poly9_17, pure_tone |
| V4 | [4] | False | 6477 | 575 | 3.0 | 7-245 | 128.734538-3958.587054 | pure_tone |

| channel | AUDF is read as | audible share | AUDF changes | AUDC changes | silent register writes | families when audible |
|---|---|---|---|---|---|---|
| 1 | own_divider | 0.989236 | 866 | 5794 | 0 | poly4, poly5_gated_poly9_17, poly9_17, pure_tone |
| 2 | own_divider | 0.789486 | 6179 | 5367 | 78 | poly4, poly5_gated_poly9_17, poly9_17, pure_tone |
| 3 | own_divider | 0.904827 | 4273 | 2510 | 665 | poly5_gated_poly9_17, poly9_17, pure_tone |
| 4 | own_divider | 0.733855 | 5906 | 2787 | 1832 | pure_tone |

AUDCTL is `{'$00': 8826}` — 0 changes in the whole song. 4 independent 8-bit channels.

| bucket | start s | ch1 changes | ch2 changes | ch3 changes | ch4 changes |
|---|---|---|---|---|---|
| 0 | 0.0 | 48 | 352 | 352 | 352 |
| 1 | 8.844635 | 30 | 325 | 345 | 255 |
| 2 | 17.689269 | 48 | 202 | 256 | 88 |
| 3 | 26.533904 | 43 | 223 | 238 | 88 |
| 4 | 35.378539 | 66 | 255 | 281 | 146 |
| 5 | 44.223174 | 25 | 233 | 173 | 353 |
| 6 | 53.067808 | 10 | 315 | 143 | 328 |
| 7 | 61.912443 | 8 | 375 | 93 | 352 |
| 8 | 70.757078 | 11 | 221 | 147 | 352 |
| 9 | 79.601712 | 10 | 329 | 145 | 328 |
| 10 | 88.446347 | 17 | 373 | 123 | 322 |
| 11 | 97.290982 | 88 | 352 | 352 | 88 |
| 12 | 106.135616 | 88 | 370 | 352 | 88 |
| 13 | 114.980251 | 58 | 283 | 160 | 358 |
| 14 | 123.824886 | 59 | 289 | 166 | 413 |
| 15 | 132.669521 | 54 | 320 | 201 | 431 |
| 16 | 141.514155 | 58 | 323 | 176 | 440 |
| 17 | 150.35879 | 53 | 322 | 150 | 316 |
| 18 | 159.203425 | 58 | 320 | 159 | 440 |
| 19 | 168.048059 | 32 | 383 | 253 | 356 |

## 5. Detected performance events

| event kind | occurrences |
|---|---|
| NOTE_ON | 2803 |
| NOTE_OFF | 2803 |
| PITCH_SLIDE | 1943 |
| VOLUME_CHANGE | 1858 |
| PITCH_CHANGE | 1332 |
| GENERATOR_CHANGE | 962 |
| VOLUME_ENVELOPE | 720 |
| PITCH_SWEEP | 570 |
| TREMOLO | 332 |
| REGISTER_PATTERN_CHANGE | 63 |
| ARPEGGIO | 48 |
| DISTORTION_CHANGE | 24 |
| VIBRATO | 22 |

Event classes the brief lists that the trace does **not** support: AUDCTL_CHANGE, CHANNEL_COUPLING_CHANGE, SIXTEEN_BIT_DISABLE, SIXTEEN_BIT_ENABLE. Their absence is published rather than filled in.

| sampling | value |
|---|---|
| events total | 13480 |
| events written | 1957 |
| per-kind cap | 200 |
| truncated by kind | {'GENERATOR_CHANGE': 762, 'NOTE_OFF': 2603, 'NOTE_ON': 2603, 'PITCH_CHANGE': 1132, 'PITCH_SLIDE': 1743, 'PITCH_SWEEP': 370, 'TREMOLO': 132, 'VOLUME_CHANGE': 1658, 'VOLUME_ENVELOPE': 520} |

## 6. Musical behaviour vs register artifacts

Every event carries a classification and the evidence that produced it. Nothing is called a slide, a vibrato or an arpeggio merely because AUDF changed.

| classification | events | meaning |
|---|---|---|
| REAL_MUSICAL_BEHAVIOUR | 12785 | audible tonal voice whose register changed while sounding |
| UNKNOWN_REGISTER_PATTERN | 632 | AUDF moved but is not a pitch: a noise clock, or volume-only output |
| REGISTER_LEVEL_EFFECT | 63 | register write on a channel that is silent, or the low byte of a joined pair |

| kind | channel | frames | classification | evidence |
|---|---|---|---|---|
| PITCH_CHANGE | 1 | 40-41 | UNKNOWN_REGISTER_PATTERN | generator is unpitched noise (poly9_17): AUDF sets the noise clock, not a pitch |
| PITCH_CHANGE | 1 | 41-42 | UNKNOWN_REGISTER_PATTERN | generator is unpitched noise (poly9_17): AUDF sets the noise clock, not a pitch |
| PITCH_CHANGE | 1 | 120-121 | UNKNOWN_REGISTER_PATTERN | generator is unpitched noise (poly9_17): AUDF sets the noise clock, not a pitch |
| PITCH_CHANGE | 1 | 121-122 | UNKNOWN_REGISTER_PATTERN | generator is unpitched noise (poly9_17): AUDF sets the noise clock, not a pitch |
| PITCH_CHANGE | 1 | 200-201 | UNKNOWN_REGISTER_PATTERN | generator is unpitched noise (poly9_17): AUDF sets the noise clock, not a pitch |

The cross-check song supplies the artifact class this song lacks. In Warhawk.sap (AUDCTL $50), 1261 register writes sit on the low byte of a joined 16-bit divider while its AUDC volume nibble is zero: they look exactly like a busy bass line and produce no sound at all. Reading AUDF without combining the pair would invent a melody that is not there — the Stage 13A lesson, reproduced mechanically.

| voice | inferred character | rule | musical role |
|---|---|---|---|
| V1 | sustained_tonal | tonal generator, notes of 8+ frames, little pitch movement inside notes | unknown |
| V2 | mixed | no single reading fits | unknown |
| V3 | tonal_with_continuous_pitch_movement | tonal generator with pitch events in a quarter or more of its activity | unknown |
| V4 | tonal_with_continuous_pitch_movement | tonal generator with pitch events in a quarter or more of its activity | unknown |

inferred_character is an inference from generator choice, note length and pitch-event density. It is evidence for the context analysis, not a claim that the original composer wrote for a 'bass' or a 'drum'.

## 7. Performance vocabulary

Note boundaries are inferred, and the inference is published so it can be repeated or disputed. A new note starts where the divider jumps by 4.0 semitones or more and the new value persists for 3 frames, or where the volume re-attacks upward from near silence by 4 levels. The consequence is visible below: this song's busiest voice has a median note of three frames, so 'note' here means 'audible gesture', not 'written score note'.

| technique | occurrences | median frames | median interval (semitones) | generator families | channels |
|---|---|---|---|---|---|
| NOTE_OFF | 2803 | 1.0 |  | tonal 2442, noise 361 | ch2 1340, ch4 575, ch3 498, ch1 390 |
| NOTE_ON | 2803 | 1.0 |  | tonal 1656, noise 1147 | ch2 1340, ch4 575, ch3 498, ch1 390 |
| VOLUME_CHANGE | 1858 | 3.0 |  | tonal 1116, noise 742 | ch2 1088, ch4 476, ch3 273, ch1 21 |
| PITCH_CHANGE | 1332 | 2.0 | -2.039 | tonal 1182, noise 150 | ch2 394, ch3 389, ch4 291, ch1 258 |
| PITCH_SLIDE_RISING | 1135 | 3.0 | -1.066 | tonal 653, noise 482 | ch2 613, ch4 315, ch3 198, ch1 9 |
| GENERATOR_CHANGE | 962 | 1.0 |  | tonal 874, noise 88 | ch2 935, ch1 26, ch3 1 |
| PITCH_SLIDE_FALLING | 808 | 5.0 | 0.635 | tonal 808 | ch4 462, ch3 206, ch2 140 |
| VOLUME_ENVELOPE_FALLING | 719 | 6.0 |  | tonal 642, noise 77 | ch2 284, ch3 187, ch1 164, ch4 84 |
| PITCH_SWEEP_RISING | 564 | 5.0 | -56.405 | tonal 564 | ch2 478, ch3 65, ch1 16, ch4 5 |
| TREMOLO | 332 | 20.0 |  | tonal 332 | ch1 205, ch4 68, ch3 54, ch2 5 |
| REGISTER_PATTERN_CHANGE | 63 | 11.0 |  | mixed 63 | ch2 30, ch3 21, ch4 12 |
| ARPEGGIO | 48 | 56.0 |  | tonal 48 | ch3 31, ch1 14, ch4 3 |
| DISTORTION_CHANGE | 24 | 1.0 |  | noise 12, tonal 12 | ch2 23, ch1 1 |
| VIBRATO | 22 | 67.0 |  | tonal 22 | ch4 11, ch3 8, ch2 3 |
| PITCH_SWEEP_FALLING | 6 | 5.0 | 4.115 | tonal 6 | ch3 6 |
| VOLUME_ENVELOPE_RISING | 1 | 19.0 |  | tonal 1 | ch4 1 |

One technique in full, as the artefact records it:

| field | value |
|---|---|
| technique | NOTE_OFF |
| occurrences | 2803 |
| duration frames | {'count': 2803, 'min': 1.0, 'p10': 1.0, 'median': 1.0, 'p90': 1.0, 'max': 1.0, 'mean': 1.0} |
| confidence | {'count': 2803, 'min': 0.9, 'p10': 0.9, 'median': 0.9, 'p90': 0.9, 'max': 0.9, 'mean': 0.9} |
| positions in note | {'end': 2803} |
| pitch bands | {'low_divider_high_pitch': 1606, 'mid_divider': 713, 'high_divider_low_pitch': 484} |
| numeric parameters | note_index, note_frames, last_divider, last_hz |

Example evidence: *AUDC volume falls to zero: the note stops sounding*

## 8. Context dependence

Method: Cohen's eta-squared of a parameter's distribution across context groups, threshold 0.14 (medium effect size: groups of at least 3 occurrences are not interchangeable); a technique needs at least 20 occurrences for a verdict. Circular tests are excluded: a factor is never used to explain the quantity it was computed from (pitch_band from the divider, note_length_band from the note length, family_bucket from the waveform).

The abstraction has to be TECHNIQUE + CONTEXT: 14 of 16 techniques split by context, 0 survive as single techniques, 2 have too few occurrences to judge.

| technique | occurrences | verdict | strongest factor | eta-squared | group medians |
|---|---|---|---|---|---|
| NOTE_OFF | 2803 | TECHNIQUE_CONTEXT_SPLIT | note_length_band | 0.4768 | {'long_note': 108.0, 'medium_note': 121.0, 'short_note': 4.0} |
| NOTE_ON | 2803 | TECHNIQUE_CONTEXT_SPLIT | family_bucket | 0.5398 | {'noise': 10556.232, 'tonal': 519.159} |
| VOLUME_CHANGE | 1858 | TECHNIQUE_CONTEXT_SPLIT | position_in_note | 0.2867 | {'end': 1.0, 'middle': 1.0, 'start': 2.0} |
| PITCH_CHANGE | 1332 | TECHNIQUE_CONTEXT_SPLIT | family_bucket | 0.6647 | {'noise': 15834.348, 'tonal': 335.203} |
| PITCH_SLIDE_RISING | 1135 | TECHNIQUE_CONTEXT_SPLIT | family_bucket | 0.9995 | {'noise': 31668.696, 'tonal': 263.906} |
| GENERATOR_CHANGE | 962 | TECHNIQUE_CONTEXT_SPLIT | pitch_band | 0.8237 | {'high_divider_low_pitch': 5.0, 'low_divider_high_pitch': 3.0, 'mid_divider': 5.0} |
| PITCH_SLIDE_FALLING | 808 | TECHNIQUE_CONTEXT_SPLIT | note_length_band | 0.9944 | {'long_note': 0.506, 'short_note': 24.653} |
| VOLUME_ENVELOPE_FALLING | 719 | TECHNIQUE_CONTEXT_SPLIT | channel | 0.418 | {'1': 10.0, '2': 15.0, '3': 8.0, '4': 8.0} |
| PITCH_SWEEP_RISING | 564 | TECHNIQUE_CONTEXT_SPLIT | channel | 0.6242 | {'1': 0.0, '2': 0.0, '3': 0.0, '4': 30.0} |
| TREMOLO | 332 | TECHNIQUE_CONTEXT_SPLIT | channel | 0.6641 | {'1': 10.0, '2': 4.0, '3': 8.0, '4': 8.0} |
| REGISTER_PATTERN_CHANGE | 63 | TECHNIQUE_CONTEXT_SPLIT | channel | 0.2926 | {'2': 1.0, '3': 33.0, '4': 163.0} |
| ARPEGGIO | 48 | TECHNIQUE_CONTEXT_SPLIT | channel | 0.8005 | {'1': 3.5, '3': 6.0, '4': 6.0} |
| DISTORTION_CHANGE | 24 | TECHNIQUE_CONTEXT_SPLIT | family_bucket | 0.7143 | {'noise': 3.0, 'tonal': 6.0} |
| VIBRATO | 22 | TECHNIQUE_CONTEXT_SPLIT | channel | 0.582 | {'2': 0.568, '3': 0.284, '4': 0.635} |
| PITCH_SWEEP_FALLING | 6 | INSUFFICIENT_EVIDENCE |  |  |  |
| VOLUME_ENVELOPE_RISING | 1 | INSUFFICIENT_EVIDENCE |  |  |  |

| dimension | meaning |
|---|---|
| channel | which voice the event belongs to |
| voice_id | the voice decomposition used (a 16-bit joined pair is one voice) |
| note_index / note_frames | the heuristic note span it falls inside |
| position_in_note | start / middle / end by thirds of the note |
| frames_into_note / frames_left_in_note | distance to the note's boundaries |
| pitch_band | divider tertile within that voice's own range (a low divider is a high pitch) |
| family_bucket | which generator family the event lands on — a hardware fact, not a role |
| onset_grid_frames / beat_index / beat_phase | position on the observed onset grid |
| previous_event_on_channel / next_event_on_channel | the immediate neighbours |
| frames_since_onset_on_channel / frames_to_next_onset_on_channel | local timing |
| events_within_25_frames_on_channel | local rhythmic density |
| other_channels_active / channels_active_mask | which other voices were sounding |
| occurrence_index_for_technique | how many times this technique has occurred so far |
| song_position_share | how far through the song it happens |
| audible_here | whether the channel's AUDC volume is non-zero in that frame |
| musical_role | unknown — deliberately not inferred; see channel_character |

## 9. Current player capabilities

Read from `C:\Users\grzes\Documents\Projects\atari-music\src\atari_music\asm\player.asm` (sha256 `02409e4d6384ddfec2386f1e4ebc1c6a12aa3c8cd8bde61c7a8ecd21a913ab69`), 810 lines of which 588 are code. Every claim below carries the source lines that support it; the entries marked *unsupported* list the patterns that were searched for and not found.

| capability | supported | detail | evidence lines | cost if added | kind |
|---|---|---|---|---|---|
| 4_independent_channels | True | One track and one instrument slot per channel; each channel counts its own note duration down independently. | 134, 232, 234, 242, 316, 325 | present | PRESENT |
| per_channel_note_duration | True | Durations are in ticks; a tick is frames_per_tick VBL frames, fixed for the song. | 61, 234, 316, 325 | present | PRESENT |
| fixed_per_channel_instrument | True | Distortion and the four ADSR numbers are loaded once at init, 5 bytes per channel. | 110, 112, 124, 135 | present | PRESENT |
| runtime_envelope_generator | True | A four-phase attack/decay/sustain/release state machine computes ch_cur_vol every frame; the shape is fixed per channel, not per note. | 502, 504, 507, 514, 544, 601 | present | PRESENT |
| note_volume_from_data | True | Each event carries a peak volume (0..15) that the envelope works against. | 312, 329 | present | PRESENT |
| per_song_audctl_value | True | AUDCTL is one byte in the song header, written every frame: any one value is expressible, but only one for the whole song. | 66, 674, 761 | present (1 byte, whole song) | PRESENT |
| sixteen_bit_pair_1_2 | True | Static join of channels 1+2: channel 1 becomes the divider low byte with AUDC forced to 0; channel 2 carries the high byte and the volume. | 677, 678, 691, 706, 712, 762 | present | PRESENT |
| whole_song_loop | True | A $FFFF sequence entry rewinds the sequence pointer to step 0. | 139, 288, 418, 425 | present | PRESENT |
| vibrato | False | No periodic pitch modulation: the player never computes an AUDF offset at run time and the event has no field for one. | (absent) | player code absent; song data absent | PLAYER_CODE_AND_DATA_LIMITATION |
| portamento_or_slide | False | Pitch is written once per note and then held. The only per-frame change to AUDF is a new note event, or the octave-pulse modulation a channel's instrument record asks for -- a slide to an arbitrary pitch is neither. | (absent) | IR field exists but is not exported; player code absent | PLAYER_CODE_AND_DATA_LIMITATION |
| per_frame_divider_modulation | True | An instrument record may ask for MOD_OCTAVE_PULSE (C1): apply_modulation alternates the channel's divider between the note's nominal N and N // 2 once per 50 Hz frame, restarting at every note onset, and the existing write_pokey_registers publishes it. One descriptor byte per channel in the instrument table; nothing per note. | 28, 127, 250, 311, 321, 624 | present (1 byte per channel) | PRESENT |
| arpeggio | False | No per-frame pitch cycling, and the note table has no effect column to trigger one. | (absent) | IR field exists but is not exported; player code absent | PLAYER_CODE_AND_DATA_LIMITATION |
| per_frame_volume_macro | False | Volume comes from the shared envelope state machine, so a note cannot carry its own frame-by-frame loudness contour; the exporter refuses such a song instead of letting the preview and the hardware diverge. | 3 | data format has no place for it; mads_exporter refuses the song | DATA_LIMITATION |
| generator_change_inside_song | False | ch_dist is loaded once at init, so a channel keeps one distortion for the whole song, and the 3-byte event has no distortion field. | 689, 701, 724, 737, 749 | present in the hardware, absent from player and data | IR_LIMITATION |
| audctl_change_mid_song | False | AUDCTL is written from the header byte every frame and never recomputed. | 673 | 1 byte of data and a load would carry a change; no path exists | DATA_LIMITATION |
| sixteen_bit_pair_3_4 | False | Only bit 4 (channels 1+2) has a write path; there is no 3+4 branch in write_pokey_registers. | 704, 728, 734, 736, 738 | ~20 bytes of code plus the low-byte convention | PLAYER_CODE_LIMITATION |
| highpass_filter_clocking | False | AUDCTL bits 2/3 are never set by the player, and a high-passed channel has no pitch of its own to drive. | (absent) | no representation at all | PLAYER_CODE_AND_DATA_LIMITATION |
| effect_column | False | The event is exactly three bytes (audf, duration, volume); there is nowhere to put an effect id or its parameter. This is the single structural reason every technique below is unreachable. | 273, 324, 328 | 1-2 bytes per note | DATA_LIMITATION |

| data format element | value |
|---|---|
| song header | 6 bytes: frames_per_tick, audctl_mode, instruments_ptr, sequence_ptr |
| instrument | 6 bytes per channel: distortion, attack_frames, decay_frames, sustain_vol, release_frames, modulation |
| note event | 3 bytes: audf, duration_ticks, volume |
| end of track | $FF |
| timing resolution | frames_per_tick VBL frames (>= 1) |
| zero page | 10 bytes |
| runtime state | 77 bytes |

## 10. Reference techniques unsupported by current player

4 of 16 techniques are supported directly; 10 more are reachable only by unrolling one note per frame; 2 have no representation.

| technique | in reference | player supports | expressible | classification | missing mechanism |
|---|---|---|---|---|---|
| NOTE_OFF | 2803 | True | True | SUPPORTED | — |
| NOTE_ON | 2803 | True | True | SUPPORTED | — |
| VOLUME_CHANGE | 1858 | True | True | SUPPORTED | — |
| PITCH_CHANGE | 1332 | True | True | SUPPORTED | — |
| PITCH_SLIDE_RISING | 1135 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| GENERATOR_CHANGE | 962 | False | False | IR_LIMITATION | present in the hardware, absent from player and data |
| PITCH_SLIDE_FALLING | 808 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| VOLUME_ENVELOPE_FALLING | 719 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| PITCH_SWEEP_RISING | 564 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| TREMOLO | 332 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| REGISTER_PATTERN_CHANGE | 63 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| ARPEGGIO | 48 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| DISTORTION_CHANGE | 24 | False | False | IR_LIMITATION | present in the hardware, absent from player and data |
| VIBRATO | 22 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| PITCH_SWEEP_FALLING | 6 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |
| VOLUME_ENVELOPE_RISING | 1 | False | True | DATA_LIMITATION | no effect column: the player can still reach this by writing one note per frame, which needs frames_per_tick=1 and a per-frame note table |

| classification | techniques |
|---|---|
| DATA_LIMITATION | 10 |
| SUPPORTED | 4 |
| IR_LIMITATION | 2 |

## 11. Player size and architecture analysis

The project's one hard binary limit is **2048 bytes on the assembled player**, and it is **exclusive**: a player of exactly 2048 bytes fails. It bounds *the assembled player (code + runtime state), strictly below the limit; the complete XEX file and the song data are not bounded by it*. In particular the complete `.xex` file is **not** bounded by it, and neither is the song data; a built executable may legitimately be larger than 2048 bytes, and several are. The `hypothetical_4KB` row below is a counterfactual this stage weighs, not a second limit.

| measure | bytes |
|---|---|
| assembled (code + state) | 1144 |
| of which code | 1067 |
| of which runtime state | 77 |
| zero page | 10 |
| total footprint | 1154 |
| player size limit (exclusive) | < 2048 |
| player within the limit | True |
| headroom inside a 2 KB envelope | 904 |
| headroom inside 4 KB | 2952 |
| estimated cost of the needed mechanisms | 269 |
| headroom left after adding them | 635 |

Measurement: mads.exe tools/mads/mads.exe on a wrapper: org $6000 / player_start: icl '../player.asm'. The recorded value is 1144 bytes; this run re-measured it as 1144 bytes. The source hash is published so a stale number is visible.

The performance is expressible with today's player only by unrolling it into 90486 bytes of note table (10.8x the note-level cost). A larger player does not change that; a wider *event encoding* does.

| unrolling measure | value |
|---|---|
| audible frames per channel | {'1': 8731, '2': 6968, '3': 7986, '4': 6477} |
| one note per frame, bytes | 90486 |
| note events in the reference | 2803 |
| note-level cost of those notes | 8409 |
| with one effect byte per note | 11212 |
| unrolled / note-level ratio | 10.76 |

This is the architectural finding the brief asks for in Part K. The same performance can already be executed by today's player if every frame becomes a note: the *player* is nearly complete for pitch and loudness. What is exhausted is the song stream, and a 4 KB player would not change that number by a single byte.

## 12. Hypothetical richer player

An event is (opcode, duration, parameters). The player keeps one small effect state per channel and advances it once per frame; the song stream names the effect and its parameter, never the per-frame register value.

| command | existing | data bytes | estimated code lines | justified by |
|---|---|---|---|---|
| NOTE audf, duration, volume | True | 3 | 0 | every note in the song |
| EFFECT id, p1, p2 (attaches to the preceding note) | False | 3 | 100 | 1943 slides + 570 sweeps + 22 vibrato + 48 arpeggio occurrences |
| SET_VOLUME level | False | 2 | 24 | 1858 volume changes + 332 tremolo runs + 720 envelopes |
| SET_GENERATOR audc | False | 2 | 8 | 962 generator changes + 24 distortion changes |
| SHAPE id (one of a small table of loudness contours) | False | 2 | 16 | 720 shaped volume runs |
| SET_AUDCTL value | False | 2 | 0 | NOT justified: the reference song never changes AUDCTL mid-song |

| refused command | reason |
|---|---|
| SET_AUDCTL from data | 0 occurrences in the reference song; including it would be invention |
| 16-bit pair 3+4 | 0 occurrences; the corpus uses the 1+2 pair or no pair at all |

| cost | value |
|---|---|
| bytes per code line (current source) | 1.815 |
| basis | 1067 code bytes over 588 code lines in the current player.asm; the same density is assumed for new code |
| added code lines | 148 |
| estimated added code bytes | 269 |
| estimated player size after | 1413 |
| added state RAM bytes | 24 |
| added song data per effected note | 3 |
| cycles available per frame | 35468 |
| estimated added cycles per frame | 112 |
| share of a frame | 0.003158 |

Code sizes are estimates from line counts, not measurements; RAM, data and CPU figures are structural.

## 13. SongPerformanceStyle representation

**Term chosen:** `SongPerformanceStyle`. SongPerformanceStyle is chosen over PerformanceVocabulary (which names only the list of techniques) and over POKEYPerformanceStyle (which would claim the style is a property of the chip rather than of this song and this player). The artefact is scoped to one song: it describes how that song's player drives POKEY, with no claim that any part of it transfers to another song. It is explicitly NOT a SoundProfile, a PlayableSoundProfile or an InstrumentProfile: it contains no instrument definition and no per-channel sound to re-apply.

**Status:** research artefact — not a production schema, not a SoundProfile.

| field | value |
|---|---|
| source song | Draconus_2024.sap sub0 |
| POKEY configuration | 4 independent 8-bit channels |
| techniques | 16 |
| event classes present | ARPEGGIO, DISTORTION_CHANGE, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE, PITCH_SWEEP, REGISTER_PATTERN_CHANGE, TREMOLO, VIBRATO, VOLUME_CHANGE, VOLUME_ENVELOPE |
| event classes absent | AUDCTL_CHANGE, CHANNEL_COUPLING_CHANGE, SIXTEEN_BIT_DISABLE, SIXTEEN_BIT_ENABLE |
| onset grid (frames) | 5 |
| musical share of events | 0.948442 |
| techniques supported by the player today | 4 |
| techniques needing a wider format | 10 |
| techniques with no representation | 2 |

The technique inventory is high confidence: it is register arithmetic. The *interpretation* of a technique as a musical intention is medium at best — a divider ramp proves a pitch ramp, not that anyone chose a portamento.

## 14. Applying the style conceptually to new music

Input: real composer export, read-only (`C:\Users\grzes\Documents\Projects\atari-music\experiments\mads_player_builds\action_data.asm`). Nothing is composed and no IR is produced.

| note | composer note | style interpretation |
|---|---|---|
| 0 | {'pitch': 'C-2', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 1 | {'pitch': 'C-2', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 2 | {'pitch': 'F-3', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 3 | {'pitch': 'G-3', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 4 | {'pitch': 'C-4', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 5 | {'pitch': 'F-3', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 6 | {'pitch': 'F-3', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |
| 7 | {'pitch': 'C-4', 'rows': 4} | NOTE_ON (the note itself, unchanged); optional onset treatment drawn from VOLUME_CHANGE (72% of its occurrences sit at a note onset); optional ending treatment drawn from GENERATOR_CHANGE (60% at a note ending) |

Shape maps; values do not. A technique carries (kind, direction, duration range, context), and that part is expressible for a new note because it names a transform rather than a register. The *measured* parameters do not map: this song's sweeps are a few frames of one or two divider steps on one specific voice, and the context analysis shows those numbers differ strongly by channel, generator family and note length inside the same song. Copying them into a different composition would be copying absolute register behaviour — the mistake Stage 14 closed. A new composition needs a *decision* per technique (depth, rate, and when it applies); this song supplies evidence about which decisions matter, not the answers.

## 15. Answers to the ten research questions

**Q1 What are the actual POKEY performance techniques used by one historical song?**

16 distinct techniques across 13480 events in Draconus_2024.sap sub0: NOTE_OFF x2803, NOTE_ON x2803, VOLUME_CHANGE x1858, PITCH_CHANGE x1332, PITCH_SLIDE_RISING x1135, GENERATOR_CHANGE x962, PITCH_SLIDE_FALLING x808, VOLUME_ENVELOPE_FALLING x719, PITCH_SWEEP_RISING x564, TREMOLO x332, REGISTER_PATTERN_CHANGE x63, ARPEGGIO x48...

**Q2 Which techniques are genuinely musical and which are register artifacts?**

12785 of 13480 events are real musical behaviour, 632 are register patterns whose AUDF is not a pitch (noise clock or volume-only output) and 63 are register-level effects: writes on a channel that is silent. The cross-check song supplies the canonical artifact this song lacks: 1261 writes to the low byte of a joined 16-bit divider, which look like a bass line and are not a pitch.

**Q3 How strongly are techniques tied to context?**

14 of 16 techniques split by context at the medium-effect threshold; 0 survive as one technique; 2 have too few occurrences to judge. The strongest factors are channel, generator family and position inside the note. Even NOTE_ON and NOTE_OFF are not context-free: their volume and length distributions differ by which generator they land on.

**Q4 Can the techniques be described without pretending they are portable instruments?**

Yes, and the description never mentions a sound to re-apply. Each technique is (kind, direction, parameter range, context, occurrence count, evidence frames): a rising sweep is a number of divider steps over a number of frames, at a position in a note, on a voice. No instrument, no per-channel timbre and no portable profile appears anywhere in SongPerformanceStyle.

**Q5 Which techniques can the current player express?**

4 of 16 directly (note on/off, pitch steps, volume levels); 10 more only by unrolling one note per frame; 2 have no representation at all.

**Q6 What prevents the current player from expressing the others?**

The event is exactly three bytes: audf, duration, volume. There is no effect field, so a slide, a vibrato, an arpeggio, a generator change or a per-frame loudness contour has nowhere to live. The player also reloads distortion once at init, so a generator change is impossible for a second reason. None of this is about code space: the mechanisms are missing because the *format* cannot describe them.

**Q7 Is the limitation primarily player code, song data, IR, or composition?**

Data and IR. The IR already declares slide_semitones, arpeggio_offsets and vibrato_depth/vibrato_speed and does not export them, and the MADS exporter refuses a per-frame volume contour rather than let the WAV and the XEX diverge. So the concepts exist upstream, the format has no bytes for them and the player has no path. Composition is not the limit: the reference song proves the behaviour is composable, just not by this engine.

**Q8 Would a larger player materially improve expressiveness?**

No. The player assembles to 1144 bytes; the mechanisms the reference song needs are estimated at 269 bytes, which fits inside the *existing* 2 KB envelope with 635 bytes to spare. Growing the player to 4 KB changes nothing, because the same performance needs 90486 bytes of song data (10.76x the note-level cost) if it must travel as one note per frame.

**Q9 Can a compact event/macro system represent the reference performance?**

Yes. 16 measured techniques reduce to five command families beyond the existing NOTE: EFFECT id, p1, p2 (attaches to the preceding note); SET_VOLUME level; SET_GENERATOR audc; SHAPE id (one of a small table of loudness contours); SET_AUDCTL value. The song's 2803 note events cost 8409 bytes today and about 16818 bytes if every note carried a three-byte effect, against 90486 bytes for the unrolled alternative. The compact system is the only one that fits.

**Q10 Is 'performance style' a more promising abstraction than 'SoundProfile'?**

Yes, and for a structural reason rather than a hopeful one. A SoundProfile claimed a sound could be lifted out and re-applied, and Stage 14 falsified that. SongPerformanceStyle claims only that one song's POKEY programming is a describable, countable, context-bound behaviour, and it is forbidden from claiming the sound travels. The cross-check supports the schema and contradicts the numbers: 92% of event classes and 94% of technique identifiers recur in a second song, while the parameters do not.

## 16. Stage 15 verdict

**PERFORMANCE_STYLE_PROMISING_BUT_UNPROVEN**

| proven |  |
|---|---|
| the_song_decomposes_into_countable_techniques | 16 techniques, 13480 events, each with evidence frames and a classification |
| musical_and_artifact_events_are_separated | 12785 musical, 632 unknown register patterns, 63 silent register writes |
| the_abstraction_is_context_bound | 14 of 16 techniques split by context at eta-squared >= 0.14 |
| no_instrument_claim_is_needed | the artefact carries techniques and contexts and no portable sound |
| the_schema_repeats_on_a_second_song | 92% of event classes and 94% of technique identifiers recur |

| unproven |  |
|---|---|
| perceptual_meaning | nothing here says a technique is *heard* as one; this stage ran no listening test, by design |
| generalisation_beyond_one_song | n=1 reference song. The cross-check shows the schema repeats; it does not show that the parameters or the contexts repeat. |
| transfer_to_new_music | Part M is a thought experiment: the shape of a technique maps, its measured values do not, and no rule for choosing which technique fires has been tested |
| the_engineering_chain | the reference song's own player format is unknown, the current 6502 player cannot execute the vocabulary, and this stage deliberately built nothing |

Narrowed to the one song analysed, the claim IS supported: this song's POKEY programming is a describable, countable, context-bound performance style. The verdict stays PROMISING_BUT_UNPROVEN because the load-bearing claim of the intended architecture is generalisation, and one song cannot show that.

**PLAYER_EXPANSION_NOT_JUSTIFIED**

the hypothesis 'the player is too small' is falsified by measurement: the mechanisms the reference song needs are estimated at 269 bytes, they fit in the current 2048-byte envelope with 635 bytes spare, and the binding constraint is the three-byte event format — a data-encoding question a 4 KB player does not touch

The two verdicts are deliberately not correlated: the style abstraction is the more promising of the two ideas, and it is precisely the one that does NOT argue for a bigger player. What it argues for, if anything, is a wider *event encoding*.

### Falsification attempt

The stage was asked to try to falsify the hypothesis rather than prove it. Two checks were made. First, a second song went through the same extractor:

| cross-check | value |
|---|---|
| song | Warhawk.sap sub0 (AUDCTL $50) |
| events / techniques | 18286 / 15 |
| shared event classes | ARPEGGIO, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE, PITCH_SWEEP, REGISTER_PATTERN_CHANGE, TREMOLO, VIBRATO, VOLUME_CHANGE, VOLUME_ENVELOPE |
| classes only in the reference | DISTORTION_CHANGE |
| classes only in the other | none |
| shared kind share | 0.923077 |
| shared technique ids | ARPEGGIO, GENERATOR_CHANGE, NOTE_OFF, NOTE_ON, PITCH_CHANGE, PITCH_SLIDE_FALLING, PITCH_SLIDE_RISING, PITCH_SWEEP_FALLING, PITCH_SWEEP_RISING, REGISTER_PATTERN_CHANGE, TREMOLO, VIBRATO, VOLUME_CHANGE, VOLUME_ENVELOPE_FALLING, VOLUME_ENVELOPE_RISING |
| shared technique id share | 0.9375 |

The event *classes* recur and most technique *identifiers* recur, while the measured parameters do not: the schema generalises, the numbers do not. That is the strongest support this stage can offer for a Performance Style abstraction, and it is also why a style cannot be transferred as a set of constants.

Second, the context test is itself the falsifier: if a technique's parameters did *not* differ across contexts, the abstraction would be a single object and no context would be needed. It failed to falsify the hypothesis — the parameters differ sharply — which is positive evidence for context and, at the same time, negative evidence for naive transfer.

## 17. What should NOT be built yet

| not yet | why |
|---|---|
| a generic style engine | one song and no listening evidence; a rule engine built now would encode one song's accidents as rules |
| automatic style transfer | the context analysis shows the parameters are song-specific; only the schema repeats |
| Composer integration or DSL syntax | there is no agreed command set, and no evidence a listener wants any of it |
| a profile bank of styles | one SongPerformanceStyle is an example, not a bank; two would be a coincidence, not a corpus |
| automatic technique assignment | choosing which technique fires is a composition decision, not a measurement |
| a 6502 player rewrite or a 4 KB player | not justified: the mechanisms fit in the current envelope, and the constraint is the event format |
| a new IR field for every technique | the IR already has unused slide and arpeggio fields; widening a schema before the format question is settled repeats the SoundProfile mistake |
| a human listening experiment | forbidden by this stage's stop condition; it is the first thing a Stage 16 should consider if the style is pursued |

## 18. Candidate Stage 16 experiments

| candidate | question it answers | cost |
|---|---|---|
| repeat the analysis on more corpus songs | do the *contexts* repeat, or only the schema? | analysis only; no production change |
| a listening test of one technique in two contexts | is a slide heard as a slide, and does its note position change how it is heard? | a blind package like Stage 12A/13A, with the Stage 14 lesson applied: vary the context, not the technique |
| prototype the event encoding inside the existing 2 KB player | does a five-command extension fit and behave? | an experimental branch; the estimate here says it fits with room to spare |
| quantify the unrolling boundary | at what event density does unrolling stop being cheaper than an effect column? | analysis only |
| check whether the corpus splits into programming idioms | do the 1986-1990 players share a style that a 2024 production does not? | corpus analysis; the reference song's AUDCTL=$00 against the corpus norm $50 is the first hint |

---

Stage 15 analysed exactly one song (`Draconus_2024__sub0`), read every input through its hash, and wrote only `reports/stage15/` and this document. No Composer, DSL, IR, player or schema was modified; no music was generated; no listening test was run; no style engine was built.

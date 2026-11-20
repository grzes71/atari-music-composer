# Stage 17 - POKEY Performance Event Language and Compact Event IR

A controlled investigation of the representation boundary between composition and POKEY execution. Analysis only: the 6502 player, the Composer, the DSL, the Music IR and the SoundProfile system are read and hashed, never modified. No audio was rendered, no music was generated, and no listening test was run.

Analysis version `stage17/1`.

## 1. Executive summary

Four songs were read (Draconus_2024__sub0, Warhawk__sub0, Ninja_Commando__sub0, Red_Max__sub0), taken from Stage 16's own selection record. 16 techniques observed in them reduce to **12 opcodes**, and every observed technique has an opcode. An event language was defined from that evidence, and a research-only interpreter renders POKEY frame streams from it.

The three findings that decide the stage:

- **The language is faithful and neutral.** A behaviour-driven encoding of the reference traces reaches a mean exact share of **1.0** once a measured repair pass is applied, on all four songs. The opcode set contains no instrument, no role and no style.
- **It is not compact.** The exact encoding is about **1.859x a raw register dump** (1.50175x before repair). The reference players change several registers per frame across four voices, so there is almost nothing for an event layer to collapse - the events are already at frame granularity.
- **The technique abstraction is not a sufficient input.** Replaying only the Stage 15 events reproduces **0.005575** of frames, because the abstraction is a lossy summary of the behaviour it was derived from. A composition has to state the operations explicitly; it cannot delegate that to the technique vocabulary.

| verdict | result |
|---|---|
| event language | `EVENT_LANGUAGE_PARTIALLY_SUPPORTED` |
| 2 KB player | `2KB_PLAYER_PLAUSIBLE` |
| main bottleneck | `MULTIPLE_BOTTLENECKS` |

## 2. Research question

> Can a compact, semantically neutral Performance Event language form a useful middle layer between composition and the POKEY player, while remaining small enough that the existing 2 KB player architecture could plausibly execute it?

The question has three separable parts and this stage answers them separately, because they can have different answers: *can the behaviour be represented*, *is the representation neutral*, and *is it compact*.

The falsification targets were fixed before the measurement: behaviours that cannot be expressed without adding semantic knowledge, behaviours that need raw register access, compression that is too poor, and event combinations that become as complex as raw frame data. Parts 9, 10 and 19 report which of those were actually hit.

## 3. Evidence sources

Every input is read through its SHA-256. The technique definitions are not re-implemented: `stage15.detect_events` is imported and called, so every encoded event is the same object Stages 15 and 16 published.

| record | file | sha256 |
|---|---|---|
| player_asm | player.asm | `2b14a973774ddecc...` |
| stage15_hypothetical_player_design | hypothetical_player_design.json | `b200a758bb0e559e...` |
| stage15_player_capability_matrix | player_capability_matrix.json | `3563513da7cc5cbe...` |
| stage15_player_gap_analysis | player_gap_analysis.json | `a7212dcccd57249d...` |
| stage15_player_size_analysis | player_size_analysis.json | `d1f9396bc273e51e...` |
| stage15_summary | summary.json | `ea5eba3a1f6777a0...` |
| stage16_context_generalization | context_generalization.json | `18878213c8144ede...` |
| stage16_song_selection | song_selection.json | `277f6c1f78795d60...` |
| stage16_universality | universality.json | `830398741e2bf41c...` |

| song | sha256 |
|---|---|
| `Draconus_2024__sub0` | `4de6026278965014...` |
| `Warhawk__sub0` | `7ef52f61762de33c...` |
| `Ninja_Commando__sub0` | `558926e74196212b...` |
| `Red_Max__sub0` | `2358e26fac933c66...` |

- selection record: `C:\Users\grzes\Documents\Projects\atari-music\reports\stage16\song_selection.json` (`277f6c1f78795d60...`)
- Stage 16 verdicts reused rather than recomputed: the universality, low-level flag, context verdict and parameter verdict for each technique are read from reports/stage16/universality.json rather than recomputed
- source hash of this module: `93c96bb0a934a2ab...`

## 4. Layer responsibilities: composition / performance / player

The three layers are separated by *who decides*. The composition decides what should be heard; the event layer records those decisions as explicit operations; the player decides nothing and only executes. Every responsibility below is assigned to exactly one layer, because Stage 16 showed that a layer which infers context becomes a style model.

The three layers are separated by *who decides*. The composition decides what should be heard; the event layer records those decisions as explicit operations; the player decides nothing and only executes.

**COMPOSITION (what / when)**

owns:

- pitch: which divider a voice sounds at
- duration: how long a note lasts
- velocity: the volume a note starts at
- rhythm and the placement of notes and rests
- musical structure: phrases, sections, repetition
- the decision that an effect happens at all, and when it starts

must not own:

- POKEY register addresses
- frame timing or tick counts
- AUDCTL bit layout
- the per-frame shape of an effect

**PERFORMANCE EVENT IR (what happens)**

owns:

- pitch modulation: slides, sweeps, vibrato, arpeggio
- volume changes and volume shapes
- generator changes
- the duration of an effect, in frames
- the channel an operation applies to
- the frame each operation starts on

must not own:

- musical intent (nothing here says 'lead' or 'percussion')
- song-specific rules ('in this song channel 3 is the bass')
- inference from context
- register addresses

**PLAYER (how / execute)**

owns:

- POKEY register writes and their order
- frame timing and the call rate
- AUDCTL handling and 16-bit pairing
- per-voice state (anchors, running effects, frame counters)
- event dispatch
- hardware clamping and the representable range

must not own:

- musical decisions
- any knowledge of which song it is playing

The boundary is testable and this stage tests it: the interpreter in Part I knows nothing about a song's identity. It receives channel numbers and parameter values and produces registers. Every case where the reconstruction failed is reported in Part I rather than being fixed by giving the interpreter a special case.

## 5. Minimal event vocabulary

16 observed techniques reduce to 12 opcodes. Techniques that share a register effect share an opcode, which is why the technique identifiers (Stage 15 splits glides and envelopes by direction) collapse.

| opcode | effect | parameters | justified by | occurrences | songs |
|---|---|---|---|---|---|
| `SET_AUDCTL` | writes AUDCTL: clock source, 16-bit pairing, high-pass routing | `value` | *(no technique: mode declaration only)* | 0 | 0 |
| `SET_GENERATOR` | writes the distortion nibble of one channel's AUDC | `dist` | DISTORTION_CHANGE, GENERATOR_CHANGE | 4981 | 3 |
| `SET_VOLUME` | writes the volume nibble of one channel's AUDC | `volume` | VOLUME_CHANGE | 4183 | 4 |
| `SET_PITCH` | writes the divider (AUDF, or both bytes of a joined pair) without retriggering | `divider` | PITCH_CHANGE, REGISTER_PATTERN_CHANGE | 10757 | 4 |
| `NOTE` | writes the divider and the volume together and starts a note | `divider`, `volume`, `duration` | NOTE_ON | 10200 | 4 |
| `NOTE_OFF` | writes volume 0 on one channel | - | NOTE_OFF | 10200 | 4 |
| `PITCH_SLIDE` | writes a linearly changing divider for a fixed number of frames | `delta`, `duration`, `curve` | PITCH_SLIDE_FALLING, PITCH_SLIDE_RISING | 3616 | 4 |
| `PITCH_SWEEP` | writes a quadratically changing divider for a fixed number of frames | `delta`, `duration`, `curve` | PITCH_SWEEP_FALLING, PITCH_SWEEP_RISING | 732 | 4 |
| `VIBRATO` | writes a triangle-modulated divider for a fixed number of frames | `depth`, `period`, `duration` | VIBRATO | 47 | 3 |
| `TREMOLO` | writes a triangle-modulated volume for a fixed number of frames | `depth`, `period`, `duration` | TREMOLO | 1681 | 4 |
| `ARPEGGIO` | cycles a table of dividers at a fixed period | `count`, `period`, `notes`, `duration` | ARPEGGIO | 448 | 4 |
| `VOLUME_SHAPE` | writes a volume that ramps or replays a table for a fixed number of frames | `target`, `levels`, `duration` | VOLUME_ENVELOPE_FALLING, VOLUME_ENVELOPE_RISING | 4432 | 4 |

| technique observed | opcode | songs | occurrences | Stage 16 verdict |
|---|---|---|---|---|
| `NOTE_OFF` | `NOTE_OFF` | 4 | 10200 | UNIVERSAL |
| `NOTE_ON` | `NOTE` | 4 | 10200 | UNIVERSAL |
| `PITCH_CHANGE` | `SET_PITCH` | 4 | 8392 | COMMON |
| `GENERATOR_CHANGE` | `SET_GENERATOR` | 3 | 4957 | COMMON |
| `VOLUME_ENVELOPE_FALLING` | `VOLUME_SHAPE` | 4 | 4418 | COMMON |
| `VOLUME_CHANGE` | `SET_VOLUME` | 4 | 4183 | UNIVERSAL |
| `REGISTER_PATTERN_CHANGE` | `SET_PITCH` | 4 | 2365 | COMMON |
| `PITCH_SLIDE_RISING` | `PITCH_SLIDE` | 4 | 2081 | COMMON |
| `TREMOLO` | `TREMOLO` | 4 | 1681 | COMMON |
| `PITCH_SLIDE_FALLING` | `PITCH_SLIDE` | 4 | 1535 | COMMON |
| `PITCH_SWEEP_RISING` | `PITCH_SWEEP` | 4 | 695 | COMMON |
| `ARPEGGIO` | `ARPEGGIO` | 4 | 448 | COMMON |
| `VIBRATO` | `VIBRATO` | 3 | 47 | SONG_SPECIFIC |
| `PITCH_SWEEP_FALLING` | `PITCH_SWEEP` | 4 | 37 | UNKNOWN |
| `DISTORTION_CHANGE` | `SET_GENERATOR` | 1 | 24 | SONG_SPECIFIC |
| `VOLUME_ENVELOPE_RISING` | `VOLUME_SHAPE` | 2 | 14 | UNKNOWN |

Candidates the brief offered that the evidence does **not** support:

| candidate | verdict | reason |
|---|---|---|
| WAIT | `REJECTED` | No Stage 15 technique corresponds to a wait: there is no WAIT kind, and no event class is an absence of behaviour. Time in this language is carried by the *frame* field of every event, so a separate WAIT opcode would duplicate information the encoding already has. A rest is a note whose volume is zero, not a wait. |
| SET_AUDCTL as a performance technique | `REJECTED_AS_TECHNIQUE_ADMITTED_AS_MODE` | AUDCTL_CHANGE occurs zero times in all four songs (Stage 15 records it as an absent kind, Stage 16 keeps it absent). It is admitted only because a stream must declare the channel mode it is written in; it is not claimed as a performance event. |
| MACRO | `DEFERRED_TO_MEASUREMENT` | Part Q is answered from the observed opcode n-grams, not assumed useful. |
| Laser, bell, bass, lead, percussion, or any instrument name | `REJECTED` | Stage 16 showed the same low-level technique carries different musical meanings in different songs, so a semantic name would have to encode song-specific grammar - exactly the inference this architecture exists to avoid. |

The shape this stage is not proposing:

- SAP -> style -> automatic interpretation (a style engine would have to guess the composition's intent, and Stage 16 measured that intent does not transfer)
- SAP -> instrument profile -> new composition (this is the SoundProfile branch, closed in Stage 14)

## 6. Event semantic contracts

Every opcode, with the eight properties Part E requires: inputs, the state it modifies, its duration, how it interacts with NOTE, how it interacts with other events, how it terminates, whether it may overlap, and whether it is interruptible.

| opcode | inputs | state modified | duration | overlap | interruptible |
|---|---|---|---|---|---|
| `SET_AUDCTL` | value: 8-bit AUDCTL byte | the channel mode; which channels are joined into pairs | 0 frames (instantaneous); persists until the next SET_AUDCTL | yes | yes |
| `SET_GENERATOR` | dist: the AUDC distortion nibble (0,2,...,14, shifted into bits 7-4) | the distortion nibble of one channel's AUDC | 0 frames (instantaneous); persists until the next SET_GENERATOR | yes | yes |
| `SET_VOLUME` | volume: 0..15 | the volume anchor of one voice<br>cancels a running volume effect | 0 frames (instantaneous) | yes | yes |
| `SET_PITCH` | divider: 0..255, or 0..65535 when the voice is a joined pair | the divider anchor of one voice<br>cancels a running pitch effect | 0 frames (instantaneous) | yes | yes |
| `NOTE` | divider<br>volume: 0..15<br>duration: frames, 0 means 'no duration' | the divider anchor and the volume anchor of one voice<br>cancels running pitch and volume effects<br>when duration > 0, schedules the volume to fall to 0 after that many frames | the note sounds until NOTE_OFF, the next volume event, or start+duration | no | yes |
| `NOTE_OFF` |  | the volume anchor is forced to 0<br>cancels a running volume effect | 0 frames (instantaneous) | yes | yes |
| `PITCH_SLIDE` | delta: divider change across the effect<br>duration: frames<br>curve: 0 | the divider of one voice, once per frame, while it runs | exactly ``duration`` frames | yes | yes |
| `PITCH_SWEEP` | delta<br>duration<br>curve: 1 | the divider of one voice, quadratically in time | exactly ``duration`` frames | yes | yes |
| `VIBRATO` | depth: divider units, peak-to-peak 2*depth<br>period: frames per cycle<br>duration | the divider of one voice, by an integer triangle wave | exactly ``duration`` frames | yes | yes |
| `TREMOLO` | depth: volume units<br>period: frames per cycle<br>duration | the volume of one voice, ducking below its anchor | exactly ``duration`` frames | yes | yes |
| `ARPEGGIO` | count<br>period: frames per tone<br>notes: divider table<br>duration | the divider of one voice, cycling an absolute table | exactly ``duration`` frames; the table repeats when it runs out | yes | yes |
| `VOLUME_SHAPE` | target: final level for a ramp<br>levels: explicit table (optional)<br>duration | the volume of one voice | exactly ``duration`` frames | yes | yes |

Interaction rules, as implemented by the interpreter:

- `SET_AUDCTL`: with NOTE - none; it changes how dividers are interpreted, not the note; with other events - re-writes the channel layout, so a joined pair's low channel stops carrying volume; termination - none; the value persists
- `SET_GENERATOR`: with NOTE - a NOTE does not change the distortion; the value survives a note; with other events - none; it never cancels a running effect; termination - none; the value persists
- `SET_VOLUME`: with NOTE - a NOTE also sets the volume anchor, so it supersedes this; with other events - cancels VOLUME_SHAPE and TREMOLO on the same voice; termination - none; the value persists
- `SET_PITCH`: with NOTE - a NOTE sets the same anchor and additionally starts a note; with other events - cancels PITCH_SLIDE, PITCH_SWEEP, VIBRATO and ARPEGGIO on the same voice; termination - none; the value persists
- `NOTE`: with NOTE - a NOTE supersedes the previous NOTE on the same voice; with other events - cancels every effect running on the same voice; termination - with duration > 0 the volume returns to 0 at start+duration; with duration = 0 the note ends only when NOTE_OFF or a volume event arrives
- `NOTE_OFF`: with NOTE - ends the current note; with other events - collides with SET_VOLUME on the same frame - see the ordering hazard below; termination - the voice stays silent until the next NOTE or volume event
- `PITCH_SLIDE`: with NOTE - runs on top of the note that is already sounding; with other events - cancels other pitch effects on the same voice, but CAN run while a volume effect runs; termination - when the duration elapses the voice returns to its divider anchor
- `PITCH_SWEEP`: with NOTE - as PITCH_SLIDE; with other events - as PITCH_SLIDE; termination - returns to the divider anchor
- `VIBRATO`: with NOTE - as PITCH_SLIDE; with other events - as PITCH_SLIDE; termination - returns to the divider anchor
- `TREMOLO`: with NOTE - as VOLUME_SHAPE; with other events - cancels other volume effects on the same voice; termination - returns to the volume anchor
- `ARPEGGIO`: with NOTE - as PITCH_SLIDE; with other events - as PITCH_SLIDE; termination - returns to the divider anchor
- `VOLUME_SHAPE`: with NOTE - runs on top of the note that is already sounding, from the note's own volume; with other events - cancels other volume effects on the same voice, but can run under a pitch effect; termination - returns to the volume anchor

**The one hazard this stage found by measurement:**

NOTE_OFF and SET_VOLUME on the same frame are ambiguous. The IR resolves the collision by opcode order, and that order puts SET_VOLUME before NOTE_OFF - so a correction written to a frame that also ends a note is silently discarded, and that reconstruction does not converge however many repair rounds it is given. Parts E and I report this as a defect in the language rather than working around it, and it is one of the measured reasons the attached note model is preferred over the sequential one.

## 7. Event sequencing model

Part F asks whether events should be sequential, attached to notes, or state changes. The answer is measured, not chosen: two composition models were built and compared on the same traces with the same interpreter.

| model | note carries | note ends when | exact share after repair | verdict |
|---|---|---|---|---|
| attached | a duration | the duration elapses | 1.0 | **preferred** |
| sequential | nothing | a separate `NOTE_OFF` arrives | 0.786241 | does not converge |

The sequential model fails for a semantic reason rather than a data reason: `NOTE_OFF` and `SET_VOLUME` collide on the same frame and the opcode order resolves the collision against the correction, so a repair pass re-patches the same frame every round and never converges. The attached model has no `NOTE_OFF` and therefore no collision.

The state-change layer is not optional and is not a competitor: the exact encoding still spends a mean of **0.884124** of its events on plain `SET_*` events. That number is the degeneracy measure Part 7 and Part 10 both need.

## 8. Reference trace encodings

For each song, the first observed occurrence of each behaviour category in canonical stream order, encoded in the language and published with the reference registers over the same window so the encoding can be checked by hand.

### Draconus_2024__sub0 (AUDCTL $00, 8826 frames)

**simple_note** - frames 0..9, channel 1

```
SET_AUDCTL ch0@0 value=0
SET_GENERATOR ch1@0 dist=192
SET_VOLUME ch1@0 volume=10
SET_PITCH ch1@0 divider=191
NOTE ch1@0+10 divider=191 volume=10
SET_GENERATOR ch2@0 dist=160
SET_VOLUME ch2@0 volume=1
SET_PITCH ch2@0 divider=243
... 38 more
```
reference registers: `AUDF1`=[191, 191, 191, 191, 191, 191]; `AUDC1`=[202, 201, 201, 200, 199, 199]; `AUDF2`=[243, 244, 245, 245, 244, 243]; `AUDC2`=[161, 161, 161, 162, 162, 162]; `AUDF3`=[204, 205, 206, 206, 205, 204]

**generator_change** - frames 0..0, channel 1

```
SET_AUDCTL ch0@0 value=0
SET_GENERATOR ch1@0 dist=192
SET_VOLUME ch1@0 volume=10
SET_PITCH ch1@0 divider=191
NOTE ch1@0+10 divider=191 volume=10
SET_GENERATOR ch2@0 dist=160
SET_VOLUME ch2@0 volume=1
SET_PITCH ch2@0 divider=243
... 9 more
```
reference registers: `AUDF1`=[191]; `AUDC1`=[202]; `AUDF2`=[243]; `AUDC2`=[161]; `AUDF3`=[204]

**busiest_multi_event_frame** - frames 0..2 - 17 events start on frame 0

```
SET_AUDCTL ch0@0 value=0
SET_GENERATOR ch1@0 dist=192
SET_VOLUME ch1@0 volume=10
SET_PITCH ch1@0 divider=191
NOTE ch1@0+10 divider=191 volume=10
SET_GENERATOR ch2@0 dist=160
SET_VOLUME ch2@0 volume=1
SET_PITCH ch2@0 divider=243
... 16 more
```
reference registers: `AUDF1`=[191, 191, 191]; `AUDC1`=[202, 201, 201]; `AUDF2`=[243, 244, 245]; `AUDC2`=[161, 161, 161]; `AUDF3`=[204, 205, 206]


### Warhawk__sub0 (AUDCTL $50, 10840 frames)

**simple_note** - frames 0..7, channel 2

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=192
SET_VOLUME ch2@0 volume=8
SET_PITCH ch2@0 divider=2410
NOTE ch2@0+8 divider=2410 volume=8
SET_GENERATOR ch3@0 dist=160
SET_VOLUME ch3@0 volume=2
SET_PITCH ch3@0 divider=41
... 33 more
```
reference registers: `AUDF1`=[106, 106, 106, 106, 106, 106]; `AUDF2`=[9, 9, 9, 9, 9, 9]; `AUDC2`=[200, 201, 199, 197, 196, 195]; `AUDF3`=[41, 40, 41, 42, 43, 43]; `AUDC3`=[162, 163, 164, 167, 168, 169]

**generator_change** - frames 0..0, channel 2

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=192
SET_VOLUME ch2@0 volume=8
SET_PITCH ch2@0 divider=2410
NOTE ch2@0+8 divider=2410 volume=8
SET_GENERATOR ch3@0 dist=160
SET_VOLUME ch3@0 volume=2
SET_PITCH ch3@0 divider=41
... 5 more
```
reference registers: `AUDF1`=[106]; `AUDF2`=[9]; `AUDC2`=[200]; `AUDF3`=[41]; `AUDC3`=[162]

**busiest_multi_event_frame** - frames 0..2 - 13 events start on frame 0

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=192
SET_VOLUME ch2@0 volume=8
SET_PITCH ch2@0 divider=2410
NOTE ch2@0+8 divider=2410 volume=8
SET_GENERATOR ch3@0 dist=160
SET_VOLUME ch3@0 volume=2
SET_PITCH ch3@0 divider=41
... 15 more
```
reference registers: `AUDF1`=[106, 106, 106]; `AUDF2`=[9, 9, 9]; `AUDC2`=[200, 201, 199]; `AUDF3`=[41, 40, 41]; `AUDC3`=[162, 163, 164]


### Ninja_Commando__sub0 (AUDCTL $50, 6081 frames)

**simple_note** - frames 0..160, channel 3

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=0
SET_VOLUME ch2@0 volume=0
SET_PITCH ch2@0 divider=1800
SET_GENERATOR ch3@0 dist=160
SET_VOLUME ch3@0 volume=10
SET_PITCH ch3@0 divider=44
NOTE ch3@0+161 divider=44 volume=10
... 178 more
```
reference registers: `AUDF1`=[8, 8, 8, 8, 8, 8]; `AUDF2`=[7, 7, 7, 7, 7, 7]; `AUDF3`=[44, 53, 44, 53, 44, 53]; `AUDC3`=[170, 170, 169, 169, 168, 167]; `AUDF4`=[241, 241, 241, 241, 241, 241]

**generator_change** - frames 0..0, channel 2

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=0
SET_VOLUME ch2@0 volume=0
SET_PITCH ch2@0 divider=1800
SET_GENERATOR ch3@0 dist=160
SET_VOLUME ch3@0 volume=10
SET_PITCH ch3@0 divider=44
NOTE ch3@0+161 divider=44 volume=10
... 3 more
```
reference registers: `AUDF1`=[8]; `AUDF2`=[7]; `AUDF3`=[44]; `AUDC3`=[170]; `AUDF4`=[241]

**busiest_multi_event_frame** - frames 0..2 - 11 events start on frame 0

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=0
SET_VOLUME ch2@0 volume=0
SET_PITCH ch2@0 divider=1800
SET_GENERATOR ch3@0 dist=160
SET_VOLUME ch3@0 volume=10
SET_PITCH ch3@0 divider=44
NOTE ch3@0+161 divider=44 volume=10
... 6 more
```
reference registers: `AUDF1`=[8, 8, 8]; `AUDF2`=[7, 7, 7]; `AUDF3`=[44, 53, 44]; `AUDC3`=[170, 170, 169]; `AUDF4`=[241, 241, 241]


### Red_Max__sub0 (AUDCTL $50, 6912 frames)

**simple_note** - frames 0..11, channel 2

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=192
SET_VOLUME ch2@0 volume=8
SET_PITCH ch2@0 divider=2700
NOTE ch2@0+12 divider=2700 volume=8
SET_GENERATOR ch3@0 dist=128
SET_VOLUME ch3@0 volume=10
SET_PITCH ch3@0 divider=0
... 41 more
```
reference registers: `AUDF1`=[140, 140, 140, 140, 140, 140]; `AUDF2`=[10, 10, 10, 10, 10, 10]; `AUDC2`=[200, 201, 200, 199, 198, 198]; `AUDF3`=[0, 181, 181, 181, 181, 181]; `AUDC3`=[138, 170, 168, 166, 164, 162]

**generator_change** - frames 0..0, channel 2

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=192
SET_VOLUME ch2@0 volume=8
SET_PITCH ch2@0 divider=2700
NOTE ch2@0+12 divider=2700 volume=8
SET_GENERATOR ch3@0 dist=128
SET_VOLUME ch3@0 volume=10
SET_PITCH ch3@0 divider=0
... 5 more
```
reference registers: `AUDF1`=[140]; `AUDF2`=[10]; `AUDC2`=[200]; `AUDC3`=[138]; `AUDF4`=[90]

**busiest_multi_event_frame** - frames 0..2 - 13 events start on frame 0

```
SET_AUDCTL ch0@0 value=80
SET_GENERATOR ch2@0 dist=192
SET_VOLUME ch2@0 volume=8
SET_PITCH ch2@0 divider=2700
NOTE ch2@0+12 divider=2700 volume=8
SET_GENERATOR ch3@0 dist=128
SET_VOLUME ch3@0 volume=10
SET_PITCH ch3@0 divider=0
... 13 more
```
reference registers: `AUDF1`=[140, 140, 140]; `AUDF2`=[10, 10, 10]; `AUDC2`=[200, 201, 200]; `AUDF3`=[0, 181, 181]; `AUDC3`=[138, 170, 168]


**The same opcode, in different songs, with different parameters:**

| opcode | song | frame | parameter | value | duration |
|---|---|---|---|---|---|
| `SET_GENERATOR` | Draconus_2024__sub0 | 0 | dist | 192 | 0 |
| `SET_GENERATOR` | Warhawk__sub0 | 0 | dist | 192 | 0 |
| `SET_GENERATOR` | Ninja_Commando__sub0 | 0 | dist | 0 | 0 |
| `SET_GENERATOR` | Red_Max__sub0 | 0 | dist | 192 | 0 |

## 9. Round-trip reconstruction

This is the key technical test. The reference trace is encoded, the IR is rendered by the offline interpreter, and the result is compared with the reference frame by frame. Every frame is classified EXACT, APPROXIMATE or UNREPRESENTABLE.

The comparison is audibility-aware: a silent channel's distortion and divider change no sound, so they are only compared when one side is making one. The strict all-nine-registers figure is published alongside as `register_exact_share`, so the harsher number is never hidden.

### Draconus_2024__sub0

| representation | events | bytes | exact | approx | unrep | register exact |
|---|---|---|---|---|---|---|
| `RAW_FRAMES` | 8826 | 79434 | 1.0 | - | 0.0 | - |
| `REGISTER_STATE_CONTROL` | 36157 | 161856 | 1.0 | 0.0 | 0.0 | 1.0 |
| `PERFORMANCE_ABSTRACTION_DRIVEN` | 15962 | 72652 | 0.002379 | 0.002153 | 0.995468 | 0.000113 |
| `PERFORMANCE_REFERENCE_ATTACHED` | 31575 | 146686 | 0.877068 | 0.0 | 0.122932 | 0.636868 |
| `PERFORMANCE_REFERENCE_ATTACHED_REPAIRED` | 33733 | 155318 | 1.0 | 0.0 | 0.0 | 0.755495 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL` | 29498 | 134204 | 0.654203 | 0.0 | 0.345797 | 0.467369 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL_REPAIRED` | 39158 | 174213 | 0.728416 | 0.0 | 0.271584 | 0.53739 |

### Warhawk__sub0

| representation | events | bytes | exact | approx | unrep | register exact |
|---|---|---|---|---|---|---|
| `RAW_FRAMES` | 10840 | 97560 | 1.0 | - | 0.0 | - |
| `REGISTER_STATE_CONTROL` | 40615 | 175844 | 1.0 | 0.0 | 0.0 | 1.0 |
| `PERFORMANCE_ABSTRACTION_DRIVEN` | 23519 | 107134 | 0.002675 | 0.003967 | 0.993358 | 0.002675 |
| `PERFORMANCE_REFERENCE_ATTACHED` | 34537 | 155138 | 0.860978 | 0.0 | 0.139022 | 0.860978 |
| `PERFORMANCE_REFERENCE_ATTACHED_REPAIRED` | 46099 | 201386 | 1.0 | 0.0 | 0.0 | 1.0 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL` | 33735 | 147207 | 0.695203 | 0.0 | 0.304797 | 0.695203 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL_REPAIRED` | 52936 | 225131 | 0.820756 | 0.0 | 0.179244 | 0.818727 |

### Ninja_Commando__sub0

| representation | events | bytes | exact | approx | unrep | register exact |
|---|---|---|---|---|---|---|
| `RAW_FRAMES` | 6081 | 54729 | 1.0 | - | 0.0 | - |
| `REGISTER_STATE_CONTROL` | 14238 | 64324 | 1.0 | 0.0 | 0.0 | 1.0 |
| `PERFORMANCE_ABSTRACTION_DRIVEN` | 6679 | 31650 | 0.017102 | 0.019405 | 0.963493 | 0.017102 |
| `PERFORMANCE_REFERENCE_ATTACHED` | 13168 | 60974 | 0.999671 | 0.0 | 0.000329 | 0.841638 |
| `PERFORMANCE_REFERENCE_ATTACHED_REPAIRED` | 13170 | 60982 | 1.0 | 0.0 | 0.0 | 0.841967 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL` | 13363 | 60643 | 0.875843 | 0.0 | 0.124157 | 0.732774 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL_REPAIRED` | 15382 | 68924 | 0.876172 | 0.0 | 0.123828 | 0.733103 |

### Red_Max__sub0

| representation | events | bytes | exact | approx | unrep | register exact |
|---|---|---|---|---|---|---|
| `RAW_FRAMES` | 6912 | 62208 | 1.0 | - | 0.0 | - |
| `REGISTER_STATE_CONTROL` | 24788 | 107518 | 1.0 | 0.0 | 0.0 | 1.0 |
| `PERFORMANCE_ABSTRACTION_DRIVEN` | 16888 | 76281 | 0.000145 | 0.049624 | 0.950231 | 0.000145 |
| `PERFORMANCE_REFERENCE_ATTACHED` | 19821 | 90571 | 0.833044 | 0.0 | 0.166956 | 0.833044 |
| `PERFORMANCE_REFERENCE_ATTACHED_REPAIRED` | 32988 | 143239 | 1.0 | 0.0 | 0.0 | 1.0 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL` | 20187 | 88132 | 0.595631 | 0.0 | 0.404369 | 0.595631 |
| `PERFORMANCE_REFERENCE_SEQUENTIAL_REPAIRED` | 40155 | 169024 | 0.719618 | 0.0 | 0.280382 | 0.719618 |

| representation | mean exact share | reading |
|---|---|---|
| raw frames | 1.0 | ground truth, not part of the language |
| register-state control | 1.0 | exact by construction, and the size control |
| technique abstraction replayed | 0.005575 | **the abstraction is not a sufficient description of the song** |
| performance, attached | 1.0 | 100% on all four songs after the measured repair pass |
| performance, sequential | 0.786241 | does not converge: NOTE_OFF collides with SET_VOLUME |

ATTACHED: with the repair pass it reaches 100% on all four songs. SEQUENTIAL: it does not converge, because NOTE_OFF and SET_VOLUME collide on the same frame and the opcode order resolves the collision against the correction.

## 10. Compression analysis

IR record = 1 byte opcode+channel, an unsigned frame delta in 1-3 bytes, 1 byte duration, then the parameters: divider/delta 2 bytes, volume/dist/target/curve/period/count 1 byte, table entries 1-2 bytes each. Raw frames = 9 bytes per frame. Current format = 3 bytes per note plus a 7-byte header and a 20-byte instrument table. The model is stated so every ratio can be recomputed by hand.

Does the event layer beat a raw frame dump? Not on this corpus. The per-song tables below give the bytes; the `does_the_event_layer_compress` line under each is the answer for that song.

### Draconus_2024__sub0

| representation | events | bytes | x raw dump | x current format |
|---|---|---|---|---|
| `A_current_note_event` | 2803 | 8436 | 0.106 | 1.0 |
| `B_raw_per_frame_state` | 8826 | 79434 | 1.0 | 9.416 |
| `C_register_state_control` | 36157 | 161856 | 2.038 | 19.186 |
| `C_performance_abstraction` | 15962 | 72652 | 0.915 | 8.612 |
| `C_performance_attached` | 31575 | 146686 | 1.847 | 17.388 |
| `C_performance_attached_repaired` | 33733 | 155318 | 1.955 | 18.411 |

The exact encoding beats a raw register dump here? **no** (a full register dump every frame is what a dedicated format would have to beat; it is the honest floor for this comparison).

### Warhawk__sub0

| representation | events | bytes | x raw dump | x current format |
|---|---|---|---|---|
| `A_current_note_event` | 3603 | 10836 | 0.111 | 1.0 |
| `B_raw_per_frame_state` | 10840 | 97560 | 1.0 | 9.003 |
| `C_register_state_control` | 40615 | 175844 | 1.802 | 16.228 |
| `C_performance_abstraction` | 23519 | 107134 | 1.098 | 9.887 |
| `C_performance_attached` | 34537 | 155138 | 1.59 | 14.317 |
| `C_performance_attached_repaired` | 46099 | 201386 | 2.064 | 18.585 |

The exact encoding beats a raw register dump here? **no** (a full register dump every frame is what a dedicated format would have to beat; it is the honest floor for this comparison).

### Ninja_Commando__sub0

| representation | events | bytes | x raw dump | x current format |
|---|---|---|---|---|
| `A_current_note_event` | 911 | 2760 | 0.05 | 1.0 |
| `B_raw_per_frame_state` | 6081 | 54729 | 1.0 | 19.829 |
| `C_register_state_control` | 14238 | 64324 | 1.175 | 23.306 |
| `C_performance_abstraction` | 6679 | 31650 | 0.578 | 11.467 |
| `C_performance_attached` | 13168 | 60974 | 1.114 | 22.092 |
| `C_performance_attached_repaired` | 13170 | 60982 | 1.114 | 22.095 |

The exact encoding beats a raw register dump here? **no** (a full register dump every frame is what a dedicated format would have to beat; it is the honest floor for this comparison).

### Red_Max__sub0

| representation | events | bytes | x raw dump | x current format |
|---|---|---|---|---|
| `A_current_note_event` | 2883 | 8676 | 0.139 | 1.0 |
| `B_raw_per_frame_state` | 6912 | 62208 | 1.0 | 7.17 |
| `C_register_state_control` | 24788 | 107518 | 1.728 | 12.393 |
| `C_performance_abstraction` | 16888 | 76281 | 1.226 | 8.792 |
| `C_performance_attached` | 19821 | 90571 | 1.456 | 10.439 |
| `C_performance_attached_repaired` | 32988 | 143239 | 2.303 | 16.51 |

The exact encoding beats a raw register dump here? **no** (a full register dump every frame is what a dedicated format would have to beat; it is the honest floor for this comparison).

**The headline.** For all four songs the exact event encoding is *larger* than a raw register dump. The reason is structural rather than a defect in the encoder: the reference players write several registers every frame across four voices, so the behaviour has almost no redundancy for an event layer to remove. An event layer only pays for itself when the same information is held constant across many frames, and at 50 Hz in these songs it is not.

The abstraction-driven encoding is smaller than the raw dump in 2 of 4 songs, and not in the rest - a count that is published because the difference matters: the only compact representation found is also the one that reproduces the least.

That pairing is the whole result: the compact representation is not faithful, and the faithful representation is not compact.

## 11. Player code cost

ESTIMATE, by construction. The baseline is measured: Stage 15 recorded 886 assembled bytes (827 code, 59 state). New code is charged at the current source's own density, 1.826 bytes per code line (827 code bytes over 453 code lines), and the per-opcode line counts are engineering estimates stated in OPCODE_COST. The RAM figures are structural, not estimates: each running effect needs an opcode, a remaining-frame counter and its parameters, per voice.

| opcode | handler lines | code bytes (EST) | state bytes | cycles | justified by |
|---|---|---|---|---|---|
| `SET_AUDCTL` | 6 | 11 | 0 | 12 | - |
| `SET_GENERATOR` | 4 | 7 | 0 | 8 | DISTORTION_CHANGE, GENERATOR_CHANGE |
| `SET_VOLUME` | 4 | 7 | 0 | 6 | VOLUME_CHANGE |
| `SET_PITCH` | 5 | 9 | 0 | 10 | PITCH_CHANGE, REGISTER_PATTERN_CHANGE |
| `NOTE` | 10 | 18 | 0 | 20 | NOTE_ON |
| `NOTE_OFF` | 3 | 5 | 0 | 6 | NOTE_OFF |
| `PITCH_SLIDE` | 18 | 33 | 4 | 22 | PITCH_SLIDE_FALLING, PITCH_SLIDE_RISING |
| `PITCH_SWEEP` | 20 | 37 | 4 | 26 | PITCH_SWEEP_FALLING, PITCH_SWEEP_RISING |
| `VIBRATO` | 22 | 40 | 5 | 30 | VIBRATO |
| `TREMOLO` | 20 | 37 | 4 | 28 | TREMOLO |
| `ARPEGGIO` | 26 | 47 | 6 | 34 | ARPEGGIO |
| `VOLUME_SHAPE` | 20 | 37 | 4 | 24 | VOLUME_ENVELOPE_FALLING, VOLUME_ENVELOPE_RISING |

| item | bytes |
|---|---|
| current player, measured (Stage 15) | 886 |
| dispatcher (ESTIMATE) | 51 |
| opcode handlers (ESTIMATE) | 288 |
| added state (structural) | 35 |
| **projected player (ESTIMATE)** | 1225 |
| envelope | 2048 |
| headroom | 823 |

Do not forget what this is: the baseline is measured, the additions are estimated from the current source's own bytes-per-code-line, and no player was modified. the estimated player after the change is 1225 bytes against a 2048-byte envelope (COMFORTABLY_FITS).

## 12. Song data cost

Player code and song data are different budgets and this stage reports them separately. Nothing in Part N is a claim about the player's size; that is Part L.

| song | frames | current note format | raw frame dump | exact event encoding | bytes/frame (event) | plain-state share |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | 8826 | 8409 | 79434 | 155318 | 17.598 | 0.879905 |
| `Warhawk__sub0` | 10840 | 10809 | 97560 | 201386 | 18.578 | 0.895272 |
| `Ninja_Commando__sub0` | 6081 | 2733 | 54729 | 60982 | 10.028 | 0.907427 |
| `Red_Max__sub0` | 6912 | 8649 | 62208 | 143239 | 20.723 | 0.853892 |

Stage 15 measured the reference song at 90,486 bytes as one note per frame and 886 bytes of player. The 'raw_frame_dump' column above is the same idea measured directly on the trace, and it is the number the event encoding is compared with.

## 13. 2 KB feasibility

ESTIMATE. The baseline is measured; the additions are estimated from the current source's bytes-per-code-line. The label is read off the resulting headroom, so it moves with the arithmetic instead of being a separate opinion.

| item | bytes |
|---|---|
| baseline player (measured) | 886 |
| added code (ESTIMATE) | 339 |
| added state (structural) | 35 |
| projected player (ESTIMATE) | 1225 |
| envelope | 2048 |
| headroom | 823 |

**COMFORTABLY_FITS**. It does not say the player should be expanded. Stage 15 measured 886 bytes against a 2 KB envelope and found the player is not the binding constraint; this stage's estimate agrees, and Part N shows why that is not a reason to build anything: the song data is the larger cost and the language does not reduce it.

Stage 15 estimated 270 bytes of added code for one song's mechanism set; this stage estimates 339 bytes, because it charges a full dispatcher and a handler per opcode rather than only the mechanisms the reference song happened to need. Stage 15 estimated 270 bytes of added code for a mechanism set justified by one song. This stage's estimate is larger because it counts a full dispatcher and a handler per opcode rather than only the mechanisms the reference song needed.

## 14. Hardware constraints

Every hardware limit is either handled explicitly or refused explicitly. Nothing is hidden inside a semantic event.

| constraint | rule | handling |
|---|---|---|
| 8-bit divider range | 0..255 when the channel is not part of a joined pair | the interpreter clamps and counts; the count is published per song |
| 16-bit channel coupling | AUDCTL bit 4 joins channels 1+2, bit 5 joins 3+4; the low channel supplies the divider's low byte and carries no volume, the high channel carries the high byte and the volume | voice_layout() encodes this rule; the language addresses the voice, and the interpreter derives both register bytes from one divider value |
| AUDCTL | one byte, global, affects every channel at once | SET_AUDCTL. There is exactly one in every stream, at frame 0; a mid-song change was never observed in the corpus |
| channel ownership | a joined pair is one voice with two registers | an event names the voice channel; the low channel of a pair is never addressed separately, so the two bytes cannot desynchronise |
| generator / distortion | AUDC bits 7-4 select the waveform, bits 3-0 the volume | SET_GENERATOR carries bits 7-4 and only bits 7-4 |
| volume | 0..15 | the interpreter clamps to 0..15 and counts the clamps |
| frame rate | the corpus is digitised at 50 Hz; an effect duration is a frame count | durations are in frames; the language has no notion of seconds, so it cannot silently resample |

A pitch outside the current mode's range is refused rather than folded. The interpreter increments unrepresentable_pitch instead of wrapping the divider, because wrapping would turn an unrepresentable pitch into a wrong but plausible one and the failure would become invisible.

No semantic event silently assumes its target is representable. A PITCH_SLIDE whose delta leaves the range is clamped and counted, not encoded away.

| song | AUDCTL | joined pairs | divider range | largest divider | unrep. pitch | clamped writes |
|---|---|---|---|---|---|---|
| `Draconus_2024__sub0` | $00 | - | 255 | 255 | 0 | 0 |
| `Warhawk__sub0` | $50 | 1-2 | 65535 | 2700 | 0 | 0 |
| `Ninja_Commando__sub0` | $50 | 1-2 | 65535 | 1800 | 0 | 0 |
| `Red_Max__sub0` | $50 | 1-2 | 65535 | 2700 | 0 | 0 |

The two AUDCTL configurations in the corpus are `$00` (all four channels independent) and `$50` (channels 1+2 joined as one 16-bit divider, channel 1 clocked at 1.79 MHz). Both are handled by one rule in `voice_layout`, which is why the language addresses voices rather than register bytes.

## 15. Macro analysis

count every opcode n-gram of length 3..8 in the fixed (exact) event stream; a candidate must occur at least 3 times; a macro call is charged 2 bytes and defined as its body plus 2. The estimated net saving is the body replaced minus the call sites minus the definition.

| song | events | best repeated sequence | occurrences | estimated net saving (bytes) |
|---|---|---|---|---|
| `Draconus_2024__sub0` | 33733 | SET_VOLUME SET_PITCH SET_VOLUME | 3870 | 38686 |
| `Warhawk__sub0` | 46099 | SET_VOLUME SET_PITCH SET_GENERATOR SET_VOLUME | 3439 | 51566 |
| `Ninja_Commando__sub0` | 13170 | SET_VOLUME SET_PITCH SET_VOLUME | 2996 | 29946 |
| `Red_Max__sub0` | 32988 | SET_VOLUME SET_GENERATOR SET_VOLUME SET_GENERATOR | 3525 | 52856 |

**MARGINAL.** the repetition a macro would capture is short and rare; the same effect is already available for free through the note model, which emits NOTE with a duration instead of spelling out the events that fill it.

## 16. Semantic neutrality

**Could the same event representation describe two songs where the same low-level technique has different musical meanings?**

Yes, and the measurement is that it already does. The opcode set is a fixed set of register operations, identical for all four songs; what differs is which song uses which opcodes, how often, and with what parameters.

The language does not say any of the following:

- it never records that a generator change marks a percussion hit
- it never records that a slide is a portamento or a sound effect
- it never infers a channel's role from its index
- it never selects an effect because of the song's identity
- it never records a style, an instrument name, or a musical role

| opcode | songs using it | usage |
|---|---|---|
| `SET_AUDCTL` | 4 | Draconus:1, Ninja:1, Red:1, Warhawk:1 |
| `SET_GENERATOR` | 4 | Draconus:3773, Ninja:7, Red:13465, Warhawk:13981 |
| `SET_VOLUME` | 4 | Draconus:13352, Ninja:6069, Red:11121, Warhawk:18734 |
| `SET_PITCH` | 4 | Draconus:12828, Ninja:5884, Red:5515, Warhawk:9776 |
| `NOTE` | 4 | Draconus:2803, Ninja:911, Red:2883, Warhawk:3603 |
| `NOTE_OFF` | 0 | Draconus:0, Ninja:0, Red:0, Warhawk:0 |
| `PITCH_SLIDE` | 0 | Draconus:0, Ninja:0, Red:0, Warhawk:0 |
| `PITCH_SWEEP` | 0 | Draconus:0, Ninja:0, Red:0, Warhawk:0 |
| `VIBRATO` | 4 | Draconus:976, Ninja:298, Red:3, Warhawk:4 |
| `TREMOLO` | 0 | Draconus:0, Ninja:0, Red:0, Warhawk:0 |
| `ARPEGGIO` | 0 | Draconus:0, Ninja:0, Red:0, Warhawk:0 |
| `VOLUME_SHAPE` | 0 | Draconus:0, Ninja:0, Red:0, Warhawk:0 |

The SoundProfile branch failed because it tried to make an instrument portable. This language makes no claim about instruments at all: it carries operations and leaves every musical decision to the composition, which is the one layer that is allowed to know what the song is.

A neutrality check a reader can run: every field in every opcode is a number or a reference to a channel. No opcode, parameter name or value names a sound, a role, or a song.

## 17. Architecture proposal

```text
COMPOSITION - what / when: pitch, duration, velocity, rhythm, structure
PERFORMANCE EVENT IR - what happens: explicit register operations with parameters
POKEY PLAYER - how: register writes, timing, AUDCTL, channel state, hardware limits
POKEY
```

Context stays in the composition. The language contains no rule of the form 'if channel 3 then percussion' and no event named after a song. A composition decides when a SET_GENERATOR happens; the player only executes it.

What stays outside the player:

- which opcode to use, and when
- every parameter value
- song structure, phrases and repeats
- any musical interpretation of a register operation

What requires player code:

- `SET_AUDCTL`
- `SET_GENERATOR`
- `SET_VOLUME`
- `SET_PITCH`
- `NOTE`
- `NOTE_OFF`
- `PITCH_SLIDE`
- `PITCH_SWEEP`
- `VIBRATO`
- `TREMOLO`
- `ARPEGGIO`
- `VOLUME_SHAPE`

What requires only song data:

- the event stream itself
- the note durations
- every effect parameter

## 18. Answers to research questions

### Q1 What is the smallest evidence-supported vocabulary?

**12 opcodes: SET_AUDCTL; SET_GENERATOR; SET_VOLUME; SET_PITCH; NOTE; NOTE_OFF; PITCH_SLIDE; PITCH_SWEEP; VIBRATO; TREMOLO; ARPEGGIO; VOLUME_SHAPE**

*Basis:* 16 techniques observed across the four Stage 16 songs reduce to that set of register effects, and no observed technique is left without an opcode. WAIT was offered by the brief and rejected: no observed technique is an absence of behaviour, and the frame field already carries time.

### Q2 Can it represent the common cross-song behaviour?

**Yes, and the common subset is small.**

*Basis:* the behaviour-driven encoding reproduces every song completely after repair (mean exact share 1.0); the opcodes used by all four songs are the low-level ones, which is Stage 16's finding that the shared vocabulary is real but low-level

### Q3 Can it represent song-specific contextual behaviour without embedding song-specific semantics?

**Yes, because context lives in the parameters, not in the opcodes.**

*Basis:* the same opcode appears in different songs with different parameters and different frequencies; the encoding records the parameter and never asks why it differs (Part R)

### Q4 Can real reference traces be reconstructed from the representation?

**Yes for the behaviour-driven encoding (1.0 mean exact share after repair) and no for the abstraction-driven one (0.005575).**

*Basis:* Part I. The distinction is the result: a faithful encoding exists, but replaying the Stage 15 technique vocabulary alone does not reproduce the song, because the vocabulary is a lossy summary of the per-frame behaviour it was derived from.

### Q5 How much smaller is it than per-frame unrolling?

**It is not smaller. It is about 1.859x a raw register dump.**

*Basis:* Part K, representation C versus B. The reference players change several registers per frame across four voices, so there is little for an event layer to collapse: the events are already at frame granularity. Without repair the ratio is 1.50175x, still above 1.

### Q6 How much larger is it than the current simple event representation?

**Substantially larger: about 18.90025x the current note format.**

*Basis:* Part K, representation C versus A. The current format spends 3 bytes per note and leaves every frame between notes to the player's own envelope; the event language spells out what happens in those frames.

### Q7 What player mechanisms are actually required?

**One dispatcher, one handler per opcode, and per-voice effect state.**

*Basis:* Part L: SET_AUDCTL; SET_GENERATOR; SET_VOLUME; SET_PITCH; NOTE; NOTE_OFF; PITCH_SLIDE; PITCH_SWEEP; VIBRATO; TREMOLO; ARPEGGIO; VOLUME_SHAPE. The mechanism families Stage 15 identified (effect step, generator set, volume set) cover all of them; nothing here needs a new hardware feature.

### Q8 Can those mechanisms plausibly fit within 2 KB?

**COMFORTABLY_FITS: estimated 1225 bytes against 2048.**

*Basis:* Part L's estimate (ESTIMATE, method stated) plus Stage 15's measured 886-byte baseline. Part M reads the label off the resulting headroom.

### Q9 Is the primary limitation player code, song data, or representation?

**Song data and representation, jointly. The player is not the limitation.**

*Basis:* Parts K and N: the exact event encoding is about 1.859x a raw register dump and about 18.90025x the current format, while the estimated player is 1225 bytes in a 2048-byte envelope. The player is the one budget with room left.

### Q10 Are macros necessary?

**No. MARGINAL.**

*Basis:* Part Q: literal opcode repetition is short and rare in the compiled streams, and the note model already provides the repetition a macro would capture.

### Q11 Can the event language remain semantically neutral?

**Yes, by construction and by test.**

*Basis:* Yes, and the measurement is that it already does. The opcode set is a fixed set of register operations, identical for all four songs; what differs is which song uses which opcodes, how often, and with what parameters. A neutrality check a reader can run: every field in every opcode is a number or a reference to a channel. No opcode, parameter name or value names a sound, a role, or a song.

### Q12 Does this architecture avoid the SoundProfile failure mode?

**Yes, and for a structural reason rather than a stylistic one.**

*Basis:* a SoundProfile claimed an instrument transfers between songs and was falsified. This language claims nothing transfers except a set of register operations: it carries no instrument, no role and no style, and every decision that did not transfer in Stage 16 stays in the composition layer. The cost is that it is not compact: about 1.50175x a raw dump.

## 19. Limitations

- **Four songs, one era, one hardware configuration family.** Two AUDCTL values are represented (`$00` and `$50`), and three of the four songs use the same one. Nothing here is evidence about cross-configuration or cross-era behaviour.
- **The technique vocabulary is inherited, and it is lossy.** Part 9 measures the cost of that inheritance directly: Stage 15's generator detector reports a fraction of the distortion changes the trace contains, so an encoding driven by the abstraction cannot reproduce them. This is a limit of the *input*, and this stage reports it rather than working around it.
- **The byte model is stated, not measured.** Every compression ratio is arithmetic on a published record layout. A real implementation could pack fields differently and the ratios would move; the model is stated so that they can be recomputed.
- **The player cost is an ESTIMATE.** The baseline is measured; the additions are charged at the current source's bytes-per-code-line. No 6502 code was written for the event language, so no figure here is a measurement of a real player.
- **The interpreter's effect curves are choices.** A triangle for vibrato and tremolo, a quadratic for a sweep, a linear ramp for a volume shape. The round trip shows they can be made exact or near-exact on this corpus, but a different curve set would produce different per-event parameters.
- **The repair pass is a cost, not a feature.** It exists to measure how much explicit correction the compact encoding needs. A production encoder would aim to emit fewer corrections, and this stage has not established that it can.
- **No listener was asked anything.** Every claim here is about registers and bytes. Whether any of it is audible, or preferable, is untested by design.

## 20. Stage 17 verdict

| verdict | result | rule |
|---|---|---|
| event language | `EVENT_LANGUAGE_PARTIALLY_SUPPORTED` | SUPPORTED requires a faithful reconstruction (exact share >= 0.999 on every song) AND a compact encoding (< 1.0x a raw register dump). PARTIALLY_SUPPORTED requires one of the two. |
| 2 KB player | `2KB_PLAYER_PLAUSIBLE` | COMFORTABLY_FITS below 75% of the envelope, LIKELY_FITS below 100%, UNCERTAIN below 110%, LIKELY_EXCEEDS below 150%, CLEARLY_EXCEEDS above that |
| main bottleneck | `MULTIPLE_BOTTLENECKS` | song data is a bottleneck when the exact encoding exceeds a raw dump; the representation is a bottleneck when replaying the technique abstraction reproduces less than half the frames. More than one triggers MULTIPLE_BOTTLENECKS. |

The language is faithful (1.0 exact share after repair on every song) but it is not compact (1.50175x a raw register dump, 1.859x with the repair pass). A middle layer that is exact but larger than the register dump it replaces does not earn its place on the grounds this stage set out to test.

The player has room; the song data does not, and the technique abstraction is not a sufficient description of a song's behaviour, so the composition has to supply the operations explicitly. Two costs, one of them structural.

The three verdicts come from different tests and are deliberately not correlated. The language can be semantically neutral and faithful while being too large; the player can fit while the song data does not.

What would change a verdict:

- a reference encoding that beats the raw dump would move the language verdict; the measurement suggests that only happens when the composition emits notes and effects at note granularity rather than at frame granularity
- a technique vocabulary that described per-frame behaviour exactly would move the abstraction verdict; Stage 15's detector is the thing to improve, not the language

## 21. What should NOT be built yet

| not yet | why not |
|---|---|
| a 4 KB player, or any player enlargement | the player is estimated at well under the 2 KB envelope and Stage 15 already falsified 'the player is too small'. The measured constraint is song data, and a larger player does not touch it. |
| implementing the event language in the player | the language is faithful but not compact: it is larger than a raw register dump. Building it would make song data bigger while changing nothing audible, on this evidence. |
| a style engine, or any automatic interpretation of a song | Stage 16 measured that context does not transfer. An engine that inferred context would have to embed exactly the song-specific grammar the evidence shows does not generalise. |
| a Composer or DSL change | no listening test was run and nothing here says a listener wants event-level control. The architecture is supported in principle and unsupported as an engineering priority. |
| reviving SoundProfile under a new name | the language carries operations and no instruments. Anything that reintroduced a portable instrument definition would reopen a branch Stage 14 closed. |
| a listening test | forbidden by the stop condition. It is the natural first step of any future stage that wants to act on this, but it is not this stage's job. |

## 22. Candidate Stage 18 experiments

| candidate | question it answers | cost |
|---|---|---|
| improve the Stage 15 detector, then repeat the abstraction replay | Is the abstraction's failure a limit of the vocabulary or of the detector? | analysis only, no production change |
| compile a compositional score into the IR instead of a trace | When the events come from a composer rather than from a recorded performance, is the encoding smaller? Note-granularity input is the only route the compression finding leaves open. | analysis only; still no player change |
| measure the byte cost of the current player's own format on one song | How far is the current 3-byte note format from the raw dump it replaces? That comparison was never made and it is the one the event language has to win. | analysis only |
| check whether an entropy or RLE bound beats the event language | Is there any representation of this behaviour that beats the raw dump? If not, the register dump is the right format and the middle layer is unnecessary. | analysis only |
| a listening test of one effect in two contexts | Is a technique heard as the same thing when its context changes? Part R says the language does not care; nobody has checked whether a listener does. | a blind package; the natural first production-facing step |

---

Stage 17 read four corpus songs and the Stage 15 and Stage 16 records through their hashes, defined an event language from the observed behaviour, and measured a round trip with a research-only interpreter. No Composer, DSL, Music IR, POKEY IR, player, schema or SoundProfile was modified; the player source is hashed as an input and never written. No audio was rendered, no music was generated, no listening test was run, and no style or instrument abstraction was implemented.

# C1 (`c1_octave_pulse`) in XEX output — 6502 player extension design

**Status: design only. Nothing here is implemented, and nothing is approved.** No production file,
test, assembly source, IR, exporter, CLI, library or experiment artefact was modified to produce this
document.

Every claim is labelled:

* **[verified]** — read from the current source, or measured in this repository by the method in the
  appendix.
* **[estimate]** — arithmetic from stated assumptions. Cycle counts are hand-computed from the
  published 6502 instruction timings, not measured on an emulator.
* **[proposed]** — a design decision that would need approval.

---

## 0. Summary

`c1_octave_pulse` needs exactly one thing the current XEX format cannot express: **a change of the
channel's frequency divider `AUDF` in the middle of a note.** Everything else C1 does — its `$40`
generator, its envelope, its channel and its clock — is already supported by the current player and
exporter **[verified]**.

The smallest reliable change is a **per-channel modulation descriptor byte in the instrument table**,
plus a short per-frame routine in `player.asm`. Measured against a scratch build of the current player:
**+88 bytes of player** (821 code bytes → 896, 59 data bytes → 72) and **+5 bytes of music data per
song** (one format-version byte, four modulation bytes). Nothing changes in the note stream.

The note stream is where the two larger alternatives spend their bytes: a per-note effect descriptor
costs **+399 bytes (+30.7 %)** on the project's own reference song, and a frame-accurate register-event
stream costs roughly **4.4 KB** for C1 on one channel of that same song.

The recommended design is option **A**, with the descriptor byte shaped as a small opcode rather than a
boolean so that a second periodic modulation costs no further format change.

---

## 1. Current architecture and the verified limitation

### 1.1 The pipeline, traced

| stage | source |
| :--- | :--- |
| composition (DSL or JSON) | `src/atari_music/ai/dsl.py`, `ai/schema.py` (`AICompositionDoc`, `AIInstrumentDef`) |
| validation | `ai/validation.py` (3-tier; rejects a distortion outside `{0x00,0x20,0x40,0x60,0x80,0xA0,0xC0,0xE0}`) |
| Music IR / POKEY IR | `ir.py` (`IRSong`, `IRPattern`, `IRNote`, `IRInstrument`, `IREnvelope`) |
| register frames (WAV path) | `ir.py::compile_ir_to_pokey_frames` → `ir.py::_render_note_to_frames` → `(total_frames, 9)` uint8 stream |
| MADS assembly (XEX path) | `mads_exporter.py::export_mads_asm` → `music_data.asm` text |
| XEX assembly | `ai/client.py::build_xex_from_composition` — `result_transform(...)` (line 587–591), then `song_asm = export_mads_asm(res)` (line 592), then a generated harness that does `org $6000` … `icl 'player.asm'` (line 1095) … `org $8000` … song data (line 1100–1102) |
| playback | `player.asm` |

`build_xex_from_composition` defaults `player_address` to `$4000`, but the CLI passes `--player-address
0x6000` and `--music-address 0x8000` **[verified]**.

**[verified] `player.asm` exists twice and the two copies are byte-identical** (same SHA-256
`2b14a973774ddecc…`): the repository root `player.asm` and `src/atari_music/asm/player.asm`. The root
one is what `build_xex_from_composition` finds first (explicit → cwd → repository root → package); the
package one is what `stage15.py::DEFAULT_PLAYER_ASM` and the stage modules watch. **Any change to the
player must be made to both, or they will silently diverge.**

### 1.2 The player

`player.asm` is 629 lines, 453 of them code **[verified via `stage15.player_capabilities`]**. It
assembles to **880 bytes** at `$6000`–`$636F`: **821 bytes of code** and **59 bytes of state/data**,
plus **10 zero-page bytes** at `$80` **[verified, measured — appendix A]**.

Public entry points, all unchanged by this design: `music_init`, `music_play`, `music_stop`,
`music_update`, `music_is_playing` **[verified]**.

`music_update` (line 168) is the whole per-frame story:

```
music_update:
    if not music_playing: rts
    dec tick_counter
    if tick_counter == 0:
        tick_counter = tempo_divider
        for x in 0..3:
            if ch_dur,x == 0:            jsr fetch_channel_note
            else: dec ch_dur,x; if 0:    jsr fetch_channel_note
    jsr update_envelopes
    jsr write_pokey_registers
```

**[verified]** the documented contract is "call exactly once per 50 Hz VBLANK" (header comment line 9
and line 166), and **nothing in the code enforces or compensates for that**; `report_pokey_audit.md`
item 11 records the same. Everything below assumes 50 Hz.

### 1.3 The music data format

**[verified]** `mads_exporter.py`'s module docstring and `stage15.player_capabilities()["data_format"]`
agree, and the emitted ASM confirms both:

| block | size | fields |
| :--- | :--- | :--- |
| song header | 6 bytes | `frames_per_tick` (1), `audctl_mode` (1), `instruments_ptr` (2), `sequence_ptr` (2) |
| instruments | 4 × 5 = 20 bytes | per channel: `distortion`, `attack`, `decay`, `sustain`, `release` |
| sequence | 2 bytes/step + 2 | `.word` pattern-track-list pointer, `$FFFF` terminator |
| pattern track lists | 4 × 2 bytes/pattern | `.word` per channel |
| track events | 3 bytes/event | `audf`, `duration_ticks`, `volume`; `$FF` = end of track |

**[verified]** for `examples/songs/Vaults-of-Nhyrmeth.dsl` the exporter emits **1299 bytes** of music
data (1239 `.byte` + 60 `.word`), of which **1217 bytes** are track events: 399 note records × 3 bytes
plus 20 end-of-track markers.

**[verified]** there is **no version field anywhere** in the header, the instrument table or the event
record.

### 1.4 The one thing C1 needs

**[verified]** `write_pokey_registers` (line 505) writes **`AUDF1..4` unconditionally, every frame**,
from the player's own `ch_audf` array:

```
lda ch_audf + 0
sta AUDF1_REG
```

**[verified]** `ch_audf` is written in exactly two places — `fetch_channel_note` (`@got_note`, line 269,
from the note's AUDF byte) and `@early_end_track` (line 260, zeroed) — and read in exactly two:
`@setup_envelope` (line 314, the rest test) and `write_pokey_registers` (lines 515–570). Nothing else
touches it.

So the player already has a per-frame register write of a per-channel divider value. **A per-frame
modulation only has to modify `ch_audf` before `write_pokey_registers` runs.** The player's structure
needs no new write path, no new pointer and no change to the note stream.

### 1.5 The verified limitation, stated exactly

**[verified]** `mads_exporter.py` writes the note's AUDF **once**, and the 3-byte event has no field for
anything else. `stage15.player_capabilities()`'s `effect_column` row says it directly: *"The event is
exactly three bytes (audf, duration, volume); there is nowhere to put an effect id or its parameter."*
The same function's `portamento_or_slide` row states *"the only per-frame change to AUDF is a new note
event"* — which is precisely what C1 needs to stop being true.

**[verified]** the IR has no rendered pitch-modulation field either: `IRNote` (`ir.py` line 90) carries
`pitch`, `midi_pitch`, `duration`, `volume`, `distortion`, `instrument_id`, `channel_role`, `is_rest`,
`slide_semitones`, `arpeggio_offsets`; the last two, plus `IRMacroStep`/`IRInstrument.macro`,
`vibrato_depth` and `vibrato_speed`, are **reserved and deliberately not rendered** —
`_render_note_to_frames` says so at lines 459–462, because rendering them would make the WAV preview
diverge from what the player can do.

**[verified] every byte of the format is already allocated**, which is why this cannot be done without a
format change:

* header — `frames_per_tick` (1..255 all used), `audctl_mode` (all 8 bits are AUDCTL bits and are
  written to the hardware), two pointers;
* instrument record — `distortion` (a multiple of `$20`; its low five bits must stay 0 because
  `write_pokey_registers` does `ora ch_dist,x` into AUDC, so the low nibble *is* the volume), and the
  four ADSR numbers;
* event — `audf` (0..`$FE`; `$FF` is the terminator), `duration_ticks`, `volume` (0..15).

The only structural slack is the unused low bits of the distortion byte, and reusing those would be
*silently changing the meaning of an existing field* — forbidden by the brief and, worse, it would
corrupt the volume of every channel whose instrument did not also mask them.

**[verified]** one further latent trap: `ch_mute_mask` is dead code — zeroed in `music_init` and never
written again — but its "mute" branch in `write_pokey_registers` stores the *mask value itself* into
`AUDCn` rather than zero. It must therefore **not** be repurposed as modulation storage without first
fixing that branch. (`report_pokey_audit.md` item 13 records the dead code; the write-the-mask bug
follows from lines 517–523.)

---

## 2. C1 behaviour and register sequence

### 2.1 Where C1 is defined

C1 is not an instrument definition; it is a register-stream transform. Its authoritative record is
`data/instrument_libraries/lead/v0.1/library.json` → `instruments[c1_octave_pulse]`, which pins:

| property | value | symbol |
| :--- | :--- | :--- |
| generator byte | `$40` (poly5-gated poly4) | `pokey_timbre_experiment.py::C_GENERATOR` |
| divider rule | `N` on even frame offsets, `N // 2` on odd | `pokey_octave_pulse_experiment.py::SCHEDULES["C1"].divider_for_frame` |
| schedule | `hold_frames=1`, `active_frames=null`, `active_notes=()` | `PulseSchedule` |
| octave value | `clamp_audf_for_tracker(N // 2)` | `pokey_timbre_experiment.py::octave_divider` |
| nominal divider | `clamp_audf_for_tracker(frequency_to_audf_8bit(f))` | `pokey_timbre_experiment.py::note_divider` |
| application | `apply_c1(stream, song, channel=3)` | `pokey_c1_musical_context_experiment.py::apply_c1` |

**[verified]** every experiment from E26 to E30 uses that same single transform: E27's `c1_stream` calls
E26's `contrast_stream` directly; E28 defines `apply_c1`; E29 and E30 call
`e28.apply_c1(baseline, song, MELODIC_CHANNEL)`
(`pokey_timbre_ab_experiment.py` line 514, `pokey_timbre_library_experiment.py` line 737).

### 2.2 Which registers change, and when

**[verified]** exactly two columns of the 9-column frame stream change, on one channel:

* **`AUDFn`** — alternates between `N` and `N // 2`, once per 50 Hz frame, for every sounding frame of
  every note.
* **`AUDCn`** — its generator nibble becomes `$40`; **the volume nibble is taken from the baseline
  stream unchanged** (`apply_c1` lines 239–245). E26/E27 additionally used a `plucked_volume_shape`;
  E28 deliberately dropped that so the A/B isolated timbre from articulation. The library records this
  under `identity.reproducibility.what_is_not_fixed` — the envelope belongs to the host composition.

`AUDCTL` is **not** touched by the transform **[verified]**: E30 rendered C1 successfully at
`AUDCTL=$10` (composition) and `$00` (solo), and the library records `audctl_source: "composition"`.

**Cadence [verified]:** the alternation advances **once per 50 Hz video frame**, not per musical tick.
`PulseSchedule.divider_for_frame(nominal, upper, offset, note_index)` indexes `offset` by frame, and
E28's `apply_c1` calls it with `offset in range(span["frames"])` where `frames = end_f - start_f` is a
frame count. With `hold_frames=1` the alternation rate is `50 / (2·1) = 25 Hz`
(`PulseSchedule.alternation_hz`).

**Phase reset [verified]:** the schedule is evaluated per note with `offset` restarting at 0, so the
divider is `N` on the note's first frame, `N//2` on its second, `N` on its third, and so on
(`apply_c1` lines 232–245).

**Rests and silence [verified]:** `apply_c1` skips a frame whose baseline volume nibble is already 0
(lines 239–241), so a rest, or a release frame that has faded to 0, keeps the baseline's `AUDF` and
`AUDC`. The transform never introduces a register write the baseline did not make.

### 2.3 Which channel

**[verified]** C1 has no channel of its own. E26/E27 wrote a single voice on channel 1 of a
hand-written stream; E28–E30 applied it to **channel 3 (the lead)** of
`examples/songs/Vaults-of-Nhyrmeth.dsl`, because channel 3 is an 8-bit channel and C1's divider
arithmetic has no 16-bit form. `pokey_c1_musical_context_experiment.py::MELODIC_CHANNEL = 3` and its
docstring state that the 16-bit bass pair (CH1+CH2) is deliberately left alone. The library records
`rendering.channel: 3` with `channel_source: "composition"`.

### 2.4 It is not a clean octave oscillator

**[verified, and worth stating before anything is built on it]**

* `$40` decodes to `Waveform.POLY5_GATED_POLY4` (`pokey_hw.decode_audc`), i.e. poly5 **gates** a
  sample-and-hold of poly4 (`pokey_synth.py` lines 166–172).
* The poly5 index is derived from the same `freq` as the tone (`pokey_synth.py` line 151:
  `poly5_idx = (phase_seq * (31.0 / (2.0 * math.pi))).astype(np.int64) % 31`), so the **gate rate
  follows the divider**. Halving `AUDF` therefore doubles the gate rate as well as the tone: the result
  is a texture change and a pitch change together. E27's `LIMITATIONS` tuple and the library's
  `rendering.waveform_note` both say so.
* **[verified by arithmetic]** the octave value is not exact for every `N`. POKEY's period is `N + 1`
  base clocks and the output is `clock / (2(N+1))`, so the exact octave needs `N' = (N-1)/2`.
  `N // 2` equals `(N-1)/2` exactly when `N` is **odd**; when `N` is **even** the ideal is `k + 0.5` and
  `N // 2` picks `k + 1`, which is flat by `1200·log2(1 + 1/(2k+2))` cents — **11.9 cents at `N = 144`**,
  shrinking to about 6.8 cents at `N = 254` and to nothing as `N` grows. This is a real approximation,
  not a rounding bug, and it is inaudible next to the 25 Hz pulse; it is recorded here so nobody later
  "fixes" it into a disagreement with the experiment.
* **[verified]** the low end degenerates: `N // 2 == 0` for `N ∈ {0, 1}`, which is POKEY's fastest
  divider rather than an octave (E27's `LIMITATIONS`). `note_divider` clamps `N` to
  `pokey_hw.AUDF_TRACKER_MAX = $FE`, and since `$FE // 2 = 127` the upper clamp never binds on the
  octave value.
* **[verified]** `AUDCTL` is one byte for the whole song, written every frame from the header, so the
  clock cannot change inside a note.
* **[verified]** the effect needs several frames per note to exist at all: with `hold_frames=1` a
  one-frame note gets a single divider value. `frames_per_tick` is 5 in the reference song and 4 in the
  E26 score, so notes are tens of frames long; a song with `frames_per_tick = 1` and very short notes
  would make C1 degenerate into a plain `$40` tone. That is a musical constraint, not a technical one.

### 2.5 Verified against assumed

| claim | status |
| :--- | :--- |
| C1 changes `AUDFn` and the `AUDCn` generator nibble, on one channel | **verified** — `apply_c1` |
| the alternation advances once per 50 Hz frame | **verified** — `divider_for_frame`, `alternation_hz` |
| the phase restarts at every note onset | **verified** — `apply_c1` passes a per-note `offset` |
| the nominal divider comes from the note's pitch | **verified** — `note_divider` → `ir.frequency_to_audf_8bit` → `pokey_hw` |
| the octave value is `N // 2`, clamped through the tracker format | **verified** — `octave_divider` |
| the envelope, channel and `AUDCTL` come from the host composition | **verified** — `apply_c1` keeps the baseline volume; library `rendering.*_source` |
| `$40` is poly5-gated poly4 and its gate rate follows the divider | **verified** — `decode_audc`, `pokey_synth.py` lines 151, 166–172 |
| the octave is approximate for even `N` | **verified by arithmetic** — §2.4 |
| how it sounds on real hardware | **not established here.** E30 is one listener, one composition, one session; the library marks its musical claims `hypothesis` |
| the CPU cost on hardware | **not measured.** §3.6 is hand-computed, not emulated |

---

## 3. Player timing and data structures

### 3.1 How often the update routine runs

**[verified]** `music_update` is meant to be called once per 50 Hz VBLANK and does everything once per
call: tick counting, note fetching, envelopes, and the register write. There is no inner loop and no
other rate. So:

* **the register write rate is 50 Hz**, and that is the granularity ceiling for any modulation — the
  fastest possible divider alternation is one frame per value, i.e. 25 Hz (E27's `LIMITATIONS`);
* a modulation hook placed inside `music_update` runs at exactly the same rate as the note logic, so it
  cannot be "too fast" or "too slow" relative to it.

### 3.2 Note duration and multi-frame notes

**[verified]** `ch_dur,x` counts **row advances**, not frames. A note with `duration = D` ticks occupies
exactly `D × frames_per_tick` frames: `fetch_channel_note` stores `ch_dur = D`, and the row-advance
block decrements it once per row and re-fetches when it reaches 0. `_render_note_to_frames` uses the same
`dur_rows * frames_per_tick` span **[verified]**, so the WAV and the XEX agree on where a note starts and
ends.

**Consequence [verified]:** a per-frame modulation must therefore count **frames**, not rows. In the
player that means toggling once per `music_update` call (which is per frame), and resetting the phase at
the same moment `fetch_channel_note` starts a new note.

### 3.3 Writing AUDF cannot disturb note timing

**[verified]** the row/tick machinery (`tick_counter`, `tempo_divider`, `ch_dur`) never reads `ch_audf`,
and `ch_audf` is only consumed by `write_pokey_registers` and by the rest test at note-fetch time. The
rest test runs *before* the modulation in the same frame (row advance → envelopes → modulation →
register write), so a modulated `ch_audf` can never be mistaken for a rest.

The one edge case **[verified]:** `N ∈ {0,1}` gives `N // 2 == 0`, so a note at `AUDF 1` would write
`AUDF 0` on alternate frames. `AUDF 0` is POKEY's fastest divider, not a rest, and the note's own AUDF
byte is still `1`, so the rest test (which reads `ch_audf` immediately after the fetch) sees `1`. No
malfunction — just the documented low-end degeneration of §2.4.

### 3.4 Per-channel state and independence

**[verified]** every piece of per-channel state is a 4-byte array indexed by `X` and iterated `cpx #4`:
`ch_audf`, `ch_dur`, `ch_peak_vol`, `ch_cur_vol`, `ch_env_phase`, `ch_env_frame`, `ch_dist`, `ch_att`,
`ch_dec`, `ch_sus`, `ch_rel`, `ch_mute_mask`. A modulation follows that pattern exactly, so **channel
independence is structural** — one channel pulsing cannot affect another, and the four channels' phases
are separate by construction.

The only shared thing is the loop bound, and (if the design adds one) a single "is anything modulated?"
byte used purely as a fast-path test.

### 3.5 Interaction with the rest of the hardware behaviour

| feature | interaction | verdict |
| :--- | :--- | :--- |
| **16-bit bass (CH1+CH2 joined, AUDCTL bit 4)** | `write_pokey_registers`'s `@write_16bit` branch treats `ch_audf+0` as the divider *low byte* and `ch_audf+1` as the *high byte*. `lsr`-ing either one alone corrupts the 16-bit divider. | **[verified]** modulation must be **refused on a channel that is part of a joined pair**. C1 as implemented never targets one (E28's `MELODIC_CHANNEL = 3`; the reference song joins 1+2). |
| **16-bit pair CH3+CH4 (AUDCTL bit 3)** | No write path exists in the player at all (`stage15.player_capabilities`'s `sixteen_bit_pair_3_4` row). | **[verified]** not a concern. |
| **percussion** | `_render_note_to_frames` gives an unpitched hit `PERCUSSION_DEFAULT_AUDF` on channel 4 and the instrument's own distortion. The player sees an ordinary note. | **[verified]** a modulation on channel 4 would pulse a percussion hit's divider — legal at register level, musically nonsensical. C1's own record says channel 3. |
| **`AUDCTL` changes** | The player writes `audctl_mode` from the header every frame and never recomputes it. A modulation does not touch it. | **[verified]** no interaction. |
| **envelope / volume** | `update_envelopes` computes `ch_cur_vol`; `write_pokey_registers` does `ora ch_dist,x`. A modulation that touches only `ch_audf` cannot alter the volume. | **[verified]** no interaction. |
| **the C1 generator `$40`** | Already supported: `IRInstrument.distortion` → the instrument table's first byte → `ch_dist,x` → `ora` into AUDC. A song with `dist=$40` on a channel **already exports and plays today**. | **[verified]** — *not* part of the gap. |
| **the envelope** | Already supported: four bytes per channel, rebuilt at run time by the 4-phase state machine. | **[verified]** — *not* part of the gap. |
| **`ch_mute_mask`** | Dead code whose "mute" branch writes the mask value into AUDC rather than 0. | **[verified]** must not be reused as modulation storage without fixing that branch (§1.5). |

### 3.6 CPU budget

**[estimate]** the PAL CPU clock is `PAL_CLOCK_HZ = 1773447.0` (`constants.py`), so one 50 Hz frame is
nominally `1 773 447 / 50 ≈ 35 469` CPU cycles, **before ANTIC DMA steals any**. The figure is derived
from the clock, not measured, and the real available budget is lower.

Hand-computed costs for the recommended routine (§5), using standard 6502 timings (`lda abs` 4,
`sta abs` 4, `sta abs,X` 5, `lda abs,X` 4, `jsr` 6, `rts` 6, `beq`/`bne` 2 plus 1 if taken, `inx` 2,
`cpx #` 2, `eor #` 2, `lsr` 2, `lda #` 2, `ldx #` 2, `jmp` 3):

| case | cycles/frame | % of the nominal budget |
| :--- | ---: | ---: |
| nothing modulated (fast path: `jsr`, `lda any_mod`, `beq`, `rts`) | **18** | 0.05 % |
| one channel modulated, three checked and skipped | **≈ 98** | 0.28 % |
| all four channels modulated | **≈ 166** | 0.47 % |

**Conclusion [estimate]:** the modulation is not a CPU risk. It costs at most about half a percent of a
frame, it runs in the same call as the existing envelope loop, and it adds no loop that scales with song
length. A timing-stability risk would come from a *longer* per-frame routine, which is one of the
reasons §5 rejects option C.

**Not established:** whether the routine's cost interacts with ANTIC DMA on a real machine, and whether
there is an audible click at a divider change. Neither can be answered from the source, and this document
does not claim to answer them. The Python model keeps the tone phase continuous across a divider change
(`pokey_synth.py` line 150 accumulates `ch_phases[ch]`), so the *model* has no discontinuity, but the
model is not hardware.

---

## 4. Three strategies, compared

All three are described against the real structures: the 6-byte header, the 4 × 5 instrument table, the
3-byte event, `ch_audf`/`ch_dist`/`ch_cur_vol`, `fetch_channel_note`, `update_envelopes`,
`write_pokey_registers`, `mads_exporter.export_mads_asm`, `ir._render_note_to_frames`.

### 4.1 The comparison

| | **A — dedicated C1 effect** | **B — generic per-note effect** | **C — register-event stream** |
| :--- | :--- | :--- | :--- |
| **where the parameter lives** | one byte per channel in the instrument table | one descriptor byte per *note* (or an effect table + a per-note index) | a separate timeline of timed register writes |
| **note/data format change** | instrument table 4 × 5 → 4 × 6; +1 version byte | event 3 → 4 bytes; +1 version byte; or a new effect table + pointer | new region + a pointer in the header (which has none) |
| **music data cost** | **+5 bytes/song** (measured design; length-independent) | **+399 bytes (+30.7 %)** on the reference song | **≈ 4 400 bytes** raw for C1 on ch3 of the reference song |
| **player change** | +88 bytes measured; one new routine, one `jsr`, a `sta` in the fetch path | +100–115 bytes (A plus a per-note descriptor read, store and test) | substantial: a second cursor and countdown per channel, or a global event queue merged with the row timeline; ~200–400 bytes of code and ~16–24 bytes of state **[estimate]** |
| **exporter change** | emit the version byte and the 4 modulation bytes; refuse a modulation on a joined channel | emit a 4th event byte; decide what an effect id means per note | emit a whole new region and encode deltas; decide what happens when an event and a note land on the same frame |
| **IR change** | one field on `IRInstrument` (`octave_pulse: bool`, or a small enum) | one field on `IRNote` | a new IR container (a register timeline) — the biggest IR change of the three |
| **runtime CPU** | ≤ 166 cycles/frame **[estimate]** | ≈ A + ~20–30 cycles/frame | proportional to the event rate; for C1 that is one event per frame per modulated channel **[estimate]** |
| **complexity** | low: one 44-byte routine, no new pointer, no new structure | medium: every note grows, every fetch path changes | high: two timelines to reconcile, and the note logic must not be re-entered mid-note |
| **backward compatibility** | old note records unchanged; new version byte makes new-player/old-data detectable | old note records become unreadable (the record grows) — a harder break | worst: a new pointer and region, and old data has no place for either |
| **future effects** | good: the byte is an opcode, so a different hold or a different ratio is a new opcode value | best: any per-note effect is expressible | best: any register automation is expressible |
| **WAV/XEX divergence risk** | low — one rule, two implementations, easily cross-checked | medium — the rule must be applied per note in both paths | high — the WAV path would have to build the same event timeline to stay comparable |
| **what it does not buy** | E27's `active_notes` / `active_frames` per-note control | — | — |

### 4.2 Option A in detail

**[proposed]** add a **modulation descriptor byte** to each channel's instrument record and a
`apply_modulation` routine.

* **Format:** instrument record 5 → 6 bytes: `distortion, attack, decay, sustain, release, modulation`.
  `modulation = 0` means "none", which is what every existing song's instruments would carry.
* **Descriptor meaning [proposed]:** `0` = none; `1` = alternate `N` / `N // 2` once per frame
  (`hold_frames = 1`); values `2..15` reserved for a longer hold (`hold_frames = n`) so that E27's C2
  costs no further format change; `$FF` reserved as "refuse". **[proposed]** anything the player does not
  recognise is treated as "none" rather than as an approximation — the exporter is the place that
  refuses, so the player never has to guess.
* **Player:** one new routine (~44 bytes) called from `music_update` between `update_envelopes` and
  `write_pokey_registers`; `fetch_channel_note` stores the nominal divider in a new `ch_audf_base` array
  and resets the phase; `music_init` ORs the four descriptor bytes into a single `any_mod` fast-path byte.
* **Why per-channel and not per-note:** the library's C1 record is per-channel
  (`active_notes = ()`, `active_frames = null`), the instrument table is already per-channel and loaded
  once at init, and per-note control costs 80× more data for something no composition in E28–E30 used.
* **What it gives up:** E27's C3 ("pulse for the first 8 frames") and C4 ("pulse on notes 0 and 2") would
  **not** be expressible. They were never evaluated inside a composition, and neither is C1.

### 4.3 Option B in detail

**[proposed]** a per-note descriptor. The natural encoding is a 4th event byte, `effect_id:effect_param`
(nibble each), read by `fetch_channel_note` into a per-channel `ch_effect` byte.

* **Cost [verified by measurement]:** the exporter writes **399** note records for the reference song, so
  +1 byte per record = **+399 bytes**, a **30.7 %** growth of the 1299-byte music data.
* **Where it wins:** per-note control. A song could pulse only the long notes, or only the first bar.
* **Where it loses:** it pays 399 bytes for a behaviour the library says is constant per channel, it
  changes every existing note record (so old data cannot be read at all), and it puts a second
  interpretation of "what an effect id means" into both the exporter and the renderer.
* **Verdict:** this is the *most flexible* of the three, which is exactly why the brief says not to
  prefer it. Nothing in E26–E30 or in the library needs per-note control.

### 4.4 Option C in detail

**[proposed]** an explicit timeline of timed register writes, e.g. per channel a list of
`(frame_delta, audf)` pairs, or globally `(frame_delta, channel, register, value)`.

* **Cost for C1 [estimate, from a measured count]:** channel 3 of the reference song has **2220 sounding
  frames** and 70 sounding notes. With `hold_frames = 1` every one of those frames changes the divider,
  so a plain `(delta, value)` stream is `2220 × 2 = 4 400` bytes — **more than three times the whole
  1299-byte song**, for one channel of one effect. A run-length or pattern encoding would compress this
  to roughly `70 × 2 ≈ 140` bytes (one run per note), but only by giving the stream a repeat/pattern
  opcode, at which point it is no longer a general event stream — it is a modulation codec, i.e. option A
  with extra machinery.
* **Player:** the note logic already consumes one pointer per channel and one countdown (`ch_dur`). An
  event timeline needs a second pointer and a second countdown per channel, plus a merge rule for frames
  where a note fetch and an event coincide. That is +8 bytes of pointer state and +4–8 bytes of countdown
  state, and it makes `music_update` re-entrant in a way the current code is not.
* **Where it wins:** any register automation at all — a volume sweep, a distortion change mid-note, an
  `AUDCTL` change. `stage15.player_capabilities` lists `generator_change_inside_song`,
  `audctl_change_mid_song` and `per_frame_volume_macro` as unsupported; C is the only strategy that
  would reach them.
* **Where it loses:** it is the largest change to the most delicate part of the player, it costs the most
  data for the effect actually wanted, and it makes WAV/XEX agreement harder because the WAV path would
  have to build the same timeline from the same source to stay comparable.
* **Verdict:** correct in general, wrong for this need. Building it now would be building for a
  requirement nobody has stated.

### 4.5 What the numbers decide

**[verified by measurement]** C1 is a **per-channel, whole-note, fixed-rate** behaviour. Against that:

* A costs **+5 bytes of data**; B costs **+399**; C costs **≈ 4 400** (or ≈ 140 plus a private codec).
* A costs **+88 bytes of player**; B adds ~15 % to that; C is 2–4× A.
* Only B and C buy per-note or arbitrary control, and neither the library nor E28–E30 asks for it.

The recommended option is **A** (§5). If per-note control is ever wanted, the versioned format (§6) leaves
room for a version 2 that adds a per-note parameter byte — a change that would then be *justified by a
requirement*, not by a hunch.

---

## 5. Recommended approach

**[proposed] Option A: a per-channel modulation descriptor byte, with a format version.**

### 5.1 Shape of the change

1. **Music data** — emit one **format version byte** immediately before the instrument table, then the
   instrument table with **6 bytes per channel** (5 existing + `modulation`).
2. **`player.asm`** — read the version in `music_init` and refuse anything that is not `1`; read the
   6th byte into a new `ch_mod` array; OR the four bytes into `any_mod`; store the note's nominal divider
   in a new `ch_audf_base` array and reset the phase in `fetch_channel_note`; call a new
   `apply_modulation` from `music_update` before `write_pokey_registers`.
3. **`mads_exporter.py`** — write the version byte and the descriptor; **refuse** a song that asks for a
   modulation on a channel that is part of a joined 16-bit pair, with a stable code.
4. **`ir.py`** — one new field on `IRInstrument`; `_render_note_to_frames` applies the same rule the
   player does, using a **shared helper** (§8).
5. **Nothing in the note stream changes.**

### 5.2 Why this and not the alternatives

* It is the only option whose data cost is **independent of song length** (+5 bytes), and C1's cost is
  paid once per channel rather than once per note.
* It reuses the structure the player already has: a per-channel constant loaded once at init, and a
  per-frame write of `ch_audf` that already happens.
* It keeps the note record — and therefore every existing song's note records — valid.
* It leaves a documented path to a version 2 for per-note control, without paying for it now.
* The two larger options are larger *in the parts of the system that are hardest to verify* (the note
  fetch path and the player's frame loop), and neither addresses a stated requirement.

### 5.3 The routine, in outline

**[proposed]** — illustrative, not final; the measured cost in §7 is for this shape.

```
; called from music_update, after update_envelopes, before write_pokey_registers
.proc apply_modulation
    lda any_mod                 ; 0 when no channel asked for a modulation
    beq @done                   ; the whole feature costs 18 cycles on an ordinary song
    ldx #0
@loop:
    lda ch_mod,x
    beq @next_channel
    lda ch_mod_phase,x
    eor #1
    sta ch_mod_phase,x
    bne @upper
    lda ch_audf_base,x          ; phase 0 -> the nominal divider
    sta ch_audf,x
    jmp @next_channel
@upper:
    lda ch_audf_base,x          ; phase 1 -> N // 2, exactly as Python's N // 2
    lsr
    sta ch_audf,x
@next_channel:
    inx
    cpx #4
    bne @loop
@done:
    rts
.endp
```

**[verified]** `lsr` on an 8-bit value is `N // 2` for every `N` in `0..255`, which is exactly what
`pokey_timbre_experiment.octave_divider` computes. There is no rounding question between the 6502 and
Python.

`fetch_channel_note` gains two things at `@got_note`/`@setup_envelope`:

```
    sta ch_audf,x               ; existing
    sta ch_audf_base,x          ; NEW: keep N for the modulation
    ...
    lda #1
    sta ch_mod_phase,x          ; NEW: a note always starts on its nominal divider
```

Phase starts at `1` and is toggled *before* being tested, so the note's first frame writes `N`, its
second `N // 2`, its third `N` — the same order as `apply_c1`'s `offset % 2 == 0`.

---

## 6. Data-format change and compatibility

### 6.1 The change

```
song_data:
    .byte <frames_per_tick>          ; header, unchanged (6 bytes total)
    .byte <audctl_mode>
    .word song_data_instruments
    .word song_data_sequence

song_data_instruments:
    .byte 1                          ; NEW: format version
    .byte <dist>,<att>,<dec>,<sus>,<rel>,<modulation>   ; NEW: 6 bytes per channel, 4 channels
    ...

song_data_sequence:                  ; unchanged
    ...
```

* **+1 byte** for the version, **+4 bytes** for the four descriptors → **+5 bytes per song**, no matter how
  long the song is.
* The header layout, the sequence table, the pattern track lists and **every note record are unchanged**.

### 6.2 Why the version byte sits where it does

**[verified]** the version byte is placed at what is currently the first instrument byte (header offset 6,
because the instrument table immediately follows the header). For any song the current exporter produces,
that byte is channel 1's `distortion`, and `_find_channel_instrument` guarantees it is one of
`$00, $20, $40, $60, $80, $A0, $C0, $E0` — including its last-resort fallback, which uses
`DISTORTION_PURE_TONE` (`$A0`) **[verified]**. The three-tier validator rejects any other distortion value
**[verified]**.

So version `1` is a value that **no currently produced song can have there**, and the new player can
detect old data and refuse it instead of playing garbage.

**Residual hole, stated rather than hidden [verified]:** `export_mads_asm` can be called on a hand-written
`IRSong` (e.g. `export-mads` reading an IR JSON) without validation, and `IRInstrument.distortion` is an
unconstrained `int`. A hand-built IR whose channel-1 distortion is exactly `1` would be misread as
version 1. The fix is one line in the exporter (refuse a distortion that is not a multiple of `$20`, or
mask it) and it belongs in the implementation, not in this document.

### 6.3 What each direction of the mismatch does

| player | data | result |
| :--- | :--- | :--- |
| **new** | new | correct |
| **new** | old | the version byte is a distortion value ≠ 1 → **refused**, POKEY silenced, `music_playing` stays 0. Loud and detectable. |
| **old** | new | the old player reads the version byte as channel 1's distortion and everything after shifts by one byte → **wrong, and the old player cannot detect it**. |
| **old** | old | correct, and **byte-for-byte the current behaviour**. |

**[verified]** the "old player / new data" row is unavoidable: the old player has no version check and the
table it reads has grown. It is mitigated by the fact that `build-xex` regenerates the song ASM and
includes `player.asm` in the same MADS run (`ai/client.py` lines 587–592 and 1095–1102), so the two are
always built together by the tool. It must be documented for the `export-mads`-then-assemble-by-hand
workflow that `mads_exporter.py`'s docstring describes.

### 6.4 Backward compatibility, item by item

| requirement | how it is met |
| :--- | :--- |
| existing songs keep their current playback | **[verified]** a song with no modulation has `modulation = 0` on every channel, so `any_mod = 0` and `apply_modulation` returns after 18 cycles without touching `ch_audf`. `write_pokey_registers` then writes exactly what it writes today. |
| existing note records remain valid | **[verified]** the event is still `audf, duration_ticks, volume`; nothing about it changes. |
| the feature is opt-in | **[proposed]** `modulation = 0` is the default in the IR and the exporter; the descriptor is only non-zero when an instrument explicitly asks for it. |
| unmodulated notes incur no processing | **[proposed]** `any_mod` is a per-song OR computed once in `music_init`; when it is 0 the entire feature is one `lda`/`beq`. There is no per-note cost at all, modulated or not. |
| XEX memory layout and entry points stay valid | **[verified]** `music_init`/`music_play`/`music_stop`/`music_update`/`music_is_playing` keep their names and their relative placement under the `org` the harness emits; the player grows by 88 bytes at `$6000` (880 → 968), still far below the music segment at `$8000`. Zero-page usage is unchanged (10 bytes). |
| other channels keep playing | **[verified]** per-channel state is a 4-byte array indexed by `X`; a modulated channel writes only its own `ch_audf` entry. |
| no existing field's meaning changes | **[proposed]** the modulation is a **new** byte in a **new** table layout announced by a **new** version byte. Nothing is overloaded. This is exactly why the "reuse the distortion byte's unused low nibble" idea was rejected. |

---

## 7. Estimated memory and CPU costs

### 7.1 Player

**[verified by measurement — appendix A]** assembling the current `player.asm` and a scratch copy carrying
the §5 changes, both at `org $6000`:

| | baseline | with option A | delta |
| :--- | ---: | ---: | ---: |
| total payload | 880 | **968** | **+88** |
| code | 821 | 896 | +75 |
| state/data | 59 | 72 | +13 |
| zero page | 10 | 10 | 0 |

Breakdown of the +88 **[verified by label-address diff]**:

| piece | bytes |
| :--- | ---: |
| `apply_modulation` (the whole new routine) | **44** |
| `music_init` (read the descriptor, OR into `any_mod`, seed the phase) | 17 |
| `fetch_channel_note` (`ch_audf_base` store, `ch_audf_base` zero on early end, phase reset) | 11 |
| `music_update` (`jsr apply_modulation`) | 3 |
| new state: `ch_mod` (4), `ch_mod_phase` (4), `ch_audf_base` (4), `any_mod` (1) | **13** |

**[estimate]** a tighter encoding of the state — one `ch_mod_bits` byte plus a 4-byte mask table — would
come to the same 13 bytes, so 13 is a fair figure rather than a conservative one. The routine could be a
few bytes smaller by reordering branches; 44 is the measured shape, not the minimum.

### 7.2 Music data

**[verified by measurement]** `examples/songs/Vaults-of-Nhyrmeth.dsl`, the project's own reference song:

| | bytes |
| :--- | ---: |
| header | 6 |
| instruments (4 × 5) | 20 |
| sequence (7 steps + terminator) | 16 |
| pattern track lists (5 patterns × 4 channels) | 40 |
| track events (399 records + 20 terminators) | 1217 |
| **total today** | **1299** |
| **with option A** (+1 version, +4 descriptors) | **1304** (**+0.38 %**) |
| **with option B** (+1 per note record) | 1698 (**+30.7 %**) |
| **with option C** (raw event stream for C1 on ch3) | ≈ 5699 (**+339 %**) |

The descriptor cost does **not** grow with song length; the per-note cost does. For a song twice as long,
A still costs +5 bytes and B costs roughly +800.

### 7.3 CPU

See §3.6: **18 cycles/frame** when nothing is modulated, **≈ 98** with one channel modulated,
**≈ 166** with all four — against a nominal ~35 469 cycles/frame. All figures are **[estimate]**,
hand-computed from 6502 instruction timings.

### 7.4 What is not estimated

* No emulator was run and no cycle count was measured on hardware.
* The audio consequence of a per-frame divider change (a click, a beat, anything) is **not** estimated
  here and must not be claimed without listening on hardware.
* The size of the harness around the player is not part of these figures. The built XEXs already in
  `experiments/` are 1019–2032 bytes; the music data is the part that changes.

---

## 8. WAV/XEX consistency plan

### 8.1 The structural risk, stated first

**[verified]** the two output paths implement "note → POKEY registers" **twice**:

* `ir.py::_render_note_to_frames` writes AUDF and AUDC per frame for the WAV preview;
* `mads_exporter.py::export_mads_asm` re-iterates `IRNote` and writes a 3-byte event per note.

`report_pokey_audit.md` already recommends making the exporter consume
`compile_ir_to_pokey_frames`' output instead of re-deriving it, precisely to eliminate this class of
divergence. That refactor is **out of scope here** and should not be smuggled in.

For C1 the risk is smaller than it looks, for one reason: **the exporter would not implement the
alternation at all.** It would publish a flag; the alternation lives in exactly two places, one line
each — `_render_note_to_frames` for the WAV and `apply_modulation` for the 6502 — and those two must be
shown to agree (§9).

### 8.2 Where each piece goes

| layer | what it holds | why there |
| :--- | :--- | :--- |
| **IR** | one new field on `IRInstrument` **[proposed]**, e.g. `modulation: int = 0` (0 = none, 1 = octave pulse every frame, 2..15 reserved for a longer hold). Not on `IRNote`. | The instrument table is per **channel**, and `mads_exporter._find_channel_instrument` already reduces a song to exactly one instrument per channel. Putting it on the note would force a per-note encoding the player does not need (§4). |
| **shared definition** | one helper that maps `(nominal, frame_offset) -> divider` **[proposed]**, in `pokey_hw` next to `clamp_audf_for_tracker`/`audf_from_hz_8bit`, so there is one statement of the rule in Python. | `_render_note_to_frames` already routes its nominal divider through `pokey_hw`, and `note_divider` in E26 does the same. The octave rule is currently only in `pokey_timbre_experiment.octave_divider`, which is an experiment module — the production paths must not import an experiment. |
| **WAV renderer** | `_render_note_to_frames` writes `nominal` on even frame offsets and `nominal // 2` on odd, per note, from the note's own instrument's descriptor. | It already writes AUDF per frame; only the value changes. |
| **MADS exporter** | writes the version byte and the descriptor byte; **does not** write anything per frame. | Its output is a note table, and the modulation is a per-channel constant, so no note data changes. |
| **6502 player** | `apply_modulation` alternates `ch_audf` per frame, phase reset per note. | It already writes `ch_audf` to AUDFn every frame. |

### 8.3 Why the two interpretations cannot drift

**[verified]** the two implementations of the rule are:

* Python: `nominal if (offset % 2 == 0) else nominal // 2`
* 6502: `lsr` on the 8-bit `nominal`, with a phase toggled once per frame and reset at each note onset

**[verified by arithmetic]** `lsr` is `// 2` for every value in `0..255`, so the *value* rule is identical
by construction, not by convention. The remaining risk is the *phase* rule — where the alternation
restarts — and that is a single, testable claim: "the note's first frame carries `N`".

Three things keep it honest:

1. **The nominal divider is already shared.** Both paths compute it through
   `pokey_hw.clamp_audf_for_tracker(ir.frequency_to_audf_8bit(...))`, so they cannot disagree about `N`
   **[verified]**. C1's `note_divider` does exactly this.
2. **The octave rule gets one Python definition** (§8.2), used by the renderer, so the WAV side has no
   second statement of it.
3. **A register-trace test** (§9) compares the WAV frame stream against an *independently written*
   expectation of the divider per frame — the pattern `pokey_octave_pulse_experiment.expected_dividers`
   already uses, which exists precisely so tests check the stream against the declared parameters rather
   than against the code that produced it.

### 8.4 What would make the drift visible

**[proposed]** the exporter should refuse anything it cannot encode, in the style the repository already
uses for `volume_contour`:

* a modulation on a channel that is part of a joined 16-bit pair → refuse, because `lsr` on one byte of a
  16-bit divider is not the effect (§3.5);
* a modulation descriptor the exporter does not recognise → refuse, rather than emit a value the player
  would silently ignore;
* and the existing `VolumeContourNotExpressibleError` behaviour stays exactly as it is.

**[verified]** this matches the precedent set by `mads_exporter.find_volume_contour_instruments` /
`VolumeContourNotExpressibleError`: *"Refusing is the only honest option; there is no lossy fallback."*
The same standard should apply here.

---

## 9. Validation plan

Nothing in this section was executed. It is a plan for the implementation, not a report.

### 9.1 Statically checkable (no emulator, no hardware)

These run in the existing pytest suite and in the existing static-analysis helpers.

**Data format**

1. **Legacy song, no modulation.** Export `Vaults-of-Nhyrmeth` and assert the emitted bytes are exactly
   the previous 1299 plus the 5 new ones, that the version byte is `1`, and that all four descriptors are
   `0`. Strongest form: keep a byte-for-byte golden of the *old* export and assert that stripping the 5 new
   bytes reproduces it.
2. **Opt-in.** A song with no modulation must not carry a non-zero descriptor anywhere, and the exporter
   must not require any new input.
3. **Refusals.** A modulation on a joined 16-bit pair, and an unrecognised descriptor, must raise a stable
   code and leave no output file — the pattern `test_instrument_selection_cli.py` already uses for
   `INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX`.
4. **The version byte's safety argument (§6.2).** For every composition fixture in the repository, assert
   that the byte at the version position of the *old* exporter's output is a multiple of `$20` and is not
   `1`. That turns the §6.2 argument into a check rather than a claim.
5. **`stage15.player_capabilities()`** must gain a `per_frame_divider_modulation` row, and the
   `portamento_or_slide` detail ("the only per-frame change to AUDF is a new note event") must be corrected.
   The existing `test_stage15`-family guards that watch `player.asm` must be updated deliberately, not
   silently.
6. **Both player copies.** A test must assert `player.asm` and `src/atari_music/asm/player.asm` are
   byte-identical after the change, since they are today.

**The rule itself**

7. **`AUDF` sequence per frame.** For nominal dividers spanning the useful range, assert the WAV frame
   stream's `AUDFn` column equals an independently written expectation: `N` on even offsets, `N // 2` on
   odd, restarting at each note. This is `expected_dividers`' pattern applied to the production compiler.
8. **A note starts on `N`.** For every sounding note, the frame carrying the note's first row must hold
   `N`, not `N // 2`. This is the phase claim the 6502 and Python must share.
9. **Different durations.** Notes of 1, 2, 3, 5 and 20 rows, at `frames_per_tick` 1, 2, 4 and 5, must all
   produce the right span and the right alternation — in particular the 1-frame and `frames_per_tick = 1`
   degenerate cases (§2.4).
10. **State reset between notes.** Two adjacent notes at the *same* pitch must each start on `N`; two
    adjacent notes at *different* pitches must each start on their own `N`. This is the case a phase that
    simply free-ran would fail.
11. **Multiple notes, one channel.** A phrase of several notes: the alternation must restart at every onset
    and must not accumulate drift.
12. **Channel independence.** Two channels modulated with different nominal dividers must produce
    independent sequences, and a modulated channel must not change any other channel's column. E28's
    `stream_differences` already reports "exactly which frames and columns differ" and is the right shape.
13. **Interaction with 16-bit bass.** A song with `uses_16bit_bass` must render the CH1+CH2 pair unchanged
    when no modulation is requested; a request to modulate a joined channel must be refused (§3.5).
14. **Interaction with percussion.** A song with an unpitched hit on channel 4 must render that hit's
    `PERCUSSION_DEFAULT_AUDF` unchanged when nothing is modulated.
15. **Boundary dividers.** `N = 0`, `1`, `2`, `3`, `$FE`, and a value `clamp_audf_for_tracker` would clamp,
    must produce `N` and `N // 2` with no out-of-range byte — and the documented degenerate cases must be
    asserted *as documented*, not fixed silently.
16. **WAV/XEX agreement at the data level.** The exporter's descriptor byte and the IR's field must be the
    same value; changing one without the other must fail a test.

**Regression**

17. Every existing song fixture must export and render identically apart from the 5 new bytes — the "no
    output moves when the feature is off" invariant, in the form
    `test_a_legacy_import_dsl_run_is_byte_identical_and_reads_no_library` already established for
    `--instrument`.
18. The whole existing suite must pass with `player.asm` changed only in the ways §5 lists; the existing
    `test_stage15`…`test_stage25` guards that hash or watch `player.asm` must be re-baselined explicitly.

### 9.2 Requires an emulator

19. **The player actually writes the intended `AUDF` sequence.** Assemble a song with C1 on one channel,
    run it in a 6502/POKEY emulator that can log register writes, and compare the captured `AUDFn` write
    sequence, frame by frame, against the WAV path's `AUDFn` column. **This is the only test that proves
    the two implementations agree at runtime**, and it is the one thing this document cannot do.
20. **No timing instability.** Measure the frame period over a long run and confirm `music_update` never
    overruns its frame. The §3.6 estimate predicts no risk; only a measurement settles it.
21. **The version refusal.** Run the new player against old data and confirm it refuses (silent, stopped)
    rather than playing noise.
22. **Zero-page and memory layout.** Confirm the player still fits and that the music segment at `$8000` is
    untouched.

Without an emulator in the toolchain, 19–22 cannot be performed and **the design cannot be called
verified**. Stating that is part of the design.

### 9.3 Requires a human listening test on real hardware

23. **Does it sound like the WAV preview?** The whole point of C1 is a timbre; a register trace proves the
    right bytes were written, not that the result is the artefact E30 evaluated.
24. **Is there a click at the divider change?** The Python model keeps the tone phase continuous
    (`pokey_synth.py` line 150); real hardware behaviour at a mid-note divider change is not modelled and
    cannot be inferred from the source.
25. **Does C1 survive the `$40` gate coupling on real POKEY?** §2.4 says the gate rate doubles with the
    divider; whether that is the same character E30 rated 4/4/1 in a composition is a listening question,
    and E30's own scope note applies: one listener, one composition, one session.

### 9.4 Deliberately not in the plan

* No new experiment, no new WAV/ASM/XEX artefacts committed as evidence, no listening page.
* No re-derivation of C1's musical value — E30 did that, and the library already records it with the right
  caveats.

---

## 10. Open questions and risks

### 10.1 Open questions that need a decision before implementation

| # | question | why it matters |
| :--- | :--- | :--- |
| Q1 | **Which format version, and where exactly?** §6.1 proposes `1` at header offset 6. | The version byte is the one part of the change that is hard to revise later, and it decides what the "old player / new data" failure looks like. |
| Q2 | **Does the player refuse loudly or degrade silently on an unknown version?** §6.3 assumes refuse (silent + stopped). | "Refuse" is the repository's established standard for WAV/XEX divergence, but a 6502 player has no way to *say* why. |
| Q3 | **Is the descriptor a boolean or an opcode?** §5.3 proposes `0`/`1` plus reserved `2..15`. | An opcode costs nothing now and avoids a second format version if E27's C2 is ever wanted. |
| Q4 | **Should the exporter also close the hand-built-IR hole of §6.2** (a distortion that is not a multiple of `$20`)? | It is a pre-existing looseness in `export_mads_asm`, and the version byte's safety argument leans on it. Fixing it changes existing behaviour, so it needs a decision. |
| Q5 | **How does a user select C1 at all?** `docs/instrument_selection_cli.md` currently *refuses* `c1_octave_pulse` with `INSTRUMENT_NOT_APPLICABLE` because it is not a bank profile. | This document designs the *player* side. The *selection* side is a separate, already-specified-but-unapproved question (that document's §11). The two must be decided together or C1 stays unreachable. |
| Q6 | **Is per-note control wanted?** §4 rejects option B on the evidence available. | If a future composition needs "pulse only the long notes", that is a version 2 and a different cost. |
| Q7 | **Should the modulation be gated on non-zero volume?** `apply_c1` skips frames whose volume nibble is 0; the §5.3 routine does not. | A release frame that has faded to 0 would alternate its `AUDF` in the XEX but not in the WAV. Inaudible, but a register trace would differ. Gating costs ~5 more bytes and needs a decision. |

### 10.2 Risks

| # | risk | severity | mitigation |
| :--- | :--- | :--- | :--- |
| R1 | **No emulator was available, so the 6502 routine is unproven.** | **high** | §9.2 items 19–22 are mandatory before the feature is called done. Until then the routine is a design, not a result. |
| R2 | **Two `player.asm` copies can drift.** | high | §9.1 item 6 asserts they stay identical. |
| R3 | **Old player + new data is silently wrong** (§6.3). | medium | Ship player and data together (which `build-xex` does); document it for the `export-mads` workflow; the new player refuses the reverse case. |
| R4 | **The octave is ~12 cents flat for even `N` at the low end** (§2.4). | low | Documented, not "fixed". Changing it would make the XEX disagree with the WAV and with E30's artefact. |
| R5 | **The `$40` gate coupling means the result is not a clean octave** (§2.4). | low | Already recorded in E27's `LIMITATIONS` and in the library. Nothing to fix; something not to forget. |
| R6 | **A modulation on a joined 16-bit channel would corrupt the divider** (§3.5). | medium | Refused by the exporter (§8.4). |
| R7 | **The WAV and XEX paths are two implementations** (§8.1). | medium | One shared Python definition of the rule, one 44-byte 6502 routine, `lsr == //2` by construction, and a register-trace test. The full fix is the exporter/compiler unification the audit report already recommends — a separate change. |
| R8 | **`ch_mute_mask`'s mute branch is broken** (§1.5). | low, but a trap | Do not reuse the array; fix the branch first if it is ever touched. |
| R9 | **The feature has no user-facing selection path yet** (Q5). | medium | Decide Q5 before or with the implementation; otherwise the player work is unreachable. |
| R10 | **A per-frame divider change is a new kind of register activity for this player.** | medium | §9.3 item 24 — the click question — cannot be answered from the source. |

### 10.3 What would make this design impossible rather than merely large

The brief asks for this to be reported rather than worked around. Two candidates were examined and
**neither blocks the design**:

* *"The player has no per-frame hook."* — It has: `music_update` runs per frame and already writes `ch_audf`
  to AUDFn every frame (§1.4).
* *"The note format has no room."* — True of the note record, but the modulation is not per-note. The
  instrument table is the right home, and it can grow behind a version byte (§6).

The real blocker is not architectural but evidential: **there is no emulator in the loop**, so the 6502 half
of the design cannot be verified here (§10.2 R1). That is a limitation of this environment, not of the
architecture — and it is an argument for a *small* change, because a 44-byte routine is easier to verify by
inspection and by trace than a 300-byte event interpreter.

---

## Appendix A — how the numbers in this document were obtained

Everything below was done **outside the repository**, in the system temporary directory. No repository file
was created or modified except this document.

* **Player size.** Assembled `player.asm` with the repository's own `tools/mads/mads.exe` (MADS 1.9.6
  build 89) inside a one-line wrapper (`org $6000` + `icl '<repo>/player.asm'`), and read the XEX header to
  get the payload size: `$6000`–`$636F` = 880 bytes. Used MADS's `-t:<file>` label table to split that into
  code (`$6000`–`$6334` = 821 bytes) and state/data (`MUSIC_PLAYING` = `$6335` … `CH_MUTE_MASK+3` = `$636F`
  = 59 bytes). `stage15.player_capabilities()` independently reports `state_bytes = 59`, which agrees.
* **Option A size.** Copied `player.asm` to the temporary directory, applied the edits listed in §5.3, and
  assembled the copy the same way: 968 bytes, with `apply_modulation` = `$62AC`–`$62D7` = 44 bytes and every
  other label's address delta taken from the two label tables — which is how the +17 / +11 / +3 / +13 split
  in §7.1 was derived.
* **Music data size.** Loaded `examples/songs/Vaults-of-Nhyrmeth.dsl` through
  `ai.client.load_composition_dsl` + `generate_music_from_composition`, ran
  `mads_exporter.export_mads_asm`, and counted every `.byte` and `.word` payload: 1239 + 60 = 1299 bytes.
* **Note-record count.** Counted the records the exporter actually writes (channel 2 mirrors channel 1 in
  16-bit bass mode): 399, i.e. 1197 event bytes + 20 end-of-track markers = 1217.
* **Sounding frames.** `ir.compile_ir_to_pokey_frames(song)` → a `(2280, 9)` stream; counted frames with a
  non-zero volume nibble in each channel's AUDC column: ch3 = 2220.
* **The octave error.** Arithmetic on `clock / (2(N+1))`; no measurement involved.
* **CPU cycles.** Hand-computed from standard 6502 instruction timings; no emulator was run.

**Not measured anywhere in this document:** real-hardware behaviour, emulator behaviour, audio quality, and
the actual cost of the harness around the player.

*(Appendix A describes the measurements taken while **designing**. The implementation added a
`py65` 6502 run, which is recorded in Appendix B §B.6; the statements above remain true of this
appendix.)*

---

## Appendix B — what the prototype actually implements (post-implementation note)

This appendix was added **after** the implementation, so the design above does not silently
contradict the code. Nothing above was rewritten; where the implementation differs from an estimate
or resolves an open question, it is recorded here.

### B.1 Strategy

**Option A, as proposed** — a per-channel modulation descriptor in a versioned instrument table.
No per-note field, no register-event stream, no change to the 3-byte note event.

### B.2 Format, as built

`mads_exporter.SONG_FORMAT_VERSION = 1`. The version byte is emitted immediately before the
instrument table (header offset 6, where ``instruments_ptr`` points), and each instrument record is
six bytes: `distortion, attack, decay, sustain, release, modulation`. The note stream, the sequence
table and the pattern track lists are unchanged.

### B.3 The three decisions §10.1 left open

| # | decision | where |
| :--- | :--- | :--- |
| Q3 | **opcode, not boolean.** `pokey_hw.MODULATION_NONE = 0`, `MODULATION_OCTAVE_PULSE = 1`; anything else is refused by the exporter and ignored by the player. | `pokey_hw`, `mads_exporter.find_unsupported_modulations` |
| Q7 | **the modulation *is* gated on non-zero volume**, following the *verified* C1 behaviour (§2.2) rather than §5.3's sketch: a frame the channel is not sounding keeps the note's nominal divider, exactly as Experiment 28's `apply_c1` does. The phase still advances on those frames. | `ir._render_note_to_frames`, `player.asm::apply_modulation` |
| Q5 | **selection is through `--instrument`**, by reading the library entry's own `identity.source.implementation` block (schedule parameters and generator byte). No profile id or fingerprint is invented for C1. | `cli._modulation_from_library_entry` |

### B.4 Measured against the estimates in §7

| | §7 estimate | measured |
| :--- | ---: | ---: |
| player growth | +88 | **+130** |
| of which `apply_modulation` | 44 | **51** |
| of which `music_init` | 17 | **46** |
| of which `music_play` | 0 | **5** |
| of which `music_update` | 3 | 3 |
| of which `fetch_channel_note` | 11 | 11 |
| of which state | 13 | **14** |
| music data growth | +5 | **+5** |

The estimate did not include the version check, its refusal path, the sticky `format_ok` guard that
makes the refusal survive a later `music_play`, the volume gate of Q7, or the `cmp #1` that keeps an
undefined descriptor from being approximated. Those are the +42.

Assembled payload: **886 → 1016 bytes** (the repository's own `stage15.measure_player_size`
convention; the XEX container reports 880 → 1010).

### B.5 The blocker this design did not foresee, and how it was resolved

**Historical record (unchanged).** At the time this prototype was implemented, the project kept
every AI-composition XEX under **2048 bytes** — a deliberate whole-file constraint, recorded in
`HISTORY.md` (2026-09-28: *"reducing XEX code size to stay strictly within the 2048-byte limit
across all AI composition artifacts"*). The player was roughly half of that budget, and the
tightest example had **16 bytes** of headroom before this change. The smallest implementation of
this design that reproduces C1 is about **+92 bytes** (a leaner `apply_modulation`, no `any_mod`
fast path, a smaller state block), and the version check alone is ~30 of those bytes and is not
optional — so the feature could not fit under a whole-file 2048, and
`tests/test_ai_composition.py::test_end_to_end_example_artifacts_compilation` failed. Measured
after the change: `dungeon_dark` 2065 (+17), `funny_prl` 2124 (+76), `action_fast` 2167 (+119).

**Resolution (2026-10-09): the proxy was removed, not the feature.** The whole-file rule was
always a proxy for the player — the file was only near 2048 because the player is half of it.
The limit now applies to **the assembled player** and is exclusive:

> The assembled player (code + runtime state) must be **strictly smaller than 2048 bytes**. The
> song data and the complete XEX file are **not** bounded by it. No ceiling was put on the file in
> its place.

The limit is stated once, in `stage15.PLAYER_SIZE_LIMIT_BYTES`, enforced by
`stage15.player_size_limit_ok` / `stage15.check_player_size`, published by
`player_size_analysis` (`within_limit`) and by `reports/stage15/player_size_analysis.json`. The
player measures **1016 bytes** against it. The three examples above are accepted, and
`test_end_to_end_example_artifacts_compilation` now passes for the correct reason: their XEX files
exceed 2048 bytes and are valid.

The independent POKEY-IR budget (2048 bytes on the *song data*: `composer_v*.max_size`,
`generator.py`, `control_generator.py`, `batch_experiment.py`) is a **different** constraint with a
different purpose and was left untouched. See `HISTORY.md` (2026-10-09) for the full audit.

### B.6 Runtime validation actually performed

`tests/test_c1_modulation.py` builds a real XEX with MADS, loads it into the `py65` 6502 emulator
already present in the environment, and executes `music_update` frame by frame, capturing every
`sta $D200..$D207`. The captured `AUDF1` sequence is **identical, frame for frame, to the WAV frame
stream** `compile_ir_to_pokey_frames` produces for the same song — and the same holds for `AUDC1`,
for the other three channels, and for an unmodulated control. A patched format version of 0, 2,
`$A0`, `$C0` or `$FF` produces **no register writes at all**, which is the refusal working.

**py65 emulates the CPU, not POKEY.** This establishes the register writes; it says nothing about
the audio. Listening on an emulator or real hardware is still required, and is not claimed here.


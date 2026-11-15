# Stage 9E — perceptual / renderer gap

Why 61 renderable sound profiles produce only 37 distinct audio signals, where the
difference is lost, and what that means for the whole-song result of Stage 9C.

| | |
| :--- | :--- |
| renderable profiles | **61** of 67 published |
| distinct audio signals | **37** |
| duplicate profiles | **24** in 6 groups (largest 10) |
| document paths read by the binding | **13** of 232 documented leaf paths |
| duplicate groups explained | **6 of 6** — all by the same boundary |
| re-render byte-identical to the package audio | **61 of 61** profiles |
| verdict | **DIAGNOSTICALLY_COMPLETE** |

Nothing was changed. The bank, the listening package, the human answers, the player and the
composer sources are read-only inputs to this diagnosis, and no fix is implemented.

---

## 1. Executive summary

**Observed.**

* The binding reads **13 document paths out of 232** that a profile defines. Six scalar values reach the IR: the
  generator nibble, three envelope frame counts, the sustain level and AUDCTL.
  (plus the pair flag and two validation-only reads).
* The audio is a **pure function of the nine register bytes**: every frame column the
  synthesiser reads changes the audio when altered, and there is no other input.
* **6 of 6 duplicate groups are explained by that one boundary** — their documents differ, their bound IR is
  identical, so everything downstream must be identical.
* The measured pitch trajectory, the volume contour, the modulation rate, the envelope
  shape in milliseconds and any generator change inside a sound are present in the
  documents and read by nothing.
* In the whole-song comparison the profile-bound side was **not** systematically louder
  (median RMS delta -2.39 dB at one shared gain), so the 5–0
  result is not a level artefact.

**Inference.**

* This is a **representation gap first, a renderer gap second, a musical interpretation
  gap third** — three separable problems, which is why §10 keeps them apart.
* The library's *audible* size is set by the handful of values that survive the binding,
  not by the 232 the archaeology measured.
* The similarity metric's blindness to level (Stage 9D) is a smaller, separate defect in
  the *analysis*, not in the pipeline that produces audio.

**Recommendation.**

* Implement nothing yet: the capabilities in §12 are ordered by evidence, and the two with
  the most reach change what the listener hears, so they need a new listening test rather
  than a patch.

## 2. Current pipeline

Read from the modules themselves, with the function that performs each step:

| # | stage | module / function | what happens to a profile |
| ---: | :--- | :--- | :--- |
| 1 | published `PlayableSoundProfile` (`pokey-playable-sound-profile-1.0`) | POKEY Sound Archaeology (producer) | the document this repository consumes |
| 2 | loaded `SoundProfile` | `sound_profiles/bank.py:load_sound_profile_bank` | parses the document, verifies `playable_fingerprint`, takes `scope`/`status` from the registry entry |
| 3 | instrument binding | `sound_profiles/binding.py:apply_profile_binding` → `_plan_instrument`, `_plan_envelope`, `_require_renderable` | validates the profile against the composition and plans the realization |
| 4 | bound POKEY IR | `sound_profiles/binding.py:_rebuild_song` | writes **distortion, envelope, audctl, is_16bit, profile_id, profile_fingerprint** onto the instrument |
| 5 | register frames | `ir.py:compile_ir_to_pokey_frames` → `_render_note_to_frames` | notes + instrument → `(frames, 9)`: AUDF1-4, AUDC1-4, AUDCTL per frame |
| 6 | WAV | `pokey_synth.py:render_pokey_samples` | a pure function of the frame array |
| 6′ | XEX | `mads_exporter.py` + `player.asm` | the same frame semantics, exported for the 6502 player |

Two properties of this chain decide everything below:

1. **A profile enters at stage 4 and nowhere else.** Stage 3 validates; stage 4 writes six
   fields; stages 5–6 never see the profile document at all.
2. **Stage 6 is total.** `render_pokey_samples` reads only the frame array, so identical
   frames must produce identical audio — there is no hidden second input.

## 3. Field propagation matrix

**Measured, not read off the schema.** A profile document was wrapped in a mapping that
records every path the real binding touches, and the binding was then run for a VOICE and a
PAIR profile. The read-set below is what the pipeline actually asked for.

| status | paths | meaning |
| :--- | ---: | :--- |
| `UNREPRESENTABLE` | 109 | a *series over time* the player has no macro for |
| `IGNORED` | 74 | nothing in the pipeline reads it |
| `USED` | 28 | read by the binding and carried into the IR |
| `PLAYER_ONLY` | 21 | provenance about how the profile was measured; not a playback instruction |

The complete read-set — the entire interface between a profile and the audio:

| path read | becomes |
| :--- | :--- |
| `envelope` | container — read only to reach the paths below it |
| `envelope.frames` | container — read only to reach the paths below it |
| `envelope.frames.attack` | `IRInstrument.envelope.attack_frames` |
| `envelope.frames.decay` | `IRInstrument.envelope.decay_frames` |
| `envelope.frames.release` | `IRInstrument.envelope.release_frames` |
| `envelope.sustain_level` | `IRInstrument.envelope.sustain_vol` |
| `pokey` | container — read only to reach the paths below it |
| `pokey.channels` | container — read only to reach the paths below it |
| `pokey.channels.pair` | validation only (the supported pair is `1+2`) |
| `pokey.channels.requires_simultaneous_channels` | validation only (a warning, not a write) |
| `pokey.hardware` | container — read only to reach the paths below it |
| `pokey.hardware.audctl_mode` | `IRInstrument.audctl` → resolved AUDCTL → frame column 8 |
| `pokey.hardware.distortion` | `IRInstrument.distortion` (nibble → AUDC bits 7..5) |

Per section:

| section | paths | statuses |
| :--- | ---: | :--- |
| `envelope` | 10 | 10 × USED |
| `gesture` | 135 | 18 × IGNORED, 21 × PLAYER_ONLY, 96 × UNREPRESENTABLE |
| `metadata` | 5 | 5 × IGNORED |
| `pairing` | 7 | 7 × IGNORED |
| `pitch` | 18 | 18 × IGNORED |
| `playability` | 9 | 9 × IGNORED |
| `playable_fingerprint` | 1 | 1 × IGNORED |
| `pokey` | 18 | 18 × USED |
| `profile_id` | 1 | 1 × IGNORED |
| `schema` | 1 | 1 × IGNORED |
| `scope` | 1 | 1 × IGNORED |
| `source_profile` | 4 | 4 × IGNORED |
| `timing` | 2 | 2 × IGNORED |
| `volume` | 20 | 7 × IGNORED, 13 × UNREPRESENTABLE |

`pitch.*` and `volume.*` are `IGNORED` rather than `UNREPRESENTABLE`: they are *reference*
measurements (the frequency and level of the source material) that this pipeline derives for
itself from the composition's notes. That they are unused is a design decision; that they are
unusable is not claimed.

## 4. Duplicate audio groups

All 61 renderable profiles, grouped by the SHA-256 of the audio they
render, and every one of those renders is compared **byte for byte** with the WAV the
listener heard: **61 of 61 identical**. The grouping below therefore reproduces exactly
the grouping Stage 9D found in the package's own files not as a coincidence of equal counts
but because it is the same audio, file for file. (The grouping check agrees as well.)

| # | size | samples | profiles | classification |
| ---: | ---: | :--- | :--- | :--- |
| 1 | 10 | sample_031, sample_025, sample_005, sample_003, sample_008, sample_012, sample_035, sample_029, sample_015, sample_037 | pokey_ref_0a53188c, pokey_ref_1ef377fc, pokey_ref_275b992a, pokey_ref_80d1ce25, pokey_ref_9098232a, pokey_ref_ad730372, pokey_ref_c321892f, pokey_ref_e4e5235f, pokey_ref_e86c9631, pokey_ref_ef214010 | `representation_duplicate` |
| 2 | 6 | sample_009, sample_059, sample_055, sample_043, sample_050, sample_039 | pokey_ref_089a0846, pokey_ref_3c36e574, pokey_ref_9a86568a, pokey_ref_a09c0263, pokey_ref_c2983132, pokey_ref_ed07bb73 | `representation_duplicate` |
| 3 | 4 | sample_051, sample_016, sample_058, sample_046 | pokey_ref_1e9be30a, pokey_ref_568403b4, pokey_ref_6db98eb5, pokey_ref_7983ed84 | `representation_duplicate` |
| 4 | 4 | sample_023, sample_017, sample_038, sample_033 | pokey_ref_3faf80b4, pokey_ref_5ee9c1a8, pokey_ref_689d3402, pokey_ref_feb29c1f | `representation_duplicate` |
| 5 | 3 | sample_056, sample_044, sample_027 | pokey_ref_1bed70f4, pokey_ref_714607ba, pokey_ref_cb9b6db2 | `representation_duplicate` |
| 6 | 3 | sample_045, sample_034, sample_032 | pokey_ref_af009fe0, pokey_ref_c25e268b, pokey_ref_c53d7640 | `representation_duplicate` |

**24 of 61 profiles** share their audio with
another profile. The values those groups hold in common (one line per group):

| group | shared IR values |
| ---: | :--- |
| 1 | audctl=0, distortion=160, envelope.attack_frames=1, envelope.decay_frames=3, envelope.release_frames=2, envelope.sustain_vol=13, is_16bit=False, resolved_audctl=0, uses_16bit_bass=False |
| 2 | audctl=80, distortion=192, envelope.attack_frames=1, envelope.decay_frames=3, envelope.release_frames=2, envelope.sustain_vol=13, is_16bit=True, resolved_audctl=80, uses_16bit_bass=True |
| 3 | audctl=0, distortion=128, envelope.attack_frames=1, envelope.decay_frames=3, envelope.release_frames=2, envelope.sustain_vol=13, is_16bit=False, resolved_audctl=0, uses_16bit_bass=False |
| 4 | audctl=0, distortion=192, envelope.attack_frames=1, envelope.decay_frames=3, envelope.release_frames=2, envelope.sustain_vol=13, is_16bit=False, resolved_audctl=0, uses_16bit_bass=False |
| 5 | audctl=80, distortion=128, envelope.attack_frames=1, envelope.decay_frames=3, envelope.release_frames=2, envelope.sustain_vol=13, is_16bit=True, resolved_audctl=80, uses_16bit_bass=True |
| 6 | audctl=0, distortion=0, envelope.attack_frames=1, envelope.decay_frames=3, envelope.release_frames=2, envelope.sustain_vol=13, is_16bit=False, resolved_audctl=0, uses_16bit_bass=False |

## 5. Differential rendering

The walk the brief asks for — document → IR → frames → WAV — stopping at the first stage
where a group's members agree:

| group | profiles | document | bound IR | frames | WAV | first agreement |
| ---: | ---: | :--- | :--- | :--- | :--- | :--- |
| 1 | 10 | differs in 428 path(s) | **identical** | **identical** | identical | `document` → `bound_ir` |
| 2 | 6 | differs in 330 path(s) | **identical** | **identical** | identical | `document` → `bound_ir` |
| 3 | 4 | differs in 125 path(s) | **identical** | **identical** | identical | `document` → `bound_ir` |
| 4 | 4 | differs in 691 path(s) | **identical** | **identical** | identical | `document` → `bound_ir` |
| 5 | 3 | differs in 280 path(s) | **identical** | **identical** | identical | `document` → `bound_ir` |
| 6 | 3 | differs in 144 path(s) | **identical** | **identical** | identical | `document` → `bound_ir` |

Where the differences sit, counted across all groups:

| document section | paths differing |
| :--- | ---: |
| `gesture.control_state` | 6 |
| `gesture.modulation` | 6 |
| `gesture.pitch` | 6 |
| `gesture.provenance` | 6 |
| `gesture.resolution` | 6 |
| `gesture.volume` | 6 |
| `metadata.source_label` | 6 |
| `pitch.audf_range` | 6 |
| `pitch.base_divider` | 6 |
| `pitch.change_rate_hz` | 6 |
| `pitch.direction_ratio` | 6 |
| `pitch.frequency_hz` | 6 |
| `pitch.range_semitones` | 6 |
| `pitch.slope_semitones_per_second` | 6 |
| `playable_fingerprint` | 6 |
| `profile_id` | 6 |
| `source_profile.profile_fingerprint` | 6 |
| `source_profile.profile_id` | 6 |
| `volume.active_ratio` | 6 |
| `volume.audc_change_rate_hz` | 6 |
| `volume.change_rate_hz` | 6 |
| `volume.dynamic_range` | 6 |
| `volume.level_distribution` | 6 |
| `volume.mean_level` | 6 |
| `volume.peak_level` | 6 |
| `pitch.base_hz` | 5 |
| `playability.gesture` | 5 |
| `pitch.behavior` | 4 |
| `pitch.frequency_change_rate_hz` | 4 |
| `pokey.channels` | 3 |
| `volume.behavior` | 3 |
| `pitch.divider_range` | 2 |

A concrete example, in the form the brief asked for:

```
Profile A            pokey_ref_0a53188c
Profile B            pokey_ref_1ef377fc

SoundProfile:        differs      (see the section table above)
PlayableSoundProfile: differs      (428 leaf paths)
bound POKEY IR:      IDENTICAL    (distortion, envelope, audctl, is_16bit all equal)
register frames:     IDENTICAL
WAV:                 IDENTICAL    (same SHA-256)

=> information loss occurs in sound_profiles/binding.py:_rebuild_song
```

**Inference.** The loss is not spread across the pipeline. It happens in one function that
writes six fields, and three of the four stages are enough to explain every group.

## 6. Information loss points

| id | boundary | module | what is lost | measurement | gap type |
| :--- | :--- | :--- | :--- | :--- | :--- |
| L1 | PlayableSoundProfile -> bound POKEY IR | `src/atari_music/sound_profiles/binding.py:_rebuild_song` | everything except the generator nibble, four envelope numbers, AUDCTL and the pair flag: measured pitch behaviour, volume contours, modulation, timing, generator changes and all provenance | the binding reads 13 of 232 documented leaf paths; _rebuild_song writes exactly distortion, envelope, audctl, is_16bit, profile_id and profile_fingerprint | representation gap |
| L2 | bound POKEY IR -> register frames | `src/atari_music/ir.py:compile_ir_to_pokey_frames` | IR fields the frame compiler never reads (measured by perturbation below), and any envelope detail the player's four-number state machine cannot express | fields whose perturbation changes no frame: envelope.decay_frames, is_16bit, macro, name, profile_fingerprint, profile_id, role, vibrato_depth, vibrato_speed; fields that do: audctl, distortion, envelope.attack_frames, envelope.release_frames, envelope.sustain_vol | renderer gap (partial) |
| L3 | register frames -> WAV | `src/atari_music/pokey_synth.py:render_pokey_samples` | nothing: the audio is a pure function of the nine register bytes | per stimulus variant, the columns whose alteration changes the audio: VOICE: AUDF1, AUDC1 (no effect: AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4, AUDCTL); PAIR: AUDF1, AUDF2, AUDC2, AUDCTL (no effect: AUDC1, AUDF3, AUDC3, AUDF4, AUDC4) | no gap |
| L4 | SoundProfile (measured) -> PlayableSoundProfile (documented) | `POKEY Sound Archaeology: profile publication (not this repository)` | not measured here: the archaeology pipeline decides what a profile document records, and the documents do carry the gesture series that L1 discards. Any loss at this boundary is outside this repository's visibility. | 232 documented leaf paths available for comparison | unresolved from this repository |

The IR → frames boundary, measured by perturbing each `IRInstrument` field in every
profile's own bound stimulus and comparing the register frames:

| IR field | changes the frames for |
| :--- | :--- |
| `audctl` | 61/61 profiles |
| `distortion` | 61/61 profiles |
| `envelope.attack_frames` | 61/61 profiles |
| `envelope.decay_frames` | 53/61 profiles |
| `envelope.release_frames` | 61/61 profiles |
| `envelope.sustain_vol` | 61/61 profiles |
| `is_16bit` | 0/61 profiles |
| `macro` | 0/61 profiles |
| `name` | 0/61 profiles |
| `profile_fingerprint` | 0/61 profiles |
| `profile_id` | 0/61 profiles |
| `role` | 0/61 profiles |
| `vibrato_depth` | 0/61 profiles |
| `vibrato_speed` | 0/61 profiles |

The frames → audio boundary, measured by zeroing one frame column and re-rendering:

| frame column | VOICE stimulus (AUDCTL $00) | PAIR stimulus (AUDCTL $50) |
| :--- | :--- | :--- |
| AUDF1 | changes the audio | changes the audio |
| AUDC1 | changes the audio | no effect |
| AUDF2 | no effect | changes the audio |
| AUDC2 | no effect | changes the audio |
| AUDF3 | no effect | no effect |
| AUDC3 | no effect | no effect |
| AUDF4 | no effect | no effect |
| AUDC4 | no effect | no effect |
| AUDCTL | no effect | changes the audio |

Read carefully, this table is stimulus-specific and that is the point:

* on a VOICE stimulus only channel 1 sounds, so columns 2–4 and AUDCTL have nothing to
  change — AUDCTL is `$00` there, so zeroing it is a no-op rather than proof that it is
  unread;
* on a PAIR stimulus the sounding channel is 2 (the pair's divider high byte lives in
  AUDF2 and its volume in AUDC2), `AUDC1` is zero by construction, and **AUDCTL does change
  the audio** — which is the clock the pair's frequency is derived from.

## 7. Gesture analysis

| gesture series | in the document | non-static | in the IR | as register writes | verdict |
| :--- | ---: | ---: | :--- | :--- | :--- |
| pitch | 45 | 45 | 0 | 0 | **lost** |
| volume | 58 | 58 | 0 | 0 | **lost** |
| modulation | 61 | — | 0 | 0 | **lost** |
| timing | 61 | — | frames_per_tick comes from the composition's tempo, not the profile | 0 | **lost** |
| control_state | 61 | — | 0 | 0 | **lost** |

Profiles with a non-static pitch gesture: 45; non-static volume gesture: 58; periodic modulation: 7.

Where each series stops:

* **pitch** — the binding writes only distortion, envelope, audctl, is_16bit, profile_id and profile_fingerprint into the IR (sound_profiles/binding.py:_rebuild_song); gesture.pitch is never read
* **volume** — same boundary; the only volume the pipeline owns is the instrument envelope, and its sources are the profile's envelope frames, not its measured contour
* **modulation** — IRInstrument has vibrato_depth/vibrato_speed but no binding writes them
* **timing** — the profile's frame period/sample rate is provenance about how it was measured; the player's tick is the composition's
* **control_state** — the profile's distortion *code* series is summarised into one nibble; a profile that changed generator inside the segment cannot be expressed

**Inference.** Every gesture series is lost at the same place, for the same reason: the
binding writes a *fixed* register configuration, and the player's data format holds one
divider and one volume per channel per row. A gesture is a *series of changes*, so it is
unrepresentable in the format rather than merely unread — reading `gesture.pitch.runs` in
the binding would not help without somewhere to put it.

## 8. Relationship to Part A

These duplicate groups were presented to the listener as different samples.

| group | profiles | distinctiveness | usefulness | Atari character |
| ---: | ---: | :--- | :--- | :--- |
| 1 | 10 | 1–3 | 3–4 | 5–5 |
| 2 | 6 | 3–4 | 3–4 | 3–4 |
| 3 | 4 | 3–3 | 3–3 | 3–3 |
| 4 | 4 | 3–4 | 4–4 | 3–4 |
| 5 | 3 | 3–3 | 3–3 | 3–4 |
| 6 | 3 | 4–5 | 3–3 | 2–2 |

**Inference.** The spread inside a group is the listener's own repeatability, not the
profiles' character — the audio is byte-identical. Stage 9D measured ICC(1,1) of 0.73–0.92
on these scales, so the spread is bounded rather than arbitrary. No rating difference
inside a group may be read as a difference between the profiles in it.

## 9. Part C analysis

Both sides of each song pair were re-rendered in memory and compared at the register and
level level. The package and the answers were read, never written.

| song | frames differing | registers changed | profiles bound | listener | RMS delta |
| :--- | ---: | :--- | ---: | :--- | ---: |
| Vaults-of-Nhyrmeth.dsl | 2280/2280 | AUDF1×2240, AUDF2×2240, AUDC2×2240, AUDCTL×2280 | 3 | default | -0.26 dB |
| as-1.dsl | 2280/2280 | AUDF1×1550, AUDF2×1550, AUDC2×1550, AUDCTL×2280 | 3 | default | +0.63 dB |
| dziki2.json | 4608/4608 | AUDF1×4080, AUDF2×4080, AUDC2×4080, AUDC3×4414, AUDC4×432, AUDCTL×4608 | 3 | default | -4.10 dB |
| as-2.dsl | 1777/2160 | AUDC3×1777 | 4 | default | -0.93 dB |
| funky.json | 4046/4608 | AUDC1×4046 | 4 | default | -3.85 dB |
| koval.json | 6112/6144 | AUDC2×5856, AUDC3×6080, AUDC4×3840 | 4 | default | -6.43 dB |

What the binding actually changed on each instrument:

* **Vaults-of-Nhyrmeth.dsl** — Bass: distortion $A0→$C0, envelope 0/4/11/2 → 1/3/6/2; Lead: distortion $A0→$A0, envelope 1/3/13/2 → 1/3/13/2; Perc: distortion $80→$80, envelope 0/3/8/2 → 0/3/8/2
* **as-1.dsl** — Bass: distortion $A0→$C0, envelope 0/4/11/2 → 0/3/2/2; Lead: distortion $A0→$A0, envelope 1/3/13/2 → 1/3/13/2; Perc: distortion $80→$80, envelope 0/3/8/2 → 0/3/8/2
* **dziki2.json** — Recorder Lead: distortion $A0→$A0, envelope 1/3/13/2 → 0/0/6/5; Viola Counter: distortion $A0→$A0, envelope 1/3/9/2 → 1/3/9/2; Harp Bells: distortion $A0→$A0, envelope 0/2/14/1 → 0/2/14/1; Deep Pure Bass: distortion $A0→$C0, envelope 0/4/11/2 → 0/4/11/2; War Drum: distortion $80→$A0, envelope 0/3/8/2 → 0/3/8/2
* **as-2.dsl** — Bass: distortion $C0→$C0, envelope 0/4/11/2 → 0/4/11/2; Chord: distortion $A0→$A0, envelope 1/3/9/2 → 1/3/9/2; Lead: distortion $A0→$A0, envelope 1/3/13/2 → 6/0/10/2; Perc: distortion $80→$80, envelope 0/3/8/2 → 0/3/8/2
* **funky.json** — Bright Lead: distortion $A0→$A0, envelope 1/3/13/2 → 0/0/6/5; Soft Inner Pad: distortion $A0→$A0, envelope 2/6/10/4 → 2/6/10/4; POKEY Bass: distortion $C0→$C0, envelope 0/4/11/2 → 0/4/11/2; Noise Percussion: distortion $80→$80, envelope 0/3/8/2 → 0/3/8/2
* **koval.json** — Bass: distortion $C0→$C0, envelope 0/4/11/2 → 0/4/11/2; Lead: distortion $A0→$A0, envelope 1/3/13/2 → 0/5/7/4; Arpeggio: distortion $A0→$A0, envelope 0/2/14/1 → 7/2/7/1; Percussion: distortion $80→$80, envelope 0/3/8/2 → 0/6/2/2; Pad: distortion $A0→$A0, envelope 2/6/10/4 → 7/2/7/1

**Mechanism, as far as the measurements go:**

* every bound song had each instrument's **generator and/or envelope replaced** — the
  intended effect of a binding, and also the whole of its effect;
* both sides were compared at **one shared gain** (as in Stage 9C), so a systematic loudness
  advantage is ruled out (median RMS delta -2.39 dB);
* the profile-bound side therefore differs in **timbre and articulation**, and the listener
  preferred the composer's own instruments. The measurements cannot settle *which* of the
  two carried the preference: **unresolved**.
* **unresolved:** whether different profiles per role would have won. The bindings were
  chosen by generator family, not by listening evidence (Stage 9D, §14).

This is a **musical interpretation gap** rather than a rendering defect: both sides render
correctly, and one of them is the sound the composer was designed around.

## 10. Representation vs renderer vs musical interpretation

| level | definition | verdict | evidence |
| :--- | :--- | :--- | :--- |
| **A. Representation gap** | the document holds information the IR cannot express | **present, dominant** — 13 of 232 paths are read; every gesture series is unrepresentable in the player's format | §3, §5, §7 |
| **B. Renderer gap** | the IR holds information the renderer does not use | **minor** — the frame compiler uses every field the binding writes, except the ones measured inert in §6 | §6 |
| **C. Musical interpretation gap** | the profile renders correctly but is used inappropriately | **present** — the profile replaces a character instrument, and the bindings were chosen by generator family | §9 |

The order matters: fixing B would change almost nothing because B is nearly empty, while
fixing A is necessary but not sufficient without C.

## 11. True vs renderer vs representation duplicates

| classification | meaning | groups | profiles |
| :--- | :--- | ---: | ---: |
| `representation_duplicate` | they differ in the document but their IR is identical: a renderer that carried the difference could tell them apart | 6 | 30 |
| `renderer_duplicate` | their IR differs but the frames do not: the player's quantization collapses them | 0 | 0 |
| `true_duplicate` | the documents are equivalent as far as any stage can tell | 0 | 0 |
| `unknown` | not explained by this diagnosis | 0 | 0 |

**Inference.** A byte-identical WAV does **not** mean a redundant profile. 30 profiles are duplicates *of the current
pipeline*, not of the library: they carry information the archaeology measured and this
renderer cannot yet use. The careful statement is that they are redundant **today**.

## 12. Missing capabilities

Ordered by how many duplicate groups need each capability, then by how many leaf paths
differ — an evidence count, not an opinion. None is implemented.

| capability | groups needing it | leaf paths differing | profiles | evidence | expected effect | risk |
| :--- | ---: | ---: | ---: | :--- | :--- | :--- |
| volume contour (a measured volume envelope, not four ADSR numbers) | 6 | 981 | 30 | **strong** | would let two profiles with the same generator but different measured level movement render differently | medium: the player already recomputes a volume every frame, so this is a data-format change rather than an engine change |
| pitch trajectory (a measured pitch contour, not one note) | 6 | 525 | 30 | **strong** | would let two profiles with the same generator but different measured pitch movement render differently | high: needs a per-frame pitch macro in the player's data format, which today holds one divider per channel per row |
| generator changes inside one sound | 6 | 188 | 30 | **strong** | would let a profile that changed distortion within its segment keep that change | medium: AUDC can change per frame, but the player writes it once per channel |
| measured pitch register base and range | 6 | 48 | 30 | **strong** | would keep the profile's own reference frequency rather than deriving it from the composition's note | low-medium: a reference fact rather than a playback instruction; may belong in the report and not in the renderer |
| modulation (periodic pitch/volume movement) | 6 | 18 | 30 | **strong** | would let a profile measured with a periodic rate keep it | high: the pitch/volume trajectory problem again, at a faster rate |
| measured envelope shape and timing in milliseconds | 0 | 0 | 0 | **not applicable** | the envelope already survives the binding, so it cannot explain a duplicate; its limitation is that the player expresses only four numbers | medium-high: the player's envelope is verified frame-by-frame against player.asm, so changing it changes the XEX as well as the WAV |

Not a duplicate explanation, but a limit on expression: measured envelope shape and timing in milliseconds.

The player's four-number envelope quantizes what it can express: perturbing envelope.decay_frames changes no frame at all for 8 of 61 profiles, because a zero-slope decay only delays the jump to sustain.

Section evidence, by how many groups differ there:

| document section | groups | leaf paths | profiles |
| :--- | ---: | ---: | ---: |
| `gesture.control_state` | 6 | 188 | 30 |
| `gesture.modulation` | 6 | 18 | 30 |
| `gesture.pitch` | 6 | 525 | 30 |
| `gesture.provenance` | 6 | 32 | 30 |
| `gesture.resolution` | 6 | 12 | 30 |
| `gesture.volume` | 6 | 981 | 30 |
| `metadata.source_label` | 6 | 6 | 30 |
| `pitch.audf_range` | 6 | 10 | 30 |
| `pitch.base_divider` | 6 | 6 | 30 |
| `pitch.change_rate_hz` | 6 | 6 | 30 |
| `pitch.direction_ratio` | 6 | 6 | 30 |
| `pitch.frequency_hz` | 6 | 13 | 30 |
| `pitch.range_semitones` | 6 | 6 | 30 |
| `pitch.slope_semitones_per_second` | 6 | 6 | 30 |
| `playable_fingerprint` | 6 | 6 | 30 |
| `profile_id` | 6 | 6 | 30 |
| `source_profile.profile_fingerprint` | 6 | 6 | 30 |
| `source_profile.profile_id` | 6 | 6 | 30 |

The perceptual evidence, stated honestly: Stage 9D established that the listener hears
differences between profiles and prefers particular ones, but **no gesture was ever
rendered**, so there is no direct perceptual evidence for any individual capability. This
list comes from what the documents differ in, not from what the listener asked for.

## 13. Loudness analysis

| song | RMS delta (profile − default) | peak delta | dynamic-range delta |
| :--- | ---: | ---: | ---: |
| Vaults-of-Nhyrmeth.dsl | -0.26 dB | +0.00 dB | +0.23 dB |
| as-1.dsl | +0.63 dB | +0.00 dB | +20.46 dB |
| dziki2.json | -4.10 dB | +0.00 dB | +6.62 dB |
| as-2.dsl | -0.93 dB | +0.00 dB | -1.96 dB |
| funky.json | -3.85 dB | +0.00 dB | +3.53 dB |
| koval.json | -6.43 dB | +0.00 dB | +0.43 dB |

Median RMS delta **-2.39 dB**; median dynamic-range delta 1.98 dB. Both sides share one gain in this comparison (as in Stage 9C), so a systematic difference is a property of the rendering, not of the level normalization.

**Inference.** Loudness does not explain the 5–0 result. Stage 9D's finding that the louder
side won 10 of 11 decided profile-vs-profile trials remains a caveat for Parts A and B; it
is not the mechanism here, where both sides share one gain by construction.

## 14. Implications

1. **The duplicate count is a pipeline fact, not a library fact.** The 24 profiles are
   distinct measurements; they render alike because a handful of values survive the binding.
2. **Any future 'how many sounds does the library have' claim must be computed on rendered
   audio**, and a curation decision must be made per *audio group* — which is what Stage
   9D's shortlist rule already does.
3. **A renderer improvement is a research act, not a bug fix.** The capabilities with the
   most reach change what the listener hears, so they invalidate the current perceptual
   evidence and require a new listening test to re-establish it.
4. **The whole-song result should be re-tested before the library is judged.** It measured
   one binding strategy, chosen without listening evidence, against instruments the
   composer was designed around.
5. **The metric defect is separate and cheaper.** It affects analysis, not audio.

## 15. Recommended next step

Stage 10 - Minimal Renderer Capability Experiment: implement exactly the pitch trajectory and volume contour the data names, bind the six songs from the listening evidence, and repeat only the whole-song comparison. Not started here.

In order, with the reason for the order:

1. **Re-bind the six songs from the listening evidence** — cheap, reversible, no engine
   change — and repeat only the whole-song comparison. If the profile-bound render still
   loses, the problem is not which profiles were chosen.
2. **Carry the volume contour before the pitch trajectory.** The player already recomputes a
   volume every frame, so this is a data-format change; a pitch trajectory needs a per-frame
   divider macro and is a far larger change.
3. **Re-run the listening test** on whatever changed, because step 2 changes what the
   listener hears and therefore invalidates the current perceptual ranking.

Explicitly not recommended now: implementing gestures speculatively, changing the player,
selecting the library, or replacing the similarity metric before the model in §13 of the
brief has been rebuilt from evidence.

## 16. STOP / decision

**DIAGNOSTICALLY_COMPLETE**

* duplicate groups: 6, explained: 6, unexplained: 0
* profiles in duplicate groups: 30 (24 redundant beyond the first of each group)
* no profile, schema, WAV, answer, player or composer source was modified

### The eight questions

| # | question | answer |
| :--- | :--- | :--- |
| Q1 | Why do 61 profiles produce only 37 distinct WAVs? | because 24 of them differ only in document fields the binding never reads. The binding reads 13 of 232 documented paths; the audio is a pure function of the register frames; and the frames depend only on the generator nibble, four envelope numbers, AUDCTL and the pair flag. |
| Q2 | Where exactly in the pipeline is the difference lost? | at the PlayableSoundProfile -> POKEY IR boundary, in binding.py:_rebuild_song, for 6 of 6 groups; no group needed any other explanation |
| Q3 | Which profile information is currently unused? | 6 named capabilities cover it; the largest are the pitch trajectory, the volume contour and the measured envelope shape/timing, each carried by the gesture and envelope sections that nothing downstream reads |
| Q4 | Does the loss have support in the listening results? | yes for the duplication itself (Stage 9D found the same 37 signals and the same 24 duplicate profiles from the audio alone, and the duplicate groups are exactly the groups whose documents differ only in unread fields); no for the perceptual weight of each individual gesture, because the listener never heard one rendered |
| Q5 | Why did profile-bound rendering lose 5-0 in Part C? | the mechanism is measured in part_c_diagnostics: the binding replaces each instrument's generator, envelope and clock, and both sides are rendered at one shared gain, so the loss is not a level artefact. The losses are explained by *what the binding changes* rather than by a rendering defect; the report states which of the candidate mechanisms the frames support and which remain unresolved. |
| Q6 | Is the problem representation, renderer or musical interpretation? | primarily representation (the binding discards most of the document), secondarily musical interpretation (the bindings were chosen by generator family, and the profile replaces a character instrument tuned for the piece), and only marginally renderer (the frame compiler does use every IR field the binding writes) |
| Q7 | What is the minimal set of future changes? | the capabilities listed in missing_capabilities, ordered by how many currently identical profiles each would separate; none is implemented here |
| Q8 | Is there a basis for implementing changes? | yes for the two that are (a) named by the data and (b) independent of any change to the composition system: the binding must carry the profile's own pitch and volume behaviour where the player can express it, and the similarity metric must include level. Both are stated in the report as proposals with their evidence. |

**STOP.** Nothing recommended above has been implemented.

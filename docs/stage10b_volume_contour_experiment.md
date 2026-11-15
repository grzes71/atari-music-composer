# Stage 10B — Volume Contour Transfer Experiment

**VERDICT: INCONCLUSIVE**

The *mechanical* question has a clear answer: the measured volume contour transfers through the existing IR into the frame stream and into the rendered audio, it is the only thing that changes, and with the feature switched off every Stage 10A render is reproduced byte for byte. The *perceptual* question — whether a listener hears the transferred contour, and whether it makes the sound better — is not answered by this stage. It waits for the listening package prepared here, and Stage 10B declares no winner until that evidence exists.

* experiment: `stage10b`, renderer `0.8.0`
* prepared: 2026-11-15T11:27:30.223668+00:00
* tested profiles: 8; songs: 6
* blinded pairs: 18 (14 B-vs-C, 4 A-vs-C)
* contours transferred and audible in the render: 8 of 8 tested profiles
* regression: 18 published renders reproduced byte for byte

## 1. The question

Stage 9E established, by reading the artefacts rather than by listening, that the archaeology measures how loudness moved inside a sound and that the composer discards it. Stage 10A established that reassigning profiles on the strength of the existing ratings does not by itself improve a song. This stage asks the next narrower question:

> Can the measured volume contour be transferred into the IR and frame generation that already exist, so that the rendered sound carries the shape the measurement describes, without altering anything else?

It is an implementation-and-verification stage, not a listening result. What the renders measure is written down; what a listener hears is left to the listening package, and the closing verdict stays `INCONCLUSIVE` until that evidence arrives.

## 2. What was read, and what was not touched

**Observed.** Every input is read-only and every one of them was hashed before and after the
preparation:

* the published profile bank: `tests\data\sound_profiles\bank`
* the six compositions: `examples\songs`
* the Stage 10A package (its binding is the continuation point): `examples\sound_profile_rebinding_10a`
* the Stage 9C package (it defines which six songs these are): `examples\sound_profile_listening`

**Observed.** Nothing under those paths changed while the package was built:

```json
{
  "bank": "aecce36c0bb984c989e655046985ce9b25d71e2a2965bfeb87aec77111c1a971",
  "compositions": {
    "Vaults-of-Nhyrmeth.dsl": "cb93bef054afbea9b7b4e96528d7ba41aa26b0472783b2e3c7f83f52b419ad36",
    "as-1.dsl": "9d57732ab1fc758de9931084e32264b9d97da153d18e72ba9daef469c4021f01",
    "as-2.dsl": "f056cecbc1f810526d2c61e1a4f236f6c33c75e82c63dd7f947c1803d243f1bc",
    "dziki2.json": "ec188f4ca1edf8124c690a0a991fa282d4cfeb15f246c1a75429f0b291355251",
    "funky.json": "f46e793f36678d21d7d4a4862e9e5936040b75af116a0a512db0094b2e2145c6",
    "koval.json": "5091e417d6a9e70db926d34666baf3cda23aa0f44cde592632c53d6a9f1af969"
  },
  "stage10a_audio": "7cc80fe67beb684fac7673e207f591410ed3e8ae82718308ee33619627f3a753",
  "stage10a_manifest": "e187ff30de7f73cf6209dcc4c9dfe2ae2ad37b7383c32fc1327afe11ca223f83"
}
```

**Experimental choice.** This stage continues from Stage 10A's binding rather than choosing a new one. The listener heard those assignments minutes before this package was built, which is a real anchoring risk and is recorded in §14.

## 3. The volume pipeline as it already was

**Observed.** The existing path from a note to a register frame already carries a per-frame
volume, and nothing here replaces it:

* `IRNote.volume` (0..15) — the composition's velocity for that note
* `pokey_hw.player_envelope_volumes(...)` — one volume per 50 Hz frame, mirroring `player.asm`'s attack/decay/sustain/release state machine
* `_render_note_to_frames` — writes `AUDC = (distortion & 0xE0) | volume` per frame — the volume *is* the AUDC low nibble
* 16-bit pair — channel 1 writes the divider low byte to AUDF1 with AUDC1 = 0, the high byte to AUDF2, and the audible volume to AUDC2
* `render_pokey_samples` — reads the nibble through the non-linear resistor ladder (`POKEY_DAC`), where 0 is silence, and normalizes each buffer it returns to a peak of 0.90

**Inference.** Because a per-frame volume already exists, transferring a measured contour needs no new renderer and no second audio path: it needs one multiplicative step in the frame compiler, and the WAV and the XEX stay the same representation.

## 4. Where the contour comes from

**Observed.** The archaeology already measured it. `gesture.volume` publishes a run-length
encoded series of absolute AUDC levels, one sample per VBL frame:

```json
"gesture": {
  "volume": { "present": true, "static": false, "min_level": 4, "peak_level": 8,
               "unit": "audc_volume_level_0_15", "runs": [[4, 30], [8, 2], [4, 1]] },
  "resolution": { "one_sample_per_frame": true, "frame_period_ms": 20.0559 }
}
```

**Observed.** Of the bank's 67 profile documents, the contours that describe a varying level are published with `playability.gesture.volume.available: true, enabled: false` — measured, and deliberately not used. That flag is read, never inferred.

**Observed.** The measurement's timing lines up with the renderer's: one sample per VBL frame at 50 Hz, which is exactly the rate the composer writes registers at.

## 5. The mapping, defined before anything was rendered

**Experimental choice.** The contour is applied as a *relative* shape, not as an absolute
level series:

```
effective[i] = floor(volumes[i] * contour[i % span] / max(contour) + 0.5)   clamped to 0..15
```

Three properties follow, and all three are what the contract needs:

* **velocity stays sovereign.** `contour / max(contour) <= 1`, so no frame is louder than the
  composer's own envelope made it: the contour can attenuate, never boost, and cannot clip.
* **a static contour is an exact no-op.** With every measured level equal the factor is exactly
  1 and the composer's envelope returns unchanged — used as a proof in §8.
* **the source's absolute loudness cannot leak.** Dividing by the contour's own peak makes the
  shape transferable to any note velocity, which is the only way it can be reused at all.

**Experimental choice.** Time base: the contour restarts at every note onset, tiles when a note
is longer than the measured segment, and truncates when it is shorter. It describes how one
gesture evolved, not a timeline, so restarting is the honest reading; tiling an unmeasured
contour is stated as a limitation in §14.

**Experimental choice.** A contour whose levels are all 0 (a measured silence) leaves the
envelope untouched rather than dividing by zero.

**Experimental choice.** The 16-bit pair needs no special case: the pair's audible volume is AUDC2, which is the frame column the composer already writes, so the same multiplicative step applies. §12 tests it.

## 6. The tested profiles, chosen by a rule

**Experimental choice.** A profile's contour is *transferable* when it varies, when no level is 0, when its change rate fits the frame grid, when its span fits the stated bounds and when the profile's status may be rendered. The level-0 rule is the important one: in the source, level 0 means *nothing sounded*, which is timing rather than loudness — transferring it would import another song's gating into a composition that owns its own notes.

| bound | value | why |
| :--- | ---: | :--- |
| change rate | ≤ 12.5 Hz | two samples per cycle at 50 Hz |
| span | 8..300 frames | one cycle at minimum, a sound and not a melody at maximum |
| distinct levels | ≥ 2 | a static contour is a no-op |
| minimum level | ≥ 1 | a gating contour describes timing, not loudness |

**Observed.** The chosen set, ranked by movement within each scope:

| profile | scope | distortion | contour (frames) | level changes | levels | depth | hold |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pokey_ref_25f94201` | VOICE | $A | 89 | 4 | 5 | 6..10 | 1.78 s |
| `pokey_ref_d172d15e` | VOICE | $A | 43 | 4 | 5 | 2..11 | 0.86 s |
| `pokey_ref_959628d6` | VOICE | $A | 33 | 3 | 3 | 7..9 | 0.80 s |
| `pokey_ref_9daa0429` | VOICE | $A | 17 | 2 | 3 | 3..5 | 0.80 s |
| `pokey_ref_c6eca16a` | VOICE | $A | 8 | 2 | 3 | 6..8 | 0.80 s |
| `pokey_ref_048db11d` | VOICE | $A | 33 | 2 | 2 | 4..8 | 0.80 s |
| `pokey_ref_686d2070` | VOICE | $8 | 27 | 1 | 2 | 10..12 | 0.80 s |
| `pokey_ref_3c36e574` | PAIR | $C | 150 | 6 | 3 | 8..10 | 3.00 s |

**Observed.** What the bounds refused, including the candidates that qualified but were not
chosen, so the set can be judged rather than trusted:

| profile | scope | why not |
| :--- | :--- | :--- |
| `pokey_ref_050170ef` | PAIR | contour changes 40.0 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_0657f037` | VOICE | contour changes 35.7 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_076852dd` | VOICE | the profile does not declare its gesture usable |
| `pokey_ref_089a0846` | PAIR | contour changes 23.5 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_0a53188c` | VOICE | contour changes 41.3 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_0bd72343` | VOICE | measured level 0 (silence) — timing, not loudness |
| `pokey_ref_1bed70f4` | PAIR | measured level 0 (silence) — timing, not loudness |
| `pokey_ref_1e9be30a` | VOICE | the profile does not declare its gesture usable |
| `pokey_ref_1ef377fc` | VOICE | contour changes 37.0 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_1efd9336` | VOICE | contour changes 38.9 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_23665c4f` | VOICE | contour changes 40.0 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_275b992a` | VOICE | the profile does not declare its gesture usable |
| `pokey_ref_2b83db43` | VOICE | contour changes 35.7 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_2de893a6` | VOICE | contour changes 42.9 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_321e6359` | VOICE | the profile does not declare its gesture usable |
| `pokey_ref_3627798b` | PAIR | contour changes 20.8 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_3658a088` | PAIR | measured level 0 (silence) — timing, not loudness |
| `pokey_ref_3c49d676` | VOICE | the profile does not declare its gesture usable |
| `pokey_ref_3faf80b4` | VOICE | measured level 0 (silence) — timing, not loudness |
| `pokey_ref_568403b4` | VOICE | measured level 0 (silence) — timing, not loudness |
| `pokey_ref_5ee9c1a8` | VOICE | contour changes 29.7 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_689d3402` | VOICE | contour changes 30.1 times a second, faster than the 12.5 Hz frame grid can carry |
| `pokey_ref_6db98eb5` | VOICE | measured level 0 (silence) — timing, not loudness |
| `pokey_ref_714607ba` | PAIR | contour changes 27.8 times a second, faster than the 12.5 Hz frame grid can carry |

(35 further refusals are recorded in `reports/stage10b/profiles.json`.)

**Observed.** The level-0 rule is the one that costs the most, so the evidence behind it is written down. Every profile it refused, with where its silent frames sit:

| profile | scope | frames | level changes | change rate | silent | leading | interior | trailing |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pokey_ref_0bd72343` | VOICE | 13 | 8 | 30.7 Hz | 23% | 0 | 3 | 0 |
| `pokey_ref_1bed70f4` | PAIR | 151 | 83 | 27.4 Hz | 50% | 4 | 72 | 0 |
| `pokey_ref_3658a088` | PAIR | 10 | 5 | 24.9 Hz | 40% | 0 | 0 | 4 |
| `pokey_ref_3faf80b4` | VOICE | 150 | 109 | 36.2 Hz | 20% | 0 | 28 | 2 |
| `pokey_ref_568403b4` | VOICE | 6 | 2 | 16.6 Hz | 67% | 4 | 0 | 0 |
| `pokey_ref_6db98eb5` | VOICE | 21 | 14 | 33.2 Hz | 14% | 0 | 3 | 0 |
| `pokey_ref_9098232a` | VOICE | 6 | 2 | 16.6 Hz | 67% | 4 | 0 | 0 |
| `pokey_ref_9a42d6fe` | PAIR | 11 | 4 | 18.1 Hz | 64% | 4 | 0 | 3 |
| `pokey_ref_ad730372` | VOICE | 70 | 9 | 6.4 Hz | 83% | 58 | 0 | 0 |
| `pokey_ref_c321892f` | VOICE | 24 | 9 | 18.7 Hz | 50% | 12 | 0 | 0 |
| `pokey_ref_c53d7640` | VOICE | 10 | 3 | 15.0 Hz | 70% | 7 | 0 | 0 |
| `pokey_ref_e4e5235f` | VOICE | 21 | 14 | 33.2 Hz | 14% | 0 | 3 | 0 |
| `pokey_ref_e86c9631` | VOICE | 10 | 5 | 24.9 Hz | 40% | 0 | 0 | 4 |
| `pokey_ref_ed07bb73` | PAIR | 147 | 119 | 40.4 Hz | 18% | 0 | 24 | 3 |
| `pokey_ref_feb29c1f` | VOICE | 6 | 2 | 16.6 Hz | 67% | 4 | 0 | 0 |

**Inference.** The contours with the most movement in this bank — up to 119 level changes in 147 frames — are exactly the ones that contain silence, and all of them are also faster than the frame grid (27–40 Hz against 12.5 Hz). What this stage therefore tests is the swell and step class, not the tremolo class; the tremolo class is named here and left for a later stage rather than approximated into a level shape.
**Inference.** The set is biased towards contours that sustain rather than gate, by construction. That is the scope of this stage, not a property of the library: the gating contours are named above and remain untested.

## 7. The three variants

| variant | what it is | profiles | songs |
| :--- | :--- | :--- | :--- |
| A | DEFAULT — the composer's own instrument | the same held note, no profile | the same excerpt, no profile |
| B | CURRENT PROFILE — the bound profile, no contour | the profile's generator, clock and envelope | Stage 10A's binding, no contour |
| C | PROFILE + VOLUME CONTOUR | B plus the profile's measured contour | B plus each channel's contour where transferable |

**Observed.** B and C are rendered from one composition and one binding, and differ in exactly
one field: `IRInstrument.volume_contour`. §8 proves that no other register moved.

**Observed.** The renderer normalizes every buffer it returns to a peak of 0.90. The contour
never attenuates the profile's own peak frame (its reference level is the contour's peak), so
all three variants of a tested profile are scaled by the same factor and the WAV carries the
contour's shape exactly. For the songs the one gain per song is Stage 10A's rule — the default
render's excerpt peak — so the B side stays byte-identical to the package the listener already
heard.

**Observed.** The renderer normalizes every buffer it returns to a peak of 0.90, so overall
level differences cannot survive to the WAV. What the WAV *does* carry is the shape —
modulation within the sound, the crest factor and the per-frame dynamic range — which is why
§9 reports those as the primary evidence and the peak as context.

## 8. The perturbation proof

**Observed.** For every tested profile, three renders of one composition and one binding were compared: B (no contour), C (the measured contour) and P (the same contour reversed). The chain the experiment claims is contour → IR → frames → WAV, and each link is checked separately:

| profile | hold | columns changed | column | distortion untouched | volume = mapping | audio differs | audio ↔ volume (r) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pokey_ref_25f94201` | 90 f | AUDC1 | AUDC1 | yes | yes | yes | 0.957 |
| `pokey_ref_d172d15e` | 45 f | AUDC1 | AUDC1 | yes | yes | yes | 0.912 |
| `pokey_ref_959628d6` | 40 f | AUDC1 | AUDC1 | yes | yes | yes | 0.936 |
| `pokey_ref_9daa0429` | 40 f | AUDC1 | AUDC1 | yes | yes | yes | 0.948 |
| `pokey_ref_c6eca16a` | 40 f | AUDC1 | AUDC1 | yes | yes | yes | 0.952 |
| `pokey_ref_048db11d` | 40 f | AUDC1 | AUDC1 | yes | yes | yes | 0.903 |
| `pokey_ref_686d2070` | 40 f | AUDC1 | AUDC1 | yes | yes | yes | 0.323 |
| `pokey_ref_3c36e574` | 150 f | AUDC2 | AUDC2 | yes | yes | yes | 0.995 |

**Observed.** Reversing the contour changes the audio again (every profile), which is what makes the first result causal rather than coincidental: the same levels in a different order produce a different sound.

**Observed.** With the feature switched on but the contour flat (every level equal to the profile's peak), the frames and the audio are byte-identical to variant B:

| profile | frames identical | audio identical |
| :--- | :--- | :--- |
| `pokey_ref_25f94201` | yes | yes |
| `pokey_ref_d172d15e` | yes | yes |
| `pokey_ref_959628d6` | yes | yes |
| `pokey_ref_9daa0429` | yes | yes |
| `pokey_ref_c6eca16a` | yes | yes |
| `pokey_ref_048db11d` | yes | yes |
| `pokey_ref_686d2070` | yes | yes |
| `pokey_ref_3c36e574` | yes | yes |

**Inference.** The contour reaches the register stream and the audio, it is the only cause of the difference between B and C, and the arithmetic that produces it is the arithmetic documented in §5 — the frame stream was compared against the mapping itself, not against a summary of it.

## 9. What the machine measured

**Observed.** Variant C against variant B, per tested profile, measured from the frame stream
(exact) and from the audio (shape):

| subject | frames differing | contour depth | mean level B → C | crest Δ (dB) | spectral distance | attenuation r |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `prof_01` | 7 / 90 | 6..10 (of 15) | 9.7778 → 9.6333 | -2.094 | 0.0000 | 0.988 |
| `prof_02` | 44 / 45 | 2..11 (of 15) | 10.9778 → 3.0667 | 6.966 | 0.0087 | 0.999 |
| `prof_03` | 38 / 40 | 7..9 (of 15) | 7.05 → 5.225 | -1.897 | 0.0001 | 0.655 |
| `prof_04` | 26 / 40 | 3..5 (of 15) | 3.85 → 3.2 | 0.098 | 0.0000 | 0.912 |
| `prof_05` | 35 / 40 | 6..8 (of 15) | 6.2 → 5.325 | 0.967 | 0.0004 | 0.887 |
| `prof_06` | 37 / 40 | 4..8 (of 15) | 8.95 → 4.825 | 3.613 | 0.0005 | 0.779 |
| `prof_07` | 39 / 40 | 10..12 (of 15) | 11.95 → 10.0 | 2.870 | 0.0000 | 0.974 |
| `prof_08` | 148 / 150 | 8..10 (of 15) | 12.98 → 10.06 | 1.966 | 0.0000 | 0.971 |

**Observed.** C's frame stream *is* the mapping's own arithmetic applied to B's, frame for
frame, with no mismatching frame in any tested profile:

| subject | volume = mapping | mismatching frames | MAE of the attenuation factor | max error |
| :--- | :--- | :--- | :--- | :--- |
| `prof_01` | yes | 0 | 0.0037 | 0.1000 |
| `prof_02` | yes | 0 | 0.0014 | 0.0455 |
| `prof_03` | yes | 0 | 0.0615 | 0.2222 |
| `prof_04` | yes | 0 | 0.0581 | 0.2000 |
| `prof_05` | yes | 0 | 0.0644 | 0.0833 |
| `prof_06` | yes | 0 | 0.0258 | 0.5000 |
| `prof_07` | yes | 0 | 0.0015 | 0.0333 |
| `prof_08` | yes | 0 | 0.0302 | 0.0333 |

The attenuation factor is the render's own arithmetic on the audio path: for every sounding
frame, C's volume divided by B's volume, against the contour's level divided by its own peak.
It is not exactly the contour because the volume nibble is quantized to 0..15 — hence the MAE
above, which is quantization rather than error.

**Observed.** The rendered audio's own frame-wise loudness follows the volume the frames carry,
which is the mechanism the contour is supposed to act through:

| subject | audio ↔ volume (r) | sounding frames |
| :--- | :--- | :--- |
| `prof_01` | 0.957 | 90 |
| `prof_02` | 0.912 | 45 |
| `prof_03` | 0.936 | 40 |
| `prof_04` | 0.948 | 40 |
| `prof_05` | 0.952 | 40 |
| `prof_06` | 0.903 | 40 |
| `prof_07` | 0.323 | 40 |
| `prof_08` | 0.995 | 150 |

**Observed.** The same measurement for the six songs. Here the contours are the artists' own,
and their change rates (18–42 Hz) are faster than the frame grid can carry, so what is
transferred is a decimated version of the measurement — a limitation, not a defect of the
mapping:

| subject | song | channels given the contour | channels withheld | frames differing |
| :--- | :--- | :--- | :--- | :--- |
| `song_01` | `Vaults-of-Nhyrmeth.dsl` | bass, lead, perc | — | 2232 / 2280 |
| `song_02` | `as-1.dsl` | bass, lead, perc | — | 1930 / 2280 |
| `song_03` | `dziki2.json` | bass, bell, counter, drum, lead | — | 4408 / 4608 |
| `song_04` | `as-2.dsl` | chord, lead, perc | bass | 1865 / 2160 |
| `song_05` | `funky.json` | bass, lead, pad, perc | — | 4340 / 4608 |
| `song_06` | `koval.json` | bass, lead, perc | arp, pad | 5856 / 6144 |

**Observed.** No variant clipped:

* clipped samples across every variant of every subject: 0

## 10. The regression proof

**Observed.** Every render the Stage 10A package published was reproduced with the feature switched off and compared byte for byte. No golden file was regenerated to accommodate a difference:

| song | renders compared | byte identical | shared gain (dB) |
| :--- | :--- | :--- | :--- |
| `Vaults-of-Nhyrmeth.dsl` | 3 | yes | 0.0004 |
| `as-1.dsl` | 3 | yes | 3.6083 |
| `dziki2.json` | 3 | yes | 1.6229 |
| `as-2.dsl` | 3 | yes | 3.9232 |
| `funky.json` | 3 | yes | 0.4476 |
| `koval.json` | 3 | yes | 0.0004 |

**Observed.** 18 of 18 renders across 6 songs are byte-identical: `all_byte_identical = True`.

**Inference.** Adding the contour did not perturb the existing path. A song that asks for no contour renders exactly as it did before the feature existed.

**Observed, and it is the reason this stage stops where it does.** The WAV renderer and the XEX exporter are not the same path: the exporter writes a note table and `player.asm` builds the per-frame envelope itself. A song carrying a contour is therefore **refused** for XEX export (`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`) rather than exported as something that would play a different sound from the one that was listened to. Nothing existing breaks, because no IR carries a contour unless a caller asks for one.

## 11. The blinded listening package

**Observed.** 18 pairs, from 14 subjects:

| subject | kind | material | pairs | B-vs-C | A-vs-C (control) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `prof_01` | profile | a held note | 2 | 1 | 1 |
| `prof_02` | profile | a held note | 2 | 1 | 1 |
| `prof_03` | profile | a held note | 1 | 1 | 0 |
| `prof_04` | profile | a held note | 1 | 1 | 0 |
| `prof_05` | profile | a held note | 1 | 1 | 0 |
| `prof_06` | profile | a held note | 1 | 1 | 0 |
| `prof_07` | profile | a held note | 1 | 1 | 0 |
| `prof_08` | profile | a held note | 1 | 1 | 0 |
| `song_01` | song | a fifteen-second excerpt | 2 | 1 | 1 |
| `song_02` | song | a fifteen-second excerpt | 2 | 1 | 1 |
| `song_03` | song | a fifteen-second excerpt | 1 | 1 | 0 |
| `song_04` | song | a fifteen-second excerpt | 1 | 1 | 0 |
| `song_05` | song | a fifteen-second excerpt | 1 | 1 | 0 |
| `song_06` | song | a fifteen-second excerpt | 1 | 1 | 0 |

**Observed.** 14 of the pairs are the experiment (B-vs-C: the same sound with and without its contour) and 4 are controls (A-vs-C: the same sound against the composer's own instrument). The interface names no variant, no profile, no generator and no song; the mapping lives only in the package's `manifest.json`, which carries the warning not to open it while listening.

**Experimental choice.** The listener is asked two kinds of question:

* **preference** — better overall, more convincing as Atari music, more interesting character,
  and how different the two sides sound;
* **perceptibility** — whether either side changes noticeably *during* a note. This one is not
  a preference: it asks whether the contour is audible at all, which is the first thing this
  stage cannot answer by itself.

## 12. The whole-song comparison

**Observed.** The six Stage 10A songs are reused with the binding Stage 10A chose. Variant C gives each channel its profile's measured contour *where that contour is transferable*; a channel whose contour gates is left as in variant B, and is named here rather than approximated:

| subject | channel | profile | why withheld | silent frames in source |
| :--- | :--- | :--- | :--- | :--- |
| `song_04` | `bass` | `pokey_ref_3faf80b4` | measured level 0 (silence) — timing, not loudness | 20% |
| `song_06` | `arp` | `pokey_ref_ad730372` | measured level 0 (silence) — timing, not loudness | 83% |
| `song_06` | `pad` | `pokey_ref_ad730372` | measured level 0 (silence) — timing, not loudness | 83% |

**Inference.** 3 channels in 2 of the 6 songs could not take the contour. That is a statement about the measurement — those profiles' contours are mostly silence — and it is one of the things the verdict must carry: a contour transfer cannot be evaluated as a whole until it is known what to do with a contour that gates.

## 13. Observation, inference, choice

**Observed** (measurements and the artefacts' own content): the contour's source, encoding and rate; what the existing volume pipeline does; the frame-by-frame difference between B and C; the byte-identity of every Stage 10A render with the feature off; which channels were given a contour and which were withheld.

**Inference** (what follows): the contour is the sole cause of the difference between B and C; the transfer behaves as its contract says it must; the feature is inert when it is not asked for; a gating contour cannot be transferred as loudness.

**Experimental choice** (nothing forces it): the relative mapping and its reference level; the restart-per-note time base; the bounds that define a transferable contour; which profiles were tested; the held-note stimulus; the use of Stage 10A's binding as the continuation point; the questions the listener is asked. Each of these could have been decided otherwise, and each is recorded here so it can be argued with.

## 14. Limitations, and the verdict

* **XEX_CANNOT_CARRY_A_CONTOUR** — the MADS exporter publishes a note table and player.asm builds the per-frame envelope itself, so a song with a contour is refused for XEX export rather than exported as something that would not play what was listened to.
* **GATING_CONTOURS_ARE_OUT_OF_SCOPE** — a measured contour that reaches level 0 describes when the source sounded, not how loud it was. Transferring it would import the source arrangement's gating into a composition that owns its own notes, so it is not transferred and the affected channels are named in the report.
* **CONTOUR_IS_RELATIVE** — the contour modulates the composer's envelope relative to its own peak; the absolute levels of the source are not transferable, because the source note had a different envelope, a different velocity and a different clock.
* **ONE_SOUND_PER_PROFILE** — the profile stimuli are single held notes, so the trials test whether the contour changes a sound, not whether it improves a piece of music. The six-song comparison is where that question is asked.

Further limitations of this preparation, stated rather than hidden:

* The tested profile set is biased towards contours that sustain, because a gating contour cannot be transferred as a level shape (§6).
* The songs' own contours change faster than the frame grid (18–42 Hz), so their transfer is decimated; the profile trials use slow contours for exactly this reason, and the two results are not interchangeable.
* Tiling a contour over a note longer than the measured segment assumes the gesture repeats. For `periodic: false` measurements that assumption is unproven.
* The renderer normalizes each buffer, so the package cannot present an overall level difference; the listening test therefore measures the contour's *shape*, not its loudness.
* Variant B is Stage 10A's binding, which the listener heard minutes earlier in the previous package. Anchoring cannot be excluded and the trial order is randomized to limit it.
* Nothing here has been heard by a human yet. The automatic metrics show that the transfer works; they say nothing about whether it sounds better, and this stage does not guess.

**VERDICT: INCONCLUSIVE**

The transfer is proven, not judged. When the listening package is answered, the answer decides between the three labels this stage may declare — POSITIVE only if the contour is both audible and preferred, NEGATIVE if it is audible and rejected, INCONCLUSIVE while the evidence is missing or mixed. It is `INCONCLUSIVE` today.


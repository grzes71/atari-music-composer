# Stage 12A — profile decoration vs replacement

Does a SoundProfile work better when it *decorates* the Composer's already-tuned instrument than when it *replaces* it? This experiment answers that with the production binding untouched: it reads the existing binding as the control (variant B) and builds three further variants from the same composed song in memory.

* experiment: `stage12a` (`stage12a/1`)
* variants: A COMPOSER_BASELINE · B PROFILE_REPLACEMENT · C PROFILE_DECORATION · D SELECTIVE_DECORATION
* test cases: **6** (6 usable, 0 technical failure)
* binding writes (IR fields, union over cases): `audctl, distortion, envelope, profile_fingerprint, profile_id`
* blind listening package: **prepared**

Observed / Inference / Experimental choice are kept apart throughout. Every variant is rendered by the *existing, unchanged* frame compiler and synthesiser.

## 1. What the binding replaces (Part 1)

**Observed.** The Composer instrument before binding is `ai/composition.py:map_instrument_character(character)`, which returns `(distortion byte, IREnvelope(attack,decay,sustain,release), role)`; an `AIInstrumentDef` may override any of those fields explicitly. `binding.py:_rebuild_song` then writes, per bound instrument:

```text
distortion            <- the profile's generator byte        (replaces)
envelope              <- composition explicit > profile > character default
audctl                <- the profile's audctl_mode           (replaces / adds a constraint)
is_16bit              <- True for a PAIR profile
profile_id/fingerprint<- provenance
uses_16bit_bass       <- song-level, OR-ed with any PAIR profile
pitch, velocity, tempo, channel allocation, patterns -> NOT touched
```

**Observed.** Which Composer parameters exist before binding: generator (distortion), envelope (4 numbers), pitch (from the note), volume/velocity (from the note), AUDCTL (song-global), clock (derived from AUDCTL), 16-bit coupling (song-level + `is_16bit`), channel allocation (from patterns), role (from character).

**Observed — the hardware fact that bounds the hypothesis.**

* AUDC is ONE byte = (distortion_nibble << 5) | volume, so the generator nibble has no additive algebra: a profile's generator can only replace the nibble, never extend it.
* The envelope is a 4-number state machine (attack/decay/sustain/release); there is no 'base + modifier' algebra, only field-wise substitution.
* AUDCTL is a song-global byte (resolve_audctl_mode OR-s instrument requirements and the song's uses_16bit_bass), so a profile's clock is a global constraint, not a channel property.
* Pitch is the note's (AUDF derived from midi + audctl) and volume is the note's velocity; neither is an IRInstrument field, so no profile fact can decorate them.

## 2. The variants (Parts 3-6)

| variant | what it does | composer fields kept |
| :--- | :--- | :--- |
| A COMPOSER_BASELINE | no profile at all | all |
| B PROFILE_REPLACEMENT | the existing `apply_profile_binding` path, unchanged | none of the three |
| C PROFILE_DECORATION | the profile's generator only | envelope, audctl, clock |
| D SELECTIVE_DECORATION | the profile's generator + attack/release | decay, sustain, audctl |

**Experimental choice.** C and D are the *smallest defensible* decorations. The generator is a single nibble with no additive algebra, so C swaps the generator and keeps the Composer's dynamics. D adds the profile's *transient* (attack/release) while keeping the Composer's decay and sustain — the envelope has no merge algebra either, only field-wise substitution, so 'transient vs body' is the stated (arguable) split. Both keep the Composer's clock; neither touches the note, its velocity or channel allocation.

## 3. Test material (Parts 7-8, 14)

**Experimental choice.** Six cases, chosen by a rule stated before any audio was inspected: one melodic, one percussive, one bass, one high/bell, one profile that collapsed into a duplicate group, one whose generator clearly differs from the default, and one PAIR/16-bit case. The phrase is identical for A/B/C/D in every case; no normalization, EQ or compression is applied beyond the synthesiser's own peak fit.

| case | character | joined | profile | why |
| :--- | :--- | :--- | :--- | :--- |
| lead_clean | bright_lead | False | pokey_ref_0657f037 | melodic: a $A pure-tone lead against a $A pure-tone profile (generator agrees) |
| lead_noised | bright_lead | False | pokey_ref_2de893a6 | melodic vs $8 direct noise: the profile's generator clearly differs from the default |
| perc_buzz | percussion | False | pokey_ref_1efd9336 | percussive: a $8-noise character against a $6 gated-buzz profile |
| bass8_poly4 | bass | False | pokey_ref_0bd72343 | 8-bit bass character against a $C poly4 profile |
| bell_gated | bell | False | pokey_ref_af009fe0 | high/bell character against a $0 gated-noise profile |
| dup_pair16 | bass | True | pokey_ref_089a0846 | PAIR/16-bit: a coupled $C profile, and a representative of duplicate group 1 |

**Observed.** Technical failures are recorded, never replaced: none.

## 4. Byte-level proof (Part 9)

**Observed.** For every case and variant: the WAV hash, the frames that differ from A, the changed POKEY columns, and the differing-sample count. A variant that was meant to decorate one field but changes several columns would be visible here.

| case | v | label | wav sha256 | Δframes | first Δframe | changed columns | Δsamples | rms |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| lead_clean | A | COMPOSER_BASELINE | d20b563df06a | 0 | — | — | 0 | 0.4127 |
| lead_clean | B | PROFILE_REPLACEMENT | 551058ee479d | 66 | 1 | AUDC1 | 60855 | 0.1299 |
| lead_clean | C | PROFILE_DECORATION | d20b563df06a | 0 | — | — | 0 | 0.4127 |
| lead_clean | D | SELECTIVE_DECORATION | d20b563df06a | 0 | — | — | 0 | 0.4127 |
| lead_noised | A | COMPOSER_BASELINE | d20b563df06a | 0 | — | — | 0 | 0.4127 |
| lead_noised | B | PROFILE_REPLACEMENT | 6b0599d47ab2 | 70 | 0 | AUDC1 | 61655 | 0.0961 |
| lead_noised | C | PROFILE_DECORATION | 15a7a35a868e | 70 | 0 | AUDC1 | 61655 | 0.3750 |
| lead_noised | D | SELECTIVE_DECORATION | 15a7a35a868e | 70 | 0 | AUDC1 | 61655 | 0.3750 |
| perc_buzz | A | COMPOSER_BASELINE | cec392386cb6 | 0 | — | — | 0 | 0.1509 |
| perc_buzz | B | PROFILE_REPLACEMENT | f82fe3844a25 | 70 | 0 | AUDC1 | 61709 | 0.1475 |
| perc_buzz | C | PROFILE_DECORATION | f82fe3844a25 | 70 | 0 | AUDC1 | 61709 | 0.1475 |
| perc_buzz | D | SELECTIVE_DECORATION | f82fe3844a25 | 70 | 0 | AUDC1 | 61709 | 0.1475 |
| bass8_poly4 | A | COMPOSER_BASELINE | 64ce68a7e912 | 0 | — | — | 0 | 0.2578 |
| bass8_poly4 | B | PROFILE_REPLACEMENT | 86298e52582e | 70 | 0 | AUDC1 | 61695 | 0.3699 |
| bass8_poly4 | C | PROFILE_DECORATION | 64ce68a7e912 | 0 | — | — | 0 | 0.2578 |
| bass8_poly4 | D | SELECTIVE_DECORATION | 289dea153533 | 57 | 0 | AUDC1 | 61695 | 0.3209 |
| bell_gated | A | COMPOSER_BASELINE | 0a78b89f9ccd | 0 | — | — | 0 | 0.5246 |
| bell_gated | B | PROFILE_REPLACEMENT | c93a65d28739 | 70 | 0 | AUDC1 | 61712 | 0.5259 |
| bell_gated | C | PROFILE_DECORATION | c93a65d28739 | 70 | 0 | AUDC1 | 61712 | 0.5259 |
| bell_gated | D | SELECTIVE_DECORATION | c93a65d28739 | 70 | 0 | AUDC1 | 61712 | 0.5259 |
| dup_pair16 | A | COMPOSER_BASELINE | 0940fc28d510 | 0 | — | — | 0 | 0.2575 |
| dup_pair16 | B | PROFILE_REPLACEMENT | df312acb2335 | 70 | 0 | AUDF1, AUDF2, AUDC2, AUDCTL | 61682 | 0.2578 |
| dup_pair16 | C | PROFILE_DECORATION | 64ce68a7e912 | 70 | 0 | AUDC2 | 61683 | 0.2578 |
| dup_pair16 | D | SELECTIVE_DECORATION | 64ce68a7e912 | 70 | 0 | AUDC2 | 61683 | 0.2578 |

## 5. Field perturbation / information flow (Part 10)

**Observed.** Per profile field: whether replacement writes it, whether decoration writes it, and whether that field, applied alone, reaches the IR, the frames and the WAV. `pitch/base` and `volume` have no IRInstrument field: they are the note's.

**lead_clean** (profile `pokey_ref_0657f037`)

| field | B replacement | C decoration | reaches IR | reaches frames | changes WAV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| generator | False | False | False | False | False |
| envelope | True | False | True | True | True |
| pitch/base | False | False | False | False | False |
| volume | False | False | False | False | False |
| audctl | True | False | True | False | False |
| clock | True | False | True | False | False |
| pairing | False | False | False | False | False |

**lead_noised** (profile `pokey_ref_2de893a6`)

| field | B replacement | C decoration | reaches IR | reaches frames | changes WAV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| generator | True | True | True | True | True |
| envelope | True | False | True | True | True |
| pitch/base | False | False | False | False | False |
| volume | False | False | False | False | False |
| audctl | True | False | True | False | False |
| clock | True | False | True | False | False |
| pairing | False | False | False | False | False |

**perc_buzz** (profile `pokey_ref_1efd9336`)

| field | B replacement | C decoration | reaches IR | reaches frames | changes WAV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| generator | True | True | True | True | True |
| envelope | False | False | False | False | False |
| pitch/base | False | False | False | False | False |
| volume | False | False | False | False | False |
| audctl | True | False | True | False | False |
| clock | True | False | True | False | False |
| pairing | False | False | False | False | False |

**bass8_poly4** (profile `pokey_ref_0bd72343`)

| field | B replacement | C decoration | reaches IR | reaches frames | changes WAV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| generator | False | False | False | False | False |
| envelope | True | False | True | True | True |
| pitch/base | False | False | False | False | False |
| volume | False | False | False | False | False |
| audctl | True | False | True | False | False |
| clock | True | False | True | False | False |
| pairing | False | False | False | False | False |

**bell_gated** (profile `pokey_ref_af009fe0`)

| field | B replacement | C decoration | reaches IR | reaches frames | changes WAV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| generator | True | True | True | True | True |
| envelope | False | False | False | False | False |
| pitch/base | False | False | False | False | False |
| volume | False | False | False | False | False |
| audctl | True | False | True | False | False |
| clock | True | False | True | False | False |
| pairing | False | False | False | False | False |

**dup_pair16** (profile `pokey_ref_089a0846`)

| field | B replacement | C decoration | reaches IR | reaches frames | changes WAV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| generator | True | True | True | True | True |
| envelope | False | False | False | False | False |
| pitch/base | False | False | False | False | False |
| volume | False | False | False | False | False |
| audctl | True | False | True | True | True |
| clock | True | False | True | True | True |
| pairing | False | False | False | False | False |

## 6. Reference comparison (Part 11)

**Observed.** Stage 9C/11B descriptors (centroid, bandwidth, flatness, RMS) and the band-energy distance to the archaeology `reference_replay.wav`, for A/B/C/D, where a reference exists.

| case | variant | centroid Hz | bandwidth Hz | flatness | dist to ref | rms |  |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| lead_clean | reference | 4754 | 5973 | 0.510 | — | — | — |
| lead_clean | A | 6240 | 6546 | 0.511 | 0.033675 | 0.4127 | — |
| lead_clean | B | 5864 | 6410 | 0.553 | 0.020493 | 0.1299 | — |
| lead_clean | C | 6240 | 6546 | 0.511 | 0.033675 | 0.4127 | — |
| lead_clean | D | 6240 | 6546 | 0.511 | 0.033675 | 0.4127 | — |
| lead_noised | reference | 5300 | 6114 | 0.601 | — | — | — |
| lead_noised | A | 6240 | 6546 | 0.511 | 0.175546 | 0.4127 | — |
| lead_noised | B | 4063 | 5656 | 0.486 | 0.052799 | 0.0961 | — |
| lead_noised | C | 4190 | 5731 | 0.501 | 0.064148 | 0.3750 | — |
| lead_noised | D | 4190 | 5731 | 0.501 | 0.064148 | 0.3750 | — |
| perc_buzz | no reference | — | — | — | — | — | — |
| bass8_poly4 | no reference | — | — | — | — | — | — |
| bell_gated | no reference | — | — | — | — | — | — |
| dup_pair16 | reference | 5761 | 6119 | 0.624 | — | — | — |
| dup_pair16 | A | 6157 | 6521 | 0.522 | 0.097744 | 0.2575 | — |
| dup_pair16 | B | 7141 | 6417 | 0.611 | 0.034305 | 0.2578 | — |
| dup_pair16 | C | 7092 | 6405 | 0.615 | 0.030029 | 0.2578 | — |
| dup_pair16 | D | 7092 | 6405 | 0.615 | 0.030029 | 0.2578 | — |

## 7. The two hypotheses (Part 12)

**Observed.** H1 — decoration preserves the Composer envelope where replacement does not — holds in **3 of 6** usable cases (`lead_clean, lead_noised, bass8_poly4`). H2 — decoration still changes the sound — holds in **4 of 6** cases (`lead_noised, perc_buzz, bell_gated, dup_pair16`).

**Observed.** Both hold together in **1** case(s) (`lead_noised`); C sits between the baseline and the reference in **2** reference-bearing case(s).

**Inference.** A successful *compromise* needs both H1 and H2 in the same case. Where H1 holds in nearly every case but H2 does too, the interesting question is not whether decoration changes the sound, but whether what it changes is *useful* — which the reference distance and, if justified, a listener decide.

## 8. Listening (Part 13)

**Experimental choice.** decoration changes the sound and comes closer to the archaeology reference than replacement in at least one case, so a C-vs-A / C-vs-B blind comparison tests a usefulness claim rather than only an audible one. Package: **prepared**.

## 9. Selection integrity (Part 14)

**Observed.** The six cases were fixed in `stage12a.CASES` before the experiment ran; none was added, removed or swapped after seeing any audio. A case that failed technically is recorded as a failure in §3, not replaced.

## Final report — the eight questions

**1. What does the current binding replace?** `binding.py:_rebuild_song` writes, per bound instrument, `distortion`, `envelope`, `audctl` and (for a PAIR) `is_16bit`, plus the provenance pair, and OR-s the song-level `uses_16bit_bass`. It does **not** touch pitch, velocity, tempo, channel allocation or patterns. The union of IR fields actually changed across cases: `audctl, distortion, envelope, profile_fingerprint, profile_id`.

**2. What information does replacement destroy?** The Composer's *character-derived* envelope and clock: `map_instrument_character` turns `character` into a distortion byte and a 4-number envelope, and because those are not 'explicit' on the composition document the profile's envelope wins. Measured: replacement changed the Composer envelope in **3 of 6** usable cases; decoration changed it in **0**.

**3. Can profile information be applied as decoration?** Per field, from the perturbation tables and the hardware facts (§1, §5):

| field | classification | why |
| :--- | :--- | :--- |
| generator (distortion) | DECORATIVE (by substitution) | the nibble can be swapped into the Composer instrument without touching the rest; it cannot be *added* — AUDC is one byte |
| envelope | DECORATIVE (by substitution) | no merge algebra; field-wise substitution is possible (C keeps it, D substitutes attack/release) |
| AUDCTL | GLOBAL_CONSTRAINT | one song-global byte; applying it changes the clock of every channel, not just the decorated one |
| clock | GLOBAL_CONSTRAINT | derived from AUDCTL, so the same constraint |
| pitch / base | NOT_EXPRESSIBLE | the note owns the pitch; the profile's base is a reference, not a register the binding may write |
| volume | NOT_EXPRESSIBLE | the note's velocity owns the peak; only the envelope shapes it |
| pairing (16-bit) | PAIR_ONLY | coupling is a scope fact; a PAIR instrument keeps it, and decoration must not steal a channel |

**4. Does decoration preserve Composer tuning?** Yes, measurably: decoration (C) keeps the Composer envelope and clock in every case (**3 of 6** preserve what replacement destroys).

**5. Does decoration transfer profile character?** Yes, measurably: C changes the WAV in **4 of 6** usable cases (different WAV hash, changed AUDC column). Whether the change is *useful* is the open question.

**6. Which fields provide the best trade-off?** By the measurement, the **generator** is the only field that both changes the sound and can be applied without a global side effect; the envelope is decorative but transient-only, and AUDCTL/clock cannot be decorated at all. The defensible subset is *the generator, optionally with the profile's transient*.

**7. Does human listening support the result?** A package is justified and prepared; its result is not yet known.

**8. The single recommended next step.** **Run the small blind listening package (C vs A, C vs B, D vs A, D vs B).**

### Verdict

**Observed.** H1 holds in 3/6 cases and H2 in 4/6; both hold together in 1.

**Inference.** **HYPOTHESIS SUPPORTED (mechanically; perceptually only if the listening package confirms it)**. Decoration preserves Composer tuning and still changes the sound; the stage's decision rule additionally requires a *perceptually meaningful* difference, which the quantitative analysis alone cannot establish, so a positive conclusion is not declared here.

**Against the brief's decision rule.** A positive conclusion needs (1) Composer information preserved better than with replacement, (2) profile character transferred, (3) a measurable and preferably perceptually meaningful difference, and (4) determinism and explainability. (1), (2) and (4) hold; (3) is measurable but its perceptual half is **unrun**, so this stage does **not** declare `HYPOTHESIS SUPPORTED`. The honest label today is *mechanically supported, perceptually unestablished*, and the blind package prepared in §8 is exactly the missing evidence — not another implementation round.

## 10. Reproducibility

Every number is a pure function of the profiles, the bank and the archaeology reference WAVs below (SHA-256); no timestamp appears in any artefact, and the case list is fixed in source. Two runs are byte-identical.

```json
{
  "archaeology/pokey_ref_0657f037/reference_replay.wav": "bbb9ffdac6be1f17060c57f161ef217b0eac3bd969e9aac474a4f6ba3fe99060",
  "archaeology/pokey_ref_089a0846/reference_replay.wav": "aecbedf0940a55f91f72e7fea9b50296bf2592667646294b04e42863f237ddb6",
  "archaeology/pokey_ref_2de893a6/reference_replay.wav": "6ceb3436200a4bf75341a5ce12168cbd9b6fe45c199c15e94207573e342aaebe",
  "bank/profiles/pokey_ref_0657f037.json": "d33d5f97f948a75eeb08d7008084d9910a43bae729d4f18361d2be53b2b3c01e",
  "bank/profiles/pokey_ref_089a0846.json": "ca336575bfc773971b41e18fbce8361c2128cedffff072abac6fdb0207ae096e",
  "bank/profiles/pokey_ref_0bd72343.json": "ba3dfd583ff2036ad0527f04e14735ce96dbed9489f73f1f3641f42bed107b57",
  "bank/profiles/pokey_ref_1efd9336.json": "af6f206cbd28ef154d9fb84f8c1686885db5c6463a3eecffb9a5d5ca6ad651d8",
  "bank/profiles/pokey_ref_2de893a6.json": "5772ebb947d1200286e75823e00dd45547ef815031484c8dc8a11678d1f660f2",
  "bank/profiles/pokey_ref_af009fe0.json": "c7989e9983193ed08fad6f5e69328eb7f46e404485bef03c9d8a9f49d7113dab",
  "bank/registry.json": "b78faec3738cc127d21ae571f526f5761a4292f302eb07de7ba08794746a81fb"
}
```


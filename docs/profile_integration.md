# POKEY Sound Profile Integration (Stage 9)

> The composition describes musical intent. The profile describes POKEY realization.

This document records the first product integration between the two projects: an existing
Atari Music Composer composition is rendered with a POKEY sound profile that was measured by
the **POKEY Sound Archaeology** project from a real Atari 8-bit tune.

Nothing in the composition language, the AI schema, the DSL, the prompts or the musical
structures changed. A profile is attached from **outside** the composition, at rendering
time, by `profile_id` — never by character, role or name.

---

## 1. Why profiles are outside the composition

A profile is not musical intent. It is a set of measured POKEY register facts — a generator
(distortion), a clock/coupling configuration (AUDCTL), a divider mode (8-bit or a joined
16-bit pair), and a measured envelope — for one voice.

Putting that in the composition would mean:

* the AI would have to reason about AUDCTL, AUDF, clocks and distortion nibbles, which is
  exactly the hardware knowledge the composer is designed not to need;
* a composition would stop being portable: re-rendering the same music with a different
  sound would require editing the music;
* profile choice would become a musical decision, turning a curation problem into a language
  change.

So the split is enforced in code:

| Layer | Owns | Does not know about |
| :--- | :--- | :--- |
| DSL / JSON, AI prompts, `AICompositionDoc`, `MusicSong` (Music IR) | notes, durations, rests, velocity, tempo, form, arrangement, semantic instrument identity | profiles, POKEY registers |
| `IRSong` (POKEY IR) | channel roles, distortion, envelopes, 8-/16-bit mode, AUDCTL | where the profile came from |
| `sound_profiles` package (new) | bank loading, binding, hardware realization | music: it never changes a note |

The binding layer's whole vocabulary is *hardware realization*: generator, AUDCTL, divider
mode, envelope shape. It cannot express a pitch, a duration or a velocity, and its tests
assert that it does not change them.

**Nothing in `atari_music.ai` imports the profile package.** The composition-side modules are
untouched; the only hook is a deliberately generic, profile-agnostic
`result_transform` on `build_xex_from_composition`.

---

## 2. Profile binding mechanism

The composition does not name a profile. A separate binding document does:

```json
{
  "schema": "atari-music/sound-profile-binding/1",
  "bank": "bank",
  "instruments": {
    "bass": "pokey_ref_3627798b",
    "lead": "pokey_ref_a8c81a84"
  }
}
```

* **keys** are the composition's instrument ids (`AIInstrumentDef.id`); an instrument's
  display *name* also resolves, but an ambiguity is an error rather than a guess.
* **values** are exact profile ids. There is no fuzzy matching, no nearest match and no
  automatic substitution — an unknown id is refused.
* **`bank`** is optional and is resolved relative to the binding file, so a binding and its
  bank can be moved together. The CLI's `--sound-bank` overrides it.
* the binding is **optional**: with no binding, nothing in this package runs.

It is applied to the compiled result, between the POKEY IR and the two output paths:

```
composition (DSL / JSON)
    ↓  parse + validate            unchanged
AICompositionDoc                   unchanged
    ↓  interpret_composition_to_music_ir
MusicSong (Music IR)               unchanged
    ↓  compile_composition_to_pokey_ir
IRSong (POKEY IR)                  ← the profile enters here and only here
    ↓  apply_profile_binding(...)     (profile-aware hardware realization)
IRSong (profile-aware)
    ↓                    ↓
WAV frames          MADS assembly → XEX
```

`apply_profile_binding(result, binding, bank, composition=None) -> MusicGenerationResult`
returns a copy whose `pokey_ir` carries the profile's hardware facts. Because both output
paths read `result.pokey_ir`, they cannot disagree about the configuration (see §9, §10).

---

## 3. Profile registry

A bank is a directory the archaeology project writes:

```
bank/
    registry.json            catalogue: id, scope, file, playable_fingerprint, status
    profiles/
        pokey_ref_XXXXXXXX.json     one PlayableSoundProfile each
```

`load_sound_profile_bank(path)` loads it and, by default, **recomputes every
`playable_fingerprint`** (SHA-256 over the canonical JSON of every field except the
fingerprint itself) and refuses a mismatch. A profile whose content was edited no longer
loads.

```python
from atari_music.sound_profiles import load_sound_profile_bank
bank = load_sound_profile_bank("bank")
profile = bank.get("pokey_ref_3627798b")   # exact; raises PROFILE_NOT_FOUND otherwise
```

Useful views over a loaded bank:

| call | what it gives |
| :--- | :--- |
| `bank.ids()` | every profile id, sorted |
| `bank.of_scope("VOICE" \| "PAIR")` | the profiles of one scope |
| `bank.of_status("PLAYABLE" \| …)` | the profiles the publishing audit gave one status |
| `bank.renderable()` | the profiles this consumer is willing to render |
| `bank.status_totals()` | how many profiles carry each status |

The bank is **self-sufficient**. Loading it needs no emulator, no SAP file, no reference
audio and no archaeology code — the profile documents are the interface. (A test asserts that
no `pokey_sound_architecture`/`pokey_sound_archaeology` module is imported by the loader.)

The registry's own `bank.note` says the bank is "a working set for format validation, not a
recommended library: no profile was selected, ranked or named". This consumer reports that
text verbatim in `describe_binding`; membership in a bank is never presented as a judgement
about how a profile sounds.

### 3.1 Two banks, two purposes

Both exist in this project and they are not interchangeable:

| | **experimental integration bank** | **full research bank** |
| :--- | :--- | :--- |
| where | generated into `examples/sound_profiles/`; the tracked inputs are in `tests/data/sound_profiles/` | `tests/data/sound_profiles/bank/` |
| size | 4 profiles (the Stage 9 demo set) | **67 profiles** — the whole published library |
| chosen by | hand, to prove the integration (2 VOICE, 2 PAIR, four generators) | nothing: it is the library as published |
| purpose | the minimal proof that a profile changes the render | complete technical access to the library |
| statuses | all four `PLAYABLE` | 22 `PLAYABLE`, 39 `PLAYABLE_WITH_LIMITATION`, 6 `MEASUREMENT_ONLY` |

**67 profiles is not 67 recommended instruments.** The full bank is the complete *technical*
library, including profiles whose measured envelope the composer cannot express and profiles
that describe no sound at all. It exists so the library is available and verified behind a
stable interface; it is not a palette, and final curation is a separate, later stage. No
profile in it was renamed, regrouped, ranked or removed, and no profile file was modified by
publication — every one is byte-identical to what the archaeology project published.

### 3.2 The published status, and what it enforces

The archaeology CLI records each profile's audited verdict in its registry entry when it is
given the audit report (§13), alongside the codes behind it. A consumer then knows what it is
holding without reimplementing the audit:

```json
{
  "profile_id": "pokey_ref_076852dd",
  "file": "profiles/pokey_ref_076852dd.json",
  "scope": "VOICE",
  "playable_fingerprint": "…",
  "status": "MEASUREMENT_ONLY",
  "blocking_issues": ["SILENT_PROFILE"],
  "limitation_codes": ["ENVELOPE_NOT_MEASURED"],
  "consumer_gap_codes": ["GESTURE_NOT_RENDERABLE_BY_CONSUMER"]
}
```

The keys are **additive**: a registry built without them is unchanged, and a bank that
publishes no status still loads — an unstatused profile is not judged, because a pipeline that
had no verdict cannot be second-guessed.

What the consumer enforces:

| status | renderable? | behaviour |
| :--- | :--- | :--- |
| `PLAYABLE` | yes | renders |
| `PLAYABLE_WITH_LIMITATION` | yes | renders; the recorded limitation and consumer gaps are reported in `describe_binding`, not hidden |
| `MEASUREMENT_ONLY` | **no** | refused with `PROFILE_STATUS_NOT_RENDERABLE`, naming the profile, the status and the blocking codes |
| `INTERNALLY_CONTRADICTORY` / `UNPLAYABLE` / `CONTEXT_DEPENDENT` | **no** | refused the same way |
| an unrecognised value | **no** | refused with `PROFILE_STATUS_UNKNOWN`, so a future verdict cannot pass silently |
| absent | not judged | loads and renders; a bank that predates the audit is not broken |

A refused profile is refused **loudly**: it is never swapped for a default, never skipped, and
never rendered as a silence that looks like a working instrument.

### 3.3 The Stage 9C listening experiment

The status table above says what a profile *permits*. It says nothing about which profiles are
worth keeping — that is a perceptual question, and the library cannot answer it. Stage 9C builds
the experiment that asks a human, and nothing in it may decide for them.

It produces a self-contained folder (`examples/sound_profile_listening/`), generated by
`prepare-listening-test-9c`, and it is the only Stage 9C artefact:

```
examples/sound_profile_listening/
    README.md            how to run it, and what it does not test
    index.html           the listening interface — neutral labels only, no server, no Python
    manifest.json        PRIVATE: sample -> profile, features, levels, gestures, refusals
    audio/
        sample_001.wav   one stimulus per renderable profile (61)
        song_01_a.wav    6 real-song pairs, default vs profile-bound, sides blinded
    evaluation_profiles.csv   empty templates, ids pre-filled, no answers
    evaluation_ab.csv
    evaluation_songs.csv
```

Three experiments, all blinded and shuffled by a recorded seed:

| part | what is compared | questions |
| :--- | :--- | :--- |
| 1 | one renderable profile at a time (61 samples) | distinctiveness, usefulness, Atari character, free-text character description, optional confidence |
| 2 | two profiles, 30 stratified A/B trials | similarity, preference, character difference, comment |
| 3 | one real song, default vs profile-bound (6 pairs) | better sound, more character, more convincing Atari, overall difference, comment |

**What is held constant.** Every profile realizes the *same* 32-step phrase at the same tempo,
velocity, duration and pitch, on POKEY channel 1; the only variable is the profile. A `PAIR`
profile gets the same phrase with the composition declaring the 1+2 join, because a pair cannot
be realized any other way. Every stimulus is set to the same peak (-0.92 dBFS) by a single gain
— no compression, no EQ, no clipping — and the original and final peak **and** RMS of every
sample are recorded, so loudness stays a measurable property rather than an assumption. The A/B
trials reuse those same stimulus files, which is the strongest available guarantee that
"everything else is identical". The song pairs apply one *shared* gain to both sides and cut an
identical excerpt, so the composition is untouched on both sides.

**What it does not settle.** No gesture is invented: the player has no per-channel macro, so a
profile that measured a contour is heard as a static tone (§14.1). Nothing is renamed, ranked or
selected — the analysis reports medians, distributions, correlations, vote counts, the listener's
own words, and evidence-based *candidate* groups with their thresholds stated, and it refuses to
declare a library. Blinding is enforced by construction: the interface, the file names and the
README never mention a profile id, a source song, a generator family, AUDCTL, a scope or a
status; that mapping exists only in `manifest.json`.

A profile whose measured envelope is wider than the composer's fields can express (the audited
`ENVELOPE_FRAME_ABOVE_CONSUMER_MAX` gap) is refused by the binding — correctly, rather than
clamped (§7). For exactly two profiles in the bank the experiment declares that **one** field
from the composer's own character default, so the profile is still heard, and records the
substitution per sample in `manifest.json` (`envelope_source`, `envelope_refusal`). The listener
is not told which samples those are.

### 3.4 What the listening actually found (Stage 9D)

The listening was performed by a human and analysed by `analyze-listening-test-9d`
([stage9d.py](../src/atari_music/stage9d.py)); the full result is
[stage9d_human_listening_results.md](stage9d_human_listening_results.md). Four findings bear
directly on the integration contract above, and one of them is negative:

1. **The library is audibly smaller than its profile count.** The 61 renderable profiles produce
   only **37 distinct audio signals**; 24 profiles render *byte-identical* audio to another
   profile. The profiles differ in measured pitch/volume gesture behaviour that the player cannot
   render (§14.1), so they differ on paper and not in sound. Any future "how many sounds do we
   have" claim must be made against rendered audio, not profile ids.
2. **Binding profiles to real songs made them worse in this test.** Across six songs the
   composer's own default instruments won 5 and the profile-bound render won 0, unanimously on
   all three questions (the sixth was a tie). Six songs is not a population, but the direction is
   consistent and it is the reason stage 9D's closing answer is **NO** to moving on to selection.
   The bindings in `examples/songs/` were chosen by generator family, not by listening evidence —
   that is the first thing to revisit.
3. **The similarity metric is blind to level.** The band-energy cosine distance used for
   stratification tracked perceived similarity well (Spearman −0.68, n=30), but it is computed on
   a *normalized* spectrum, so a profile sustaining 12 dB lower scores as identical to one that
   does not. The listener did not agree, and their similarity ratings correlate with the level gap
   almost as strongly. A level term belongs in the metric.
4. **The listener keys on generator family, the metric on the spectrum.** Every profile the
   listener called "noisy" is a noise/poly generator (`$0`, `$8`) and every one called "clean" is
   `$A`/`$C`; the two family sets are disjoint. Spectral flatness does not separate them.

What the status table in §3.2 says is what *renders*, and what §3.3/§3.4 add is that rendering
and being *useful* are different claims: the library renders, and this experiment is the first
evidence about whether it is worth rendering. It says: as isolated sounds, yes; as a way to make
a song better, not yet.

### 3.5 Why that happened (Stage 9E)

Stage 9E diagnoses the two results above instead of acting on them
([stage9e.py](../src/atari_music/stage9e.py), `analyze-listening-test-9e`; full report
[stage9e_perceptual_renderer_gap.md](stage9e_perceptual_renderer_gap.md), machine-readable
results in `reports/stage9e/`). It is read-only, and it measures the pipeline rather than reading
it: the profile document is wrapped in a mapping that records every path the real binding touches,
each IR field is perturbed to see which frames it changes, each frame column is zeroed to see
whether the audio changes — and its own re-render is compared **byte for byte** with the stimulus
the listener heard (61 of 61 identical), so its claims are about the pipeline that produced the
experiment. Three facts, each measured:

1. **The binding reads 13 of the 232 documented leaf paths a profile defines.** `_rebuild_song`
   writes six fields onto the instrument — the generator nibble, three envelope frame counts, the
   sustain level and AUDCTL (plus the pair flag) — and stages 5–6 never see the profile document
   at all. The binding path described in §2 is therefore already complete: `apply_profile_binding`
   receives the profile and returns an `IRSong`, and the profile cannot reach the rendered audio
   except through those six values.
2. **All 6 duplicate groups are lost at exactly that boundary.** For every group the documents
   differ (by 125–691 leaf paths) while the bound IR is already identical, so frames and WAV must
   be too. The classification is `representation_duplicate` for 6 of 6 groups, 30 profiles; no
   group needed a renderer or quantization explanation. §11 of the report states the consequence
   carefully: a byte-identical WAV does **not** mean a redundant profile, only redundant *today*.
3. **The whole-song loss is not a level artefact.** Both sides of each A/B pair were rendered at
   one shared gain, exactly as in Stage 9C; the profile-bound side was not louder (median RMS
   delta −2.39 dB). The binding replaced each instrument's generator and/or envelope, so the two
   sides differ in timbre and articulation, and the composer's own instruments — designed around
   the piece — won. That is a musical-interpretation gap, and it is why step 1 of the recommended
   work is to re-bind the six songs from listening evidence rather than to change the engine.

The consequence for the contract in §1–§3: the gap is **representation first** (the document holds
most of what was measured and the IR cannot express it), **musical interpretation second** (which
profile was chosen for which role), and **renderer only marginally** (the frame compiler does use
every field the binding writes, except a few measured inert, such as `envelope.decay_frames`,
which changes no frame for 8 of 61 profiles). The capabilities that would close the first gap are
ranked by evidence in §12 of the report — measured volume contour and pitch trajectory first —
and **none of them is implemented**: carrying them changes what the listener hears, so it
invalidates the current perceptual ranking and needs a new listening test.

---

## 4. VOICE integration

A `VOICE` profile is a single 8-bit channel's worth of hardware: one generator, one clock
configuration, one envelope, one divider per note.

Binding one to an instrument changes exactly four things on that instrument:

| IR field | comes from |
| :--- | :--- |
| `IRInstrument.distortion` | the profile's generator nibble, shifted into the AUDC bits (`"$8"` → `0x80`) |
| `IRInstrument.envelope` | the profile's measured envelope, subject to §7 precedence |
| `IRInstrument.audctl` | the profile's `audctl_mode` (its *requirement*; see §6) |
| `IRInstrument.profile_id` / `.profile_fingerprint` | provenance |

`is_16bit` stays `False`, and the instrument keeps its channel: a VOICE profile is realized
on whichever channel the composition already assigned, which is what the archaeology audit
saw (`pokey_ref_a8c81a84` was measured on the source's channel 3 and renders perfectly well
on the Composer's channel 3 *or* any other plain 64 kHz channel).

If a bound instrument sounds on more than one channel, the profile is realized independently
on each; this is reported in `describe_binding` as a note rather than silently accepted.

---

## 5. PAIR integration

A `PAIR` profile is a joined **16-bit** pair. Its document says so explicitly:

```json
"channels": { "audible_channel": 2, "companion_channel": 1, "divider_bits": 16,
              "pair": "1+2", "requires_simultaneous_channels": true },
"hardware": { "audctl_mode": "$50", "clock_mode": "joined16:1+2:divider_msb:1.79MHz" }
```

This is the same pair layout the Composer's own `BASS 16BIT` uses — channel 1 carries the low
divider byte and is muted, channel 2 carries the high byte and the AUDC — but a **different
clock**. The Composer's convention is `$10` (join 1+2 at 64 kHz); the archaeology pair is
`$50` (join 1+2 with channel 1 at 1.79 MHz), and the divider offsets differ: `N + 1` versus
`N + 7`.

Those are different sounds for the same note. The integration therefore **never** converts one
into the other:

* the profile's `audctl_mode` is written into AUDCTL as given (`$50` stays `$50`);
* the divider arithmetic follows the clock: `pokey_hw.audf16_from_hz(f, $50, 1)` applies the
  `+7` offset at 1.79 MHz, and `audf16_from_hz(f, $10, 1)` applies `+1` at 64 kHz;
* all 18 archaeology PAIR profiles are `1+2`; a profile declaring another pair is refused
  (`PROFILE_PAIR_CHANNEL_CONFLICT`) because the Composer implements only the one joined pair;
* two voices cannot both be bound to a PAIR profile (`PROFILE_PAIR_CHANNEL_CONFLICT`);
* channel 2 is the pair's high byte, so an instrument with notes there — or any *other*
  instrument with notes there — is refused (`PROFILE_PAIR_CHANNEL_CONFLICT`, carrying the
  existing `BASS16_CHANNEL_CONFLICT` code in its detail, since it is the same collision).

The Composer's existing `BASS 16BIT` feature is untouched: with no binding, `uses_16bit_bass`
still produces `$10` exactly as before.

---

## 6. Pitch handling

**The composition owns the note; the profile supplies the clock.**

```
composition note (MIDI) → frequency
      + profile's AUDCTL     → divider for that frequency
      → AUDF register(s)
```

* `pitch.base_hz` is **not the note**. It is the profile's reference frequency (what its
  gesture data is relative to); substituting it would replace the melody with one measured
  drone.
* `pitch.base_divider` is **evidence**, not a register value to copy: in ten archaeology
  profiles the two fields describe different instants (a defect the archaeology audit
  records, and one it deliberately left in the frozen artefacts).
* The composition's pitch is preserved bit-for-bit: the same note produces the same
  frequency, and only the divider that realizes it changes with the profile's clock.

Measured on the example (`bass`, note D-2 = MIDI 38, 73.416 Hz):

| | AUDCTL | divider | AUDF1 (low) | AUDF2 (high) |
| :--- | :--- | :--- | :--- | :--- |
| no binding (existing `BASS 16BIT`) | `$10` | `N+1` @ 64 kHz = 430 | `$AE` | `$01` |
| profile `pokey_ref_3627798b` | `$50` | `N+7` @ 1.79 MHz = 12071 | `$27` | `$2F` |

Both are correct realizations of the same D-2; they are simply different hardware.

`AUDF` is clamped to `$FE` before it reaches the tracker format, in both the WAV frame stream
and the exported assembly, exactly as before this stage — so a note whose divider byte would be
`$FF` is stored as `$FE` in **both** outputs rather than diverging (§10).

---

## 7. Volume handling

Contract precedence (archaeology `docs/composer_compatibility_contract.md` §5, C-5.1/C-5.2),
implemented field by field:

1. **The note's velocity is authoritative.** `peak_vol = min(15, max(0, IRNote.volume))` is
   unchanged, and the profile's `volume.peak_level` is **never** substituted: that number is
   what the *source segment* peaked at, and using it would delete the composer's dynamics.
   (In the example the lead carries velocity 13 while `pokey_ref_a8c81a84` measured a peak level
   of 12; the bound render still peaks at 13.)
2. **The envelope is the profile's unless the composition says otherwise.** Per field:
   an explicitly declared `AIInstrumentDef.attack_frames` / `decay_frames` / `sustain_vol` /
   `release_frames` always wins; otherwise the profile's measured value is used; if the profile
   provides nothing, the character default from `map_instrument_character` stays.
   `describe_binding` reports the source of every envelope field (`composition`, `profile`,
   `character_default`), so the claim is auditable.
3. **`envelope.confidence` is carried into the report** — `0.55` is not the same claim as
   `0.9`.
4. A profile whose measured envelope falls outside the composer's expressible range
   (`0..15` frames) is **refused** (`PROFILE_ENVELOPE_OUT_OF_RANGE`) rather than silently
   clamped, because clamping would change the requested envelope without saying so.
5. `volume.behavior == "modulated"` and the measured per-frame volume contour are **not**
   reproduced by default: the player has no per-frame volume modulation from an instrument, so a
   binding that silently added one would change every existing rendering. This is the archaeology
   audit's `VOLUME_MODULATION_NOT_REPRODUCIBLE` consumer gap. Stage 10B builds the capability that
   can close it, behind an explicit switch — see §13.4 — and reports that the XEX path still cannot
   carry it.

**The contour, when it is asked for (Stage 10B).** `apply_profile_binding(..., volume_contour=...)`
is off by default and takes `True`, `False`, or a set of binding keys (so one channel's gating
contour can be withheld while its neighbours take theirs). When it is on, `IRInstrument.volume_contour`
carries the profile's measured levels and the frame compiler applies

```
effective[i] = floor(volumes[i] * contour[i % span] / max(contour) + 0.5)   clamped to 0..15
```

which keeps the composer's velocity as the ceiling (the factor is ≤ 1, so it can only attenuate),
makes a static contour an exact no-op, and stops the source's absolute loudness from leaking. The
span restarts at every note onset. A measured level of 0 is **not transferred**: it means the source
was not sounding, which is timing rather than loudness. `export_mads_asm` refuses such a song with
`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`, because the note table and `player.asm` cannot reproduce a
per-frame contour.

---

## 8. Channel allocation

A profile's **source channel is provenance, not an assignment**.

* The composition decides which channel each voice plays on, exactly as before. No channel
  is moved, reserved or reassigned by the binding.
* What the binding checks is that the channel the composition already chose can **carry** the
  profile's configuration, by comparing the bits that govern that channel's pair:

  | profile bit | requirement |
  | :--- | :--- |
  | join bit of the pair (`$10` for 1+2, `$08` for 3+4) | set if the profile was measured joined, clear otherwise |
  | 1.79 MHz bit (`$40` for channel 1, `$20` for channel 3) | set if the profile was measured at that clock |
  | 15 kHz bit (`$01`) | matches the profile's base clock |

* Two profiles on different pairs do not conflict: AUDCTL bits that govern different channels
  are OR-ed, so a PAIR profile on 1+2 and a VOICE profile on channel 3 coexist, with channel 3
  still running at 64 kHz — which is real hardware behaviour, not an approximation.
* Two profiles that demand the *same* pair differently **do** conflict, and the binding raises
  `PROFILE_AUDCTL_CONFLICT` naming the channel, the effective AUDCTL and the exact bits that
  disagree.

`pokey_ref_a8c81a84` was measured on source channel 3, and the example realizes it on the
Composer's channel 3 because that is where the `lead` voice lives — not because the profile
said so.

---

## 9. WAV path

```
composition → Music IR → POKEY IR → profile-aware POKEY IR
    → compile_ir_to_pokey_frames(song) → (frames, 9) register stream
    → render_pokey_to_wav(frames, path)          [existing renderer, unchanged]
```

The existing Composer renderer remains the WAV renderer. The archaeology renderer is
**not** used and is not imported; only the profile *data* crosses the boundary, which keeps the
dependency clean (one small package, no research code).

The only change inside the frame compiler is that the AUDCTL byte is now resolved once
(`resolve_audctl_mode`) and passed into the divider conversions, so a channel's divider is
derived under the clock the profile specifies. With nothing bound, the resolved AUDCTL is
`$00` or `$10` and every divider is identical to before.

---

## 10. XEX path

The XEX path consumes the **same** profile-aware `IRSong`:

```
composition → profile-aware POKEY IR → export_mads_asm(song) → MADS + player.asm → .xex
```

Two things follow, and both are asserted by tests:

1. **WAV and XEX cannot disagree.** `export_mads_asm` writes the instrument table and the
   track event streams from the resolved AUDCTL and the same divider arithmetic the frame
   compiler uses, so the byte in the exported header is the byte the WAV frames carry. The
   XEX is built from the *transformed* result, via a profile-agnostic `result_transform` hook
   on `build_xex_from_composition`, not by re-deriving anything.
2. **The export header no longer lies.** It previously read
   `; Mode: 16-bit bass (AUDCTL=$50)` while writing `.byte $10`. It now prints the value that
   is written and describes it (`AUDCTL=$10 (16-bit pair Ch1+Ch2 at 64 kHz)`).

One coupled fix was needed for (1): the 16-bit bass **instrument table** hard-coded
`DISTORTION_PURE_TONE` for channel 2 while the frame compiler wrote channel 1's instrument
distortion into `AUDC2`. For the Composer's own 16-bit bass those coincide, but for a
profile-bound pair they do not — the WAV would carry `$C0` and the XEX `$A0`. Channel 2's
table entry now takes the same value the frame compiler writes.

---

## 11. Errors

Every failure is explicit and carries a stable code. A profile is never substituted, dropped,
downgraded, or silently reinterpreted.

| Code | Raised when |
| :--- | :--- |
| `PROFILE_BANK_MISSING` | the bank directory or its `registry.json` is absent |
| `PROFILE_BANK_SCHEMA_UNSUPPORTED` | `registry.json` is not valid JSON or not schema `pokey-sound-profile-registry-1.0` |
| `PROFILE_FILE_MISSING` | a registry entry names a profile file that is not there |
| `PROFILE_INVALID` | a profile document is malformed, has the wrong schema, or its `profile_id` disagrees with the registry |
| `PROFILE_FINGERPRINT_MISMATCH` | the profile's content does not hash to the fingerprint its registry entry publishes |
| `PROFILE_NOT_FOUND` | the requested `profile_id` is not in the bank (the message lists the ids that are) |
| `PROFILE_SCOPE_UNSUPPORTED` | the profile declares a scope other than `VOICE` / `PAIR` |
| `PROFILE_BINDING_MISSING` | the binding file does not exist |
| `PROFILE_BINDING_INVALID` | bad JSON, wrong `schema`, missing `instruments`, or `--sound-bank` without `--profile-bindings` |
| `PROFILE_BINDING_UNKNOWN_INSTRUMENT` | the binding names an instrument the composition does not declare (or matches several ambiguously) |
| `PROFILE_AUDCTL_CONFLICT` | the effective AUDCTL cannot give the profile the clock/coupling it needs on the channel it would realize on |
| `PROFILE_PAIR_CHANNEL_CONFLICT` | a PAIR profile needs the pair but channel 2 (or another voice on it) makes it impossible; also used for a non-`1+2` pair and for two PAIR profiles |
| `PROFILE_CHANNEL_REQUIREMENT` | a bound instrument has no sounding notes, or its notes are on a channel the profile cannot be realized on |
| `PROFILE_DISTORTION_CONFLICT` | the composition explicitly declared a distortion that disagrees with the profile's measured generator |
| `PROFILE_ENVELOPE_OUT_OF_RANGE` | the profile's measured envelope does not fit the composer's `0..15` frame fields |

The CLI turns every one of these into a normal error message and a non-zero exit code — no
traceback, and no partial output file.

`PROFILE_DISTORTION_CONFLICT` is the code the Stage 8B contract proposed (§C-10.4) for exactly
this case, now implemented. The collision error for the joined pair carries the existing
`BASS16_CHANNEL_CONFLICT` in its `detail`, since the composition validator already has that
code for the same situation.

---

## 12. Backward compatibility

Profile support is strictly opt-in. With no binding:

* `atari_music.ai` modules are not imported through the profile package at all;
* `IRSong` resolution is `$00`, or `$10` when the composition declares `BASS 16BIT`;
* the WAV, the exported assembly and the XEX are unchanged.

Measured, by building the same composition before and after this stage (the tracked sources
stashed and restored, the untracked package left in place):

| artefact | result |
| :--- | :--- |
| WAV (`import-dsl`, `import-json`) | **byte-identical** |
| XEX (`build-xex`) | **byte-identical** |
| MADS assembly | all **588 data lines identical**; the only change is the `; Mode:` comment, which used to misreport `$50` for a song that writes `$10` |
| exported POKEY IR JSON | the only difference is three **new optional fields** per instrument (`audctl`, `profile_id`, `profile_fingerprint`), all `null`; no existing value changed |

The three new fields are optional with `None` defaults, so an older IR document still loads
(`IRSong.from_json_file`) and a document without them renders exactly as before.

The pre-existing test suite also passes unchanged: **351 tests collected and passing**, of
which 52 are new.

---

## 13. Example

Everything in this section uses files tracked in `tests/data/sound_profiles/`
(`examples/` is gitignored in this repository, so runnable inputs live with the test data):

```
tests/data/sound_profiles/
    vaults_of_nhyrmeth.dsl        the composition   — the DSL example from docs/music_dsl.md §4
    vaults_binding.json           the binding       — instrument → profile id
    bank/                         the profile bank  — registry.json + 4 profiles
```

Note what is **not** in the composition: no profile id, no POKEY register, no AUDCTL. The
binding is the only place the two meet.

The bank was generated by the archaeology project's own CLI, from its 67-profile library, with
no profile chosen for how it sounds — four were picked because the Stage 8C/8D audit rates them
technically clean and they cover both scopes and four generators:

```bash
# in the POKEY Sound Archaeology project
python -m pokey_sound_archaeology playable --bank examples/integration_bank \
    --profiles pokey_ref_a8c81a84,pokey_ref_048db11d,pokey_ref_050170ef,pokey_ref_3627798b
```

`pokey_ref_3627798b` and `pokey_ref_050170ef` are `PAIR` (`$50`, 16-bit, generators `$C` and
`$8`); `pokey_ref_a8c81a84` and `pokey_ref_048db11d` are `VOICE` (`$00`, 8-bit, generators `$8`
and `$A`). The tracked copy under `tests/data/sound_profiles/bank/` is now the **full 67-profile
research bank** (§3.1), which contains those four unchanged — so a fresh checkout can render the
example without the other repository present, and the example still resolves its own two ids.

```bash
# Profile-bound WAV + assembly (MVI-1 VOICE + MVI-2 PAIR in one run)
python -m atari_music import-dsl tests/data/sound_profiles/vaults_of_nhyrmeth.dsl \
    --sound-bank tests/data/sound_profiles/bank \
    --profile-bindings tests/data/sound_profiles/vaults_binding.json \
    --output-wav examples/sound_profiles/vaults_profile.wav \
    --output-asm examples/sound_profiles/vaults_profile.asm

# The same composition with no profile, for the A/B
python -m atari_music import-dsl tests/data/sound_profiles/vaults_of_nhyrmeth.dsl \
    --output-wav examples/sound_profiles/vaults_default.wav

# The XEX, from the same profile-aware representation
python -m atari_music build-xex tests/data/sound_profiles/vaults_of_nhyrmeth.dsl --format dsl \
    -o examples/sound_profiles/vaults_profile.xex \
    --sound-bank tests/data/sound_profiles/bank \
    --profile-bindings tests/data/sound_profiles/vaults_binding.json
```

> **Careful when you build the XEX into a directory you also export into.** `build-xex -o X.xex`
> writes its harness assembly to `X.asm` — the same stem, so it will overwrite a deliberate
> `--output-asm X.asm` export. That is pre-existing behaviour, not part of this feature, and it
> is left alone; the example artefacts are produced by building the XEX in a scratch directory
> and copying only the `.xex`. The tests compare the two artefacts separately because they are
> different files.

The run reports what it is about to change before it renders:

```
Applying sound profile binding from .../bank (67 profile(s) in bank):
  bass -> pokey_ref_3627798b (PAIR, divider 16-bit, clock joined16:1+2:divider_msb:1.79MHz, status PLAYABLE)
      generator $0C -> AUDC $C0 [profile], channels [1]
      envelope attack=1/profile, decay=3/profile, release=2/profile, sustain=6/profile
  lead -> pokey_ref_a8c81a84 (VOICE, divider 8-bit, clock 64kHz, status PLAYABLE)
      generator $08 -> AUDC $80 [profile], channels [3]
      envelope attack=0/profile, decay=1/profile, release=2/profile, sustain=5/profile
  effective AUDCTL $50 (16-bit pair Ch1+Ch2 at 1.79 MHz), 16-bit bass: True
```

**What actually changed in the registers** (same composition, same notes, one binding):

| | default | profile-bound |
| :--- | :--- | :--- |
| AUDCTL | `$10` (1+2 join, 64 kHz) | `$50` (1+2 join, 1.79 MHz) |
| channel 2 `AUDC` (bass, the pair's audible half) | `$A0` + velocity | `$C0` + velocity (profile generator `$C`) |
| channel 2 divider for D-2 | N=430 (`+1`), low `$AE` high `$01` | N=12071 (`+7`), low `$27` high `$2F` |
| channel 3 `AUDC` (lead) | `$A0` + velocity | `$80` + velocity (profile generator `$8`) |
| channel 3 divider (lead, D-4) | unchanged — channel 3 is not joined | unchanged |
| channel 4 (percussion, unbound) | unchanged | unchanged |
| exported header | `AUDCTL=$10 (16-bit pair Ch1+Ch2 at 64 kHz)` | `AUDCTL=$50 (16-bit pair Ch1+Ch2 at 1.79 MHz)` |

**And audibly**: the two WAVs have identical length, identical peak and **100 % of samples
differ** (the first difference is 76 samples in, at the bass onset). The RMS drops from 6963
to 2157 because the bound profiles' measured envelopes sustain lower than the character
defaults — that is the profile doing what the contract says it does, not a rendering fault.

The example renders two profiles into one composition on purpose: a `PAIR` profile and a
`VOICE` profile coexisting, which is the target architecture in one run.

> `Pan Inspektor na Tropie` was requested for this stage but exists in this repository only as
> a SAP source asset (`music/Husak_Jakub/Inspektor.sap`), not as a composition document, so it
> could not be rendered here. It is also the material Stage 8B identified as using three
> different AUDCTL values inside one subsong — behaviour the current `IRSong` cannot express
> (see §14).

### 13.1 The songs folder — one binding per song

`examples/songs/` holds seventeen songs (twelve Music DSL, five composition JSON). Next to each
one is a binding file, `<song file>.binding.json`, so the song and its realization can be read
side by side:

```
examples/songs/
    as-1.dsl
    as-1.dsl.binding.json          <- the realization, not the music
    dziki.json
    dziki.json.binding.json
    ...
```

Each binding names the full research bank with a path relative to itself, so it resolves
without `--sound-bank`:

```json
{
  "schema": "atari-music/sound-profile-binding/1",
  "bank": "../../tests/data/sound_profiles/bank",
  "instruments": {
    "bass": "pokey_ref_331fbbd7",
    "lead": "pokey_ref_1ef377fc",
    "perc": "pokey_ref_6db98eb5"
  }
}
```

```bash
python -m atari_music import-dsl examples/songs/as-1.dsl \
    --profile-bindings examples/songs/as-1.dsl.binding.json \
    --output-wav out/as-1.wav
```

**How the profiles were chosen.** By *generator family*, mirroring the semantics the composer
already uses for its own instrument characters — not by preference, and not by listening:

| channel's role | pool | why |
| :--- | :--- | :--- |
| percussion | `$00` VOICE, generator nibble `$8` (poly9/17 direct) | the composer's own percussion default is `DISTORTION_WHITE_NOISE` `$80` |
| bass, 8-bit | `$00` VOICE, nibble `$C` (poly4 direct) | the composer's own bass default is `DISTORTION_4BIT_POLY` `$C0` |
| bass where the song already joins 1+2 | a `PAIR` profile (`$50`) | the song's channel 1 *is* the low byte of a joined pair |
| melodic / harmony | `$00` VOICE, nibble `$A` (pure tone) | the composer's own lead/harmony default is `DISTORTION_PURE_TONE` `$A0` |

Within a pool the profile is chosen by a stable rotation over the song list, so the same inputs
always give the same binding and different songs exercise different profiles. **One profile per
POKEY channel**: every instrument sounding on a channel shares that channel's profile, because
a channel carries one generator — and because the note-level `instrument_id` would otherwise
make the WAV alternate generator per note while the exported assembly can only publish one per
channel.

Two consequences worth stating plainly:

* these bindings are **technical assignments that exercise the library**, not curation. They
  are not "the best bass" and they say nothing about how a profile sounds (§3.1, §14.6);
* every one of them was **proved by applying it** — the generator asks the binding layer, so a
  profile the consumer refuses (an envelope the composer cannot express, an AUDCTL the channel
  cannot carry) is never chosen. The tests re-apply all seventeen.

`examples/` is gitignored in this repository, so the songs and their bindings are local
working material rather than tracked fixtures; the tests skip when the folder is absent.

### 13.2 The listening package

```bash
# Build the blinded package: 61 profile stimuli, 30 A/B trials, 6 song pairs.
# The bank is read only; nothing is renamed, ranked or selected.
python -m atari_music.cli prepare-listening-test-9c \
    --package-dir examples/sound_profile_listening \
    --sound-bank tests/data/sound_profiles/bank \
    --songs-dir examples/songs

# Listen: open examples/sound_profile_listening/index.html (or serve the folder if the browser
# blocks file: audio — the README gives the one-line command), fill in the three CSVs, then:
python -m atari_music.cli analyze-listening-test-9c \
    --package-dir examples/sound_profile_listening \
    --output-dir reports/stage9c
```

`--song NAME` (repeatable) replaces the default varied song programme; `--seed` changes the
presentation order and is recorded in the manifest. The build is deterministic: the same bank,
seed and songs give the same sample ids and byte-identical audio, which the tests assert.

The analysis refuses to run while the templates are still empty, writes
`reports/stage9c/{report.md,profile_scores.csv,ab_results.csv,song_results.csv,vocabulary.json}`
and is itself deterministic. It reports where the measurements and the listening **disagree**
(technically distant pairs heard as similar, and the reverse) as first-class evidence, and it
ends by listing candidate groups with their thresholds — explicitly not a selection (§3.3).

### 13.3 The rebinding experiment (Stage 10A)

§13.1's bindings were chosen by generator family, and Stage 9D/9E showed what that costs. Stage 10A
re-asks the whole-song question with **only the assignment changed**:

```bash
python -m atari_music.cli prepare-rebinding-10a
```

It recovers the six Part C songs from the Stage 9C manifest (and refuses to run if a binding file no
longer matches it), chooses replacements from the listener's own ratings, renders three versions per
song — the composer's own instruments, the old binding and the new one — and writes a blinded package
to `examples/sound_profile_rebinding_10a/` plus `docs/stage10a_rebinding_experiment.md` and
`reports/stage10a/`.

Two properties make the comparison trustworthy:

* **Compatibility is measured, not assumed.** Every candidate profile is put through
  `apply_profile_binding`; a refusal removes it. The assignment obeys the constraints in §2–§8 for
  free, because the layer that enforces them is the layer that was asked.
* **The default and old sides are compared byte for byte with the Stage 9C stimuli.** They are
  identical, and the shared gain matches the gain Stage 9C recorded — so the package re-tests the
  same 5–0 with the same audio rather than a plausible-looking rerun. If they ever diverge, the
  build stops instead of shipping.

A replacement is adopted only when the listener rated it **no lower on every scale** and higher on at
least one, by two points on a single scale or one point on two scales together — because
distinctiveness and Atari character oppose each other in the listener's own ratings
(Spearman −0.57), so distinctiveness alone never justifies a change. Channels with no such
replacement keep the profile they had, and the report says which and why.

### 13.4 The volume contour transfer experiment (Stage 10B)

Stage 9E named the first capability the composer lacks (the archaeology measures how loudness moved
inside a sound; the player discards it) and Stage 10A showed that reassigning profiles does not fix
anything by itself. Stage 10B implements the transfer behind a switch, proves it end to end, and
prepares the listening test that judges it:

```bash
python -m atari_music.cli prepare-volume-contour-10b
```

It renders three variants of one subject — **A** the composer's own instrument, **B** the profile,
**C** the same profile with its measured contour — from one composition and one binding, so B and C
differ in exactly one field. The subjects are 8 profiles (7 VOICE + 1 PAIR, chosen by a stated
eligibility rule) held as single notes long enough for their contour to be heard once, and the same
six Stage 10A songs, so the question is asked both of an isolated sound and of a real arrangement.

Three proofs carry the claim:

* **Perturbation.** B, C and a third render with the contour **reversed**. Only one frame column may
  differ, it must be the AUDC column of the channel that sounds (AUDC2 for a 16-bit pair), the
  distortion nibble must be untouched, the low nibble must equal the mapping's own arithmetic frame
  for frame, and the audio's frame-wise RMS must follow the volume the frames carry.
* **No-op.** With the feature switched on and a flat contour, the frames and the audio are
  byte-identical to B.
* **Regression.** With the feature switched off, all 18 renders the Stage 10A package published are
  reproduced **byte for byte**. No golden file is updated.

The experiment's honest boundary: a measured contour that reaches level 0 is refused (silence is
timing, not loudness), the affected song channels are named in the report, and `build-xex` refuses a
contour outright (`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`) rather than exporting an XEX that would
play something other than what was listened to.

---

## 14. Limitations

Carried into the integration deliberately, with the smallest necessary change made rather
than the problem moved elsewhere.

1. **A pitch *gesture* is not transferred.** 60 of the 67 archaeology profiles carry a
   measured pitch/volume contour; the player has no per-channel macro, vibrato or per-frame
   volume modulation, so a profile is realized as a **static** generator, envelope and clock.
   The contours stay in the document, unread. (`GESTURE_NOT_RENDERABLE_BY_CONSUMER`,
   126 occurrences in the archaeology audit.)
2. **Measured volume modulation is not reproduced** — the same reason as (1).
   `volume.level_distribution` and `volume.change_rate_hz` are reported, not claimed.
3. **AUDCTL is one value for the whole song.** A profile is applied to the frame stream as a
   single byte; a composition that changed AUDCTL mid-song (the archaeology corpus does not;
   the Composer's `Inspektor` does) is not representable today. Profiles bound in one render
   must therefore agree on the bits that govern their channels, and a disagreement is a
   refused conflict rather than a silent choice.
4. **`AUDF` `$FF` cannot be exported.** The 6502 tracker reserves `$FF` as an end-of-track
   marker, so the value is clamped to `$FE` in the frame stream *and* in the assembly, which
   keeps the two outputs identical but sharpens the very lowest note of a profile whose span
   reaches `$FF`. Five archaeology profiles reach `$FF`; none is in the example bank.
5. **Envelope confidence varies.** Only 4 of 67 profiles measured an envelope at or above 0.9;
   38 measured none at all. When a bound profile has no trustworthy envelope the character
   default stays, and the report says so, instead of inventing a shape.
6. **A profile is not a curated instrument.** No profile carries a role or a name; choosing
   which profile realizes "bass" is an explicit binding decision for now, and automatic
   character→profile mapping is deliberately not implemented (the archaeology contract
   C-10.3/C-10.5 refuse it).
7. **The published bank is not a curated library.** It holds all 67 profiles the archaeology
   pipeline produced, published so the whole corpus can be exercised — not a selection. It is
   explicitly not a recommendation, and no profile is ranked, renamed or assigned a role.
   Stage 9C (§3.3) exists precisely to gather the perceptual evidence a later curation step
   would need.
8. **`result_transform` is a general hook**, not a profile-specific one. It exists so the XEX
   path can share the profile-aware IR without `atari_music.ai` learning about profiles; a
   second, unrelated use of it would be a sign the boundary is drawn in the wrong place.
9. **A profile's *character* is not known to this consumer.** A binding is by exact
   `profile_id`; the library carries no role, no name and no category, so nothing maps "bass"
   to a profile automatically and nothing ranks profiles by eligibility. Assigning a profile
   to a voice is an explicit, external decision — including in the example bindings of §13.1,
   which choose by generator family and say so. Automatic character→profile mapping remains
   deliberately unimplemented (archaeology contract C-10.3 / C-10.5).
10. **The published status is a verdict about programmability, not about sound.** `PLAYABLE`
   means every register is determined and self-consistent; `PLAYABLE_WITH_LIMITATION` adds a
   recorded caveat. Neither says a profile is a good choice for a part, and 6 of the 67
   profiles describe no sound at all and are refused outright (§3.2).
11. **`build-xex` writes its harness assembly next to the `.xex`** using the same stem, so it
   overwrites an `--output-asm` export of the same name in the same directory. Pre-existing
   behaviour, left unchanged; §13 notes how the example works around it.
12. **A listening stimulus is a phrase, not a gesture.** Stage 9C renders each profile as a
   static tone under a fixed phrase, so a profile whose document carries a measured pitch or
   volume contour is heard in reduced form. That is a property of the integration (§14.1), not
   of the sound, and the package says so.
13. **Two profiles need one substituted envelope field.** The composer refuses to clamp a
   measured attack wider than its envelope fields (`ENVELOPE_FRAME_ABOVE_CONSUMER_MAX`); the
   experiment declares that single field from the composer's own character default and marks
   the affected samples in `manifest.json`. Their rating therefore reflects the profile's
   generator, clock and pitch with one substituted field.
14. **Peak normalization preserves a real loudness spread.** Stimuli share a peak, not an RMS:
   profiles that sustain low are measurably quieter (about 13 dB of RMS range in this bank).
   That is deliberately not equalized, because RMS equalization would destroy the A/B
   comparisons in parts 2 and 3; instead the loudness of every sample is recorded and the
   analysis reports its correlation with the ratings.

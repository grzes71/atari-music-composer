# Lead Library v0.1

**This is an experimental specification.** It describes four melodic POKEY instruments that Experiments
26-30 produced and evaluated. **None of them has been integrated into the production Composer.** Nothing
in the production pipeline reads this directory: no DSL, IR, compiler, MADS exporter, 6502 player or CLI
change, and there is no runtime mechanism that selects an instrument from this library.

---

## 1. What this library is for

The project had four candidate lead timbres and no shared way to describe them. v0.1 is that
description: for each instrument, what it *is*, what was actually rendered, what it might be *for*, and
what is wrong with it.

It is deliberately four entries, not a library-sized collection:

* Experiment 29 shortlisted twelve candidates from the 67-profile bank, and Experiment 30 compared four
  of them;
* Experiment 30 rated **all four** useful in the composition context, so none could be dropped on
  evidence;
* therefore the useful work in v0.1 is to describe four instruments *correctly*, not to add more.

The library is role-scoped: it contains only `lead` instruments. Bass, percussion, harmony and SFX are
explicitly out of scope.

---

## 2. Where it lives, and why

```
data/instrument_libraries/lead/v0.1/
    library.json      the instrument specification
    evaluation.json   the Experiment 30 listening ratings
    README.md         this file
```

The project had no `data/` directory before this. Three alternatives were considered:

| alternative | why not |
|---|---|
| `experiments/experiment30/` | `/experiments` is in `.gitignore`, so a specification meant to be read and versioned would not be tracked |
| `src/atari_music/` | it is the production tree; the brief requires the library to stay isolated from production execution |
| `docs/` | the existing `docs/` holds narrative reports, not machine-readable data |

`data/instrument_libraries/<role>/<version>/` was chosen because it is tracked, it is outside the
production tree, it names the role and the version in the path, and it leaves room for a future
`bass/v0.1/` without redesigning anything. It is also the path the brief suggested.

---

## 3. The format

Two files, both JSON, both carrying a `schema` string in the project's existing style
(`pokey-sound-profile-registry-1.0`, `atari-music/sound-profile-binding/1`):

* `library.json` — schema `atari-music/instrument-library/1`
* `evaluation.json` — schema `atari-music/instrument-library-evaluation/1`

### Why the ratings are in a second file

`library.json` holds only what is stable about an instrument. The ratings are one listener's opinion
from one session; they are not properties of the instrument, and putting them beside the identity fields
would invite exactly that reading. They live in `evaluation.json`, joined back by `instrument_id`.

### Why one file and not a registry plus one file per instrument

The bank uses `registry.json` + `profiles/*.json`, which is right for 67 research artefacts that are
independently produced. Four hand-curated instruments do not need that machinery, and the brief asks for
no framework beyond what the four entries require. A registry split can be introduced later if the
library ever grows past what one file can hold.

---

## 4. How an instrument is identified

Each entry has five groups, kept deliberately separate:

| group | what it holds |
|---|---|
| `identity` | where the instrument comes from, and whether it can be reproduced from this record |
| `rendering` | the register parameters actually applied, and which of them came from the profile and which from the composition |
| `musical` | a plain-language character description and a usage hypothesis, **each marked as a hypothesis** |
| `limitations` | the profile's own audit codes, plus the limits of the renderer |
| `validation` | whether the specification checks out, whether it rendered, and whether it was listened to |

The groups answer five different questions and must not be read as one. In particular, nothing in
`musical` is a measured property, and nothing in `validation` is a statement about how the instrument
sounds.

### The fields, one by one

* **`instrument_id`** — the stable name. It is the same name Experiments 29 and 30 used, so the library,
  the experiment artefacts and the reports all refer to the same thing.
* **`display_name`** — the human-readable form.
* **`role`** — always `lead` in this library.
* **`library_version`** — the version the entry belongs to. This is the only field repeated from the
  library header, and it is repeated on purpose: it pins each entry to the version it was specified
  against, so an entry stays identifiable if it is ever lifted out of the file.
* **`identity.source`** — either a bank profile (`kind: "bank_profile"`, with its `profile_id` and
  `profile_fingerprint`) or an experiment (`kind: "experiment"`, with the code that implements it).
* **`identity.source.profile_fingerprint`** — the bank's own `playable_fingerprint`. It is a SHA-256 over
  the whole profile document, so recording it is also a content check: if the profile were edited, the
  fingerprint would no longer match and the test suite would fail.
* **`identity.evidence`** — which experiment measured this instrument, which manifest records it, and
  which letter it was given there. This is the trail back to the raw data.
* **`identity.reproducibility`** — whether the instrument can be reproduced from this record. For the
  three bank profiles: yes, by id and fingerprint. For C1: **no, not fully** — see §6.
* **`rendering.*`** — the parameters actually applied: `generator_byte`, `audctl_mode`,
  `envelope_observed_in_experiment30`, `divider`, and the observed AUDCTL per context. Every one has a
  matching `*_source` field naming where the value came from.
* **`rendering.envelope_sources_observed_in_experiment30`** — field by field, `profile` or
  `composition`. This is the single most important distinction in the library: it is where the C1
  asymmetry shows up.
* **`musical.character` / `musical.usage_hypothesis`** — `{text, basis}`. `basis` is always `hypothesis`
  in v0.1. Nothing here has been verified, and the test suite fails if a musical claim is ever marked
  `verified`.
* **`limitations.profile_codes`** — the bank's `limitation_codes`, `blocking_codes` and
  `consumer_gap_codes`, copied verbatim and checked against the bank by the tests.
* **`limitations.rendering`** — the practical limits: what the engine cannot render, how many channels
  the instrument occupies, and anything specific to the timbre.
* **`validation.specification`** — whether the identity and the references resolve.
* **`validation.render_in_experiment30`** — whether it rendered, and under which check.
* **`validation.listening`** — whether it has been listened to, and a pointer into `evaluation.json`.

### What the `basis` values mean

| value | meaning |
|---|---|
| `verified` | read from the repository: the profile document, the registry, or the Experiment 30 manifest |
| `hypothesis` | a musical guess. Not measured, not heard, not a property of the instrument |
| `listening` | a listener's rating. It lives in `evaluation.json`, never in `library.json` |

---

## 5. The four instruments

| id | source | generator | character (hypothesis) |
|---|---|---|---|
| `c1_octave_pulse` | Experiments 26/27, applied by Experiment 28's `apply_c1` | `$40` + alternating divider | ringing, beating lead |
| `pure_sustain` | `pokey_ref_25f94201` | `$A0` | clean sustained square, the plainest of the four |
| `pure_pluck` | `pokey_ref_9daa0429` | `$A0` | the same square with a sharp attack and a low sustain |
| `buzz_steady` | `pokey_ref_2b83db43` | `$C0` | grainy poly4 buzz, a metallic edge |

The three bank profiles are **referenced, not copied**: the library records their id and fingerprint and
leaves the profile documents as the single source of truth. No profile file was duplicated into this
directory.

---

## 6. A bank profile is not the same kind of thing as C1

This is the most important thing to understand about the library.

**A bank profile is a measurement.** It is a JSON document describing one coherent POKEY register
configuration observed in a real recording: generator, clock, coupling, envelope, and the evidence
around them. It has an id and a content fingerprint, it can be loaded by
`atari_music.sound_profiles.bank`, and the binding machinery can realize it on a song.

**C1 is not a profile. It is code.** It is a register transform — rewrite one channel's divider and
generator nibble with a fixed schedule — introduced in Experiment 26/27 and applied to a composition in
Experiment 28. The consequences:

* **it has no `profile_id` and no fingerprint.** None is recorded, and none may be invented. The tests
  assert that both keys are *absent* from C1's `identity.source`.
* **its envelope is not its own.** `apply_c1` deliberately keeps the host composition's articulation. In
  Experiment 30 the applied envelope was attack 1, decay 3, sustain 13, release 2 — every field from the
  composition's `bright_lead` character default. Experiment 26/27's isolated prototype used attack 1,
  decay 8, sustain 12, release 3 for its own C1 variant. Both are C1; neither is *C1's* envelope.
* **therefore C1 is `partially_reproducible`.** Its generator and divider schedule are pinned in code,
  but its envelope, channel and AUDCTL come from the song. A record that stored Experiment 30's envelope
  would describe Experiment 30's composition, not the instrument.

That asymmetry is not a defect in C1; it is a difference in kind. It is why the library records
`envelope_sources_observed_in_experiment30` field by field rather than one envelope per instrument.

---

## 7. Where the ratings come from

`evaluation.json` transcribes the ratings the listener returned from Experiment 30, in
`experiments/experiment30/evaluation_experiment30__anonymous.csv`. They are **transcribed, not
recomputed**, and the test suite re-reads that CSV when it is present and asserts that every value
matches.

The ratings preserve all four distinctions the experiment made:

* **solo** (a 9-second figure) versus **composition** (`Vaults-of-Nhyrmeth.dsl` with only the lead's
  timbre changed);
* **original** level versus **loudness-matched**.

Nothing is aggregated. There is **no combined score, no weighting, no ranking and no "best instrument"** —
the test suite walks the whole document and fails if a key resembling one appears. One listener's
single-session ratings cannot support a number like that, and producing one would hide the differences
that matter most.

One observation worth carrying forward: on six of the sixteen rows the listener wrote that the original
and the loudness-matched versions sounded identical to them. Experiment 30 measured an 8.15 LU spread in
the composition block before matching, so the two versions really do differ in level. The comment is
recorded as the listener's observation, not as a measurement.

`evaluation.json` also carries three `observations_about_the_ratings`. They are descriptions of the
ratings as recorded, each with a `what_it_does_not_mean` field, and no score is derived from them:

* **in the composition block all four were rated identically** (4 / 4 / 1, both versions), so the
  composition block on its own does not separate these instruments — it says all four work in that
  arrangement, not which is better;
* **in the solo block the three bank instruments were rated identically to each other** (3 / 3 / 2) and
  `c1_octave_pulse` stood out (4 / 4 / 2, or 4 / 3 / 2 matched). Identical ratings are *not* proof that
  the three sounds were indistinguishable — the listener may simply not have needed to tell them apart;
* **every instrument scored better in the composition than solo**, by roughly one point on usefulness and
  interest and one point on annoyance. In this experiment the context moved the ratings more than the
  instrument did.

A test checks each of those three claims against the ratings themselves, so an observation cannot drift
away from the data it describes.


---

## 8. Technical limitations of the library

1. **The ratings are one listener, one session, one composition, one test grid.** They are preliminary
   and are not properties of the instruments.
2. **Everything here is a synthetic render** of the POKEY register model. Nothing has been exported to a
   player, and a timbre that sounds good here is not proof that the same sound is reachable on real
   hardware.
3. **Only one part, on one channel.** Experiment 30 changed CH3 only. A timbre can work on a lead and
   fail on a bass or in a denser mix; the library cannot say anything about that.
4. **The bank profiles carry audit codes that are not resolved.** `GESTURE_NOT_RENDERABLE_BY_CONSUMER`
   appears on all three: a measured gesture in the source recording is dropped.
   `AUDF_FF_EXPORT_BOUNDARY` appears on `pure_pluck`. `VOLUME_MODULATION_NOT_REPRODUCIBLE` and
   `PITCH_BASE_PAIR_INCONSISTENT` appear on `buzz_steady`, which is why that profile is
   `PLAYABLE_WITH_LIMITATION` and not `PLAYABLE`. The codes are recorded verbatim; the library does not
   claim to have fixed them.
5. **C1 cannot be reproduced from this record alone** (§6).
6. **The `$40` generator is not a clean octave.** It is poly5-gated poly4, so halving the divider doubles
   the poly5 gate rate as well. C1 is a texture change and a pitch change together.
7. **`data/` is new.** Nothing else in the project reads it yet, by design.

---

## 9. Deliberately left for later

* **A runtime loader or instrument-selection mechanism.** The brief forbids one, and v0.1 does not need
  it: four entries in one file are read by humans and by tests.
* **Registering these instruments with the Composer.** That is a separate, explicitly-scoped decision
  that has not been taken.
* **Integrating C1 at all.** It is code, not a profile, so integrating it would mean either a new
  instrument-mapping mechanism or turning it into something the bank can express. Neither is in scope.
* **The other eight Experiment 29 candidates.** They were not rejected; they were simply not the four
  this library was asked to describe.
* **Bass, percussion, harmony and SFX libraries.** The path layout leaves room for them.
* **Resolving the audit codes** on the three bank profiles.
* **A second listening round.** The ratings in `evaluation.json` are the first, and the caveats say so.

---

## 10. Validating the specification

```
python -m pytest tests/test_lead_library_v0_1.py -q
```

The suite checks the four required instruments and their unique ids; the schema and version; that every
bank reference resolves and every recorded fingerprint matches both the loaded profile and the
registry's published value; that C1 has no invented `profile_id`; that every recorded rendering parameter
equals the one Experiment 30 actually applied; that every musical claim is marked as a hypothesis; that
the ratings match the returned CSV; that no combined score exists; and that no production module, bank
profile or Experiment 26-30 artefact was changed.




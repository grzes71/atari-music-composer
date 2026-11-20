# Instrument Selection CLI Contract (proposed, not implemented)

**Status:** design only. Nothing in this document is implemented. No CLI flag exists, no loader
exists, and no production file was changed to produce this specification.

Every claim below is tagged:

| tag | meaning |
| :--- | :--- |
| **[verified]** | read from the current source in this repository, with the file and symbol named |
| **[proposed]** | a design decision this document recommends, not yet implemented |
| **[open]** | cannot be settled from the repository alone |

---

## 1. Purpose and non-goals

### Purpose

Give a user one explicit, deterministic way to say *"use this instrument from the Lead Instrument
Library for this part of this composition"*, and have that choice reach **both** the rendered WAV and
the exported XEX, or fail loudly.

Lead Library v0.1 (`data/instrument_libraries/lead/v0.1/`) describes four instruments. Nothing reads
it: **[verified]** no module under `src/` contains the string `instrument_librar`. This document
specifies the smallest interface that would let a user act on that library.

### Non-goals

Explicitly **out of scope** for this contract:

* automatic instrument selection, or mapping instruments to musical roles;
* selecting a whole library or instrument set and applying implicit defaults;
* bass, percussion, harmony or SFX libraries;
* new synthesis algorithms or POKEY effects;
* a new instrument loader, runtime integration, or any CLI implementation;
* changing the DSL, the existing sound profiles, Lead Library v0.1, or the E26–E30 artefacts.

A future role-based interface would need, at minimum, a role vocabulary, a per-role default instrument
and a resolution order between role defaults and explicit assignments. That is deliberately **not**
designed here.

---

## 2. What exists today

This section is the factual basis for everything that follows. The task brief referred to commands
named `render` and `build`; **[verified]** neither exists.

### 2.1 The real pipeline commands

**[verified]** from `src/atari_music/cli.py`, the commands that touch a composition are:

| command | options | what it does |
| :--- | :--- | :--- |
| `import-dsl` | `--output-json`, `--output-ir`, `--output-wav`, `--output-asm`, `--sound-bank`, `--profile-bindings` | DSL → optional canonical JSON, POKEY IR, WAV, MADS asm |
| `import-json` | `--output-ir`, `--output-wav`, `--output-asm`, `--sound-bank`, `--profile-bindings` | the same, from canonical JSON |
| `export-mads` | `--output-asm` | an **already-realised** POKEY IR JSON → MADS asm. No bank, no binding. |
| `build-xex` | `--format`, `--output`, `--player-address`, `--music-address`, `--zp-base`, `--mads`, `--player-asm`, `--sound-bank`, `--profile-bindings` | composition → relocatable XEX via MADS |
| `compose` | `--profile`, `--seed`, `--key`, `--tempo`, `--length`, `--intensity`, `--variation`, `--output-json`, `--output-wav`, `--output-asm` | generate a song, then render. **No bank or binding options.** |
| `ai-compose` | generation options | generate via an LLM |

There is no command that renders *and* builds from one invocation; a user runs `import-dsl` for the
WAV and `build-xex` for the XEX.

### 2.2 How a profile already reaches both outputs

**[verified]** `cli.py::_resolve_profile_binding` loads `--profile-bindings` (and the bank it names,
or `--sound-bank`), and refuses a bank without a binding:

> `--sound-bank` requires `--profile-bindings`: a bank lists profiles but does not say which voice uses
> which one

**[verified]** `cli.py::_bind_result` calls `describe_binding` (prints what will change) and then
`apply_profile_binding`, converting every `SoundProfileError` into a CLI error.

**[verified]** `import-dsl` and `import-json` apply the bound result to **all** of `--output-ir`,
`--output-wav` and `--output-asm`, so those three cannot disagree.

**[verified]** `build-xex` passes the same binding into `build_xex_from_composition` as its
`result_transform` hook. `ai/client.py` documents that hook as:

> Whatever it returns is what both the WAV preview and the XEX are built from, so a caller that
> rewrites hardware realization … cannot make the two outputs disagree.

**[verified]** the hook is called once, before `export_mads_asm(res)`. **[verified]** in the current
`build_xex_from_composition` body there is no `render_wav` call, so `build-xex` writes only the XEX —
the "WAV preview" in that docstring is aspirational, not a code path.

**Conclusion [verified]:** there is already exactly one place where a hardware-realisation override is
applied consistently to both outputs — the `result_transform` → `_bind_result` → `apply_profile_binding`
path. `docs/profile_integration.md` §14.8 adds a constraint:

> `result_transform` is a general hook, not a profile-specific one … **a second, unrelated use of it
> would be a sign the boundary is drawn in the wrong place.**

So the new feature must reuse this path, not add a parallel one.

### 2.3 How the DSL names things

**[verified]** from `docs/music_dsl.md` and `src/atari_music/ai/dsl.py`:

```
INSTRUMENT <id> character=<role> [dist=$XX] [att=N] [dec=N] [sus=N] [rel=N] [name="..."]
CH<1..4> <instrument-id> V<vol>
```

* an instrument is declared with a **string id** (`lead`, `bass`, `perc`);
* **[verified]** `dsl.py` builds `AIInstrumentDef(id=inst_id, name=name_val or inst_id.capitalize())`,
  so `INSTRUMENT lead character=bright_lead` yields `id="lead"`, `name="Lead"`;
* a channel header names the **instrument id**, and pattern tracks are keyed by the channel number as a
  string (`"1"`…`"4"`);
* **[verified]** `docs/music_dsl.md` §9.2: mid-channel instrument switching is illegal — one waveform
  per channel for the whole song;
* **[verified]** `src/atari_music/ai/composition.py` assigns `IRInstrument.id = index` in
  `doc.instruments`, and `name = inst_def.name or inst_def.id`;
* **[verified]** if `doc.instruments` is empty, four defaults are created with names
  `Lead`, `Bass`, `Harmony`, `Percussion` and ids `0..3`.

### 2.4 The stable identifier for a part

**[verified]** `binding.py::_resolve_targets(song, key, composition)` resolves a binding key in this
order and returns the matching IR instrument ids:

1. the composition instrument's `id`,
2. else the composition instrument's `name`,
3. else the IR instrument's `name` — and more than one match here is an error
   (`PROFILE_BINDING_UNKNOWN_INSTRUMENT`).

**[verified]** `binding.py::_instrument_channels(song, instrument_id)` then maps an instrument to the
channels carrying at least one sounding note of it.

So "a part" is already, precisely, **a composition instrument id**, and the machinery that turns it
into channels exists.

### 2.5 What a profile binding actually writes

**[verified]** `binding.py::apply_profile_binding(result, binding, bank, composition=None,
volume_contour=False)` writes exactly these fields onto the bound `IRInstrument`:

`distortion`, `envelope`, `audctl`, `is_16bit`, and — only when `volume_contour` is enabled —
`volume_contour`; plus `profile_id` and `profile_fingerprint` as provenance.

**[verified]** `binding.py::_rebuild_song` additionally sets `IRSong.uses_16bit_bass` when a bound
profile is a `PAIR` profile. It never changes a pitch, a duration, a rest, a velocity or a role.

**[verified]** the bound `IRInstrument` records `profile_id` and `profile_fingerprint`, so an
`--output-ir` document is a faithful, checkable record of which profile was applied.

### 2.6 What Lead Library v0.1 records

**[verified]** `data/instrument_libraries/lead/v0.1/library.json`:

| instrument | source kind | profile id | recorded `registry_path` |
| :--- | :--- | :--- | :--- |
| `pure_sustain` | `bank_profile` | `pokey_ref_25f94201` | `tests/data/sound_profiles/bank/registry.json` |
| `pure_pluck` | `bank_profile` | `pokey_ref_9daa0429` | same |
| `buzz_steady` | `bank_profile` | `pokey_ref_2b83db43` | same |
| `c1_octave_pulse` | `experiment` | **absent** | absent |

**[verified]** `load_sound_profile_bank(root, *, verify_fingerprints=True, only=None)` takes the
**directory** holding `registry.json` and `profiles/`. The parent of the library's recorded
`registry_path` is exactly that directory, so a bank directory is derivable — but the library has no
explicit `bank_dir` field; see §11.2.

---

## 3. Proposed CLI syntax

### 3.1 The flag

**[proposed]**

```
--instrument <part>=<instrument-id>        (repeatable)
--instrument-library <dir>                 (optional)
```

Two flags, long-form only. No short aliases, to avoid colliding with the existing short options
(`-p`, `-s`, `-k`, `-t`, `-l`, `-v`, `-o`) and to keep the intent explicit.

**Why not `--instrument-profile`.** The brief's illustration used that name and marked it as an
example. It is rejected here because the right-hand side names a **Lead Library instrument**
(`pure_sustain`), not a bank profile (`pokey_ref_25f94201`), and those are different kinds of thing —
one is a curated, role-scoped, versioned entry, the other is a research measurement. Reusing "profile"
for both would make a future error message ambiguous. The existing `--profile-bindings` keeps its name
and its meaning unchanged.

### 3.2 Realistic examples

Rendered WAV, one part overridden:

```powershell
atari-music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl `
  --instrument lead=pure_sustain `
  --output-wav song.wav
```

Both outputs from one composition, two parts, an explicit library directory:

```powershell
atari-music import-dsl examples/songs/Vaults-of-Nhyrmeth.dsl `
  --instrument-library data/instrument_libraries/lead/v0.1 `
  --instrument lead=buzz_steady `
  --instrument bass=pure_sustain `
  --output-wav song.wav --output-asm song.asm --output-ir song.ir.json
```

The XEX, with the same assignment, so both artefacts carry the same hardware realisation:

```powershell
atari-music build-xex examples/songs/Vaults-of-Nhyrmeth.dsl --format dsl `
  --instrument lead=pure_sustain `
  --output song.xex
```

A refused request — C1 is not applicable through this pipeline (§7.3):

```powershell
atari-music import-dsl song.dsl --instrument lead=c1_octave_pulse --output-wav song.wav
# Error: instrument 'c1_octave_pulse' is an experimental register transform, not a bank profile;
#   it cannot be applied by the profile-binding pipeline. [INSTRUMENT_NOT_APPLICABLE]
```

### 3.3 Which commands get the flag

**[proposed]** exactly three, because they compile a composition and then realise it:

| command | flag added | why |
| :--- | :--- | :--- |
| `import-dsl` | yes | compiles, then writes IR / WAV / ASM |
| `import-json` | yes | same |
| `build-xex` | yes | compiles, then builds the XEX |
| `export-mads` | **no** | it consumes an **already-realised** IR. The override must be applied before the IR is written, so offering the flag here would imply it could be applied afterwards, which it cannot. |
| `compose`, `ai-compose` | **no** | neither has `--profile-bindings` today; adding one is a separate scope decision (§11.5) |

The flag means the same thing on all three commands and produces the same IR, so a WAV from
`import-dsl` and an XEX from `build-xex` agree.

### 3.4 Multiple assignments

**[proposed]** repeat the flag. Each occurrence is one assignment:

```
--instrument lead=pure_sustain --instrument bass=buzz_steady
```

Deterministic rules:

* the same **part** assigned twice is an **error** (`INSTRUMENT_TARGET_DUPLICATE`), not "last wins" —
  a silently discarded assignment is exactly the kind of surprise this contract exists to avoid;
* the same **instrument** assigned to two different parts is allowed;
* zero occurrences means the flag does nothing at all (§9).

---

## 4. Identifier semantics

### 4.1 The right-hand side: a Lead Library instrument id

**[proposed]** the value is the **stable `instrument_id` from a Lead Library document** —
`c1_octave_pulse`, `pure_sustain`, `pure_pluck`, `buzz_steady` in v0.1. It is *not* a bank profile id.

Rationale **[proposed]**: the library is the curated layer, it is versioned, and its ids are the ones a
user can be expected to remember. Bank profile ids (`pokey_ref_25f94201`) remain the language of
`--profile-bindings`, which is unchanged, so both routes exist and neither is overloaded.

Resolution **[proposed]**:

1. load the library document (§5);
2. find the entry whose `instrument_id` equals the value exactly;
3. take its `identity.source.kind`:
   * `bank_profile` → the library entry yields a `profile_id` and a bank directory (§5.3), which feed
     the existing `ProfileBinding` path unchanged;
   * `experiment` → **refuse** with `INSTRUMENT_NOT_APPLICABLE` (§7.3).

Exact match only. No case folding, no prefix matching, no fuzzy resolution — an unknown value is an
error listing the available ids.

### 4.2 The left-hand side: a composition instrument id

**[proposed]** the target part is resolved by the **existing** `binding.py::_resolve_targets` — the
composition instrument `id`, then its `name`, then the IR instrument `name`. The CLI must not
reimplement or reorder this, so a part that resolves under `--profile-bindings` resolves identically
under `--instrument`.

An unresolved part is `INSTRUMENT_TARGET_UNKNOWN`, mirroring the existing
`PROFILE_BINDING_UNKNOWN_INSTRUMENT`; an ambiguous one is `INSTRUMENT_TARGET_AMBIGUOUS`.

**Why not a channel number or a pattern id.** A channel is where a part is *realised*, not what it
*is*: **[verified]** `_instrument_channels` maps one instrument to possibly several channels, and
`docs/music_dsl.md` §9.2 forbids two instruments on one channel. Addressing by instrument id is the
only identifier that is stable across a re-arrangement, and it is the one the binding layer already
uses.

---

## 5. Instrument-library version resolution

### 5.1 The problem

**[verified]** the library is versioned by directory (`data/instrument_libraries/lead/v0.1/`) and by a
`library_version` field inside `library.json`. A future `v0.2` may add, rename or drop instruments, so
an invocation must state — or deterministically inherit — which version it means.

### 5.2 Proposed resolution

**[proposed]**, in order:

1. `--instrument-library <dir>` if given — a directory containing `library.json`;
2. otherwise the fixed default `data/instrument_libraries/lead/v0.1`, resolved relative to the
   repository root the same way `build-xex` already locates `player.asm` **[verified]**: explicit path →
   current working directory → repository root.

The version is then **read from the document** (`library_version`), never guessed from the directory
name. **[proposed]** a mismatch between the directory name and the declared version is an error
(`INSTRUMENT_LIBRARY_VERSION_MISMATCH`) rather than a silent preference for one of them.

**No library is loaded unless at least one `--instrument` is present.** That is the mechanism that
keeps §9 true.

### 5.3 Deriving the bank

**[proposed]** for a `bank_profile` entry, the bank directory is the **parent of the entry's recorded
`registry_path`** (`tests/data/sound_profiles/bank`), and the profile is loaded with the existing
`load_sound_profile_bank(bank_dir, only=(profile_id,))`.

**[verified]** `only=` exists and restricts loading to the named ids while still raising
`PROFILE_NOT_FOUND` for a typo, so nothing else in the bank is read and a typo cannot pass.

**[verified]** the loader recomputes every fingerprint and refuses a mismatch
(`PROFILE_FINGERPRINT_MISMATCH`), so the library's recorded `profile_fingerprint` is a checkable
expectation. **[proposed]** the CLI compares the loaded profile's fingerprint with the library entry's
recorded one and refuses a disagreement (`INSTRUMENT_SOURCE_DRIFT`) — that is what makes the library's
identity claim meaningful rather than decorative.

### 5.4 What version selection does **not** do

**[proposed]** it does not select a *set* of instruments, does not apply any default, and does not
change anything about a part that was not named. Reading a library is not applying one.

---

## 6. Validation and error behaviour

### 6.1 The shape of a failure

**[verified]** the existing convention: every `SoundProfileError` is turned into a `click.ClickException`
by `_bind_result`, which prints the message and exits non-zero — no traceback, and no partial output
file.

**[proposed]** the new failures follow the same shape: a one-line message plus a stable code, raised
**before** any output file is written, so a refused run leaves no WAV, no ASM and no XEX behind.

### 6.2 New stable codes

**[proposed]** these codes are new and specific to instrument selection:

| code | raised when |
| :--- | :--- |
| `INSTRUMENT_LIBRARY_MISSING` | `--instrument-library` names a directory without `library.json` |
| `INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED` | `library.json` is not valid JSON or not schema `atari-music/instrument-library/1` |
| `INSTRUMENT_LIBRARY_VERSION_MISMATCH` | the directory name and the declared `library_version` disagree |
| `INSTRUMENT_NOT_FOUND` | the requested `instrument_id` is not in the library (the message lists the ids that are) |
| `INSTRUMENT_TARGET_UNKNOWN` | the left-hand part does not resolve to exactly one instrument |
| `INSTRUMENT_TARGET_AMBIGUOUS` | the left-hand part matches several instruments |
| `INSTRUMENT_TARGET_DUPLICATE` | the same part is assigned more than once |
| `INSTRUMENT_NOT_APPLICABLE` | the instrument exists but this pipeline cannot apply it — C1 (§7.3); `detail.reason` carries why |
| `INSTRUMENT_SOURCE_DRIFT` | the loaded profile's fingerprint disagrees with the library entry's recorded one |
| `INSTRUMENT_BINDING_CONFLICT` | `--instrument` and `--profile-bindings` disagree about the same part (§7.2) |
| `INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX` | a command that must produce a XEX is asked for an instrument needing a capability the XEX format lacks (§8.3) |

### 6.3 Codes reused unchanged

**[proposed]** every code the binding layer already raises passes through untouched, because the
override feeds the same path **[verified]**: `PROFILE_NOT_FOUND`, `PROFILE_FINGERPRINT_MISMATCH`,
`PROFILE_STATUS_NOT_RENDERABLE`, `PROFILE_SCOPE_UNSUPPORTED`, `PROFILE_AUDCTL_CONFLICT`,
`PROFILE_PAIR_CHANNEL_CONFLICT`, `PROFILE_CHANNEL_REQUIREMENT`, `PROFILE_DISTORTION_CONFLICT`,
`PROFILE_ENVELOPE_OUT_OF_RANGE`, `PROFILE_BANK_MISSING`, `PROFILE_BANK_SCHEMA_UNSUPPORTED`.

No new code is invented where an existing one already means the same thing. In particular:

* a requested instrument whose profile the audit marks unrenderable →
  **[verified]** `PROFILE_STATUS_NOT_RENDERABLE`, not a new code;
* an instrument whose part has no sounding notes → **[verified]** `PROFILE_CHANNEL_REQUIREMENT`;
* an instrument whose clock the song's AUDCTL cannot give → **[verified]** `PROFILE_AUDCTL_CONFLICT`.

### 6.4 A stable composition id is still validated independently

**[verified]** `ai/validation.py` already rejects an event that references an undefined instrument
(`UNKNOWN_INSTRUMENT`) during the 3-tier validation, before any binding is considered. **[proposed]**
this contract does not change that: `--instrument` targets a part the composition already declares; it
never creates one.

---

## 7. Parameter precedence and conflict handling

### 7.1 The precedence that already exists **[verified]**

`binding.py` implements a per-field contract, and the new flag does **not** change it:

| field | who wins | verified detail |
| :--- | :--- | :--- |
| envelope (attack, decay, sustain, release) | **composition, field by field** | `_plan_envelope`: "an explicitly declared composition field always wins … Only fields the composition left open are taken from the profile" |
| generator (distortion) | **profile**, unless the composition declared it explicitly | `_plan_instrument`: a profile whose generator disagrees with an explicit `dist=` is refused (`PROFILE_DISTORTION_CONFLICT`), never merged |
| clock / coupling (AUDCTL) | **profile**, subject to a conflict check | `_rebuild_song` writes `profile.audctl_mode`; `_validate_requirements` refuses an unsatisfiable configuration |
| 16-bit pairing | **profile** | `_rebuild_song` sets `is_16bit` and `uses_16bit_bass` for a `PAIR` profile |
| pitch, duration, rest, velocity, role | **composition, always** | `binding.py` module docstring: it "never changes a pitch, a duration, a rest, a velocity, an arrangement or a role" |

So the existing rule is: **the composition owns the music; the profile owns the hardware realisation;
and for the one field both can express (the envelope), the composition's explicit value wins.**

### 7.2 What the new flag may and may not do **[proposed]**

`--instrument part=X` **chooses which profile is used**. It does not add a new precedence tier and does
not let an instrument override an explicit DSL parameter.

With `INSTRUMENT lead character=bright_lead att=4 dist=$C0` in the DSL and
`--instrument lead=pure_sustain` (generator `$A0`, attack 6):

* the explicit `dist=$C0` **wins over** `pure_sustain`'s `$A0`, and because they disagree the run is
  **refused** with `PROFILE_DISTORTION_CONFLICT` **[verified]**;
* the explicit `att=4` **wins over** the profile's attack 6 **[verified]**;
* the profile's decay and sustain are used, because the composition left them open **[verified]**;
* nothing about the notes changes.

The message must name both sides — which DSL parameter, which instrument — so the user can fix either
one. **[proposed]** silently ignoring either side is not an option; that is the existing behaviour and
it is the right one.

### 7.3 Conflict between `--instrument` and `--profile-bindings` **[proposed]**

Both mechanisms assign a profile to a part. The rule:

| situation | behaviour |
| :--- | :--- |
| they target **different** parts | both applied; no interaction |
| they target the **same** part with the **same** resolved `profile_id` | allowed; the duplicate is harmless and is reported as such |
| they target the **same** part with **different** `profile_id`s | **error** `INSTRUMENT_BINDING_CONFLICT` |

Rejecting the third case rather than picking a winner is deliberate: which of two explicit user
instructions should win is not derivable from the repository, and guessing would make the result depend
on argument order.

### 7.4 Why the override cannot be expressed in the DSL **[verified]**

`binding.py`'s contract is that a profile is a **rendering-time dependency**: "The composition does not
name it, the DSL cannot express it, the AI never sees it." **[proposed]** this contract keeps that
boundary. The override is an invocation argument, never written into the composition, which is also why
no DSL change is required.

### 7.5 Reproducing a run **[verified]**

The bound `IRInstrument` records `profile_id` and `profile_fingerprint`, so `--output-ir` captures
exactly what was applied. **[proposed]** the CLI should echo the same information that
`_echo_binding_report` already prints, so a run is reproducible from its log even without the IR.

---

## 8. WAV versus XEX capability constraints

### 8.1 What the two paths can express

**[verified]** from `ir.py::_render_note_to_frames`, `mads_exporter.py::export_mads_asm` and
`pokey_hw`:

| property | in the IR | WAV renderer | XEX exporter / 6502 player |
| :--- | :--- | :--- | :--- |
| generator (distortion) | `IRInstrument.distortion`, `IRNote.distortion` | **yes** — `(distortion & 0xE0) \| vol` per frame | **yes** — one byte per channel in the instrument table |
| envelope (attack/decay/sustain/release) | `IREnvelope` | **yes** — `player_envelope_volumes` | **yes** — four bytes per channel; `player.asm` rebuilds the envelope at run time |
| clock / coupling (AUDCTL) | `IRInstrument.audctl` → `resolve_audctl_mode` | **yes** | **yes** — one header byte |
| 16-bit pairing | `is_16bit`, `uses_16bit_bass` | **yes** | **yes** — CH2 emitted as the pair's high byte |
| note pitch and duration | `IRNote` | **yes** | **yes** — `.byte audf, duration, volume` per note |
| **per-frame volume contour** | `IRInstrument.volume_contour` | **yes** — `apply_volume_contour` shapes the envelope | **NO** — `export_mads_asm` raises `VolumeContourNotExpressibleError` (`VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX`) |
| **within-note divider change** (C1) | not representable | only via an out-of-band frame transform | **NO** — the note table stores **one AUDF per note** |
| `macro`, `vibrato_*`, `slide_semitones`, `arpeggio_offsets` | present as reserved fields | **NO** — deliberately not rendered | **NO** |

The last row is a **[verified]** deliberate design choice, not an oversight: `ir.py` states these are
"intentionally NOT rendered … applying them here would make the WAV preview diverge from what real
hardware plays."

### 8.2 The one divergence that matters for this contract **[verified]**

Of everything `apply_profile_binding` can write, only **`volume_contour`** is WAV-only. It is **off by
default** (`volume_contour=False`), which is why the existing WAV and XEX paths agree today.

**[proposed]** therefore:

* `--instrument` uses the default, `volume_contour=False`. A library instrument is applied as a static
  generator, envelope and clock — which is what the three bank instruments are anyway;
* the flag offers **no** option to enable a contour in v1. A contour would silently make the WAV
  inexpressible as a XEX, which is the failure mode this contract exists to prevent;
* on `build-xex`, if a contour ever became set by some other route, the existing
  `VolumeContourNotExpressibleError` still fires unchanged **[verified]**.

### 8.3 C1 is not applicable, and that is structural **[verified]**

`c1_octave_pulse` is the one library instrument this contract must refuse, and the reason is stronger
than "unsupported":

1. **[verified]** `apply_profile_binding` requires a `SoundProfile` loaded from a bank. C1 is not a
   profile: it is `e28.apply_c1(stream, song, channel)`, a transform over the **compiled frame array**.
   The existing binding path cannot express it at all.
2. **[verified]** the XEX note table stores `.byte audf, duration, volume` — **one divider per note**.
   C1's defining behaviour is the divider alternating **inside** a note. The current MADS/player format
   therefore cannot express C1, exactly as it cannot express a volume contour.

**[proposed]** `--instrument <part>=c1_octave_pulse` fails with `INSTRUMENT_NOT_APPLICABLE` on all three
commands, with a `detail.reason` naming (1) and (2). It is not silently downgraded to a static `$40`
tone, and it is not accepted on `import-dsl` and then rejected on `build-xex` — the refusal must be
identical everywhere, so a WAV is never produced for something that cannot ship.

**[open]** whether C1 should be supported later, and how, is §11.1.

### 8.4 What this contract does not promise **[proposed]**

* it does not promise that a library instrument sounds the same on real hardware as in the WAV — these
  are synthetic renders of the register model;
* it does not promise XEX support for anything that exists only in the Python renderer;
* it does not add a flag to force a divergent XEX.

---

## 9. Backward-compatibility requirements

### 9.1 The rule

**[proposed]** with **no** `--instrument` and **no** `--instrument-library`:

* the library is not opened, not parsed and not imported;
* no instrument is selected, replaced or defaulted;
* `--profile-bindings` and `--sound-bank` behave exactly as they do today;
* no DSL default changes, because the DSL is not touched;
* the WAV, the MADS assembly, the POKEY IR and the XEX are unchanged.

### 9.2 No silent fallback, ever **[proposed]**

An instrument that cannot be applied is an **error**, never a fallback to:

* the composition's own character default,
* another instrument from the library,
* the profile the part would have had without the flag.

This mirrors the existing binding layer, which **[verified]** "refuses loudly — never swapped for a
default, never skipped, never rendered as silence that looks like a working instrument."

### 9.3 How the regression requirement must be stated **[proposed]**

`docs/profile_integration.md` §12 set the precedent: the claim was made **by measurement**, not by
argument — the same composition built before and after, and the artefacts compared.

**[proposed]** the implementation must repeat that measurement and publish it:

| artefact, without the new flags | required result | status |
| :--- | :--- | :--- |
| WAV (`import-dsl`, `import-json`) | **byte-identical** | **[open]** — not yet measured for this change |
| XEX (`build-xex`) | **byte-identical** | **[open]** |
| MADS assembly | identical | **[open]** |
| exported POKEY IR JSON | identical | **[open]** |
| the existing test suite | passes unchanged | **[open]** |

**Do not assume bit-identity.** §12 of the profile document records that an earlier stage changed one
comment line in the assembly and added three nullable IR fields, and that is the level of detail this
measurement must reach. Sources of nondeterminism to check before claiming identity **[open]**: dict
ordering in the IR serialiser, the `; Mode:` comment §12 records as previously wrong, and `build-xex`
writing its harness assembly beside the `.xex` (§14.11 of the same document).

### 9.4 The one deliberate asymmetry **[proposed]**

The feature exists only when it is used. A user who never types `--instrument` cannot be affected by
it — not by a changed default, not by a new import, not by a new code path in the renderer.

---

## 10. Acceptance criteria and implementation test matrix

### 10.1 Acceptance criteria

The feature is acceptable when **all** of these hold:

1. `import-dsl`, `import-json` and `build-xex` accept `--instrument part=id` (repeatable) and
   `--instrument-library <dir>`.
2. `--instrument` works with **no** `--profile-bindings`: the flag alone is enough.
3. A `bank_profile` library instrument is applied, and the resulting `--output-ir` shows that
   instrument's `profile_id` and `profile_fingerprint` **[verified]**.
4. The WAV from `import-dsl` and the XEX from `build-xex` come from the **same** bound IR — through the
   existing `result_transform` path **[verified]**, not a new one.
5. `c1_octave_pulse` is refused identically on all three commands, with `INSTRUMENT_NOT_APPLICABLE` and
   a reason.
6. Every failure in §6.2 and §6.3 leaves **no** output file behind.
7. With no new flags, §9.3's measurements are taken and published.
8. **[proposed]** no file outside `cli.py` and its tests changes — the resolution logic belongs in the
   CLI, so the binding layer stays unaware that a library exists.

### 10.2 Test matrix **[proposed]**

Small on purpose. One row is one test; the "expect" column is the observable.

| # | invocation | expect |
| :--- | :--- | :--- |
| 1 | `import-dsl song.dsl --output-wav a.wav` | unchanged from before the change (baseline) |
| 2 | `build-xex song.dsl --output a.xex` | unchanged from before the change (baseline) |
| 3 | `import-dsl song.dsl --instrument lead=pure_sustain --output-wav b.wav` | exit 0; `b.wav` differs from `a.wav` |
| 4 | as 3, plus `--output-ir i.json` | the `lead` instrument in `i.json` carries `profile_id=pokey_ref_25f94201` and the library's fingerprint |
| 5 | `build-xex song.dsl --instrument lead=pure_sustain --output b.xex` | exit 0; the emitted instrument table carries `$A0` and attack 6 |
| 6 | `--instrument lead=c1_octave_pulse` on each of the three commands | exit non-zero, `INSTRUMENT_NOT_APPLICABLE`, no output file |
| 7 | `--instrument nosuchpart=pure_sustain` | exit non-zero, `INSTRUMENT_TARGET_UNKNOWN` |
| 8 | `--instrument lead=nosuchinstrument` | exit non-zero, `INSTRUMENT_NOT_FOUND`; the message lists the four ids |
| 9 | `--instrument lead=pure_sustain --instrument lead=pure_pluck` | exit non-zero, `INSTRUMENT_TARGET_DUPLICATE` |
| 10 | `--instrument lead=pure_sustain --instrument bass=pure_pluck` | exit 0; both parts changed, a third untouched |
| 11 | `--instrument lead=pure_sustain` on a song whose DSL declares `INSTRUMENT lead ... dist=$C0` | exit non-zero, `PROFILE_DISTORTION_CONFLICT` |
| 12 | `--instrument lead=pure_sustain` on a song whose DSL declares `INSTRUMENT lead ... att=4` | exit 0; the applied attack is **4**, the profile's decay and sustain are used |
| 13 | `--instrument lead=pure_sustain --profile-bindings b.json`, where `b.json` binds `lead` to a **different** profile | exit non-zero, `INSTRUMENT_BINDING_CONFLICT` |
| 14 | same, but `b.json` binds `lead` to the **same** profile | exit 0 |
| 15 | `--instrument lead=pure_sustain --profile-bindings b.json`, where `b.json` binds a different part | exit 0; both applied |
| 16 | `--instrument-library <empty dir>` | exit non-zero, `INSTRUMENT_LIBRARY_MISSING` |
| 17 | `--instrument-library <dir holding a v0.2 library.json>` | exit 0, the v0.2 instrument is used; the declared version, not the directory name, decides |
| 18 | `--instrument lead=pure_sustain` where the part has no sounding notes | exit non-zero, `PROFILE_CHANNEL_REQUIREMENT` |
| 19 | `import-dsl ... --instrument ... --output-asm x.asm`, then `export-mads` on the produced IR | both asm files are identical |
| 20 | `import-dsl song.dsl --instrument-library <dir>` with **no** `--instrument` | exit 0, output identical to test 1 — a library path alone changes nothing |

Row 20 is the guard for §9: **naming a library is not selecting from it.**

---

## 11. Open questions

These cannot be settled from the repository. Each states what would settle it.

### 11.1 How, if ever, should C1 be supported?

**[open]** C1 is structurally outside both the binding path and the XEX format (§8.3). Options, none
assessed here: extend the IR with a divider-gesture field and teach `mads_exporter`/`player.asm` to emit
it; support C1 for WAV only behind an explicit flag that also refuses `build-xex`; or leave C1
permanently out of the CLI and reachable only from experiment code.

*What would settle it:* a decision on whether the XEX format may grow a within-note divider gesture at
all. That is a player-format change, larger than this contract.

### 11.2 Should the library declare an explicit bank directory?

**[verified]** the library records `registry_path` per instrument and the bank directory is its parent.
That works, but it is an implicit derivation from a file path.

**[open]** whether Lead Library v0.1 should gain an explicit `bank_dir` field. The brief forbids
redesigning the schema unless a concrete blocking issue is found; **no blocking issue was found** —
`Path(registry_path).parent` is unambiguous and correct for the current bank. Recorded as a fragility,
not a defect.

### 11.3 Should the value accept a raw bank profile id?

**[open]** `--instrument lead=pokey_ref_25f94201` is deliberately **not** accepted by this contract;
that is what `--profile-bindings` is for. Whether one flag should accept both namespaces — and how it
would disambiguate them — is undecided. Accepting both would need an explicit discriminator, because
nothing in the strings themselves distinguishes the two namespaces.

### 11.4 What happens when a part spans several channels?

**[verified]** `_instrument_channels` can return more than one channel for one instrument, and
`_resolve_targets` can return more than one IR instrument for one key; the existing binding applies to
all of them. **[open]** whether that is the desired semantics for `--instrument` too, or whether a
multi-channel part should be refused as too broad. The current behaviour suggests applying to all.

### 11.5 Should `compose` and `ai-compose` gain the flag?

**[open]** neither has `--profile-bindings` today. Adding `--instrument` there would let a user generate
and voice in one command, which is convenient but expands the surface. Left out of v1.

### 11.6 Does a "one profile per channel" constraint need surfacing?

**[verified]** `stage10a.py` contains a `ONE_PROFILE_PER_CHANNEL` finding. **[open]** whether assigning
two different library instruments that would land on the same channel can happen through this flag, and
what the error should say. The binding layer's `PROFILE_PAIR_CHANNEL_CONFLICT` and
`PROFILE_CHANNEL_REQUIREMENT` cover the cases seen so far, but this contract does not prove coverage for
every combination.

### 11.7 Is a `--dry-run` needed?

**[open]** `_echo_binding_report` already prints what a binding will change before it is applied
**[verified]**. Whether `--instrument` should gain an explicit "resolve and report, write nothing" mode
is a usability question this contract does not answer.

### 11.8 Is the flag name final?

**[open]** `--instrument` was chosen over the brief's illustrative `--instrument-profile` (§3.1). If a
future contract adds role-based selection, the two flags must read as a coherent pair; renaming later
would be a breaking change, so the name is worth confirming before implementation.

---

## 12. Summary of the proposal

| question | answer |
| :--- | :--- |
| flag | `--instrument <part>=<instrument-id>`, repeatable; `--instrument-library <dir>` optional |
| commands | `import-dsl`, `import-json`, `build-xex` only |
| part | a composition instrument id, resolved by the existing `_resolve_targets` |
| instrument | a Lead Library `instrument_id`, not a bank profile id |
| version | read from `library.json`; the directory defaults to `data/instrument_libraries/lead/v0.1` |
| application | the existing `result_transform` → `_bind_result` → `apply_profile_binding` path, unchanged |
| precedence | unchanged: the composition owns the music, the profile owns the hardware realisation |
| conflicts | explicit errors, never a silent winner |
| C1 | refused with `INSTRUMENT_NOT_APPLICABLE`, because neither the binding path nor the XEX format can express it |
| without the flag | nothing loads, nothing changes |









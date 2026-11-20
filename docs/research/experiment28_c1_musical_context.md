# Experiment 28 — the C1 octave-pulse timbre in a real game-tune composition

Experiments 26 and 27 established the C1 octave-pulse timbre on an isolated note and a four-note test
phrase, and one listener rated C1's low-register phrase 4/5 for usefulness and 4/5 for timbral
interest. That is a test-tone result. This experiment asks the next question: **does C1 add anything
useful when one melodic part of an actual game tune carries it?**

One controlled A/B, nothing else. No new research stage, no production change, no instrument
registration, no scope expansion.

**Audition `experiments/experiment28/A_baseline.wav` against `experiments/experiment28/B_c1.wav`.**

## 1. The composition selected, and why

| | |
|---|---|
| file | `examples/songs/Vaults-of-Nhyrmeth.dsl` |
| title / author | *Vaults of Nhyrmeth* — "POKEY Composer" |
| tempo / grid | 90 BPM, 5 frames per row (50 Hz grid) |
| length | 2280 frames = **45.6 s**, `AUDCTL = $10` (16-bit bass join) |
| parts | CH1+CH2 bass (16-bit), **CH3 lead**, CH4 percussion |
| sequence | A1 A2 B1 B2 A1 A2 A3 (seven 64/68-row patterns) |

Why this one, against the brief's criteria:

* **recognisable melody** — the lead is a clear D-minor line (D4 E4 F4 G4 A4 D5 C5 Bb4 C5 A4 F4 G4
  A4 D4 in the first section), which is what makes a timbre change audible as a change of instrument
  rather than as noise;
* **at least one supporting part** — a sustained 16-bit bass on CH1+CH2 and percussion on CH4, so the
  lead sits in a real arrangement and the listener has a fixed reference;
* **enough sustained notes** — 99 sounding lead notes over 2220 frames, many of them 6-, 8- and
  16-row held notes, so the pulse has time to be heard inside a note rather than only at onsets;
* **renders deterministically through the existing pipeline** — two compilations produce byte-identical
  register streams (asserted);
* **clean provenance** — it is the project's **own** documented example composition
  (`docs/music_dsl.md` §4, authored by the project) and is already a test fixture
  (`tests/data/sound_profiles/vaults_of_nhyrmeth.dsl`). It is **not** a copied commercial game
  soundtrack. The other DSL examples in `examples/songs/` are transcriptions of copyrighted Polish TV
  themes and were rejected for exactly that reason.

No new composition was written, because a suitable existing one was available.

## 2. Which part received C1, and why

**Channel 3, the lead — the melodic part.**

* The brief asks for one *melodic* part, and CH3 is the melody.
* CH3 is an **8-bit** channel, which is precisely the case Experiment 27's C1 implementation covers
  (single 8-bit channel, nominal divider `N`, octave `N // 2`).
* The 16-bit bass on CH1+CH2 was deliberately left alone: C1 as implemented has no 16-bit divider
  arithmetic, so applying it there would have meant inventing new logic — a different effect, not this
  experiment. Reporting that as the boundary is preferable to quietly changing the algorithm.
* The percussion was left alone: it is not melodic, and the brief forbids applying the effect
  indiscriminately.

The lead's register is MIDI **60–81** (C4–A5), i.e. nominal dividers **35–120** (261.7–879.7 Hz),
with octave-up values 17–60 (519.2–1759.4 Hz). Both stay well inside the renderer's 20 kHz clamp and
the tracker's `$FE` divider limit.

## 3. The exact differences between A and B

One compilation, two register streams. **A** is `ir.compile_ir_to_pokey_frames` output, unmodified.
**B** is that same array with two columns of one channel rewritten:

| register | A | B |
|---|---|---|
| `AUDF3` (column 4) | the note's nominal divider `N`, constant for the whole note | `N` on even frame offsets, `N // 2` on odd offsets, restarting at every note onset |
| `AUDC3` (column 5), generator bits 7..5 | `$A0` (pure tone), constant | `$40` (poly5-gated poly4) on every sounding frame |
| `AUDC3`, volume bits 3..0 | the instrument's envelope | **identical, frame for frame** |

Measured, not asserted: **2220 of 2280 frames differ, and only in register columns [4, 5]**.

Everything else is byte-identical between the two streams:

* `AUDF1`, `AUDC1`, `AUDF2`, `AUDC2`, `AUDF4`, `AUDC4` and `AUDCTL` — frame for frame;
* the note onsets, pitches, durations and phrase timing on every channel (the transform reads the
  compiler's own note grid, computed with the same row-cursor arithmetic);
* rests and any zero-volume frame keep the baseline's `AUDF3` and `AUDC3` untouched, so the transform
  cannot introduce a register write the baseline did not make;
* the frame rate, sample rate, bit depth, duration and render path.

### The effect is Experiment 27's, not a re-implementation

`apply_c1` calls `pokey_octave_pulse_experiment.SCHEDULES["C1"].divider_for_frame` directly for the
divider, and takes the generator from `pokey_timbre_experiment.C_GENERATOR` and the octave value from
`pokey_timbre_experiment.octave_divider`. Rendering uses
`pokey_timbre_experiment.render_registers` / `to_int16` / `write_wav`. No second implementation of the
alternation exists in this experiment.

### One deliberate narrowing, stated rather than glossed over

Experiments 26 and 27's C1 **also** replaced the note's volume shape with
`pokey_timbre_experiment.plucked_volume_shape`. **This experiment does not.** The brief lists C1's
relevant behaviour as the generator, the divider alternation and the timing, requires the same note
onsets, pitches and durations, and forbids changing the musical content. A different envelope would
change articulation and dynamics — a second dimension — and would make it impossible to tell whether
a difference was heard as *timbre* or as *articulation*. So the volume nibble is held at the
baseline's and the A/B difference is the generator and the divider only.

**This means B is not the exact C1 that Experiment 27 listened to.** It is a narrower version of it,
and the report says so rather than implying otherwise.

## 4. The gain and rendering policy

Unchanged from Experiments 26 and 27:

* both variants are rendered **raw** — the experimental renderer returns an un-normalised buffer;
* **one** gain is derived from the louder of the two raw renders and applied to both;
  `reference_peak = 3.02463102`, `gain = 0.29755696`, target peak 0.90;
* **no per-file normalisation anywhere**, so the loudness relation between A and B survives.

| file | raw peak | raw RMS | RMS after the shared gain |
|---|---|---|---|
| `A_baseline.wav` | 3.024631 | 0.8083 | **0.2405** |
| `B_c1.wav` | 3.024631 | 0.8075 | **0.2403** |

The two delivered RMS figures differ by 0.01 dB, so the comparison is effectively level-matched: the
generator swap happens not to change the total mix energy much. A test asserts the ratio stays inside
±10 %, and the actual figure is recorded in `summary.json` rather than assumed.

The peak of 3.02 (rather than 2.0) is expected: three channels sound simultaneously, and the project's
DC-blocking filter passes the summed square-wave edges.

## 5. Validation and test results

`tests/test_pokey_c1_musical_context_experiment.py` — **52 tests, all passing (35.5 s)**. What they
pin down:

| claim | how it is checked |
|---|---|
| A is the production compiler's output | byte-equality against `ir.compile_ir_to_pokey_frames(song)` |
| one compilation, two streams | both variants derived from the same `baseline_stream(song)` call |
| the note grid is the compiler's | spans are ordered, non-overlapping, whole rows, inside the stream; the baseline's `AUDF3` per note equals `e26.note_divider(midi)` and is constant within the note; every sounding frame lies inside a non-rest span |
| note count, pitch, onset, duration unchanged | 99 sounding lead notes; the transform only rewrites registers, never the grid |
| only the intended registers changed | the differing columns are exactly `{4, 5}` = `AUDF3`/`AUDC3`; channels 1, 2 and 4 and `AUDCTL` are byte-identical |
| exactly the sounding frames changed | the set of differing frames equals the set of sounding lead frames (2220), and no other frame differs |
| the C1 generator schedule | `$40` on every changed frame, `$A0` in the baseline |
| the C1 divider schedule | per frame, `SCHEDULES["C1"].divider_for_frame(N, N//2, offset, index)`, recomputed independently in the test; the alternation restarts at each note onset; the value set per note is exactly `{N, N // 2}` |
| the volume is untouched | the AUDC low nibble is equal in A and B on every frame |
| silent frames are untouched | rests and zero-volume frames keep both baseline registers |
| the effect is Experiment 27's | identity/parameter checks on `SCHEDULES["C1"]`, `C_GENERATOR`, `octave_divider` |
| determinism | the transform is a pure function; two renders produce byte-identical WAVs, summary and README |
| the audio differs as expected | the two WAVs differ, and more than half the samples differ |
| the gain policy | one shared gain, `peak_after_gain == raw_peak * gain` for both, nothing clips, RMS ratio within ±10 % |
| no production change | SHA-256 of ten production files plus the DSL, before and after a render; no CLI wiring; no production module imports the experiment |

**Existing regression tests, exact result:** running the new file together with the Experiment 26 and 27
suites, the Experiment 27 listening-page suite, `test_cli.py`, `test_dsl.py`, `test_pokey_semantics.py`,
`test_sound_profiles.py`, `test_sound_profile_library.py` and `test_ai_composition.py` gives

```
417 passed in 75.64s
```

Two pre-existing guards in the Experiment 26 and 27 test files (`no production module imports the
prototype`) had to be updated: Experiment 28 reuses both modules by design, so their exclusion sets now
name all three experiment modules. The guards still enforce their real invariant — no *production*
module may depend on an experiment — and the change is confined to test files.

## 6. Known limitations

1. **`$40` is not a clean octave oscillator.** `$40` is poly5-gated poly4, and the poly5 gate runs at
   the divider rate too. Doubling the divider therefore doubles the *gate* rate as well as the tone:
   the result is a texture and pitch change together, not an added octave. A listener may hear it as a
   rough or metallic colour rather than as a doubled pitch. This is the single most important caveat
   for interpreting the result, and it was already the leading limitation in Experiment 27.
2. **The volume shape was not changed**, so this is C1's generator and divider only — a narrower change
   than the C1 Experiment 27 listened to. If C1's *volume* shape contributed to its appeal, this
   experiment would not show it.
3. **The two files differ in more than the generator.** The divider also moves, and `$40` and `$A0` do
   not have identical energy at the same DAC volume, so a small part of any perceived difference may be
   loudness. The measured RMS of both files is in `summary.json` (0.2405 vs 0.2403, a 0.01 dB gap), so
   this can be judged rather than guessed.
4. **One composition, one part, one register.** Nothing here generalises to other tunes, other parts or
   other registers. The lead sits at MIDI 60–81 (C4–A5) and the octave-up values land at 519–1759 Hz, so
   this says nothing about very low or very high registers.
5. **The 16-bit bass was not tested.** C1 has no 16-bit divider arithmetic; a bass application would be
   a different experiment. Experiment 27's strongest subjective result was in the *low* register, so
   this is a real gap rather than a hypothetical one — it is simply out of scope here.
6. **Fixed 25 Hz alternation.** The divider can only change once per 50 Hz frame, so the rate cannot be
   varied in this experiment.
7. **One listener, one session.** The preliminary ratings from Experiment 27 are not evidence of general
   superiority, and neither is anything in this report.
8. **The mechanism is not hardware-verified for this use.** The register stream is real and the renderer
   is the project's, but the 6502 player's own behaviour when AUDC is rewritten every frame has not been
   re-verified for this specific pattern; the experiment stays inside the WAV preview.

## 7. What this experiment does not establish

**It establishes neither general musical superiority nor readiness for production integration.**

Specifically:

* **no quality is measured.** The tests confirm the experiment is *technically correct* — that A is the
  production output, that B changes only the intended registers, that the note grid is unchanged, that
  the effect is Experiment 27's, and that the levels are handled honestly. A larger RMS, a different
  hash or more register changes are **not** evidence of a better sound. Whether B sounds better, richer,
  more interesting, or like a fault is a question for the ear, and a null result is a result.
* **nothing is integrated.** No DSL, IR, compiler, MADS exporter, player or CLI change. C1 is **not**
  registered as an instrument, nothing was added to the instrument library, and the experiment is not
  reachable from the production command line. Making C1 a permanent instrument would need a separate
  decision and a separate piece of work.
* **it is one composition, one part, one listener.** Even if the listener prefers B, that would be a
  preliminary subjective result about *Vaults of Nhyrmeth*'s lead line — not about C1 in general, and not
  a licence to change the production instrument set.

The next step is the listener's, and it is a listening judgement, not a technical one.

## Reproduction

The exact command that produces both WAVs, `summary.json` and the listening `README.md`:

```
python -m atari_music.pokey_c1_musical_context_experiment
```

Deterministic: the same command reproduces all four files byte for byte, and a test asserts it.

Files produced in `experiments/experiment28/`:

| file | what it is |
|---|---|
| `A_baseline.wav` | the composition as the existing pipeline renders it |
| `B_c1.wav` | the same render with C1 on the lead channel only |
| `README.md` | how to listen |
| `summary.json` | the composition, the target, the effect, the difference report, the level policy, the measurements, the limitations |




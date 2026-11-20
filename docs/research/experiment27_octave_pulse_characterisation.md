# Experiment 27 — Musical characterisation of the POKEY octave-pulse timbre

Develops **only** variant C of Experiment 26, which was judged interesting on listening. The question
is whether a controlled switch of AUDF between `N` and `N // 2` gives a repeatable, musically usable
instrument timbre.

No historical corpus was re-analysed, no new archaeology stage was started, and **no production file
was changed**. The experiment is one new module, `src/atari_music/pokey_octave_pulse_experiment.py`,
one new test file, and the WAV set in `experiments/experiment27/`.

## 1. Starting point: the real variant C, not a reconstruction

C1 is Experiment 26's variant C. The module does not re-implement it — `c1_stream` calls
`pokey_timbre_experiment.contrast_stream` directly, and the generator (`$40`, poly5-gated poly4), the
volume shape (`plucked_volume_shape`), the renderer, the DAC/polynomial tables and the shared-gain
policy are all taken from that module.

The strongest evidence that C1 is the artefact that was actually listened to: **the delivered
`C1_pulse1_note.wav` and `C1_pulse1_phrase.wav` are byte-identical to Experiment 26's
`C_contrast_note.wav` and `C_contrast_phrase.wav`**, because the register streams and the shared gain
are the same. The test suite asserts this.

## 2. The one parameter under study

The pulse **schedule** is the only thing that changes. Generator, volume shape, note grid, channel
(`CH1`), clock (`AUDCTL = $00`) and render path are identical in all four variants, so each
comparison moves one thing:

| variant | `hold_frames` | `active_frames` | `active_notes` | alternation | what it changes vs C1 |
|---|---|---|---|---|---|
| **C1** pulse1 | 1 | whole note | every note | 25 Hz | — (Experiment 26's C) |
| **C2** pulse4 | **4** | whole note | every note | 6.25 Hz | the pulse **rate** only |
| **C3** onset | 1 | **8** | every note | 25 Hz | the pulse **duration** only |
| **C4** selected | 1 | whole note | **notes 0 and 2** | 25 Hz | **which notes** carry it only |

A note with the pulse switched off keeps the same generator and the same volume shape and simply
holds a constant divider. That is the reading of "the normal sound between them" that does not change
a second parameter.

## 3. Material

| score | notes | length |
|---|---|---|
| `note` | A-4 (MIDI 69) | 48 frames = 0.96 s |
| `phrase` | A-4, C-5, E-5, C-5 | 80 frames = 1.60 s |
| `phrase_low` | the same phrase an octave down: A-3, C-4, E-4, C-4 | 80 frames = 1.60 s |

`note` and `phrase` are Experiment 26's, unchanged. `phrase_low` is new, so the effect can be judged
in a second register — and it is a sharp test, because the low phrase's octave-up dividers
(71 / 60 / 47) are exactly the high phrase's own fundamentals.

Twelve WAVs: four variants × three scores. All 44.1 kHz, 16-bit mono PCM, 50 Hz frame grid.

## 4. Level policy

Unchanged from Experiment 26: every variant rendered **raw**, one gain derived from the single
loudest of the twelve renders (reference peak 2.0, so gain `0.45`), applied to all twelve. No file is
normalised on its own. Because the generator, the volume and the reference peak are the same as in
Experiment 26, this is the same gain Experiment 26 used, so C1 here is directly loudness-comparable
with Experiment 26's C files. Measured RMS after the shared gain: 0.2803–0.2807 on the note,
0.3061–0.3078 on the phrases — a spread under 0.2 dB, so the variants are level-matched and the
comparison is about timbre.

## 5. Deliverables

`experiments/experiment27/` (local, gitignored like the rest of the project's generated audio):

* `C1_pulse1_{note,phrase,phrase_low}.wav`
* `C2_pulse4_{note,phrase,phrase_low}.wav`
* `C3_onset_{note,phrase,phrase_low}.wav`
* `C4_selected_{note,phrase,phrase_low}.wav`
* `summary.json` — the baseline, the parameter table, both divider values per note, the level policy,
  the limitations and the per-file measurements
* `README.md` — the listening instruction

Regenerate with:

```
python -m atari_music.pokey_octave_pulse_experiment
```

Deterministic: the same command reproduces all fourteen files byte for byte.

## 6. Technical verdict — which variants are correct, and how they differ

All four are technically correct: every frame's AUDF is exactly the value the declared schedule
names, no other register moves, and every divider is encodable by the project's own tracker format.

| variant | divider switches (note / phrase) | difference from C1 |
|---|---|---|
| C1 | 47 / 79 | the baseline: the divider flips every frame for the whole note, on every note |
| C2 | 11 / 19 | the same pulse, held 4 frames per value — 4× slower, 6.25 Hz instead of 25 Hz |
| C3 | 8 / 35 | the pulse stops after frame 8 (160 ms); the rest of the note holds a constant divider |
| C4 | 47 / 41 | notes 0 and 2 pulse, notes 1 and 3 hold a constant divider |

One consequence worth stating plainly rather than hiding: **on the single-note score C4 is identical
to C1**, because the only note is note 0 and C4 selects note 0. That is a property of the
parameterisation, it is asserted by a test, and it is why C4's note file carries no new information
beyond C1's.

The number of divider switches is a description of how much the mechanism is doing. It is **not** a
quality score, and more switches do not mean a better sound.

## 7. Real limitations of the mechanism

* The player writes registers once per 50 Hz frame, so the divider cannot change more often than
  every 20 ms. The fastest alternation is 25 Hz, and the achievable rates are 50 / (2 · hold) Hz:
  25, 12.5, 8.33, 6.25 Hz … A faster pulse cannot be expressed and is not simulated.
* `N // 2 == 0` for a nominal divider of 0 or 1, which is POKEY's *fastest* divider rather than an
  octave. The lowest note used here is A-3 (AUDF 143), so the experiment never reaches that region.
* AUDF clamps at `$FE` so the tracker format stays encodable, so the octave relation is only exact
  while `N <= 254` — about 124 Hz and above at 64 kHz. Below that, the "octave" is approximate.
* `$40` is poly5-gated poly4, and the poly5 gate runs at the divider rate too. Doubling the divider
  therefore doubles the *gate* rate as well as the tone: this is a texture and pitch change together,
  **not** a clean octave oscillator. That is the most important limitation for judging the sound.
* AUDCTL is fixed for the whole stream, so the clock cannot change inside a note.

## 8. What is not claimed, and what was not done

Nothing here measures quality, and no winner is picked. The final judgement of musical usefulness is
a listening question. In particular, a larger switch count, a larger RMS or a different hash are not
evidence of a better sound.

The mechanism is **not** integrated into the production DSL or IR, no general instrument system or
modulation layer was built, no further historical analysis was done, and no production file was
changed. The experiment is not reachable from the production command line.


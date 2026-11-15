# Experiment 26 — Audible POKEY timbre prototype

A small, isolated experiment. Its only output is six WAV files you can listen to and compare.
It is not an archaeology stage, not a corpus study and not a similarity claim.

**Nothing in the production pipeline was changed.** The prototype lives in one new module,
`src/atari_music/pokey_timbre_experiment.py`, and one new test file. No production DSL, IR,
compiler, MADS exporter, player, CLI command or profile bank was touched — `cli.py` in particular
was not edited, so the experiment is not reachable from the production command line.

## 1. What the existing code already does

Checked by reading and running it, not assumed:

| Mechanism | Status before this experiment |
|---|---|
| `pokey_synth.render_pokey_samples(frames, …)` renders an **arbitrary** `(N, 9)` register stream at 50 Hz → 44.1 kHz | already works, and it decodes AUDC **once per frame** |
| a per-frame **AUDC distortion** change | already renderable — the limitation is in the compiler, not the renderer |
| a per-frame **AUDF divider** change | already renderable, for the same reason |
| `IRInstrument.volume_contour` → `ir.apply_volume_contour` | already in the pipeline; a per-frame AUDC volume shape that reaches the WAV preview |
| `IRNote.distortion`, `IREnvelope`, `pokey_hw.player_envelope_volumes`, `ir.resolve_audctl_mode` | already in the pipeline |
| `IRMacroStep` / `IRInstrument.macro`, `vibrato_depth`, `vibrato_speed`, `IRNote.slide_semitones`, `arpeggio_offsets` | reserved and deliberately **not rendered** |
| a mid-note distortion change through the IR | **not expressible**: `_render_note_to_frames` writes `(distortion & 0xE0) | vol` with one constant generator for the whole note |
| `render_pokey_to_wav` | normalises **every** buffer to peak 0.90, which would erase the loudness relation between A, B and C |

So there was exactly **one** renderer-level gap: honest, un-normalised level handling. Everything
else is a *compiler* limitation, and the renderer already accepts the streams the experiment needs.

## 2. The one prototype mechanism

Because the production renderer already takes any register stream, the only new mechanism is:

* a **register-stream writer** that emits mid-note AUDC and AUDF changes the compiler cannot
  express, and
* a render path that applies **one shared gain** instead of per-buffer normalisation.

The render loop is a faithful copy of `pokey_synth.render_pokey_samples` up to the normalisation
step, and `tests/test_pokey_timbre_experiment.py` asserts the two agree **bit-for-bit** once the
production normalisation is re-applied. The DAC ladder and the POLY4/5/9/17 tables are imported
from `pokey_synth`, not re-derived. So the prototype is not a second synth with its own sound.

## 3. The controlled experiment

Fixed for all three variants: the notes, the pitches, the durations, the channel (CH1), the clock
(`AUDCTL = $00`, 4 independent 8-bit channels at 64 kHz), 50 Hz frames, 44.1 kHz 16-bit mono WAV.

| Score | Notes | Length |
|---|---|---|
| `note` | A-4 (MIDI 69) | 48 frames = 0.96 s |
| `phrase` | A-4, C-5, E-5, C-5 (69, 72, 76, 72) | 80 frames = 1.60 s |

| Variant | Source | Generator (AUDC bits 7..5) | Divider | Volume |
|---|---|---|---|---|
| **A** baseline | `ir.compile_ir_to_pokey_frames` — the existing pipeline, unchanged | `$A0` constant (pure tone) | constant per note | `pokey_hw.player_envelope_volumes` (the player's own ADSR) |
| **B** evolving | prototype register writer | steps every 8 frames (160 ms): `$A0 → $60 → $C0 → $40`, restarting at each note onset | constant per note | **identical to A** |
| **C** contrast | prototype register writer | `$40` constant (poly5-gated poly4) | alternates every frame between `N` and `N // 2` — an octave pulse at 25 Hz | softer onset than A: 1-frame attack, 8-frame glide to 12, 3-frame release |

B is deliberately a **one-dimension** change: it alters only the generator nibble, so any timbre
difference you hear from A cannot be a level difference. C is deliberately a three-dimension
contrast, and its sustain level equals A's so the comparison is about character, not loudness.

Realised pitch (8-bit POKEY quantisation): A-4 = AUDF 71 → 439.84 Hz against a nominal 440 Hz,
C-5 = 60 → 519.2 Hz, E-5 = 47 → 659.8 Hz.

## 4. Level handling

Every variant is rendered **raw**. One gain — `TARGET_PEAK / reference_peak` = `0.90 / 2.0` = `0.45`
— is derived from the loudest of the six raw renders and applied to all six. Nothing clips, the
loudest file peaks at exactly the target, and every loudness relation between A, B and C survives
untouched. **No file is normalised on its own.**

The raw peak is 2.0 for all six because every variant contains the same square-wave edges (the
project's DC-blocking render path passes the ±1 → ∓1 transitions); the differences show up in RMS,
not in peak. Measured RMS after the shared gain: A note 0.2494, B note 0.2493, C note 0.2807;
A phrase 0.2345, B phrase 0.2346, C phrase 0.3078. A and B are within 0.1 % of each other by
design; C is about 1 dB louder because the `$40` generator carries more high-frequency energy.

## 5. Deliverables

`experiments/experiment26/` (local, gitignored like the rest of the project's generated audio):

* `A_baseline_note.wav`, `B_evolving_note.wav`, `C_contrast_note.wav`
* `A_baseline_phrase.wav`, `B_evolving_phrase.wav`, `C_contrast_phrase.wav`
* `summary.json` — every parameter, the score, the level policy and the per-file measurements
* `README.md` — the short listening instruction

Regenerate with:

```
python -m atari_music.pokey_timbre_experiment
```

Deterministic: the same command reproduces all eight files byte for byte.

## 6. What is not claimed

A more complex register trace is not automatically a better sound. Nothing here measures quality,
and the tests only confirm that the experiment is technically correct — that the renderer is
faithful, that the variants play identical notes, that they genuinely differ, and that the levels
are handled honestly. Whether B or C sounds *better* is a question for the ear, and a null result
is a result.

Not done, on purpose: no production change, no general instrument system, no profile bank, no
modulation language, no further historical analysis, no statistical superiority claim.


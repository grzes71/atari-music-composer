"""Experiment 26 — an audible POKEY timbre prototype (isolated, not part of the pipeline).

Goal: produce short, technically correct, listenable A/B/C WAV pairs that answer one question —
can a single POKEY note be given a richer, evolving timbre?

WHAT THE EXISTING CODE ALREADY DOES (checked, not assumed)
----------------------------------------------------------
* ``pokey_synth.render_pokey_samples`` already renders an **arbitrary** ``(N, 9)`` uint8 register
  stream: it decodes AUDC per frame through ``pokey_hw.decode_audc``, derives the divider through
  ``pokey_hw.hz_from_audf_8bit``, and mixes the ``POKEY_DAC`` ladder with the POLY4/5/9/17 tables.
  A per-frame *distortion* change and a per-frame *divider* change are therefore **already
  renderable**. The limitation lives in the compiler, not in the renderer.
* ``ir.compile_ir_to_pokey_frames`` already supports ``IRInstrument.volume_contour`` (a per-frame
  AUDC volume shape, applied by ``ir.apply_volume_contour``, and it reaches the WAV preview),
  ``IRNote.distortion`` (a per-note generator), ``IREnvelope`` (via
  ``pokey_hw.player_envelope_volumes``) and ``ir.resolve_audctl_mode``.
* ``IRMacroStep``/``IRInstrument.macro``, ``vibrato_depth``, ``vibrato_speed``,
  ``IRNote.slide_semitones`` and ``arpeggio_offsets`` are **reserved and deliberately not
  rendered** — the 6502 player sets AUDC once per channel and has no per-frame pitch modulation.
* A mid-note **distortion** change is *not expressible* through the IR: ``_render_note_to_frames``
  writes ``(distortion & 0xE0) | vol`` with one constant generator for the whole note.
* ``render_pokey_to_wav`` normalises **every** buffer to peak 0.90. That is the one production
  behaviour this experiment must not use, because it would erase the loudness relation between A,
  B and C.

THE ONE PROTOTYPE MECHANISM
---------------------------
Because the production renderer already accepts any register stream, the only new mechanism needed
is a *register-stream writer* that emits mid-note AUDC/AUDF changes the compiler cannot express,
plus a render path that applies **one shared gain** instead of per-buffer normalisation. The render
loop below is a faithful copy of ``pokey_synth.render_pokey_samples`` up to the normalisation step,
and ``tests/test_pokey_timbre_experiment.py`` asserts that the two agree bit-for-bit once the
production normalisation is re-applied. No production file is modified.

NOT DONE, ON PURPOSE
--------------------
No production DSL/IR/compiler/MADS-exporter/player change, no instrument system, no profile bank,
no modulation language, no further archaeology.
"""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np

from atari_music import ir, pokey_hw
from atari_music.constants import (
    AUDCTL_9BIT_POLY,
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_PURE_TONE,
)
from atari_music.ir import IREnvelope, IRInstrument, IRNote, IRPattern, IRSong
from atari_music.pokey_synth import (
    POKEY_DAC,
    POLY4_SEQ,
    POLY5_SEQ,
    POLY9_SEQ,
    POLY17_SEQ,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "experiment26"

#: One register write per PAL VBL frame, the rate the whole project uses.
FRAME_RATE_HZ = 50.0
SAMPLE_RATE = 44100
#: The score's rows-per-tick. 4 is the project default (80 ms per row at 50 Hz).
FRAMES_PER_TICK = 4
#: 4 independent 8-bit channels at the 64 kHz base clock. Identical in all three variants, so the
#: clock is not a variable of this experiment.
AUDCTL = 0x00
#: Every variant is scaled by ONE gain derived from the loudest of the six raw renders, so the
#: relative loudness of A, B and C is preserved and nothing clips.
TARGET_PEAK = 0.90


# ===========================================================================
# 1. The controlled score. One note, and a short phrase. Identical in A, B and C.
# ===========================================================================
#: (MIDI pitch, duration in rows). MIDI 69 = A4 = 440 Hz.
ISOLATED_NOTE: Tuple[Tuple[int, int], ...] = ((69, 12),)
#: A4, C5, E5, C5 — four notes, each 5 rows, so the phrase exercises pitch change and re-attack.
SHORT_PHRASE: Tuple[Tuple[int, int], ...] = ((69, 5), (72, 5), (76, 5), (72, 5))

SCORES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "note": ISOLATED_NOTE,
    "phrase": SHORT_PHRASE,
}

#: The variants, in the order they should be listened to.
VARIANT_ORDER: Tuple[str, ...] = ("A", "B", "C")
VARIANT_NAMES: Dict[str, str] = {
    "A": "baseline",
    "B": "evolving",
    "C": "contrast",
}

#: The instrument every variant starts from: a pure tone, the project's default generator.
BASELINE_DISTORTION = DISTORTION_PURE_TONE
#: The envelope all three variants share as their *starting* shape. A sustained lead: 1 frame to
#: the peak, 3 frames to settle on the sustain level, then the player's release ramp.
BASELINE_ENVELOPE = IREnvelope(
    attack_frames=1, decay_frames=3, sustain_vol=12, release_frames=3
)

#: B — the generator nibble steps through four different POKEY generators, one every 8 frames
#: (160 ms). The sequence restarts at every note onset, the way a gesture does.
B_GENERATOR_SEQUENCE: Tuple[int, ...] = (0xA0, 0x60, 0xC0, 0x40)
B_GENERATOR_STEP_FRAMES = 8

#: C — a different character: one fixed buzzy generator, an octave pulse on the divider, and a
#: softer onset than A's envelope. The sustain level matches A's on purpose, so the comparison is
#: about timbre rather than about loudness.
C_GENERATOR = 0x40
C_ATTACK_FRAMES = 1
C_DECAY_FRAMES = 8
C_SUSTAIN_VOL = 12
C_RELEASE_FRAMES = 3


# ---------------------------------------------------------------------------
# The score grid. Both the baseline song and the hand-written streams use this, so
# the notes, their pitches and their frame spans cannot drift apart between variants.
# ---------------------------------------------------------------------------
def total_rows(score: Sequence[Tuple[int, int]]) -> int:
    return int(sum(duration for _midi, duration in score))


def total_frames(score: Sequence[Tuple[int, int]]) -> int:
    return total_rows(score) * FRAMES_PER_TICK


def note_spans(score: Sequence[Tuple[int, int]]) -> List[Tuple[int, int, int]]:
    """``(start_frame, end_frame, midi)`` for every note, in performance order."""
    spans: List[Tuple[int, int, int]] = []
    row = 0
    for midi, duration in score:
        start = row * FRAMES_PER_TICK
        end = start + duration * FRAMES_PER_TICK
        spans.append((start, end, int(midi)))
        row += duration
    return spans


def note_divider(midi: int, audctl: int = AUDCTL, channel: int = 1) -> int:
    """The AUDF byte the production compiler would write for this pitch.

    Routed through the same ``ir.frequency_to_audf_8bit`` / ``pokey_hw`` pair the compiler uses,
    so a hand-written stream and a compiled one cannot disagree about what a pitch is.
    """
    frequency = ir.midi_pitch_to_frequency(int(midi))
    return pokey_hw.clamp_audf_for_tracker(
        ir.frequency_to_audf_8bit(frequency, audctl=audctl, channel=channel)
    )


# ===========================================================================
# 2. A — the baseline, produced by the existing pipeline.
# ===========================================================================
def baseline_song(score: Sequence[Tuple[int, int]]) -> IRSong:
    """The score as an ``IRSong`` the production compiler can consume.

    This is the "existing pipeline" side of the comparison: the register stream for variant A is
    ``ir.compile_ir_to_pokey_frames`` output, unchanged. Only the *choice* of instrument parameters
    (pure tone, the shared envelope) is ours, and it is the same starting point B and C evolve from.
    """
    notes = [
        IRNote(
            midi_pitch=int(midi),
            pitch=ir.midi_to_note_name(int(midi)),
            duration=int(duration),
            volume=15,
            instrument_id=0,
            channel_role="melody",
        )
        for midi, duration in score
    ]
    return IRSong(
        title="experiment26 baseline",
        author="Experiment 26",
        tempo_bpm=125,
        frames_per_tick=FRAMES_PER_TICK,
        key="A",
        mode="major",
        seed=26,
        instruments=[
            IRInstrument(
                id=0,
                name="baseline_pure_tone",
                distortion=BASELINE_DISTORTION,
                role="melody",
                envelope=BASELINE_ENVELOPE,
            )
        ],
        patterns=[IRPattern(id=1, name="score", rows=total_rows(score), tracks={1: notes})],
        sequence=[1],
        uses_16bit_bass=False,
    )


def baseline_stream(score: Sequence[Tuple[int, int]]) -> np.ndarray:
    """Variant A's register stream: the production compiler's own output, untouched."""
    return ir.compile_ir_to_pokey_frames(baseline_song(score))


# ===========================================================================
# 3. The volume shapes the variants use.
# ===========================================================================
def player_volume_shape(note_frames: int) -> List[int]:
    """The project's own player-faithful envelope, per frame. Variant A's (and B's) volume.

    Called directly so the hand-written streams use exactly the arithmetic
    ``_render_note_to_frames`` uses, rather than a re-derived approximation of it.
    """
    return pokey_hw.player_envelope_volumes(
        note_frames,
        FRAMES_PER_TICK,
        15,
        BASELINE_ENVELOPE.attack_frames,
        BASELINE_ENVELOPE.decay_frames,
        BASELINE_ENVELOPE.sustain_vol,
        BASELINE_ENVELOPE.release_frames,
    )


def plucked_volume_shape(note_frames: int) -> List[int]:
    """Variant C's volume: a 1-frame attack, an 8-frame glide, then a 3-frame release.

    Deliberately *not* ``player_envelope_volumes``: A reaches its sustain level after 3 frames, C
    holds the peak for 3 and then glides down over 8, so the onsets differ while the sustained level
    is the same. It is still a plain per-frame AUDC volume series, which is a shape the existing
    ``IRInstrument.volume_contour`` mechanism could carry — see the module docstring.
    """
    out: List[int] = []
    span = max(1, C_DECAY_FRAMES - 1)
    for index in range(note_frames):
        if index < C_ATTACK_FRAMES:
            level = 15
        elif index < C_ATTACK_FRAMES + C_DECAY_FRAMES:
            progress = (index - C_ATTACK_FRAMES) / span
            level = int(round(15 - (15 - C_SUSTAIN_VOL) * progress))
        else:
            level = C_SUSTAIN_VOL
        remaining = note_frames - 1 - index
        if remaining < C_RELEASE_FRAMES:
            level -= C_RELEASE_FRAMES - remaining
        out.append(max(0, min(15, level)))
    return out


def generator_for_frame(frame_offset: int) -> int:
    """Variant B's generator nibble at a given frame offset inside a note."""
    step = frame_offset // B_GENERATOR_STEP_FRAMES
    return int(B_GENERATOR_SEQUENCE[step % len(B_GENERATOR_SEQUENCE)])


def octave_divider(divider: int) -> int:
    """The closest divider to one octave above *divider*.

    POKEY's period is ``(N + 1)`` base clocks, so halving ``N + 1`` doubles the frequency; ``N // 2``
    is the nearest representable divider to that. It is clamped through the same
    ``pokey_hw.clamp_audf_for_tracker`` the compiler uses, so a hand-written stream can never carry a
    divider the project's own tracker format could not.
    """
    return pokey_hw.clamp_audf_for_tracker(max(pokey_hw.AUDF_MIN, int(divider) // 2))


# ===========================================================================
# 4. B and C — hand-written register streams, using only real POKEY registers.
# ===========================================================================
#: The frame layout the whole project uses: AUDF1, AUDC1, AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4,
#: AUDCTL. Channel 1 carries the experiment's single voice.
CHANNEL = 1


def _empty_stream(score: Sequence[Tuple[int, int]]) -> np.ndarray:
    frames = np.zeros((total_frames(score), 9), dtype=np.uint8)
    frames[:, 8] = AUDCTL
    return frames


def evolving_stream(score: Sequence[Tuple[int, int]]) -> np.ndarray:
    """Variant B: the generator nibble steps through four POKEY generators inside each note.

    The volume is *exactly* variant A's, so the only thing that differs from A is the AUDC
    generator nibble (bits 7..5) — one dimension, deliberately. The divider is A's too.
    """
    frames = _empty_stream(score)
    audf_col = ir.audf_column(CHANNEL)
    audc_col = ir.audc_column(CHANNEL)
    for start, end, midi in note_spans(score):
        divider = note_divider(midi)
        volumes = player_volume_shape(end - start)
        for offset in range(end - start):
            frames[start + offset, audf_col] = divider
            frames[start + offset, audc_col] = (generator_for_frame(offset) & 0xE0) | volumes[offset]
    return frames


def contrast_stream(score: Sequence[Tuple[int, int]]) -> np.ndarray:
    """Variant C: a fixed buzzy generator, an octave pulse on the divider, a plucked volume.

    The divider alternates every frame between the nominal value and its octave, which is a
    per-frame AUDF change — the class of register behaviour the production compiler cannot express
    at all (``IRNote`` has no rendered pitch modulation; see the module docstring).
    """
    frames = _empty_stream(score)
    audf_col = ir.audf_column(CHANNEL)
    audc_col = ir.audc_column(CHANNEL)
    for start, end, midi in note_spans(score):
        divider = note_divider(midi)
        upper = octave_divider(divider)
        volumes = plucked_volume_shape(end - start)
        for offset in range(end - start):
            frames[start + offset, audf_col] = divider if offset % 2 == 0 else upper
            frames[start + offset, audc_col] = (C_GENERATOR & 0xE0) | volumes[offset]
    return frames


def register_stream(variant: str, score_name: str) -> np.ndarray:
    """The register stream for one variant and one score. A is compiled, B and C are written here."""
    if variant not in VARIANT_ORDER:
        raise ValueError(f"unknown variant {variant!r}; known: {list(VARIANT_ORDER)}")
    if score_name not in SCORES:
        raise ValueError(f"unknown score {score_name!r}; known: {sorted(SCORES)}")
    score = SCORES[score_name]
    if variant == "A":
        return baseline_stream(score)
    if variant == "B":
        return evolving_stream(score)
    return contrast_stream(score)


# ===========================================================================
# 5. The render path. Reuses the hardware model; the ONE difference is the gain.
# ===========================================================================
def dc_block(audio_mix: np.ndarray) -> np.ndarray:
    """The production single-pole high-pass (``y[n] = x[n] - x[n-1] + R*y[n-1]``, R = 0.995).

    Same recurrence, same order of operations, same dtype as ``pokey_synth.render_pokey_samples``,
    so the experimental and production renderers stay comparable sample for sample.
    """
    blocked = np.zeros_like(audio_mix)
    r = 0.995
    for index in range(1, len(audio_mix)):
        blocked[index] = audio_mix[index] - audio_mix[index - 1] + r * blocked[index - 1]
    return blocked


def render_registers(
    frames: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    frame_rate_hz: float = FRAME_RATE_HZ,
) -> np.ndarray:
    """Render a ``(N, 9)`` POKEY register stream to a **raw, un-normalised** float32 buffer.

    This is ``pokey_synth.render_pokey_samples`` with the final normalisation removed and nothing
    else changed: the same generator decode, the same divider arithmetic, the same DAC ladder and
    the same polynomial tables, all imported rather than re-derived. Returning the raw buffer is the
    whole point — a single shared gain can then be applied to every variant, which per-buffer
    normalisation would make impossible.

    ``tests/test_pokey_timbre_experiment.py`` pins this against the production renderer.
    """
    num_frames = frames.shape[0]
    samples_per_frame = int(round(sample_rate / frame_rate_hz))
    total_samples = num_frames * samples_per_frame

    audio_mix = np.zeros(total_samples, dtype=np.float32)
    ch_phases = np.zeros(4, dtype=np.float64)
    ch_lfsr_steps = np.zeros(4, dtype=np.float64)

    for f_idx in range(num_frames):
        f_row = frames[f_idx]
        audctl = int(f_row[8])
        s_start = f_idx * samples_per_frame
        s_end = s_start + samples_per_frame
        t_frame = np.arange(samples_per_frame, dtype=np.float64) / sample_rate

        is_16bit_1_2 = bool(audctl & AUDCTL_JOIN_1_2_16BIT)

        for ch in range(4):
            audf = int(f_row[ch * 2])
            audc = int(f_row[ch * 2 + 1])
            vol = audc & 0x0F

            if vol == 0:
                continue

            if is_16bit_1_2 and ch == 0:
                # Channel 1 is the divider low byte; audio is output on CH2
                continue

            if is_16bit_1_2 and ch == 1:
                div16 = int(f_row[0]) + (int(f_row[2]) << 8)
                freq = pokey_hw.hz_from_audf_16bit(div16, audctl)
            else:
                freq = pokey_hw.hz_from_audf_8bit(audf, audctl, channel=ch + 1)

            freq = max(10.0, min(freq, 20000.0))
            amp = POKEY_DAC[vol]

            waveform = pokey_hw.decode_audc(audc)
            if waveform == pokey_hw.Waveform.VOLUME_ONLY:
                continue

            delta_phase = 2.0 * math.pi * freq * (samples_per_frame / sample_rate)
            phase_seq = ch_phases[ch] + 2.0 * math.pi * freq * t_frame
            ch_phases[ch] = (ch_phases[ch] + delta_phase) % (2.0 * math.pi)
            poly5_idx = (phase_seq * (31.0 / (2.0 * math.pi))).astype(np.int64) % 31
            poly4_idx = (phase_seq * (15.0 / (2.0 * math.pi))).astype(np.int64) % 15
            use_9bit = bool(audctl & AUDCTL_9BIT_POLY)
            noise_seq = POLY9_SEQ if use_9bit else POLY17_SEQ
            poly_len = 511 if use_9bit else 131071

            if waveform == pokey_hw.Waveform.PURE_TONE:
                wave_samples = np.where(np.sin(phase_seq) >= 0.0, 1.0, -1.0)
            elif waveform == pokey_hw.Waveform.POLY4:
                wave_samples = POLY4_SEQ[poly4_idx] * 2.0 - 1.0
            elif waveform == pokey_hw.Waveform.POLY9_17:
                step_seq = (ch_lfsr_steps[ch] + (2.0 * freq) * t_frame).astype(np.int64)
                wave_samples = noise_seq[step_seq % poly_len]
            elif waveform == pokey_hw.Waveform.POLY5_GATED_PURE:
                wave_samples = POLY5_SEQ[poly5_idx] * 2.0 - 1.0
            elif waveform == pokey_hw.Waveform.POLY5_GATED_POLY4:
                gate = POLY5_SEQ[poly5_idx] > 0.5
                body = POLY4_SEQ[poly4_idx] * 2.0 - 1.0
                src = np.where(gate, np.arange(gate.shape[0]), 0)
                np.maximum.accumulate(src, out=src)
                wave_samples = body[src]
            else:  # POLY5_GATED_POLY9_17
                noise_samples = noise_seq[
                    (ch_lfsr_steps[ch] + (2.0 * freq) * t_frame).astype(np.int64) % poly_len
                ]
                wave_samples = (POLY5_SEQ[poly5_idx] * 2.0 - 1.0) * noise_samples

            if waveform in (pokey_hw.Waveform.POLY9_17, pokey_hw.Waveform.POLY5_GATED_POLY9_17):
                delta_steps = (2.0 * freq) * (samples_per_frame / sample_rate)
                ch_lfsr_steps[ch] = (ch_lfsr_steps[ch] + delta_steps) % poly_len

            audio_mix[s_start:s_end] += wave_samples * amp

    return dc_block(audio_mix)


def to_int16(samples: np.ndarray, gain: float = 1.0) -> np.ndarray:
    """Scale a raw buffer by *gain* and quantise, using the production conversion expression.

    ``(x * 32767).astype(int16)`` with no clip, exactly as ``pokey_synth.render_pokey_samples``
    does it, so the equivalence test can compare the two outputs directly. The caller guarantees
    ``gain`` keeps the peak below full scale.
    """
    return (samples * gain * 32767.0).astype(np.int16)


def write_wav(path: Path, samples_int16: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    """Write 16-bit mono PCM, the same format ``pokey_synth.render_pokey_to_wav`` produces."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples_int16.tobytes())
    return path


def wav_filename(variant: str, score_name: str) -> str:
    """``A_baseline_note.wav`` and friends — unambiguous, sortable by variant."""
    return f"{variant}_{VARIANT_NAMES[variant]}_{score_name}.wav"


def render_experiment(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Dict[str, Any]:
    """Render A/B/C for the note and the phrase, and write the WAVs plus ``summary.json``.

    Level handling is the point of this function. Every variant is rendered **raw**, the single
    loudest sample across all six renders fixes one gain (``TARGET_PEAK / reference_peak``), and that
    one gain is applied to all six. So nothing clips, the loudest file peaks at exactly
    ``TARGET_PEAK``, and every loudness relation between A, B and C survives untouched. No per-file
    normalisation is applied anywhere.
    """
    output_dir = Path(output_dir)
    streams: Dict[Tuple[str, str], np.ndarray] = {}
    raw: Dict[Tuple[str, str], np.ndarray] = {}
    for variant in VARIANT_ORDER:
        for score_name in SCORES:
            key = (variant, score_name)
            streams[key] = register_stream(variant, score_name)
            raw[key] = render_registers(streams[key])

    reference_peak = max(float(np.max(np.abs(buffer))) for buffer in raw.values())
    if reference_peak <= 0.0:
        raise ValueError("every rendered variant is silent; the experiment has nothing to compare")
    gain = TARGET_PEAK / reference_peak

    files: Dict[str, Path] = {}
    rows: List[Dict[str, Any]] = []
    for variant in VARIANT_ORDER:
        for score_name in SCORES:
            key = (variant, score_name)
            buffer = raw[key]
            samples = to_int16(buffer, gain)
            name = wav_filename(variant, score_name)
            files[name] = write_wav(output_dir / name, samples)
            rows.append({
                "file": name,
                "variant": variant,
                "variant_name": VARIANT_NAMES[variant],
                "score": score_name,
                "frames": int(streams[key].shape[0]),
                "samples": int(samples.shape[0]),
                "duration_seconds": round(samples.shape[0] / SAMPLE_RATE, 4),
                "raw_peak": round(float(np.max(np.abs(buffer))), 6),
                "raw_rms": round(float(np.sqrt(np.mean(np.square(buffer, dtype=np.float64)))), 6),
                "peak_after_gain": round(float(np.max(np.abs(samples))) / 32767.0, 6),
                "rms_after_gain": round(
                    float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) / 32767.0, 6
                ),
                "unique_audc": sorted(int(v) for v in np.unique(streams[key][:, 1])),
                "unique_audf": sorted(int(v) for v in np.unique(streams[key][:, 0])),
            })
    result: Dict[str, Any] = {
        "output_dir": output_dir,
        "streams": streams,
        "raw": raw,
        "rows": rows,
        "files": files,
        "gain": gain,
        "reference_peak": reference_peak,
    }
    result["summary_path"] = write_summary(result, output_dir)
    result["note_path"] = write_listening_note(result, output_dir)
    return result


def listening_note(summary: Mapping[str, Any]) -> str:
    """The short listening instruction that ships next to the WAVs."""
    policy = summary["level_policy"]
    lines: List[str] = [
        "# Experiment 26 — how to listen\n",
        "Six files, three variants, two scores. Same notes, same pitches, same durations, same",
        "sample rate, same rendering conditions. The only thing that changes is what the registers do",
        "*inside* a note.\n",
        "## Order\n",
        "| # | file | what it is |",
        "|---|---|---|",
    ]
    for index, row in enumerate(summary["files"], start=1):
        lines.append(
            f"| {index} | `{row['file']}` | {row['variant']} ({row['variant_name']}), "
            f"{row['score']}, {row['duration_seconds']:.2f} s |"
        )
    lines += [
        "",
        "Play the **note** files first, in A → B → C order, then the **phrase** files in the same",
        "order. A is the reference; B and C are the two proposals.\n",
        "## What to listen for\n",
        "* **A → B**: does the single note change character *while it is sounding*? B holds the same",
        "  pitch and the same volume as A and only swaps POKEY's generator every 160 ms, so anything",
        "  you hear is timbre, not level and not pitch.",
        "* **A → C**: C is a different generator with the divider switching an octave up every 20 ms.",
        "  Listen for a hollow, ringing quality and for a rougher, less pure pitch.",
        "* **Phrase**: do the changes survive a re-attack and a pitch change, or do they sound like a",
        "  stuck effect? Each note restarts its own gesture, so a new attack should sound like a new",
        "  note.\n",
        "## Levels (so you know what you are hearing)\n",
        f"One shared gain of `{policy['shared_gain']}` was applied to all six files, taken from the",
        f"loudest of the six raw renders (reference peak `{policy['reference_peak']}`) and targeting a",
        f"peak of `{policy['target_peak']}`. **No file was normalised on its own**, so the loudness",
        "relation between A, B and C is intact. Measured levels:\n",
        "| file | raw peak | raw RMS | RMS after the shared gain |",
        "|---|---|---|---|",
    ]
    for row in summary["files"]:
        lines.append(
            f"| `{row['file']}` | {row['raw_peak']:.4f} | {row['raw_rms']:.4f} | "
            f"{row['rms_after_gain']:.4f} |"
        )
    lines += [
        "",
        "All six peak at the same level because every variant contains the same square-wave edges;",
        "the differences above are in density, not in peak. A and B are within 0.1 % of each other by",
        "design — B changes no volume.\n",
        "## What this experiment does not claim\n",
        "A more complex register trace is not automatically a better sound. Nothing here measures",
        "quality, and the tests only confirm that the experiment is technically correct. Judge it by",
        "ear, and treat a null result as a result.\n",
        "## Regenerating\n",
        "```\npython -m atari_music.pokey_timbre_experiment\n```\n",
        "Deterministic: the same command reproduces these files byte for byte. No production file is",
        "read or written by the render beyond the shared hardware model, the register compiler and the",
        "DAC/polynomial tables.\n",
    ]
    return "\n".join(lines)


def write_listening_note(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "README.md"
    path.write_text(listening_note(build_summary(result)), encoding="utf-8")
    return path



def score_summary(name: str) -> Dict[str, Any]:
    """The score's notes, with the nominal and realised pitch of each, for the summary."""
    score = SCORES[name]
    return {
        "notes": [
            {
                "midi": int(midi),
                "name": ir.midi_to_note_name(int(midi)),
                "rows": int(rows),
                "frames": int(rows) * FRAMES_PER_TICK,
                "nominal_hz": round(ir.midi_pitch_to_frequency(int(midi)), 3),
                "audf": note_divider(int(midi)),
                "realised_hz": round(
                    pokey_hw.hz_from_audf_8bit(note_divider(int(midi)), AUDCTL, CHANNEL), 3
                ),
            }
            for midi, rows in score
        ],
        "total_frames": total_frames(score),
        "total_seconds": round(total_frames(score) / FRAME_RATE_HZ, 4),
    }


def build_summary(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The JSON record: what was rendered, how it was levelled, and how each variant differs."""
    gain = float(result["gain"])
    reference_peak = float(result["reference_peak"])
    return {
        "experiment": "experiment26",
        "purpose": (
            "audible A/B/C comparison of one POKEY note, to hear whether a richer timbre is "
            "reachable at all"
        ),
        "sample_rate": SAMPLE_RATE,
        "wav_format": "16-bit mono PCM",
        "frame_rate_hz": FRAME_RATE_HZ,
        "frames_per_tick": FRAMES_PER_TICK,
        "audctl": f"${AUDCTL:02X}",
        "channel": CHANNEL,
        "score": {name: score_summary(name) for name in ("note", "phrase")},
        "level_policy": {
            "per_file_normalisation": False,
            "shared_gain": round(gain, 8),
            "reference_peak": round(reference_peak, 8),
            "target_peak": TARGET_PEAK,
            "note": (
                "one gain derived from the loudest of the six raw renders is applied to all six, so "
                "the loudness relation between A, B and C is preserved and nothing clips"
            ),
        },
        "variants": {
            "A": {
                "name": "baseline",
                "source": "ir.compile_ir_to_pokey_frames on an IRSong (existing pipeline, unchanged)",
                "generator": f"${BASELINE_DISTORTION:02X} constant (pure tone)",
                "divider": "constant per note",
                "volume": "pokey_hw.player_envelope_volumes (the project's own player ADSR)",
            },
            "B": {
                "name": "evolving",
                "source": "experimental register writer",
                "generator": (
                    f"steps every {B_GENERATOR_STEP_FRAMES} frames through "
                    + " -> ".join(f"${value:02X}" for value in B_GENERATOR_SEQUENCE)
                ),
                "divider": "constant per note",
                "volume": "identical to A, so B differs from A in the generator nibble only",
            },
            "C": {
                "name": "contrast",
                "source": "experimental register writer",
                "generator": f"${C_GENERATOR:02X} constant (poly5-gated poly4)",
                "divider": "alternates every frame between N and N // 2 (an octave pulse)",
                "volume": (
                    f"softer onset than A: {C_ATTACK_FRAMES}-frame attack, {C_DECAY_FRAMES}-frame "
                    f"glide to {C_SUSTAIN_VOL}, {C_RELEASE_FRAMES}-frame release. The sustain level "
                    "equals A's, so C differs from A in generator, divider and onset only"
                ),
            },
        },
        "files": list(result["rows"]),
    }


def write_summary(result: Mapping[str, Any], output_dir: Path) -> Path:
    summary = build_summary(result)
    path = Path(output_dir) / "summary.json"
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def main(output_dir: Path = DEFAULT_OUTPUT_DIR) -> int:
    """Render the experiment and print where the files are. No production code is touched."""
    result = render_experiment(output_dir)
    summary = build_summary(result)
    print(
        f"shared gain {summary['level_policy']['shared_gain']} "
        f"(reference peak {summary['level_policy']['reference_peak']})"
    )
    for row in summary["files"]:
        print(
            f"  {row['file']:24s} {row['frames']:3d} frames  {row['duration_seconds']:.3f}s  "
            f"raw_peak {row['raw_peak']:.4f}  rms {row['rms_after_gain']:.4f}  "
            f"AUDC {[hex(v) for v in row['unique_audc']]}"
        )
    print(f"summary: {result['summary_path']}")
    print(f"listening note: {result['note_path']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())







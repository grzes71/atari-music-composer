"""Experiment 27 — musical characterisation of the POKEY octave-pulse timbre.

STARTING POINT
--------------
Variant **C** of Experiment 26 was judged interesting on listening, so this experiment develops it
and nothing else. C1 below *is* Experiment 26's variant C: ``c1_stream`` calls
``pokey_timbre_experiment.contrast_stream`` directly rather than re-implementing it, so the baseline
cannot drift away from the artefact that was actually listened to. Everything else — the generator
(``$40``), the volume shape (``plucked_volume_shape``), the score grid, the channel, AUDCTL, the
renderer and the level policy — is taken from that module too.

THE ONE PARAMETER UNDER STUDY
-----------------------------
Experiment 26's C pulses the divider on a fixed grid: alternate every frame between ``N`` and
``N // 2``, for the whole note, on every note. This experiment varies **only the pulse schedule**
and holds everything else fixed, so each comparison isolates one thing:

===========  ==================  ===================  ==========================
variant      ``hold_frames``     ``active_frames``    ``active_notes``
===========  ==================  ===================  ==========================
C1           1                   the whole note       every note
C2           **4**               the whole note       every note
C3           1                   **8**                every note
C4           1                   the whole note       **notes 0 and 2**
===========  ==================  ===================  ==========================

So C2 changes the pulse *rate* and nothing else, C3 changes the pulse *duration* and nothing else,
and C4 changes *which notes* carry it and nothing else. A note with the pulse switched off keeps the
same generator and the same volume shape and simply holds a constant divider — that is what
"the normal sound between them" means here, and it is the only reading that does not change a second
parameter.

REAL LIMITATIONS OF THE MECHANISM (recorded, not worked around)
--------------------------------------------------------------
* **20 ms granularity.** The player writes registers once per PAL frame, so the divider can change at
  most every 20 ms. The fastest alternation is therefore one frame per value (25 Hz); possible
  alternation rates are 50 / (2 * hold) Hz — 25, 12.5, 8.3, 6.25 Hz ... A faster pulse cannot be
  expressed and is not simulated.
* **``N // 2 == 0`` at the bottom of the range.** For a nominal divider of 0 or 1 the octave-up value
  is 0, which is POKEY's fastest divider, not a musical octave. This experiment's lowest note is
  A-3 (AUDF 143), so it never reaches that region — the limit is stated rather than exercised.
* **AUDDF clamps at ``$FE``.** ``pokey_hw.clamp_audf_for_tracker`` caps the divider so the tracker
  format stays encodable. A nominal divider that is already clamped has no exact octave above it, so
  the octave relation is only faithful while ``N <= 254`` (about 124 Hz and above at 64 kHz).
* **``$40`` is a gated generator, not a pure oscillator.** ``$40`` is poly5-gated poly4, and the poly5
  gate runs at the divider rate too. Doubling the divider therefore doubles the *gate* rate as well as
  the tone, so this is a change of texture and of pitch together, not a clean octave doubling.
* **AUDCTL is fixed for the whole stream.** The clock cannot change mid-song, so the mechanism cannot
  switch between 64 kHz and 1.79 MHz inside a note.

NOT DONE, ON PURPOSE
--------------------
No production DSL/IR/compiler/MADS-exporter/player change, no general instrument system, no modulation
layer, no further archaeology, no automatic winner. Which variant is musically useful is a listening
question, and the tests here only establish that the experiment is technically correct.
"""

from __future__ import annotations

import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import pokey_hw, pokey_timbre_experiment as e26

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "experiment27"

#: Everything physical is Experiment 26's, so the two experiments are directly comparable.
SAMPLE_RATE = e26.SAMPLE_RATE
FRAME_RATE_HZ = e26.FRAME_RATE_HZ
FRAMES_PER_TICK = e26.FRAMES_PER_TICK
AUDCTL = e26.AUDCTL
CHANNEL = e26.CHANNEL
TARGET_PEAK = e26.TARGET_PEAK


# ===========================================================================
# 1. The score. Experiment 26's note and phrase, plus a low phrase.
# ===========================================================================
#: Identical to Experiment 26, so C1's files are directly comparable with its C files.
ISOLATED_NOTE: Tuple[Tuple[int, int], ...] = e26.ISOLATED_NOTE
SHORT_PHRASE: Tuple[Tuple[int, int], ...] = e26.SHORT_PHRASE
#: The same phrase transposed down an octave (A-3, C-4, E-4, C-4). Its octave-up dividers land on
#: the high phrase's fundamentals, so the effect can be judged in a lower register.
LOW_PHRASE: Tuple[Tuple[int, int], ...] = ((57, 5), (60, 5), (64, 5), (60, 5))

SCORES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "note": ISOLATED_NOTE,
    "phrase": SHORT_PHRASE,
    "phrase_low": LOW_PHRASE,
}


# ===========================================================================
# 2. The pulse schedule — the single parameter this experiment varies.
# ===========================================================================
@dataclass(frozen=True)
class PulseSchedule:
    """When the divider is switched between ``N`` and ``N // 2`` inside a note.

    ``hold_frames`` is how many consecutive frames each divider value is held, so the alternation
    rate is ``FRAME_RATE_HZ / (2 * hold_frames)``. ``active_frames`` is how many frames from the note
    onset the pulse runs (``None`` means the whole note); after it the divider is constant. Empty
    ``active_notes`` means every note.
    """

    hold_frames: int
    active_frames: Optional[int] = None
    active_notes: Tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.hold_frames < 1:
            raise ValueError("hold_frames must be at least 1 frame")
        if self.active_frames is not None and self.active_frames < 0:
            raise ValueError("active_frames must not be negative")

    @property
    def alternation_hz(self) -> float:
        """How many times per second the divider flips, at the project's 50 Hz frame rate."""
        return FRAME_RATE_HZ / (2.0 * self.hold_frames)

    def applies_to_note(self, note_index: int) -> bool:
        return not self.active_notes or note_index in self.active_notes

    def divider_for_frame(self, nominal: int, upper: int, offset: int, note_index: int) -> int:
        """The AUDF byte for a frame offset inside note *note_index*."""
        if not self.applies_to_note(note_index):
            return nominal
        if self.active_frames is not None and offset >= self.active_frames:
            return nominal
        return nominal if (offset // self.hold_frames) % 2 == 0 else upper


#: C1 is Experiment 26's C, restated as a schedule so the four variants share one code path.
SCHEDULES: Dict[str, PulseSchedule] = {
    "C1": PulseSchedule(hold_frames=1),
    "C2": PulseSchedule(hold_frames=4),
    "C3": PulseSchedule(hold_frames=1, active_frames=8),
    "C4": PulseSchedule(hold_frames=1, active_notes=(0, 2)),
}

VARIANT_ORDER: Tuple[str, ...] = ("C1", "C2", "C3", "C4")
VARIANT_NAMES: Dict[str, str] = {
    "C1": "pulse1",
    "C2": "pulse4",
    "C3": "onset",
    "C4": "selected",
}
VARIANT_DESCRIPTIONS: Dict[str, str] = {
    "C1": "Experiment 26's C: the divider flips every frame (25 Hz) for the whole note, on every note",
    "C2": "each divider is held 4 frames (80 ms, 6.25 Hz) for the whole note, on every note",
    "C3": "the pulse runs for the first 8 frames only, then the divider is constant",
    "C4": "the pulse is on for notes 0 and 2 and off for the rest, which hold a constant divider",
}

#: The real limits of the mechanism. Recorded rather than worked around: the experiment does not
#: pretend to a capability the 50 Hz player and the 8-bit AUDF register do not have.
LIMITATIONS: Tuple[str, ...] = (
    "the player writes registers once per 50 Hz frame, so the divider cannot change more often than "
    "every 20 ms and the fastest alternation is 25 Hz",
    "possible alternation rates are 50 / (2 * hold_frames) Hz: 25, 12.5, 8.33, 6.25 ...",
    "N // 2 == 0 for a nominal divider of 0 or 1, which is POKEY's fastest divider rather than an "
    "octave; the lowest note used here is A-3 (AUDF 143) and never reaches it",
    "AUDF clamps at $FE for the tracker format, so the octave relation is only exact while N <= 254, "
    "about 124 Hz and above at 64 kHz",
    "$40 is poly5-gated poly4, so doubling the divider doubles the poly5 gate rate as well: the "
    "result is a texture and pitch change together, not a clean octave oscillator",
    "AUDCTL is fixed for the whole stream, so the clock cannot change inside a note",
)


# ===========================================================================
# 3. The register streams.
# ===========================================================================
def _empty_stream(score: Sequence[Tuple[int, int]]) -> np.ndarray:
    """A silent ``(N, 9)`` stream with the experiment's AUDCTL already in place."""
    frames = np.zeros((e26.total_frames(score), 9), dtype=np.uint8)
    frames[:, 8] = AUDCTL
    return frames


def scheduled_stream(
    score: Sequence[Tuple[int, int]], schedule: PulseSchedule
) -> np.ndarray:
    """Write one score with one pulse schedule.

    Only two registers are ever touched: channel 1's AUDF (the divider) and channel 1's AUDC (the
    generator plus the volume). The generator and the volume come from Experiment 26's variant C
    unchanged, so a difference between two streams written here is a difference in the divider
    schedule and in nothing else.
    """
    frames = _empty_stream(score)
    audf_col = e26.ir.audf_column(CHANNEL)
    audc_col = e26.ir.audc_column(CHANNEL)
    for note_index, (start, end, midi) in enumerate(e26.note_spans(score)):
        nominal = e26.note_divider(midi)
        upper = e26.octave_divider(nominal)
        volumes = e26.plucked_volume_shape(end - start)
        for offset in range(end - start):
            frames[start + offset, audf_col] = schedule.divider_for_frame(
                nominal, upper, offset, note_index
            )
            frames[start + offset, audc_col] = (e26.C_GENERATOR & 0xE0) | volumes[offset]
    return frames


def c1_stream(score: Sequence[Tuple[int, int]]) -> np.ndarray:
    """C1 — Experiment 26's variant C, taken from the module that produced the listened artefact.

    Deliberately a direct call rather than a re-implementation: ``scheduled_stream`` with
    ``SCHEDULES["C1"]`` is proven equal to this by the test suite, which is what licenses the other
    three variants as the same mechanism with one parameter moved.
    """
    return e26.contrast_stream(score)


def variant_stream(variant: str, score_name: str) -> np.ndarray:
    """The register stream for one variant and one score."""
    if variant not in VARIANT_ORDER:
        raise ValueError(f"unknown variant {variant!r}; known: {list(VARIANT_ORDER)}")
    if score_name not in SCORES:
        raise ValueError(f"unknown score {score_name!r}; known: {sorted(SCORES)}")
    score = SCORES[score_name]
    if variant == "C1":
        return c1_stream(score)
    return scheduled_stream(score, SCHEDULES[variant])


def expected_dividers(variant: str, score_name: str) -> List[int]:
    """The AUDF byte each frame of *score_name* should carry under *variant*.

    A plain, independent statement of the schedule, so the tests check the streams against the
    declared parameters rather than against the code that produced them.
    """
    schedule = SCHEDULES[variant]
    out: List[int] = []
    for note_index, (start, end, midi) in enumerate(e26.note_spans(SCORES[score_name])):
        nominal = e26.note_divider(midi)
        upper = e26.octave_divider(nominal)
        for offset in range(end - start):
            pulsing = schedule.applies_to_note(note_index) and (
                schedule.active_frames is None or offset < schedule.active_frames
            )
            if not pulsing:
                out.append(nominal)
                continue
            held = offset // schedule.hold_frames
            out.append(nominal if held % 2 == 0 else upper)
    return out


def wav_filename(variant: str, score_name: str) -> str:
    """``C1_pulse1_note.wav`` and friends."""
    return f"{variant}_{VARIANT_NAMES[variant]}_{score_name}.wav"


# ===========================================================================
# 4. The render. Same renderer, same shared-gain policy as Experiment 26.
# ===========================================================================
def divider_switches(frames: np.ndarray) -> int:
    """How many frames change the divider relative to the previous frame.

    A description of how much the mechanism is doing, **not** a quality score.
    """
    column = frames[:, e26.ir.audf_column(CHANNEL)].astype(np.int64)
    return int(np.count_nonzero(np.diff(column)))


def render_experiment(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Dict[str, Any]:
    """Render C1–C4 across the three scores and write the WAVs, ``summary.json`` and ``README.md``.

    Level handling is Experiment 26's policy, unchanged: every variant is rendered **raw**, one gain
    is derived from the single loudest of the twelve renders, and that one gain is applied to all
    twelve. No file is normalised on its own, so the loudness relation between the variants survives.
    """
    output_dir = Path(output_dir)
    streams: Dict[Tuple[str, str], np.ndarray] = {}
    raw: Dict[Tuple[str, str], np.ndarray] = {}
    for variant in VARIANT_ORDER:
        for score_name in SCORES:
            key = (variant, score_name)
            streams[key] = variant_stream(variant, score_name)
            raw[key] = e26.render_registers(streams[key])

    reference_peak = max(float(np.max(np.abs(buffer))) for buffer in raw.values())
    if reference_peak <= 0.0:
        raise ValueError("every rendered variant is silent; there is nothing to compare")
    gain = TARGET_PEAK / reference_peak

    files: Dict[str, Path] = {}
    rows: List[Dict[str, Any]] = []
    for variant in VARIANT_ORDER:
        for score_name in SCORES:
            key = (variant, score_name)
            buffer = raw[key]
            samples = e26.to_int16(buffer, gain)
            name = wav_filename(variant, score_name)
            files[name] = e26.write_wav(output_dir / name, samples)
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
                "unique_audf": sorted(int(v) for v in np.unique(streams[key][:, 0])),
                "unique_audc": sorted(int(v) for v in np.unique(streams[key][:, 1])),
                "divider_switches": divider_switches(streams[key]),
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


def score_summary(name: str) -> Dict[str, Any]:
    """The score's notes with both divider values, so the octave pair is auditable per note."""
    score = SCORES[name]
    return {
        "notes": [
            {
                "index": index,
                "midi": int(midi),
                "name": e26.ir.midi_to_note_name(int(midi)),
                "rows": int(rows),
                "frames": int(rows) * FRAMES_PER_TICK,
                "nominal_hz": round(e26.ir.midi_pitch_to_frequency(int(midi)), 3),
                "audf": e26.note_divider(int(midi)),
                "octave_up_audf": e26.octave_divider(e26.note_divider(int(midi))),
                "realised_hz": round(
                    pokey_hw.hz_from_audf_8bit(e26.note_divider(int(midi)), AUDCTL, CHANNEL), 3
                ),
                "octave_up_hz": round(
                    pokey_hw.hz_from_audf_8bit(
                        e26.octave_divider(e26.note_divider(int(midi))), AUDCTL, CHANNEL
                    ),
                    3,
                ),
            }
            for index, (midi, rows) in enumerate(score)
        ],
        "total_frames": e26.total_frames(score),
        "total_seconds": round(e26.total_frames(score) / FRAME_RATE_HZ, 4),
    }


def build_summary(result: Mapping[str, Any]) -> Dict[str, Any]:
    """The JSON record: the shared baseline, the parameter under study, and the limitations."""
    return {
        "experiment": "experiment27",
        "purpose": (
            "characterise whether a controlled AUDF switch between N and N // 2 gives a repeatable, "
            "musically usable instrument timbre"
        ),
        "baseline": {
            "variant": "C1",
            "source": (
                "variant C of Experiment 26, taken directly from "
                "pokey_timbre_experiment.contrast_stream rather than re-implemented"
            ),
            "experiment26_files": [
                "experiments/experiment26/C_contrast_note.wav",
                "experiments/experiment26/C_contrast_phrase.wav",
            ],
        },
        "shared_with_experiment26": {
            "generator": f"${e26.C_GENERATOR:02X} (poly5-gated poly4), constant",
            "volume": (
                "pokey_timbre_experiment.plucked_volume_shape: 1-frame attack, 8-frame glide to 12, "
                "3-frame release, restarting at every note onset"
            ),
            "scores_reused": ["note", "phrase"],
            "sample_rate": SAMPLE_RATE,
            "frame_rate_hz": FRAME_RATE_HZ,
            "audctl": f"${AUDCTL:02X}",
            "channel": CHANNEL,
        },
        "parameter_under_study": (
            "the divider pulse schedule only. The generator, the volume shape, the note grid, the "
            "channel, AUDCTL and the render path are identical in all four variants"
        ),
        "scores": {name: score_summary(name) for name in SCORES},
        "variants": {
            variant: {
                "name": VARIANT_NAMES[variant],
                "description": VARIANT_DESCRIPTIONS[variant],
                "hold_frames": SCHEDULES[variant].hold_frames,
                "active_frames": SCHEDULES[variant].active_frames,
                "active_notes": list(SCHEDULES[variant].active_notes) or "every note",
                "alternation_hz": SCHEDULES[variant].alternation_hz,
            }
            for variant in VARIANT_ORDER
        },
        "limitations": list(LIMITATIONS),
        "level_policy": {
            "per_file_normalisation": False,
            "shared_gain": round(float(result["gain"]), 8),
            "reference_peak": round(float(result["reference_peak"]), 8),
            "target_peak": TARGET_PEAK,
            "note": (
                "one gain derived from the loudest of the twelve raw renders is applied to all "
                "twelve, exactly as in Experiment 26, so C1's files here are directly "
                "loudness-comparable with Experiment 26's C files"
            ),
        },
        "files": list(result["rows"]),
    }


def write_summary(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "summary.json"
    path.write_text(
        json.dumps(build_summary(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def listening_note(summary: Mapping[str, Any]) -> str:
    """The short listening instruction that ships next to the WAVs."""
    lines: List[str] = [
        "# Experiment 27 — how to listen\n",
        "Four variants of one mechanism: the AUDF divider switching between `N` and `N // 2` inside a",
        "note. Same notes, same pitches, same durations, same generator, same volume shape, same",
        "channel, same clock, same renderer, same shared gain. Only the **pulse schedule** changes.\n",
        "## The four variants\n",
        "| variant | hold per value | active for | active on | alternation |",
        "|---|---|---|---|---|",
    ]
    for variant in VARIANT_ORDER:
        row = summary["variants"][variant]
        active_frames = row["active_frames"]
        active_notes = row["active_notes"]
        notes_text = (
            active_notes if isinstance(active_notes, str)
            else ", ".join(str(value) for value in active_notes)
        )
        lines.append(
            f"| **{variant}** {row['name']} | {row['hold_frames']} frame(s) | "
            f"{'whole note' if active_frames is None else str(active_frames) + ' frames'} | "
            f"{notes_text} | {row['alternation_hz']:.2f} Hz |"
        )
    lines += [
        "",
        "C1 is Experiment 26's variant C, unchanged. C2 changes the rate only. C3 changes the duration",
        "only. C4 changes which notes carry the effect only — the other notes keep the same generator",
        "and volume and simply hold a constant divider, so the plain sound sits between the treated",
        "ones inside the same file.\n",
        "## Files\n",
        "| # | file | variant | score | length |",
        "|---|---|---|---|---|",
    ]
    for index, row in enumerate(summary["files"], start=1):
        lines.append(
            f"| {index} | `{row['file']}` | {row['variant']} ({row['variant_name']}) | "
            f"{row['score']} | {row['duration_seconds']:.2f} s |"
        )
    lines += [
        "",
        "## Order\n",
        "Start with `C1_pulse1_note.wav` and `C1_pulse1_phrase.wav` to re-anchor on the sound that was",
        "found interesting. Then play the other three variants against it, one at a time:\n",
        "* **C1 → C2** — the pulse slows from 25 Hz to 6.25 Hz. Does it stop reading as a rough texture",
        "  and start reading as a musical octave trill? Is the slower version more usable?",
        "* **C1 → C3** — the pulse lasts 8 frames (160 ms) and then the divider is constant. Does that",
        "  read as an attack transient, and does the note settle into something usable?",
        "* **C1 → C4** — inside `C4_selected_phrase.wav`, notes 1 and 3 are plain. Does alternating the",
        "  effect on and off sound deliberate, or like a fault?",
        "* **`phrase` vs `phrase_low`** — the same effect an octave lower. The low phrase's octave-up",
        "  dividers land exactly on the high phrase's fundamentals, so if the effect only works in one",
        "  register, that is where it will show.\n",
        "## Levels\n",
        f"One shared gain of `{summary['level_policy']['shared_gain']}` was applied to all twelve files,",
        "taken from the loudest of the twelve raw renders (reference peak",
        f"`{summary['level_policy']['reference_peak']}`) and targeting a peak of",
        f"`{summary['level_policy']['target_peak']}`. **No file was normalised on its own.** Because the",
        "generator and the volume are shared with Experiment 26 and the reference peak is the same 2.0,",
        "this is the same gain Experiment 26 used — so C1 here is directly loudness-comparable with",
        "`experiments/experiment26/C_contrast_note.wav`.\n",
        "| file | raw RMS | RMS after the shared gain | divider switches |",
        "|---|---|---|---|",
    ]
    for row in summary["files"]:
        lines.append(
            f"| `{row['file']}` | {row['raw_rms']:.4f} | {row['rms_after_gain']:.4f} | "
            f"{row['divider_switches']} |"
        )
    lines += [
        "",
        "The `divider switches` column counts frames where AUDF differs from the previous frame. It",
        "says how much the mechanism is doing; it does **not** say how good it sounds.\n",
        "## Known limitations of the mechanism\n",
    ]
    for item in summary["limitations"]:
        lines.append(f"* {item}")
    lines += [
        "",
        "## What this experiment does not do\n",
        "It does not pick a winner, and it does not measure quality. More register changes, a bigger",
        "RMS or a different hash are not evidence of a better sound. Nothing is integrated into the",
        "production DSL or IR, and no production file is changed.\n",
        "## Regenerating\n",
        "```\npython -m atari_music.pokey_octave_pulse_experiment\n```\n",
        "Deterministic: the same command reproduces all fourteen files byte for byte.\n",
    ]
    return "\n".join(lines)


def write_listening_note(result: Mapping[str, Any], output_dir: Path) -> Path:
    path = Path(output_dir) / "README.md"
    path.write_text(listening_note(build_summary(result)), encoding="utf-8")
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
            f"  {row['file']:26s} {row['frames']:3d} frames  {row['duration_seconds']:.3f}s  "
            f"switches {row['divider_switches']:3d}  AUDf {row['unique_audf']}"
        )
    print(f"summary: {result['summary_path']}")
    print(f"listening note: {result['note_path']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())






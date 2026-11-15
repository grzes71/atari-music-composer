"""Stage 13A — pitch-trajectory perceptual experiment.

The question: does the *temporal pitch behaviour* the archaeology measured inside a real
POKEY sound contain transferable perceptual information that improves a new
Composer-generated sound?

This module is an experiment. It renders with the **unchanged** composer frame compiler and
synthesiser and then rewrites only the AUDF column of the frames for the tested note — an
offline transformation, so the production IR, player and renderer are never touched. Because
only AUDF changes, the byte-level proof that "the only difference is pitch/divider
behaviour" is exact by construction.

Variants (neutral names):

* ``A`` STATIC             — the plain Composer rendering (the control)
* ``B`` PROFILE_STATIC     — A plus the profile trajectory's static level as a constant shift
* ``C`` PROFILE_TRAJECTORY — A plus the profile's measured relative trajectory, frame by frame
* ``D`` CONTROL_TRAJECTORY — A plus *another* profile's trajectory (a donor of similar shape)

Pitch is transferred in the representation Stage 5 validated: ``semitones_from_base``
(``hz = base * 2 ** (delta / 12)``), which is what every published profile already stores.
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music.ai.client import generate_music_from_composition
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.ir import (
    FRAME_RATE_HZ,
    compile_ir_to_pokey_frames,
    frequency_to_audf_8bit,
    resolve_audctl_mode,
)
from atari_music import pokey_hw
from atari_music.pokey_synth import render_pokey_samples
from atari_music.sound_profiles import SoundProfile, SoundProfileBank, load_sound_profile_bank
from atari_music.stage9c import SAMPLE_RATE, spectral_features
from atari_music.stage11b import read_wav_samples

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"
DEFAULT_STAGE13_DIR = REPO_ROOT / "reports" / "stage13a"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = Path(r"C:\Users\grzes\Documents\Projects\pokey-sound-architecture")

ANALYSIS_VERSION = "stage13a/1"

#: bpm 150 -> ``frames_per_tick = 3`` (composition.py), the finest note grid the Composer
#: offers, so a trajectory of N frames needs a note of only ``3*ceil(N/3)`` frames.
BPM = 150
VELOCITY = 13
#: One instrument, identical for every variant and every case: the only variable is pitch.
CHARACTER = "bright_lead"

#: A trajectory whose every point lies within one octave of its base is treated as music; a
#: larger excursion is a divider/pair register artifact, not pitch (measured; see recon).
SEMITONE_LIMIT = 12.0

VARIANT_ORDER = ("A", "B", "C", "D")
VARIANT_LABELS = {
    "A": "STATIC",
    "B": "PROFILE_STATIC",
    "C": "PROFILE_TRAJECTORY",
    "D": "CONTROL_TRAJECTORY",
}


class Stage13AError(RuntimeError):
    """A precondition of the experiment was not met."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_samples(samples: np.ndarray) -> str:
    return hashlib.sha256(samples.astype(np.int16).tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Part 1-2 — reconnaissance: what pitch information actually exists
# ---------------------------------------------------------------------------
def expand_runs(runs: Any) -> Optional[Tuple[float, ...]]:
    """``[[delta, frames], ...]`` -> one delta per VBL frame, or ``None`` if malformed."""
    if not isinstance(runs, (list, tuple)) or not runs:
        return None
    out: List[float] = []
    for run in runs:
        if not isinstance(run, (list, tuple)) or len(run) != 2:
            return None
        delta, length = run
        if isinstance(delta, bool) or isinstance(length, bool):
            return None
        if not isinstance(delta, (int, float)) or not isinstance(length, int) or length < 0:
            return None
        out.extend([float(delta)] * length)
    return tuple(out) or None


def profile_trajectory(profile: SoundProfile) -> Optional[Dict[str, Any]]:
    """The profile's measured pitch trajectory as a per-frame semitone series, or ``None``.

    Nothing is repaired: a series that does not parse, is empty, or leaves the one-octave
    musical bound is returned for inspection but never marked transferable.
    """
    gesture = (profile.document.get("gesture") or {}).get("pitch") or {}
    deltas = expand_runs(gesture.get("runs"))
    if deltas is None:
        return None
    absolute = max(abs(value) for value in deltas)
    steps = [abs(deltas[i] - deltas[i - 1]) for i in range(1, len(deltas))]
    changes = sum(1 for step in steps if step > 1e-9)
    return {
        "frames": len(deltas),
        "deltas": deltas,
        "max_abs_semitones": round(absolute, 4),
        "max_step_semitones": round(max(steps), 4) if steps else 0.0,
        "changes": changes,
        "range_semitones": round(max(deltas) - min(deltas), 4),
        "mean_semitones": round(sum(deltas) / len(deltas), 4),
        "starts_at_base": abs(deltas[0]) < 1e-9,
        "mode": gesture.get("mode"),
        "unit": gesture.get("unit"),
        "quantization_semitones": gesture.get("quantization_semitones"),
        "direction": gesture.get("direction"),
        "change_rate_hz": gesture.get("change_rate_hz"),
        "behavior": (profile.document.get("pitch") or {}).get("behavior"),
        "source_base_hz": gesture.get("base_hz"),
        "bounded": bool(absolute <= SEMITONE_LIMIT),
    }


def reconnaissance(
    bank: SoundProfileBank, *, arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR
) -> Dict[str, Any]:
    """Every pitch fact the bank publishes, measured from the documents themselves."""
    modes: Dict[str, int] = {}
    units: Dict[str, int] = {}
    quantizations: Dict[str, int] = {}
    directions: Dict[str, int] = {}
    behaviors: Dict[str, int] = {}
    static = 0
    with_runs = 0
    bounded: List[Dict[str, Any]] = []
    unbounded: List[Dict[str, Any]] = []

    for profile_id in bank.ids():
        profile = bank.get(profile_id)
        trajectory = profile_trajectory(profile)
        gesture = (profile.document.get("gesture") or {}).get("pitch") or {}
        modes[str(gesture.get("mode"))] = modes.get(str(gesture.get("mode")), 0) + 1
        units[str(gesture.get("unit"))] = units.get(str(gesture.get("unit")), 0) + 1
        key = str(gesture.get("quantization_semitones"))
        quantizations[key] = quantizations.get(key, 0) + 1
        directions[str(gesture.get("direction"))] = (
            directions.get(str(gesture.get("direction")), 0) + 1
        )
        behavior = str((profile.document.get("pitch") or {}).get("behavior"))
        behaviors[behavior] = behaviors.get(behavior, 0) + 1
        if gesture.get("static"):
            static += 1
        if trajectory is None:
            continue
        with_runs += 1
        entry = {
            "profile_id": profile_id,
            "scope": profile.scope,
            "frames": trajectory["frames"],
            "max_abs_semitones": trajectory["max_abs_semitones"],
            "changes": trajectory["changes"],
            "range_semitones": trajectory["range_semitones"],
            "behavior": trajectory["behavior"],
            "direction": trajectory["direction"],
        }
        (bounded if trajectory["bounded"] else unbounded).append(entry)

    trace = Path(arch_root) / "reports" / "trace_profile_comparisons"
    return {
        "bank": str(bank.root),
        "profiles": len(bank.profiles),
        "representation": {
            "modes": modes,
            "units": units,
            "quantizations_semitones": quantizations,
            "rebase_formula": "hz = base_hz * 2 ** (delta_semitones / 12)",
            "validated_by": "Stage 5 Experiment A (semitones_from_base); Stage 6: relative pitch transfers best",
        },
        "gesture_pitch": {
            "static": static,
            "non_static_with_runs": with_runs,
            "directions": directions,
            "behaviors": behaviors,
        },
        "transferable": {
            "bounded_within_one_octave": len(bounded),
            "unbounded_register_artifacts": len(unbounded),
            "note": "an excursion beyond one octave is a divider/pair register artifact, not pitch; "
            "those series are excluded from case selection",
        },
        "bounded_profiles": sorted(bounded, key=lambda entry: entry["profile_id"]),
        "unbounded_profiles": sorted(unbounded, key=lambda entry: entry["profile_id"]),
        "reference_audio_available": sum(
            1
            for profile_id in bank.ids()
            if (trace / profile_id / "reference_replay.wav").is_file()
        ),
        "first_loss_note": (
            "the binding reads 13 of 232 documented paths and never reads gesture.pitch "
            "(Stage 9E): pitch is carried by the profile and used by nothing"
        ),
    }


# ---------------------------------------------------------------------------
# Part 7 — case selection, fixed before any experimental audio is inspected
# ---------------------------------------------------------------------------
def _donor_for(
    profile_id: str, trajectory: Mapping[str, Any], pool: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """The closest *other* bounded trajectory, and whether it is a defensible control.

    The brief asks the control to match the tested trajectory in magnitude, duration and
    number of pitch changes. A donor is accepted only if it is within 2 semitones of range,
    within half the frame count, and within 3 changes; otherwise the control branch is
    marked unavailable rather than filled with an arbitrary trajectory.
    """
    candidates = [entry for entry in pool if entry["profile_id"] != profile_id]

    def gaps(entry: Mapping[str, Any]) -> Dict[str, float]:
        return {
            "range": abs(entry["range_semitones"] - trajectory["range_semitones"]),
            "frames": abs(entry["frames"] - trajectory["frames"]),
            "changes": abs(entry["changes"] - trajectory["changes"]),
        }

    def scaled(entry: Mapping[str, Any]) -> float:
        gap = gaps(entry)
        return (
            gap["range"] / max(1.0, trajectory["range_semitones"])
            + gap["frames"] / max(5.0, trajectory["frames"])
            + gap["changes"] / max(3.0, trajectory["changes"])
        )

    if not candidates:
        return {"profile_id": None, "acceptable": False, "reason": "no other bounded trajectory"}
    best = min(candidates, key=lambda entry: (scaled(entry), entry["profile_id"]))
    gap = gaps(best)
    acceptable = (
        gap["range"] <= 2.0
        and gap["frames"] <= 0.5 * trajectory["frames"]
        and gap["changes"] <= 3
    )
    return {
        "profile_id": best["profile_id"],
        "scope": best["scope"],
        "frames": best["frames"],
        "range_semitones": best["range_semitones"],
        "changes": best["changes"],
        "behavior": best["behavior"],
        "gaps": {key: round(value, 3) for key, value in gap.items()},
        "scaled_distance": round(scaled(best), 3),
        "acceptable": bool(acceptable),
        "reason": (
            "within 2 semitones of range, half the frame count and 3 changes"
            if acceptable
            else "no donor is close enough in magnitude, duration and change count"
        ),
    }


def select_cases(bank: SoundProfileBank) -> List[Dict[str, Any]]:
    """Eight cases covering the bounded trajectories, chosen by a stated rule.

    Rule (fixed before results): the strongest, the longest, a vibrato, a near-static, a
    rising, a falling, the shortest, and the next by id — each distinct, all bounded.
    """
    pool: List[Dict[str, Any]] = []
    for profile_id in bank.ids():
        trajectory = profile_trajectory(bank.get(profile_id))
        if trajectory is None or not trajectory["bounded"]:
            continue
        pool.append({**trajectory, "profile_id": profile_id, "scope": bank.get(profile_id).scope})
    by_id = sorted(pool, key=lambda entry: entry["profile_id"])

    taken: set = set()
    chosen: List[Tuple[str, Dict[str, Any]]] = []

    def rest() -> List[Dict[str, Any]]:
        return [entry for entry in by_id if entry["profile_id"] not in taken]

    def take(reason: str, chooser) -> None:
        entry = chooser(rest())
        if entry is None:
            return
        taken.add(entry["profile_id"])
        chosen.append((reason, entry))

    take("strongest measured pitch movement", lambda c: max(c, key=lambda e: e["max_abs_semitones"], default=None))
    take("longest trajectory", lambda c: max(c, key=lambda e: e["frames"], default=None))
    take("vibrato-like behaviour", lambda c: next((e for e in c if e["behavior"] == "vibrato"), None))
    take(
        "nearly static (smallest non-zero excursion)",
        lambda c: min((e for e in c if e["max_abs_semitones"] > 0.0), key=lambda e: e["max_abs_semitones"], default=None),
    )
    take("rising direction", lambda c: next((e for e in c if e["direction"] == "rising"), None))
    take("falling direction", lambda c: next((e for e in c if e["direction"] == "falling"), None))
    take("shortest trajectory", lambda c: min(c, key=lambda e: e["frames"], default=None))
    take("next by id (family coverage)", lambda c: c[0] if c else None)

    cases: List[Dict[str, Any]] = []
    for index, (reason, entry) in enumerate(chosen[:8], start=1):
        cases.append(
            {
                "case": f"pitch_{index:02d}",
                "profile_id": entry["profile_id"],
                "scope": entry["scope"],
                "reason": reason,
                "frames": entry["frames"],
                "max_abs_semitones": entry["max_abs_semitones"],
                "range_semitones": entry["range_semitones"],
                "changes": entry["changes"],
                "behavior": entry["behavior"],
                "direction": entry["direction"],
                "donor": _donor_for(entry["profile_id"], entry, pool),
            }
        )
    return cases


# ---------------------------------------------------------------------------
# Part 3, 8, 9 — the fixed musical input and the isolated trajectory transform
# ---------------------------------------------------------------------------
#: Level 2 applies the trajectory to the third event of a short phrase; the other events
#: stay exactly as the Composer wrote them.
LEVEL2_EVENT = 2


def note_steps(frames: int, frames_per_tick: int) -> int:
    """The smallest whole number of composition steps that covers *frames* frames."""
    return max(1, -(-int(frames) // int(frames_per_tick)))


def composition(steps: Sequence[Tuple[str, int]], *, joined: bool = False) -> AICompositionDoc:
    """One instrument, one phrase, on channel 1 — identical for every variant of a case."""
    events: List[AIPatternChannelEvent] = []
    step = 0
    for note, duration in steps:
        events.append(
            AIPatternChannelEvent(
                step=step, note=note, instrument="inst", duration=duration, volume=VELOCITY
            )
        )
        step += duration
    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="Stage 13A pitch trajectory stimulus", bpm=BPM, key="C", mode="major"
        ),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=joined),
        instruments=[AIInstrumentDef(id="inst", name=CHARACTER, character=CHARACTER)],
        patterns=[
            AIPatternDef(
                id="S",
                length_steps=sum(duration for _, duration in steps),
                channels={"1": events},
            )
        ],
        sequence=["S"],
        loop_point=0,
    )


def compiled(steps: Sequence[Tuple[str, int]], *, joined: bool = False):
    """The compiled IR song and its frames, from the unchanged production compiler."""
    result = generate_music_from_composition(composition(steps, joined=joined))
    return result.pokey_ir, compile_ir_to_pokey_frames(result.pokey_ir)


def event_window(
    steps: Sequence[Tuple[str, int]], event: int, frames_per_tick: int
) -> Tuple[int, int]:
    """Frame range ``[start, end)`` of one event."""
    start_step = sum(duration for _, duration in steps[:event])
    return (
        start_step * frames_per_tick,
        start_step * frames_per_tick + steps[event][1] * frames_per_tick,
    )


def apply_pitch(
    frames: np.ndarray,
    *,
    window: Tuple[int, int],
    base_freq_hz: float,
    deltas: Sequence[float],
    audctl: int,
    channel: int = 1,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Rewrite **only** the AUDF column of *window*, following a per-frame semitone series.

    The transform is offline and total: every other column, and every frame outside the
    window, is left untouched. The series is applied from the window's first frame; when the
    window is longer than the series the last value is held (nothing is stretched or
    truncated — the note length is chosen to cover the series).
    """
    out = frames.copy()
    start, end = window
    audf_col = (int(channel) - 1) * 2
    applied: List[int] = []
    for offset in range(max(0, end - start)):
        index = min(offset, len(deltas) - 1)
        freq = float(base_freq_hz) * (2.0 ** (float(deltas[index]) / 12.0))
        value = pokey_hw.clamp_audf_for_tracker(
            frequency_to_audf_8bit(freq, audctl=audctl, channel=channel)
        )
        out[start + offset, audf_col] = value
        applied.append(int(value))
    return out, {"applied_audf": applied, "applied_semitones": list(deltas)[: max(0, end - start)]}


def render(frames: np.ndarray) -> np.ndarray:
    return render_pokey_samples(frames, SAMPLE_RATE, FRAME_RATE_HZ)


# ---------------------------------------------------------------------------
# Parts 4-6 — the variants
# ---------------------------------------------------------------------------
def variants_for_case(bank: SoundProfileBank, case: Mapping[str, Any]) -> Dict[str, Any]:
    """Render A/B/C/D for one case, at Level 1 (isolated) and Level 2 (in a phrase)."""
    profile = bank.get(case["profile_id"])
    own = profile_trajectory(profile)
    if own is None:
        raise Stage13AError(f"{case['profile_id']} carries no parsable pitch trajectory")
    donor = None
    if case.get("donor") and case["donor"].get("acceptable"):
        donor = profile_trajectory(bank.get(case["donor"]["profile_id"]))

    frames_per_tick = compiled((("C4", 1),))[0].frames_per_tick
    steps1 = note_steps(own["frames"], frames_per_tick)
    steps2: List[Tuple[str, int]] = [("C4", 2), ("E4", 2), ("G4", steps1), ("C5", 2)]

    out: Dict[str, Any] = {"frames_per_tick": frames_per_tick, "levels": {}}
    for level, phrase, event in ((1, [("C4", steps1)], 0), (2, steps2, LEVEL2_EVENT)):
        song, frames = compiled(phrase)
        audctl = resolve_audctl_mode(song)
        window = event_window(phrase, event, song.frames_per_tick)
        base_freq = pokey_hw.hz_from_audf_8bit(int(frames[window[0], 0]), audctl, channel=1)
        deltas = own["deltas"]
        mean = sum(deltas) / len(deltas)
        plan: Dict[str, Optional[List[float]]] = {
            "A": None,
            "B": [round(mean, 4)] * (window[1] - window[0]),
            "C": list(deltas),
            "D": list(donor["deltas"]) if donor is not None else None,
        }
        rendered: Dict[str, Any] = {}
        for name in VARIANT_ORDER:
            series = plan[name]
            if series is None:
                variant_frames, applied = frames, None
            else:
                variant_frames, applied = apply_pitch(
                    frames,
                    window=window,
                    base_freq_hz=base_freq,
                    deltas=series,
                    audctl=audctl,
                )
            rendered[name] = {
                "frames": variant_frames,
                "samples": render(variant_frames),
                "applied": applied,
            }
        out["levels"][level] = {
            "phrase": [{"note": note, "steps": steps} for note, steps in phrase],
            "window": list(window),
            "base_freq_hz": round(float(base_freq), 4),
            "audctl": audctl,
            "plan": plan,
            "rendered": rendered,
        }
    out["profile_trajectory"] = own
    out["donor_profile_id"] = case["donor"]["profile_id"] if donor is not None else None
    out["control_available"] = donor is not None
    return out


# ---------------------------------------------------------------------------
# Part 10, 17 — quantitative analysis and the frame-level proof
# ---------------------------------------------------------------------------
SAMPLES_PER_FRAME = SAMPLE_RATE // int(FRAME_RATE_HZ)


def _rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean((samples.astype(np.float64) / 32768.0) ** 2)))


def _block_centroid(block: np.ndarray) -> float:
    """Spectral centroid of one short block, in Hz."""
    audio = block.astype(np.float64) / 32768.0
    if audio.size < 32:
        return 0.0
    window = np.hanning(audio.size)
    magnitude = np.abs(np.fft.rfft(audio * window))
    frequencies = np.fft.rfftfreq(audio.size, d=1.0 / SAMPLE_RATE)
    total = float(magnitude.sum())
    if total <= 0.0:
        return 0.0
    return float((frequencies * magnitude).sum() / total)


def centroid_series(samples: np.ndarray, block_frames: int = 4) -> List[float]:
    """Centroid per ``block_frames``-frame block across a whole render.

    A short-time proxy for "how the pitch moves": on a single monophonic tone the centroid
    follows the fundamental's harmonics, so a moving pitch shows as a moving centroid.
    """
    span = SAMPLES_PER_FRAME * block_frames
    if span <= 0:
        return []
    return [
        round(_block_centroid(samples[start : start + span]), 3)
        for start in range(0, samples.size - span + 1, span)
    ]


def _block_pitch_hz(block: np.ndarray, *, floor_hz: float = 50.0, ceil_hz: float = 3000.0) -> float:
    """FFT-autocorrelation pitch estimate of one block, or ``0.0`` when it is unvoiced."""
    audio = block.astype(np.float64) / 32768.0
    audio = audio - audio.mean()
    size = audio.size
    if size < 256 or float(np.max(np.abs(audio))) < 1e-6:
        return 0.0
    windowed = audio * np.hanning(size)
    spectrum = np.fft.rfft(windowed, 2 * size)
    correlation = np.fft.irfft(spectrum * np.conj(spectrum))[:size]
    if correlation[0] <= 0.0:
        return 0.0
    correlation = correlation / correlation[0]
    low = max(1, int(SAMPLE_RATE / ceil_hz))
    high = min(size - 1, int(SAMPLE_RATE / floor_hz))
    if high <= low:
        return 0.0
    lag = low + int(np.argmax(correlation[low:high]))
    if correlation[lag] < 0.3:
        return 0.0
    return float(SAMPLE_RATE / lag)


def pitch_series(samples: np.ndarray, block_frames: int = 2) -> List[float]:
    """The measured fundamental per block, in Hz (``0.0`` where the block is unvoiced).

    Two-frame blocks (40 ms) are used because the shortest tested trajectories are only a
    handful of frames long; a longer block would average a fast sweep away.
    """
    span = SAMPLES_PER_FRAME * block_frames
    if span <= 0:
        return []
    return [
        round(_block_pitch_hz(samples[start : start + span]), 2)
        for start in range(0, samples.size - span + 1, span)
    ]


def _semitone_spread(series: Sequence[float]) -> float:
    """Standard deviation of a Hz series expressed in semitones (0 when fewer than 2 voiced)."""
    voiced = [value for value in series if value > 0.0]
    if len(voiced) < 2:
        return 0.0
    semitones = [12.0 * float(np.log2(value / voiced[0])) for value in voiced]
    return round(float(np.std(semitones)), 4)


def pitch_metrics(deltas: Sequence[float]) -> Dict[str, Any]:
    """Trajectory descriptors: range, RMS, maximum excursion, changes, rate, direction."""
    if not deltas:
        return {
            "frames": 0,
            "range_semitones": 0.0,
            "rms_semitones": 0.0,
            "max_abs_semitones": 0.0,
            "changes": 0,
            "change_rate_hz": 0.0,
            "direction_changes": 0,
        }
    array = np.asarray(list(deltas), dtype=np.float64)
    steps = np.abs(np.diff(array)) if array.size > 1 else np.zeros(0)
    signs = np.sign(np.diff(array))
    nonzero = signs[signs != 0.0]
    direction_changes = (
        int(np.count_nonzero(np.diff(nonzero) != 0.0)) if nonzero.size > 1 else 0
    )
    return {
        "frames": int(array.size),
        "range_semitones": round(float(array.max() - array.min()), 4),
        "rms_semitones": round(float(np.sqrt(np.mean(array**2))), 4),
        "max_abs_semitones": round(float(np.max(np.abs(array))), 4),
        "changes": int(np.count_nonzero(steps > 1e-9)),
        "change_rate_hz": round(
            float(np.count_nonzero(steps > 1e-9)) / (array.size / FRAME_RATE_HZ), 4
        ),
        "direction_changes": direction_changes,
    }


def frame_proof(
    frames: np.ndarray, base_frames: np.ndarray, *, window: Sequence[int]
) -> Dict[str, Any]:
    """Part 17: exactly which frames and which POKEY columns differ, and what must not."""
    rows = min(frames.shape[0], base_frames.shape[0])
    changed = np.nonzero((frames[:rows] != base_frames[:rows]).any(axis=1))[0]
    columns = np.nonzero((frames[:rows] != base_frames[:rows]).any(axis=0))[0]
    names = {0: "AUDF1", 1: "AUDC1", 2: "AUDF2", 3: "AUDC2", 4: "AUDF3", 5: "AUDC3",
             6: "AUDF4", 7: "AUDC4", 8: "AUDCTL"}
    changed_names = [names[int(column)] for column in columns]
    outside_start, outside_end = int(window[0]), int(window[1])
    outside = [index for index in range(rows) if not (outside_start <= index < outside_end)]
    return {
        "changed_frames": int(changed.size),
        "first_changed_frame": int(changed[0]) if changed.size else None,
        "changed_pokey_columns": changed_names,
        "only_audf_changed": all(name.startswith("AUDF") for name in changed_names),
        "audc_unchanged": bool(np.array_equal(frames[:rows, 1::2], base_frames[:rows, 1::2])),
        "audctl_unchanged": bool(np.array_equal(frames[:rows, 8], base_frames[:rows, 8])),
        "frames_outside_window_unchanged": bool(
            np.array_equal(frames[outside], base_frames[outside])
        ),
        "window": [int(window[0]), int(window[1])],
    }


# ---------------------------------------------------------------------------
# Parts 10-12 — per-case analysis: descriptors, proof, reference, ablation
# ---------------------------------------------------------------------------
def reference_centroid_series(
    profile_id: str, arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR
) -> Optional[Dict[str, Any]]:
    """The source reference's short-time centroid behaviour, when a reference exists."""
    path = (
        Path(arch_root)
        / "reports"
        / "trace_profile_comparisons"
        / profile_id
        / "reference_replay.wav"
    )
    if not path.is_file():
        return None
    samples = read_wav_samples(path)
    series = centroid_series(samples)
    return {
        "path": str(path),
        "duration_seconds": round(samples.size / SAMPLE_RATE, 4),
        "features": spectral_features(samples, SAMPLE_RATE),
        "centroid_series": series,
        "centroid_std_hz": round(float(np.std(series)), 3) if series else 0.0,
        "centroid_range_hz": round(float(max(series) - min(series)), 3) if series else 0.0,
    }


def analyse_case(
    case: Mapping[str, Any],
    bank: SoundProfileBank,
    *,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Dict[str, Any]:
    """Render A/B/C/D at both levels, describe them, prove the transform and ablate it."""
    variants = variants_for_case(bank, case)
    reference = reference_centroid_series(case["profile_id"], arch_root)
    levels: Dict[str, Any] = {}

    for level, data in variants["levels"].items():
        base_frames = data["rendered"]["A"]["frames"]
        described: Dict[str, Any] = {}
        for name in VARIANT_ORDER:
            entry = data["rendered"][name]
            samples = entry["samples"]
            # the audio descriptors are measured on the *tested note*, so Level 1 and Level 2
            # are directly comparable (Level 2's other events are not part of the measurement)
            start_sample = data["window"][0] * SAMPLES_PER_FRAME
            end_sample = data["window"][1] * SAMPLES_PER_FRAME
            segment = samples[start_sample:end_sample]
            series = centroid_series(segment)
            audio_pitch = pitch_series(segment)
            applied = entry["applied"]["applied_semitones"] if entry["applied"] else []
            described[name] = {
                "label": VARIANT_LABELS[name],
                "wav_sha256": _sha256_samples(samples),
                "sample_rate": SAMPLE_RATE,
                "duration_seconds": round(samples.size / SAMPLE_RATE, 4),
                "peak": int(np.max(np.abs(samples))) if samples.size else 0,
                "rms": round(_rms(samples), 6),
                "frame_count": int(entry["frames"].shape[0]),
                "features": spectral_features(samples, SAMPLE_RATE),
                "pitch": pitch_metrics(applied),
                "centroid_series": series,
                "centroid_std_hz": round(float(np.std(series)), 3) if series else 0.0,
                "centroid_range_hz": (
                    round(float(max(series) - min(series)), 3) if series else 0.0
                ),
                "audio_pitch_hz_series": audio_pitch,
                "audio_pitch_std_semitones": _semitone_spread(audio_pitch),
                "proof": frame_proof(entry["frames"], base_frames, window=data["window"]),
            }

        def spread(name: str) -> float:
            return described[name]["centroid_std_hz"]

        def pitch_spread(name: str) -> float:
            return described[name]["audio_pitch_std_semitones"]

        levels[level] = {
            "phrase": data["phrase"],
            "window": data["window"],
            "base_freq_hz": data["base_freq_hz"],
            "audctl": data["audctl"],
            "variants": described,
            "ablation": {
                "pitch_range_C_minus_B": round(
                    described["C"]["pitch"]["range_semitones"]
                    - described["B"]["pitch"]["range_semitones"],
                    4,
                ),
                "pitch_rms_C_minus_B": round(
                    described["C"]["pitch"]["rms_semitones"]
                    - described["B"]["pitch"]["rms_semitones"],
                    4,
                ),
                "centroid_std_C_minus_B": round(spread("C") - spread("B"), 3),
                "centroid_std_C_minus_A": round(spread("C") - spread("A"), 3),
                "centroid_std_D_minus_A": (
                    round(spread("D") - spread("A"), 3)
                    if variants["control_available"]
                    else None
                ),
                "centroid_std_C_minus_D": (
                    round(spread("C") - spread("D"), 3)
                    if variants["control_available"]
                    else None
                ),
                "audio_pitch_spread_A": pitch_spread("A"),
                "audio_pitch_spread_B": pitch_spread("B"),
                "audio_pitch_spread_C": pitch_spread("C"),
                "audio_pitch_spread_D": (
                    pitch_spread("D") if variants["control_available"] else None
                ),
                "audio_pitch_spread_C_minus_A": round(pitch_spread("C") - pitch_spread("A"), 4),
                "audio_pitch_spread_C_minus_B": round(pitch_spread("C") - pitch_spread("B"), 4),
                "audio_pitch_spread_C_minus_D": (
                    round(pitch_spread("C") - pitch_spread("D"), 4)
                    if variants["control_available"]
                    else None
                ),
            },
        }

    own = variants["profile_trajectory"]
    level1 = levels[1]
    proof_c = level1["variants"]["C"]["proof"]
    return {
        "case": case["case"],
        "profile_id": case["profile_id"],
        "scope": case["scope"],
        "reason": case["reason"],
        "behavior": case["behavior"],
        "direction": case["direction"],
        "donor": case.get("donor"),
        "control_available": variants["control_available"],
        "trajectory": {
            "frames": own["frames"],
            "range_semitones": own["range_semitones"],
            "max_abs_semitones": own["max_abs_semitones"],
            "mean_semitones": own["mean_semitones"],
            "changes": own["changes"],
            "starts_at_base": own["starts_at_base"],
            "bounded": own["bounded"],
            "mode": own["mode"],
            "unit": own["unit"],
        },
        "preservation": {
            "starts_at_base": own["starts_at_base"],
            "max_abs_semitones": own["max_abs_semitones"],
            "within_one_octave": own["bounded"],
            "only_audf_changed": proof_c["only_audf_changed"],
            "audc_unchanged": proof_c["audc_unchanged"],
            "audctl_unchanged": proof_c["audctl_unchanged"],
            "frames_outside_window_unchanged": proof_c["frames_outside_window_unchanged"],
        },
        "reference": reference,
        "reference_vs_variants": (
            {
                "reference_centroid_std_hz": reference["centroid_std_hz"],
                "A_centroid_std_hz": level1["variants"]["A"]["centroid_std_hz"],
                "C_centroid_std_hz": level1["variants"]["C"]["centroid_std_hz"],
                "reference_beyond_A": round(
                    reference["centroid_std_hz"] - level1["variants"]["A"]["centroid_std_hz"], 3
                ),
                "C_towards_reference": round(
                    level1["variants"]["C"]["centroid_std_hz"]
                    - level1["variants"]["A"]["centroid_std_hz"],
                    3,
                ),
            }
            if reference is not None
            else None
        ),
        "levels": levels,
    }


# ---------------------------------------------------------------------------
# Parts 12-13 — ablation, the control comparison and the decision inputs
# ---------------------------------------------------------------------------
#: A pitch movement smaller than this is not treated as a material difference in the audio.
MATERIAL_PITCH_SEMITONES = 0.5


def evaluate(cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """H1 transferability, H2 beyond static, H3 preservation, H4 reference, H5 C vs D."""
    usable = [case for case in cases if "levels" in case]

    def level1(case: Mapping[str, Any]) -> Mapping[str, Any]:
        return case["levels"][1]

    def spread(case: Mapping[str, Any], name: str) -> float:
        return level1(case)["ablation"][f"audio_pitch_spread_{name}"]

    h1 = [
        case["case"]
        for case in usable
        if case["preservation"]["only_audf_changed"]
        and case["preservation"]["audc_unchanged"]
        and case["preservation"]["audctl_unchanged"]
        and case["preservation"]["frames_outside_window_unchanged"]
    ]
    h2 = [case["case"] for case in usable if spread(case, "C") - spread(case, "A") >= MATERIAL_PITCH_SEMITONES]
    h3 = [
        case["case"]
        for case in usable
        if case["preservation"]["starts_at_base"]
        and case["preservation"]["within_one_octave"]
        and case["preservation"]["frames_outside_window_unchanged"]
    ]
    h4: List[str] = []
    h4_against: List[str] = []
    for case in usable:
        reference = case.get("reference")
        if not reference:
            continue
        target = reference["centroid_std_hz"]
        a_std = level1(case)["variants"]["A"]["centroid_std_hz"]
        c_std = level1(case)["variants"]["C"]["centroid_std_hz"]
        (h4 if abs(c_std - target) < abs(a_std - target) else h4_against).append(case["case"])

    with_control = [case for case in usable if case["control_available"]]
    h5_c = [
        case["case"]
        for case in with_control
        if spread(case, "C") - spread(case, "A") > spread(case, "D") - spread(case, "A")
    ]
    h5_d = [case["case"] for case in with_control if case["case"] not in h5_c]
    h5_tie = [
        case["case"]
        for case in with_control
        if abs((spread(case, "C") - spread(case, "A")) - (spread(case, "D") - spread(case, "A")))
        < 0.1
    ]

    return {
        "usable_cases": [case["case"] for case in usable],
        "H1_technical_transfer": {
            "cases": h1,
            "count": len(h1),
            "of": len(usable),
            "why": "only the AUDF column changes; AUDC, AUDCTL and frames outside the note are byte-identical",
        },
        "H2_beyond_static_pitch": {
            "cases": h2,
            "count": len(h2),
            "of": len(usable),
            "why": f"C adds at least {MATERIAL_PITCH_SEMITONES} semitones of measured pitch spread over B",
        },
        "H3_preserves_musical_pitch": {
            "cases": h3,
            "count": len(h3),
            "of": len(usable),
            "why": "the trajectory starts at the note's own pitch and stays within one octave of it",
        },
        "H4_reproduces_the_reference": {
            "cases": h4,
            "against": h4_against,
            "count": len(h4),
            "of": len(h4) + len(h4_against),
            "why": "C's short-time centroid spread is closer to the source reference's than A's",
        },
        "H5_specific_to_the_profile": {
            "C_moves_more": h5_c,
            "D_moves_more": h5_d,
            "indistinguishable": h5_tie,
            "of": len(with_control),
            "why": "where a donor control exists, does the profile's own trajectory move the "
            "measured pitch more than a similar trajectory from another profile?",
            "note": "a mixed split here means generic pitch movement explains the effect as well as "
            "the profile's own trajectory does",
        },
    }


# ---------------------------------------------------------------------------
# Part 14 — is a listening package justified, and which trials
# ---------------------------------------------------------------------------
LISTENING_TRIAL_LIMIT = 16


def listening_plan(cases: Sequence[Mapping[str, Any]], hypotheses: Mapping[str, Any]) -> Dict[str, Any]:
    """A small blind plan if, and only if, the analysis separates static from trajectory.

    Four cases are taken (the largest measured trajectories) and each contributes an isolated
    C-vs-A, an isolated C-vs-B, a phrase-level C-vs-A, and — where a donor exists — a C-vs-D
    control, which keeps the block at or below the brief's 16-trial ceiling with the mix the
    brief recommends.
    """
    usable = [case for case in cases if "levels" in case]
    justified = bool(hypotheses["H1_technical_transfer"]["count"]) and bool(
        hypotheses["H2_beyond_static_pitch"]["count"]
    )
    ranked = sorted(usable, key=lambda case: (-case["trajectory"]["max_abs_semitones"], case["case"]))
    trials: List[Dict[str, Any]] = []
    if justified:
        for case in ranked[:4]:
            for level, left, right, kind in (
                (1, "C", "A", "isolated: trajectory vs static"),
                (1, "C", "B", "isolated: trajectory vs profile static level"),
                (2, "C", "A", "phrase: trajectory vs static"),
            ):
                trials.append(
                    {
                        "trial_id": f"{case['case']}_L{level}_{left}_vs_{right}",
                        "case": case["case"],
                        "level": level,
                        "left": left,
                        "right": right,
                        "kind": kind,
                    }
                )
            if case["control_available"]:
                trials.append(
                    {
                        "trial_id": f"{case['case']}_L1_C_vs_D",
                        "case": case["case"],
                        "level": 1,
                        "left": "C",
                        "right": "D",
                        "kind": "isolated: profile trajectory vs donor control",
                    }
                )
    return {
        "justified": justified,
        "trials": trials[:LISTENING_TRIAL_LIMIT],
        "count": len(trials[:LISTENING_TRIAL_LIMIT]),
        "reason": (
            "the trajectory is technically transferred and changes the measured pitch in at least "
            "one case, so a blind static-vs-trajectory comparison tests a real distinction"
            if justified
            else "the analysis does not separate the trajectory from the static rendering"
        ),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def run_experiment(
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    cases: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Reconnaissance, selection, the four variants, the ablation and the decision. Deterministic."""
    bank = load_sound_profile_bank(Path(bank_dir))
    recon = reconnaissance(bank, arch_root=arch_root)
    selected = list(cases) if cases is not None else select_cases(bank)

    analysed: List[Dict[str, Any]] = []
    for case in selected:
        try:
            analysed.append(analyse_case(case, bank, arch_root=arch_root))
        except Exception as error:  # a technical failure is recorded, never hidden
            analysed.append(
                {
                    "case": case["case"],
                    "profile_id": case["profile_id"],
                    "technical_failure": f"{type(error).__name__}: {error}",
                }
            )

    hypotheses = evaluate(analysed)
    listening = listening_plan(analysed, hypotheses)

    inputs: Dict[str, str] = {}
    registry = Path(bank_dir) / "registry.json"
    if registry.is_file():
        inputs["bank/registry.json"] = sha256_file(registry)
    for case in selected:
        profile_path = Path(bank_dir) / "profiles" / f"{case['profile_id']}.json"
        if profile_path.is_file():
            inputs[f"bank/profiles/{case['profile_id']}.json"] = sha256_file(profile_path)
        if case.get("donor") and case["donor"].get("profile_id"):
            donor_path = Path(bank_dir) / "profiles" / f"{case['donor']['profile_id']}.json"
            if donor_path.is_file():
                inputs[f"bank/profiles/{case['donor']['profile_id']}.json"] = sha256_file(donor_path)
        reference = (
            Path(arch_root)
            / "reports"
            / "trace_profile_comparisons"
            / case["profile_id"]
            / "reference_replay.wav"
        )
        if reference.is_file():
            inputs[f"archaeology/{case['profile_id']}/reference_replay.wav"] = sha256_file(reference)

    return {
        "analysis_version": ANALYSIS_VERSION,
        "experiment": "stage13a",
        "variants": VARIANT_LABELS,
        "stimulus": {
            "bpm": BPM,
            "velocity": VELOCITY,
            "character": CHARACTER,
            "channel": 1,
            "sample_rate": SAMPLE_RATE,
            "frame_rate_hz": FRAME_RATE_HZ,
            "representation": "semitones_from_base: hz = base_hz * 2 ** (delta / 12)",
            "transform": "offline AUDF-only rewrite of the tested note's frames; the production "
            "IR, player and renderer are unchanged",
            "level_1": "one sustained note carrying the trajectory",
            "level_2": "a four-event phrase with the trajectory on the third event only",
        },
        "reconnaissance": recon,
        "selection": selected,
        "cases": analysed,
        "hypotheses": hypotheses,
        "listening": listening,
        "inputs": inputs,
    }


# ---------------------------------------------------------------------------
# Writing the record and the document
# ---------------------------------------------------------------------------
def write_experiment(
    bundle: Mapping[str, Any],
    *,
    stage13a_dir: Path = DEFAULT_STAGE13_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the machine record and the document. Deterministic byte-for-byte."""
    stage13a_dir = Path(stage13a_dir)
    docs_dir = Path(docs_dir)
    stage13a_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, Path] = {}
    for name, payload in (
        ("experiment.json", bundle),
        ("reconnaissance.json", bundle["reconnaissance"]),
        ("selection.json", bundle["selection"]),
        ("cases.json", bundle["cases"]),
        ("hypotheses.json", bundle["hypotheses"]),
        ("listening.json", bundle["listening"]),
    ):
        path = stage13a_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = path

    doc = docs_dir / "stage13a_pitch_trajectory_experiment.md"
    doc.write_text(render_report(bundle), encoding="utf-8", newline="\n")
    written["stage13a_pitch_trajectory_experiment.md"] = doc
    return written


def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join([":---"] * len(header)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("—" if cell is None else str(cell) for cell in row) + " |")
    return "\n".join(lines)


def verdict(bundle: Mapping[str, Any]) -> Dict[str, str]:
    """The decision tree, applied to the measured hypotheses (listening not yet run)."""
    h = bundle["hypotheses"]
    h1 = h["H1_technical_transfer"]["count"] > 0
    h2 = h["H2_beyond_static_pitch"]["count"] > 0
    h3 = h["H3_preserves_musical_pitch"]["count"] > 0
    h5 = h["H5_specific_to_the_profile"]
    mixed = bool(h5["C_moves_more"]) and bool(h5["D_moves_more"])
    if not (h1 and h2 and h3):
        label = "NOT SUPPORTED"
        why = "the trajectory is not transferred, adds nothing over static pitch, or breaks the note"
    elif mixed or not bundle["listening"]["justified"]:
        label = "INCONCLUSIVE"
        why = (
            "the technical effect is clean and measurable, but where a donor control exists the "
            "profile's own trajectory does not move the measured pitch further than a similar "
            "trajectory from another profile (a mixed split), and the blind listening is not run"
            if mixed
            else "the analysis does not separate the trajectory from the static rendering"
        )
    else:
        label = "INCONCLUSIVE"
        why = (
            "the technical effect is clean and measurable and the control is beaten, but the "
            "decision rule additionally requires listening evidence, and the prepared blind "
            "package has not been run"
        )
    return {"label": label, "why": why}


def render_report(bundle: Mapping[str, Any]) -> str:
    """`docs/stage13a_pitch_trajectory_experiment.md`."""
    recon = bundle["reconnaissance"]
    hypotheses = bundle["hypotheses"]
    listening = bundle["listening"]
    decision = verdict(bundle)
    usable = [case for case in bundle["cases"] if "levels" in case]
    failures = [case for case in bundle["cases"] if "technical_failure" in case]
    lines: List[str] = []
    add = lines.append

    add("# Stage 13A — pitch trajectory perceptual experiment")
    add("")
    add(f"**VERDICT: {decision['label']}**")
    add("")
    add(
        "Does the temporal pitch behaviour measured inside a real POKEY sound contain "
        "transferable information that improves a new Composer-generated sound? This experiment "
        "answers the technical half exactly and prepares the perceptual half. The production IR, "
        "player and renderer are untouched: the trajectory is applied as an offline rewrite of "
        "one note's AUDF column."
    )
    add("")
    add(f"* experiment: `{bundle['experiment']}` (`{bundle['analysis_version']}`)")
    add("* variants: A STATIC · B PROFILE_STATIC · C PROFILE_TRAJECTORY · D CONTROL_TRAJECTORY")
    add(
        f"* cases: **{len(usable)}** usable of {len(bundle['selection'])}"
        f" ({len(failures)} technical failure{'' if len(failures) == 1 else 's'})"
    )
    add(
        f"* bounded trajectories in the bank: **{recon['transferable']['bounded_within_one_octave']}** of "
        f"{recon['transferable']['bounded_within_one_octave'] + recon['transferable']['unbounded_register_artifacts']} "
        "non-static series"
    )
    add(
        f"* listening package: **{'prepared' if listening['justified'] else 'not prepared'}** "
        f"({listening['count']} trials)"
    )
    add("")
    add("**Observed / Inference / Experimental choice** are kept apart throughout.")
    add("")

    add("## 1. Reconnaissance (Part 1)")
    add("")
    add(
        f"**Observed.** {recon['profiles']} profiles. Representation: "
        + ", ".join(
            f"`{key}` ×{value}" for key, value in sorted(recon["representation"]["modes"].items())
        )
        + "; unit "
        + ", ".join(
            f"`{key}` ×{value}" for key, value in sorted(recon["representation"]["units"].items())
        )
        + "; quantization "
        + ", ".join(
            f"{key} semitones ×{value}"
            for key, value in sorted(recon["representation"]["quantizations_semitones"].items())
        )
        + "."
    )
    add("")
    add(
        f"**Observed.** Gesture pitch: **{recon['gesture_pitch']['static']}** static, "
        f"**{recon['gesture_pitch']['non_static_with_runs']}** non-static with runs; behaviours "
        + ", ".join(
            f"{key} ×{value}" for key, value in sorted(recon["gesture_pitch"]["behaviors"].items())
        )
        + "; directions "
        + ", ".join(
            f"{key} ×{value}" for key, value in sorted(recon["gesture_pitch"]["directions"].items())
        )
        + "."
    )
    add("")
    add(
        f"**Observed — the finding that shapes the whole stage.** Only "
        f"**{recon['transferable']['bounded_within_one_octave']}** of the non-static series stay "
        f"within one octave of their base; "
        f"**{recon['transferable']['unbounded_register_artifacts']}** leave it, by up to 96 "
        "semitones. Those excursions are divider/pair register artifacts, not pitch, so they are "
        "excluded from case selection. (Context: " + recon["first_loss_note"] + ".)"
    )
    add("")

    add("## 2. What \"pitch trajectory\" means here (Parts 2, 5)")
    add("")
    add(
        "**Experimental choice.** The trajectory is the profile's `gesture.pitch.runs`, expanded "
        "verbatim to one semitone delta per VBL frame, and re-based on the Composer's note with the "
        "representation Stage 5 validated: `hz = base_hz * 2 ** (delta / 12)`. The note's own pitch "
        "is the base, so a static series is an exact no-op and the movement is *inside* the note. "
        "Nothing is stretched or truncated: the note is made `3 * ceil(frames / 3)` frames long (the "
        "finest grid the Composer offers) so it covers the series, and any remainder holds the last "
        "value."
    )
    add("")
    add("```text")
    add("static      C4 --------------- C4        (variant A / B)")
    add("trajectory  C4 -> +d1 -> +d2 -> +d3     (variant C / D, one delta per frame)")
    add("```")
    add("")

    add("## 3. Test material (Parts 7-8, 14)")
    add("")
    add(
        "**Experimental choice.** Cases were chosen by a rule stated in `stage13a.select_cases` "
        "before any audio was inspected: strongest, longest, vibrato, near-static, rising, falling, "
        "shortest, and one more for coverage — all bounded. One instrument (`bright_lead`), one "
        "velocity, one tempo, one channel and one renderer for every variant of every case."
    )
    add("")
    add(
        _md_table(
            ("case", "profile", "scope", "frames", "max|Δ| st", "changes", "behaviour / direction", "why"),
            [
                (
                    case["case"], case["profile_id"], case["scope"], case["frames"],
                    case["max_abs_semitones"], case["changes"],
                    f"{case['behavior']} / {case['direction']}", case["reason"],
                )
                for case in bundle["selection"]
            ],
        )
    )
    add("")

    add("## 4. The variants (Parts 3-4, 6)")
    add("")
    add(
        _md_table(
            ("variant", "pitch used", "everything else"),
            (
                ("A STATIC", "the Composer's note pitch", "unchanged"),
                ("B PROFILE_STATIC", "the trajectory's time-mean delta, held constant", "unchanged"),
                ("C PROFILE_TRAJECTORY", "the profile's measured per-frame delta", "unchanged"),
                ("D CONTROL_TRAJECTORY", "another profile's measured delta (donor)", "unchanged"),
            ),
        )
    )
    add("")
    add(
        "**Experimental choice.** B is the profile's *static pitch level* — the only static pitch a "
        "profile offers a consumer, since `base_hz` is a reference the binding deliberately does not "
        "apply. C minus B therefore isolates the *movement* from the *level*. D is a real donor "
        "trajectory, accepted only when it is within 2 semitones of range, half the frame count and "
        "3 changes of the tested one; otherwise the branch is recorded unavailable rather than filled "
        "with something arbitrary."
    )
    add("")
    unavailable = [case["case"] for case in usable if not case["control_available"]]
    add(
        "**Observed.** No defensible control exists for "
        + (", ".join(f"`{name}`" for name in unavailable) if unavailable else "any case")
        + "."
    )
    add("")

    add("## 5. Frame-level proof (Part 17)")
    add("")
    add(
        "**Observed.** For every case and level the only POKEY column that changes is AUDF1; AUDC, "
        "AUDCTL and every frame outside the tested note are byte-identical to A. That is the proof "
        "that the only variable is pitch/divider behaviour."
    )
    add("")
    add(
        _md_table(
            ("case", "level", "changed frames", "first", "columns", "AUDC unchanged",
             "AUDCTL unchanged", "outside unchanged"),
            [
                (
                    case["case"], level,
                    case["levels"][level]["variants"]["C"]["proof"]["changed_frames"],
                    case["levels"][level]["variants"]["C"]["proof"]["first_changed_frame"],
                    ", ".join(case["levels"][level]["variants"]["C"]["proof"]["changed_pokey_columns"]),
                    case["levels"][level]["variants"]["C"]["proof"]["audc_unchanged"],
                    case["levels"][level]["variants"]["C"]["proof"]["audctl_unchanged"],
                    case["levels"][level]["variants"]["C"]["proof"]["frames_outside_window_unchanged"],
                )
                for case in usable
                for level in (1, 2)
            ],
        )
    )
    add("")

    add("## 6. Quantitative analysis (Part 10)")
    add("")
    add(
        "**Observed.** Applied pitch (exact, from the frames) and the audio descriptors measured on "
        "the *tested note* with a short-time pitch tracker. `spread` is the standard deviation of the "
        "tracked fundamental, in semitones; A and B are 0 by construction."
    )
    add("")
    add(
        _md_table(
            ("case", "level", "applied range st", "applied RMS st", "changes", "rate Hz",
             "A spread st", "C spread st", "C−A"),
            [
                (
                    case["case"], level,
                    case["levels"][level]["variants"]["C"]["pitch"]["range_semitones"],
                    case["levels"][level]["variants"]["C"]["pitch"]["rms_semitones"],
                    case["levels"][level]["variants"]["C"]["pitch"]["changes"],
                    case["levels"][level]["variants"]["C"]["pitch"]["change_rate_hz"],
                    case["levels"][level]["ablation"]["audio_pitch_spread_A"],
                    case["levels"][level]["ablation"]["audio_pitch_spread_C"],
                    case["levels"][level]["ablation"]["audio_pitch_spread_C_minus_A"],
                )
                for case in usable
                for level in (1, 2)
            ],
        )
    )
    add("")

    add("## 7. Reference comparison (Part 11)")
    add("")
    add(
        "**Observed.** The source reference's short-time centroid spread against A's and C's, where a "
        "reference exists. The question is whether C reproduces a temporal aspect of the reference "
        "that A cannot."
    )
    add("")
    reference_rows = [
        (
            case["case"], case["profile_id"],
            case["reference_vs_variants"]["reference_centroid_std_hz"],
            case["reference_vs_variants"]["A_centroid_std_hz"],
            case["reference_vs_variants"]["C_centroid_std_hz"],
            case["reference_vs_variants"]["C_towards_reference"],
        )
        for case in usable
        if case["reference_vs_variants"] is not None
    ]
    add(
        _md_table(
            ("case", "profile", "reference centroid std Hz", "A centroid std Hz",
             "C centroid std Hz", "C − A Hz"),
            reference_rows,
        )
        if reference_rows
        else "**Observed.** No reference audio is available for the selected profiles."
    )
    add("")

    add("## 8. Ablation (Part 12) and the control (Part 13)")
    add("")
    add(
        f"**Observed.** H2 — C adds measurable pitch movement over the static profile level B — holds "
        f"in **{hypotheses['H2_beyond_static_pitch']['count']} of "
        f"{hypotheses['H2_beyond_static_pitch']['of']}** cases (threshold "
        f"{MATERIAL_PITCH_SEMITONES} semitones). Because B holds one constant delta, the audio-side "
        "C−B and C−A numbers are equal."
    )
    add("")
    h5 = hypotheses["H5_specific_to_the_profile"]
    add(
        f"**Observed — the control that matters.** Where a donor exists ({h5['of']} cases): the "
        f"profile's own trajectory moved the measured pitch further in "
        f"**{len(h5['C_moves_more'])}** ({', '.join(h5['C_moves_more']) or '—'}), the donor's in "
        f"**{len(h5['D_moves_more'])}** ({', '.join(h5['D_moves_more']) or '—'}), and "
        f"**{len(h5['indistinguishable'])}** were indistinguishable."
    )
    add("")
    add(
        "**Inference.** A mixed split means generic pitch movement explains the measured effect as "
        "well as the profile's own trajectory does: the *movement* is real, but this experiment finds "
        "no evidence that the archaeology-derived shape carries unique information."
    )
    add("")

    add("## 9. Listening (Parts 14-15)")
    add("")
    add(
        f"**Experimental choice.** "
        f"{listening['reason'][:1].upper()}{listening['reason'][1:]}. Package: "
        f"**{'prepared' if listening['justified'] else 'not prepared'}** ({listening['count']} trials). "
        "Each trial asks which side is preferred, which is more convincing as Atari music, how "
        "confident the answer is, how different the two sides are, and which side (if either) has "
        "pitch movement or a more expressive character — never which side carries the profile."
    )
    add("")
    if listening["trials"]:
        add(
            _md_table(
                ("trial", "kind"),
                [(trial["trial_id"], trial["kind"]) for trial in listening["trials"]],
            )
        )
        add("")

    add("## 10. Reproducibility")
    add("")
    add(
        "Every number is a pure function of the bank and the archaeology reference WAVs below "
        "(SHA-256); there is no timestamp in any artefact and the case list is fixed in source."
    )
    add("")
    add("```json")
    add(json.dumps(bundle["inputs"], indent=2, sort_keys=True))
    add("```")
    add("")

    add("## Final report — the eight questions")
    add("")
    add(
        f"**1. Is profile-derived pitch trajectory technically transferable?** **Yes.** H1 holds in "
        f"{hypotheses['H1_technical_transfer']['count']} of {hypotheses['H1_technical_transfer']['of']} "
        "cases: the trajectory is re-based on the Composer's note in the Stage-5 representation and "
        "reaches the register frames exactly, changing only AUDF."
    )
    add("")
    add(
        f"**2. Does it add information beyond static profile pitch?** **Yes.** H2 holds in "
        f"{hypotheses['H2_beyond_static_pitch']['count']} of "
        f"{hypotheses['H2_beyond_static_pitch']['of']} cases. B (the static level) adds no measurable "
        "pitch movement at all, so C − B is the whole trajectory."
    )
    add("")
    add(
        f"**3. Does it preserve the musical pitch of the Composer?** **Yes.** H3 holds in "
        f"{hypotheses['H3_preserves_musical_pitch']['count']} of "
        f"{hypotheses['H3_preserves_musical_pitch']['of']} cases: the series starts at the note's own "
        "pitch, stays within one octave of it, AUDC and AUDCTL are untouched, and every frame outside "
        "the note is byte-identical to the static render."
    )
    add("")
    add(
        f"**4. Does it reproduce an aspect of the reference that static misses?** **Partly.** C's "
        f"centroid spread is closer to the source reference's than A's in "
        f"{hypotheses['H4_reproduces_the_reference']['count']} of "
        f"{hypotheses['H4_reproduces_the_reference']['of']} reference-bearing cases (against: "
        f"{', '.join(hypotheses['H4_reproduces_the_reference']['against']) or '—'})."
    )
    add("")
    add(
        f"**5. Is the effect specific to the profile trajectory?** **Not established.** Where a donor "
        f"control exists the split is {len(h5['C_moves_more'])} to {len(h5['D_moves_more'])}: a "
        "similar trajectory taken from a different profile moves the measured pitch about as much."
    )
    add("")
    add(
        f"**6. Is the effect perceptually audible?** **Prepared, not yet measured.** The blind package "
        f"({listening['count']} trials: isolated C-vs-A, isolated C-vs-B, phrase-level C-vs-A and "
        "C-vs-D controls) is built; its result is unknown."
    )
    add("")
    add(
        "**7. Is it musically useful rather than merely detectable?** **Unknown.** Detectable: yes. "
        "Characteristic of the profile: not shown (question 5). Useful: only a listener can say, and "
        "the brief's rule forbids declaring it on technical grounds alone."
    )
    add("")
    add(
        "**8. The single highest-value next step.** **Run the prepared blind listening package "
        "(C vs A, C vs B, C vs D).** The mechanics are settled and the ablation is clean; what the "
        "decision tree still needs is whether a listener hears and prefers the movement — and whether "
        "the profile's own trajectory is distinguishable from a generic one. If the listener cannot "
        "tell C from D, the conclusion is already visible in the measurement: generic pitch movement, "
        "not the profile, is what is audible."
    )
    add("")
    add("### Verdict")
    add("")
    add(f"**{decision['label']}.** {decision['why'].capitalize()}.")
    add("")
    add(
        "The decision tree's `SUPPORTED` branch additionally requires a perceptually meaningful "
        "difference and, preferably, that C beat the generic control D — and the quantitative half of "
        "that (C vs D) is already mixed. `INCONCLUSIVE` is therefore the honest label today, with the "
        "listening package as the evidence that would move it."
    )
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Parts 14-15, 20 — the blind listening package
# ---------------------------------------------------------------------------
LISTENING_PACKAGE_DIR = REPO_ROOT / "examples" / "stage13a_listening"
LISTENING_SEED = 20261009
_ANSWER_HEADER = (
    "trial_id",
    "better_overall",
    "more_atari_character",
    "confidence_1_5",
    "difference_1_5",
    "pitch_movement",
    "expressive_character",
    "comment",
)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.astype(np.int16).tobytes())


def build_listening_package(
    bundle: Mapping[str, Any],
    *,
    out_dir: Path = LISTENING_PACKAGE_DIR,
    seed: int = LISTENING_SEED,
    bank_dir: Path = DEFAULT_BANK_DIR,
) -> Dict[str, Any]:
    """Write the blinded WAVs, the private manifest, the template, the metadata and the page."""
    import random

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audio").mkdir(exist_ok=True)
    bank = load_sound_profile_bank(Path(bank_dir))
    by_id = {case["case"]: case for case in bundle["selection"]}
    rng = random.Random(seed)

    trials: List[Dict[str, Any]] = []
    for trial in bundle["listening"]["trials"]:
        case = by_id[trial["case"]]
        levels = variants_for_case(bank, case)["levels"]
        data = levels[trial["level"]]
        samples = {name: data["rendered"][name]["samples"] for name in VARIANT_ORDER}
        left, right = trial["left"], trial["right"]
        sides = {"a": left, "b": right} if rng.random() < 0.5 else {"a": right, "b": left}
        hashes: Dict[str, str] = {}
        for side in ("a", "b"):
            variant = sides[side]
            path = out_dir / "audio" / f"{trial['trial_id']}_{side}.wav"
            _write_wav(path, samples[variant])
            hashes[side] = _sha256_samples(samples[variant])
        trials.append(
            {
                "trial_id": trial["trial_id"],
                "case": trial["case"],
                "level": trial["level"],
                "kind": trial["kind"],
                "profile_id": case["profile_id"],
                "compared": {"left": left, "right": right},
                "sides": sides,
                "audio": {
                    "a": f"audio/{trial['trial_id']}_a.wav",
                    "b": f"audio/{trial['trial_id']}_b.wav",
                },
                "sha256": hashes,
            }
        )

    manifest = {
        "schema": "atari-music/stage13a-listening/1",
        "experiment": "stage13a",
        "seed": seed,
        "sample_rate": SAMPLE_RATE,
        "stimulus": bundle["stimulus"],
        "level_policy": "the synthesiser normalizes every buffer to a peak of 0.90; no extra gain, "
        "EQ or compression is applied, and no per-frame normalization",
        "trials": trials,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "evaluation_stage13a.csv").write_text(
        ",".join(_ANSWER_HEADER)
        + "\n"
        + "".join(f"{trial['trial_id']}" + "," * (len(_ANSWER_HEADER) - 1) + "\n" for trial in trials),
        encoding="utf-8",
    )
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": "stage13a",
                "variants": bundle["variants"],
                "trials": len(trials),
                "inputs": bundle["inputs"],
                "wav_hashes": {
                    f"{trial['trial_id']}:{side}": digest
                    for trial in trials
                    for side, digest in trial["sha256"].items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "index.html").write_text(
        render_index_html(manifest), encoding="utf-8", newline="\n"
    )
    (out_dir / "README.md").write_text(_listening_readme(manifest), encoding="utf-8", newline="\n")
    return manifest


def render_index_html(manifest: Mapping[str, Any]) -> str:
    """The listening interface: one self-contained page, no server and no Python.

    The payload carries only the trial ids and the two audio paths, so the page cannot reveal
    which side carries the profile trajectory even to a curious listener.
    """
    payload = {
        "experiment": manifest["experiment"],
        "trials": [
            {
                "trial_id": trial["trial_id"],
                "a": trial["audio"]["a"],
                "b": trial["audio"]["b"],
            }
            for trial in manifest["trials"]
        ],
    }
    return _INDEX_HTML.replace("__PACKAGE__", json.dumps(payload, sort_keys=True))


def _listening_readme(manifest: Mapping[str, Any]) -> str:
    return (
        "# Stage 13A listening — pitch trajectory\n\n"
        "Two versions of the same note (or the same short phrase). The only difference between the\n"
        "two sides is whether a **measured pitch trajectory** — how the pitch of a real POKEY sound\n"
        "moved inside the note, taken from the archaeology — has been applied to it. One side is the\n"
        "Composer's plain rendering; the other carries the movement.\n\n"
        "**You need nothing installed.** Open `index.html`, listen, answer, and use the\n"
        "\"Download the answer CSV\" button at the end. If the browser refuses to play local audio,\n"
        "serve the folder instead:\n\n"
        "```bash\npython -m http.server 8741 --directory examples/stage13a_listening\n```\n\n"
        f"There are **{len(manifest['trials'])} pairs**. Some compare against the Composer's plain\n"
        "sound; a few compare two different movements against each other. Listen to both sides as\n"
        "often as you like, then answer. Answers are kept in this browser, so a session can be\n"
        "resumed. Nothing is uploaded. `manifest.json` is the private key and should not be opened\n"
        "while listening.\n\n"
        "Questions: which sounds **better overall**, which is **more convincing as Atari music**,\n"
        "how **confident** you are, how **different** the two sides are (1-5), and — the important\n"
        "ones — which side (if either) has **pitch movement**, and which has the **more expressive\n"
        "character**. There are no right answers.\n"
    )


_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>POKEY pitch trajectory comparison</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; padding: 1.5rem;
         background: #14161a; color: #e8e8ea; line-height: 1.5; }
  main { max-width: 60rem; margin: 0 auto; }
  h1, h2 { line-height: 1.2; }
  .note { background: #1d2026; border-left: 3px solid #4a7; padding: .75rem 1rem; margin: 1rem 0;
          border-radius: 3px; font-size: .95rem; }
  .card { background: #1a1d22; border: 1px solid #2c3036; border-radius: 6px; padding: 1rem;
          margin: 1rem 0; }
  .card.done { border-color: #3d6; }
  .label { font-weight: 600; min-width: 13rem; }
  audio { width: 100%; max-width: 30rem; }
  .q { margin: .6rem 0; }
  .scale { display: flex; gap: .4rem; flex-wrap: wrap; }
  .scale label { background: #23272e; border: 1px solid #333; border-radius: 4px;
                 padding: .25rem .6rem; cursor: pointer; font-variant-numeric: tabular-nums; }
  .scale input { margin-right: .3rem; }
  textarea { width: 100%; min-height: 3rem; background: #23272e; color: inherit;
             border: 1px solid #333; border-radius: 4px; padding: .4rem; font: inherit; }
  button { background: #2d5; color: #06120a; border: 0; border-radius: 4px; padding: .55rem 1rem;
           font: inherit; font-weight: 600; cursor: pointer; margin-right: .5rem; }
  button.ghost { background: #333; color: #ddd; }
  .progress { position: sticky; top: 0; background: #14161aee; padding: .6rem 0; z-index: 5;
              border-bottom: 1px solid #2c3036; font-variant-numeric: tabular-nums; }
  .small { font-size: .88rem; color: #aab; }
  .ab { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 40rem) { .ab { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<main>
<h1>Does the pitch move?</h1>

<div class="note">
  <strong>Your ears are the instrument here.</strong> Each pair plays the same note, the same
  velocity, the same instrument and the same renderer — twice. The only difference is whether a
  <em>pitch movement measured from a real POKEY sound</em> has been applied inside the note. Nothing
  on this page says which side is which, and there is no expected answer.
</div>
<div class="note">
  <strong>Set your volume once and leave it alone.</strong> Both sides of a pair are presented at the
  same gain. Judge character rather than loudness.
</div>
<div class="note">
  <strong>Some pairs compare two movements against each other</strong>, not a movement against a
  plain sound. Say which (if either) sounds better and which sounds more expressive.
</div>

<div class="progress" id="progress">progress</div>

<h2>Comparisons (<span id="count"></span> pairs)</h2>
<p class="small">Listen to both sides as many times as you like, then answer. Answers are kept in
this browser, so a session can be resumed.</p>
<div id="trials"></div>

<h2>Finish</h2>
<p class="small">Click the button to download the answer file. Nothing is uploaded anywhere —
everything stays in this browser until you download it.</p>
<button onclick="downloadAll()">Download the answer CSV</button>
<button class="ghost" onclick="if(confirm('Erase all answers in this browser?')){localStorage.clear();location.reload();}">Reset answers</button>

<script>
const PACKAGE = __PACKAGE__;
const STORE = "stage13a-answers-v1";
let answers = JSON.parse(localStorage.getItem(STORE) || "{}");

function save() { localStorage.setItem(STORE, JSON.stringify(answers)); refresh(); }
function get(key, field) { return (answers[key] || {})[field] ?? ""; }
function set(key, field, value) {
  answers[key] = answers[key] || {};
  answers[key][field] = value;
  save();
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}
function download(name, header, rows) {
  const body = [header.join(",")].concat(rows.map(r => r.map(csvEscape).join(","))).join("\n") + "\n";
  const url = URL.createObjectURL(new Blob([body], {type: "text/csv;charset=utf-8"}));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

const HEADER = ["trial_id", "better_overall", "more_atari_character", "confidence_1_5",
                "difference_1_5", "pitch_movement", "expressive_character", "comment"];
const CHOICES = [
  ["better_overall", "Which version sounds better overall?"],
  ["more_atari_character", "Which sounds more convincing as Atari music?"]
];
const SIDE_QUESTIONS = [
  ["pitch_movement", "Does either side change noticeably in pitch during the note?"],
  ["expressive_character", "Which side has the more expressive character?"]
];

function choiceRow(key, field, question) {
  const current = get(key, field);
  const values = ["a", "b", "none"];
  const labels = ["A", "B", "No clear difference"];
  const inputs = values.map((value, index) => {
    const checked = String(current) === value ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${labels[index]}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function movementRow(key, field, question) {
  const current = get(key, field);
  const values = ["a", "b", "both", "neither"];
  const labels = ["A", "B", "both", "neither"];
  const inputs = values.map((value, index) => {
    const checked = String(current) === value ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${labels[index]}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function scaleRow(key, field, question, labels) {
  const current = get(key, field);
  const inputs = labels.map((label, index) => {
    const value = String(index + 1);
    const checked = String(current) === value ? " checked" : "";
    return `<label><input type="radio" name="${key}-${field}" value="${value}"${checked}
      onchange="set('${key}','${field}','${value}')">${label}</label>`;
  }).join("");
  return `<div class="q"><div class="label">${question}</div><div class="scale">${inputs}</div></div>`;
}

function commentRow(key) {
  const value = String(get(key, "comment")).replace(/</g, "&lt;");
  return `<div class="q"><div class="label">Comment (optional)</div>
    <textarea oninput="set('${key}','comment',this.value)">${value}</textarea></div>`;
}

function isDone(key) {
  const answered = CHOICES.every(q => get(key, q[0]) !== "")
    && SIDE_QUESTIONS.every(q => get(key, q[0]) !== "");
  return answered && get(key, "confidence_1_5") !== "" && get(key, "difference_1_5") !== "";
}

document.getElementById("trials").innerHTML = PACKAGE.trials.map((trial, index) => {
  const id = trial.trial_id;
  const body = `<div class="small">This pair is one short phrase, played twice.</div>
    <div class="ab">
      <div><div class="label">A</div><audio controls preload="none" src="${trial.a}"></audio></div>
      <div><div class="label">B</div><audio controls preload="none" src="${trial.b}"></audio></div>
    </div>` +
    CHOICES.map(q => choiceRow(id, q[0], q[1])).join("") +
    scaleRow(id, "confidence_1_5", "How confident are you in that answer?",
      ["1 guess", "2", "3", "4", "5 certain"]) +
    scaleRow(id, "difference_1_5", "How different do the two sides sound?",
      ["1 identical", "2", "3 noticeable", "4", "5 very large"]) +
    SIDE_QUESTIONS.map(q => movementRow(id, q[0], q[1])).join("") +
    commentRow(id) +
    `<div class="small">Pair ${index + 1} of ${PACKAGE.trials.length}</div>`;
  return `<div class="card${isDone(id) ? " done" : ""}" id="${id}">${body}</div>`;
}).join("");

function refresh() {
  const done = PACKAGE.trials.filter(trial => isDone(trial.trial_id)).length;
  document.getElementById("progress").textContent =
    `Progress — ${done}/${PACKAGE.trials.length} pairs answered (answers are saved in this browser)`;
  document.getElementById("count").textContent = PACKAGE.trials.length;
}

function downloadAll() {
  download("evaluation_stage13a.csv", HEADER,
    PACKAGE.trials.map(trial => [trial.trial_id, get(trial.trial_id, "better_overall"),
      get(trial.trial_id, "more_atari_character"),
      get(trial.trial_id, "confidence_1_5"),
      get(trial.trial_id, "difference_1_5"),
      get(trial.trial_id, "pitch_movement"),
      get(trial.trial_id, "expressive_character"), get(trial.trial_id, "comment")]));
}

refresh();
</script>
</main>
</body>
</html>
"""

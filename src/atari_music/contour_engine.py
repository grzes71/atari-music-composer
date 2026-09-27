"""Melodic Contour & Interval Grammar Engine for Composer v2.

Generates abstract interval sequences satisfying specific melodic contours:
- UP, DOWN, ARCH, ASCENDING, DESCENDING, WAVE, QUESTION_ANSWER
Decouples directional motion from absolute note frequencies.
"""

from __future__ import annotations

import random
from typing import List

from atari_music.music_ir import MelodicContour


def generate_contour_intervals(
    contour: MelodicContour,
    num_notes: int,
    rng: random.Random,
) -> List[int]:
    """Generate interval sequence (num_notes - 1 intervals) fulfilling contour."""
    if num_notes <= 1:
        return []

    num_intervals = num_notes - 1
    intervals: List[int] = []

    if contour == MelodicContour.UP:
        # Strictly upward motion (+1 to +3)
        intervals = [rng.choice([1, 2, 2, 3]) for _ in range(num_intervals)]

    elif contour == MelodicContour.DOWN:
        # Strictly downward motion (-1 to -3)
        intervals = [rng.choice([-1, -2, -2, -3]) for _ in range(num_intervals)]

    elif contour == MelodicContour.ARCH:
        # Rise in first half, fall in second half
        half = num_intervals // 2
        for i in range(num_intervals):
            if i < half:
                intervals.append(rng.choice([1, 2, 2, 3]))
            else:
                intervals.append(rng.choice([-1, -2, -2, -3]))

    elif contour == MelodicContour.ASCENDING:
        # Net upward with occasional step-back: e.g. +2, +2, -1, +2, +3...
        for _ in range(num_intervals):
            step = rng.choice([2, 2, 1, 3, -1])
            intervals.append(step)

    elif contour == MelodicContour.DESCENDING:
        # Net downward with occasional step-up: e.g. -2, -2, +1, -2, -3...
        for _ in range(num_intervals):
            step = rng.choice([-2, -2, -1, -3, 1])
            intervals.append(step)

    elif contour == MelodicContour.WAVE:
        # Alternating undulating motion
        cur_dir = 1
        for _ in range(num_intervals):
            val = rng.choice([1, 2, 2]) * cur_dir
            intervals.append(val)
            if rng.random() < 0.65:
                cur_dir = -cur_dir

    elif contour == MelodicContour.QUESTION_ANSWER:
        # Antecedent rises to open dominant, consequent resolves downwards
        half = num_intervals // 2
        for i in range(num_intervals):
            if i < half:
                intervals.append(rng.choice([1, 2, 3, -1]))
            else:
                intervals.append(rng.choice([-1, -2, -3, 1]))

    return intervals


def generate_archetype_intervals(archetype: str, num_notes: int, rng: random.Random) -> List[int]:
    """Generate interval sequence fulfilling a specific musical archetype."""
    if num_notes <= 1:
        return []
    num_intervals = num_notes - 1

    if archetype == "stepwise":
        return [rng.choice([1, 2, -1, -2, 2, -1]) for _ in range(num_intervals)]
    elif archetype == "arpeggiated":
        return [rng.choice([3, 4, -3, -4, 5, -5]) for _ in range(num_intervals)]
    elif archetype in ("angular", "playful_leaps", "staccato"):
        return [rng.choice([3, 4, 5, -5, -4, 7, -6, 2]) for _ in range(num_intervals)]
    elif archetype in ("repetitive", "ostinato"):
        cell = [0, 2, 0, -2]
        return [cell[i % len(cell)] for i in range(num_intervals)]
    elif archetype == "fanfare":
        fanfare_steps = [4, 3, 5, -7, 0, 7, -4]
        return [fanfare_steps[i % len(fanfare_steps)] for i in range(num_intervals)]
    elif archetype == "lyrical":
        return generate_contour_intervals(MelodicContour.ARCH, num_notes, rng)
    elif archetype == "wave":
        return generate_contour_intervals(MelodicContour.WAVE, num_notes, rng)
    elif archetype == "ascending":
        return generate_contour_intervals(MelodicContour.ASCENDING, num_notes, rng)
    elif archetype == "descending":
        return generate_contour_intervals(MelodicContour.DESCENDING, num_notes, rng)
    elif archetype == "question_answer":
        return generate_contour_intervals(MelodicContour.QUESTION_ANSWER, num_notes, rng)
    elif archetype in ("modal", "drone_anchor", "wide_arch"):
        return [rng.choice([2, -2, 3, -3, 1, -1, 0]) for _ in range(num_intervals)]
    else:
        return generate_contour_intervals(MelodicContour.WAVE, num_notes, rng)



def realize_pitches_from_intervals(
    root_midi: int,
    intervals: List[int],
    scale: List[int],
    chord_tones: List[int],
    min_midi: int = 55,
    max_midi: int = 84,
) -> List[int]:
    """Convert relative intervals into scale-quantized absolute MIDI notes."""
    pitches = [root_midi]
    cur = root_midi

    for step in intervals:
        cur += step
        # Clamp to playable range
        cur = max(min_midi, min(max_midi, cur))
        # Quantize to closest note in scale
        cur = _quantize_to_scale(cur, root_midi, scale)
        pitches.append(cur)

    # Ensure last note anchors near tonic or chord tone
    if pitches and chord_tones:
        pitches[-1] = _quantize_to_chord_tones(pitches[-1], root_midi, chord_tones)

    return pitches


def _quantize_to_scale(midi: int, root_midi: int, scale: List[int]) -> int:
    """Find closest scale degree."""
    rel = (midi - root_midi) % 12
    closest_deg = min(scale, key=lambda d: abs(d - rel))
    octave_shift = ((midi - root_midi) // 12) * 12
    return root_midi + octave_shift + closest_deg


def _quantize_to_chord_tones(midi: int, root_midi: int, chord_tones: List[int]) -> int:
    """Find closest chord tone."""
    rel = (midi - root_midi) % 12
    closest_tone = min(chord_tones, key=lambda t: abs(t - rel))
    octave_shift = ((midi - root_midi) // 12) * 12
    return root_midi + octave_shift + closest_tone

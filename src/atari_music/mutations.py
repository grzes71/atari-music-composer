"""Motivic Mutation Engine for Composer v2.

Implements controlled symbolic mutations on melodic phrases and interval sequences:
- Transposition (diatonic scale shift)
- Inversion (reflecting interval direction)
- Retrograde (reversing phrase sequence)
- Rhythmic mutation (subdivision / augmentation)
- Interval substitution (step vs leap mutation)
- Note omission (rest replacement)
- Note insertion (passing / approach notes)
- Octave displacement (+/- 12 semitones)
- Rest insertion
Probabilities are scaled by the `novelty` parameter (0.0 .. 1.0).
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from atari_music.music_ir import MelodicContour, MusicPhrase, SymbolicNote


class MutationConfig:
    """Configurable probability matrix for motivic mutations."""

    def __init__(self, novelty: float = 0.50, **kwargs: float):
        self.novelty = max(0.0, min(1.0, novelty))
        # Base mutation rates scaled linearly with novelty
        factor = 0.4 + 0.8 * self.novelty
        self.transposition = kwargs.get("transposition", kwargs.get("transposition_prob", min(0.60, 0.25 * factor)))
        self.interval_mutation = kwargs.get("interval_mutation", kwargs.get("interval_mutation_prob", min(0.50, 0.20 * factor)))
        self.rhythm_mutation = kwargs.get("rhythm_mutation", kwargs.get("rhythm_mutation_prob", min(0.50, 0.20 * factor)))
        self.inversion = kwargs.get("inversion", kwargs.get("inversion_prob", min(0.35, 0.10 * factor)))
        self.retrograde = kwargs.get("retrograde", kwargs.get("retrograde_prob", min(0.30, 0.08 * factor)))
        self.note_insertion = kwargs.get("note_insertion", kwargs.get("note_insertion_prob", min(0.40, 0.15 * factor)))
        self.note_omission = kwargs.get("note_omission", kwargs.get("note_omission_prob", min(0.30, 0.10 * factor)))
        self.octave_displacement = kwargs.get("octave_displacement", kwargs.get("octave_displacement_prob", min(0.25, 0.08 * factor)))



def mutate_intervals(
    intervals: List[int],
    config: MutationConfig,
    scale_steps: List[int],
    rng: random.Random,
) -> List[int]:
    """Apply motivic mutations directly on the interval sequence."""
    if not intervals:
        return intervals

    mutated = list(intervals)

    # 1. Inversion: reflect interval signs (+2 -> -2)
    if rng.random() < config.inversion:
        mutated = [-x for x in mutated]

    # 2. Retrograde: reverse sequence
    if rng.random() < config.retrograde:
        mutated = list(reversed(mutated))

    # 3. Interval substitution on individual elements
    for i in range(len(mutated)):
        if rng.random() < config.interval_mutation:
            cur = mutated[i]
            if abs(cur) <= 2:  # Step -> Leap or small change
                mutated[i] = rng.choice([cur + 1, cur - 1, 3, 4, -3, -4])
            else:             # Leap -> Step
                mutated[i] = 1 if cur > 0 else -1

    return mutated


def mutate_rhythm(
    durations: List[int],
    total_rows: int,
    config: MutationConfig,
    rng: random.Random,
) -> List[int]:
    """Mutate duration sequence while preserving total row length."""
    if not durations or len(durations) < 2:
        return durations

    durs = list(durations)

    if rng.random() < config.rhythm_mutation:
        # Pick adjacent pair and exchange/subdivide
        idx = rng.randint(0, len(durs) - 2)
        combined = durs[idx] + durs[idx + 1]
        if combined >= 4:
            # Subdivide or redistribute: e.g. 2+2 -> 3+1 or 1+3 (syncopation)
            if combined == 4:
                durs[idx], durs[idx + 1] = rng.choice([(3, 1), (1, 3), (2, 2)])
            elif combined == 6:
                durs[idx], durs[idx + 1] = rng.choice([(4, 2), (2, 4), (3, 3)])

    # Ensure sum matches total_rows
    cur_sum = sum(durs)
    if cur_sum != total_rows and len(durs) > 0:
        diff = total_rows - cur_sum
        durs[-1] = max(1, durs[-1] + diff)

    return durs


def generate_phrase_variation(
    base_phrase: MusicPhrase,
    variation_id: str,
    novelty: float,
    scale: List[int],
    rng: random.Random,
) -> MusicPhrase:
    """Generate a genuine A' or A'' variation preserving contour and length."""
    config = MutationConfig(novelty=novelty)

    # Mutate intervals
    new_intervals = mutate_intervals(base_phrase.intervals, config, scale, rng)

    # Mutate rhythm if higher novelty
    total_phrase_rows = sum(base_phrase.rhythm) if base_phrase.rhythm else 16
    new_rhythm = mutate_rhythm(base_phrase.rhythm, total_phrase_rows, config, rng)

    # Transposition offset (e.g. shift up scale degree +2 or +4 semitones)
    transposition = 0
    if rng.random() < config.transposition:
        transposition = rng.choice([scale[1 % len(scale)], scale[2 % len(scale)], scale[4 % len(scale)]])

    return MusicPhrase(
        id=variation_id,
        contour=base_phrase.contour,
        intervals=new_intervals,
        rhythm=new_rhythm,
    )

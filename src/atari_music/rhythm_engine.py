"""Rhythm Engine for Composer v2.

Generates decoupled duration sequences and groove templates:
- Meter handling (4/4, 32-row patterns)
- Note density control (low, medium, high)
- Syncopation factor (offbeat ties and pushes)
- Rest insertion probability
"""

from __future__ import annotations

import random
from typing import List


def generate_rhythm_template(
    total_rows: int,
    density: str,
    syncopation: float,
    rng: random.Random,
) -> List[int]:
    """Generate list of row durations summing exactly to total_rows (v2 compatibility)."""
    durations: List[int] = []
    rem = total_rows

    if density == "high":
        allowed = [1, 2, 2, 2] if syncopation > 0.4 else [2, 2, 2, 4]
    elif density == "medium":
        allowed = [2, 2, 4, 4] if syncopation < 0.3 else [2, 3, 1, 4]
    else:  # low
        allowed = [4, 4, 8, 4]

    while rem > 0:
        choices = [d for d in allowed if d <= rem]
        if not choices:
            durations.append(rem)
            break
        dur = rng.choice(choices)
        durations.append(dur)
        rem -= dur

    return durations


def generate_profile_rhythm(
    rhythm_family: str,
    total_rows: int,
    syncopation: float,
    rng: random.Random,
) -> List[int]:
    """Generate musically distinct rhythm patterns matching the profile's rhythm family."""
    durations: List[int] = []
    rem = total_rows

    if rhythm_family == "sparse":
        # Broad sustained notes, breaths, and wide anchors (durations 4, 6, 8, 12, 16)
        pool = [4, 6, 8, 8, 12, 16] if syncopation < 0.4 else [3, 4, 6, 8, 10]
    elif rhythm_family == "lyrical":
        # Flowing song-like phrasing with natural accents (durations 2, 3, 4, 6)
        pool = [2, 2, 3, 4, 4, 6] if syncopation > 0.3 else [2, 4, 4, 6, 8]
    elif rhythm_family == "driving":
        # Fast, energetic arcade drive (durations 1, 2 with occasional 4)
        pool = [1, 1, 2, 2, 2] if syncopation > 0.4 else [2, 2, 2, 2, 4]
    elif rhythm_family == "syncopated":
        # Off-beat pushes, dotted notes, and ties (3+1, 1+3, 1+2+1)
        pool = [1, 3, 3, 1, 2, 3]
    elif rhythm_family == "ostinato":
        # Repeating structured rhythmic motif
        cell = [2, 2, 4] if syncopation < 0.4 else [3, 1, 4]
        cell_sum = sum(cell)
        while rem >= cell_sum:
            durations.extend(cell)
            rem -= cell_sum
        pool = [2, 4]
    elif rhythm_family == "march":
        # Fanfare dotted rhythm: 3+1 or 4+2+2
        cell = [3, 1, 2, 2] if syncopation > 0.3 else [4, 2, 2]
        cell_sum = sum(cell)
        while rem >= cell_sum:
            durations.extend(cell)
            rem -= cell_sum
        pool = [2, 4, 4]
    elif rhythm_family == "playful":
        # Short staccatos, uneven pauses, and sudden syncopated steps
        pool = [1, 1, 2, 1, 3, 4]
    else:
        pool = [2, 2, 4, 4]

    while rem > 0:
        valid_choices = [d for d in pool if d <= rem]
        if not valid_choices:
            durations.append(rem)
            break
        pick = rng.choice(valid_choices)
        durations.append(pick)
        rem -= pick

    return durations


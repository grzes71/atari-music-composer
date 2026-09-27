"""Harmonic Engine for Composer v2.

Provides:
- Chord progression templates for Major, Minor, Dorian, and Pentatonic
- Harmonic function mappings (TONIC, PREDOMINANT, DOMINANT, RESOLUTION)
- Chord tone alignment (anchoring melodic downbeats to chord degrees)
- Cadence resolution (V -> I, VII -> i)
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from atari_music.music_ir import ChordStep, HarmonicFunction

# Canonical Chord Progressions by mode
PROGRESSIONS: Dict[str, List[List[ChordStep]]] = {
    "minor": [
        # i - VI - III - VII (classic chiptune / 80s pop)
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=5, name="VI", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=2, name="III", function=HarmonicFunction.TONIC),
            ChordStep(degree=6, name="VII", function=HarmonicFunction.DOMINANT),
        ],
        # i - VII - VI - VII (Andalusian / driving arcade progression)
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=6, name="VII", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=5, name="VI", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=6, name="VII", function=HarmonicFunction.RESOLUTION),
        ],
        # i - iv - V - i (classical minor cadence)
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=3, name="iv", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=4, name="V", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=0, name="i", function=HarmonicFunction.RESOLUTION),
        ],
    ],
    "major": [
        # I - V - vi - IV (pop / heroic game theme)
        [
            ChordStep(degree=0, name="I", function=HarmonicFunction.TONIC),
            ChordStep(degree=4, name="V", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=5, name="vi", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=3, name="IV", function=HarmonicFunction.RESOLUTION),
        ],
        # I - IV - V - I (classic cadence)
        [
            ChordStep(degree=0, name="I", function=HarmonicFunction.TONIC),
            ChordStep(degree=3, name="IV", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=4, name="V", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=0, name="I", function=HarmonicFunction.RESOLUTION),
        ],
    ],
    "dorian": [
        # i - IV - VII - i (classic modal groove, common in retro chiptune style)
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=3, name="IV", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=6, name="VII", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=0, name="i", function=HarmonicFunction.RESOLUTION),
        ],
        # i - v - bVII - IV (flowing exploration modal)
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=4, name="v", function=HarmonicFunction.TONIC),
            ChordStep(degree=6, name="VII", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=3, name="IV", function=HarmonicFunction.RESOLUTION),
        ],
    ],
    "mixolydian": [
        # I - bVII - IV - I (classic rock / arcade heroic fanfare)
        [
            ChordStep(degree=0, name="I", function=HarmonicFunction.TONIC),
            ChordStep(degree=6, name="bVII", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=3, name="IV", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=0, name="I", function=HarmonicFunction.RESOLUTION),
        ],
    ],
    "pentatonic": [
        # Static modal / pedal point progression
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=3, name="IV", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=0, name="i", function=HarmonicFunction.RESOLUTION),
        ],
    ],
    "modal_pedal": [
        # Sustained root drone with minimal modal tension (Dungeon style)
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=6, name="VII", function=HarmonicFunction.DOMINANT),
            ChordStep(degree=0, name="i", function=HarmonicFunction.RESOLUTION),
        ],
        [
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=1, name="bII", function=HarmonicFunction.PREDOMINANT),
            ChordStep(degree=0, name="i", function=HarmonicFunction.TONIC),
            ChordStep(degree=4, name="v", function=HarmonicFunction.RESOLUTION),
        ],
    ],
}


def select_progression(mode: str, rng: random.Random) -> List[ChordStep]:
    """Select a harmonic chord progression for given mode (v2 compatibility)."""
    options = PROGRESSIONS.get(mode, PROGRESSIONS["minor"])
    return rng.choice(options)


def select_profile_progression(mode: str, profile_name: str, rng: random.Random) -> List[ChordStep]:
    """Select a progression tuned to the profile's emotional and dramatic role."""
    if profile_name == "dungeon":
        if rng.random() < 0.70:
            return rng.choice(PROGRESSIONS["modal_pedal"])
        return rng.choice(PROGRESSIONS.get("minor", PROGRESSIONS["minor"]))
    elif profile_name == "ending":
        if rng.random() < 0.60:
            return rng.choice(PROGRESSIONS.get("mixolydian", PROGRESSIONS["major"]))
        return rng.choice(PROGRESSIONS.get("major", PROGRESSIONS["major"]))
    elif profile_name == "exploration":
        if rng.random() < 0.70:
            return rng.choice(PROGRESSIONS.get("dorian", PROGRESSIONS["minor"]))
        return rng.choice(PROGRESSIONS.get("minor", PROGRESSIONS["minor"]))

    return select_progression(mode, rng)



def get_chord_tones(chord: ChordStep, scale: List[int]) -> List[int]:
    """Return scale degree offsets for the root, third, and fifth of chord."""
    root_idx = chord.degree
    third_idx = (root_idx + 2) % len(scale)
    fifth_idx = (root_idx + 4) % len(scale)
    return [scale[root_idx], scale[third_idx], scale[fifth_idx]]

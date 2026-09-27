"""MusicProfile Architecture and Registry for Composer v3.

Defines the compositional parameter space for distinct Atari game musical styles:
- TITLE: Lyrical, spacious, memorable theme with Intro and definitive Outro
- EXPLORATION: Atmospheric, modal (Dorian/Mixolydian), wide phrases, breathing rests
- ACTION: High-energy (155-185 BPM), driving pulse, syncopation, active bass & percussion
- FUNNY: Whimsical, quirky angular leaps, staccato rests, chromatic touches
- DUNGEON: Ominous, slow (65-90 BPM), pedal drone, minor/Dorian, dark ostinatos
- ENDING: Triumphant fanfare, building energy, climax, definitive final cadence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MusicProfile:
    """Style-driven compositional profile governing the generation space."""
    name: str
    description: str
    tempo_range: Tuple[int, int]
    energy_range: Tuple[float, float]
    density_range: Tuple[float, float]
    allowed_meters: List[str]
    allowed_modes: List[str]
    form_choices: List[str]
    rhythm_family: str
    melodic_archetypes: List[str]
    bass_styles: List[str]
    register: str                 # "low", "mid", "high", "wide"
    novelty_range: Tuple[float, float]
    min_channels: int = 2
    max_channels: int = 4
    has_intro: bool = False
    has_outro: bool = False
    uses_16bit_bass_chance: float = 0.50
    percussion_intensity: str = "medium"  # "none", "sparse", "medium", "heavy"
    target_duration: int = 24             # Target seconds


TITLE_PROFILE = MusicProfile(
    name="title",
    description="Lyrical, memorable title theme with atmospheric Intro and definitive Outro",
    tempo_range=(75, 100),
    energy_range=(0.25, 0.50),
    density_range=(0.25, 0.45),
    allowed_meters=["4/4"],
    allowed_modes=["minor", "major"],
    form_choices=[
        "INTRO A B A OUTRO",
        "A B A OUTRO",
        "INTRO A B A' OUTRO",
    ],
    rhythm_family="lyrical",
    melodic_archetypes=["lyrical", "stepwise", "wave", "question_answer"],
    bass_styles=["soft_pedal", "counter_motion", "sparse_root"],
    register="mid",
    novelty_range=(0.35, 0.55),
    min_channels=3,
    max_channels=4,
    has_intro=True,
    has_outro=True,
    uses_16bit_bass_chance=0.70,
    percussion_intensity="sparse",
    target_duration=24,
)

EXPLORATION_PROFILE = MusicProfile(
    name="exploration",
    description="Atmospheric and melancholic exploration theme with modal harmony and wide phrasing",
    tempo_range=(80, 110),
    energy_range=(0.20, 0.45),
    density_range=(0.20, 0.40),
    allowed_meters=["4/4", "3/4"],
    allowed_modes=["dorian", "minor", "mixolydian"],
    form_choices=[
        "A B A C",
        "A B C A",
        "A B A' C",
    ],
    rhythm_family="sparse",
    melodic_archetypes=["modal", "wave", "ascending", "wide_arch"],
    bass_styles=["walking", "counter_motion", "pedal_drone"],
    register="wide",
    novelty_range=(0.40, 0.65),
    min_channels=2,
    max_channels=4,
    has_intro=False,
    has_outro=False,
    uses_16bit_bass_chance=0.80,
    percussion_intensity="none",
    target_duration=26,
)

ACTION_PROFILE = MusicProfile(
    name="action",
    description="Fast, driving arcade combat theme with high syncopation and aggressive rhythm",
    tempo_range=(155, 185),
    energy_range=(0.75, 0.95),
    density_range=(0.60, 0.85),
    allowed_meters=["4/4"],
    allowed_modes=["minor", "dorian"],
    form_choices=[
        "INTRO A B A B",
        "A B A B",
        "INTRO A B A' B",
    ],
    rhythm_family="driving",
    melodic_archetypes=["driving", "angular", "arpeggiated", "syncopated"],
    bass_styles=["driving_pulse", "ostinato", "octave_hits", "counter_motion"],
    register="mid",
    novelty_range=(0.45, 0.70),
    min_channels=3,
    max_channels=4,
    has_intro=True,
    has_outro=False,
    uses_16bit_bass_chance=0.30,
    percussion_intensity="heavy",
    target_duration=22,
)

FUNNY_PROFILE = MusicProfile(
    name="funny",
    description="Quirky, comic theme with playful angular leaps, syncopated stops, and whimsical phrasing",
    tempo_range=(105, 140),
    energy_range=(0.45, 0.70),
    density_range=(0.40, 0.65),
    allowed_meters=["4/4"],
    allowed_modes=["major", "mixolydian", "pentatonic"],
    form_choices=[
        "A A' B A",
        "A B A' C",
        "A A' B A OUTRO",
    ],
    rhythm_family="playful",
    melodic_archetypes=["angular", "playful_leaps", "staccato", "wave"],
    bass_styles=["bouncy_staccato", "walking", "counter_motion"],
    register="high",
    novelty_range=(0.50, 0.75),
    min_channels=2,
    max_channels=4,
    has_intro=False,
    has_outro=False,
    uses_16bit_bass_chance=0.20,
    percussion_intensity="sparse",
    target_duration=22,
)

DUNGEON_PROFILE = MusicProfile(
    name="dungeon",
    description="Dark, ominous dungeon theme with low pedal drone, minor/Dorian ostinatos, and sparse tension",
    tempo_range=(65, 90),
    energy_range=(0.15, 0.35),
    density_range=(0.15, 0.35),
    allowed_meters=["4/4"],
    allowed_modes=["minor", "dorian"],
    form_choices=[
        "INTRO A A' B A",
        "A A' B A",
        "INTRO A B A",
    ],
    rhythm_family="ostinato",
    melodic_archetypes=["repetitive", "descending", "ostinato", "drone_anchor"],
    bass_styles=["pedal_drone", "dark_ostinato", "sparse_low"],
    register="low",
    novelty_range=(0.30, 0.55),
    min_channels=2,
    max_channels=3,
    has_intro=True,
    has_outro=False,
    uses_16bit_bass_chance=0.95,
    percussion_intensity="none",
    target_duration=28,
)

ENDING_PROFILE = MusicProfile(
    name="ending",
    description="Triumphant victory fanfare with building culmination and definitive resolution",
    tempo_range=(100, 140),
    energy_range=(0.60, 0.90),
    density_range=(0.45, 0.70),
    allowed_meters=["4/4"],
    allowed_modes=["major", "mixolydian"],
    form_choices=[
        "INTRO A B C OUTRO",
        "INTRO A B OUTRO",
        "A B C OUTRO",
    ],
    rhythm_family="march",
    melodic_archetypes=["fanfare", "ascending", "lyrical_climax", "arpeggiated"],
    bass_styles=["fanfare_bass", "driving_pulse", "counter_motion"],
    register="wide",
    novelty_range=(0.35, 0.60),
    min_channels=3,
    max_channels=4,
    has_intro=True,
    has_outro=True,
    uses_16bit_bass_chance=0.50,
    percussion_intensity="medium",
    target_duration=24,
)

PROFILES: Dict[str, MusicProfile] = {
    "title": TITLE_PROFILE,
    "exploration": EXPLORATION_PROFILE,
    "action": ACTION_PROFILE,
    "funny": FUNNY_PROFILE,
    "dungeon": DUNGEON_PROFILE,
    "ending": ENDING_PROFILE,
}


def get_profile(name_or_profile: str | MusicProfile) -> MusicProfile:
    """Retrieve MusicProfile by name or pass through existing instance."""
    if isinstance(name_or_profile, MusicProfile):
        return name_or_profile
    key = str(name_or_profile).strip().lower()
    if key not in PROFILES:
        valid_keys = ", ".join(PROFILES.keys())
        raise KeyError(f"Unknown music profile '{name_or_profile}'. Available profiles: {valid_keys}")
    return PROFILES[key]

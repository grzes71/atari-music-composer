"""Enriched Symbolic Music IR (Intermediate Representation) for Composer v2.

Completely independent of hardware POKEY registers:
- Tempo, Key, Mode/Scale, Meter
- Harmonic grammar (Chord Progressions, Harmonic Functions: TONIC, PREDOMINANT, DOMINANT, RESOLUTION)
- Melodic Contour (UP, DOWN, ARCH, ASCENDING, DESCENDING, WAVE, QUESTION_ANSWER)
- Interval Grammar (relative intervals decoupled from absolute pitches)
- Channel roles (melody, bass, harmony, rhythm, percussion)
- Patterns, Tracks, Notes, and Sequence Form
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from atari_music.constants import NOTE_NAMES


class HarmonicFunction(str, Enum):
    TONIC = "TONIC"
    PREDOMINANT = "PREDOMINANT"
    DOMINANT = "DOMINANT"
    RESOLUTION = "RESOLUTION"


class MelodicContour(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    ARCH = "ARCH"
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"
    WAVE = "WAVE"
    QUESTION_ANSWER = "QUESTION_ANSWER"


class ChannelRole(str, Enum):
    MELODY = "melody"
    BASS = "bass"
    HARMONY = "harmony"
    RHYTHM = "rhythm"
    PERCUSSION = "percussion"


class ChordStep(BaseModel):
    """A chord in a progression with scale degree and harmonic function."""
    degree: int  # 0 = tonic (I), 3/4 = IV, 4 = V, 5 = vi, etc.
    name: str    # e.g. "i", "VI", "III", "VII" or "I", "IV", "V"
    function: HarmonicFunction = HarmonicFunction.TONIC
    duration_bars: int = 1


class SymbolicNote(BaseModel):
    """Symbolic musical note event."""
    pitch: Optional[int] = None       # MIDI pitch number (e.g. 60 = C-4), None for rest
    pitch_name: Optional[str] = None  # e.g. "C-4"
    duration: int = 2                 # Duration in tracker rows (e.g. 2 rows = 8th note)
    velocity: int = 15                # 0..15 volume
    role: ChannelRole = ChannelRole.MELODY
    is_rest: bool = False
    is_chord_tone: bool = True
    interval_from_prev: int = 0       # Delta semitones from previous note


class MusicPhrase(BaseModel):
    """A musical phrase containing interval grammar and relative motion."""
    id: str = "A"                     # e.g. "A", "A'", "A''", "B"
    contour: MelodicContour = MelodicContour.WAVE
    intervals: List[int] = Field(default_factory=list)      # Relative interval sequence, e.g. [+2, +2, +1, -3]
    rhythm: List[int] = Field(default_factory=list)         # Duration sequence in rows
    notes: List[SymbolicNote] = Field(default_factory=list) # Concrete notes after harmonic realization


class SymbolicTrack(BaseModel):
    """Single channel track within a pattern."""
    channel_idx: int                  # 1..4
    role: ChannelRole = ChannelRole.MELODY
    notes: List[SymbolicNote] = Field(default_factory=list)


class SymbolicPattern(BaseModel):
    """Pattern composed of symbolic tracks."""
    id: int
    name: str = ""
    rows: int = 32
    tracks: Dict[int, SymbolicTrack] = Field(default_factory=dict)


class MusicSong(BaseModel):
    """Top-Level Music IR independent of hardware synthesis."""
    title: str
    tempo_bpm: int = 130
    meter: str = "4/4"
    key: str = "C"
    mode: str = "minor"
    progression: List[ChordStep] = Field(default_factory=list)
    form: str = "A B A B"             # e.g. "A A B A", "A B A B", "A A B B"
    phrases: Dict[str, MusicPhrase] = Field(default_factory=dict)
    patterns: List[SymbolicPattern] = Field(default_factory=list)
    sequence: List[int] = Field(default_factory=list)
    min_channels: int = 2
    max_channels: int = 4
    novelty: float = 0.50
    style: str = "atari_1980s"

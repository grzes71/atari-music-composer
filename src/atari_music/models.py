"""Data models for Atari 8-bit POKEY Music Analysis Dataset."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class RawDumpMeta(BaseModel):
    """Metadata for raw POKEY dump."""
    song_file: str
    subsong_index: int
    author: Optional[str] = None
    title: Optional[str] = None
    date: Optional[str] = None
    sap_type: Optional[str] = None
    declared_duration: str
    duration_ms: float
    is_looping: bool
    loop_start_ms: Optional[float] = None
    loop_end_ms: Optional[float] = None
    is_stereo: bool
    playback_rate_hz: float
    fastplay_scanlines: Optional[int] = None
    total_frames: int
    features_detected: List[str] = Field(default_factory=list)


class PokeyEvent(BaseModel):
    """Discrete POKEY register modification event (Layer 2)."""
    frame: int
    time_ms: float
    pokey: int = Field(description="POKEY index: 0 for left/mono, 1 for right stereo")
    reg_name: str = Field(alias="register", serialization_alias="register", description="Register name, e.g. AUDF1, AUDC2, AUDCTL")
    old: int = Field(description="Previous 8-bit value (0-255)")
    new: int = Field(description="New 8-bit value (0-255)")


class ChannelVoiceState(BaseModel):
    """Instantaneous state and musical interpretation of a single POKEY channel."""
    channel: int = Field(description="Channel index (1 to 4)")
    pokey: int = Field(description="POKEY index: 0 or 1")
    audf: int
    audc: int
    volume: int = Field(description="Volume level (0 to 15)")
    distortion: int = Field(description="Distortion byte (0x00..0xE0)")
    volume_only: bool = Field(description="True if AUDC bit 4 is set (DAC mode)")
    is_active: bool = Field(description="True if volume > 0")
    
    # Measured / Inferred Musical Attributes
    frequency_hz: Optional[float] = None
    frequency_confidence: float = 0.0
    note: Optional[str] = None
    note_confidence: float = 0.0
    midi_pitch: Optional[float] = None
    cents_deviation: Optional[float] = None
    is_16bit_high: bool = False
    is_noise: bool = False


class FrameSnapshot(BaseModel):
    """Full POKEY state at a given frame."""
    frame: int
    time_ms: float
    audctl0: int
    audctl1: Optional[int] = None
    voices: List[ChannelVoiceState]
    active_voices_count: int


class MusicalFeaturesSummary(BaseModel):
    """High-level musical and technical feature summary of a piece."""
    channels_used_count: int
    max_simultaneous_voices: int
    distortions_used: List[int]
    audctl_values_used: List[int]
    
    uses_16bit: bool
    uses_15khz: bool
    uses_179mhz: bool
    uses_highpass: bool
    uses_9bit_poly: bool
    uses_ultrasound: bool
    uses_volume_only_digi: bool
    fast_audc_change_count: int

    unique_frequencies_count: int
    pitch_range_semitones: Optional[float] = None
    lowest_note: Optional[str] = None
    highest_note: Optional[str] = None
    most_frequent_notes: List[Tuple[str, int]] = Field(default_factory=list)
    step_vs_leap_ratio: Optional[float] = None

    estimated_tempo_bpm: Optional[float] = None
    tempo_confidence: float = 0.0


class RepetitionAndMemory(BaseModel):
    """Analysis of pattern repetition, formal structure, and memory footprint."""
    music_category: str = Field(
        description="Categorization: standard_melody, percussion_noise, digi_sample, hybrid, stereo"
    )
    flags: List[str] = Field(default_factory=list)
    
    unique_patterns_count: int
    total_bars_detected: int
    repetition_ratio: float
    repeating_motif_lengths: List[int] = Field(default_factory=list)
    detected_form: Optional[str] = None

    # Memory Footprint
    raw_sap_bytes: int
    event_stream_bytes: int
    deduplicated_pattern_bytes: int
    estimated_atari_player_ram_bytes: int


class DatasetRecord(BaseModel):
    """Unified record in dataset.jsonl describing one song/subsong."""
    id: str = Field(description="Unique song identifier, e.g. Composer_Name__SongTitle__sub0")
    meta: RawDumpMeta
    features: MusicalFeaturesSummary
    analysis: RepetitionAndMemory
    raw_dump_path: str
    events_path: str

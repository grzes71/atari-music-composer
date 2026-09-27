"""Public Music Generation API for Atari POKEY Music Engine.

This module provides the stable, decoupled high-level facade:
Application / CLI
       ↓
Music Generation API (generate_music)
       ↓
Composer v4 Engine
       ↓
Music IR
       ↓
POKEY IR
       ↓
WAV / Future Atari 6502 Exporter

Enforces strict parameter validation, seed determinism, and seamless export data.
"""

from __future__ import annotations

import logging
from pathlib import Path
import random
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


from atari_music.composer_v4 import (
    ComposerV4QualityReport,
    ComposerV4Result,
    compose_song_v4,
)
from atari_music.ir import IRSong, compile_ir_to_pokey_frames
from atari_music.music_ir import MusicSong
from atari_music.pokey_synth import render_pokey_to_wav
from atari_music.profiles import PROFILES, get_profile

VALID_PROFILES = tuple(PROFILES.keys())  # ("title", "exploration", "action", "funny", "dungeon", "ending")
VALID_ROOT_KEYS = (
    "C", "C#", "DB",
    "D", "D#", "EB",
    "E",
    "F", "F#", "GB",
    "G", "G#", "AB",
    "A", "A#", "BB",
    "B",
)
VALID_LENGTH_CHOICES = ("short", "medium", "long")


class MusicGenerationMetadata(BaseModel):
    """Rich metadata describing the generated composition and export parameters."""
    profile: str
    seed: int
    tempo: int
    key: str
    mode: str
    duration: float
    channels_used: int
    form: str
    memory_size_bytes: int
    pattern_count: int
    sequence_length: int
    frames_per_tick: int
    uses_16bit_bass: bool
    length_intent: Optional[str] = None
    intensity_intent: Optional[float] = None
    variation_intent: Optional[float] = None


class MusicGenerationResult(BaseModel):
    """Complete, self-contained output of the music generation pipeline.
    
    Contains both the high-level symbolic Music IR and hardware-compiled POKEY IR,
    along with technical quality metrics and metadata for downstream tools (WAV render, Atari exporter).
    """
    music_ir: MusicSong
    pokey_ir: IRSong
    metadata: MusicGenerationMetadata
    quality_report: ComposerV4QualityReport

    def render_wav(self, output_path: str | Path, sample_rate: int = 44100) -> Path:
        """Render the generated POKEY composition directly to a standard PCM WAV audio file."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        frames = compile_ir_to_pokey_frames(self.pokey_ir)
        render_pokey_to_wav(frames, out_p, sample_rate=sample_rate)
        return out_p

    def save_json(self, output_path: str | Path) -> Path:
        """Export the POKEY IR to a JSON file."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        self.pokey_ir.to_json_file(out_p)
        return out_p


def generate_music(
    profile: str = "action",
    seed: int = 1234,
    key: Optional[str] = None,
    tempo: Optional[int] = None,
    length: Optional[str] = None,
    intensity: Optional[float] = None,
    variation: Optional[float] = None,
    uses_16bit_bass: Optional[bool] = None,
) -> MusicGenerationResult:
    """Public Music Generation API.
    
    Parameters
    ----------
    profile : str, default="action"
        Compositional archetype determining mood, rhythm, and genre.
        Supported profiles: "title", "exploration", "action", "funny", "dungeon", "ending".
    seed : int, default=1234
        Deterministic RNG seed. Identical parameters and seed guarantee bitwise-identical output.
    key : Optional[str], default=None
        Root musical key (e.g. "C", "D", "E", "F", "G", "A", "B"). If None, chosen by profile rules.
    tempo : Optional[int], default=None
        Target tempo in BPM (between 50 and 240 BPM). If None, chosen within profile tempo bounds.
    length : Optional[str], default=None
        High-level duration intent: "short" (~15s), "medium" (~24s), or "long" (~34s).
    intensity : Optional[float], default=None
        Expected intensity/density between 0.0 (subdued) and 1.0 (driving/culminating).
    variation : Optional[float], default=None
        Degree of motivic and interval variation within the profile between 0.0 (conservative)
        and 1.0 (highly adventurous).
        
    Returns
    -------
    MusicGenerationResult
        Self-contained result bundle with Music IR, POKEY IR, metadata, and quality report.
    """
    # 1. Validation
    # Profile
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("Profile must be a non-empty string.")
    norm_profile = profile.strip().lower()
    if norm_profile not in VALID_PROFILES:
        valid_str = ", ".join(VALID_PROFILES)
        raise ValueError(f"Unknown music profile '{profile}'. Supported profiles: {valid_str}")

    # Seed
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"Seed must be an integer, got {seed!r}")

    # Key
    norm_key: Optional[str] = None
    if key is not None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Key must be a non-empty string or None.")
        norm_key = key.strip().upper()
        if norm_key not in VALID_ROOT_KEYS:
            raise ValueError(
                f"Invalid musical key '{key}'. Supported root keys: C, D, E, F, G, A, B (with optional # or b)"
            )
        # Canonical normalization (e.g. DB -> C#)
        key_map = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}
        norm_key = key_map.get(norm_key, norm_key)

    # Tempo
    if tempo is not None:
        if not isinstance(tempo, int) or isinstance(tempo, bool):
            raise ValueError(f"Tempo must be an integer, got {tempo!r}")
        if tempo < 50 or tempo > 240:
            raise ValueError(
                f"Tempo {tempo} BPM is outside allowable POKEY musical bounds (50 to 240 BPM)."
            )

    # Length
    target_duration: Optional[int] = None
    norm_length: Optional[str] = None
    if length is not None:
        if not isinstance(length, str) or not length.strip():
            raise ValueError("Length must be a string ('short', 'medium', 'long') or None.")
        norm_length = length.strip().lower()
        if norm_length not in VALID_LENGTH_CHOICES:
            raise ValueError(
                f"Invalid length '{length}'. Allowed choices: {', '.join(VALID_LENGTH_CHOICES)}"
            )

        prof_obj = get_profile(norm_profile)
        base_dur = prof_obj.target_duration
        if norm_length == "short":
            target_duration = max(14, int(round(base_dur * 0.70)))
        elif norm_length == "long":
            target_duration = min(42, int(round(base_dur * 1.35)))
        else:  # medium
            target_duration = base_dur

    # Intensity
    if intensity is not None:
        if not isinstance(intensity, (int, float)):
            raise ValueError(f"Intensity must be a float between 0.0 and 1.0, got {intensity!r}")
        if intensity < 0.0 or intensity > 1.0:
            raise ValueError(f"Intensity {intensity} is outside valid range [0.0, 1.0].")

    # Variation
    if variation is not None:
        if not isinstance(variation, (int, float)):
            raise ValueError(f"Variation must be a float between 0.0 and 1.0, got {variation!r}")
        if variation < 0.0 or variation > 1.0:
            raise ValueError(f"Variation {variation} is outside valid range [0.0, 1.0].")

    # 16-bit bass resolution (defaults to False to guarantee 4 independent channels unless explicitly enabled)
    actual_16bit = bool(uses_16bit_bass) if uses_16bit_bass is not None else False

    # 2. Invoke Composer v4 Engine
    v4_res: ComposerV4Result = compose_song_v4(
        profile=norm_profile,
        seed=seed,
        tempo=tempo,
        key=norm_key,
        novelty=variation,
        duration=target_duration,
        uses_16bit_bass=actual_16bit,
    )

    q = v4_res.quality_report

    # 3. Assemble Metadata
    metadata = MusicGenerationMetadata(
        profile=norm_profile,
        seed=seed,
        tempo=q.tempo,
        key=v4_res.music_ir.key,
        mode=v4_res.music_ir.mode,
        duration=q.duration,
        channels_used=q.channels_used,
        form=q.form,
        memory_size_bytes=q.memory_size,
        pattern_count=q.pattern_count,
        sequence_length=len(v4_res.pokey_ir.sequence),
        frames_per_tick=v4_res.pokey_ir.frames_per_tick,
        uses_16bit_bass=v4_res.pokey_ir.uses_16bit_bass,
        length_intent=norm_length,
        intensity_intent=intensity,
        variation_intent=variation,
    )

    return MusicGenerationResult(
        music_ir=v4_res.music_ir,
        pokey_ir=v4_res.pokey_ir,
        metadata=metadata,
        quality_report=q,
    )

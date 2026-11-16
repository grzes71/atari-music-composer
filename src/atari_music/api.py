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
from typing import Any, Dict, List, Mapping, Optional, Sequence
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
    format_version: int = 1
    length_intent: Optional[str] = None
    intensity_intent: Optional[float] = None
    variation_intent: Optional[float] = None
    #: Provenance of any bound POKEY sound profiles (one entry per bound instrument).
    #: Empty for every composition that was not rendered with a profile binding, which
    #: is the default. Recorded here because a profile is a rendering-time dependency:
    #: the composition does not name it, so the result must say which one realized it.
    sound_profiles: List[Dict[str, Any]] = Field(default_factory=list)


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
        from atari_music.ir import song_requires_v2

        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if song_requires_v2(self.pokey_ir):
            from atari_music.frame_simulator import simulate_ir_song_frames
            frames = simulate_ir_song_frames(self.pokey_ir, format_version=2)
        else:
            frames = compile_ir_to_pokey_frames(self.pokey_ir)
        render_pokey_to_wav(frames, out_p, sample_rate=sample_rate)
        return out_p

    def save_json(self, output_path: str | Path) -> Path:
        """Export the POKEY IR to a JSON file."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        self.pokey_ir.to_json_file(out_p)
        return out_p

    def export_mads(
        self,
        output_path: Optional[str | Path] = None,
        *,
        song_label: str = "song_data",
        player_version: str = "auto",
    ) -> str:
        """Export this result to MADS assembly using v1 or v2 format resolution."""
        from atari_music.instruments.planner import resolve_export_format_version
        from atari_music.mads_exporter import export_mads_asm

        fmt = resolve_export_format_version(self.pokey_ir, player_version)
        return export_mads_asm(self, output_path, song_label=song_label, format_version=fmt)

    def build_xex(
        self,
        output_path: str | Path,
        *,
        player_address: str | int = 0x6000,
        music_address: Optional[str | int] = 0x8000,
        zp_base: int = 0x80,
        mads_bin: Optional[str | Path] = None,
        player_asm: Optional[str | Path] = None,
        player_version: str = "auto",
        keep_asm: bool = True,
    ) -> Path:
        """Compile this result to a relocatable Atari XEX binary via the shared MADS pipeline."""
        from atari_music.ai.client import build_xex_from_result

        return build_xex_from_result(
            self,
            output_path=output_path,
            player_address=player_address,
            music_address=music_address,
            zp_base=zp_base,
            mads_bin=mads_bin,
            player_asm=player_asm,
            player_version=player_version,
            keep_asm=keep_asm,
        )


def generate_music(
    profile: str = "action",
    seed: int = 1234,
    key: Optional[str] = None,
    tempo: Optional[int] = None,
    length: Optional[str] = None,
    intensity: Optional[float] = None,
    variation: Optional[float] = None,
    uses_16bit_bass: Optional[bool] = None,
    channel_instruments: Optional[Mapping[int | str, str]] = None,
    program_changes: Optional[Sequence[Mapping[str, Any] | Any]] = None,
    instrument_catalog_path: Optional[Path] = None,
    player_version: str = "auto",
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
        channel_instruments=channel_instruments,
        program_changes=program_changes,
        instrument_catalog_path=instrument_catalog_path,
        player_version=player_version,
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
        format_version=q.format_version,
        length_intent=norm_length,
        intensity_intent=intensity,
        variation_intent=variation,
        sound_profiles=list(v4_res.sound_profiles),
    )

    return MusicGenerationResult(
        music_ir=v4_res.music_ir,
        pokey_ir=v4_res.pokey_ir,
        metadata=metadata,
        quality_report=q,
    )


def _load_song_input_for_arrange(
    input_song: Any,
) -> tuple[IRSong, MusicSong, Optional[str]]:
    """Load an existing AI composition or POKEY IR without ever invoking an AI provider."""
    import json

    if isinstance(input_song, MusicGenerationResult):
        return (
            input_song.pokey_ir.model_copy(deep=True),
            input_song.music_ir.model_copy(deep=True),
            input_song.metadata.profile,
        )
    if isinstance(input_song, IRSong):
        ms = MusicSong(
            title=input_song.title,
            tempo_bpm=input_song.tempo_bpm,
            key=input_song.key,
            mode=input_song.mode,
            sequence=list(input_song.sequence),
        )
        return input_song.model_copy(deep=True), ms, None

    from atari_music.ai.client import generate_music_from_composition, load_composition_json
    from atari_music.ai.schema import AICompositionDoc

    if isinstance(input_song, AICompositionDoc):
        res = generate_music_from_composition(input_song)
        return res.pokey_ir, res.music_ir, res.metadata.profile

    data: Optional[Dict[str, Any]] = None
    if isinstance(input_song, (Path, str)):
        p = Path(input_song) if isinstance(input_song, Path) or (len(str(input_song)) < 512 and Path(str(input_song)).is_file()) else None
        raw_text = p.read_text(encoding="utf-8") if p is not None else str(input_song)
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as err:
            raise ValueError(f"failed to parse composition JSON: {err}") from err
        if isinstance(parsed, dict):
            data = parsed
        else:
            raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
    elif isinstance(input_song, Mapping):
        data = dict(input_song)
    else:
        raise TypeError(
            f"unsupported input_song type {type(input_song).__name__}; expected IRSong, MusicGenerationResult, AICompositionDoc, dict, or JSON path"
        )

    if data.get("format") == "atari-music-composition":
        doc = load_composition_json(data)
        res = generate_music_from_composition(doc)
        return res.pokey_ir, res.music_ir, res.metadata.profile

    ir_song = IRSong.model_validate(data)
    ms = MusicSong(
        title=ir_song.title,
        tempo_bpm=ir_song.tempo_bpm,
        key=ir_song.key,
        mode=ir_song.mode,
        sequence=list(ir_song.sequence),
    )
    return ir_song, ms, None


def arrange_song(
    input_song: Any,
    channel_instruments: Optional[Mapping[int | str, str]] = None,
    *,
    program_change_policy: str = "preserve",
    instrument_catalog_path: Optional[Path | str] = None,
    player_version: str = "auto",
) -> MusicGenerationResult:
    """Arrange an existing composition with new POKEY catalog instruments without calling AI.

    Supports AI Composition JSON (``atari-music-composition``), POKEY IR JSON (``IRSong``),
    :class:`IRSong`, or :class:`MusicGenerationResult`. Returns a new :class:`MusicGenerationResult`
    compatible with ``render_wav()``, ``export_mads_asm()``, ``export_mads()``, and ``build_xex()``
    while keeping *input_song* and all musical events (notes, rests, durations, tempo, patterns,
    sequence) immutable.
    """
    from atari_music.instruments.planner import (
        arrange_ir_song,
        resolve_export_format_version,
    )
    from atari_music.ir import calculate_ir_binary_size, song_requires_v2
    import numpy as np

    base_ir, music_ir, style_hint = _load_song_input_for_arrange(input_song)
    cat_path = Path(instrument_catalog_path) if instrument_catalog_path is not None else None
    arranged_ir, _rt_report = arrange_ir_song(
        base_ir,
        channel_instruments=channel_instruments,
        program_change_policy=program_change_policy,
        catalog_path=cat_path,
        player_version=player_version,
    )

    export_ver = resolve_export_format_version(arranged_ir, player_version)
    mem_size = calculate_ir_binary_size(arranged_ir, format_version=export_ver)
    if song_requires_v2(arranged_ir):
        from atari_music.frame_simulator import simulate_ir_song_frames
        frames = simulate_ir_song_frames(arranged_ir, format_version=2)
    else:
        frames = compile_ir_to_pokey_frames(arranged_ir)

    total_frames = int(frames.shape[0])
    duration_s = round(float(total_frames) / 50.0, 2)

    active_channels = 0
    active_pct: Dict[int, float] = {}
    for ch in range(1, 5):
        audc_col = (ch - 1) * 2 + 1
        active_f = int(np.count_nonzero((frames[:, audc_col] & 0x0F) > 0)) if total_frames > 0 else 0
        pct = round((active_f / total_frames) * 100.0, 1) if total_frames > 0 else 0.0
        active_pct[ch] = pct
        if pct > 0:
            active_channels += 1

    sound_profiles_meta = [
        {
            "ir_instrument_id": inst.id,
            "instrument_id": inst.profile_id,
            "display_name": inst.name,
            "behavior_id": inst.behavior_id,
            "profile_fingerprint": inst.profile_fingerprint,
        }
        for inst in arranged_ir.instruments
        if inst.profile_id is not None
    ]

    metadata = MusicGenerationMetadata(
        profile=style_hint or music_ir.style or "arranged",
        seed=0,
        tempo=arranged_ir.tempo_bpm,
        key=arranged_ir.key,
        mode=arranged_ir.mode,
        duration=duration_s,
        channels_used=max(1, sum(1 for ch in range(1, 5) if any(pat.tracks.get(ch) for pat in arranged_ir.patterns))),
        form=" ".join(str(x) for x in arranged_ir.sequence),
        memory_size_bytes=mem_size,
        pattern_count=len(arranged_ir.patterns),
        sequence_length=len(arranged_ir.sequence),
        frames_per_tick=arranged_ir.frames_per_tick,
        uses_16bit_bass=arranged_ir.uses_16bit_bass,
        format_version=export_ver,
        sound_profiles=sound_profiles_meta,
    )

    quality = ComposerV4QualityReport(
        profile_name=metadata.profile,
        memory_size=mem_size,
        under_budget=(mem_size <= 2048),
        channels_used=metadata.channels_used,
        active_channels_audio=active_channels,
        duration=duration_s,
        tempo=arranged_ir.tempo_bpm,
        form=metadata.form,
        pitch_range=0,
        repetition=0.0,
        novelty=0.0,
        melodic_density=0.0,
        rhythmic_density=0.0,
        harmonic_complexity=0.0,
        pattern_count=len(arranged_ir.patterns),
        attempts_needed=1,
        format_version=export_ver,
        active_frame_pct=active_pct,
    )

    return MusicGenerationResult(
        music_ir=music_ir,
        pokey_ir=arranged_ir,
        metadata=metadata,
        quality_report=quality,
    )

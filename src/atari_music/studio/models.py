"""Data models for Atari Music Composer Studio (PySide6-free)."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atari_music.ai.schema import AICompositionDoc
from atari_music.instruments.planner import PlayerVersionChoice, ProgramChangePolicy
from atari_music.instruments.runtime import RuntimeDiagnostic
from atari_music.ir import IRSong
from atari_music.music_ir import MusicSong

StudioTargetName = Literal["xex_v2", "xex_v1", "wav"]


class CompositionFidelityError(ValueError):
    """Raised when loading or compiling a composition would silently drop playback data."""


class ChannelAnalysis(BaseModel):
    """Immutable musical summary extracted for one POKEY channel (1..4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: int = Field(ge=1, le=4)
    note_count: int = Field(ge=0)
    active: bool
    role: str
    initial_instrument_name: str
    original_instrument_names: Tuple[str, ...] = ()
    midi_min: Optional[int] = None
    midi_max: Optional[int] = None
    avg_duration: float = 0.0
    has_program_changes: bool = False
    program_change_count: int = 0
    distinct_instruments_count: int = 0


class StudioArrangementConfig(BaseModel):
    """Immutable working arrangement configuration edited by Studio controls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel_instruments: Dict[int, Optional[str]] = Field(
        default_factory=lambda: {1: None, 2: None, 3: None, 4: None}
    )
    program_change_policy: ProgramChangePolicy = "preserve"
    player_version: PlayerVersionChoice = "auto"
    target_backend: StudioTargetName = "xex_v2"

    @field_validator("channel_instruments")
    @classmethod
    def _normalize_channels(
        cls, value: Dict[int, Optional[str]]
    ) -> Dict[int, Optional[str]]:
        out: Dict[int, Optional[str]] = {1: None, 2: None, 3: None, 4: None}
        for raw_ch, inst_id in value.items():
            ch = int(raw_ch)
            if ch not in (1, 2, 3, 4):
                raise ValueError(f"channel key must be 1..4, got {raw_ch!r}")
            norm = inst_id.strip() if isinstance(inst_id, str) and inst_id.strip() else None
            out[ch] = norm
        return out

    def with_channel(
        self, channel: int, instrument_id: Optional[str]
    ) -> "StudioArrangementConfig":
        """Return a new config with *channel* updated without mutating self."""
        if channel not in (1, 2, 3, 4):
            raise ValueError(f"channel must be 1..4, got {channel!r}")
        updated = dict(self.channel_instruments)
        updated[channel] = instrument_id
        return self.model_copy(update={"channel_instruments": updated})

    def assigned_map(self) -> Dict[int, str]:
        """Return only channels explicitly overridden with a catalog instrument."""
        return {
            ch: inst_id
            for ch in (1, 2, 3, 4)
            if (inst_id := self.channel_instruments.get(ch)) is not None
        }


class LoadedCompositionState(BaseModel):
    """Immutable snapshot of a loaded composition and its compiled baseline POKEY IR."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: Optional[Path] = None
    source_kind: Literal["ai-composition", "dsl", "pokey-ir"]
    source_ai_doc: Optional[AICompositionDoc] = None
    base_pokey_ir: IRSong
    base_music_ir: MusicSong
    base_ir_sha256: str
    musical_fingerprint: str
    title: str
    author: str
    key: str
    mode: str
    tempo_bpm: int
    pattern_count: int
    sequence_length: int
    frames_per_tick: int
    base_uses_16bit_bass: bool
    base_v1_compatible: bool
    base_v2_reasons: Tuple[str, ...] = ()
    channels: Dict[int, ChannelAnalysis]
    baseline_config: StudioArrangementConfig = Field(
        default_factory=StudioArrangementConfig
    )


@dataclass(frozen=True)
class CatalogOptionStatus:
    """Catalog instrument metadata plus compatibility status for one channel."""

    instrument_id: str
    display_name: str
    family: str
    intended_roles: Tuple[str, ...]
    base_distortion: int
    divider_mode: str
    preferred_clock_hz: Optional[str]
    channels_allowed: Tuple[int, ...]
    midi_range: Tuple[int, int]
    behavior_id: Optional[str]
    tier: str
    compatible: bool
    status: str
    reason: Optional[str] = None
    midi_warning: Optional[str] = None


@dataclass(frozen=True)
class ChannelSlotEvaluation:
    """Availability, effective label, and catalog compatibility for one channel."""

    channel: int
    available_for_assignment: bool
    lock_reason: Optional[str]
    effective_instrument_label: str
    effective_is_16bit: bool
    options: Tuple[CatalogOptionStatus, ...] = ()
    diagnostics: Tuple[RuntimeDiagnostic, ...] = ()


@dataclass(frozen=True)
class ArrangementEvaluation:
    """Complete compatibility evaluation for a candidate StudioArrangementConfig."""

    is_valid: bool
    effective_format_version: Optional[int]
    effective_uses_16bit_bass: bool
    effective_audctl: int
    v2_reasons: Tuple[str, ...]
    channels: Dict[int, ChannelSlotEvaluation]
    diagnostics: Tuple[RuntimeDiagnostic, ...] = ()
    blocking_errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderCacheKey:
    """Deterministic identity covering every parameter affecting rendered WAV audio."""

    base_ir_sha256: str
    assigned_channels: Tuple[Tuple[int, str], ...]
    program_change_policy: ProgramChangePolicy
    player_version: PlayerVersionChoice
    sample_rate: int
    catalog_digest: str

    def digest(self) -> str:
        """Compute canonical SHA-256 cache key string."""
        payload = {
            "base_ir_sha256": self.base_ir_sha256,
            "assigned_channels": [[ch, iid] for ch, iid in sorted(self.assigned_channels)],
            "program_change_policy": self.program_change_policy,
            "player_version": self.player_version,
            "sample_rate": int(self.sample_rate),
            "catalog_digest": self.catalog_digest,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CachedRenderEntry:
    """Rendered WAV preview metadata stored in session cache."""

    cache_key: str
    wav_path: Path
    duration_seconds: float
    format_version: int
    uses_16bit_bass: bool
    memory_size_bytes: int
    config: StudioArrangementConfig
    arranged_ir_sha256: str
    from_cache: bool = False
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)

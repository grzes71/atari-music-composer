"""Data models for Atari Music Composer Studio (PySide6-free)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atari_music.ai.schema import AICompositionDoc
from atari_music.instruments.planner import PlayerVersionChoice, ProgramChangePolicy
from atari_music.instruments.runtime import RuntimeDiagnostic
from atari_music.ir import IRSong
from atari_music.music_ir import MusicSong

StudioTargetName = Literal["xex_v2", "xex_v1", "wav"]
VariantSlot = Literal["A", "B"]
VariantRenderStatus = Literal["empty", "not_rendered", "ready", "outdated"]
PRESET_SCHEMA_ID = "atari-music/arrangement-preset/1"


def parse_atari_address(raw: str | int | bool, *, label: str = "address") -> int:
    """Parse user-entered hex (``$6000``, ``0x6000``) or decimal address into ``0..$FFFF``.

    This is purely syntactic integer conversion; XEX segment boundaries and overlaps are
    validated authoritatively by ``atari_music.xex_layout.validate_xex_layout``.
    """
    if isinstance(raw, bool):
        raise ValueError(f"Invalid {label}: boolean is not a valid address.")
    if isinstance(raw, int):
        val = int(raw)
    else:
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{label} cannot be empty.")
        try:
            if text.startswith("$"):
                val = int(text[1:], 16)
            elif text.lower().startswith("0x"):
                val = int(text, 16)
            else:
                val = int(text, 10)
        except ValueError as exc:
            raise ValueError(
                f"Invalid {label} {raw!r}; expected hex ($6000 / 0x6000) or decimal integer."
            ) from exc

    if val < 0 or val > 0xFFFF:
        raise ValueError(f"{label} ${val:X} out of 16-bit 6502 address range ($0000-$FFFF).")
    return val


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


class XexExportOptions(BaseModel):
    """Immutable export parameters for compiling a Studio arrangement to Atari XEX.

    ``player_address`` and ``music_address`` undergo 16-bit integer parsing only here; memory
    region bounds (``$0400-$BFFF``) and overlaps are judged authoritatively on built segments by
    ``atari_music.xex_layout.validate_xex_layout``. ``zp_base`` is checked against ``$80-$F2``
    because ``PLAYER_ZP_BASE`` (+0..13) is a compile-time equate not present as a load segment.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_path: Path
    player_address: int = Field(default=0x6000, ge=0x0000, le=0xFFFF)
    music_address: Optional[int] = Field(default=0x8000, ge=0x0000, le=0xFFFF)
    zp_base: int = Field(default=0x80, ge=0x80, le=0xF2)
    keep_asm: bool = True
    keep_arrangement_json: bool = True
    mads_bin: Optional[Path] = None
    player_asm: Optional[Path] = None

    @field_validator("player_address", mode="before")
    @classmethod
    def _parse_player_addr(cls, value: str | int | bool) -> int:
        return parse_atari_address(value, label="player_address")

    @field_validator("music_address", mode="before")
    @classmethod
    def _parse_music_addr(cls, value: Optional[str | int | bool]) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return parse_atari_address(value, label="music_address")

    @field_validator("zp_base", mode="before")
    @classmethod
    def _parse_zp_base(cls, value: str | int | bool) -> int:
        val = parse_atari_address(value, label="zp_base")
        if val < 0x80 or val > 0xF2:
            raise ValueError(
                f"zp_base ${val:02X} out of safe user Zero Page bounds ($80-$F2; "
                "player+harness uses 14 bytes PLAYER_ZP_BASE+0..13 within $80-$FF)."
            )
        return val

    @model_validator(mode="after")
    def _validate_paths(self) -> "XexExportOptions":
        if not str(self.output_path).strip():
            raise ValueError("output_path cannot be empty.")
        return self


@dataclass(frozen=True)
class ToolchainPaths:
    """Resolved MADS toolchain paths and preflight availability diagnostics."""

    mads_bin: Optional[Path]
    player_asm: Optional[Path]
    mads_error: Optional[str] = None
    player_asm_error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return (
            self.mads_bin is not None
            and self.player_asm is not None
            and self.mads_error is None
            and self.player_asm_error is None
        )


@dataclass(frozen=True)
class XexExportResult:
    """Metadata produced after successful MADS compilation and atomic XEX commit."""

    xex_path: Path
    asm_path: Optional[Path]
    size_bytes: int
    format_version: int
    uses_16bit_bass: bool
    effective_audctl: int
    player_address: int
    music_address: Optional[int]
    zp_base: int
    segments: Tuple[Tuple[int, int, str], ...]
    warnings: Tuple[str, ...] = ()
    arrangement_json_path: Optional[Path] = None


class ArrangementPreset(BaseModel):
    """Persistent Studio arrangement preset (schema ``atari-music/arrangement-preset/1``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["atari-music/arrangement-preset/1"] = PRESET_SCHEMA_ID
    name: str
    description: Optional[str] = Field(default=None, max_length=500)
    arrangement: StudioArrangementConfig = Field(default_factory=StudioArrangementConfig)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Preset name must be a string.")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Preset name cannot be empty.")
        if len(cleaned) > 80:
            raise ValueError("Preset name cannot exceed 80 characters.")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
            raise ValueError("Preset name cannot contain control characters.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Preset description must be a string.")
        cleaned = value.strip()
        if not cleaned:
            return None
        if any((ord(ch) < 32 and ch not in ("\n", "\r", "\t")) or ord(ch) == 127 for ch in cleaned):
            raise ValueError("Preset description cannot contain control characters.")
        return cleaned


@dataclass(frozen=True)
class PresetRecord:
    """Validated arrangement preset paired with its storage identity and file path."""

    preset_id: str
    path: Path
    preset: ArrangementPreset


@dataclass(frozen=True)
class PresetScanIssue:
    """Diagnostic record for a malformed or unsupported preset file in storage."""

    path: Path
    code: str
    message: str


@dataclass(frozen=True)
class PresetScanResult:
    """Result of scanning a presets directory without failing on individual bad files."""

    presets: Tuple[PresetRecord, ...] = ()
    errors: Tuple[PresetScanIssue, ...] = ()


@dataclass(frozen=True)
class PresetApplyResult:
    """Result of explicitly applying an ``ArrangementPreset`` to Studio state."""

    preset: ArrangementPreset
    config: StudioArrangementConfig
    evaluation: ArrangementEvaluation


@dataclass(frozen=True)
class ComparisonVariant:
    """Immutable snapshot of one A/B comparison arrangement slot."""

    slot: VariantSlot
    config: StudioArrangementConfig
    label: str = "Editor"
    rendered_entry: Optional[CachedRenderEntry] = None


@dataclass(frozen=True)
class ComparisonSlotStatus:
    """Resolved status summary for one A/B comparison slot."""

    slot: VariantSlot
    render_status: VariantRenderStatus
    variant: Optional[ComparisonVariant] = None
    active_listen: bool = False
    matches_editor: bool = False
    is_valid_arrangement: Optional[bool] = None
    blocking_errors: Tuple[str, ...] = ()

    @property
    def can_listen(self) -> bool:
        return self.render_status == "ready" and self.variant is not None and self.variant.rendered_entry is not None

    @property
    def can_render(self) -> bool:
        return self.variant is not None and self.is_valid_arrangement is True

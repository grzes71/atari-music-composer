"""Pydantic v2 data models for the Stage A instrument and behavior architecture."""

from __future__ import annotations

from typing import Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atari_music.constants import AUDCTL_JOIN_1_2_16BIT, AUDCTL_JOIN_3_4_16BIT

InstrumentFamily = Literal["lead", "bass", "pad", "harmony", "percussion", "fx"]
DividerMode = Literal["8bit", "16bit_ch12", "16bit_ch34"]
ClockMode = Literal["64khz", "15khz", "1.79mhz"]
WaveformFamily = Literal[
    "pure",
    "poly4",
    "poly5",
    "poly5_4",
    "poly17_noise",
    "poly9_noise",
    "hpf_pair",
]
RuntimeTier = Literal[
    "core_v1",
    "core_v2_iter1",
    "core_v2_iter2",
    "experimental_deferred",
    "wav_only",
]
ModulationMode = Literal["none", "octave_pulse"]
SourceKind = Literal["curated_preset", "sound_profile_bank", "sound_design_demo"]
ChannelRoleName = Literal["melody", "bass", "harmony", "rhythm", "percussion"]

_VALID_ID_PATTERN = r"^[a-z][a-z0-9_]*$"
_ALL_JOIN_AUDCTL_BITS = AUDCTL_JOIN_1_2_16BIT | AUDCTL_JOIN_3_4_16BIT
_DIVIDER_JOIN_MASK: Dict[DividerMode, int] = {
    "8bit": 0,
    "16bit_ch12": AUDCTL_JOIN_1_2_16BIT,
    "16bit_ch34": AUDCTL_JOIN_3_4_16BIT,
}


def _validate_audc_distortion_nibble(value: int) -> int:
    """Validate upper POKEY AUDC generator bits ($00..$E0 without volume/DAC-only bits)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("distortion nibble must be an integer")
    if value < 0x00 or value > 0xE0 or (value & 0x1F) != 0:
        raise ValueError(
            f"invalid POKEY distortion nibble 0x{value:02x}: "
            "expected one of $00, $20, $40, $60, $80, $A0, $C0, $E0"
        )
    return value


class EnvelopeSpec(BaseModel):
    """Static linear 4-phase POKEY ADSR parameters matching player.asm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attack_frames: int = Field(ge=0, le=255)
    decay_frames: int = Field(ge=0, le=255)
    sustain_vol: int = Field(ge=0, le=15)
    release_frames: int = Field(ge=0, le=255)
    peak_vol: int = Field(default=15, ge=1, le=15)


class HardwareConstraints(BaseModel):
    """Separation of advisory clock preference from hard POKEY hardware constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    divider_mode: DividerMode = "8bit"
    preferred_clock_hz: Optional[ClockMode] = None
    required_audctl_bits: int = Field(default=0, ge=0, le=255)
    forbidden_audctl_bits: int = Field(default=0, ge=0, le=255)
    poly4_safe_tuning: bool = False
    midi_range: Tuple[int, int] = (24, 108)
    channels_allowed: Tuple[int, ...] = (1, 2, 3, 4)

    @field_validator("midi_range")
    @classmethod
    def _validate_midi_range(cls, value: Tuple[int, int]) -> Tuple[int, int]:
        low, high = value
        if low < 0 or high > 127 or low > high:
            raise ValueError(
                f"invalid midi_range {value!r}: expected 0 <= low <= high <= 127"
            )
        return value

    @field_validator("channels_allowed")
    @classmethod
    def _validate_channels_allowed(cls, value: Tuple[int, ...]) -> Tuple[int, ...]:
        if not value:
            raise ValueError("channels_allowed must not be empty")
        if any(ch < 1 or ch > 4 for ch in value):
            raise ValueError(f"channels_allowed must contain only 1..4, got {value!r}")
        if len(set(value)) != len(value):
            raise ValueError(f"channels_allowed contains duplicates: {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_constraints(self) -> "HardwareConstraints":
        if self.required_audctl_bits & self.forbidden_audctl_bits:
            raise ValueError(
                "required_audctl_bits and forbidden_audctl_bits must be disjoint"
            )
        expected_join = _DIVIDER_JOIN_MASK[self.divider_mode]
        actual_join = self.required_audctl_bits & _ALL_JOIN_AUDCTL_BITS
        if actual_join != expected_join:
            raise ValueError(
                f"divider_mode={self.divider_mode!r} requires exact AUDCTL join bits "
                f"0x{expected_join:02x}, got 0x{actual_join:02x} in required_audctl_bits=0x{self.required_audctl_bits:02x}"
            )
        if self.divider_mode == "16bit_ch12" and 1 not in self.channels_allowed:
            raise ValueError("16bit_ch12 divider_mode requires channel 1 in channels_allowed")
        if self.divider_mode == "16bit_ch34" and 3 not in self.channels_allowed:
            raise ValueError("16bit_ch34 divider_mode requires channel 3 in channels_allowed")
        return self


class TransientMacroStep(BaseModel):
    """Single frame-timed step inside a compact note-start transient or percussion macro."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_frames: int = Field(ge=1, le=255)
    distortion_nibble: Optional[int] = None
    audf_offset: int = Field(default=0, ge=-127, le=127)
    fixed_audf: Optional[int] = Field(default=None, ge=0, le=0xFE)
    volume: Optional[int] = Field(default=None, ge=0, le=15)

    @field_validator("distortion_nibble")
    @classmethod
    def _validate_distortion(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return _validate_audc_distortion_nibble(value)

    @model_validator(mode="after")
    def _validate_pitch_mode(self) -> "TransientMacroStep":
        if self.fixed_audf is not None and self.audf_offset != 0:
            raise ValueError("TransientMacroStep cannot set both fixed_audf and non-zero audf_offset")
        return self


class TransientMacroSpec(BaseModel):
    """Short note-onset transient or percussion macro bounded to 8 steps for 6502 ROM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    steps: Tuple[TransientMacroStep, ...] = Field(min_length=1, max_length=8)
    loop: bool = False


class PitchEnvelopeSpec(BaseModel):
    """Short initial divider deviation for scoop, sub-punch, or drum pitch drop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_audf_delta: int = Field(ge=-127, le=127)
    duration_frames: int = Field(ge=0, le=15)
    step_delta: int = Field(ge=-16, le=16)


class VibratoSpec(BaseModel):
    """Declarative delayed vibrato parameters (deferred to second v2 iteration)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delay_frames: int = Field(ge=0, le=63)
    depth_audf: int = Field(ge=0, le=7)
    rate_frames: int = Field(ge=1, le=15)


class InstrumentProvenance(BaseModel):
    """Origin and audit verification metadata; bank links must carry real ID and SHA-256."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: SourceKind
    profile_id: Optional[str] = None
    profile_fingerprint: Optional[str] = None
    validation_status: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_provenance(self) -> "InstrumentProvenance":
        if self.source_kind == "sound_profile_bank":
            if not self.profile_id or not self.profile_fingerprint:
                raise ValueError(
                    "sound_profile_bank provenance requires non-empty profile_id and profile_fingerprint"
                )
        elif self.profile_fingerprint and not self.profile_id:
            raise ValueError("profile_fingerprint requires profile_id")
        if self.profile_fingerprint is not None:
            fp = self.profile_fingerprint.lower()
            if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
                raise ValueError("profile_fingerprint must be a 64-character lowercase SHA-256 hex digest")
        return self


class InstrumentBehavior(BaseModel):
    """Time-domain performance behavior specification independent of static timbre profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    behavior_id: str = Field(min_length=1, pattern=_VALID_ID_PATTERN)
    version: int = Field(default=1, ge=1)
    required_runtime_tier: RuntimeTier
    transient_macro: Optional[TransientMacroSpec] = None
    pitch_envelope: Optional[PitchEnvelopeSpec] = None
    vibrato: Optional[VibratoSpec] = None
    modulation_mode: ModulationMode = "none"
    arpeggio_offsets: Tuple[int, ...] = Field(default=(), max_length=4)
    uses_hpf_xor: bool = False
    uses_wav_only_contour: bool = False
    allow_per_note_switch: bool = False

    @field_validator("arpeggio_offsets")
    @classmethod
    def _validate_arpeggio(cls, value: Tuple[int, ...]) -> Tuple[int, ...]:
        if any(offset < -24 or offset > 24 for offset in value):
            raise ValueError(f"arpeggio_offsets must be in -24..24 semitones, got {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_tier_alignment(self) -> "InstrumentBehavior":
        if self.uses_wav_only_contour and self.required_runtime_tier != "wav_only":
            raise ValueError("uses_wav_only_contour requires required_runtime_tier='wav_only'")
        if (self.arpeggio_offsets or self.uses_hpf_xor) and self.required_runtime_tier not in (
            "experimental_deferred",
            "wav_only",
        ):
            raise ValueError(
                "arpeggio_offsets and uses_hpf_xor must use required_runtime_tier='experimental_deferred' or 'wav_only'"
            )
        if self.vibrato is not None and self.required_runtime_tier in ("core_v1", "core_v2_iter1"):
            raise ValueError("vibrato is deferred past iter1 and cannot target core_v1 or core_v2_iter1")
        if (
            self.transient_macro is not None
            or self.pitch_envelope is not None
            or self.allow_per_note_switch
        ) and self.required_runtime_tier == "core_v1":
            raise ValueError(
                "transient_macro, pitch_envelope, and allow_per_note_switch cannot target core_v1"
            )
        return self


PerformanceSpec = InstrumentBehavior


class InstrumentProfile(BaseModel):
    """Static POKEY instrument definition validated independently from its behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str = Field(min_length=1, pattern=_VALID_ID_PATTERN)
    display_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    family: InstrumentFamily
    intended_roles: Tuple[ChannelRoleName, ...] = Field(min_length=1)
    base_distortion: int
    envelope: EnvelopeSpec
    waveform_family: WaveformFamily
    hardware_constraints: HardwareConstraints
    behavior_id: Optional[str] = None
    provenance: InstrumentProvenance

    @field_validator("base_distortion")
    @classmethod
    def _validate_base_distortion(cls, value: int) -> int:
        return _validate_audc_distortion_nibble(value)

    @field_validator("intended_roles")
    @classmethod
    def _validate_roles(cls, value: Tuple[ChannelRoleName, ...]) -> Tuple[ChannelRoleName, ...]:
        if len(set(value)) != len(value):
            raise ValueError(f"intended_roles contains duplicate entries: {value!r}")
        return value


class InstrumentCatalogDocument(BaseModel):
    """Root JSON schema for versioned SSOT instrument catalogs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["atari-music/instrument-catalog/1"]
    catalog_version: str = Field(min_length=1)
    behaviors: Tuple[InstrumentBehavior, ...] = ()
    instruments: Tuple[InstrumentProfile, ...] = Field(min_length=1)

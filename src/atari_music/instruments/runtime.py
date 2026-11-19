"""Stateless POKEY capability validator and AUDCTL conflict resolver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Literal, Optional, Sequence, Tuple

from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_CH1_179MHZ,
    AUDCTL_CH3_179MHZ,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
)
from atari_music.instruments.catalog import CatalogError, InstrumentCatalog
from atari_music.instruments.models import (
    InstrumentBehavior,
    InstrumentProfile,
    RuntimeTier,
)

BackendKind = Literal["wav", "asap", "xex_v1", "xex_v2"]
CompatibilityStatus = Literal[
    "FULL_HARDWARE_V1",
    "FULL_HARDWARE_V2_ITER1",
    "DEFERRED_FEATURE",
    "WAV_PREVIEW_ONLY",
    "BLOCKED_CONFLICT",
]

_VALID_TIERS: FrozenSet[RuntimeTier] = frozenset(
    {"core_v1", "core_v2_iter1", "core_v2_iter2", "experimental_deferred", "wav_only"}
)
_HPF_AUDCTL_MASK = AUDCTL_HIPASS_CH2_CH4 | AUDCTL_HIPASS_CH1_CH3


class InvalidTargetCapabilityError(ValueError):
    """Raised when (backend, song_format_version, enabled_tiers, is_implemented) is inconsistent."""


@dataclass(frozen=True)
class TargetCapability:
    """Explicit capability contract for a backend without heuristic auto-promotion."""

    backend: BackendKind
    song_format_version: Literal[1, 2]
    enabled_tiers: FrozenSet[RuntimeTier]
    max_instruments_per_song: int = 32
    is_implemented: bool = True
    allow_fallback: bool = False

    def __post_init__(self) -> None:
        _validate_target_capability(self)


def _validate_target_capability(target: TargetCapability) -> None:
    if target.song_format_version not in (1, 2):
        raise InvalidTargetCapabilityError(
            f"unsupported song_format_version {target.song_format_version!r}; expected 1 or 2"
        )
    if target.max_instruments_per_song < 1:
        raise InvalidTargetCapabilityError(
            f"max_instruments_per_song must be >= 1, got {target.max_instruments_per_song}"
        )
    if not target.enabled_tiers or not (target.enabled_tiers <= _VALID_TIERS):
        raise InvalidTargetCapabilityError(
            f"enabled_tiers must be a non-empty subset of {_VALID_TIERS!r}, got {target.enabled_tiers!r}"
        )

    if target.backend == "xex_v1":
        if target.song_format_version != 1:
            raise InvalidTargetCapabilityError("backend 'xex_v1' requires song_format_version == 1")
        if not (target.enabled_tiers <= {"core_v1"}):
            raise InvalidTargetCapabilityError(
                f"backend 'xex_v1' allows only 'core_v1', got {sorted(target.enabled_tiers)!r}"
            )
    elif target.backend == "xex_v2":
        if target.song_format_version != 2:
            raise InvalidTargetCapabilityError("backend 'xex_v2' requires song_format_version == 2")
        if not (target.enabled_tiers <= {"core_v1", "core_v2_iter1"}):
            raise InvalidTargetCapabilityError(
                f"backend 'xex_v2' Iter 1 allows only core_v1/core_v2_iter1, got {sorted(target.enabled_tiers)!r}"
            )
    elif target.backend == "asap":
        if target.is_implemented:
            raise InvalidTargetCapabilityError(
                "CORE pipeline has no built-in SAP exporter; backend 'asap' requires is_implemented=False"
            )
        allowed = {"core_v1"} if target.song_format_version == 1 else {"core_v1", "core_v2_iter1"}
        if not (target.enabled_tiers <= allowed):
            raise InvalidTargetCapabilityError(
                f"backend 'asap' with song_format_version={target.song_format_version} allows only "
                f"{sorted(allowed)!r}, got {sorted(target.enabled_tiers)!r}"
            )
    elif target.backend == "wav":
        allowed_wav = (
            {"core_v1", "wav_only"}
            if target.song_format_version == 1
            else {"core_v1", "core_v2_iter1", "wav_only"}
        )
        if not (target.enabled_tiers <= allowed_wav):
            raise InvalidTargetCapabilityError(
                f"backend 'wav' with song_format_version={target.song_format_version} allows only "
                f"{sorted(allowed_wav)!r}, got {sorted(target.enabled_tiers)!r}"
            )
    else:
        raise InvalidTargetCapabilityError(f"unknown backend {target.backend!r}")


TARGET_V1_XEX = TargetCapability(
    backend="xex_v1",
    song_format_version=1,
    enabled_tiers=frozenset({"core_v1"}),
    is_implemented=True,
)
TARGET_V2_ITER1_XEX = TargetCapability(
    backend="xex_v2",
    song_format_version=2,
    enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
    is_implemented=True,
)
TARGET_WAV_V1_PREVIEW = TargetCapability(
    backend="wav",
    song_format_version=1,
    enabled_tiers=frozenset({"core_v1", "wav_only"}),
    is_implemented=True,
)
TARGET_WAV_PREVIEW = TargetCapability(
    backend="wav",
    song_format_version=2,
    enabled_tiers=frozenset({"core_v1", "core_v2_iter1", "wav_only"}),
    is_implemented=True,
)
TARGET_SAP_V1_PLANNED = TargetCapability(
    backend="asap",
    song_format_version=1,
    enabled_tiers=frozenset({"core_v1"}),
    is_implemented=False,
)
TARGET_SAP_V2_ITER1_PLANNED = TargetCapability(
    backend="asap",
    song_format_version=2,
    enabled_tiers=frozenset({"core_v1", "core_v2_iter1"}),
    is_implemented=False,
)


@dataclass(frozen=True)
class ChannelAssignmentRequest:
    """Immutable request binding one or more catalog instruments to POKEY channel 1..4."""

    channel: int
    instrument_ids: Tuple[str, ...]
    midi_min: Optional[int] = None
    midi_max: Optional[int] = None


@dataclass(frozen=True)
class RuntimeDiagnostic:
    """Single non-mutating diagnostic produced by POKEYRuntime."""

    severity: Literal["ERROR", "WARNING"]
    code: str
    message: str
    channel: Optional[int] = None
    instrument_id: Optional[str] = None


@dataclass(frozen=True)
class RuntimeResolutionReport:
    """Deterministic compatibility and AUDCTL resolution report."""

    status: CompatibilityStatus
    is_compatible: bool
    effective_audctl: int
    unique_instrument_ids: Tuple[str, ...]
    diagnostics: Tuple[RuntimeDiagnostic, ...]
    target_implemented: bool


def _implied_divider_bits(profile: InstrumentProfile) -> int:
    mode = profile.hardware_constraints.divider_mode
    if mode == "16bit_ch12":
        return AUDCTL_JOIN_1_2_16BIT
    if mode == "16bit_ch34":
        return AUDCTL_JOIN_3_4_16BIT
    return 0


def _evaluate_profile_constraints(
    channel: Optional[int],
    profile: InstrumentProfile,
    midi_min: Optional[int],
    midi_max: Optional[int],
) -> List[RuntimeDiagnostic]:
    """Validate static profile hardware constraints cleanly separated from behavior."""
    diags: List[RuntimeDiagnostic] = []
    hc = profile.hardware_constraints

    if hc.divider_mode == "16bit_ch34":
        diags.append(
            RuntimeDiagnostic(
                severity="ERROR",
                code="UNRESOLVED_HARDWARE_POLICY",
                message=(
                    f"profile {profile.instrument_id!r} requests 16-bit CH3+CH4 ($08), "
                    "which is outside Stage A/C Iter 1 scope"
                ),
                channel=channel,
                instrument_id=profile.instrument_id,
            )
        )

    if hc.required_audctl_bits & _HPF_AUDCTL_MASK:
        diags.append(
            RuntimeDiagnostic(
                severity="ERROR",
                code="DEFERRED_FEATURE",
                message=(
                    f"profile {profile.instrument_id!r} requires HPF XOR AUDCTL bits "
                    f"0x{hc.required_audctl_bits & _HPF_AUDCTL_MASK:02x}, which are deferred past v2 Iter 1"
                ),
                channel=channel,
                instrument_id=profile.instrument_id,
            )
        )

    if channel is not None:
        if channel not in hc.channels_allowed:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="CHANNEL_NOT_ALLOWED",
                    message=(
                        f"profile {profile.instrument_id!r} allows channels {hc.channels_allowed}, "
                        f"cannot bind to channel {channel}"
                    ),
                    channel=channel,
                    instrument_id=profile.instrument_id,
                )
            )
        if hc.divider_mode == "16bit_ch12" and channel != 1:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="PAIR_16BIT_CHANNEL_CONFLICT",
                    message=(
                        f"profile {profile.instrument_id!r} uses 16-bit CH1+CH2 pair and must be bound to channel 1"
                    ),
                    channel=channel,
                    instrument_id=profile.instrument_id,
                )
            )
        if (hc.required_audctl_bits & AUDCTL_CH1_179MHZ) and channel != 1:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="CHANNEL_NOT_ALLOWED",
                    message=(
                        f"profile {profile.instrument_id!r} requires AUDCTL CH1 1.79 MHz ($40) "
                        f"which is only available on channel 1, got channel {channel}"
                    ),
                    channel=channel,
                    instrument_id=profile.instrument_id,
                )
            )
        if (hc.required_audctl_bits & AUDCTL_CH3_179MHZ) and channel != 3:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="CHANNEL_NOT_ALLOWED",
                    message=(
                        f"profile {profile.instrument_id!r} requires AUDCTL CH3 1.79 MHz ($20) "
                        f"which is only available on channel 3, got channel {channel}"
                    ),
                    channel=channel,
                    instrument_id=profile.instrument_id,
                )
            )

    if midi_min is not None and midi_max is not None and midi_min > midi_max:
        diags.append(
            RuntimeDiagnostic(
                severity="ERROR",
                code="INVALID_MIDI_RANGE",
                message=f"requested midi_min ({midi_min}) exceeds midi_max ({midi_max})",
                channel=channel,
                instrument_id=profile.instrument_id,
            )
        )
    else:
        low, high = hc.midi_range
        if (midi_min is not None and midi_min < low) or (midi_max is not None and midi_max > high):
            diags.append(
                RuntimeDiagnostic(
                    severity="WARNING",
                    code="MIDI_RANGE_EXCEEDED",
                    message=(
                        f"requested MIDI span ({midi_min}..{midi_max}) exceeds profile {profile.instrument_id!r} "
                        f"recommended range {low}..{high}"
                    ),
                    channel=channel,
                    instrument_id=profile.instrument_id,
                )
            )
    return diags


def _evaluate_behavior_constraints(
    channel: Optional[int],
    profile: InstrumentProfile,
    behavior: Optional[InstrumentBehavior],
    target: TargetCapability,
) -> List[RuntimeDiagnostic]:
    """Validate behavior tier and pairing against target independently of static profile."""
    if behavior is None:
        return []

    diags: List[RuntimeDiagnostic] = []
    if behavior.required_runtime_tier not in target.enabled_tiers:
        code = (
            "WAV_ONLY_NOT_EXPORTABLE"
            if behavior.required_runtime_tier == "wav_only"
            else "BEHAVIOR_NOT_IN_TARGET_TIER"
        )
        diags.append(
            RuntimeDiagnostic(
                severity="ERROR",
                code=code,
                message=(
                    f"profile {profile.instrument_id!r} uses behavior {behavior.behavior_id!r} "
                    f"(tier {behavior.required_runtime_tier!r}) which is not enabled by backend "
                    f"{target.backend!r} v{target.song_format_version}"
                ),
                channel=channel,
                instrument_id=profile.instrument_id,
            )
        )

    if (
        behavior.modulation_mode == "octave_pulse"
        and profile.hardware_constraints.divider_mode in ("16bit_ch12", "16bit_ch34")
    ):
        diags.append(
            RuntimeDiagnostic(
                severity="ERROR",
                code="PAIR_16BIT_CHANNEL_CONFLICT",
                message=(
                    f"octave_pulse modulation in {behavior.behavior_id!r} cannot be used on 16-bit pair "
                    f"for profile {profile.instrument_id!r}"
                ),
                channel=channel,
                instrument_id=profile.instrument_id,
            )
        )
    return diags


def _status_from_results(
    *,
    has_error: bool,
    diags: Sequence[RuntimeDiagnostic],
    tiers_used: FrozenSet[RuntimeTier],
    has_multi_instrument_channel: bool,
) -> CompatibilityStatus:
    codes = {d.code for d in diags if d.severity == "ERROR"}
    if has_error:
        if codes == {"WAV_ONLY_NOT_EXPORTABLE"}:
            return "WAV_PREVIEW_ONLY"
        if codes <= {"BEHAVIOR_NOT_IN_TARGET_TIER", "DEFERRED_FEATURE", "UNRESOLVED_HARDWARE_POLICY"}:
            return "DEFERRED_FEATURE"
        return "BLOCKED_CONFLICT"
    if "wav_only" in tiers_used:
        return "WAV_PREVIEW_ONLY"
    if "core_v2_iter1" in tiers_used or has_multi_instrument_channel:
        return "FULL_HARDWARE_V2_ITER1"
    return "FULL_HARDWARE_V1"


class POKEYRuntime:
    """Stateless hardware/backend capability validator and AUDCTL conflict resolver."""

    @staticmethod
    def check_profile(
        profile: InstrumentProfile,
        behavior: Optional[InstrumentBehavior],
        target: TargetCapability,
        *,
        channel: Optional[int] = None,
    ) -> Tuple[CompatibilityStatus, Tuple[RuntimeDiagnostic, ...]]:
        _validate_target_capability(target)
        diags: List[RuntimeDiagnostic] = []
        if not target.is_implemented:
            diags.append(
                RuntimeDiagnostic(
                    severity="WARNING",
                    code="TARGET_NOT_IMPLEMENTED",
                    message=(
                        f"target backend {target.backend!r} (v{target.song_format_version}) is a planning "
                        "contract and is not yet implemented in the CORE pipeline"
                    ),
                )
            )
        diags.extend(_evaluate_profile_constraints(channel, profile, None, None))
        diags.extend(_evaluate_behavior_constraints(channel, profile, behavior, target))

        tiers = frozenset({behavior.required_runtime_tier}) if behavior else frozenset({"core_v1"})
        has_error = any(d.severity == "ERROR" for d in diags)
        status = _status_from_results(
            has_error=has_error,
            diags=diags,
            tiers_used=tiers,
            has_multi_instrument_channel=False,
        )
        return status, tuple(diags)

    @staticmethod
    def resolve(
        requests: Sequence[ChannelAssignmentRequest],
        catalog: InstrumentCatalog,
        target: TargetCapability,
    ) -> RuntimeResolutionReport:
        _validate_target_capability(target)
        diags: List[RuntimeDiagnostic] = []

        if not target.is_implemented:
            diags.append(
                RuntimeDiagnostic(
                    severity="WARNING",
                    code="TARGET_NOT_IMPLEMENTED",
                    message=(
                        f"target backend {target.backend!r} (v{target.song_format_version}) is not yet "
                        "implemented for export/execution"
                    ),
                )
            )

        # Step 1: deterministic request validation (no channel auto-rerouting).
        ordered_requests = sorted(requests, key=lambda r: r.channel)
        seen_channels: set[int] = set()
        valid_channel_requests: List[ChannelAssignmentRequest] = []
        for req in ordered_requests:
            if req.channel not in (1, 2, 3, 4):
                diags.append(
                    RuntimeDiagnostic(
                        severity="ERROR",
                        code="CHANNEL_NOT_ALLOWED",
                        message=f"invalid POKEY channel {req.channel}; expected 1..4",
                        channel=req.channel,
                    )
                )
                continue
            if req.channel in seen_channels:
                diags.append(
                    RuntimeDiagnostic(
                        severity="ERROR",
                        code="DUPLICATE_CHANNEL_REQUEST",
                        message=f"duplicate assignment request for channel {req.channel}",
                        channel=req.channel,
                    )
                )
                continue
            seen_channels.add(req.channel)
            if not req.instrument_ids:
                diags.append(
                    RuntimeDiagnostic(
                        severity="ERROR",
                        code="INVALID_CHANNEL_REQUEST",
                        message=f"channel {req.channel} assignment must specify at least one instrument_id",
                        channel=req.channel,
                    )
                )
                continue
            valid_channel_requests.append(req)

        # Step 2: independent profile and behavior validation per channel assignment.
        unique_ids_ordered: List[str] = []
        seen_unique_ids: set[str] = set()
        tiers_used: set[RuntimeTier] = set()
        has_multi_inst_channel = False
        uses_16bit_ch12 = False
        required_audctl = 0
        forbidden_audctl = 0

        for req in valid_channel_requests:
            dedup_chan_ids = tuple(dict.fromkeys(req.instrument_ids))
            if len(dedup_chan_ids) > 1:
                has_multi_inst_channel = True
                if target.song_format_version == 1:
                    diags.append(
                        RuntimeDiagnostic(
                            severity="ERROR",
                            code="MULTI_INSTRUMENT_REQUIRES_V2",
                            message=(
                                f"channel {req.channel} assigns {len(dedup_chan_ids)} instruments "
                                f"{dedup_chan_ids}, but song_format_version=1 allows only 1 per channel"
                            ),
                            channel=req.channel,
                        )
                    )

            for inst_id in req.instrument_ids:
                if inst_id not in seen_unique_ids:
                    seen_unique_ids.add(inst_id)
                    unique_ids_ordered.append(inst_id)
                try:
                    profile, behavior = catalog.resolve_profile_behavior(inst_id)
                except CatalogError as exc:
                    diags.append(
                        RuntimeDiagnostic(
                            severity="ERROR",
                            code="INSTRUMENT_NOT_FOUND",
                            message=str(exc),
                            channel=req.channel,
                            instrument_id=inst_id,
                        )
                    )
                    continue

                diags.extend(
                    _evaluate_profile_constraints(req.channel, profile, req.midi_min, req.midi_max)
                )
                diags.extend(_evaluate_behavior_constraints(req.channel, profile, behavior, target))

                tiers_used.add(behavior.required_runtime_tier if behavior else "core_v1")
                if profile.hardware_constraints.divider_mode == "16bit_ch12":
                    uses_16bit_ch12 = True

                # Step 3: aggregate HARD AUDCTL constraints only (preferred_clock_hz never adds errors/bits).
                required_audctl |= (
                    profile.hardware_constraints.required_audctl_bits
                    | _implied_divider_bits(profile)
                )
                forbidden_audctl |= profile.hardware_constraints.forbidden_audctl_bits

        if len(unique_ids_ordered) > target.max_instruments_per_song:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="INSTRUMENT_LIMIT_EXCEEDED",
                    message=(
                        f"{len(unique_ids_ordered)} unique instruments exceed target limit "
                        f"{target.max_instruments_per_song}"
                    ),
                )
            )

        # Step 4: cross-channel AUDCTL & pair conflict rules.
        if uses_16bit_ch12 and 2 in seen_channels:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="PAIR_16BIT_CHANNEL_CONFLICT",
                    message="channel 2 cannot be assigned independently while channel 1 uses 16-bit CH1+CH2 mode",
                    channel=2,
                )
            )

        conflict_mask = required_audctl & forbidden_audctl
        if conflict_mask & AUDCTL_15KHZ:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="AUDCTL_CLOCK_CONFLICT",
                    message=(
                        "conflicting hard AUDCTL 15 kHz ($01) requirement vs forbidden $01 constraint across tracks"
                    ),
                )
            )
        non_clock_conflicts = conflict_mask & ~AUDCTL_15KHZ
        if non_clock_conflicts:
            diags.append(
                RuntimeDiagnostic(
                    severity="ERROR",
                    code="AUDCTL_BIT_CONFLICT",
                    message=(
                        f"conflicting hard AUDCTL bit mask 0x{non_clock_conflicts:02x} "
                        "(both required and forbidden across assigned profiles)"
                    ),
                )
            )

        # Step 5: strict effective_audctl contract (0 whenever any ERROR occurred).
        has_error = any(d.severity == "ERROR" for d in diags)
        effective_audctl = 0 if has_error else required_audctl
        status = _status_from_results(
            has_error=has_error,
            diags=diags,
            tiers_used=frozenset(tiers_used) if tiers_used else frozenset({"core_v1"}),
            has_multi_instrument_channel=has_multi_inst_channel,
        )
        return RuntimeResolutionReport(
            status=status,
            is_compatible=not has_error,
            effective_audctl=effective_audctl,
            unique_instrument_ids=tuple(unique_ids_ordered),
            diagnostics=tuple(diags),
            target_implemented=target.is_implemented,
        )

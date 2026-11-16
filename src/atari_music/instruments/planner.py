"""Shared CORE instrument assignment, runtime validation, and v1/v2 planning helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atari_music.constants import AUDCTL_JOIN_1_2_16BIT
from atari_music.instruments.catalog import (
    INSTRUMENT_NOT_FOUND,
    CatalogError,
    InstrumentCatalog,
    load_instrument_catalog,
)
from atari_music.instruments.runtime import (
    TARGET_V1_XEX,
    TARGET_V2_ITER1_XEX,
    ChannelAssignmentRequest,
    POKEYRuntime,
    RuntimeDiagnostic,
    RuntimeResolutionReport,
    TargetCapability,
)
from atari_music.ir import IRInstrument, IRSong, song_requires_v2

PlayerVersionChoice = Literal["auto", "v1", "v2"]

#: Role aliases accepted by CLI/API channel assignment parsers.
_ROLE_TO_CHANNEL: Dict[str, int] = {
    "bass": 1,
    "harmony": 2,
    "counter": 2,
    "pad": 2,
    "lead": 3,
    "melody": 3,
    "perc": 4,
    "percussion": 4,
    "drums": 4,
    "rhythm": 4,
}


class InstrumentPlanError(ValueError):
    """Structured configuration/validation error for channel instrument planning."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID_INSTRUMENT_PLAN",
        diagnostics: Tuple[RuntimeDiagnostic, ...] = (),
    ) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.diagnostics = diagnostics


class ProgramChangeSpec(BaseModel):
    """Declarative request to switch instrument on a POKEY channel mid-song."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: int = Field(ge=1, le=4)
    instrument_id: str = Field(min_length=1)
    pattern_index: Optional[int] = Field(default=None, ge=0)
    section: Optional[str] = None
    note_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_target(self) -> "ProgramChangeSpec":
        if self.pattern_index is None and (self.section is None or not self.section.strip()):
            raise ValueError(
                "ProgramChangeSpec requires either pattern_index (>= 0) or non-empty section name"
            )
        return self


@dataclass(frozen=True)
class ResolvedInstrumentPlan:
    """Validated multi-channel catalog assignment ready for Composer/AI/EX export."""

    catalog: InstrumentCatalog
    initial_channel_profiles: Dict[int, str]
    channel_profile_lists: Dict[int, Tuple[str, ...]]
    program_changes: Tuple[ProgramChangeSpec, ...]
    unique_profile_ids: Tuple[str, ...]
    profile_to_ir_index: Dict[str, int]
    ir_instruments: Tuple[IRInstrument, ...]
    effective_audctl: int
    uses_16bit_ch12: bool
    requires_v2: bool
    runtime_report: RuntimeResolutionReport
    sound_profiles_metadata: Tuple[Dict[str, Any], ...]


def parse_channel_identifier(raw_key: Any) -> int:
    """Parse ``1..4``, ``ch1..ch4``, or semantic role name into POKEY channel ``1..4``."""
    text = str(raw_key).strip().lower()
    if text in _ROLE_TO_CHANNEL:
        return _ROLE_TO_CHANNEL[text]
    if text.startswith("ch") and text[2:].isdigit():
        ch = int(text[2:])
    elif text.isdigit():
        ch = int(text)
    else:
        raise InstrumentPlanError(
            f"invalid channel identifier {raw_key!r}; expected 1..4, ch1..ch4, or role "
            f"({', '.join(sorted(_ROLE_TO_CHANNEL))})",
            code="INVALID_CHANNEL_IDENTIFIER",
        )
    if ch < 1 or ch > 4:
        raise InstrumentPlanError(
            f"POKEY channel {ch} out of range 1..4 (from {raw_key!r})",
            code="INVALID_CHANNEL_IDENTIFIER",
        )
    return ch


def parse_channel_instrument_specs(raw_items: Sequence[str]) -> Dict[int, str]:
    """Parse repeatable ``CH=INSTRUMENT_ID`` CLI assignments into ``{channel: profile_id}``."""
    out: Dict[int, str] = {}
    for item in raw_items:
        if "=" not in item:
            raise InstrumentPlanError(
                f"invalid channel assignment {item!r}; expected CH=INSTRUMENT_ID (e.g. 3=lead_attack_bite)",
                code="INVALID_ASSIGNMENT_SYNTAX",
            )
        raw_ch, raw_id = item.split("=", 1)
        ch = parse_channel_identifier(raw_ch)
        inst_id = raw_id.strip()
        if not inst_id:
            raise InstrumentPlanError(
                f"empty instrument_id in {item!r}",
                code="INVALID_ASSIGNMENT_SYNTAX",
            )
        if ch in out:
            raise InstrumentPlanError(
                f"channel {ch} assigned multiple times ({out[ch]!r} and {inst_id!r}); "
                "use --program-change for mid-song switches",
                code="DUPLICATE_CHANNEL_ASSIGNMENT",
            )
        out[ch] = inst_id
    return out


def parse_program_change_specs(raw_items: Sequence[str]) -> Tuple[ProgramChangeSpec, ...]:
    """Parse repeatable ``CH@TARGET[:NOTE_IDX]=INSTRUMENT_ID`` specifications."""
    specs: List[ProgramChangeSpec] = []
    for item in raw_items:
        if "=" not in item or "@" not in item.split("=", 1)[0]:
            raise InstrumentPlanError(
                f"invalid --program-change {item!r}; expected CH@SECTION=INSTRUMENT_ID "
                "or CH@PATTERN_IDX[:NOTE_IDX]=INSTRUMENT_ID (e.g. 3@B=lead_attack_bite or 4@1:2=perc_snare_crisp)",
                code="INVALID_PROGRAM_CHANGE_SYNTAX",
            )
        lhs, raw_id = item.split("=", 1)
        raw_ch, raw_loc = lhs.split("@", 1)
        ch = parse_channel_identifier(raw_ch)
        inst_id = raw_id.strip()
        if not inst_id:
            raise InstrumentPlanError(
                f"empty instrument_id in --program-change {item!r}",
                code="INVALID_PROGRAM_CHANGE_SYNTAX",
            )
        note_idx = 0
        target_part = raw_loc.strip()
        if ":" in target_part:
            target_part, note_s = target_part.split(":", 1)
            if not note_s.strip().isdigit():
                raise InstrumentPlanError(
                    f"invalid note index {note_s!r} in --program-change {item!r}; expected integer >= 0",
                    code="INVALID_PROGRAM_CHANGE_SYNTAX",
                )
            note_idx = int(note_s.strip())
        if target_part.isdigit():
            specs.append(
                ProgramChangeSpec(
                    channel=ch,
                    instrument_id=inst_id,
                    pattern_index=int(target_part),
                    note_index=note_idx,
                )
            )
        else:
            if not target_part:
                raise InstrumentPlanError(
                    f"missing section or pattern index in --program-change {item!r}",
                    code="INVALID_PROGRAM_CHANGE_SYNTAX",
                )
            specs.append(
                ProgramChangeSpec(
                    channel=ch,
                    instrument_id=inst_id,
                    section=target_part,
                    note_index=note_idx,
                )
            )
    return tuple(specs)


def normalize_player_version(player_version: str) -> PlayerVersionChoice:
    """Normalize ``auto|v1|v2|1|2`` into canonical :data:`PlayerVersionChoice`."""
    norm = str(player_version).strip().lower()
    if norm in ("auto",):
        return "auto"
    if norm in ("v1", "1"):
        return "v1"
    if norm in ("v2", "2"):
        return "v2"
    raise InstrumentPlanError(
        f"unsupported player version {player_version!r}; expected 'auto', 'v1', or 'v2'",
        code="INVALID_PLAYER_VERSION",
    )


def resolve_export_format_version(song: IRSong, player_version: str = "auto") -> int:
    """Resolve format version (1 or 2) without ever silently promoting v1-compatible songs."""
    choice = normalize_player_version(player_version)
    if choice == "v1":
        return 1
    if choice == "v2":
        return 2
    return 2 if song_requires_v2(song) else 1


def coerce_program_changes(
    items: Optional[Sequence[Mapping[str, Any] | ProgramChangeSpec]],
) -> Tuple[ProgramChangeSpec, ...]:
    """Validate and normalize arbitrary dict/model program change requests."""
    if not items:
        return ()
    out: List[ProgramChangeSpec] = []
    for item in items:
        if isinstance(item, ProgramChangeSpec):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ProgramChangeSpec.model_validate(item))
        else:
            raise InstrumentPlanError(
                f"invalid program_changes entry {item!r}; expected ProgramChangeSpec or dict",
                code="INVALID_PROGRAM_CHANGE_SYNTAX",
            )
    return tuple(out)


def resolve_channel_instrument_plan(
    channel_instruments: Optional[Mapping[int | str, str]],
    *,
    program_changes: Optional[Sequence[Mapping[str, Any] | ProgramChangeSpec]] = None,
    catalog: Optional[InstrumentCatalog] = None,
    catalog_path: Optional[Path] = None,
    uses_16bit_bass: bool = False,
    player_version: str = "auto",
) -> ResolvedInstrumentPlan:
    """Validate catalog instrument assignments and runtime compatibility for channels 1..4."""
    ver_choice = normalize_player_version(player_version)
    cat = catalog if catalog is not None else load_instrument_catalog(catalog_path)
    pc_specs = coerce_program_changes(program_changes)

    initial_map: Dict[int, str] = {}
    if channel_instruments:
        for raw_ch, raw_id in channel_instruments.items():
            ch = parse_channel_identifier(raw_ch)
            inst_id = str(raw_id).strip()
            if not inst_id:
                raise InstrumentPlanError(
                    f"channel {ch} has empty catalog instrument_id",
                    code="INVALID_ASSIGNMENT_SYNTAX",
                )
            initial_map[ch] = inst_id

    if not initial_map and not pc_specs:
        raise InstrumentPlanError(
            "resolve_channel_instrument_plan requires at least one channel assignment or program_change",
            code="EMPTY_INSTRUMENT_PLAN",
        )

    # Gather per-channel ordered list of catalog instrument IDs
    ch_lists: Dict[int, List[str]] = {ch: ([initial_map[ch]] if ch in initial_map else []) for ch in range(1, 5)}
    for pc in pc_specs:
        if pc.instrument_id not in ch_lists[pc.channel]:
            ch_lists[pc.channel].append(pc.instrument_id)

    # Validate catalog membership upfront (zero instruments outside catalog!)
    resolved_pairs: Dict[str, Tuple[Any, Any]] = {}
    unique_ids: List[str] = []
    for ch in range(1, 5):
        for inst_id in ch_lists[ch]:
            if not cat.has_profile(inst_id):
                available = ", ".join(p.instrument_id for p in cat.instruments)
                raise InstrumentPlanError(
                    f"instrument {inst_id!r} (channel {ch}) not found in catalog (available: {available})",
                    code=INSTRUMENT_NOT_FOUND,
                )
            if inst_id not in resolved_pairs:
                try:
                    resolved_pairs[inst_id] = cat.resolve_profile_behavior(inst_id)
                except CatalogError as exc:
                    raise InstrumentPlanError(str(exc), code=exc.code) from exc
                unique_ids.append(inst_id)

    # Enforce 16-bit bass consistency with explicit uses_16bit_bass flag
    ch1_16bit = False
    for inst_id in ch_lists[1]:
        prof, _beh = resolved_pairs[inst_id]
        if prof.hardware_constraints.divider_mode == "16bit_ch12":
            ch1_16bit = True
    if uses_16bit_bass and 1 in initial_map and not ch1_16bit:
        p1, _ = resolved_pairs[initial_map[1]]
        if p1.hardware_constraints.divider_mode != "16bit_ch12":
            raise InstrumentPlanError(
                f"uses_16bit_bass=True conflicts with 8-bit channel 1 profile {p1.instrument_id!r}; "
                "use a 16-bit CH1+CH2 profile such as 'bass_16bit_pure' or 'bass_16bit_poly5_growl'",
                code="PAIR_16BIT_CHANNEL_CONFLICT",
            )
    if uses_16bit_bass and ch_lists[2]:
        raise InstrumentPlanError(
            "uses_16bit_bass=True claims channel 2 as the 16-bit high-byte slave; "
            "channel 2 cannot carry an independent catalog instrument",
            code="PAIR_16BIT_CHANNEL_CONFLICT",
        )

    # Determine whether any feature requires v2 (behaviors or mid-channel switch)
    has_v2_behavior = False
    for inst_id in unique_ids:
        _prof, beh = resolved_pairs[inst_id]
        if beh is not None and beh.required_runtime_tier != "core_v1":
            has_v2_behavior = True
    has_mid_switch = bool(pc_specs) or any(len(ch_lists[ch]) > 1 for ch in range(1, 5))
    requires_v2 = has_v2_behavior or has_mid_switch or (len(unique_ids) > 4)

    if ver_choice == "v1":
        if has_mid_switch:
            raise InstrumentPlanError(
                "mid-song PROGRAM_CHANGE or multiple instruments per channel require --player-version v2 (or auto)",
                code="PROGRAM_CHANGE_REQUIRES_V2",
            )
        target = TARGET_V1_XEX
    else:
        target = TARGET_V1_XEX if (ver_choice == "auto" and not requires_v2) else TARGET_V2_ITER1_XEX

    requests = [
        ChannelAssignmentRequest(channel=ch, instrument_ids=tuple(ch_lists[ch]))
        for ch in range(1, 5)
        if ch_lists[ch]
    ]
    runtime = POKEYRuntime()
    report = runtime.resolve(requests, cat, target=target)
    if not report.is_compatible:
        err_msgs = "; ".join(
            d.message for d in report.diagnostics if d.severity == "ERROR"
        ) or f"status={report.status}"
        raise InstrumentPlanError(
            err_msgs,
            code=next((d.code for d in report.diagnostics if d.severity == "ERROR"), "RUNTIME_CONFLICT"),
            diagnostics=report.diagnostics,
        )

    # Map unique profile IDs -> consecutive IRInstrument IDs 0..K-1
    ir_instruments: List[IRInstrument] = []
    profile_to_ir_index: Dict[str, int] = {}
    meta: List[Dict[str, Any]] = []
    for idx, inst_id in enumerate(unique_ids):
        prof, beh = resolved_pairs[inst_id]
        ir_inst = IRInstrument.from_catalog_profile(idx, prof, beh)
        ir_instruments.append(ir_inst)
        profile_to_ir_index[inst_id] = idx
        meta.append(
            {
                "ir_instrument_id": idx,
                "instrument_id": prof.instrument_id,
                "display_name": prof.display_name,
                "family": prof.family,
                "behavior_id": prof.behavior_id,
                "required_runtime_tier": beh.required_runtime_tier if beh else "core_v1",
                "profile_fingerprint": prof.provenance.profile_fingerprint,
            }
        )

    effective_audctl = int(report.effective_audctl)
    uses_16bit_ch12 = bool(effective_audctl & AUDCTL_JOIN_1_2_16BIT) or uses_16bit_bass

    return ResolvedInstrumentPlan(
        catalog=cat,
        initial_channel_profiles=initial_map,
        channel_profile_lists={ch: tuple(ch_lists[ch]) for ch in range(1, 5)},
        program_changes=pc_specs,
        unique_profile_ids=tuple(unique_ids),
        profile_to_ir_index=profile_to_ir_index,
        ir_instruments=tuple(ir_instruments),
        effective_audctl=effective_audctl,
        uses_16bit_ch12=uses_16bit_ch12,
        requires_v2=requires_v2,
        runtime_report=report,
        sound_profiles_metadata=tuple(meta),
    )


def build_catalog_summary_for_ai(
    catalog: InstrumentCatalog,
    *,
    target: TargetCapability = TARGET_V2_ITER1_XEX,
) -> Tuple[Dict[str, Any], ...]:
    """Return CORE-compatible catalog profiles for AI prompts & mock selection."""
    runtime = POKEYRuntime()
    rows: List[Dict[str, Any]] = []
    for prof in catalog.instruments:
        ch_def = prof.hardware_constraints.channels_allowed[0]
        report = runtime.resolve(
            [ChannelAssignmentRequest(channel=ch_def, instrument_ids=(prof.instrument_id,))],
            catalog,
            target=target,
        )
        if not report.is_compatible:
            continue
        beh = catalog.get_behavior(prof.behavior_id) if prof.behavior_id else None
        rows.append(
            {
                "instrument_id": prof.instrument_id,
                "display_name": prof.display_name,
                "family": prof.family,
                "intended_roles": prof.intended_roles,
                "channels_allowed": prof.hardware_constraints.channels_allowed,
                "divider_mode": prof.hardware_constraints.divider_mode,
                "behavior_id": prof.behavior_id,
                "tier": beh.required_runtime_tier if beh else "core_v1",
            }
        )
    return tuple(rows)


def select_ai_catalog_instrument_id(
    catalog: InstrumentCatalog,
    character_or_role: str,
    *,
    uses_16bit_bass: bool = False,
    channel: Optional[int] = None,
) -> Optional[str]:
    """Select an existing compatible SSOT catalog profile ID matching semantic AI role/character."""
    text = (character_or_role or "").strip().lower()
    available = {
        row["instrument_id"]: row
        for row in build_catalog_summary_for_ai(catalog, target=TARGET_V2_ITER1_XEX)
    }
    candidates: List[str]
    if "kick" in text or "thud" in text:
        candidates = ["perc_kick_tight", "perc_tom_pitched"]
    elif "tom" in text:
        candidates = ["perc_tom_pitched", "perc_kick_tight"]
    elif "snare" in text or "clap" in text:
        candidates = ["perc_snare_crisp", "perc_hihat_closed"]
    elif any(k in text for k in ("hihat", "hat", "cymbal", "shake", "percussion", "noise", "drum")):
        candidates = ["perc_hihat_closed", "perc_snare_crisp", "perc_kick_tight"]
    elif "bass" in text:
        candidates = (
            ["bass_16bit_pure", "bass_16bit_poly5_growl"]
            if uses_16bit_bass
            else ["bass_poly4_punch", "bass_15khz_pure"]
        )
    elif any(k in text for k in ("dark", "pad", "drone", "harmony", "counter")):
        candidates = ["harmony_soft_square", "lead_pure_sustain"]
    elif any(k in text for k in ("bell", "ornament", "pluck", "high")):
        candidates = ["lead_pure_pluck", "lead_pure_sustain"]
    elif "buzz" in text:
        candidates = ["lead_buzz_steady", "lead_attack_bite"]
    elif "octave" in text or "c1" in text:
        candidates = ["lead_c1_octave_pulse", "lead_attack_bite"]
    else:
        candidates = ["lead_attack_bite", "lead_pure_sustain", "lead_pure_pluck"]

    for cid in candidates:
        info = available.get(cid)
        if info is None:
            continue
        if channel is not None and channel not in info["channels_allowed"]:
            continue
        return cid

    for cid, info in available.items():
        if channel is None or channel in info["channels_allowed"]:
            return cid
    return None

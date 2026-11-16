"""Shared CORE instrument assignment, runtime validation, and v1/v2 planning helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
from atari_music.ir import (
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    resolve_initial_channel_instruments,
    song_requires_v2,
)

PlayerVersionChoice = Literal["auto", "v1", "v2"]
ProgramChangePolicy = Literal["preserve", "replace", "remove"]

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


def normalize_program_change_policy(policy: str) -> ProgramChangePolicy:
    """Validate and normalize ``preserve|replace|remove`` policy names."""
    norm = str(policy).strip().lower()
    if norm == "preserve":
        return "preserve"
    if norm == "replace":
        return "replace"
    if norm == "remove":
        return "remove"
    raise InstrumentPlanError(
        f"unsupported program_change_policy {policy!r}; expected 'preserve', 'replace', or 'remove'",
        code="INVALID_PROGRAM_CHANGE_POLICY",
    )


def composition_musical_fingerprint(song: IRSong) -> str:
    """Compute a SHA-256 hash of instrument-independent musical content in *song*.

    Excludes instrument definitions, channel assignments, distortion bytes,
    ``initial_channel_instruments``, and ``PROGRAM_CHANGE`` commands so two
    arrangements of the same composition yield the exact same hash if and only if
    all notes, rests, durations, volumes, tempo, patterns, and sequence match.
    """
    payload = {
        "tempo_bpm": int(song.tempo_bpm),
        "frames_per_tick": int(song.frames_per_tick),
        "key": song.key,
        "mode": song.mode,
        "sequence": list(song.sequence),
        "patterns": [
            {
                "id": int(pat.id),
                "rows": int(pat.rows),
                "tracks": {
                    str(ch): [
                        {
                            "pitch": n.pitch,
                            "midi_pitch": n.midi_pitch,
                            "duration": int(n.duration),
                            "volume": int(n.volume),
                            "is_rest": bool(n.is_rest),
                            "slide_semitones": int(n.slide_semitones),
                            "arpeggio_offsets": list(n.arpeggio_offsets),
                        }
                        for n in notes
                    ]
                    for ch, notes in sorted(pat.tracks.items())
                },
            }
            for pat in song.patterns
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def arrange_ir_song(
    song: IRSong,
    *,
    channel_instruments: Optional[Mapping[int | str, str]] = None,
    program_change_policy: str = "preserve",
    catalog: Optional[InstrumentCatalog] = None,
    catalog_path: Optional[Path] = None,
    player_version: str = "auto",
) -> Tuple[IRSong, Optional[RuntimeResolutionReport]]:
    """Return a deep-copied *song* with channel instrument overrides applied without mutating input.

    Unassigned channels keep their original instruments and ``PROGRAM_CHANGE`` events.
    Assigned channels follow ``program_change_policy`` (``preserve``, ``replace``, ``remove``).
    """
    ver_choice = normalize_player_version(player_version)
    policy = normalize_program_change_policy(program_change_policy)
    base = song.model_copy(deep=True)

    assigned: Dict[int, str] = {}
    if channel_instruments:
        for raw_ch, raw_id in channel_instruments.items():
            ch = parse_channel_identifier(raw_ch)
            inst_id = str(raw_id).strip()
            if not inst_id:
                raise InstrumentPlanError(
                    f"channel {ch} has empty catalog instrument_id",
                    code="INVALID_ASSIGNMENT_SYNTAX",
                )
            assigned[ch] = inst_id

    if not assigned:
        if ver_choice == "v1" and song_requires_v2(base):
            raise InstrumentPlanError(
                "song requires format v2 (" + "; ".join(song_requires_v2(base)) + ")",
                code="FORMAT_VERSION_CONFLICT",
            )
        return base, None

    cat = catalog if catalog is not None else load_instrument_catalog(catalog_path)

    # Reject unknown catalog IDs upfront
    for ch in sorted(assigned):
        pid = assigned[ch]
        if not cat.has_profile(pid):
            available = ", ".join(p.instrument_id for p in cat.instruments)
            raise InstrumentPlanError(
                f"instrument {pid!r} (channel {ch}) not found in catalog (available: {available})",
                code=INSTRUMENT_NOT_FOUND,
            )

    # Preserve musical integrity of existing CH2 harmony if 16-bit pair requested on CH1
    if 1 in assigned:
        p1, _ = cat.resolve_profile_behavior(assigned[1])
        if p1.hardware_constraints.divider_mode == "16bit_ch12":
            if 2 in assigned:
                raise InstrumentPlanError(
                    "channel 2 cannot be assigned independently while channel 1 uses 16-bit CH1+CH2 mode",
                    code="PAIR_16BIT_CHANNEL_CONFLICT",
                )
            has_ch2_notes = any(
                any(not n.is_rest for n in pat.tracks.get(2, []))
                for pat in base.patterns
            )
            if has_ch2_notes and not base.uses_16bit_bass:
                raise InstrumentPlanError(
                    f"profile {assigned[1]!r} on channel 1 requires 16-bit CH1+CH2 pairing, "
                    "which conflicts with existing independent notes on channel 2",
                    code="PAIR_16BIT_CHANNEL_CONFLICT",
                )

    orig_inst_by_idx: Dict[int, IRInstrument] = {
        idx: inst for idx, inst in enumerate(base.instruments)
    }
    id_to_orig_idx: Dict[int, int] = {
        inst.id: idx for idx, inst in enumerate(base.instruments)
    }
    orig_init = resolve_initial_channel_instruments(base)

    # Represent instrument references per note cleanly using symbolic tokens:
    # ("orig", orig_idx) or ("cat", catalog_id)
    ch_init_token: Dict[int, Tuple[str, Any]] = {}
    for ch in range(1, 5):
        if ch in assigned:
            ch_init_token[ch] = ("cat", assigned[ch])
        else:
            ch_init_token[ch] = ("orig", orig_init[ch])

    new_patterns: List[IRPattern] = []
    used_tokens: List[Tuple[str, Any]] = []
    ch_catalog_profiles: Dict[int, List[str]] = {c: [] for c in range(1, 5)}

    def _register_token(tok: Tuple[str, Any], ch_num: int) -> None:
        if tok not in used_tokens:
            used_tokens.append(tok)
        if tok[0] == "cat":
            pid = tok[1]
            if pid not in ch_catalog_profiles[ch_num]:
                ch_catalog_profiles[ch_num].append(pid)
        else:
            orig_i = orig_inst_by_idx.get(tok[1])
            if orig_i is not None and orig_i.profile_id and cat.has_profile(orig_i.profile_id):
                if orig_i.profile_id not in ch_catalog_profiles[ch_num]:
                    ch_catalog_profiles[ch_num].append(orig_i.profile_id)

    for ch in range(1, 5):
        _register_token(ch_init_token[ch], ch)

    pattern_token_tracks: Dict[int, Dict[int, List[Tuple[IRNote, Tuple[str, Any], Tuple[Tuple[str, Any], ...]]]]] = {}
    for pat in base.patterns:
        pat_map: Dict[int, List[Tuple[IRNote, Tuple[str, Any], Tuple[Tuple[str, Any], ...]]]] = {}
        for ch, notes in pat.tracks.items():
            orig_start = orig_init.get(ch, 0)
            annotated: List[Tuple[IRNote, Tuple[str, Any], Tuple[Tuple[str, Any], ...]]] = []
            prev_orig_idx: Optional[int] = orig_start

            for n in notes:
                raw_o_idx = id_to_orig_idx.get(n.instrument_id, orig_start)
                raw_pcs = tuple(id_to_orig_idx.get(pid, pid) for pid in n.pending_program_changes)

                if ch not in assigned:
                    tok = ("orig", raw_o_idx)
                    pc_toks = tuple(("orig", p) for p in raw_pcs)
                else:
                    new_tok: Tuple[str, Any] = ("cat", assigned[ch])
                    if policy == "remove":
                        tok = new_tok
                        pc_toks = ()
                    elif policy == "replace":
                        tok = new_tok
                        is_switch = bool(raw_pcs) or (
                            not n.is_rest and prev_orig_idx is not None and raw_o_idx != prev_orig_idx
                        )
                        pc_toks = (new_tok,) if is_switch else ()
                    else:  # preserve
                        tok = new_tok if (raw_o_idx == orig_start or n.is_rest) else ("orig", raw_o_idx)
                        pc_toks = tuple(
                            (new_tok if p == orig_start else ("orig", p)) for p in raw_pcs
                        )

                if not n.is_rest:
                    prev_orig_idx = raw_o_idx

                _register_token(tok, ch)
                for p_t in pc_toks:
                    _register_token(p_t, ch)
                annotated.append((n, tok, pc_toks))
            pat_map[ch] = annotated
        pattern_token_tracks[pat.id] = pat_map

    # Determine effective runtime target (respecting auto vs v1 vs v2 and POKEYRuntime checks)
    has_multi_inst_ch = False
    for ch in range(1, 5):
        ch_toks = {ch_init_token[ch]}
        for pat in base.patterns:
            for _n, tok, pc_toks in pattern_token_tracks[pat.id].get(ch, []):
                ch_toks.add(tok)
                ch_toks.update(pc_toks)
        if len(ch_toks) > 1:
            has_multi_inst_ch = True

    has_v2_beh = False
    for tok in used_tokens:
        if tok[0] == "cat":
            _p, beh = cat.resolve_profile_behavior(tok[1])
            if beh is not None and beh.required_runtime_tier != "core_v1":
                has_v2_beh = True
        else:
            oi = orig_inst_by_idx.get(tok[1])
            if oi is not None and (
                (oi.macro and any(s.is_v2_step() for s in oi.macro))
                or (oi.pitch_envelope is not None and oi.pitch_envelope.duration_frames > 0)
            ):
                has_v2_beh = True

    has_any_pc = any(
        pc_toks
        for pat in base.patterns
        for ch_list in pattern_token_tracks[pat.id].values()
        for _n, _tok, pc_toks in ch_list
    )
    est_requires_v2 = has_v2_beh or has_any_pc or has_multi_inst_ch or (len(used_tokens) > 4)

    runtime_target = TARGET_V1_XEX if (ver_choice == "v1" or (ver_choice == "auto" and not est_requires_v2)) else TARGET_V2_ITER1_XEX
    requests = [
        ChannelAssignmentRequest(channel=ch, instrument_ids=tuple(cids))
        for ch, cids in ch_catalog_profiles.items()
        if cids
    ]
    rt_report: Optional[RuntimeResolutionReport] = (
        POKEYRuntime().resolve(requests, cat, target=runtime_target)
        if requests
        else None
    )
    if rt_report is not None and not rt_report.is_compatible:
        errs = "; ".join(d.message for d in rt_report.diagnostics if d.severity == "ERROR")
        raise InstrumentPlanError(
            errs,
            code=next((d.code for d in rt_report.diagnostics if d.severity == "ERROR"), "RUNTIME_CONFLICT"),
            diagnostics=rt_report.diagnostics,
        )

    # Materialize compact IRInstrument list (0..K-1)
    token_to_new_id: Dict[Tuple[str, Any], int] = {}
    final_instruments: List[IRInstrument] = []
    for new_id, tok in enumerate(used_tokens):
        token_to_new_id[tok] = new_id
        if tok[0] == "cat":
            prof, beh = cat.resolve_profile_behavior(tok[1])
            final_instruments.append(IRInstrument.from_catalog_profile(new_id, prof, beh))
        else:
            oi = orig_inst_by_idx[tok[1]].model_copy(deep=True)
            updates: Dict[str, Any] = {"id": new_id}
            # v2 Iter 1 exporter refuses legacy vibrato on untouched v1 channels when promoted to v2
            if est_requires_v2 and (oi.vibrato_depth != 0 or oi.vibrato_speed != 0):
                updates["vibrato_depth"] = 0
                updates["vibrato_speed"] = 0
            final_instruments.append(oi.model_copy(update=updates))

    for pat in base.patterns:
        new_tracks: Dict[int, List[IRNote]] = {}
        for ch, items in pattern_token_tracks[pat.id].items():
            new_notes: List[IRNote] = []
            for orig_n, tok, pc_toks in items:
                new_id = token_to_new_id[tok]
                new_pcs = tuple(token_to_new_id[p] for p in pc_toks)
                new_notes.append(
                    orig_n.model_copy(
                        update={
                            "instrument_id": new_id,
                            "pending_program_changes": new_pcs,
                        }
                    )
                )
            new_tracks[ch] = new_notes
        new_patterns.append(
            IRPattern(id=pat.id, name=pat.name, rows=pat.rows, tracks=new_tracks)
        )

    uses_16bit_out = bool(base.uses_16bit_bass)
    if 1 in assigned:
        p1, _ = cat.resolve_profile_behavior(assigned[1])
        if p1.hardware_constraints.divider_mode == "16bit_ch12":
            uses_16bit_out = True
        elif p1.hardware_constraints.divider_mode == "8bit" and base.uses_16bit_bass:
            # Explicit 8-bit bass overrides 16-bit bass mode
            uses_16bit_out = False

    new_init_ch = {ch: token_to_new_id[ch_init_token[ch]] for ch in range(1, 5)}
    candidate = base.model_copy(
        update={
            "instruments": final_instruments,
            "patterns": new_patterns,
            "uses_16bit_bass": uses_16bit_out,
            "initial_channel_instruments": new_init_ch,
        }
    )

    # Check whether song genuinely needs v2 once assembled cleanly (remove/static core_v1 can stay v1!)
    candidate_no_init = candidate.model_copy(update={"initial_channel_instruments": None})
    if not song_requires_v2(candidate_no_init):
        candidate = candidate_no_init

    final_reasons = song_requires_v2(candidate)
    if ver_choice == "v1" and final_reasons:
        raise InstrumentPlanError(
            "selected arrangement requires format v2 (" + "; ".join(final_reasons) + ")",
            code="FORMAT_VERSION_CONFLICT",
        )

    return candidate, rt_report


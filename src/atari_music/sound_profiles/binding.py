"""External profile binding: attaching a POKEY sound profile to a compiled song.

A profile is a **rendering-time dependency**. The composition does not name it, the DSL
cannot express it, the AI never sees it. A separate binding document says which profile
realizes which already-declared instrument:

    composition (DSL / JSON)          ← musical intent, unchanged
        ↓  parse / validate / Music IR
    IRSong (POKEY IR)                 ← channel roles, distortion, envelopes
        ↓  apply_profile_binding(...)   ← the profile enters here, and only here
    profile-aware IRSong
        ↓                    ↓
     WAV frames          MADS / XEX

Everything this module changes lives in the hardware realization of a voice: the
generator (distortion), the AUDCTL clock/coupling configuration, and the envelope shape.
It never changes a pitch, a duration, a rest, a velocity, an arrangement or a role.

Pitch and volume are the composition's, by contract:

* the note determines the pitch — the profile supplies the *clock*, and the divider is
  derived from the note and that clock. ``pitch.base_hz`` is the profile's reference, not
  the note to play, and ``base_divider`` is evidence, never a register value to copy;
* the note's velocity is the peak volume — ``volume.peak_level`` is what the *source
  segment* peaked at and substituting it would delete the composer's dynamics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from atari_music.api import MusicGenerationMetadata, MusicGenerationResult
from atari_music.ir import IREnvelope, IRInstrument, IRSong, resolve_audctl_mode
from atari_music.pokey_hw import describe_audctl
from atari_music.sound_profiles.bank import (
    KNOWN_SCOPES,
    KNOWN_STATUSES,
    PROFILE_SCOPE_UNSUPPORTED,
    RENDERABLE_STATUSES,
    SCOPE_PAIR,
    SCOPE_VOICE,
    SoundProfile,
    SoundProfileBank,
    SoundProfileError,
)

logger = logging.getLogger(__name__)

#: Schema of the binding document this module reads.
BINDING_SCHEMA = "atari-music/sound-profile-binding/1"

# --- Error codes ------------------------------------------------------------
#: The binding file does not exist.
PROFILE_BINDING_MISSING = "PROFILE_BINDING_MISSING"
#: The binding file is not valid JSON, has the wrong schema, or is malformed.
PROFILE_BINDING_INVALID = "PROFILE_BINDING_INVALID"
#: The binding names an instrument the composition does not declare.
PROFILE_BINDING_UNKNOWN_INSTRUMENT = "PROFILE_BINDING_UNKNOWN_INSTRUMENT"
#: A bound profile needs a clock/coupling configuration the song's AUDCTL cannot provide.
PROFILE_AUDCTL_CONFLICT = "PROFILE_AUDCTL_CONFLICT"
#: A PAIR profile needs both channels of its pair, and one of them carries other notes.
PROFILE_PAIR_CHANNEL_CONFLICT = "PROFILE_PAIR_CHANNEL_CONFLICT"
#: A bound instrument's notes sit on a channel the profile cannot be realized on.
PROFILE_CHANNEL_REQUIREMENT = "PROFILE_CHANNEL_REQUIREMENT"
#: The composition declares an explicit distortion that disagrees with the profile's.
PROFILE_DISTORTION_CONFLICT = "PROFILE_DISTORTION_CONFLICT"
#: The profile's measured envelope does not fit the composer's frame fields (0..15).
PROFILE_ENVELOPE_OUT_OF_RANGE = "PROFILE_ENVELOPE_OUT_OF_RANGE"
#: The bank publishes a status this consumer does not recognise.
PROFILE_STATUS_UNKNOWN = "PROFILE_STATUS_UNKNOWN"
#: The profile's audited status says it must not be rendered as a sound.
PROFILE_STATUS_NOT_RENDERABLE = "PROFILE_STATUS_NOT_RENDERABLE"

#: AUDCTL bits, by the role they play for a pair or a channel.
_AUDCTL_15KHZ = 0x01
_AUDCTL_JOIN_3_4 = 0x08
_AUDCTL_JOIN_1_2 = 0x10
_AUDCTL_CH3_HS = 0x20
_AUDCTL_CH1_HS = 0x40

#: The composer's only joined-pair layout. Archaeology PAIR profiles are all ``1+2``.
_SUPPORTED_PAIR = "1+2"

#: Envelope frame fields the composer can express (see ``AIInstrumentDef``).
_ENVELOPE_FRAME_MAX = 15


def _pair_bits(channel: int) -> Tuple[int, int]:
    """The (join bit, high-speed bit) that govern *channel*'s pair."""
    if channel in (1, 2):
        return _AUDCTL_JOIN_1_2, _AUDCTL_CH1_HS
    return _AUDCTL_JOIN_3_4, _AUDCTL_CH3_HS


def _hex(value: Optional[int]) -> str:
    return "none" if value is None else f"${value:02X}"


@dataclass(frozen=True)
class ProfileBinding:
    """An external mapping from a composition instrument to a profile id."""

    schema: str
    instruments: Mapping[str, str]
    bank: Optional[Path] = None
    source: Optional[Path] = None

    def bank_path(self, fallback: Optional[Union[str, Path]] = None) -> Path:
        """The bank this binding refers to: its own ``bank`` field, or *fallback*."""
        chosen = self.bank if self.bank is not None else (Path(fallback) if fallback is not None else None)
        if chosen is None:
            raise SoundProfileError(
                "no sound profile bank given: the binding declares none and no --sound-bank "
                "was supplied",
                code=PROFILE_BINDING_INVALID,
                detail={"binding": str(self.source) if self.source else None},
            )
        return Path(chosen)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"ProfileBinding({dict(self.instruments)!r})"


def load_profile_binding(source: Union[str, Path, Mapping[str, Any]]) -> ProfileBinding:
    """Read and validate a binding document (path, JSON text, or mapping).

    Format::

        {
          "schema": "atari-music/sound-profile-binding/1",
          "bank": "path/to/bank",          # optional; --sound-bank wins if given
          "instruments": {
            "bass": "pokey_ref_050170ef",
            "lead": "pokey_ref_048db11d"
          }
        }

    Keys of ``instruments`` are the composition's instrument ids (``AIInstrumentDef.id``);
    an instrument's display name also resolves, but an ambiguity is an error.
    """
    if isinstance(source, Mapping):
        data: Any = dict(source)
        path: Optional[Path] = None
    else:
        path = Path(source)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as err:
            raise SoundProfileError(
                f"profile binding not found: {path}",
                code=PROFILE_BINDING_MISSING,
                detail={"path": str(path)},
            ) from err
        except json.JSONDecodeError as err:
            raise SoundProfileError(
                f"profile binding is not valid JSON: {path} ({err})",
                code=PROFILE_BINDING_INVALID,
                detail={"path": str(path), "error": str(err)},
            ) from err

    if not isinstance(data, dict):
        raise SoundProfileError(
            f"profile binding must be a JSON object: {path}",
            code=PROFILE_BINDING_INVALID,
            detail={"path": str(path) if path else None},
        )

    schema = data.get("schema")
    if schema != BINDING_SCHEMA:
        raise SoundProfileError(
            f"profile binding schema {schema!r} is not supported; this consumer reads "
            f"{BINDING_SCHEMA!r}",
            code=PROFILE_BINDING_INVALID,
            detail={"path": str(path) if path else None, "schema": schema},
        )

    raw_instruments = data.get("instruments")
    if not isinstance(raw_instruments, dict):
        raise SoundProfileError(
            f"profile binding needs an 'instruments' object mapping instrument id -> profile id: "
            f"{path}",
            code=PROFILE_BINDING_INVALID,
            detail={"path": str(path) if path else None},
        )

    instruments: Dict[str, str] = {}
    for key, value in raw_instruments.items():
        name = str(key).strip()
        if not name:
            raise SoundProfileError(
                "profile binding contains an empty instrument name",
                code=PROFILE_BINDING_INVALID,
                detail={"path": str(path) if path else None},
            )
        profile_id = str(value).strip() if isinstance(value, str) else ""
        if not profile_id:
            raise SoundProfileError(
                f"profile binding maps instrument {name!r} to an empty profile id",
                code=PROFILE_BINDING_INVALID,
                detail={"path": str(path) if path else None, "instrument": name},
            )
        instruments[name] = profile_id

    if not instruments:
        logger.warning("Profile binding %s binds no instruments; it will change nothing.", path)

    bank_path = data.get("bank")
    if bank_path is not None and not isinstance(bank_path, str):
        raise SoundProfileError(
            f"profile binding 'bank' must be a string path: {path}",
            code=PROFILE_BINDING_INVALID,
            detail={"path": str(path) if path else None},
        )

    resolved_bank: Optional[Path] = None
    if bank_path:
        candidate = Path(bank_path)
        if not candidate.is_absolute() and path is not None:
            # A relative bank path is relative to the binding file, not to the CWD, so a
            # binding and its bank can be moved together.
            candidate = (path.parent / candidate).resolve()
        resolved_bank = candidate

    return ProfileBinding(
        schema=str(schema),
        instruments=instruments,
        bank=resolved_bank,
        source=path,
    )


# ---------------------------------------------------------------------------
# Inspection of a compiled song
# ---------------------------------------------------------------------------
def _instrument_channels(song: IRSong, instrument_id: int) -> Tuple[int, ...]:
    """Channels carrying at least one sounding note of *instrument_id*, ascending."""
    channels: set = set()
    for pattern in song.patterns:
        for channel, notes in pattern.tracks.items():
            for note in notes:
                if note.instrument_id == instrument_id and not note.is_rest:
                    channels.add(int(channel))
                    break
    return tuple(sorted(channels))


def _channels_with_notes(song: IRSong) -> Dict[int, Tuple[int, ...]]:
    """channel -> the instrument ids that sound on it."""
    occupancy: Dict[int, set] = {}
    for pattern in song.patterns:
        for channel, notes in pattern.tracks.items():
            for note in notes:
                if not note.is_rest:
                    occupancy.setdefault(int(channel), set()).add(int(note.instrument_id))
    return {channel: tuple(sorted(ids)) for channel, ids in sorted(occupancy.items())}


def _resolve_targets(
    song: IRSong,
    key: str,
    composition: Optional[Any],
) -> Tuple[int, ...]:
    """IR instrument ids the binding key refers to.

    Resolution order: the composition's instrument ``id``, then its ``name``, then the IR
    instrument's ``name``. Anything other than exactly one match is an error, because a
    binding that silently lands somewhere unintended is worse than one that fails.
    """
    if composition is not None:
        by_id = [idx for idx, inst in enumerate(composition.instruments) if str(inst.id) == key]
        if by_id:
            return tuple(by_id)
        by_name = [idx for idx, inst in enumerate(composition.instruments) if str(inst.name) == key]
        if by_name:
            return tuple(by_name)

    by_ir_name = [inst.id for inst in song.instruments if str(inst.name) == key]
    if len(by_ir_name) > 1:
        raise SoundProfileError(
            f"profile binding key {key!r} matches {len(by_ir_name)} instruments by name; "
            "use the composition's instrument id instead",
            code=PROFILE_BINDING_UNKNOWN_INSTRUMENT,
            detail={"instrument": key, "matches": by_ir_name},
        )
    return tuple(by_ir_name)


def _composition_instrument(composition: Optional[Any], ir_id: int) -> Optional[Any]:
    """The ``AIInstrumentDef`` an IR instrument id came from, when it is available.

    ``compile_composition_to_pokey_ir`` assigns ``IRInstrument.id = index`` in
    ``doc.instruments``, so this is the instrument whose *explicit* fields decide the
    envelope and distortion precedence of contract C-5.2 / C-10.4.
    """
    if composition is None:
        return None
    try:
        return composition.instruments[ir_id]
    except (IndexError, TypeError):  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# Profile requirement checks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Requirement:
    """What a profile demands of AUDCTL for the channels it will be realized on."""

    join_bit: int
    hs_bit: int
    wants_join: bool
    wants_hs: bool
    wants_15k: bool

    def unmet(self, audctl: int) -> List[str]:
        problems: List[str] = []
        want_join = self.join_bit if self.wants_join else 0
        if (audctl & self.join_bit) != want_join:
            problems.append(
                f"the {'1+2' if self.join_bit == _AUDCTL_JOIN_1_2 else '3+4'} channel join bit "
                f"(${self.join_bit:02X}) is {'clear' if want_join else 'set'} in AUDCTL "
                f"${audctl:02X}, but the profile was measured with it "
                f"{'set' if want_join else 'clear'}"
            )
        want_hs = self.hs_bit if self.wants_hs else 0
        if (audctl & self.hs_bit) != want_hs:
            problems.append(
                f"the 1.79 MHz clock bit (${self.hs_bit:02X}) is "
                f"{'clear' if want_hs else 'set'} in AUDCTL ${audctl:02X}, but the profile was "
                f"measured with it {'set' if want_hs else 'clear'}"
            )
        if bool(audctl & _AUDCTL_15KHZ) != self.wants_15k:
            problems.append(
                f"the 15 kHz base clock bit ($01) is "
                f"{'clear' if self.wants_15k else 'set'} in AUDCTL ${audctl:02X}, but the profile "
                f"was measured with it {'set' if self.wants_15k else 'clear'}"
            )
        return problems


def _requirement(profile: SoundProfile, channel: int) -> _Requirement:
    """The AUDCTL bits *profile* needs for the pair that contains *channel*."""
    audctl_mode = profile.audctl_mode or 0
    join_bit, hs_bit = _pair_bits(channel)
    return _Requirement(
        join_bit=join_bit,
        hs_bit=hs_bit,
        wants_join=bool(audctl_mode & join_bit),
        wants_hs=bool(audctl_mode & hs_bit),
        wants_15k=bool(audctl_mode & _AUDCTL_15KHZ),
    )


# ---------------------------------------------------------------------------
# Applying a binding
# ---------------------------------------------------------------------------
@dataclass
class _Plan:
    """Everything one bound instrument contributes, before the song is rebuilt."""

    binding_key: str
    ir_id: int
    instrument_name: str
    profile: SoundProfile
    channels: Tuple[int, ...]
    distortion: Optional[int]
    distortion_source: str
    envelope: Optional[IREnvelope]
    envelope_sources: Dict[str, str] = field(default_factory=dict)
    #: The profile's measured volume contour, only when the caller asked for it.
    volume_contour: Optional[Tuple[int, ...]] = None
    volume_contour_source: str = "not requested"
    requirements: Tuple[Tuple[int, _Requirement], ...] = ()
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _plan_envelope(
    profile: SoundProfile,
    ir_inst: IRInstrument,
    inst_def: Optional[Any],
) -> Tuple[IREnvelope, Dict[str, str]]:
    """Resolve the envelope by contract precedence (composition, then profile, then IR).

    Field by field: an explicitly declared composition field always wins, so no existing
    explicit instrument envelope is ever overwritten. Only fields the composition left
    open are taken from the profile.
    """
    frames = profile.envelope_frames
    sustain_level = profile.envelope_sustain_level

    mapping = (
        # (field, explicit composition attr, profile source value)
        ("attack_frames", "attack_frames", frames.get("attack")),
        ("decay_frames", "decay_frames", frames.get("decay")),
        ("release_frames", "release_frames", frames.get("release")),
        ("sustain_vol", "sustain_vol", sustain_level),
    )

    values: Dict[str, int] = {}
    sources: Dict[str, str] = {}
    for field_name, explicit_attr, profile_value in mapping:
        explicit = getattr(inst_def, explicit_attr, None) if inst_def is not None else None
        if explicit is not None:
            values[field_name] = int(explicit)
            sources[field_name] = "composition"
            continue
        if profile_value is None:
            values[field_name] = int(getattr(ir_inst.envelope, field_name))
            sources[field_name] = "character_default"
            continue
        value = int(profile_value)
        if value < 0 or value > _ENVELOPE_FRAME_MAX:
            raise SoundProfileError(
                f"profile {profile.profile_id} measures {field_name} = {value}, outside the "
                f"0..{_ENVELOPE_FRAME_MAX} range the composer's envelope fields can express; "
                "refusing rather than clamping the requested envelope",
                code=PROFILE_ENVELOPE_OUT_OF_RANGE,
                detail={
                    "profile_id": profile.profile_id,
                    "field": field_name,
                    "value": value,
                    "max": _ENVELOPE_FRAME_MAX,
                },
            )
        values[field_name] = value
        sources[field_name] = "profile"

    return IREnvelope(**values), sources


def _require_renderable(profile: SoundProfile, binding_key: str) -> None:
    """Refuse a profile the publishing audit says must not be rendered as a sound.

    This is the one check that exists because the bank is a *research* catalogue, not a
    curated library: it contains profiles that describe no sound at all. Such a profile is
    refused loudly — never swapped for a default, never skipped, never rendered as silence
    that looks like a working instrument.

    A bank that publishes no status for a profile is not refused: a profile without a
    verdict was published by a pipeline that had none to give. A status this consumer does
    not recognise *is* refused, so a future verdict cannot pass silently.
    """
    status = profile.status
    if status is None:
        return
    if status not in KNOWN_STATUSES:
        raise SoundProfileError(
            f"profile {profile.profile_id} (bound to instrument {binding_key!r}) publishes "
            f"audit status {status!r}, which this consumer does not recognise; refusing rather "
            f"than guessing what it permits",
            code=PROFILE_STATUS_UNKNOWN,
            detail={"profile_id": profile.profile_id, "status": status, "instrument": binding_key},
        )
    if status in RENDERABLE_STATUSES:
        return

    codes = ", ".join(profile.blocking_codes) or "no code recorded"
    raise SoundProfileError(
        f"profile {profile.profile_id} (bound to instrument {binding_key!r}) carries audit "
        f"status {status}, which this consumer must not render as a sound ({codes}). Choose a "
        "profile whose status is " + " or ".join(RENDERABLE_STATUSES) + ".",
        code=PROFILE_STATUS_NOT_RENDERABLE,
        detail={
            "profile_id": profile.profile_id,
            "status": status,
            "instrument": binding_key,
            "blocking_codes": list(profile.blocking_codes),
        },
    )


def _plan_instrument(
    song: IRSong,
    binding_key: str,
    ir_id: int,
    profile: SoundProfile,
    composition: Optional[Any],
    volume_contour: bool = False,
) -> _Plan:
    """Validate and describe what *profile* does to one instrument. Raises on conflict."""
    _require_renderable(profile, binding_key)
    ir_inst = next(inst for inst in song.instruments if inst.id == ir_id)
    inst_def = _composition_instrument(composition, ir_id)
    channels = _instrument_channels(song, ir_id)
    occupancy = _channels_with_notes(song)

    plan = _Plan(
        binding_key=binding_key,
        ir_id=ir_id,
        instrument_name=ir_inst.name,
        profile=profile,
        channels=channels,
        distortion=None,
        distortion_source="unset",
        envelope=None,
    )

    # --- generator (distortion) -------------------------------------------
    distortion_byte = profile.distortion_byte
    explicit_distortion = getattr(inst_def, "distortion", None) if inst_def is not None else None
    if distortion_byte is None:
        plan.distortion = int(ir_inst.distortion)
        plan.distortion_source = "instrument (profile declares none)"
        plan.warnings.append(
            f"profile {profile.profile_id} declares no distortion; the instrument's own "
            f"generator ${ir_inst.distortion:02X} is kept"
        )
    elif explicit_distortion is not None and int(explicit_distortion) != distortion_byte:
        raise SoundProfileError(
            f"instrument {ir_inst.name!r} ({binding_key!r}) explicitly declares distortion "
            f"${int(explicit_distortion) & 0xE0:02X}, but profile {profile.profile_id} measures "
            f"the generator ${distortion_byte:02X} (nibble {_hex(profile.distortion_nibble)}); a "
            "profile is one coherent register configuration, so a partial override is refused "
            "rather than merged",
            code=PROFILE_DISTORTION_CONFLICT,
            detail={
                "instrument": binding_key,
                "profile_id": profile.profile_id,
                "composition_distortion": int(explicit_distortion) & 0xE0,
                "profile_distortion": distortion_byte,
            },
        )
    else:
        plan.distortion = distortion_byte
        plan.distortion_source = (
            "profile (agrees with the composition's explicit value)"
            if explicit_distortion is not None
            else "profile"
        )

    # --- envelope ----------------------------------------------------------
    plan.envelope, plan.envelope_sources = _plan_envelope(profile, ir_inst, inst_def)

    # --- volume contour (opt-in) -------------------------------------------
    # The volume contour is *not* part of what a profile realizes by default: the composer
    # has always driven loudness from the note's own velocity and the envelope above, and a
    # binding that silently changed that would change every existing rendering. It is
    # therefore switched on explicitly, and a profile that measures no contour contributes
    # nothing rather than a contour of zeroes.
    if volume_contour:
        contour = profile.volume_contour
        if contour:
            plan.volume_contour = contour
            plan.volume_contour_source = "profile"
            plan.notes.append(
                f"volume contour: {len(contour)} frames, levels "
                f"{min(contour)}..{max(contour)} (from gesture.volume.runs)"
            )
        else:
            plan.volume_contour = None
            plan.volume_contour_source = "profile declares none"
            plan.warnings.append(
                f"volume contour requested, but profile {profile.profile_id} publishes no "
                "measured level series; the instrument keeps the composer's velocity and "
                "envelope unchanged"
            )

    # --- channel / scope requirements --------------------------------------
    if profile.scope == SCOPE_PAIR:
        if profile.pair and profile.pair != _SUPPORTED_PAIR:
            raise SoundProfileError(
                f"profile {profile.profile_id} declares pair {profile.pair!r}; the composer "
                f"implements only {_SUPPORTED_PAIR}",
                code=PROFILE_PAIR_CHANNEL_CONFLICT,
                detail={"profile_id": profile.profile_id, "pair": profile.pair},
            )
        if not channels:
            raise SoundProfileError(
                f"instrument {ir_inst.name!r} ({binding_key!r}) has no sounding notes, so "
                f"PAIR profile {profile.profile_id} has nothing to realize",
                code=PROFILE_CHANNEL_REQUIREMENT,
                detail={"instrument": binding_key, "profile_id": profile.profile_id},
            )
        offending = [channel for channel in channels if channel != 1]
        if offending:
            raise SoundProfileError(
                f"PAIR profile {profile.profile_id} needs both channels of the {_SUPPORTED_PAIR} "
                f"pair, and the pair is driven from channel 1, but instrument {ir_inst.name!r} "
                f"({binding_key!r}) has notes on channel(s) {offending}; channel 2's register is "
                "the high divider byte of the pair, so its notes cannot be independent",
                code=PROFILE_CHANNEL_REQUIREMENT,
                detail={
                    "instrument": binding_key,
                    "profile_id": profile.profile_id,
                    "channels": list(channels),
                },
            )
        # Channel 2 is overwritten by the pair's high byte, so nothing else may live there.
        intruders = [other for other in occupancy.get(2, ()) if other != ir_id]
        if intruders:
            names = ", ".join(
                next(inst.name for inst in song.instruments if inst.id == other)
                for other in intruders
            )
            raise SoundProfileError(
                f"[{binding_key}] 16-bit pair collision on channels 1 & 2: channel 2 carries "
                f"notes of {names}, but PAIR profile {profile.profile_id} makes channel 2 a "
                "hardware frequency slave to channel 1",
                code=PROFILE_PAIR_CHANNEL_CONFLICT,
                detail={
                    "instrument": binding_key,
                    "profile_id": profile.profile_id,
                    "conflicting_instruments": list(intruders),
                    "existing_code": "BASS16_CHANNEL_CONFLICT",
                },
            )
        plan.requirements = ((1, _requirement(profile, 1)),)
    elif profile.scope == SCOPE_VOICE:
        if not channels:
            raise SoundProfileError(
                f"instrument {ir_inst.name!r} ({binding_key!r}) has no sounding notes, so "
                f"VOICE profile {profile.profile_id} has nothing to realize",
                code=PROFILE_CHANNEL_REQUIREMENT,
                detail={"instrument": binding_key, "profile_id": profile.profile_id},
            )
        plan.requirements = tuple(
            (channel, _requirement(profile, channel)) for channel in channels
        )
        if len(channels) > 1:
            plan.notes.append(
                f"the instrument sounds on {len(channels)} channels ({list(channels)}); the "
                "profile's hardware configuration is realized independently on each"
            )
    else:
        raise SoundProfileError(
            f"profile {profile.profile_id} declares scope {profile.scope!r}; this consumer "
            f"implements {' and '.join(KNOWN_SCOPES)}",
            code=PROFILE_SCOPE_UNSUPPORTED,
            detail={"profile_id": profile.profile_id, "scope": profile.scope},
        )

    if profile.requires_simultaneous_channels and profile.scope != SCOPE_PAIR:
        plan.warnings.append(
            f"profile {profile.profile_id} declares requires_simultaneous_channels but its scope "
            f"is {profile.scope}"
        )

    return plan


def _rebuild_song(song: IRSong, plans: List[_Plan], volume_contour: bool = False) -> IRSong:
    """The song with only hardware-realization fields changed.

    With ``volume_contour`` False this writes exactly the fields it always wrote, so a
    binding built with the feature off is byte-identical to one built before it existed.
    """
    updates: Dict[int, Dict[str, Any]] = {}
    for plan in plans:
        update: Dict[str, Any] = {
            "distortion": plan.distortion,
            "envelope": plan.envelope,
            "audctl": plan.profile.audctl_mode,
            "profile_id": plan.profile.profile_id,
            "profile_fingerprint": plan.profile.fingerprint,
        }
        if plan.profile.scope == SCOPE_PAIR:
            update["is_16bit"] = True
        if volume_contour:
            update["volume_contour"] = (
                list(plan.volume_contour) if plan.volume_contour else None
            )
        updates[plan.ir_id] = update

    return song.model_copy(
        update={
            "instruments": [
                inst.model_copy(update=updates[inst.id]) if inst.id in updates else inst
                for inst in song.instruments
            ],
            "uses_16bit_bass": bool(
                song.uses_16bit_bass or any(plan.profile.scope == SCOPE_PAIR for plan in plans)
            ),
        }
    )


def _validate_requirements(plans: List[_Plan], audctl_val: int) -> None:
    """Refuse a binding whose hardware configuration AUDCTL cannot provide."""
    for plan in plans:
        for channel, requirement in plan.requirements:
            problems = requirement.unmet(audctl_val)
            if problems:
                raise SoundProfileError(
                    f"profile {plan.profile.profile_id} cannot be realized on channel {channel} "
                    f"of instrument {plan.instrument_name!r}: "
                    + "; ".join(problems)
                    + f". Effective AUDCTL is ${audctl_val:02X} "
                    f"({describe_audctl(audctl_val)}). Bind the profile to a voice whose channel "
                    "can carry this configuration, or change the composition's own hardware "
                    "flags.",
                    code=PROFILE_AUDCTL_CONFLICT,
                    detail={
                        "instrument": plan.binding_key,
                        "profile_id": plan.profile.profile_id,
                        "channel": channel,
                        "audctl": audctl_val,
                        "problems": problems,
                    },
                )


def _wants_contour(volume_contour: Union[bool, Iterable[str]], binding_key: str) -> bool:
    """Whether *binding_key* takes the profile's volume contour.

    ``volume_contour`` is True for every bound instrument, False for none, or an iterable of
    binding keys for exactly those. The per-key form exists because a profile can measure a
    contour that is mostly silence: whether that may be transferred is a decision about one
    instrument, not about the whole song, and it must be recorded per instrument.
    """
    if isinstance(volume_contour, bool):
        return volume_contour
    return binding_key in set(volume_contour)


def apply_profile_binding(
    result: MusicGenerationResult,
    binding: ProfileBinding,
    bank: SoundProfileBank,
    composition: Optional[Any] = None,
    volume_contour: Union[bool, Iterable[str]] = False,
) -> MusicGenerationResult:
    """Return a copy of *result* whose POKEY IR is realized by the bound profiles.

    The composition document is not modified, and neither is the Music IR: only the
    ``IRSong``'s instrument hardware fields and AUDCTL change, which is what both the WAV
    renderer and the MADS/XEX exporter consume.

    With ``volume_contour`` True, each bound instrument also receives its profile's measured
    per-frame level contour (``IRInstrument.volume_contour``). Default False: a binding built
    by this function alone must stay byte-identical to one built before the feature existed.

    Raises
    ------
    SoundProfileError
        On any conflict, with a stable code. Nothing is substituted, dropped or
        downgraded, and no bound profile is ever skipped.
    """
    song = result.pokey_ir
    if not binding.instruments:
        logger.warning("Profile binding binds no instruments; the result is unchanged.")
        return result

    plans: List[_Plan] = []
    for key, profile_id in binding.instruments.items():
        targets = _resolve_targets(song, key, composition)
        if not targets:
            declared = (
                ", ".join(str(inst.id) for inst in composition.instruments)
                if composition is not None and getattr(composition, "instruments", None)
                else ", ".join(inst.name for inst in song.instruments)
            )
            raise SoundProfileError(
                f"profile binding names instrument {key!r}, which the composition does not "
                f"declare — declared instruments: {declared}",
                code=PROFILE_BINDING_UNKNOWN_INSTRUMENT,
                detail={"instrument": key, "declared": declared},
            )
        if len(targets) > 1:
            raise SoundProfileError(
                f"profile binding key {key!r} matches {len(targets)} instruments; it must be "
                "unambiguous",
                code=PROFILE_BINDING_UNKNOWN_INSTRUMENT,
                detail={"instrument": key, "matches": list(targets)},
            )
        profile = bank.get(profile_id)
        plans.append(
            _plan_instrument(
                song,
                key,
                targets[0],
                profile,
                composition,
                _wants_contour(volume_contour, key),
            )
        )

    # Two different PAIR profiles cannot share the one pair the composer implements.
    pair_plans = [plan for plan in plans if plan.profile.scope == SCOPE_PAIR]
    if len(pair_plans) > 1:
        raise SoundProfileError(
            "more than one voice is bound to a PAIR profile: "
            + ", ".join(f"{plan.binding_key!r} -> {plan.profile.profile_id}" for plan in pair_plans)
            + f", but the composer has one joined pair ({_SUPPORTED_PAIR})",
            code=PROFILE_PAIR_CHANNEL_CONFLICT,
            detail={"instruments": [plan.binding_key for plan in pair_plans]},
        )

    # Rebuild the instruments: hardware fields only, nothing musical, then check the
    # configuration that will actually be written into AUDCTL.
    new_song = _rebuild_song(song, plans, any(plan.volume_contour for plan in plans))
    audctl_val = resolve_audctl_mode(new_song)
    _validate_requirements(plans, audctl_val)

    metadata: MusicGenerationMetadata = result.metadata.model_copy(
        update={
            "sound_profiles": [
                {
                    "instrument": plan.binding_key,
                    "instrument_name": plan.instrument_name,
                    "profile_id": plan.profile.profile_id,
                    "profile_fingerprint": plan.profile.fingerprint,
                    "scope": plan.profile.scope,
                    "bank_schema": bank.schema,
                    **(
                        {
                            "volume_contour_frames": len(plan.volume_contour),
                            "volume_contour_source": plan.volume_contour_source,
                        }
                        if plan.volume_contour
                        else {}
                    ),
                }
                for plan in plans
            ],
            "uses_16bit_bass": new_song.uses_16bit_bass,
        }
    )

    logger.info(
        "Applied %d sound profile binding(s); AUDCTL=$%02X (%s)",
        len(plans),
        audctl_val,
        describe_audctl(audctl_val),
    )

    return result.model_copy(update={"pokey_ir": new_song, "metadata": metadata})


def describe_binding(
    result: MusicGenerationResult,
    binding: ProfileBinding,
    bank: SoundProfileBank,
    composition: Optional[Any] = None,
    volume_contour: Union[bool, Iterable[str]] = False,
) -> Dict[str, Any]:
    """A machine-readable description of what a binding does to a song.

    Built from the same planning code the application uses, so a report can never claim
    something different from what was rendered. Raises on the same conflicts.

    ``volume_contour`` must be the same value that was passed to ``apply_profile_binding``,
    otherwise the description would not describe the song that was rendered.
    """
    song = result.pokey_ir
    entries: List[Dict[str, Any]] = []
    plans: List[_Plan] = []
    for key, profile_id in binding.instruments.items():
        targets = _resolve_targets(song, key, composition)
        if len(targets) != 1:
            raise SoundProfileError(
                f"profile binding names instrument {key!r}, which the composition does not "
                "declare unambiguously",
                code=PROFILE_BINDING_UNKNOWN_INSTRUMENT,
                detail={"instrument": key, "matches": list(targets)},
            )
        profile = bank.get(profile_id)
        plan = _plan_instrument(
            song,
            key,
            targets[0],
            profile,
            composition,
            _wants_contour(volume_contour, key),
        )
        plans.append(plan)
        entries.append(
            {
                "instrument": key,
                "instrument_name": plan.instrument_name,
                "channels": list(plan.channels),
                "profile_id": profile.profile_id,
                "scope": profile.scope,
                "status": profile.status,
                "blocking_issues": list(profile.blocking_codes),
                "limitation_codes": list(profile.limitation_codes),
                "consumer_gap_codes": list(profile.consumer_gap_codes),
                "audctl_mode": _hex(profile.audctl_mode),
                "clock_mode": profile.clock_mode,
                "coupling": profile.coupling,
                "divider_bits": profile.divider_bits,
                "distortion_nibble": _hex(profile.distortion_nibble),
                "distortion_audc": _hex(plan.distortion),
                "distortion_source": plan.distortion_source,
                "envelope": {
                    name: {"value": int(getattr(plan.envelope, name)), "source": source}
                    for name, source in plan.envelope_sources.items()
                },
                "envelope_confidence": profile.envelope_confidence,
                **(
                    {
                        "volume_contour": {
                            "source": plan.volume_contour_source,
                            "frames": len(plan.volume_contour) if plan.volume_contour else 0,
                            "levels": (
                                [min(plan.volume_contour), max(plan.volume_contour)]
                                if plan.volume_contour
                                else None
                            ),
                        }
                    }
                    if plan.volume_contour
                    else {}
                ),
                "source_songs": len(profile.source_songs),
                "source_segments": profile.source_segments,
                "notes": list(plan.notes),
                "warnings": list(plan.warnings),
            }
        )

    audctl_val = resolve_audctl_mode(song)
    if plans:
        new_song = _rebuild_song(song, plans)
        audctl_val = resolve_audctl_mode(new_song)
        _validate_requirements(plans, audctl_val)

    return {
        "schema": binding.schema,
        "bank": str(bank.root),
        "bank_status": bank.status,
        "bank_note": bank.note,
        "profile_count": len(bank.profiles),
        "instruments": entries,
        "audctl": audctl_val,
        "audctl_hex": _hex(audctl_val),
        "audctl_description": describe_audctl(audctl_val),
        "uses_16bit_bass": bool(
            song.uses_16bit_bass or any(plan.profile.scope == SCOPE_PAIR for plan in plans)
        ),
    }

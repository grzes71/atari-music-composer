"""Loading a portable POKEY sound profile bank.

A bank is a directory written by the POKEY Sound Archaeology project:

    bank/
        registry.json          the catalogue: ids, scopes, fingerprints
        profiles/
            pokey_ref_XXXXXXXX.json     one PlayableSoundProfile per file

The bank is the *only* input the Composer needs. Loading it must not require the
archaeology package, an emulator, the SAP corpus or the reference audio.

Every failure mode is explicit and carries a stable code. Nothing is substituted,
nothing is guessed: an unknown id raises, and a profile whose content does not match
the fingerprint its registry entry publishes raises.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

logger = logging.getLogger(__name__)

#: The registry schema this loader understands. A bank with any other value is
#: refused rather than interpreted.
REGISTRY_SCHEMA = "pokey-sound-profile-registry-1.0"

#: The playable artefact schema a bank entry must declare.
PROFILE_SCHEMA = "pokey-playable-sound-profile-1.0"

#: The two scopes a profile may declare.
SCOPE_VOICE = "VOICE"
SCOPE_PAIR = "PAIR"
KNOWN_SCOPES = (SCOPE_VOICE, SCOPE_PAIR)

# --- Audit statuses a published entry may carry ------------------------------
#: Every register the profile needs is determined and self-consistent. Renderable.
STATUS_PLAYABLE = "PLAYABLE"
#: Renderable, with a recorded caveat (a consumer-side gap or a measured limitation).
STATUS_PLAYABLE_WITH_LIMITATION = "PLAYABLE_WITH_LIMITATION"
#: The profile describes no sound, so there is nothing to programme. Not renderable.
STATUS_MEASUREMENT_ONLY = "MEASUREMENT_ONLY"
#: The profile contradicts itself. Not renderable.
STATUS_INTERNALLY_CONTRADICTORY = "INTERNALLY_CONTRADICTORY"
#: Cannot be programmed at all. Not renderable.
STATUS_UNPLAYABLE = "UNPLAYABLE"
#: The document is only meaningful next to a context the consumer does not have.
STATUS_CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"

#: Statuses this consumer is willing to render. The set is deliberately the *audited* one:
#: a profile the audit rated as describing no sound (or as self-contradictory) is refused,
#: never silently downgraded to a default instrument.
RENDERABLE_STATUSES = (STATUS_PLAYABLE, STATUS_PLAYABLE_WITH_LIMITATION)

#: Every status the audit can publish, so an unknown value can be reported as such.
KNOWN_STATUSES = (
    STATUS_PLAYABLE,
    STATUS_PLAYABLE_WITH_LIMITATION,
    STATUS_MEASUREMENT_ONLY,
    STATUS_INTERNALLY_CONTRADICTORY,
    STATUS_UNPLAYABLE,
    STATUS_CONTEXT_DEPENDENT,
)

# --- Error codes ------------------------------------------------------------
#: The bank directory does not exist or has no registry.json.
PROFILE_BANK_MISSING = "PROFILE_BANK_MISSING"
#: registry.json is not valid JSON, or its schema is not the one we understand.
PROFILE_BANK_SCHEMA_UNSUPPORTED = "PROFILE_BANK_SCHEMA_UNSUPPORTED"
#: A registry entry names a file that is not there.
PROFILE_FILE_MISSING = "PROFILE_FILE_MISSING"
#: A profile document is not valid JSON or lacks a required field.
PROFILE_INVALID = "PROFILE_INVALID"
#: A profile's content does not hash to the fingerprint its registry entry publishes.
PROFILE_FINGERPRINT_MISMATCH = "PROFILE_FINGERPRINT_MISMATCH"
#: The requested profile id is not in the bank.
PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
#: The profile declares a scope this consumer does not implement.
PROFILE_SCOPE_UNSUPPORTED = "PROFILE_SCOPE_UNSUPPORTED"


class SoundProfileError(Exception):
    """A sound profile bank or binding failure with a stable machine-readable code."""

    code = "SOUND_PROFILE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        detail: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.detail: Dict[str, Any] = dict(detail or {})

    def __str__(self) -> str:  # pragma: no cover - formatting only
        if self.detail:
            return f"[{self.code}] {super().__str__()}"
        return f"[{self.code}] {super().__str__()}"


def parse_hex_nibble(value: Any) -> Optional[int]:
    """Parse a profile's ``distortion`` nibble (``"$A"``, ``"A"``, ``10``) to 0..15."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value & 0x0F
    text = str(value).strip().lstrip("$").lstrip("0x").lstrip("0X")
    if not text:
        return 0
    try:
        return int(text, 16) & 0x0F
    except ValueError:
        return None


def parse_audctl(value: Any) -> Optional[int]:
    """Parse an ``audctl_mode`` byte (``"$50"``, ``80``) to 0..255."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value & 0xFF
    text = str(value).strip().lstrip("$").lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text:
        return 0
    try:
        return int(text, 16) & 0xFF
    except ValueError:
        return None


def playable_fingerprint_of(document: Mapping[str, Any]) -> str:
    """Recompute a playable profile's fingerprint exactly as its producer does.

    The fingerprint covers every field except ``playable_fingerprint`` itself, over a
    canonical JSON rendering (sorted keys, no insignificant whitespace, UTF-8).
    """
    comparable = {key: value for key, value in document.items() if key != "playable_fingerprint"}
    canonical = json.dumps(comparable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SoundProfile:
    """One ``PlayableSoundProfile``, with the facts a POKEY consumer needs.

    The document is kept verbatim so nothing is lost, and the accessors read the
    fields the Stage 8B compatibility contract mapped onto Composer concepts. A
    missing field stays missing: no accessor invents a value.
    """

    profile_id: str
    scope: str
    fingerprint: str
    document: Mapping[str, Any]
    source_file: Optional[Path] = None
    #: The verdict the publishing audit recorded for this profile, when the bank carries one.
    #: ``None`` for a bank published before the status was attached, which is treated as
    #: "unknown" rather than "fine": see :pyattr:`renderable`.
    status: Optional[str] = None
    #: Condition codes the audit attached (profile-intrinsic reasons it is not renderable).
    blocking_codes: Tuple[str, ...] = ()
    #: Codes of the audited limitations and consumer-side gaps, kept as evidence.
    limitation_codes: Tuple[str, ...] = ()
    consumer_gap_codes: Tuple[str, ...] = ()

    @property
    def renderable(self) -> bool:
        """Whether this profile may be rendered as a sound.

        A bank that publishes no status is not judged here — an unstatused profile was
        published by a pipeline that had no verdict to give, and refusing it would break
        banks that predate the audit. A status that *is* present and not renderable, or a
        value this consumer does not recognise, is refused by the binding layer with an
        explicit error.
        """
        return self.status is None or self.status in RENDERABLE_STATUSES

    @property
    def status_known(self) -> bool:
        return self.status in KNOWN_STATUSES

    # --- hardware -----------------------------------------------------------
    @property
    def hardware(self) -> Mapping[str, Any]:
        return (self.document.get("pokey") or {}).get("hardware") or {}

    @property
    def channels(self) -> Mapping[str, Any]:
        return (self.document.get("pokey") or {}).get("channels") or {}

    @property
    def distortion_nibble(self) -> Optional[int]:
        """The AUDC generator nibble (bits 7..5) the profile was measured with."""
        return parse_hex_nibble(self.hardware.get("distortion"))

    @property
    def distortion_byte(self) -> Optional[int]:
        """The AUDC generator byte: the nibble in the generator-bit position.

        Archaeology stores distortion as a nibble (``"$A"``); the Composer's AUDC
        uses the full byte (``0xA0``). Copying ``"$A"`` verbatim yields ``0x00``, i.e.
        a silent channel, so the shift is explicit here.
        """
        nibble = self.distortion_nibble
        if nibble is None:
            return None
        return (nibble << 4) & 0xE0

    @property
    def audctl_mode(self) -> Optional[int]:
        return parse_audctl(self.hardware.get("audctl_mode"))

    @property
    def clock_mode(self) -> Optional[str]:
        return self.hardware.get("clock_mode")

    @property
    def coupling(self) -> Optional[str]:
        return self.hardware.get("coupling")

    @property
    def audible_channel(self) -> Optional[int]:
        channel = self.channels.get("audible_channel")
        return int(channel) if isinstance(channel, int) else None

    @property
    def companion_channel(self) -> Optional[int]:
        channel = self.channels.get("companion_channel")
        return int(channel) if isinstance(channel, int) else None

    @property
    def divider_bits(self) -> int:
        bits = self.channels.get("divider_bits")
        return int(bits) if isinstance(bits, int) else 8

    @property
    def pair(self) -> Optional[str]:
        value = self.channels.get("pair")
        return str(value) if value else None

    @property
    def requires_simultaneous_channels(self) -> bool:
        return bool(self.channels.get("requires_simultaneous_channels"))

    # --- envelope -----------------------------------------------------------
    @property
    def envelope_frames(self) -> Mapping[str, Any]:
        return (self.document.get("envelope") or {}).get("frames") or {}
    @property
    def envelope_confidence(self) -> Optional[float]:
        value = (self.document.get("envelope") or {}).get("confidence")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def envelope_sustain_level(self) -> Optional[int]:
        value = (self.document.get("envelope") or {}).get("sustain_level")
        return int(value) if isinstance(value, int) else None

    # --- volume contour -----------------------------------------------------
    @property
    def volume_gesture(self) -> Mapping[str, Any]:
        """The measured volume gesture: the profile's own record of how loudness moved."""
        return (self.document.get("gesture") or {}).get("volume") or {}

    @property
    def volume_contour_declared(self) -> Mapping[str, Any]:
        """What the profile itself says about whether that contour may be used.

        The archaeology publishes ``playability.gesture.volume.{available,enabled}``: for the
        profiles that carry a contour this is ``available: true, enabled: false`` — the data
        exists and the artefact does not use it yet. Recorded here rather than inferred, so a
        consumer can tell "measured but unused" from "never measured".
        """
        return ((self.document.get("playability") or {}).get("gesture") or {}).get("volume") or {}

    @property
    def volume_contour(self) -> Optional[Tuple[int, ...]]:
        """The measured per-frame AUDC volume levels (0..15), or ``None`` when there are none.

        ``gesture.volume.runs`` is run-length encoded as ``[[level, frames], ...]`` in the order
        measured, one sample per VBL frame (``gesture.resolution.one_sample_per_frame``). It is
        expanded verbatim: a level the archaeology did not measure is never invented, and a series
        whose shape or values are not what the unit claims (``audc_volume_level_0_15``) yields
        ``None`` rather than a clamped or repaired reading.
        """
        runs = self.volume_gesture.get("runs")
        if not isinstance(runs, (list, tuple)) or not runs:
            return None
        levels: List[int] = []
        for run in runs:
            if not isinstance(run, (list, tuple)) or len(run) != 2:
                return None
            level, length = run
            if isinstance(level, bool) or isinstance(length, bool):
                return None
            if not isinstance(level, int) or not isinstance(length, int):
                return None
            if not 0 <= level <= 15 or length < 0:
                return None
            levels.extend([level] * length)
        return tuple(levels) or None

    @property
    def volume_levels_outside_the_nibble(self) -> Tuple[int, ...]:
        """Measured levels outside ``0..15``, which make the series unusable rather than clampable."""
        runs = self.volume_gesture.get("runs")
        if not isinstance(runs, (list, tuple)):
            return ()
        return tuple(
            int(run[0])
            for run in runs
            if isinstance(run, (list, tuple))
            and len(run) == 2
            and isinstance(run[0], int)
            and not isinstance(run[0], bool)
            and not 0 <= run[0] <= 15
        )

    # --- provenance ---------------------------------------------------------
    @property
    def source_songs(self) -> List[Mapping[str, Any]]:
        return list((self.document.get("source") or {}).get("songs") or [])

    @property
    def source_segments(self) -> Optional[int]:
        value = (self.document.get("coverage") or {}).get("segments")
        return int(value) if isinstance(value, int) else None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"SoundProfile({self.profile_id!r}, scope={self.scope!r})"


@dataclass(frozen=True)
class SoundProfileBank:
    """A loaded, verified profile bank.

    Immutable and self-sufficient: everything a render needs is in memory, so a later
    change on disk cannot alter an in-flight render.
    """

    root: Path
    schema: str
    profiles: Mapping[str, SoundProfile]
    status: str = "experimental"
    note: str = ""
    producer: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.producer is None:
            object.__setattr__(self, "producer", {})

    def get(self, profile_id: str) -> SoundProfile:
        """Exact lookup. An unknown id raises; nothing is substituted."""
        profile = self.profiles.get(str(profile_id).strip())
        if profile is None:
            known = ", ".join(sorted(self.profiles)) or "(bank is empty)"
            raise SoundProfileError(
                f"sound profile {profile_id!r} is not in the bank at {self.root} — known ids: {known}",
                code=PROFILE_NOT_FOUND,
                detail={"profile_id": profile_id, "bank": str(self.root), "known": sorted(self.profiles)},
            )
        return profile

    def ids(self) -> Tuple[str, ...]:
        """Every profile id in the bank, sorted."""
        return tuple(sorted(self.profiles))

    def of_scope(self, scope: str) -> Tuple[SoundProfile, ...]:
        """Every profile of one scope, sorted by id."""
        return tuple(self.profiles[key] for key in self.ids() if self.profiles[key].scope == scope)

    def of_status(self, status: str) -> Tuple[SoundProfile, ...]:
        """Every profile the publishing audit gave one status, sorted by id."""
        return tuple(
            self.profiles[key] for key in self.ids() if self.profiles[key].status == status
        )

    def renderable(self) -> Tuple[SoundProfile, ...]:
        """Every profile this consumer is willing to render, sorted by id."""
        return tuple(self.profiles[key] for key in self.ids() if self.profiles[key].renderable)

    def status_totals(self) -> Dict[str, int]:
        """How many profiles carry each audited status (``"unknown"`` when none was published)."""
        totals: Dict[str, int] = {}
        for profile in self.profiles.values():
            key = profile.status or "unknown"
            totals[key] = totals.get(key, 0) + 1
        return dict(sorted(totals.items()))


def _optional_text(value: Any) -> Optional[str]:
    """A registry string field, or ``None`` when absent/empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _code_tuple(value: Any) -> Tuple[str, ...]:
    """A registry list of condition codes, as a sorted tuple of non-empty strings."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


def _read_json(path: Path, *, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise SoundProfileError(
            f"{what} not found: {path}",
            code=PROFILE_BANK_MISSING if what == "registry.json" else PROFILE_FILE_MISSING,
            detail={"path": str(path)},
        ) from err
    except json.JSONDecodeError as err:
        raise SoundProfileError(
            f"{what} is not valid JSON: {path} ({err})",
            code=PROFILE_BANK_SCHEMA_UNSUPPORTED,
            detail={"path": str(path), "error": str(err)},
        ) from err


def _load_profile_document(path: Path, profile_id: str) -> Dict[str, Any]:
    document = _read_json(path, what=f"profile {profile_id}")
    if not isinstance(document, dict):
        raise SoundProfileError(
            f"profile {profile_id} is not a JSON object: {path}",
            code=PROFILE_INVALID,
            detail={"path": str(path), "profile_id": profile_id},
        )
    schema = document.get("schema")
    if schema != PROFILE_SCHEMA:
        raise SoundProfileError(
            f"profile {profile_id} declares schema {schema!r}; this consumer reads "
            f"{PROFILE_SCHEMA!r}",
            code=PROFILE_INVALID,
            detail={"path": str(path), "profile_id": profile_id, "schema": schema},
        )
    if document.get("profile_id") != profile_id:
        raise SoundProfileError(
            f"profile file {path.name} contains profile_id {document.get('profile_id')!r}, "
            f"but the registry lists it as {profile_id!r}",
            code=PROFILE_INVALID,
            detail={"path": str(path), "profile_id": profile_id},
        )
    return document


def load_sound_profile_bank(
    root: Union[str, Path],
    *,
    verify_fingerprints: bool = True,
    only: Optional[Tuple[str, ...]] = None,
) -> SoundProfileBank:
    """Load and verify a profile bank directory.

    Parameters
    ----------
    root:
        Directory holding ``registry.json`` and ``profiles/``.
    verify_fingerprints:
        Recompute every ``playable_fingerprint`` and refuse a mismatch. Turning this
        off is for debugging only; the CLI never does.
    only:
        Restrict loading to these profile ids (the rest are not read). Unknown ids in
        this list still raise ``PROFILE_NOT_FOUND``, so a typo cannot be ignored.

    Raises
    ------
    SoundProfileError
        With one of the module-level codes. Never returns a partial bank.
    """
    bank_root = Path(root)
    if not bank_root.is_dir():
        raise SoundProfileError(
            f"sound profile bank directory not found: {bank_root}",
            code=PROFILE_BANK_MISSING,
            detail={"bank": str(bank_root)},
        )

    registry_path = bank_root / "registry.json"
    registry = _read_json(registry_path, what="registry.json")
    if not isinstance(registry, dict):
        raise SoundProfileError(
            f"registry.json is not a JSON object: {registry_path}",
            code=PROFILE_BANK_SCHEMA_UNSUPPORTED,
            detail={"path": str(registry_path)},
        )

    schema = registry.get("schema")
    if schema != REGISTRY_SCHEMA:
        raise SoundProfileError(
            f"registry schema {schema!r} is not supported; this consumer reads {REGISTRY_SCHEMA!r}",
            code=PROFILE_BANK_SCHEMA_UNSUPPORTED,
            detail={"path": str(registry_path), "schema": schema},
        )

    entries = registry.get("profiles")
    if not isinstance(entries, list):
        raise SoundProfileError(
            f"registry.json has no 'profiles' list: {registry_path}",
            code=PROFILE_BANK_SCHEMA_UNSUPPORTED,
            detail={"path": str(registry_path)},
        )

    wanted = {str(item) for item in only} if only is not None else None
    profiles: Dict[str, SoundProfile] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            raise SoundProfileError(
                f"registry.json contains a non-object profile entry: {registry_path}",
                code=PROFILE_BANK_SCHEMA_UNSUPPORTED,
                detail={"path": str(registry_path)},
            )
        profile_id = str(entry.get("profile_id") or "")
        if not profile_id:
            raise SoundProfileError(
                f"registry.json contains an entry without a profile_id: {registry_path}",
                code=PROFILE_BANK_SCHEMA_UNSUPPORTED,
                detail={"path": str(registry_path)},
            )
        if wanted is not None and profile_id not in wanted:
            continue

        relative = str(entry.get("file") or f"profiles/{profile_id}.json")
        document = _load_profile_document(bank_root / relative, profile_id)

        expected = str(entry.get("playable_fingerprint") or "")
        if verify_fingerprints:
            actual = playable_fingerprint_of(document)
            if not expected:
                raise SoundProfileError(
                    f"registry entry for {profile_id} publishes no playable_fingerprint",
                    code=PROFILE_INVALID,
                    detail={"profile_id": profile_id},
                )
            if actual != expected:
                raise SoundProfileError(
                    f"profile {profile_id} does not match the fingerprint its registry entry "
                    f"publishes: expected {expected}, recomputed {actual}",
                    code=PROFILE_FINGERPRINT_MISMATCH,
                    detail={
                        "profile_id": profile_id,
                        "expected_fingerprint": expected,
                        "actual_fingerprint": actual,
                        "path": str(bank_root / relative),
                    },
                )

        scope = str(entry.get("scope") or document.get("scope") or "")
        if scope not in KNOWN_SCOPES:
            raise SoundProfileError(
                f"profile {profile_id} declares scope {scope!r}; this consumer implements "
                f"{' and '.join(KNOWN_SCOPES)}",
                code=PROFILE_SCOPE_UNSUPPORTED,
                detail={"profile_id": profile_id, "scope": scope},
            )

        profiles[profile_id] = SoundProfile(
            profile_id=profile_id,
            scope=scope,
            fingerprint=expected or playable_fingerprint_of(document),
            document=document,
            source_file=bank_root / relative,
            status=_optional_text(entry.get("status")),
            blocking_codes=_code_tuple(entry.get("blocking_issues")),
            limitation_codes=_code_tuple(entry.get("limitation_codes")),
            consumer_gap_codes=_code_tuple(entry.get("consumer_gap_codes")),
        )

    if wanted is not None:
        missing = sorted(wanted - set(profiles))
        if missing:
            known = ", ".join(sorted(profiles)) or "(bank is empty)"
            raise SoundProfileError(
                f"sound profile(s) {', '.join(missing)} not found in the bank at {bank_root} — "
                f"known ids: {known}",
                code=PROFILE_NOT_FOUND,
                detail={"profile_id": missing[0], "missing": missing, "bank": str(bank_root)},
            )

    bank_meta = registry.get("bank") or {}
    bank = SoundProfileBank(
        root=bank_root,
        schema=schema,
        profiles=profiles,
        status=str(bank_meta.get("status") or "experimental"),
        note=str(bank_meta.get("note") or ""),
        producer=registry.get("producer") or {},
    )
    logger.debug("Loaded sound profile bank %s: %d profile(s)", bank_root, len(bank.profiles))
    return bank

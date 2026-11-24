"""Loader and validator for the versioned SSOT JSON instrument catalog."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from pydantic import ValidationError

from atari_music.instruments.models import (
    ChannelRoleName,
    InstrumentBehavior,
    InstrumentCatalogDocument,
    InstrumentFamily,
    InstrumentProfile,
)
from atari_music.sound_profiles.bank import SoundProfileError, load_sound_profile_bank

CATALOG_SCHEMA_ID = "atari-music/instrument-catalog/1"
DEFAULT_CATALOG_PATH = Path("src/atari_music/instruments/catalog.json")
_PACKAGED_CATALOG_PACKAGE = "atari_music.instruments"
_PACKAGED_CATALOG_RESOURCE = "catalog.json"

CATALOG_NOT_FOUND = "CATALOG_NOT_FOUND"
CATALOG_JSON_INVALID = "CATALOG_JSON_INVALID"
CATALOG_SCHEMA_UNSUPPORTED = "CATALOG_SCHEMA_UNSUPPORTED"
CATALOG_INTEGRITY_ERROR = "CATALOG_INTEGRITY_ERROR"
INSTRUMENT_NOT_FOUND = "INSTRUMENT_NOT_FOUND"

_REPO_ROOT = Path(__file__).resolve().parents[3]


class CatalogError(ValueError):
    """Structured error raised when loading or validating an instrument catalog."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        errors: Tuple[str, ...] = (),
    ) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.errors = tuple(errors)


class InstrumentCatalog:
    """Immutable indexed lookup over a validated instrument catalog document."""

    def __init__(self, document: InstrumentCatalogDocument) -> None:
        self._document = document
        self._profiles: Dict[str, InstrumentProfile] = {
            prof.instrument_id: prof for prof in document.instruments
        }
        self._behaviors: Dict[str, InstrumentBehavior] = {
            beh.behavior_id: beh for beh in document.behaviors
        }

    @property
    def schema_id(self) -> str:
        return self._document.schema_id

    @property
    def catalog_version(self) -> str:
        return self._document.catalog_version

    @property
    def instruments(self) -> Tuple[InstrumentProfile, ...]:
        return self._document.instruments

    @property
    def behaviors(self) -> Tuple[InstrumentBehavior, ...]:
        return self._document.behaviors

    def has_profile(self, instrument_id: str) -> bool:
        return instrument_id in self._profiles

    def get_profile(self, instrument_id: str) -> InstrumentProfile:
        profile = self._profiles.get(instrument_id)
        if profile is None:
            available = ", ".join(sorted(self._profiles))
            raise CatalogError(
                f"instrument {instrument_id!r} not found in catalog (available: {available})",
                code=INSTRUMENT_NOT_FOUND,
            )
        return profile

    def get_behavior(self, behavior_id: str) -> Optional[InstrumentBehavior]:
        return self._behaviors.get(behavior_id)

    def list_profiles(
        self,
        *,
        family: Optional[InstrumentFamily] = None,
        role: Optional[ChannelRoleName] = None,
    ) -> Tuple[InstrumentProfile, ...]:
        return tuple(
            prof
            for prof in self._document.instruments
            if (family is None or prof.family == family)
            and (role is None or role in prof.intended_roles)
        )

    def list_behaviors(self) -> Tuple[InstrumentBehavior, ...]:
        return self._document.behaviors

    def resolve_profile_behavior(
        self, instrument_id: str
    ) -> Tuple[InstrumentProfile, Optional[InstrumentBehavior]]:
        profile = self.get_profile(instrument_id)
        if profile.behavior_id is None:
            return profile, None
        behavior = self._behaviors.get(profile.behavior_id)
        if behavior is None:
            raise CatalogError(
                f"instrument {instrument_id!r} references missing behavior {profile.behavior_id!r}",
                code=CATALOG_INTEGRITY_ERROR,
            )
        return profile, behavior

    def to_deterministic_json(self) -> str:
        payload = self._document.model_dump(mode="json")
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _resolve_catalog_path(path: Optional[Path]) -> Path:
    candidate = DEFAULT_CATALOG_PATH if path is None else Path(path)
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute():
        repo_candidate = _REPO_ROOT / candidate
        if repo_candidate.is_file() or path is None:
            return repo_candidate
    return candidate


def _resolve_bank_path(bank_dir: Path) -> Path:
    if bank_dir.is_dir():
        return bank_dir
    return _REPO_ROOT / bank_dir


def _parse_and_validate_document(raw: Mapping[str, Any]) -> InstrumentCatalogDocument:
    if not isinstance(raw, Mapping):
        raise CatalogError(
            "catalog root must be a JSON object",
            code=CATALOG_SCHEMA_UNSUPPORTED,
        )
    declared_schema = raw.get("schema_id")
    if declared_schema != CATALOG_SCHEMA_ID:
        raise CatalogError(
            f"unsupported catalog schema_id {declared_schema!r}; expected {CATALOG_SCHEMA_ID!r}",
            code=CATALOG_SCHEMA_UNSUPPORTED,
        )

    # Validate behaviors and profiles independently before full document assembly so
    # an invalid behavior or profile produces clear diagnostics tied to its layer.
    errors: List[str] = []
    raw_behaviors = raw.get("behaviors")
    raw_instruments = raw.get("instruments")
    if not isinstance(raw_behaviors, list):
        errors.append("field 'behaviors' must be a list")
    if not isinstance(raw_instruments, list):
        errors.append("field 'instruments' must be a list")

    seen_behaviors: set[str] = set()
    if isinstance(raw_behaviors, list):
        for idx, item in enumerate(raw_behaviors):
            try:
                beh = InstrumentBehavior.model_validate(item)
                if beh.behavior_id in seen_behaviors:
                    errors.append(f"duplicate behavior_id {beh.behavior_id!r}")
                seen_behaviors.add(beh.behavior_id)
            except ValidationError as exc:
                errors.append(f"behaviors[{idx}]: {exc}")

    seen_instruments: set[str] = set()
    if isinstance(raw_instruments, list):
        for idx, item in enumerate(raw_instruments):
            try:
                prof = InstrumentProfile.model_validate(item)
                if prof.instrument_id in seen_instruments:
                    errors.append(f"duplicate instrument_id {prof.instrument_id!r}")
                seen_instruments.add(prof.instrument_id)
                if prof.behavior_id is not None and prof.behavior_id not in seen_behaviors:
                    errors.append(
                        f"instrument {prof.instrument_id!r} references unknown behavior_id {prof.behavior_id!r}"
                    )
            except ValidationError as exc:
                errors.append(f"instruments[{idx}]: {exc}")

    if errors:
        raise CatalogError(
            f"instrument catalog failed validation ({len(errors)} error(s))",
            code=CATALOG_INTEGRITY_ERROR,
            errors=tuple(errors),
        )

    try:
        return InstrumentCatalogDocument.model_validate(dict(raw))
    except ValidationError as exc:
        raise CatalogError(
            f"instrument catalog document invalid: {exc}",
            code=CATALOG_INTEGRITY_ERROR,
            errors=(str(exc),),
        ) from exc


def _verify_bank_provenance(
    doc: InstrumentCatalogDocument, bank_dir: Path
) -> List[str]:
    """Read-only check of sound_profile_bank provenance against an existing bank."""
    bank_refs = [
        prof for prof in doc.instruments if prof.provenance.source_kind == "sound_profile_bank"
    ]
    if not bank_refs:
        return []

    resolved_bank = _resolve_bank_path(bank_dir)
    wanted_ids = tuple(sorted({str(prof.provenance.profile_id) for prof in bank_refs}))
    try:
        bank = load_sound_profile_bank(
            resolved_bank, verify_fingerprints=True, only=wanted_ids
        )
    except SoundProfileError as exc:
        raise CatalogError(
            f"provenance bank check failed: {exc}",
            code=CATALOG_INTEGRITY_ERROR,
            errors=(str(exc),),
        ) from exc

    warnings: List[str] = []
    errors: List[str] = []
    for prof in bank_refs:
        pid = str(prof.provenance.profile_id)
        fp = str(prof.provenance.profile_fingerprint)
        bank_profile = bank.profiles.get(pid)
        if bank_profile is None:
            errors.append(f"{prof.instrument_id}: profile_id {pid!r} not found in bank")
            continue
        if bank_profile.fingerprint != fp:
            errors.append(
                f"{prof.instrument_id}: provenance fingerprint mismatch for {pid!r} "
                f"(catalog={fp[:12]}..., bank={bank_profile.fingerprint[:12]}...)"
            )
        if bank_profile.status and bank_profile.status != "PLAYABLE":
            warnings.append(
                f"{prof.instrument_id}: bank profile {pid!r} carries status {bank_profile.status!r}"
            )
    if errors:
        raise CatalogError(
            f"provenance mismatch against bank {resolved_bank}",
            code=CATALOG_INTEGRITY_ERROR,
            errors=tuple(errors),
        )
    return warnings


def _parse_catalog_json_text(text: str, source_label: str) -> Mapping[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(
            f"instrument catalog is not valid JSON: {source_label} ({exc})",
            code=CATALOG_JSON_INVALID,
        ) from exc
    if not isinstance(data, Mapping):
        raise CatalogError(
            f"catalog root must be a JSON object: {source_label}",
            code=CATALOG_SCHEMA_UNSUPPORTED,
        )
    return data


def _read_catalog_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise CatalogError(
            f"instrument catalog file not found: {path}",
            code=CATALOG_NOT_FOUND,
        )
    return _parse_catalog_json_text(path.read_text(encoding="utf-8"), str(path))


def _read_packaged_catalog_json() -> Mapping[str, Any]:
    resource = resources.files(_PACKAGED_CATALOG_PACKAGE).joinpath(
        _PACKAGED_CATALOG_RESOURCE
    )
    if not resource.is_file():
        raise CatalogError(
            f"packaged instrument catalog not found: {_PACKAGED_CATALOG_PACKAGE}/{_PACKAGED_CATALOG_RESOURCE}",
            code=CATALOG_NOT_FOUND,
        )
    return _parse_catalog_json_text(
        resource.read_text(encoding="utf-8"),
        f"package://{_PACKAGED_CATALOG_PACKAGE}/{_PACKAGED_CATALOG_RESOURCE}",
    )


def _load_catalog_mapping(path: Optional[Union[Path, str]]) -> Mapping[str, Any]:
    is_default = path is None or Path(path) == DEFAULT_CATALOG_PATH
    resolved = _resolve_catalog_path(None if path is None else Path(path))
    if resolved.is_file():
        return _read_catalog_json(resolved)
    if is_default:
        return _read_packaged_catalog_json()
    raise CatalogError(
        f"instrument catalog file not found: {resolved}",
        code=CATALOG_NOT_FOUND,
    )


def validate_instrument_catalog(
    raw_or_path: Optional[Union[Path, str, Mapping[str, Any]]] = None,
    *,
    bank_dir: Optional[Path] = None,
) -> List[str]:
    """Validate a raw catalog mapping or JSON file path; optionally verify bank provenance."""
    raw_data = (
        _load_catalog_mapping(raw_or_path)
        if raw_or_path is None or isinstance(raw_or_path, (Path, str))
        else raw_or_path
    )
    doc = _parse_and_validate_document(raw_data)
    if bank_dir is not None:
        return _verify_bank_provenance(doc, Path(bank_dir))
    return []


def load_instrument_catalog(
    path: Optional[Path] = None,
    *,
    bank_dir: Optional[Path] = None,
) -> InstrumentCatalog:
    """Load, validate, and optionally provenance-check an SSOT instrument catalog."""
    raw_data = _load_catalog_mapping(path)
    doc = _parse_and_validate_document(raw_data)
    if bank_dir is not None:
        _verify_bank_provenance(doc, Path(bank_dir))
    return InstrumentCatalog(doc)

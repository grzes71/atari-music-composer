"""Preset serialization, validation, and storage primitives for Studio (PySide6-free)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import List, Optional, Tuple
import unicodedata

from pydantic import ValidationError

from atari_music.studio.instruments import InstrumentService
from atari_music.studio.models import (
    PRESET_SCHEMA_ID,
    ArrangementPreset,
    LoadedCompositionState,
    PresetApplyResult,
    PresetRecord,
    PresetScanIssue,
    PresetScanResult,
    StudioArrangementConfig,
)

DEFAULT_PRESETS_DIR = Path.home() / ".atari_music_studio" / "presets"

PRESET_NOT_FOUND = "PRESET_NOT_FOUND"
PRESET_ALREADY_EXISTS = "PRESET_ALREADY_EXISTS"
PRESET_JSON_INVALID = "PRESET_JSON_INVALID"
PRESET_SCHEMA_UNSUPPORTED = "PRESET_SCHEMA_UNSUPPORTED"
PRESET_VALIDATION_ERROR = "PRESET_VALIDATION_ERROR"
PRESET_UNKNOWN_INSTRUMENT = "PRESET_UNKNOWN_INSTRUMENT"
PRESET_INVALID_NAME = "PRESET_INVALID_NAME"
PRESET_STORAGE_ERROR = "PRESET_STORAGE_ERROR"

_WINDOWS_RESERVED_STEMS = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
_SLUG_MAX_LEN = 64
_LATIN_TRANS = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss"})


class PresetError(ValueError):
    """Structured error raised during preset parsing, validation, storage, or application."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        path: Optional[Path] = None,
    ) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.path = path


def preset_slug(name: str) -> str:
    """Convert a preset display *name* into a safe, deterministic filename stem."""
    if not isinstance(name, str):
        raise PresetError("Preset name must be a string.", code=PRESET_INVALID_NAME)
    trimmed = name.strip()
    if not trimmed:
        raise PresetError("Preset name cannot be empty.", code=PRESET_INVALID_NAME)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in trimmed):
        raise PresetError("Preset name cannot contain control characters.", code=PRESET_INVALID_NAME)

    ascii_norm = (
        unicodedata.normalize("NFKD", trimmed.translate(_LATIN_TRANS))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9_-]+", "-", ascii_norm.lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)[:_SLUG_MAX_LEN].strip("-_")

    if not slug or slug in (".", ".."):
        raise PresetError(
            f"Preset name {name!r} produces an empty or unsafe file identifier.",
            code=PRESET_INVALID_NAME,
        )
    if slug.lower() in _WINDOWS_RESERVED_STEMS:
        raise PresetError(
            f"Preset name {name!r} maps to reserved OS filename stem {slug!r}.",
            code=PRESET_INVALID_NAME,
        )
    return slug


def parse_preset_json(raw_text: str, *, source: Optional[Path] = None) -> ArrangementPreset:
    """Parse and strictly validate preset JSON text against ``PRESET_SCHEMA_ID``."""
    if not isinstance(raw_text, str):
        raise PresetError(
            "Preset payload must be a JSON string.",
            code=PRESET_JSON_INVALID,
            path=source,
        )
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PresetError(
            f"Malformed preset JSON: {exc}",
            code=PRESET_JSON_INVALID,
            path=source,
        ) from exc

    if not isinstance(parsed, dict):
        raise PresetError(
            f"Preset JSON root must be an object, got {type(parsed).__name__}.",
            code=PRESET_VALIDATION_ERROR,
            path=source,
        )

    schema_id = parsed.get("schema_id")
    if schema_id != PRESET_SCHEMA_ID:
        raise PresetError(
            f"Unsupported preset schema_id {schema_id!r}; expected {PRESET_SCHEMA_ID!r}.",
            code=PRESET_SCHEMA_UNSUPPORTED,
            path=source,
        )

    try:
        return ArrangementPreset.model_validate(parsed)
    except ValidationError as exc:
        raise PresetError(
            f"Preset schema validation failed: {exc}",
            code=PRESET_VALIDATION_ERROR,
            path=source,
        ) from exc


def serialize_preset_json(preset: ArrangementPreset) -> str:
    """Validate *preset* and serialize it deterministically to formatted JSON."""
    try:
        validated = ArrangementPreset.model_validate(preset.model_dump())
    except ValidationError as exc:
        raise PresetError(
            f"Preset validation failed before serialization: {exc}",
            code=PRESET_VALIDATION_ERROR,
        ) from exc

    if validated.schema_id != PRESET_SCHEMA_ID:
        raise PresetError(
            f"Unsupported preset schema_id {validated.schema_id!r}; expected {PRESET_SCHEMA_ID!r}.",
            code=PRESET_SCHEMA_UNSUPPORTED,
        )
    return json.dumps(validated.model_dump(mode="json"), indent=2) + "\n"


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write raw *data* to *target* via a same-directory temporary file and ``os.replace``."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PresetError(
            f"Cannot create presets directory '{target.parent}': {exc}",
            code=PRESET_STORAGE_ERROR,
            path=target,
        ) from exc

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.stem}_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp_path, target)
    except OSError as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise PresetError(
            f"Failed to write preset file '{target}': {exc}",
            code=PRESET_STORAGE_ERROR,
            path=target,
        ) from exc


def _atomic_write_text(target: Path, content: str) -> None:
    """Write UTF-8 *content* atomically to *target*."""
    _atomic_write_bytes(target, content.encode("utf-8"))


class PresetRepository:
    """Filesystem JSON preset storage rooted strictly inside ``presets_dir``."""

    def __init__(self, presets_dir: Optional[Path] = None) -> None:
        self._presets_dir = Path(presets_dir) if presets_dir is not None else DEFAULT_PRESETS_DIR

    @property
    def presets_dir(self) -> Path:
        return self._presets_dir

    def _resolved_root(self) -> Path:
        return self._presets_dir.resolve()

    def _is_within_root(self, candidate: Path, *, root: Path) -> bool:
        try:
            resolved = candidate.resolve()
        except OSError:
            return False
        return resolved.parent == root and resolved.is_relative_to(root)

    def _resolve_stem_path(self, preset_id: str) -> Path:
        if not isinstance(preset_id, str):
            raise PresetError("Preset identifier must be a string.", code=PRESET_INVALID_NAME)
        raw = preset_id.strip()
        if not raw or "/" in raw or "\\" in raw or "\x00" in raw or ":" in raw:
            raise PresetError(
                f"Invalid preset identifier {preset_id!r}.",
                code=PRESET_INVALID_NAME,
            )
        stem = raw[:-5] if raw.lower().endswith(".json") else raw
        if not stem or stem in (".", "..") or ".." in stem:
            raise PresetError(
                f"Invalid preset identifier {preset_id!r}.",
                code=PRESET_INVALID_NAME,
            )
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in stem):
            raise PresetError(
                f"Preset identifier {preset_id!r} contains control characters.",
                code=PRESET_INVALID_NAME,
            )
        if stem.lower() in _WINDOWS_RESERVED_STEMS:
            raise PresetError(
                f"Preset identifier {preset_id!r} uses a reserved filename stem.",
                code=PRESET_INVALID_NAME,
            )

        root = self._resolved_root()
        candidate = self._presets_dir / f"{stem}.json"
        if candidate.is_symlink() and not self._is_within_root(candidate, root=root):
            raise PresetError(
                f"Refusing symlink pointing outside presets directory: {candidate}",
                code=PRESET_STORAGE_ERROR,
                path=candidate,
            )
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise PresetError(
                f"Cannot resolve preset path for {preset_id!r}: {exc}",
                code=PRESET_STORAGE_ERROR,
                path=candidate,
            ) from exc
        if resolved.parent != root or not resolved.is_relative_to(root):
            raise PresetError(
                f"Preset path escapes repository directory: {preset_id!r}",
                code=PRESET_INVALID_NAME,
                path=candidate,
            )
        return candidate

    def _read_and_parse(self, path: Path) -> ArrangementPreset:
        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PresetError(
                f"Invalid UTF-8 encoding in preset file '{path}': {exc}",
                code=PRESET_JSON_INVALID,
                path=path,
            ) from exc
        except OSError as exc:
            raise PresetError(
                f"Failed to read preset file '{path}': {exc}",
                code=PRESET_STORAGE_ERROR,
                path=path,
            ) from exc
        return parse_preset_json(raw_text, source=path)

    def _find_name_conflict(
        self,
        name: str,
        *,
        exclude_path: Optional[Path] = None,
    ) -> Optional[PresetRecord]:
        target_cf = name.strip().casefold()
        scan = self.list_presets()
        for rec in scan.presets:
            if exclude_path is not None and rec.path.resolve() == exclude_path.resolve():
                continue
            if rec.preset.name.strip().casefold() == target_cf:
                return rec
        return None

    def list_presets(self) -> PresetScanResult:
        """Scan ``presets_dir`` safely, isolating malformed or unsupported JSON files."""
        if not self._presets_dir.exists():
            return PresetScanResult(presets=(), errors=())
        if not self._presets_dir.is_dir():
            raise PresetError(
                f"Presets path '{self._presets_dir}' exists and is not a directory.",
                code=PRESET_STORAGE_ERROR,
                path=self._presets_dir,
            )

        root = self._resolved_root()
        records: List[PresetRecord] = []
        issues: List[PresetScanIssue] = []

        for entry in sorted(self._presets_dir.glob("*.json"), key=lambda p: p.name.lower()):
            if entry.is_symlink() and not self._is_within_root(entry, root=root):
                issues.append(
                    PresetScanIssue(
                        path=entry,
                        code=PRESET_STORAGE_ERROR,
                        message="Skipped symlink pointing outside presets directory.",
                    )
                )
                continue
            if not entry.is_file():
                continue
            try:
                preset = self._read_and_parse(entry)
                records.append(PresetRecord(preset_id=entry.stem, path=entry, preset=preset))
            except PresetError as exc:
                issues.append(PresetScanIssue(path=entry, code=exc.code, message=str(exc)))

        records.sort(key=lambda r: (r.preset.name.casefold(), r.preset_id))
        return PresetScanResult(presets=tuple(records), errors=tuple(issues))

    def load_preset(self, preset_id: str) -> PresetRecord:
        """Load and validate a single preset from ``presets_dir`` by its identifier."""
        target = self._resolve_stem_path(preset_id)
        if not target.exists():
            raise PresetError(
                f"Preset {preset_id!r} not found in '{self._presets_dir}'.",
                code=PRESET_NOT_FOUND,
                path=target,
            )
        if not target.is_file():
            raise PresetError(
                f"Preset path '{target}' is not a regular file.",
                code=PRESET_STORAGE_ERROR,
                path=target,
            )
        preset = self._read_and_parse(target)
        return PresetRecord(preset_id=target.stem, path=target, preset=preset)

    def save_preset(
        self,
        name: str,
        arrangement: StudioArrangementConfig,
        *,
        description: Optional[str] = None,
        overwrite: bool = False,
    ) -> PresetRecord:
        """Persist a validated preset atomically, preserving ``created_at`` on overwrite."""
        slug = preset_slug(name)
        target = self._resolve_stem_path(slug)
        clean_name = name.strip()

        if target.exists():
            if not overwrite:
                raise PresetError(
                    f"Preset {clean_name!r} (id={slug!r}) already exists.",
                    code=PRESET_ALREADY_EXISTS,
                    path=target,
                )
            existing = self._read_and_parse(target)
            now = datetime.now(timezone.utc)
            created_at = existing.created_at or now
        else:
            conflict = self._find_name_conflict(clean_name)
            if conflict is not None:
                raise PresetError(
                    f"A preset named {clean_name!r} already exists at '{conflict.path.name}'.",
                    code=PRESET_ALREADY_EXISTS,
                    path=conflict.path,
                )
            now = datetime.now(timezone.utc)
            created_at = now

        preset = ArrangementPreset(
            name=clean_name,
            description=description,
            arrangement=arrangement.model_copy(deep=True),
            created_at=created_at,
            updated_at=now,
        )
        payload = serialize_preset_json(preset)
        _atomic_write_text(target, payload)
        return PresetRecord(preset_id=target.stem, path=target, preset=preset)

    def rename_preset(
        self,
        preset_id: str,
        new_name: str,
        *,
        overwrite: bool = False,
    ) -> PresetRecord:
        """Rename a preset safely without losing the original file if writing or cleanup fails."""
        src_record = self.load_preset(preset_id)
        src_path = src_record.path
        new_slug = preset_slug(new_name)
        dst_path = self._resolve_stem_path(new_slug)
        clean_new_name = new_name.strip()

        conflict = self._find_name_conflict(clean_new_name, exclude_path=src_path)
        if conflict is not None:
            if conflict.path.resolve() != dst_path.resolve() or not overwrite:
                raise PresetError(
                    f"Cannot rename to {clean_new_name!r}: preset '{conflict.path.name}' already exists.",
                    code=PRESET_ALREADY_EXISTS,
                    path=conflict.path,
                )

        if dst_path != src_path and dst_path.exists() and not overwrite:
            raise PresetError(
                f"Cannot rename to {clean_new_name!r}: target file '{dst_path.name}' already exists.",
                code=PRESET_ALREADY_EXISTS,
                path=dst_path,
            )

        now = datetime.now(timezone.utc)
        created_at = src_record.preset.created_at or now
        updated = src_record.preset.model_copy(
            update={
                "name": clean_new_name,
                "created_at": created_at,
                "updated_at": now,
            }
        )
        payload = serialize_preset_json(updated)

        if dst_path == src_path:
            _atomic_write_text(src_path, payload)
            return PresetRecord(preset_id=src_path.stem, path=src_path, preset=updated)

        dst_backup: Optional[bytes] = None
        if dst_path.exists():
            try:
                dst_backup = dst_path.read_bytes()
            except OSError as exc:
                raise PresetError(
                    f"Failed to read destination backup '{dst_path}' before rename: {exc}",
                    code=PRESET_STORAGE_ERROR,
                    path=dst_path,
                ) from exc

        _atomic_write_text(dst_path, payload)
        try:
            src_path.unlink()
        except OSError as exc:
            # Roll back destination so we neither lose the original nor leave split copies.
            try:
                if dst_backup is not None:
                    _atomic_write_bytes(dst_path, dst_backup)
                else:
                    dst_path.unlink(missing_ok=True)
            except (OSError, PresetError):
                pass
            raise PresetError(
                f"Failed to remove source preset '{src_path}' after rename: {exc}",
                code=PRESET_STORAGE_ERROR,
                path=src_path,
            ) from exc

        return PresetRecord(preset_id=dst_path.stem, path=dst_path, preset=updated)

    def delete_preset(self, preset_id: str) -> Path:
        """Delete one preset file inside ``presets_dir``."""
        target = self._resolve_stem_path(preset_id)
        if not target.exists():
            raise PresetError(
                f"Preset {preset_id!r} not found for deletion.",
                code=PRESET_NOT_FOUND,
                path=target,
            )
        if not target.is_file():
            raise PresetError(
                f"Preset path '{target}' is not a regular file.",
                code=PRESET_STORAGE_ERROR,
                path=target,
            )
        try:
            target.unlink()
        except OSError as exc:
            raise PresetError(
                f"Failed to delete preset '{target}': {exc}",
                code=PRESET_STORAGE_ERROR,
                path=target,
            ) from exc
        return target


def apply_preset_to_state(
    state: LoadedCompositionState,
    preset: ArrangementPreset,
    *,
    instrument_service: InstrumentService,
) -> PresetApplyResult:
    """Validate preset instrument references against catalog and evaluate on immutable *state*."""
    missing: List[Tuple[int, str]] = [
        (ch, inst_id)
        for ch, inst_id in sorted(preset.arrangement.assigned_map().items())
        if not instrument_service.catalog.has_profile(inst_id)
    ]
    if missing:
        details = ", ".join(f"CH{ch}={inst_id!r}" for ch, inst_id in missing)
        raise PresetError(
            f"Preset {preset.name!r} references unknown catalog instrument(s): {details}.",
            code=PRESET_UNKNOWN_INSTRUMENT,
        )

    new_config = preset.arrangement.model_copy(deep=True)
    evaluation = instrument_service.evaluate_arrangement(state, new_config)
    return PresetApplyResult(
        preset=preset,
        config=new_config,
        evaluation=evaluation,
    )

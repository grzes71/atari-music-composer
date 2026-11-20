"""CLI interface for Atari 8-bit Music Analysis Toolkit."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import click

from atari_music import __version__
from atari_music import pokey_hw
from atari_music.logging_config import setup_logging
from atari_music.xex_layout import XexLayoutError


def _set_log_level(ctx: click.Context, param: click.Parameter, value: Optional[str]) -> Optional[str]:
    """Callback to eagerly configure logging level."""
    if value is not None:
        setup_logging(value)
    elif not logging.getLogger().handlers:
        setup_logging()
    return value


def _resolve_profile_binding(
    sound_bank: Optional[Path],
    profile_bindings: Optional[Path],
):
    """Load the optional profile binding and its bank, or return ``(None, None)``.

    Both options are opt-in: without ``--profile-bindings`` nothing is loaded and the
    command behaves exactly as before. A binding is what says *which* voice uses *which*
    profile, so a bank on its own is refused rather than guessed at.
    """
    if profile_bindings is None:
        if sound_bank is not None:
            raise click.ClickException(
                "--sound-bank requires --profile-bindings: a bank lists profiles but does not "
                "say which voice uses which one"
            )
        return None, None

    from atari_music.sound_profiles import (
        SoundProfileError,
        load_profile_binding,
        load_sound_profile_bank,
    )

    try:
        binding = load_profile_binding(profile_bindings)
        bank = load_sound_profile_bank(binding.bank_path(sound_bank))
    except SoundProfileError as err:
        raise click.ClickException(f"{err}")
    return bank, binding


def _bind_result(result, composition, bank, binding):
    """Apply a profile binding to a compiled result, reporting what it changes.

    Every refusal the binding layer makes is turned into a CLI error, so a conflict is
    reported to the user instead of escaping as a traceback.
    """
    from atari_music.sound_profiles import SoundProfileError, apply_profile_binding, describe_binding

    try:
        _echo_binding_report(describe_binding(result, binding, bank, composition=composition))
        return apply_profile_binding(result, binding, bank, composition=composition)
    except SoundProfileError as err:
        raise click.ClickException(f"{err}")


def _echo_binding_report(report: dict) -> None:
    """Print what a profile binding is about to change."""
    click.echo(
        f"Applying sound profile binding from {report['bank']} "
        f"({report['profile_count']} profile(s) in bank):"
    )
    for entry in report["instruments"]:
        click.echo(
            f"  {entry['instrument']} -> {entry['profile_id']} ({entry['scope']}, "
            f"divider {entry['divider_bits']}-bit, clock {entry['clock_mode']}, "
            f"status {entry['status'] or 'unpublished'})"
        )
        click.echo(
            f"      generator {entry['distortion_nibble']} -> AUDC {entry['distortion_audc']} "
            f"[{entry['distortion_source']}], channels {entry['channels']}"
        )
        sources = ", ".join(
            f"{name.replace('_frames', '').replace('_vol', '')}={value['value']}/{value['source']}"
            for name, value in entry["envelope"].items()
        )
        click.echo(f"      envelope {sources}")
        for note in entry["notes"]:
            click.echo(f"      note: {note}")
        for warning in entry["warnings"]:
            click.echo(f"      warning: {warning}")
    click.echo(
        f"  effective AUDCTL {report['audctl_hex']} ({report['audctl_description']}), "
        f"16-bit bass: {report['uses_16bit_bass']}"
    )


# =============================================================================
# Instrument selection (docs/reference/instrument-selection-cli.md)
# =============================================================================
#: The Lead Library schema this consumer reads.
INSTRUMENT_LIBRARY_SCHEMA = "atari-music/instrument-library/1"
#: Where the Lead Library lives when ``--instrument-library`` is not given.
DEFAULT_INSTRUMENT_LIBRARY = "data/instrument_libraries/lead/v0.1"
#: The repository root, used to resolve a library's recorded bank path.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Stable codes for a refused --instrument request ------------------------
INSTRUMENT_LIBRARY_MISSING = "INSTRUMENT_LIBRARY_MISSING"
INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED = "INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED"
INSTRUMENT_LIBRARY_VERSION_MISMATCH = "INSTRUMENT_LIBRARY_VERSION_MISMATCH"
INSTRUMENT_NOT_FOUND = "INSTRUMENT_NOT_FOUND"
INSTRUMENT_TARGET_UNKNOWN = "INSTRUMENT_TARGET_UNKNOWN"
INSTRUMENT_TARGET_AMBIGUOUS = "INSTRUMENT_TARGET_AMBIGUOUS"
INSTRUMENT_TARGET_DUPLICATE = "INSTRUMENT_TARGET_DUPLICATE"
INSTRUMENT_NOT_APPLICABLE = "INSTRUMENT_NOT_APPLICABLE"
INSTRUMENT_SOURCE_DRIFT = "INSTRUMENT_SOURCE_DRIFT"
INSTRUMENT_BINDING_CONFLICT = "INSTRUMENT_BINDING_CONFLICT"
INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX = "INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX"

#: The only library source kind this pipeline can realize: it needs a bank ``SoundProfile``.
_SOURCE_BANK_PROFILE = "bank_profile"
#: A Lead Library entry that is a register transform rather than a measurement. C1 is one.
_SOURCE_EXPERIMENT = "experiment"

#: How a Lead Library entry is realized. A ``bank_profile`` entry yields a profile id that feeds
#: ``apply_profile_binding``; an ``experiment`` entry this data format can realize yields a
#: modulation descriptor that feeds the IR directly.
_SELECT_BANK_PROFILE = "bank_profile"
_SELECT_MODULATION = "modulation"


class InstrumentSelectionError(click.ClickException):
    """A refused ``--instrument`` request, carrying a stable code like ``SoundProfileError``.

    Raised before any output file is written, so a refused run leaves no WAV, ASM or XEX behind.
    """

    def __init__(self, message: str, code: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


def _locate_instrument_library(directory: Optional[Path]) -> Path:
    """The library directory: explicit, else the repository default.

    The default is resolved like ``build-xex`` locates ``player.asm``: relative to the current
    working directory first, then to the repository root, so the command works from either.
    """
    if directory is not None:
        return Path(directory)
    candidate = Path(DEFAULT_INSTRUMENT_LIBRARY)
    if candidate.is_dir():
        return candidate
    return _REPO_ROOT / DEFAULT_INSTRUMENT_LIBRARY


def _load_instrument_library(directory: Optional[Path]) -> Tuple[Path, Dict[str, Any]]:
    """Read and validate a Lead Library document. Returns ``(directory, document)``.

    The version comes from the document, never from the directory name; a disagreement between the
    two is refused rather than silently resolved one way.
    """
    library_dir = _locate_instrument_library(directory)
    path = library_dir / "library.json"
    if not path.is_file():
        raise InstrumentSelectionError(
            f"instrument library not found: {path} (expected a 'library.json' in {library_dir})",
            code=INSTRUMENT_LIBRARY_MISSING,
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise InstrumentSelectionError(
            f"instrument library is not valid JSON: {path} ({err})",
            code=INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED,
        )
    declared = document.get("schema") if isinstance(document, dict) else None
    if not isinstance(document, dict) or declared != INSTRUMENT_LIBRARY_SCHEMA:
        raise InstrumentSelectionError(
            f"instrument library schema {declared!r} is not supported; this consumer reads "
            f"{INSTRUMENT_LIBRARY_SCHEMA!r}",
            code=INSTRUMENT_LIBRARY_SCHEMA_UNSUPPORTED,
        )
    version = document.get("library_version")
    if not isinstance(version, str) or library_dir.name != f"v{version}":
        raise InstrumentSelectionError(
            f"instrument library version mismatch: {path} declares library_version {version!r} "
            f"but lives in a directory named {library_dir.name!r}; the declared version and the "
            "directory name must agree",
            code=INSTRUMENT_LIBRARY_VERSION_MISMATCH,
        )
    return library_dir, document


def _parse_instrument_assignments(values: Sequence[str]) -> List[Tuple[str, str]]:
    """``("part=instrument-id", ...)`` to ``[(part, instrument_id), ...]``.

    Malformed syntax and a repeated part are refused here, before anything is compiled, so a typo
    is reported immediately rather than after a render.
    """
    assignments: List[Tuple[str, str]] = []
    seen: Dict[str, str] = {}
    for value in values:
        part, separator, instrument_id = str(value).partition("=")
        part, instrument_id = part.strip(), instrument_id.strip()
        if not separator or not part or not instrument_id:
            raise InstrumentSelectionError(
                f"--instrument expects PART=INSTRUMENT_ID, got {value!r}",
                code=INSTRUMENT_TARGET_UNKNOWN,
            )
        if part in seen:
            raise InstrumentSelectionError(
                f"--instrument assigns part {part!r} twice ({seen[part]!r} and {instrument_id!r}); "
                "one instrument per part",
                code=INSTRUMENT_TARGET_DUPLICATE,
            )
        seen[part] = instrument_id
        assignments.append((part, instrument_id))
    return assignments


def _modulation_from_library_entry(entry: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    """``(descriptor, generator byte)`` for an experiment entry this format version realizes.

    The Lead Library records C1 as an *experiment*, not a bank profile: it has no profile id and
    none may be invented for it. What it does record is machine-readable enough to act on —
    ``identity.source.implementation`` states the divider schedule and the generator byte. Only
    the one schedule this player implements (the whole note, every note, one frame per value) is
    accepted; anything else returns ``None`` so the caller refuses it rather than approximating
    it. The generator must be a real AUDC nibble, so it can never carry a stray low nibble into
    the ``ora ch_dist,x`` that builds AUDC.
    """
    source = entry.get("identity", {}).get("source", {})
    if not isinstance(source, Mapping) or source.get("kind") != _SOURCE_EXPERIMENT:
        return None
    implementation = source.get("implementation")
    if not isinstance(implementation, Mapping):
        return None
    schedule = implementation.get("schedule_parameters")
    if not isinstance(schedule, Mapping):
        return None
    if schedule.get("hold_frames") != 1:
        return None
    if schedule.get("active_frames") is not None:
        return None
    if schedule.get("active_notes"):
        return None
    generator = implementation.get("generator_byte")
    if not isinstance(generator, str):
        return None
    try:
        distortion = int(generator.strip().lstrip("$"), 16)
    except ValueError:
        return None
    if distortion & 0x0F or distortion > 0xE0:
        return None
    return pokey_hw.MODULATION_OCTAVE_PULSE, distortion


def _resolve_library_entries(
    document: Mapping[str, Any], assignments: Sequence[Tuple[str, str]]
) -> List[Tuple[str, Dict[str, Any], str]]:
    """Pair each requested part with its library entry and how that entry is realized.

    Returns ``(part, entry, kind)``. ``kind`` is ``_SELECT_BANK_PROFILE`` when the entry is a
    measurement this pipeline can bind, and ``_SELECT_MODULATION`` when it is an experiment this
    data format can realize. Anything else is refused rather than approximated.
    """
    entries: Dict[str, Dict[str, Any]] = {}
    for entry in document.get("instruments", []):
        if isinstance(entry, dict) and entry.get("instrument_id"):
            entries[str(entry["instrument_id"])] = entry

    resolved: List[Tuple[str, Dict[str, Any], str]] = []
    for part, instrument_id in assignments:
        entry = entries.get(instrument_id)
        if entry is None:
            raise InstrumentSelectionError(
                f"instrument {instrument_id!r} is not in the library; available: "
                f"{', '.join(sorted(entries))}",
                code=INSTRUMENT_NOT_FOUND,
            )
        source = entry.get("identity", {}).get("source", {})
        if source.get("kind") == _SOURCE_BANK_PROFILE:
            resolved.append((part, entry, _SELECT_BANK_PROFILE))
            continue
        if _modulation_from_library_entry(entry) is not None:
            resolved.append((part, entry, _SELECT_MODULATION))
            continue
        raise InstrumentSelectionError(
            f"instrument {instrument_id!r} is an experimental register transform whose schedule "
            "this player does not implement, and it is not a bank profile, so neither "
            "--profile-bindings nor the modulation path can apply it",
            code=INSTRUMENT_NOT_APPLICABLE,
        )
    return resolved


def _library_bank(resolved: Sequence[Tuple[str, Dict[str, Any]]]) -> Tuple[Path, Tuple[str, ...]]:
    """The bank directory and the profile ids the requested instruments need.

    A library entry records the registry it came from; the bank directory is that file's parent,
    which is what ``load_sound_profile_bank`` expects.
    """
    directories = set()
    profile_ids = set()
    for _part, entry in resolved:
        source = entry["identity"]["source"]
        registry = Path(str(source["registry_path"]))
        directories.add((registry if registry.is_absolute() else _REPO_ROOT / registry).parent)
        profile_ids.add(str(source["profile_id"]))
    if len(directories) > 1:
        raise InstrumentSelectionError(
            "the requested instruments do not come from one bank: "
            + ", ".join(sorted(str(path) for path in directories)),
            code=INSTRUMENT_NOT_APPLICABLE,
        )
    return directories.pop(), tuple(sorted(profile_ids))


def _assert_xex_expressible(song: Any) -> None:
    """Refuse a hardware realization the XEX note table cannot encode.

    The table stores one volume per note and ``player.asm`` rebuilds the envelope at run time, so a
    per-frame volume contour has no representation. This feature never sets one; the guard exists so
    that a library entry which somehow did would be refused here rather than exported as something
    that does not match the rendered WAV.
    """
    contoured = [
        instrument.name for instrument in song.instruments
        if getattr(instrument, "volume_contour", None)
    ]
    if contoured:
        raise InstrumentSelectionError(
            "the XEX note table stores one volume per note and player.asm rebuilds the envelope at "
            f"run time, so a per-frame volume contour cannot be exported: {', '.join(contoured)}",
            code=INSTRUMENT_NOT_EXPRESSIBLE_IN_XEX,
        )


def _resolve_audctl_mode(song) -> int:
    """The song's effective AUDCTL, without importing ``ir`` at module scope."""
    from atari_music.ir import resolve_audctl_mode

    return resolve_audctl_mode(song)


def _apply_modulation_selection(
    result,
    composition,
    modulation_entries: Sequence[Tuple[str, Dict[str, Any]]],
    targets_by_part: Mapping[str, Tuple[int, ...]],
):
    """Write a modulation descriptor — and the entry's own generator — onto the resolved parts.

    This is the other half of the Lead Library. A ``bank_profile`` entry is realized by a
    profile; an ``experiment`` entry is realized by the descriptor and the generator the library
    itself records, applied to the IR instrument the part resolves to. Nothing is invented for
    it, and no bank profile or fingerprint is fabricated.

    Two refusals, both because a modulation is one coherent register configuration and neither
    half of it can be applied partially:

    * a generator the *composition* explicitly declares that disagrees with the entry's own —
      the same rule ``sound_profiles.binding._plan_instrument`` applies to a profile;
    * a part that lands on a channel a 16-bit pair owns, which has no divider of its own to move.
      The MADS exporter refuses such a song too; refusing here means the WAV path cannot quietly
      render an approximation either.
    """
    from atari_music.mads_exporter import joined_channels
    from atari_music.sound_profiles.binding import (
        PROFILE_DISTORTION_CONFLICT,
        _composition_instrument,
        _instrument_channels,
    )

    song = result.pokey_ir
    updates: Dict[int, Dict[str, Any]] = {}
    for part, entry in modulation_entries:
        chosen = _modulation_from_library_entry(entry)
        assert chosen is not None, "only entries that classify are passed here"
        modulation, distortion = chosen
        for ir_id in targets_by_part[part]:
            ir_inst = next(inst for inst in song.instruments if inst.id == ir_id)
            inst_def = _composition_instrument(composition, ir_id)
            explicit = getattr(inst_def, "distortion", None) if inst_def is not None else None
            if explicit is not None and (int(explicit) & 0xE0) != distortion:
                raise InstrumentSelectionError(
                    f"instrument {ir_inst.name!r} ({part!r}) explicitly declares distortion "
                    f"${int(explicit) & 0xE0:02X}, but {entry['instrument_id']!r} is "
                    f"{pokey_hw.describe_modulation(modulation)} and owns the generator "
                    f"${distortion:02X}; a modulation is one coherent register configuration, so "
                    "a partial override is refused rather than merged",
                    code=PROFILE_DISTORTION_CONFLICT,
                )
            updates[ir_id] = {"modulation": modulation, "distortion": distortion}
        click.echo(
            f"  {part} -> {entry['instrument_id']} "
            f"({pokey_hw.describe_modulation(modulation)}, generator ${distortion:02X}, "
            f"IR instrument id(s) {list(targets_by_part[part])})"
        )

    if not updates:
        return result

    new_song = song.model_copy(update={
        "instruments": [
            inst.model_copy(update=updates[inst.id]) if inst.id in updates else inst
            for inst in song.instruments
        ],
    })

    paired = set(joined_channels(_resolve_audctl_mode(new_song)))
    for ir_id in updates:
        clashing = sorted(set(_instrument_channels(new_song, ir_id)) & paired)
        if clashing:
            raise InstrumentSelectionError(
                f"a modulation cannot be applied to instrument id {ir_id} on channel(s) "
                f"{clashing}: a joined 16-bit pair has one divider in two bytes, so it has no "
                "single divider to move. Use an 8-bit channel, or drop --instrument for this part",
                code=INSTRUMENT_NOT_APPLICABLE,
            )

    return result.model_copy(update={"pokey_ir": new_song})


def _apply_instrument_assignments(
    result,
    composition,
    assignments: Sequence[Tuple[str, str]],
    library_dir: Optional[Path],
    file_binding,
):
    """Apply ``--instrument``: a bank profile through the binding path, a modulation through the IR.

    The library is read once and each instrument is resolved to whatever it actually is. A
    ``bank_profile`` entry yields a profile id and is handed to ``apply_profile_binding`` exactly
    as ``--profile-bindings`` would be, so a WAV and a XEX built from the same composition share
    one realization. An ``experiment`` entry this data format can realize yields a modulation
    descriptor, which is written straight onto the resolved IR instrument because no profile
    exists to bind.
    """
    from atari_music.sound_profiles import (
        SoundProfileError,
        load_profile_binding,
        load_sound_profile_bank,
    )
    from atari_music.sound_profiles.binding import BINDING_SCHEMA, _resolve_targets

    _library_dir, document = _load_instrument_library(library_dir)
    resolved = _resolve_library_entries(document, assignments)

    # --instrument and --profile-bindings must not disagree about the same part.
    if file_binding is not None:
        for part, entry, kind in resolved:
            other = file_binding.instruments.get(part)
            if other is None:
                continue
            chosen = (
                str(entry["identity"]["source"]["profile_id"])
                if kind == _SELECT_BANK_PROFILE
                else str(entry["instrument_id"])
            )
            if str(other) != chosen:
                raise InstrumentSelectionError(
                    f"part {part!r} is assigned to {chosen!r} by --instrument and to {other!r} by "
                    "--profile-bindings; one part cannot have two instruments",
                    code=INSTRUMENT_BINDING_CONFLICT,
                )

    # Resolve the parts with the binding layer's own resolver, so a part that resolves under
    # --profile-bindings resolves identically here.
    song = result.pokey_ir
    declared = (
        ", ".join(str(inst.id) for inst in composition.instruments)
        if composition is not None and getattr(composition, "instruments", None)
        else ", ".join(str(inst.name) for inst in song.instruments)
    )
    targets_by_part: Dict[str, Tuple[int, ...]] = {}
    for part, _entry, _kind in resolved:
        targets = _resolve_targets(song, part, composition)
        if not targets:
            raise InstrumentSelectionError(
                f"--instrument names part {part!r}, which the composition does not declare; "
                f"declared parts: {declared}",
                code=INSTRUMENT_TARGET_UNKNOWN,
            )
        if len(targets) > 1:
            raise InstrumentSelectionError(
                f"--instrument names part {part!r}, which matches {len(targets)} instruments in "
                "the composition; use a part id that identifies exactly one",
                code=INSTRUMENT_TARGET_AMBIGUOUS,
            )
        targets_by_part[part] = targets

    bank_entries = [
        (part, entry) for part, entry, kind in resolved if kind == _SELECT_BANK_PROFILE
    ]
    modulation_entries = [
        (part, entry) for part, entry, kind in resolved if kind == _SELECT_MODULATION
    ]

    if bank_entries:
        bank_dir, profile_ids = _library_bank(bank_entries)
        try:
            bank = load_sound_profile_bank(bank_dir, only=profile_ids)
        except SoundProfileError as err:
            raise click.ClickException(f"{err}")

        # The library's recorded fingerprint is a checkable expectation, not decoration.
        for _part, entry in bank_entries:
            source = entry["identity"]["source"]
            actual = bank.get(str(source["profile_id"])).fingerprint
            if str(source.get("profile_fingerprint")) != str(actual):
                raise InstrumentSelectionError(
                    f"instrument {entry['instrument_id']!r} records fingerprint "
                    f"{source.get('profile_fingerprint')!r} for profile {source['profile_id']!r}, "
                    f"but the bank has {actual!r}; the library and the bank disagree",
                    code=INSTRUMENT_SOURCE_DRIFT,
                )

        binding = load_profile_binding({
            "schema": BINDING_SCHEMA,
            "bank": str(bank_dir),
            "instruments": {
                part: str(entry["identity"]["source"]["profile_id"])
                for part, entry in bank_entries
            },
        })
        result = _bind_result(result, composition, bank, binding)

    if modulation_entries:
        result = _apply_modulation_selection(
            result, composition, modulation_entries, targets_by_part
        )
    return result


def _apply_selections(
    result,
    composition,
    file_bank,
    file_binding,
    assignments: Sequence[Tuple[str, str]],
    library_dir: Optional[Path],
    for_xex: bool = False,
):
    """The single place ``--profile-bindings`` and ``--instrument`` reach the IR.

    Both feed the same ``apply_profile_binding`` path, so the WAV and the XEX cannot diverge. With
    neither option the result is returned untouched and the profile package is never imported.
    """
    if file_bank is not None and file_binding is not None:
        result = _bind_result(result, composition, file_bank, file_binding)
    if assignments:
        result = _apply_instrument_assignments(
            result, composition, assignments, library_dir, file_binding
        )
        if for_xex:
            _assert_xex_expressible(result.pokey_ir)
    return result


@click.group()
@click.version_option(
    __version__,
    "-v",
    "--version",
    prog_name="atari-music",
)
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to custom .env configuration file (default: .env).",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default=None,
    envvar="LOG_LEVEL",
    is_eager=True,
    expose_value=True,
    callback=_set_log_level,
    help="Global logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
)
@click.pass_context
def cli(ctx: click.Context, env_file: Optional[Path] = None, log_level: Optional[str] = None) -> None:
    """Atari 8-bit POKEY Music Composer & Toolchain: procedural and AI-assisted music composition, validation, software synthesis, and relocatable MOS 6502 assembly compilation."""
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file



@cli.command("extract", hidden=True)
@click.option(
    "--inventory",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    default=Path("inventory.json"),
    help="Path to inventory.json file",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("dataset"),
    help="Directory where dataset artifacts will be created",
)
@click.option(
    "--asapscan",
    type=click.Path(exists=True, path_type=Path),
    default=Path("tools/asap/asapscan.exe"),
    help="Path to asapscan binary",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=None,
    help="Limit maximum subsongs to process (for testing/benchmarks)",
)
def extract_cmd(
    inventory: Path,
    output_dir: Path,
    asapscan: Path,
    limit: Optional[int],
) -> None:
    """Execute full 3-layer extraction on all SAP files and generate dataset.jsonl."""
    from atari_music.dataset import build_full_dataset

    click.echo(f"Starting full POKEY extraction using inventory {inventory}...")
    success, fail, failed_items = build_full_dataset(
        inventory_path=inventory,
        dataset_dir=output_dir,
        asapscan_bin=str(asapscan),
        max_subsongs=limit,
    )
    click.echo(f"\nExtraction completed!")
    click.echo(f"  Successfully processed subsongs: {success}")
    click.echo(f"  Failed subsongs: {fail}")
    if failed_items:
        click.echo("  Failures:")
        for item in failed_items[:10]:
            click.echo(f"    - {item}")


@cli.command("analyze")
@click.argument("composition_json", type=click.Path(exists=True, path_type=Path))
@click.option("--structure", "-s", is_flag=True, default=False, help="Include detailed macro-structural and form analysis.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output machine-readable JSON to stdout.")
@click.option("--output-json", "-o", type=click.Path(path_type=Path), default=None, help="Save JSON analysis report to file.")
def analyze_cmd(
    composition_json: Path,
    structure: bool,
    as_json: bool,
    output_json: Optional[Path],
) -> None:
    """Analyze musical properties, hardware constraints, and structure of a composition JSON."""
    from atari_music.ai.analysis import analyze_composition
    from atari_music.ai.client import load_composition
    from atari_music.ai.structure_analysis import analyze_composition_structure

    comp_doc = load_composition(composition_json)
    rep = analyze_composition(comp_doc)
    struct_rep = analyze_composition_structure(comp_doc) if structure else None

    if as_json or output_json:
        data = rep.model_dump(mode="json")
        if struct_rep:
            data["macro_structure"] = struct_rep.model_dump(mode="json")
        json_str = json.dumps(data, indent=2)
        if output_json:
            output_json.parent.mkdir(parents=True, exist_ok=True)
            output_json.write_text(json_str, encoding="utf-8")
        if as_json:
            click.echo(json_str)
        elif output_json:
            click.echo(f"Analysis saved to {output_json}")

    if not as_json:
        click.echo(f"=== Composition Analysis: {comp_doc.metadata.title} ===")
        click.echo(f"  Fingerprint (SHA-256): {rep.fingerprint}")
        click.echo(f"  Key/Mode:             {comp_doc.metadata.key} {comp_doc.metadata.mode}")
        click.echo(f"  Tempo:                {comp_doc.metadata.bpm} BPM")
        click.echo(f"  Duration (PAL 50Hz):  {rep.structure.duration_seconds:.2f}s ({rep.structure.sequence_length} steps across {rep.structure.sequence_pattern_count} patterns)")
        click.echo(f"  Repetition Ratio:     {rep.structure.repetition_ratio:.1%}")

        click.echo("\n[Rhythm & Notes]")
        click.echo(f"  Total Notes:          {rep.rhythm.total_notes}")
        click.echo(f"  Note Density:         {rep.rhythm.note_density:.2f} notes/sec")
        click.echo(f"  Rest Ratio:           {rep.rhythm.rest_ratio:.1%}")
        click.echo(f"  Average Note Length:  {rep.rhythm.avg_note_length:.2f} steps")

        click.echo("\n[Melody & Harmony]")
        click.echo(f"  Pitch Range:          {rep.melody.pitch_range_semitones} semitones (MIDI {rep.melody.min_pitch}..{rep.melody.max_pitch})")
        click.echo(f"  Melodic Direction:    {rep.melody.melodic_direction}")
        click.echo(f"  Stepwise vs Leap:     {rep.melody.stepwise_vs_leap_ratio:.2f}")
        click.echo(f"  Consonance Ratio:     {rep.harmony.consonance_ratio:.1%} ({rep.harmony.consonant_intervals_count} consonant / {rep.harmony.dissonant_intervals_count} dissonant)")
        click.echo(f"  Sounding Chords:      {rep.harmony.sounding_chords_count} steps with vertical chords")

        click.echo("\n[POKEY Hardware Utilization]")
        click.echo(f"  Channels Configured:  {comp_doc.hardware.channels}")
        bass_status = f"Yes ({rep.pokey.bass_16bit_channel_usage})" if rep.pokey.uses_16bit_bass else "No"
        click.echo(f"  16-bit Bass Mode:     {bass_status}")
        if rep.pokey.audf_frequency_range:
            click.echo(f"  AUDF Register Range:  {rep.pokey.audf_frequency_range.get('min_audf')} .. {rep.pokey.audf_frequency_range.get('max_audf')}")
        if rep.pokey.warnings:
            click.echo(f"  Warnings ({len(rep.pokey.warnings)}):")
            for w in rep.pokey.warnings:
                click.echo(f"    ! {w}")
        else:
            click.echo("  Hardware Warnings:    None (within safe player bounds)")

        if struct_rep:
            click.echo("\n[Macro-Structure & Form]")
            click.echo(f"  Deduced Form:         {struct_rep.form.compact_form}")
            click.echo(f"  Form Archetype:       {struct_rep.form.archetype}")
            click.echo(f"  Material Reuse Ratio: {struct_rep.material_reuse_ratio:.1%}")
            click.echo(f"  Thematic Variations:  {struct_rep.variation_count} patterns ({struct_rep.variation_ratio:.1%})")
            click.echo(f"  Structural Novelty:   {struct_rep.structural_novelty:.1%}")
            click.echo(f"  Shannon Diversities:  Melody={struct_rep.melodic_diversity:.2f}, Rhythm={struct_rep.rhythmic_diversity:.2f}, Harmony={struct_rep.harmonic_diversity:.2f}")

        if output_json and not as_json:
            click.echo(f"\nSaved JSON report -> {output_json}")


@cli.command("reanalyze-raw", hidden=True)
@click.option(
    "--dataset-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset"),
    help="Path to dataset directory",
)
def reanalyze_raw_cmd(dataset_dir: Path) -> None:
    """Re-analyze features and update dataset.jsonl directly from existing RAW dumps."""
    from atari_music.dataset import reanalyze_dataset_from_raw

    click.echo(f"Re-analyzing dataset from raw dumps in {dataset_dir}...")
    updated = reanalyze_dataset_from_raw(dataset_dir)
    click.echo(f"Successfully re-analyzed {updated} subsongs.")


@cli.command("report", hidden=True)
@click.option(
    "--dataset-jsonl",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset/dataset.jsonl"),
    help="Path to dataset.jsonl file",
)
@click.option(
    "--output-report",
    type=click.Path(path_type=Path),
    default=Path("report_stage2.md"),
    help="Output report markdown path",
)
def report_cmd(dataset_jsonl: Path, output_report: Path) -> None:
    """Generate comprehensive Stage 2 statistical report from dataset.jsonl."""
    from atari_music.reporting import generate_stage2_report

    click.echo(f"Generating Stage 2 report from {dataset_jsonl}...")
    generate_stage2_report(dataset_jsonl, output_report)
    click.echo(f"Saved report to {output_report}")


@cli.command("stage3", hidden=True)
@click.option(
    "--dataset-jsonl",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset/dataset.jsonl"),
    help="Path to dataset.jsonl",
)
@click.option(
    "--visualizations-dir",
    type=click.Path(path_type=Path),
    default=Path("visualizations"),
    help="Output directory for visual dashboards and audio validation",
)
@click.option(
    "--output-report",
    type=click.Path(path_type=Path),
    default=Path("stage3_report.md"),
    help="Output Stage 3 report path",
)
def stage3_cmd(dataset_jsonl: Path, visualizations_dir: Path, output_report: Path) -> None:
    """Execute complete Stage 3 verification, visualization, and report generation."""
    from atari_music.stage3_reporter import run_stage3_pipeline

    click.echo("Running Stage 3 verification pipeline...")
    run_stage3_pipeline(dataset_jsonl, visualizations_dir, output_report)
    click.echo("Stage 3 pipeline complete!")


@cli.command("mine-archetypes", hidden=True)
@click.option(
    "--dataset-jsonl",
    type=click.Path(exists=True, path_type=Path),
    default=Path("dataset/dataset.jsonl"),
    help="Path to dataset.jsonl",
)
@click.option(
    "--output-path",
    type=click.Path(path_type=Path),
    default=Path("dataset/archetypes.json"),
    help="Output JSON path for mined archetype library",
)
def mine_archetypes_cmd(dataset_jsonl: Path, output_path: Path) -> None:
    """Mine empirical melody, rhythm, bass, and percussion archetypes from dataset."""
    from atari_music.archetypes import mine_archetypes_from_dataset

    click.echo(f"Mining musical archetypes from {dataset_jsonl}...")
    lib = mine_archetypes_from_dataset(dataset_jsonl)
    lib.to_json_file(output_path)
    click.echo(f"Archetype library saved to {output_path}")


@cli.command("generate-song", hidden=True)
@click.option("--seed", type=int, default=42, help="RNG seed for procedural generation")
@click.option("--key", type=str, default="C", help="Musical key (C, D, E, F, G, A, B)")
@click.option("--mode", type=str, default="minor", help="Scale mode (minor, major, dorian, pentatonic)")
@click.option("--tempo", type=int, default=125, help="Tempo in BPM")
@click.option("--distortion-style", type=str, default="hybrid", help="pure_a0, gritty_c0, hybrid")
@click.option("--output-json", type=click.Path(path_type=Path), default=Path("generated/song_custom.json"))
@click.option("--output-wav", type=click.Path(path_type=Path), default=Path("generated/song_custom.wav"))
def generate_song_cmd(
    seed: int,
    key: str,
    mode: str,
    tempo: int,
    distortion_style: str,
    output_json: Path,
    output_wav: Path,
) -> None:
    """Generate a single procedural song, save IR JSON, and render POKEY WAV."""
    from atari_music.generator import generate_song
    from atari_music.ir import calculate_ir_binary_size, compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    params = {
        "key": key,
        "mode": mode,
        "tempo": tempo,
        "distortion_style": distortion_style,
    }
    song = generate_song(seed=seed, parameters=params)
    song.to_json_file(output_json)
    size_b = calculate_ir_binary_size(song)
    click.echo(f"Generated song: '{song.title}' -> IR size: {size_b} B (budget: 2048 B)")

    frames = compile_ir_to_pokey_frames(song)
    render_pokey_to_wav(frames, output_wav)
    click.echo(f"Rendered WAV: {output_wav} ({frames.shape[0]/50.0:.2f} seconds)")


@cli.command("run-experiment", hidden=True)
@click.option("--count", "-n", type=int, default=100, help="Number of songs to generate")
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("generated"))
@click.option("--dataset-jsonl", type=click.Path(exists=True, path_type=Path), default=Path("dataset/dataset.jsonl"))
def run_experiment_cmd(count: int, output_dir: Path, dataset_jsonl: Path) -> None:
    """Generate batch of N songs, render WAVs, compute metrics, and compare with REAL dataset."""
    from atari_music.batch_experiment import run_batch_experiment

    run_batch_experiment(count=count, out_dir=output_dir, dataset_jsonl_path=dataset_jsonl)


@cli.command("stage4-report", hidden=True)
@click.option("--summary-json", type=click.Path(exists=True, path_type=Path), default=Path("generated/analysis_summary.json"))
@click.option("--archetypes-json", type=click.Path(exists=True, path_type=Path), default=Path("dataset/archetypes.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage4_report.md"))
def stage4_report_cmd(summary_json: Path, archetypes_json: Path, output_report: Path) -> None:
    """Generate stage4_report.md from batch experiment results and archetype library."""
    from atari_music.stage4_reporter import generate_stage4_report

    click.echo(f"Generating Stage 4 report -> {output_report}...")
    generate_stage4_report(summary_json, archetypes_json, output_report)
    click.echo("Stage 4 report generated successfully!")


@cli.command("prepare-listening-test", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test"))
@click.option("--raw-dir", type=click.Path(exists=True, path_type=Path), default=Path("dataset/raw"))
@click.option("--dataset-jsonl", type=click.Path(exists=True, path_type=Path), default=Path("dataset/dataset.jsonl"))
def prepare_listening_test_cmd(output_dir: Path, raw_dir: Path, dataset_jsonl: Path) -> None:
    """Prepare 30-sample blinded listening test (Group A, B, and C) with WAVs, CSV, and key."""
    from atari_music.listening_test import prepare_listening_test

    prepare_listening_test(output_dir=output_dir, dataset_raw_dir=raw_dir, dataset_jsonl=dataset_jsonl)


@cli.command("stage5-report", hidden=True)
@click.option("--test-dir", type=click.Path(exists=True, path_type=Path), default=Path("listening_test"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage5_report.md"))
def stage5_report_cmd(test_dir: Path, output_report: Path) -> None:
    """Generate stage5_report.md from listening test setup."""
    from atari_music.stage5_reporter import generate_stage5_report

    click.echo(f"Generating Stage 5 report -> {output_report}...")
    generate_stage5_report(test_dir, output_report)
    click.echo("Stage 5 report generated successfully!")


@cli.command("investigate-memorization", hidden=True)
@click.option("--raw-dir", type=click.Path(exists=True, path_type=Path), default=Path("dataset/raw"))
@click.option("--generated-dir", type=click.Path(exists=True, path_type=Path), default=Path("generated"))
@click.option("--output-comp", type=click.Path(path_type=Path), default=Path("generator_comparison.md"))
@click.option("--output-stage5-5", type=click.Path(path_type=Path), default=Path("stage5_5_report.md"))
def investigate_cmd(raw_dir: Path, generated_dir: Path, output_comp: Path, output_stage5_5: Path) -> None:
    """Run full memorization, transposition, and novelty investigation pipeline."""
    from atari_music.run_investigation import run_full_investigation

    click.echo("Starting Stage 5.5 Memorization & Novelty Investigation...")
    run_full_investigation(
        dataset_raw_dir=raw_dir,
        generated_dir=generated_dir,
        output_comparison_md=output_comp,
        output_stage5_5_md=output_stage5_5,
    )
    click.echo("Investigation finished successfully!")


@cli.command("compose-v2", hidden=True)
@click.option("--seed", type=int, default=42, help="RNG seed")
@click.option("--novelty", type=float, default=0.65, help="Novelty parameter (0.0 .. 1.0)")
@click.option("--key", type=str, default="C", help="Musical key")
@click.option("--mode", type=str, default="minor", help="Scale mode")
@click.option("--tempo", type=int, default=130, help="Tempo in BPM")
@click.option("--min-channels", type=int, default=2, help="Minimum active channels")
@click.option("--max-channels", type=int, default=4, help="Maximum active channels")
@click.option("--output-wav", type=click.Path(path_type=Path), default=Path("generated/composer_v2_sample.wav"))
@click.option("--output-json", type=click.Path(path_type=Path), default=Path("generated/composer_v2_sample.json"))
def compose_v2_cmd(
    seed: int,
    novelty: float,
    key: str,
    mode: str,
    tempo: int,
    min_channels: int,
    max_channels: int,
    output_wav: Path,
    output_json: Path,
) -> None:
    """Compose a song using Composer v2 with pure Music IR, interval grammar, and constraints."""
    from atari_music.composer_v2 import ComposerV2Config, compose_song_v2
    from atari_music.ir import compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    cfg = ComposerV2Config(
        seed=seed,
        novelty=novelty,
        key=key,
        mode=mode,
        tempo=tempo,
        min_channels=min_channels,
        max_channels=max_channels,
    )
    res = compose_song_v2(cfg)
    res.pokey_ir.to_json_file(output_json)
    frames = compile_ir_to_pokey_frames(res.pokey_ir)
    render_pokey_to_wav(frames, output_wav)
    click.echo(f"Composed song: {res.music_ir.title}")
    click.echo(f"Quality: {res.quality_report.model_dump()}")
    click.echo(f"Saved: {output_json} & {output_wav}")


@cli.command("run-composer-v2-experiment", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("experiments/composer_v2"))
@click.option("--raw-dir", type=click.Path(exists=True, path_type=Path), default=Path("dataset/raw"))
def run_v2_experiment_cmd(output_dir: Path, raw_dir: Path) -> None:
    """Run full 60-song experiment (novelty 0.50, 0.65, 0.80) and generate summary."""
    from atari_music.composer_v2_experiment import run_composer_v2_experiments

    run_composer_v2_experiments(base_out_dir=output_dir, dataset_raw_dir=raw_dir)


@cli.command("stage6-report", hidden=True)
@click.option("--summary-json", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v2/summary.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage6_composer_v2_report.md"))
def stage6_report_cmd(summary_json: Path, output_report: Path) -> None:
    """Generate stage6_composer_v2_report.md from experiment results."""
    from atari_music.stage6_reporter import generate_stage6_report

    click.echo(f"Generating Stage 6 report -> {output_report}...")
    generate_stage6_report(summary_json, output_report)
    click.echo("Stage 6 report generated successfully!")


@cli.command("prepare-listening-test-v2", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test_v2"))
@click.option("--seed", type=int, default=2026, help="Randomization seed for anonymization")
def prepare_listening_test_v2_cmd(output_dir: Path, seed: int) -> None:
    """Prepare 80-sample blinded listening test (Group A, B, C, D) with WAVs, CSV, and keys."""
    from atari_music.listening_test_v2 import prepare_listening_test_v2, validate_listening_test_v2

    click.echo(f"Preparing Stage 6.5 blind listening test in '{output_dir}'...")
    res = prepare_listening_test_v2(output_dir=output_dir, seed=seed)
    click.echo(f"Successfully copied and randomized {res['total_samples']} samples!")
    click.echo("Running pre-flight validation checks...")
    val = validate_listening_test_v2(output_dir)
    click.echo(f"Validation status: {val['status']}")


@cli.command("validate-listening-test-v2", hidden=True)
@click.option("--test-dir", type=click.Path(exists=True, path_type=Path), default=Path("listening_test_v2"))
def validate_listening_test_v2_cmd(test_dir: Path) -> None:
    """Run rigorous sanity checks on listening_test_v2 artifacts."""
    from atari_music.listening_test_v2 import validate_listening_test_v2

    click.echo(f"Validating test artifacts in '{test_dir}'...")
    val = validate_listening_test_v2(test_dir)
    click.echo(f"{val['status']}")
    click.echo(f"Distribution: {val['group_distribution']}")
    click.echo(f"Peak bounds: {val['peak_range']}, RMS bounds: {val['rms_range']}")


@cli.command("stage6-5-report", hidden=True)
@click.option("--test-dir", type=click.Path(exists=True, path_type=Path), default=Path("listening_test_v2"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage6_5_listening_report.md"))
def stage6_5_report_cmd(test_dir: Path, output_report: Path) -> None:
    """Generate stage6_5_listening_report.md from listening test v2 setup."""
    from atari_music.listening_test_v2 import generate_stage6_5_report

    click.echo(f"Generating Stage 6.5 report -> {output_report}...")
    generate_stage6_5_report(test_dir, output_report)
    click.echo("Stage 6.5 report generated successfully!")


@cli.command("audit-diversity", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test_v2_selected"))
@click.option("--report-path", type=click.Path(path_type=Path), default=Path("stage6_6_diversity_report.md"))
def audit_diversity_cmd(output_dir: Path, report_path: Path) -> None:
    """Run full Diversity Audit (Stage 6.6) across 80 tracks and build selected 30-track suite."""
    from atari_music.diversity_audit import (
        extract_all_80_track_features,
        compute_similarity_matrices,
        run_clustering,
        select_30_diverse_tracks,
        create_selected_test_suite,
        generate_diversity_report,
    )

    click.echo("Extracting features from all 80 generated tracks...")
    tracks = extract_all_80_track_features()
    click.echo(f"Extracted features for {len(tracks)} tracks.")

    click.echo("Computing multidimensional similarity & distance matrices...")
    sim_data = compute_similarity_matrices(tracks)

    click.echo("Running clustering and silhouette analysis...")
    clust_res = run_clustering(sim_data["overall_dist"], tracks)
    click.echo(f"Optimal clusters found: k={clust_res['best_k']} (Silhouette: {clust_res['best_silhouette']})")

    click.echo("Selecting 30 most diverse & representative tracks across all groups...")
    selected = select_30_diverse_tracks(tracks, sim_data["overall_dist"])
    click.echo(f"Selected {len(selected)} diverse tracks.")

    click.echo(f"Creating selected test suite in '{output_dir}'...")
    suite_info = create_selected_test_suite(selected, output_dir=output_dir)
    click.echo(f"Created suite with {suite_info['selected_count']} WAVs and answer key.")

    click.echo(f"Generating Diversity Audit Report -> {report_path}...")
    generate_diversity_report(tracks, sim_data, clust_res, selected, report_path)
    click.echo("Stage 6.6 Diversity Report generated successfully!")


@cli.command("compose-v3", hidden=True)
@click.option("--profile", "-p", type=str, default="title", help="Music profile: title, exploration, action, funny, dungeon, ending")
@click.option("--seed", "-s", type=int, default=42, help="Deterministic RNG seed")
@click.option("--tempo", type=int, default=None, help="Optional tempo BPM override")
@click.option("--key", "-k", type=str, default=None, help="Key override (C, D, E, F, G, A, B)")
@click.option("--mode", "-m", type=str, default=None, help="Mode override (minor, major, dorian, mixolydian)")
@click.option("--novelty", type=float, default=None, help="Novelty override (0.0 .. 1.0)")
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Path for output JSON")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Path for output WAV")
def compose_v3_cmd(
    profile: str,
    seed: int,
    tempo: Optional[int],
    key: Optional[str],
    mode: Optional[str],
    novelty: Optional[float],
    output_json: Optional[Path],
    output_wav: Optional[Path],
) -> None:
    """Compose a song using Composer v3 with specified profile."""
    from atari_music.composer_v3 import compose_song_v3
    from atari_music.ir import compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    res = compose_song_v3(
        profile=profile,
        seed=seed,
        tempo=tempo,
        key=key,
        mode=mode,
        novelty=novelty,
    )

    q = res.quality_report
    click.echo(f"Composed [{res.profile_name.upper()}]: '{res.music_ir.title}'")
    click.echo(f"Tempo: {q.tempo} BPM, Form: {q.form}, Dur: {q.duration:.1f}s, Mem: {q.memory_size} B, Channels: {q.channels_used}")

    if output_json:
        res.pokey_ir.to_json_file(output_json)
        click.echo(f"Saved POKEY IR -> {output_json}")

    if output_wav:
        frames = compile_ir_to_pokey_frames(res.pokey_ir)
        render_pokey_to_wav(frames, output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")


@cli.command("run-composer-v3-experiment", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("experiments/composer_v3"))
def run_composer_v3_experiment_cmd(output_dir: Path) -> None:
    """Run 18-track experiment across all 6 profiles (3 tracks per profile)."""
    from atari_music.composer_v3_experiment import run_composer_v3_experiment

    click.echo(f"Running Composer v3 experiment -> {output_dir}...")
    run_composer_v3_experiment(output_dir=output_dir)
    click.echo("Composer v3 experiment completed successfully!")


@cli.command("stage7-report", hidden=True)
@click.option("--summary-json", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v3/summary.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage7_composer_v3_report.md"))
def stage7_report_cmd(summary_json: Path, output_report: Path) -> None:
    """Generate stage7_composer_v3_report.md from experiment results."""
    from atari_music.stage7_reporter import generate_stage7_report

    click.echo(f"Generating Stage 7 report -> {output_report}...")
    generate_stage7_report(summary_json, output_report)
    click.echo("Stage 7 report generated successfully!")


@cli.command("prepare-listening-test-v3", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("listening_test_v3"))
@click.option("--seed", type=int, default=42)
def prepare_listening_test_v3_cmd(output_dir: Path, seed: int) -> None:
    """Prepare Stage 7.1 blind listening test suite with 18 randomized WAVs."""
    from atari_music.listening_test_v3 import prepare_listening_test_v3

    click.echo(f"Preparing Stage 7.1 listening test suite -> {output_dir}...")
    res = prepare_listening_test_v3(output_dir=output_dir, seed=seed)
    click.echo(f"Generated {res['total_samples']} randomized samples and templates successfully!")


@cli.command("stage7-1-report", hidden=True)
@click.option("--test-dir", type=click.Path(path_type=Path), default=Path("listening_test_v3"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage7_1_listening_report.md"))
def stage7_1_report_cmd(test_dir: Path, output_report: Path) -> None:
    """Execute perceptual audit and generate stage7_1_listening_report.md."""
    from atari_music.listening_test_v3 import execute_full_stage7_1_validation

    click.echo("Running Stage 7.1 perceptual audit and generating report...")
    res = execute_full_stage7_1_validation(base_dir=Path("."))
    click.echo(f"Report generated successfully -> {res['report_path']}")


@cli.command("compose")
@click.option("--profile", "-p", type=str, default="action", help="Music profile: title, exploration, action, funny, dungeon, ending")
@click.option("--seed", "-s", type=int, default=1234, help="Deterministic RNG seed")
@click.option("--key", "-k", type=str, default=None, help="Root key (C, D, E, F, G, A, B)")
@click.option("--tempo", "-t", type=int, default=None, help="Tempo in BPM (50..240)")
@click.option("--length", "-l", type=click.Choice(["short", "medium", "long"], case_sensitive=False), default=None, help="Duration intent: short, medium, long")
@click.option("--intensity", type=float, default=None, help="Expected intensity (0.0 .. 1.0)")
@click.option("--variation", "-v", type=float, default=None, help="Motivic variation level (0.0 .. 1.0)")
@click.option(
    "--channel-instrument",
    "channel_instruments_raw",
    multiple=True,
    metavar="CH=INSTRUMENT_ID",
    help="Assign SSOT catalog instrument to channel 1..4 or role (e.g. 1=bass_poly4_punch, 3=lead_attack_bite).",
)
@click.option(
    "--program-change",
    "program_changes_raw",
    multiple=True,
    metavar="CH@TARGET[:NOTE]=INSTRUMENT_ID",
    help="Schedule mid-song PROGRAM_CHANGE (e.g. 3@B=lead_attack_bite or 4@1:2=perc_snare_crisp).",
)
@click.option(
    "--instrument-catalog",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional SSOT instrument catalog JSON path (default: data/instruments/catalog.json).",
)
@click.option(
    "--player-version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target player format version for MADS export & validation (default: auto).",
)
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Path for output JSON")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Path for output WAV")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Path for output MADS assembly (.asm)")
def compose_cmd(
    profile: str,
    seed: int,
    key: Optional[str],
    tempo: Optional[int],
    length: Optional[str],
    intensity: Optional[float],
    variation: Optional[float],
    channel_instruments_raw: Tuple[str, ...],
    program_changes_raw: Tuple[str, ...],
    instrument_catalog: Optional[Path],
    player_version: str,
    output_json: Optional[Path],
    output_wav: Optional[Path],
    output_asm: Optional[Path],
) -> None:
    """Generate Atari POKEY music via the public Music Generation API."""
    from atari_music.api import generate_music
    from atari_music.instruments import (
        CatalogError,
        InstrumentPlanError,
        parse_channel_instrument_specs,
        parse_program_change_specs,
        resolve_export_format_version,
    )
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError, export_mads_asm

    ch_map = None
    pc_specs = None
    try:
        if channel_instruments_raw:
            ch_map = parse_channel_instrument_specs(channel_instruments_raw)
        if program_changes_raw:
            pc_specs = parse_program_change_specs(program_changes_raw)

        res = generate_music(
            profile=profile,
            seed=seed,
            key=key,
            tempo=tempo,
            length=length,
            intensity=intensity,
            variation=variation,
            channel_instruments=ch_map,
            program_changes=pc_specs,
            instrument_catalog_path=instrument_catalog,
            player_version=player_version,
        )
    except (InstrumentPlanError, CatalogError, ValueError) as err:
        raise click.ClickException(str(err)) from err

    m = res.metadata
    click.echo(f"Generated [{m.profile.upper()}]: '{res.music_ir.title}' (Seed: {m.seed})")
    click.echo(
        f"Key: {m.key} {m.mode}, Tempo: {m.tempo} BPM, Form: {m.form}, "
        f"Dur: {m.duration:.1f}s, Mem: {m.memory_size_bytes} B, Channels: {m.channels_used}, Format: v{m.format_version}"
    )

    if output_json:
        res.save_json(output_json)
        click.echo(f"Saved POKEY IR -> {output_json}")

    if output_wav:
        res.render_wav(output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")

    if output_asm:
        try:
            export_ver = resolve_export_format_version(res.pokey_ir, player_version)
            export_mads_asm(res, output_asm, format_version=export_ver)
        except (FormatVersionError, StreamValidationError, InstrumentPlanError) as err:
            raise click.ClickException(str(err)) from err
        click.echo(f"Exported MADS ASM (v{export_ver}) -> {output_asm}")


@cli.command("export-mads")
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output-asm", "-o", type=click.Path(path_type=Path), required=True, help="Destination MADS assembly path")
@click.option(
    "--player-version", "--format-version",
    "player_version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target player format version (auto, v1, v2; default: auto preserves v1 when sufficient)",
)
def export_mads_cmd(input_json: Path, output_asm: Path, player_version: str) -> None:
    """Convert an existing POKEY IR JSON into relocatable MADS assembly data."""
    from atari_music.instruments import InstrumentPlanError, resolve_export_format_version
    from atari_music.ir import IRSong
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError, export_mads_asm

    song = IRSong.from_json_file(input_json)
    try:
        export_ver = resolve_export_format_version(song, player_version)
        export_mads_asm(song, output_asm, format_version=export_ver)
    except (FormatVersionError, StreamValidationError, InstrumentPlanError) as err:
        raise click.ClickException(str(err)) from err
    click.echo(f"Successfully exported '{song.title}' (v{export_ver}) -> {output_asm}")


@cli.command("compose-v4", hidden=True)
@click.option("--profile", "-p", type=str, default="title", help="Music profile: title, exploration, action, funny, dungeon, ending")
@click.option("--seed", "-s", type=int, default=42, help="Deterministic RNG seed")
@click.option("--tempo", type=int, default=None, help="Optional tempo BPM override")
@click.option("--key", "-k", type=str, default=None, help="Key override (C, D, E, F, G, A, B)")
@click.option("--mode", "-m", type=str, default=None, help="Mode override (minor, major, dorian, mixolydian)")
@click.option("--novelty", type=float, default=None, help="Novelty override (0.0 .. 1.0)")
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Path for output JSON")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Path for output WAV")
def compose_v4_cmd(
    profile: str,
    seed: int,
    tempo: Optional[int],
    key: Optional[str],
    mode: Optional[str],
    novelty: Optional[float],
    output_json: Optional[Path],
    output_wav: Optional[Path],
) -> None:
    """Compose a song using Composer v4 with specified profile."""
    from atari_music.composer_v4 import compose_song_v4
    from atari_music.ir import compile_ir_to_pokey_frames
    from atari_music.pokey_synth import render_pokey_to_wav

    res = compose_song_v4(
        profile=profile,
        seed=seed,
        tempo=tempo,
        key=key,
        mode=mode,
        novelty=novelty,
    )

    q = res.quality_report
    click.echo(f"Composed [{res.profile_name.upper()}]: '{res.music_ir.title}'")
    click.echo(f"Tempo: {q.tempo} BPM, Form: {q.form}, Dur: {q.duration:.1f}s, Mem: {q.memory_size} B, Channels: {q.channels_used}")
    click.echo(f"Section Voice Counts: {q.section_channel_counts}")

    if output_json:
        res.pokey_ir.to_json_file(output_json)
        click.echo(f"Saved POKEY IR -> {output_json}")

    if output_wav:
        frames = compile_ir_to_pokey_frames(res.pokey_ir)
        render_pokey_to_wav(frames, output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")


@cli.command("run-composer-v4-experiment", hidden=True)
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("experiments/composer_v4"))
def run_composer_v4_experiment_cmd(output_dir: Path) -> None:
    """Run 18-track experiment across all 6 profiles for Composer v4."""
    from atari_music.composer_v4_experiment import run_composer_v4_experiment

    click.echo(f"Running Composer v4 experiment -> {output_dir}...")
    run_composer_v4_experiment(output_dir=output_dir)
    click.echo("Composer v4 experiment completed successfully!")


@cli.command("stage8-report", hidden=True)
@click.option("--v3-summary", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v3/summary.json"))
@click.option("--v4-summary", type=click.Path(exists=True, path_type=Path), default=Path("experiments/composer_v4/summary.json"))
@click.option("--output-report", type=click.Path(path_type=Path), default=Path("stage8_composer_v4_report.md"))
def stage8_report_cmd(v3_summary: Path, v4_summary: Path, output_report: Path) -> None:
    """Generate stage8_composer_v4_report.md comparing v3 and v4 results."""
    from atari_music.stage8_reporter import generate_stage8_report

    click.echo(f"Generating Stage 8 report -> {output_report}...")
    generate_stage8_report(v3_summary, v4_summary, output_report)
    click.echo("Stage 8 report generated successfully!")


@cli.command("import-json")
@click.argument("composition_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Render and save audio WAV")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Export MADS assembly file")
@click.option("--output-ir", type=click.Path(path_type=Path), default=None, help="Export POKEY IR JSON")
@click.option(
    "--sound-bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Optional POKEY sound profile bank directory (registry.json + profiles/)",
)
@click.option(
    "--profile-bindings",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional binding file mapping composition instrument -> profile id",
)
@click.option(
    "--instrument",
    "instrument",
    multiple=True,
    metavar="PART=INSTRUMENT_ID",
    help="Assign a Lead Library instrument to a composition part (repeatable). PART is the "
         "composition's instrument id; INSTRUMENT_ID is a Lead Library instrument_id.",
)
@click.option(
    "--instrument-library",
    "instrument_library",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help=f"Optional Lead Library directory (default: {DEFAULT_INSTRUMENT_LIBRARY})",
)
@click.option(
    "--player-version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target MADS export format version (auto, v1, v2; default: auto)",
)
def import_json_cmd(
    composition_json: Path,
    output_wav: Optional[Path],
    output_asm: Optional[Path],
    output_ir: Optional[Path],
    sound_bank: Optional[Path],
    profile_bindings: Optional[Path],
    instrument: Tuple[str, ...],
    instrument_library: Optional[Path],
    player_version: str,
) -> None:
    """Validate and import an AI composition JSON document."""
    from atari_music.ai.client import load_composition_json, generate_music_from_composition
    from atari_music.ai.schema import MusicCompositionError
    from atari_music.instruments import InstrumentPlanError, resolve_export_format_version
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError, export_mads_asm

    assignments = _parse_instrument_assignments(instrument)

    click.echo(f"Validating and loading JSON composition from {composition_json}...")
    try:
        comp = load_composition_json(composition_json)
    except json.JSONDecodeError as err:
        raise click.ClickException(f"Failed to parse JSON in '{composition_json}': {err}")
    except MusicCompositionError as err:
        raise click.ClickException(f"Validation failed for '{composition_json}': {err}")

    click.echo(f"Loaded successfully!")
    click.echo(f"  Title: {comp.metadata.title} (Author: {comp.metadata.author or 'Unknown'})")
    click.echo(f"  Key: {comp.metadata.key} {comp.metadata.mode}, BPM: {comp.metadata.bpm}")
    click.echo(f"  Channels: {comp.hardware.channels}, 16-bit bass: {comp.hardware.use_16bit_bass}")
    click.echo(f"  Patterns: {len(comp.patterns)}, Sequence: {' -> '.join(comp.sequence)}")

    bank, binding = _resolve_profile_binding(sound_bank, profile_bindings)

    if output_wav or output_asm or output_ir:
        click.echo("Compiling composition through Music IR & POKEY IR...")
        res = generate_music_from_composition(comp)
        res = _apply_selections(
            res, comp, bank, binding, assignments, instrument_library
        )
        if output_ir:
            res.save_json(output_ir)
            click.echo(f"Saved POKEY IR -> {output_ir}")
        if output_wav:
            res.render_wav(output_wav)
            click.echo(f"Rendered WAV -> {output_wav}")
        if output_asm:
            try:
                export_ver = resolve_export_format_version(res.pokey_ir, player_version)
                export_mads_asm(res.pokey_ir, output_asm, format_version=export_ver)
            except (FormatVersionError, StreamValidationError, InstrumentPlanError) as err:
                raise click.ClickException(str(err)) from err
            click.echo(f"Exported MADS ASM (v{export_ver}) -> {output_asm}")


@cli.command("import-dsl")
@click.argument("composition_dsl", type=click.Path(exists=True, path_type=Path))
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Render and save audio WAV")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Export MADS assembly file")
@click.option("--output-ir", type=click.Path(path_type=Path), default=None, help="Export POKEY IR JSON")
@click.option("--output-json", type=click.Path(path_type=Path), default=None, help="Export canonical composition JSON")
@click.option(
    "--sound-bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Optional POKEY sound profile bank directory (registry.json + profiles/)",
)
@click.option(
    "--profile-bindings",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional binding file mapping composition instrument -> profile id",
)
@click.option(
    "--instrument",
    "instrument",
    multiple=True,
    metavar="PART=INSTRUMENT_ID",
    help="Assign a Lead Library instrument to a composition part (repeatable). PART is the "
         "composition's instrument id; INSTRUMENT_ID is a Lead Library instrument_id.",
)
@click.option(
    "--instrument-library",
    "instrument_library",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help=f"Optional Lead Library directory (default: {DEFAULT_INSTRUMENT_LIBRARY})",
)
@click.option(
    "--player-version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target MADS export format version (auto, v1, v2; default: auto)",
)
def import_dsl_cmd(
    composition_dsl: Path,
    output_wav: Optional[Path],
    output_asm: Optional[Path],
    output_ir: Optional[Path],
    output_json: Optional[Path],
    sound_bank: Optional[Path],
    profile_bindings: Optional[Path],
    instrument: Tuple[str, ...],
    instrument_library: Optional[Path],
    player_version: str,
) -> None:
    """Validate and import an AI composition Music DSL document."""
    from atari_music.ai.client import load_composition_dsl, generate_music_from_composition
    from atari_music.ai.schema import MusicCompositionError
    from atari_music.instruments import InstrumentPlanError, resolve_export_format_version
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError, export_mads_asm

    assignments = _parse_instrument_assignments(instrument)

    click.echo(f"Validating and loading Music DSL from {composition_dsl}...")
    try:
        comp = load_composition_dsl(composition_dsl)
    except MusicCompositionError as err:
        raise click.ClickException(f"Failed to parse/validate Music DSL in '{composition_dsl}': {err}")

    click.echo(f"Loaded successfully!")
    click.echo(f"  Title: {comp.metadata.title} (Author: {comp.metadata.author or 'Unknown'})")
    click.echo(f"  Key: {comp.metadata.key} {comp.metadata.mode}, BPM: {comp.metadata.bpm}")
    click.echo(f"  Channels: {comp.hardware.channels}, 16-bit bass: {comp.hardware.use_16bit_bass}")
    click.echo(f"  Patterns: {len(comp.patterns)}, Sequence: {' -> '.join(comp.sequence)}")

    bank, binding = _resolve_profile_binding(sound_bank, profile_bindings)

    if output_json:
        comp_json = comp.model_dump_json(indent=2)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(comp_json, encoding="utf-8")
        click.echo(f"Saved Composition JSON -> {output_json}")

    if output_wav or output_asm or output_ir:
        click.echo("Compiling composition through Music IR & POKEY IR...")
        res = generate_music_from_composition(comp)
        res = _apply_selections(
            res, comp, bank, binding, assignments, instrument_library
        )
        if output_ir:
            res.save_json(output_ir)
            click.echo(f"Saved POKEY IR -> {output_ir}")
        if output_wav:
            res.render_wav(output_wav)
            click.echo(f"Rendered WAV -> {output_wav}")
        if output_asm:
            try:
                export_ver = resolve_export_format_version(res.pokey_ir, player_version)
                export_mads_asm(res.pokey_ir, output_asm, format_version=export_ver)
            except (FormatVersionError, StreamValidationError, InstrumentPlanError) as err:
                raise click.ClickException(str(err)) from err
            click.echo(f"Exported MADS ASM (v{export_ver}) -> {output_asm}")


@cli.command("build-xex")
@click.argument("composition_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("output.xex"), help="Output Atari XEX binary path")
@click.option("--format", "composition_format", type=click.Choice(["json", "dsl"], case_sensitive=False), default=None, help="Input format: 'json' or 'dsl' (defaults to json or inferred if omitted)")
@click.option("--player-address", type=str, default="0x6000", help="Relocatable player address (hex or dec, e.g. 0x6000)")
@click.option("--music-address", type=str, default="0x8000", help="Relocatable music data address (hex or dec, e.g. 0x8000)")
@click.option("--zp-base", type=str, default="0x80", help="Zero-page base address (hex or dec, e.g. 0x80)")
@click.option("--mads", type=click.Path(path_type=Path), default=Path("tools/mads/mads.exe"), help="Path to mads.exe")
@click.option("--player-asm", type=click.Path(exists=True, path_type=Path), default=None, help="Path to player.asm (defaults to current directory or repository root)")
@click.option(
    "--sound-bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Optional POKEY sound profile bank directory (registry.json + profiles/)",
)
@click.option(
    "--profile-bindings",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional binding file mapping composition instrument -> profile id",
)
@click.option(
    "--instrument",
    "instrument",
    multiple=True,
    metavar="PART=INSTRUMENT_ID",
    help="Assign a Lead Library instrument to a composition part (repeatable). PART is the "
         "composition's instrument id; INSTRUMENT_ID is a Lead Library instrument_id.",
)
@click.option(
    "--instrument-library",
    "instrument_library",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help=f"Optional Lead Library directory (default: {DEFAULT_INSTRUMENT_LIBRARY})",
)
@click.option(
    "--player-version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target MADS export format version (auto, v1, v2; default: auto)",
)
def build_xex_cmd(
    composition_file: Path,
    output: Path,
    composition_format: Optional[str],
    player_address: str,
    music_address: str,
    zp_base: str,
    mads: Path,
    player_asm: Optional[Path],
    sound_bank: Optional[Path],
    profile_bindings: Optional[Path],
    instrument: Tuple[str, ...],
    instrument_library: Optional[Path],
    player_version: str,
) -> None:
    """Compile AI composition (JSON or Music DSL) directly to relocatable Atari XEX binary using MADS."""
    from atari_music.ai.client import build_xex_from_composition
    from atari_music.instruments import InstrumentPlanError
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError

    def parse_addr(val: str) -> int:
        s = val.strip()
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s)

    p_addr = parse_addr(player_address)
    m_addr = parse_addr(music_address)
    z_addr = parse_addr(zp_base)

    assignments = _parse_instrument_assignments(instrument)
    bank, binding = _resolve_profile_binding(sound_bank, profile_bindings)

    def result_transform(result, composition):
        """The same profile-aware IR the WAV path uses, so XEX cannot diverge from it."""
        return _apply_selections(
            result, composition, bank, binding, assignments, instrument_library, for_xex=True
        )

    fmt_label = f" ({composition_format.upper()})" if composition_format else ""
    click.echo(f"Building Atari XEX from {composition_file}{fmt_label}...")
    click.echo(f"  Configuration: player=${p_addr:04X}, music=${m_addr:04X}, ZP=${z_addr:02X}")
    try:
        xex_path = build_xex_from_composition(
            composition_file,
            output_xex=output,
            player_address=p_addr,
            music_address=m_addr,
            zp_base=z_addr,
            mads_exe=mads,
            player_asm=player_asm,
            format=composition_format,
            player_version=player_version,
            result_transform=result_transform
            if assignments or (bank is not None and binding is not None)
            else None,
        )
    except (XexLayoutError, FormatVersionError, StreamValidationError, InstrumentPlanError) as exc:
        # Surface build/format/assignment refusals as clean CLI errors instead of a traceback.
        raise click.ClickException(str(exc)) from exc
    size = xex_path.stat().st_size
    click.echo(f"Successfully compiled XEX -> {xex_path} ({size} bytes)")


@cli.command("ai-compose")
@click.option("--style", type=str, default="dark dungeon exploration", help="Composition style/description")
@click.option("--mood", "-m", multiple=True, help="Mood keywords (can be specified multiple times)")
@click.option("--duration", type=float, default=25.0, help="Target duration in seconds")
@click.option("--bpm", type=int, default=120, help="Target BPM")
@click.option("--key", type=str, default=None, help="Root musical key (e.g. A, D, E, F#, Bb)")
@click.option("--mode", type=str, default=None, help="Musical mode/scale (e.g. minor, major, dorian, phrygian)")
@click.option("--notes", type=str, default=None, help="Additional compositional notes or guidance")
@click.option("--channels", type=int, default=4, help="POKEY channels (1..4)")
@click.option("--use-16bit-bass/--no-16bit-bass", default=False, help="Enable 16-bit bass mode")
@click.option("--structure", type=str, default="A-B-A", help="Song structure (e.g. A-B-A)")
@click.option("--format", "composition_format", type=click.Choice(["json", "dsl"], case_sensitive=False), default="json", help="Composition format for LLM generation: json (default) or dsl")
@click.option(
    "--prompt-profile",
    type=click.Choice(["classic", "rich"], case_sensitive=False),
    default="classic",
    help="Prompt engineering profile: classic (default, unchanged) or rich (grid, chiptune craft, style idioms, rich example).",
)
@click.option("--temperature", type=float, default=None, help="Optional LLM sampling temperature override (default: 0.7)")
@click.option(
    "--tempo-grid",
    type=click.Choice(["describe", "exact"], case_sensitive=False),
    default="describe",
    help="Rhythmic grid mode in rich profile: describe (default) or exact (suggests exact PAL grid BPM).",
)
@click.option("--plan-first/--no-plan-first", default=False, help="Opt-in: generate a structured MusicalBrief plan before composing notes.")
@click.option("--quality-passes", type=int, default=0, help="Opt-in: number of post-validation musical critique & revision passes (default: 0).")
@click.option(
    "--rhythmic-density",
    type=click.Choice(["low", "medium", "high", "extreme"], case_sensitive=False),
    default=None,
    help="Opt-in rhythmic density target independent of BPM (low, medium, high, extreme).",
)
@click.option("--provider", type=click.Choice(["mock", "openai", "deepseek"], case_sensitive=False), default=None, help="AI provider override (overrides AI_PROVIDER, e.g. mock, openai, deepseek)")
@click.option("--model", type=str, default=None, help="AI model name override")
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to custom .env configuration file (overrides global --env-file)",
)
@click.option("--max-retries", type=int, default=3, help="Maximum validation repair retry attempts (default: 3)")
@click.option(
    "--channel-instrument",
    "channel_instruments_raw",
    multiple=True,
    metavar="CH=INSTRUMENT_ID",
    help="Assign SSOT catalog instrument to channel 1..4 or role (e.g. 1=bass_poly4_punch, 3=lead_attack_bite).",
)
@click.option(
    "--use-instrument-catalog/--no-use-instrument-catalog",
    default=False,
    help="Opt-in: expose SSOT catalog instruments & behaviors to AI composition.",
)
@click.option(
    "--instrument-catalog",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional SSOT instrument catalog JSON path (default: data/instruments/catalog.json).",
)
@click.option(
    "--player-version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target MADS export format version when --output-asm is given (auto, v1, v2; default: auto).",
)
@click.option("--output-ir", type=click.Path(path_type=Path), default=None, help="Optional output POKEY IR JSON path")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Optional output MADS assembly (.asm) path")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Optional output WAV path")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default=None,
    is_eager=True,
    expose_value=False,
    callback=_set_log_level,
    help="Logging level override (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    required=False,
    help="Output file path (omitted or '-' prints to stdout)",
)
@click.pass_context
def ai_compose_cmd(
    ctx: click.Context,
    style: str,
    mood: tuple[str, ...],
    duration: float,
    bpm: int,
    key: Optional[str],
    mode: Optional[str],
    notes: Optional[str],
    channels: int,
    use_16bit_bass: bool,
    structure: str,
    composition_format: str,
    prompt_profile: str,
    temperature: Optional[float],
    tempo_grid: str,
    plan_first: bool,
    quality_passes: int,
    rhythmic_density: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    env_file: Optional[Path],
    max_retries: int,
    channel_instruments_raw: Tuple[str, ...],
    use_instrument_catalog: bool,
    instrument_catalog: Optional[Path],
    player_version: str,
    output_ir: Optional[Path],
    output_asm: Optional[Path],
    output_wav: Optional[Path],
    output: Optional[Path],
) -> None:
    """Generate a valid AI composition (JSON or Music DSL) using an AI provider."""
    from atari_music.ai.providers.base import CompositionRequest
    from atari_music.ai.client import generate_music_from_composition, request_ai_composition
    from atari_music.ai.dsl import export_music_dsl
    from atari_music.config import Config
    from atari_music.instruments import (
        CatalogError,
        InstrumentPlanError,
        parse_channel_instrument_specs,
        resolve_channel_instrument_plan,
        resolve_export_format_version,
    )
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError, export_mads_asm

    ch_map = None
    try:
        if channel_instruments_raw:
            ch_map = parse_channel_instrument_specs(channel_instruments_raw)
            resolve_channel_instrument_plan(
                ch_map,
                catalog_path=instrument_catalog,
                uses_16bit_bass=use_16bit_bass,
                player_version=player_version,
            )
    except (InstrumentPlanError, CatalogError, ValueError) as err:
        raise click.ClickException(str(err)) from err

    global_env_file = ctx.obj.get("env_file") if (ctx and isinstance(ctx.obj, dict)) else None
    effective_env_file = env_file or global_env_file
    cfg = Config.from_args(args=[], env_path=effective_env_file or ".env", validate=False)

    # Priority: CLI --provider > Config (AI_PROVIDER via env > env-file > default "mock")
    effective_provider = provider if provider is not None else (cfg.ai_provider or "mock")
    effective_model = model if model is not None else cfg.ai_model

    req = CompositionRequest(
        style=style,
        mood=list(mood) if mood else ["mysterious", "tense"],
        duration_seconds=duration,
        bpm=bpm,
        key=key,
        mode=mode,
        notes=notes,
        channels=channels,
        use_16bit_bass=use_16bit_bass,
        structure=structure,
        format=composition_format.lower(),
        channel_instruments=ch_map,
        enable_catalog_instruments=bool(use_instrument_catalog or ch_map),
        instrument_catalog_path=str(instrument_catalog) if instrument_catalog else None,
        prompt_profile=prompt_profile.lower(),
        temperature=temperature,
        tempo_grid=tempo_grid.lower(),
        plan_first=plan_first,
        quality_passes=quality_passes,
        rhythmic_density=rhythmic_density.lower() if rhythmic_density else None,
    )
    is_stdout = output is None or str(output) == "-"

    # Informational logs go to stderr so stdout is not polluted
    click.echo(f"Requesting composition from provider '{effective_provider}' (format: {req.format})...", err=True)
    click.echo(
        f"  Style: {style}, BPM: {bpm}, Channels: {channels}, 16-bit bass: {use_16bit_bass}, max retries: {max_retries}",
        err=True,
    )
    comp = request_ai_composition(
        req,
        provider_name=effective_provider,
        model=effective_model,
        max_retries=max_retries,
        env_path=effective_env_file,
        format=req.format,
    )

    if req.format == "dsl":
        content_str = export_music_dsl(comp)
    else:
        content_str = json.dumps(comp.model_dump(mode="json"), indent=2)

    if is_stdout:
        click.echo(content_str)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(content_str)
        click.echo(f"Successfully generated and validated composition -> {output}", err=True)
        click.echo(f"  Title: {comp.metadata.title}", err=True)

    if output_ir or output_asm or output_wav:
        res = generate_music_from_composition(comp)
        if output_ir:
            res.save_json(output_ir)
            click.echo(f"Saved POKEY IR -> {output_ir}", err=True)
        if output_wav:
            res.render_wav(output_wav)
            click.echo(f"Rendered WAV -> {output_wav}", err=True)
        if output_asm:
            try:
                export_ver = resolve_export_format_version(res.pokey_ir, player_version)
                export_mads_asm(res.pokey_ir, output_asm, format_version=export_ver)
            except (FormatVersionError, StreamValidationError, InstrumentPlanError) as err:
                raise click.ClickException(str(err)) from err
            click.echo(f"Exported MADS ASM (v{export_ver}) -> {output_asm}", err=True)


@cli.command("list-instruments")
@click.option(
    "--instrument-catalog", "--catalog",
    "catalog_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="SSOT instrument catalog JSON path (default: data/instruments/catalog.json)",
)
@click.option(
    "--family",
    type=click.Choice(["lead", "bass", "pad", "harmony", "percussion", "fx"], case_sensitive=False),
    default=None,
    help="Filter instruments by family",
)
@click.option(
    "--role",
    type=click.Choice(["melody", "bass", "harmony", "rhythm", "percussion"], case_sensitive=False),
    default=None,
    help="Filter instruments by intended role",
)
@click.option(
    "--target",
    type=click.Choice(["xex_v2", "xex_v1", "wav"], case_sensitive=False),
    default="xex_v2",
    help="Target backend to report compatibility for (default: xex_v2)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit catalog listing as JSON")
def list_instruments_cmd(
    catalog_path: Optional[Path],
    family: Optional[str],
    role: Optional[str],
    target: str,
    as_json: bool,
) -> None:
    """List curated instruments in the SSOT catalog (data/instruments/catalog.json)."""
    from atari_music.instruments import (
        TARGET_V1_XEX,
        TARGET_V2_ITER1_XEX,
        TARGET_WAV_PREVIEW,
        CatalogError,
        ChannelAssignmentRequest,
        POKEYRuntime,
        load_instrument_catalog,
    )

    try:
        catalog = load_instrument_catalog(catalog_path)
    except CatalogError as err:
        raise click.ClickException(str(err)) from err

    target_map = {
        "xex_v2": TARGET_V2_ITER1_XEX,
        "xex_v1": TARGET_V1_XEX,
        "wav": TARGET_WAV_PREVIEW,
    }
    target_cap = target_map[target.lower()]
    runtime = POKEYRuntime()
    profiles = catalog.list_profiles(
        family=family.lower() if family else None,
        role=role.lower() if role else None,
    )

    rows: List[Dict[str, Any]] = []
    for prof in profiles:
        beh = catalog.get_behavior(prof.behavior_id) if prof.behavior_id else None
        ch_def = prof.hardware_constraints.channels_allowed[0]
        rep = runtime.resolve(
            [ChannelAssignmentRequest(channel=ch_def, instrument_ids=(prof.instrument_id,))],
            catalog,
            target=target_cap,
        )
        rows.append(
            {
                "instrument_id": prof.instrument_id,
                "display_name": prof.display_name,
                "family": prof.family,
                "intended_roles": list(prof.intended_roles),
                "distortion_hex": f"${prof.base_distortion:02X}",
                "divider_mode": prof.hardware_constraints.divider_mode,
                "channels_allowed": list(prof.hardware_constraints.channels_allowed),
                "midi_range": list(prof.hardware_constraints.midi_range),
                "waveform_family": prof.waveform_family,
                "preferred_clock_hz": prof.hardware_constraints.preferred_clock_hz,
                "required_audctl_bits": prof.hardware_constraints.required_audctl_bits,
                "poly4_safe_tuning": prof.hardware_constraints.poly4_safe_tuning,
                "envelope": prof.envelope.model_dump(mode="json"),
                "behavior_id": prof.behavior_id,
                "tier": beh.required_runtime_tier if beh else "core_v1",
                "target": target.lower(),
                "compatible": rep.is_compatible,
                "status": rep.status,
            }
        )

    if as_json:
        click.echo(json.dumps({"catalog_version": catalog.catalog_version, "instruments": rows}, indent=2))
        return

    click.echo(f"SSOT Instrument Catalog v{catalog.catalog_version} ({len(rows)} matching, target={target.lower()}):")
    for r in rows:
        flag = "OK" if r["compatible"] else r["status"]
        chs = ",".join(str(c) for c in r["channels_allowed"])
        click.echo(
            f"  {r['instrument_id']:<24} {r['family']:<10} ch=[{chs:<7}] {r['tier']:<21} [{flag}] - {r['display_name']}"
        )


@cli.command("inspect-instrument")
@click.argument("instrument_id", type=str)
@click.option(
    "--instrument-catalog", "--catalog",
    "catalog_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="SSOT instrument catalog JSON path (default: data/instruments/catalog.json)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit instrument specification as JSON")
def inspect_instrument_cmd(
    instrument_id: str,
    catalog_path: Optional[Path],
    as_json: bool,
) -> None:
    """Display full hardware, envelope, macro, and compatibility details for a catalog instrument."""
    from atari_music.instruments import (
        TARGET_V1_XEX,
        TARGET_V2_ITER1_XEX,
        TARGET_WAV_PREVIEW,
        CatalogError,
        ChannelAssignmentRequest,
        POKEYRuntime,
        load_instrument_catalog,
    )

    try:
        catalog = load_instrument_catalog(catalog_path)
        profile, behavior = catalog.resolve_profile_behavior(instrument_id)
    except CatalogError as err:
        raise click.ClickException(str(err)) from err

    runtime = POKEYRuntime()
    ch_def = profile.hardware_constraints.channels_allowed[0]
    compat = {
        name: {
            "compatible": rep.is_compatible,
            "status": rep.status,
            "effective_audctl": f"${rep.effective_audctl:02X}",
            "diagnostics": [d.message for d in rep.diagnostics],
        }
        for name, tgt in (
            ("xex_v1", TARGET_V1_XEX),
            ("xex_v2", TARGET_V2_ITER1_XEX),
            ("wav", TARGET_WAV_PREVIEW),
        )
        for rep in (
            runtime.resolve(
                [ChannelAssignmentRequest(channel=ch_def, instrument_ids=(instrument_id,))],
                catalog,
                target=tgt,
            ),
        )
    }

    if as_json:
        payload = {
            "profile": profile.model_dump(mode="json"),
            "behavior": behavior.model_dump(mode="json") if behavior else None,
            "compatibility": compat,
        }
        click.echo(json.dumps(payload, indent=2))
        return

    hc = profile.hardware_constraints
    env = profile.envelope
    click.echo(f"Instrument: {profile.instrument_id} ({profile.display_name})")
    click.echo(f"  Family / Roles:    {profile.family} / {', '.join(profile.intended_roles)}")
    click.echo(f"  Waveform / AUDC:   {profile.waveform_family} (${profile.base_distortion:02X})")
    click.echo(
        f"  ADSR Envelope:     A={env.attack_frames} D={env.decay_frames} S={env.sustain_vol} R={env.release_frames} (peak={env.peak_vol})"
    )
    click.echo(
        f"  Hardware:          mode={hc.divider_mode}, clock={hc.preferred_clock_hz or '64khz'}, "
        f"AUDCTL_req=${hc.required_audctl_bits:02X}, AUDCTL_forb=${hc.forbidden_audctl_bits:02X}, "
        f"channels={list(hc.channels_allowed)}, MIDI={list(hc.midi_range)}"
    )
    if behavior is not None:
        click.echo(
            f"  Behavior:          {behavior.behavior_id} (tier={behavior.required_runtime_tier}, "
            f"mod={behavior.modulation_mode}, per_note_switch={behavior.allow_per_note_switch})"
        )
        if behavior.pitch_envelope is not None:
            pe = behavior.pitch_envelope
            click.echo(
                f"    Pitch Envelope:  start_delta={pe.start_audf_delta}, frames={pe.duration_frames}, step_delta={pe.step_delta}"
            )
        if behavior.transient_macro is not None:
            click.echo(f"    Transient Macro: {len(behavior.transient_macro.steps)} step(s):")
            for s_idx, step in enumerate(behavior.transient_macro.steps):
                audf_desc = (
                    f"fixed=${step.fixed_audf:02X}" if step.fixed_audf is not None else f"offset={step.audf_offset:+d}"
                )
                dist_desc = f"${step.distortion_nibble:02X}" if step.distortion_nibble is not None else "base"
                vol_desc = str(step.volume) if step.volume is not None else "env"
                click.echo(
                    f"      [{s_idx}] {step.duration_frames}f dist={dist_desc} {audf_desc} vol={vol_desc}"
                )
    click.echo("  Runtime Compatibility:")
    for name, info in compat.items():
        click.echo(f"    {name:<8}: compatible={info['compatible']} status={info['status']} AUDCTL={info['effective_audctl']}")
        for msg in info["diagnostics"]:
            click.echo(f"      - {msg}")


@cli.command("validate-instruments")
@click.option(
    "--instrument-catalog", "--catalog",
    "catalog_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="SSOT instrument catalog JSON path (default: data/instruments/catalog.json)",
)
def validate_instruments_cmd(catalog_path: Optional[Path]) -> None:
    """Validate integrity, schema, and provenance of the SSOT instrument catalog."""
    from atari_music.instruments import DEFAULT_CATALOG_PATH, CatalogError, load_instrument_catalog, validate_instrument_catalog

    try:
        target_path = DEFAULT_CATALOG_PATH if catalog_path is None else catalog_path
        validate_instrument_catalog(target_path)
        catalog = load_instrument_catalog(catalog_path)
    except CatalogError as err:
        raise click.ClickException(str(err)) from err
    click.echo(
        f"Instrument catalog VALID: schema={catalog.schema_id} version={catalog.catalog_version} "
        f"({len(catalog.instruments)} instruments, {len(catalog.behaviors)} behaviors)"
    )


@cli.command("arrange")
@click.argument("input_composition", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--channel-instrument",
    "channel_instruments_raw",
    multiple=True,
    metavar="CH=INSTRUMENT_ID",
    help="Assign SSOT catalog instrument to channel 1..4 or role (repeatable; leaves unassigned channels unchanged).",
)
@click.option(
    "--program-change-policy",
    type=click.Choice(["preserve", "replace", "remove"], case_sensitive=False),
    default="preserve",
    help="How to handle existing PROGRAM_CHANGE events on overridden channels (preserve, replace, remove; default: preserve).",
)
@click.option(
    "--instrument-catalog",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional SSOT instrument catalog JSON path (default: data/instruments/catalog.json).",
)
@click.option(
    "--player-version",
    type=click.Choice(["auto", "v1", "v2"], case_sensitive=False),
    default="auto",
    help="Target player format version (auto, v1, v2; default: auto).",
)
@click.option("--output-json", "--output-ir", "output_json", type=click.Path(path_type=Path), default=None, help="Output arranged POKEY IR JSON path")
@click.option("--output-wav", type=click.Path(path_type=Path), default=None, help="Output WAV path")
@click.option("--output-asm", type=click.Path(path_type=Path), default=None, help="Output MADS assembly (.asm) path")
@click.option("--output-xex", "-o", "output_xex", type=click.Path(path_type=Path), default=None, help="Output Atari XEX binary path")
@click.option("--player-address", type=str, default="0x6000", help="Relocatable player address for XEX (default: 0x6000)")
@click.option("--music-address", type=str, default="0x8000", help="Relocatable music data address for XEX (default: 0x8000)")
@click.option("--zp-base", type=str, default="0x80", help="Zero-page base address for XEX (default: 0x80)")
@click.option("--mads", type=click.Path(path_type=Path), default=Path("tools/mads/mads.exe"), help="Path to mads.exe for XEX compilation")
@click.option("--player-asm", type=click.Path(exists=True, path_type=Path), default=None, help="Optional explicit path to player.asm")
def arrange_cmd(
    input_composition: Path,
    channel_instruments_raw: Tuple[str, ...],
    program_change_policy: str,
    instrument_catalog: Optional[Path],
    player_version: str,
    output_json: Optional[Path],
    output_wav: Optional[Path],
    output_asm: Optional[Path],
    output_xex: Optional[Path],
    player_address: str,
    music_address: str,
    zp_base: str,
    mads: Path,
    player_asm: Optional[Path],
) -> None:
    """Re-arrange an existing composition JSON with new POKEY channel instruments without calling AI."""
    from atari_music.ai.schema import MusicCompositionError
    from atari_music.api import arrange_song
    from atari_music.instruments import (
        CatalogError,
        InstrumentPlanError,
        parse_channel_instrument_specs,
    )
    from atari_music.mads_exporter import FormatVersionError, StreamValidationError

    def _parse_addr(val: str) -> int:
        s = val.strip()
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s)

    try:
        ch_map = parse_channel_instrument_specs(channel_instruments_raw) if channel_instruments_raw else None
        arranged = arrange_song(
            input_composition,
            channel_instruments=ch_map,
            program_change_policy=program_change_policy,
            instrument_catalog_path=instrument_catalog,
            player_version=player_version,
        )
    except (InstrumentPlanError, CatalogError, MusicCompositionError, ValueError, FileNotFoundError) as err:
        raise click.ClickException(str(err)) from err

    m = arranged.metadata
    click.echo(
        f"Arranged '{arranged.pokey_ir.title}' (Format: v{m.format_version}, Policy: {program_change_policy.lower()}, "
        f"Mem: {m.memory_size_bytes} B, Channels: {m.channels_used})"
    )

    if output_json:
        arranged.save_json(output_json)
        click.echo(f"Saved arranged POKEY IR -> {output_json}")

    if output_wav:
        arranged.render_wav(output_wav)
        click.echo(f"Rendered WAV -> {output_wav}")

    if output_asm:
        try:
            arranged.export_mads(output_asm, player_version=player_version)
        except (FormatVersionError, StreamValidationError, InstrumentPlanError) as err:
            raise click.ClickException(str(err)) from err
        click.echo(f"Exported MADS ASM (v{m.format_version}) -> {output_asm}")

    if output_xex:
        try:
            p_addr = _parse_addr(player_address)
            m_addr = _parse_addr(music_address)
            z_addr = _parse_addr(zp_base)
            arranged.build_xex(
                output_xex,
                player_address=p_addr,
                music_address=m_addr,
                zp_base=z_addr,
                mads_bin=mads,
                player_asm=player_asm,
                player_version=player_version,
                keep_asm=False,
            )
        except (
            XexLayoutError,
            FormatVersionError,
            StreamValidationError,
            InstrumentPlanError,
            MusicCompositionError,
            FileNotFoundError,
            ValueError,
        ) as err:
            raise click.ClickException(str(err)) from err
        click.echo(f"Compiled XEX -> {output_xex} ({output_xex.stat().st_size} bytes)")


@cli.command("prepare-listening-test-9c")
@click.option(
    "--package-dir",
    type=click.Path(path_type=Path),
    default=Path("examples/sound_profile_listening"),
    help="Where to write the listening package.",
)
@click.option(
    "--sound-bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("tests/data/sound_profiles/bank"),
    help="Published sound profile bank to listen to (read only).",
)
@click.option(
    "--songs-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/songs"),
    help="Songs and their .binding.json files used for the whole-song A/B trials.",
)
@click.option(
    "--song",
    "songs",
    multiple=True,
    help="Song file name (inside --songs-dir) to use for the whole-song A/B trials; repeatable. "
    "Defaults to the built-in varied programme.",
)
@click.option("--seed", type=int, default=20261005, help="Presentation-order seed (recorded in the manifest).")
def prepare_listening_test_9c_cmd(
    package_dir: Path, sound_bank: Path, songs_dir: Path, songs: Tuple[str, ...], seed: int
) -> None:
    """Build the Stage 9C blinded listening package: stimuli, A/B program, templates, interface.

    Nothing is modified: the bank is read, the songs are read, and every artefact lands in
    --package-dir. No profile is renamed, ranked, selected or excluded beyond the profiles that
    cannot produce a sound at all.
    """
    from atari_music.stage9c import build_package

    click.echo(f"Building the Stage 9C listening package in '{package_dir}'...")
    manifest = build_package(
        package_dir,
        bank_dir=sound_bank,
        songs_dir=songs_dir,
        seed=seed,
        context_songs=songs or None,
        log=lambda message: click.echo(f"  {message}", err=True),
    )
    click.echo(
        f"Wrote {manifest['profile_count']} blinded profile stimuli, "
        f"{len(manifest['ab_trials'])} A/B trials and {len(manifest['song_trials'])} song pairs."
    )
    click.echo(f"  profiles in the bank: {manifest['profile_count_in_bank']}")
    click.echo(f"  excluded (not renderable): {len(manifest['excluded_profiles'])}")
    substitutions = manifest["stimulus"]["envelope_substitutions"]
    if substitutions:
        click.echo(
            f"  envelope substituted for {len(substitutions)} profile(s); see manifest.json",
            err=True,
        )
    click.echo(f"Open '{package_dir / 'index.html'}' to listen, then run analyze-listening-test-9c.")


@cli.command("analyze-listening-test-9c")
@click.option(
    "--package-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_listening"),
    help="The listening package whose filled-in CSVs should be analysed.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage9c"),
    help="Where to write the analysis.",
)
def analyze_listening_test_9c_cmd(package_dir: Path, output_dir: Path) -> None:
    """Analyse the completed Stage 9C evaluation CSVs into reports/stage9c/.

    Refuses to run until the templates actually carry answers, and never declares a final
    library: it reports what the listener said and where that disagrees with the measurements.
    """
    from atari_music.stage9c import AnalysisNotReady, analyze_experiment

    click.echo(f"Analysing the listening results in '{package_dir}'...")
    try:
        written = analyze_experiment(package_dir, output_dir, log=lambda message: click.echo(f"  {message}"))
    except AnalysisNotReady as error:
        raise click.ClickException(str(error)) from error
    for name, path in written.items():
        click.echo(f"  {name}: {path}")


@cli.command("analyze-listening-test-9d")
@click.option(
    "--package-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_listening"),
    help="The listening package holding the completed answer CSVs.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage9d_human_listening_results.md.",
)
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage9d"),
    help="Where to write the machine-readable analysis.",
)
def analyze_listening_test_9d_cmd(package_dir: Path, docs_dir: Path, reports_dir: Path) -> None:
    """Analyse the human listening results and answer whether a selection stage is justified.

    Read-only with respect to the experiment: the answers, manifest, profiles and audio are read
    (and hashed), never written. The analysis is deterministic and reports what the listening
    showed, including the results that argue against the library.
    """
    from atari_music.stage9d import AnswersMissing, analyze_stage9d

    click.echo(f"Analysing the human listening results in '{package_dir}'...")
    try:
        written = analyze_stage9d(
            package_dir,
            docs_dir=docs_dir,
            reports_dir=reports_dir,
            log=lambda message: click.echo(f"  {message}", err=True),
        )
    except AnswersMissing as error:
        raise click.ClickException(str(error)) from error

    verdict = json.loads(written["verdict"].read_text(encoding="utf-8"))
    for name, path in written.items():
        click.echo(f"  {name}: {path}")
    click.echo(f"Closing answer: {verdict['verdict']}")
    for criterion in verdict["criteria"]:
        mark = "met" if criterion["met"] else "NOT met"
        click.echo(f"  [{mark}] {criterion['criterion']} ({criterion['value']})")


@cli.command("analyze-listening-test-9e")
@click.option(
    "--bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("tests/data/sound_profiles/bank"),
    help="The sound profile bank the diagnosis walks.",
)
@click.option(
    "--songs-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/songs"),
    help="Where the six listening-test sources and their bindings live.",
)
@click.option(
    "--package-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_listening"),
    help="The listening package, whose audio this diagnosis must reproduce byte for byte.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage9e_perceptual_renderer_gap.md.",
)
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage9e"),
    help="Where to write the machine-readable diagnosis.",
)
def analyze_listening_test_9e_cmd(
    bank: Path, songs_dir: Path, package_dir: Path, docs_dir: Path, reports_dir: Path
) -> None:
    """Diagnose why 61 profiles render to 37 distinct sounds and what the renderer cannot carry.

    Read-only: the bank, the package, the answers and the song sources are read and hashed, never
    written. The diagnosis refuses to run if its own re-render does not reproduce the package
    audio byte for byte, so its claims are about the pipeline the listener actually heard.
    """
    from atari_music.stage9e import Stage9EError, analyze_stage9e

    click.echo(f"Diagnosing the pipeline behind '{package_dir}'...")
    try:
        written = analyze_stage9e(
            bank_dir=bank,
            songs_dir=songs_dir,
            package_dir=package_dir,
            docs_dir=docs_dir,
            reports_dir=reports_dir,
            log=lambda message: click.echo(f"  {message}", err=True),
        )
    except Stage9EError as error:
        raise click.ClickException(str(error)) from error

    verdict = json.loads(written["verdict"].read_text(encoding="utf-8"))
    for name, path in written.items():
        click.echo(f"  {name}: {path}")
    click.echo(f"Closing answer: {verdict['verdict']}")
    click.echo(
        f"  {verdict['groups_explained']} of {verdict['groups']} duplicate groups explained; "
        f"{verdict['groups_unexplained']} unexplained"
    )


@cli.command("prepare-rebinding-10a")
@click.option(
    "--package-dir",
    type=click.Path(path_type=Path),
    default=Path("examples/sound_profile_rebinding_10a"),
    help="Where to write the blinded package.",
)
@click.option(
    "--stage9c-package",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_listening"),
    help="The Stage 9C package: its manifest defines the six songs (read only).",
)
@click.option(
    "--songs-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/songs"),
    help="The songs and the per-song bindings the old assignment lives in (read only).",
)
@click.option(
    "--sound-bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("tests/data/sound_profiles/bank"),
    help="The published profile bank the new assignment draws from (read only).",
)
@click.option(
    "--stage9d-reports",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("reports/stage9d"),
    help="The human listening evidence the assignment is chosen from (read only).",
)
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage10a"),
    help="Where to write the machine-readable record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage10a_rebinding_experiment.md.",
)
@click.option("--seed", type=int, default=20261006, help="Blinded-orientation seed (recorded).")
def prepare_rebinding_10a_cmd(
    package_dir: Path,
    stage9c_package: Path,
    songs_dir: Path,
    sound_bank: Path,
    stage9d_reports: Path,
    reports_dir: Path,
    docs_dir: Path,
    seed: int,
) -> None:
    """Rebind the six Part C songs from the listening evidence and build the comparison package.

    Read-only with respect to everything it is about: no profile is edited, renamed or removed, no
    composition or binding is modified, and no production module is touched. The default and old
    sides are verified byte-for-byte against the Stage 9C package before the package is written, so
    the comparison is with the same audio the listener already judged.
    """
    from atari_music.stage10a import Stage10AError, build_package

    click.echo(f"Preparing the Stage 10A rebinding experiment in '{package_dir}'...")
    try:
        bundle = build_package(
            package_dir,
            stage9c_package=stage9c_package,
            songs_dir=songs_dir,
            bank_dir=sound_bank,
            reports_dir=stage9d_reports,
            analysis_dir=reports_dir,
            docs_dir=docs_dir,
            seed=seed,
            log=lambda message: click.echo(f"  {message}", err=True),
        )
    except Stage10AError as error:
        raise click.ClickException(str(error)) from error

    plan = bundle["plan"].as_dict()
    click.echo(
        f"Changed {plan['changed_channels']} of "
        f"{len(bundle['plan'].decisions)} channels "
        f"({plan['changed_roles']} roles) in {len(plan['songs_changed'])} songs; "
        f"{len(plan['songs_unchanged'])} song(s) left untouched."
    )
    click.echo(f"  {len(bundle['trials'])} blinded comparisons, 3 per song.")
    click.echo("  The default and old sides reproduce the Stage 9C stimuli byte for byte.")
    for name, path in sorted(bundle["written"].items()):
        click.echo(f"  {name}: {path}")
    click.echo("Listen at " + str(Path(package_dir) / "index.html"))
    click.echo("Then fill " + str(Path(package_dir) / "evaluation_rebinding_10a.csv"))


@cli.command("prepare-volume-contour-10b")
@click.option(
    "--package-dir",
    type=click.Path(path_type=Path),
    default=Path("examples/sound_profile_volume_contour_10b"),
    help="Where to write the blinded package.",
)
@click.option(
    "--stage10a-package",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_rebinding_10a"),
    help="The Stage 10A package: its binding is the continuation point (read only).",
)
@click.option(
    "--stage9c-package",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_listening"),
    help="The Stage 9C package: its manifest defines the six songs (read only).",
)
@click.option(
    "--songs-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/songs"),
    help="The six compositions (read only).",
)
@click.option(
    "--sound-bank",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("tests/data/sound_profiles/bank"),
    help="The published profile bank the contours are read from (read only).",
)
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage10b"),
    help="Where to write the machine-readable record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage10b_volume_contour_experiment.md.",
)
@click.option("--seed", type=int, default=20261007, help="Blinded-orientation seed (recorded).")
def prepare_volume_contour_10b_cmd(
    package_dir: Path,
    stage10a_package: Path,
    stage9c_package: Path,
    songs_dir: Path,
    sound_bank: Path,
    reports_dir: Path,
    docs_dir: Path,
    seed: int,
) -> None:
    """Render the three volume-contour variants and build the blinded listening package.

    Read-only with respect to everything it is about: no profile is edited, no composition or binding
    is modified, and no production module is used differently than before. Every render the Stage 10A
    package published is reproduced byte for byte with the feature switched off before the package is
    written, and the package is refused if it is not.
    """
    from atari_music.stage10b import Stage10BError, build_package

    click.echo(f"Preparing the Stage 10B volume contour experiment in '{package_dir}'...")
    try:
        bundle = build_package(
            package_dir,
            stage10a_package=stage10a_package,
            stage9c_package=stage9c_package,
            songs_dir=songs_dir,
            bank_dir=sound_bank,
            reports_dir=reports_dir,
            analysis_dir=reports_dir,
            docs_dir=docs_dir,
            seed=seed,
            log=lambda message: click.echo(f"  {message}", err=True),
        )
    except Stage10BError as error:
        raise click.ClickException(str(error)) from error

    regression = bundle["regression"]
    withheld = sum(len(subject.withheld) for subject in bundle["subjects"])
    click.echo(
        f"Tested {len(bundle['tested'])} profiles; {withheld} song channel(s) could not take a "
        "contour because their measurement contains silence."
    )
    click.echo(
        f"  {regression['renders_compared']} published Stage 10A renders reproduced byte for byte: "
        f"{regression['all_byte_identical']}."
    )
    click.echo(f"  {len(bundle['trials'])} blinded comparisons.")
    for name, path in sorted(bundle["written"].items()):
        click.echo(f"  {name}: {path}")
    click.echo("Listen at " + str(Path(package_dir) / "index.html"))
    click.echo("Then fill " + str(Path(package_dir) / "evaluation_volume_contour_10b.csv"))
    click.echo(
        "The verdict stays INCONCLUSIVE until that evidence exists: this stage proves the transfer, "
        "it does not judge it."
    )


@cli.command("analyze-volume-contour-10b")
@click.option(
    "--package-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("examples/sound_profile_volume_contour_10b"),
    help="The package whose answer sheet to read.",
)
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage10b"),
    help="Where to write answers.json.",
)
def analyze_volume_contour_10b_cmd(package_dir: Path, reports_dir: Path) -> None:
    """Count the Stage 10B answers against the package's private key.

    Counts only. Whether the contour is preferable is a judgement about the counts, and this command
    deliberately does not make it.
    """
    from atari_music.stage10b import Stage10BError, summarise_answers

    try:
        summary = summarise_answers(package_dir, analysis_dir=reports_dir)
    except Stage10BError as error:
        raise click.ClickException(str(error)) from error

    if not summary["answered"]:
        click.echo("The Stage 10B answer sheet is still empty; nothing to count yet.")
        return
    click.echo(f"Answered {summary['answered']} of {summary['trials']} pairs.")
    for kind, bucket in sorted(summary["by_kind"].items()):
        click.echo(
            f"  {kind}: side C chosen {bucket['c']}, the other side {bucket['other']}, "
            f"no clear difference {bucket['none']}"
        )
    click.echo(
        f"  movement heard: {summary['perceptibility']['heard']}, "
        f"neither side: {summary['perceptibility']['neither']}"
    )
    if "difference_median" in summary:
        click.echo(f"  median reported difference: {summary['difference_median']} of 5")
    click.echo(f"  written: {Path(reports_dir) / 'answers.json'}")


@cli.command("synthesize-stage11a")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage11"),
    help="Where to write the Stage 11 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage11_perceptual_synthesis.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
def synthesize_stage11a_cmd(
    reports_dir: Path, docs_dir: Path, archaeology_dir: Optional[Path]
) -> None:
    """Synthesise the Stage 11A evidence: read-only, writes reports/stage11 and one document.

    Nothing is rendered and nothing is changed; the command reads the published Stage 7B, 8C,
    9D, 9E, 10A and 10B artefacts plus the two answer sheets, and reproduces the synthesis.
    """
    from atari_music import stage11a

    archaeology = archaeology_dir or stage11a.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage11a.build_synthesis(archaeology=archaeology)
    written = stage11a.write_synthesis(bundle, stage11_dir=reports_dir, docs_dir=docs_dir)

    gap = bundle["representation_gap"]
    coll = bundle["collapse"]
    click.echo(f"Read {len(bundle['inputs'])} input artefacts (hashed; no timestamps written).")
    click.echo(
        f"  binding reads {gap['read_by_binding_count']} of {gap['leaf_paths_total']} "
        "documented leaf paths"
    )
    click.echo(
        f"  collapse: {coll['profiles_probed']} profiles -> {coll['distinct_audio_signals']} "
        f"distinct signals ({coll['redundant_profiles']} redundant in {coll['groups']} groups)"
    )
    click.echo(f"  Stage 11B go / no-go: {bundle['go_no_go']['decision']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("run-stage11b")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage11"),
    help="Where to write the Stage 11 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage11_spectral_experiment.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
@click.option("--limit", type=int, default=8, help="How many representative profiles to test.")
def run_stage11b_cmd(
    reports_dir: Path, docs_dir: Path, archaeology_dir: Optional[Path], limit: int
) -> None:
    """Render the controlled spectral ablation with the existing renderer and describe it.

    Read-only with respect to every input: it renders with the unchanged frame compiler and
    synthesiser, writes only Stage 11 artefacts, and recommends no renderer change.
    """
    from atari_music import stage11b

    archaeology = archaeology_dir or stage11b.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage11b.run_experiment(arch_root=archaeology, limit=limit)
    written = stage11b.write_experiment(bundle, stage11_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo(f"Selected {summary['selected']} distinct-audio representative profiles.")
    for key, value in sorted(summary["expressibility_counts"].items()):
        click.echo(f"  {key}: {value}")
    click.echo(f"  best single feature: {summary['best_single_feature_counts']}")
    click.echo(f"  listening package: {'prepared' if bundle['listening']['justified'] else 'not prepared'}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("run-stage12a")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage12a"),
    help="Where to write the Stage 12A machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage12a_decoration_experiment.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
def run_stage12a_cmd(
    reports_dir: Path, docs_dir: Path, archaeology_dir: Optional[Path]
) -> None:
    """Run the Stage 12A decoration-vs-replacement experiment.

    Read-only with respect to production: the existing binding is used unchanged as the
    replacement control, the decoration variants are built in memory, and only Stage 12A
    artefacts are written. Nothing here changes what any existing caller renders.
    """
    from atari_music import stage12a

    archaeology = archaeology_dir or stage12a.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage12a.run_experiment(arch_root=archaeology)
    written = stage12a.write_experiment(
        bundle, stage12a_dir=reports_dir, docs_dir=docs_dir
    )

    usable = [record for record in bundle["cases"] if "variants" in record]
    hypotheses = bundle["hypotheses"]
    click.echo(f"Cases: {len(bundle['cases'])} ({len(usable)} usable).")
    click.echo(
        "  binding writes: " + ", ".join(bundle["binding_writes_ir_fields_union"])
    )
    click.echo(
        f"  H1 (decoration preserves Composer tuning): "
        f"{hypotheses['H1_decoration_preserves_composer_tuning']['count']}/{len(usable)}"
    )
    click.echo(
        f"  H2 (decoration changes the sound): "
        f"{hypotheses['H2_decoration_changes_the_sound']['count']}/{len(usable)}"
    )
    click.echo(f"  listening package justified: {bundle['listening']['justified']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("prepare-stage12a-listening")
@click.option(
    "--package-dir",
    type=click.Path(path_type=Path),
    default=Path("examples/stage12a_listening"),
    help="Where to write the blind listening package.",
)
@click.option("--seed", type=int, default=20261008, help="Blinded-orientation seed (recorded).")
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
def prepare_stage12a_listening_cmd(
    package_dir: Path, seed: int, archaeology_dir: Optional[Path]
) -> None:
    """Prepare the small blind Stage 12A listening package (C-vs-A and C-vs-B).

    It is refused unless the quantitative analysis justifies it; when it is, it writes only
    WAVs, a private manifest, an answer template, metadata and a README.
    """
    from atari_music import stage12a

    archaeology = archaeology_dir or stage12a.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage12a.run_experiment(arch_root=archaeology)
    if not bundle["listening"]["justified"]:
        raise click.ClickException(
            "the Stage 12A analysis does not justify a listening package: "
            + bundle["listening"]["reason"]
        )
    manifest = stage12a.build_listening_package(
        bundle, out_dir=package_dir, seed=seed, arch_root=archaeology
    )
    click.echo(f"Wrote {len(manifest['trials'])} blinded pairs to {package_dir}.")
    click.echo("Open " + str(Path(package_dir) / "index.html"))
    click.echo("Then download " + str(Path(package_dir) / "evaluation_stage12a.csv"))


@cli.command("run-stage13a")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage13a"),
    help="Where to write the Stage 13A machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage13a_pitch_trajectory_experiment.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
def run_stage13a_cmd(
    reports_dir: Path, docs_dir: Path, archaeology_dir: Optional[Path]
) -> None:
    """Run the Stage 13A pitch-trajectory experiment (offline transform; production untouched)."""
    from atari_music import stage13a

    archaeology = archaeology_dir or stage13a.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage13a.run_experiment(arch_root=archaeology)
    written = stage13a.write_experiment(
        bundle, stage13a_dir=reports_dir, docs_dir=docs_dir
    )
    recon = bundle["reconnaissance"]
    hypotheses = bundle["hypotheses"]
    decision = stage13a.verdict(bundle)
    click.echo(
        f"Bounded trajectories: {recon['transferable']['bounded_within_one_octave']} of "
        f"{recon['transferable']['bounded_within_one_octave'] + recon['transferable']['unbounded_register_artifacts']} "
        "non-static series."
    )
    for name in ("H1_technical_transfer", "H2_beyond_static_pitch", "H3_preserves_musical_pitch"):
        block = hypotheses[name]
        click.echo(f"  {name}: {block['count']}/{block['of']}")
    click.echo(f"  listening package justified: {bundle['listening']['justified']}")
    click.echo(f"  verdict: {decision['label']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("prepare-stage13a-listening")
@click.option(
    "--package-dir",
    type=click.Path(path_type=Path),
    default=Path("examples/stage13a_listening"),
    help="Where to write the blind listening package.",
)
@click.option("--seed", type=int, default=20261009, help="Blinded-orientation seed (recorded).")
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
def prepare_stage13a_listening_cmd(
    package_dir: Path, seed: int, archaeology_dir: Optional[Path]
) -> None:
    """Prepare the small blind Stage 13A listening package (pitch trajectory vs static)."""
    from atari_music import stage13a

    archaeology = archaeology_dir or stage13a.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage13a.run_experiment(arch_root=archaeology)
    if not bundle["listening"]["justified"]:
        raise click.ClickException(
            "the Stage 13A analysis does not justify a listening package: "
            + bundle["listening"]["reason"]
        )
    manifest = stage13a.build_listening_package(bundle, out_dir=package_dir, seed=seed)
    click.echo(f"Wrote {len(manifest['trials'])} blinded pairs to {package_dir}.")
    click.echo("Open " + str(Path(package_dir) / "index.html"))
    click.echo("Then download " + str(Path(package_dir) / "evaluation_stage13a.csv"))


@cli.command("synthesize-stage14")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage14"),
    help="Where to write the Stage 14 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage14_final_synthesis.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The producer repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
def synthesize_stage14_cmd(
    reports_dir: Path, docs_dir: Path, archaeology_dir: Optional[Path]
) -> None:
    """Synthesise the whole evidence base and record the go/no-go decision.

    Read-only: it reads the published Stage 7B-13A artefacts (including the Stage 12A and 13A
    answer sheets), writes only Stage 14 records and one document, and changes nothing.
    """
    from atari_music import stage14

    archaeology = archaeology_dir or stage14.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage14.run_synthesis(arch_root=archaeology)
    written = stage14.write_synthesis(bundle, stage14_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo(f"Capability rows judged: {summary['capabilities_judged']}.")
    click.echo(f"  perceptually useful, NEGATIVE: {len(summary['perceptually_useful_negative'])}")
    click.echo(f"  perceptually useful, POSITIVE: {len(summary['perceptually_useful_positive'])}")
    for key, value in summary["hypotheses"].items():
        click.echo(f"  {key}: {value}")
    click.echo(f"  direct transfer: {summary['direct_transfer']}")
    click.echo(f"  context dependence: {summary['context_dependence']}")
    click.echo(f"  {summary['recommendation']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage15")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage15"),
    help="Where to write the Stage 15 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage15_performance_style.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
@click.option(
    "--player-asm",
    type=click.Path(path_type=Path),
    default=None,
    help="The 6502 player to inspect (defaults to the module's DEFAULT_PLAYER_ASM).",
)
@click.option(
    "--no-measure/--measure",
    "no_measure",
    default=False,
    help="Skip re-assembling the player and use the recorded size instead.",
)
def analyze_stage15_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    player_asm: Optional[Path],
    no_measure: bool,
) -> None:
    """Analyse one SAP as a POKEY performance style and compare it with the current player.

    Read-only: it reads the corpus' published frame trace and the player source, writes only
    Stage 15 records and one document, and changes nothing. It renders no audio, generates no
    music, and asks for no listening.
    """
    from atari_music import stage15

    archaeology = archaeology_dir or stage15.DEFAULT_ARCHAEOLOGY_DIR
    bundle = stage15.run_analysis(
        arch_root=archaeology,
        player_asm=player_asm or stage15.DEFAULT_PLAYER_ASM,
        live_measure=not no_measure,
    )
    written = stage15.write_analysis(bundle, stage15_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    song = summary["reference_song"]
    click.echo(
        f"Reference song: {song['title']} ({song['song']} sub{song['subsong']}), "
        f"{song['author']} {song['date']} — rank {song['rank']}, AUDCTL {song['audctl']}."
    )
    click.echo(
        f"  selection unanimous across orderings: {song['selection_unanimous']}"
    )
    click.echo(
        f"Events: {summary['events']['total']} in {summary['events']['techniques']} techniques."
    )
    for name, count in summary["events"]["classifications"].items():
        click.echo(f"  {name}: {count}")
    click.echo(f"  classes absent: {', '.join(summary['events']['classes_absent']) or 'none'}")
    for name, count in summary["context"]["verdict_counts"].items():
        click.echo(f"  context {name}: {count}")
    player = summary["player"]
    click.echo(
        f"Player: {player['assembled_bytes']} bytes assembled "
        f"({player['code_bytes']} code + {player['state_bytes']} state), "
        f"{player['headroom_in_2KB']} bytes of headroom in 2 KB."
    )
    click.echo(
        f"  mechanisms needed: ~{player['estimated_mechanisms_bytes']} bytes, "
        f"{player['headroom_after_mechanisms']} bytes left."
    )
    click.echo(
        f"  unrolled song data would be {player['unrolled_song_data_bytes']} bytes "
        f"({player['unrolled_ratio']}x)."
    )
    click.echo(f"  {summary['verdicts']['performance_style']['verdict']} + "
               f"{summary['verdicts']['player_expansion']['verdict']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage16")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage16"),
    help="Where to write the Stage 16 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage16_cross_song_generalization.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
@click.option(
    "--stage15-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 15 artefacts live (read-only; defaults to the module default).",
)
def analyze_stage16_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    stage15_dir: Optional[Path],
) -> None:
    """Test whether the Stage 15 performance style generalises across songs.

    Read-only: it re-uses the Stage 15 analysis unchanged, reads the corpus traces and the
    Stage 15 record through their hashes, writes only Stage 16 records and one document, and
    changes nothing. It renders no audio, generates no music, and asks for no listening.
    """
    from atari_music import stage16

    bundle = stage16.run_analysis(
        arch_root=archaeology_dir or stage16.DEFAULT_ARCHAEOLOGY_DIR,
        stage15_dir=stage15_dir or stage16.DEFAULT_STAGE15_DIR,
    )
    written = stage16.write_analysis(bundle, stage16_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo("Songs: " + ", ".join(summary["songs"]))
    click.echo(
        "Techniques in the union: "
        f"{summary['vocabulary']['techniques_in_union']} "
        f"({summary['vocabulary']['techniques_in_all_songs']} in all four, "
        f"{summary['vocabulary']['techniques_in_one_song_only']} in one only)"
    )
    click.echo(
        f"  mean pairwise Jaccard {summary['vocabulary']['mean_pairwise_jaccard']}, "
        f"share-weighted Ruzicka {summary['vocabulary']['mean_pairwise_ruzicka']}"
    )
    loo = summary["leave_one_out"]
    click.echo(
        f"Leave-one-song-out: technique {loo['technique_coverage']}, "
        f"core-context prediction {loo['core_context_coverage']}, "
        f"dominant-context match {loo['core_context_dominant_match']}, "
        f"parameter support {loo['parameter_coverage']}"
    )
    click.echo(
        "Transferability vector: "
        + ", ".join(f"{name} {value}" for name, value in summary["transferability_vector"].items())
    )
    click.echo(
        "Universality: "
        + ", ".join(f"{name} {value}" for name, value in summary["universality_counts"].items())
    )
    click.echo(
        f"  {summary['verdicts']['generalization']['verdict']} + "
        f"{summary['verdicts']['model']['verdict']}"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage17")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage17"),
    help="Where to write the Stage 17 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage17_performance_event_language.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
@click.option(
    "--stage15-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 15 artefacts live (read-only; defaults to the module default).",
)
@click.option(
    "--stage16-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 16 artefacts live (read-only; defaults to the module default).",
)
def analyze_stage17_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    stage15_dir: Optional[Path],
    stage16_dir: Optional[Path],
) -> None:
    """Define and test a compact POKEY performance event language.

    Read-only and research-only: it reads the corpus traces and the Stage 15/16 records through
    their hashes, defines an event vocabulary from observed behaviour, and measures a round trip
    with an offline interpreter. It renders no audio, generates no music, changes no Composer,
    DSL, IR or player source, and asks for no listening.
    """
    from atari_music import stage17

    bundle = stage17.run_analysis(
        arch_root=archaeology_dir or stage17.DEFAULT_ARCHAEOLOGY_DIR,
        stage15_dir=stage15_dir or stage17.DEFAULT_STAGE15_DIR,
        stage16_dir=stage16_dir or stage17.DEFAULT_STAGE16_DIR,
    )
    written = stage17.write_analysis(bundle, stage17_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo("Songs: " + ", ".join(summary["songs"]))
    click.echo(
        f"Vocabulary: {summary['opcode_count']} opcodes "
        f"from {summary['techniques_in_union']} observed techniques"
    )
    click.echo(
        "Reconstruction (mean exact share): "
        + ", ".join(
            f"{name} {value}" for name, value in summary["exact_share"].items()
        )
    )
    click.echo(
        "Compression: "
        f"{summary['compression']['ratio_to_raw_dump_before_repair']}x a raw frame dump "
        f"({summary['compression']['ratio_to_raw_dump_after_repair']}x repaired), "
        f"{summary['compression']['ratio_to_current_format_after_repair']}x the current format"
    )
    player = summary["player"]
    click.echo(
        f"Player: {player['baseline_bytes']} measured baseline, "
        f"{player['projected_bytes_estimate']} estimated after (ESTIMATE), "
        f"{player['headroom_bytes']} headroom in {player['envelope_bytes']} -> {player['label']}"
    )
    click.echo(f"Macros: {summary['macros']}")
    click.echo(
        f"  {summary['verdicts']['event_language']} + "
        f"{summary['verdicts']['two_kb_player']} + "
        f"{summary['verdicts']['main_bottleneck']}"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage18")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage18"),
    help="Where to write the Stage 18 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage18_temporal_compression.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's DEFAULT_ARCHAEOLOGY_DIR).",
)
@click.option(
    "--stage17-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 17 artefacts live (read-only; defaults to the module default).",
)
def analyze_stage18_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    stage17_dir: Optional[Path],
) -> None:
    """Test whether the POKEY history has usable temporal redundancy.

    Read-only and research-only: it reads the corpus traces and the Stage 16/17 records through
    their hashes, defines one canonical raw representation, implements several byte formats, and
    decodes every one of them back for a byte-for-byte comparison. It renders no audio, generates
    no music, changes no Composer, DSL, IR or player source, and asks for no listening.
    """
    from atari_music import stage18

    bundle = stage18.run_analysis(
        arch_root=archaeology_dir or stage18.DEFAULT_ARCHAEOLOGY_DIR,
        stage17_dir=stage17_dir or stage18.DEFAULT_STAGE17_DIR,
    )
    written = stage18.write_analysis(bundle, stage18_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo("Songs: " + ", ".join(summary["songs"]))
    click.echo(
        f"Canonical raw baseline: {bundle['raw_baseline']['songs'][0]['payload_bytes']} bytes on "
        "the first song (9 bytes per frame, absolute state)"
    )
    click.echo(
        f"Measurements: {summary['measurements']}, all lossless: {summary['all_lossless']}"
    )
    best = summary["best_overall"]
    click.echo(
        f"Best: {best['label']} mean ratio {best['mean_ratio']} "
        f"(saving {best['mean_saving_percent']}%), worst song {best['max_ratio']}"
    )
    click.echo(
        "Best per family: "
        + ", ".join(f"{name} {value}" for name, value in summary["best_per_group_ratio"].items())
    )
    click.echo(
        "Dictionary scopes: "
        + ", ".join(f"{name} {value}" for name, value in summary["dictionary_scopes"].items())
    )
    comparison = summary["comparison"]
    click.echo(
        f"Versus Stage 17 exact IR: {comparison['stage17_exact_vs_temporal_mean']}x smaller. "
        f"Versus the current note format: it is "
        f"{comparison['current_note_format_vs_temporal_mean']} of the temporal encoding"
    )
    click.echo(
        f"  {summary['verdicts']['temporal_compression']} + "
        f"{summary['verdicts']['player_integration']}"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage19")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage19"),
    help="Where to write the Stage 19 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage19_temporal_grammar.md.",
)
@click.option(
    "--stage16-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 16 selection record lives (read-only).",
)
@click.option(
    "--stage17-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 17 artefacts live (read-only).",
)
@click.option(
    "--stage18-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 18 artefacts live (read-only).",
)
def analyze_stage19_cmd(
    reports_dir: Path,
    docs_dir: Path,
    stage16_dir: Optional[Path],
    stage17_dir: Optional[Path],
    stage18_dir: Optional[Path],
) -> None:
    """Test whether the POKEY history has a small, neutral, shared temporal grammar.

    Read-only and research-only: it reads the corpus and the Stage 15/16/17/18 records through
    their hashes, induces a temporal grammar bottom-up, and encodes and decodes every candidate.
    It renders no audio, generates no music, changes no composer, DSL, IR or player source, and
    asks for no listening.
    """
    from atari_music import stage19

    bundle = stage19.run_analysis(
        stage16_dir=stage16_dir or stage19.DEFAULT_STAGE16_DIR,
        stage17_dir=stage17_dir or stage19.DEFAULT_STAGE17_DIR,
        stage18_dir=stage18_dir or stage19.DEFAULT_STAGE18_DIR,
    )
    written = stage19.write_analysis(bundle, stage19_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo("Songs: " + ", ".join(summary["songs"]))
    click.echo(
        "Candidate vocabulary: " + ", ".join(summary["primitive_vocabulary"])
        + " (LITERAL is the residual channel, REPEAT is the induced construction)"
    )
    click.echo(
        "Induced per song: "
        + "; ".join(
            f"{slug.split('_')[0]} {'+'.join(primitives)}"
            for slug, primitives in summary["induced_vocabulary_by_song"].items()
        )
    )
    click.echo(
        "Shared vocabulary (all four): " + ", ".join(summary["shared_vocabulary"])
    )
    click.echo(
        f"Grammar ratio {summary['grammar_ratio']:.4f}, with grammar and decoder charged "
        f"{summary['grammar_ratio_with_grammar']:.4f}, structural coverage "
        f"{summary['grammar_structural_coverage']}, residual share "
        f"{summary['grammar_residual_share']}"
    )
    click.echo(
        f"REPEAT lexicon: in-sample {summary['repeat_ratio']:.4f}, leave-one-out "
        f"{summary['repeat_leave_one_out_ratio']:.4f}, references that transferred "
        f"{summary['repeat_references_transferred']}"
    )
    click.echo(
        f"Leave-one-out: vocabulary {summary['leave_one_out_ratios']['union_vocabulary_arm']}, "
        f"frozen parameters {summary['leave_one_out_ratios']['frozen_parameter_arm']}"
    )
    click.echo(f"All exact: {summary['all_exact']}")
    click.echo(
        f"  {summary['verdicts']['H1']} + {summary['verdicts']['H2']} + "
        f"{summary['verdicts']['H3']} + {summary['verdicts']['player_integration']}"
    )
    click.echo(f"  deciding condition: {summary['deciding_condition']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage20")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage20"),
    help="Where to write the Stage 20 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage20_residual_performance.md.",
)
@click.option(
    "--stage16-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the Stage 16 selection record lives (read-only).",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's default).",
)
def analyze_stage20_cmd(
    reports_dir: Path,
    docs_dir: Path,
    stage16_dir: Optional[Path],
    archaeology_dir: Optional[Path],
) -> None:
    """Measure what the note representation does not explain, and test the residual's structure.

    Read-only and research-only: it reads the corpus traces and the Stage 15-19 records through
    their hashes, builds an explicit note-level baseline from the repository's own pitch and
    envelope functions, forms an exact residual, and measures how much of that residual the Stage
    19 grammar explains and whether it generalises. It renders no audio, generates no music, changes
    no composer, DSL, IR or player source, and asks for no listening.
    """
    from atari_music import stage20

    bundle = stage20.run_analysis(
        stage16_dir=stage16_dir or stage20.DEFAULT_STAGE16_DIR,
        arch_root=archaeology_dir or stage20.DEFAULT_ARCHAEOLOGY_DIR,
    )
    written = stage20.write_analysis(bundle, stage20_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo("Songs: " + ", ".join(summary["songs"]))
    click.echo(
        f"Note baseline: register coverage {summary['note_register_coverage']:.4f}, "
        f"frame coverage {summary['note_frame_coverage']:.4f}"
    )
    click.echo(
        f"Residual: {summary['residual_share']:.4f} of register values "
        f"({summary['residual_register_values']} of {summary['register_values']})"
    )
    click.echo(
        f"Stage 19 grammar on the residual: structural share "
        f"{summary['grammar_structural_share']:.4f}, size gain "
        f"{summary['grammar_size_gain']:.4f}"
    )
    click.echo(
        f"  adds {summary['additional_explained_share']:.4f} of the whole stream; "
        f"{summary['remaining_share']:.4f} remains"
    )
    click.echo(
        f"Nulls and controls: no-notes floor {summary['null_no_notes_coverage']:.4f}, "
        f"shifted {summary['control_shifted_coverage']:.4f}, shuffled residual "
        f"{summary['null_shuffled_structural_share']:.4f}"
    )
    click.echo(f"Level model fidelity: {summary['level_model_fidelity']:.4f}")
    click.echo(
        "Leave-one-out gains: "
        + ", ".join(f"{name} {value:.4f}" for name, value in summary["leave_one_out_gain"].items())
    )
    click.echo(
        "  " + " + ".join(summary["verdicts"].values())
    )
    click.echo(f"  deciding condition: {summary['deciding_condition']}")
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage21")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage21"),
    help="Where to write the Stage 21 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage21_controlled_validation.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's default).",
)
@click.option(
    "--songs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent .dsl compositions live (read-only).",
)
@click.option(
    "--ai-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent AI composition documents live (read-only).",
)
@click.option(
    "--control-limit",
    type=int,
    default=None,
    help="Use only the first N control compositions (a bounded smoke run; default is all).",
)
@click.option(
    "--detail-limit",
    type=int,
    default=None,
    help="Run the per-song detail on only the first N control songs (default is all).",
)
@click.option(
    "--historical-limit",
    type=int,
    default=None,
    help="Use only N historical traces, always keeping the four Stage 20 songs (default is all).",
)
def analyze_stage21_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    songs_dir: Optional[Path],
    ai_dir: Optional[Path],
    control_limit: Optional[int],
    detail_limit: Optional[int],
    historical_limit: Optional[int],
) -> None:
    """Validate the note-level explanation against independent compositions.

    Read-only and research-only: it audits what data exists, assigns evidence tiers, and then runs
    the same Stage 20 pipeline over traces whose composition is known, so the instrument Stage 20
    measured with can be calibrated. It reads the corpus traces, the .dsl scores and the AI
    composition documents through their hashes and writes nothing but its own artefacts. It renders
    no audio, generates no music, changes no composer, DSL, IR or player source, and asks for no
    listening.
    """
    from atari_music import stage21

    bundle = stage21.run_analysis(
        arch_root=archaeology_dir or stage21.DEFAULT_ARCHAEOLOGY_DIR,
        songs_dir=songs_dir or stage21.DEFAULT_SONGS_DIR,
        ai_dir=ai_dir or stage21.DEFAULT_AI_DIR,
        control_limit=control_limit,
        detail_limit=detail_limit,
        historical_limit=historical_limit,
    )
    written = stage21.write_analysis(bundle, stage21_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo(
        f"Dataset: {summary['historical_songs']} historical songs all Tier "
        f"{'/'.join(summary['historical_tiers'])}, {summary['control_songs']} in-house "
        f"compositions all Tier {'/'.join(summary['in_house_tiers'])}"
    )
    click.echo(f"  dataset verdict: {summary['dataset_verdict']}")
    click.echo(
        f"Predictor bridge: holds = {summary['predictor_bridge_holds']}"
    )
    click.echo(
        f"Control corpus, independent composition notes: residual "
        f"{summary['control_independent_residual_values']} of "
        f"{summary['control_register_values']} register values "
        f"({summary['control_independent_residual_share']:.4f})"
    )
    click.echo(
        f"Control corpus, Stage 15 detector notes: residual "
        f"{summary['control_residual_share']:.4f}; detector recall "
        f"{summary['control_detector_recall']:.4f}; pitch exact "
        f"{summary['control_pitch_exact_share']:.4f}"
    )
    click.echo(
        f"Historical corpus, Stage 15 detector notes: residual "
        f"{summary['historical_residual_share']:.4f}"
    )
    click.echo(
        f"Stage 19 frozen grammar structural share: known-artefact residual "
        f"{summary['control_grammar_structural_share']:.4f} against historical "
        f"{summary['historical_grammar_structural_share']:.4f}"
    )
    click.echo(f"  null instrument test: {summary['null_instrument_verdict']}")
    click.echo("  " + " + ".join(summary["verdicts"].values()))
    click.echo(
        f"  performance layer direction: {summary['performance_layer_direction']}"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage22")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage22"),
    help="Where to write the Stage 22 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage22_detector_error_decomposition.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's default).",
)
@click.option(
    "--songs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent .dsl compositions live (read-only).",
)
@click.option(
    "--ai-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent AI composition documents live (read-only).",
)
@click.option(
    "--control-limit",
    type=int,
    default=None,
    help="Use only the first N control compositions (a bounded smoke run; default is all).",
)
@click.option(
    "--detail-limit",
    type=int,
    default=None,
    help="Run the per-song detail on only the first N control songs (default is all).",
)
@click.option(
    "--historical-limit",
    type=int,
    default=None,
    help="Use only N historical traces (default is all).",
)
def analyze_stage22_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    songs_dir: Optional[Path],
    ai_dir: Optional[Path],
    control_limit: Optional[int],
    detail_limit: Optional[int],
    historical_limit: Optional[int],
) -> None:
    """Decompose the Stage 15 detector's residual on ground-truth compositions.

    Read-only and diagnostic-only: it compiles the Tier A control corpus to exact traces, runs the
    existing detector over them, and attributes the residual to named, measured causes. It does not
    repair the detector, does not re-open the performance-layer question, and writes nothing but its
    own artefacts. It renders no audio, generates no music, and changes no composer, DSL, IR or
    player source.
    """
    from atari_music import stage22

    bundle = stage22.run_analysis(
        arch_root=archaeology_dir or stage22.DEFAULT_ARCHAEOLOGY_DIR,
        songs_dir=songs_dir or stage22.DEFAULT_SONGS_DIR,
        ai_dir=ai_dir or stage22.DEFAULT_AI_DIR,
        control_limit=control_limit,
        detail_limit=detail_limit,
        historical_limit=historical_limit,
    )
    written = stage22.write_analysis(bundle, stage22_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    partition = bundle["taxonomy"]["cause_partition"]
    click.echo(
        f"Control corpus: {summary['control_songs']} Tier A compositions, "
        f"{summary['control_notes']} sounding notes, {summary['register_values']} register values"
    )
    click.echo(
        f"  Stage 15 detector residual: {summary['detector_residual_values']} "
        f"({summary['detector_residual_share']:.4f}); under the exporter convention "
        f"{summary['detector_residual_share_exporter']:.4f}"
    )
    click.echo(
        f"  cause partition: note set {partition['note_set_share']:.4f}, "
        f"value reading {partition['value_share']:.4f}, "
        f"interaction {partition['interaction_share']:.4f} "
        f"(closes = {partition['closes']})"
    )
    click.echo(
        f"  B10 (the exact composition): {summary['b10_values']} register values "
        f"(zero = {summary['b10_is_zero']})"
    )
    click.echo(
        f"  level-contour marginal: {summary['envelope_marginal_values']}; "
        f"channel/volume/AUDCTL marginals: {summary['noop_field_marginals']}"
    )
    click.echo(
        f"  note precision {summary['note_precision_by_count']:.4f}, "
        f"recall {summary['note_recall_by_count']:.4f}, "
        f"merged spans {summary['merged_spans']}, false spans {summary['false_spans']}; "
        f"pitch exact {summary['pitch_divider_exact_share']:.4f}, "
        f"generator onset exact {summary['generator_onset_correct_share']:.4f}"
    )
    click.echo(
        f"Historical comparison: residual share ratio "
        f"{summary['residual_share_ratio']} -> {summary['falsification_verdict']}"
    )
    click.echo("  " + " + ".join(summary["verdicts"].values()))
    click.echo(
        f"  read-only audit: {summary['read_only']} over "
        f"{summary['read_only_files_checked']} production and composition artefacts"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage23")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage23"),
    help="Where to write the Stage 23 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage23_controlled_historical_residual_test.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's default).",
)
@click.option(
    "--songs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent .dsl compositions live (read-only).",
)
@click.option(
    "--ai-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent AI composition documents live (read-only).",
)
@click.option(
    "--skip-reproducibility",
    is_flag=True,
    default=False,
    help="Skip the second pass that verifies the analysis is byte-identical.",
)
def analyze_stage23_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    songs_dir: Optional[Path],
    ai_dir: Optional[Path],
    skip_reproducibility: bool,
) -> None:
    """Test whether the historical residual difference is real or an artefact.

    Read-only and analysis-only: it compares the historical and the control corpus on a
    convention-free residual estimand, applies composition matching, a source-clustered bootstrap,
    leave-one-source-out and negative controls, and reports whether the difference is robust and
    identified. It changes no detector, compiles nothing, renders no audio and generates no music.
    """
    from atari_music import stage23

    bundle = stage23.run_analysis(
        arch_root=archaeology_dir or stage23.DEFAULT_ARCHAEOLOGY_DIR,
        songs_dir=songs_dir or stage23.DEFAULT_SONGS_DIR,
        ai_dir=ai_dir or stage23.DEFAULT_AI_DIR,
        verify_reproducibility=not skip_reproducibility,
    )
    written = stage23.write_analysis(bundle, stage23_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    test = bundle["history_specific_test"]
    click.echo(
        f"Corpora: {summary['historical_traces']} historical traces from "
        f"{summary['historical_sources']} SAP sources / {summary['historical_authors']} composers, "
        f"{summary['control_songs']} control compositions"
    )
    click.echo(
        f"  primary estimand {summary['primary_estimand']} (convention-free): control "
        f"{summary['primary_control_mean']:.4f}, historical "
        f"{summary['primary_historical_mean']:.4f}, difference "
        f"{summary['primary_difference']:+.4f} "
        f"[{summary['primary_ci'][0]:+.4f}, {summary['primary_ci'][1]:+.4f}]"
    )
    click.echo(
        f"  sign stable across definitions: {summary['sign_stable_across_definitions']}; "
        f"preserved leave-one-source-out: {summary['sign_preserved_leave_one_source_out']}; "
        f"channels positive: {summary['channels_with_positive_difference']}/4"
    )
    click.echo(
        f"  matched gap {summary['matched_gap_mean']} against a control leave-one-out error of "
        f"{summary['control_loo_mae']}; extrapolations "
        f"{summary['traces_beyond_control_support']}/{summary['historical_traces']}"
    )
    click.echo(
        "  features with no common range: "
        + (", ".join(summary["features_without_common_range"]) or "none")
    )
    click.echo(f"  history-specific criteria: {test['criteria_passed']}/{test['criteria_total']}")
    click.echo("  verdicts:")
    for subject, verdict in sorted(summary["verdicts"].items()):
        click.echo(f"    {subject}: {verdict}")
    click.echo(
        f"  reproducibility: {summary['reproducible']}; read-only: {summary['read_only']} over "
        f"{summary['read_only_files_checked']} files"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage24")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage24"),
    help="Where to write the Stage 24 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage24_corpus_overlap_and_confounding.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's default).",
)
@click.option(
    "--songs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent .dsl compositions live (read-only).",
)
@click.option(
    "--ai-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent AI composition documents live (read-only).",
)
@click.option(
    "--skip-reproducibility",
    is_flag=True,
    default=False,
    help="Skip the second pass that verifies the analysis is byte-identical.",
)
def analyze_stage24_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    songs_dir: Optional[Path],
    ai_dir: Optional[Path],
    skip_reproducibility: bool,
) -> None:
    """Test whether the historical-versus-control residual comparison is identifiable.

    Read-only and analysis-only: it audits both corpora, defines a common feature set, measures
    univariate and multivariate overlap, re-derives the matching with a declared balance criterion,
    and reports whether the difference can be located in a comparable population. It changes no
    detector, compiles nothing, renders no audio, creates no corpus and generates no music.
    """
    from atari_music import stage24

    bundle = stage24.run_analysis(
        arch_root=archaeology_dir or stage24.DEFAULT_ARCHAEOLOGY_DIR,
        songs_dir=songs_dir or stage24.DEFAULT_SONGS_DIR,
        ai_dir=ai_dir or stage24.DEFAULT_AI_DIR,
        verify_reproducibility=not skip_reproducibility,
    )
    written = stage24.write_analysis(bundle, stage24_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo(
        f"Corpora: {summary['historical_traces']} historical traces from "
        f"{summary['historical_sources']} SAP sources / {summary['historical_authors']} composers, "
        f"{summary['control_traces']} control compositions"
    )
    click.echo(
        f"  matching features {summary['matching_features']}, excluded {summary['excluded_features']}; "
        f"strictly separated {summary['features_separated'] or 'none'}, "
        f"degenerate {summary['features_degenerate'] or 'none'}"
    )
    click.echo(
        f"  support: {summary['historical_inside_control_box']}/{summary['historical_traces']} "
        f"historical inside the control box vs "
        f"{summary['control_inside_control_box_leave_one_out']}/{summary['control_traces']} control "
        f"leave-one-out; {summary['historical_in_propensity_region']} historical in the propensity "
        f"overlap region"
    )
    click.echo(
        f"  nearest historical distance {summary['historical_nearest_min']} against a control "
        f"leave-one-out maximum of {summary['control_loo_max']}; "
        f"{summary['historical_beyond_control_loo_max']} beyond it"
    )
    click.echo(
        f"  matching: {summary['methods']} methods, {summary['reportable_methods']} reportable, "
        f"{summary['validated_methods']} validated"
    )
    click.echo(
        f"  raw difference {summary['raw_difference']} "
        f"[{summary['raw_ci'][0]}, {summary['raw_ci'][1]}]; stability {summary['stability']}"
    )
    click.echo(
        f"  falsification: {summary['falsification_passed']}/{summary['falsification_total']} "
        "conditions pass"
    )
    click.echo(
        f"  A/B/C: descriptive {summary['descriptive_answer']}; matched "
        f"{summary['matched_answer']}; identified {summary['identified_answer']}"
    )
    click.echo(f"  verdict: {summary['verdict']}")
    for verdict in summary["auxiliary_verdicts"]:
        click.echo(f"    {verdict}")
    click.echo(
        f"  reproducibility: {summary['reproducible']}; read-only: {summary['read_only']} over "
        f"{summary['read_only_files_checked']} files"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


@cli.command("analyze-stage25")
@click.option(
    "--reports-dir",
    type=click.Path(path_type=Path),
    default=Path("reports/stage25"),
    help="Where to write the Stage 25 machine record.",
)
@click.option(
    "--docs-dir",
    type=click.Path(path_type=Path),
    default=Path("docs"),
    help="Where to write stage25_matched_control_corpus_design.md.",
)
@click.option(
    "--archaeology-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="The corpus repository (defaults to the module's default).",
)
@click.option(
    "--songs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent .dsl compositions live (read-only).",
)
@click.option(
    "--ai-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where the independent AI composition documents live (read-only).",
)
@click.option(
    "--skip-reproducibility",
    is_flag=True,
    default=False,
    help="Skip the second pass that verifies the analysis is byte-identical.",
)
def analyze_stage25_cmd(
    reports_dir: Path,
    docs_dir: Path,
    archaeology_dir: Optional[Path],
    songs_dir: Optional[Path],
    ai_dir: Optional[Path],
    skip_reproducibility: bool,
) -> None:
    """Design and validate a matched control corpus for the Stage 24 support gap.

    Read-only and analysis-only, plus a deliberately minimal pilot: it probes the real pipeline for
    the configurations the design needs, classifies every matching feature as controllable or only
    observable, declares a corpus design with a stated size floor, runs four compositions through the
    production compiler to prove the mechanics, and states which parts of the problem no corpus can
    fix. It modifies no production file, builds no corpus, renders no audio and generates no music.
    """
    from atari_music import stage25

    bundle = stage25.run_analysis(
        arch_root=archaeology_dir or stage25.DEFAULT_ARCHAEOLOGY_DIR,
        songs_dir=songs_dir or stage25.DEFAULT_SONGS_DIR,
        ai_dir=ai_dir or stage25.DEFAULT_AI_DIR,
        verify_reproducibility=not skip_reproducibility,
    )
    written = stage25.write_analysis(bundle, stage25_dir=reports_dir, docs_dir=docs_dir)

    summary = bundle["summary"]
    click.echo(
        f"Stage 24 left: {summary['stage24_verdict']} - "
        f"{summary['historical_inside_joint_box']}/{summary['historical_traces']} historical traces "
        f"inside the joint control box against "
        f"{summary['control_inside_joint_box_leave_one_out']} control leave-one-out"
    )
    click.echo(
        f"  capability: {summary['capabilities_reachable']}/{summary['capabilities_total']} probed "
        f"capabilities reachable; production changes required: "
        f"{summary['production_changes_required'] or 'none'}"
    )
    click.echo(
        f"  length: {summary['max_reachable_frames']} frames reachable against a historical maximum "
        f"of {summary['historical_max_frames']}"
    )
    click.echo(
        f"  design: {summary['design_groups']} groups, minimum {summary['design_minimum_size']} "
        f"compositions ({summary['design_floor_control_traces']} control traces floor)"
    )
    click.echo(
        f"  pilot: {summary['pilot_built']}/{summary['pilot_specs']} built, "
        f"{summary['pilot_passed']}/{summary['pilot_total']} continuation criteria passed"
    )
    click.echo(
        f"  ground truth: {summary['ground_truth_consistent']}; caliper enforced: "
        f"{summary['caliper_enforced']}; caliper retains everything above: "
        f"{summary['caliper_retains_everything_above']}"
    )
    click.echo(f"  validation scope: {summary['validation_scope']}")
    click.echo(f"  verdict: {summary['verdict']}")
    for verdict in summary["auxiliary_verdicts"]:
        click.echo(f"    {verdict}")
    click.echo(
        f"  reproducibility: {summary['reproducible']}; read-only: {summary['read_only']} over "
        f"{summary['read_only_files_checked']} files"
    )
    for name, path in sorted(written.items()):
        click.echo(f"  {name}: {path}")


if __name__ == "__main__":
    cli()









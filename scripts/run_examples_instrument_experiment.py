#!/usr/bin/env python
"""Build every example composition as a XEX **and** a WAV, plain and per Lead Library instrument.

What it does
------------
Discovers every input composition under ``examples/``, enumerates the instruments in the Lead
Library dynamically, and for each song produces one ``plain`` variant plus one variant per
instrument, each as a matched ``.xex`` / ``.wav`` pair. Everything lands under
``build/examples_instrument_experiment/`` together with ``manifest.json`` and ``report.md``.

How the two formats are kept consistent
---------------------------------------
Both artifacts are produced by the **real CLI**, and both go through the same
``cli._apply_selections`` call inside it:

* ``atari-music build-xex <src> -o <xex> --format <json|dsl> [--instrument PART=ID]``
* ``atari-music import-json|import-dsl <src> --output-wav <wav> [--instrument PART=ID]``

so the WAV and the XEX of one variant are rendered from the same POKEY IR. Nothing here
re-implements the pipeline, and no source file under ``examples/`` is touched.

Which part an instrument is applied to
--------------------------------------
The Lead Library declares ``role: "lead"`` for every entry (``README.md``: "always ``lead`` in
this library"). The composition side declares a ``character`` per instrument, and the two lead
characters are ``bright_lead`` and ``dark_lead``. The part rule is therefore:

1. the part whose ``character`` is a lead character, else
2. the part whose ``id`` is exactly ``lead``, else
3. the composition's first declared instrument (recorded as a fallback).

Which rule matched is recorded per song in the manifest, so no mapping is implicit.

Reruns
------
The experiment owns ``build/examples_instrument_experiment/`` and nothing else. A normal run
removes that directory before writing, so a rerun can never leave a stale artifact behind;
``--no-clean`` skips the removal. The directory is only ever removed when its name matches the
experiment, so a mistyped ``--output-dir`` cannot delete something else.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from atari_music import stage15, xex_layout  # noqa: E402
from atari_music.ai.dsl import parse_music_dsl  # noqa: E402
from atari_music.ai.schema import AICompositionDoc  # noqa: E402

EXPERIMENT_NAME = "examples_instrument_experiment"
EXAMPLES_DIR = REPO_ROOT / "examples"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / EXPERIMENT_NAME
DEFAULT_LIBRARY = REPO_ROOT / "data" / "instrument_libraries" / "lead" / "v0.1"
MADS_EXE = REPO_ROOT / "tools" / "mads" / "mads.exe"

#: The composition ``character`` values that mean "this is a lead part".
LEAD_CHARACTERS: Tuple[str, ...] = ("bright_lead", "dark_lead")

#: Lead Library role -> the composition characters that part may be applied to.
ROLE_CHARACTERS: Dict[str, Tuple[str, ...]] = {"lead": LEAD_CHARACTERS}

#: A WAV shorter than this is reported as unexpectedly short.
WAV_MIN_SECONDS = 1.0

#: How far a variant's duration may drift from its song's ``plain`` before it is flagged.
WAV_DURATION_TOLERANCE_S = 0.5


def _log(message: str) -> None:
    print(message, flush=True)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _song_id(rel_path: str) -> str:
    """A stable, filesystem-safe id that keeps enough of the path to stay unique.

    ``examples/ai/live/stage15/div_01_dark_dungeon.json`` -> ``ai__live__stage15__div_01_dark_dungeon__json``

    The extension is part of the id on purpose: ``examples/songs/Vaults-of-Nhyrmeth.dsl`` and
    ``examples/songs/Vaults-of-Nhyrmeth.json`` are two different compositions whose stems agree,
    and dropping the extension would make them share one directory.
    """
    rel = Path(rel_path)
    parts = rel.parts[1:] if rel.parts and rel.parts[0] == "examples" else rel.parts
    stem = Path(*parts).with_suffix("").as_posix()
    extension = rel.suffix.lstrip(".").lower() or "none"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem.replace("/", "__"))
    return f"{safe}__{extension}"


def _read_composition(path: Path) -> Tuple[Any, str]:
    """Return ``(document, format)`` for a JSON or DSL composition."""
    if path.suffix.lower() == ".json":
        return AICompositionDoc.model_validate(json.loads(path.read_text(encoding="utf-8"))), "json"
    return parse_music_dsl(path.read_text(encoding="utf-8")), "dsl"


def discover_compositions() -> List[Dict[str, Any]]:
    """Every input composition under ``examples/``, whatever its supported format.

    A JSON file counts only when it declares ``format == "atari-music-composition"``: the tree
    also holds metrics, analysis and manifest documents that are not inputs.
    """
    found: List[Dict[str, Any]] = []
    for path in sorted(EXAMPLES_DIR.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith(".binding.json"):
            continue  # a binding is configuration, not a composition
        if path.suffix.lower() not in (".json", ".dsl"):
            continue
        try:
            if path.suffix.lower() == ".json":
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not (isinstance(raw, dict) and raw.get("format") == "atari-music-composition"):
                    continue
            doc, fmt = _read_composition(path)
        except Exception:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        found.append({
            "rel_path": rel,
            "song_id": _song_id(rel),
            "format": fmt,
            "title": str(doc.metadata.title),
            "parts": [(str(i.id), str(i.character)) for i in doc.instruments],
        })
    return found


def lead_part(parts: Sequence[Tuple[str, str]], characters: Sequence[str]) -> Tuple[Optional[str], str]:
    """The part an instrument of the given characters belongs on, and which rule chose it."""
    for part_id, character in parts:
        if character in characters:
            return part_id, f"character:{character}"
    for part_id, _character in parts:
        if part_id == "lead":
            return part_id, "id:lead"
    if parts:
        return parts[0][0], "fallback:first-instrument"
    return None, "no-parts"


def load_instruments(library_dir: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(usable, unsupported)`` — the library's instruments, split by what this pipeline can use.

    "Usable" is decided by the mechanism's own contract, not by a hardcoded list: a
    ``bank_profile`` entry is bound through the profile-binding path, an ``experiment`` entry is
    realized as a modulation. Everything else the CLI refuses, and is reported rather than
    silently dropped.
    """
    document = json.loads((library_dir / "library.json").read_text(encoding="utf-8"))
    usable: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []
    for entry in document.get("instruments", []):
        source = (entry.get("identity") or {}).get("source") or {}
        role = str(entry.get("role") or "")
        record: Dict[str, Any] = {
            "instrument_id": str(entry.get("instrument_id")),
            "role": role,
            "kind": str(source.get("kind") or ""),
            "display_name": str(entry.get("display_name") or ""),
        }
        if role not in ROLE_CHARACTERS:
            record["reason"] = f"role {role!r} has no part mapping in this experiment"
            unsupported.append(record)
            continue
        if record["kind"] == "bank_profile":
            record["profile_id"] = str(source.get("profile_id") or "")
            record["registry_path"] = str(source.get("registry_path") or "")
            usable.append(record)
            continue
        if record["kind"] == "experiment":
            record["generator_byte"] = str(
                (source.get("implementation") or {}).get("generator_byte") or ""
            )
            usable.append(record)
            continue
        record["reason"] = f"kind {record['kind']!r} is not selectable by the CLI"
        unsupported.append(record)
    return usable, unsupported


# ---------------------------------------------------------------------------
# Generation — both formats through the real CLI
# ---------------------------------------------------------------------------
def _run(cmd: Sequence[str], timeout: int = 900) -> Dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        list(cmd), cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout,
    )
    return {
        "returncode": proc.returncode,
        "seconds": round(time.perf_counter() - started, 3),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _instrument_args(part: Optional[str], instrument_id: Optional[str]) -> List[str]:
    if part is None or instrument_id is None:
        return []
    return ["--instrument", f"{part}={instrument_id}"]


def build_xex(
    python: str, src: Path, out: Path, fmt: str, library: Path,
    part: Optional[str], instrument_id: Optional[str],
) -> Dict[str, Any]:
    """``atari-music build-xex`` — the same command a user runs."""
    return _run([
        python, "-m", "atari_music", "build-xex", str(src), "-o", str(out),
        "--format", fmt, "--mads", str(MADS_EXE), "--instrument-library", str(library),
        *_instrument_args(part, instrument_id),
    ])


def render_wav(
    python: str, src: Path, out: Path, fmt: str, library: Path,
    part: Optional[str], instrument_id: Optional[str],
) -> Dict[str, Any]:
    """``atari-music import-json`` / ``import-dsl --output-wav`` — the same command a user runs."""
    command = "import-json" if fmt == "json" else "import-dsl"
    return _run([
        python, "-m", "atari_music", command, str(src), "--output-wav", str(out),
        "--instrument-library", str(library),
        *_instrument_args(part, instrument_id),
    ])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_xex(path: Path) -> Dict[str, Any]:
    """The project's own container + memory-layout check, plus the size facts worth recording."""
    result: Dict[str, Any] = {"exists": path.is_file(), "ok": False}
    if not path.is_file():
        result["error"] = "file was not created"
        return result
    data = path.read_bytes()
    result["size_bytes"] = len(data)
    result["non_empty"] = len(data) > 0
    # Deliberately informational: a file above 2048 bytes is not a failure.
    result["exceeds_2048"] = len(data) > 2048
    if not data:
        result["error"] = "file is empty"
        return result
    try:
        segments = xex_layout.validate_xex_layout(data)
    except xex_layout.XexLayoutError as err:
        result["error"] = str(err)
        return result
    result["ok"] = True
    result["segments"] = [
        {"start": f"${s.start:04X}", "end": f"${s.end:04X}", "length": s.length, "role": s.role}
        for s in segments
    ]
    return result


def validate_wav(path: Path) -> Dict[str, Any]:
    """Open with the standard library reader and record what it says."""
    result: Dict[str, Any] = {"exists": path.is_file(), "ok": False, "flags": []}
    if not path.is_file():
        result["error"] = "file was not created"
        return result
    result["size_bytes"] = path.stat().st_size
    result["non_empty"] = path.stat().st_size > 0
    if not result["non_empty"]:
        result["error"] = "file is empty"
        return result
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
    except Exception as err:  # wave.Error, EOFError, OSError
        result["error"] = f"not a readable WAV: {type(err).__name__}: {err}"
        return result
    duration = frames / rate if rate else 0.0
    result.update({
        "channels": channels,
        "sample_width_bytes": width,
        "sample_rate_hz": rate,
        "frames": frames,
        "duration_seconds": round(duration, 4),
        "ok": frames > 0 and rate > 0,
    })
    if frames == 0:
        result["flags"].append("empty")
    elif duration < WAV_MIN_SECONDS:
        result["flags"].append("unexpectedly_short")
    return result


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------
def build_matrix(
    compositions: Sequence[Dict[str, Any]], usable: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """The expected variants: ``plain`` plus one per usable instrument, for every song."""
    matrix: List[Dict[str, Any]] = []
    for song in compositions:
        part, rule = lead_part(song["parts"], ROLE_CHARACTERS["lead"])
        variants: List[Dict[str, Any]] = [{
            "variant": "plain",
            "instrument_id": None,
            "part": None,
            "mapping": None,
            "part_rule": None,
        }]
        for instrument in usable:
            variants.append({
                "variant": f"instrument_{instrument['instrument_id']}",
                "instrument_id": instrument["instrument_id"],
                "part": part,
                "mapping": f"{part}={instrument['instrument_id']}" if part else None,
                "part_rule": rule,
            })
        matrix.append({**song, "lead_part": part, "lead_part_rule": rule, "variants": variants})
    return matrix


def print_matrix(
    matrix: Sequence[Dict[str, Any]], usable: Sequence[Dict[str, Any]],
    unsupported: Sequence[Dict[str, Any]], output_dir: Path, library: Path,
) -> None:
    """Record the discovered matrix before anything is generated (Phase 2)."""
    total = sum(len(song["variants"]) for song in matrix)
    _log("=" * 78)
    _log(f"Experiment : {EXPERIMENT_NAME}")
    _log(f"Source dir : {EXAMPLES_DIR.relative_to(REPO_ROOT).as_posix()}")
    _log(f"Library    : {library}")
    _log(f"Output dir : {output_dir}")
    _log(f"Compositions: {len(matrix)}")
    _log(f"Instruments usable by the CLI: {len(usable)}")
    for instrument in usable:
        _log(f"  - {instrument['instrument_id']}  kind={instrument['kind']}  role={instrument['role']}")
    if unsupported:
        _log(f"Instruments NOT usable: {len(unsupported)}")
        for instrument in unsupported:
            _log(f"  x {instrument['instrument_id']}: {instrument['reason']}")
    _log(f"Expected variants: {total}  (expected artifacts: {total * 2})")
    _log("-" * 78)
    for song in matrix:
        _log(
            f"  {song['rel_path']}  [{song['format']}]  lead_part={song['lead_part']!r} "
            f"({song['lead_part_rule']})  variants={len(song['variants'])}"
        )
    _log("=" * 78)


def _tail(run: Dict[str, Any], limit: int = 400) -> str:
    text = (run.get("stderr") or run.get("stdout") or "").strip()
    return text[-limit:] if text else "(no output)"


def _stash_asm(song_dir: Path, xex_path: Path) -> None:
    """Move the ``.asm`` that ``build-xex`` leaves beside its output into the song's ``tmp/``.

    The assembly source is an intermediate of the XEX build, not a requested artifact, so it is
    kept out of the final outputs rather than mixed with them — but kept, because it is what makes
    a failed build diagnosable.
    """
    generated = xex_path.with_suffix(".asm")
    if not generated.is_file():
        return
    tmp_dir = song_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    generated.replace(tmp_dir / generated.name)


def _flag_duration_drift(variants: List[Dict[str, Any]]) -> None:
    """Flag a variant whose WAV duration differs from the song's ``plain`` beyond tolerance.

    Not a failure: the artifacts are still valid. It is the cheap sanity check that the variant
    really rendered the same song rather than a truncated or extended one.
    """
    baseline = next(
        (v["wav"].get("duration_seconds") for v in variants if v["variant"] == "plain"), None
    )
    if baseline is None:
        return
    for variant in variants:
        duration = variant["wav"].get("duration_seconds")
        if duration is None:
            continue
        delta = round(duration - baseline, 4)
        variant["wav_duration_delta_vs_plain_s"] = delta
        if abs(delta) > WAV_DURATION_TOLERANCE_S:
            variant["wav"]["flags"].append("duration_differs_from_plain")


def _flag_xex_unchanged(variants: List[Dict[str, Any]]) -> None:
    """Mark a variant whose XEX is byte-identical to its song's ``plain``.

    Not a failure — the file is a valid XEX and the variant is a valid pair — but it is a fact
    about the pipeline worth naming: the exported binary carries **one instrument record per
    POKEY channel**, chosen from the notes that actually sound on that channel. When a
    composition's lead part does not own a channel in that mapping, an override applied to the
    lead has no record to land on, so the XEX is unchanged even though the WAV is not.
    """
    plain = next((v for v in variants if v["variant"] == "plain"), None)
    if plain is None or not plain["xex"].get("ok"):
        return
    import hashlib

    baseline = hashlib.sha256((REPO_ROOT / plain["xex_path"]).read_bytes()).hexdigest()
    for variant in variants:
        if variant["variant"] == "plain" or not variant["xex"].get("ok"):
            continue
        digest = hashlib.sha256((REPO_ROOT / variant["xex_path"]).read_bytes()).hexdigest()
        variant["xex_unchanged_by_override"] = digest == baseline


def run_experiment(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    if output_dir.name != EXPERIMENT_NAME:
        raise SystemExit(
            f"refusing to write to {output_dir}: this experiment only owns a directory named "
            f"{EXPERIMENT_NAME!r}"
        )
    library = Path(args.library).resolve()
    python = sys.executable

    compositions = discover_compositions()
    usable, unsupported = load_instruments(library)
    matrix = build_matrix(compositions, usable)

    if args.only:
        matrix = [s for s in matrix if args.only in s["rel_path"]]
    if args.limit:
        matrix = matrix[: args.limit]

    duplicates = sorted({s["song_id"] for s in matrix
                         if sum(1 for o in matrix if o["song_id"] == s["song_id"]) > 1})
    if duplicates:
        raise SystemExit(
            "refusing to run: these song ids are not unique, so two compositions would write "
            f"into one directory: {duplicates}"
        )

    print_matrix(matrix, usable, unsupported, output_dir, library)
    if args.dry_run:
        _log("dry run: nothing generated")
        return 0

    if output_dir.exists() and not args.no_clean:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    player_bytes = stage15.measure_player_size(stage15.DEFAULT_PLAYER_ASM, MADS_EXE)
    if player_bytes is None:
        player_bytes = stage15.PLAYER_ASSEMBLED_BYTES_RECORDED
    player_within_limit = stage15.player_size_limit_ok(player_bytes)

    started = time.perf_counter()
    songs_out: List[Dict[str, Any]] = []
    for song in matrix:
        song_dir = output_dir / song["song_id"]
        song_dir.mkdir(parents=True, exist_ok=True)
        src = REPO_ROOT / song["rel_path"]
        _log(f"[{song['song_id']}] {song['rel_path']}")
        variant_records: List[Dict[str, Any]] = []
        for variant in song["variants"]:
            xex_path = song_dir / f"{variant['variant']}.xex"
            wav_path = song_dir / f"{variant['variant']}.wav"
            part = variant["part"]
            instrument_id = variant["instrument_id"]

            xex_run = build_xex(python, src, xex_path, song["format"], library, part, instrument_id)
            xex_check = validate_xex(xex_path)
            _stash_asm(song_dir, xex_path)
            wav_run = render_wav(python, src, wav_path, song["format"], library, part, instrument_id)
            wav_check = validate_wav(wav_path)

            build_ok = xex_run["returncode"] == 0 and xex_check["ok"]
            render_ok = wav_run["returncode"] == 0 and wav_check["ok"]
            errors: List[str] = []
            if xex_run["returncode"] != 0:
                errors.append(f"build-xex exit {xex_run['returncode']}: {_tail(xex_run)}")
            elif not xex_check["ok"]:
                errors.append(f"xex validation: {xex_check.get('error')}")
            if wav_run["returncode"] != 0:
                errors.append(f"render exit {wav_run['returncode']}: {_tail(wav_run)}")
            elif not wav_check["ok"]:
                errors.append(f"wav validation: {wav_check.get('error')}")

            _log(
                f"    {variant['variant']:<34} xex={'ok' if build_ok else 'FAIL'} "
                f"wav={'ok' if render_ok else 'FAIL'} "
                f"pair={'ok' if (build_ok and render_ok) else 'FAIL'}"
            )
            variant_records.append({
                "variant": variant["variant"],
                "instrument_id": instrument_id,
                "mapping": variant["mapping"],
                "part_rule": variant["part_rule"],
                "xex_path": xex_path.relative_to(REPO_ROOT).as_posix(),
                "wav_path": wav_path.relative_to(REPO_ROOT).as_posix(),
                "build_status": "ok" if build_ok else "failed",
                "render_status": "ok" if render_ok else "failed",
                "pair_ok": bool(build_ok and render_ok),
                "xex": {**xex_check, "exit_code": xex_run["returncode"], "seconds": xex_run["seconds"]},
                "wav": {**wav_check, "exit_code": wav_run["returncode"], "seconds": wav_run["seconds"]},
                "errors": errors,
            })

        _flag_duration_drift(variant_records)
        _flag_xex_unchanged(variant_records)
        songs_out.append({
            "rel_path": song["rel_path"],
            "song_id": song["song_id"],
            "format": song["format"],
            "title": song["title"],
            "parts": [{"id": pid, "character": ch} for pid, ch in song["parts"]],
            "lead_part": song["lead_part"],
            "lead_part_rule": song["lead_part_rule"],
            "expected_variants": [v["variant"] for v in song["variants"]],
            "variants": variant_records,
        })
    elapsed = round(time.perf_counter() - started, 1)
    manifest = _manifest(songs_out, usable, unsupported, library, player_bytes,
                         player_within_limit, elapsed)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = output_dir / "report.md"
    report_path.write_text(render_report(manifest), encoding="utf-8")

    totals = manifest["totals"]
    _log("=" * 78)
    _log(f"songs={totals['songs']} expected_variants={totals['expected_variants']} "
         f"xex_ok={totals['xex_ok']} wav_ok={totals['wav_ok']} pairs_ok={totals['pairs_ok']} "
         f"failed={totals['failed_variants']}")
    _log(f"manifest -> {manifest_path}")
    _log(f"report   -> {report_path}")
    _log(f"elapsed  : {elapsed}s")
    return 0


# ---------------------------------------------------------------------------
# Manifest and report
# ---------------------------------------------------------------------------
def _totals(songs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    variants = [v for song in songs for v in song["variants"]]
    flags: Dict[str, int] = {}
    for variant in variants:
        for flag in variant["wav"].get("flags", []):
            flags[flag] = flags.get(flag, 0) + 1
    durations = [
        v["wav"]["duration_seconds"] for v in variants if "duration_seconds" in v["wav"]
    ]
    return {
        "songs": len(songs),
        "expected_variants": len(variants),
        "expected_artifacts": len(variants) * 2,
        "xex_ok": sum(1 for v in variants if v["build_status"] == "ok"),
        "wav_ok": sum(1 for v in variants if v["render_status"] == "ok"),
        "pairs_ok": sum(1 for v in variants if v["pair_ok"]),
        "failed_variants": sum(1 for v in variants if not v["pair_ok"]),
        "xex_files_on_disk": sum(1 for v in variants if (REPO_ROOT / v["xex_path"]).is_file()),
        "wav_files_on_disk": sum(1 for v in variants if (REPO_ROOT / v["wav_path"]).is_file()),
        "xex_total_bytes": sum(v["xex"].get("size_bytes", 0) for v in variants),
        "wav_total_bytes": sum(v["wav"].get("size_bytes", 0) for v in variants),
        "xex_over_2048_bytes": sum(1 for v in variants if v["xex"].get("exceeds_2048")),
        "xex_unchanged_by_override": sum(
            1 for v in variants if v.get("xex_unchanged_by_override")
        ),
        "wav_flags": flags,
        "wav_duration_seconds": {
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
        },
    }


def _manifest(
    songs: Sequence[Dict[str, Any]], usable: Sequence[Dict[str, Any]],
    unsupported: Sequence[Dict[str, Any]], library: Path, player_bytes: int,
    player_within_limit: bool, elapsed: float,
) -> Dict[str, Any]:
    return {
        "experiment": EXPERIMENT_NAME,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_dir": EXAMPLES_DIR.relative_to(REPO_ROOT).as_posix(),
        "instrument_library": {
            "path": library.relative_to(REPO_ROOT).as_posix()
            if library.is_relative_to(REPO_ROOT) else str(library),
            "usable_instruments": list(usable),
            "unsupported_instruments": list(unsupported),
            "role_to_composition_characters": {k: list(v) for k, v in ROLE_CHARACTERS.items()},
        },
        "player": {
            "assembled_bytes": player_bytes,
            "limit_bytes": stage15.PLAYER_SIZE_LIMIT_BYTES,
            "limit_is_exclusive": True,
            "within_limit": player_within_limit,
            "measured_by": "stage15.measure_player_size",
        },
        "pipeline": {
            "xex_command": (
                "python -m atari_music build-xex <src> -o <xex> --format <json|dsl> "
                "--mads tools/mads/mads.exe --instrument-library <lib> [--instrument PART=ID]"
            ),
            "wav_command": (
                "python -m atari_music import-json|import-dsl <src> --output-wav <wav> "
                "--instrument-library <lib> [--instrument PART=ID]"
            ),
            "consistency": (
                "both commands run cli._apply_selections on the same compiled IR, so one "
                "variant's WAV and XEX share one hardware realization"
            ),
        },
        "totals": _totals(songs),
        "elapsed_seconds": elapsed,
        "songs": list(songs),
    }


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(out)


def render_report(manifest: Dict[str, Any]) -> str:
    totals = manifest["totals"]
    library = manifest["instrument_library"]
    player = manifest["player"]
    songs = manifest["songs"]
    variants = [v for s in songs for v in s["variants"]]

    out: List[str] = []
    out.append("# Example songs: XEX + WAV for every instrument\n")
    out.append(f"Generated: `{manifest['generated_at_utc']}` · elapsed "
               f"`{manifest['elapsed_seconds']}s`\n")
    out.append("Every input composition under `examples/` was built as a `.xex` and rendered as "
               "a `.wav`, once with the default configuration (`plain`) and once per Lead Library "
               "instrument. Both artifacts of a variant come from the same compiled POKEY IR, "
               "because both CLI commands run the same `cli._apply_selections` step.\n")

    out.append("## Summary\n")
    out.append(_md_table(["measure", "value"], [
        ["source compositions discovered", totals["songs"]],
        ["instruments usable by the CLI", len(library["usable_instruments"])],
        ["instruments not usable", len(library["unsupported_instruments"])],
        ["expected variants", totals["expected_variants"]],
        ["expected artifacts (xex + wav)", totals["expected_artifacts"]],
        ["successful XEX builds", totals["xex_ok"]],
        ["successful WAV renders", totals["wav_ok"]],
        ["fully successful pairs", totals["pairs_ok"]],
        ["failed variants", totals["failed_variants"]],
        ["XEX files on disk", totals["xex_files_on_disk"]],
        ["WAV files on disk", totals["wav_files_on_disk"]],
        ["XEX files over 2048 bytes (not a failure)", totals["xex_over_2048_bytes"]],
        ["instrument variants whose XEX equals plain", totals["xex_unchanged_by_override"]],
        ["WAV total size", f"{totals['wav_total_bytes'] / 1e6:.1f} MB"],
        ["WAV duration range", f"{totals['wav_duration_seconds']['min']}–"
                               f"{totals['wav_duration_seconds']['max']} s"],
    ]))
    out.append("")

    out.append("## Instruments\n")
    out.append(_md_table(
        ["instrument id", "kind", "role", "realized as"],
        [[i["instrument_id"], i["kind"], i["role"],
          i.get("profile_id") or (f"generator {i.get('generator_byte')}"
                                  if i.get("generator_byte") else "")]
         for i in library["usable_instruments"]],
    ))
    out.append("")
    if library["unsupported_instruments"]:
        out.append("Not usable by the current mechanism:\n")
        out.append(_md_table(
            ["instrument id", "kind", "reason"],
            [[i["instrument_id"], i["kind"], i["reason"]]
             for i in library["unsupported_instruments"]],
        ))
        out.append("")
    else:
        out.append("Every instrument in the library is usable by the current mechanism.\n")

    out.append("## Part mapping\n")
    out.append("The Lead Library declares `role: \"lead\"`. The part an instrument is applied to "
               "is chosen per composition by: (1) the part whose `character` is `bright_lead` or "
               "`dark_lead`, else (2) the part whose id is exactly `lead`, else (3) the "
               "composition's first instrument. Which rule matched is recorded below.\n")
    rules: Dict[str, int] = {}
    for song in songs:
        rules[song["lead_part_rule"]] = rules.get(song["lead_part_rule"], 0) + 1
    out.append(_md_table(["rule", "compositions"], [[k, v] for k, v in sorted(rules.items())]))
    out.append("")
    out.append(_md_table(
        ["song id", "source", "format", "lead part", "rule"],
        [[s["song_id"], f"`{s['rel_path']}`", s["format"], s["lead_part"], s["lead_part_rule"]]
         for s in songs],
    ))
    out.append("")

    out.append("## Player size\n")
    out.append(_md_table(["measure", "value"], [
        ["assembled player", f"{player['assembled_bytes']} bytes"],
        ["limit (exclusive)", f"< {player['limit_bytes']} bytes"],
        ["within limit", player["within_limit"]],
        ["measured by", f"`{player['measured_by']}`"],
    ]))
    out.append("")

    failures = [v for v in variants if not v["pair_ok"]]
    out.append("## Variants whose XEX is byte-identical to `plain`\n")
    unchanged = [v for v in variants if v.get("xex_unchanged_by_override")]
    if not unchanged:
        out.append("None: every instrument override changed the exported binary.\n")
    else:
        by_song: Dict[str, List[str]] = {}
        for variant in unchanged:
            song_id = variant["xex_path"].split("/")[-2]
            by_song.setdefault(song_id, []).append(variant["variant"])
        out.append(
            f"{len(unchanged)} variant(s) in {len(by_song)} song(s) produced a XEX byte-identical "
            "to that song's `plain` XEX, while their WAVs differ.\n"
        )
        out.append(
            "This is a property of the exported format, not a failed build: the XEX carries "
            "**one instrument record per POKEY channel**, chosen by the exporter from the notes "
            "that actually sound on that channel (and, for a 16-bit bass song, channel 2 always "
            "carries channel 1's bass). When a composition's lead part does not own a channel in "
            "that mapping, an override applied to the lead has no record to land on, so the "
            "binary is unchanged even though the software renderer, which reads the per-note IR "
            "instruments, is not.\n"
        )
        out.append(_md_table(["song id", "variants identical to plain"],
                             [[sid, ", ".join(names)] for sid, names in sorted(by_song.items())]))
        out.append("")

    out.append("## Failures\n")
    if not failures:
        out.append("None. Every expected variant produced a valid XEX and a valid WAV.\n")
    else:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for variant in failures:
            reason = variant["errors"][0] if variant["errors"] else "unknown"
            key = reason.split("\n")[0][:160]
            grouped.setdefault(key, []).append(variant)
        out.append(f"{len(failures)} variant(s) failed, grouped by reason:\n")
        for reason, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            out.append(f"- **{len(items)}×** `{reason}`")
            for item in items[:8]:
                out.append(f"  - `{item['variant']}`")
            if len(items) > 8:
                out.append(f"  - … and {len(items) - 8} more")
        out.append("")

    flagged = [v for v in variants if v["wav"].get("flags")]
    out.append("## WAV flags\n")
    if not flagged:
        out.append("None: every WAV opened, was non-empty, and matched its song's `plain` "
                   f"duration within {WAV_DURATION_TOLERANCE_S}s.\n")
    else:
        out.append(_md_table(["variant", "flags"],
                             [[v["variant"], ", ".join(v["wav"]["flags"])]
                              for v in flagged[:40]]))
        out.append("")

    out.append("## Caveats\n")
    out.append("- The two artifacts are *not* proven byte-identical to each other: the WAV is the "
               "software synthesizer's rendering of the same POKEY register stream the XEX player "
               "reproduces on hardware. They share one IR, not one byte stream.\n")
    out.append("- WAV files are compared by duration only. No byte-for-byte comparison is used, "
               "and none would be meaningful.\n")
    out.append("- `plain` uses the composition's own instruments with no override; it is never "
               "labelled as an instrument variant.\n")
    if library["unsupported_instruments"]:
        out.append("- Instruments listed as not usable are refused by the existing mechanism; "
                   "they were not substituted or approximated.\n")
    out.append("- `build/` is not tracked by git, so the artifacts are reproducible from the "
               "script but not committed.\n")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help=f"experiment directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--library", default=str(DEFAULT_LIBRARY),
                        help=f"Lead Library directory (default: {DEFAULT_LIBRARY})")
    parser.add_argument("--only", default=None,
                        help="only compositions whose relative path contains this substring")
    parser.add_argument("--limit", type=int, default=None, help="stop after N compositions")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the matrix and generate nothing")
    parser.add_argument("--no-clean", action="store_true",
                        help="keep existing files in the experiment directory")
    return run_experiment(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

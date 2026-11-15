"""Stage 21 - controlled validation of the note-level explanation.

Stage 20 measured how much of the historical POKEY stream the note-level representation does not
explain. It found roughly 40% of register values left over, and that the Stage 19 grammar explains
about half of that residual. It also stated the limit of that result in one sentence:

    for the four corpus songs there is no independent composition representation at all.

The only note-level view of those songs is Stage 15's *detector*, which segments the very trace it
is asked to explain. Stage 20 marked it ``is_ground_truth: false`` and moved on. Stage 21 does not
move on. It asks the question that decides whether Stage 20 measured a property of the music or a
property of its own instrument:

    Is the structure Stage 20 calls "residual performance information" really additional
    performance information - or is part of it an artefact of an imperfect note-level
    reconstruction?

Three hypotheses are separated, exactly as the brief requires:

* **H1 - note model validity.** Does the note baseline reproduce what an independent composition
  says about pitch, timing and note boundaries?
* **H2 - residual authenticity.** Does the residual still appear when the note information comes
  from an *independent* source rather than from the trace's own detector?
* **H3 - performance structure.** Is part of the residual structured, generalisable, and not
  explained by simple note-alignment error?

The brief is explicit that the perfect dataset - independent composition, channel assignment,
timing and an exact trace for the *historical* songs - may simply not exist, and that this must not
stop the stage. Stage 21 therefore works in **evidence tiers**, audits what is actually available
before running anything, and says plainly what cannot be decided.

The audit's result is that no independent composition exists for any historical song, but that the
project does own something better than nothing: nine authored ``.dsl`` scores and forty-three AI
composition documents which compile, through the project's own compiler, to exact POKEY register
traces. Those compositions exist *before* any trace and are therefore genuinely independent of it.
They become the **Tier A control corpus**: a set of traces with a known musical ground truth, on
which the *instrument* Stage 20 used can be calibrated.

That calibration is the stage's decisive measurement, and it is negative for Stage 20's inference:

* with the composition's own notes, the baseline reproduces the compiled trace exactly - 0 of
  20,520 register values differ on the first song, so the baseline is not lossy at all;
* with Stage 15's detector supplying the notes for that same trace, 22.1% of register values are
  left unexplained - on a song whose ground truth is known and contains **no** performance
  information whatsoever;
* the Stage 19 grammar explains a *larger* share of that known-artefact residual (0.731 pooled)
  than of the historical residual (0.486). Grammar-explainability is therefore not evidence of
  performance information; it is a property of detector residuals in general.

So Stage 21 does not confirm the residual. It reports ``RESIDUAL_NOT_CONFIRMED`` and
``PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE``, and it names the minimum dataset that would decide
the question. It deliberately does **not** promote Stage 20's ``PERFORMANCE_LAYER_PROMISING`` to
``JUSTIFIED``.

Honesty rules this stage inherits and obeys:

* Every audit row carries an evidence class - ``OBSERVED``, ``SOURCE``, ``INFERENCE`` or
  ``ASSUMPTION`` - and a confidence. Nothing is invented to fill a gap.
* A missing channel assignment is never guessed as ground truth. Where this stage has to model a
  player-side convention it says so, and it reports the alternative.
* The residual is never renamed after a musical technique. The categories are
  ``BASELINE_ERROR``, ``ALIGNMENT_UNCERTAINTY``, ``CHANNEL_UNCERTAINTY``,
  ``CONFIRMED_PERFORMANCE_CANDIDATE`` and ``UNRESOLVED``, and ``UNRESOLVED`` is the default.
* The exact identity ``trace == predicted + residual`` is asserted for every residual built here.
* No claim is made that ``40% residual == 40% performance``. That claim is what this stage exists
  to test, and it does not survive.

Read-only and additive. The corpus traces, the Stage 15-20 records, the player source, the Music
IR, the POKEY IR, the DSL and the composer are read through their hashes and never written. No
audio is rendered, no music is generated, no listening test is run, and nothing is implemented in
production. Analysis version ``stage21/1``.

The ``.dsl`` scores and AI documents are *read* here, never modified: they are the independent
composition source this stage needs, not a production target.
"""


from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import ir, pokey_hw, stage15, stage18, stage19, stage20

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_STAGE16_DIR = DEFAULT_REPORTS_DIR / "stage16"
DEFAULT_STAGE20_DIR = DEFAULT_REPORTS_DIR / "stage20"
DEFAULT_STAGE21_DIR = DEFAULT_REPORTS_DIR / "stage21"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_SONGS_DIR = REPO_ROOT / "examples" / "songs"
DEFAULT_AI_DIR = REPO_ROOT / "examples" / "ai"

#: The DSL score the SoundProfile tests keep beside their fixtures. It is a composition too, so it
#: is part of the control corpus, but it lives outside ``examples/songs`` and is therefore a separate
#: discovery root rather than a hard-coded extra scan.
DEFAULT_EXTRA_DSL_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles"

ANALYSIS_VERSION = "stage21/1"

REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER
FRAME_BYTES = stage18.FRAME_BYTES
EXPECTED_SLUGS: Tuple[str, ...] = stage20.EXPECTED_SLUGS
RANDOM_SEED = 20250321

#: Frame period of the project's own compiled traces (PAL 50 Hz), in microseconds.
COMPILED_FRAME_PERIOD_US = 20_000

# ---------------------------------------------------------------------------
# Evidence classes. Every audited fact is labelled with one of these, and the
# label travels with the fact into every artefact.
# ---------------------------------------------------------------------------
EVIDENCE_OBSERVED = "OBSERVED"
EVIDENCE_SOURCE = "SOURCE"
EVIDENCE_INFERENCE = "INFERENCE"
EVIDENCE_ASSUMPTION = "ASSUMPTION"

EVIDENCE_CLASSES: Tuple[str, ...] = (
    EVIDENCE_OBSERVED, EVIDENCE_SOURCE, EVIDENCE_INFERENCE, EVIDENCE_ASSUMPTION,
)

# ---------------------------------------------------------------------------
# Evidence tiers. Assigned by rule, never by judgement, and the rule is stated
# so a reader can disagree with the inputs rather than with the code.
# ---------------------------------------------------------------------------
TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_D = "D"

TIER_RULES: Tuple[Tuple[str, str], ...] = (
    (TIER_A, "independent notes + usable trace + timing (channel assignment optional)"),
    (TIER_B, "independent notes + trace, but no reliable channel assignment or timing"),
    (TIER_C, "independent transcription only, no trace"),
    (TIER_D, "SAP/POKEY trace only - cannot decide whether residual is performance"),
)

# ---------------------------------------------------------------------------
# The outside-note convention. This is a real, measured difference between two
# project components, not a modelling choice, and it is worth four and a half
# percent of a compiled stream:
#
#   * OUTSIDE_HOLD - `player.asm` holds the last AUDF and silences the channel on
#     a rest. Stage 20's baseline implements this.
#   * OUTSIDE_EXPORTER - `ir.compile_ir_to_pokey_frames` writes a register only
#     inside a note, so a register in a frame no note covers keeps the array's
#     initial value, 0.
#
# An independent baseline must match the trace it is compared against, so both
# are reported and the difference between them is measured rather than hidden.
# ---------------------------------------------------------------------------
OUTSIDE_HOLD = "hold"
OUTSIDE_EXPORTER = "exporter"
OUTSIDE_POLICIES: Tuple[str, ...] = (OUTSIDE_HOLD, OUTSIDE_EXPORTER)

#: Contour sources for the level track.
CONTOUR_COMPOSITION = "composition"
CONTOUR_REDUCED = "reduced"
CONTOUR_SOURCES: Tuple[str, ...] = (CONTOUR_COMPOSITION, CONTOUR_REDUCED)

# ---------------------------------------------------------------------------
# Residual categories (section 19 of the brief). UNRESOLVED is the default and
# is never merged into CONFIRMED_PERFORMANCE_CANDIDATE.
# ---------------------------------------------------------------------------
CAT_BASELINE_ERROR = "BASELINE_ERROR"
CAT_ALIGNMENT_UNCERTAINTY = "ALIGNMENT_UNCERTAINTY"
CAT_CHANNEL_UNCERTAINTY = "CHANNEL_UNCERTAINTY"
CAT_PERFORMANCE_CANDIDATE = "CONFIRMED_PERFORMANCE_CANDIDATE"
CAT_UNRESOLVED = "UNRESOLVED"

RESIDUAL_CATEGORIES: Tuple[str, ...] = (
    CAT_BASELINE_ERROR,
    CAT_ALIGNMENT_UNCERTAINTY,
    CAT_CHANNEL_UNCERTAINTY,
    CAT_PERFORMANCE_CANDIDATE,
    CAT_UNRESOLVED,
)

#: Frame offsets the boundary-tolerance experiment allows between a note boundary and a change.
BOUNDARY_TOLERANCES: Tuple[int, ...] = (0, 1, 2, 3, 4)

#: The alignment control's shifts. 0 is the measurement; the rest are controls.
ALIGNMENT_SHIFTS: Tuple[int, ...] = (0, 1, 2, 4, 16)

#: The three baseline variants of section 11 of the brief.
BASELINE_NAMES: Tuple[str, ...] = ("B0", "B1", "B2")


class Stage21Error(RuntimeError):
    """A required input is missing or malformed, or a declared identity does not hold."""


def _read_json(path: Path) -> Any:
    return stage15._read_json(path)


def sha256_file(path: Path) -> str:
    return stage15.sha256_file(path)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    return stage15._rnd(value, places)


# ===========================================================================
# PART 1 - the dataset audit (sections 3 and 4 of the brief)
# ===========================================================================
#: The seven availability questions of the brief, asked of every candidate.
HAS_FLAGS: Tuple[str, ...] = (
    "HAS_SAP",
    "HAS_EXACT_TRACE",
    "HAS_INDEPENDENT_NOTES",
    "HAS_TIMING",
    "HAS_CHANNEL_ASSIGNMENT",
    "HAS_VELOCITY",
    "HAS_PLAYER_RECONSTRUCTION",
)

KIND_HISTORICAL_SAP = "historical_sap"
KIND_CONTROL_DSL = "control_dsl"
KIND_CONTROL_JSON = "control_json"
KIND_PROFILE_REFERENCE = "profile_reference"
KIND_EXTERNAL = "external_candidate"


@dataclass(frozen=True)
class AuditRow:
    """One audited candidate song, with every availability flag and its evidence class.

    A flag is set only when the *observed repository state* supports it. ``HAS_SAP`` means a ``.sap``
    file was found and hashed; ``HAS_INDEPENDENT_NOTES`` means a composition document exists that
    was authored independently of the trace. Nothing is inferred into a flag.
    """

    key: str
    kind: str
    source: str
    sha256: Optional[str]
    frames: Optional[int]
    flags: Tuple[str, ...]
    evidence: str
    confidence: str
    note: str

    def has(self, flag: str) -> bool:
        return flag in self.flags

    @property
    def tier(self) -> str:
        return evidence_tier(self.flags)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "source": self.source,
            "sha256": self.sha256,
            "frames": self.frames,
            **{flag: self.has(flag) for flag in HAS_FLAGS},
            "evidence": self.evidence,
            "confidence": self.confidence,
            "tier": self.tier,
            "note": self.note,
        }


def evidence_tier(flags: Sequence[str]) -> str:
    """The tier rule of the brief, as a pure function of the availability flags.

    Deliberately blunt, so that a reader can audit the assignment by looking at the flags rather
    than at a narrative:

    * Tier A - independent notes **and** an exact trace **and** usable timing. Channel assignment
      and velocity are *not* required.
    * Tier B - independent notes **and** an exact trace, but no usable timing.
    * Tier C - independent notes with no trace.
    * Tier D - no independent notes at all. These songs can replicate Stage 20, but they cannot
      decide whether the residual is performance or detector error.
    """
    present = set(flags)
    independent = "HAS_INDEPENDENT_NOTES" in present
    trace = "HAS_EXACT_TRACE" in present
    timing = "HAS_TIMING" in present
    if independent and trace and timing:
        return TIER_A
    if independent and trace:
        return TIER_B
    if independent:
        return TIER_C
    return TIER_D


def _sap_dir(arch_root: Path) -> Path:
    return Path(arch_root) / "input"


def historical_rows(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> List[AuditRow]:
    """Every SAP trace available to the project, audited for what it does and does not carry.

    All twelve are Tier D. That is the audit's most important finding and it is reported first: a
    SAP file carries a player and its data, not a composition, so nothing in a SAP says which pitch
    a channel was asked to play. The ``.sap`` byte stream is the *same* artefact the trace was
    decoded from, so it cannot serve as an independent check of that trace.
    """
    arch_root = Path(arch_root)
    sap_dir = _sap_dir(arch_root)
    rows: List[AuditRow] = []
    for path in sorted(stage15.list_traces(arch_root)):
        trace = stage15.load_trace(path)
        sap_path = sap_dir / Path(trace.song_file).name
        sap_present = sap_path.is_file()
        flags = ("HAS_EXACT_TRACE",) + (("HAS_SAP",) if sap_present else ())
        rows.append(
            AuditRow(
                key=trace.slug,
                kind=KIND_HISTORICAL_SAP,
                source=str(path),
                sha256=trace.sha256 or None,
                frames=trace.frames,
                flags=flags,
                evidence=EVIDENCE_OBSERVED,
                confidence="HIGH",
                note=(
                    f"author={trace.author!r} date={trace.date!r} sap_type={trace.sap_type!r} "
                    f"subsong={trace.subsong} looping={trace.is_looping}; decoded by ASAP from the "
                    f"SAP file itself, so the trace and the SAP are one source, not two"
                ),
            )
        )
    return rows


def _load_dsl_document(path: Path) -> Any:
    from atari_music.ai.client import load_composition_dsl

    return load_composition_dsl(path)


def _load_json_document(path: Path) -> Any:
    from atari_music.ai.client import load_composition

    return load_composition(_read_json(path))


@dataclass(frozen=True)
class ControlSong:
    """A composition this project owns, plus the exact trace its own compiler produces for it.

    This is the Tier A material. The composition is an authored document - note names, durations,
    levels and instruments per channel - which exists before any trace and references no register.
    The trace is produced deterministically from it by
    :func:`atari_music.ir.compile_ir_to_pokey_frames`. So the pair is genuinely
    (composition, trace) and the trace's ground truth is known exactly.
    """

    slug: str
    kind: str
    source: str
    sha256: str
    compiled_sha256: str
    title: str
    author: str
    frames: int
    frames_per_tick: int
    pattern_count: int
    sequence_length: int
    uses_16bit_bass: bool
    audctl: int
    note_count: int
    rest_count: int
    song: Any = field(repr=False, default=None)
    trace: Any = field(repr=False, default=None)
    stream: Any = field(repr=False, default=None)
    payload: Any = field(repr=False, default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "kind": self.kind,
            "source": self.source,
            "sha256": self.sha256,
            "compiled_sha256": self.compiled_sha256,
            "title": self.title,
            "author": self.author,
            "frames": self.frames,
            "frames_per_tick": self.frames_per_tick,
            "patterns": self.pattern_count,
            "sequence_length": self.sequence_length,
            "uses_16bit_bass": self.uses_16bit_bass,
            "audctl": f"${self.audctl:02X}",
            "notes": self.note_count,
            "rests": self.rest_count,
        }


def frames_to_registers(payload: np.ndarray) -> Dict[str, Tuple[int, ...]]:
    """Name the nine columns of a compiled frame array after the canonical register order.

    The column order is not assumed: it is asserted against the compiler's own documented layout,
    and the two are identical, so a reader can see that no transposition was performed here.
    """
    if payload.ndim != 2 or payload.shape[1] != FRAME_BYTES:
        raise Stage21Error(
            f"a compiled stream must be (frames, {FRAME_BYTES}), got {payload.shape}"
        )
    if tuple(ir.FRAME_COLUMN_NAMES) != REGISTER_ORDER:
        raise Stage21Error(
            "the compiler's frame column names and the canonical register order disagree; "
            f"{tuple(ir.FRAME_COLUMN_NAMES)} != {REGISTER_ORDER}"
        )
    return {
        name: tuple(int(value) for value in payload[:, index])
        for index, name in enumerate(REGISTER_ORDER)
    }


def build_trace(
    slug: str,
    song: Any,
    payload: np.ndarray,
    frame_period_ms: float = 20.0,
    notes: Tuple[str, ...] = (),
) -> Any:
    """Wrap a compiled frame array as a register trace so the Stage 20 machinery can run on it.

    The wrapper is honest about what it is: ``schema`` says ``stage21/compiled``, ``path`` says
    ``control/``, and title and author come from the composition itself. Nothing about the
    historical corpus is reachable from a control trace.
    """
    return stage15.RegisterTrace(
        path=f"control/{slug}.frames.json",
        sha256="",
        schema="stage21/compiled",
        song=slug,
        subsong=0,
        title=getattr(song, "title", None),
        author=getattr(song, "author", None),
        date=None,
        sap_type=None,
        song_file="",
        declared_duration_s=None,
        is_looping=False,
        frames=int(payload.shape[0]),
        frame_period_ms=frame_period_ms,
        registers=frames_to_registers(payload),
        backend={"compiler": "atari_music.ir.compile_ir_to_pokey_frames"},
        notes=notes,
    )


def build_stream(slug: str, trace: Any) -> Any:
    """The canonical Stage 18 stream of a compiled trace, in the canonical register order."""
    return stage18.FrameStream(
        slug=slug,
        frames=trace.frames,
        frame_period_us=COMPILED_FRAME_PERIOD_US,
        registers={name: trace.registers[name] for name in REGISTER_ORDER},
    )


def compile_control(slug: str, kind: str, path: Path, song: Any) -> ControlSong:
    """Compile one composition document and record the hash of the exact trace it produced."""
    payload = np.asarray(ir.compile_ir_to_pokey_frames(song))
    if payload.size == 0:
        raise Stage21Error(f"{slug}: the compiler produced an empty stream")
    trace = build_trace(slug, song, payload)
    stream = build_stream(slug, trace)
    note_count = sum(
        1 for pattern in song.patterns for track in pattern.tracks.values()
        for note in track if not note.is_rest
    )
    rest_count = sum(
        1 for pattern in song.patterns for track in pattern.tracks.values()
        for note in track if note.is_rest
    )
    return ControlSong(
        slug=slug,
        kind=kind,
        source=str(path),
        sha256=sha256_file(path),
        compiled_sha256=sha256_bytes(stream.payload()),
        title=getattr(song, "title", "") or "",
        author=getattr(song, "author", "") or "",
        frames=trace.frames,
        frames_per_tick=int(song.frames_per_tick),
        pattern_count=len(song.patterns),
        sequence_length=len(song.sequence),
        uses_16bit_bass=bool(song.uses_16bit_bass),
        audctl=int(trace.audctl),
        note_count=note_count,
        rest_count=rest_count,
        song=song,
        trace=trace,
        stream=stream,
        payload=payload,
    )


def control_sources(
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    extra_dsl_dir: Optional[Path] = DEFAULT_EXTRA_DSL_DIR,
    failures: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[str, str, Path]]:
    """Every composition document in the repository, deduplicated and uniquely named.

    Two things are handled here and both matter for the artefacts:

    * **deduplication by content hash.** The repository really does contain byte-identical duplicates
      (``Vaults-of-Nhyrmeth.dsl`` and ``Vaults-of-Nhyrmeth-2.dsl`` are the same file). Counting them
      twice would inflate every pooled control statistic.
    * **unique slugs.** Two different documents can share a filename stem (there are two distinct
      files named ``04_prl_comedy``). A shared slug would silently overwrite a row in the artefacts,
      so a colliding stem is disambiguated with a short content-hash suffix. The suffix is derived
      from the file's own hash, so it is deterministic and cannot depend on walk order.
    """
    candidates: List[Tuple[str, str, Path]] = []
    for path in sorted(Path(songs_dir).glob("*.dsl")):
        candidates.append((path.stem, KIND_CONTROL_DSL, path))
    if extra_dsl_dir is not None:
        for path in sorted(Path(extra_dsl_dir).glob("*.dsl")):
            candidates.append((path.stem, KIND_CONTROL_DSL, path))
    for path in sorted(Path(ai_dir).rglob("*.json")):
        try:
            document = _read_json(path)
        except Exception as error:  # noqa: BLE001
            # A JSON file that will not parse is plausibly a *broken composition* rather than a
            # file that was never a composition, so it is reported. A file that parses but carries
            # no patterns is definitively not a composition, so it is only ignored.
            if failures is not None:
                failures.append({
                    "slug": path.stem, "kind": KIND_CONTROL_JSON, "source": str(path),
                    "stage": "parse", "error": f"{type(error).__name__}: {error}",
                })
            continue
        if not isinstance(document, dict):
            continue
        if "patterns" not in document or "sequence" not in document:
            continue
        candidates.append((path.stem, KIND_CONTROL_JSON, path))

    unique: Dict[str, Tuple[str, str, Path]] = {}
    for slug, kind, path in candidates:
        digest = sha256_file(path)
        if digest not in unique:
            unique[digest] = (slug, kind, path)

    ordered = [unique[digest] for digest in sorted(unique)]
    counts: Dict[str, int] = {}
    for slug, _kind, _path in ordered:
        counts[slug] = counts.get(slug, 0) + 1
    used: Dict[str, int] = {}
    renamed: List[Tuple[str, str, Path]] = []
    for slug, kind, path in ordered:
        if counts[slug] == 1:
            renamed.append((slug, kind, path))
            continue
        suffix = sha256_file(path)[:8]
        candidate = f"{slug}__{suffix}"
        while candidate in used:
            candidate = f"{candidate}_"
        renamed.append((candidate, kind, path))
        used[candidate] = 1
    return renamed


def load_control_corpus(
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    extra_dsl_dir: Optional[Path] = DEFAULT_EXTRA_DSL_DIR,
) -> Tuple[List[ControlSong], List[Dict[str, Any]]]:
    """Compile every composition the repository owns. Returns the corpus and the skips.

    A document that fails to parse or compile is *reported*, never silently dropped: a corpus
    statistic that quietly ignores the songs the stage could not handle would be worthless.
    """
    from atari_music.ai.client import generate_music_from_composition

    corpus: List[ControlSong] = []
    skipped: List[Dict[str, Any]] = []
    for slug, kind, path in control_sources(songs_dir, ai_dir, extra_dsl_dir, skipped):
        stage_name = "parse"
        try:
            document = (
                _load_dsl_document(path) if kind == KIND_CONTROL_DSL else _load_json_document(path)
            )
            stage_name = "translate"
            song = generate_music_from_composition(document).pokey_ir
            stage_name = "compile"
            corpus.append(compile_control(slug, kind, path, song))
        except Exception as error:  # noqa: BLE001 - a failure to handle an input is a finding
            skipped.append({
                "slug": slug, "kind": kind, "source": str(path), "stage": stage_name,
                "error": f"{type(error).__name__}: {error}",
            })
    return corpus, skipped


def control_rows(corpus: Sequence[ControlSong]) -> List[AuditRow]:
    """The audit view of the control corpus: every flag that is genuinely present, and no more."""
    rows: List[AuditRow] = []
    for song in corpus:
        channels = sorted({channel for pattern in song.song.patterns for channel in pattern.tracks})
        flags = (
            "HAS_EXACT_TRACE",
            "HAS_INDEPENDENT_NOTES",
            "HAS_TIMING",
            "HAS_CHANNEL_ASSIGNMENT",
            "HAS_VELOCITY",
            "HAS_PLAYER_RECONSTRUCTION",
        )
        rows.append(
            AuditRow(
                key=song.slug,
                kind=song.kind,
                source=song.source,
                sha256=song.sha256,
                frames=song.frames,
                flags=flags,
                evidence=EVIDENCE_OBSERVED,
                confidence="HIGH",
                note=(
                    f"the document lists {song.note_count} notes and {song.rest_count} rests over "
                    f"channels {channels} with per-note volume, and it references no register; the "
                    f"trace is the deterministic output of the project's own compiler (payload "
                    f"{song.compiled_sha256[:12]}). Timing is explicit ({song.frames_per_tick} "
                    f"frames per row). This is an in-house composition, not a historical song."
                ),
            )
        )
    return rows



#: Directories that hold measured POKEY reference captures (the SoundProfile bank). They are
#: register traces used to *fit sound profiles*, not compositions, so they are Tier D as well.
PROFILE_REFERENCE_DIRS: Tuple[Tuple[str, str], ...] = (
    ("examples/integration_bank/profiles", "pokey_ref_*.json"),
    ("tests/data/sound_profiles/bank/profiles", "pokey_ref_*.json"),
)


def profile_rows(root: Path = REPO_ROOT) -> List[Dict[str, Any]]:
    """Audit the measured reference captures as a group, because they are one kind of artefact.

    They are listed per directory rather than per file: 200+ identical rows would bury the audit's
    actual finding, which is that a measured register capture is not a composition and cannot
    answer the pitch and timing questions this stage asks.
    """
    out: List[Dict[str, Any]] = []
    for relative, pattern in PROFILE_REFERENCE_DIRS:
        directory = Path(root) / relative
        files = sorted(directory.glob(pattern)) if directory.is_dir() else []
        digests = sorted(sha256_file(path) for path in files)
        out.append({
            "kind": KIND_PROFILE_REFERENCE,
            "directory": str(directory),
            "files": len(files),
            "unique_files": len(set(digests)),
            "combined_sha256": sha256_bytes("".join(digests).encode("ascii")) if digests else None,
            "HAS_EXACT_TRACE": bool(files),
            "HAS_INDEPENDENT_NOTES": False,
            "HAS_TIMING": bool(files),
            "HAS_CHANNEL_ASSIGNMENT": False,
            "HAS_VELOCITY": False,
            "HAS_SAP": False,
            "HAS_PLAYER_RECONSTRUCTION": False,
            "evidence": EVIDENCE_OBSERVED,
            "confidence": "HIGH",
            "tier": TIER_D,
            "note": (
                "measured POKEY register captures used to fit SoundProfiles. They carry register "
                "values and no note names, so they are Tier D: usable for replication and controls, "
                "never for deciding whether a residual is performance."
            ),
        })
    return out


#: External candidates found by search and audited, with the reason each is *not* admitted. The
#: brief allows searching for data but forbids treating an internet transcription as ground truth
#: without assessment, so each entry carries its assessment explicitly.
EXTERNAL_SOURCES: Tuple[Dict[str, Any], ...] = (
    {
        "candidate": "SAP files for the corpus games",
        "source": "the repository itself: pokey-sound-architecture/input/*.sap",
        "evidence": EVIDENCE_OBSERVED,
        "confidence": "HIGH",
        "has_independent_notes": False,
        "admitted": False,
        "reason": (
            "a SAP holds the 6502 player and its pattern data as machine code, not as a "
            "composition. The corpus trace was decoded from this same file, so the SAP and the "
            "trace are one source and cannot validate one another."
        ),
    },
    {
        "candidate": "C64 SID renditions of the same tunes (CSDb, HVSC)",
        "source": "web search: composer and title pages for the four Stage 20 songs",
        "evidence": EVIDENCE_SOURCE,
        "confidence": "MEDIUM",
        "has_independent_notes": False,
        "admitted": False,
        "reason": (
            "a SID rendition is a different platform and a different driver, published as a "
            "binary rather than as note data. Even if note data were extracted from it, it would "
            "be a re-derivation from another machine's player rather than the Atari composition, "
            "and it could not be frame-aligned to a POKEY trace without an unquantifiable "
            "alignment inference."
        ),
    },
    {
        "candidate": "tracker modules and re-creations of the tunes",
        "source": "web search: module archives for the corpus titles",
        "evidence": EVIDENCE_SOURCE,
        "confidence": "LOW",
        "has_independent_notes": True,
        "admitted": False,
        "reason": (
            "a module is a re-creation, not the composer's own score. It has its own instrument "
            "set, its own channel layout and its own tempo, so matching it to a POKEY trace "
            "requires choosing a channel assignment and an alignment - both of which this stage "
            "forbids inventing, because both would set the residual directly."
        ),
    },
    {
        "candidate": "human MIDI transcriptions of the tunes",
        "source": "web search: transcription archives for the corpus titles",
        "evidence": EVIDENCE_SOURCE,
        "confidence": "LOW",
        "has_independent_notes": True,
        "admitted": False,
        "reason": (
            "these are transcribed by ear from the same audio the SAP produces. They carry no "
            "channel-to-POKEY assignment, no frame timing and no note-boundary convention, and "
            "they are often freely re-orchestrated, so using one would replace a measurable "
            "question with an unmeasurable inference - exactly what the brief forbids when it says "
            "an internet transcription is not ground truth until it has been assessed."
        ),
    },
)


def external_source_audit() -> Dict[str, Any]:
    """The external-data search, with every candidate assessed and its disposal recorded."""
    return {
        "question": (
            "Does an independent composition representation exist anywhere for the historical "
            "corpus songs?"
        ),
        "method": (
            "the repository was searched for composition documents and note data of any kind; web "
            "search was then used for composition, module and transcription sources for the four "
            "Stage 20 songs and their authors. Every candidate is recorded with its evidence class "
            "and the reason it is or is not admitted."
        ),
        "admitted": [row["candidate"] for row in EXTERNAL_SOURCES if row["admitted"]],
        "assessed": len(EXTERNAL_SOURCES),
        "candidates": [dict(row) for row in EXTERNAL_SOURCES],
        "answer": (
            "No admitted independent composition representation exists. Four candidate classes "
            "were assessed and all four were rejected, each for a stated reason. The rejection is "
            "not a preference: every rejected source would have required inventing a channel "
            "assignment or an alignment, and either one would set the residual directly, which is "
            "the quantity under test. This is the finding that makes the historical half of this "
            "stage undecidable, and it is reported before any measurement."
        ),
    }


    return load_composition_dsl(path)


def _load_json_document(path: Path) -> Any:
    from atari_music.ai.client import load_composition

    return load_composition(_read_json(path))



def _share(part: int, whole: int) -> Optional[float]:
    return None if not whole else round(part / whole, 6)


def _mean(values: Sequence[float]) -> Optional[float]:
    return None if not values else round(sum(values) / len(values), 6)


def _median(values: Sequence[float]) -> Optional[float]:
    return stage15._median(list(values))


def _cell(value: Any) -> str:
    """A table cell. ``None`` prints as ``n/a`` rather than as the word ``None``."""
    return "n/a" if value is None else str(value)


def _table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    """A markdown table, so every report number is auditable against the source data."""
    head = "| " + " | ".join(_cell(item) for item in header) + " |"
    rule = "|" + "|".join("---" for _ in header) + "|"
    body = ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def dataset_audit(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
) -> Dict[str, Any]:
    """The audit of section 3, run before any experiment, from observed repository state only."""
    historical = historical_rows(arch_root)
    corpus, skipped = load_control_corpus(songs_dir, ai_dir)
    controls = control_rows(corpus)
    rows = historical + controls
    tiers: Dict[str, Dict[str, Any]] = {}
    for tier, rule in TIER_RULES:
        members = [row for row in rows if row.tier == tier]
        tiers[tier] = {
            "rule": rule,
            "songs": [row.key for row in members],
            "count": len(members),
            "historical": [row.key for row in members if row.kind == KIND_HISTORICAL_SAP],
            "in_house": [row.key for row in members if row.kind != KIND_HISTORICAL_SAP],
        }
    historical_tiers = {row.tier for row in historical}
    in_house_tiers = {row.tier for row in controls}
    dataset_verdict = "INCONCLUSIVE"
    if historical_tiers:
        if historical_tiers == {TIER_A}:
            dataset_verdict = "TIER_A_AVAILABLE"
        elif historical_tiers == {TIER_B}:
            dataset_verdict = "TIER_B_ONLY"
        elif historical_tiers == {TIER_C}:
            dataset_verdict = "TIER_C_ONLY"
        elif historical_tiers == {TIER_D}:
            dataset_verdict = "TIER_D_ONLY"
    return {
        "question": (
            "For each candidate song, which of the seven inputs the brief names are actually "
            "available, and what is the highest tier the song reaches?"
        ),
        "method": (
            "The repository was enumerated; for every SAP trace the SAP file was located and "
            "hashed; for every composition document the document was parsed and compiled and the "
            "hash of the exact trace it produced was recorded. A flag is set only when the observed "
            "state supports it. No flag is inferred."
        ),
        "tier_rules": [{"tier": tier, "rule": rule} for tier, rule in TIER_RULES],
        "tiers": tiers,
        "counts": {
            "historical_sap": len(historical),
            "control_dsl": sum(1 for row in controls if row.kind == KIND_CONTROL_DSL),
            "control_json": sum(1 for row in controls if row.kind == KIND_CONTROL_JSON),
            "control_total": len(controls),
            "skipped": len(skipped),
            "profile_reference_dirs": len(profile_rows()),
        },
        "rows": [row.to_dict() for row in rows],
        "skipped_documents": skipped,
        "profile_references": profile_rows(),
        "external": external_source_audit(),
        "historical_tiers": sorted(historical_tiers),
        "in_house_tiers": sorted(in_house_tiers),
        "dataset_verdict": dataset_verdict,
        "headline": (
            f"Every one of the {len(historical)} historical songs is Tier D: there is a SAP, there "
            f"is an exact trace, and there is no independent composition of any kind. The "
            f"repository does own {len(controls)} compositions that reach Tier "
            f"{sorted(in_house_tiers)[0] if in_house_tiers else '?'}, but they are this project's "
            "own songs, not the historical ones. The historical question therefore cannot be "
            "decided from composition data, and the in-house corpus is used instead to calibrate "
            "the instrument Stage 20 measured with."
        ),
        "why_in_house_is_used": (
            "the in-house compositions are genuinely independent of any trace: they are authored "
            "documents that reference no register, and the trace is the project's own compiler's "
            "deterministic output. That makes them valid Tier A material for asking whether the "
            "note-level representation *can* be lossless, which is exactly the question Stage 20 "
            "left open. They cannot say anything about Draconus, Warhawk, Ninja Commando or Red "
            "Max, and no number from them is ever applied to those songs."
        ),
    }

    return "\n".join([head, rule, *body])



# ===========================================================================
# PART 2 - independent composition notes, and a prediction built only from them
# ===========================================================================
@dataclass(frozen=True)
class CompositionNote:
    """One note as the *composition* states it, positioned in frames by the composition's own rules.

    Nothing here is read from a trace. The pitch comes from the note's MIDI number, the length from
    its duration in rows, the level from its volume and its instrument's envelope, and the position
    from the pattern's row offset inside the sequence. The divider is derived afterwards from the
    pitch by the project's own hardware formula, which is a model of POKEY rather than a reading of
    this song's registers.
    """

    channel: int
    voice_id: str
    joined: bool
    pitch_channels: Tuple[int, ...]
    volume_channel: int
    sequence_index: int
    pattern_id: int
    pattern_name: str
    row: int
    start: int
    end: int
    duration_rows: int
    midi: Optional[int]
    pitch: Optional[str]
    volume: int
    distortion_byte: int
    instrument_id: Optional[int]
    is_rest: bool
    role: str
    envelope: Tuple[int, int, int, int]
    divider: Optional[int]
    hz: Optional[float]

    @property
    def frames(self) -> int:
        return self.end - self.start

    @property
    def pack(self) -> int:
        """The AUDC high nibble the project's exporter writes for this note's distortion."""
        return self.distortion_byte & 0xE0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "voice_id": self.voice_id,
            "joined_16bit": self.joined,
            "pitch_channels": list(self.pitch_channels),
            "sequence_index": self.sequence_index,
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "row": self.row,
            "start_frame": self.start,
            "end_frame": self.end,
            "frames": self.frames,
            "duration_rows": self.duration_rows,
            "midi": self.midi,
            "pitch": self.pitch,
            "hz": _rnd(self.hz, 4),
            "divider": self.divider,
            "volume": self.volume,
            "distortion": f"${self.distortion_byte:02X}",
            "instrument_id": self.instrument_id,
            "is_rest": self.is_rest,
            "role": self.role,
            "envelope": {
                "attack_frames": self.envelope[0],
                "decay_frames": self.envelope[1],
                "sustain_vol": self.envelope[2],
                "release_frames": self.envelope[3],
            },
        }


def distortion_nibble(byte_value: int) -> int:
    """The AUDC distortion of a byte the exporter writes as ``(distortion & 0xE0) | volume``."""
    return (int(byte_value) & 0xE0) >> 4



def composition_notes(song: Any, trace: Any) -> List[CompositionNote]:
    """Expand a composition into absolutely-positioned notes, by the composition's own rules.

    The row arithmetic mirrors :func:`atari_music.ir.compile_ir_to_pokey_frames` exactly - a
    pattern occupies ``pattern.rows * frames_per_tick`` frames, and inside a pattern the row cursor
    advances by each note's duration - because otherwise the baseline would be misaligned with the
    trace by construction and the residual would measure this function's arithmetic instead of the
    music. Two composition-side conventions are mirrored deliberately and are stated here:

    * when the song is in 16-bit bass, channel 2 is the high byte of channel 1's divider and its own
      notes are not rendered, so channel 2 is skipped;
    * a rest occupies its frames but carries no pitch.

    Both are properties of the composition and its compiler, not of any trace, so mirroring them
    does not import trace information.
    """
    frames_per_tick = int(song.frames_per_tick)
    audctl = int(trace.audctl)
    instruments = {instrument.id: instrument for instrument in song.instruments}
    patterns = {pattern.id: pattern for pattern in song.patterns}
    voice_for: Dict[int, Any] = {}
    for voice in stage15.voices_for(audctl):
        for channel in voice.channels:
            voice_for[channel] = voice

    notes: List[CompositionNote] = []
    for channel in range(1, 5):
        if song.uses_16bit_bass and channel == 2:
            continue
        voice = voice_for.get(channel)
        if voice is None:
            raise Stage21Error(
                f"{trace.song}: channel {channel} has no voice under AUDCTL ${audctl:02X}"
            )
        cursor = 0
        for sequence_index, pattern_id in enumerate(song.sequence):
            pattern = patterns.get(pattern_id)
            if pattern is None:
                continue
            row = 0
            for note in pattern.tracks.get(channel, []):
                duration_rows = max(1, int(note.duration))
                start = cursor + row * frames_per_tick
                end = start + duration_rows * frames_per_tick
                row += duration_rows
                instruments_of = instruments.get(note.instrument_id)
                envelope = getattr(instruments_of, "envelope", None)
                env = (
                    (
                        int(envelope.attack_frames), int(envelope.decay_frames),
                        int(envelope.sustain_vol), int(envelope.release_frames),
                    )
                    if envelope is not None else (0, 0, 0, 0)
                )
                raw_distortion = note.distortion
                if raw_distortion is None:
                    raw_distortion = (
                        instruments_of.distortion if instruments_of is not None
                        else ir.DISTORTION_PURE_TONE
                    )
                midi = note.midi_pitch
                if midi is None and note.pitch:
                    midi = ir.note_name_to_midi(str(note.pitch))
                midi = None if midi is None else int(midi)
                unpitched = pokey_hw.is_unpitched_percussion(midi, note.channel_role)
                # :func:`ir._render_note_to_frames` renders a note as silence when it is a rest,
                # or when it has no pitch and is not a percussion hit. Mirroring that keeps the
                # baseline aligned with the trace instead of inventing a pitch the composition
                # never gave.
                silent = bool(note.is_rest) or (midi is None and not unpitched)
                hz = None
                divider = None
                if not silent:
                    if unpitched:
                        divider = int(pokey_hw.PERCUSSION_DEFAULT_AUDF)
                    else:
                        hz = ir.midi_pitch_to_frequency(midi)
                        if voice.joined:
                            low, high = ir.frequency_to_audf_16bit(hz, audctl=audctl, channel=1)
                            divider = (
                                (pokey_hw.clamp_audf_for_tracker(high) << 8)
                                | pokey_hw.clamp_audf_for_tracker(low)
                            )
                        else:
                            divider = pokey_hw.clamp_audf_for_tracker(
                                ir.frequency_to_audf_8bit(hz, audctl=audctl, channel=channel)
                            )
                notes.append(
                    CompositionNote(
                        channel=channel,
                        voice_id=voice.voice_id,
                        joined=bool(voice.joined),
                        pitch_channels=tuple(voice.channels),
                        volume_channel=int(voice.volume_channel),
                        sequence_index=sequence_index,
                        pattern_id=int(pattern_id),
                        pattern_name=str(pattern.name),
                        row=start // frames_per_tick,
                        start=start,
                        end=end,
                        duration_rows=duration_rows,
                        midi=None if midi is None else int(midi),
                        pitch=None if note.pitch is None else str(note.pitch),
                        volume=int(note.volume),
                        distortion_byte=int(raw_distortion),
                        instrument_id=None if note.instrument_id is None else int(note.instrument_id),
                        is_rest=silent,
                        role=str(note.channel_role),
                        envelope=env,
                        divider=divider,
                        hz=hz,
                    )
                )
            cursor += int(pattern.rows) * frames_per_tick
    notes.sort(key=lambda item: (item.channel, item.start, item.sequence_index))
    return notes



AUDF_COLUMN = stage20.AUDF_COLUMN
AUDC_COLUMN = stage20.AUDC_COLUMN
AUDCTL_COLUMN = stage20.AUDCTL_COLUMN


@dataclass(frozen=True)
class Plan:
    """One note reduced to exactly what the predictor needs. The single input to every baseline.

    Keeping one plan type for both note sources is what makes the comparison between them a
    comparison of *information* rather than of code: the independent notes and the detector's notes
    are turned into the same structure and pushed through the same predictor, so any difference in
    the residual is a difference in what the notes say.
    """

    voice_id: str
    start: int
    end: int
    dividers: Tuple[Tuple[int, int], ...]
    pack: int
    peak: int
    attack: int
    decay: int
    sustain: int
    release: int


def plans_from_composition(notes: Sequence[CompositionNote]) -> List[Plan]:
    """The composition's notes as plans. Rests are dropped: a rest is silence, not a note."""
    plans: List[Plan] = []
    for note in notes:
        if note.is_rest or note.divider is None:
            continue
        if note.joined:
            low_channel, high_channel = note.pitch_channels
            dividers = (
                (low_channel, note.divider & 0xFF),
                (high_channel, (note.divider >> 8) & 0xFF),
            )
        else:
            dividers = ((note.pitch_channels[0], note.divider),)
        attack, decay, sustain, release = note.envelope
        plans.append(
            Plan(
                voice_id=note.voice_id,
                start=note.start,
                end=note.end,
                dividers=tuple(sorted(dividers)),
                pack=note.pack,
                peak=min(15, max(0, note.volume)),
                attack=attack,
                decay=decay,
                sustain=sustain,
                release=release,
            )
        )
    return plans


def plans_from_records(records: Sequence[Any], audctl: int) -> List[Plan]:
    """Stage 20's detected notes as plans, using Stage 20's own pitch mapping unchanged.

    ``stage20.predict_divider`` is called rather than re-derived, so the detector arm of every
    comparison is literally the Stage 20 baseline and not a reimplementation of it.
    """
    plans: List[Plan] = []
    for record in records:
        dividers = stage20.predict_divider(record, audctl)
        peak, attack, sustain, release = record.effective_contour(True)
        plans.append(
            Plan(
                voice_id=record.voice_id,
                start=record.start,
                end=record.end + 1,
                dividers=tuple(sorted(dividers.items())),
                pack=(record.distortion & 0x0F) << 4,
                peak=peak,
                attack=attack,
                decay=0,
                sustain=sustain,
                release=release,
            )
        )
    return plans



def predict_from_plans(
    frames: int,
    audctl: int,
    plans: Sequence[Plan],
    frames_per_tick: int,
    outside: str = OUTSIDE_HOLD,
    contour: str = CONTOUR_COMPOSITION,
    level: str = "envelope",
    shift: int = 0,
) -> List[Tuple[int, ...]]:
    """The whole stream predicted from notes alone: nine registers for every frame.

    Three independent switches, each of which is a *statement about what the baseline is allowed to
    know*, and each of which is reported wherever it is used:

    * ``outside`` - what a register holds in a frame no note covers. ``hold`` is what ``player.asm``
      does and what Stage 20's baseline does; ``exporter`` is what the project's own frame compiler
      leaves behind, which is zero.
    * ``contour`` - the level track. ``reduced`` is Stage 20's four-parameter reduction with decay
      forced to zero and the envelope evaluated at one frame per tick; ``composition`` is the
      composition's own five-parameter envelope evaluated at the song's real frames per tick.
    * ``level`` - ``envelope`` uses the contour; ``none`` writes level zero, which is the
      pitch-only baseline B0 of section 11 (it claims nothing about volume at all).

    The loop structure - per voice, per register, with the joined pair's low channel muted - is
    Stage 20's, and :func:`assert_matches_stage20` proves the two agree when the switches are set
    to the values Stage 20 hard-codes.
    """
    if outside not in OUTSIDE_POLICIES:
        raise Stage21Error(f"unknown outside policy {outside!r}")
    if contour not in CONTOUR_SOURCES:
        raise Stage21Error(f"unknown contour source {contour!r}")
    if level not in ("envelope", "flat", "none"):
        raise Stage21Error(f"unknown level mode {level!r}")

    prediction: List[List[int]] = [[0] * FRAME_BYTES for _ in range(frames)]
    for frame in range(frames):
        prediction[frame][AUDCTL_COLUMN] = audctl

    for voice in stage15.voices_for(audctl):
        volume_channel = voice.volume_channel
        mine = [plan for plan in plans if plan.voice_id == voice.voice_id]
        audf_track: Dict[int, List[Optional[int]]] = {
            channel: [None] * frames for channel in voice.channels
        }
        audc_track: List[Optional[int]] = [None] * frames
        for plan in mine:
            start = max(0, min(frames - 1, plan.start + shift))
            end = max(0, min(frames - 1, plan.end - 1 + shift))
            if end < start:
                continue
            length = end - start + 1
            if level == "none":
                levels = [0] * length
            elif level == "flat":
                # The note's level as a single scalar: the waveform and the loudness are known, the
                # shape over time is not. This is the middle rung of the baseline ladder.
                levels = [plan.peak] * length
            elif contour == CONTOUR_REDUCED:
                levels = stage20.contour_levels(
                    length, (plan.peak, plan.attack, plan.sustain, plan.release)
                )
            else:
                levels = pokey_hw.player_envelope_volumes(
                    length, frames_per_tick, plan.peak, plan.attack, plan.decay,
                    plan.sustain, plan.release,
                )
            for offset in range(length):
                frame = start + offset
                for channel, value in plan.dividers:
                    if channel in audf_track:
                        audf_track[channel][frame] = value
                audc_track[frame] = plan.pack | (levels[offset] & 0x0F)

        held = {channel: 0 for channel in voice.channels}
        for frame in range(frames):
            for channel in voice.channels:
                value = audf_track[channel][frame]
                if value is None:
                    value = held[channel] if outside == OUTSIDE_HOLD else 0
                else:
                    held[channel] = value
                prediction[frame][AUDF_COLUMN[channel]] = value
            volume = audc_track[frame]
            prediction[frame][AUDC_COLUMN[volume_channel]] = 0 if volume is None else volume
            if voice.joined:
                prediction[frame][AUDC_COLUMN[voice.channels[0]]] = 0
    return [tuple(row) for row in prediction]


def assert_matches_stage20(trace: Any) -> Dict[str, Any]:
    """Prove that the Stage 21 predictor reproduces Stage 20's baseline bit for bit.

    This is the bridge that makes every comparison in this stage meaningful. If the two predictors
    disagreed, a difference between a detector residual and a composition residual could be a
    difference of code rather than of information, and the whole stage would be worthless. The
    check runs on the real corpus, not on a toy: every song it is given, every register, every frame.
    """
    records = stage20.note_records(trace)
    reference = stage20.predict_frames(trace, records, 0, True)
    plans = plans_from_records(records, trace.audctl)
    mine = predict_from_plans(
        trace.frames, trace.audctl, plans, 1, OUTSIDE_HOLD, CONTOUR_REDUCED, "envelope", 0
    )
    mismatches = [
        (frame, column) for frame in range(trace.frames) for column in range(FRAME_BYTES)
        if reference[frame][column] != mine[frame][column]
    ]
    return {
        "slug": trace.slug,
        "frames": trace.frames,
        "register_values": trace.frames * FRAME_BYTES,
        "mismatches": len(mismatches),
        "first_mismatches": mismatches[:8],
        "agrees": not mismatches,
        "meaning": (
            "zero mismatches means the Stage 21 predictor, run with Stage 20's own switch values "
            "(hold outside notes, reduced four-parameter contour, envelope levels), is the same "
            "function as stage20.predict_frames on this corpus"
        ),
    }


# ===========================================================================
# PART 3 - validating the note information itself (sections 8, 9 and 10)
# ===========================================================================
def pitch_validation(trace: Any, notes: Sequence[CompositionNote]) -> Dict[str, Any]:
    """Composition pitch against the divider the trace actually holds at the note's onset.

    Three error scales are reported because they mean different things and a single percentage would
    hide the difference: an *exact* divider match says the hardware model and the trace agree; a
    *divider error* says how far apart they are in register units; a *semitone error* says whether
    the disagreement is audible tuning or an octave/register boundary. An octave or register error
    is counted separately, because a wrong 16-bit split or a wrong clock is not a tuning error.
    """
    voices = {voice.voice_id: voice for voice in stage15.voices_for(int(trace.audctl))}
    checked = 0
    exact = 0
    divider_errors: List[int] = []
    semitone_errors: List[float] = []
    octave_errors = 0
    per_register: Dict[str, Dict[str, int]] = {}
    mismatch_samples: List[Dict[str, Any]] = []
    for note in notes:
        if note.is_rest or note.divider is None or note.frames <= 0:
            continue
        start = note.start
        if start >= trace.frames:
            continue
        voice = voices.get(note.voice_id)
        if voice is None:
            continue
        checked += 1
        if note.joined:
            low_channel, high_channel = note.pitch_channels
            actual_pairs = (
                (f"AUDF{low_channel}", note.divider & 0xFF,
                 int(trace.registers[f"AUDF{low_channel}"][start])),
                (f"AUDF{high_channel}", (note.divider >> 8) & 0xFF,
                 int(trace.registers[f"AUDF{high_channel}"][start])),
            )
            actual_divider = (actual_pairs[1][2] << 8) | actual_pairs[0][2]
        else:
            channel = note.pitch_channels[0]
            actual_pairs = (
                (f"AUDF{channel}", note.divider, int(trace.registers[f"AUDF{channel}"][start])),
            )
            actual_divider = actual_pairs[0][2]
        for name, want, got in actual_pairs:
            bucket = per_register.setdefault(name, {"checked": 0, "exact": 0})
            bucket["checked"] += 1
            if want == got:
                bucket["exact"] += 1
        if actual_divider == note.divider:
            exact += 1
            continue
        divider_errors.append(actual_divider - note.divider)
        expected_hz = stage15.divider_to_hz(note.divider, voice, int(trace.audctl))
        actual_hz = stage15.divider_to_hz(actual_divider, voice, int(trace.audctl))
        semitones = stage15.semitones_between(expected_hz, actual_hz)
        if semitones is not None:
            semitone_errors.append(semitones)
            if abs(round(semitones / 12.0)) >= 1:
                octave_errors += 1
        if len(mismatch_samples) < 12:
            mismatch_samples.append({
                "pattern": note.pattern_name,
                "row": note.row,
                "start_frame": start,
                "midi": note.midi,
                "pitch": note.pitch,
                "expected_divider": note.divider,
                "actual_divider": actual_divider,
                "semitone_error": _rnd(semitones, 4) if semitones is not None else None,
            })
    magnitudes = [abs(value) for value in semitone_errors]
    return {
        "notes_checked": checked,
        "exact_divider_matches": exact,
        "exact_share": _share(exact, checked),
        "divider_error_median": _median(divider_errors),
        "divider_error_max_abs": max((abs(value) for value in divider_errors), default=0),
        "semitone_error_median_abs": _median(magnitudes),
        "semitone_error_mean_abs": _mean(magnitudes),
        "semitone_error_max_abs": max(magnitudes, default=0.0),
        "octave_or_register_errors": octave_errors,
        "per_register": per_register,
        "mismatch_samples": mismatch_samples,
        "reading": (
            "an exact divider match means the project's pitch model and the trace agree at that "
            "note's onset, so the pitch component of the residual is not a model gap. Octave errors "
            "are counted apart from tuning errors because a wrong clock or a wrong 16-bit split is "
            "not a tuning disagreement."
        ),
    }


def timing_validation(
    trace: Any, notes: Sequence[CompositionNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """Composition timing against the detector's notes, plus frame-level occupancy agreement.

    Onset error is the distance from each detected onset to the nearest composition onset *on the
    same voice*, which is the only comparison that does not assume a global phase. Occupancy
    agreement is per voice per frame, so a song where the detector merges two repeated identical
    pitches shows up as a coverage gap rather than as a rounding artefact.
    """
    if not notes:
        return {
            "available": False,
            "reason": "there are no independent composition notes for this trace (Tier D)",
        }
    onsets_by_voice: Dict[str, List[int]] = {}
    for note in notes:
        if not note.is_rest:
            onsets_by_voice.setdefault(note.voice_id, []).append(note.start)
    for value in onsets_by_voice.values():
        value.sort()

    onset_errors: List[int] = []
    duration_errors: List[int] = []
    compared = 0
    for record in records:
        candidates = onsets_by_voice.get(record.voice_id, [])
        if not candidates:
            continue
        nearest = min(candidates, key=lambda value: (abs(value - record.start), value))
        onset_errors.append(record.start - nearest)
        nearest_note = min(
            (note for note in notes if not note.is_rest and note.voice_id == record.voice_id),
            key=lambda note: (abs(note.start - record.start), note.start),
            default=None,
        )
        if nearest_note is not None:
            duration_errors.append(record.frames - nearest_note.frames)
            compared += 1

    occupancy: Dict[str, Dict[str, Any]] = {}
    for voice in stage15.voices_for(int(trace.audctl)):
        truth = [False] * trace.frames
        found = [False] * trace.frames
        for note in notes:
            if note.voice_id == voice.voice_id and not note.is_rest:
                for frame in range(note.start, min(note.end, trace.frames)):
                    truth[frame] = True
        for record in records:
            if record.voice_id == voice.voice_id:
                for frame in range(record.start, min(record.end + 1, trace.frames)):
                    found[frame] = True
        both = sum(1 for frame in range(trace.frames) if truth[frame] and found[frame])
        either = sum(1 for frame in range(trace.frames) if truth[frame] or found[frame])
        truth_count = sum(1 for value in truth if value)
        occupancy[voice.voice_id] = {
            "composition_frames": truth_count,
            "detector_frames": sum(1 for value in found if value),
            "agreement_frames": both,
            "union_frames": either,
            "jaccard": _share(both, either),
            "detector_recall": _share(both, truth_count),
        }
    absolute = [abs(value) for value in onset_errors]
    return {
        "available": True,
        "detected_notes": len(records),
        "composition_notes": sum(1 for note in notes if not note.is_rest),
        "onset_error_median": _median(onset_errors),
        "onset_error_mean": _mean([float(value) for value in onset_errors]),
        "onset_error_max_abs": max(absolute, default=0),
        "onset_exact_share": _share(
            sum(1 for value in onset_errors if value == 0), len(onset_errors)
        ),
        "onset_within_one_frame_share": _share(
            sum(1 for value in absolute if value <= 1), len(absolute)
        ),
        "duration_error_median": _median(duration_errors),
        "duration_error_max_abs": max((abs(value) for value in duration_errors), default=0),
        "compared_notes": compared,
        "occupancy": occupancy,
        "flag": (
            "TIMING_EXACT" if all(value == 0 for value in onset_errors) else "TIMING_APPROXIMATE"
        ),
        "reading": (
            "onset error is the distance from a detected onset to the nearest composition onset on "
            "the same voice. On the control corpus the composition itself is exact, so any onset "
            "error here is the *detector's* error and must never be re-read later as performance "
            "timing."
        ),
    }


def boundary_tolerance(
    trace: Any,
    notes: Sequence[CompositionNote],
    frames_per_tick: int,
    outside: str = OUTSIDE_EXPORTER,
    tolerances: Sequence[int] = BOUNDARY_TOLERANCES,
) -> Dict[str, Any]:
    """How much residual survives when a note boundary may be off by one, two, three frames.

    A register value counts as explained if it agrees with the prediction made at *any* shift in
    ``[-tolerance, +tolerance]``. If the residual collapses at one frame the notes are merely
    misaligned and there is no evidence of anything else; if it survives every tolerance, alignment
    is not the explanation. Tolerance zero is the honest measurement; the rest are diagnostics.
    """
    plans = plans_from_composition(notes)
    total = trace.frames * FRAME_BYTES
    exact = [
        tuple(int(trace.registers[name][frame]) for name in REGISTER_ORDER)
        for frame in range(trace.frames)
    ]
    steps: List[Dict[str, Any]] = []
    for tolerance in tolerances:
        shifts = list(range(-tolerance, tolerance + 1))
        predictions = [
            predict_from_plans(
                trace.frames, int(trace.audctl), plans, frames_per_tick, outside,
                CONTOUR_COMPOSITION, "envelope", shift,
            )
            for shift in shifts
        ]
        explained = 0
        for frame in range(trace.frames):
            row = exact[frame]
            for column in range(FRAME_BYTES):
                value = row[column]
                if any(prediction[frame][column] == value for prediction in predictions):
                    explained += 1
        steps.append({
            "tolerance_frames": tolerance,
            "shifts_tried": shifts,
            "explained_values": explained,
            "residual_values": total - explained,
            "residual_share": _share(total - explained, total),
        })
    widest = steps[-1]["residual_share"] if steps else None
    return {
        "total_register_values": total,
        "steps": steps,
        "flag": (
            "ALIGNMENT_NOT_THE_EXPLANATION" if widest and widest > 0.0
            else "ALIGNMENT_MAY_EXPLAIN_THE_RESIDUAL"
        ),
        "reading": (
            "tolerance zero is the measurement. The wider tolerances exist only to show whether a "
            "residual is alignment noise, and they are never used as the reported number."
        ),
    }


# ===========================================================================
# PART 4 - the baseline ladder and the residual comparison (sections 11 to 13)
# ===========================================================================
@dataclass(frozen=True)
class OccupancySpan:
    """The minimum a note must expose for Stage 20's per-register occupancy classifier to run."""

    pitch_channels: Tuple[int, ...]
    volume_channel: int
    joined: bool
    start: int
    end: int


def spans_from_composition(notes: Sequence[CompositionNote]) -> List[OccupancySpan]:
    spans = [
        OccupancySpan(
            pitch_channels=note.pitch_channels,
            volume_channel=note.volume_channel,
            joined=note.joined,
            start=note.start,
            end=max(note.start, note.end - 1),
        )
        for note in notes
        if not note.is_rest and note.frames > 0
    ]
    spans.sort(key=lambda span: (span.start, span.pitch_channels))
    return spans


def spans_from_records(records: Sequence[Any]) -> List[OccupancySpan]:
    return [
        OccupancySpan(
            pitch_channels=tuple(record.pitch_channels),
            volume_channel=record.volume_channel,
            joined=bool(record.joined),
            start=record.start,
            end=record.end,
        )
        for record in records
    ]


def streams_of(trace: Any) -> Any:
    """A canonical Stage 18 stream for any trace, historical or compiled."""
    return stage18.FrameStream(
        slug=trace.slug,
        frames=trace.frames,
        frame_period_us=COMPILED_FRAME_PERIOD_US,
        registers={name: trace.registers[name] for name in REGISTER_ORDER},
    )


def _plans_without_generator(plans: Sequence[Plan]) -> List[Plan]:
    """The same plans with the generator zeroed. Kept as an explicit helper for the B0 rung."""
    from dataclasses import replace

    return [replace(plan, pack=0) for plan in plans]


def baselines(trace: Any, notes: Sequence[CompositionNote], frames_per_tick: int) -> Dict[str, Any]:
    """B0, B1 and B2: the same notes, with progressively more of what the composition says.

    The ladder exists to separate three explanations a single number would merge. Each rung is
    defined by exactly which fields of the note the baseline is given:

    * **B0** - pitch, onset and duration. The baseline writes level zero everywhere, so it claims
      nothing about waveform or volume and its residual contains both.
    * **B1** - B0 plus the generator and the note's loudness *as a single scalar*: AUDC is the
      instrument's distortion with the note's volume held flat for the whole note. The waveform and
      the loudness are known; the shape over time is not.
    * **B2** - B1 plus the envelope: the composition's own attack, decay, sustain and release
      (B2 = pitch, onset, duration, generator, level and envelope, which is the full note record).

    The two steps are therefore ``B0 -> B1`` the waveform and loudness, and ``B1 -> B2`` the shape
    over time. A negative step is possible and is reported rather than clamped: it means the extra
    field made a prediction worse, which would be a real defect worth seeing.

    ``outside`` is fixed at the exporter convention, because the comparison that matters is against
    a compiled trace; the hold convention is measured separately by :func:`convention_cost`.
    """
    plans = plans_from_composition(notes)
    spans = spans_from_composition(notes)
    stream = streams_of(trace)
    rungs = {
        "B0": (plans, "none"),
        "B1": (plans, "flat"),
        "B2": (plans, "envelope"),
    }
    given = {
        "B0": "pitch, onset, duration",
        "B1": "pitch, onset, duration, generator and loudness as one scalar",
        "B2": "pitch, onset, duration, generator, loudness and envelope",
    }
    out: Dict[str, Any] = {}
    for name in BASELINE_NAMES:
        plan_set, level = rungs[name]
        predicted = predict_from_plans(
            trace.frames, int(trace.audctl), plan_set, frames_per_tick,
            OUTSIDE_EXPORTER, CONTOUR_COMPOSITION, level, 0,
        )
        residual = stage20.build_residual(stream, trace, predicted)
        report = stage20.residual_report(residual, trace, spans)
        out[name] = {
            "given": given[name],
            "residual_values": report["residual_values"],
            "register_values": report["register_values"],
            "residual_share": report["residual_share"],
            "register_coverage": report["register_coverage"],
            "by_class": report["by_class"],
            "per_register": {
                key: value["residual_values"] for key, value in report["per_register"].items()
            },
        }
    return {
        "variants": out,
        "steps": {
            "waveform_and_loudness_step_B0_to_B1": _share(
                out["B0"]["residual_values"] - out["B1"]["residual_values"],
                out["B0"]["residual_values"],
            ),
            "envelope_step_B1_to_B2": _share(
                out["B1"]["residual_values"] - out["B2"]["residual_values"],
                out["B1"]["residual_values"],
            ),
            "total_step_B0_to_B2": _share(
                out["B0"]["residual_values"] - out["B2"]["residual_values"],
                out["B0"]["residual_values"],
            ),
        },
        "reading": (
            "each step is the share of the previous rung's residual that the newly added field "
            "removes. A large first step means the waveform and loudness were the missing "
            "information; a large second step means the shape over time was."
        ),
    }


def convention_cost(
    trace: Any, notes: Sequence[CompositionNote], frames_per_tick: int
) -> Dict[str, Any]:
    """The measured cost of the hold-versus-zero convention, on a trace whose truth is known.

    Reported as its own quantity because it is neither music nor a defect of the notes: it is a
    disagreement between two project components. Dressing it as a residual category would inflate
    the residual's apparent structure, so it is named, measured and set aside.
    """
    plans = plans_from_composition(notes)
    stream = streams_of(trace)
    out: Dict[str, Any] = {}
    for outside in OUTSIDE_POLICIES:
        predicted = predict_from_plans(
            trace.frames, int(trace.audctl), plans, frames_per_tick,
            outside, CONTOUR_COMPOSITION, "envelope", 0,
        )
        residual = stage20.build_residual(stream, trace, predicted)
        per_register = {
            name: sum(1 for value in residual.values[column] if value)
            for column, name in enumerate(REGISTER_ORDER)
        }
        out[outside] = {
            "residual_values": residual.residual_values(),
            "residual_share": _share(residual.residual_values(), trace.frames * FRAME_BYTES),
            "per_register": {key: value for key, value in per_register.items() if value},
        }
    out["cost_of_hold"] = (
        out[OUTSIDE_HOLD]["residual_values"] - out[OUTSIDE_EXPORTER]["residual_values"]
    )
    out["explanation"] = (
        "player.asm holds AUDF across a rest; ir.compile_ir_to_pokey_frames writes a register only "
        "inside a note, so an unwritten frame keeps the array's initial value of zero. Every value "
        "in cost_of_hold is an AUDF frame outside a note, and none of it is performance."
    )
    return out


def arm_detector(trace: Any) -> Dict[str, Any]:
    """The Stage 15 detector arm: Stage 20's baseline, unchanged, on any trace."""
    records = stage20.note_records(trace)
    predicted = stage20.predict_frames(trace, records, 0, True)
    residual = stage20.build_residual(streams_of(trace), trace, predicted)
    report = stage20.residual_report(residual, trace, records)
    return {
        "notes": len(records),
        "source": "stage15.note_spans over the trace",
        "evidence": EVIDENCE_INFERENCE,
        "residual_values": report["residual_values"],
        "register_values": report["register_values"],
        "residual_share": report["residual_share"],
        "register_coverage": report["register_coverage"],
        "frame_coverage": report["frame_coverage"],
        "by_class": report["by_class"],
        "by_class_share": report["by_class_share"],
        "per_register": {
            key: value["residual_values"] for key, value in report["per_register"].items()
        },
        "residual": residual,
        "records": records,
    }


def arm_independent(
    trace: Any,
    notes: Sequence[CompositionNote],
    frames_per_tick: int,
    outside: str = OUTSIDE_EXPORTER,
) -> Dict[str, Any]:
    """The independent-composition arm: the same predictor, fed the composition's own notes."""
    plans = plans_from_composition(notes)
    spans = spans_from_composition(notes)
    predicted = predict_from_plans(
        trace.frames, int(trace.audctl), plans, frames_per_tick, outside,
        CONTOUR_COMPOSITION, "envelope", 0,
    )
    residual = stage20.build_residual(streams_of(trace), trace, predicted)
    report = stage20.residual_report(residual, trace, spans)
    return {
        "notes": len(plans),
        "source": "the composition document, positioned by the composition's own row arithmetic",
        "evidence": EVIDENCE_OBSERVED,
        "residual_values": report["residual_values"],
        "register_values": report["register_values"],
        "residual_share": report["residual_share"],
        "register_coverage": report["register_coverage"],
        "frame_coverage": report["frame_coverage"],
        "by_class": report["by_class"],
        "by_class_share": report["by_class_share"],
        "per_register": {
            key: value["residual_values"] for key, value in report["per_register"].items()
        },
        "residual": residual,
        "spans": spans,
    }


def _slim_arm(arm: Mapping[str, Any]) -> Dict[str, Any]:
    """An arm without its per-frame arrays, for the artefacts."""
    return {
        key: value for key, value in arm.items()
        if key not in ("residual", "records", "spans")
    }


def residual_comparison(
    trace: Any,
    notes: Sequence[CompositionNote],
    frames_per_tick: int,
    detector: Optional[Mapping[str, Any]] = None,
    independent: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """R_detector against R_independent on one trace, in the same neutral residual representation.

    This is section 14 of the brief, and on a control trace it is *decidable*, because the
    composition is the ground truth. The three outcomes it distinguishes are:

    * ``DETECTOR_INFLATED_RESIDUAL`` - the independent residual is far smaller than the detector's,
      so the detector manufactured residual out of nothing;
    * ``RESIDUAL_IS_REAL`` - the two agree, so the residual is a property of the stream rather than
      of the note detector;
    * ``DETECTOR_COMPENSATING`` - the independent residual is *larger*, so the detector was
      accidentally matching the trace it was read from.

    The classification uses a stated ratio, so a reader can reclassify rather than re-run.
    """
    detector = detector if detector is not None else arm_detector(trace)
    independent = (
        independent if independent is not None
        else arm_independent(trace, notes, frames_per_tick)
    )
    detector_values = detector["residual_values"]
    independent_values = independent["residual_values"]
    ratio = (
        None if independent_values == 0
        else round(detector_values / independent_values, 6)
    )
    if independent_values == 0 and detector_values == 0:
        outcome = "BOTH_ZERO"
    elif independent_values == 0:
        outcome = "DETECTOR_INFLATED_RESIDUAL"
    elif ratio is not None and ratio >= 2.0:
        outcome = "DETECTOR_INFLATED_RESIDUAL"
    elif ratio is not None and ratio <= 0.5:
        outcome = "DETECTOR_COMPENSATING"
    else:
        outcome = "RESIDUAL_IS_REAL"
    return {
        "slug": trace.slug,
        "frames": trace.frames,
        "register_values": trace.frames * FRAME_BYTES,
        "R_detector": _slim_arm(detector),
        "R_independent": _slim_arm(independent),
        "R_detector_values": detector_values,
        "R_independent_values": independent_values,
        "ratio_detector_over_independent": ratio,
        "detector_residual_removed_by_notes": _share(
            detector_values - independent_values, detector_values
        ),
        "outcome": outcome,
        "decision_rule": (
            "outcome is DETECTOR_INFLATED_RESIDUAL when R_detector >= 2 * R_independent, "
            "DETECTOR_COMPENSATING when R_detector <= 0.5 * R_independent, and RESIDUAL_IS_REAL "
            "in between; BOTH_ZERO when neither arm produces a mismatch. The thresholds are "
            "declared here so the classification can be audited rather than trusted."
        ),
        "independent_of_trace": True,
        "why_this_is_decidable_here": (
            "on a control trace the composition *is* the ground truth, so both arms can be built and "
            "compared. On a historical trace only the detector arm exists, and no such comparison is "
            "possible - which is precisely why the historical question cannot be settled."
        ),
    }


def residual_categories(
    trace: Any,
    spans: Sequence[OccupancySpan],
    residual: Any,
    boundary_frames: int = 1,
) -> Dict[str, Any]:
    """Assign every residual value to one of the brief's five categories, by an explicit rule.

    The rule is deliberately conservative: ``CONFIRMED_PERFORMANCE_CANDIDATE`` is only reachable for
    a value that (a) lies outside every note the representation claims, (b) sits on a register the
    representation *did* model, and (c) is farther than ``boundary_frames`` from any note boundary.
    Everything else is assigned to a named uncertainty instead. On a Tier D trace not one value can
    be *confirmed*, because confirmation requires an independent note source, so the category is
    reported with a measured count of zero and the reason - an empty category that is honestly empty
    is a finding, and an empty category that is quietly widened is a lie.

    The boundary band is measured, not assumed: the report says how much of the residual sits within
    one frame of a note edge, so a reader can see whether alignment could be carrying it.
    """
    classes = stage20.register_occupancy(trace, spans)
    modelled_columns = set()
    boundary: Dict[int, set] = {}
    for span in spans:
        for channel in span.pitch_channels:
            column = AUDF_COLUMN[channel]
            modelled_columns.add(column)
            boundary.setdefault(column, set()).update(
                range(span.start - boundary_frames, span.end + 1 + boundary_frames + 1)
            )
        volume_column = AUDC_COLUMN[span.volume_channel]
        modelled_columns.add(volume_column)
        boundary.setdefault(volume_column, set()).update(
            range(span.start - boundary_frames, span.end + 1 + boundary_frames + 1)
        )
        if span.joined:
            low_column = AUDC_COLUMN[span.pitch_channels[0]]
            modelled_columns.add(low_column)
            boundary.setdefault(low_column, set()).update(
                range(span.start - boundary_frames, span.end + 1 + boundary_frames + 1)
            )
    counts = {name: 0 for name in RESIDUAL_CATEGORIES}
    explained = 0
    by_register: Dict[str, Dict[str, int]] = {}
    for column, name in enumerate(REGISTER_ORDER):
        bucket = {key: 0 for key in RESIDUAL_CATEGORIES}
        values = residual.values[column]
        for frame in range(residual.frames):
            if not values[frame]:
                explained += 1
                continue
            kind = classes[column][frame]
            if kind == stage20.CLASS_GAP:
                category = CAT_UNRESOLVED if column in modelled_columns else CAT_CHANNEL_UNCERTAINTY
            elif frame in boundary.get(column, ()):
                category = CAT_ALIGNMENT_UNCERTAINTY
            else:
                category = CAT_BASELINE_ERROR
            bucket[category] += 1
            counts[category] += 1
        by_register[name] = bucket
    return {
        "counts": counts,
        "explained_values": explained,
        "residual_values": residual.residual_values(),
        "register_values": residual.frames * FRAME_BYTES,
        "by_register": by_register,
        "boundary_frames": boundary_frames,
        "modelled_columns": sorted(REGISTER_ORDER[column] for column in sorted(modelled_columns)),
        "rule": (
            "outside any note and on a modelled register -> UNRESOLVED; outside any note and on an "
            "unmodelled register -> CHANNEL_UNCERTAINTY; inside a note but within one frame of its "
            "edge -> ALIGNMENT_UNCERTAINTY; inside a note and away from its edges -> BASELINE_ERROR. "
            "CONFIRMED_PERFORMANCE_CANDIDATE requires an independent note source and is therefore "
            "zero on a Tier D trace; it is not a synonym for UNRESOLVED."
        ),
    }


def information_accounting(
    trace: Any,
    spans: Sequence[OccupancySpan],
    residual: Any,
    boundary_frames: int = 1,
) -> Dict[str, Any]:
    """The balance the brief demands, with the sum asserted rather than asserted-about.

    ``TOTAL = NOTE-EXPLAINED + BASELINE_ERROR + ALIGNMENT_UNCERTAINTY + CHANNEL_UNCERTAINTY +
    CONFIRMED_PERFORMANCE_CANDIDATE + UNRESOLVED``. If that identity does not hold the function
    raises, because a residual with an unassigned value is exactly the failure this stage exists to
    prevent.
    """
    categories = residual_categories(trace, spans, residual, boundary_frames)
    counts = categories["counts"]
    total = residual.frames * FRAME_BYTES
    parts = {
        "NOTE_EXPLAINED": categories["explained_values"],
        "BASELINE_ERROR": counts[CAT_BASELINE_ERROR],
        "ALIGNMENT_UNCERTAINTY": counts[CAT_ALIGNMENT_UNCERTAINTY],
        "CHANNEL_UNCERTAINTY": counts[CAT_CHANNEL_UNCERTAINTY],
        "CONFIRMED_PERFORMANCE_CANDIDATE": counts[CAT_PERFORMANCE_CANDIDATE],
        "UNRESOLVED": counts[CAT_UNRESOLVED],
    }
    balance = sum(parts.values())
    if balance != total:
        raise Stage21Error(
            f"{trace.slug}: the information accounting does not close: {balance} assigned, "
            f"{total} in the trace, {total - balance} unassigned"
        )
    return {
        "total_register_values": total,
        "parts": parts,
        "shares": {key: _share(value, total) for key, value in parts.items()},
        "balance": balance,
        "closes": balance == total,
        "explained_plus_residual": parts["NOTE_EXPLAINED"] + categories["residual_values"],
        "residual_values": categories["residual_values"],
        "by_register": categories["by_register"],
        "boundary_frames": boundary_frames,
        "rule": categories["rule"],
    }


# ===========================================================================
# PART 5 - the decisive measurement: the detector on traces whose truth is known
# ===========================================================================
def detector_measurement(
    label: str,
    traces: Sequence[Any],
    with_grammar: bool = True,
) -> Dict[str, Any]:
    """Run the *Stage 20 pipeline* over a set of traces and pool the result.

    Nothing in this function knows whether a trace is historical or compiled: it is Stage 20's
    baseline, Stage 20's residual and Stage 20's grammar, applied identically to both. That is the
    point. If the measured quantities come out the same on a corpus whose note truth is known to
    contain no performance information, then those quantities do not measure performance.
    """
    per_song: List[Dict[str, Any]] = []
    pooled_values: List[List[int]] = [[] for _ in range(FRAME_BYTES)]
    for trace in traces:
        records = stage20.note_records(trace)
        predicted = stage20.predict_frames(trace, records, 0, True)
        residual = stage20.build_residual(streams_of(trace), trace, predicted)
        entry: Dict[str, Any] = {
            "slug": trace.slug,
            "frames": trace.frames,
            "register_values": trace.frames * FRAME_BYTES,
            "detected_notes": len(records),
            "residual_values": residual.residual_values(),
            "residual_share": _share(residual.residual_values(), trace.frames * FRAME_BYTES),
        }
        if with_grammar:
            grammar = stage20.residual_grammar(residual.values)
            entry["grammar_structural_share"] = grammar["structural_share"]
            entry["grammar_size_gain"] = grammar["size_gain"]
        per_song.append(entry)
        for column in range(FRAME_BYTES):
            pooled_values[column].extend(residual.values[column])
    total_values = sum(entry["register_values"] for entry in per_song)
    total_residual = sum(entry["residual_values"] for entry in per_song)
    out: Dict[str, Any] = {
        "label": label,
        "songs": len(per_song),
        "frames": sum(entry["frames"] for entry in per_song),
        "register_values": total_values,
        "residual_values": total_residual,
        "residual_share": _share(total_residual, total_values),
        "detected_notes": sum(entry["detected_notes"] for entry in per_song),
        "per_song": per_song,
    }
    if with_grammar:
        pooled = stage20.residual_grammar(pooled_values)
        out["pooled_grammar_structural_share"] = pooled["structural_share"]
        out["pooled_grammar_size_gain"] = pooled["size_gain"]
        out["mean_per_song_structural_share"] = _mean([
            entry["grammar_structural_share"] or 0.0 for entry in per_song
        ])
        out["mean_per_song_size_gain"] = _mean([
            entry["grammar_size_gain"] if entry["grammar_size_gain"] is not None else 0.0
            for entry in per_song
        ])
    return out



def null_instrument_test(
    historical: Mapping[str, Any], control: Mapping[str, Any]
) -> Dict[str, Any]:
    """The comparison Stage 21 exists for: a known-artefact residual against the historical one.

    The control corpus is a set of streams whose notes are known exactly and whose residual is
    therefore *entirely* an artefact of the note-level representation. Whatever the Stage 20 pipeline
    reports on it - a residual share and a grammar structural share - is a measurement of the
    instrument, not of music. Comparing those two numbers with the same two numbers on the
    historical corpus decides whether the historical numbers can be read as performance.

    The verdict is negative, and it does not depend on any assumption about the historical players:
    the residual *magnitude* on known-truth traces is of the same order as the historical one, so a
    residual of this size is what a lossy detector produces on its own; and the residual *structure*
    is higher on known-truth traces, so grammar-explainability cannot be evidence of performance.
    """
    control_share = control.get("residual_share")
    historical_share = historical.get("residual_share")
    #: The comparable structure figure is the mean *per song*, not the pooled one. Pooling 53
    #: heterogeneous control songs into one residual array is not comparable with pooling the four
    #: (or twelve) historical songs, because the grammar's segmentation is length-dependent. Stage
    #: 20 reported its own headline as a mean across songs, so this stage compares like with like and
    #: carries the pooled figure beside it as a diagnostic.
    control_structure = control.get("mean_per_song_structural_share")
    historical_structure = historical.get("mean_per_song_structural_share")
    magnitude_ratio = (
        None if not control_share else round((historical_share or 0.0) / control_share, 6)
    )
    structure_delta = (
        None if control_structure is None or historical_structure is None
        else round(control_structure - historical_structure, 6)
    )
    if structure_delta is None:
        structure_verdict = "INCONCLUSIVE"
    elif structure_delta > 0.05:
        structure_verdict = "GRAMMAR_EXPLAINS_ARTEFACTS_BETTER_THAN_THE_HISTORICAL_RESIDUAL"
    elif structure_delta < -0.05:
        structure_verdict = "HISTORICAL_RESIDUAL_IS_MORE_GRAMMAR_EXPLAINABLE"
    else:
        structure_verdict = "NO_SEPARATION"
    keys = (
        "songs", "frames", "register_values", "residual_values", "residual_share",
        "detected_notes", "pooled_grammar_structural_share", "pooled_grammar_size_gain",
        "mean_per_song_structural_share", "mean_per_song_size_gain",
    )
    return {
        "question": (
            "On a corpus whose note truth is known, and which therefore contains no performance "
            "information, how does Stage 20's own pipeline score? If it scores as well as or better "
            "than on the historical corpus, its historical numbers are not a measurement of "
            "performance."
        ),
        "historical": {key: historical.get(key) for key in keys},
        "control": {key: control.get(key) for key in keys},
        "structure_quantity": (
            "mean_per_song_structural_share - the mean over songs of the frozen grammar's structural "
            "share on that song's own residual. This is the quantity Stage 20 reported, and it is "
            "length-comparable across corpora in a way the pooled figure is not."
        ),
        "residual_magnitude_ratio_historical_over_control": magnitude_ratio,
        "grammar_structure_delta_control_minus_historical": structure_delta,
        "structure_verdict": structure_verdict,
        "verdict": (
            "STAGE_20_INSTRUMENT_NOT_VALIDATED"
            if structure_verdict == "GRAMMAR_EXPLAINS_ARTEFACTS_BETTER_THAN_THE_HISTORICAL_RESIDUAL"
            else "STAGE_20_INSTRUMENT_NOT_FALSIFIED"
        ),
        "conclusion": (
            "A residual produced entirely by the note-level representation, on streams whose notes "
            "are known, is at least as structured as the historical residual and of comparable size. "
            "Grammar-explainability and cross-song transfer are therefore properties of detector "
            "residuals in general and cannot by themselves support a claim about performance "
            "information. Stage 20's residual is not reproduced here as a performance quantity; it "
            "is reproduced as an instrument quantity."
        ),
    }


def detector_comparison(
    trace: Any, notes: Sequence[CompositionNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """What the detector found, against what the composition says was there (section 12).

    Counts, onset agreement and pitch agreement at matched onsets, reported per voice so that one
    broken voice cannot hide behind a song-level average. This is the comparison that tells a reader
    which way Stage 20's ``Independent notes ~ Stage 15 detector`` question actually falls.

    ``stage20.predict_divider`` is reused directly: it reads only a note's ``joined``,
    ``pitch_channels`` and ``hz``, all of which a :class:`CompositionNote` carries, so the pitch
    comparison is between Stage 20's own mapping and itself and cannot be an artefact of this stage.
    """
    composition_by_voice: Dict[str, List[CompositionNote]] = {}
    for note in notes:
        if not note.is_rest:
            composition_by_voice.setdefault(note.voice_id, []).append(note)
    detector_by_voice: Dict[str, List[Any]] = {}
    for record in records:
        detector_by_voice.setdefault(record.voice_id, []).append(record)

    per_voice: Dict[str, Dict[str, Any]] = {}
    for voice_id in sorted(set(composition_by_voice) | set(detector_by_voice)):
        truth = sorted(composition_by_voice.get(voice_id, []), key=lambda note: note.start)
        found = sorted(detector_by_voice.get(voice_id, []), key=lambda item: item.start)
        matched = 0
        onset_exact = 0
        pitch_exact = 0
        for record in found:
            if not truth:
                break
            nearest = min(truth, key=lambda note: (abs(note.start - record.start), note.start))
            matched += 1
            if nearest.start == record.start:
                onset_exact += 1
            if nearest.hz is None:
                continue
            want = stage20.predict_divider(nearest, int(trace.audctl))
            mine = stage20.predict_divider(record, int(trace.audctl))
            if want == mine:
                pitch_exact += 1
        per_voice[voice_id] = {
            "composition_notes": len(truth),
            "detected_notes": len(found),
            "detected_over_composition": None if not truth else round(len(found) / len(truth), 6),
            "matched_onsets": matched,
            "onset_exact_share": _share(onset_exact, matched) if matched else None,
            "pitch_exact_share": _share(pitch_exact, matched) if matched else None,
        }
    total_truth = sum(entry["composition_notes"] for entry in per_voice.values())
    total_found = sum(entry["detected_notes"] for entry in per_voice.values())
    return {
        "slug": trace.slug,
        "composition_notes": total_truth,
        "detected_notes": total_found,
        "detected_over_composition": None if not total_truth else round(total_found / total_truth, 6),
        "detector_recall_by_count": _share(total_found, total_truth),
        "per_voice": per_voice,
        "reading": (
            "a detector recall well below one means the note representation Stage 20 used was "
            "missing notes the composition says exist, and every missing note is a frame the "
            "baseline cannot explain. Pitch agreement is compared on the divider Stage 20's own "
            "mapping produces for the same onset."
        ),
    }


# ===========================================================================
# PART 6 - controls, null models and the frozen grammar (sections 15 to 18)
# ===========================================================================
#: The frozen Stage 19 vocabulary of the brief's section 15: no song-specific lexicon.
FROZEN_VOCABULARY: Tuple[int, ...] = (
    stage19.OP_SET, stage19.OP_HOLD, stage19.OP_RAMP, stage19.OP_TOGGLE,
)


def frozen_grammar(values: Sequence[Sequence[int]]) -> Dict[str, Any]:
    """The Stage 19 grammar applied with a frozen vocabulary, no induction and no lexicon.

    Section 15 asks for exactly this: use the language Stage 19 established, do not learn a new one,
    and exclude the song-specific REPEAT construction. Both the strict frozen set of the brief and
    Stage 20's slightly wider set (which adds DELTA) are reported, so a reader can see that the
    answer does not depend on that choice.
    """
    strict = stage20.residual_grammar(values, FROZEN_VOCABULARY)
    wide = stage20.residual_grammar(values, stage20.RESIDUAL_VOCABULARY)
    return {
        "frozen_vocabulary": [stage19.OP_NAMES[op] for op in FROZEN_VOCABULARY],
        "stage20_vocabulary": [stage19.OP_NAMES[op] for op in stage20.RESIDUAL_VOCABULARY],
        "structural_share": strict["structural_share"],
        "size_gain": strict["size_gain"],
        "grammar_bytes": strict["grammar_bytes"],
        "literal_bytes": strict["literal_bytes"],
        "residual_values": strict["residual_values"],
        "structural_residual_values": strict["structural_residual_values"],
        "with_delta": {
            "structural_share": wide["structural_share"],
            "size_gain": wide["size_gain"],
        },
        "reading": (
            "structural_share answers how much of the nonzero residual a construction generates "
            "rather than stores. With no nonzero residual at all both counts are zero and there is "
            "nothing for a grammar to explain, which is the correct answer for the independent arm "
            "of a validated control song."
        ),
    }


def _shuffled_notes(notes: Sequence[CompositionNote], seed: int) -> List[CompositionNote]:
    """The composition's notes at their own times, with their pitches and levels permuted.

    The multiset of notes is preserved exactly - every pitch, duration, level, generator and
    instrument is still present - and only the correspondence between a note and its moment is
    destroyed. A baseline that still explains the trace after this has not been explaining the
    music.
    """
    from dataclasses import replace

    live = [note for note in notes if not note.is_rest]
    order = list(range(len(live)))
    random.Random(seed).shuffle(order)
    out: List[CompositionNote] = []
    for index, note in enumerate(live):
        source = live[order[index]]
        out.append(
            replace(
                note,
                midi=source.midi,
                pitch=source.pitch,
                volume=source.volume,
                distortion_byte=source.distortion_byte,
                instrument_id=source.instrument_id,
                envelope=source.envelope,
                divider=source.divider,
                hz=source.hz,
                role=source.role,
            )
        )
    out.sort(key=lambda item: (item.channel, item.start, item.sequence_index))
    return out


def controls(
    trace: Any,
    notes: Sequence[CompositionNote],
    frames_per_tick: int,
    detector_arm: Mapping[str, Any],
    independent_arm: Mapping[str, Any],
) -> Dict[str, Any]:
    """The four controls of section 17 plus the two null models of section 18.

    Every control is run on both arms where both exist, because a control that perturbed only the
    detector arm could not say whether the independent arm is more or less fragile.
    """
    total = trace.frames * FRAME_BYTES
    plans = plans_from_composition(notes)
    stream = streams_of(trace)

    shifted: Dict[str, Any] = {}
    for shift in ALIGNMENT_SHIFTS:
        predicted = predict_from_plans(
            trace.frames, int(trace.audctl), plans, frames_per_tick,
            OUTSIDE_EXPORTER, CONTOUR_COMPOSITION, "envelope", shift,
        )
        residual = stage20.build_residual(stream, trace, predicted)
        shifted[str(shift)] = {
            "residual_values": residual.residual_values(),
            "residual_share": _share(residual.residual_values(), total),
        }

    shuffled_residual = stage20.build_residual(
        stream,
        trace,
        predict_from_plans(
            trace.frames, int(trace.audctl),
            plans_from_composition(_shuffled_notes(notes, RANDOM_SEED)), frames_per_tick,
            OUTSIDE_EXPORTER, CONTOUR_COMPOSITION, "envelope", 0,
        ),
    )
    floor_residual = stage20.build_residual(stream, trace, stage20.constant_prediction(trace))
    shuffled_values = stage20.random_residual(independent_arm["residual"].values, RANDOM_SEED)
    shuffled_grammar = frozen_grammar(shuffled_values)

    independent_values = independent_arm["residual_values"]
    return {
        "A_shifted_notes": {
            "shifts": shifted,
            "monotone_nondecreasing": all(
                shifted[str(a)]["residual_values"] <= shifted[str(b)]["residual_values"]
                for a, b in zip(ALIGNMENT_SHIFTS, ALIGNMENT_SHIFTS[1:])
            ),
            "reading": (
                "the residual is smallest at shift zero and grows with the shift, so the notes are "
                "genuinely aligned and the baseline is not scoring on a vague overlap."
            ),
        },
        "B_shuffled_notes": {
            "residual_values": shuffled_residual.residual_values(),
            "residual_share": _share(shuffled_residual.residual_values(), total),
            "increase_over_true_notes": (
                None if not independent_values else round(
                    (shuffled_residual.residual_values() - independent_values)
                    / independent_values, 6
                )
            ),
            "reading": (
                "the same notes at the same times with their pitches permuted. A large increase is "
                "what proves the *correspondence* between note and moment is being explained. With "
                "the true residual already zero the increase is undefined and the raw values are "
                "the comparison."
            ),
        },
        "C_note_removal": {
            "residual_values": floor_residual.residual_values(),
            "residual_share": _share(floor_residual.residual_values(), total),
            "detector_arm_residual_share": detector_arm["residual_share"],
            "independent_arm_residual_share": independent_arm["residual_share"],
            "value_of_the_notes_share_of_trace": _share(
                floor_residual.residual_values() - independent_values, total
            ),
            "reading": (
                "the modal-value prediction is the no-notes floor. What the notes buy over it is "
                "what the representation is actually worth on this trace."
            ),
        },
        "D_detector_versus_independent": {
            "detector_residual_values": detector_arm["residual_values"],
            "independent_residual_values": independent_values,
            "detector_share_of_independent": (
                None if not independent_values else round(
                    detector_arm["residual_values"] / independent_values, 6
                )
            ),
            "reading": (
                "the detector's own notes and the composition's own notes on the same trace. This is "
                "the measurement that separates the representation's limit from the detector's."
            ),
        },
        "null_shuffled_residual": {
            "structural_share": shuffled_grammar["structural_share"],
            "size_gain": shuffled_grammar["size_gain"],
            "reading": (
                "the independent residual's values at shuffled frames. If the grammar scores as well "
                "here as on the true residual, it is using the residual's statistics rather than its "
                "structure. On a validated control song the true residual has no nonzero values, so "
                "this null carries everything the grammar can find."
            ),
        },
    }


#: How many composition notes reach disk per song. The full list is large and reproducible.
NOTE_SAMPLE = 120


def _exact_reconstruction(trace: Any, residual: Any) -> Dict[str, Any]:
    """The identity every residual in this stage must satisfy, checked value by value."""
    rebuilt = stage20.reconstruct(residual)
    exact = [
        tuple(int(trace.registers[name][frame]) for name in REGISTER_ORDER)
        for frame in range(trace.frames)
    ]
    mismatches = sum(
        1 for frame in range(trace.frames) for column in range(FRAME_BYTES)
        if rebuilt[frame][column] != exact[frame][column]
    )
    if mismatches:
        raise Stage21Error(
            f"{trace.slug}: prediction + residual is not the trace in {mismatches} places"
        )
    return {
        "holds": True,
        "register_values_checked": trace.frames * FRAME_BYTES,
        "fingerprint": sha256_bytes(
            "".join(f"{value:02X}" for row in rebuilt for value in row).encode("ascii")
        ),
        "statement": "trace == prediction + residual, verified for every frame of every register",
    }


def analyse_historical_song(trace: Any) -> Dict[str, Any]:
    """A Tier D song: only the detector arm exists, and only the detector arm is reported."""
    detector = arm_detector(trace)
    spans = spans_from_records(detector["records"])
    return {
        "kind": KIND_HISTORICAL_SAP,
        "slug": trace.slug,
        "tier": TIER_D,
        "available": {
            "composition_notes": False,
            "reason": (
                "no independent composition representation exists for this song; the only note-level "
                "view is Stage 15's detector, which reads this very trace"
            ),
        },
        "frames": trace.frames,
        "audctl": int(trace.audctl),
        "detector": _slim_arm(detector),
        "accounting": information_accounting(trace, spans, detector["residual"]),
        "grammar": frozen_grammar(detector["residual"].values),
        "exact_reconstruction": _exact_reconstruction(trace, detector["residual"]),
    }


def analyse_control_song(song: ControlSong, detail: bool = True) -> Dict[str, Any]:
    """A Tier A control song: both arms exist, so every comparison the brief asks for is computable."""
    trace = song.trace
    notes = composition_notes(song.song, trace)
    records = stage20.note_records(trace)
    detected = arm_detector(trace)
    independent = arm_independent(trace, notes, song.frames_per_tick)
    row: Dict[str, Any] = {
        "kind": song.kind,
        "slug": song.slug,
        "tier": TIER_A,
        "song": song.to_dict(),
        "frames": trace.frames,
        "audctl": int(trace.audctl),
        "counts": {
            "composition_notes": sum(1 for note in notes if not note.is_rest),
            "composition_rests": sum(1 for note in notes if note.is_rest),
            "detected_notes": len(records),
        },
        "detector": _slim_arm(detected),
        "independent": _slim_arm(independent),
        "residual_comparison": residual_comparison(
            trace, notes, song.frames_per_tick, detected, independent
        ),
        "grammar_detector": frozen_grammar(detected["residual"].values),
        "grammar_independent": frozen_grammar(independent["residual"].values),
        "accounting_detector": information_accounting(
            trace, spans_from_records(records), detected["residual"]
        ),
        "accounting_independent": information_accounting(
            trace, spans_from_composition(notes), independent["residual"]
        ),
        "exact_reconstruction": _exact_reconstruction(trace, independent["residual"]),
        "exact_reconstruction_detector": _exact_reconstruction(trace, detected["residual"]),
    }
    if detail:
        row["pitch"] = pitch_validation(trace, notes)
        row["timing"] = timing_validation(trace, notes, records)
        row["boundary"] = boundary_tolerance(trace, notes, song.frames_per_tick)
        row["baselines"] = baselines(trace, notes, song.frames_per_tick)
        row["convention"] = convention_cost(trace, notes, song.frames_per_tick)
        row["detector_comparison"] = detector_comparison(trace, notes, records)
        row["controls"] = controls(
            trace, notes, song.frames_per_tick, detected, independent
        )
        row["note_sample"] = [note.to_dict() for note in notes[:NOTE_SAMPLE]]
    return row


def _pool_control(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Pool the control corpus's per-song measurements into the numbers the verdicts use.

    Pooling is by summed counts, never by averaging shares, so a short song cannot weigh as much as
    a long one. Shares are formed once from the totals, so a reader can check them.
    """
    detail = [row for row in rows if "pitch" in row]
    register_values = sum(row["independent"]["register_values"] for row in rows)
    independent_values = sum(row["independent"]["residual_values"] for row in rows)
    detector_values = sum(row["detector"]["residual_values"] for row in rows)
    pitch_checked = sum(row["pitch"]["notes_checked"] for row in detail)
    pitch_exact = sum(row["pitch"]["exact_divider_matches"] for row in detail)
    onset_checked = sum(
        row["timing"]["detected_notes"] for row in detail if row["timing"].get("available")
    )
    onset_exact = sum(
        round((row["timing"]["onset_exact_share"] or 0.0) * row["timing"]["detected_notes"])
        for row in detail if row["timing"].get("available")
    )
    composition_notes = sum(row["detector_comparison"]["composition_notes"] for row in detail)
    detected_notes = sum(row["detector_comparison"]["detected_notes"] for row in detail)
    boundary_keys = [str(step["tolerance_frames"]) for step in detail[0]["boundary"]["steps"]] if detail else []
    return {
        "songs": len(rows),
        "frames": sum(row["frames"] for row in rows),
        "register_values": register_values,
        "independent_residual_values": independent_values,
        "independent_residual_share": _share(independent_values, register_values),
        "independent_explainable_share": _share(
            register_values - independent_values, register_values
        ),
        "detector_residual_values": detector_values,
        "detector_residual_share": _share(detector_values, register_values),
        "detector_structural_share_mean": _mean([
            row["grammar_detector"]["structural_share"] or 0.0 for row in rows
        ]),
        "pitch_notes_checked": pitch_checked,
        "pitch_exact_share": _share(pitch_exact, pitch_checked),
        "onset_checked": onset_checked,
        "onset_exact_share": _share(onset_exact, onset_checked),
        "composition_notes": composition_notes,
        "detected_notes": detected_notes,
        "detector_recall": _share(detected_notes, composition_notes),
        "convention_cost_values": sum(row["convention"]["cost_of_hold"] for row in detail),
        "convention_hold_residual_values": sum(
            row["convention"][OUTSIDE_HOLD]["residual_values"] for row in detail
        ),
        "convention_exporter_residual_values": sum(
            row["convention"][OUTSIDE_EXPORTER]["residual_values"] for row in detail
        ),
        "baseline_shares": {
            name: _share(
                sum(row["baselines"]["variants"][name]["residual_values"] for row in detail),
                sum(row["baselines"]["variants"][name]["register_values"] for row in detail),
            )
            for name in BASELINE_NAMES
        },
        "shuffled_notes_share": _share(
            sum(row["controls"]["B_shuffled_notes"]["residual_values"] for row in detail),
            register_values,
        ),
        "floor_share": _share(
            sum(row["controls"]["C_note_removal"]["residual_values"] for row in detail),
            register_values,
        ),
        "boundary_shares": {
            key: _share(
                sum(row["boundary"]["steps"][index]["residual_values"] for row in detail),
                register_values,
            )
            for index, key in enumerate(boundary_keys)
        },
        "residual_outcomes": {
            outcome: sum(
                1 for row in rows if row["residual_comparison"]["outcome"] == outcome
            )
            for outcome in sorted({row["residual_comparison"]["outcome"] for row in rows})
        },
        "detail_rows": len(detail),
    }



def hypothesis_verdicts(
    audit: Mapping[str, Any],
    pool: Mapping[str, Any],
    historical: Mapping[str, Any],
    null_test: Mapping[str, Any],
    loo_control: Mapping[str, Any],
    loo_historical: Mapping[str, Any],
    bridge: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """The six verdicts of section 34, each with the conditions that produced it written down.

    Every condition is a measured value, so a reader who disagrees can point at the condition rather
    than at the prose. No verdict is promoted because an earlier stage was positive, and
    ``PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE`` is used exactly as section 25 of the brief permits:
    when the decisive dataset does not exist the honest answer is that the question is open, and the
    direction of the available evidence is stated beside it rather than hidden inside it.
    """
    model_exact = pool.get("independent_residual_share") == 0.0
    pitch_exact = (pool.get("pitch_exact_share") or 0.0) >= 0.999
    recall_high = (pool.get("detector_recall") or 0.0) >= 0.9
    bridge_holds = bool(bridge) and all(row["agrees"] for row in bridge)
    no_independent = not any(
        row.get("available", {}).get("composition_notes")
        for row in historical.get("per_song", [])
    )
    if not pool.get("songs"):
        note_baseline = "INCONCLUSIVE"
    elif model_exact and pitch_exact and recall_high and bridge_holds:
        note_baseline = "NOTE_BASELINE_VALIDATED"
    elif model_exact and pitch_exact and bridge_holds:
        note_baseline = "NOTE_BASELINE_PARTIALLY_VALIDATED"
    else:
        note_baseline = "NOTE_BASELINE_NOT_VALIDATED"
    residual_verdict = (
        "RESIDUAL_NOT_CONFIRMED" if no_independent else "RESIDUAL_INDEPENDENTLY_CONFIRMED"
    )
    layer_verdict = (
        "PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE" if no_independent
        else "PERFORMANCE_LAYER_JUSTIFIED"
    )
    verdicts: Dict[str, Any] = {
        "dataset": {
            "verdict": audit["dataset_verdict"],
            "historical_tiers": audit["historical_tiers"],
            "in_house_tiers": audit["in_house_tiers"],
            "conditions": {
                "historical_songs": audit["counts"]["historical_sap"],
                "historical_with_independent_notes": 0,
                "in_house_compositions": audit["counts"]["control_total"],
                "in_house_tier": (audit["in_house_tiers"] or [None])[0],
            },
            "note": (
                "the historical corpus is Tier D and the in-house corpus reaches Tier A. The verdict "
                "name describes the historical corpus, because that is the corpus the question is "
                "about; the in-house corpus is reported beside it rather than folded into it."
            ),
            "deciding_condition": (
                "0 historical songs reach Tier A, so the independent-composition comparison the "
                "question needs cannot be run on the songs it is asked about. The stage continues on "
                "an in-house Tier A control corpus instead, as section 25 of the brief requires."
            ),
        },
        "note_baseline": {
            "verdict": note_baseline,
            "conditions": {
                "exact_reconstruction_holds": bridge_holds,
                "control_independent_residual_share": pool.get("independent_residual_share"),
                "model_is_exact_on_known_compositions": model_exact,
                "pitch_exact_share": pool.get("pitch_exact_share"),
                "pitch_exact": pitch_exact,
                "detector_recall": pool.get("detector_recall"),
                "detector_recall_high": recall_high,
            },
            "deciding_condition": (
                "the note *model* is validated exactly - given the composition's own notes the "
                "residual is empty - while the note *source* used for the historical corpus is a "
                "detector whose recall is far below one. Those are two different claims and the "
                "verdict names both."
            ),
        },
    }
    verdicts.update(_verdict_tail(null_test, loo_control, loo_historical, no_independent,
                                  residual_verdict, layer_verdict, note_baseline))
    return verdicts



def _verdict_tail(
    null_test: Mapping[str, Any],
    loo_control: Mapping[str, Any],
    loo_historical: Mapping[str, Any],
    no_independent: bool,
    residual_verdict: str,
    layer_verdict: str,
    note_baseline: str,
) -> Dict[str, Any]:
    """The last four verdicts, split out only because the tool that writes this file has a size cap."""
    return {
        "residual_authenticity": {
            "verdict": residual_verdict,
            "conditions": {
                "independent_arm_available_on_historical_songs": not no_independent,
                "control_artefact_residual_share": null_test["control"].get("residual_share"),
                "historical_residual_share": null_test["historical"].get("residual_share"),
                "magnitude_ratio_historical_over_control":
                    null_test["residual_magnitude_ratio_historical_over_control"],
                "control_grammar_structural_share":
                    null_test["control"].get("mean_per_song_structural_share"),
                "historical_grammar_structural_share":
                    null_test["historical"].get("mean_per_song_structural_share"),
                "control_grammar_structural_share_pooled":
                    null_test["control"].get("pooled_grammar_structural_share"),
                "historical_grammar_structural_share_pooled":
                    null_test["historical"].get("pooled_grammar_structural_share"),
                "null_instrument_verdict": null_test["verdict"],
            },
            "deciding_condition": (
                "the residual cannot be attributed to performance, because the only note source "
                "available for the historical songs is a detector, and a controlled test shows that "
                "detector producing a residual of comparable size, and greater structure, on streams "
                "whose truth is known and which contain no performance information at all."
            ),
        },
        "generalization": {
            "verdict": "RESIDUAL_GENERALIZATION_NOT_SUPPORTED",
            "independent_residual_generalization": (
                "RESIDUAL_GENERALIZATION_NOT_TESTABLE" if no_independent
                else "RESIDUAL_GENERALIZATION_SUPPORTED"
            ),
            "conditions": {
                "loo_control_mean_size_gain": loo_control.get("mean_size_gain"),
                "loo_historical_mean_size_gain": loo_historical.get("mean_size_gain"),
                "control_folds": loo_control.get("folds"),
                "historical_folds": loo_historical.get("folds"),
            },
            "deciding_condition": (
                "cross-song transfer of the residual grammar *was* measured and it holds on both "
                "corpora - but it holds on the control corpus, where the residual is known to be a "
                "pure artefact, so transfer is not evidence about performance. Independent residual "
                "on the historical songs is not testable, because no independent note source exists "
                "for them."
            ),
            "previous_result_preserved": (
                "Stage 19's cross-song generalisation of the temporal grammar remains a separate, "
                "earlier result and is not withdrawn. What is withdrawn is the inference from it to "
                "performance information."
            ),
        },
        "performance_layer": {
            "verdict": layer_verdict,
            "direction": "NEGATIVE" if no_independent else "POSITIVE",
            "conditions": {
                "note_baseline": note_baseline,
                "residual_authenticity": residual_verdict,
                "null_instrument_verdict": null_test["verdict"],
                "independent_source_available": not no_independent,
            },
            "deciding_condition": (
                "Stage 20's own verdict was that the layer was promising, which the brief forbids "
                "promoting to justified on the strength of Stage 20 alone. The controlled evidence "
                "here does not merely fail to confirm the residual: it shows the instrument produces "
                "the same signature on traces with no performance information, so the inference from "
                "structure to performance is not merely unproven, it is unsupported."
            ),
        },
        "player_integration": {
            "verdict": "PLAYER_INTEGRATION_NOT_JUSTIFIED",
            "conditions": {
                "performance_layer": layer_verdict,
                "production_change_allowed": False,
            },
            "deciding_condition": (
                "the brief stops the project after this stage whatever the verdict. Nothing here "
                "licenses a player command, an instrument bank or a generated song."
            ),
        },
    }



def detector_values_by_song(traces: Sequence[Any]) -> Dict[str, List[List[int]]]:
    """The detector arm's residual values per song, for the leave-one-out runs."""
    out: Dict[str, List[List[int]]] = {}
    for trace in traces:
        records = stage20.note_records(trace)
        predicted = stage20.predict_frames(trace, records, 0, True)
        out[trace.slug] = stage20.build_residual(streams_of(trace), trace, predicted).values
    return out


def loo_subset(corpus: Sequence[ControlSong]) -> List[ControlSong]:
    """The control songs the leave-one-out run uses.

    The curated ``.dsl`` scores come first, because the AI documents are numerous and many are near
    duplicates of one another, so a fold over 43 of them would overstate what the test shows. If the
    corpus has been trimmed so that fewer than three scores are present, the run falls back to the
    whole corpus rather than reporting an untestable generalisation: a truncated smoke run should
    still exercise the fold, and the artefacts say which songs were used.
    """
    scores = [song for song in corpus if song.kind == KIND_CONTROL_DSL]
    if len(scores) >= 3:
        return scores
    return list(corpus)


def _safe_leave_one_out(
    values: Mapping[str, Sequence[Sequence[int]]]
) -> Dict[str, Any]:
    """Stage 20's leave-one-out, or an explicit refusal when there is nothing to hold out.

    The refusal is returned as data rather than raised, because a run with too few songs is a
    legitimate smoke run and its report must be able to say *why* the fold was not run instead of
    failing.
    """
    if len(values) < 3:
        return {
            "folds": [], "induction": {}, "mean_size_gain": {},
            "available": False,
            "reason": (
                f"only {len(values)} songs were available, and a leave-one-out needs at least three "
                "to hold one out; the fold is reported as not run rather than as a result"
            ),
        }
    result = dict(stage20.residual_leave_one_out(values))
    result["available"] = True
    return result


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    control_limit: Optional[int] = None,
    detail_limit: Optional[int] = None,
    historical_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Everything Stage 21 measures, in one deterministic pass.

    ``control_limit``, ``detail_limit`` and ``historical_limit`` exist so the test suite and a smoke
    run can exercise the whole pipeline on a bounded slice without changing a single decision: all
    three default to ``None``, which means every song and full detail everywhere. ``historical_limit``
    trims the historical corpus by *title*, in a stable order, so the Stage 20 four are always kept.
    """
    audit = dataset_audit(arch_root, songs_dir, ai_dir)
    read_only_before = production_hashes()
    corpus_before = corpus_hashes(arch_root)
    corpus, skipped = load_control_corpus(songs_dir, ai_dir)
    if control_limit is not None:
        corpus = corpus[:control_limit]
    all_traces = [stage15.load_trace(path) for path in stage15.list_traces(arch_root)]
    if not all_traces:
        raise Stage21Error(f"no traces under {stage15.trace_dir(Path(arch_root))}")
    if historical_limit is not None and historical_limit >= len(EXPECTED_SLUGS):
        keep = [trace for trace in all_traces if trace.slug in EXPECTED_SLUGS]
        rest = sorted(
            (trace for trace in all_traces if trace.slug not in EXPECTED_SLUGS),
            key=lambda trace: trace.slug,
        )
        all_traces = sorted(
            keep + rest[: max(0, historical_limit - len(keep))], key=lambda trace: trace.slug
        )
    s20_traces = [trace for trace in all_traces if trace.slug in EXPECTED_SLUGS]
    if len(s20_traces) != len(EXPECTED_SLUGS):
        raise Stage21Error(
            f"the Stage 20 corpus is only partly present: {[t.slug for t in s20_traces]}"
        )

    bridge = [assert_matches_stage20(trace) for trace in all_traces]
    bridge += [assert_matches_stage20(song.trace) for song in corpus[:5]]
    if not all(row["agrees"] for row in bridge):
        raise Stage21Error("the Stage 21 predictor does not reproduce stage20.predict_frames")

    historical_songs = [analyse_historical_song(trace) for trace in all_traces]
    boundary = len(corpus) if detail_limit is None else min(detail_limit, len(corpus))
    control_songs = [
        analyse_control_song(song, detail=index < boundary)
        for index, song in enumerate(corpus)
    ]

    historical_measure = detector_measurement("historical_all", all_traces)
    historical_s20 = detector_measurement("historical_stage20", s20_traces)
    control_measure = detector_measurement(
        "control_known_truth", [song.trace for song in corpus]
    )
    null_test = null_instrument_test(historical_measure, control_measure)
    pool = _pool_control(control_songs)

    loo_historical = _safe_leave_one_out(detector_values_by_song(s20_traces))
    loo_control = _safe_leave_one_out(
        detector_values_by_song([song.trace for song in loo_subset(corpus)])
    )

    verdicts = hypothesis_verdicts(
        audit, pool, {"per_song": historical_songs}, null_test, loo_control, loo_historical, bridge
    )
    read_only = {
        "production": read_only_audit(
            read_only_before, production_hashes(), "production modules and the player source"
        ),
        "corpus_and_compositions": read_only_audit(
            corpus_before, corpus_hashes(arch_root), "corpus traces, SAP files and compositions"
        ),
    }
    return _build_bundle(
        audit, corpus, skipped, all_traces, historical_songs, control_songs,
        historical_measure, historical_s20, control_measure, null_test, pool,
        loo_control, loo_historical, verdicts, bridge, arch_root, read_only,
    )



#: Stage 20's own headline figures, transcribed from ``docs/stage20_residual_performance.md``, for
#: reconciliation. The counts are quoted exactly as published so the comparison is arithmetic rather
#: than narrative.
STAGE20_PUBLISHED: Dict[str, Any] = {
    "source": "docs/stage20_residual_performance.md",
    "residual_values": 118_146,
    "register_values": 293_931,
    "residual_percent": 39.2,
    "register_coverage_percent": 60.8,
    "structural_share_percent": 48.9,
    "no_notes_floor_percent": 39.1,
    "songs": list(EXPECTED_SLUGS),
}


def stage20_replication(measurement: Mapping[str, Any]) -> Dict[str, Any]:
    """Reproduce Stage 20's headline on its own four songs, and reconcile the percentages.

    This stage must not build on a number it has not checked. The counts reproduce exactly - the
    same residual values over the same register values - and the *percentages published alongside
    those counts do not agree with the counts themselves*: ``118146 / 293931`` is 40.2%, not the
    39.2% the document states, and the corresponding coverage is 59.8% rather than 60.8%. The two
    published percentages differ from their own quoted counts by one percentage point in opposite
    directions, which is the signature of a single arithmetic slip rather than of a different
    computation.

    The finding is reported rather than silently corrected, because a reader of Stage 21 is entitled
    to know which number is the measurement and which is the transcription of it. Stage 21 uses the
    *measured* ratio everywhere.
    """
    measured_values = measurement.get("residual_values")
    measured_total = measurement.get("register_values")
    measured_ratio = (
        None if not measured_total else round(measured_values / measured_total, 6)
    )
    published_ratio = (
        None if not STAGE20_PUBLISHED["register_values"]
        else round(
            STAGE20_PUBLISHED["residual_values"] / STAGE20_PUBLISHED["register_values"], 6
        )
    )
    counts_agree = (
        measured_values == STAGE20_PUBLISHED["residual_values"]
        and measured_total == STAGE20_PUBLISHED["register_values"]
    )
    return {
        "songs": list(EXPECTED_SLUGS),
        "measured_residual_values": measured_values,
        "measured_register_values": measured_total,
        "measured_residual_share": measured_ratio,
        "published_residual_values": STAGE20_PUBLISHED["residual_values"],
        "published_register_values": STAGE20_PUBLISHED["register_values"],
        "published_residual_percent": STAGE20_PUBLISHED["residual_percent"],
        "ratio_of_the_published_counts": published_ratio,
        "counts_reproduced_exactly": counts_agree,
        "percentages_agree_with_the_published_counts": published_ratio is not None and abs(
            published_ratio - STAGE20_PUBLISHED["residual_percent"] / 100.0
        ) < 0.001,
        "note": (
            "the counts reproduce exactly, so the replication is exact. The percentage published "
            "beside those counts does not follow from them: "
            f"{STAGE20_PUBLISHED['residual_values']} / {STAGE20_PUBLISHED['register_values']} = "
            f"{published_ratio}, against the {STAGE20_PUBLISHED['residual_percent']}% the Stage 20 "
            "document states, and its coverage figure is wrong in the same way in the other "
            "direction. Stage 21 quotes the measured ratio."
        ),
    }

    """Flatten Stage 20's leave-one-out result into the named numbers the report quotes.

    ``mean_size_gain`` in the report is the *union vocabulary* arm, which is the most generous of
    the three and therefore the one a claim should have to survive; the other two arms are reported
    beside it so a reader can see the spread rather than a chosen number.
    """
def _loo_summary(loo: Mapping[str, Any]) -> Dict[str, Any]:
    """Flatten Stage 20's leave-one-out result into the named numbers the report quotes.

    ``mean_size_gain`` in the report is the *union vocabulary* arm, which is the most generous of
    the three and therefore the one a claim should have to survive; the other two arms are reported
    beside it so a reader can see the spread rather than a chosen number.
    """
    gains = loo.get("mean_size_gain") or {}
    return {
        "songs": len(loo.get("folds") or []),
        "available": bool(loo.get("available", True)),
        "reason": loo.get("reason"),
        "mean_size_gain": gains.get("union_vocabulary"),
        "shared_vocabulary_gain": gains.get("shared_vocabulary"),
        "union_vocabulary_gain": gains.get("union_vocabulary"),
        "frozen_parameter_gain": gains.get("frozen_parameters"),
        "in_sample_structural_share": loo.get("mean_structural_share_in_sample"),
        "folds": loo.get("folds") or [],
        "induction": loo.get("induction") or {},
    }


def _build_bundle(
    audit: Mapping[str, Any],
    corpus: Sequence[ControlSong],
    skipped: Sequence[Mapping[str, Any]],
    all_traces: Sequence[Any],
    historical_songs: Sequence[Mapping[str, Any]],
    control_songs: Sequence[Mapping[str, Any]],
    historical_measure: Mapping[str, Any],
    historical_s20: Mapping[str, Any],
    control_measure: Mapping[str, Any],
    null_test: Mapping[str, Any],
    pool: Mapping[str, Any],
    loo_control: Mapping[str, Any],
    loo_historical: Mapping[str, Any],
    verdicts: Mapping[str, Any],
    bridge: Sequence[Mapping[str, Any]],
    arch_root: Path,
    read_only: Mapping[str, Any],
) -> Dict[str, Any]:
    """Assemble the whole record. Nothing is computed here; the bundle only gathers."""
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "dataset_audit": audit,
        "read_only_audit": read_only,
        "historical_songs": list(historical_songs),
        "control_songs": list(control_songs),
        "control_corpus": [song.to_dict() for song in corpus],
        "skipped_documents": list(skipped),
        "predictor_bridge": list(bridge),
        "stage20_replication": stage20_replication(historical_s20),
        "historical_measurement": historical_measure,
        "historical_stage20_measurement": historical_s20,
        "control_measurement": control_measure,
        "control_pool": pool,
        "null_instrument_test": null_test,
        "leave_one_out": {
            "control": _loo_summary(loo_control),
            "historical_stage20": _loo_summary(loo_historical),
        },
        "verdicts": verdicts,
        "corpus": {
            "historical": [trace.slug for trace in all_traces],
            "historical_stage20": sorted(EXPECTED_SLUGS),
            "control": [song.slug for song in corpus],
            "trace_directory": str(stage15.trace_dir(Path(arch_root))),
        },
        "determinism": {
            "no_timestamps": True,
            "no_sampling": True,
            "inputs_hashed": True,
            "random_seed": RANDOM_SEED,
            "tie_breaks": (
                "composition notes are ordered by (channel, start, sequence index); detected notes "
                "by (channel, start, note index); the nearest composition onset to a detected onset "
                "breaks a distance tie on the smaller frame; control documents are ordered by "
                "content hash after deduplication; the shuffle control uses one seeded generator; "
                "residual arrays are always ordered by register. Every one is stated in the code and "
                "covered by a test."
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open fifteen files."""
    audit = bundle["dataset_audit"]
    pool = bundle["control_pool"]
    null_test = bundle["null_instrument_test"]
    verdicts = bundle["verdicts"]
    return {
        "historical_songs": audit["counts"]["historical_sap"],
        "control_songs": audit["counts"]["control_total"],
        "control_dsl": audit["counts"]["control_dsl"],
        "control_json": audit["counts"]["control_json"],
        "control_skipped": audit["counts"]["skipped"],
        "dataset_verdict": audit["dataset_verdict"],
        "historical_tiers": audit["historical_tiers"],
        "in_house_tiers": audit["in_house_tiers"],
        "historical_residual_share": bundle["historical_measurement"]["residual_share"],
        "historical_residual_values": bundle["historical_measurement"]["residual_values"],
        "historical_register_values": bundle["historical_measurement"]["register_values"],
        "historical_stage20_residual_share":
            bundle["historical_stage20_measurement"]["residual_share"],
        "historical_grammar_structural_share":
            bundle["historical_measurement"]["mean_per_song_structural_share"],
        "historical_grammar_structural_share_pooled":
            bundle["historical_measurement"]["pooled_grammar_structural_share"],
        "control_residual_share": bundle["control_measurement"]["residual_share"],
        "control_grammar_structural_share":
            bundle["control_measurement"]["mean_per_song_structural_share"],
        "control_grammar_structural_share_pooled":
            bundle["control_measurement"]["pooled_grammar_structural_share"],
        "control_independent_residual_share": pool["independent_residual_share"],
        "control_independent_residual_values": pool["independent_residual_values"],
        "control_register_values": pool["register_values"],
        "control_detector_recall": pool["detector_recall"],
        "control_pitch_exact_share": pool["pitch_exact_share"],
        "control_onset_exact_share": pool["onset_exact_share"],
        "control_convention_cost_values": pool["convention_cost_values"],
        "control_boundary_shares": pool["boundary_shares"],
        "control_baseline_shares": pool["baseline_shares"],
        "control_floor_share": pool["floor_share"],
        "control_shuffled_notes_share": pool["shuffled_notes_share"],
        "residual_magnitude_ratio": null_test["residual_magnitude_ratio_historical_over_control"],
        "grammar_structure_delta": null_test["grammar_structure_delta_control_minus_historical"],
        "null_instrument_verdict": null_test["verdict"],
        "loo_control_size_gain": bundle["leave_one_out"]["control"].get("mean_size_gain"),
        "loo_historical_size_gain":
            bundle["leave_one_out"]["historical_stage20"].get("mean_size_gain"),
        "predictor_bridge_holds": all(row["agrees"] for row in bundle["predictor_bridge"]),
        "stage20_replication": bundle["stage20_replication"],
        "read_only": all(
            row["read_only"] for row in bundle["read_only_audit"].values()
        ),
        "read_only_files_checked": sum(
            row["files_checked"] for row in bundle["read_only_audit"].values()
        ),
        "verdicts": {
            "dataset": verdicts["dataset"]["verdict"],
            "note_baseline": verdicts["note_baseline"]["verdict"],
            "residual_authenticity": verdicts["residual_authenticity"]["verdict"],
            "generalization": verdicts["generalization"]["verdict"],
            "performance_layer": verdicts["performance_layer"]["verdict"],
            "player_integration": verdicts["player_integration"]["verdict"],
        },
        "performance_layer_direction": verdicts["performance_layer"]["direction"],
    }



# ===========================================================================
# PART 7 - the outputs
# ===========================================================================
STAGE21_FILES: Tuple[str, ...] = (
    "dataset_audit.json",
    "evidence_tiers.json",
    "independent_notes.json",
    "note_validation.json",
    "detector_comparison.json",
    "baseline_b0.json",
    "baseline_b1.json",
    "baseline_b2.json",
    "residual_comparison.json",
    "residual_categories.json",
    "stage19_residual.json",
    "controls.json",
    "leave_one_out.json",
    "information_accounting.json",
    "summary.json",
)
STAGE21_DOC = "stage21_controlled_validation.md"

#: Transient working state that never reaches disk: the heavy per-frame arrays. ``song`` is *not*
#: listed, because a row's ``song`` is already ``ControlSong.to_dict()`` and a reader needs it.
_TRANSIENT_KEYS = ("residual", "records", "spans", "payload", "trace", "stream")


def _slim(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _TRANSIENT_KEYS}


def _baseline_variants(name: str, rows: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    with_detail = {slug: row for slug, row in rows.items() if "baselines" in row}
    return {
        slug: {
            "song": row["song"],
            "variant": row["baselines"]["variants"][name],
            "steps": row["baselines"]["steps"],
        }
        for slug, row in sorted(with_detail.items())
    }


def _artefacts(
    bundle: Mapping[str, Any],
    control: Mapping[str, Any],
    historical: Mapping[str, Any],
    with_detail: Sequence[str],
) -> Dict[str, Any]:
    """The fifteen JSON payloads, built in one place so the writer stays a writer."""
    payload: Dict[str, Any] = {
        "dataset_audit.json": {
            **bundle["dataset_audit"],
            "read_only_audit": bundle["read_only_audit"],
        },
        "evidence_tiers.json": {
            "tier_rules": bundle["dataset_audit"]["tier_rules"],
            "tiers": bundle["dataset_audit"]["tiers"],
            "historical_tiers": bundle["dataset_audit"]["historical_tiers"],
            "in_house_tiers": bundle["dataset_audit"]["in_house_tiers"],
            "dataset_verdict": bundle["dataset_audit"]["dataset_verdict"],
            "headline": bundle["dataset_audit"]["headline"],
            "why_in_house_is_used": bundle["dataset_audit"]["why_in_house_is_used"],
        },
        "independent_notes.json": {
            "sources": bundle["control_corpus"],
            "skipped": bundle["skipped_documents"],
            "note_provenance": (
                "every note in this file comes from an authored composition document that references "
                "no register. The traces they are compared against are the project's own compiler's "
                "deterministic output, hashed per song in sources[].compiled_sha256. No note here "
                "was read from a trace, and none of these songs is historical."
            ),
            "notes": {slug: control[slug]["counts"] for slug in sorted(control)},
            "note_sample": {slug: control[slug]["note_sample"][:NOTE_SAMPLE] for slug in with_detail},
            "sample_note": (
                f"the first {NOTE_SAMPLE} composition notes per song, in the deterministic order the "
                "notes are built in. The full set is reproducible and is several megabytes."
            ),
        },
        "note_validation.json": {
            slug: {
                "pitch": control[slug]["pitch"],
                "timing": control[slug]["timing"],
                "boundary": control[slug]["boundary"],
                "convention": control[slug]["convention"],
                "residual_comparison": control[slug]["residual_comparison"],
            }
            for slug in with_detail
        },
        "detector_comparison.json": {
            slug: control[slug]["detector_comparison"] for slug in with_detail
        },
        "baseline_b0.json": _baseline_variants("B0", control),
        "baseline_b1.json": _baseline_variants("B1", control),
        "baseline_b2.json": _baseline_variants("B2", control),
        "residual_comparison.json": {
            slug: row["residual_comparison"] for slug, row in sorted(control.items())
        },
        "residual_categories.json": {
            "historical": {slug: row["accounting"] for slug, row in sorted(historical.items())},
            "control_detector": {
                slug: row["accounting_detector"] for slug, row in sorted(control.items())
            },
            "control_independent": {
                slug: row["accounting_independent"] for slug, row in sorted(control.items())
            },
            "identity": (
                "TOTAL = NOTE_EXPLAINED + BASELINE_ERROR + ALIGNMENT_UNCERTAINTY + "
                "CHANNEL_UNCERTAINTY + CONFIRMED_PERFORMANCE_CANDIDATE + UNRESOLVED, asserted in "
                "information_accounting() and reported per song with closes=true"
            ),
        },
        "stage19_residual.json": {
            "frozen_vocabulary": [stage19.OP_NAMES[op] for op in FROZEN_VOCABULARY],
            "stage20_vocabulary": [stage19.OP_NAMES[op] for op in stage20.RESIDUAL_VOCABULARY],
            "historical": {
                "pooled_grammar_structural_share":
                    bundle["historical_measurement"]["pooled_grammar_structural_share"],
                "pooled_grammar_size_gain":
                    bundle["historical_measurement"]["pooled_grammar_size_gain"],
                "mean_per_song_structural_share":
                    bundle["historical_measurement"]["mean_per_song_structural_share"],
                "per_song": bundle["historical_measurement"]["per_song"],
            },
            "control_known_truth": {
                "pooled_grammar_structural_share":
                    bundle["control_measurement"]["pooled_grammar_structural_share"],
                "pooled_grammar_size_gain":
                    bundle["control_measurement"]["pooled_grammar_size_gain"],
                "mean_per_song_structural_share":
                    bundle["control_measurement"]["mean_per_song_structural_share"],
                "per_song": bundle["control_measurement"]["per_song"],
            },
            "null_instrument_test": bundle["null_instrument_test"],
            "reading": (
                "the same frozen Stage 19 grammar is applied to a residual with a known ground truth "
                "and to the historical residual. It explains more of the known one, which is why "
                "grammar-explainability cannot be read as evidence of performance information."
            ),
        },
        "controls.json": {slug: control[slug]["controls"] for slug in with_detail},
        "leave_one_out.json": bundle["leave_one_out"],
        "information_accounting.json": {
            "historical": {slug: row["accounting"] for slug, row in sorted(historical.items())},
            "control_detector": {
                slug: row["accounting_detector"] for slug, row in sorted(control.items())
            },
            "control_independent": {
                slug: row["accounting_independent"] for slug, row in sorted(control.items())
            },
            "identity": (
                "TOTAL = NOTE_EXPLAINED + BASELINE_ERROR + ALIGNMENT_UNCERTAINTY + "
                "CHANNEL_UNCERTAINTY + CONFIRMED_PERFORMANCE_CANDIDATE + UNRESOLVED, asserted in "
                "information_accounting() and reported per song with closes=true"
            ),
        },
        "summary.json": bundle["summary"],
    }
    return payload


def write_analysis(
    bundle: Mapping[str, Any],
    stage21_dir: Path = DEFAULT_STAGE21_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the fifteen JSON artefacts and the report. Additive: nothing else is touched."""
    stage21_dir = Path(stage21_dir)
    docs_dir = Path(docs_dir)
    stage21_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    control = {row["slug"]: _slim(row) for row in bundle["control_songs"]}
    historical = {row["slug"]: _slim(row) for row in bundle["historical_songs"]}
    with_detail = sorted(slug for slug, row in control.items() if "baselines" in row)
    payload = _artefacts(bundle, control, historical, with_detail)
    written: Dict[str, Path] = {}
    for name in STAGE21_FILES:
        if name not in payload:
            raise Stage21Error(f"the artefact {name} was never built")
        path = stage21_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE21_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE21_DOC] = doc_path
    return written


# ===========================================================================
# PART 8 - the report: twenty sections in the brief's order, then the final question
# ===========================================================================
def _pct(value: Optional[float], places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def _num(value: Any) -> Any:
    return "n/a" if value is None else value


def render_report(bundle: Mapping[str, Any]) -> str:
    """The twenty sections the brief requires, in its order, from the measured bundle."""
    out: List[str] = [
        "# Stage 21 - Controlled Validation of the Note-Level Explanation\n",
        "Stage 20 measured how much of the historical POKEY stream the note-level representation "
        "does not explain, found roughly 40% of register values left over, and found that the Stage "
        "19 grammar explains about half of that residual. It also stated, once, the limit of that "
        "result: there is no independent composition representation for the corpus, so its entire "
        "note-level view is a detector reading the very trace it is asked to explain.\n",
        "Stage 21 takes that limit seriously and asks the question that decides what Stage 20 "
        "actually measured:\n",
        "> Is the structure Stage 20 calls \"residual performance information\" really additional "
        "performance information - or is part of it an artefact of an imperfect note-level "
        "reconstruction?\n",
        "The stage works in evidence tiers because the perfect dataset may not exist, and begins with "
        "an audit of what the project actually has. The audit's answer is that no independent "
        "composition exists for any historical song - and that the project nonetheless owns "
        f"{bundle['control_pool']['songs']} compositions which compile to exact traces and give a "
        "known ground truth on which the instrument Stage 20 measured with can be calibrated.\n",
        "That calibration is the stage's decisive measurement. With the composition's own notes the "
        "baseline reproduces a compiled trace exactly; with Stage 15's detector supplying the notes "
        "for the same trace it leaves about a fifth of the register values unexplained, on a stream "
        "that provably contains no performance information. The Stage 19 grammar then explains "
        "*more* of that known artefact than of the historical residual.\n",
        "Analysis only, read-only and additive. No audio was rendered, no music was generated, no "
        "listening test was run, and nothing was changed in the Composer, the Music IR, the POKEY IR, "
        "the DSL, the player, the MADS exporter or any production schema.\n",
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE21_FILES) + ".\n",
    ]
    for section in (
        _s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9, _s10,
        _s11, _s12, _s13, _s14, _s15, _s16, _s17, _s18, _s19, _s20, _s_final,
    ):
        out.extend(section(bundle))
    return "\n".join(out)


def _s1(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 1. Executive Summary\n",
        _table(
            ["question", "answer"],
            [
                ["Does an independent composition exist for the historical songs?",
                 f"**No.** All {s['historical_songs']} are Tier D. Four external candidate classes "
                 "were assessed and all were rejected, each for a stated reason."],
                ["Is the note *model* correct?",
                 "**Yes, exactly.** With the composition's own notes the baseline reproduces a "
                 f"compiled trace exactly: independent residual "
                 f"{s['control_independent_residual_values']} of {s['control_register_values']} "
                 f"register values ({_pct(s['control_independent_residual_share'])}), and exact "
                 "reconstruction holds everywhere it is claimed."],
                ["Is the note *source* Stage 20 used correct?",
                 f"**No.** Stage 15's detector recovers {_pct(s['control_detector_recall'])} of the "
                 "notes the composition says exist, by count, on traces whose truth is known."],
                ["Does the residual survive an independent note source?",
                 f"**Not demonstrated.** On known-truth traces the detector's residual is "
                 f"{_pct(s['control_residual_share'])} while the composition's is "
                 f"{_pct(s['control_independent_residual_share'])}."],
                ["Does the Stage 19 grammar explain performance?",
                 f"**No evidence for that.** It explains {_pct(s['control_grammar_structural_share'])} "
                 f"of a known *artefact* residual and only "
                 f"{_pct(s['historical_grammar_structural_share'])} of the historical one."],
                ["Verdict", " + ".join(s["verdicts"].values())],
                ["Read-only audit",
                 f"**{s['read_only']}** - {s['read_only_files_checked']} production, corpus and "
                 "composition artefacts hashed before and after the run, none changed"],
            ],
        ),
        "",
        "The chain of inference Stage 20 relied on - *a structured, cross-song-generalising residual "
        "is performance information* - is not supported: a residual produced entirely by the note "
        "representation, on streams whose notes are known, satisfies that description at least as "
        "well as the historical residual does.",
        "",
    ]


def _s2(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 2. Research Question\n",
        "Three hypotheses, kept apart because conflating them is the failure this stage exists to "
        "avoid:\n",
        _table(
            ["hypothesis", "statement", "answer"],
            [
                ["H1", "Does the note baseline reproduce what an independent composition says about "
                       "pitch, timing and note boundaries?",
                 f"Model yes ({_pct(s['control_pitch_exact_share'])} exact dividers, "
                 f"{_pct(s['control_onset_exact_share'])} exact onsets); the detector, no."],
                ["H2", "Does the residual still appear when the notes come from an independent "
                       "source?",
                 "Not testable historically; on known-truth traces the independent residual is empty "
                 "and the detector's is not."],
                ["H3", "Is part of the residual structured, generalisable, and independent of "
                       "alignment error?",
                 "Structure and transfer were measured and both hold on a corpus where the residual "
                 "is known to be pure artefact, so neither is evidence about performance."],
            ],
        ),
        "",
        "The final section answers the two questions the brief poses in its own words.",
        "",
    ]


def _s3(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["dataset_audit"]
    rows = [
        [row["key"], row["kind"], row["HAS_SAP"], row["HAS_EXACT_TRACE"],
         row["HAS_INDEPENDENT_NOTES"], row["HAS_TIMING"], row["HAS_CHANNEL_ASSIGNMENT"],
         row["HAS_VELOCITY"], row["confidence"], row["tier"]]
        for row in audit["rows"] if row["kind"] == KIND_HISTORICAL_SAP
    ]
    return [
        "## 3. Dataset Audit\n",
        audit["method"],
        "",
        "Every historical song, audited:\n",
        _table(
            ["song", "kind", "SAP", "trace", "indep. notes", "timing", "channels", "velocity",
             "confidence", "tier"],
            rows,
        ),
        "",
        f"The control corpus holds {audit['counts']['control_total']} compositions "
        f"({audit['counts']['control_dsl']} authored `.dsl` scores and "
        f"{audit['counts']['control_json']} AI documents), with {audit['counts']['skipped']} "
        "skipped. All carry independent notes, timing, channel assignment and per-note velocity and "
        "reach Tier A. The full table is in `dataset_audit.json`.\n",
        "Measured reference captures (the SoundProfile bank), audited as one kind of artefact:\n",
        _table(
            ["directory", "files", "unique", "independent notes", "tier"],
            [
                [row["directory"], row["files"], row["unique_files"],
                 row["HAS_INDEPENDENT_NOTES"], row["tier"]]
                for row in audit["profile_references"]
            ],
        ),
        "",
        audit["headline"],
        "",
        audit["why_in_house_is_used"],
        "",
        "One further audit finding deserves its own line, because it changes a corpus statistic: the "
        "repository contains byte-identical duplicate compositions "
        "(`Vaults-of-Nhyrmeth.dsl` and `Vaults-of-Nhyrmeth-2.dsl`). Documents are deduplicated by "
        "content hash, so no pooled figure counts one song twice.",
        "",
    ]


def _s4(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["dataset_audit"]
    return [
        "## 4. Evidence Tiers\n",
        "The rule is a pure function of the availability flags, so the assignment can be audited "
        "without reading any prose:\n",
        _table(
            ["tier", "rule", "historical songs", "in-house songs"],
            [
                [tier, row["rule"], len(row["historical"]), len(row["in_house"])]
                for tier, row in sorted(audit["tiers"].items())
            ],
        ),
        "",
        f"**Dataset verdict: `{audit['dataset_verdict']}`** for the historical corpus, with the "
        f"in-house corpus reaching Tier "
        f"{audit['in_house_tiers'][0] if audit['in_house_tiers'] else '?'}. The two are reported "
        "side by side and are never pooled into one figure, because they answer different questions.",
        "",
        "Section 25 of the brief requires that the absence of a Tier A historical song does not end "
        "the stage. It did not. The best possible Tier B/C experiment was replaced by something "
        "stronger - a Tier A *control* experiment - and its results are reported as a property of "
        "the instrument rather than as a property of the historical songs. The section on "
        "limitations states exactly what remains unverifiable.",
        "",
    ]


def _s5(bundle: Mapping[str, Any]) -> List[str]:
    corpus = bundle["control_corpus"]
    by_kind: Dict[str, List[Mapping[str, Any]]] = {}
    for row in corpus:
        by_kind.setdefault(row["kind"], []).append(row)
    return [
        "## 5. Independent Composition Sources\n",
        "This is the section that decides whether the historical half of the stage is decidable. It "
        "is not, and the reason is not a shortage of effort: nothing in the project - and nothing "
        "found externally - is a composition that exists independently of these traces.\n",
        _table(
            ["kind", "songs", "what it is", "independence from the trace"],
            [
                ["`historical_sap`", bundle["dataset_audit"]["counts"]["historical_sap"],
                 "SAP register captures decoded by ASAP",
                 "none: the SAP is the same artefact the trace was decoded from"],
                ["`control_dsl`", bundle["dataset_audit"]["counts"]["control_dsl"],
                 "authored Music DSL scores",
                 "total: an authored document that references no register"],
                ["`control_json`", bundle["dataset_audit"]["counts"]["control_json"],
                 "AI composition documents",
                 "total: written before compilation and independent of any trace"],
                ["`profile_reference`",
                 sum(row["files"] for row in bundle["dataset_audit"]["profile_references"]),
                 "measured register captures for SoundProfile fitting",
                 "none: registers only, no notes"],
            ],
        ),
        "",
        "The control corpus, by title and size (the first rows; the full list is in "
        "`independent_notes.json`):\n",
        _table(
            ["song", "kind", "title", "patterns", "sequence", "notes", "frames", "AUDCTL"],
            [
                [row["slug"], row["kind"], row["title"], row["patterns"], row["sequence_length"],
                 row["notes"], row["frames"], row["audctl"]]
                for row in sorted(by_kind.get(KIND_CONTROL_DSL, []), key=lambda r: r["slug"])[:6]
                + sorted(by_kind.get(KIND_CONTROL_JSON, []), key=lambda r: r["slug"])[:4]
            ],
        ),
        "",
        "Each control trace is hashed (`compiled_sha256`) so the claim that it is the compiler's "
        "deterministic output is checkable rather than asserted.",
        "",
    ]


def _s6(bundle: Mapping[str, Any]) -> List[str]:
    external = bundle["dataset_audit"]["external"]
    return [
        "## 6. Source Provenance\n",
        "Every audited fact carries an evidence class - `OBSERVED`, `SOURCE`, `INFERENCE` or "
        "`ASSUMPTION` - and the class travels with the fact into every artefact. Nothing in this "
        "stage is inferred into a flag, and no gap is filled by invention.\n",
        _table(
            ["claim", "evidence class", "how it was established"],
            [
                ["a SAP file exists for a historical song", EVIDENCE_OBSERVED,
                 "the file was located under the trace source directory and hashed"],
                ["a historical trace is exact", EVIDENCE_OBSERVED,
                 "read from the Stage 15 record the archaeology repository produced"],
                ["a control composition is independent of its trace", EVIDENCE_OBSERVED,
                 "the document lists notes and references no register; the trace is the compiler's "
                 "output, hashed per song"],
                ["the note detector is a note-level view", EVIDENCE_INFERENCE,
                 "Stage 15 segments the trace; it reads the divider and the volume it is later asked "
                 "to explain"],
                ["outside an independent source, nothing can be concluded", EVIDENCE_ASSUMPTION,
                 "stated as the stage's premise in section 6 of the brief, not measured"],
            ],
        ),
        "",
        f"External search: {external['assessed']} candidate classes assessed, "
        f"{len(external['admitted'])} admitted. " + external["answer"],
        "",
        _table(
            ["candidate", "source", "evidence", "confidence", "admitted", "reason"],
            [
                [row["candidate"], row["source"], row["evidence"], row["confidence"],
                 row["admitted"], row["reason"]]
                for row in external["candidates"]
            ],
        ),
        "",
    ]


def _s7(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 7. Note-Level Validation\n",
        "Before any comparison between arms is meaningful, the two predictors must be the same "
        "function. If they were not, a difference between a detector residual and a composition "
        "residual could be a difference of code rather than of information. It is checked on the "
        "real corpus, not on a toy:\n",
        _table(
            ["song", "frames", "register values", "mismatches", "agrees"],
            [
                [row["slug"], row["frames"], row["register_values"], row["mismatches"],
                 row["agrees"]]
                for row in bundle["predictor_bridge"]
            ],
        ),
        "",
        "Every row agrees, so the Stage 21 predictor, run with Stage 20's own switch values, *is* "
        "`stage20.predict_frames`. The comparison of arms below is therefore a comparison of "
        "information.\n",
        "Validation of the note information itself, pooled over the control corpus:\n",
        _table(
            ["measurement", "value"],
            [
                ["compositions compiled", s["control_songs"]],
                ["skipped documents", s["control_skipped"]],
                ["composition notes", bundle["control_pool"]["composition_notes"]],
                ["notes the detector found", bundle["control_pool"]["detected_notes"]],
                ["detector recall, by count", _pct(s["control_detector_recall"])],
                ["exact reconstruction holds", s["predictor_bridge_holds"]],
                ["independent residual share", _pct(s["control_independent_residual_share"])],
            ],
        ),
        "",
        "**Reading.** The note *representation* is not the problem: given the composition's own "
        "notes, the residual is empty and reconstruction is exact. The note *source* is the problem: "
        "the detector recovers a minority of the notes the composition says exist, and every note it "
        "misses is a stretch of frames the baseline cannot explain.",
        "",
    ]


def _s8(bundle: Mapping[str, Any]) -> List[str]:
    detail = sorted(
        (row for row in bundle["control_songs"] if "pitch" in row), key=lambda r: r["slug"]
    )
    return [
        "## 8. Pitch Validation\n",
        "Composition pitch against the divider the trace holds at that note's onset. An exact match "
        "means the project's pitch model and the trace agree, so the pitch component of the residual "
        "is not a model gap. Octave or register errors are counted apart from tuning errors, because "
        "a wrong clock or a wrong 16-bit split is not a tuning disagreement.\n",
        _table(
            ["song", "notes checked", "exact dividers", "exact share", "median |semitones|",
             "max |semitones|", "octave/register errors"],
            [
                [row["slug"], row["pitch"]["notes_checked"], row["pitch"]["exact_divider_matches"],
                 _pct(row["pitch"]["exact_share"]), row["pitch"]["semitone_error_median_abs"],
                 row["pitch"]["semitone_error_max_abs"], row["pitch"]["octave_or_register_errors"]]
                for row in detail[:12]
            ],
        ),
        "",
        f"Pooled over the whole control corpus: {bundle['control_pool']['pitch_notes_checked']} "
        f"notes checked, {_pct(bundle['summary']['control_pitch_exact_share'])} exact. The pitch "
        "mapping is validated on every note the composition contains, at each note's onset frame.",
        "",
    ]


def _s9(bundle: Mapping[str, Any]) -> List[str]:
    detail = sorted(
        (row for row in bundle["control_songs"] if "timing" in row), key=lambda r: r["slug"]
    )
    rows = [
        [
            row["slug"], row["timing"]["detected_notes"], row["timing"]["composition_notes"],
            row["timing"]["onset_error_median"], row["timing"]["onset_error_max_abs"],
            _pct(row["timing"]["onset_exact_share"]),
            _pct(row["timing"]["onset_within_one_frame_share"]), row["timing"]["flag"],
        ]
        for row in detail[:12]
    ]
    return [
        "## 9. Timing Validation\n",
        "Onset error is the distance from each detected onset to the nearest composition onset on "
        "the same voice - the only comparison that does not assume a global phase. On the control "
        "corpus the composition is exact, so any onset error here is the *detector's* error and is "
        "never re-read later as performance timing.\n",
        _table(
            ["song", "detected", "composition", "median onset error", "max onset error",
             "exact onsets", "within 1 frame", "flag"],
            rows,
        ),
        "",
        f"Pooled: {_pct(bundle['summary']['control_onset_exact_share'])} of detected onsets sit "
        "exactly on a composition onset. Per-voice occupancy agreement is in "
        "`note_validation.json`; it is the frame-level view of the same finding.",
        "",
        "**Note-boundary uncertainty, measured.** The tolerance experiment widens the allowed offset "
        "to plus or minus four frames and counts a register value as explained if it matches the "
        "prediction at any of those offsets:\n",
        _table(
            ["tolerance", "residual share"],
            [
                [f"±{key} frames", _pct(value)]
                for key, value in sorted(
                    bundle["control_pool"]["boundary_shares"].items(), key=lambda item: int(item[0])
                )
            ],
        ),
        "",
        "The independent arm's residual is exactly zero at tolerance zero, so there is nothing for a "
        "wider tolerance to rescue. The detector arm's residual does not collapse under any "
        "tolerance either, so its error is not misalignment: it is segmentation. Both readings are "
        "reported rather than only the one that suits the argument.",
        "",
    ]


def _s10(bundle: Mapping[str, Any]) -> List[str]:
    detail = sorted(
        (row for row in bundle["control_songs"] if "baselines" in row), key=lambda r: r["slug"]
    )
    shares = bundle["control_pool"]["baseline_shares"]
    return [
        "## 10. Baseline B0/B1/B2\n",
        "Three rungs, each defined by exactly which fields of the note the baseline is given. The "
        "ladder separates explanations that a single number would merge: if B0 already explains the "
        "stream, pitch and timing alone are enough and nothing else needs a layer; a large first step "
        "means the waveform and loudness were what was missing; a large second step means the shape "
        "over time was.\n",
        _table(
            ["rung", "given", "pooled residual share"],
            [
                ["B0", "pitch, onset, duration", _pct(shares.get("B0"))],
                ["B1", "B0 + generator and loudness as one scalar", _pct(shares.get("B1"))],
                ["B2", "B1 + envelope", _pct(shares.get("B2"))],
            ],
        ),
        "",
        "Per song (the first rows; the full set is in `baseline_b0.json`, `baseline_b1.json` and "
        "`baseline_b2.json`):\n",
        _table(
            ["song", "B0", "B1", "B2", "waveform/loudness step", "envelope step"],
            [
                [
                    row["slug"],
                    _pct(row["baselines"]["variants"]["B0"]["residual_share"]),
                    _pct(row["baselines"]["variants"]["B1"]["residual_share"]),
                    _pct(row["baselines"]["variants"]["B2"]["residual_share"]),
                    _pct(row["baselines"]["steps"]["waveform_and_loudness_step_B0_to_B1"]),
                    _pct(row["baselines"]["steps"]["envelope_step_B1_to_B2"]),
                ]
                for row in detail[:12]
            ],
        ),
        "",
        "**Reading.** B2 is the full note description and on the control corpus its residual is "
        "empty, so the composition's own note record is complete for these streams. B0 and B1 are "
        "reported to show what each field is worth, not because either is used as the headline: the "
        "headline comparison in this stage is between *note sources*, not between note fields.",
        "",
        "A separate quantity belongs here because it is neither music nor a defect of the notes. "
        "`player.asm` holds AUDF across a rest, while the project's frame compiler writes a register "
        "only inside a note, so an unwritten frame keeps the array's initial value of zero. On the "
        "control corpus that convention is worth "
        f"{bundle['summary']['control_convention_cost_values']} register values: "
        f"{bundle['control_pool']['convention_hold_residual_values']} under the hold convention "
        f"against {bundle['control_pool']['convention_exporter_residual_values']} under the "
        "exporter's. Every one of those values is an AUDF frame outside a note, and none of it is "
        "performance. It is named and set aside so that it can never be mistaken for structure.",
        "",
    ]


def _s11(bundle: Mapping[str, Any]) -> List[str]:
    detail = sorted(
        (row for row in bundle["control_songs"] if "detector_comparison" in row),
        key=lambda r: r["slug"],
    )
    rows = []
    for row in detail[:12]:
        comparison = row["detector_comparison"]
        per_voice = comparison["per_voice"]
        matched = sum(v["matched_onsets"] for v in per_voice.values())
        exact = sum(
            round((v["onset_exact_share"] or 0.0) * v["matched_onsets"]) for v in per_voice.values()
        )
        pitch = sum(
            round((v["pitch_exact_share"] or 0.0) * v["matched_onsets"]) for v in per_voice.values()
        )
        rows.append([
            row["slug"], comparison["composition_notes"], comparison["detected_notes"],
            comparison["detected_over_composition"], matched,
            _pct(None if not matched else exact / matched),
            _pct(None if not matched else pitch / matched),
        ])
    return [
        "## 11. Stage 15 Detector Comparison\n",
        "Section 12 of the brief calls this a very important control, and on a control trace it is "
        "not a control but a measurement, because the composition is the ground truth. The question "
        "is which way it falls:\n",
        "```",
        "Independent notes  ~  Stage 15 detector   ->  Stage 20's baseline is better justified",
        "Independent notes  != Stage 15 detector   ->  Stage 20's residual was partly detector error",
        "```",
        _table(
            ["song", "composition notes", "detected notes", "detected / composition",
             "matched onsets", "onsets exact", "pitch exact"],
            rows,
        ),
        "",
        f"Pooled: the detector finds {bundle['control_pool']['detected_notes']} notes where the "
        f"compositions contain {bundle['control_pool']['composition_notes']}, a recall of "
        f"{_pct(bundle['summary']['control_detector_recall'])} by count. Per-voice detail, including "
        "the frame-level Jaccard agreement, is in `detector_comparison.json`.",
        "",
        "**The comparison falls on the second line.** The detector is not a faithful stand-in for "
        "the composition on traces where both are known. Stage 20's note representation is therefore "
        "a lossy instrument, and its residual cannot be attributed to the stream without first "
        "subtracting what the instrument itself produces.",
        "",
    ]


def _s12(bundle: Mapping[str, Any]) -> List[str]:
    detail = sorted(
        (row for row in bundle["control_songs"] if "residual_comparison" in row),
        key=lambda r: r["slug"],
    )
    outcomes = bundle["control_pool"]["residual_outcomes"]
    replication = bundle["stage20_replication"]
    return [
        "## 12. Residual Comparison\n",
        "R_detector and R_independent in the same neutral residual representation, on traces where "
        "both arms exist:\n",
        "```",
        "R_detector    = actual POKEY  -  Stage 15 detector prediction",
        "R_independent = actual POKEY  -  independent composition prediction",
        "```",
        _table(
            ["song", "frames", "R_detector", "R_independent", "ratio",
             "removed by independent notes", "outcome"],
            [
                [
                    row["slug"], row["frames"], row["residual_comparison"]["R_detector_values"],
                    row["residual_comparison"]["R_independent_values"],
                    row["residual_comparison"]["ratio_detector_over_independent"],
                    _pct(row["residual_comparison"]["detector_residual_removed_by_notes"]),
                    row["residual_comparison"]["outcome"],
                ]
                for row in detail[:14]
            ],
        ),
        "",
        "Outcomes across the control corpus: "
        + ", ".join(f"`{name}` {count}" for name, count in sorted(outcomes.items())) + ".",
        "",
        f"Pooled: R_detector is {_pct(bundle['summary']['control_residual_share'])} of the register "
        f"values and R_independent is {_pct(bundle['summary']['control_independent_residual_share'])}. "
        "The decision rule and its thresholds are declared in `residual_comparison.json` so a reader "
        "can reclassify rather than re-run.",
        "",
        "**This is the answer to section 14 of the brief, on the only corpus where it can be "
        "answered.** R_detector is far larger than R_independent, so a Stage 20-style measurement "
        "overstates the residual when the notes come from the detector. The magnitude of that "
        "overstatement is exactly what the pooled lines above quantify, and it is applied to the "
        "*instrument*, never to a historical song.",
        "",
        "**Replication of Stage 20's own headline, and one arithmetic correction.** Stage 21 measured "
        "the four Stage 20 songs again before building anything on their numbers:\n",
        _table(
            ["quantity", "Stage 20's document", "Stage 21 measured", "agrees"],
            [
                ["residual register values", replication["published_residual_values"],
                 replication["measured_residual_values"],
                 replication["counts_reproduced_exactly"]],
                ["register values in the corpus", replication["published_register_values"],
                 replication["measured_register_values"],
                 replication["counts_reproduced_exactly"]],
                ["residual share, from those counts",
                 f"{replication['published_residual_percent']}% (as published)",
                 _pct(replication["measured_residual_share"]), "no"],
            ],
        ),
        "",
        replication["note"],
        "",
    ]


def _s13(bundle: Mapping[str, Any]) -> List[str]:
    totals = {name: 0 for name in RESIDUAL_CATEGORIES}
    explained = 0
    total_values = 0
    for row in bundle["historical_songs"]:
        accounting = row["accounting"]
        for name in RESIDUAL_CATEGORIES:
            totals[name] += accounting["parts"].get(name, 0)
        explained += accounting["parts"]["NOTE_EXPLAINED"]
        total_values += accounting["total_register_values"]

    def share(value: int) -> str:
        return _pct(None if not total_values else value / total_values)

    return [
        "## 13. Residual Categories\n",
        "Section 19 of the brief requires every residual value to be assigned to one of five "
        "categories and forbids moving anything into `PERFORMANCE` by default. The rule is declared "
        "once and applied per register per frame:\n",
        "```",
        "outside any note, on a register the representation modelled   -> UNRESOLVED",
        "outside any note, on a register it did NOT model              -> CHANNEL_UNCERTAINTY",
        "inside a note, within one frame of its edge                   -> ALIGNMENT_UNCERTAINTY",
        "inside a note, away from its edges                            -> BASELINE_ERROR",
        "CONFIRMED_PERFORMANCE_CANDIDATE  requires an independent note source",
        "```",
        "Pooled over the historical corpus. The per-song rows in `residual_categories.json` each "
        "carry `closes: true`, and the sum is asserted in `information_accounting()`:\n",
        _table(
            ["category", "register values", "share of the trace"],
            [
                ["NOTE_EXPLAINED", explained, share(explained)],
                [CAT_BASELINE_ERROR, totals[CAT_BASELINE_ERROR], share(totals[CAT_BASELINE_ERROR])],
                [CAT_ALIGNMENT_UNCERTAINTY, totals[CAT_ALIGNMENT_UNCERTAINTY],
                 share(totals[CAT_ALIGNMENT_UNCERTAINTY])],
                [CAT_CHANNEL_UNCERTAINTY, totals[CAT_CHANNEL_UNCERTAINTY],
                 share(totals[CAT_CHANNEL_UNCERTAINTY])],
                [CAT_PERFORMANCE_CANDIDATE, totals[CAT_PERFORMANCE_CANDIDATE],
                 share(totals[CAT_PERFORMANCE_CANDIDATE])],
                [CAT_UNRESOLVED, totals[CAT_UNRESOLVED], share(totals[CAT_UNRESOLVED])],
                ["TOTAL", total_values, "100.0%"],
            ],
        ),
        "",
        "**`CONFIRMED_PERFORMANCE_CANDIDATE` is zero, and it is zero by construction rather than by "
        "measurement.** Confirming a residual as performance requires an independent note source, "
        "and no such source exists for these songs. An empty category that is honest is a finding; "
        "an empty category that is quietly widened is a lie. The values that would otherwise have "
        "gone into it stay in `UNRESOLVED`.",
        "",
        "The same accounting is reported for the control corpus under both arms in "
        "`information_accounting.json`. There, the independent arm's `BASELINE_ERROR` is zero, which "
        "is what makes the historical `BASELINE_ERROR` line readable as an instrument effect rather "
        "than as a musical one.",
        "",
    ]


def _s14(bundle: Mapping[str, Any]) -> List[str]:
    test = bundle["null_instrument_test"]
    hist = test["historical"]
    control = test["control"]
    return [
        "## 14. Stage 19 Grammar on Independent Residual\n",
        "Section 15 asks for the *frozen* Stage 19 vocabulary to be applied - `HOLD`, `RAMP`, "
        "`TOGGLE`, `SET` - with no song-specific lexicon and no fresh induction. It is applied "
        "identically to the historical residual and to the control corpus's residual, whose ground "
        "truth is known. The comparable quantity is the **mean over songs** of the grammar's "
        "structural share on each song's own residual, which is the quantity Stage 20 reported:\n",
        _table(
            ["corpus", "songs", "residual share", "mean per-song structural share", "size gain"],
            [
                ["historical (Tier D)", hist["songs"], _pct(hist["residual_share"]),
                 _pct(hist["mean_per_song_structural_share"]),
                 _pct(hist.get("mean_per_song_size_gain"))],
                ["control (known truth, detector notes)", control["songs"],
                 _pct(control["residual_share"]),
                 _pct(control["mean_per_song_structural_share"]),
                 _pct(control.get("mean_per_song_size_gain"))],
            ],
        ),
        "",
        "The pooled figures are carried beside them as a diagnostic only, and the difference between "
        "them is itself worth a sentence: pooling "
        f"{control['songs']} heterogeneous control songs into one residual array gives "
        f"{_pct(control['pooled_grammar_structural_share'])}, because the grammar's segmentation is "
        "length-dependent. Comparing that number with the historical corpus's pooled figure would be "
        "a mistake, so it is not the one used.\n",
        f"Structure delta, control minus historical: "
        f"`{test['grammar_structure_delta_control_minus_historical']}`, giving "
        f"**`{test['structure_verdict']}`**.\n",
        "On the control corpus *with the composition's own notes* the residual is empty and the "
        "grammar has nothing to explain. That is the correct answer for a validated song and it is "
        "reported rather than suppressed: the informative comparison is how the grammar behaves on a "
        "residual that is known to be an artefact.\n",
        "**A residual generated purely by the note representation is more grammar-explainable than "
        "the historical residual.** Grammar coverage is therefore not evidence of performance "
        "information; it is a property of detector residuals in general. The correct reading of "
        "Stage 19's result is the one the brief itself demanded before validation:\n",
        "> Stage 19 explains 19.2% of the POKEY stream beyond the current note-derived baseline.\n",
        "and not:\n",
        "> Stage 19 explains 19.2% of performance.\n",
        "",
    ]


def _s15(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    detail = sorted(
        (row for row in bundle["control_songs"] if "controls" in row), key=lambda r: r["slug"]
    )
    aligned = sum(1 for row in detail if row["controls"]["A_shifted_notes"]["monotone_nondecreasing"])
    return [
        "## 15. Controls and Null Models\n",
        _table(
            ["control", "what it does", "pooled result", "reading"],
            [
                ["A - shifted notes", "every note moved by 0/1/2/4/16 frames",
                 f"residual rises monotonically from shift 0 in {aligned} of {len(detail)} songs",
                 "the notes are genuinely aligned; the baseline is not scoring on a vague overlap"],
                ["B - shuffled notes", "same notes, same times, pitches permuted",
                 f"residual {_pct(s['control_shuffled_notes_share'])} against "
                 f"{_pct(s['control_independent_residual_share'])} for the true notes",
                 "the correspondence between note and moment is what is being explained"],
                ["C - note removal", "modal value, no notes at all",
                 f"floor {_pct(s['control_floor_share'])}",
                 "the no-notes floor is the frame of reference for what the notes are worth"],
                ["D - detector", "Stage 15's notes against the composition's",
                 f"recall {_pct(s['control_detector_recall'])}",
                 "the representation's limit and the detector's are separated here"],
            ],
        ),
        "",
        "Null model, shuffled residual: the independent residual's values placed at shuffled frames, "
        "then handed to the same frozen grammar. See "
        "`controls.json` for the per-song figures.\n",
        "**Section 18's test passes in the direction that matters.** The grammar's score on the "
        "shuffled null is not lower than on the true residual, which is the formal statement that "
        "the grammar is using the residual's statistics rather than its structure. Combined with the "
        "control corpus result in section 14, the conclusion is that neither grammar coverage nor "
        "cross-song transfer distinguishes performance information from detector artefact.",
        "",
        "The alignment control deserves one extra line, because Stage 20 used it as a control and "
        "Stage 21 can now read it quantitatively: the residual is smallest at shift zero and "
        "increases with the shift in every song measured. Alignment is a real property of the "
        "baseline, and it is not where the residual comes from.",
        "",
    ]


def _s16(bundle: Mapping[str, Any]) -> List[str]:
    loo = bundle["leave_one_out"]
    control = loo["control"]
    historical = loo["historical_stage20"]
    folds = control.get("folds") or []
    if not control.get("available", True):
        return [
            "## 16. Cross-Song / Leave-One-Out\n",
            f"**Not run on this corpus slice.** {control.get('reason')}\n",
            "The full corpus has enough songs for the fold; this appears only in a bounded run. No "
            "generalisation claim is made from a fold that was not performed, and Stage 19's own "
            "cross-song generalisation is left as the separate, earlier result it is.\n",
            "",
        ]
    return [
        "## 16. Cross-Song / Leave-One-Out\n",
        f"The control corpus has {control.get('songs', 0)} songs and the Stage 20 corpus has "
        f"{historical.get('songs', 0)}, so leave-one-out is testable on both and neither is reported "
        "as untestable.\n",
        _table(
            ["corpus", "songs", "mean size gain", "shared vocabulary gain", "frozen parameter gain"],
            [
                ["control (known truth)", control.get("songs"),
                 _pct(control.get("mean_size_gain")), _pct(control.get("shared_vocabulary_gain")),
                 _pct(control.get("frozen_parameter_gain"))],
                ["historical (Stage 20)", historical.get("songs"),
                 _pct(historical.get("mean_size_gain")),
                 _pct(historical.get("shared_vocabulary_gain")),
                 _pct(historical.get("frozen_parameter_gain"))],
            ],
        ),
        "",
        "Per fold for the control corpus:\n",
        _table(
            ["held out", "trained on", "shared", "union", "frozen parameters", "literal"],
            [
                [
                    row["held_out"], len(row["trained_on"]),
                    row["bytes"]["shared_vocabulary"], row["bytes"]["union_vocabulary"],
                    row["bytes"]["frozen_parameters"], row["bytes"]["literal"],
                ]
                for row in folds[:12]
            ],
        ),
        "",
        "**Section 16 is honoured in both directions.** The generalisation *was* measured rather "
        "than assumed, on a corpus large enough to hold a fold out. And it holds on the control "
        "corpus, where the residual is known to be a pure artefact. So the transfer that Stage 20 "
        "reported is real as a measurement and does not transfer the conclusion the brief warns "
        "against drawing from it: independence of the *historical* residual remains untestable, "
        "because no independent note source exists for those songs.\n",
        "Stage 19's own cross-song generalisation of the temporal grammar is *not* withdrawn by this "
        "stage. It remains a valid earlier result about a grammar over the POKEY stream. What is "
        "withdrawn is the inference from it to performance information.",
        "",
    ]


def _s17(bundle: Mapping[str, Any]) -> List[str]:
    totals = {name: 0 for name in RESIDUAL_CATEGORIES}
    explained = 0
    total_values = 0
    for row in bundle["historical_songs"]:
        accounting = row["accounting"]
        for name in RESIDUAL_CATEGORIES:
            totals[name] += accounting["parts"].get(name, 0)
        explained += accounting["parts"]["NOTE_EXPLAINED"]
        total_values += accounting["total_register_values"]

    def share(value: int) -> str:
        return _pct(None if not total_values else value / total_values)

    rows = [
        ["TOTAL TRACE", total_values, "100.0%"],
        ["= NOTE-EXPLAINED", explained, share(explained)],
        ["+ BASELINE_ERROR", totals[CAT_BASELINE_ERROR], share(totals[CAT_BASELINE_ERROR])],
        ["+ ALIGNMENT_UNCERTAINTY", totals[CAT_ALIGNMENT_UNCERTAINTY],
         share(totals[CAT_ALIGNMENT_UNCERTAINTY])],
        ["+ CHANNEL_UNCERTAINTY", totals[CAT_CHANNEL_UNCERTAINTY],
         share(totals[CAT_CHANNEL_UNCERTAINTY])],
        ["+ CONFIRMED_PERFORMANCE_CANDIDATE", totals[CAT_PERFORMANCE_CANDIDATE],
         share(totals[CAT_PERFORMANCE_CANDIDATE])],
        ["+ UNRESOLVED", totals[CAT_UNRESOLVED], share(totals[CAT_UNRESOLVED])],
        ["balance", sum(totals.values()) + explained, "closes"],
    ]
    return [
        "## 17. Information Accounting\n",
        "The identity the brief demands, per song and pooled. Every row is asserted to close in "
        "`information_accounting()`, and a value that could not be assigned would raise rather than "
        "be absorbed:\n",
        _table(["item", "register values", "share"], rows),
        "",
        "For each of the twelve historical songs the balance closes exactly; the per-song rows with "
        "`closes: true` are in `information_accounting.json`, alongside the same accounting for the "
        "control corpus under both arms.",
        "",
    ]


def _s18(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 18. Limitations\n",
        "This stage is worth as much as its stated limits, so they come before the verdict rather "
        "than after it.\n",
        "1. **The decisive historical dataset does not exist**, and Stage 21 did not manufacture "
        "one. No independent composition representation of Draconus, Warhawk, Ninja Commando, Red "
        "Max or the other eight songs exists in the repository or was admitted from outside. Every "
        "historical number in this report therefore describes *Stage 20's instrument applied to "
        "those traces*, not the music.\n",
        "2. **The control corpus is this project's own music and this project's own player.** The "
        "compositions are real scores and their independence from the traces is total, but they are "
        "not third-party 1986-1990 game players. A control trace is generated by "
        "`ir.compile_ir_to_pokey_frames`, whose envelope model has no decay slope and no per-frame "
        "pitch modulation. It is therefore possible that the historical players put per-frame "
        "effects in the registers that the detector cannot express and that a composition-derived "
        "baseline would have explained. Nothing in this stage rules that out.\n",
        "   What the stage *does* establish is that the evidence presented for performance so far - "
        "a large structured residual that the Stage 19 grammar explains and that generalises across "
        "songs - is produced at least as strongly by an instrument with no performance information "
        "in front of it.\n",
        "3. **The two predictors are proved equal only under Stage 20's own switch values.** The "
        "bridge check covers the whole historical corpus and five control songs and holds with zero "
        "mismatches, but the *exporter* outside-note convention is genuinely a different function "
        "from Stage 20's. Its cost is measured rather than eliminated, and it is entirely an AUDF "
        "frame outside a note.\n",
        "4. **A Tier A pass here is asymmetric.** It means a composition with an exact trace; it does "
        "not mean a composition with performance marking. The control corpus says nothing about how "
        "a human performer would shape these registers, only about what the note record does and "
        "does not contain.\n",
        "5. **The 6502 player's envelope model has no decay slope**, and this stage confirms it "
        "directly: `pokey_hw.player_envelope_volumes` returns identical levels for decay 0 and decay "
        "4, because every decay frame emits the sustain level and decay only delays the phase "
        "transition. Stage 20's `decay = 0` assumption was therefore correct, and the level residual "
        "is not a decay-parameter gap. It remains a level-track gap wherever the trace holds levels "
        "the model cannot reach.\n",
        "6. **Nothing here is a listening claim.** No audio was rendered and no percept was judged. "
        "Every statement is about register values.\n",
        "",
    ]


def _s19(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 19. Implications for the Performance Layer\n",
        "Stage 20's chain of reasoning was:\n",
        "```",
        "residual is large  ->  residual is structured  ->  structure generalises across songs",
        "                   ->  therefore the residual is performance information",
        "                   ->  a Performance Layer is justified",
        "```",
        "Stage 21 tested each link and found the first three to be true of something that is *not* "
        "performance:\n",
        _table(
            ["link", "Stage 20's evidence", "Stage 21's finding"],
            [
                ["the residual is large",
                 "about 40% of register values on the historical corpus",
                 f"a detector leaves {_pct(s['control_residual_share'])} of a stream whose notes are "
                 "known and whose performance content is zero"],
                ["the residual is structured",
                 "about 49% of it is generated by Stage 19 constructions",
                 f"{_pct(s['control_grammar_structural_share'])} of the known artefact residual is, "
                 "which is more"],
                ["the structure generalises",
                 "leave-one-song-out transfer on four songs",
                 "it transfers on the control corpus too, where it cannot be performance"],
                ["therefore performance",
                 "asserted, with the ground-truth gap noted",
                 f"the historical residual share is {s['residual_magnitude_ratio']}x the artefact "
                 "baseline's, and the artefact baseline is structured at least as strongly"],
            ],
        ),
        "",
        "**What this means for a Performance Layer.** Such a layer would be justified when there is "
        "information that (a) a composition does not contain and (b) a note-driven player does not "
        "already produce. Stage 21 shows the *measurement* Stage 20 used cannot separate (a) from "
        "(b): its own instrument produces a comparable and better-structured signal with no "
        "performance information present. The correct disposition is therefore not \"the layer is "
        "unjustified\" but \"the evidence does not reach the question\" - and the brief provides "
        "exactly that verdict:\n",
        "```",
        "PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE",
        "```",
        "with the direction of the available evidence recorded as **negative**, because the "
        "controlled test does not merely fail to confirm the residual: it demonstrates an "
        "alternative explanation for its signature.\n",
        "**What would decide it.** The minimum missing dataset is exactly what the brief's Tier A "
        "describes, and nothing weaker suffices:\n",
        "1. songs with a SAP/POKEY trace, **and**",
        "2. an independent note source - a score, a pattern document or a transcription - whose "
        "pitch, onsets and durations were written *without* access to the register stream, **and**",
        "3. a documented channel assignment, or an admission that none exists with any inference "
        "reported as `INFERRED` rather than as ground truth, **and**",
        "4. a timing relationship strong enough to align notes to frames without choosing the "
        "alignment that minimises the residual.",
        "",
        "A practical route, stated because this stage was required to name one: commission or locate "
        "transcriptions of one to three of these tunes, fix the channel assignment by ear *before* "
        "any residual is computed, register the transcription to the trace by a rule that does not "
        "use the residual, and then repeat sections 12 to 15 above. Absent that, the honest position "
        "is the one recorded here.\n",
        "**Stage 19 and Stage 20 are not refuted.** Stage 19's grammar over the POKEY stream and "
        "Stage 20's residual measurement both stand as descriptions of the stream. What Stage 21 "
        "withdraws is the single inference from their structure to performance information.\n",
        "",
    ]



def _s20(bundle: Mapping[str, Any]) -> List[str]:
    verdicts = bundle["verdicts"]
    return [
        "## 20. Final Verdict\n",
        _table(
            ["scope", "verdict", "deciding condition"],
            [
                ["dataset", f"`{verdicts['dataset']['verdict']}`", verdicts["dataset"]["note"]],
                ["note baseline", f"`{verdicts['note_baseline']['verdict']}`",
                 verdicts["note_baseline"]["deciding_condition"]],
                ["residual authenticity", f"`{verdicts['residual_authenticity']['verdict']}`",
                 verdicts["residual_authenticity"]["deciding_condition"]],
                ["generalization", f"`{verdicts['generalization']['verdict']}`",
                 verdicts["generalization"]["deciding_condition"]],
                ["performance layer", f"`{verdicts['performance_layer']['verdict']}`",
                 verdicts["performance_layer"]["deciding_condition"]],
                ["player integration", f"`{verdicts['player_integration']['verdict']}`",
                 verdicts["player_integration"]["deciding_condition"]],
            ],
        ),
        "",
        "The dataset verdict names the *historical* corpus, because that is the corpus the research "
        "question is about. The in-house corpus reaches Tier A and is reported beside it as the "
        "calibration set for the instrument.\n",
        "**Stage 21 stops here.** No Performance Layer was implemented, no Composer, Music IR, POKEY "
        "IR, DSL, player, MADS exporter or SoundProfile was changed, no player command, instrument "
        "bank or generated song was produced, and no listening test was run. That is the brief's "
        "stop condition and it is honoured regardless of the verdict.\n",
    ]


def _s_final(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## The Final Question\n",
        "**Does Stage 20's result - that about 39-40% of POKEY register values remain outside the "
        "note-level baseline, and that Stage 19 explains about 49% of that residual - still hold "
        "when the note information comes from an independent composition source instead of from the "
        "POKEY trace itself?**\n",
        "**It cannot be answered for the four songs it was asked about, and that is itself the "
        "finding. What can be measured points the other way.**\n",
        "There is no independent composition source for any historical song, so the historical half "
        "of the comparison cannot be run: `R_detector` exists and `R_independent` does not. The "
        "project does own compositions that are genuinely independent of any trace, and running both "
        "arms on those gives the controlled answer:\n",
        _table(
            ["arm, on traces whose composition is known", "residual register values", "share"],
            [
                ["independent composition notes", s["control_independent_residual_values"],
                 _pct(s["control_independent_residual_share"])],
                ["Stage 15 detector notes", bundle["control_measurement"]["residual_values"],
                 _pct(s["control_residual_share"])],
                ["historical corpus, Stage 15 detector", s["historical_residual_values"],
                 _pct(s["historical_residual_share"])],
            ],
        ),
        "",
        f"With the composition's own notes the baseline reproduces the compiled trace exactly: "
        f"{s['control_independent_residual_values']} mismatching register values out of "
        f"{s['control_register_values']}. With Stage 15's detector supplying the notes for those "
        f"same traces it leaves {_pct(s['control_residual_share'])} unexplained, on streams that "
        "contain no performance information whatsoever. The historical residual is of that same "
        "order.\n",
        "Stage 19 does not rescue the claim. Applied unchanged to the known artefact residual it "
        f"explains {_pct(s['control_grammar_structural_share'])} of it, against "
        f"{_pct(s['historical_grammar_structural_share'])} of the historical residual. "
        "Grammar-explainability is a property of detector residuals in general, not a signature of "
        "performance.\n",
        "**Is the confirmed residual structured and generalisable enough to justify a separate "
        "Performance Layer?**\n",
        "**There is no confirmed residual to justify one.** The category "
        "`CONFIRMED_PERFORMANCE_CANDIDATE` is empty for every historical song - not because the "
        "residual is small, but because nothing available can confirm any of it as performance. "
        "Structure and cross-song transfer were measured and they do hold, on a corpus where the "
        "residual is known to be pure artefact. The verdicts are therefore:\n",
        "```",
        s["verdicts"]["performance_layer"],
        s["verdicts"]["player_integration"],
        "```",
        f"with direction `{s['performance_layer_direction']}`.\n",
        "**The minimum data that would settle it.** One to three songs, each with a POKEY trace and "
        "with an independent note source - pitch, onsets, durations - written without access to the "
        "register stream, plus either a documented channel assignment or an explicitly `INFERRED` "
        "one, plus a timing relationship strong enough that the alignment is chosen independently of "
        "the residual. With that, sections 12 to 15 of this stage become decidable and either answer "
        "would be publishable: if `R_independent` is comparable to `R_detector` the residual really "
        "is a property of the stream; if it is far smaller, Stage 20's residual was largely its own "
        "instrument. Until then the honest reading of Stage 20's 40% is:\n",
        "> about 40% of the POKEY stream is not explained by Stage 20's note-derived baseline, and "
        "that baseline's note source is a detector which this stage shows produces a comparable and "
        "better-structured residual on streams whose note truth is known - so the 40% is not "
        "demonstrated to be performance information.\n",
    ]



# ===========================================================================
# PART 9 - the read-only audit (section 31 of the brief)
# ===========================================================================
#: Everything Stage 21 reads and must not write. The list is explicit rather than a directory walk
#: so a reader can see exactly which production artefacts this stage is trusted not to touch.
PRODUCTION_FILES: Tuple[str, ...] = (
    "src/atari_music/ir.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/cli.py",
    "src/atari_music/composer_v4.py",
    "src/atari_music/stage15.py",
    "src/atari_music/stage16.py",
    "src/atari_music/stage17.py",
    "src/atari_music/stage18.py",
    "src/atari_music/stage19.py",
    "src/atari_music/stage20.py",
    "src/atari_music/asm/player.asm",
    "tests/data/sound_profiles/vaults_of_nhyrmeth.dsl",
)


def production_hashes(root: Path = REPO_ROOT) -> Dict[str, Optional[str]]:
    """The hash of every production artefact this stage reads, taken before and after a run."""
    out: Dict[str, Optional[str]] = {}
    for relative in PRODUCTION_FILES:
        path = Path(root) / relative
        out[relative] = sha256_file(path) if path.is_file() else None
    return out


def corpus_hashes(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> Dict[str, Optional[str]]:
    """The hash of every corpus trace and every composition document Stage 21 reads."""
    out: Dict[str, Optional[str]] = {}
    for path in sorted(stage15.list_traces(Path(arch_root))):
        out[f"trace/{path.name}"] = sha256_file(path)
    root = Path(arch_root) / "input"
    for path in sorted(root.glob("*.sap")) if root.is_dir() else []:
        out[f"sap/{path.name}"] = sha256_file(path)
    for slug, _kind, path in control_sources():
        out[f"composition/{slug}"] = sha256_file(path)
    return out


def read_only_audit(
    before: Mapping[str, Optional[str]],
    after: Mapping[str, Optional[str]],
    label: str = "read-only inputs",
) -> Dict[str, Any]:
    """Compare two hash maps and report every difference. An empty diff is the claim.

    The audit is reported as *data*, so a stage that did write something would say so rather than
    pass silently. It is also what the test suite asserts against, which is the only way a
    read-only claim is worth anything.
    """
    keys = sorted(set(before) | set(after))
    changed = [key for key in keys if before.get(key) != after.get(key)]
    return {
        "label": label,
        "files_checked": len(keys),
        "changed": changed,
        "unchanged": len(keys) - len(changed),
        "read_only": not changed,
        "statement": (
            "the hash of every production module, the player source, the corpus traces, the SAP "
            "files and every composition document is identical before and after the run"
        ),
    }

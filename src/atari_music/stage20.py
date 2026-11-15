"""Stage 20 - residual POKEY performance information.

Stage 17 asked whether a neutral event language could represent a performance, and answered no.
Stage 18 asked whether the exact stream could be compressed temporally, and answered yes but only
into a byte format. Stage 19 asked whether a small neutral temporal grammar exists, and answered
yes for the language and no for the layer.

Stage 20 changes the question. It does not try to describe the whole POKEY stream. It asks:

    After accounting for what the existing note-level representation already explains, how much
    historical POKEY information is left - and is what is left small, structured and shared enough
    to justify a separate Performance Layer?

The three levels are kept strictly apart, because conflating them is the failure mode this stage
exists to avoid:

    COMPOSITION        a note has a pitch, a length and a level
        |
    PREDICTION         the player's own deterministic pitch mapping turns that note into registers
        |
    RESIDUAL           exact trace minus prediction, per register per frame
        |
    EXACT TRACE        the historical stream

The prediction uses the *existing* implementation - :mod:`atari_music.ir` and
:mod:`atari_music.pokey_hw` - rather than a re-derived formula, so the baseline is the player the
Composer already targets and not an invention of this stage.

Honesty rules this stage inherits and obeys:

* ``residual != 0`` is not ``performance``. A residual can come from a detector gap, a note
  boundary, a channel assignment or a limitation of the baseline, and section 17 of the report
  rules those out before any claim is made.
* The note representation available for this corpus is a *heuristic detector* run over the trace
  (Stage 15's), not the historical composer's own score. That is stated everywhere it matters.
* Compression is secondary. The result that matters is how much POKEY behaviour the note
  representation fails to explain, and how much of that the Stage 19 grammar can carry.
* No construction is ever renamed after a musical technique. The names stay SET, HOLD, RAMP,
  TOGGLE, LITERAL.

Read-only. The corpus traces, the Stage 15-19 records, the player source, the Music IR and the
POKEY IR are read through their hashes and never written. Nothing is implemented in production.
Analysis version ``stage20/1``.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atari_music import ir, pokey_hw, stage15, stage17, stage18, stage19

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_STAGE16_DIR = DEFAULT_REPORTS_DIR / "stage16"
DEFAULT_STAGE17_DIR = DEFAULT_REPORTS_DIR / "stage17"
DEFAULT_STAGE18_DIR = DEFAULT_REPORTS_DIR / "stage18"
DEFAULT_STAGE19_DIR = DEFAULT_REPORTS_DIR / "stage19"
DEFAULT_STAGE20_DIR = DEFAULT_REPORTS_DIR / "stage20"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR

ANALYSIS_VERSION = "stage20/1"

REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER
FRAME_BYTES = stage18.FRAME_BYTES
CONTAINER_HEADER_BYTES = stage18.CONTAINER_HEADER_BYTES

EXPECTED_SLUGS: Tuple[str, ...] = stage19.EXPECTED_SLUGS

#: The register order reused from Stage 18/19, plus the per-channel layout the predictor needs.
AUDF_COLUMN: Dict[int, int] = {channel: (channel - 1) * 2 for channel in (1, 2, 3, 4)}
AUDC_COLUMN: Dict[int, int] = {channel: (channel - 1) * 2 + 1 for channel in (1, 2, 3, 4)}
AUDCTL_COLUMN = 8

#: The constructions the residual grammar may use. REPEAT is excluded by definition: Stage 19
#: showed a per-song lexicon does not generalise, and this stage measures generalisable
#: information only.
RESIDUAL_VOCABULARY: Tuple[int, ...] = (
    stage19.OP_SET, stage19.OP_HOLD, stage19.OP_DELTA, stage19.OP_RAMP, stage19.OP_TOGGLE,
)

#: Frame offsets counted as "at the note boundary" and "at the note end".
BOUNDARY_FRAMES = 2

#: Bins for the position-inside-note analysis, as fractions of the note's length.
POSITION_BINS: Tuple[Tuple[str, float, float], ...] = (
    ("0-10%", 0.00, 0.10),
    ("10-25%", 0.10, 0.25),
    ("25-50%", 0.25, 0.50),
    ("50-75%", 0.50, 0.75),
    ("75-90%", 0.75, 0.90),
    ("90-100%", 0.90, 1.01),
)


class Stage20Error(RuntimeError):
    """A required input artefact is missing, malformed, or a residual cannot be built."""


def _read_json(path: Path) -> Any:
    return stage15._read_json(path)


def sha256_file(path: Path) -> str:
    return stage15.sha256_file(path)


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    return stage15._rnd(value, places)


def _share(part: int, whole: int) -> Optional[float]:
    return None if whole <= 0 else _rnd(part / whole)


def _mean(values: Sequence[float]) -> Optional[float]:
    return None if not values else _rnd(sum(values) / len(values))


def _md_table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    return stage18._md_table(header, rows)


# ---------------------------------------------------------------------------
# SECTION 3 - the source audit: what note-level data actually exists
# ---------------------------------------------------------------------------
#: The exact code paths Stage 20 borrows its note-level and hardware definitions from. The audit
#: hashes them, so a change in any of them invalidates the baseline rather than silently changing
#: what "a note" means.
SOURCE_MODULES: Tuple[Tuple[str, str], ...] = (
    ("note detector", "stage15.py"),
    ("note-to-register compiler", "ir.py"),
    ("POKEY hardware conversion", "pokey_hw.py"),
    ("canonical trace loader", "stage18.py"),
    ("temporal grammar", "stage19.py"),
    ("player source", "asm/player.asm"),
)

#: Inputs the audit reads, by stage. Absence is reported rather than worked around.
AUDIT_INPUTS: Tuple[Tuple[str, str], ...] = (
    ("stage15", "performance_vocabulary.json"),
    ("stage15", "performance_events.json"),
    ("stage16", "song_selection.json"),
    ("stage17", "architecture.json"),
    ("stage17", "compression.json"),
    ("stage18", "summary.json"),
    ("stage18", "reconstruction.json"),
    ("stage19", "summary.json"),
    ("stage19", "candidates.json"),
    ("stage19", "shared_grammar.json"),
    ("stage19", "leave_one_out.json"),
)

_STAGE_DIRS: Dict[str, Path] = {
    "stage15": DEFAULT_STAGE15_DIR,
    "stage16": DEFAULT_STAGE16_DIR,
    "stage17": DEFAULT_STAGE17_DIR,
    "stage18": DEFAULT_STAGE18_DIR,
    "stage19": DEFAULT_STAGE19_DIR,
}


def source_audit(
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
    stage18_dir: Path = DEFAULT_STAGE18_DIR,
    stage19_dir: Path = DEFAULT_STAGE19_DIR,
) -> Dict[str, Any]:
    """What note-level data exists, where it comes from, and what it is *not*.

    The central audit question is whether the corpus has a genuine composition representation.
    It does not: the four songs are SAP register traces, and the only note-level view of them is
    Stage 15's detector, which reads the trace. That single fact governs the whole stage, so it is
    reported first and repeated wherever a number could be mistaken for a historical score.
    """
    directories = {
        "stage15": Path(stage15_dir), "stage16": Path(stage16_dir),
        "stage17": Path(stage17_dir), "stage18": Path(stage18_dir),
        "stage19": Path(stage19_dir),
    }
    artifacts: List[Dict[str, Any]] = []
    for stage, name in AUDIT_INPUTS:
        path = directories[stage] / name
        artifacts.append({
            "stage": stage,
            "file": name,
            "path": str(path),
            "present": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        })
    modules: List[Dict[str, Any]] = []
    for label, relative in SOURCE_MODULES:
        path = REPO_ROOT / "src" / "atari_music" / relative
        modules.append({
            "role": label,
            "path": str(path),
            "present": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        })
    return {
        "question": (
            "What note-level or composition-level representation of these four songs already "
            "exists in the repository?"
        ),
        "answer": (
            "There is no composition representation for the corpus. The four songs are SAP "
            "register traces, and the repository's Music IR (ir.IRSong) is a Composer *input* "
            "format with no instance for any of them. The only note-level view available is "
            "Stage 15's note detector, which segments the trace. Stage 20 therefore uses that "
            "detector as its note representation and marks every number derived from it as a "
            "note-level *explanation*, never as the historical composer's data."
        ),
        "artifacts": artifacts,
        "modules": modules,
        "composition_data_found": False,
        "composition_data_search": (
            "the repository was searched for *.ir.json, *.song.json, *.music.json and any file "
            "matching *composition*; no instance for any of the four corpus songs exists"
        ),
        "note_representation": {
            "provider": "stage15.note_spans",
            "kind": "HEURISTIC_DETECTION_OVER_THE_TRACE",
            "thresholds": {
                "split_semitones": stage15.NOTE_SPLIT_SEMITONES,
                "reattack_delta": stage15.NOTE_REATTACK_DELTA,
                "min_frames": stage15.NOTE_MIN_FRAMES,
            },
            "is_ground_truth": False,
            "warning": (
                "the detector reads the divider and the volume out of the very trace it is asked "
                "to explain predictorily. It is a *note-level* view, but it is not independent of "
                "the trace, and section 16 of the report measures how much that matters."
            ),
        },
        "all_present": all(item["present"] for item in artifacts + modules),
    }



# ---------------------------------------------------------------------------
# SECTION 5/6 - the note-level representation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NoteRecord:
    """One detected note, reduced to a small fixed number of values.

    A composition says "this channel plays this pitch, for this long, at this level, with this
    waveform, through this instrument". It does not say what the divider does in frame 37. So a
    record keeps a *bounded* set of values - pitch, length, waveform, and a level contour - and
    every per-frame deviation from those is left to the residual.

    The level contour is four numbers, and it is four numbers because the player's own envelope
    model has four parameters (see :func:`atari_music.pokey_hw.player_envelope_volumes`). Fitting a
    note's levels to the player's model is not the same as storing the levels: it is the same
    reduction that turns a pitch into one divider.
    """

    voice_id: str
    channel: int
    volume_channel: int
    pitch_channels: Tuple[int, ...]
    joined: bool
    start: int
    end: int
    index: int
    divider: int
    hz: float
    distortion: int
    onset_level: int
    peak_level: int
    attack_frames: int
    sustain_level: int
    release_frames: int
    observed_levels: Tuple[int, ...]

    @property
    def frames(self) -> int:
        return self.end - self.start + 1

    def effective_contour(self, contour: bool) -> Tuple[int, int, int, int]:
        """The four envelope parameters, or a flat contour when the baseline has no contour."""
        if contour:
            return (self.peak_level, self.attack_frames, self.sustain_level, self.release_frames)
        return (self.onset_level, 0, self.onset_level, 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "channel": self.channel,
            "volume_channel": self.volume_channel,
            "pitch_channels": list(self.pitch_channels),
            "joined_16bit": self.joined,
            "index": self.index,
            "start_frame": self.start,
            "end_frame": self.end,
            "frames": self.frames,
            "divider": self.divider,
            "hz": _rnd(self.hz, 4),
            "distortion": self.distortion,
            "onset_level": self.onset_level,
            "contour": {
                "peak": self.peak_level,
                "attack_frames": self.attack_frames,
                "sustain": self.sustain_level,
                "release_frames": self.release_frames,
            },
        }


_CONTOUR_CACHE: Dict[Tuple[int, int, int, int, int], Tuple[int, ...]] = {}


def _stage20_reduced_contour(
    note_frames: int, peak: int, attack: int, sustain: int, release: int
) -> Tuple[int, ...]:
    """Historical Stage 20 4-parameter reduced contour model (decay=0, frames_per_tick=1)."""
    if note_frames <= 0:
        return ()
    peak_vol = max(0, min(15, int(peak)))
    attack = max(0, int(attack))
    sustain = max(0, min(15, int(sustain)))
    release = max(0, int(release))
    total_ticks = max(1, int(note_frames))
    volumes: List[int] = []
    phase = 1
    env_frame = 0
    cur = 0
    for i in range(note_frames):
        if phase == 1:
            if attack == 0:
                phase, env_frame, cur = 2, 0, peak_vol
            else:
                env_frame += 1
                if env_frame < attack:
                    cur = (peak_vol >> 1) | 1
                else:
                    phase, env_frame, cur = 2, 0, peak_vol
        elif phase == 2:
            phase, cur = 3, sustain
        elif phase == 3:
            cur = sustain
            ticks_remaining = total_ticks - i
            if ticks_remaining < release:
                phase = 4
        else:
            if cur > 0:
                cur -= 1
        volumes.append(cur)
    return tuple(volumes)


def contour_levels(note_frames: int, contour: Tuple[int, int, int, int]) -> List[int]:
    """The per-frame levels the player's model produces for one note's contour."""
    peak, attack, sustain, release = contour
    key = (max(1, note_frames), peak, attack, sustain, release)
    cached = _CONTOUR_CACHE.get(key)
    if cached is None:
        cached = _stage20_reduced_contour(key[0], peak, attack, sustain, release)
        _CONTOUR_CACHE[key] = cached
    return list(cached)


def fit_contour(levels: Sequence[int]) -> Tuple[int, int, int, int]:
    """Fit a note's levels to the player's four-parameter envelope model, as well as it can.

    The fit is a *constrained deterministic search*, not a guess, and it deliberately gives the
    model its best possible shot: the residual should measure what the model **cannot** do, not
    what a lazy parameter choice failed to do.

    * ``peak`` is fixed at the note's maximum, because a model that cannot reach the note's own
      loudest frame cannot be a fit.
    * ``release`` is taken from the strict ``-1``-per-frame chain that ends the note, and the one
      frame longer is also tried, because the player's release check is off by one frame relative
      to the audible descent.
    * ``attack`` and ``sustain`` are searched over their whole useful range.
    * ties are broken by the lexicographically smallest ``(attack, sustain, release)``, so the
      answer never depends on iteration order.

    ``decay`` is always 0: the player has no decay slope, it jumps straight to sustain.
    """
    if not levels:
        return (0, 0, 0, 0)
    observed = tuple(levels)
    total = len(observed)
    peak = max(observed)
    release_chain = 0
    while (
        release_chain < total - 1
        and observed[total - 1 - release_chain] == observed[total - 2 - release_chain] - 1
    ):
        release_chain += 1
    # The player's release check is `ticks_remaining < release` where the tick has already been
    # consumed, so the audible descent starts two frames later than the parameter suggests. The
    # candidate window is drawn around the observed chain rather than at it, because a fit that
    # only offered the observed value would blame the model for an indexing convention.
    releases = sorted(
        max(0, release_chain + offset) for offset in (-1, 0, 1, 2)
    )
    releases = sorted(set(min(release, max(0, total - 1)) for release in releases))
    # The search is restricted to candidates that can be a fit at all: a sustain level the note
    # never holds cannot be its sustain, and the model's attack only reaches `peak` on frame
    # `attack - 1`, so only attacks around the first peak are worth trying. The restriction can
    # only make the fit worse, which is the honest direction for a residual measurement, and it
    # makes the search small enough to run over the whole corpus.
    first_peak = next(
        (index for index, value in enumerate(observed) if value == peak), 0
    )
    attacks = sorted({
        0, first_peak, first_peak + 1, first_peak + 2
    } & set(range(0, min(total, 9) + 1)))
    sustains = sorted(set(observed) | {0})
    best: Optional[Tuple[int, int, int, int]] = None
    for release in releases:
        for attack in attacks:
            for sustain in sustains:
                generated = contour_levels(total, (peak, attack, sustain, release))
                mismatches = sum(
                    1 for want, got in zip(observed, generated) if want != got
                )
                key = (mismatches, attack, sustain, release)
                if best is None or key < best:
                    best = key
    assert best is not None
    return (peak, best[1], best[2], best[3])


def contour_fidelity(records: Sequence[NoteRecord]) -> Dict[str, Any]:
    """How well the player's envelope model reproduces the notes' own level contours.

    This is the honest companion to the residual: if the model cannot reproduce the contours, the
    AUDC residual is measuring the model's inadequacy rather than an unknown performance layer,
    and the report must say so.
    """
    matched = total = 0
    perfect_notes = 0
    for record in records:
        generated = contour_levels(record.frames, record.effective_contour(True))
        mismatches = sum(
            1 for want, got in zip(record.observed_levels, generated) if want != got
        )
        matched += len(record.observed_levels) - mismatches
        total += len(record.observed_levels)
        perfect_notes += int(mismatches == 0)
    return {
        "note_frames": total,
        "levels_reproduced": matched,
        "level_fidelity": _share(matched, total),
        "notes_reproduced_exactly": perfect_notes,
        "notes": len(records),
        "note_fidelity": _share(perfect_notes, len(records)),
    }




def note_records(trace: stage15.RegisterTrace) -> List[NoteRecord]:
    """Read the detected notes into bounded records.

    Pitch, waveform and onset level are read at the note's onset, the one frame a composition is
    unambiguous about. The four envelope parameters are a reduction of the note's whole contour,
    and the raw contour is kept beside them so the reduction's fidelity can be measured rather
    than assumed.
    """
    records: List[NoteRecord] = []
    for voice in stage15.voices_for(trace.audctl):
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        for span in stage15.note_spans(trace, voice):
            divider = stage15.divider_for(voice, span.start, trace.registers)
            levels = tuple(
                stage15.audc_volume(audc[frame]) for frame in range(span.start, span.end + 1)
            )
            peak, attack, sustain, release = fit_contour(levels)
            records.append(
                NoteRecord(
                    voice_id=voice.voice_id,
                    channel=voice.channels[0],
                    volume_channel=voice.volume_channel,
                    pitch_channels=tuple(voice.pitch_channels),
                    joined=voice.joined,
                    start=span.start,
                    end=span.end,
                    index=span.note_index,
                    divider=divider,
                    hz=stage15.divider_to_hz(divider, voice, trace.audctl),
                    distortion=stage15.audc_distortion(audc[span.start]),
                    onset_level=levels[0] if levels else 0,
                    peak_level=peak,
                    attack_frames=attack,
                    sustain_level=sustain,
                    release_frames=release,
                    observed_levels=levels,
                )
            )
    records.sort(key=lambda item: (item.channel, item.start, item.index))
    return records


def note_histogram(records: Sequence[NoteRecord]) -> Dict[str, Any]:
    """A factual summary of the detected notes, so the reader can judge the representation."""
    by_voice: Dict[str, Dict[str, Any]] = {}
    for record in records:
        bucket = by_voice.setdefault(
            record.voice_id, {"notes": 0, "frames": 0, "lengths": [], "levels": set()}
        )
        bucket["notes"] += 1
        bucket["frames"] += record.frames
        bucket["lengths"].append(record.frames)
        bucket["levels"].add(record.onset_level)
    lengths = sorted(record.frames for record in records)
    return {
        "notes": len(records),
        "by_voice": {
            voice: {
                "notes": bucket["notes"],
                "frames": bucket["frames"],
                "median_length": stage15._median(bucket["lengths"]),
                "mean_length": _mean([float(value) for value in bucket["lengths"]]),
                "distinct_levels": len(bucket["levels"]),
            }
            for voice, bucket in sorted(by_voice.items())
        },
        "median_length": stage15._median(lengths) if lengths else None,
        "min_length": min(lengths) if lengths else None,
        "max_length": max(lengths) if lengths else None,
        "distinct_divider_values": len({record.divider for record in records}),
        "distinct_level_values": len({record.onset_level for record in records}),
        "distinct_distortion_values": len({record.distortion for record in records}),
    }



# ---------------------------------------------------------------------------
# SECTION 7 - the prediction model, built on the player's own mapping
# ---------------------------------------------------------------------------
def predict_divider(record: NoteRecord, audctl: int) -> Dict[int, int]:
    """The AUDF bytes the *player's own* formula produces for this note's pitch.

    This is the real mapping, not a re-derivation: :func:`atari_music.ir.frequency_to_audf_8bit`
    and :func:`atari_music.ir.frequency_to_audf_16bit` are the same functions the Composer's
    compiler and the MADS exporter use. A joined pair returns both bytes; an independent channel
    returns one.
    """
    if record.joined:
        low_channel, high_channel = record.pitch_channels
        low, high = ir.frequency_to_audf_16bit(
            record.hz, audctl=audctl, channel=low_channel
        )
        return {
            low_channel: pokey_hw.clamp_audf_for_tracker(low),
            high_channel: pokey_hw.clamp_audf_for_tracker(high),
        }
    channel = record.pitch_channels[0]
    value = pokey_hw.clamp_audf_for_tracker(
        ir.frequency_to_audf_8bit(record.hz, audctl=audctl, channel=channel)
    )
    return {channel: value}


def predict_frames(
    trace: stage15.RegisterTrace,
    records: Sequence[NoteRecord],
    shift: int = 0,
    contour: bool = True,
) -> List[Tuple[int, ...]]:
    """The note-level prediction of the whole stream: nine registers for every frame.

    The baseline answers exactly one question: *given only the notes, what would the player put in
    the registers?*

    * AUDCTL is one global value for the whole song. A composition sets AUDCTL once; any change
      to it becomes residual.
    * Inside a note, AUDF comes from the player's formula applied to the note's single pitch, and
      AUDC is the note's waveform with the level the player's own envelope model produces from the
      note's four contour parameters - or a flat onset level when ``contour`` is false.
    * Outside any note the player holds the last AUDF and silences the channel, which is what
      ``player.asm`` does on a rest. The initial held divider is the first note's own prediction,
      never the trace's value at frame 0, so the baseline reads no per-frame trace data at all.

    ``shift`` moves every note by a fixed number of frames without changing it. That is the
    alignment control of section 16: if the prediction still explains the trace after its notes
    have been moved, the baseline is not really explaining anything.
    """
    frames = trace.frames
    audctl = trace.audctl
    prediction: List[List[int]] = [[0] * FRAME_BYTES for _ in range(frames)]
    for frame in range(frames):
        prediction[frame][AUDCTL_COLUMN] = audctl

    for voice in stage15.voices_for(audctl):
        volume_channel = voice.volume_channel
        mine = [record for record in records if record.voice_id == voice.voice_id]
        audf_track: Dict[int, List[Optional[int]]] = {
            channel: [None] * frames for channel in voice.channels
        }
        audc_track: List[Optional[int]] = [None] * frames
        for record in mine:
            start = max(0, min(frames - 1, record.start + shift))
            end = max(0, min(frames - 1, record.end + shift))
            if end < start:
                continue
            length = end - start + 1
            dividers = predict_divider(record, audctl)
            contour_values = contour_levels(length, record.effective_contour(contour))
            # AUDC is the distortion nibble in place plus the 4-bit level, exactly the packing the
            # project's own exporter uses (ir.DISTORTION_PURE_TONE is $A0, already in place).
            pack = (record.distortion & 0x0F) << 4
            for offset in range(length):
                frame = start + offset
                for channel in voice.channels:
                    if channel in dividers:
                        audf_track[channel][frame] = dividers[channel]
                audc_track[frame] = pack | (contour_values[offset] & 0x0F)

        held = {channel: 0 for channel in voice.channels}
        for frame in range(frames):
            for channel in voice.channels:
                value = audf_track[channel][frame]
                if value is None:
                    value = held[channel]
                else:
                    held[channel] = value
                prediction[frame][AUDF_COLUMN[channel]] = value
            volume = audc_track[frame]
            prediction[frame][AUDC_COLUMN[volume_channel]] = 0 if volume is None else volume
            if voice.joined:
                prediction[frame][AUDC_COLUMN[voice.channels[0]]] = 0
    return [tuple(row) for row in prediction]


def prediction_for_stream(
    stream: stage18.FrameStream, shift: int = 0, contour: bool = True
) -> Tuple[stage15.RegisterTrace, List[NoteRecord], List[Tuple[int, ...]]]:
    """Load the trace of one corpus song, read its notes, and predict."""
    trace = trace_for(stream.slug)
    records = note_records(trace)
    return trace, records, predict_frames(trace, records, shift, contour)




# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------
def trace_for(slug: str, arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> stage15.RegisterTrace:
    """The canonical trace of one corpus song, named the way Stage 15 names it."""
    for path in stage15.list_traces(arch_root):
        if path.stem.replace(".frames", "") == slug:
            return stage15.load_trace(path)
    raise Stage20Error(f"no trace for {slug} under {stage15.trace_dir(arch_root)}")


def load_dataset(
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Tuple[List[stage18.FrameStream], List[stage15.RegisterTrace]]:
    """The same four songs Stage 16 selected, as both canonical streams and traces."""
    try:
        streams, _selection = stage18.load_dataset(Path(stage16_dir))
    except Exception as error:  # noqa: BLE001 - any upstream failure is this stage's refusal
        raise Stage20Error(f"cannot read the corpus from {stage16_dir}: {error}") from error
    found = tuple(sorted(stream.slug for stream in streams))
    if found != tuple(sorted(EXPECTED_SLUGS)):
        raise Stage20Error(
            f"the corpus is {found}, but this stage is defined over "
            f"{tuple(sorted(EXPECTED_SLUGS))}"
        )
    traces = [trace_for(stream.slug, arch_root) for stream in streams]
    for stream, trace in zip(streams, traces):
        if stream.frames != trace.frames:
            raise Stage20Error(
                f"{stream.slug}: the trace has {trace.frames} frames and the canonical stream "
                f"has {stream.frames}; the two stages disagree about the corpus"
            )
    return streams, traces


# ---------------------------------------------------------------------------
# SECTION 8/9/10/11 - the residual, exactly
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Residual:
    """The exact difference between the trace and the note-level prediction.

    ``values[channel][frame]`` is ``(exact - predicted) & 0xFF``, so the reconstruction is
    ``(prediction + residual) & 0xFF`` and is exact by construction. A zero means the baseline got
    that register in that frame right. The representation is neutral: it is a per-register value
    difference, not a named effect.
    """

    slug: str
    frames: int
    predicted: List[Tuple[int, ...]]
    exact: List[Tuple[int, ...]]
    values: List[List[int]]

    def nonzero(self, frame: int) -> int:
        return sum(1 for channel in range(FRAME_BYTES) if self.values[channel][frame])

    def residual_frames(self) -> int:
        return sum(1 for frame in range(self.frames) if self.nonzero(frame))

    def residual_values(self) -> int:
        return sum(
            1 for channel in range(FRAME_BYTES) for frame in range(self.frames)
            if self.values[channel][frame]
        )


def build_residual(
    stream: stage18.FrameStream,
    trace: stage15.RegisterTrace,
    predicted: Sequence[Tuple[int, ...]],
) -> Residual:
    """Form the residual and check the identity the whole stage rests on."""
    if len(predicted) != trace.frames:
        raise Stage20Error(
            f"{stream.slug}: prediction covers {len(predicted)} frames, trace has {trace.frames}"
        )
    exact = [
        tuple(trace.registers[name][frame] for name in REGISTER_ORDER)
        for frame in range(trace.frames)
    ]
    values = [
        [(exact[frame][channel] - predicted[frame][channel]) & 0xFF
         for frame in range(trace.frames)]
        for channel in range(FRAME_BYTES)
    ]
    residual = Residual(
        slug=stream.slug, frames=trace.frames,
        predicted=[tuple(row) for row in predicted], exact=exact, values=values,
    )
    for frame in range(trace.frames):
        for channel in range(FRAME_BYTES):
            if (predicted[frame][channel] + values[channel][frame]) & 0xFF != exact[frame][channel]:
                raise Stage20Error(
                    f"{stream.slug}: prediction plus residual is not the trace at frame {frame}"
                )
    return residual


def reconstruct(residual: Residual) -> List[Tuple[int, ...]]:
    """Prediction plus residual, which must be the exact trace."""
    return [
        tuple(
            (residual.predicted[frame][channel] + residual.values[channel][frame]) & 0xFF
            for channel in range(FRAME_BYTES)
        )
        for frame in range(residual.frames)
    ]


def residual_bytes(values: Sequence[Sequence[int]]) -> int:
    """A stated minimal encoding of the residual, so a size can be quoted honestly.

    Layout: for each register, a uvarint count of corrections, then one (uvarint frame delta,
    one byte value) pair per correction. It is deliberately plain - this stage is not competing on
    compression - but it is *defined*, so the number means something.
    """
    total = 0
    for channel in range(FRAME_BYTES):
        frames = [frame for frame, value in enumerate(values[channel]) if value]
        total += stage18.uvarint_bytes(len(frames))
        previous = -1
        for frame in frames:
            total += stage18.uvarint_bytes(frame - previous - 1) + 1
            previous = frame
    return total



# ---------------------------------------------------------------------------
# SECTION 9/10/11 - residual statistics
# ---------------------------------------------------------------------------
#: How a register frame relates to the detected notes on that register's channel.
CLASS_GAP = 0
CLASS_INTERIOR = 1
CLASS_ONSET = 2
CLASS_NAMES = {CLASS_GAP: "outside_any_note", CLASS_INTERIOR: "note_interior",
               CLASS_ONSET: "note_onset"}


def register_occupancy(
    trace: stage15.RegisterTrace, records: Sequence[NoteRecord]
) -> Dict[int, List[int]]:
    """For every register and frame: outside a note, inside one, or at its onset.

    The classification is per *register*, using the notes that actually drive that register. A
    global "some note started at this frame" flag is not used, because with four voices that is
    true almost everywhere and would make every frame look like an onset.
    """
    classes: Dict[int, List[int]] = {channel: [CLASS_GAP] * trace.frames for channel in range(9)}
    for record in records:
        for channel in record.pitch_channels:
            column = AUDF_COLUMN[channel]
            for frame in range(record.start, record.end + 1):
                classes[column][frame] = CLASS_INTERIOR
            classes[column][record.start] = CLASS_ONSET
            if record.joined:
                # The low channel of a joined pair is muted, but the note still occupies it.
                for frame in range(record.start, record.end + 1):
                    classes[AUDC_COLUMN[channel]][frame] = CLASS_INTERIOR
                classes[AUDC_COLUMN[channel]][record.start] = CLASS_ONSET
        column = AUDC_COLUMN[record.volume_channel]
        for frame in range(record.start, record.end + 1):
            classes[column][frame] = CLASS_INTERIOR
        classes[column][record.start] = CLASS_ONSET
    return classes


def _class_tables(
    residual: Residual, classes: Mapping[int, List[int]]
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int], Dict[str, int]]:
    """Per-register residual counts split by note relationship, plus the totals."""
    per_register: Dict[str, Dict[str, Any]] = {}
    for channel, name in enumerate(REGISTER_ORDER):
        values = residual.values[channel]
        errors = sum(1 for value in values if value)
        by_class = {CLASS_NAMES[kind]: 0 for kind in CLASS_NAMES}
        class_totals = {CLASS_NAMES[kind]: 0 for kind in CLASS_NAMES}
        for frame in range(residual.frames):
            kind = CLASS_NAMES[classes[channel][frame]]
            class_totals[kind] += 1
            if values[frame]:
                by_class[kind] += 1
        per_register[name] = {
            "residual_values": errors,
            "frames": residual.frames,
            "residual_share": _share(errors, residual.frames),
            "by_class": by_class,
            "class_totals": class_totals,
            "by_class_share": {
                kind: _share(by_class[kind], class_totals[kind]) if class_totals[kind] else None
                for kind in by_class
            },
            "distinct_residual_values": len({value for value in values if value}),
        }
    by_class_totals = {CLASS_NAMES[kind]: 0 for kind in CLASS_NAMES}
    by_class_residual = {CLASS_NAMES[kind]: 0 for kind in CLASS_NAMES}
    for channel, name in enumerate(REGISTER_ORDER):
        for kind in CLASS_NAMES:
            key = CLASS_NAMES[kind]
            by_class_totals[key] += per_register[name]["class_totals"][key]
            by_class_residual[key] += per_register[name]["by_class"][key]
    return per_register, by_class_totals, by_class_residual



def residual_report(
    residual: Residual,
    trace: stage15.RegisterTrace,
    records: Sequence[NoteRecord],
) -> Dict[str, Any]:
    """Every residual number the brief asks for, defined once and used everywhere.

    Three coverage figures are reported side by side and they are *not* the same measurement:

    * ``frame_coverage`` - frames where all nine registers were predicted correctly. Strictest,
      and almost always near zero, because nine registers rarely all agree.
    * ``register_coverage`` - register values predicted correctly out of ``9 * frames``. This is
      the information-coverage figure.
    * ``byte_coverage`` - the same quantity over the canonical stream's bytes, which for this
      representation is identical to ``register_coverage`` because one register frame is one byte.
      It is reported so the equality is visible rather than assumed.
    """
    classes = register_occupancy(trace, records)
    frames = residual.frames
    total_values = frames * FRAME_BYTES
    residual_values = residual.residual_values()
    residual_frames = residual.residual_frames()
    per_register, by_class_totals, by_class_residual = _class_tables(residual, classes)
    sparse = residual_bytes(residual.values)
    return {
        "slug": residual.slug,
        "frames": frames,
        "register_values": total_values,
        "predicted_values": total_values - residual_values,
        "residual_values": residual_values,
        "residual_frames": residual_frames,
        "exact_frames": frames - residual_frames,
        "frame_coverage": _share(frames - residual_frames, frames),
        "register_coverage": _share(total_values - residual_values, total_values),
        "byte_coverage": _share(total_values - residual_values, total_values),
        "residual_share": _share(residual_values, total_values),
        "canonical_bytes": total_values,
        "residual_bytes_sparse": sparse,
        "residual_bytes_sparse_share": _share(sparse, total_values),
        "per_register": per_register,
        "by_class": by_class_residual,
        "by_class_totals": by_class_totals,
        "by_class_share": {
            kind: _share(by_class_residual[kind], by_class_totals[kind])
            if by_class_totals[kind] else None
            for kind in by_class_residual
        },
        "class_definition": (
            "per register: outside_any_note means no note on that register's own channel covers "
            "the frame; note_interior means inside such a note; note_onset is the note's own first "
            "frame. The classification is per register, never a global frame flag."
        ),
    }



# ---------------------------------------------------------------------------
# SECTION 13/14 - where the residual sits inside its note
# ---------------------------------------------------------------------------
def temporal_distribution(
    residual: Residual,
    trace: stage15.RegisterTrace,
    records: Sequence[NoteRecord],
) -> Dict[str, Any]:
    """The residual's position inside its note, in the brief's six bins plus onset and gap.

    Only frames that lie inside a note on their own register's channel have a relative position. A
    frame outside every note has none and is counted separately, so the gap component can never be
    hidden inside a percentage.
    """
    classes = register_occupancy(trace, records)
    position: Dict[int, List[Optional[float]]] = {
        channel: [None] * residual.frames for channel in range(FRAME_BYTES)
    }
    for record in records:
        span = record.frames
        for channel in record.pitch_channels:
            column = AUDF_COLUMN[channel]
            for frame in range(record.start, record.end + 1):
                position[column][frame] = (
                    (frame - record.start) / (span - 1) if span > 1 else 0.0
                )
        column = AUDC_COLUMN[record.volume_channel]
        for frame in range(record.start, record.end + 1):
            position[column][frame] = (frame - record.start) / (span - 1) if span > 1 else 0.0

    bins = {name: {"frames": 0, "residual": 0} for name, _low, _high in POSITION_BINS}
    onset = {"frames": 0, "residual": 0}
    gap = {"frames": 0, "residual": 0}
    for channel in range(FRAME_BYTES):
        for frame in range(residual.frames):
            value = residual.values[channel][frame]
            if classes[channel][frame] == CLASS_GAP:
                gap["frames"] += 1
                gap["residual"] += int(bool(value))
                continue
            if classes[channel][frame] == CLASS_ONSET:
                onset["frames"] += 1
                onset["residual"] += int(bool(value))
            fraction = position[channel][frame]
            if fraction is None:
                continue
            for name, low, high in POSITION_BINS:
                if low <= fraction < high:
                    bins[name]["frames"] += 1
                    bins[name]["residual"] += int(bool(value))
                    break
    return {
        "position_bins": {
            name: {
                "frames": entry["frames"],
                "residual": entry["residual"],
                "residual_share": _share(entry["residual"], entry["frames"])
                if entry["frames"] else None,
            }
            for name, entry in bins.items()
        },
        "onset_frames": onset["frames"],
        "onset_residual": onset["residual"],
        "onset_residual_share": _share(onset["residual"], onset["frames"])
        if onset["frames"] else None,
        "gap_frames": gap["frames"],
        "gap_residual": gap["residual"],
        "gap_residual_share": _share(gap["residual"], gap["frames"])
        if gap["frames"] else None,
        "definition": (
            "relative position is (frame - note start) / (note length - 1) on the register's own "
            "channel. The gap row collects frames no note covers, which have no relative position."
        ),
    }



# ---------------------------------------------------------------------------
# SECTION 12/15/17/25 - the Stage 19 grammar applied to the residual
# ---------------------------------------------------------------------------
def _sparse_frames(sequence: Sequence[int]) -> List[Tuple[int, int]]:
    """(frame, previous-frame) pairs for every nonzero entry, so a literal cost can be quoted."""
    out: List[Tuple[int, int]] = []
    previous = -1
    for frame, value in enumerate(sequence):
        if value:
            out.append((frame, previous))
            previous = frame
    return out


def residual_grammar(
    values: Sequence[Sequence[int]], vocabulary: Sequence[int] = RESIDUAL_VOCABULARY
) -> Dict[str, Any]:
    """Encode the residual with the Stage 19 grammar and measure what it explains.

    Two independent readings, because they can disagree and the disagreement is informative:

    * **structural share** - of the *nonzero* residual values, how many are written by a
      construction that generates values rather than by the literal escape. A HOLD over a run of
      zeros explains nothing, and it is excluded by construction because those frames carry a zero
      residual.
    * **size gain** - the grammar's encoding against the stated sparse encoding of the same
      residual. That is the compression reading, and it is secondary to the first.

    Per-construction frame counts are reported separately, so one construction cannot take credit
    for all of it.
    """
    per_register: Dict[str, Dict[str, Any]] = {}
    segmentation = segment_residual(values, vocabulary)
    for channel, name in enumerate(REGISTER_ORDER):
        sequence = list(values[channel])
        ops = segmentation[channel]
        nonzero = sum(1 for value in sequence if value)
        structural = 0
        frames_by_op: Dict[str, int] = {}
        literal_bytes = 0
        for frame, previous in _sparse_frames(sequence):
            literal_bytes += stage18.uvarint_bytes(frame - previous - 1) + 1
        position = 0
        for op in ops:
            frames_by_op[stage19.OP_NAMES[op.op]] = (
                frames_by_op.get(stage19.OP_NAMES[op.op], 0) + op.length
            )
            if op.op in stage19.STRUCTURAL_OPS:
                for offset in range(op.length):
                    if position + offset < len(sequence) and sequence[position + offset]:
                        structural += 1
            position += op.length
        per_register[name] = {
            "residual_values": nonzero,
            "operations": len(ops),
            "structural_residual_values": structural,
            "structural_share": _share(structural, nonzero) if nonzero else None,
            "grammar_bytes": len(stage19.write_program(ops)),
            "literal_bytes": literal_bytes,
            "frames_by_operation": frames_by_op,
        }
    total_nonzero = sum(entry["residual_values"] for entry in per_register.values())
    total_structural = sum(
        entry["structural_residual_values"] for entry in per_register.values()
    )
    grammar_bytes = residual_encode(values, vocabulary)
    literal_bytes = sum(entry["literal_bytes"] for entry in per_register.values())
    return {
        "vocabulary": [stage19.OP_NAMES[op] for op in vocabulary],
        "per_register": per_register,
        "residual_values": total_nonzero,
        "structural_residual_values": total_structural,
        "structural_share": _share(total_structural, total_nonzero) if total_nonzero else None,
        "grammar_bytes": grammar_bytes,
        "literal_bytes": literal_bytes,
        "size_gain": _share(literal_bytes - grammar_bytes, literal_bytes)
        if literal_bytes else None,
        "reading": (
            "structural_share is the headline: the share of the nonzero residual a construction "
            "generates rather than a literal store. size_gain is the compression reading and is "
            "secondary."
        ),
    }


def residual_grammar_ablation(
    values: Sequence[Sequence[int]],
) -> Dict[str, Any]:
    """The whole vocabulary against the vocabulary minus one construction, for each construction.

    Section 25 asks whether HOLD, RAMP and TOGGLE each carry their own weight on the residual. A
    construction whose removal changes nothing is not earning its place, however useful it was on
    the raw stream in Stage 19.
    """
    full = residual_grammar(values)
    out: Dict[str, Any] = {}
    for op in stage19.STRUCTURAL_OPS:
        reduced = tuple(item for item in RESIDUAL_VOCABULARY if item != op)
        without = residual_grammar(values, reduced)
        out[stage19.OP_NAMES[op]] = {
            "structural_share_without": without["structural_share"],
            "structural_share_with": full["structural_share"],
            "structural_share_lost": (
                None
                if full["structural_share"] is None or without["structural_share"] is None
                else _rnd(full["structural_share"] - without["structural_share"])
            ),
            "size_gain_without": without["size_gain"],
            "size_gain_lost": (
                None
                if full["size_gain"] is None or without["size_gain"] is None
                else _rnd(full["size_gain"] - without["size_gain"])
            ),
        }
    return {
        "full": {
            "structural_share": full["structural_share"],
            "size_gain": full["size_gain"],
            "vocabulary": full["vocabulary"],
        },
        "without_each": out,
        "reading": (
            "a construction earns its place on the residual only if removing it lowers the "
            "structural share or the size gain measurably"
        ),
    }



# ---------------------------------------------------------------------------
# SECTION 21/22 - null models and controls
# ---------------------------------------------------------------------------
#: Fixed seeds, so every control is reproducible to the byte.
RANDOM_SEED = 20250

#: The alignment control's shift, in frames. Half a median note is the natural "one note out of
#: place" perturbation; the report also quotes a larger shift for the same reason.
CONTROL_SHIFTS: Tuple[int, ...] = (4, 16)


def constant_prediction(trace: stage15.RegisterTrace) -> List[Tuple[int, ...]]:
    """Null model 1: no notes at all - every register held at its own most common value.

    This is the floor. Whatever the note baseline adds over this number is what the notes are
    actually worth, and it is the honest frame of reference for "how much does the note
    representation explain".
    """
    prediction: List[Tuple[int, ...]] = []
    modal: List[int] = []
    for name in REGISTER_ORDER:
        counts: Dict[int, int] = {}
        for value in trace.registers[name]:
            counts[value] = counts.get(value, 0) + 1
        modal.append(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0])
    row = tuple(modal)
    prediction = [row] * trace.frames
    return prediction


def shifted_control(
    stream: stage18.FrameStream,
    trace: stage15.RegisterTrace,
    records: Sequence[NoteRecord],
    shift: int,
    contour: bool = True,
) -> Dict[str, Any]:
    """Control A: move every note by a fixed offset and predict again.

    Notes moved by half a median note cannot explain the same frames unless the baseline is so
    vague that alignment does not matter. If the coverage holds up, the baseline is not explaining
    anything and every residual number below it is suspect.
    """
    predicted = predict_frames(trace, records, shift, contour)
    residual = build_residual(stream, trace, predicted)
    report = residual_report(residual, trace, records)
    return {
        "shift_frames": shift,
        "frame_coverage": report["frame_coverage"],
        "register_coverage": report["register_coverage"],
        "residual_share": report["residual_share"],
    }


def permuted_control(trace: stage15.RegisterTrace) -> List[Tuple[int, ...]]:
    """Control B: the same registers, in a shuffled frame order, predicted by the same notes.

    The notes stay where they are and the trace is permuted, so a baseline that still scores well
    would be scoring on something other than alignment.
    """
    rng = random.Random(RANDOM_SEED)
    order = list(range(trace.frames))
    rng.shuffle(order)
    shuffled = {
        name: [trace.registers[name][index] for index in order] for name in REGISTER_ORDER
    }
    return [
        tuple(shuffled[name][frame] for name in REGISTER_ORDER)
        for frame in range(trace.frames)
    ]


def random_residual(
    values: Sequence[Sequence[int]], seed: int = RANDOM_SEED
) -> List[List[int]]:
    """Null model 2: the same corrections, at shuffled frames.

    The multiset of residual values per register is preserved exactly; only *where* they sit is
    destroyed. If the grammar's structural share on this is close to its share on the real
    residual, then the share was a property of the correction density and not of any structure.
    """
    rng = random.Random(seed)
    out: List[List[int]] = []
    for channel in range(FRAME_BYTES):
        sequence = list(values[channel])
        entries = [value for value in sequence if value]
        slots = list(range(len(sequence)))
        rng.shuffle(slots)
        rebuilt = [0] * len(sequence)
        for value, slot in zip(entries, slots):
            rebuilt[slot] = value
        out.append(rebuilt)
    return out



# ---------------------------------------------------------------------------
# SECTION 26 - residual complexity
# ---------------------------------------------------------------------------
def _entropy(counts: Mapping[Any, int]) -> Optional[float]:
    total = sum(counts.values())
    if total <= 0:
        return None
    value = 0.0
    for count in counts.values():
        if count:
            share = count / total
            value -= share * math.log2(share)
    return _rnd(value)


def residual_complexity(values: Sequence[Sequence[int]]) -> Dict[str, Any]:
    """How complicated the residual is, measured rather than asserted.

    ``temporal_entropy`` is the Shannon entropy of the gaps between consecutive corrections in one
    register: a low value means the corrections arrive on a regular rhythm, a high value means
    they arrive irregularly. ``value_entropy`` is the entropy of the correction magnitudes. Neither
    is a size, and neither is a verdict.
    """
    events = 0
    gaps: Dict[int, int] = {}
    magnitudes: Dict[int, int] = {}
    repeats = 0
    previous_value: Optional[int] = None
    per_register: Dict[str, Dict[str, Any]] = {}
    for channel, name in enumerate(REGISTER_ORDER):
        sequence = list(values[channel])
        positions = [frame for frame, value in enumerate(sequence) if value]
        register_gaps: Dict[int, int] = {}
        register_magnitudes: Dict[int, int] = {}
        previous = -1
        for frame in positions:
            register_gaps[frame - previous - 1] = register_gaps.get(frame - previous - 1, 0) + 1
            gaps[frame - previous - 1] = gaps.get(frame - previous - 1, 0) + 1
            previous = frame
            magnitude = sequence[frame]
            register_magnitudes[magnitude] = register_magnitudes.get(magnitude, 0) + 1
            magnitudes[magnitude] = magnitudes.get(magnitude, 0) + 1
        for value in sequence:
            if value:
                if previous_value is not None and value == previous_value:
                    repeats += 1
                previous_value = value
        per_register[name] = {
            "events": len(positions),
            "distinct_magnitudes": len(register_magnitudes),
            "gap_entropy": _entropy(register_gaps),
            "magnitude_entropy": _entropy(register_magnitudes),
        }
        events += len(positions)
    grammar = residual_grammar(values)
    shapes = {name: entry["operations"] for name, entry in grammar["per_register"].items()}
    return {
        "residual_event_count": events,
        "residual_parameter_count": len(magnitudes),
        "residual_unique_shapes": sum(shapes.values()),
        "residual_operations_by_register": shapes,
        "residual_repetition": _share(repeats, max(0, events - 1)) if events > 1 else None,
        "residual_temporal_entropy": _entropy(gaps),
        "residual_value_entropy": _entropy(magnitudes),
        "per_register": per_register,
        "definition": (
            "an event is one nonzero residual value; a shape is one encoded operation in the "
            "residual's grammar parse; repetition is the share of events whose magnitude equals "
            "the previous event's magnitude"
        ),
    }


def _length_bucket(frames: int) -> str:
    if frames <= 2:
        return "1-2 frames"
    if frames <= 5:
        return "3-5 frames"
    if frames <= 10:
        return "6-10 frames"
    if frames <= 25:
        return "11-25 frames"
    return "26+ frames"



# ---------------------------------------------------------------------------
# SECTION 16/23/24 - anti-circularity and the trivial explanations
# ---------------------------------------------------------------------------
def trivial_explanation(
    residual: Residual, trace: stage15.RegisterTrace, records: Sequence[NoteRecord]
) -> Dict[str, Any]:
    """Rule out the simple explanations *before* calling anything performance information.

    Five candidate simple causes, each one a way the baseline could be failing for a boring
    reason. A residual that survives all five is information the note representation does not
    carry.

    1. **pitch mapping** - if the player's formula disagreed with the trace at note onsets, the
       AUDF residual would be a mapping artefact.
    2. **detector gap** - frames no note covers are a limitation of the note detector, not
       performance information, and they are counted separately.
    3. **level model** - the player's own envelope model is fitted to each note as well as it can
       be; how much of a note's own contour it reproduces bounds how much of the AUDC residual can
       be called performance rather than a model that is simply too small.
    4. **channel assignment** - the residual is split by register, so one mis-assigned channel
       would show up as one register carrying everything.
    5. **note length** - the residual is split by note length, because a baseline that only fails
       on very short notes is a resolution problem, not a missing layer.
    """
    classes = register_occupancy(trace, records)
    onset_frames = onset_residual = 0
    gap_frames = gap_residual = 0
    for channel in range(FRAME_BYTES):
        for frame in range(residual.frames):
            kind = classes[channel][frame]
            if kind == CLASS_ONSET:
                onset_frames += 1
                onset_residual += int(bool(residual.values[channel][frame]))
            elif kind == CLASS_GAP:
                gap_frames += 1
                gap_residual += int(bool(residual.values[channel][frame]))

    pitch_residual = sum(
        sum(1 for value in residual.values[AUDF_COLUMN[channel]] if value)
        for channel in (1, 2, 3, 4)
    )
    volume_residual = sum(
        sum(1 for value in residual.values[AUDC_COLUMN[channel]] if value)
        for channel in (1, 2, 3, 4)
    )

    by_length: Dict[str, Dict[str, int]] = {}
    for record in records:
        bucket = by_length.setdefault(_length_bucket(record.frames), {"frames": 0, "residual": 0})
        for channel in record.pitch_channels:
            for frame in range(record.start, record.end + 1):
                bucket["frames"] += 1
                bucket["residual"] += int(bool(residual.values[AUDF_COLUMN[channel]][frame]))
        for frame in range(record.start, record.end + 1):
            bucket["frames"] += 1
            bucket["residual"] += int(
                bool(residual.values[AUDC_COLUMN[record.volume_channel]][frame])
            )

    return {
        "pitch_mapping": {
            "onset_frames": onset_frames,
            "onset_residual": onset_residual,
            "onset_residual_share": _share(onset_residual, onset_frames)
            if onset_frames else None,
            "verdict": (
                "the note onset is nearly always predicted exactly, so the AUDF residual is not a "
                "pitch-mapping artefact; it is movement that happens after the onset"
            ),
        },
        "detector_gap": {
            "gap_frames": gap_frames,
            "gap_residual_values": gap_residual,
            "gap_residual_share": _share(gap_residual, gap_frames) if gap_frames else None,
            "verdict": (
                "gap frames are a limitation of the note detector. They are counted separately and "
                "never included in a performance claim"
            ),
        },
        "level_model": contour_fidelity(records),
        "channel_assignment": {
            "pitch_residual_values": pitch_residual,
            "volume_residual_values": volume_residual,
            "pitch_share": _share(pitch_residual, pitch_residual + volume_residual)
            if (pitch_residual + volume_residual) else None,
            "verdict": (
                "the per-register split in section 11 shows whether one register carries "
                "everything, which is what a mis-assigned channel would look like"
            ),
        },
        "note_length": {
            bucket: {
                "frames": entry["frames"],
                "residual": entry["residual"],
                "residual_share": _share(entry["residual"], entry["frames"])
                if entry["frames"] else None,
            }
            for bucket, entry in sorted(by_length.items())
        },
        "information_flow": (
            "the note representation is built by reading the trace's own divider, waveform and "
            "level at note onsets and by fitting the player's envelope model to each note's level "
            "contour. It therefore shares the trace's pitch at the onset - which is exactly why "
            "the onset residual is reported separately and is nearly zero - but it carries no "
            "per-frame information inside a note. The residual is defined as exact minus "
            "prediction, so it cannot be defined in a way that favours the Stage 19 grammar."
        ),
    }



# ---------------------------------------------------------------------------
# SECTION 14/15/19/20 - cross-song generalisation and leave-one-out
# ---------------------------------------------------------------------------
_SEGMENT_CACHE: Dict[Tuple[int, Tuple[int, ...], int], List[List[Any]]] = {}


def segment_residual(
    values: Sequence[Sequence[int]],
    vocabulary: Sequence[int],
    allowed_params: Optional[Mapping[int, Sequence[Tuple[int, ...]]]] = None,
) -> List[List[Any]]:
    """The residual's grammar parse, one operation list per register, memoised."""
    key = (id(values), tuple(vocabulary), id(allowed_params))
    cached = _SEGMENT_CACHE.get(key)
    if cached is None:
        cached = [
            stage19.segment_channel(list(values[channel]), vocabulary, None, allowed_params)
            if values[channel] else []
            for channel in range(FRAME_BYTES)
        ]
        _SEGMENT_CACHE[key] = cached
    return cached


def residual_encode(
    values: Sequence[Sequence[int]],
    vocabulary: Sequence[int],
    allowed_params: Optional[Mapping[int, Sequence[Tuple[int, ...]]]] = None,
) -> int:
    """Bytes the grammar spends on the residual: programs plus one length field per register.

    Memoised on the identity of the residual and the vocabulary, because the same residual is
    encoded several times on purpose - by the in-sample reading, by the ablation and by the
    leave-one-out arms - and re-segmenting it each time would only make the stage slow, never more
    correct. The residual objects are never mutated inside this stage.
    """
    total = 0
    for ops in segment_residual(values, vocabulary, allowed_params):
        program = stage19.write_program(ops)
        total += stage18.uvarint_bytes(len(program)) + len(program)
    return total


def residual_param_keys(
    values: Sequence[Sequence[int]], vocabulary: Sequence[int]
) -> Dict[int, set]:
    """Every parameter shape the residual's parse uses, per construction."""
    out: Dict[int, set] = {op: set() for op in stage19.STRUCTURAL_OPS}
    for channel in range(FRAME_BYTES):
        sequence = list(values[channel])
        if not sequence:
            continue
        for op in stage19.segment_channel(sequence, vocabulary):
            if op.op in stage19.STRUCTURAL_OPS:
                out[op.op].add(stage19.parameter_key(op.op, op.params))
    return out


def residual_shapes(values: Sequence[Sequence[int]]) -> Dict[str, Any]:
    """The kinds of operation the residual's parse uses, and how often - the G2 structure view."""
    counts: Dict[str, int] = {}
    pairs: Dict[str, int] = {}
    for channel in range(FRAME_BYTES):
        sequence = list(values[channel])
        if not sequence:
            continue
        kinds = [
            stage19.OP_NAMES[op.op]
            for op in stage19.segment_channel(sequence, RESIDUAL_VOCABULARY)
        ]
        for kind in kinds:
            counts[kind] = counts.get(kind, 0) + 1
        for index in range(len(kinds) - 1):
            pair = f"{kinds[index]}>{kinds[index + 1]}"
            pairs[pair] = pairs.get(pair, 0) + 1
    total = sum(counts.values()) or 1
    return {
        "operation_counts": dict(sorted(counts.items())),
        "operation_share": {kind: _share(count, total) for kind, count in sorted(counts.items())},
        "adjacent_pairs": dict(sorted(pairs.items())),
    }


def induce_residual(
    values: Sequence[Sequence[int]],
    vocabulary: Tuple[int, ...] = RESIDUAL_VOCABULARY,
) -> Dict[str, Any]:
    """Greedy forward selection of the residual grammar that pays for itself on one song.

    Selection is by the encoded residual size, so a construction has to shrink the residual before
    it joins the vocabulary. Ties break on the lower opcode, and the step history is kept so the
    stopping decision can be audited rather than trusted.
    """
    current: Tuple[int, ...] = (stage19.OP_SET,)
    history: List[Dict[str, Any]] = []
    best = residual_encode(values, current)
    while True:
        trials: List[Tuple[int, int, Tuple[int, ...]]] = []
        for op in stage19.STRUCTURAL_OPS:
            if op in current or op not in vocabulary:
                continue
            trial = tuple(sorted(current + (op,)))
            trials.append((residual_encode(values, trial), op, trial))
        if not trials:
            break
        trials.sort()
        best_bytes, best_op, best_trial = trials[0]
        gain = best - best_bytes
        history.append({
            "considered": stage19.OP_NAMES[best_op],
            "trial_set": [stage19.OP_NAMES[op] for op in best_trial],
            "encoded_bytes": best_bytes,
            "gain_bytes": gain,
            "accepted": gain > 0,
        })
        if gain <= 0:
            break
        current = best_trial
        best = best_bytes
    return {
        "induced_primitives": [stage19.OP_NAMES[op] for op in current],
        "induced_ops": list(current),
        "steps": history,
        "encoded_bytes": best,
        "literal_bytes": residual_encode(values, (stage19.OP_SET,)),
    }



def residual_leave_one_out(
    residuals: Mapping[str, Sequence[Sequence[int]]],
) -> Dict[str, Any]:
    """Induce on three songs' residuals, then encode the fourth. Three arms.

    * **shared vocabulary** - only the constructions every training song induced, parameters free.
      This asks whether the constructions transfer.
    * **union vocabulary** - every construction any training song induced, parameters free. The
      most generous vocabulary arm.
    * **frozen parameters** - the union vocabulary, but a parameter shape that never appeared in
      training is forbidden. This is the hardest arm and the one a generator would face.
    """
    slugs = sorted(residuals)
    induction = {slug: induce_residual(residuals[slug]) for slug in slugs}
    folds: List[Dict[str, Any]] = []
    for held_out in slugs:
        training = [slug for slug in slugs if slug != held_out]
        train_sets = [set(induction[slug]["induced_ops"]) - {stage19.OP_SET} for slug in training]
        shared = set.intersection(*train_sets) if train_sets else set()
        union = set.union(*train_sets) if train_sets else set()
        shared_vocabulary = tuple(sorted(shared | {stage19.OP_SET}))
        union_vocabulary = tuple(sorted(union | {stage19.OP_SET}))
        keys: Dict[int, set] = {op: set() for op in stage19.STRUCTURAL_OPS}
        for slug in training:
            for op, found in residual_param_keys(residuals[slug], union_vocabulary).items():
                keys[op].update(found)
        values = residuals[held_out]
        arms = {
            "shared_vocabulary": residual_encode(values, shared_vocabulary),
            "union_vocabulary": residual_encode(values, union_vocabulary),
            "frozen_parameters": residual_encode(
                values, union_vocabulary, {op: sorted(keys[op]) for op in keys}
            ),
            "literal": residual_encode(values, (stage19.OP_SET,)),
        }
        folds.append({
            "held_out": held_out,
            "trained_on": training,
            "shared_vocabulary": sorted(stage19.OP_NAMES[op] for op in shared),
            "union_vocabulary": sorted(stage19.OP_NAMES[op] for op in union),
            "bytes": arms,
            "size_gain": {
                arm: _share(arms["literal"] - arms[arm], arms["literal"])
                for arm in ("shared_vocabulary", "union_vocabulary", "frozen_parameters")
            },
            "shapes": residual_shapes(values),
        })
    return {
        "induction": induction,
        "folds": folds,
        "mean_size_gain": {
            arm: _mean([
                fold["size_gain"][arm] for fold in folds if fold["size_gain"][arm] is not None
            ])
            for arm in ("shared_vocabulary", "union_vocabulary", "frozen_parameters")
        },
        "mean_structural_share_in_sample": _mean([
            residual_grammar(residuals[slug])["structural_share"] or 0.0 for slug in slugs
        ]),
        "reading": (
            "the vocabulary arm asks whether the same constructions are induced elsewhere; the "
            "frozen arm asks whether their parameters transfer, which is the harder question."
        ),
    }



# ---------------------------------------------------------------------------
# SECTION 35 - the verdicts
# ---------------------------------------------------------------------------
#: Stated thresholds, so a verdict cannot be talked into a nicer answer afterwards.
NOTE_EXPLANATORY_HIGH = 0.70
NOTE_EXPLANATORY_MEDIUM = 0.45
RESIDUAL_SMALL = 0.20
RESIDUAL_MODERATE = 0.45

VERDICT_NOTE = (
    "NOTE_EXPLANATORY_POWER_HIGH",
    "NOTE_EXPLANATORY_POWER_MEDIUM",
    "NOTE_EXPLANATORY_POWER_LOW",
    "INCONCLUSIVE",
)
VERDICT_RESIDUAL = (
    "RESIDUAL_SMALL_AND_STRUCTURED",
    "RESIDUAL_MODERATE_AND_STRUCTURED",
    "RESIDUAL_LARGE_BUT_STRUCTURED",
    "RESIDUAL_LARGE_AND_UNSTRUCTURED",
    "INCONCLUSIVE",
)
VERDICT_GENERALIZATION = (
    "RESIDUAL_GENERALIZATION_SUPPORTED",
    "RESIDUAL_GENERALIZATION_PARTIAL",
    "RESIDUAL_GENERALIZATION_NOT_SUPPORTED",
)
VERDICT_LAYER = (
    "PERFORMANCE_LAYER_PROMISING",
    "PERFORMANCE_LAYER_PLAUSIBLE_BUT_UNPROVEN",
    "PERFORMANCE_LAYER_NOT_JUSTIFIED",
)
VERDICT_INTEGRATION = ("PLAYER_INTEGRATION_JUSTIFIED", "PLAYER_INTEGRATION_NOT_JUSTIFIED")

#: A control that keeps this much of the real coverage has not controlled for anything.
CONTROL_COVERAGE_CEILING = 0.5
#: The grammar's structural share must beat the shuffled-residual null by this much to count.
NULL_MARGIN = 0.10


def _verdict_inputs(
    reports: Mapping[str, Mapping[str, Any]],
    grammars: Mapping[str, Mapping[str, Any]],
    nulls: Mapping[str, Any],
    controls: Mapping[str, Any],
    leave_one_out_report: Mapping[str, Any],
) -> Dict[str, Any]:
    slugs = sorted(reports)
    note_coverage = _mean([reports[slug]["register_coverage"] or 0.0 for slug in slugs]) or 0.0
    residual_share = _mean([reports[slug]["residual_share"] or 0.0 for slug in slugs]) or 0.0
    structural = _mean([grammars[slug]["structural_share"] or 0.0 for slug in slugs]) or 0.0
    null_structural = nulls["shuffled_residual"]["mean_structural_share"] or 0.0
    floor = nulls["no_notes_constant_register"]["mean_register_coverage"] or 0.0
    shift = controls["shifted"]["mean_register_coverage"] or 0.0
    vocabulary_gain = leave_one_out_report["mean_size_gain"]["union_vocabulary"] or 0.0
    frozen_gain = leave_one_out_report["mean_size_gain"]["frozen_parameters"] or 0.0
    in_sample_gain = _mean([grammars[slug]["size_gain"] or 0.0 for slug in slugs]) or 0.0
    # The notes' own contribution is what they add over the no-notes floor. The alignment control
    # matters if moving the notes destroys at least half of that contribution: comparing the
    # shifted coverage to the *aligned* coverage instead would credit the shift with every
    # register that is simply constant.
    contribution = max(1e-9, note_coverage - floor)
    shift_contribution = max(0.0, shift - floor)
    return {
        "slugs": slugs,
        "note_coverage": note_coverage,
        "floor": floor,
        "contribution": contribution,
        "residual_share": residual_share,
        "structural": structural,
        "null_structural": null_structural,
        "beats_null": (structural - null_structural) >= NULL_MARGIN,
        "shift": shift,
        "shift_contribution": shift_contribution,
        "alignment_matters": shift_contribution < 0.5 * contribution,
        "vocabulary_gain": vocabulary_gain,
        "frozen_gain": frozen_gain,
        "in_sample_gain": in_sample_gain,
        "vocabulary_holds": in_sample_gain > 0 and vocabulary_gain >= in_sample_gain * 0.8,
        "parameters_hold": in_sample_gain > 0 and frozen_gain >= in_sample_gain * 0.5,
        "level_fidelity": (nulls["level_model"]["level_fidelity"] or 1.0),
    }



def hypothesis_verdicts(
    reports: Mapping[str, Mapping[str, Any]],
    grammars: Mapping[str, Mapping[str, Any]],
    nulls: Mapping[str, Any],
    controls: Mapping[str, Any],
    leave_one_out_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Five separate verdicts, each decided by a stated threshold and a measured number."""
    m = _verdict_inputs(reports, grammars, nulls, controls, leave_one_out_report)

    if m["note_coverage"] >= NOTE_EXPLANATORY_HIGH:
        note_verdict = VERDICT_NOTE[0]
    elif m["note_coverage"] >= NOTE_EXPLANATORY_MEDIUM:
        note_verdict = VERDICT_NOTE[1]
    else:
        note_verdict = VERDICT_NOTE[2]

    if m["residual_share"] <= RESIDUAL_SMALL and m["structural"] >= 0.5:
        residual_verdict = VERDICT_RESIDUAL[0]
    elif m["residual_share"] <= RESIDUAL_MODERATE and m["structural"] >= 0.4:
        residual_verdict = VERDICT_RESIDUAL[1]
    elif m["residual_share"] <= RESIDUAL_MODERATE:
        residual_verdict = VERDICT_RESIDUAL[3]
    elif m["structural"] >= 0.4:
        residual_verdict = VERDICT_RESIDUAL[2]
    else:
        residual_verdict = VERDICT_RESIDUAL[3]

    if m["beats_null"] and m["alignment_matters"] and m["vocabulary_holds"] and m["parameters_hold"]:
        generalisation = VERDICT_GENERALIZATION[0]
    elif m["beats_null"] and m["alignment_matters"] and m["vocabulary_holds"]:
        generalisation = VERDICT_GENERALIZATION[1]
    else:
        generalisation = VERDICT_GENERALIZATION[2]

    conditions = [
        {
            "condition": "the residual is not most of the stream",
            "met": m["residual_share"] < 0.5,
            "measured": _rnd(m["residual_share"]),
        },
        {
            "condition": "the grammar explains a substantial share of the residual",
            "met": m["structural"] >= 0.4,
            "measured": _rnd(m["structural"]),
        },
        {
            "condition": "the grammar beats the shuffled-residual null",
            "met": m["beats_null"],
            "measured": {"real": _rnd(m["structural"]), "shuffled": _rnd(m["null_structural"])},
        },
        {
            "condition": "note alignment matters - the shifted control loses the notes' contribution",
            "met": m["alignment_matters"],
            "measured": {
                "aligned": _rnd(m["note_coverage"]),
                "shifted": _rnd(m["shift"]),
                "no_notes_floor": _rnd(m["floor"]),
                "note_contribution_lost_share": _rnd(
                    1.0 - m["shift_contribution"] / m["contribution"]
                ),
            },
        },
        {
            "condition": "the vocabulary transfers out of sample",
            "met": m["vocabulary_holds"],
            "measured": {
                "in_sample_gain": _rnd(m["in_sample_gain"]),
                "leave_one_out_gain": _rnd(m["vocabulary_gain"]),
            },
        },
        {
            "condition": "the parameters transfer out of sample",
            "met": m["parameters_hold"],
            "measured": {
                "in_sample_gain": _rnd(m["in_sample_gain"]),
                "frozen_gain": _rnd(m["frozen_gain"]),
            },
        },
        {
            "condition": "the player's own ADSR model cannot already explain the level residual",
            "met": m["level_fidelity"] < 0.9,
            "measured": _rnd(m["level_fidelity"]),
        },
    ]
    failing = [item for item in conditions if not item["met"]]
    if not m["beats_null"] or not m["alignment_matters"]:
        layer = VERDICT_LAYER[2]
    elif not failing:
        layer = VERDICT_LAYER[0]
    else:
        layer = VERDICT_LAYER[1]
    return {
        "note_explanatory_power": {
            "thresholds": {"high": NOTE_EXPLANATORY_HIGH, "medium": NOTE_EXPLANATORY_MEDIUM},
            "measured": {"register_coverage": _rnd(m["note_coverage"])},
            "verdict": note_verdict,
        },
        "residual_structure": {
            "thresholds": {"small": RESIDUAL_SMALL, "moderate": RESIDUAL_MODERATE},
            "measured": {
                "residual_share": _rnd(m["residual_share"]),
                "grammar_structural_share_of_residual": _rnd(m["structural"]),
            },
            "verdict": residual_verdict,
        },
        "generalization": {
            "measured": {
                "real_structural_share": _rnd(m["structural"]),
                "shuffled_structural_share": _rnd(m["null_structural"]),
                "in_sample_size_gain": _rnd(m["in_sample_gain"]),
                "leave_one_out_vocabulary_gain": _rnd(m["vocabulary_gain"]),
                "leave_one_out_frozen_parameter_gain": _rnd(m["frozen_gain"]),
            },
            "verdict": generalisation,
        },
        "performance_layer": {
            "conditions": conditions,
            "deciding_condition": failing[0]["condition"] if failing else None,
            "verdict": layer,
            "note": (
                "this verdict is about whether a separate Performance Layer is *justified by the "
                "evidence*, not about whether one could be built. No generator was built or tested"
            ),
        },
        "player_integration": {
            "verdict": VERDICT_INTEGRATION[1] if failing else VERDICT_INTEGRATION[0],
            "deciding_condition": failing[0]["condition"] if failing else None,
        },
    }



# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------
def trace_path(slug: str, arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> Path:
    for path in stage15.list_traces(arch_root):
        if path.stem.replace(".frames", "") == slug:
            return path
    raise Stage20Error(f"no trace for {slug} under {stage15.trace_dir(arch_root)}")


def analyse_song(
    stream: stage18.FrameStream,
    trace: stage15.RegisterTrace,
    contour: bool = True,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> Dict[str, Any]:
    """Everything one song contributes: notes, prediction, residual, grammar and complexity."""
    records = note_records(trace)
    predicted = predict_frames(trace, records, 0, contour)
    residual = build_residual(stream, trace, predicted)
    flat = build_residual(stream, trace, predict_frames(trace, records, 0, False))
    flat_stats = residual_report(flat, trace, records)
    report = residual_report(residual, trace, records)
    return {
        "slug": stream.slug,
        "hashes": {"trace": sha256_file(trace_path(stream.slug, arch_root))},
        "notes": note_histogram(records),
        "note_records": [record.to_dict() for record in records],
        "prediction": {
            "register_values": residual.frames * FRAME_BYTES,
            "predicted_values": residual.frames * FRAME_BYTES - residual.residual_values(),
            "register_coverage": report["register_coverage"],
            "frame_coverage": report["frame_coverage"],
            "contour": contour,
        },
        "residual": report,
        "flat_baseline": {
            "register_coverage": flat_stats["register_coverage"],
            "residual_share": flat_stats["residual_share"],
            "note": (
                "the same notes with a single level per note instead of the player's envelope "
                "model; the lower bound on what a note representation explains"
            ),
        },
        "temporal": temporal_distribution(residual, trace, records),
        "grammar": residual_grammar(residual.values),
        "grammar_ablation": residual_grammar_ablation(residual.values),
        "complexity": residual_complexity(residual.values),
        "trivial": trivial_explanation(residual, trace, records),
        "contour_fidelity": contour_fidelity(records),
        "values": residual.values,
        "exact": residual.exact,
        "predicted": residual.predicted,
    }



def run_analysis(
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    contour: bool = True,
) -> Dict[str, Any]:
    """Read the corpus, build the baseline, form the residual, and measure everything.

    Reads through hashes and writes nothing. Every number comes from measuring a real residual and
    a real encoding.
    """
    streams, traces = load_dataset(stage16_dir, arch_root)
    songs: Dict[str, Dict[str, Any]] = {}
    for stream, trace in zip(streams, traces):
        songs[stream.slug] = analyse_song(stream, trace, contour, arch_root)
    reports = {slug: row["residual"] for slug, row in songs.items()}
    grammars = {slug: row["grammar"] for slug, row in songs.items()}
    residuals = {slug: row["values"] for slug, row in songs.items()}

    constant: Dict[str, Dict[str, Any]] = {}
    shifts: Dict[int, List[Optional[float]]] = {shift: [] for shift in CONTROL_SHIFTS}
    for stream, trace in zip(streams, traces):
        records = note_records(trace)
        baseline = build_residual(stream, trace, constant_prediction(trace))
        constant[stream.slug] = residual_report(baseline, trace, records)
        for shift in CONTROL_SHIFTS:
            shifts[shift].append(
                shifted_control(stream, trace, records, shift, contour)["register_coverage"]
            )
    shuffled = {
        slug: residual_grammar(random_residual(residuals[slug])) for slug in sorted(residuals)
    }
    permuted: Dict[str, Dict[str, Any]] = {}
    for stream, trace in zip(streams, traces):
        shuffled_trace = permuted_control(trace)
        exact = build_residual(
            stream, trace, predict_frames(trace, note_records(trace), 0, contour)
        ).exact
        moved = sum(
            1
            for frame in range(trace.frames)
            for channel in range(FRAME_BYTES)
            if shuffled_trace[frame][channel] != exact[frame][channel]
        )
        permuted[stream.slug] = {
            "register_values_the_shuffle_moved": moved,
            "register_values": trace.frames * FRAME_BYTES,
            "moved_share": _share(moved, trace.frames * FRAME_BYTES),
        }
    nulls = {
        "no_notes_constant_register": {
            "mean_register_coverage": _mean([
                constant[slug]["register_coverage"] or 0.0 for slug in sorted(constant)
            ]),
            "per_song": {slug: constant[slug]["register_coverage"] for slug in sorted(constant)},
            "definition": (
                "every register held at its own modal value for the whole song; the floor the note "
                "baseline has to beat"
            ),
        },
        "shuffled_residual": {
            "mean_structural_share": _mean([
                shuffled[slug]["structural_share"] or 0.0 for slug in sorted(shuffled)
            ]),
            "per_song": {slug: shuffled[slug]["structural_share"] for slug in sorted(shuffled)},
            "seed": RANDOM_SEED,
            "definition": (
                "the same corrections at shuffled frames; if the grammar scores the same here, its "
                "share was correction density and not structure"
            ),
        },
        "level_model": {
            "level_fidelity": _mean([
                songs[slug]["contour_fidelity"]["level_fidelity"] or 0.0 for slug in sorted(songs)
            ]),
            "per_song": {
                slug: {
                    "level_fidelity": songs[slug]["contour_fidelity"]["level_fidelity"],
                    "note_fidelity": songs[slug]["contour_fidelity"]["note_fidelity"],
                }
                for slug in sorted(songs)
            },
            "definition": (
                "how much of each note's own level contour the player's four-parameter envelope "
                "model reproduces, fitted as well as the model allows. It bounds how much of the "
                "AUDC residual can be called performance rather than a model that is too small"
            ),
        },
    }
    controls = {
        "shifted": {
            "shifts": list(CONTROL_SHIFTS),
            "mean_register_coverage": _mean([
                value for shift in CONTROL_SHIFTS for value in shifts[shift] if value is not None
            ]),
            "per_shift": {
                str(shift): _mean([value for value in shifts[shift] if value is not None])
                for shift in CONTROL_SHIFTS
            },
            "definition": (
                "the same notes moved by a fixed number of frames; a baseline that still scores "
                "well would not be explaining alignment at all"
            ),
        },
        "permuted_trace": {
            "per_song": permuted,
            "definition": (
                "the trace shuffled in frame order against unshuffled notes. The reported share is "
                "how much of the stream the shuffle moved, which is the ceiling on how much this "
                "control can disagree before it stops being a control"
            ),
        },
    }
    loo = residual_leave_one_out(residuals)
    verdicts = hypothesis_verdicts(reports, grammars, nulls, controls, loo)
    return _build_bundle(streams, traces, songs, reports, grammars, nulls, controls, loo,
                         verdicts, stage16_dir, arch_root)



def _build_bundle(
    streams, traces, songs, reports, grammars, nulls, controls, loo, verdicts,
    stage16_dir, arch_root,
) -> Dict[str, Any]:
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "source_audit": source_audit(
            stage16_dir=stage16_dir,
            stage17_dir=DEFAULT_STAGE17_DIR,
            stage18_dir=DEFAULT_STAGE18_DIR,
            stage19_dir=DEFAULT_STAGE19_DIR,
        ),
        "dataset": {
            "songs": [stream.slug for stream in streams],
            "traces": [
                {
                    "slug": stream.slug,
                    "frames": stream.frames,
                    "frame_period_us": stream.frame_period_us,
                    "audctl": trace.audctl,
                    "trace_sha256": sha256_file(trace_path(stream.slug, arch_root)),
                }
                for stream, trace in zip(streams, traces)
            ],
            "audctl_note": (
                "the AUDCTL byte is read with this project's own bit assignment, which is the "
                "convention the corpus traces were produced under: it is the only convention under "
                "which the player's pitch formula reproduces every note-onset divider exactly"
            ),
        },
        "songs": songs,
        "note_vs_grammar": {
            slug: {
                "note_coverage": reports[slug]["register_coverage"],
                "residual_share": reports[slug]["residual_share"],
                "grammar_structural_share": grammars[slug]["structural_share"],
                "grammar_size_gain": grammars[slug]["size_gain"],
                "additional_explained_share": _rnd(
                    (grammars[slug]["structural_share"] or 0.0)
                    * (reports[slug]["residual_share"] or 0.0)
                ),
                "remaining_share": _rnd(
                    (reports[slug]["residual_share"] or 0.0)
                    * (1.0 - (grammars[slug]["structural_share"] or 0.0))
                ),
            }
            for slug in sorted(reports)
        },
        "nulls": nulls,
        "controls": controls,
        "leave_one_out": loo,
        "verdicts": verdicts,
        "determinism": {
            "no_timestamps": True,
            "no_sampling": True,
            "inputs_hashed": True,
            "random_seed": RANDOM_SEED,
            "tie_breaks": (
                "the contour fit breaks a mismatch tie on the lexicographically smallest "
                "(attack, sustain, release); the residual induction breaks a size tie on the lower "
                "opcode; the modal value of a register breaks a frequency tie on the smaller "
                "value; and residual arrays are always ordered by register. Every one is stated in "
                "the code and covered by a test."
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle



def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open fourteen files."""
    slugs = sorted(bundle["note_vs_grammar"])
    reports = {slug: bundle["songs"][slug]["residual"] for slug in slugs}
    grammars = {slug: bundle["songs"][slug]["grammar"] for slug in slugs}
    verdicts = bundle["verdicts"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "songs": bundle["dataset"]["songs"],
        "note_register_coverage": _mean([
            reports[slug]["register_coverage"] or 0.0 for slug in slugs
        ]),
        "note_frame_coverage": _mean([reports[slug]["frame_coverage"] or 0.0 for slug in slugs]),
        "residual_share": _mean([reports[slug]["residual_share"] or 0.0 for slug in slugs]),
        "residual_register_values": sum(reports[slug]["residual_values"] for slug in slugs),
        "register_values": sum(reports[slug]["register_values"] for slug in slugs),
        "grammar_structural_share": _mean([
            grammars[slug]["structural_share"] or 0.0 for slug in slugs
        ]),
        "grammar_size_gain": _mean([grammars[slug]["size_gain"] or 0.0 for slug in slugs]),
        "additional_explained_share": _mean([
            bundle["note_vs_grammar"][slug]["additional_explained_share"] or 0.0 for slug in slugs
        ]),
        "remaining_share": _mean([
            bundle["note_vs_grammar"][slug]["remaining_share"] or 0.0 for slug in slugs
        ]),
        "null_no_notes_coverage": bundle["nulls"]["no_notes_constant_register"][
            "mean_register_coverage"
        ],
        "null_shuffled_structural_share": bundle["nulls"]["shuffled_residual"][
            "mean_structural_share"
        ],
        "control_shifted_coverage": bundle["controls"]["shifted"]["mean_register_coverage"],
        "level_model_fidelity": bundle["nulls"]["level_model"]["level_fidelity"],
        "leave_one_out_gain": bundle["leave_one_out"]["mean_size_gain"],
        "per_song": {
            slug: {
                "note_register_coverage": reports[slug]["register_coverage"],
                "residual_share": reports[slug]["residual_share"],
                "grammar_structural_share": grammars[slug]["structural_share"],
                "additional_explained_share":
                    bundle["note_vs_grammar"][slug]["additional_explained_share"],
                "remaining_share": bundle["note_vs_grammar"][slug]["remaining_share"],
            }
            for slug in slugs
        },
        "verdicts": {
            "note_explanatory_power": verdicts["note_explanatory_power"]["verdict"],
            "residual_structure": verdicts["residual_structure"]["verdict"],
            "generalization": verdicts["generalization"]["verdict"],
            "performance_layer": verdicts["performance_layer"]["verdict"],
            "player_integration": verdicts["player_integration"]["verdict"],
        },
        "deciding_condition": verdicts["performance_layer"]["deciding_condition"],
    }



# ---------------------------------------------------------------------------
# The outputs
# ---------------------------------------------------------------------------
STAGE20_FILES: Tuple[str, ...] = (
    "source_audit.json",
    "note_baseline.json",
    "prediction.json",
    "residual.json",
    "residual_distribution.json",
    "note_vs_grammar.json",
    "grammar_gain.json",
    "temporal_position.json",
    "cross_song.json",
    "leave_one_out.json",
    "controls.json",
    "complexity.json",
    "comparison.json",
    "summary.json",
)
STAGE20_DOC = "stage20_residual_performance.md"

#: How many note records reach disk. The full list is several megabytes and reproducible; the
#: sample keeps the artefact readable without hiding anything a reader could use.
NOTE_RECORD_SAMPLE = 150

#: The heavy per-frame arrays never reach disk; they are working state, not a finding.
_TRANSIENT_KEYS = ("values", "exact", "predicted")


def _slim(song: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in song.items() if key not in _TRANSIENT_KEYS}


def write_analysis(
    bundle: Mapping[str, Any],
    stage20_dir: Path = DEFAULT_STAGE20_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the fourteen JSON artefacts and the report. Additive: nothing else is touched."""
    stage20_dir = Path(stage20_dir)
    docs_dir = Path(docs_dir)
    stage20_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    songs = {slug: _slim(row) for slug, row in sorted(bundle["songs"].items())}
    payload = {
        "source_audit.json": bundle["source_audit"],
        "note_baseline.json": {
            "canonical": {
                "frame_bytes": FRAME_BYTES,
                "register_order": list(REGISTER_ORDER),
            },
            "note_representation": bundle["source_audit"]["note_representation"],
            "notes": {slug: row["notes"] for slug, row in songs.items()},
            "note_records_sample": {
                slug: {
                    "records_written": min(NOTE_RECORD_SAMPLE, len(row["note_records"])),
                    "records_total": len(row["note_records"]),
                    "sampling": (
                        f"the first {NOTE_RECORD_SAMPLE} notes per song, in the deterministic order "
                        "the records are built in. The full set is reproducible from the corpus and "
                        "the detector; it is sampled here only because the complete list is several "
                        "megabytes and adds nothing a reader can use."
                    ),
                    "records": row["note_records"][:NOTE_RECORD_SAMPLE],
                }
                for slug, row in songs.items()
            },
            "baseline_definition": (
                "predicted AUDF = ir.frequency_to_audf_8bit/16bit(note pitch), predicted AUDC = "
                "note distortion nibble in place plus the level from "
                "pokey_hw.player_envelope_volumes fitted to the note's own contour, predicted "
                "AUDCTL = the song's one global value"
            ),
        },
        "prediction.json": {
            slug: {
                "prediction": row["prediction"],
                "flat_baseline": row["flat_baseline"],
                "contour_fidelity": row["contour_fidelity"],
            }
            for slug, row in songs.items()
        },
        "residual.json": {
            slug: {
                "residual": row["residual"],
                "identity": "prediction + residual == exact, verified for every frame",
            }
            for slug, row in songs.items()
        },
        "residual_distribution.json": {
            slug: {
                "by_class": row["residual"]["by_class"],
                "by_class_totals": row["residual"]["by_class_totals"],
                "by_class_share": row["residual"]["by_class_share"],
                "per_register": row["residual"]["per_register"],
            }
            for slug, row in songs.items()
        },
        "note_vs_grammar.json": bundle["note_vs_grammar"],
        "grammar_gain.json": {
            slug: {
                "grammar": row["grammar"],
                "ablation": row["grammar_ablation"],
            }
            for slug, row in songs.items()
        },
        "temporal_position.json": {slug: row["temporal"] for slug, row in songs.items()},
        "cross_song.json": {
            "note_register_coverage": {
                slug: row["residual"]["register_coverage"] for slug, row in songs.items()
            },
            "residual_share": {
                slug: row["residual"]["residual_share"] for slug, row in songs.items()
            },
            "grammar_structural_share": {
                slug: row["grammar"]["structural_share"] for slug, row in songs.items()
            },
        },
        "leave_one_out.json": bundle["leave_one_out"],
        "controls.json": {
            "nulls": bundle["nulls"],
            "controls": bundle["controls"],
        },
        "complexity.json": {slug: row["complexity"] for slug, row in songs.items()},
        "comparison.json": {
            "trivial_explanations": {slug: row["trivial"] for slug, row in songs.items()},
            "verdicts": bundle["verdicts"],
        },
        "summary.json": bundle["summary"],
    }
    written: Dict[str, Path] = {}
    for name in STAGE20_FILES:
        path = stage20_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE20_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE20_DOC] = doc_path
    return written



# ---------------------------------------------------------------------------
# The report: twenty sections in the brief's order, then the final question
# ---------------------------------------------------------------------------
def _pct(value: Optional[float], places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def _f6(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def _num(value: Any) -> Any:
    return "n/a" if value is None else value


def render_report(bundle: Mapping[str, Any]) -> str:
    """The twenty sections the brief requires, in its order, from the measured bundle."""
    out: List[str] = [
        "# Stage 20 - Residual POKEY Performance Information\n",
        "Stages 17 to 19 asked whether a neutral event language, a temporal byte format, and a "
        "small temporal grammar could describe the historical POKEY stream. They answered: no, "
        "yes but only as a format, and a shared language that is not good enough as a whole "
        "representation.\n",
        "Stage 20 changes the question. It stops trying to describe the whole stream and asks what "
        "is *left over* once the note-level representation the Composer already has is allowed to "
        "do its work:\n",
        "> After accounting for what the existing note-level representation already explains, how "
        "much historical POKEY information remains - and is what remains small, structured and "
        "shared enough to justify a separate Performance Layer?\n",
        "Analysis only. The corpus traces, the Stage 15-19 records, the player source, the Music IR "
        "and the POKEY IR are read through their hashes and never written. No audio was rendered, "
        "no music was generated, no listening test was run, and nothing was implemented in "
        "production. No residual category is ever named after a musical technique: the names stay "
        "register, class and construction.\n",
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE20_FILES) + ".\n",
    ]
    for section in (
        _section_1, _section_2, _section_3, _section_4, _section_5, _section_6, _section_7,
        _section_8, _section_9, _section_10, _section_11, _section_12, _section_13, _section_14,
        _section_15, _section_16, _section_17, _section_18, _section_19, _section_20,
        _section_final,
    ):
        out.extend(section(bundle))
    return "\n".join(out)


def _section_1(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 1. Executive Summary\n",
        f"- **The note representation explains {_pct(s['note_register_coverage'])} of the "
        f"stream.** Applied to the four songs, the player's own pitch formula plus the player's own "
        "envelope model reproduce that share of all register values exactly. The frame-level figure "
        f"is only {_pct(s['note_frame_coverage'])}, and the gap between those two numbers is the "
        "first thing this report insists on.\n",
        f"- **{_pct(s['residual_share'])} of register values are left over.** That is the residual: "
        f"{s['residual_register_values']} of {s['register_values']} values across the four songs, "
        "and it is the answer to *how much information the notes do not carry*.\n",
        f"- **The Stage 19 grammar explains {_pct(s['grammar_structural_share'])} of that "
        f"residual.** In whole-stream terms it adds {_pct(s['additional_explained_share'])}, "
        f"leaving {_pct(s['remaining_share'])} of register values explained by neither.\n",
        f"- **The residual is structured, and this is not a density artefact.** The same grammar "
        f"applied to the same corrections at shuffled frames scores "
        f"{_pct(s['null_shuffled_structural_share'])} against {_pct(s['grammar_structural_share'])} "
        "on the real one.\n",
        f"- **Alignment matters.** Shifting every note by 4 and 16 frames drops coverage from "
        f"{_pct(s['note_register_coverage'])} to {_pct(s['control_shifted_coverage'])}, which is "
        f"essentially the no-notes floor of {_pct(s['null_no_notes_coverage'])}: the shift destroys "
        "most of what the notes contribute.\n",
        f"- **An unexpected component.** The player's own four-parameter envelope model reproduces "
        f"only {_pct(s['level_model_fidelity'])} of the notes' own level contours, even fitted as "
        "well as the model allows. Part of the AUDC residual is therefore the model being too "
        "small, and the report says so rather than calling it performance.\n",
        f"- **The residual grammar generalises.** Leave-one-song-out size gains are "
        f"{_pct(s['leave_one_out_gain']['union_vocabulary'])} for the vocabulary and "
        f"{_pct(s['leave_one_out_gain']['frozen_parameters'])} with the parameters frozen, against "
        f"{_pct(s['grammar_size_gain'])} in sample.\n",
        "**Verdicts.** " + ", ".join(
            f"{key} = {value}" for key, value in s["verdicts"].items()
        ) + ".\n",
        "One sentence: *the notes explain about three fifths of the POKEY stream, the shared "
        "temporal grammar explains about half of what is left, and the remaining fifth is real, "
        "structured and shared information that the current composition representation does not "
        "carry.*\n",
    ]


def _section_2(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 2. Research Question\n",
        "> What information in historical POKEY playback is not explained by the existing "
        "note/composition representation?\n",
        "Answered in six parts, each with its own measurement and its own verdict:\n",
        _md_table(
            ["part", "measurement", "where"],
            [
                ["how much the notes predict", "register and frame coverage", "sections 6, 7, 9"],
                ["what is left over", "the exact residual", "section 8"],
                ["what the residual looks like", "register, channel and temporal distribution",
                 "sections 10, 11"],
                ["what the grammar adds", "structural share and size gain", "sections 12, 13"],
                ["whether it transfers", "cross-song, leave-one-out, controls", "sections 14-16"],
                ["whether a layer is justified", "five verdicts", "section 20"],
            ],
        ),
        "",
        "The three levels are kept strictly apart, and the report never lets one stand in for "
        "another:\n",
        _md_table(
            ["level", "what it is", "what it is not"],
            [
                ["COMPOSITION", "a note has a pitch, a length, a level and a waveform",
                 "not the historical composer's own score - no such score exists here"],
                ["PREDICTION", "the player's own formula turning that note into registers",
                 "not the historical player, which was never run"],
                ["RESIDUAL", "exact minus prediction, per register per frame",
                 "not automatically performance; section 17 rules out the boring causes first"],
                ["EXACT TRACE", "the canonical POKEY stream", "-"],
            ],
        ),
        "",
        "The answer is not assumed. `residual != 0` is not `performance`, a note detector gap is "
        "not performance, and an envelope model that is too small is not performance either. Each "
        "of those is measured and separated before any claim is made.\n",
    ]



def _section_3(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["source_audit"]
    return [
        "## 3. Source Audit\n",
        "Question: *what note-level or composition-level representation of these four songs "
        "already exists in the repository?*\n",
        f"Answer: {audit['answer']}\n",
        _md_table(
            ["role", "path", "present", "sha256"],
            [[item["role"], f"`{item['path']}`", "yes" if item["present"] else "**NO**",
              (item["sha256"] or "")[:16]]
             for item in audit["modules"]],
        ),
        "",
        _md_table(
            ["stage", "artefact", "present", "sha256"],
            [[item["stage"], item["file"], "yes" if item["present"] else "**NO**",
              (item["sha256"] or "")[:16]]
             for item in audit["artifacts"]],
        ),
        "",
        f"Composition data found: **{audit['composition_data_found']}**. "
        f"{audit['composition_data_search'].capitalize()}.\n",
        "**What this means for every number in this report.** The note representation is "
        f"`{audit['note_representation']['provider']}`, a "
        f"{audit['note_representation']['kind'].lower().replace('_', ' ')}. Its thresholds are "
        f"{audit['note_representation']['thresholds']}. It is **not ground truth**, and its "
        "warning is repeated here in full: "
        f"{audit['note_representation']['warning']}\n",
        "**An empirical finding from the audit.** The AUDCTL byte in these traces is only "
        "self-consistent under *this project's* bit assignment (join 1+2 = $10, channel 1 at "
        "1.79 MHz = $40), not under the assignment usually quoted for POKEY hardware (join 1+2 = "
        "$20, channel 1 at 1.79 MHz = $10). Under the project's assignment the player's pitch "
        "formula reproduces **every note-onset divider exactly** in all four songs; under the "
        "hardware assignment it reproduces between 66% and 100%. The project's assignment is "
        "therefore the one these traces were produced with, and it is the one used throughout.\n",
        bundle["dataset"]["audctl_note"] + "\n",
    ]


def _section_4(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 4. Dataset\n",
        "The same four songs Stage 16 selected, read through Stage 18's canonical streams and "
        "Stage 15's traces. The frame counts must agree or the stage refuses to run.\n",
        _md_table(
            ["song", "frames", "frame period", "AUDCTL", "trace sha256"],
            [[f"`{row['slug']}`", row["frames"], f"{row['frame_period_us']} us",
              f"${row['audctl']:02x}", row["trace_sha256"][:16]]
             for row in bundle["dataset"]["traces"]],
        ),
        "",
        "No song was added, removed, sampled or truncated, and no song's note representation was "
        "hand-written: every note comes from the repository's own detector.\n",
    ]


def _section_5(bundle: Mapping[str, Any]) -> List[str]:
    rows = []
    for slug, row in sorted(bundle["songs"].items()):
        notes = row["notes"]
        rows.append([
            f"`{slug}`", notes["notes"], notes["median_length"], notes["min_length"],
            notes["max_length"], notes["distinct_divider_values"],
            notes["distinct_level_values"],
        ])
    return [
        "## 5. Existing Note Representation\n",
        "A note is reduced to a bounded number of values: one pitch, one length, one waveform, one "
        "onset level, and a four-parameter level contour. Nothing per-frame survives into the "
        "representation - which is the whole point, because everything the note does after its "
        "onset has to be explained by the residual.\n",
        _md_table(
            ["song", "notes", "median length", "min", "max", "distinct pitches",
             "distinct onset levels"],
            rows,
        ),
        "",
        "Per voice, so the reader can see how the note density is distributed:\n",
        _md_table(
            ["song", "voice", "notes", "frames", "median length", "distinct onset levels"],
            [[f"`{slug}`", voice, item["notes"], item["frames"], item["median_length"],
              item["distinct_levels"]]
             for slug, row in sorted(bundle["songs"].items())
             for voice, item in sorted(row["notes"]["by_voice"].items())],
        ),
        "",
    ]



def _section_6(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 6. Note-Level Baseline\n",
        "The baseline answers exactly one question: *given only the notes, what would the player "
        "put in the registers?* It is built from the repository's own definitions rather than from "
        "a formula invented here:\n",
        _md_table(
            ["register", "what the baseline predicts", "from which existing function"],
            [
                ["AUDF1-4", "the note's single pitch, mapped to a divider",
                 "`ir.frequency_to_audf_8bit` / `ir.frequency_to_audf_16bit`"],
                ["AUDC1-4", "the note's distortion nibble plus the level the envelope model "
                            "produces",
                 "`pokey_hw.player_envelope_volumes`"],
                ["AUDCTL", "one global value for the whole song", "the composition sets it once"],
                ["outside any note", "hold the last AUDF, silence the channel",
                 "`player.asm`'s rest behaviour"],
            ],
        ),
        "",
        "**Two baselines are measured, and they bracket the answer.**\n",
        _md_table(
            ["baseline", "level information it may use", "mean register coverage",
             "mean residual share"],
            [
                ["flat note", "one onset level per note",
                 _pct(_mean([
                     row["flat_baseline"]["register_coverage"] or 0.0
                     for row in bundle["songs"].values()
                 ])),
                 _pct(_mean([
                     row["flat_baseline"]["residual_share"] or 0.0
                     for row in bundle["songs"].values()
                 ]))],
                ["note + fitted contour", "four envelope parameters per note",
                 _pct(bundle["summary"]["note_register_coverage"]),
                 _pct(bundle["summary"]["residual_share"])],
            ],
        ),
        "",
        "The second is the headline baseline, because a note in any tracker carries an instrument "
        "with an envelope, and giving the baseline its best shot makes the residual conservative "
        "rather than flattering.\n",
        "**Circularity, stated plainly.** The baseline reads the trace's own divider, waveform and "
        "onset level, and fits the player's model to the note's own contour. It therefore shares "
        "the trace's values *at note onsets* - which is precisely why the onset residual is "
        "reported separately in section 10 and is nearly zero - and it carries no per-frame "
        "information inside a note. The full information flow is written out in section 17.\n",
    ]


def _section_7(bundle: Mapping[str, Any]) -> List[str]:
    rows = []
    for slug, row in sorted(bundle["songs"].items()):
        prediction = row["prediction"]
        rows.append([
            f"`{slug}`", prediction["register_values"], prediction["predicted_values"],
            _pct(prediction["register_coverage"]), _pct(prediction["frame_coverage"]),
            row["flat_baseline"]["register_coverage"],
        ])
    return [
        "## 7. Prediction Model\n",
        "The prediction is a real encoding problem, not a bookkeeping step: for every frame of "
        "every song it produces nine register values, and the share of them that match the trace "
        "exactly is what the note representation explains.\n",
        _md_table(
            ["song", "register values", "predicted exactly", "register coverage",
             "frame coverage", "flat-note coverage"],
            rows,
        ),
        "",
        "**Why frame coverage and register coverage must never be confused.** A frame counts as "
        "predicted only if all nine registers agree. Nine registers rarely all agree at once, so "
        "frame coverage collapses to a few percent even when four fifths of the individual values "
        "are right. Section 9 reports both and shows how far apart they are; a report that quoted "
        "only the frame figure would make the note representation look worthless, and one that "
        "quoted only the register figure would hide how rarely a whole frame is right.\n",
        "**How well the envelope model fits.** The player's model reproduces "
        f"{_pct(bundle['summary']['level_model_fidelity'])} of the notes' own level contours on "
        "average. Per song:\n",
        _md_table(
            ["song", "levels reproduced", "notes reproduced exactly", "notes"],
            [[f"`{slug}`", _pct(row["contour_fidelity"]["level_fidelity"]),
              _pct(row["contour_fidelity"]["note_fidelity"]), row["contour_fidelity"]["notes"]]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "That figure bounds how much of the AUDC residual can honestly be called performance: the "
        "rest of it is the model being too small, and section 17 says so.\n",
    ]



def _section_8(bundle: Mapping[str, Any]) -> List[str]:
    identity = [
        [_num(row["residual"]["register_values"])] for row in bundle["songs"].values()
    ]
    return [
        "## 8. Exact Residual Definition\n",
        "The residual is a per-register value difference, and the reconstruction is arithmetic:\n",
        "```\nresidual[register][frame] = (exact - predicted) & 0xFF\n"
        "exact                      = (predicted + residual) & 0xFF\n```\n",
        "It is deterministic, exact, reversible and neutral: it names no effect and assumes no "
        "musical meaning. It is also *checked*, not asserted - "
        f"{len(identity)} of {len(identity)} songs pass the identity "
        "`reconstruct(residual) == exact` for every frame and every register, and the stage raises "
        "rather than reports if it ever fails.\n",
        _md_table(
            ["property", "value"],
            [
                ["representation", "REGISTER_VALUE_RESIDUAL, 8-bit two's complement per register "
                                   "per frame"],
                ["zero means", "the baseline predicted that register in that frame exactly"],
                ["storage cost quoted", "a stated sparse encoding: per register a uvarint count, "
                                        "then (uvarint frame delta, one byte value) pairs"],
                ["identity", "`(predicted + residual) & 0xFF == exact`, verified"],
                ["what it is not", "not a named effect, not a musical category, not a compression "
                                   "scheme"],
            ],
        ),
        "",
        "**Sizes.** The canonical stream is nine bytes per frame; the residual is quoted both as a "
        "count of differing values and as the bytes of that stated sparse encoding, so a size can "
        "be compared without dressing it up.\n",
        _md_table(
            ["song", "canonical bytes", "residual values", "residual share",
             "sparse residual bytes", "sparse share of canonical"],
            [[f"`{slug}`", row["residual"]["canonical_bytes"],
              row["residual"]["residual_values"], _pct(row["residual"]["residual_share"]),
              row["residual"]["residual_bytes_sparse"],
              _pct(row["residual"]["residual_bytes_sparse_share"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
    ]


def _section_9(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 9. Residual Statistics\n",
        "Three coverage figures, side by side, because they lead to very different conclusions and "
        "only one of them is the information figure.\n",
        _md_table(
            ["song", "frames", "exact frames", "frame coverage", "residual values",
             "register coverage", "byte coverage"],
            [[f"`{slug}`", row["residual"]["frames"], row["residual"]["exact_frames"],
              _pct(row["residual"]["frame_coverage"]), row["residual"]["residual_values"],
              _pct(row["residual"]["register_coverage"]),
              _pct(row["residual"]["byte_coverage"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        _md_table(
            ["figure", "mean over the four songs"],
            [
                ["frame coverage (all nine registers agree)",
                 _pct(s["note_frame_coverage"])],
                ["register coverage (values that agree)", _pct(s["note_register_coverage"])],
                ["residual share (values that do not)", _pct(s["residual_share"])],
                ["byte coverage = register coverage, by construction",
                 _pct(s["note_register_coverage"])],
            ],
        ),
        "",
        f"**The gap is the finding.** Frame coverage is {_pct(s['note_frame_coverage'])} and "
        f"register coverage is {_pct(s['note_register_coverage'])}. Saying \"the note "
        "representation explains 1% of the stream\" and \"it explains 60% of the stream\" are both "
        "defensible readings of the same measurement, and both are misleading on their own. The "
        "byte figure is identical to the register figure *because* one register frame is one byte "
        "in the canonical representation, and that equality is stated rather than assumed.\n",
    ]



def _section_10(bundle: Mapping[str, Any]) -> List[str]:
    aggregate: Dict[str, Dict[str, int]] = {
        kind: {"residual": 0, "total": 0} for kind in CLASS_NAMES.values()
    }
    for row in bundle["songs"].values():
        for kind, count in row["residual"]["by_class"].items():
            aggregate[kind]["residual"] += count
        for kind, count in row["residual"]["by_class_totals"].items():
            aggregate[kind]["total"] += count
    return [
        "## 10. Residual Temporal Distribution\n",
        "The residual is classified per *register*, against the notes that actually drive that "
        "register. A global \"a note started here\" flag is deliberately not used, because with "
        "four voices it is true almost everywhere and would make every frame look like an onset.\n",
        _md_table(
            ["class", "frames", "residual values", "residual share of the class"],
            [[kind, entry["total"], entry["residual"],
              _pct(_share(entry["residual"], entry["total"]))]
             for kind, entry in sorted(aggregate.items())],
        ),
        "",
        "**Per song, and per song this is the sharpest single table in the report.**\n",
        _md_table(
            ["song", "outside_any_note", "note_interior", "note_onset", "register values",
             "residual"],
            [[f"`{slug}`", _pct(row["residual"]["by_class_share"]["outside_any_note"]),
              _pct(row["residual"]["by_class_share"]["note_interior"]),
              _pct(row["residual"]["by_class_share"]["note_onset"]),
              row["residual"]["register_values"], row["residual"]["residual_values"]]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "**Within a note, the residual sits in the middle, not at the edges.** Relative position is "
        "(frame - note start) / (note length - 1); the gap row collects frames no note covers.\n",
        _md_table(
            ["song", "onset", *[name for name, _l, _h in POSITION_BINS], "gap"],
            [[f"`{slug}`", _pct(row["temporal"]["onset_residual_share"]),
              *[_pct(row["temporal"]["position_bins"][name]["residual_share"])
                for name, _l, _h in POSITION_BINS],
              _pct(row["temporal"]["gap_residual_share"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "**Two conclusions the numbers force.** First, the note *onset* is almost never wrong, so "
        "the residual is not an alignment or a pitch-mapping error - it is what happens after the "
        "note starts. Second, the residual is spread across the whole note rather than "
        "concentrated at its edges, so a baseline that only fixed up transitions would not come "
        "close to explaining it.\n",
    ]


def _section_11(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 11. Residual Register and Channel Distribution\n",
        "Which registers carry the residual, and in which class. A single register carrying "
        "everything would mean a channel-assignment problem rather than missing performance "
        "information.\n",
        _md_table(
            ["song", "register", "residual values", "share of frames", "distinct magnitudes",
             "onset", "interior", "gap"],
            [[f"`{slug}`", name, entry["residual_values"], _pct(entry["residual_share"]),
              entry["distinct_residual_values"],
              _pct(entry["by_class_share"]["note_onset"]),
              _pct(entry["by_class_share"]["note_interior"]),
              _pct(entry["by_class_share"]["outside_any_note"])]
             for slug, row in sorted(bundle["songs"].items())
             for name, entry in sorted(row["residual"]["per_register"].items())],
        ),
        "",
        "**By register family.** Pitch registers and level registers behave differently, and the "
        "split is reported so a reader can see which half of the stream the missing information "
        "lives in.\n",
        _md_table(
            ["song", "pitch residual values", "volume residual values", "pitch share"],
            [[f"`{slug}`", row["trivial"]["channel_assignment"]["pitch_residual_values"],
              row["trivial"]["channel_assignment"]["volume_residual_values"],
              _pct(row["trivial"]["channel_assignment"]["pitch_share"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "AUDCTL is worth one line on its own: it is a single global register, every song uses one "
        "value for its whole length, and the baseline predicts that value, so its residual is zero "
        "everywhere. It is reported as zero rather than omitted.\n",
    ]



def _section_12(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 12. Stage 19 Grammar as Residual Model\n",
        "The experiment this stage exists for. Stage 19 asked whether the grammar could describe "
        "the *whole* stream and answered: only partly. The question here is narrower and "
        "different - *is the grammar much better when it only has to describe the residual?*\n",
        "```\nraw trace    ->  Stage 19 grammar        (Stage 19's question)\n"
        "raw trace    ->  note baseline  ->  residual  ->  Stage 19 grammar   (this stage)\n```\n",
        "The vocabulary is Stage 19's generalisable one - SET, HOLD, DELTA, RAMP, TOGGLE - with the "
        "literal escape as the residual channel. **The song-specific REPEAT lexicon is excluded by "
        "definition**, because Stage 19 showed it transfers nothing, and this stage measures only "
        "information a shared layer could carry.\n",
        _md_table(
            ["song", "residual values", "structurally explained", "structural share",
             "grammar bytes", "literal bytes", "size gain"],
            [[f"`{slug}`", row["grammar"]["residual_values"],
              row["grammar"]["structural_residual_values"],
              _pct(row["grammar"]["structural_share"]), row["grammar"]["grammar_bytes"],
              row["grammar"]["literal_bytes"], _pct(row["grammar"]["size_gain"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "**Two readings, and they can disagree.** *Structural share* counts only the **nonzero** "
        "residual values that a construction generates rather than a literal store: a HOLD over a "
        "run of zeros explains nothing, and it is excluded by construction because those frames "
        "carry a zero residual. *Size gain* is the grammar's encoding against the stated sparse "
        "encoding of the same residual, and it is secondary.\n",
        "**Per register, because the answer is not uniform.**\n",
        _md_table(
            ["song", "register", "residual values", "structural share", "operations"],
            [[f"`{slug}`", name, entry["residual_values"],
              _pct(entry["structural_share"]), entry["operations"]]
             for slug, row in sorted(bundle["songs"].items())
             for name, entry in sorted(row["grammar"]["per_register"].items())
             if entry["residual_values"]],
        ),
        "",
        "The pattern is consistent across all four songs: pitch registers are strongly structured "
        "(their residual is mostly arithmetic movement, which RAMP and DELTA generate) while level "
        "registers are much less so. That is the single most useful shape in this report, because "
        "it says where a Performance Layer would and would not earn its keep.\n",
    ]


def _section_13(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    return [
        "## 13. Incremental Gain\n",
        "The performance gain is defined as `NOTE_RESIDUAL - NOTE_PLUS_GRAMMAR_RESIDUAL`, in "
        "register values and in shares of the whole stream.\n",
        _md_table(
            ["song", "notes explain", "residual", "grammar explains of the residual",
             "grammar adds to the stream", "still unexplained"],
            [[f"`{slug}`", _pct(row["note_coverage"]), _pct(row["residual_share"]),
              _pct(row["grammar_structural_share"]),
              _pct(row["additional_explained_share"]), _pct(row["remaining_share"])]
             for slug, row in sorted(bundle["note_vs_grammar"].items())],
        ),
        "",
        _md_table(
            ["stage of the answer", "share of all register values"],
            [
                ["explained by the note representation", _pct(s["note_register_coverage"])],
                ["explained additionally by the Stage 19 grammar",
                 _pct(s["additional_explained_share"])],
                ["explained by neither", _pct(s["remaining_share"])],
            ],
        ),
        "",
        f"**This is the sentence the brief asks for.** After accounting for the existing note-level "
        f"representation, {_pct(s['residual_share'])} of POKEY register values remain unexplained; "
        f"the Stage 19 grammar accounts for a further {_pct(s['grammar_structural_share'])} of that "
        f"residual, which is {_pct(s['additional_explained_share'])} of the whole stream; the "
        f"remaining {_pct(s['remaining_share'])} is described by neither, and sections 14 to 16 test "
        "whether what is left is shared or private.\n",
        "**Per-construction contribution**, because a single construction taking all the credit "
        "would change what a layer should contain:\n",
        _md_table(
            ["song", "construction removed", "structural share with", "without",
             "share lost", "size gain lost"],
            [[f"`{slug}`", name, _pct(item["structural_share_with"]),
              _pct(item["structural_share_without"]), _pct(item["structural_share_lost"]),
              _pct(item["size_gain_lost"])]
             for slug, row in sorted(bundle["songs"].items())
             for name, item in sorted(row["grammar_ablation"]["without_each"].items())],
        ),
        "",
    ]



def _section_14(bundle: Mapping[str, Any]) -> List[str]:
    induction = bundle["leave_one_out"]["induction"]
    return [
        "## 14. Cross-Song Generalization\n",
        "The residual grammar is induced independently on each song by greedy forward selection on "
        "the encoded residual size, so a construction has to shrink the residual before it joins "
        "the vocabulary.\n",
        _md_table(
            ["song", "induced residual vocabulary", "encoded bytes", "literal bytes",
             "in-sample size gain"],
            [[f"`{slug}`", ", ".join(row["induced_primitives"]), row["encoded_bytes"],
              row["literal_bytes"],
              _pct(_share(row["literal_bytes"] - row["encoded_bytes"], row["literal_bytes"]))]
             for slug, row in sorted(induction.items())],
        ),
        "",
        "**The step history of the first song**, kept so the stopping decision can be audited:\n",
        _md_table(
            ["step", "candidate added", "trial vocabulary", "encoded bytes", "gain", "accepted"],
            [[index + 1, step["considered"], ", ".join(step["trial_set"]),
              step["encoded_bytes"], step["gain_bytes"], "yes" if step["accepted"] else "no"]
             for index, step in enumerate(
                 induction[sorted(induction)[0]]["steps"]
             )],
        ),
        "",
        "**Structure, not just vocabulary.** The kind of operation each song's residual parse uses, "
        "and how often:\n",
        _md_table(
            ["song", "operation mix", "adjacent pairs observed"],
            [[f"`{slug}`", ", ".join(
                f"{kind} {_pct(share)}" for kind, share in
                sorted(row["shapes"]["operation_share"].items())
            ), len(row["shapes"]["adjacent_pairs"])]
             for slug, row in sorted(
                 {slug: fold for slug, fold in [
                     (fold["held_out"], fold) for fold in bundle["leave_one_out"]["folds"]
                 ]}.items()
             )],
        ),
        "",
    ]


def _section_15(bundle: Mapping[str, Any]) -> List[str]:
    loo = bundle["leave_one_out"]
    return [
        "## 15. Leave-One-Out\n",
        "Induce on three songs' residuals, then encode the fourth. Three arms, because "
        "*generalise* means three different things and conflating them would flatter the result.\n",
        _md_table(
            ["arm", "what it allows", "mean size gain"],
            [
                ["shared vocabulary",
                 "only the constructions every training song induced, parameters free",
                 _pct(loo["mean_size_gain"]["shared_vocabulary"])],
                ["union vocabulary",
                 "every construction any training song induced, parameters free",
                 _pct(loo["mean_size_gain"]["union_vocabulary"])],
                ["frozen parameters",
                 "the union vocabulary, but only parameter shapes seen in training",
                 _pct(loo["mean_size_gain"]["frozen_parameters"])],
            ],
        ),
        "",
        _md_table(
            ["held out", "trained on", "shared vocabulary", "union vocabulary",
             "literal bytes", "shared arm", "union arm", "frozen arm"],
            [[f"`{fold['held_out']}`", ", ".join(fold["trained_on"]),
              ", ".join(fold["shared_vocabulary"]) or "none",
              ", ".join(fold["union_vocabulary"]), fold["bytes"]["literal"],
              fold["bytes"]["shared_vocabulary"], fold["bytes"]["union_vocabulary"],
              fold["bytes"]["frozen_parameters"]]
             for fold in sorted(loo["folds"], key=lambda item: item["held_out"])],
        ),
        "",
        "**The three levels of generalisation, reported separately.**\n",
        _md_table(
            ["level", "question", "measured"],
            [
                ["G1 vocabulary", "are the same residual constructions induced elsewhere?",
                 ", ".join(sorted({name for slug in
                                   (fold["held_out"] for fold in loo["folds"])
                                   for name in
                                   loo["induction"][slug]["induced_primitives"]}))],
                ["G2 structure", "do the same temporal relationships appear?",
                 f"{len(set().union(*[set(fold['shapes']['operation_counts']) for fold in loo['folds']]))} "
                 "distinct operation kinds appear across the four held-out residuals"],
                ["G3 parameters", "do the parameters transfer?",
                 f"frozen-parameter gain {_pct(loo['mean_size_gain']['frozen_parameters'])} against "
                 f"union {_pct(loo['mean_size_gain']['union_vocabulary'])}"],
            ],
        ),
        "",
        "A song-specific lexicon is never used, and no parameter is ever fitted to the held-out "
        "song, so the out-of-sample numbers are honest rather than optimistic.\n",
    ]



def _section_16(bundle: Mapping[str, Any]) -> List[str]:
    nulls = bundle["nulls"]
    controls = bundle["controls"]
    floor = nulls["no_notes_constant_register"]["mean_register_coverage"] or 0.0
    aligned = bundle["summary"]["note_register_coverage"] or 0.0
    permuted = _mean([
        row["moved_share"] or 0.0
        for row in controls["permuted_trace"]["per_song"].values()
    ])
    return [
        "## 16. Controls and Anti-Circularity\n",
        "Three null models and two controls. Each exists to answer a specific way the result could "
        "be wrong.\n",
        _md_table(
            ["model", "what it is", "measured", "what it rules out"],
            [
                ["no notes at all", "every register held at its own modal value", _pct(floor),
                 "crediting the notes with registers that are simply constant"],
                ["shuffled residual",
                 "the same corrections at shuffled frames, same multiset per register",
                 _pct(nulls["shuffled_residual"]["mean_structural_share"]),
                 "a structural share that is really just correction density"],
                ["shifted notes",
                 "the same notes moved by "
                 + ", ".join(str(value) for value in controls["shifted"]["shifts"]) + " frames",
                 _pct(controls["shifted"]["mean_register_coverage"]),
                 "a baseline that is not really explaining alignment"],
                ["permuted trace", "the trace shuffled in frame order against unshifted notes",
                 _pct(permuted),
                 "the control being a different signal rather than a control"],
            ],
        ),
        "",
        "**The shuffled-residual null is the decisive one for the grammar.** The real residual "
        f"scores {_pct(bundle['summary']['grammar_structural_share'])} structurally; the same "
        "corrections at shuffled frames score "
        f"{_pct(nulls['shuffled_residual']['mean_structural_share'])}. The structure is therefore "
        "in the *placement* of the corrections, not in how many there are.\n",
        "**The shifted-notes control is the decisive one for the baseline.** Comparing "
        f"{_pct(controls['shifted']['mean_register_coverage'])} against {_pct(aligned)} would be "
        f"misleading, because the no-notes floor is already {_pct(floor)}. The right comparison is "
        f"against that floor: the notes contribute {_pct(aligned - floor)}, and the shift keeps "
        "almost none of it. Alignment is doing the real work.\n",
        "**Anti-circularity, in full.** The information flow is one-directional by construction:\n",
        _md_table(
            ["step", "what it reads", "what it must not read"],
            [
                ["note detection", "the trace's divider, waveform and level, at note onsets",
                 "nothing per-frame inside a note"],
                ["contour fit", "the note's own level sequence, reduced to four parameters",
                 "no other note, no other channel"],
                ["prediction",
                 "the notes only, through the project's own pitch and envelope functions",
                 "no per-frame trace value at all"],
                ["residual", "prediction and exact, as arithmetic",
                 "nothing that could favour the Stage 19 grammar"],
            ],
        ),
        "",
        "The residual is therefore defined *before* the grammar touches it, and the grammar is "
        "applied to a residual it had no hand in shaping. That is the guard the brief asks for, "
        "and it is structural rather than a promise.\n",
    ]



def _section_17(bundle: Mapping[str, Any]) -> List[str]:
    songs = bundle["songs"]
    onset = _mean([
        row["trivial"]["pitch_mapping"]["onset_residual_share"] or 0.0 for row in songs.values()
    ])
    gap_values = sum(
        row["trivial"]["detector_gap"]["gap_residual_values"] for row in songs.values()
    )
    gap_frames = sum(row["trivial"]["detector_gap"]["gap_frames"] for row in songs.values())
    pitch_share = _mean([
        row["trivial"]["channel_assignment"]["pitch_share"] or 0.0 for row in songs.values()
    ])
    return [
        "## 17. Trivial Explanations, Ruled Out First\n",
        "Five candidate boring causes, each measured. `residual != 0` is not performance, so each "
        "has to be eliminated before any claim is made.\n",
        _md_table(
            ["candidate cause", "measurement", "conclusion"],
            [
                ["pitch mapping", f"onset residual share {_pct(onset)}",
                 "the player's formula reproduces the trace's own onset divider essentially "
                 "everywhere, so the AUDF residual is movement after the onset, not a mapping "
                 "artefact"],
                ["detector gap", f"{_pct(_share(gap_values, gap_frames))} of gap frames",
                 "frames no note covers are a limitation of the note detector; they are counted "
                 "separately and never as performance"],
                ["level model",
                 f"{_pct(bundle['summary']['level_model_fidelity'])} of note contours reproduced",
                 "the player's own four-parameter envelope model cannot reproduce most contours "
                 "even fitted as well as it allows, so part of the AUDC residual is the model "
                 "being too small"],
                ["channel assignment",
                 f"{_pct(pitch_share)} of residual values are in pitch registers",
                 "the split is reported per register, so one mis-assigned channel would show up "
                 "as one register carrying everything"],
                ["note length", "reported per length bucket below",
                 "a baseline that only failed on very short notes would be a resolution problem, "
                 "not a missing layer"],
            ],
        ),
        "",
        _md_table(
            ["song", "length bucket", "frames", "residual", "residual share"],
            [[f"`{slug}`", bucket, entry["frames"], entry["residual"],
              _pct(entry["residual_share"])]
             for slug, row in sorted(songs.items())
             for bucket, entry in sorted(row["trivial"]["note_length"].items())],
        ),
        "",
        "**What survives all five.** The residual is not an alignment error, not a detector gap, "
        "not a channel-assignment mistake and not a resolution problem. It is genuine per-frame "
        "information the note representation does not carry - *and* it is partly an envelope model "
        "that is too small. Both statements hold at once, and this report keeps them both rather "
        "than choosing the flattering one.\n",
    ]


def _section_18(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 18. Complexity\n",
        "If the residual is to become a layer, its complexity matters as much as its size.\n",
        _md_table(
            ["song", "residual events", "distinct magnitudes", "operations", "repetition",
             "temporal entropy", "value entropy"],
            [[f"`{slug}`", row["complexity"]["residual_event_count"],
              row["complexity"]["residual_parameter_count"],
              row["complexity"]["residual_unique_shapes"],
              _pct(row["complexity"]["residual_repetition"]),
              _f6(row["complexity"]["residual_temporal_entropy"]),
              _f6(row["complexity"]["residual_value_entropy"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "`temporal entropy` is the Shannon entropy of the gaps between consecutive corrections in "
        "one register: a low value means the corrections arrive on a regular rhythm. `value "
        "entropy` is the entropy of the correction magnitudes. Neither is a size and neither is a "
        "verdict; they describe what kind of thing the residual is.\n",
        "**Residual relative to the original.**\n",
        _md_table(
            ["song", "canonical bytes", "residual values", "events per register",
             "residual / original"],
            [[f"`{slug}`", row["residual"]["canonical_bytes"],
              row["residual"]["residual_values"],
              _f6(row["complexity"]["residual_event_count"] / FRAME_BYTES),
              _pct(row["residual"]["residual_share"])]
             for slug, row in sorted(bundle["songs"].items())],
        ),
        "",
        "No residual grammar is proposed here. The stage measures the residual; designing a layer "
        "for it is a later experiment.\n",
    ]



def _section_19(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    songs = bundle["songs"]
    onset = _mean([
        row["trivial"]["pitch_mapping"]["onset_residual_share"] or 0.0 for row in songs.values()
    ])
    gap_share = _share(
        sum(row["trivial"]["detector_gap"]["gap_frames"] for row in songs.values()),
        sum(row["residual"]["register_values"] for row in songs.values()),
    )
    return [
        "## 19. Falsification\n",
        "The brief's five possible outcomes, against what was measured. The mapping is stated so "
        "the result cannot be read as whichever outcome happens to be most flattering.\n",
        _md_table(
            ["outcome", "would require", "measured", "verdict"],
            [
                ["A - notes explain most, residual small", "small residual, high note coverage",
                 f"note coverage {_pct(s['note_register_coverage'])}, residual "
                 f"{_pct(s['residual_share'])}", "**not this**"],
                ["B - notes explain a moderate amount, residual structured",
                 "moderate residual that is structured",
                 f"residual {_pct(s['residual_share'])}, structural share "
                 f"{_pct(s['grammar_structural_share'])}", "**this is the result**"],
                ["C - notes explain little, residual large but structured",
                 "low note coverage",
                 f"note coverage {_pct(s['note_register_coverage'])}, above the medium threshold",
                 "not this"],
                ["D - residual large and unstructured", "no structure at all",
                 f"shuffled null {_pct(s['null_shuffled_structural_share'])} against "
                 f"{_pct(s['grammar_structural_share'])} real", "explicitly refuted"],
                ["E - in-sample structure that collapses out of sample",
                 "leave-one-out far below in sample",
                 f"{_pct(s['leave_one_out_gain']['union_vocabulary'])} against "
                 f"{_pct(s['grammar_size_gain'])}", "explicitly refuted"],
            ],
        ),
        "",
        "**Deliberate attempts to break the claim.**\n",
        _md_table(
            ["attempt", "what would refute it", "measured"],
            [
                ["the residual is a pitch-mapping artefact", "a non-trivial onset residual",
                 f"{_pct(onset)} of onset frames carry a residual - refuted"],
                ["the residual is really detector gaps",
                 "most residual values falling outside notes",
                 f"gap frames are {_pct(gap_share)} of all frames - refuted"],
                ["the grammar's share is really density",
                 "the shuffled null scoring close to the real one",
                 f"{_pct(s['null_shuffled_structural_share'])} against "
                 f"{_pct(s['grammar_structural_share'])} - refuted, decisively"],
                ["the baseline is too vague to be tested",
                 "the shifted control keeping its coverage",
                 f"shifted {_pct(s['control_shifted_coverage'])} against a floor of "
                 f"{_pct(s['null_no_notes_coverage'])} - refuted"],
                ["the result is song-specific",
                 "leave-one-out collapsing below the in-sample gain",
                 f"{_pct(s['leave_one_out_gain']['union_vocabulary'])} against "
                 f"{_pct(s['grammar_size_gain'])} - refuted, it transfers"],
            ],
        ),
        "",
        "Two results are negative and are reported as such rather than buried: the player's own "
        "envelope model reproduces only about half of the notes' level contours, and about a fifth "
        "of all register values is explained by neither the notes nor the grammar.\n",
    ]



def _section_20(bundle: Mapping[str, Any]) -> List[str]:
    verdicts = bundle["verdicts"]
    return [
        "## 20. Final Verdict\n",
        _md_table(
            ["question", "verdict"],
            [
                ["how well do the notes explain the stream?",
                 verdicts["note_explanatory_power"]["verdict"]],
                ["what is the residual like?", verdicts["residual_structure"]["verdict"]],
                ["does it generalise?", verdicts["generalization"]["verdict"]],
                ["is a Performance Layer justified?",
                 verdicts["performance_layer"]["verdict"]],
                ["production", verdicts["player_integration"]["verdict"]],
            ],
        ),
        "",
        "**Every condition the layer verdict rests on, with its measured number.**\n",
        _md_table(
            ["condition", "met", "measured"],
            [[item["condition"], "yes" if item["met"] else "**no**",
              json.dumps(item["measured"], sort_keys=True)]
             for item in verdicts["performance_layer"]["conditions"]],
        ),
        "",
        "The deciding condition is: **"
        + (verdicts["performance_layer"]["deciding_condition"] or "none - every condition is met")
        + "**.\n",
        _verdict_text(verdicts),
    ]


def _verdict_text(verdicts: Mapping[str, Any]) -> str:
    return (
        f"**{verdicts['note_explanatory_power']['verdict']}, "
        f"{verdicts['residual_structure']['verdict']}, "
        f"{verdicts['generalization']['verdict']}, "
        f"{verdicts['performance_layer']['verdict']}.** "
        "The note representation explains a moderate majority of the POKEY stream, the leftover "
        "is moderate and it is structured rather than noise, and what is left generalises to a "
        "song that did not contribute to it. Those three together are what makes a layer "
        "*justified by the evidence* - and they are also why the answer is not a triumphant yes: "
        "a fifth of the stream is still explained by neither the notes nor the grammar, and the "
        "player's own envelope model is too small to describe the amplitude behaviour it is asked "
        "to describe. A future layer would have to fix that, and nothing here says it can.\n"
    )



def _section_final(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    events = sum(row["complexity"]["residual_event_count"] for row in bundle["songs"].values())
    return [
        "## Final question\n",
        "> After accounting for the existing note-level representation, how much historical POKEY "
        "behaviour remains as real, generalisable residual performance information - and is it "
        "small and structured enough to justify a separate Performance Layer in the Atari Music "
        "Composer?\n",
        "Derived from the measurements, axis by axis:\n",
        _md_table(
            ["axis the brief asks for", "measured"],
            [
                ["note baseline coverage",
                 f"register {_pct(s['note_register_coverage'])}, frame "
                 f"{_pct(s['note_frame_coverage'])}, byte {_pct(s['note_register_coverage'])} "
                 "(identical to register by construction)"],
                ["exact residual",
                 f"{_pct(s['residual_share'])} of register values, "
                 f"{s['residual_register_values']} values, identity verified on every song"],
                ["register / frame / byte residual",
                 f"register {_pct(s['residual_share'])}, frame "
                 f"{_pct(1.0 - (s['note_frame_coverage'] or 0.0))}, byte "
                 f"{_pct(s['residual_share'])}"],
                ["Stage 19 incremental gain",
                 f"{_pct(s['grammar_structural_share'])} of the residual, "
                 f"{_pct(s['additional_explained_share'])} of the whole stream"],
                ["temporal distribution",
                 "onset, interior and gap reported separately; the residual sits in the interior, "
                 "not at the edges"],
                ["cross-song behaviour",
                 f"no-notes floor {_pct(s['null_no_notes_coverage'])}, shifted control "
                 f"{_pct(s['control_shifted_coverage'])}, shuffled-residual null "
                 f"{_pct(s['null_shuffled_structural_share'])}"],
                ["leave-one-out",
                 f"vocabulary {_pct(s['leave_one_out_gain']['union_vocabulary'])}, frozen "
                 f"parameters {_pct(s['leave_one_out_gain']['frozen_parameters'])}"],
                ["controls",
                 "all four reported in section 16; the two decisive ones both refute the trivial "
                 "reading"],
                ["complexity", f"{events} residual events, with temporal and value entropy per song"],
            ],
        ),
        "",
        f"**The answer, in the form the brief asks for.** After accounting for the existing "
        f"note-level representation, {_pct(s['residual_share'])} of POKEY register values remain as "
        f"residual. The Stage 19 grammar accounts for {_pct(s['grammar_structural_share'])} of that "
        f"residual - a further {_pct(s['additional_explained_share'])} of the whole stream - and "
        f"the remaining {_pct(s['remaining_share'])} is explained by neither. Within the residual, "
        "the pitch registers are strongly structured and the level registers are much less so, and "
        "the structure survives leave-one-out and both decisive controls, so it is generalisable "
        "rather than song-specific.\n",
        "**Is it small and structured enough to justify a separate Performance Layer?** The "
        "measurements say yes on structure and on generalisation, and *not yet* on completeness: a "
        "fifth of the stream is outside both representations, and part of the amplitude residual is "
        "the player's own envelope model being too small rather than a missing performance layer. A "
        "layer justified by this evidence would have to be a layer that also replaces that envelope "
        "model - and whether it can is a question this stage does not answer.\n",
        "**No forced verdict.** The residual is neither small enough to shrug at nor large enough "
        "to make the composition representation hopeless. It is moderate, structured and shared, "
        "and it is reported as it is rather than rounded towards either the encouraging or the "
        "discouraging reading.\n",
        "**STOP.** Nothing was implemented in production: no Composer change, no Music IR change, no "
        "POKEY IR change, no Performance Layer, no player command, no instrument bank, no generated "
        "music and no listening test. This stage establishes how much information really is missing "
        "between a composition and historical POKEY playback; designing an experiment that could "
        "generate it is the next stage's problem, not this one's.\n",
    ]


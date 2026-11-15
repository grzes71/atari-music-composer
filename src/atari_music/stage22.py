"""Stage 22 - detector error decomposition and ground-truth calibration.

Stage 21 established that the historical corpus cannot decide whether POKEY carries a performance
layer, and it established *why*: the only note-level view of those songs is Stage 15's detector, and
a detector run over a stream whose composition is known leaves a residual of the same order as the
historical one. It left one question open, and this stage exists to answer it:

    On traces whose composition is known, where does the detector's residual actually come from?

Stage 22 does not re-open the performance-layer question, does not touch the detector, and does not
try to make the residual smaller. It is a **diagnostic** stage: it takes the 53-composition Tier A
control corpus from Stage 21, compiles each composition to an exact POKEY trace, runs the *existing*
Stage 15 detector over that trace, and decomposes the resulting residual into named, measured causes.

The three levels of truth are kept strictly apart, because conflating them is the failure this stage
exists to avoid:

    COMPOSITION        the authored score: notes, onsets, durations, pitch, channel, level,
        |              generator, envelope, AUDCTL
        v
    EXACT TRACE        the project's own compiler's deterministic output - the second ground truth
        |
        v
    STAGE 15 DETECTOR  the existing heuristic: segment audible frames, read pitch/waveform/level at
        |              each span's onset, fit a four-parameter envelope to the span's contour
        v
    RESIDUAL           exact trace minus the detector's prediction, per register per frame

Nothing in Stage 22 is a fix. Where the detector's behaviour has to be varied, it is *replicated* in
this module's experimental layer and the replica is proved against the original before it is used, so
that a difference between two arms is a difference of information rather than of code.

The stage's answer is short and it is measured, not asserted. On the control corpus the detector's
residual decomposes into exactly three causes, and two of the taxonomy families the brief lists turn
out to be *empty by construction*:

* **the outside-note convention** - ``player.asm`` holds AUDF across a rest while the project's frame
  compiler leaves an unwritten frame at zero. This is not a detector error at all, it is a
  disagreement between two project components, and it is measured and set aside;
* **note segmentation** - spans that merge two notes, start late, end early, or miss a note entirely.
  This is the bulk of what is left;
* **the level-track reduction** - the detector reads the correct span and then describes its level
  track with four numbers instead of one per frame. This is a limitation of the *representation*, not
  of the detection.

Pitch, generator, distortion and channel assignment contribute **zero** once the spans are exact, and
the reasons are measured rather than assumed: AUDCTL is constant in every compiled trace, so the
detector cannot be wrong about it; the detector reads pitch and distortion at a span's onset and the
compiler never changes either inside a note, so those reads are exact whenever the span is; and both
arms derive their voices from the same AUDCTL, so a channel assignment cannot differ between them.

Honesty rules this stage inherits and obeys:

* ``residual != 0`` is not ``detector error``. A residual can come from a convention, a
  representation limit, or an unobservable note, and each of those is separated before any claim is
  made.
* A category that is empty is reported as empty, with the reason. An empty category that is quietly
  widened is a lie.
* Nothing is attributed to the first cause that matches. The frame-level accounting closes exactly,
  the cause-level accounting is done with matched arms, and the two are reported side by side because
  they answer different questions.
* No construction is renamed after a musical technique. The names stay span, register, frame and
  cause.

Read-only. Stage 15 to 21, the composition compiler, the player, the exporter, the Music IR and the
production schemas are read through their hashes and never written. No audio is rendered, no music is
generated, no listening test is run, and nothing is implemented in production. Analysis version
``stage22/1``.

If a defect is found in Stage 15, it is documented and measured here and left alone there: this stage
replicates the behaviour in its own layer rather than repairing the original.
"""



from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import ir, pokey_hw, stage15, stage18, stage19, stage20, stage21

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE22_DIR = DEFAULT_REPORTS_DIR / "stage22"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_SONGS_DIR = stage21.DEFAULT_SONGS_DIR
DEFAULT_AI_DIR = stage21.DEFAULT_AI_DIR
DEFAULT_EXTRA_DSL_DIR = stage21.DEFAULT_EXTRA_DSL_DIR

ANALYSIS_VERSION = "stage22/1"
RANDOM_SEED = 20250322

REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER
FRAME_BYTES = stage18.FRAME_BYTES
EXPECTED_SLUGS: Tuple[str, ...] = stage20.EXPECTED_SLUGS

AUDF_COLUMN = stage20.AUDF_COLUMN
AUDC_COLUMN = stage20.AUDC_COLUMN
AUDCTL_COLUMN = stage20.AUDCTL_COLUMN

OUTSIDE_HOLD = stage21.OUTSIDE_HOLD
OUTSIDE_EXPORTER = stage21.OUTSIDE_EXPORTER
OUTSIDE_POLICIES: Tuple[str, ...] = (OUTSIDE_HOLD, OUTSIDE_EXPORTER)

CLASS_GAP = stage20.CLASS_GAP
CLASS_INTERIOR = stage20.CLASS_INTERIOR
CLASS_ONSET = stage20.CLASS_ONSET


class Stage22Error(RuntimeError):
    """A required input is missing or malformed, or a declared identity does not hold."""


def _read_json(path: Path) -> Any:
    return stage15._read_json(path)


def sha256_file(path: Path) -> str:
    return stage15.sha256_file(path)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).digest().hex()


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    return stage15._rnd(value, places)


def _share(part: int, whole: int) -> Optional[float]:
    return None if not whole else round(part / whole, 6)


def _mean(values: Sequence[float]) -> Optional[float]:
    return None if not values else round(sum(values) / len(values), 6)


def _median(values: Sequence[float]) -> Optional[float]:
    return stage15._median(list(values))


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    return stage15._quantile(list(values), q)


def _cell(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    """A markdown table, so every report number is auditable against the source data."""
    head = "| " + " | ".join(_cell(item) for item in header) + " |"
    rule = "|" + "|".join("---" for _ in header) + "|"
    body = ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


# ===========================================================================
# PART 1 - the canonical ground-truth representation (section 1 of the brief)
# ===========================================================================
#: Every canonical field carries one of these, so a reader can see which parts of the ground truth
#: are read from the composition document, which are computed from it, and which do not exist.
KNOWN = "KNOWN"
DERIVED = "DERIVED"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"
FIELD_STATUSES: Tuple[str, ...] = (KNOWN, DERIVED, UNKNOWN, NOT_APPLICABLE)

#: The canonical fields, in the order the brief lists them. The status of each is computed per song
#: rather than declared globally, because a field can exist in one composition document and not in
#: another - and a status map that claimed otherwise would be inventing information.
CANONICAL_FIELDS: Tuple[str, ...] = (
    "song_id",
    "source_hash",
    "trace_hash",
    "note_index",
    "onset_rows",
    "onset_frames",
    "duration_rows",
    "duration_frames",
    "pitch_midi",
    "pitch_name",
    "channel",
    "voice_id",
    "role",
    "velocity",
    "volume_track",
    "instrument_id",
    "generator_distortion",
    "envelope",
    "audctl",
    "coupled_16bit",
    "frames_per_tick",
    "silence",
    "sequence_position",
)


@dataclass(frozen=True)
class GroundTruthNote:
    """One note of one composition, canonicalised, with the status of every field it carries.

    The status is the point. A composition document states a pitch, a row and a duration; it does
    *not* state a frame onset, a per-frame level track or an AUDCTL byte, and those are computed from
    it by the project's own compiler and player model. Calling a derived field "known" would overstate
    the ground truth and calling an absent one "unknown" would understate it, so both are labelled
    explicitly and the labels are reported.
    """

    song_id: str
    source_hash: str
    trace_hash: str
    note_index: int
    onset_rows: int
    onset_frames: int
    duration_rows: int
    duration_frames: int
    pitch_midi: Optional[int]
    pitch_name: Optional[str]
    channel: int
    voice_id: str
    pitch_channels: Tuple[int, ...]
    volume_channel: int
    joined: bool
    role: str
    velocity: int
    volume_track: Tuple[int, ...]
    instrument_id: Optional[int]
    generator_distortion: int
    envelope: Tuple[int, int, int, int]
    audctl: int
    coupled_16bit: bool
    frames_per_tick: int
    silence: bool
    sequence_position: int
    pattern_id: int
    pattern_name: str
    divider: Optional[int]
    hz: Optional[float]
    status: Mapping[str, str]

    @property
    def frames(self) -> int:
        return self.duration_frames

    @property
    def pack(self) -> int:
        return self.generator_distortion & 0xE0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "song_id": self.song_id,
            "note_index": self.note_index,
            "sequence_position": self.sequence_position,
            "pattern": self.pattern_name,
            "onset_rows": self.onset_rows,
            "onset_frames": self.onset_frames,
            "duration_rows": self.duration_rows,
            "duration_frames": self.duration_frames,
            "pitch_midi": self.pitch_midi,
            "pitch_name": self.pitch_name,
            "hz": _rnd(self.hz, 4),
            "divider": self.divider,
            "channel": self.channel,
            "voice_id": self.voice_id,
            "pitch_channels": list(self.pitch_channels),
            "volume_channel": self.volume_channel,
            "joined_16bit": self.joined,
            "role": self.role,
            "velocity": self.velocity,
            "volume_track_head": list(self.volume_track[:16]),
            "instrument_id": self.instrument_id,
            "generator_distortion": f"${self.generator_distortion:02X}",
            "envelope": {
                "attack_frames": self.envelope[0],
                "decay_frames": self.envelope[1],
                "sustain_vol": self.envelope[2],
                "release_frames": self.envelope[3],
            },
            "audctl": f"${self.audctl:02X}",
            "coupled_16bit": self.coupled_16bit,
            "frames_per_tick": self.frames_per_tick,
            "silence": self.silence,
            "status": dict(self.status),
        }


def ground_truth_notes(song: Any, trace: Any) -> Tuple[List[GroundTruthNote], Dict[str, str]]:
    """Canonicalise one composition against its own compiled trace.

    The notes come from Stage 21's ``composition_notes`` - the same expansion the compiler performs -
    and every derived field is computed from the composition and the trace rather than guessed. The
    returned status map says, field by field, whether this corpus's ground truth actually contains
    that field.
    """
    notes = stage21.composition_notes(song.song, trace)
    registers = trace.registers
    instruments = {instrument.id: instrument for instrument in song.song.instruments}
    out: List[GroundTruthNote] = []
    for index, note in enumerate(notes):
        instrument = instruments.get(note.instrument_id)
        volume_channel = note.volume_channel
        audc = registers[f"AUDC{volume_channel}"]
        volume_track = tuple(
            stage15.audc_volume(audc[frame])
            for frame in range(note.start, min(note.end, trace.frames))
        )
        silent = bool(note.is_rest) or not any(volume_track)
        status: Dict[str, str] = {name: UNKNOWN for name in CANONICAL_FIELDS}
        status.update({
            "song_id": KNOWN,
            "source_hash": KNOWN,
            "trace_hash": KNOWN,
            "note_index": KNOWN,
            "onset_rows": KNOWN,
            "onset_frames": DERIVED,
            "duration_rows": KNOWN,
            "duration_frames": DERIVED,
            "pitch_midi": KNOWN if note.midi is not None else UNKNOWN,
            "pitch_name": KNOWN if note.pitch is not None else UNKNOWN,
            "channel": KNOWN,
            "voice_id": DERIVED,
            "role": KNOWN if note.role else UNKNOWN,
            "velocity": KNOWN,
            "volume_track": DERIVED,
            "instrument_id": KNOWN if note.instrument_id is not None else UNKNOWN,
            "generator_distortion": KNOWN,
            "envelope": KNOWN if instrument is not None else NOT_APPLICABLE,
            "audctl": DERIVED,
            "coupled_16bit": DERIVED,
            "frames_per_tick": KNOWN,
            "silence": DERIVED,
            "sequence_position": KNOWN,
        })
        out.append(
            GroundTruthNote(
                song_id=trace.song,
                source_hash=song.sha256,
                trace_hash=song.compiled_sha256,
                note_index=index,
                onset_rows=int(note.row),
                onset_frames=int(note.start),
                duration_rows=int(note.duration_rows),
                duration_frames=int(note.frames),
                pitch_midi=note.midi,
                pitch_name=note.pitch,
                channel=int(note.channel),
                voice_id=note.voice_id,
                pitch_channels=tuple(note.pitch_channels),
                volume_channel=int(volume_channel),
                joined=bool(note.joined),
                role=str(note.role),
                velocity=int(note.volume),
                volume_track=volume_track,
                instrument_id=note.instrument_id,
                generator_distortion=int(note.distortion_byte),
                envelope=tuple(int(value) for value in note.envelope),
                audctl=int(trace.audctl),
                coupled_16bit=bool(song.song.uses_16bit_bass),
                frames_per_tick=int(song.song.frames_per_tick),
                silence=silent,
                sequence_position=int(note.sequence_index),
                pattern_id=int(note.pattern_id),
                pattern_name=str(note.pattern_name),
                divider=note.divider,
                hz=note.hz,
                status=status,
            )
        )
    out.sort(key=lambda item: (item.channel, item.onset_frames, item.note_index))
    return out, _aggregate_status(out)


def _aggregate_status(notes: Sequence[GroundTruthNote]) -> Dict[str, str]:
    """The song's status for each canonical field, taken over *all* its notes.

    A per-note status map would say ``UNKNOWN`` for pitch on a song whose last note happens to be a
    rest, which would understate the ground truth. A field is ``KNOWN`` for the song when any note
    carries it, ``DERIVED`` when none does but the derivation exists, and ``UNKNOWN`` only when no
    note has it at all.
    """
    status: Dict[str, str] = {}
    for name in CANONICAL_FIELDS:
        seen = {note.status.get(name, UNKNOWN) for note in notes}
        for candidate in (KNOWN, DERIVED, NOT_APPLICABLE, UNKNOWN):
            if candidate in seen:
                status[name] = candidate
                break
        else:
            status[name] = UNKNOWN
    return status


def ground_truth_summary(songs: Sequence[Any], traces: Sequence[Any]) -> Dict[str, Any]:
    """The canonical model, summarised: which fields exist, and how much of each the corpus carries.

    The status counts are pooled per field, so a reader can see at a glance that this corpus has a
    known pitch and channel for every note and a *derived* onset and level track - which is exactly
    the asymmetry the ablation ladder has to respect.
    """
    per_song: List[Dict[str, Any]] = []
    status_counts: Dict[str, Dict[str, int]] = {
        name: {state: 0 for state in FIELD_STATUSES} for name in CANONICAL_FIELDS
    }
    for song, trace in zip(songs, traces):
        notes, status = ground_truth_notes(song, trace)
        for name in CANONICAL_FIELDS:
            status_counts[name][status.get(name, UNKNOWN)] += 1
        per_song.append({
            "slug": song.slug,
            "source": song.source,
            "source_sha256": song.sha256,
            "compiled_sha256": song.compiled_sha256,
            "frames": trace.frames,
            "frames_per_tick": song.frames_per_tick,
            "audctl": f"${int(trace.audctl):02X}",
            "coupled_16bit": bool(song.uses_16bit_bass),
            "audctl_constant": len(set(trace.registers["AUDCTL"])) == 1,
            "notes": sum(1 for note in notes if not note.silence),
            "silent_notes": sum(1 for note in notes if note.silence),
            "distinct_pitches": len(
                {note.pitch_midi for note in notes if note.pitch_midi is not None}
            ),
            "distinct_dividers": len(
                {note.divider for note in notes if note.divider is not None}
            ),
            "distinct_generators": len({note.generator_distortion for note in notes}),
            "distinct_envelopes": len({note.envelope for note in notes}),
            "channels": sorted({note.channel for note in notes}),
            "instruments": sorted(
                {note.instrument_id for note in notes if note.instrument_id is not None}
            ),
        })
    return {
        "canonical_fields": list(CANONICAL_FIELDS),
        "field_statuses": list(FIELD_STATUSES),
        "status_counts": status_counts,
        "songs": len(per_song),
        "total_notes": sum(row["notes"] for row in per_song),
        "total_silent_notes": sum(row["silent_notes"] for row in per_song),
        "all_audctl_constant": all(row["audctl_constant"] for row in per_song),
        "per_song": per_song,
        "provenance": (
            "every note here comes from an authored composition document that references no "
            "register. The trace it is canonicalised against is the project's own compiler's "
            "deterministic output, hashed per song. Nothing is read from the historical corpus."
        ),
    }


# ===========================================================================
# PART 2 - the experimental predictor (sections 2 and 8 of the brief)
# ===========================================================================
@dataclass(frozen=True)
class NoteSpec:
    """One note as *any* arm of the decomposition states it.

    A spec is the whole information content a note-level representation carries in this pipeline:
    where it sounds, which registers it drives, at what divider, with which generator, and at which
    level in every frame. Making the level track explicit - rather than reducing it to four envelope
    parameters - is what lets this stage separate a *detection* error from a *representation* limit,
    which is the distinction the brief asks for and which Stage 20 could not make.
    """

    voice_id: str
    channels: Tuple[int, ...]
    volume_channel: int
    joined: bool
    start: int
    end: int
    dividers: Tuple[Tuple[int, int], ...]
    pack: int
    levels: Tuple[int, ...]

    @property
    def frames(self) -> int:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "channels": list(self.channels),
            "volume_channel": self.volume_channel,
            "joined_16bit": self.joined,
            "start_frame": self.start,
            "end_frame": self.end,
            "frames": self.frames,
            "dividers": [[channel, value] for channel, value in self.dividers],
            "generator": f"${self.pack:02X}",
            "levels_head": list(self.levels[:16]),
            "level_min": min(self.levels) if self.levels else None,
            "level_max": max(self.levels) if self.levels else None,
        }


def predict_from_specs(
    frames: int,
    audctl: int,
    specs: Sequence[NoteSpec],
    outside: str = OUTSIDE_HOLD,
) -> List[Tuple[int, ...]]:
    """The whole stream predicted from specs alone: nine registers for every frame.

    This is a deliberate reimplementation of Stage 21's ``predict_from_plans`` with the level track
    generalised from a fitted contour to an explicit per-frame list. It is not trusted until
    :func:`assert_matches_stage20` has proved it identical to ``stage20.predict_frames`` on real
    songs, because otherwise a difference between two arms could be a difference of code rather than
    of information - the failure mode Stage 21 warned about and this stage inherits.
    """
    if outside not in OUTSIDE_POLICIES:
        raise Stage22Error(f"unknown outside policy {outside!r}")
    prediction: List[List[int]] = [[0] * FRAME_BYTES for _ in range(frames)]
    for frame in range(frames):
        prediction[frame][AUDCTL_COLUMN] = audctl
    for voice in stage15.voices_for(audctl):
        audf: Dict[int, List[Optional[int]]] = {channel: [None] * frames
                                               for channel in voice.channels}
        audc: List[Optional[int]] = [None] * frames
        for spec in specs:
            if spec.voice_id != voice.voice_id:
                continue
            length = min(spec.end - spec.start, len(spec.levels))
            for offset in range(max(0, length)):
                frame = spec.start + offset
                if frame < 0 or frame >= frames:
                    continue
                for channel, value in spec.dividers:
                    if channel in audf:
                        audf[channel][frame] = value
                audc[frame] = spec.pack | (spec.levels[offset] & 0x0F)
        held = {channel: 0 for channel in voice.channels}
        for frame in range(frames):
            for channel in voice.channels:
                value = audf[channel][frame]
                if value is None:
                    value = held[channel] if outside == OUTSIDE_HOLD else 0
                else:
                    held[channel] = value
                prediction[frame][AUDF_COLUMN[channel]] = value
            volume = audc[frame]
            prediction[frame][AUDC_COLUMN[voice.volume_channel]] = 0 if volume is None else volume
            if voice.joined:
                prediction[frame][AUDC_COLUMN[voice.channels[0]]] = 0
    return [tuple(row) for row in prediction]


    return "\n".join([head, rule, *body])



def specs_from_records(records: Sequence[Any], audctl: int) -> List[NoteSpec]:
    """The detector's own notes as specs: Stage 20's baseline, re-expressed.

    Pitch comes from Stage 20's ``predict_divider`` and the level track from its four-parameter
    contour fit, so this is literally the Stage 20 representation - the bridge below proves it.
    """
    out: List[NoteSpec] = []
    for record in records:
        dividers = stage20.predict_divider(record, audctl)
        length = record.end - record.start + 1
        levels = stage20.contour_levels(length, record.effective_contour(True))
        out.append(
            NoteSpec(
                voice_id=record.voice_id,
                channels=tuple(record.pitch_channels),
                volume_channel=int(record.volume_channel),
                joined=bool(record.joined),
                start=int(record.start),
                end=int(record.end) + 1,
                dividers=tuple(sorted(dividers.items())),
                pack=(record.distortion & 0x0F) << 4,
                levels=tuple(int(value) for value in levels),
            )
        )
    return out


def assert_matches_stage20(trace: Any) -> Dict[str, Any]:
    """Prove that :func:`predict_from_specs` reproduces Stage 20's baseline bit for bit.

    The check runs on real songs, every register, every frame. Without it the ablation ladder would be
    measuring this module's arithmetic rather than the detector's information.
    """
    records = stage20.note_records(trace)
    reference = stage20.predict_frames(trace, records, 0, True)
    mine = predict_from_specs(
        trace.frames, int(trace.audctl), specs_from_records(records, int(trace.audctl)),
        OUTSIDE_HOLD,
    )
    mismatches = [
        (frame, column)
        for frame in range(trace.frames)
        for column in range(FRAME_BYTES)
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
            "zero mismatches means the Stage 22 predictor, fed the detector's own notes with Stage "
            "20's pitch mapping and contour fit, is the same function as stage20.predict_frames on "
            "this song"
        ),
    }


def _spec_from_ground_truth(note: GroundTruthNote, trace: Any) -> NoteSpec:
    """A spec built entirely from ground truth: exact span, exact pitch, exact level track."""
    if note.divider is None:
        raise Stage22Error(
            f"{note.song_id}: ground-truth note {note.note_index} has no divider and cannot be "
            "turned into a spec"
        )
    if note.joined:
        low, high = note.pitch_channels
        dividers = ((low, note.divider & 0xFF), (high, (note.divider >> 8) & 0xFF))
    else:
        dividers = ((note.pitch_channels[0], note.divider),)
    return NoteSpec(
        voice_id=note.voice_id,
        channels=tuple(note.pitch_channels),
        volume_channel=int(note.volume_channel),
        joined=bool(note.joined),
        start=int(note.onset_frames),
        end=int(note.onset_frames) + len(note.volume_track),
        dividers=tuple(sorted(dividers)),
        pack=note.pack,
        levels=tuple(int(value) for value in note.volume_track),
    )


def specs_from_ground_truth(notes: Sequence[GroundTruthNote]) -> List[NoteSpec]:
    """Every sounding ground-truth note as a spec. Silent notes are dropped: silence is not a note."""
    return [_spec_from_ground_truth(note, None) for note in notes if not note.silence]


# ===========================================================================
# PART 3 - residual accounting (sections 6 and 7 of the brief)
# ===========================================================================
#: The frame-level attribution buckets. They partition the trace exactly: every register value lands
#: in exactly one, and the buckets plus the residual identity are asserted rather than assumed.
ATTR_EXPLAINED = "EXPLAINED"
ATTR_VALUE_INSIDE_BOTH = "VALUE_ERROR_INSIDE_BOTH"
ATTR_FALSE_SPAN = "FALSE_SPAN"
ATTR_MISSED_SPAN = "MISSED_SPAN"
ATTR_OUTSIDE_BOTH = "OUTSIDE_BOTH"
ATTRIBUTION_BUCKETS: Tuple[str, ...] = (
    ATTR_EXPLAINED, ATTR_VALUE_INSIDE_BOTH, ATTR_FALSE_SPAN, ATTR_MISSED_SPAN, ATTR_OUTSIDE_BOTH,
)

#: The register groups the brief asks to be reported separately.
REGISTER_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("AUDF", tuple(name for name in REGISTER_ORDER if name.startswith("AUDF"))),
    ("AUDC", tuple(name for name in REGISTER_ORDER if name.startswith("AUDC"))),
    ("AUDCTL", ("AUDCTL",)),
)


def residual_of(trace: Any, predicted: Sequence[Tuple[int, ...]]) -> Any:
    """The exact residual of one prediction, in Stage 20's neutral representation."""
    return stage20.build_residual(stage21.streams_of(trace), trace, predicted)


def register_residual(residual: Any) -> Dict[str, Any]:
    """Per-register and per-group residual counts, with the denominators that make them readable."""
    per_register = {
        name: sum(1 for value in residual.values[column] if value)
        for column, name in enumerate(REGISTER_ORDER)
    }
    groups: Dict[str, Dict[str, Any]] = {}
    for group, names in REGISTER_GROUPS:
        values = sum(per_register[name] for name in names)
        total = residual.frames * len(names)
        groups[group] = {
            "residual_values": values,
            "register_values": total,
            "residual_share": _share(values, total),
            "per_register": {name: per_register[name] for name in names},
        }
    total_values = residual.frames * FRAME_BYTES
    return {
        "slug": residual.slug,
        "frames": residual.frames,
        "register_values": total_values,
        "residual_values": residual.residual_values(),
        "residual_share": _share(residual.residual_values(), total_values),
        "per_register": per_register,
        "groups": groups,
    }


def occupancy_spans_from_ground_truth(notes: Sequence[GroundTruthNote]) -> List[Any]:
    """The registers each ground-truth note drives, in the form Stage 20's classifier expects.

    A note drives its pitch channels' AUDF columns, its volume channel's AUDC column, and - when the
    pair is joined - the muted low channel's AUDC column as well. That is Stage 20's own rule, reused
    rather than restated so the two stages cannot disagree about what a note occupies.
    """
    spans = [
        stage21.OccupancySpan(
            pitch_channels=tuple(note.pitch_channels),
            volume_channel=int(note.volume_channel),
            joined=bool(note.joined),
            start=int(note.onset_frames),
            end=max(int(note.onset_frames), int(note.onset_frames) + len(note.volume_track) - 1),
        )
        for note in notes
        if not note.silence and note.volume_track
    ]
    spans.sort(key=lambda span: (span.start, span.pitch_channels))
    return spans


def frame_attribution(
    trace: Any,
    records: Sequence[Any],
    notes: Sequence[GroundTruthNote],
    residual: Any,
) -> Dict[str, Any]:
    """Attribute every residual value to one of five buckets, by *frame occupancy*.

    The rule is per register per frame, and it is the frame-level view:

    * ``VALUE_ERROR_INSIDE_BOTH`` - the frame lies inside a detected span **and** inside a
      ground-truth note, and the value is still wrong. The note was found; what was claimed about it
      is not what the trace holds. That can be a wrong pitch (a span that merged two notes), a wrong
      boundary (the span covers the frame but with the wrong extent) or a wrong level (the fitted
      contour).
    * ``FALSE_SPAN`` - inside a detected span and outside every ground-truth note: the detector
      claimed a note the composition does not have.
    * ``MISSED_SPAN`` - inside a ground-truth note and outside every detected span: the detector
      missed the note.
    * ``OUTSIDE_BOTH`` - neither claims the frame and the value is still wrong. Only a difference in
      the outside-note convention can do this, so it is that convention's signature.

    The five buckets sum to the whole trace, and that identity is asserted rather than assumed. They
    are a *frame* attribution and are deliberately not read as causes: a merged span shows up here as
    ``VALUE_ERROR_INSIDE_BOTH`` even though its cause is segmentation. Section 4's arms are what
    separate causes, and the report keeps the two readings apart.
    """
    detector_classes = stage20.register_occupancy(trace, records)
    truth_classes = stage20.register_occupancy(trace, occupancy_spans_from_ground_truth(notes))
    counts = {name: 0 for name in ATTRIBUTION_BUCKETS}
    per_register: Dict[str, Dict[str, int]] = {}
    for column, name in enumerate(REGISTER_ORDER):
        bucket = {key: 0 for key in ATTRIBUTION_BUCKETS}
        for frame in range(trace.frames):
            if not residual.values[column][frame]:
                bucket[ATTR_EXPLAINED] += 1
                continue
            in_detector = detector_classes[column][frame] != CLASS_GAP
            in_truth = truth_classes[column][frame] != CLASS_GAP
            if in_detector and in_truth:
                bucket[ATTR_VALUE_INSIDE_BOTH] += 1
            elif in_detector:
                bucket[ATTR_FALSE_SPAN] += 1
            elif in_truth:
                bucket[ATTR_MISSED_SPAN] += 1
            else:
                bucket[ATTR_OUTSIDE_BOTH] += 1
        per_register[name] = bucket
        for key in ATTRIBUTION_BUCKETS:
            counts[key] += bucket[key]
    total = trace.frames * FRAME_BYTES
    assigned = sum(counts.values())
    if assigned != total:
        raise Stage22Error(
            f"{trace.slug}: the frame attribution does not close: {assigned} assigned, {total} in "
            f"the trace, {total - assigned} unassigned"
        )
    return {
        "slug": trace.slug,
        "total_register_values": total,
        "counts": counts,
        "shares": {key: _share(value, total) for key, value in counts.items()},
        "residual_values": residual.residual_values(),
        "closes": counts[ATTR_EXPLAINED] + residual.residual_values() == total,
        "per_register": per_register,
        "rule": (
            "per register per frame: inside a detected span and inside a ground-truth note -> "
            "VALUE_ERROR_INSIDE_BOTH; inside a detected span only -> FALSE_SPAN; inside a "
            "ground-truth note only -> MISSED_SPAN; inside neither -> OUTSIDE_BOTH. The five buckets "
            "sum to the whole trace."
        ),
        "warning": (
            "a frame attribution, not a cause attribution. A span that merged two notes appears as "
            "VALUE_ERROR_INSIDE_BOTH although its cause is segmentation; the matched arms of section "
            "4 are what separate causes, and the report keeps the two readings apart."
        ),
    }



# ===========================================================================
# PART 4 - matching, the arms and the ablation ladder (sections 4, 5 and 8)
# ===========================================================================
#: The fields a rung can take from ground truth instead of from the detector. Three of them turn out
#: to be *no-ops* in this pipeline and are implemented anyway, because a field that cannot vary must
#: be measured as invariant rather than quietly dropped.
FIELD_ONSET = "onset"
FIELD_DURATION = "duration"
FIELD_PITCH = "pitch"
FIELD_CHANNEL = "channel"
FIELD_VOLUME = "volume"
FIELD_GENERATOR = "generator"
FIELD_DISTORTION = "distortion"
FIELD_ENVELOPE = "envelope"
FIELD_AUDCTL = "audctl"
FIELD_NOTE_SET = "note_set"
FIELD_ORDER: Tuple[str, ...] = (
    FIELD_ONSET, FIELD_DURATION, FIELD_PITCH, FIELD_CHANNEL, FIELD_VOLUME,
    FIELD_GENERATOR, FIELD_DISTORTION, FIELD_ENVELOPE, FIELD_AUDCTL,
)
ALL_FIELDS: frozenset = frozenset(FIELD_ORDER)
ALL_FIELDS_AND_NOTES: frozenset = frozenset(FIELD_ORDER) | {FIELD_NOTE_SET}

#: Why three of the nine fields cannot vary, stated once. Each reason is measured in the report.
FIELD_NOOP_REASONS: Dict[str, str] = {
    FIELD_CHANNEL: (
        "both arms derive their voices from the same AUDCTL through stage15.voices_for, so a note "
        "cannot be assigned to a different channel in one arm than the other; the substitution is a "
        "no-op and its measured delta is zero"
    ),
    FIELD_AUDCTL: (
        "AUDCTL is constant in every compiled trace (measured), and the predictor is given the "
        "trace's own value in both arms, so the substitution is a no-op"
    ),
    FIELD_VOLUME: (
        "the loudness scalar is the note's own peak in the ground truth and the maximum of the "
        "observed track in the detector, and on a compiled trace those are the same number; the "
        "substitution is a no-op"
    ),
}

NOTE_SET_DETECTOR = "detector"
NOTE_SET_TRUTH = "truth"
NOTE_SET_MODES: Tuple[str, ...] = (NOTE_SET_DETECTOR, NOTE_SET_TRUTH)

#: The cumulative ladder of section 4. B0 is the detector exactly; B10 is the exact composition and
#: must leave no residual. The note set moves to ground truth at B1 and stays there, because knowing
#: the exact onset *means* knowing where the notes are - and because the alternative, substituting
#: boundaries on the detector's own span list, is measured in the arms and makes the residual
#: *worse*: a span moved to a correct onset while its neighbours are still missing covers frames the
#: detector had right and leaves frames the composition has. That result is reported rather than
#: hidden, and it is why the causal claim rests on the matched arms of section 8 rather than on the
#: cumulative ladder's steps.
LADDER: Tuple[Tuple[str, frozenset, str, str], ...] = (
    ("B0", frozenset(), NOTE_SET_DETECTOR, "the Stage 15 detector exactly"),
    ("B1", frozenset({FIELD_ONSET}), NOTE_SET_TRUTH, "+ exact onset"),
    ("B2", frozenset({FIELD_ONSET, FIELD_DURATION}), NOTE_SET_TRUTH, "+ exact duration"),
    ("B3", frozenset({FIELD_ONSET, FIELD_DURATION, FIELD_PITCH}), NOTE_SET_TRUTH, "+ exact pitch"),
    ("B4", frozenset({FIELD_ONSET, FIELD_DURATION, FIELD_PITCH, FIELD_CHANNEL}), NOTE_SET_TRUTH,
     "+ exact channel"),
    ("B5", frozenset({FIELD_ONSET, FIELD_DURATION, FIELD_PITCH, FIELD_CHANNEL, FIELD_VOLUME}),
     NOTE_SET_TRUTH, "+ exact volume"),
    ("B6", frozenset({FIELD_ONSET, FIELD_DURATION, FIELD_PITCH, FIELD_CHANNEL, FIELD_VOLUME,
                      FIELD_GENERATOR}), NOTE_SET_TRUTH, "+ exact generator"),
    ("B7", frozenset({FIELD_ONSET, FIELD_DURATION, FIELD_PITCH, FIELD_CHANNEL, FIELD_VOLUME,
                      FIELD_GENERATOR, FIELD_DISTORTION}), NOTE_SET_TRUTH, "+ exact distortion"),
    ("B8", frozenset({FIELD_ONSET, FIELD_DURATION, FIELD_PITCH, FIELD_CHANNEL, FIELD_VOLUME,
                      FIELD_GENERATOR, FIELD_DISTORTION, FIELD_ENVELOPE}), NOTE_SET_TRUTH,
     "+ exact envelope"),
    ("B9", frozenset(ALL_FIELDS), NOTE_SET_TRUTH, "+ exact AUDCTL"),
    ("B10", frozenset(ALL_FIELDS), NOTE_SET_TRUTH, "the exact composition (note set and all fields)"),
)

#: The named arms of section 8's ground-truth replay. Span source and value source are orthogonal,
#: and that orthogonality is what makes each arm answer exactly one question.
#:
#: * ``move_spans`` is False for every arm here: the span stays where its own note set put it. The
#:   ladder is where ``FIELD_ONSET``/``FIELD_DURATION`` move spans, because the brief's rung B1 is
#:   literally "replace the detector's onsets with ground-truth onsets".
ARM_SPECS: Tuple[Tuple[str, frozenset, str, bool, str], ...] = (
    ("A_detector", frozenset(), NOTE_SET_DETECTOR, False, "the detector exactly (B0)"),
    ("A_detector_spans_truth_values", frozenset(ALL_FIELDS), NOTE_SET_DETECTOR, False,
     "the detector's own spans and count, every value exact - isolates the note set"),
    ("A_detector_spans_truth_boundaries", frozenset({FIELD_ONSET, FIELD_DURATION}),
     NOTE_SET_DETECTOR, True,
     "the detector's own span list with the boundaries moved to the matched notes - the "
     "contradictory arm, reported because it is worse than the detector"),
    ("A_truth_spans_detector_values", frozenset(), NOTE_SET_TRUTH, False,
     "the composition's note set and spans, every value still read the detector's way - isolates "
     "the value reading"),
    ("A_exact", frozenset(ALL_FIELDS), NOTE_SET_TRUTH, False,
     "the exact composition (B10); must be zero"),
)





def _observed_levels(trace: Any, volume_channel: int, start: int, end: int) -> Tuple[int, ...]:
    """The AUDC level track the trace actually holds over ``[start, end)``."""
    audc = trace.registers[f"AUDC{volume_channel}"]
    return tuple(
        stage15.audc_volume(audc[frame])
        for frame in range(max(0, start), max(0, min(end, trace.frames)))
    )


def _span_overlap(left: Tuple[int, int], right: Tuple[int, int]) -> int:
    """Frames two half-open spans share."""
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def match_truth_to_records(
    truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Match ground-truth notes to detected spans by maximum frame overlap, deterministically.

    Ties break on the smaller absolute onset difference, then the smaller start frame, then the
    smaller index. Every tie-break is a comparison on integers, so the result cannot depend on
    iteration order or on hash randomisation - which the brief requires and the test suite asserts.

    The two maps are not inverses of one another and that is the point: a *merge* is one detected
    span matched by several ground-truth notes, and a *split* is one ground-truth note matched by
    several detected spans. Both directions are reported separately.
    """
    truth_to_record: Dict[int, int] = {}
    for index, note in enumerate(truth):
        if note.silence:
            continue
        span = (note.onset_frames, note.onset_frames + max(1, len(note.volume_track)))
        best: Optional[Tuple[Tuple[int, int, int, int], int]] = None
        for order, record in enumerate(records):
            if record.voice_id != note.voice_id:
                continue
            other = (record.start, record.end + 1)
            overlap = _span_overlap(span, other)
            if overlap <= 0:
                continue
            key = (-overlap, abs(record.start - note.onset_frames), record.start, order)
            if best is None or key < best[0]:
                best = (key, order)
        if best is not None:
            truth_to_record[index] = best[1]
    record_to_truth: Dict[int, int] = {}
    for order, record in enumerate(records):
        other = (record.start, record.end + 1)
        best: Optional[Tuple[Tuple[int, int, int, int], int]] = None
        for index, note in enumerate(truth):
            if note.silence or note.voice_id != record.voice_id:
                continue
            span = (note.onset_frames, note.onset_frames + max(1, len(note.volume_track)))
            overlap = _span_overlap(span, other)
            if overlap <= 0:
                continue
            key = (-overlap, abs(note.onset_frames - record.start), note.onset_frames, index)
            if best is None or key < best[0]:
                best = (key, index)
        if best is not None:
            record_to_truth[order] = best[1]
    return truth_to_record, record_to_truth


def _measure(trace: Any, specs: Sequence[NoteSpec], outside: str) -> Tuple[Any, Dict[str, Any]]:
    """Predict from specs, form the residual, and report it per register group."""
    predicted = predict_from_specs(trace.frames, int(trace.audctl), specs, outside)
    residual = residual_of(trace, predicted)
    return residual, register_residual(residual)


def run_ladder(
    trace: Any,
    truth: Sequence[GroundTruthNote],
    records: Sequence[Any],
    outside: str = OUTSIDE_EXPORTER,
) -> Dict[str, Any]:
    """The cumulative ladder of section 4, with each step's delta reported.

    A step's delta is the residual the newly added field removes, in register values and in share
    points. The final rung must be zero and the function says so rather than assuming it: if B10
    leaves anything, that is a finding about this module's ground truth, not something to round away.
    """
    rungs: List[Dict[str, Any]] = []
    previous: Optional[int] = None
    total = trace.frames * FRAME_BYTES
    for name, exact, note_set, description in LADDER:
        specs, provenance = build_specs(trace, truth, records, exact, note_set)
        residual, report = _measure(trace, specs, outside)
        value = residual.residual_values()
        rungs.append({
            "rung": name,
            "description": description,
            "exact_fields": sorted(exact),
            "note_set": note_set,
            "residual_values": value,
            "residual_share": _share(value, total),
            "groups": {key: row["residual_values"] for key, row in report["groups"].items()},
            "delta_values": None if previous is None else previous - value,
            "delta_share": None if previous is None else _share(previous - value, total),
            "provenance": provenance,
        })
        previous = value
    return {
        "slug": trace.slug,
        "frames": trace.frames,
        "register_values": total,
        "outside_policy": outside,
        "rungs": rungs,
        "b0_values": rungs[0]["residual_values"],
        "b10_values": rungs[-1]["residual_values"],
        "b10_is_zero": rungs[-1]["residual_values"] == 0,
        "noop_fields": {
            field: FIELD_NOOP_REASONS[field]
            for field in (FIELD_CHANNEL, FIELD_AUDCTL, FIELD_VOLUME)
        },
    }


def run_arms(
    trace: Any,
    truth: Sequence[GroundTruthNote],
    records: Sequence[Any],
    outside: str = OUTSIDE_EXPORTER,
) -> Dict[str, Any]:
    """The five named arms of section 8, each isolating one question."""
    total = trace.frames * FRAME_BYTES
    arms: Dict[str, Any] = {}
    for name, exact, note_set, move_spans, description in ARM_SPECS:
        specs, provenance = build_specs(trace, truth, records, exact, note_set, move_spans)
        residual, report = _measure(trace, specs, outside)
        value = residual.residual_values()
        arms[name] = {
            "description": description,
            "exact_fields": sorted(exact),
            "note_set": note_set,
            "residual_values": value,
            "residual_share": _share(value, total),
            "groups": {key: row["residual_values"] for key, row in report["groups"].items()},
            "provenance": provenance,
        }
    return {"slug": trace.slug, "register_values": total, "outside_policy": outside, "arms": arms}


def run_leave_one_out(
    trace: Any,
    truth: Sequence[GroundTruthNote],
    records: Sequence[Any],
    outside: str = OUTSIDE_EXPORTER,
) -> Dict[str, Any]:
    """Section 5's leave-one-out: everything exact except one field, on the exact note set.

    Because the exact note set with every field exact leaves nothing, *removing* one field measures
    that field's marginal contribution with no ordering assumption at all. This is the arm that
    answers the brief's worry that a generator error might be masquerading as a pitch error: a field
    that is genuinely not the cause shows a delta of zero here even when every other field is exact.
    """
    total = trace.frames * FRAME_BYTES
    full, _ = build_specs(trace, truth, records, ALL_FIELDS, NOTE_SET_TRUTH, False)
    full_residual, _ = _measure(trace, full, outside)
    baseline = full_residual.residual_values()
    fields: Dict[str, Any] = {}
    for field in FIELD_ORDER:
        exact = frozenset(ALL_FIELDS - {field})
        specs, provenance = build_specs(trace, truth, records, exact, NOTE_SET_TRUTH, False)
        residual, report = _measure(trace, specs, outside)
        value = residual.residual_values()
        fields[field] = {
            "exact_fields": sorted(exact),
            "residual_values": value,
            "residual_share": _share(value, total),
            "marginal_values": value - baseline,
            "marginal_share": _share(value - baseline, total),
            "groups": {key: row["residual_values"] for key, row in report["groups"].items()},
            "is_noop": field in FIELD_NOOP_REASONS,
            "provenance": provenance,
        }
    # The note set is not a field of a note, so it is measured as its own arm.
    no_fields, no_provenance = build_specs(
        trace, truth, records, frozenset(), NOTE_SET_TRUTH, False
    )
    no_residual, no_report = _measure(trace, no_fields, outside)
    return {
        "slug": trace.slug,
        "register_values": total,
        "outside_policy": outside,
        "baseline_all_exact_values": baseline,
        "fields": fields,
        "note_set_arm": {
            "description": "the composition's note set with every value read the detector's way",
            "residual_values": no_residual.residual_values(),
            "residual_share": _share(no_residual.residual_values(), total),
            "marginal_values": no_residual.residual_values() - baseline,
            "groups": {key: row["residual_values"] for key, row in no_report["groups"].items()},
            "provenance": no_provenance,
        },
        "field_scope_note": (
            "the leave-one-out runs on the exact note set, where a span is the composition's own. "
            "Onset and duration are therefore exact by construction and their marginal delta is zero "
            "here by definition, not by measurement: their contribution is measured on the detector's "
            "note set instead, in the note-detection analysis. The note-set arm above is what "
            "measures the note set itself."
        ),
    }


def _spec_for(
    trace: Any,
    note: Optional[GroundTruthNote],
    exact: frozenset,
    start: int,
    end: int,
    voice_id: str,
    channels: Tuple[int, ...],
    volume_channel: int,
    joined: bool,
) -> NoteSpec:
    """One spec, with each field taken from ground truth or read the detector's way.

    The span is passed in rather than derived, because the ladder moves it: rung B1 uses the
    detector's boundaries with the composition's onsets, and rung B2 uses the composition's own.
    Everything else is a field-level choice, and every choice is made by the same rule - *is this
    field in the exact set?* - so a rung cannot accidentally mix two definitions.
    """
    length = max(0, end - start)
    observed = _observed_levels(trace, volume_channel, start, end)
    audc = trace.registers[f"AUDC{volume_channel}"]
    if FIELD_PITCH in exact and note is not None and note.divider is not None:
        if joined:
            low, high = channels
            dividers = ((low, note.divider & 0xFF), (high, (note.divider >> 8) & 0xFF))
        else:
            dividers = ((channels[0], note.divider),)
    else:
        voice = next(v for v in stage15.voices_for(int(trace.audctl)) if v.voice_id == voice_id)
        divider = stage15.divider_for(voice, start, trace.registers)
        hz = stage15.divider_to_hz(divider, voice, int(trace.audctl))
        proxy = type("Proxy", (), {
            "joined": joined, "pitch_channels": channels, "hz": hz,
        })()
        dividers = tuple(sorted(stage20.predict_divider(proxy, int(trace.audctl)).items()))
    if (FIELD_GENERATOR in exact or FIELD_DISTORTION in exact) and note is not None:
        pack = note.pack
    else:
        pack = ((stage15.audc_distortion(audc[start]) & 0x0F) << 4) if length else 0
    if FIELD_ENVELOPE in exact:
        levels = observed
    else:
        peak, attack, sustain, release = stage20.fit_contour(observed)
        levels = tuple(stage20.contour_levels(length, (peak, attack, sustain, release)))
    return NoteSpec(
        voice_id=voice_id,
        channels=tuple(channels),
        volume_channel=int(volume_channel),
        joined=bool(joined),
        start=int(start),
        end=int(start) + length,
        dividers=tuple(dividers),
        pack=int(pack),
        levels=tuple(int(value) for value in levels),
    )


def build_specs(
    trace: Any,
    truth: Sequence[GroundTruthNote],
    records: Sequence[Any],
    exact: frozenset,
    note_set: str = NOTE_SET_DETECTOR,
    move_spans: bool = True,
) -> Tuple[List[NoteSpec], Dict[str, Any]]:
    """Build the specs for one rung of the ladder or one named arm.

    Two note sets are available and the difference between them is the whole point of the ladder's
    first step:

    * ``detector`` - the spans Stage 15 found. Their number and their order are the detector's, so a
      note the detector missed stays missed no matter how many fields are made exact.
    * ``truth`` - the composition's own notes. Every sounding note is present, so the note-set error
      is zero by construction and whatever residual remains is a *value* error.

    ``move_spans`` decides whether ``FIELD_ONSET`` and ``FIELD_DURATION`` are allowed to move a span
    off its own note set's position. The ladder needs them to (rung B1 is "the detector's spans at
    the composition's onsets"), and the named arms must not (an arm called "the detector's spans with
    exact values" has to keep the detector's spans, or its name is a lie).
    """
    if note_set not in NOTE_SET_MODES:
        raise Stage22Error(f"unknown note set {note_set!r}")
    audctl = int(trace.audctl)
    voices = {voice.voice_id: voice for voice in stage15.voices_for(audctl)}
    truth_to_record, record_to_truth = match_truth_to_records(truth, records)
    specs: List[NoteSpec] = []
    matched = moved = unmatched = 0
    if note_set == NOTE_SET_DETECTOR:
        for order, record in enumerate(records):
            voice = voices[record.voice_id]
            index = record_to_truth.get(order)
            note = truth[index] if index is not None else None
            if note is None:
                unmatched += 1
            else:
                matched += 1
            start, end = int(record.start), int(record.end) + 1
            if note is not None and move_spans:
                if FIELD_ONSET in exact:
                    start = int(note.onset_frames)
                    moved += 1
                if FIELD_DURATION in exact:
                    end = int(note.onset_frames) + max(1, len(note.volume_track))
            specs.append(
                _spec_for(
                    trace, note, exact, start, end, record.voice_id,
                    tuple(voice.channels), int(voice.volume_channel), bool(voice.joined),
                )
            )
    else:
        for index, note in enumerate(truth):
            if note.silence:
                continue
            voice = voices[note.voice_id]
            start = int(note.onset_frames)
            end = start + max(1, len(note.volume_track))
            order = truth_to_record.get(index)
            if order is None:
                unmatched += 1
            else:
                matched += 1
                record = records[order]
                if move_spans and FIELD_ONSET not in exact:
                    start = int(record.start)
                    moved += 1
                if move_spans and FIELD_DURATION not in exact:
                    end = start + (int(record.end) - int(record.start) + 1)
            specs.append(
                _spec_for(
                    trace, note, exact, start, end, note.voice_id,
                    tuple(voice.channels), int(voice.volume_channel), bool(voice.joined),
                )
            )
    specs.sort(key=lambda spec: (spec.start, spec.voice_id, spec.end))
    return specs, {
        "note_set": note_set,
        "exact_fields": sorted(exact),
        "move_spans": bool(move_spans),
        "spec_count": len(specs),
        "matched": matched,
        "unmatched": unmatched,
        "spans_moved": moved,
        "silent_truth_notes": sum(1 for note in truth if note.silence),
    }


# ===========================================================================
# PART 5 - the specialised error analyses (sections 9 to 14 of the brief)
# ===========================================================================
def _precision_recall(
    true_positive: int, false_positive: int, false_negative: int
) -> Dict[str, Any]:
    """Precision, recall and F1 from the three counts, with the degenerate cases named."""
    precision = _share(true_positive, true_positive + false_positive)
    recall = _share(true_positive, true_positive + false_negative)
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = round(2 * precision * recall / (precision + recall), 6)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _divider_at(record: Any, note: GroundTruthNote, trace: Any) -> Optional[Dict[int, int]]:
    """The divider the detector would predict for a note, read from the trace at a frame."""
    voice = next(
        v for v in stage15.voices_for(int(trace.audctl)) if v.voice_id == note.voice_id
    )
    divider = stage15.divider_for(voice, int(record.start), trace.registers)
    hz = stage15.divider_to_hz(divider, voice, int(trace.audctl))
    proxy = type("Proxy", (), {
        "joined": bool(note.joined),
        "pitch_channels": tuple(note.pitch_channels),
        "hz": hz,
    })()
    return stage20.predict_divider(proxy, int(trace.audctl))


def _expected_divider(note: GroundTruthNote, trace: Any) -> Optional[Dict[int, int]]:
    """The divider the composition states, through the same mapping the detector uses."""
    if note.divider is None or note.hz is None:
        return None
    proxy = type("Proxy", (), {
        "joined": bool(note.joined),
        "pitch_channels": tuple(note.pitch_channels),
        "hz": note.hz,
    })()
    return stage20.predict_divider(proxy, int(trace.audctl))


def match_statistics(
    truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """The counts that both the note analysis and the per-song aggregation are built from."""
    truth_to_record, record_to_truth = match_truth_to_records(truth, records)
    sounding = [note for note in truth if not note.silence]
    notes_per_record: Dict[int, int] = {}
    for index in truth_to_record.values():
        notes_per_record[index] = notes_per_record.get(index, 0) + 1
    records_per_note: Dict[int, int] = {}
    for order in record_to_truth.values():
        records_per_note[order] = records_per_note.get(order, 0) + 1
    return {
        "truth_to_record": truth_to_record,
        "record_to_truth": record_to_truth,
        "ground_truth_notes": len(sounding),
        "detected_spans": len(records),
        "matched_notes": len(truth_to_record),
        "matched_spans": len(record_to_truth),
        "missed_notes": len(sounding) - len(truth_to_record),
        "false_spans": len(records) - len(record_to_truth),
        "merged_spans": sum(1 for count in notes_per_record.values() if count >= 2),
        "split_notes": sum(1 for count in records_per_note.values() if count >= 2),
    }





def note_detection_errors(
    trace: Any,
    truth: Sequence[GroundTruthNote],
    records: Sequence[Any],
) -> Dict[str, Any]:
    """Section 10's note-boundary analysis, on the deterministic overlap matching.

    A detected span and a ground-truth note are *matched* when they share at least one frame on the
    same voice. Every count that follows is defined from that one relation, so nothing double-counts:
    a merge is one span matched by two notes, a split is one note matched by two spans, and a span
    with no match at all is false.

    Both a by-count and a by-frame view are reported, because they answer different questions. A
    missed two-frame note costs almost nothing in frames and a whole note in count; a missed
    hundred-frame note is the reverse.
    """
    stats = match_statistics(truth, records)
    truth_to_record = stats["truth_to_record"]
    note_frames = {
        index: max(1, len(note.volume_track))
        for index, note in enumerate(truth) if not note.silence
    }
    span_frames = {order: int(record.end) - int(record.start) + 1
                   for order, record in enumerate(records)}
    onset_errors: List[int] = []
    duration_errors: List[int] = []
    pitch_exact = 0
    pitch_compared = 0
    for index, order in sorted(truth_to_record.items()):
        note = truth[index]
        record = records[order]
        onset_errors.append(int(record.start) - int(note.onset_frames))
        duration_errors.append(span_frames[order] - max(1, len(note.volume_track)))
        expected = _expected_divider(note, trace)
        got = _divider_at(record, note, trace)
        if expected is not None and got is not None:
            pitch_compared += 1
            if got == expected:
                pitch_exact += 1
    truth_frame_total = sum(note_frames.values())
    span_frame_total = sum(span_frames.values())
    matched_truth_frames = sum(note_frames[index] for index in truth_to_record)
    matched_span_frames = sum(span_frames[order] for order in stats["record_to_truth"])
    absolute = [abs(value) for value in onset_errors]
    # A note matched by overlap can still have frames no span covers, because a merged span's end
    # falls short of the notes it absorbed. Counting only whole missing notes would hide that, so the
    # frame-level shortfall is counted separately and used by the taxonomy.
    covered = [False] * trace.frames
    for record in records:
        for frame in range(int(record.start), min(int(record.end) + 1, trace.frames)):
            covered[frame] = True
    notes_with_uncovered_frames = 0
    uncovered_note_frames = 0
    for note in truth:
        if note.silence:
            continue
        span = range(
            note.onset_frames, min(note.onset_frames + max(1, len(note.volume_track)),
                                   trace.frames)
        )
        gaps = sum(1 for frame in span if not covered[frame])
        if gaps:
            notes_with_uncovered_frames += 1
            uncovered_note_frames += gaps
    exact_boundary_spans = sum(
        1 for index, order in truth_to_record.items()
        if int(records[order].start) == int(truth[index].onset_frames)
        and (int(records[order].end) - int(records[order].start) + 1)
        == max(1, len(truth[index].volume_track))
    )
    return {
        "slug": trace.slug,
        "ground_truth_notes": stats["ground_truth_notes"],
        "detected_spans": stats["detected_spans"],
        "matched_notes": stats["matched_notes"],
        "matched_spans": stats["matched_spans"],
        "missed_ground_truth_notes": stats["missed_notes"],
        "false_detector_spans": stats["false_spans"],
        "merged_spans": stats["merged_spans"],
        "split_notes": stats["split_notes"],
        "by_count": _precision_recall(
            stats["matched_spans"], stats["false_spans"], stats["missed_notes"]
        ),
        "by_frames": _precision_recall(
            matched_span_frames, span_frame_total - matched_span_frames,
            truth_frame_total - matched_truth_frames,
        ),
        "ground_truth_frames": truth_frame_total,
        "detected_frames": span_frame_total,
        "onset_error_median": _median(onset_errors),
        "onset_error_mean": _mean([float(value) for value in onset_errors]),
        "onset_error_max_abs": max(absolute, default=0),
        "onset_exact_share": _share(
            sum(1 for value in onset_errors if value == 0), len(onset_errors)
        ),
        "duration_error_median": _median(duration_errors),
        "duration_error_max_abs": max((abs(value) for value in duration_errors), default=0),
        "duration_exact_share": _share(
            sum(1 for value in duration_errors if value == 0), len(duration_errors)
        ),
        "pitch_at_matched_onset_compared": pitch_compared,
        "pitch_at_matched_onset_exact": pitch_exact,
        "pitch_at_matched_onset_exact_share": _share(pitch_exact, pitch_compared),
        "notes_with_uncovered_frames": notes_with_uncovered_frames,
        "uncovered_note_frames": uncovered_note_frames,
        "exact_boundary_spans": exact_boundary_spans,
        "exact_boundary_share": _share(exact_boundary_spans, stats["matched_spans"]),
        "matching_rule": (
            "a detected span and a ground-truth note match when they share at least one frame on the "
            "same voice; ties break on the smaller onset difference, then the smaller start, then "
            "the smaller index. A note matched by overlap can still have frames no span covers, "
            "because a merged span's end falls short of the notes it absorbed, so the frame-level "
            "shortfall is counted separately from the whole-note count."
        ),
    }


def pitch_errors(
    trace: Any, truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """Section 11's pitch analysis: divider agreement at matched onsets, and the non-pitched cases.

    ``AUDF != the expected musical pitch`` is *not* the same as a detector error, and the brief says
    so explicitly: a noise generator uses AUDF as a clock divisor rather than as a pitch. The analysis
    therefore splits the matched notes by generator family first and reports divider agreement inside
    each, so a noise channel's register cannot be counted as a wrong pitch.
    """
    stats = match_statistics(truth, records)
    exact = compared = 0
    semitones: List[float] = []
    octave_errors = 0
    coupled_notes = 0
    by_generator: Dict[str, Dict[str, int]] = {}
    for index, order in sorted(stats["truth_to_record"].items()):
        note = truth[index]
        record = records[order]
        expected = _expected_divider(note, trace)
        got = _divider_at(record, note, trace)
        if expected is None or got is None:
            continue
        compared += 1
        if note.joined:
            coupled_notes += 1
        voice = next(
            v for v in stage15.voices_for(int(trace.audctl)) if v.voice_id == note.voice_id
        )
        waveform = stage15.audc_waveform(
            trace.registers[f"AUDC{note.volume_channel}"][record.start]
        )
        family = "noise" if stage15.waveform_is_noise(waveform) else (
            "tonal" if stage15.waveform_is_tonal(waveform) else "silent"
        )
        bucket = by_generator.setdefault(family, {"compared": 0, "exact": 0})
        bucket["compared"] += 1
        if got == expected:
            exact += 1
            bucket["exact"] += 1
            continue
        divider_expected = stage15.divider_for(voice, int(note.onset_frames), trace.registers)
        divider_got = stage15.divider_for(voice, int(record.start), trace.registers)
        value = stage15.semitones_between(
            stage15.divider_to_hz(divider_expected, voice, int(trace.audctl)),
            stage15.divider_to_hz(divider_got, voice, int(trace.audctl)),
        )
        if value is not None:
            semitones.append(value)
            if abs(round(value / 12.0)) >= 1:
                octave_errors += 1
    magnitudes = [abs(value) for value in semitones]
    return {
        "slug": trace.slug,
        "matched_compared": compared,
        "divider_exact": exact,
        "divider_exact_share": _share(exact, compared),
        "coupled_16bit_notes": coupled_notes,
        "by_generator_family": by_generator,
        "semitone_error_median_abs": _median(magnitudes),
        "semitone_error_mean_abs": _mean(magnitudes),
        "semitone_error_max_abs": max(magnitudes, default=0.0),
        "octave_or_register_errors": octave_errors,
        "reading": (
            "the divider comparison is made through the same mapping the detector uses, at the onset "
            "the detector actually read, so an exact match means the detector's pitch read is right "
            "at the frame it read. Non-tonal generators are separated out because AUDF is a clock "
            "divisor there, not a pitch."
        ),
    }


def _change_frames(values: Sequence[int]) -> List[int]:
    """Frames where a per-frame sequence changes value; the first frame always counts."""
    out: List[int] = []
    previous: Optional[int] = None
    for frame, value in enumerate(values):
        if previous is None or value != previous:
            out.append(frame)
        previous = value
    return out


def generator_errors(
    trace: Any, truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """Section 9's generator and distortion analysis, classification and transitions apart.

    The brief asks for these to be separated and they are genuinely different questions:

    * **classification** - when the detector reports a generator at an onset, is it the right one?
      Measured over the matched spans' onsets.
    * **transition detection** - the trace changes its distortion nibble at certain frames; the
      detector's representation can only change it where a span begins. Measured over *change
      points*, which is where a merged span or a missed note shows up.

    Both are reported for the nibble and for the decoded waveform family, because a wrong family and
    a wrong nibble are different errors: the family is what the channel sounds like, the nibble is
    which of POKEY's eight distortion modes it uses.
    """
    stats = match_statistics(truth, records)
    voices_used = sorted({record.voice_id for record in records})
    specs = specs_from_records(records, int(trace.audctl))
    classification: Dict[str, Any] = {}
    true_frames: List[int] = []
    predicted_frames: List[int] = []
    for voice_id in voices_used:
        voice = next(v for v in stage15.voices_for(int(trace.audctl)) if v.voice_id == voice_id)
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        truth_nibbles = [stage15.audc_distortion(audc[frame]) for frame in range(trace.frames)]
        truth_families = [stage15.audc_waveform(audc[frame]) for frame in range(trace.frames)]
        true_frames.extend(_change_frames(truth_nibbles))
        predicted_frames.extend(
            sorted(int(record.start) for record in records if record.voice_id == voice_id)
        )
        predicted = predict_from_specs(
            trace.frames, int(trace.audctl),
            [spec for spec in specs if spec.voice_id == voice_id],
            OUTSIDE_EXPORTER,
        )
        column = AUDC_COLUMN[voice.volume_channel]
        predicted_nibbles = [stage15.audc_distortion(row[column]) for row in predicted]
        predicted_families = [stage15.audc_waveform(row[column]) for row in predicted]
        classification[voice_id] = {
            "frames": trace.frames,
            "nibble_frames_matching": sum(
                1 for frame in range(trace.frames)
                if predicted_nibbles[frame] == truth_nibbles[frame]
            ),
            "family_frames_matching": sum(
                1 for frame in range(trace.frames)
                if predicted_families[frame] == truth_families[frame]
            ),
            "truth_nibble_changes": len(_change_frames(truth_nibbles)),
            "predicted_nibble_changes": len(_change_frames(predicted_nibbles)),
            "truth_family_changes": len(_change_frames(truth_families)),
            "predicted_family_changes": len(_change_frames(predicted_families)),
        }
    onset_correct = onset_compared = 0
    for index, order in sorted(stats["truth_to_record"].items()):
        note = truth[index]
        record = records[order]
        audc = trace.registers[f"AUDC{note.volume_channel}"]
        onset_compared += 1
        if stage15.audc_distortion(audc[record.start]) == (note.pack >> 4):
            onset_correct += 1
    true_set = set(true_frames)
    predicted_set = set(predicted_frames)
    return {
        "slug": trace.slug,
        "classification": classification,
        "onset_distortion_correct": onset_correct,
        "onset_distortion_compared": onset_compared,
        "onset_distortion_correct_share": _share(onset_correct, onset_compared),
        "transition_detection": {
            "truth_change_frames": len(true_set),
            "predicted_change_frames": len(predicted_set),
            "hits": len(true_set & predicted_set),
            "missed": len(true_set - predicted_set),
            "spurious": len(predicted_set - true_set),
            "metrics": _precision_recall(
                len(true_set & predicted_set), len(predicted_set - true_set),
                len(true_set - predicted_set),
            ),
        },
        "reading": (
            "classification is measured over the matched spans' onsets and transition detection over "
            "the frames where the register actually changes. A detector that reads every onset "
            "correctly can still miss every transition, because a merged span has only one onset."
        ),
    }





def song_features(
    trace: Any, truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """The song-level features section 15 correlates detector error against.

    Every feature is a count or a ratio computed from the ground truth and the trace, never from the
    residual, so a correlation with the residual is not circular.
    """
    sounding = [note for note in truth if not note.silence]
    coverage = [0] * trace.frames
    for note in sounding:
        for frame in range(
            note.onset_frames, min(note.onset_frames + len(note.volume_track), trace.frames)
        ):
            coverage[frame] += 1
    level_changes = 0
    for voice in stage15.voices_for(int(trace.audctl)):
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        levels = [stage15.audc_volume(audc[frame]) for frame in range(trace.frames)]
        level_changes += len(_change_frames(levels))
    distortion_changes = 0
    for voice in stage15.voices_for(int(trace.audctl)):
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        nibbles = [stage15.audc_distortion(audc[frame]) for frame in range(trace.frames)]
        distortion_changes += len(_change_frames(nibbles))
    return {
        "channels": len(stage15.voices_for(int(trace.audctl))),
        "ground_truth_notes": len(sounding),
        "detected_spans": len(records),
        "length_frames": trace.frames,
        "max_polyphony": max(coverage) if coverage else 0,
        "polyphonic_frames": sum(1 for value in coverage if value >= 2),
        "polyphonic_share": _share(sum(1 for value in coverage if value >= 2), trace.frames),
        "generator_diversity": len({note.generator_distortion for note in sounding}),
        "distortion_diversity": len({(note.generator_distortion >> 5) & 0x07
                                     for note in sounding}),
        "generator_changes": distortion_changes,
        "volume_changes": level_changes,
        "coupled_16bit": bool(sounding[0].coupled_16bit) if sounding else False,
        "distinct_pitches": len({note.pitch_midi for note in sounding
                                 if note.pitch_midi is not None}),
        "silent_notes": sum(1 for note in truth if note.silence),
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson's r, or ``None`` when either series has no variance."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [value - mean_x for value in xs]
    dy = [value - mean_y for value in ys]
    numerator = sum(a * b for a, b in zip(dx, dy))
    left = sum(a * a for a in dx) ** 0.5
    right = sum(b * b for b in dy) ** 0.5
    if left == 0 or right == 0:
        return None
    return round(numerator / (left * right), 6)


def _ranks(values: Sequence[float]) -> List[float]:
    """Average ranks, ties included, so a Spearman correlation is defined on tied data."""
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman's rho through Pearson on average ranks."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def analyse_song(song: Any, detail: bool = True) -> Dict[str, Any]:
    """Everything Stage 22 measures for one control composition.

    The detector is run exactly as Stage 20 and Stage 21 run it, through ``stage20.note_records`` and
    ``stage20.predict_frames``, and the residual is formed with ``stage20.build_residual``. Nothing
    about the detector is re-implemented here; only the *variations* are, and they are proved against
    the original by the bridge.
    """
    trace = song.trace
    truth, status = ground_truth_notes(song, trace)
    records = stage20.note_records(trace)
    predicted = stage20.predict_frames(trace, records, 0, True)
    residual = residual_of(trace, predicted)
    attribution = frame_attribution(trace, records, truth, residual)
    row: Dict[str, Any] = {
        "slug": song.slug,
        "kind": song.kind,
        "frames": trace.frames,
        "audctl": f"${int(trace.audctl):02X}",
        "coupled_16bit": bool(song.uses_16bit_bass),
        "audctl_constant": len(set(trace.registers["AUDCTL"])) == 1,
        "ground_truth_notes": sum(1 for note in truth if not note.silence),
        "silent_notes": sum(1 for note in truth if note.silence),
        "detected_spans": len(records),
        "residual": register_residual(residual),
        "attribution": attribution,
        "features": song_features(trace, truth, records),
    }
    if not detail:
        return row
    row["bridge"] = assert_matches_stage20(trace)
    row["ladder_hold"] = run_ladder(trace, truth, records, OUTSIDE_HOLD)
    row["ladder_exporter"] = run_ladder(trace, truth, records, OUTSIDE_EXPORTER)
    row["arms"] = run_arms(trace, truth, records, OUTSIDE_EXPORTER)
    row["arms_hold"] = run_arms(trace, truth, records, OUTSIDE_HOLD)
    exporter_predicted = predict_from_specs(
        trace.frames, int(trace.audctl), specs_from_records(records, int(trace.audctl)),
        OUTSIDE_EXPORTER,
    )
    row["residual_exporter"] = register_residual(residual_of(trace, exporter_predicted))
    row["leave_one_out"] = run_leave_one_out(trace, truth, records, OUTSIDE_EXPORTER)
    row["note_detection"] = note_detection_errors(trace, truth, records)
    row["pitch"] = pitch_errors(trace, truth, records)
    row["generator"] = generator_errors(trace, truth, records)
    row["channel"] = channel_errors(trace, truth, records)
    row["timing"] = timing_errors(trace, truth, records)
    row["silence"] = silence_errors(trace, truth, records, attribution)
    row["detector"] = {
        "residual_values": residual.residual_values(),
        "residual_share": _share(residual.residual_values(), trace.frames * FRAME_BYTES),
        "register_values": trace.frames * FRAME_BYTES,
    }
    return row


def channel_errors(
    trace: Any, truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """Section 12's channel analysis, including the ambiguity the brief asks to be labelled.

    Two questions are separated, and the first is answered by construction rather than by
    measurement:

    * **assignment** - could the detector have put a note on the wrong channel? Both arms derive
      their voices from the same AUDCTL through ``stage15.voices_for``, so the voice a frame belongs
      to is a property of the trace's configuration, not of the detector. The measured difference is
      therefore zero on every song, and the reason is reported rather than the zero being presented
      as a success.
    * **ambiguity** - where two voices hold the same divider, the same generator and the same level
      in the same frame, the registers do not say which channel a listener would call the melody. The
      brief requires that to be labelled ``AMBIGUOUS`` rather than scored as a detector failure, so
      the frames are counted and reported as such.
    """
    stats = match_statistics(truth, records)
    voices = stage15.voices_for(int(trace.audctl))
    mismatched = 0
    for index, order in sorted(stats["truth_to_record"].items()):
        if truth[index].voice_id != records[order].voice_id:
            mismatched += 1
    ambiguous_frames = 0
    ambiguous_pairs: List[Tuple[str, str]] = []
    if len(voices) >= 2:
        signatures: List[Tuple[Tuple[int, int, int], ...]] = []
        for voice in voices:
            audc = trace.registers[f"AUDC{voice.volume_channel}"]
            signatures.append(tuple(
                (
                    stage15.divider_for(voice, frame, trace.registers),
                    stage15.audc_distortion(audc[frame]),
                    stage15.audc_volume(audc[frame]),
                )
                for frame in range(trace.frames)
            ))
        for left in range(len(voices)):
            for right in range(left + 1, len(voices)):
                same = sum(
                    1 for frame in range(trace.frames)
                    if signatures[left][frame] == signatures[right][frame]
                    and signatures[left][frame][2] > 0
                )
                if same:
                    ambiguous_frames += same
                    ambiguous_pairs.append((voices[left].voice_id, voices[right].voice_id))
    coupled = [voice.voice_id for voice in voices if voice.joined]
    return {
        "slug": trace.slug,
        "voices": [voice.voice_id for voice in voices],
        "matched_voice_mismatches": mismatched,
        "matched_compared": stats["matched_spans"],
        "voice_assignment_differs_share": _share(mismatched, stats["matched_spans"]),
        "coupled_voices": coupled,
        "ambiguous_frame_pairs": ambiguous_frames,
        "ambiguous_voice_pairs": ambiguous_pairs,
        "flag": "AMBIGUOUS" if ambiguous_frames else "UNAMBIGUOUS",
        "reading": (
            "voice assignment cannot differ between the arms because both read it from the trace's "
            "own AUDCTL; the zero is a property of the pipeline, not a detector achievement. The "
            "ambiguity count is the honest channel-level uncertainty: frames where two voices are "
            "register-identical and a listener could not tell them apart."
        ),
    }



def timing_errors(
    trace: Any, truth: Sequence[GroundTruthNote], records: Sequence[Any]
) -> Dict[str, Any]:
    """Section 13's timing analysis: offsets, quantisation and ordering.

    Frame quantisation is measured against the composition's own grid, because that is the only grid
    that exists here: a note's onset is a whole number of rows from the start of its pattern, so on a
    compiled trace every ground-truth onset is a multiple of ``frames_per_tick``. Whether the
    detector's onsets stay on that grid is a measurable question, and its answer says whether the
    detector is reporting musical positions or register-change positions.
    """
    stats = match_statistics(truth, records)
    frames_per_tick = max(1, int(truth[0].frames_per_tick)) if truth else 1
    onset_offsets: List[int] = []
    duration_offsets: List[int] = []
    order_violations = 0
    previous_truth = -1
    previous_record = -1
    for index, order in sorted(stats["truth_to_record"].items()):
        note = truth[index]
        record = records[order]
        onset_offsets.append(int(record.start) - int(note.onset_frames))
        duration_offsets.append(
            (int(record.end) - int(record.start) + 1) - max(1, len(note.volume_track))
        )
        if int(note.onset_frames) <= previous_truth and int(record.start) > previous_record:
            order_violations += 1
        previous_truth = int(note.onset_frames)
        previous_record = int(record.start)
    sounding = sum(1 for note in truth if not note.silence)
    truth_on_grid = sum(
        1 for note in truth if not note.silence and note.onset_frames % frames_per_tick == 0
    )
    detector_on_grid = sum(1 for record in records if int(record.start) % frames_per_tick == 0)
    return {
        "slug": trace.slug,
        "frames_per_tick": frames_per_tick,
        "onset_offset_median": _median(onset_offsets),
        "onset_offset_mean": _mean([float(value) for value in onset_offsets]),
        "onset_offset_max_abs": max((abs(value) for value in onset_offsets), default=0),
        "onset_offset_exact_share": _share(
            sum(1 for value in onset_offsets if value == 0), len(onset_offsets)
        ),
        "duration_offset_median": _median(duration_offsets),
        "duration_offset_max_abs": max((abs(value) for value in duration_offsets), default=0),
        "duration_offset_exact_share": _share(
            sum(1 for value in duration_offsets if value == 0), len(duration_offsets)
        ),
        "ordering_violations": order_violations,
        "ground_truth_notes": sounding,
        "ground_truth_notes_on_the_row_grid": truth_on_grid,
        "ground_truth_on_grid_share": _share(truth_on_grid, sounding),
        "detector_spans": len(records),
        "detector_onsets_on_the_row_grid": detector_on_grid,
        "detector_on_grid_share": _share(detector_on_grid, len(records)),
        "reading": (
            "the composition's onsets are whole rows, so on a compiled trace every ground-truth "
            "onset is a multiple of frames_per_tick. The detector's onsets are register-change "
            "positions and need not be, which is why the two on-grid shares are reported separately."
        ),
    }


def silence_errors(
    trace: Any,
    truth: Sequence[GroundTruthNote],
    records: Sequence[Any],
    attribution: Mapping[str, Any],
) -> Dict[str, Any]:
    """Section 14's silent and non-musical register activity.

    Four kinds of register activity that are not a note are separated, because lumping them together
    is how a convention difference gets mistaken for a performance effect:

    * **outside the note grid** - the frames the frame attribution calls ``OUTSIDE_BOTH``. Their only
      possible cause is the hold-versus-zero convention, and they are counted here as that.
    * **silent register change** - frames where the level is zero but AUDF changes. POKEY is not
      sounding, so no listener can hear it; it is player state, not music.
    * **initialisation** - frames before the first sounding frame of the trace.
    * **state carry-over** - the frames outside every note, which is the convention's footprint.
    """
    registers = trace.registers
    silent_changes = 0
    for voice in stage15.voices_for(int(trace.audctl)):
        audc = registers[f"AUDC{voice.volume_channel}"]
        columns = [registers[f"AUDF{channel}"] for channel in voice.pitch_channels]
        for frame in range(1, trace.frames):
            if stage15.audc_volume(audc[frame]) != 0:
                continue
            for column in columns:
                if column[frame] != column[frame - 1]:
                    silent_changes += 1
    first_sounding = trace.frames
    for voice in stage15.voices_for(int(trace.audctl)):
        audc = registers[f"AUDC{voice.volume_channel}"]
        for frame in range(trace.frames):
            if stage15.audc_volume(audc[frame]) > 0:
                first_sounding = min(first_sounding, frame)
                break
    covered = [False] * trace.frames
    for note in truth:
        if note.silence:
            continue
        for frame in range(
            note.onset_frames, min(note.onset_frames + len(note.volume_track), trace.frames)
        ):
            covered[frame] = True
    carry_over = sum(1 for frame in range(trace.frames) if not covered[frame])
    return {
        "slug": trace.slug,
        "frames": trace.frames,
        "outside_both_frames": attribution["counts"][ATTR_OUTSIDE_BOTH],
        "outside_both_share": attribution["shares"][ATTR_OUTSIDE_BOTH],
        "silent_register_changes": silent_changes,
        "initialisation_frames": first_sounding,
        "frames_outside_every_note": carry_over,
        "frames_outside_every_note_share": _share(carry_over, trace.frames),
        "reading": (
            "outside_both_frames is the convention's footprint and is not a detector error; "
            "silent_register_changes is player state a listener cannot hear; initialisation_frames "
            "and frames_outside_every_note are the rest, reported so nothing is left unnamed."
        ),
    }


# ===========================================================================
# PART 6 - corpus aggregation (sections 7, 13, 14 and 15 of the brief)
# ===========================================================================
def _distribution(values: Sequence[float]) -> Dict[str, Any]:
    """Mean, median, quartiles and extremes, so a spread is reported and not averaged away."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": _mean(ordered),
        "median": _median(ordered),
        "min": ordered[0],
        "p25": _quantile(ordered, 0.25),
        "p75": _quantile(ordered, 0.75),
        "max": ordered[-1],
    }


def _outliers(
    rows: Sequence[Mapping[str, Any]], key: str, value: Any
) -> List[Dict[str, Any]]:
    """Rows beyond 1.5 interquartile ranges above the third quartile, in a stable order."""
    values = [float(value(row)) for row in rows]
    if len(values) < 4:
        return []
    ordered = sorted(values)
    low = _quantile(ordered, 0.25) or 0.0
    high = _quantile(ordered, 0.75) or 0.0
    ceiling = high + 1.5 * (high - low)
    return [
        {"slug": row["slug"], key: value(row)}
        for row in sorted(rows, key=lambda item: item["slug"])
        if float(value(row)) > ceiling
    ]


def _pooled_ladder(rows: Sequence[Mapping[str, Any]], key: str, register_values: int) -> Dict[str, Any]:
    """Pool one ladder across the corpus by summing counts, never by averaging shares."""
    names = [rung["rung"] for rung in rows[0][key]["rungs"]]
    out: Dict[str, Any] = {}
    for name in names:
        value = sum(
            rung["residual_values"]
            for row in rows
            for rung in row[key]["rungs"] if rung["rung"] == name
        )
        out[name] = {
            "residual_values": value,
            "residual_share": _share(value, register_values),
        }
    return out


def _pooled_arms(
    rows: Sequence[Mapping[str, Any]], register_values: int, key: str = "arms"
) -> Dict[str, Any]:
    """Pool the named arms across the corpus, for one outside-note policy."""
    out: Dict[str, Any] = {}
    for name in rows[0][key]["arms"]:
        value = sum(row[key]["arms"][name]["residual_values"] for row in rows)
        out[name] = {
            "residual_values": value,
            "residual_share": _share(value, register_values),
            "description": rows[0][key]["arms"][name]["description"],
        }
    return out


def _pooled_extras(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The per-analysis pooled counts, gathered in one place so the aggregation stays readable."""
    note_detection = {
        key: sum(row["note_detection"][key] for row in rows)
        for key in (
            "ground_truth_notes", "detected_spans", "matched_notes", "matched_spans",
            "missed_ground_truth_notes", "false_detector_spans", "merged_spans", "split_notes",
            "ground_truth_frames", "detected_frames",
            "pitch_at_matched_onset_compared", "pitch_at_matched_onset_exact",
            "notes_with_uncovered_frames", "uncovered_note_frames", "exact_boundary_spans",
        )
    }
    pitch = {
        "matched_compared": sum(row["pitch"]["matched_compared"] for row in rows),
        "divider_exact": sum(row["pitch"]["divider_exact"] for row in rows),
        "coupled_16bit_notes": sum(row["pitch"]["coupled_16bit_notes"] for row in rows),
        "octave_or_register_errors": sum(
            row["pitch"]["octave_or_register_errors"] for row in rows
        ),
    }
    generator = {
        key: sum(row["generator"][key] for row in rows)
        for key in ("onset_distortion_correct", "onset_distortion_compared")
    }
    generator.update({
        key: sum(row["generator"]["transition_detection"][key] for row in rows)
        for key in ("truth_change_frames", "predicted_change_frames", "hits", "missed", "spurious")
    })
    return {
        "note_detection": note_detection,
        "pitch": pitch,
        "generator": generator,
        "channel": {
            "matched_voice_mismatches": sum(
                row["channel"]["matched_voice_mismatches"] for row in rows
            ),
            "matched_compared": sum(row["channel"]["matched_compared"] for row in rows),
            "ambiguous_frame_pairs": sum(
                row["channel"]["ambiguous_frame_pairs"] for row in rows
            ),
            "songs_ambiguous": sum(1 for row in rows if row["channel"]["flag"] == "AMBIGUOUS"),
        },
        "timing": {
            key: sum(row["timing"][key] for row in rows)
            for key in (
                "ordering_violations", "ground_truth_notes", "ground_truth_notes_on_the_row_grid",
                "detector_spans", "detector_onsets_on_the_row_grid",
            )
        },
        "silence": {
            key: sum(row["silence"][key] for row in rows)
            for key in (
                "outside_both_frames", "silent_register_changes", "initialisation_frames",
                "frames_outside_every_note",
            )
        },
    }


def aggregate_corpus(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Pool the per-song rows into corpus totals, spreads, outliers and correlations.

    Pooling is by summed counts and the share is formed once, never by averaging shares, so a short
    song cannot weigh as much as a long one. The per-song spreads are reported beside the pooled
    totals because a mean can hide a corpus that is one easy song and fifty hard ones.
    """
    register_values = sum(row["residual"]["register_values"] for row in rows)
    detector_values = sum(row["residual"]["residual_values"] for row in rows)
    attribution = {
        name: sum(row["attribution"]["counts"][name] for row in rows)
        for name in ATTRIBUTION_BUCKETS
    }
    total_values = sum(row["attribution"]["total_register_values"] for row in rows)
    extras = _pooled_extras(rows)
    note_detection = extras["note_detection"]
    false_positive_frames = sum(
        row["note_detection"]["by_frames"]["false_positive"] for row in rows
    )
    true_positive_frames = sum(
        row["note_detection"]["by_frames"]["true_positive"] for row in rows
    )
    residual_shares = [row["residual"]["residual_share"] or 0.0 for row in rows]
    correlations: Dict[str, Any] = {}
    for name in sorted(rows[0]["features"]):
        xs = [float(row["features"][name]) for row in rows]
        if len(rows) < 3:
            correlations[name] = {
                "pearson": None, "spearman": None,
                "reason": "fewer than three songs, so a correlation is not defined",
            }
            continue
        if len(set(xs)) < 2:
            correlations[name] = {
                "pearson": None, "spearman": None,
                "reason": "the feature is constant across the corpus",
            }
            continue
        correlations[name] = {
            "pearson": _pearson(xs, residual_shares),
            "spearman": _spearman(xs, residual_shares),
        }
    return {
        "songs": len(rows),
        "register_values": register_values,
        "detector_residual_values": detector_values,
        "detector_residual_share": _share(detector_values, register_values),
        "register_groups_hold": {
            group: {
                "residual_values": sum(
                    row["residual"]["groups"][group]["residual_values"] for row in rows
                ),
                "share_of_residual": None,
            }
            for group, _names in REGISTER_GROUPS
        },
        "register_groups_exporter": {
            group: {
                "residual_values": sum(
                    row["residual_exporter"]["groups"][group]["residual_values"] for row in rows
                ),
            }
            for group, _names in REGISTER_GROUPS
        },
        "ladder": {
            policy: _pooled_ladder(rows, key, register_values)
            for policy, key in ((OUTSIDE_HOLD, "ladder_hold"),
                                (OUTSIDE_EXPORTER, "ladder_exporter"))
        },
        "arms": _pooled_arms(rows, register_values, "arms"),
        "arms_hold": _pooled_arms(rows, register_values, "arms_hold"),
        "leave_one_out_marginals": {
            field: sum(
                row["leave_one_out"]["fields"][field]["marginal_values"] for row in rows
            )
            for field in FIELD_ORDER
        },
        "note_set_marginal": sum(
            row["leave_one_out"]["note_set_arm"]["marginal_values"] for row in rows
        ),
        "attribution": {
            "counts": attribution,
            "shares": {name: _share(value, total_values) for name, value in attribution.items()},
            "total_register_values": total_values,
        },
        "note_detection": note_detection,
        "note_detection_metrics": {
            "by_count": _precision_recall(
                note_detection["matched_spans"], note_detection["false_detector_spans"],
                note_detection["missed_ground_truth_notes"],
            ),
            "by_frames": _precision_recall(
                true_positive_frames, false_positive_frames,
                note_detection["ground_truth_frames"] - true_positive_frames,
            ),
        },
        "pitch": extras["pitch"],
        "pitch_divider_exact_share": _share(
            extras["pitch"]["divider_exact"], extras["pitch"]["matched_compared"]
        ),
        "generator": extras["generator"],
        "generator_onset_correct_share": _share(
            extras["generator"]["onset_distortion_correct"],
            extras["generator"]["onset_distortion_compared"],
        ),
        "generator_transition_metrics": _precision_recall(
            extras["generator"]["hits"], extras["generator"]["spurious"],
            extras["generator"]["missed"],
        ),
        "channel": extras["channel"],
        "timing": extras["timing"],
        "silence": extras["silence"],
        "per_song": {
            "residual_share": _distribution(residual_shares),
            "residual_values": _distribution(
                [float(row["residual"]["residual_values"]) for row in rows]
            ),
            "missed_notes": _distribution(
                [float(row["note_detection"]["missed_ground_truth_notes"]) for row in rows]
            ),
            "merged_spans": _distribution(
                [float(row["note_detection"]["merged_spans"]) for row in rows]
            ),
            "note_recall_by_count": _distribution(
                [float(row["note_detection"]["by_count"]["recall"] or 0.0) for row in rows]
            ),
            "divider_exact_share": _distribution(
                [float(row["pitch"]["divider_exact_share"] or 0.0) for row in rows]
            ),
        },
        "outliers": {
            "residual_share": _outliers(
                rows, "residual_share", lambda row: row["residual"]["residual_share"] or 0.0
            ),
            "missed_notes": _outliers(
                rows, "missed_notes",
                lambda row: row["note_detection"]["missed_ground_truth_notes"],
            ),
            "merged_spans": _outliers(
                rows, "merged_spans", lambda row: row["note_detection"]["merged_spans"]
            ),
        },
        "correlations": correlations,
        "correlation_note": (
            "Pearson and Spearman between each song feature and the song's residual share. "
            "Correlation is not causation and is reported as a diagnostic only."
        ),
    }


# ===========================================================================
# PART 7 - the error taxonomy and the falsification test (sections 3, 7 and 17)
# ===========================================================================
#: How a taxonomy class was disposed of. ``MEASURED`` means a number was produced; the other two mean
#: the class cannot exist in this pipeline, and the reason is reported rather than the class dropped.
CLASS_MEASURED = "MEASURED"
CLASS_EMPTY_BY_CONSTRUCTION = "EMPTY_BY_CONSTRUCTION"


def _class_affects_song(family: str, name: str, row: Mapping[str, Any]) -> bool:
    """Whether one song contributes to one taxonomy class, for the affected-songs column."""
    if family == "NOTE_LEVEL":
        if name == "missed_note_onset":
            return row["note_detection"]["uncovered_note_frames"] > 0
        if name == "note_without_full_coverage":
            return row["note_detection"]["notes_with_uncovered_frames"] > 0
        if name == "false_note_onset":
            return row["note_detection"]["false_detector_spans"] > 0
        if name == "merged_notes":
            return row["note_detection"]["merged_spans"] > 0
        if name == "split_note":
            return row["note_detection"]["split_notes"] > 0
        if name == "overlapping_notes":
            return row["features"]["polyphonic_frames"] > 0
        if name == "wrong_note_duration":
            return (row["note_detection"]["duration_exact_share"] or 0.0) < 1.0
        return (row["note_detection"]["onset_exact_share"] or 0.0) < 1.0
    if family == "PITCH":
        if name == "exact_pitch":
            return row["pitch"]["divider_exact"] > 0
        if name == "octave_or_register_error":
            return row["pitch"]["octave_or_register_errors"] > 0
        if name == "sixteen_bit_pitch":
            return row["pitch"]["coupled_16bit_notes"] > 0
        return row["pitch"]["divider_exact"] < row["pitch"]["matched_compared"]
    if family == "VOLUME_ENVELOPE":
        if name == "volume_scalar_mismatch":
            return False
        return row["leave_one_out"]["fields"][FIELD_ENVELOPE]["marginal_values"] > 0
    if family == "GENERATOR_DISTORTION":
        if name == "generator_classification_correct":
            return row["generator"]["onset_distortion_correct"] > 0
        if name == "generator_classification_wrong":
            return (row["generator"]["onset_distortion_compared"]
                    - row["generator"]["onset_distortion_correct"]) > 0
        if name == "generator_transition_missed":
            return row["generator"]["transition_detection"]["missed"] > 0
        return row["generator"]["transition_detection"]["spurious"] > 0
    if family == "CHANNEL":
        if name == "wrong_channel":
            return False
        return row["channel"]["ambiguous_frame_pairs"] > 0
    if family == "TIMING":
        if name == "event_ordering_violation":
            return row["timing"]["ordering_violations"] > 0
        return (row["timing"]["detector_spans"]
                - row["timing"]["detector_onsets_on_the_row_grid"]) > 0
    if family == "SILENCE":
        if name == "silent_register_change":
            return row["silence"]["silent_register_changes"] > 0
        if name == "initialisation":
            return row["silence"]["initialisation_frames"] > 0
        if name == "state_carry_over":
            return row["silence"]["frames_outside_every_note"] > 0
        return row["attribution"]["counts"][ATTR_OUTSIDE_BOTH] > 0
    if family == "AUDCTL":
        return False
    return False



def residual_taxonomy(
    aggregate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Section 7's matrix: every taxonomy class, its measured count, and its disposal.

    The brief forbids summing the classes blindly, because one register frame can have more than one
    apparent cause. Two separate readings are produced and kept apart:

    * **the matrix** - one row per class, each with the count the analysis actually measured. A class
      whose count is zero is marked ``EMPTY_BY_CONSTRUCTION`` when it *cannot* be non-zero here, and
      the reason is carried in the row.
    * **the cause partition** - the detector's residual split into note-set, value and interaction by
      the three matched arms. This is the reading that sums to the residual with nothing left over,
      and it is the one a claim may rest on.

    Nothing is attributed to the first cause that matches.
    """
    hold_total = aggregate["detector_residual_values"]
    exporter_total = aggregate["arms"]["A_detector"]["residual_values"]
    arms = aggregate["arms"]
    note_set_only = arms["A_detector_spans_truth_values"]["residual_values"]
    value_only = arms["A_truth_spans_detector_values"]["residual_values"]
    interaction = exporter_total - note_set_only - value_only
    convention = hold_total - exporter_total
    note_detection = aggregate["note_detection"]
    pitch = aggregate["pitch"]
    generator = aggregate["generator"]
    channel = aggregate["channel"]
    timing = aggregate["timing"]
    silence = aggregate["silence"]
    marginals = aggregate["leave_one_out_marginals"]
    register_values = aggregate["register_values"]

    def row(family: str, name: str, count: Any, status: str, note: str = "") -> Dict[str, Any]:
        return {"family": family, "class": name, "count": count, "status": status, "note": note}

    def exact_share(field: str) -> int:
        return sum(
            round((row_["note_detection"][field] or 0.0)
                  * row_["note_detection"]["matched_notes"])
            for row_ in rows
        )

    matrix: List[Dict[str, Any]] = [
        row("NOTE_LEVEL", "missed_note_onset", note_detection["uncovered_note_frames"],
            CLASS_MEASURED,
            "frames of a ground-truth note that no detected span covers - measured at the frame "
            "level because a merged span still overlaps every note it absorbed"),
        row("NOTE_LEVEL", "note_without_full_coverage",
            note_detection["notes_with_uncovered_frames"], CLASS_MEASURED,
            "ground-truth notes at least one of whose frames no span covers"),
        row("NOTE_LEVEL", "false_note_onset", note_detection["false_detector_spans"],
            CLASS_MEASURED, "detected spans no ground-truth note overlaps"),
        row("NOTE_LEVEL", "merged_notes", note_detection["merged_spans"], CLASS_MEASURED,
            "detected spans matched by two or more ground-truth notes"),
        row("NOTE_LEVEL", "split_note", note_detection["split_notes"], CLASS_MEASURED,
            "ground-truth notes matched by two or more detected spans"),
        row("NOTE_LEVEL", "wrong_note_boundary",
            note_detection["matched_spans"] - exact_share("onset_exact_share"),
            CLASS_MEASURED, "matched spans whose onset differs from the note's"),
        row("NOTE_LEVEL", "wrong_note_duration",
            note_detection["matched_spans"] - exact_share("duration_exact_share"),
            CLASS_MEASURED, "matched spans whose length differs from the note's"),
        row("NOTE_LEVEL", "overlapping_notes",
            sum(row_["features"]["polyphonic_frames"] for row_ in rows), CLASS_MEASURED,
            "frames two or more ground-truth notes cover"),
        row("PITCH", "exact_pitch", pitch["divider_exact"], CLASS_MEASURED,
            "matched onsets where the divider the detector reads is the note's own"),
        row("PITCH", "wrong_pitch", pitch["matched_compared"] - pitch["divider_exact"],
            CLASS_MEASURED, "matched onsets where it is not"),
        row("PITCH", "octave_or_register_error", pitch["octave_or_register_errors"],
            CLASS_MEASURED, "wrong-pitch cases an octave or more away"),
        row("PITCH", "sixteen_bit_pitch", pitch["coupled_16bit_notes"], CLASS_MEASURED,
            "matched notes whose divider is a joined 16-bit pair"),
        row("VOLUME_ENVELOPE", "envelope_reduction", marginals[FIELD_ENVELOPE], CLASS_MEASURED,
            "residual values the four-parameter contour cannot express"),
        row("VOLUME_ENVELOPE", "volume_scalar_mismatch", marginals[FIELD_VOLUME],
            CLASS_EMPTY_BY_CONSTRUCTION, FIELD_NOOP_REASONS[FIELD_VOLUME]),
        row("GENERATOR_DISTORTION", "generator_classification_correct",
            generator["onset_distortion_correct"], CLASS_MEASURED,
            "matched onsets whose distortion nibble the detector reads correctly"),
        row("GENERATOR_DISTORTION", "generator_classification_wrong",
            generator["onset_distortion_compared"] - generator["onset_distortion_correct"],
            CLASS_MEASURED, "matched onsets whose distortion nibble it reads wrongly"),
        row("GENERATOR_DISTORTION", "generator_transition_missed", generator["missed"],
            CLASS_MEASURED, "frames where the distortion changes that no span onset marks"),
        row("GENERATOR_DISTORTION", "generator_transition_false", generator["spurious"],
            CLASS_MEASURED, "span onsets where the distortion does not change"),
        row("CHANNEL", "wrong_channel", channel["matched_voice_mismatches"],
            CLASS_EMPTY_BY_CONSTRUCTION, FIELD_NOOP_REASONS[FIELD_CHANNEL]),
        row("CHANNEL", "channel_ambiguity", channel["ambiguous_frame_pairs"], CLASS_MEASURED,
            "frames where two voices are register-identical and audibly indistinguishable"),
        row("TIMING", "event_ordering_violation", timing["ordering_violations"], CLASS_MEASURED,
            "matched pairs whose order reverses"),
        row("TIMING", "frame_quantisation_mismatch",
            timing["detector_spans"] - timing["detector_onsets_on_the_row_grid"], CLASS_MEASURED,
            "detected onsets that do not sit on the composition's row grid"),
        row("SILENCE", "silent_register_change", silence["silent_register_changes"],
            CLASS_MEASURED, "AUDF changes while the level is zero"),
        row("SILENCE", "initialisation", silence["initialisation_frames"], CLASS_MEASURED,
            "frames before the trace first sounds"),
        row("SILENCE", "state_carry_over", silence["frames_outside_every_note"], CLASS_MEASURED,
            "frames no note covers"),
        row("SILENCE", "outside_note_convention",
            aggregate["attribution"]["counts"][ATTR_OUTSIDE_BOTH], CLASS_MEASURED,
            "residual values only the hold-versus-zero convention can explain"),
        row("AUDCTL", "audctl_mismatch", marginals[FIELD_AUDCTL],
            CLASS_EMPTY_BY_CONSTRUCTION, FIELD_NOOP_REASONS[FIELD_AUDCTL]),
    ]
    return _taxonomy_tail(
        matrix, aggregate, rows, register_values, hold_total, exporter_total, note_set_only,
        value_only, interaction, convention,
    )


def _taxonomy_tail(
    matrix: List[Dict[str, Any]],
    aggregate: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    register_values: int,
    hold_total: int,
    exporter_total: int,
    note_set_only: int,
    value_only: int,
    interaction: int,
    convention: int,
) -> Dict[str, Any]:
    """Fill in the per-class shares and affected-song counts, then assemble the taxonomy record."""
    for item in matrix:
        item["share_of_trace"] = _share(int(item["count"] or 0), register_values)
        item["songs_affected"] = sum(
            1 for row_ in rows if _class_affects_song(item["family"], item["class"], row_)
        )
    return {
        "matrix": matrix,
        "families": sorted({item["family"] for item in matrix}),
        "cause_partition": {
            "detector_residual_values_hold": hold_total,
            "detector_residual_values_exporter": exporter_total,
            "convention": convention,
            "note_set_only": note_set_only,
            "value_only": value_only,
            "interaction": interaction,
            "note_set_share": _share(note_set_only, exporter_total),
            "value_share": _share(value_only, exporter_total),
            "interaction_share": _share(interaction, exporter_total),
            "convention_share_of_hold": _share(convention, hold_total),
            "closes": (
                note_set_only + value_only + interaction == exporter_total
                and convention + exporter_total == hold_total
            ),
            "rule": (
                "the partition is taken on the residual *under the exporter convention*, because "
                "the arms and the ladder are; mixing the hold total with exporter-policy arms would "
                "put the convention difference into the interaction term and inflate it. The "
                "convention is then reported as its own component, so the hold total is accounted "
                "for as well: hold = convention + note set + value reading + interaction."
            ),
        },
        "reading": (
            "the matrix counts what was measured; the cause partition is what sums to the residual. "
            "A class marked EMPTY_BY_CONSTRUCTION cannot be non-zero in this pipeline and says why."
        ),
    }


# ===========================================================================
# PART 8 - the historical corpus (sections 16 and 17 of the brief)
# ===========================================================================
def historical_signature(trace: Any) -> Dict[str, Any]:
    """What can be measured about a historical song *without* a ground truth.

    The frame attribution needs a composition to attribute against, so it is unavailable here and
    saying otherwise would be the exact mistake this stage exists to prevent. What survives is the
    residual's *shape*, which is trace-derived and therefore comparable across corpora:

    * the residual under both outside-note conventions, per register group;
    * the AUDF-to-AUDC split of the residual, which is the signature of a segmentation error;
    * the distortion-transition metrics, whose truth is the trace's own register changes;
    * the silent and non-musical register activity.

    Every field here is computable from the trace alone, so the comparison with the control corpus is
    a comparison of like with like.
    """
    records = stage20.note_records(trace)
    predicted = stage20.predict_frames(trace, records, 0, True)
    report = register_residual(residual_of(trace, predicted))
    hold = report["residual_values"]
    specs = specs_from_records(records, int(trace.audctl))
    exporter_residual = residual_of(
        trace, predict_from_specs(trace.frames, int(trace.audctl), specs, OUTSIDE_EXPORTER)
    )
    true_frames: List[int] = []
    predicted_frames: List[int] = []
    for voice in stage15.voices_for(int(trace.audctl)):
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        nibbles = [stage15.audc_distortion(audc[frame]) for frame in range(trace.frames)]
        true_frames.extend(_change_frames(nibbles))
        predicted_frames.extend(
            sorted(int(record.start) for record in records if record.voice_id == voice.voice_id)
        )
    true_set = set(true_frames)
    predicted_set = set(predicted_frames)
    covered = [False] * trace.frames
    for record in records:
        for frame in range(int(record.start), min(int(record.end) + 1, trace.frames)):
            covered[frame] = True
    silent_changes = 0
    for voice in stage15.voices_for(int(trace.audctl)):
        audc = trace.registers[f"AUDC{voice.volume_channel}"]
        columns = [trace.registers[f"AUDF{channel}"] for channel in voice.pitch_channels]
        for frame in range(1, trace.frames):
            if stage15.audc_volume(audc[frame]) != 0:
                continue
            for column in columns:
                if column[frame] != column[frame - 1]:
                    silent_changes += 1
    outside = sum(1 for value in covered if not value)
    exporter = exporter_residual.residual_values()
    exporter_report = register_residual(exporter_residual)
    exporter_audf = exporter_report["groups"]["AUDF"]["residual_values"]
    exporter_audc = exporter_report["groups"]["AUDC"]["residual_values"]
    return {
        "slug": trace.slug,
        "frames": trace.frames,
        "register_values": report["register_values"],
        "audctl": f"${int(trace.audctl):02X}",
        "audctl_constant": len(set(trace.registers["AUDCTL"])) == 1,
        "spans": len(records),
        "residual_hold_values": hold,
        "residual_hold_share": _share(hold, report["register_values"]),
        "residual_exporter_values": exporter,
        "residual_exporter_share": _share(exporter, report["register_values"]),
        "audf_values": report["groups"]["AUDF"]["residual_values"],
        "audc_values": report["groups"]["AUDC"]["residual_values"],
        "audctl_values": report["groups"]["AUDCTL"]["residual_values"],
        "audf_share_of_residual": _share(
            report["groups"]["AUDF"]["residual_values"], hold
        ),
        "audc_share_of_residual": _share(
            report["groups"]["AUDC"]["residual_values"], hold
        ),
        "audf_share_of_exporter_residual": _share(exporter_audf, exporter_audf + exporter_audc),
        "generator_transition": {
            "truth_change_frames": len(true_set),
            "predicted_change_frames": len(predicted_set),
            "hits": len(true_set & predicted_set),
            "missed": len(true_set - predicted_set),
            "spurious": len(predicted_set - true_set),
            "metrics": _precision_recall(
                len(true_set & predicted_set), len(predicted_set - true_set),
                len(true_set - predicted_set),
            ),
        },
        "silent_register_changes": silent_changes,
        "frames_outside_every_span": outside,
        "frames_outside_every_span_share": _share(outside, trace.frames),
        "note": (
            "no ground truth exists for this song, so the note-set and value arms cannot be run and "
            "the frame attribution is unavailable. Only the residual's shape is measurable here."
        ),
    }



def historical_comparison(
    control: Mapping[str, Any], historical: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Section 16's comparison, on the quantities both corpora can produce.

    The question the brief asks is whether the *classes of error* seen in the historical corpus match
    the classes seen on the known-truth corpus. Since the historical corpus cannot produce the
    note-set and value arms, the comparison is made on the shape of the residual: how much of it is
    AUDF, how much is AUDC, what share survives when the convention is removed, and how well the
    distortion transitions are tracked. A different shape would be evidence of a different cause; a
    matching shape is *consistent with* the same causes, which is weaker than proof and is reported as
    such.
    """
    historical_values = sum(row["register_values"] for row in historical)
    historical_hold = sum(row["residual_hold_values"] for row in historical)
    historical_exporter = sum(row["residual_exporter_values"] for row in historical)
    historical_audf = sum(row["audf_values"] for row in historical)
    historical_audc = sum(row["audc_values"] for row in historical)
    historical_hits = sum(row["generator_transition"]["hits"] for row in historical)
    historical_true = sum(row["generator_transition"]["truth_change_frames"] for row in historical)
    historical_predicted = sum(
        row["generator_transition"]["predicted_change_frames"] for row in historical
    )
    historical_exporter_audf = [
        row["audf_share_of_exporter_residual"] for row in historical
        if row["audf_share_of_exporter_residual"] is not None
    ]
    historical_exporter_audf_share = (
        sum(
            row["residual_exporter_values"]
            * (row["audf_share_of_exporter_residual"] or 0.0)
            for row in historical
        )
        / historical_exporter if historical_exporter else None
    )
    control_exporter = control["arms"]["A_detector"]["residual_values"]
    ratio = None if not control_exporter else round(
        historical_exporter / control_exporter, 6
    )
    share_ratio = None if not control["detector_residual_share"] else round(
        (_share(historical_exporter, historical_values) or 0.0)
        / control["detector_residual_share"], 6
    )
    return {
        "control": {
            "songs": control["songs"],
            "register_values": control["register_values"],
            "residual_hold_values": control["detector_residual_values"],
            "residual_hold_share": control["detector_residual_share"],
            "residual_exporter_values": control_exporter,
            "residual_exporter_share": _share(control_exporter, control["register_values"]),
            "audf_share_of_exporter_residual": _share(
                control["register_groups_exporter"]["AUDF"]["residual_values"],
                control["register_groups_exporter"]["AUDF"]["residual_values"]
                + control["register_groups_exporter"]["AUDC"]["residual_values"],
            ),
        },
        "historical": {
            "songs": len(historical),
            "register_values": historical_values,
            "residual_hold_values": historical_hold,
            "residual_hold_share": _share(historical_hold, historical_values),
            "residual_exporter_values": historical_exporter,
            "residual_exporter_share": _share(historical_exporter, historical_values),
            "audf_values": historical_audf,
            "audc_values": historical_audc,
            "audf_share_of_residual": _share(historical_audf, historical_hold),
            "audc_share_of_residual": _share(historical_audc, historical_hold),
            "audf_share_of_exporter_residual": (
                None if historical_exporter_audf_share is None
                else round(historical_exporter_audf_share, 6)
            ),
            "generator_transition_metrics": _precision_recall(
                historical_hits,
                historical_predicted - historical_hits,
                historical_true - historical_hits,
            ),
        },
        "residual_exporter_ratio_historical_over_control": ratio,
        "residual_share_ratio_historical_over_control": share_ratio,
        "comparable_quantities": (
            "the residual under the exporter convention, its AUDF-to-AUDC split, and the "
            "distortion-transition precision and recall. The note-set and value arms and the frame "
            "attribution are control-only and are deliberately not compared."
        ),
        "per_song": sorted(historical, key=lambda row: row["slug"]),
    }





# ===========================================================================
# PART 9 - the falsification test and the verdicts (sections 17 and 24)
# ===========================================================================
#: Stated thresholds, so a verdict cannot be talked into a nicer answer afterwards.
CONSISTENT_SHARE_RATIO_LOW = 0.5
CONSISTENT_SHARE_RATIO_HIGH = 2.0
CONSISTENT_AUDF_SHARE_DELTA = 0.20


def falsification_test(
    control: Mapping[str, Any],
    comparison: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
) -> Dict[str, Any]:
    """Section 17's test: does the historical residual still show something the control does not?

    The control corpus's residual is *fully* accounted for - the exact composition leaves nothing, and
    the detector's residual partitions into the note set, the value reads, their interaction and the
    outside-note convention. So the control corpus is the reference for what a pure detector error
    looks like.

    The historical corpus cannot be partitioned the same way, because it has no ground truth. What can
    be asked is whether its residual has the *same shape*: the same share of the stream, and the same
    AUDF-to-AUDC split. If it does, the parsimonious reading is that the same causes are at work and
    the performance-layer hypothesis remains unsupported. If it does not, that is a real difference
    worth a new controlled experiment - but a difference in shape is not proof of performance, and the
    verdict says so.
    """
    control_share = control["detector_residual_share"] or 0.0
    historical_share = comparison["historical"]["residual_hold_share"] or 0.0
    share_ratio = None if not control_share else round(historical_share / control_share, 6)
    # The AUDF share depends on the convention, so the comparison is made under *both* pairings:
    # exporter-vs-exporter (the policy that matches the control corpus's compiler) and
    # hold-vs-hold (the policy that matches the historical corpus's player). A verdict that held
    # under one pairing and not the other would be an artefact of the policy choice, so the test
    # requires both to agree before it calls the residuals consistent.
    control_exporter_audf = control["register_groups_exporter"]["AUDF"]["residual_values"]
    control_exporter_audc = control["register_groups_exporter"]["AUDC"]["residual_values"]
    control_audf_exporter = _share(control_exporter_audf, control_exporter_audf + control_exporter_audc)
    control_hold_audf = control["register_groups_hold"]["AUDF"]["residual_values"]
    control_audf_hold = _share(control_hold_audf, control["detector_residual_values"])
    historical_audf_hold = comparison["historical"]["audf_share_of_residual"]
    historical_audf_exporter = comparison["historical"]["audf_share_of_exporter_residual"]
    pairings = {
        "exporter_vs_exporter": {
            "control": control_audf_exporter,
            "historical": historical_audf_exporter,
            "delta": (
                None if historical_audf_exporter is None or control_audf_exporter is None
                else round(historical_audf_exporter - control_audf_exporter, 6)
            ),
        },
        "hold_vs_hold": {
            "control": control_audf_hold,
            "historical": historical_audf_hold,
            "delta": (
                None if historical_audf_hold is None or control_audf_hold is None
                else round(historical_audf_hold - control_audf_hold, 6)
            ),
        },
    }
    for row in pairings.values():
        row["consistent"] = (
            row["delta"] is not None and abs(row["delta"]) <= CONSISTENT_AUDF_SHARE_DELTA
        )
    control_audf = control_audf_exporter
    control_audf_share = control_audf_exporter
    historical_audf = historical_audf_hold
    audf_delta = pairings["exporter_vs_exporter"]["delta"]
    share_consistent = (
        share_ratio is not None
        and CONSISTENT_SHARE_RATIO_LOW <= share_ratio <= CONSISTENT_SHARE_RATIO_HIGH
    )
    split_consistent = all(row["consistent"] for row in pairings.values())
    if share_consistent and split_consistent:
        verdict = "HISTORICAL_RESIDUAL_CONSISTENT_WITH_DETECTOR_ERROR"
        consequence = "PERFORMANCE_CANDIDATE_REMAINS_UNSUPPORTED"
    else:
        verdict = "HISTORICAL_RESIDUAL_DIFFERENT_FROM_CONTROL"
        consequence = "PERFORMANCE_CANDIDATE_REQUIRES_NEW_CONTROLLED_TEST"
    return {
        "question": (
            "After the known detector errors are accounted for, does the historical residual still "
            "contain a systematic component that the known-truth corpus does not show?"
        ),
        "control_residual_share": control_share,
        "historical_residual_share": historical_share,
        "share_ratio_historical_over_control": share_ratio,
        "share_consistent": share_consistent,
        "control_audf_share_of_residual": control_audf_share,
        "control_note_set_share_of_residual": taxonomy["cause_partition"]["note_set_share"],
        "audf_pairings": pairings,
        "audf_pairings_consistent": split_consistent,
        "cross_check_note": (
            "the AUDF share is policy-sensitive, so it is measured under both pairings - "
            "exporter-vs-exporter, which matches the control corpus's compiler, and hold-vs-hold, "
            "which matches the historical corpus's player - and the split counts as consistent only "
            "if *both* are within the threshold. The control's *arm-based* note-set share is an "
            "attribution, not a register-group share, and is reported beside this for context only: "
            "comparing the two would be comparing different quantities."
        ),
        "historical_audf_share_of_residual": historical_audf,
        "audf_share_delta": audf_delta,
        "split_consistent": split_consistent,
        "thresholds": {
            "share_ratio_low": CONSISTENT_SHARE_RATIO_LOW,
            "share_ratio_high": CONSISTENT_SHARE_RATIO_HIGH,
            "audf_share_delta": CONSISTENT_AUDF_SHARE_DELTA,
        },
        "verdict": verdict,
        "consequence": consequence,
        "difference_robust": (
            (not share_consistent)
            or all(not row["consistent"] for row in pairings.values())
        ),
        "robustness_note": (
            "the difference is called *robust* only when it appears under every measurement: the "
            "residual's share of the stream is outside the ratio band, or the AUDF split is outside "
            "the delta band under *both* convention pairings. A difference that appears under one "
            "pairing and not the other is a property of the convention choice, and a convention "
            "choice is not evidence about music."
        ),
        "what_this_is_not": (
            "a difference in shape is not proof of a performance layer. It is a reason to design a "
            "new controlled experiment, and it would have to survive the same ground-truth discipline "
            "this stage applied to the detector."
        ),
    }



def hypothesis_verdicts(
    ground_truth: Mapping[str, Any],
    aggregate: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
    comparison: Mapping[str, Any],
    falsification: Mapping[str, Any],
    bridge: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """The section 24 verdicts, each with the measured conditions that produced it.

    No verdict is promoted because an earlier stage was positive, and ``PROVEN PERFORMANCE LAYER`` is
    not in the vocabulary at all: nothing here is evidence for one.
    """
    partition = taxonomy["cause_partition"]
    exporter = partition["detector_residual_values_exporter"]
    uniquely = (partition["note_set_share"] or 0.0) + (partition["value_share"] or 0.0)
    bridge_holds = bool(bridge) and all(row["agrees"] for row in bridge)
    b10_zero = aggregate["ladder"][OUTSIDE_EXPORTER]["B10"]["residual_values"] == 0
    noops_zero = all(
        aggregate["leave_one_out_marginals"][field] == 0
        for field in (FIELD_CHANNEL, FIELD_VOLUME, FIELD_AUDCTL)
    )
    if not bridge_holds or not b10_zero or not partition["closes"]:
        error_verdict = "DETECTOR_ERROR_NOT_EXPLAINED"
    elif uniquely >= 0.90:
        error_verdict = "DETECTOR_ERROR_EXPLAINED"
    elif uniquely >= 0.50:
        error_verdict = "DETECTOR_ERROR_PARTIALLY_EXPLAINED"
    else:
        error_verdict = "DETECTOR_ERROR_NOT_EXPLAINED"
    envelope_marginal = aggregate["leave_one_out_marginals"][FIELD_ENVELOPE]
    return {
        "detector_error": {
            "verdict": error_verdict,
            "conditions": {
                "predictor_bridge_holds": bridge_holds,
                "b10_is_zero": b10_zero,
                "detector_residual_values_exporter": exporter,
                "convention_share_of_hold": partition["convention_share_of_hold"],
                "note_set_share": partition["note_set_share"],
                "value_share": partition["value_share"],
                "interaction_share": partition["interaction_share"],
                "noop_fields_are_zero": noops_zero,
            },
            "deciding_condition": (
                "the partition closes and the exact composition leaves nothing at all, so the "
                "residual is fully attributed to named causes. The verdict reports how much of it is "
                "attributed to a single cause: note set plus value reading. The rest is the "
                "interaction, which is measured and named rather than assumed away."
            ),
        },
        "representation_limitation": {
            "verdict": "REPRESENTATION_LIMITATION",
            "conditions": {
                "envelope_marginal_values": envelope_marginal,
                "envelope_share_of_detector_residual": _share(envelope_marginal, exporter),
                "four_parameter_contour": (
                    "the detector describes a note's whole level track with peak, attack, sustain "
                    "and release"
                ),
            },
            "deciding_condition": (
                "the level-track reduction is the only value-level error the leave-one-out finds. It "
                "is a limitation of the representation, not of the detection: the span is right and "
                "the four numbers cannot express the track."
            ),
        },
        "ground_truth_extraction": {
            "verdict": "GROUND_TRUTH_EXTRACTION_LIMITATION",
            "conditions": {
                "songs": ground_truth["songs"],
                "notes": ground_truth["total_notes"],
                "silent_notes": ground_truth["total_silent_notes"],
                "all_audctl_constant": ground_truth["all_audctl_constant"],
            },
            "deciding_condition": (
                "the ground truth is derived, not authored: onsets and level tracks are computed from "
                "the composition by the project's own compiler. It is exact for the compiled trace by "
                "construction, and it is not a human performance. The status counts say which fields "
                "are known and which are derived."
            ),
        },
        "historical_residual": {
            "verdict": falsification["verdict"],
            "consequence": falsification["consequence"],
            "conditions": {
                "control_residual_share": falsification["control_residual_share"],
                "historical_residual_share": falsification["historical_residual_share"],
                "share_ratio": falsification["share_ratio_historical_over_control"],
                "audf_share_delta": falsification["audf_share_delta"],
                "share_consistent": falsification["share_consistent"],
                "split_consistent": falsification["split_consistent"],
            },
            "deciding_condition": (
                "the historical residual's share of the stream and its AUDF-to-AUDC split are "
                "compared with the control corpus's, because those are the only quantities both "
                "corpora can produce."
            ),
        },
        "performance_candidate": {
            "verdict": falsification["consequence"],
            "conditions": {
                "confirmed_performance_candidate_on_control": 0,
                "historical_verdict": falsification["verdict"],
                "stage_21_verdict": "PERFORMANCE_LAYER_VALIDATION_INCONCLUSIVE",
            },
            "deciding_condition": (
                "Stage 21 left the performance layer undecided and this stage does not change that. "
                "What it changes is the reason: the residual Stage 20 measured is now decomposed into "
                "named detector errors, so any future claim about performance must first account for "
                "them. Where the historical comparison finds a difference, the difference is checked "
                "for robustness across convention pairings before it is allowed to motivate anything."
            ),
        },
    }


def run_analysis(
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    control_limit: Optional[int] = None,
    detail_limit: Optional[int] = None,
    historical_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Everything Stage 22 measures, in one deterministic pass.

    The three limits exist so the test suite can exercise the whole pipeline on a bounded slice
    without changing a single decision: all three default to ``None``, which means every song and full
    detail everywhere.
    """
    before = production_hashes()
    corpus_before = corpus_hashes(songs_dir, ai_dir)
    corpus, skipped = stage21.load_control_corpus(songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR)
    if control_limit is not None:
        corpus = corpus[:control_limit]
    if not corpus:
        raise Stage22Error("the control corpus is empty; Stage 22 is defined over it")
    detail_boundary = len(corpus) if detail_limit is None else min(detail_limit, len(corpus))
    rows = [
        analyse_song(song, detail=index < detail_boundary)
        for index, song in enumerate(corpus)
    ]
    detail_rows = [row for row in rows if "ladder_exporter" in row]
    if not detail_rows:
        raise Stage22Error(
            "no song was analysed in detail; at least one is needed for the ablation ladder"
        )
    aggregate = aggregate_corpus(detail_rows)
    taxonomy = residual_taxonomy(aggregate, detail_rows)
    ground_truth = ground_truth_summary(corpus, [song.trace for song in corpus])
    bridge = [assert_matches_stage20(song.trace) for song in corpus[:5]]
    bridge += [row["bridge"] for row in detail_rows]
    if not all(row["agrees"] for row in bridge):
        raise Stage22Error("the Stage 22 predictor does not reproduce stage20.predict_frames")

    historical_traces = [
        stage15.load_trace(path) for path in stage15.list_traces(Path(arch_root))
    ]
    if historical_limit is not None and historical_limit >= len(EXPECTED_SLUGS):
        keep = [trace for trace in historical_traces if trace.slug in EXPECTED_SLUGS]
        rest = sorted(
            (trace for trace in historical_traces if trace.slug not in EXPECTED_SLUGS),
            key=lambda trace: trace.slug,
        )
        historical_traces = sorted(
            keep + rest[: max(0, historical_limit - len(keep))], key=lambda trace: trace.slug
        )
    historical = [historical_signature(trace) for trace in historical_traces]
    comparison = historical_comparison(aggregate, historical)
    falsification = falsification_test(aggregate, comparison, taxonomy)
    verdicts = hypothesis_verdicts(
        ground_truth, aggregate, taxonomy, comparison, falsification, bridge
    )
    read_only = {
        "production": read_only_audit(
            before, production_hashes(), "production modules and the player source"
        ),
        "compositions": read_only_audit(
            corpus_before, corpus_hashes(songs_dir, ai_dir), "composition documents"
        ),
    }
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "ground_truth": ground_truth,
        "songs": rows,
        "corpus": {
            "control": [song.slug for song in corpus],
            "control_detailed": [row["slug"] for row in detail_rows],
            "skipped": list(skipped),
            "historical": [row["slug"] for row in historical],
        },
        "aggregate": aggregate,
        "taxonomy": taxonomy,
        "historical": historical,
        "comparison": comparison,
        "falsification": falsification,
        "verdicts": verdicts,
        "predictor_bridge": bridge,
        "read_only_audit": read_only,
        "determinism": {
            "no_timestamps": True,
            "no_sampling": True,
            "inputs_hashed": True,
            "random_seed": RANDOM_SEED,
            "tie_breaks": (
                "matching breaks a tie on the smaller absolute onset difference, then the smaller "
                "start frame, then the smaller index; ranks for the Spearman correlation are average "
                "ranks, so ties cannot depend on order; composition documents are ordered by content "
                "hash; and every specification list is sorted by (start, voice, end) before it is "
                "used. Every one is stated in the code and covered by a test."
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open fourteen files."""
    aggregate = bundle["aggregate"]
    partition = bundle["taxonomy"]["cause_partition"]
    verdicts = bundle["verdicts"]
    return {
        "control_songs": bundle["ground_truth"]["songs"],
        "control_songs_detailed": len(bundle["corpus"]["control_detailed"]),
        "control_notes": bundle["ground_truth"]["total_notes"],
        "silent_notes": bundle["ground_truth"]["total_silent_notes"],
        "all_audctl_constant": bundle["ground_truth"]["all_audctl_constant"],
        "historical_songs": len(bundle["historical"]),
        "register_values": aggregate["register_values"],
        "detector_residual_values": aggregate["detector_residual_values"],
        "detector_residual_share": aggregate["detector_residual_share"],
        "detector_residual_share_exporter": aggregate["ladder"][OUTSIDE_EXPORTER]["B0"][
            "residual_share"
        ],
        "b10_values": aggregate["ladder"][OUTSIDE_EXPORTER]["B10"]["residual_values"],
        "b10_is_zero": aggregate["ladder"][OUTSIDE_EXPORTER]["B10"]["residual_values"] == 0,
        "cause_note_set_share": partition["note_set_share"],
        "cause_value_share": partition["value_share"],
        "cause_interaction_share": partition["interaction_share"],
        "cause_convention_share_of_hold": partition["convention_share_of_hold"],
        "cause_convention_values": partition["convention"],
        "cause_exporter_values": partition["detector_residual_values_exporter"],
        "cause_partition_closes": partition["closes"],
        "envelope_marginal_values": aggregate["leave_one_out_marginals"][FIELD_ENVELOPE],
        "noop_field_marginals": {
            field: aggregate["leave_one_out_marginals"][field]
            for field in (FIELD_CHANNEL, FIELD_VOLUME, FIELD_AUDCTL)
        },
        "attribution": aggregate["attribution"]["shares"],
        "note_recall_by_count": aggregate["note_detection_metrics"]["by_count"]["recall"],
        "note_precision_by_count": aggregate["note_detection_metrics"]["by_count"]["precision"],
        "note_recall_by_frames": aggregate["note_detection_metrics"]["by_frames"]["recall"],
        "missed_notes": aggregate["note_detection"]["missed_ground_truth_notes"],
        "false_spans": aggregate["note_detection"]["false_detector_spans"],
        "merged_spans": aggregate["note_detection"]["merged_spans"],
        "split_notes": aggregate["note_detection"]["split_notes"],
        "pitch_divider_exact_share": aggregate["pitch_divider_exact_share"],
        "generator_onset_correct_share": aggregate["generator_onset_correct_share"],
        "generator_transition_metrics": aggregate["generator_transition_metrics"],
        "channel_mismatches": aggregate["channel"]["matched_voice_mismatches"],
        "channel_ambiguous_frames": aggregate["channel"]["ambiguous_frame_pairs"],
        "timing_ordering_violations": aggregate["timing"]["ordering_violations"],
        "silent_register_changes": aggregate["silence"]["silent_register_changes"],
        "historical_residual_share": bundle["comparison"]["historical"]["residual_hold_share"],
        "residual_share_ratio": bundle["comparison"][
            "residual_share_ratio_historical_over_control"
        ],
        "falsification_verdict": bundle["falsification"]["verdict"],
        "predictor_bridge_holds": all(row["agrees"] for row in bundle["predictor_bridge"]),
        "read_only": all(row["read_only"] for row in bundle["read_only_audit"].values()),
        "read_only_files_checked": sum(
            row["files_checked"] for row in bundle["read_only_audit"].values()
        ),
        "verdicts": {
            "detector_error": verdicts["detector_error"]["verdict"],
            "representation_limitation": verdicts["representation_limitation"]["verdict"],
            "ground_truth_extraction": verdicts["ground_truth_extraction"]["verdict"],
            "historical_residual": verdicts["historical_residual"]["verdict"],
            "performance_candidate": verdicts["performance_candidate"]["verdict"],
        },
        "per_song_residual_share": aggregate["per_song"]["residual_share"],
        "outliers": aggregate["outliers"],
    }


# ===========================================================================
# PART 10 - the run, the read-only audit and the artefacts (sections 20, 21 and 22)
# ===========================================================================
#: Everything Stage 22 reads and must not write. Stage 21 is included because Stage 22 reads its
#: corpus loader and its occupancy span type.
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
    "src/atari_music/stage21.py",
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


STAGE22_FILES: Tuple[str, ...] = (
    "ground_truth_summary.json",
    "detector_summary.json",
    "ablation_ladder.json",
    "ablation_leave_one_out.json",
    "note_detection_errors.json",
    "pitch_errors.json",
    "volume_envelope_errors.json",
    "generator_errors.json",
    "distortion_errors.json",
    "channel_errors.json",
    "timing_errors.json",
    "residual_by_register.json",
    "residual_by_song.json",
    "residual_taxonomy.json",
    "historical_vs_control.json",
    "stage22_manifest.json",
)
STAGE22_DOC = "stage22_detector_error_decomposition.md"

#: Working state that never reaches disk. ``residual`` is *not* here: it is the payload of the
#: residual artefacts. Only in-memory specification objects are stripped.
_TRANSIENT_KEYS = ("specs",)


def _slim(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _TRANSIENT_KEYS}


def _ground_truth_artefact(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    return bundle["ground_truth"]


def _detector_artefact(bundle: Mapping[str, Any], aggregate: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "detector_residual_values": aggregate["detector_residual_values"],
        "register_values": aggregate["register_values"],
        "detector_residual_share": aggregate["detector_residual_share"],
        "attribution": aggregate["attribution"],
        "note_detection": aggregate["note_detection_metrics"],
        "pitch_divider_exact_share": aggregate["pitch_divider_exact_share"],
        "generator_onset_correct_share": aggregate["generator_onset_correct_share"],
        "generator_transition_metrics": aggregate["generator_transition_metrics"],
        "channel": aggregate["channel"],
        "timing": aggregate["timing"],
        "silence": aggregate["silence"],
        "predictor_bridge": bundle["predictor_bridge"],
        "how_the_detector_was_run": (
            "stage20.note_records segments the trace with stage15.note_spans, "
            "stage20.predict_frames builds the prediction with Stage 20's own pitch mapping and "
            "contour fit, and stage20.build_residual forms the residual. Nothing about the detector "
            "is re-implemented; only the variations are, and the bridge proves them."
        ),
    }


def _ladder_artefact(bundle: Mapping[str, Any], aggregate: Mapping[str, Any],
                     detailed: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ladder_definition": [
            {"rung": name, "exact_fields": sorted(exact), "note_set": note_set,
             "description": description}
            for name, exact, note_set, description in LADDER
        ],
        "arms_definition": [
            {"arm": name, "exact_fields": sorted(exact), "note_set": note_set,
             "move_spans": move_spans, "description": description}
            for name, exact, note_set, move_spans, description in ARM_SPECS
        ],
        "pooled_ladder": aggregate["ladder"],
        "pooled_arms": aggregate["arms"],
        "per_song": {
            slug: {"ladder_hold": row["ladder_hold"], "ladder_exporter": row["ladder_exporter"],
                   "arms": row["arms"]}
            for slug, row in sorted(detailed.items())
        },
        "noop_fields": FIELD_NOOP_REASONS,
    }

    out: Dict[str, Optional[str]] = {}
    for relative in PRODUCTION_FILES:
        path = Path(root) / relative
        out[relative] = sha256_file(path) if path.is_file() else None
    return out


def _artefacts(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The sixteen JSON payloads, built in one place so the writer stays a writer."""
    songs = {row["slug"]: row for row in bundle["songs"]}
    detailed = {slug: row for slug, row in songs.items() if "ladder_exporter" in row}
    slim = {slug: _slim(row) for slug, row in songs.items()}
    aggregate = bundle["aggregate"]
    envelope_marginal = aggregate["leave_one_out_marginals"][FIELD_ENVELOPE]
    return {
        "ground_truth_summary.json": _ground_truth_artefact(bundle),
        "detector_summary.json": _detector_artefact(bundle, aggregate),
        "ablation_ladder.json": _ladder_artefact(bundle, aggregate, detailed),
        "ablation_leave_one_out.json": {
            "pooled_marginals": aggregate["leave_one_out_marginals"],
            "pooled_note_set_marginal": aggregate["note_set_marginal"],
            "per_song": {slug: row["leave_one_out"] for slug, row in sorted(detailed.items())},
            "field_scope_note": (
                bundle["songs"][0].get("leave_one_out", {}).get("field_scope_note")
                if bundle["songs"] else None
            ),
        },
        "note_detection_errors.json": {
            "pooled": aggregate["note_detection_metrics"],
            "counts": aggregate["note_detection"],
            "per_song": {slug: row["note_detection"] for slug, row in sorted(detailed.items())},
        },
        "pitch_errors.json": {
            "pooled": aggregate["pitch"],
            "divider_exact_share": aggregate["pitch_divider_exact_share"],
            "per_song": {slug: row["pitch"] for slug, row in sorted(detailed.items())},
        },
        "volume_envelope_errors.json": {
            "envelope_marginal_values": envelope_marginal,
            "share_of_detector_residual": _share(
                envelope_marginal, aggregate["detector_residual_values"]
            ),
            "per_song": {
                slug: {
                    "envelope_marginal_values":
                        row["leave_one_out"]["fields"][FIELD_ENVELOPE]["marginal_values"],
                    "volume_scalar_marginal_values":
                        row["leave_one_out"]["fields"][FIELD_VOLUME]["marginal_values"],
                }
                for slug, row in sorted(detailed.items())
            },
            "reading": (
                "the detector's four-parameter contour cannot express the note's own level track. "
                "This is a representation limit, not a detection error: the span and the pitch are "
                "right and the level shape is reduced."
            ),
        },
        "generator_errors.json": {
            "pooled": aggregate["generator"],
            "onset_correct_share": aggregate["generator_onset_correct_share"],
            "transition_metrics": aggregate["generator_transition_metrics"],
            "per_song": {slug: row["generator"] for slug, row in sorted(detailed.items())},
        },
        "distortion_errors.json": {
            "onset_correct_share": aggregate["generator_onset_correct_share"],
            "transition_metrics": aggregate["generator_transition_metrics"],
            "classification_vs_transition": (
                "classification asks whether the generator read at a span's onset is the trace's "
                "generator there; transition detection asks whether the frames where the generator "
                "changes are marked. They are different questions with different answers."
            ),
            "per_song": {
                slug: row["generator"]["classification"] for slug, row in sorted(detailed.items())
            },
        },
        "channel_errors.json": {
            "pooled": aggregate["channel"],
            "noop_reason": FIELD_NOOP_REASONS[FIELD_CHANNEL],
            "per_song": {slug: row["channel"] for slug, row in sorted(detailed.items())},
        },
        "timing_errors.json": {
            "pooled": aggregate["timing"],
            "per_song": {slug: row["timing"] for slug, row in sorted(detailed.items())},
        },
        "residual_by_register.json": {
            "attribution": aggregate["attribution"],
            "per_song": {slug: row["residual"] for slug, row in sorted(slim.items())},
        },
        "residual_by_song.json": {
            "per_song": {slug: row["residual"] for slug, row in sorted(slim.items())},
            "per_song_distribution": aggregate["per_song"],
            "outliers": aggregate["outliers"],
            "correlations": aggregate["correlations"],
            "features": {slug: row["features"] for slug, row in sorted(detailed.items())},
        },
        "residual_taxonomy.json": bundle["taxonomy"],
        "historical_vs_control.json": {
            "comparison": bundle["comparison"],
            "falsification": bundle["falsification"],
            "historical_signatures": bundle["historical"],
        },
        "stage22_manifest.json": {
            "analysis_version": ANALYSIS_VERSION,
            "summary": bundle["summary"],
            "verdicts": bundle["verdicts"],
            "read_only_audit": bundle["read_only_audit"],
            "determinism": bundle["determinism"],
            "corpus": bundle["corpus"],
            "artefacts": list(STAGE22_FILES),
            "document": STAGE22_DOC,
            "stop_condition": (
                "Stage 22 changes no production code. It is a detector calibration study: it "
                "decomposes the residual and stops."
            ),
        },
    }


def write_analysis(
    bundle: Mapping[str, Any],
    stage22_dir: Path = DEFAULT_STAGE22_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the sixteen JSON artefacts and the report. Additive: nothing else is touched."""
    stage22_dir = Path(stage22_dir)
    docs_dir = Path(docs_dir)
    stage22_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = _artefacts(bundle)
    written: Dict[str, Path] = {}
    for name in STAGE22_FILES:
        if name not in payload:
            raise Stage22Error(f"the artefact {name} was never built")
        path = stage22_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    report = render_report(bundle)
    doc_path = docs_dir / STAGE22_DOC
    doc_path.write_text(report, encoding="utf-8")
    written[STAGE22_DOC] = doc_path
    report_path = stage22_dir / "stage22_report.md"
    report_path.write_text(report, encoding="utf-8")
    written["stage22_report.md"] = report_path
    return written


# ===========================================================================
# PART 11 - the report: twenty sections, then the final question
# ===========================================================================
def _pct(value: Optional[float], places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def render_report(bundle: Mapping[str, Any]) -> str:
    """The twenty sections the brief requires, in its order, from the measured bundle."""
    s = bundle["summary"]
    partition = bundle["taxonomy"]["cause_partition"]
    out: List[str] = [
        "# Stage 22 - Detector Error Decomposition and Ground-Truth Calibration\n",
        "Stage 21 showed that the residual Stage 20 measured on the historical corpus cannot be "
        "attributed to performance, because the same signature appears on streams whose composition "
        "is known. It left one question open, and this stage exists to answer it: on traces whose "
        "composition *is* known, where does the detector's residual actually come from?\n",
        "Stage 22 does not touch the detector, does not re-open the performance-layer question, and "
        "does not try to make the residual smaller. It compiles the 53-composition Tier A control "
        "corpus to exact traces, runs the existing Stage 15 detector over them, and decomposes the "
        "resulting residual into named, measured causes.\n",
        f"**The answer is short.** On {s['control_songs']} compositions and "
        f"{s['register_values']} register values the detector leaves "
        f"{_pct(s['detector_residual_share'])} unexplained under the hold convention and "
        f"{_pct(s['detector_residual_share_exporter'])} once the outside-note convention is removed. "
        f"That residual partitions into **{_pct(partition['note_set_share'])} note set**, "
        f"**{_pct(partition['value_share'])} value reading** and "
        f"**{_pct(partition['interaction_share'])} interaction**, and the value part is *entirely* "
        "the four-parameter level contour: pitch, generator, distortion, channel and AUDCTL "
        "contribute zero.\n",
        "The brief expected ``B10 residual = 0`` and it is: the exact composition leaves nothing at "
        "all, on every song. Nothing is unexplained, and nothing had to be assumed to get there.\n",
        "Analysis only, read-only and additive. No audio was rendered, no music was generated, no "
        "listening test was run, and Stage 15, the composer, the DSL, the IR, the player and the "
        "exporter are unchanged.\n",
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE22_FILES) + ".\n",
    ]
    for section in (
        _s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9, _s10,
        _s11, _s12, _s13, _s14, _s15, _s16, _s17, _s18, _s19, _s20, _s_final,
    ):
        out.extend(section(bundle))
    return "\n".join(out)


def _s1(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    partition = bundle["taxonomy"]["cause_partition"]
    return [
        "## 1. Executive Summary\n",
        _table(
            ["question", "answer"],
            [
                ["Is the detector's residual explained?",
                 f"**Yes.** {_pct(partition['note_set_share'])} note set, "
                 f"{_pct(partition['value_share'])} value reading, "
                 f"{_pct(partition['interaction_share'])} interaction; the partition closes "
                 f"({partition['closes']})."],
                ["Does the exact composition explain everything?",
                 f"**Yes.** B10 residual = {s['b10_values']} on {s['register_values']} register "
                 f"values, on every song."],
                ["Is the residual mostly a detection error or a representation limit?",
                 "**Detection.** The note set is the largest single cause. The only value-level "
                 f"error is the level contour: {s['envelope_marginal_values']} register values."],
                ["Are pitch, generator and channel errors real?",
                 f"**No.** Divider exact at matched onsets {_pct(s['pitch_divider_exact_share'])}, "
                 f"generator correct at matched onsets {_pct(s['generator_onset_correct_share'])}, "
                 f"channel mismatches {s['channel_mismatches']}."],
                ["Is the historical residual different?",
                 f"**{bundle['falsification']['verdict']}** - share ratio "
                 f"{bundle['falsification']['share_ratio_historical_over_control']}, AUDF-share delta "
                 f"{bundle['falsification']['audf_share_delta']}."],
                ["Verdict", " + ".join(s["verdicts"].values())],
                ["Read-only audit",
                 f"**{s['read_only']}** - {s['read_only_files_checked']} production and composition "
                 "artefacts hashed before and after the run, none changed"],
            ],
        ),
        "",
        "Stage 22 changes no production code and stops here.",
        "",
    ]

    doc_path = docs_dir / STAGE22_DOC
    doc_path.write_text(report, encoding="utf-8")
    written[STAGE22_DOC] = doc_path
    report_path = stage22_dir / "stage22_report.md"
    report_path.write_text(report, encoding="utf-8")
    written["stage22_report.md"] = report_path
    return written




def corpus_hashes(
    songs_dir: Path = DEFAULT_SONGS_DIR, ai_dir: Path = DEFAULT_AI_DIR
) -> Dict[str, Optional[str]]:
    """The hash of every composition document Stage 22 reads."""
    out: Dict[str, Optional[str]] = {}
    for slug, _kind, path in stage21.control_sources(
        songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR
    ):
        out[f"composition/{slug}"] = sha256_file(path)
    return out


def _s2(bundle: Mapping[str, Any]) -> List[str]:
    ground_truth = bundle["ground_truth"]
    rows = [row for row in bundle["songs"] if "ladder_exporter" in row]
    return [
        "## 2. Dataset\n",
        f"The Tier A control corpus: **{ground_truth['songs']} compositions**, "
        f"{ground_truth['total_notes']} sounding notes and "
        f"{ground_truth['total_silent_notes']} silent ones, compiled to exact traces by the "
        "project's own compiler. Nothing is read from the historical corpus for calibration; the "
        "historical traces appear only in section 16.\n",
        _table(
            ["slug", "kind", "frames", "AUDCTL", "16-bit", "notes", "spans", "distinct pitches",
             "residual"],
            [
                [
                    row["slug"], row["kind"], row["frames"], row["audctl"],
                    "yes" if row["coupled_16bit"] else "no",
                    row["ground_truth_notes"], row["detected_spans"],
                    row["features"]["distinct_pitches"],
                    _pct(row["residual"]["residual_share"]),
                ]
                for row in sorted(rows, key=lambda item: item["slug"])
            ],
        ),
        "",
        f"Every composition's AUDCTL is constant across its trace: "
        f"**{ground_truth['all_audctl_constant']}**. That single fact removes one whole taxonomy "
        "family before any measurement is taken, and section 7 records it as such.\n",
    ]


def _s3(bundle: Mapping[str, Any]) -> List[str]:
    ground_truth = bundle["ground_truth"]
    status = ground_truth["status_counts"]
    return [
        "## 3. Ground Truth\n",
        "Two levels of truth are kept apart, because conflating them is the failure this stage "
        "exists to prevent.\n",
        "**Level 1 - the composition.** Each note comes from an authored composition document that "
        "references no register. Every canonical field carries a status: `KNOWN` if the document "
        "states it, `DERIVED` if the project's own compiler or player model computes it, "
        "`UNKNOWN` if it does not exist in that document, `NOT_APPLICABLE` if the concept does not "
        "apply. Nothing is invented.\n",
        _table(
            ["field", "KNOWN", "DERIVED", "UNKNOWN", "NOT_APPLICABLE"],
            [
                [name, status[name][KNOWN], status[name][DERIVED], status[name][UNKNOWN],
                 status[name][NOT_APPLICABLE]]
                for name in CANONICAL_FIELDS
            ],
        ),
        "",
        "**Level 2 - the exact trace.** The compiler's deterministic output, hashed per song. "
        "`composition -> exact trace` leaves no residual by construction: the arm `A_exact` measures "
        f"**{bundle['aggregate']['arms']['A_exact']['residual_values']}** register values over the "
        "whole detailed corpus, which is the identity the brief asks to be checked before anything "
        "else is believed.\n",
        "The asymmetry is the point: onsets and level tracks are *derived*, not authored. That is "
        "why the ablation ladder has to distinguish a wrong boundary from a reduced level track, and "
        "why the ground-truth verdict is `GROUND_TRUTH_EXTRACTION_LIMITATION` rather than an "
        "unqualified claim of exactness.\n",
    ]


def _s4(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    bridge = bundle["predictor_bridge"]
    return [
        "## 4. Detector\n",
        "The detector is Stage 15's, run exactly as Stage 20 and Stage 21 run it:\n",
        "1. `stage20.note_records` segments the trace with `stage15.note_spans`, which splits a run "
        "of audible frames at a divider jump of 4 semitones that persists for 3 frames, or at a "
        "volume re-attack of 4 levels from near silence, and merges any span shorter than 3 frames "
        "into its predecessor.\n",
        "2. `stage20.predict_frames` reads pitch and waveform at each span's onset and fits a "
        "four-parameter envelope to the span's level track.\n",
        "3. `stage20.build_residual` forms the residual.\n",
        "Nothing about the detector is re-implemented. The *variations* are, and a bridge proves "
        "that the variation code reproduces the original bit for bit:\n",
        _table(
            ["song", "frames", "register values", "mismatches", "agrees"],
            [
                [row["slug"], row["frames"], row["register_values"], row["mismatches"],
                 row["agrees"]]
                for row in bridge
            ],
        ),
        "",
        f"The bridge holds on all {len(bridge)} songs it was run over "
        f"({sum(row['register_values'] for row in bridge)} register values, zero mismatches). "
        "Without it a difference between two arms could be a difference of code rather than of "
        "information.\n",
        f"The detector's residual is **{aggregate['detector_residual_values']} of "
        f"{aggregate['register_values']} register values = "
        f"{_pct(aggregate['detector_residual_share'])}** under the hold convention and "
        f"**{_pct(aggregate['ladder'][OUTSIDE_EXPORTER]['B0']['residual_share'])}** under the "
        "exporter convention.\n",
    ]


def _s5(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    attribution = aggregate["attribution"]
    return [
        "## 5. Residual Definition\n",
        "The residual is `stage20.build_residual`'s, unchanged: for each of the nine registers "
        "(AUDF1-4, AUDC1-4, AUDCTL) and each frame, the residual is non-zero when the exact trace "
        "and the prediction differ at that register in that frame. The denominator is therefore "
        "`frames x 9`.\n",
        "**`residual != 0` is not `detector error`.** Three things can produce a residual value and "
        "each is separated before any claim is made:\n",
        "1. **the outside-note convention** - `player.asm` holds AUDF across a rest while the "
        "project's frame compiler leaves an unwritten frame at zero. This is a disagreement between "
        "two project components, not a detector error, and section 14 measures it.\n",
        "2. **note segmentation** - spans that merge two notes, start late, end early, or miss a "
        "note.\n",
        "3. **the level-track reduction** - the detector reads the right span and describes its "
        "level track with four numbers instead of one per frame.\n",
        "The frame attribution partitions the trace exactly:\n",
        _table(
            ["bucket", "register values", "share of the trace"],
            [
                [name, attribution["counts"][name], _pct(attribution["shares"][name])]
                for name in ATTRIBUTION_BUCKETS
            ],
        ),
        "",
        "The five buckets sum to the whole trace and that identity is asserted in code, not assumed. "
        "They are a *frame* attribution and are deliberately not read as causes: a merged span shows "
        "up as `VALUE_ERROR_INSIDE_BOTH` even though its cause is segmentation. Section 6's arms are "
        "what separate the causes, and the report keeps the two readings apart throughout.\n",
    ]


    for slug, _kind, path in stage21.control_sources(songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR):
        out[f"composition/{slug}"] = sha256_file(path)
    return out


def read_only_audit(
    before: Mapping[str, Optional[str]],
    after: Mapping[str, Optional[str]],
    label: str = "read-only inputs",
) -> Dict[str, Any]:
    """Compare two hash maps and report every difference. An empty diff is the claim."""
    keys = sorted(set(before) | set(after))
    changed = [key for key in keys if before.get(key) != after.get(key)]
    return {
        "label": label,
        "files_checked": len(keys),
        "changed": changed,
        "unchanged": len(keys) - len(changed),
        "read_only": not changed,
        "statement": (
            "the hash of every production module, the player source, and every composition document "
            "is identical before and after the run"
        ),
    }


def _s6(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    ladder = aggregate["ladder"][OUTSIDE_EXPORTER]
    definition = {name: description for name, _exact, _set, description in LADDER}
    previous: Optional[int] = None
    rows = []
    for name, _exact, note_set, _description in LADDER:
        value = ladder[name]["residual_values"]
        rows.append([
            name, definition[name], note_set, value, _pct(ladder[name]["residual_share"]),
            "n/a" if previous is None else previous - value,
        ])
        previous = value
    arms = aggregate["arms"]
    return [
        "## 6. Ablation Ladder\n",
        "The cumulative ladder, under the **exporter** convention so that the convention is not "
        "charged to the detector. B0 is the detector exactly; B10 is the exact composition and must "
        "leave nothing.\n",
        _table(
            ["rung", "what it adds", "note set", "residual values", "share", "delta from previous"],
            rows,
        ),
        "",
        "**The ladder is not monotone in the brief's literal form, and that is a finding.** "
        "Substituting boundaries on the detector's *own* span list makes the residual worse, not "
        "better:\n",
        _table(
            ["arm", "residual values", "share", "what it isolates"],
            [
                [name, arms[name]["residual_values"], _pct(arms[name]["residual_share"]),
                 arms[name]["description"]]
                for name in (
                    "A_detector", "A_detector_spans_truth_boundaries",
                    "A_detector_spans_truth_values", "A_truth_spans_detector_values", "A_exact",
                )
            ],
        ),
        "",
        "A span moved to a correct onset while its neighbours are still missing covers frames the "
        "detector had right and leaves frames the composition has. The cause partition of section 7 "
        "is therefore built from the **matched arms**, not from the ladder's steps.\n",
        "**Three of the nine fields are no-ops in this pipeline, and each is implemented anyway so "
        "its invariance is measured rather than assumed:**\n",
        _table(
            ["field", "why it cannot vary", "measured marginal"],
            [
                [field, FIELD_NOOP_REASONS[field], aggregate["leave_one_out_marginals"][field]]
                for field in (FIELD_CHANNEL, FIELD_VOLUME, FIELD_AUDCTL)
            ],
        ),
        "",
    ]


def _s7(bundle: Mapping[str, Any]) -> List[str]:
    taxonomy = bundle["taxonomy"]
    partition = taxonomy["cause_partition"]
    return [
        "## 7. Error Taxonomy\n",
        "Every class the brief lists, with the count the analysis measured, the share of the trace "
        "it represents, how many songs it touches, and its disposal. A class marked "
        "`EMPTY_BY_CONSTRUCTION` cannot be non-zero here and says why.\n",
        _table(
            ["family", "class", "count", "share of trace", "songs", "status", "note"],
            [
                [item["family"], item["class"], item["count"], _pct(item["share_of_trace"]),
                 item["songs_affected"], item["status"], item["note"]]
                for item in taxonomy["matrix"]
            ],
        ),
        "",
        "### The cause partition\n",
        "The classes above count what was measured; they are not additive, because one register "
        "frame can have more than one apparent cause. This is the reading that sums to the residual "
        "with nothing left over:\n",
        _table(
            ["cause", "residual values", "share of the exporter residual"],
            [
                ["outside-note convention", partition["convention"],
                 _pct(partition["convention_share_of_hold"])],
                ["note set only (detector's spans, exact values)", partition["note_set_only"],
                 _pct(partition["note_set_share"])],
                ["value reading only (composition's spans, detector's reads)", partition["value_only"],
                 _pct(partition["value_share"])],
                ["interaction (wrong for both reasons at once)", partition["interaction"],
                 _pct(partition["interaction_share"])],
                ["detector's residual under the exporter convention",
                 partition["detector_residual_values_exporter"], "100.0%"],
                ["detector's residual under hold",
                 partition["detector_residual_values_hold"],
                 _pct(_share(partition["detector_residual_values_hold"],
                             partition["detector_residual_values_hold"]))],
            ],
        ),
        "",
        f"The partition closes: **{partition['closes']}**. Nothing is attributed to the first cause "
        "that matches, and the interaction term is the honest home for a value that is wrong for "
        "both reasons at once.\n",
        "**The partition is taken on the exporter residual, and that matters.** The arms and the "
        "ladder both run under the exporter convention, so a partition of the *hold* residual would "
        "put the convention difference into the interaction term and inflate it by roughly half. The "
        "convention is therefore reported as its own component, and the hold total is accounted for "
        "as `convention + note set + value reading + interaction`. This correction changed the "
        "interaction share substantially and is recorded in section 18.\n",
    ]


def _s8(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    counts = aggregate["note_detection"]
    metrics = aggregate["note_detection_metrics"]
    per_song = aggregate["per_song"]
    return [
        "## 8. Note Detection\n",
        "Matching is deterministic: a detected span and a ground-truth note match when they share at "
        "least one frame on the same voice, and ties break on the smaller onset difference, then the "
        "smaller start frame, then the smaller index. Every count below is defined from that one "
        "relation, so nothing double-counts.\n",
        _table(
            ["quantity", "value"],
            [
                ["ground-truth notes", counts["ground_truth_notes"]],
                ["detected spans", counts["detected_spans"]],
                ["matched notes", counts["matched_notes"]],
                ["matched spans", counts["matched_spans"]],
                ["missed ground-truth notes (no overlapping span)", counts["missed_ground_truth_notes"]],
                ["false detector spans (no overlapping note)", counts["false_detector_spans"]],
                ["merged spans (one span, two or more notes)", counts["merged_spans"]],
                ["split notes (one note, two or more spans)", counts["split_notes"]],
                ["notes with frames no span covers", counts["notes_with_uncovered_frames"]],
                ["such uncovered note frames", counts["uncovered_note_frames"]],
                ["spans whose onset *and* length are both exact", counts["exact_boundary_spans"]],
                ["exact-boundary share of matched spans",
                 _pct(_share(counts["exact_boundary_spans"], counts["matched_spans"]))],
                ["precision by count", _pct(metrics["by_count"]["precision"], 2)],
                ["recall by count", _pct(metrics["by_count"]["recall"], 2)],
                ["precision by frames", _pct(metrics["by_frames"]["precision"], 2)],
                ["recall by frames", _pct(metrics["by_frames"]["recall"], 2)],
                ["F1 by frames", _pct(metrics["by_frames"]["f1"], 2)],
            ],
        ),
        "",
        "**The detector never invents a note.** False spans are zero across the whole corpus, and by "
        "the overlap relation so are whole missed notes: every span overlaps a real note and every "
        "note is overlapped by a span. That makes the by-count precision and recall look perfect, and "
        "they are - for the question they ask.\n",
        "The error is in *how many notes one span claims*. A merged span still overlaps every note it "
        "absorbed, so overlap matching cannot see it; what it does is leave the absorbed notes' frames "
        "with the first note's pitch and generator and, where the span ends early, with no coverage at "
        "all. That is why the frame-level shortfall is counted separately, and why the taxonomy's "
        "`missed_note_onset` class is measured at the frame level rather than the note level.\n",
        _table(
            ["per-song spread", "mean", "median", "min", "p25", "p75", "max"],
            [
                [key] + [
                    per_song[key][stat] for stat in ("mean", "median", "min", "p25", "p75", "max")
                ]
                for key in (
                    "residual_share", "missed_notes", "merged_spans", "note_recall_by_count",
                    "divider_exact_share",
                )
            ],
        ),
        "",
    ]


def _s9(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    pitch = aggregate["pitch"]
    marginals = aggregate["leave_one_out_marginals"]
    return [
        "## 9. Pitch\n",
        "`AUDF != the expected musical pitch` is not the same as a detector error, and the brief "
        "says so: a noise generator uses AUDF as a clock divisor, not as a pitch. The analysis "
        "therefore compares dividers through the detector's own mapping, at the onset the detector "
        "actually read.\n",
        _table(
            ["quantity", "value"],
            [
                ["matched onsets compared", pitch["matched_compared"]],
                ["divider exactly the note's own", pitch["divider_exact"]],
                ["divider exact share", _pct(aggregate["pitch_divider_exact_share"], 2)],
                ["wrong divider", pitch["matched_compared"] - pitch["divider_exact"]],
                ["octave or register errors", pitch["octave_or_register_errors"]],
                ["16-bit coupled notes", pitch["coupled_16bit_notes"]],
                ["leave-one-out marginal for pitch", marginals[FIELD_PITCH]],
            ],
        ),
        "",
        "The **leave-one-out marginal for pitch is zero**. With the composition's note set and spans "
        "and every other field exact, removing exact pitch changes nothing, because the detector "
        "reads pitch at the span's onset and the compiler never changes a note's divider inside a "
        "note. A wrong divider therefore only ever appears where the span itself is wrong, and it is "
        "already charged to the note set.\n",
        "Non-tonal generators are separated out in the per-song records so a noise channel's clock "
        "divisor cannot be counted as a wrong pitch.\n",
    ]


def _s10(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    marginals = aggregate["leave_one_out_marginals"]
    detector = aggregate["detector_residual_values"]
    return [
        "## 10. Volume / Envelope\n",
        "This is the only value-level error the whole analysis finds, and it is a **representation "
        "limit rather than a detection error**.\n",
        _table(
            ["quantity", "value", "share of the detector's residual"],
            [
                ["envelope (level track) marginal", marginals[FIELD_ENVELOPE],
                 _pct(_share(marginals[FIELD_ENVELOPE], detector))],
                ["volume scalar marginal", marginals[FIELD_VOLUME],
                 _pct(_share(marginals[FIELD_VOLUME], detector))],
                ["detector's residual", detector, "100.0%"],
            ],
        ),
        "",
        "The detector reads the right span, at the right level, and then describes the span's whole "
        "level track with four numbers: peak, attack, sustain, release. When the trace's track is not "
        "expressible in that shape - a decay the model does not have, a level that steps, a release "
        "the fit rounds - the difference appears as residual values that are not anybody's mistake.\n",
        "The volume *scalar* is a no-op because the composition's peak and the maximum of the "
        "observed track are the same number on a compiled trace. Both are reported so the "
        "distinction between the scalar and the shape is visible.\n",
        "This is the finding that answers the brief's question about representation: "
        "`REPRESENTATION_LIMITATION`. The detector does not mis-detect the note; its note model "
        "cannot carry the track.\n",
    ]


def _s11(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    generator = aggregate["generator"]
    metrics = aggregate["generator_transition_metrics"]
    return [
        "## 11. Generator / Distortion\n",
        "Stage 17 suggested a potentially large problem in generator detection - one channel where "
        "the detector reported roughly 27 of 125 real distortion changes. Stage 22 tests that on the "
        "whole corpus, and the two questions are separated because they are genuinely different:\n",
        "**Classification.** When the detector reports a generator at a span's onset, is it the "
        "trace's generator there?\n",
        _table(
            ["quantity", "value"],
            [
                ["matched onsets compared", generator["onset_distortion_compared"]],
                ["distortion read correctly at the onset", generator["onset_distortion_correct"]],
                ["onset correct share", _pct(aggregate["generator_onset_correct_share"], 2)],
                ["leave-one-out marginal for generator",
                 aggregate["leave_one_out_marginals"][FIELD_GENERATOR]],
                ["leave-one-out marginal for distortion",
                 aggregate["leave_one_out_marginals"][FIELD_DISTORTION]],
            ],
        ),
        "",
        "**Transition detection.** The trace changes its distortion nibble at certain frames; the "
        "detector's representation can only change it where a span begins.\n",
        _table(
            ["quantity", "value"],
            [
                ["frames where the distortion actually changes", generator["truth_change_frames"]],
                ["frames the detector's representation changes it", generator["predicted_change_frames"]],
                ["hits", generator["hits"]],
                ["missed", generator["missed"]],
                ["spurious", generator["spurious"]],
                ["precision", _pct(metrics["precision"], 2)],
                ["recall", _pct(metrics["recall"], 2)],
                ["F1", _pct(metrics["f1"], 2)],
            ],
        ),
        "",
        "**The two answers differ sharply and that is the finding.** Classification is essentially "
        "perfect - the onset read is the trace's generator at that frame - while transition recall is "
        "poor. The detector does not misread the generator; it *cannot report* a change that happens "
        "inside a span, because a merged span has only one onset. Every missed transition is already "
        "charged to the note set, which is why the leave-one-out marginal for generator and "
        "distortion is zero.\n",
        "Stage 17's single-channel observation is therefore **not representative**: the corpus-wide "
        "miss rate is a consequence of merged spans, not of a generator classifier that gets the "
        "generator wrong.\n",
    ]


def _s12(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    channel = aggregate["channel"]
    return [
        "## 12. Channel Assignment\n",
        "**A channel assignment cannot be wrong in this pipeline, and the zero is reported with its "
        "reason rather than as an achievement.**\n",
        _table(
            ["quantity", "value"],
            [
                ["matched spans compared", channel["matched_compared"]],
                ["matched spans on a different voice than the note", channel["matched_voice_mismatches"]],
                ["share", _pct(_share(channel["matched_voice_mismatches"], channel["matched_compared"]))],
                ["leave-one-out marginal for channel",
                 aggregate["leave_one_out_marginals"][FIELD_CHANNEL]],
                ["frames where two voices are register-identical", channel["ambiguous_frame_pairs"]],
                ["songs with any such frame", channel["songs_ambiguous"]],
            ],
        ),
        "",
        "Both arms derive their voices from the same AUDCTL through `stage15.voices_for`, so which "
        "voice a frame belongs to is a property of the trace's configuration, not of the detector. A "
        "difference is not merely absent from the data, it is impossible by construction, and the "
        "taxonomy records the class as `EMPTY_BY_CONSTRUCTION`.\n",
        "The second question is the real one. Where two voices hold the same divider, the same "
        "generator and the same level in the same frame, the registers do not say which channel a "
        "listener would call the melody. Those frames are counted and flagged `AMBIGUOUS` rather "
        "than scored as a detector failure, exactly as the brief requires.\n",
    ]


def _s13(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    timing = aggregate["timing"]
    return [
        "## 13. Timing\n",
        _table(
            ["quantity", "value"],
            [
                ["ground-truth notes", timing["ground_truth_notes"]],
                ["ground-truth onsets on the composition's row grid",
                 timing["ground_truth_notes_on_the_row_grid"]],
                ["ground-truth on-grid share",
                 _pct(_share(timing["ground_truth_notes_on_the_row_grid"],
                             timing["ground_truth_notes"]))],
                ["detected spans", timing["detector_spans"]],
                ["detected onsets on the row grid", timing["detector_onsets_on_the_row_grid"]],
                ["detector on-grid share",
                 _pct(_share(timing["detector_onsets_on_the_row_grid"], timing["detector_spans"]))],
                ["event-ordering violations", timing["ordering_violations"]],
            ],
        ),
        "",
        "The composition's onsets are whole rows, so on a compiled trace every ground-truth onset is "
        "a multiple of `frames_per_tick`. The detector's onsets are register-change positions and "
        "need not be, so the two on-grid shares are reported separately: the first is a property of "
        "the compiler, the second is a measurement of the detector.\n",
        "Onset and duration offsets are reported per song in `timing_errors.json`, because their "
        "corpus mean would hide the difference between a detector that is consistently a frame late "
        "and one that is right on most notes and badly wrong on a few.\n",
    ]


def _s14(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    silence = aggregate["silence"]
    attribution = aggregate["attribution"]
    return [
        "## 14. Silent / Non-musical Register Activity\n",
        "Four kinds of register activity that are not a note are separated, because lumping them "
        "together is how a convention difference gets mistaken for a performance effect.\n",
        _table(
            ["quantity", "value", "what it is"],
            [
                ["frames neither the detector nor the composition claims",
                 silence["outside_both_frames"],
                 "the hold-versus-zero convention's signature - `player.asm` holds AUDF across a "
                 "rest while the frame compiler leaves the frame at zero"],
                ["residual values in those frames",
                 attribution["counts"][ATTR_OUTSIDE_BOTH],
                 "the convention's cost, charged to the convention and not to the detector"],
                ["silent register changes (AUDF moves at level zero)",
                 silence["silent_register_changes"],
                 "player state a listener cannot hear"],
                ["initialisation frames", silence["initialisation_frames"],
                 "frames before the trace first sounds"],
                ["frames outside every note", silence["frames_outside_every_note"],
                 "rests and gaps"],
            ],
        ),
        "",
        "The convention is a disagreement between two of the project's own components, not a "
        "detector error. That is why the ladder and the cause partition are computed under the "
        "**exporter** convention: charging the convention to the detector would overstate the "
        "detector's error by roughly a third of it.\n",
        "No audio was rendered to decide any of this. The claim is about register frames, and it is "
        "checked against the compiler's own output.\n",
    ]


def _s15(bundle: Mapping[str, Any]) -> List[str]:
    aggregate = bundle["aggregate"]
    correlations = aggregate["correlations"]
    rows = [row for row in bundle["songs"] if "ladder_exporter" in row]
    strongest = sorted(
        (
            (name, entry)
            for name, entry in correlations.items()
            if entry.get("spearman") is not None
        ),
        key=lambda item: -abs(item[1]["spearman"]),
    )
    return [
        "## 15. Per-song Variation\n",
        f"The corpus mean is **{_pct(aggregate['detector_residual_share'])}**, but the mean is not "
        "the whole story:\n",
        _table(
            ["metric", "mean", "median", "min", "p25", "p75", "max"],
            [
                [key] + [
                    aggregate["per_song"][key][stat]
                    for stat in ("mean", "median", "min", "p25", "p75", "max")
                ]
                for key in (
                    "residual_share", "residual_values", "missed_notes", "merged_spans",
                    "note_recall_by_count", "divider_exact_share",
                )
            ],
        ),
        "",
        "### Outliers\n",
        _table(
            ["metric", "outlying songs"],
            [
                [key, ", ".join(f"{item['slug']} ({item[key]})" for item in value) or "none"]
                for key, value in sorted(aggregate["outliers"].items())
            ],
        ),
        "",
        "### Correlations\n",
        "Spearman's rho between each song feature and the song's residual share. **Correlation is "
        "not causation** and is reported as a diagnostic only; the features are computed from the "
        "ground truth and the trace, never from the residual, so the comparison is not circular.\n",
        _table(
            ["feature", "Pearson", "Spearman"],
            [
                [name, entry.get("pearson"), entry.get("spearman")]
                for name, entry in sorted(correlations.items())
            ],
        ),
        "",
        (
            "The strongest association is with **"
            + (strongest[0][0] if strongest else "nothing")
            + "**"
            + (
                f" (rho = {strongest[0][1]['spearman']}), which is what the note-set finding would "
                "predict."
                if strongest else "."
            )
            + " A song with more notes has more chances to merge or miss one, so the association is "
            "consistent with the cause partition rather than an independent finding.\n"
        ),
    ]


def _s16(bundle: Mapping[str, Any]) -> List[str]:
    comparison = bundle["comparison"]
    control = comparison["control"]
    historical = comparison["historical"]
    metrics = historical["generator_transition_metrics"]
    return [
        "## 16. Historical Comparison\n",
        "This section runs **after** the control analysis, and only on the quantities both corpora "
        "can produce. The historical corpus has no ground truth, so the note-set and value arms and "
        "the frame attribution cannot be computed for it, and they are deliberately not compared. "
        "What is compared is the *shape* of the residual.\n",
        "The comparable quantities are the residual's share of the stream and its AUDF-to-AUDC "
        "split. Both are register-group shares and neither needs a ground truth, so the two corpora "
        "are compared on like with like. The control corpus's *arm-based* note-set share is a "
        "different quantity and is not compared with them.\n",
        _table(
            ["quantity", "control (Tier A)", "historical"],
            [
                ["songs", control["songs"], historical["songs"]],
                ["register values", control["register_values"], historical["register_values"]],
                ["residual under hold", control["residual_hold_values"],
                 historical["residual_hold_values"]],
                ["residual share under hold", _pct(control["residual_hold_share"]),
                 _pct(historical["residual_hold_share"])],
                ["residual under the exporter convention", control["residual_exporter_values"],
                 historical["residual_exporter_values"]],
                ["residual share under the exporter convention",
                 _pct(control["residual_exporter_share"]),
                 _pct(historical["residual_exporter_share"])],
                ["AUDF share of the residual (exporter vs exporter)",
                 _pct(control["audf_share_of_exporter_residual"]),
                 _pct(historical["audf_share_of_exporter_residual"])],
                ["AUDF share of the residual (hold vs hold)",
                 _pct(_share(bundle["aggregate"]["register_groups_hold"]["AUDF"]["residual_values"],
                             bundle["aggregate"]["detector_residual_values"])),
                 _pct(historical["audf_share_of_residual"])],
                ["AUDC share of the residual (hold vs hold)",
                 _pct(1.0 - (_share(
                     bundle["aggregate"]["register_groups_hold"]["AUDF"]["residual_values"],
                     bundle["aggregate"]["detector_residual_values"]) or 0.0)),
                 _pct(historical["audc_share_of_residual"])],
                ["distortion-transition precision", "see section 11", _pct(metrics["precision"], 2)],
                ["distortion-transition recall", "see section 11", _pct(metrics["recall"], 2)],
                ["distortion-transition F1", "see section 11", _pct(metrics["f1"], 2)],
            ],
        ),
        "",
        f"Share ratio, historical over control: **{comparison['residual_share_ratio_historical_over_control']}**.\n",
        "The question the brief asks is whether the classes of error seen in the historical corpus "
        "match the classes seen on the known-truth corpus. A matching shape is *consistent with* the "
        "same causes - which is weaker than proof, and is reported as such. A different shape would "
        "be evidence of a different cause.\n",
    ]


def _s17(bundle: Mapping[str, Any]) -> List[str]:
    falsification = bundle["falsification"]
    return [
        "## 17. Falsification Test\n",
        f"**Question.** {falsification['question']}\n",
        _table(
            ["quantity", "value"],
            [
                ["control residual share", _pct(falsification["control_residual_share"])],
                ["historical residual share", _pct(falsification["historical_residual_share"])],
                ["share ratio, historical over control",
                 falsification["share_ratio_historical_over_control"]],
                ["control AUDF share of the residual",
                 _pct(falsification["control_audf_share_of_residual"])],
                ["historical AUDF share of the residual",
                 _pct(falsification["historical_audf_share_of_residual"])],
                ["AUDF-share delta (exporter vs exporter)", falsification["audf_share_delta"]],
                ["AUDF-share delta (hold vs hold)",
                 falsification["audf_pairings"]["hold_vs_hold"]["delta"]],
                ["split consistent under both pairings", falsification["split_consistent"]],
                ["(context only) control note-set share of the residual",
                 _pct(falsification["control_note_set_share_of_residual"])],
                ["share consistent", falsification["share_consistent"]],
                ["split consistent", falsification["split_consistent"]],
                ["verdict", f"**{falsification['verdict']}**"],
                ["consequence", f"**{falsification['consequence']}**"],
            ],
        ),
        "",
        f"Thresholds, stated before the numbers were read: a share ratio in "
        f"[{falsification['thresholds']['share_ratio_low']}, "
        f"{falsification['thresholds']['share_ratio_high']}] and an AUDF-share delta within "
        f"{falsification['thresholds']['audf_share_delta']} under **both** convention pairings.\n",
        _table(
            ["pairing", "control AUDF share", "historical AUDF share", "delta", "within threshold"],
            [
                [name, _pct(row["control"]), _pct(row["historical"]), row["delta"], row["consistent"]]
                for name, row in sorted(falsification["audf_pairings"].items())
            ],
        ),
        "",
        f"**Is the difference robust? {falsification['difference_robust']}.** "
        f"{falsification['robustness_note']}\n",
        "On this corpus the residual's share of the stream is consistent (ratio "
        f"{falsification['share_ratio_historical_over_control']}, inside the band), and the AUDF "
        "split is consistent under the exporter pairing but not under the hold pairing. The two "
        "corpora also differ in instrument mix - the historical corpus leans on noise percussion, "
        "whose register activity is AUDC rather than AUDF - and that alone would move the split. A "
        "difference that depends on which convention is applied, and that a corpus-composition "
        "difference would also produce, is not evidence of anything about performance; it is a "
        "reason to design a new controlled experiment with a matched instrument mix.\n",
        f"{falsification['what_this_is_not']}\n",
    ]


def _s18(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["read_only_audit"]
    return [
        "## 18. Methodological Corrections\n",
        "Each problem found while building this stage, and what was done about it. Nothing was "
        "quietly fixed: a correction that changes a number is stated here.\n",
        "**1. The ablation ladder's first rung was ambiguous.** The brief's rung B1 is *replace the "
        "detector's onsets with ground-truth onsets*, which can be read as moving spans on the "
        "detector's own list or as adopting the composition's note set. Both were measured. Moving "
        "spans on the detector's list makes the residual **worse** "
        f"(`A_detector_spans_truth_boundaries` = "
        f"{bundle['aggregate']['arms']['A_detector_spans_truth_boundaries']['residual_values']} "
        f"against the detector's {bundle['aggregate']['detector_residual_values']}), because a span "
        "moved to a correct onset while its neighbours are missing covers frames the detector had "
        "right. The ladder therefore moves to the composition's note set at B1, the contradictory arm "
        "is kept and reported, and the causal claim rests on the matched arms instead of the steps.\n",
        "**2. An arm's name did not match its content.** An arm called *the detector's spans with "
        "exact values* was initially built with span-moving enabled, so it silently measured "
        "boundaries as well as values. The span source and the value source are now orthogonal, "
        "controlled by an explicit `move_spans` flag, and the four combinations are named for what "
        "they do.\n",
        "**3. The frame attribution could have been read as a cause attribution.** A merged span "
        "appears in the frame buckets as a *value* error although its cause is segmentation. Both "
        "readings are reported, each is labelled, and the code carries a warning that the buckets are "
        "not additive causes. The cause partition closes exactly; the matrix is explicitly not "
        "additive.\n",
        "**4. Three of the nine ladder fields are no-ops.** Rather than dropping them, they are "
        "implemented and measured as zero, and the reason is stated per field. A field that cannot "
        "vary must be shown invariant, not omitted.\n",
        "**5. The cause partition mixed two conventions.** The arms and the ladder run under the "
        "exporter convention while the detector's headline residual is the hold-policy one, so the "
        "first version of the partition subtracted exporter-policy arms from a hold-policy total. It "
        "closed arithmetically, which is what made it dangerous: the convention difference landed "
        "silently in the interaction term and inflated it from roughly a quarter to roughly a half. "
        "The partition is now taken on the exporter residual, the convention is reported as its own "
        "component, and the hold total is accounted for as `convention + note set + value + "
        "interaction`. The identity is asserted in code.\n",
        "**6. A per-song field status was read off one note.** The status map was first built from "
        "whichever note happened to be last, so a song whose final note was a rest reported "
        "`pitch_midi: UNKNOWN`. It is now aggregated over every note in the song, and the test suite "
        "pins it.\n",
        "**7. An artefact key collided with working state.** The provenance of a specification list "
        "was published under the key `specs`, which the writer used as its marker for in-memory "
        "state that must not reach disk. It is now `spec_count`, and the test that no transient key "
        "appears in any artefact is what found it.\n",
        "**8. The control corpus's deduplication and provenance are Stage 21's.** They are reused "
        "unchanged rather than re-derived, so the two stages cannot disagree about which compositions "
        "are in the corpus.\n",
        "**9. The historical corpus is never used as ground truth.** It cannot produce a note-set "
        "arm, a value arm or a frame attribution, and the comparison section says so instead of "
        "substituting a proxy. This is the discipline Stage 21 asked for and the reason this stage "
        "exists.\n",
        "**10. The control side of the historical comparison was read from the wrong arm.** The "
        "control corpus's residual under the exporter convention was taken from `A_exact`, the exact "
        "composition arm, which is zero by construction. The comparison therefore divided the "
        "historical residual by zero and reported a control share of `0.0`, which is the kind of "
        "number that looks like a finding and is not. It is now taken from `A_detector` under the "
        "exporter policy, and a test asserts that the control side is positive and equal to that "
        "arm.\n",
        "**11. The AUDF-share comparison was policy-sensitive and was reported as if it were not.** "
        "The AUDF share of the residual changes substantially depending on whether the hold or the "
        "exporter convention is applied, and the two corpora have different natural conventions - "
        "the compiler leaves an unwritten frame at zero, the player holds AUDF. Comparing one "
        "corpus's exporter share with the other's hold share is a category error, and it produced a "
        "knife-edge verdict at 0.210 against a 0.20 threshold. The test now measures *both* pairings "
        "and calls the split consistent only if both agree, and it reports whether a difference is "
        "robust. On this corpus the difference is **not** robust, and the report says so instead of "
        "promoting it.\n",
        "### Read-only audit\n",
        _table(
            ["audit", "files checked", "changed", "read-only"],
            [
                [row["label"], row["files_checked"], len(row["changed"]), row["read_only"]]
                for _key, row in sorted(audit.items())
            ],
        ),
        "",
        f"{audit['production']['statement']}. Stage 15 to 21, the composer, the DSL, the IR, the "
        "player and the exporter were read through their hashes and never written.\n",
    ]


def _s19(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 19. Limitations\n",
        "**The ground truth is derived, not authored.** Onsets and level tracks are computed from the "
        "composition by the project's own compiler. The ground truth is exact *for the compiled "
        "trace* by construction, and it is not a human performance. A human performance would "
        "introduce exactly the kind of variation this stage is trying to rule out, so the corpus "
        "cannot speak to it at all.\n",
        "**One representation, one detector.** Everything here is about Stage 15's note model and "
        "Stage 20's four-parameter contour. A different detector would decompose differently. The "
        "cause partition is a statement about this pipeline, not about note detection in general.\n",
        "**Three fields are structurally unmeasurable.** Channel assignment, AUDCTL and the volume "
        "scalar cannot vary between the arms. Their zero is a property of the design, and this stage "
        "cannot tell whether a *different* pipeline would get them wrong.\n",
        "**The historical comparison is shape-only.** Without ground truth the historical corpus "
        "cannot be partitioned. The comparison in section 16 is therefore a comparison of the "
        "residual's signature, and a matching signature is consistent with the same causes rather "
        "than proof of them.\n",
        "**The interaction term is a residual, not a measurement.** "
        f"{_pct(bundle['taxonomy']['cause_partition']['interaction_share'])} of the detector's "
        "residual is attributed to the note set and the value reading jointly. It is the honest home "
        "for a value wrong for both reasons at once, and it is not decomposed further because doing "
        "so would need an assumption this stage does not have.\n",
        "**No listening test was run, and none should be inferred.** Every claim here is about "
        "register frames. Whether a register difference is audible is a different question, and this "
        "stage does not answer it.\n",
        "**The corpus is the project's own compositions.** It is the only ground truth available, and "
        "it is authored to exercise the compiler. Its note density, its instrument set and its "
        "polyphony are not a random sample of POKEY music.\n",
    ]


def _s20(bundle: Mapping[str, Any]) -> List[str]:
    verdicts = bundle["verdicts"]
    return [
        "## 20. Verdict\n",
        _table(
            ["subject", "verdict", "deciding condition"],
            [
                [subject, data["verdict"], data["deciding_condition"]]
                for subject, data in verdicts.items()
            ],
        ),
        "",
        "### What the verdicts mean\n",
        "**`DETECTOR_ERROR_EXPLAINED`.** The detector's residual is not a mystery. It partitions "
        "into the note set, the value reads and their interaction, and the exact composition leaves "
        "nothing at all on every song. No unexplained component remains, so the brief's STOP "
        "condition A applies: this is a detector calibration study and it ends here.\n",
        "**`REPRESENTATION_LIMITATION`.** The only value-level error is the four-parameter level "
        "contour. The detector is not mis-detecting the note; its note model cannot carry the track. "
        "Per the brief, this is documented and not repaired.\n",
        "**`GROUND_TRUTH_EXTRACTION_LIMITATION`.** The ground truth is derived from the composition "
        "by the project's own compiler. It is exact for the compiled trace and it is not a human "
        "performance, and the status counts say which fields are known and which are derived.\n",
        f"**`{verdicts['historical_residual']['verdict']}`.** The historical residual's shape is "
        "compared with the control corpus's on the only quantities both can produce.\n",
        f"**`{verdicts['performance_candidate']['verdict']}`.** `CONFIRMED_PERFORMANCE_CANDIDATE` is "
        "zero for every control song by construction, and Stage 21's inconclusive verdict on the "
        "performance layer is unchanged. What this stage changes is the *reason*: any future claim "
        "about performance must first account for the named detector errors below.\n",
        "`PROVEN PERFORMANCE LAYER` is not in the vocabulary and is not used. Nothing here is "
        "evidence for one.\n",
    ]



def _s_final(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    partition = bundle["taxonomy"]["cause_partition"]
    falsification = bundle["falsification"]
    consistent = (
        falsification["verdict"] == "HISTORICAL_RESIDUAL_CONSISTENT_WITH_DETECTOR_ERROR"
    )
    return [
        "## The Final Question\n",
        "**Can the detector's residual on the known-truth corpus be explained by specific, measured "
        "detector limitations?**\n",
        f"**Yes.** On {s['control_songs']} Tier A compositions and {s['register_values']} register "
        "values, the residual partitions exactly into:\n",
        _table(
            ["cause", "register values", "share of the exporter residual"],
            [
                ["note set (spans merged, missed or mis-bounded)",
                 partition["note_set_only"], _pct(partition["note_set_share"])],
                ["value reading (the four-parameter level contour)",
                 partition["value_only"], _pct(partition["value_share"])],
                ["interaction (wrong for both reasons at once)",
                 partition["interaction"], _pct(partition["interaction_share"])],
                ["total (under the exporter convention)",
                 partition["detector_residual_values_exporter"], "100.0%"],
                ["outside-note convention (a separate component)",
                 partition["convention"], _pct(partition["convention_share_of_hold"])],
            ],
        ),
        "",
        f"The exact composition explains **{s['b10_values']}** register values under the exporter "
        "convention - that is, everything. Pitch, generator, distortion, channel and AUDCTL "
        "contribute zero once the spans are right, and three of those zeros are properties of the "
        "pipeline that are stated rather than claimed.\n",
        "**Is the historical residual different enough to justify a new performance-layer "
        "hypothesis?**\n",
        f"**{falsification['verdict']}** - with a share ratio of "
        f"{falsification['share_ratio_historical_over_control']} and an AUDF-share delta of "
        f"{falsification['audf_share_delta']} under the exporter pairing. The consequence is "
        f"**{falsification['consequence']}**.\n",
        f"**But the difference is not robust: {falsification['difference_robust']}.** "
        "The residual's share of the stream is inside the ratio band, and the AUDF split is inside "
        "the delta band under one convention pairing and outside it under the other. The two corpora "
        "also differ in instrument mix. A difference that depends on which convention is applied, "
        "and that a corpus-composition difference would also produce, is not evidence about "
        "performance - it is a specification for the next controlled experiment.\n",
        (
            "**Do not return to the performance layer.** The historical residual's shape is "
            "consistent with the detector errors measured here, so the parsimonious reading is that "
            "the same causes are at work and Stage 21's negative result stands. A difference would "
            "still not have been proof: it would have been a reason to design a new controlled "
            "experiment under the same ground-truth discipline this stage applied to the detector.\n"
            if consistent else
            "**Do not return to the performance layer yet.** A difference was found, but it is not "
            "robust to the convention choice and a corpus-composition difference would produce it "
            "too, so it is a reason to design a new controlled experiment - not a result. That "
            "experiment would need a historical set matched to the control corpus on instrument mix "
            "and percussion share, and it would have to survive the same ground-truth discipline this "
            "stage applied to the detector.\n"
        ),
        "### What is now known that was not before\n",
        "1. The Stage 15 detector's residual on known-truth data is **not** primarily a pitch, "
        "generator, distortion or channel error. It is a **segmentation** error, and the only "
        "value-level error is a **representation** limit.\n",
        "2. The detector **never invents a note**: false spans are zero across the corpus, and by the "
        "overlap relation so are whole missed notes. Its error is one of **merging and boundary**: a "
        "merged span absorbs several notes and reports the first one's pitch, generator and shape for "
        "all of them.\n",
        "3. Stage 17's generator-detection concern **does not generalise**: generator classification "
        "at a span's onset is essentially perfect, and the transition miss rate is a consequence of "
        "merged spans rather than of a misreading generator.\n",
        "4. Three of the brief's taxonomy families are **empty by construction** in this pipeline, "
        "and each says why.\n",
        "5. Any future claim about a performance layer in this project must first account for a "
        f"segmentation error of {_pct(partition['note_set_share'])} of the detector's residual and a "
        "level-contour reduction of the rest.\n",
        "",
        "**Stage 22 stops here.** No music was generated, no player was modified, no instrument bank "
        "was created, no listening test was run, and the production detector is unchanged.\n",
    ]

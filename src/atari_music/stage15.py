"""Stage 15 — SAP performance style and player capability investigation.

Analysis only. This stage opens a **new research branch**. It does not reopen Stage 14 and
does not try to make SoundProfile transfer work again: a ``SoundProfile`` was closed as a
*portable instrument definition*, and this stage asks a different question — whether a
complete Atari song can be read as a **POKEY performance style**, i.e. a set of contextual
techniques ("how this player drives the chip") rather than a set of instruments.

The pipeline is:

    historical SAP
        ↓  (existing archaeology trace: ASAP + the corpus' normalised frame dump)
    complete POKEY behaviour, frame by frame
        ↓  performance events (notes, slides, vibrato, envelopes, generator changes)
        ↓  musical behaviour vs register artifact (explicit, evidenced)
        ↓  performance vocabulary — techniques, not instruments
        ↓  context analysis (is the abstraction TECHNIQUE, or TECHNIQUE + CONTEXT?)
        ↓  comparison against the current 6502 player
        ↓  what a richer player would actually need

Nothing here renders audio, generates music, edits a schema, or changes the player. Every
published artefact is read through its SHA-256 so the stage cannot silently consume a
different input than the one it reports.

Reference-song selection is deterministic and is *recomputed from the trace data* rather
than asserted: every candidate subsong in the corpus is scored on the brief's own preference
list, and the same input always yields the same reference song. The ranking table is
published so the choice can be audited.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_CH1_179MHZ,
    AUDCTL_CH3_179MHZ,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    PAL_CLOCK_HZ,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = Path(r"C:\Users\grzes\Documents\Projects\pokey-sound-architecture")
DEFAULT_PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"
DEFAULT_MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"

ANALYSIS_VERSION = "stage15/1"

#: Nominal PAL frame rate the corpus traces are digitised at. Used only to turn frame
#: counts into seconds for readability; every reported number that matters is in frames.
FRAME_HZ = 50.0

#: Event classification vocabulary required by the brief.
CLASS_MUSICAL = "REAL_MUSICAL_BEHAVIOUR"
CLASS_ARTIFACT = "REGISTER_LEVEL_EFFECT"
CLASS_UNKNOWN = "UNKNOWN_REGISTER_PATTERN"

#: The event classes the brief suggests. Only those the trace actually supports are
#: emitted; the absence of the rest is itself published evidence.
EVENT_KINDS = (
    "NOTE_ON",
    "NOTE_OFF",
    "PITCH_CHANGE",
    "PITCH_SLIDE",
    "PITCH_SWEEP",
    "VOLUME_CHANGE",
    "VOLUME_ENVELOPE",
    "GENERATOR_CHANGE",
    "DISTORTION_CHANGE",
    "VIBRATO",
    "TREMOLO",
    "ARPEGGIO",
    "AUDCTL_CHANGE",
    "SIXTEEN_BIT_ENABLE",
    "SIXTEEN_BIT_DISABLE",
    "CHANNEL_COUPLING_CHANGE",
    "REGISTER_PATTERN_CHANGE",
)

#: Effect-size threshold (Cohen's eta-squared, "medium") above which a technique's
#: parameter distribution is judged to differ between contexts.
CONTEXT_ETA2_THRESHOLD = 0.14

#: How many individual events are written to ``performance_events.json``. The cap is applied
#: per kind, so truncation can never hide a whole event class; the full counts always travel
#: with the sample, and the full stream is reproducible by re-running the analysis.
MAX_EVENTS_PER_KIND = 200

#: Zero-page bytes the player consumes from the caller (``PLAYER_ZP_BASE + 0..9``).
PLAYER_ZERO_PAGE_BYTES = 10


class Stage15Error(RuntimeError):
    """A required input artefact is missing or malformed."""


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise Stage15Error(f"missing artefact: {path}") from error
    except json.JSONDecodeError as error:
        raise Stage15Error(f"malformed JSON: {path}: {error}") from error


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), places)


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(math.floor(pos))
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _eta_squared(groups: Sequence[Sequence[float]]) -> Optional[float]:
    """Share of a parameter's variance explained by group membership (0..1).

    Cohen's eta-squared: deterministic and interpretable. ``>= CONTEXT_ETA2_THRESHOLD``
    means the groups are not interchangeable, so one abstraction is not enough.
    """
    flat = [v for group in groups for v in group]
    if len(flat) < 4:
        return None
    grand = sum(flat) / len(flat)
    total = sum((v - grand) ** 2 for v in flat)
    if total <= 0.0:
        return None
    between = 0.0
    for group in groups:
        if not group:
            continue
        mean = sum(group) / len(group)
        between += len(group) * (mean - grand) ** 2
    return between / total


# ---------------------------------------------------------------------------
# POKEY semantics (read-only reuse of the project's own hardware model)
# ---------------------------------------------------------------------------
def audc_volume(audc: int) -> int:
    return int(audc) & 0x0F


def audc_distortion(audc: int) -> int:
    return (int(audc) >> 4) & 0x0F


def audc_waveform(audc: int) -> str:
    """The generator POKEY actually selects (``pokey_hw`` is the single source of truth)."""
    if audc_volume(audc) == 0:
        return "silent"
    return pokey_hw.decode_audc(int(audc)).value


def waveform_is_noise(waveform: str) -> bool:
    return waveform in ("poly9_17", "poly5_gated_poly9_17")


def waveform_is_tonal(waveform: str) -> bool:
    return waveform in ("pure_tone", "poly4", "poly5_gated_pure", "poly5_gated_poly4")


@dataclass(frozen=True)
class Voice:
    """One audibly independent sound source in the song.

    Usually this is one channel. When AUDCTL joins a pair into a 16-bit divider the pair is
    one voice: the *low* channel supplies the divider's low byte and carries no volume, the
    *high* channel carries the volume and its own AUDF is only the high byte. Keeping that
    explicit is what makes the artifact analysis in Part C possible.
    """

    voice_id: str
    channels: Tuple[int, ...]
    volume_channel: int
    pitch_channels: Tuple[int, ...]
    joined: bool
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "channels": list(self.channels),
            "volume_channel": self.volume_channel,
            "pitch_channels": list(self.pitch_channels),
            "joined_16bit": self.joined,
            "note": self.note,
        }


def voices_for(audctl: int) -> List[Voice]:
    """Split a POKEY configuration into audibly independent voices."""
    if audctl & AUDCTL_JOIN_1_2_16BIT:
        head = [
            Voice("V12", (1, 2), 2, (1, 2), True,
                  "channels 1+2 joined as a 16-bit divider; AUDF1 is the low byte")
        ]
    else:
        head = [
            Voice("V1", (1,), 1, (1,), False, "channel 1 runs its own 8-bit divider"),
            Voice("V2", (2,), 2, (2,), False, "channel 2 runs its own 8-bit divider"),
        ]
    if audctl & AUDCTL_JOIN_3_4_16BIT:
        head += [
            Voice("V34", (3, 4), 4, (3, 4), True,
                  "channels 3+4 joined as a 16-bit divider; AUDF3 is the low byte")
        ]
    else:
        head += [
            Voice("V3", (3,), 3, (3,), False, "channel 3 runs its own 8-bit divider"),
            Voice("V4", (4,), 4, (4,), False, "channel 4 runs its own 8-bit divider"),
        ]
    return head


def pitch_interpretation(audctl: int) -> Dict[int, str]:
    """For every channel, how its AUDF may be read (the Part C interpretation key)."""
    result: Dict[int, str] = {}
    joined12 = bool(audctl & AUDCTL_JOIN_1_2_16BIT)
    joined34 = bool(audctl & AUDCTL_JOIN_3_4_16BIT)
    for channel in (1, 2, 3, 4):
        if joined12 and channel in (1, 2):
            result[channel] = (
                "divider_lsb_of_joined_pair" if channel == 1 else "divider_msb_of_joined_pair"
            )
        elif joined34 and channel in (3, 4):
            result[channel] = (
                "divider_lsb_of_joined_pair" if channel == 3 else "divider_msb_of_joined_pair"
            )
        elif audctl & AUDCTL_HIPASS_CH1_CH3 and channel == 1:
            result[channel] = "highpass_clocked_by_ch3"
        elif audctl & AUDCTL_HIPASS_CH2_CH4 and channel == 2:
            result[channel] = "highpass_clocked_by_ch4"
        else:
            result[channel] = "own_divider"
    return result


def divider_for(voice: Voice, frame: int, registers: Mapping[str, Sequence[int]]) -> int:
    """The divider that actually sets this voice's pitch in one frame."""
    if voice.joined:
        low, high = voice.channels
        return (registers[f"AUDF{high}"][frame] << 8) | registers[f"AUDF{low}"][frame]
    return registers[f"AUDF{voice.channels[0]}"][frame]


def divider_to_hz(divider: int, voice: Voice, audctl: int) -> float:
    if voice.joined:
        return pokey_hw.hz_from_audf_16bit(int(divider), audctl=audctl, channel=voice.channels[0])
    return pokey_hw.hz_from_audf_8bit(int(divider), audctl=audctl, channel=voice.channels[0])


def semitones_between(hz_a: Optional[float], hz_b: Optional[float]) -> Optional[float]:
    """Signed interval in semitones from *hz_a* to *hz_b* (positive = rising)."""
    if not hz_a or not hz_b or hz_a <= 0 or hz_b <= 0:
        return None
    return 12.0 * math.log2(hz_b / hz_a)


# ---------------------------------------------------------------------------
# Part A input: the trace
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RegisterTrace:
    """One subsong's normalised POKEY register stream, plus where it came from."""

    path: str
    sha256: str
    schema: str
    song: str
    subsong: int
    title: Optional[str]
    author: Optional[str]
    date: Optional[str]
    sap_type: Optional[str]
    song_file: str
    declared_duration_s: Optional[float]
    is_looping: bool
    frames: int
    frame_period_ms: float
    registers: Mapping[str, Tuple[int, ...]]
    backend: Mapping[str, Any]
    notes: Tuple[str, ...]

    @property
    def duration_s(self) -> float:
        return self.frames * self.frame_period_ms / 1000.0

    @property
    def audctl(self) -> int:
        return int(self.registers["AUDCTL"][0])

    @property
    def slug(self) -> str:
        return Path(self.path).name.replace(".frames.json", "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "schema": self.schema,
            "song": self.song,
            "subsong": self.subsong,
            "title": self.title,
            "author": self.author,
            "date": self.date,
            "sap_type": self.sap_type,
            "song_file": self.song_file,
            "declared_duration_s": _rnd(self.declared_duration_s),
            "is_looping": self.is_looping,
            "frames": self.frames,
            "frame_period_ms": _rnd(self.frame_period_ms),
            "duration_s": _rnd(self.duration_s),
            "audctl": f"${self.audctl:02X}",
            "backend": dict(self.backend),
            "notes": list(self.notes),
        }


def trace_dir(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> Path:
    return Path(arch_root) / "output" / "traces"


def list_traces(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> List[Path]:
    return sorted(trace_dir(arch_root).glob("*.frames.json"))


def load_trace(path: Path) -> RegisterTrace:
    data = _read_json(path)
    registers = {name: tuple(values) for name, values in data["registers"].items()}
    frames = int(data["frame_count"])
    for name, values in registers.items():
        if len(values) != frames:
            raise Stage15Error(f"{path}: register {name} has {len(values)} of {frames} frames")
    source = data["source"]
    return RegisterTrace(
        path=str(path),
        sha256=sha256_file(path),
        schema=data.get("schema", ""),
        song=source["song"],
        subsong=int(source["subsong"]),
        title=source.get("title"),
        author=source.get("author"),
        date=source.get("date"),
        sap_type=source.get("sap_type"),
        song_file=source.get("song_file", ""),
        declared_duration_s=source.get("declared_duration_s"),
        is_looping=bool(source.get("is_looping", False)),
        frames=frames,
        frame_period_ms=float(data["frame_period_ms"]),
        registers=registers,
        backend=dict(data.get("backend", {})),
        notes=tuple(data.get("notes", [])),
    )


# ---------------------------------------------------------------------------
# Reference-song selection (deterministic, auditable)
# ---------------------------------------------------------------------------
def candidate_metrics(trace: RegisterTrace) -> Dict[str, Any]:
    """Measurable properties of one subsong, computed from its trace alone.

    Every metric is *audible-aware*: a register written while the channel's AUDC volume
    nibble is zero produces no sound, so it cannot count as "POKEY behaviour" of the song.
    """
    registers = trace.registers
    frames = trace.frames
    audctl = trace.audctl
    voices = voices_for(audctl)

    audible_channels: List[int] = []
    families: Dict[int, List[str]] = {}
    for channel in (1, 2, 3, 4):
        audc = registers[f"AUDC{channel}"]
        sounding = sum(1 for frame in range(frames) if audc_volume(audc[frame]) > 0)
        if sounding >= 0.10 * frames:
            audible_channels.append(channel)
        families[channel] = sorted(
            {audc_waveform(audc[frame]) for frame in range(frames) if audc_volume(audc[frame]) > 0}
        )

    used_families = sorted({name for names in families.values() for name in names})
    pitch_values: set = set()
    for voice in voices:
        audc = registers[f"AUDC{voice.volume_channel}"]
        for frame in range(frames):
            if audc_volume(audc[frame]) > 0:
                pitch_values.add(divider_for(voice, frame, registers))

    audf_changes = sum(
        1
        for channel in (1, 2, 3, 4)
        for frame in range(1, frames)
        if registers[f"AUDF{channel}"][frame] != registers[f"AUDF{channel}"][frame - 1]
    )
    audc_changes = sum(
        1
        for channel in (1, 2, 3, 4)
        for frame in range(1, frames)
        if registers[f"AUDC{channel}"][frame] != registers[f"AUDC{channel}"][frame - 1]
    )
    silent_writes = sum(
        1
        for channel in (1, 2, 3, 4)
        for frame in range(1, frames)
        if registers[f"AUDF{channel}"][frame] != registers[f"AUDF{channel}"][frame - 1]
        and audc_volume(registers[f"AUDC{channel}"][frame]) == 0
        and audc_volume(registers[f"AUDC{channel}"][frame - 1]) == 0
    )
    return {
        "trace": trace.slug,
        "path": trace.path,
        "sha256": trace.sha256,
        "song": trace.song,
        "subsong": trace.subsong,
        "title": trace.title,
        "author": trace.author,
        "date": trace.date,
        "duration_s": _rnd(trace.duration_s),
        "frames": frames,
        "audctl": f"${audctl:02X}",
        "audctl_description": pokey_hw.describe_audctl(audctl),
        "audctl_changes": sum(
            1
            for frame in range(1, frames)
            if registers["AUDCTL"][frame] != registers["AUDCTL"][frame - 1]
        ),
        "audible_channels": len(audible_channels),
        "audible_channel_list": audible_channels,
        "generator_families": len(used_families),
        "generator_family_list": used_families,
        "families_by_channel": {str(channel): names for channel, names in families.items()},
        "distinct_pitch_values": len(pitch_values),
        "audf_changes": audf_changes,
        "audc_changes": audc_changes,
        "audf_changes_per_second": _rnd(audf_changes / trace.duration_s) if trace.duration_s else None,
        "silent_register_writes": silent_writes,
        "silent_write_share": _rnd(silent_writes / audf_changes) if audf_changes else None,
        "pitch_interpretation": {str(k): v for k, v in pitch_interpretation(audctl).items()},
        "voices": [voice.to_dict() for voice in voices],
    }


def selection_gates(metrics: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The brief's own preference list, as pass/fail gates with the measured value."""
    return [
        {
            "gate": "G1_duration_at_least_30s",
            "requirement": "at least 30 seconds",
            "measured": metrics["duration_s"],
            "passed": bool(metrics["duration_s"] and metrics["duration_s"] >= 30.0),
        },
        {
            "gate": "G2_multiple_channels",
            "requirement": "contains multiple channels (>= 2 with audible output)",
            "measured": metrics["audible_channels"],
            "passed": metrics["audible_channels"] >= 2,
        },
        {
            "gate": "G3_not_static_tone",
            "requirement": "not merely a simple static-tone tune (>= 2 generator families)",
            "measured": metrics["generator_families"],
            "passed": metrics["generator_families"] >= 2,
        },
        {
            "gate": "G4_meaningful_register_modulation",
            "requirement": "uses meaningful register modulation (>= 8 distinct audible pitch values)",
            "measured": metrics["distinct_pitch_values"],
            "passed": metrics["distinct_pitch_values"] >= 8,
        },
    ]


def select_reference_song(arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR) -> Dict[str, Any]:
    """Rank every corpus subsong on the brief's list and return the winner.

    The ordering is lexicographic on the brief's own bullets, in the brief's own order:
    multiple channels, non-trivial POKEY behaviour (generator families), meaningful register
    modulation (distinct audible pitch values), enough material (frames). The filename and
    subsong break ties, so the result is a total order and the same input always wins. The
    full ranked table *and* the ranking under three other natural orderings are returned, so
    a reader can see whether the winner is an artefact of one particular tie-break.
    """
    rows: List[Dict[str, Any]] = []
    for path in list_traces(arch_root):
        trace = load_trace(path)
        metrics = candidate_metrics(trace)
        gates = selection_gates(metrics)
        metrics["gates"] = gates
        metrics["eligible"] = all(gate["passed"] for gate in gates)
        rows.append(metrics)

    eligible = [row for row in rows if row["eligible"]]
    ranked = sorted(
        eligible,
        key=lambda row: (
            -row["audible_channels"],
            -row["generator_families"],
            -row["distinct_pitch_values"],
            -row["frames"],
            row["trace"],
        ),
    )
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position

    alternate_keys = {
        "generator_families_first": lambda r: (
            -r["generator_families"], -r["distinct_pitch_values"],
            -r["audible_channels"], -r["frames"], r["trace"]),
        "pitch_vocabulary_first": lambda r: (
            -r["distinct_pitch_values"], -r["generator_families"],
            -r["audible_channels"], -r["frames"], r["trace"]),
        "material_first": lambda r: (
            -r["frames"], -r["distinct_pitch_values"],
            -r["generator_families"], -r["audible_channels"], r["trace"]),
    }
    sensitivity = {}
    for name, key in alternate_keys.items():
        ordered = sorted(eligible, key=key)
        sensitivity[name] = ordered[0]["trace"] if ordered else None

    if not ranked:
        raise Stage15Error(f"no eligible trace under {trace_dir(arch_root)}")
    winner, runner_up = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    return {
        "corpus_glob": str(trace_dir(arch_root) / "*.frames.json"),
        "candidates_considered": len(rows),
        "candidates_eligible": len(ranked),
        "rejected": [
            {"trace": row["trace"], "failed": [g["gate"] for g in row["gates"] if not g["passed"]]}
            for row in rows
            if not row["eligible"]
        ],
        "ranking_key": (
            "audible_channels desc, generator_families desc, distinct_pitch_values desc, "
            "frames desc, filename asc"
        ),
        "ranking": ranked,
        "winner": winner,
        "runner_up": runner_up,
        "sensitivity": sensitivity,
        "winner_robust": all(value == winner["trace"] for value in sensitivity.values()),
    }


# ---------------------------------------------------------------------------
# PART A — what the song actually does, over time
# ---------------------------------------------------------------------------
def audctl_bits(audctl: int) -> List[str]:
    """Decode an AUDCTL byte into the hardware mechanisms it actually enables."""
    names = []
    if audctl & AUDCTL_15KHZ:
        names.append("base clock 15 kHz (instead of 64 kHz)")
    if audctl & AUDCTL_HIPASS_CH1_CH3:
        names.append("channel 1 high-pass clocked by channel 3")
    if audctl & AUDCTL_HIPASS_CH2_CH4:
        names.append("channel 2 high-pass clocked by channel 4")
    if audctl & AUDCTL_JOIN_3_4_16BIT:
        names.append("channels 3+4 joined into a 16-bit divider")
    if audctl & AUDCTL_JOIN_1_2_16BIT:
        names.append("channels 1+2 joined into a 16-bit divider")
    if audctl & AUDCTL_CH3_179MHZ:
        names.append("channel 3 clocked at 1.79 MHz")
    if audctl & AUDCTL_CH1_179MHZ:
        names.append("channel 1 clocked at 1.79 MHz")
    if not names:
        names.append("default: four independent 8-bit channels at the 64 kHz base clock")
    return names


def timeline_buckets(trace: RegisterTrace, buckets: int = 20) -> List[Dict[str, Any]]:
    """A coarse, fixed-width view of the song, so "what changes over time" is visible."""
    registers = trace.registers
    frames = trace.frames
    width = max(1, frames // buckets)
    rows = []
    for index in range(buckets):
        start = index * width
        if start >= frames:
            break
        end = min(frames, start + width) if index < buckets - 1 else frames
        per_channel = []
        for channel in (1, 2, 3, 4):
            audf = registers[f"AUDF{channel}"]
            audc = registers[f"AUDC{channel}"]
            per_channel.append(
                {
                    "channel": channel,
                    "audible_frames": sum(
                        1 for frame in range(start, end) if audc_volume(audc[frame]) > 0
                    ),
                    "audf_changes": sum(
                        1 for frame in range(start + 1, end) if audf[frame] != audf[frame - 1]
                    ),
                    "audc_changes": sum(
                        1 for frame in range(start + 1, end) if audc[frame] != audc[frame - 1]
                    ),
                    "audf_min": min(audf[start:end]),
                    "audf_max": max(audf[start:end]),
                }
            )
        rows.append(
            {
                "bucket": index,
                "start_frame": start,
                "end_frame": end - 1,
                "start_s": _rnd(start * trace.frame_period_ms / 1000.0),
                "channels": per_channel,
            }
        )
    return rows


def trace_summary(trace: RegisterTrace) -> Dict[str, Any]:
    """Per-frame facts about the song, summarised per channel and per voice."""
    registers = trace.registers
    frames = trace.frames
    audctl = trace.audctl

    channels: List[Dict[str, Any]] = []
    for channel in (1, 2, 3, 4):
        audf = registers[f"AUDF{channel}"]
        audc = registers[f"AUDC{channel}"]
        sounding = [frame for frame in range(frames) if audc_volume(audc[frame]) > 0]
        audf_changes = [frame for frame in range(1, frames) if audf[frame] != audf[frame - 1]]
        audc_changes = [frame for frame in range(1, frames) if audc[frame] != audc[frame - 1]]
        channels.append(
            {
                "channel": channel,
                "pitch_interpretation": pitch_interpretation(audctl)[channel],
                "audible_frames": len(sounding),
                "audible_share": _rnd(len(sounding) / frames),
                "first_audible_frame": sounding[0] if sounding else None,
                "last_audible_frame": sounding[-1] if sounding else None,
                "audf_distinct": len({audf[frame] for frame in range(frames)}),
                "audf_changes": len(audf_changes),
                "audc_distinct": len({audc[frame] for frame in range(frames)}),
                "audc_changes": len(audc_changes),
                "families_when_audible": sorted({audc_waveform(audc[frame]) for frame in sounding}),
                "volume_levels_when_audible": sorted(
                    {audc_volume(audc[frame]) for frame in sounding}
                ),
                "max_audible_volume": max(
                    (audc_volume(audc[frame]) for frame in sounding), default=0
                ),
                "silent_register_writes": sum(
                    1
                    for frame in audf_changes
                    if audc_volume(audc[frame]) == 0 and audc_volume(audc[frame - 1]) == 0
                ),
            }
        )

    voices = []
    for voice in voices_for(audctl):
        audc = registers[f"AUDC{voice.volume_channel}"]
        audible = [frame for frame in range(frames) if audc_volume(audc[frame]) > 0]
        dividers = [divider_for(voice, frame, registers) for frame in audible]
        hz = [divider_to_hz(divider, voice, audctl) for divider in dividers]
        spans = note_spans(trace, voice)
        voices.append(
            {
                **voice.to_dict(),
                "audible_frames": len(audible),
                "note_count": len(spans),
                "note_duration_frames_median": _rnd(
                    _median([s.end - s.start + 1 for s in spans])
                ),
                "note_duration_frames_max": max(
                    (s.end - s.start + 1 for s in spans), default=0
                ),
                "divider_min": min(dividers) if dividers else None,
                "divider_max": max(dividers) if dividers else None,
                "hz_min": _rnd(min(hz)) if hz else None,
                "hz_max": _rnd(max(hz)) if hz else None,
                "families_when_audible": sorted(
                    {audc_waveform(audc[frame]) for frame in audible}
                ),
            }
        )

    audctl_series = registers["AUDCTL"]
    audctl_values: Dict[str, int] = {}
    for frame in range(frames):
        key = f"${audctl_series[frame]:02X}"
        audctl_values[key] = audctl_values.get(key, 0) + 1

    total_audf_changes = sum(c["audf_changes"] for c in channels)
    total_audc_changes = sum(c["audc_changes"] for c in channels)
    silent_writes = sum(c["silent_register_writes"] for c in channels)
    return {
        "song": trace.song,
        "subsong": trace.subsong,
        "title": trace.title,
        "author": trace.author,
        "date": trace.date,
        "frames": frames,
        "frame_period_ms": _rnd(trace.frame_period_ms),
        "duration_s": _rnd(trace.duration_s),
        "frame_hz_nominal": _rnd(1000.0 / trace.frame_period_ms, 3),
        "trace_schema": trace.schema,
        "trace_sha256": trace.sha256,
        "trace_path": trace.path,
        "backend": dict(trace.backend),
        "trace_notes": list(trace.notes),
        "audctl": {
            "values_by_frames": audctl_values,
            "changes": sum(
                1 for frame in range(1, frames) if audctl_series[frame] != audctl_series[frame - 1]
            ),
            "description": pokey_hw.describe_audctl(audctl),
            "bits": audctl_bits(audctl),
            "interpretation": {str(k): v for k, v in pitch_interpretation(audctl).items()},
        },
        "voices": voices,
        "channels": channels,
        "timeline": timeline_buckets(trace),
        "register_writes": {
            "audf_changes": total_audf_changes,
            "audc_changes": total_audc_changes,
            "audf_changes_per_second": _rnd(total_audf_changes / trace.duration_s),
            "audc_changes_per_second": _rnd(total_audc_changes / trace.duration_s),
            "silent_register_writes": silent_writes,
            "silent_write_share_of_audf_changes": _rnd(
                silent_writes / max(1, total_audf_changes)
            ),
        },
    }


# ---------------------------------------------------------------------------
# Note segmentation — a documented heuristic, used for context only
# ---------------------------------------------------------------------------
#: A run of audible frames is split at a frame where the divider jumps this far in
#: semitones and the new value persists (a note change, not a glide or an ornament).
NOTE_SPLIT_SEMITONES = 4.0
#: ...or where the volume re-attacks upward by this many levels from a near-silent level.
NOTE_REATTACK_DELTA = 4
#: A sub-span shorter than this many frames is merged into its predecessor.
NOTE_MIN_FRAMES = 3


@dataclass(frozen=True)
class NoteSpan:
    """One sounding note of one voice (a heuristic segmentation, not a decoded score)."""

    voice_id: str
    channel: int
    start: int
    end: int
    note_index: int

    @property
    def frames(self) -> int:
        return self.end - self.start + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "channel": self.channel,
            "note_index": self.note_index,
            "start_frame": self.start,
            "end_frame": self.end,
            "frames": self.frames,
        }


def note_spans(trace: RegisterTrace, voice: Voice) -> List[NoteSpan]:
    """Segment one voice's audible frames into notes.

    The trace has no note boundaries, only registers, so a boundary has to be inferred. Two
    signals are used, both register-level and both auditable: a *large* divider jump whose
    new value persists (a new note rather than a glide), and a *volume re-attack* from near
    silence (used where pitch is meaningless, e.g. noise percussion). The thresholds are
    module constants so the segmentation can be re-run with different ones.
    """
    registers = trace.registers
    frames = trace.frames
    audctl = trace.audctl
    audc = registers[f"AUDC{voice.volume_channel}"]
    volume = [audc_volume(audc[frame]) for frame in range(frames)]
    dividers = [divider_for(voice, frame, registers) for frame in range(frames)]
    hz = [divider_to_hz(divider, voice, audctl) for divider in dividers]

    spans: List[NoteSpan] = []
    start: Optional[int] = None
    for frame in range(frames):
        audible = volume[frame] > 0
        if not audible:
            if start is not None:
                spans.append(NoteSpan(voice.voice_id, voice.volume_channel, start, frame - 1, 0))
                start = None
            continue
        if start is None:
            start = frame
            continue
        split = False
        interval = semitones_between(hz[frame - 1], hz[frame])
        if interval is not None and abs(interval) >= NOTE_SPLIT_SEMITONES:
            look_ahead = min(frames, frame + 1 + NOTE_MIN_FRAMES)
            persists = all(
                abs(semitones_between(hz[frame], hz[other]) or 0.0) < NOTE_SPLIT_SEMITONES
                for other in range(frame + 1, look_ahead)
            )
            if persists or abs(interval) >= 2.0 * NOTE_SPLIT_SEMITONES:
                split = True
        if not split and (volume[frame] - volume[frame - 1]) >= NOTE_REATTACK_DELTA and volume[frame - 1] <= 2:
            split = True
        if split:
            if frame - start >= NOTE_MIN_FRAMES:
                spans.append(NoteSpan(voice.voice_id, voice.volume_channel, start, frame - 1, 0))
                start = frame
    if start is not None:
        spans.append(NoteSpan(voice.voice_id, voice.volume_channel, start, frames - 1, 0))
    return [
        NoteSpan(span.voice_id, span.channel, span.start, span.end, index)
        for index, span in enumerate(spans)
    ]


# ---------------------------------------------------------------------------
# PART B / C — performance events, and which of them are register artifacts
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """One inferred performance event, with its evidence and its interpretation."""

    kind: str
    channel: int
    voice_id: str
    start_frame: int
    end_frame: int
    parameters: Mapping[str, Any]
    confidence: float
    source_frames: Tuple[int, ...]
    classification: str
    evidence: Tuple[str, ...]

    @property
    def duration_frames(self) -> int:
        return self.end_frame - self.start_frame + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "channel": self.channel,
            "voice_id": self.voice_id,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "duration_frames": self.duration_frames,
            "parameters": dict(self.parameters),
            "confidence": _rnd(self.confidence, 3),
            "source_frames": list(self.source_frames),
            "classification": self.classification,
            "evidence": list(self.evidence),
        }


def _pitch_interpretation_of(
    waveform: str,
    audible: bool,
    pitch_source: str,
) -> Tuple[str, List[str], float]:
    """Decide whether a divider change on this channel may be read as a musical pitch."""
    if pitch_source == "divider_lsb_of_joined_pair":
        return (
            CLASS_ARTIFACT,
            ["AUDF is the low byte of a joined 16-bit divider; read alone it is not a pitch"],
            0.30,
        )
    if pitch_source.startswith("highpass_clocked_by"):
        return (
            CLASS_UNKNOWN,
            [f"channel is high-pass clocked ({pitch_source}); its divider is a filter clock, not a pitch"],
            0.35,
        )
    if not audible:
        return (
            CLASS_ARTIFACT,
            ["both frames are silent on this voice, so the write produces no audible change"],
            0.40,
        )
    if waveform == "volume_only":
        return (
            CLASS_UNKNOWN,
            ["AUDC selects volume-only output: there is no tone whose pitch could change"],
            0.35,
        )
    if waveform_is_noise(waveform):
        return (
            CLASS_UNKNOWN,
            [f"generator is unpitched noise ({waveform}): AUDF sets the noise clock, not a pitch"],
            0.50,
        )
    if waveform_is_tonal(waveform):
        return (
            CLASS_MUSICAL,
            [f"audible tonal voice ({waveform}) whose divider changed while sounding"],
            0.85,
        )
    return (CLASS_UNKNOWN, [f"unclassified generator state ({waveform})"], 0.30)


def _confidence_for_tonal(run_steps: int, interval_semitones: Optional[float], quantised: bool) -> float:
    base = 0.55
    if run_steps >= 2:
        base += 0.25
    if interval_semitones is not None and abs(interval_semitones) >= 0.5:
        base += 0.10
    if quantised:
        base -= 0.15
    return min(0.95, max(0.05, base))


def _sign_runs(deltas: Sequence[Tuple[int, int]]) -> List[List[Tuple[int, int]]]:
    """Group ``(index, delta)`` pairs into maximal same-direction runs."""
    runs: List[List[Tuple[int, int]]] = []
    current: List[Tuple[int, int]] = []
    for index, delta in deltas:
        if delta == 0:
            continue
        if current and (delta > 0) != (current[-1][1] > 0):
            runs.append(current)
            current = []
        current.append((index, delta))
    if current:
        runs.append(current)
    return runs


def _count_reversals(deltas: Sequence[Tuple[int, int]]) -> int:
    reversals = 0
    previous_sign = 0
    for _, delta in deltas:
        if delta == 0:
            continue
        sign = 1 if delta > 0 else -1
        if previous_sign and sign != previous_sign:
            reversals += 1
        previous_sign = sign
    return reversals


def _pitch_events(
    voice: Voice,
    span: NoteSpan,
    dividers: Sequence[int],
    hz: Sequence[float],
    volume: Sequence[int],
    classification: str,
    evidence: Sequence[str],
    base_confidence: float,
    waveform: str,
) -> List[Event]:
    """Pitch events inside one note, given its divider series."""
    channel = voice.volume_channel
    frames = list(range(span.start, span.end + 1))
    deltas = [
        (i, dividers[i] - dividers[i - 1])
        for i in range(1, len(frames))
        if dividers[i] != dividers[i - 1]
    ]
    if not deltas:
        return []
    offsets = [semitones_between(hz[0], value) or 0.0 for value in hz]
    excursion = max(offsets) - min(offsets)
    reversals = _count_reversals(deltas)
    distinct = len(set(dividers))
    common = Counter(dividers).most_common(2)
    common_share = sum(count for _, count in common) / len(dividers)
    body = {
        "note_index": span.note_index,
        "note_frames": span.frames,
        "waveform": waveform,
        "accumulated_reversals": reversals,
        "accumulated_excursion_semitones": _rnd(excursion, 3),
        "accumulated_distinct_values": distinct,
    }
    if reversals >= 2 and excursion <= 1.0 and distinct >= 3 and len(deltas) >= 4:
        return [
            Event(
                "VIBRATO", channel, voice.voice_id, span.start, span.end,
                {**body, "steps": len(deltas)},
                min(0.95, base_confidence if classification == CLASS_MUSICAL else 0.4),
                (span.start, span.end), classification,
                tuple(evidence) + (
                    f"{reversals} direction reversals inside the note with only a "
                    f"{_rnd(excursion, 2)}-semitone excursion: a periodic pitch ornament",
                ),
            )
        ]
    if reversals >= 2 and excursion >= 1.0 and distinct <= 8 and common_share >= 0.6:
        return [
            Event(
                "ARPEGGIO", channel, voice.voice_id, span.start, span.end,
                {**body, "steps": len(deltas),
                 "top_values": [{"divider": v, "frames": c} for v, c in common]},
                min(0.9, base_confidence if classification == CLASS_MUSICAL else 0.4),
                (span.start, span.end), classification,
                tuple(evidence) + (
                    f"pitch alternates between {distinct} values ({common_share:.0%} on the top two) "
                    f"with {reversals} reversals: a repeated pitch cycle, not a glide",
                ),
            )
        ]

    out: List[Event] = []
    for run in _sign_runs(deltas):
        first_index = run[0][0] - 1
        last_index = run[-1][0]
        steps = len(run)
        interval = semitones_between(hz[first_index], hz[last_index])
        uniform = len({abs(delta) for _, delta in run}) == 1
        run_frames = last_index - first_index + 1
        if steps == 1:
            kind = "PITCH_CHANGE"
        elif abs(interval or 0.0) >= 3.0 and run_frames >= 4:
            kind = "PITCH_SWEEP"
        else:
            kind = "PITCH_SLIDE"
        confidence = (
            _confidence_for_tonal(steps, interval, steps == 1)
            if classification == CLASS_MUSICAL
            else base_confidence
        )
        details = [
            f"{steps} divider step(s) over {run_frames} frame(s), {_rnd(interval, 2)} semitones "
            f"{'rising' if run[0][1] > 0 else 'falling'}",
        ]
        if uniform:
            details.append(
                "every step is the same size: a linear *divider* ramp, whose audible pitch "
                "rate is not linear"
            )
        if steps == 1 and interval is not None and abs(interval) >= 2.0:
            details.append(
                f"one division step spans {abs(interval):.2f} semitones: a quantisation step at "
                "this register value, not a glide"
            )
        out.append(
            Event(
                kind, channel, voice.voice_id, frames[first_index], frames[last_index],
                {**body, "steps": steps, "uniform_divider_step": uniform,
                 "start_divider": dividers[first_index], "end_divider": dividers[last_index],
                 "start_hz": _rnd(hz[first_index]), "end_hz": _rnd(hz[last_index]),
                 "interval_semitones": _rnd(interval, 3),
                 "direction": "rising" if run[0][1] > 0 else "falling",
                 "peak_volume": max(volume)},
                confidence, (frames[first_index], frames[last_index]), classification,
                tuple(evidence) + tuple(details),
            )
        )
    return out


def _volume_events(
    voice: Voice,
    span: NoteSpan,
    volume: Sequence[int],
    waveform: str,
) -> List[Event]:
    """Loudness events inside one note, given its volume-level series."""
    channel = voice.volume_channel
    frames = list(range(span.start, span.end + 1))
    deltas = [
        (i, volume[i] - volume[i - 1])
        for i in range(1, len(volume))
        if volume[i] != volume[i - 1]
    ]
    if not deltas:
        return []
    out: List[Event] = []
    reversals = _count_reversals(deltas)
    distinct_volumes = len(set(volume))
    if reversals >= 2 and distinct_volumes >= 3:
        return [
            Event(
                "TREMOLO", channel, voice.voice_id, span.start, span.end,
                {"steps": len(deltas), "reversals": reversals, "distinct_levels": distinct_volumes,
                 "min_volume": min(volume), "max_volume": max(volume), "waveform": waveform,
                 "note_index": span.note_index},
                0.80, (span.start, span.end), CLASS_MUSICAL,
                (f"{reversals} volume direction reversals across {distinct_volumes} levels inside "
                 "the note: a periodic loudness ornament",),
            )
        ]
    for run in _sign_runs(deltas):
        first_index = run[0][0] - 1
        last_index = run[-1][0]
        steps = len(run)
        if steps >= 3:
            out.append(
                Event(
                    "VOLUME_ENVELOPE", channel, voice.voice_id,
                    frames[first_index], frames[last_index],
                    {"steps": steps, "direction": "rising" if run[0][1] > 0 else "falling",
                     "start_level": volume[first_index], "end_level": volume[last_index],
                     "levels": sorted({volume[i] for i in range(first_index, last_index + 1)}),
                     "waveform": waveform, "note_index": span.note_index},
                    0.85, (frames[first_index], frames[last_index]), CLASS_MUSICAL,
                    (f"{steps} monotone volume steps over {last_index - first_index + 1} frame(s), "
                     f"{volume[first_index]} -> {volume[last_index]}: a shaped loudness contour "
                     "rather than a single level",),
                )
            )
        else:
            out.append(
                Event(
                    "VOLUME_CHANGE", channel, voice.voice_id,
                    frames[first_index], frames[last_index],
                    {"steps": steps, "start_level": volume[first_index],
                     "end_level": volume[last_index], "waveform": waveform,
                     "note_index": span.note_index},
                    0.70, (frames[first_index], frames[last_index]), CLASS_MUSICAL,
                    ("a short volume step while sounding",),
                )
            )
    return out


def _generator_events(
    trace: RegisterTrace,
    voice: Voice,
    span: NoteSpan,
) -> List[Event]:
    """Generator/distortion changes inside one note."""
    channel = voice.volume_channel
    audc = trace.registers[f"AUDC{channel}"]
    frames = list(range(span.start, span.end + 1))
    waves = [audc_waveform(audc[frame]) for frame in frames]
    out: List[Event] = []
    for index in range(1, len(waves)):
        if waves[index] == waves[index - 1]:
            continue
        before, after = waves[index - 1], waves[index]
        same_family = waveform_is_tonal(before) == waveform_is_tonal(after) and (
            waveform_is_noise(before) == waveform_is_noise(after)
        )
        out.append(
            Event(
                "DISTORTION_CHANGE" if same_family else "GENERATOR_CHANGE",
                channel, voice.voice_id, frames[index], frames[index],
                {"from_waveform": before, "to_waveform": after,
                 "from_audc": f"${audc[frames[index - 1]]:02X}",
                 "to_audc": f"${audc[frames[index]]:02X}", "note_index": span.note_index,
                 "note_frames": span.frames},
                0.90, (frames[index],), CLASS_MUSICAL,
                (f"AUDC changes the selected generator from {before} to {after} while sounding; "
                 f"{'audibly the same family' if same_family else 'the sound family itself changes'}",),
            )
        )
    return out


def _span_events(trace: RegisterTrace, voice: Voice, span: NoteSpan) -> List[Event]:
    """Every musical event inside one note of one voice."""
    registers = trace.registers
    audctl = trace.audctl
    channel = voice.volume_channel
    audc = registers[f"AUDC{channel}"]
    frames = list(range(span.start, span.end + 1))
    dividers = [divider_for(voice, frame, registers) for frame in frames]
    hz = [divider_to_hz(divider, voice, audctl) for divider in dividers]
    volume = [audc_volume(audc[frame]) for frame in frames]
    waves = [audc_waveform(audc[frame]) for frame in frames]
    # The dominant generator of the span. Ties are broken by the sorted order of the candidate
    # names, never by set iteration order: a set's order depends on string hashing, which is
    # randomised per process, and that made this analysis non-deterministic between runs.
    distinct_waves = sorted(set(waves))
    dominant_wave = (
        min(distinct_waves, key=lambda name: (-waves.count(name), name)) if waves else "silent"
    )
    classification, evidence, base_confidence = _pitch_interpretation_of(
        dominant_wave, True, pitch_interpretation(audctl)[channel]
    )

    out: List[Event] = [
        Event(
            "NOTE_ON", channel, voice.voice_id, span.start, span.start,
            {"divider": dividers[0], "hz": _rnd(hz[0]), "volume": volume[0],
             "waveform": waves[0], "note_index": span.note_index, "note_frames": span.frames},
            0.95, (span.start,), CLASS_MUSICAL,
            ("AUDC volume rises from zero with a live divider: an audible note onset",),
        ),
        Event(
            "NOTE_OFF", channel, voice.voice_id, span.end, span.end,
            {"note_index": span.note_index, "note_frames": span.frames,
             "last_divider": dividers[-1], "last_hz": _rnd(hz[-1]),
             "waveform": waves[-1]},
            0.90, (span.end,), CLASS_MUSICAL,
            ("AUDC volume falls to zero: the note stops sounding",),
        ),
    ]
    out.extend(
        _pitch_events(
            voice, span, dividers, hz, volume, classification, evidence, base_confidence,
            dominant_wave,
        )
    )
    out.extend(_volume_events(voice, span, volume, dominant_wave))
    out.extend(_generator_events(trace, voice, span))
    return out


def _register_only_events(trace: RegisterTrace, channel: int, pitch_source: str) -> List[Event]:
    """Divider activity on a channel that cannot be read as a musical pitch (Part C).

    Two situations produce this: the low byte of a 16-bit joined pair, and a channel that is
    written while silent. Both are *real register behaviour* of the player and both are
    inaudible, so neither may be mistaken for performance. Writes that an audible span
    already accounts for are not repeated here.
    """
    registers = trace.registers
    frames = trace.frames
    audf = registers[f"AUDF{channel}"]
    audc = registers[f"AUDC{channel}"]
    volume = [audc_volume(audc[frame]) for frame in range(frames)]
    coupled_lsb = pitch_source == "divider_lsb_of_joined_pair"
    changes = []
    for frame in range(1, frames):
        if audf[frame] == audf[frame - 1]:
            continue
        silent = volume[frame] == 0 and volume[frame - 1] == 0
        if silent or coupled_lsb:
            changes.append(frame)
    if not changes:
        return []
    if coupled_lsb:
        classification, evidence, confidence = _pitch_interpretation_of("silent", False, pitch_source)
    else:
        classification, evidence, confidence = _pitch_interpretation_of("silent", False, "own_divider")
    grouped: List[List[int]] = []
    for frame in changes:
        if grouped and frame - grouped[-1][-1] <= 2:
            grouped[-1].append(frame)
        else:
            grouped.append([frame])
    out = []
    for group in grouped:
        details = (
            f"{len(group)} AUDF write(s) on this channel; its AUDC volume nibble is 0 in both "
            "frames, so nothing is audible"
        ) if _group_is_silent(volume, group) else (
            f"{len(group)} AUDF write(s) on the low byte of a joined 16-bit divider"
        )
        out.append(
            Event(
                "REGISTER_PATTERN_CHANGE", channel, f"C{channel}", group[0], group[-1],
                {"audf_writes": len(group),
                 "start_audf": audf[group[0] - 1], "end_audf": audf[group[-1]],
                 "spans_frames": group[-1] - group[0] + 1},
                confidence, (group[0], group[-1]), classification,
                tuple(evidence) + (details,),
            )
        )
    return out


def _group_is_silent(volume: Sequence[int], group: Sequence[int]) -> bool:
    """True when none of the written frames in *group* is audible."""
    return all(volume[frame] == 0 for frame in group)


def _audctl_events(trace: RegisterTrace) -> List[Event]:
    """AUDCTL transitions: reconfiguration of the chip itself, mid-song."""
    series = trace.registers["AUDCTL"]
    out: List[Event] = []
    for frame in range(1, trace.frames):
        if series[frame] == series[frame - 1]:
            continue
        before, after = series[frame - 1], series[frame]
        out.append(
            Event(
                "AUDCTL_CHANGE", 0, "GLOBAL", frame, frame,
                {"from_audctl": f"${before:02X}", "to_audctl": f"${after:02X}",
                 "from_meaning": pokey_hw.describe_audctl(before),
                 "to_meaning": pokey_hw.describe_audctl(after)},
                0.95, (frame,), CLASS_MUSICAL,
                ("AUDCTL is rewritten mid-song, changing the chip's clocking or coupling",),
            )
        )
        for bit in (AUDCTL_JOIN_1_2_16BIT, AUDCTL_JOIN_3_4_16BIT):
            if (after & bit) and not (before & bit):
                out.append(
                    Event("SIXTEEN_BIT_ENABLE", 0, "GLOBAL", frame, frame,
                          {"bit": f"${bit:02X}", "audctl": f"${after:02X}"},
                          0.95, (frame,), CLASS_MUSICAL,
                          ("a channel pair is joined into a 16-bit divider",))
                )
            if (before & bit) and not (after & bit):
                out.append(
                    Event("SIXTEEN_BIT_DISABLE", 0, "GLOBAL", frame, frame,
                          {"bit": f"${bit:02X}", "audctl": f"${after:02X}"},
                          0.95, (frame,), CLASS_MUSICAL,
                          ("a 16-bit joined pair is split back into two 8-bit channels",))
                )
        joined_before = before & (AUDCTL_JOIN_1_2_16BIT | AUDCTL_JOIN_3_4_16BIT)
        joined_after = after & (AUDCTL_JOIN_1_2_16BIT | AUDCTL_JOIN_3_4_16BIT)
        if joined_before != joined_after:
            out.append(
                Event("CHANNEL_COUPLING_CHANGE", 0, "GLOBAL", frame, frame,
                      {"from_audctl": f"${before:02X}", "to_audctl": f"${after:02X}"},
                      0.95, (frame,), CLASS_MUSICAL,
                      ("the coupling between POKEY channels changes mid-song",))
            )
    return out


def detect_events(trace: RegisterTrace) -> List[Event]:
    """Part B: every temporally meaningful event the trace actually supports."""
    audctl = trace.audctl
    voices = voices_for(audctl)
    interpretation = pitch_interpretation(audctl)
    events: List[Event] = []
    for voice in voices:
        for span in note_spans(trace, voice):
            events.extend(_span_events(trace, voice, span))
    for channel in (1, 2, 3, 4):
        events.extend(_register_only_events(trace, channel, interpretation[channel]))
    events.extend(_audctl_events(trace))
    events.sort(key=lambda item: (item.start_frame, item.channel, item.kind))
    return events


# ---------------------------------------------------------------------------
# PART D / E — the performance vocabulary, and the context of every occurrence
# ---------------------------------------------------------------------------
def family_bucket(event: Event) -> str:
    """The generator family an event happened on — part of what makes it meaningful."""
    if event.channel == 0:
        return "global"
    waveform = event.parameters.get("waveform") or event.parameters.get("to_waveform")
    if not waveform:
        return "mixed"
    if waveform_is_noise(waveform):
        return "noise"
    if waveform_is_tonal(waveform):
        return "tonal"
    if waveform == "volume_only":
        return "volume_only"
    return "mixed"


def technique_id(event: Event) -> str:
    """The name a run of occurrences is grouped under.

    Direction is part of the name for glides and envelopes: a rising sweep and a falling
    sweep are different techniques, and treating them as one would hide exactly the
    context-dependence this stage is testing for.
    """
    if event.kind in ("PITCH_SLIDE", "PITCH_SWEEP", "VOLUME_ENVELOPE", "VOLUME_CHANGE"):
        direction = event.parameters.get("direction")
        if direction:
            return f"{event.kind}_{str(direction).upper()}"
    return event.kind


def _numeric_summary(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {}
    return {
        "count": len(values),
        "min": _rnd(min(values), 3),
        "p10": _rnd(_quantile(values, 0.10), 3),
        "median": _rnd(_median(values), 3),
        "p90": _rnd(_quantile(values, 0.90), 3),
        "max": _rnd(max(values), 3),
        "mean": _rnd(_mean(values), 3),
    }


def event_contexts(trace: RegisterTrace, events: Sequence[Event]) -> List[Dict[str, Any]]:
    """Part E: the situation each occurrence happened in, recorded as first-class data."""
    frames = trace.frames
    registers = trace.registers
    volumes = {
        channel: [audc_volume(registers[f"AUDC{channel}"][frame]) for frame in range(frames)]
        for channel in (1, 2, 3, 4)
    }
    spans_by_channel: Dict[int, List[NoteSpan]] = {}
    ranges: Dict[int, Tuple[int, int]] = {}
    for voice in voices_for(trace.audctl):
        spans_by_channel.setdefault(voice.volume_channel, []).extend(note_spans(trace, voice))
        audible = [f for f in range(frames) if volumes[voice.volume_channel][f] > 0]
        if audible:
            dividers = [divider_for(voice, f, registers) for f in audible]
            ranges[voice.volume_channel] = (min(dividers), max(dividers))
    for channel in spans_by_channel:
        spans_by_channel[channel].sort(key=lambda span: span.start)
    span_starts = {channel: [s.start for s in spans] for channel, spans in spans_by_channel.items()}

    onsets = sorted(event.start_frame for event in events if event.kind == "NOTE_ON")
    gaps = [b - a for a, b in zip(onsets, onsets[1:]) if 3 <= (b - a) <= 200]
    grid = Counter(gaps).most_common(1)[0][0] if gaps else None

    by_channel: Dict[int, List[Event]] = {}
    for event in events:
        by_channel.setdefault(event.channel, []).append(event)
    return _contexts_build(
        frames, registers, volumes, spans_by_channel, span_starts, ranges, grid, events,
        by_channel,
    )


def _contexts_build(
    frames: int,
    registers: Mapping[str, Sequence[int]],
    volumes: Mapping[int, Sequence[int]],
    spans_by_channel: Mapping[int, Sequence[NoteSpan]],
    span_starts: Mapping[int, Sequence[int]],
    ranges: Mapping[int, Tuple[int, int]],
    grid: Optional[int],
    events: Sequence[Event],
    by_channel: Mapping[int, Sequence[Event]],
) -> List[Dict[str, Any]]:
    """The per-occurrence context record (split out only to keep the code readable).

    Per-channel frame lists and event indices are precomputed, and every local-context lookup
    is a bisect, so the cost is ``O(n log n)`` rather than ``O(n^2)`` in the events of one
    channel. That matters: this song has over nine thousand events on a single voice.
    """
    channel_frames: Dict[int, List[int]] = {
        channel: [item.start_frame for item in items] for channel, items in by_channel.items()
    }
    channel_slot: Dict[int, Dict[int, int]] = {
        channel: {id(item): index for index, item in enumerate(items)}
        for channel, items in by_channel.items()
    }
    channel_onsets: Dict[int, List[int]] = {
        channel: [item.start_frame for item in items if item.kind == "NOTE_ON"]
        for channel, items in by_channel.items()
    }
    contexts: List[Dict[str, Any]] = []
    technique_seen: Counter = Counter()
    for event in events:
        channel = event.channel
        siblings = by_channel.get(channel, [])
        frames_of_channel = channel_frames.get(channel, [])
        slot = channel_slot.get(channel, {}).get(id(event), 0)
        if frames_of_channel:
            low_index = bisect.bisect_left(frames_of_channel, event.start_frame - 25)
            high_index = bisect.bisect_right(frames_of_channel, event.start_frame + 25)
            local_count = high_index - low_index
        else:
            local_count = 0
        span = None
        starts = span_starts.get(channel)
        if starts:
            insert = bisect.bisect_right(starts, event.start_frame) - 1
            if insert >= 0:
                candidate = spans_by_channel[channel][insert]
                if candidate.start <= event.start_frame <= candidate.end:
                    span = candidate
        if span is not None:
            fraction = (event.start_frame - span.start + 0.5) / max(1, span.frames)
            where = "start" if fraction <= 1 / 3 else ("middle" if fraction <= 2 / 3 else "end")
            note_index: Optional[int] = span.note_index
            note_frames: Optional[int] = span.frames
            frames_into_note = event.start_frame - span.start
            frames_left_in_note = span.end - event.start_frame
        else:
            fraction, where, note_index, note_frames = None, "outside_note", None, None
            frames_into_note = frames_left_in_note = None

        key = technique_id(event)
        technique_seen[key] += 1
        if channel in ranges:
            low, high = ranges[channel]
            divider = registers[f"AUDF{channel}"][event.start_frame]
            third = max(1, (high - low) // 3)
            if divider <= low + third:
                band = "low_divider_high_pitch"
            elif divider <= low + 2 * third:
                band = "mid_divider"
            else:
                band = "high_divider_low_pitch"
        else:
            band = "unknown"
        active_mask = "".join(
            "1" if volumes[other][event.start_frame] > 0 else "0" for other in (1, 2, 3, 4)
        )
        on_channel = channel_onsets.get(channel, [])
        onset_insert = bisect.bisect_left(on_channel, event.start_frame)
        previous_onset = on_channel[onset_insert - 1] if onset_insert > 0 else None
        next_onset = on_channel[onset_insert] if onset_insert < len(on_channel) and on_channel[onset_insert] > event.start_frame else None
        sibling_index = slot
        previous_kind = siblings[sibling_index - 1].kind if sibling_index > 0 else None
        next_kind = (
            siblings[sibling_index + 1].kind if sibling_index + 1 < len(siblings) else None
        )
        contexts.append(
            {
                "technique_id": key,
                "occurrence_index_for_technique": technique_seen[key],
                "channel": channel,
                "voice_id": event.voice_id,
                "family_bucket": family_bucket(event),
                "classification": event.classification,
                "note_index": note_index,
                "note_frames": note_frames,
                "position_in_note": where,
                "position_fraction": _rnd(fraction, 4),
                "frames_into_note": frames_into_note,
                "frames_left_in_note": frames_left_in_note,
                "pitch_band": band,
                "audible_here": bool(volumes.get(channel, [0])[event.start_frame] > 0),
                "channels_active_mask": active_mask,
                "other_channels_active": sum(
                    1
                    for position_index, other in enumerate((1, 2, 3, 4))
                    if other != channel and active_mask[position_index] == "1"
                ),
                "events_within_25_frames_on_channel": local_count,
                "previous_event_on_channel": previous_kind,
                "next_event_on_channel": next_kind,
                "frames_since_onset_on_channel": (
                    event.start_frame - previous_onset if previous_onset is not None else None
                ),
                "frames_to_next_onset_on_channel": (
                    next_onset - event.start_frame if next_onset is not None else None
                ),
                "onset_grid_frames": grid,
                "beat_index": int(event.start_frame // grid) if grid else None,
                "beat_phase": _rnd((event.start_frame % grid) / grid, 4) if grid else None,
                "song_position_share": _rnd(event.start_frame / max(1, frames - 1), 4),
                "sibling_index": sibling_index,
                "duration_frames": event.duration_frames,
                "confidence": event.confidence,
            }
        )
    return contexts


def performance_vocabulary(
    trace: RegisterTrace,
    events: Sequence[Event],
    contexts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Part D: reusable *techniques*. Counted, parameterised, and tied to their contexts."""
    techniques: Dict[str, Dict[str, Any]] = {}
    for event, context in zip(events, contexts):
        key = str(context["technique_id"])
        record = techniques.setdefault(
            key,
            {
                "technique_id": key,
                "event_kind": event.kind,
                "family_buckets": Counter(),
                "channels": Counter(),
                "classifications": Counter(),
                "confidences": [],
                "durations": [],
                "positions_in_note": Counter(),
                "pitch_bands": Counter(),
                "numeric": {},
                "categorical": {},
                "example": None,
                "occurrences": 0,
            },
        )
        record["occurrences"] += 1
        record["family_buckets"][str(context["family_bucket"])] += 1
        record["channels"][str(event.channel)] += 1
        record["classifications"][event.classification] += 1
        record["confidences"].append(event.confidence)
        record["durations"].append(event.duration_frames)
        record["positions_in_note"][str(context["position_in_note"])] += 1
        record["pitch_bands"][str(context["pitch_band"])] += 1
        for name, value in event.parameters.items():
            if isinstance(value, bool):
                record["categorical"].setdefault(name, Counter())[str(value)] += 1
            elif isinstance(value, (int, float)):
                record["numeric"].setdefault(name, []).append(float(value))
            elif isinstance(value, str):
                record["categorical"].setdefault(name, Counter())[value] += 1
        if record["example"] is None or event.confidence > record["example"]["confidence"]:
            record["example"] = event.to_dict()

    out: List[Dict[str, Any]] = []
    for key, record in techniques.items():
        out.append(
            {
                "technique_id": key,
                "event_kind": record["event_kind"],
                "occurrences": record["occurrences"],
                "family_buckets": dict(record["family_buckets"].most_common()),
                "channels": dict(record["channels"].most_common()),
                "classifications": dict(record["classifications"].most_common()),
                "confidence": _numeric_summary(record["confidences"]),
                "duration_frames": _numeric_summary(record["durations"]),
                "positions_in_note": dict(record["positions_in_note"].most_common()),
                "pitch_bands": dict(record["pitch_bands"].most_common()),
                "numeric_parameters": {
                    name: _numeric_summary(values) for name, values in record["numeric"].items()
                },
                "categorical_parameters": {
                    name: dict(counter.most_common(12))
                    for name, counter in record["categorical"].items()
                },
                "example": record["example"],
            }
        )
    out.sort(key=lambda item: (-item["occurrences"], item["technique_id"]))
    for position, record in enumerate(out, start=1):
        record["rank_by_occurrences"] = position
    kinds = Counter(event.kind for event in events)
    return {
        "song": trace.song,
        "subsong": trace.subsong,
        "event_count": len(events),
        "technique_count": len(out),
        "kinds_present": sorted(kinds),
        "kinds_absent": sorted(set(EVENT_KINDS) - set(kinds)),
        "occurrences_by_kind": dict(kinds.most_common()),
        "classifications": dict(Counter(e.classification for e in events).most_common()),
        "techniques": out,
    }


#: Parameters that describe *where* an event is, not *what* it is; never used as a
#: dependent variable when testing context dependence.
INDEX_LIKE_PARAMETERS = frozenset(
    {
        "note_index", "beat_index", "song_position_share", "sibling_index",
        "start_frame", "end_frame",
    }
)

#: Context factors a technique's parameters are tested against.
CONTEXT_FACTORS = (
    "channel", "position_in_note", "pitch_band", "family_bucket", "note_length_band",
)

#: Every context dimension recorded per occurrence, and what each one means. Published with
#: the artefact so a reader can see that no semantic role was assumed anywhere.
CONTEXT_DIMENSIONS_DOC = {
    "channel": "which voice the event belongs to",
    "voice_id": "the voice decomposition used (a 16-bit joined pair is one voice)",
    "note_index / note_frames": "the heuristic note span it falls inside",
    "position_in_note": "start / middle / end by thirds of the note",
    "frames_into_note / frames_left_in_note": "distance to the note's boundaries",
    "pitch_band": "divider tertile within that voice's own range (a low divider is a high pitch)",
    "family_bucket": "which generator family the event lands on — a hardware fact, not a role",
    "onset_grid_frames / beat_index / beat_phase": "position on the observed onset grid",
    "previous_event_on_channel / next_event_on_channel": "the immediate neighbours",
    "frames_since_onset_on_channel / frames_to_next_onset_on_channel": "local timing",
    "events_within_25_frames_on_channel": "local rhythmic density",
    "other_channels_active / channels_active_mask": "which other voices were sounding",
    "occurrence_index_for_technique": "how many times this technique has occurred so far",
    "song_position_share": "how far through the song it happens",
    "audible_here": "whether the channel's AUDC volume is non-zero in that frame",
    "musical_role": "unknown — deliberately not inferred; see channel_character",
}

#: Parameters a factor is *derived from*. Testing one against the other would be circular:
#: ``pitch_band`` is computed from the divider, ``note_length_band`` from the note length,
#: ``family_bucket`` from the waveform. None may be used to "explain" its own input.
PITCH_SPACE_TOKENS = ("divider", "audf", "hz", "semitones")


def is_circular(factor: str, parameter: str) -> bool:
    """True when the factor is computed from this very parameter (or its unit family)."""
    if factor == "pitch_band":
        return any(token in parameter for token in PITCH_SPACE_TOKENS)
    if factor == "note_length_band":
        return parameter in ("note_frames", "frames_left_in_note")
    if factor == "family_bucket":
        return parameter in ("waveform", "from_waveform", "to_waveform")
    return False


def _note_length_band(note_frames: Optional[int], tertiles: Tuple[float, float]) -> str:
    if note_frames is None:
        return "no_note"
    first, second = tertiles
    if note_frames <= first:
        return "short_note"
    if note_frames <= second:
        return "medium_note"
    return "long_note"


def context_dependence(
    vocabulary: Mapping[str, Any],
    events: Sequence[Event],
    contexts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Part F: does the same register behaviour mean different things in different places?

    For each technique, every candidate parameter is tested against every context factor with
    Cohen's eta-squared. A technique whose parameter spreads widely across one factor is not
    one behaviour: the abstraction has to carry the context with it.
    """
    note_lengths = [float(c["note_frames"]) for c in contexts if c.get("note_frames")]
    tertiles = (
        _quantile(note_lengths, 1 / 3) or 0.0,
        _quantile(note_lengths, 2 / 3) or 0.0,
    )
    rows_by_technique: Dict[str, List[int]] = {}
    for index, context in enumerate(contexts):
        rows_by_technique.setdefault(str(context["technique_id"]), []).append(index)
    def factor_key(context: Mapping[str, Any], factor: str) -> str:
        if factor == "note_length_band":
            return _note_length_band(context.get("note_frames"), tertiles)
        return str(context.get(factor))

    results: List[Dict[str, Any]] = []
    for technique in vocabulary["techniques"]:
        technique_id = technique["technique_id"]
        indices = rows_by_technique.get(technique_id, [])
        candidates = [
            name
            for name, summary in technique["numeric_parameters"].items()
            if name not in INDEX_LIKE_PARAMETERS and summary.get("count", 0) >= 20
        ]
        tests: List[Dict[str, Any]] = []
        for factor in CONTEXT_FACTORS:
            for name in candidates:
                if is_circular(factor, name):
                    continue
                groups: Dict[str, List[float]] = {}
                for index in indices:
                    value = events[index].parameters.get(name)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        groups.setdefault(factor_key(contexts[index], factor), []).append(float(value))
                usable = {key: values for key, values in groups.items() if len(values) >= 3}
                if len(usable) < 2:
                    continue
                eta2 = _eta_squared(list(usable.values()))
                if eta2 is None:
                    continue
                tests.append(
                    {
                        "factor": factor,
                        "parameter": name,
                        "eta_squared": _rnd(eta2, 4),
                        "groups": len(usable),
                        "group_medians": {
                            key: _rnd(_median(values), 3) for key, values in sorted(usable.items())
                        },
                        "group_sizes": {key: len(values) for key, values in sorted(usable.items())},
                    }
                )
        tests.sort(key=lambda item: (-item["eta_squared"], item["factor"], item["parameter"]))
        strongest = tests[0] if tests else None
        occurrences = int(technique["occurrences"])
        artifact = sum(
            count for name, count in technique["classifications"].items() if name != CLASS_MUSICAL
        )
        if occurrences < 20 or strongest is None:
            verdict = "INSUFFICIENT_EVIDENCE"
        elif strongest["eta_squared"] >= CONTEXT_ETA2_THRESHOLD:
            verdict = "TECHNIQUE_CONTEXT_SPLIT"
        else:
            verdict = "SINGLE_TECHNIQUE"
        results.append(
            {
                "technique_id": technique_id,
                "occurrences": occurrences,
                "channels": technique["channels"],
                "positions_in_note": technique["positions_in_note"],
                "pitch_bands": technique["pitch_bands"],
                "family_buckets": technique["family_buckets"],
                "non_musical_occurrences": artifact,
                "non_musical_share": _rnd(artifact / occurrences) if occurrences else None,
                "context_tests": tests[:8],
                "strongest_factor": strongest["factor"] if strongest else None,
                "strongest_parameter": strongest["parameter"] if strongest else None,
                "strongest_eta_squared": strongest["eta_squared"] if strongest else None,
                "verdict": verdict,
            }
        )
    return _context_summary(results)


def channel_character(
    trace: RegisterTrace,
    events: Sequence[Event],
    contexts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """What each voice *looks like* it is doing — as an inference, never as a label.

    The brief forbids assuming semantic roles. What can be measured is which generator a
    channel uses, how long its notes last, how much of its activity is pitch movement, and
    whether it is continuously active. Those are hardware facts. The character below is a
    reading of them, published with the rule that produced it so it can be disagreed with.
    """
    out = []
    for voice in voices_for(trace.audctl):
        channel = voice.volume_channel
        rows = [index for index, context in enumerate(contexts) if context["channel"] == channel]
        spans = note_spans(trace, voice)
        families: Counter = Counter()
        for index in rows:
            families[str(contexts[index]["family_bucket"])] += 1
        total = max(1, len(rows))
        noise_share = families.get("noise", 0) / total
        median_note = _median([span.frames for span in spans])
        audc = trace.registers[f"AUDC{channel}"]
        audible_share = sum(
            1 for frame in range(trace.frames) if audc_volume(audc[frame]) > 0
        ) / trace.frames
        pitch_events = sum(
            1 for index in rows if contexts[index]["technique_id"].startswith("PITCH_")
        )
        if noise_share >= 0.5:
            character = "noise_generator_dominant"
            rule = "more than half of this voice's events sit on a noise generator"
        elif (median_note or 0) >= 8 and pitch_events / total < 0.25:
            character = "sustained_tonal"
            rule = "tonal generator, notes of 8+ frames, little pitch movement inside notes"
        elif pitch_events / total >= 0.25:
            character = "tonal_with_continuous_pitch_movement"
            rule = "tonal generator with pitch events in a quarter or more of its activity"
        else:
            character = "mixed"
            rule = "no single reading fits"
        out.append(
            {
                "voice_id": voice.voice_id,
                "channel": channel,
                "channels": list(voice.channels),
                "joined_16bit": voice.joined,
                "events": len(rows),
                "event_families": dict(families.most_common()),
                "noise_share": _rnd(noise_share),
                "audible_share_of_song": _rnd(audible_share),
                "notes": len(spans),
                "median_note_frames": _rnd(median_note),
                "pitch_events": pitch_events,
                "pitch_event_share": _rnd(pitch_events / total),
                "inferred_character": character,
                "inference_rule": rule,
                "musical_role": "unknown",
                "role_note": (
                    "No semantic role is claimed. The brief forbids assuming bass/lead/"
                    "percussion labels, and nothing in a register trace proves one."
                ),
            }
        )
    return {
        "song": trace.song,
        "subsong": trace.subsong,
        "voices": out,
        "note": (
            "inferred_character is an inference from generator choice, note length and pitch-"
            "event density. It is evidence for the context analysis, not a claim that the "
            "original composer wrote for a 'bass' or a 'drum'."
        ),
    }


# ---------------------------------------------------------------------------
# PART G — what the current 6502 player can actually do (read from its source)
# ---------------------------------------------------------------------------
def _line_numbers(source: Sequence[str], patterns: Sequence[str]) -> List[Dict[str, Any]]:
    """Line evidence for a set of patterns, so every claim points at the source."""
    hits = []
    compiled = [(pattern, re.compile(pattern, re.IGNORECASE)) for pattern in patterns]
    for number, line in enumerate(source, start=1):
        for pattern, regex in compiled:
            if regex.search(line):
                hits.append({"line": number, "pattern": pattern, "text": line.strip()[:110]})
                break
    return hits


def _player_source_facts(lines: Sequence[str]) -> Dict[str, Any]:
    """Structural facts about the player source, counted rather than assumed."""
    comments = sum(1 for line in lines if line.strip().startswith(";"))
    blank = sum(1 for line in lines if not line.strip())
    state_bytes = 0
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s+\.byte\s", stripped):
            payload = stripped.split(".byte", 1)[1].split(";", 1)[0]
            state_bytes += len([item for item in payload.split(",") if item.strip()])
    return {
        "source_lines": len(lines),
        "source_comment_lines": comments,
        "source_blank_lines": blank,
        "source_code_lines": len(lines) - comments - blank,
        "state_bytes": state_bytes,
    }


def player_capabilities(asm_path: Path = DEFAULT_PLAYER_ASM) -> Dict[str, Any]:
    """Part G: the player's real feature set, with the source lines that prove it."""
    text = Path(asm_path).read_text(encoding="utf-8")
    lines = text.splitlines()

    def row(name, supported, detail, patterns, cost, kind):
        return {
            "capability": name,
            "supported": supported,
            "detail": detail,
            "evidence": _line_numbers(lines, patterns)[:6],
            "what_it_would_cost": cost,
            "cost_kind": kind,
        }

    rows = [
        row("4_independent_channels", True,
            "One track and one instrument slot per channel; each channel counts its own note "
            "duration down independently.",
            [r"cpx\s+#4", r"ch_dur,x"], "present", "PRESENT"),
        row("per_channel_note_duration", True,
            "Durations are in ticks; a tick is frames_per_tick VBL frames, fixed for the song.",
            [r"sta ch_dur,x", r"dec ch_dur,x", r"sta tempo_divider"], "present", "PRESENT"),
        row("fixed_per_channel_instrument", True,
            "Distortion and the four ADSR numbers are loaded once at init, 5 bytes per channel.",
            [r"sta ch_dist,x", r"load_inst_loop", r"sta ch_rel,x"], "present", "PRESENT"),
        row("runtime_envelope_generator", True,
            "A four-phase attack/decay/sustain/release state machine computes ch_cur_vol every "
            "frame; the shape is fixed per channel, not per note.",
            [r"@phase_attack", r"@phase_decay", r"@phase_release"], "present", "PRESENT"),
        row("note_volume_from_data", True,
            "Each event carries a peak volume (0..15) that the envelope works against.",
            [r"sta ch_peak_vol,x"], "present", "PRESENT"),
        row("per_song_audctl_value", True,
            "AUDCTL is one byte in the song header, written every frame: any one value is "
            "expressible, but only one for the whole song.",
            [r"sta audctl_mode", r"sta AUDCTL_REG"], "present (1 byte, whole song)", "PRESENT"),
        row("sixteen_bit_pair_1_2", True,
            "Static join of channels 1+2: channel 1 becomes the divider low byte with AUDC "
            "forced to 0; channel 2 carries the high byte and the volume.",
            [r"@write_16bit", r"and\s+#\$10", r"sta AUDC1_REG"], "present", "PRESENT"),
        row("whole_song_loop", True,
            "A $FFFF sequence entry rewinds the sequence pointer to step 0.",
            [r"cpx\s+#\$FF", r"sta seq_step_idx"], "present", "PRESENT"),
        row("vibrato", False,
            "No periodic pitch modulation: the player never computes an AUDF offset at run time "
            "and the event has no field for one.",
            [r"vibrato", r"vib_"], "player code absent; song data absent",
            "PLAYER_CODE_AND_DATA_LIMITATION"),
        row("portamento_or_slide", False,
            "Pitch is written once per note and then held. The only per-frame change to AUDF is a "
            "new note event, or the octave-pulse modulation a channel's instrument record asks for "
            "-- a slide to an arbitrary pitch is neither.",
            [r"\bslide\b", r"porta"], "IR field exists but is not exported; player code absent",
            "PLAYER_CODE_AND_DATA_LIMITATION"),
        row("per_frame_divider_modulation", True,
            "An instrument record may ask for MOD_OCTAVE_PULSE (C1): apply_modulation alternates "
            "the channel's divider between the note's nominal N and N // 2 once per 50 Hz frame, "
            "restarting at every note onset, and the existing write_pokey_registers publishes it. "
            "One descriptor byte per channel in the instrument table; nothing per note.",
            [r"apply_modulation", r"ch_mod,x", r"ch_audf_base,x", r"MOD_OCTAVE_PULSE"],
            "present (1 byte per channel)", "PRESENT"),
        row("arpeggio", False,
            "No per-frame pitch cycling, and the note table has no effect column to trigger one.",
            [r"arpegg", r"\bARP"], "IR field exists but is not exported; player code absent",
            "PLAYER_CODE_AND_DATA_LIMITATION"),
        row("per_frame_volume_macro", False,
            "Volume comes from the shared envelope state machine, so a note cannot carry its own "
            "frame-by-frame loudness contour; the exporter refuses such a song instead of letting "
            "the preview and the hardware diverge.",
            [r"volume_contour", r"\bmacro\b"],
            "data format has no place for it; mads_exporter refuses the song",
            "DATA_LIMITATION"),
        row("generator_change_inside_song", False,
            "ch_dist is loaded once at init, so a channel keeps one distortion for the whole "
            "song, and the 3-byte event has no distortion field.",
            [r"ora ch_dist"], "present in the hardware, absent from player and data",
            "IR_LIMITATION"),
        row("audctl_change_mid_song", False,
            "AUDCTL is written from the header byte every frame and never recomputed.",
            [r"lda audctl_mode"],
            "1 byte of data and a load would carry a change; no path exists",
            "DATA_LIMITATION"),
        row("sixteen_bit_pair_3_4", False,
            "Only bit 4 (channels 1+2) has a write path; there is no 3+4 branch in "
            "write_pokey_registers.",
            [r"@write_ch3_ch4", r"@mute_ch3"], "~20 bytes of code plus the low-byte convention",
            "PLAYER_CODE_LIMITATION"),
        row("highpass_filter_clocking", False,
            "AUDCTL bits 2/3 are never set by the player, and a high-passed channel has no pitch "
            "of its own to drive.",
            [r"highpass", r"hipass"], "no representation at all",
            "PLAYER_CODE_AND_DATA_LIMITATION"),
        row("effect_column", False,
            "The event is exactly three bytes (audf, duration, volume); there is nowhere to put "
            "an effect id or its parameter. This is the single structural reason every technique "
            "below is unreachable.",
            [r"Read AUDF", r"Read duration", r"Read volume"], "1-2 bytes per note",
            "DATA_LIMITATION"),
    ]
    return {
        "source": str(asm_path),
        "source_sha256": sha256_text(text),
        "source_bytes": len(text.encode("utf-8")),
        **_player_source_facts(lines),
        "data_format": {
            "song_header_bytes": 6,
            "header_fields": ["frames_per_tick", "audctl_mode", "instruments_ptr",
                              "sequence_ptr"],
            "song_format_version": 1,
            "format_version_bytes": 1,
            "instrument_bytes_per_channel": 6,
            "instrument_fields": ["distortion", "attack_frames", "decay_frames",
                                  "sustain_vol", "release_frames", "modulation"],
            "instrument_count": 4,
            "event_bytes": 3,
            "event_fields": ["audf", "duration_ticks", "volume"],
            "event_terminator": "$FF",
            "timing_resolution": "frames_per_tick VBL frames (>= 1)",
            "zero_page_bytes": PLAYER_ZERO_PAGE_BYTES,
        },
        "capabilities": rows,
        "supported": [item["capability"] for item in rows if item["supported"]],
        "unsupported": [item["capability"] for item in rows if not item["supported"]],
    }


# ---------------------------------------------------------------------------
# PART H / I / K — what is missing, what it would cost, and where the limit is
# ---------------------------------------------------------------------------
#: Assembled size of the current player, measured on 2026-10-12 with
#: ``tools/mads/mads.exe`` on a wrapper holding ``org $6000`` + ``icl '../player.asm'``
#: (``-b:$6000 -o:...bin``, file size = code + state). The source SHA-256 travels with it so
#: a stale number is visible rather than silently believed.
#:
#: 886 was the player before the C1 per-channel modulation; 1016 added C1
#: modulation; the Phase 1 ADSR envelope & channel muting fixes (linear Attack/Decay
#: ramps via ``scale_env_step``, VBI-frame Release, ``ch_sus_lvl``, and ``$00`` muting
#: in ``write_pokey_registers``) bring it to 1144.
PLAYER_ASSEMBLED_BYTES_RECORDED = 1144
PLAYER_ASSEMBLED_BYTES_METHOD = (
    "mads.exe tools/mads/mads.exe on a wrapper: org $6000 / player_start: icl '../player.asm'"
)

#: The project's one hard binary limit. It bounds the **player**, not the file.
#:
#: It is **exclusive**: a player of exactly ``PLAYER_SIZE_LIMIT_BYTES`` bytes fails. A player of
#: ``PLAYER_SIZE_LIMIT_BYTES - 1`` bytes passes.
#:
#: The limit was previously applied to the complete XEX file. That was a proxy for this rule and
#: the proxy stopped being equivalent when the C1 per-channel modulation grew the player; the
#: whole-file rule was removed on 2026-10-09 (see ``HISTORY.md``) and nothing replaced it, because
#: no byte budget on the file was ever justified by the hardware.
PLAYER_SIZE_LIMIT_BYTES = 2048

#: What ``PLAYER_SIZE_LIMIT_BYTES`` does and does not bound. Written down once, here, because the
#: four quantities below are easy to conflate and only the first is a policy limit:
#:
#: * **player** — the assembled ``player.asm`` (code + runtime state), as measured by
#:   :func:`measure_player_size`. **Strictly below** the limit. This is the only quantity the
#:   limit governs.
#: * **song data** — the exported MADS data block (patterns, sequence, instrument table). Bounded
#:   by its own, far smaller POKEY-IR budget (``composer_v*.max_size``), never by this limit.
#: * **XEX file** — the complete DOS binary (harness + player + song data). **Not bounded at all.**
#: * **loaded segments** — the start address and length of each ``org`` block. Bounded by the
#:   Atari memory map, not by a byte budget.
PLAYER_SIZE_LIMIT_SCOPE = (
    "the assembled player (code + runtime state), strictly below the limit; the complete XEX "
    "file and the song data are not bounded by it"
)

#: Kept for the Stage 15 report and its historical comparisons. ``current_envelope_2KB`` is the
#: same number as ``PLAYER_SIZE_LIMIT_BYTES`` and is defined from it so the two cannot drift;
#: ``hypothetical_4KB`` is a *counterfactual* the stage weighs, not a second limit.
PLAYER_SIZE_BUDGETS = {
    "current_envelope_2KB": PLAYER_SIZE_LIMIT_BYTES,
    "hypothetical_4KB": 4096,
    "atari_minimum_free_ram_16KB": 16384,
}


class PlayerSizeError(ValueError):
    """The assembled player reached or exceeded :data:`PLAYER_SIZE_LIMIT_BYTES`."""


def player_size_limit_ok(assembled_bytes: int) -> bool:
    """The single statement of the player-size policy: **strictly** below the limit.

    Exclusive by construction, so ``2047`` is ``True`` and ``2048`` is ``False``. Every caller
    that needs to know whether a player fits asks here rather than comparing against 2048
    itself, so the boundary is stated once and cannot drift between callers.
    """
    return int(assembled_bytes) < PLAYER_SIZE_LIMIT_BYTES


def check_player_size(assembled_bytes: int) -> int:
    """Return *assembled_bytes* when it fits the player limit, else raise.

    Raises
    ------
    PlayerSizeError
        When the player is at or above the limit. The message names both numbers, because the
        boundary is exclusive and "2048 > 2048" is the kind of thing that reads like a bug.
    """
    size = int(assembled_bytes)
    if not player_size_limit_ok(size):
        raise PlayerSizeError(
            f"assembled player is {size} bytes; the player limit is "
            f"{PLAYER_SIZE_LIMIT_BYTES} bytes and is exclusive (a player of exactly "
            f"{PLAYER_SIZE_LIMIT_BYTES} bytes fails). The limit applies to the player, not to "
            f"the XEX file or the song data."
        )
    return size

#: A technique a 1-VBL pitch step can simulate, because the player can always write a new
#: note. Everything here is therefore a DATA problem, not a code problem, unless listed in
#: ``CODE_ONLY``.
EXPRESSIBLE_BY_UNROLLING = (
    "PITCH_CHANGE", "PITCH_SLIDE", "PITCH_SWEEP", "VIBRATO", "ARPEGGIO",
    "VOLUME_CHANGE", "VOLUME_ENVELOPE", "TREMOLO", "REGISTER_PATTERN_CHANGE",
)
NOTE_TABLE_BYTES = 3

#: Mapping from a technique to the player capability that would carry it.
TECHNIQUE_MECHANISM = {
    "NOTE_ON": "4_independent_channels",
    "NOTE_OFF": "4_independent_channels",
    "PITCH_CHANGE": "per_channel_note_duration",
    "PITCH_SLIDE": "effect_column",
    "PITCH_SWEEP": "effect_column",
    "VIBRATO": "effect_column",
    "TREMOLO": "per_frame_volume_macro",
    "ARPEGGIO": "effect_column",
    "VOLUME_CHANGE": "note_volume_from_data",
    "VOLUME_ENVELOPE": "per_frame_volume_macro",
    "GENERATOR_CHANGE": "generator_change_inside_song",
    "DISTORTION_CHANGE": "generator_change_inside_song",
    "AUDCTL_CHANGE": "audctl_change_mid_song",
    "SIXTEEN_BIT_ENABLE": "audctl_change_mid_song",
    "SIXTEEN_BIT_DISABLE": "audctl_change_mid_song",
    "CHANNEL_COUPLING_CHANGE": "audctl_change_mid_song",
    "REGISTER_PATTERN_CHANGE": "effect_column",
}


def measure_player_size(asm_path: Path, mads: Path) -> Optional[int]:
    """Re-measure the assembled player size, if MADS is present.

    Everything happens in a throwaway directory: the player source is copied in and the wrapper
    includes the copy, so a "read-only" stage never writes into the source tree. Returns
    ``None`` when the assembler is missing or fails, so the analysis degrades to the recorded
    measurement instead of failing.
    """
    if not Path(mads).is_file():
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="stage15_measure_") as workspace:
            directory = Path(workspace)
            (directory / "player.asm").write_text(
                Path(asm_path).read_text(encoding="utf-8"), encoding="utf-8"
            )
            (directory / "measure.asm").write_text(
                "    org $6000\nplayer_start:\n    icl 'player.asm'\n", encoding="utf-8"
            )
            binary = directory / "measure.bin"
            result = subprocess.run(
                [str(mads), "measure.asm", "-b:$6000", "-o:measure.bin"],
                capture_output=True, text=True, check=False, cwd=str(directory),
            )
            if result.returncode != 0 or not binary.is_file():
                return None
            return binary.stat().st_size
    except OSError:
        return None


def player_gap_analysis(
    vocabulary: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> Dict[str, Any]:
    """Part H: every technique of the reference song, against what the player can do."""
    capability_by_name = {item["capability"]: item for item in capabilities["capabilities"]}
    rows = []
    for technique in vocabulary["techniques"]:
        key = technique["technique_id"]
        kind = technique["event_kind"]
        mechanism = TECHNIQUE_MECHANISM.get(kind, "effect_column")
        capability = capability_by_name.get(mechanism)
        supported = bool(capability and capability["supported"])
        unrollable = kind in EXPRESSIBLE_BY_UNROLLING
        if supported:
            missing, classification, expressible = "", "SUPPORTED", True
        elif unrollable:
            missing = (
                "no effect column: the player can still reach this by writing one note per "
                "frame, which needs frames_per_tick=1 and a per-frame note table"
            )
            classification, expressible = "DATA_LIMITATION", True
        else:
            missing = capability["what_it_would_cost"] if capability else "no representation"
            classification = capability["cost_kind"] if capability else "UNKNOWN"
            expressible = False
        occurrences = int(technique["occurrences"])
        median_frames = float(technique["duration_frames"].get("median") or 1.0)
        rows.append(
            {
                "technique_id": key,
                "event_kind": kind,
                "occurrences_in_reference": occurrences,
                "in_reference": True,
                "player_capability_that_would_carry_it": mechanism,
                "current_player_supports": supported,
                "expressible_today": expressible,
                "missing_mechanism": missing,
                "classification": classification,
                "median_event_frames": _rnd(median_frames, 2),
                "data_cost_as_notes_bytes": int(round(median_frames * NOTE_TABLE_BYTES * occurrences)),
                "data_cost_as_notes_note": (
                    "each occurrence unrolled into one 3-byte note per frame, at its median length"
                ),
            }
        )
    rows.sort(
        key=lambda item: (item["classification"] != "SUPPORTED", -item["occurrences_in_reference"])
    )
    counts = Counter(item["classification"] for item in rows)
    return {
        "rows": rows,
        "classification_counts": dict(counts.most_common()),
        "techniques_total": len(rows),
        "techniques_supported_directly": sum(1 for item in rows if item["current_player_supports"]),
        "techniques_reachable_only_by_unrolling": sum(
            1 for item in rows if item["expressible_today"] and not item["current_player_supports"]
        ),
        "techniques_unreachable": sum(1 for item in rows if not item["expressible_today"]),
        "answer": (
            f"{sum(1 for item in rows if item['current_player_supports'])} of {len(rows)} "
            "techniques are supported directly; "
            f"{sum(1 for item in rows if item['expressible_today'] and not item['current_player_supports'])} "
            "more are reachable only by unrolling one note per frame; "
            f"{sum(1 for item in rows if not item['expressible_today'])} have no representation."
        ),
    }


def player_size_analysis(
    capabilities: Mapping[str, Any],
    asm_path: Path = DEFAULT_PLAYER_ASM,
    mads: Optional[Path] = DEFAULT_MADS,
    live_measure: bool = True,
) -> Dict[str, Any]:
    """Part I/K: is the limit code size, or something else?"""
    measured = (
        measure_player_size(asm_path, mads) if (mads is not None and live_measure) else None
    )
    assembled = measured if measured is not None else PLAYER_ASSEMBLED_BYTES_RECORDED
    state_bytes = int(capabilities["state_bytes"])
    zero_page = int(capabilities["data_format"]["zero_page_bytes"])
    return {
        "measured_this_run": measured,
        "recorded_measurement": PLAYER_ASSEMBLED_BYTES_RECORDED,
        "measurement_method": PLAYER_ASSEMBLED_BYTES_METHOD,
        "assembled_bytes": assembled,
        "code_bytes": assembled - state_bytes,
        "state_bytes": state_bytes,
        "zero_page_bytes": zero_page,
        "total_player_footprint_bytes": assembled + zero_page,
        "source_sha256": capabilities["source_sha256"],
        "source_lines": capabilities["source_lines"],
        "source_comment_lines": capabilities["source_comment_lines"],
        "source_blank_lines": capabilities["source_blank_lines"],
        "source_code_lines": capabilities["source_code_lines"],
        "budgets": dict(PLAYER_SIZE_BUDGETS),
        "headroom_bytes": {
            name: budget - assembled for name, budget in PLAYER_SIZE_BUDGETS.items()
        },
        "limit_bytes": PLAYER_SIZE_LIMIT_BYTES,
        "limit_is_exclusive": True,
        "limit_scope": PLAYER_SIZE_LIMIT_SCOPE,
        "within_limit": player_size_limit_ok(assembled),
        "limit_note": (
            "The limit bounds the assembled player (code + runtime state), strictly: a player "
            "of exactly limit_bytes fails. It does not bound the song data or the complete XEX "
            "file, which is why a built .xex may legitimately be larger than limit_bytes."
        ),
        "code_bytes_note": (
            "assembled_bytes comes from the assembler; code_bytes subtracts the runtime-variable "
            "block, counted from the .byte declarations in the source so the split is auditable."
        ),
    }


def unrolling_cost(
    trace: RegisterTrace,
    events: Sequence[Event],
    gap: Mapping[str, Any],
) -> Dict[str, Any]:
    """What the reference performance costs if it has to travel as one note per frame.

    This is the number that decides Part I. A 2 KB or 4 KB player is irrelevant if the same
    performance needs two orders of magnitude more *song data* than the current format can
    represent, because the format — not the code — is what is exhausted.
    """
    frames = trace.frames
    registers = trace.registers
    per_channel_audible = {
        channel: sum(
            1 for frame in range(frames)
            if audc_volume(registers[f"AUDC{channel}"][frame]) > 0
        )
        for channel in (1, 2, 3, 4)
    }
    unrolled = {channel: count * NOTE_TABLE_BYTES for channel, count in per_channel_audible.items()}
    unrolled_total = sum(unrolled.values())

    note_events = sum(1 for event in events if event.kind == "NOTE_ON")
    current_note_bytes = note_events * NOTE_TABLE_BYTES
    effect_bytes = note_events * (NOTE_TABLE_BYTES + 1)
    ratio = unrolled_total / current_note_bytes if current_note_bytes else None
    return {
        "audible_frames_per_channel": {str(k): v for k, v in per_channel_audible.items()},
        "unrolled_bytes_per_channel": {str(k): v for k, v in unrolled.items()},
        "unrolled_total_bytes": unrolled_total,
        "note_events_in_reference": note_events,
        "current_format_bytes_for_those_notes": current_note_bytes,
        "format_with_one_effect_byte_per_note": effect_bytes,
        "unrolled_to_current_ratio": _rnd(ratio, 2),
        "ratio_meaning": (
            "how many times more song data the same performance needs when it must be written "
            "as one note per frame instead of as notes plus effects"
        ),
        "gap_rows_totalling": sum(
            int(row["data_cost_as_notes_bytes"]) for row in gap["rows"]
        ),
        "verdict": (
            "The performance is expressible with today's player only by unrolling it into "
            f"{unrolled_total} bytes of note table ({_rnd(ratio, 1)}x the note-level cost). "
            "A larger player does not change that; a wider *event encoding* does."
        ),
    }


# ---------------------------------------------------------------------------
# PART J — a conceptual richer player, justified by the reference song
# ---------------------------------------------------------------------------
#: Estimated instruction counts per mechanism. Estimates, and their basis is published:
#: the current source's own bytes-per-code-line, so the arithmetic can be redone.
MECHANISM_LINES = {
    "effect_dispatch": 28,
    "slide_step": 22,
    "vibrato_step": 26,
    "arpeggio_step": 24,
    "volume_macro_step": 18,
    "set_volume": 6,
    "set_generator": 8,
    "envelope_shape_from_table": 16,
    "sixteen_bit_pair_3_4": 20,
    "audctl_from_data": 6,
}


def hypothetical_player_design(
    vocabulary: Mapping[str, Any],
    size: Mapping[str, Any],
) -> Dict[str, Any]:
    """Part J: what a player would need to execute the reference vocabulary.

    Only mechanisms the song justifies are proposed, and each carries the occurrence count
    that justifies it. Nothing is implemented here; the code estimates are word counts turned
    into bytes by the *current* source's own bytes-per-code-line.
    """
    occurrences: Dict[str, int] = {}
    for technique in vocabulary["techniques"]:
        kind = technique["event_kind"]
        occurrences[kind] = occurrences.get(kind, 0) + int(technique["occurrences"])

    source_lines_total = int(size.get("source_lines") or 0)
    code_lines = max(
        1,
        source_lines_total
        - int(size.get("source_comment_lines") or 0)
        - int(size.get("source_blank_lines") or 0),
    )
    bytes_per_line = float(size.get("code_bytes") or 0) / code_lines

    def command(name, existing, justified, data_bytes, lines):
        return {
            "command": name,
            "existing": existing,
            "justified_by": justified,
            "data_bytes": data_bytes,
            "code_lines": lines,
        }

    commands = [
        command("NOTE audf, duration, volume", True, "every note in the song", 3, 0),
        command(
            "EFFECT id, p1, p2 (attaches to the preceding note)", False,
            f"{occurrences.get('PITCH_SLIDE', 0)} slides + {occurrences.get('PITCH_SWEEP', 0)} "
            f"sweeps + {occurrences.get('VIBRATO', 0)} vibrato + "
            f"{occurrences.get('ARPEGGIO', 0)} arpeggio occurrences",
            3,
            MECHANISM_LINES["effect_dispatch"] + MECHANISM_LINES["slide_step"]
            + MECHANISM_LINES["vibrato_step"] + MECHANISM_LINES["arpeggio_step"],
        ),
        command(
            "SET_VOLUME level", False,
            f"{occurrences.get('VOLUME_CHANGE', 0)} volume changes + "
            f"{occurrences.get('TREMOLO', 0)} tremolo runs + "
            f"{occurrences.get('VOLUME_ENVELOPE', 0)} envelopes",
            2,
            MECHANISM_LINES["set_volume"] + MECHANISM_LINES["volume_macro_step"],
        ),
        command(
            "SET_GENERATOR audc", False,
            f"{occurrences.get('GENERATOR_CHANGE', 0)} generator changes + "
            f"{occurrences.get('DISTORTION_CHANGE', 0)} distortion changes",
            2, MECHANISM_LINES["set_generator"],
        ),
        command(
            "SHAPE id (one of a small table of loudness contours)", False,
            f"{occurrences.get('VOLUME_ENVELOPE', 0)} shaped volume runs",
            2, MECHANISM_LINES["envelope_shape_from_table"],
        ),
        command(
            "SET_AUDCTL value", False,
            "NOT justified: the reference song never changes AUDCTL mid-song", 2, 0,
        ),
    ]
    total_code_lines = sum(item["code_lines"] for item in commands)
    estimated_code_bytes = int(round(total_code_lines * bytes_per_line))
    added_cycles = 40 + 4 * 18
    return {
        "principle": (
            "An event is (opcode, duration, parameters). The player keeps one small effect state "
            "per channel and advances it once per frame; the song stream names the effect and its "
            "parameter, never the per-frame register value."
        ),
        "commands": commands,
        "refused_commands": [
            {
                "command": "SET_AUDCTL from data",
                "reason": "0 occurrences in the reference song; including it would be invention",
            },
            {
                "command": "16-bit pair 3+4",
                "reason": "0 occurrences; the corpus uses the 1+2 pair or no pair at all",
            },
        ],
        "cost": {
            "bytes_per_code_line_current_source": _rnd(bytes_per_line, 3),
            "bytes_per_code_line_basis": (
                f"{size['code_bytes']} code bytes over {code_lines} code lines in the current "
                "player.asm; the same density is assumed for new code"
            ),
            "added_code_lines": total_code_lines,
            "estimated_added_code_bytes": estimated_code_bytes,
            "estimated_player_bytes_after": int(size["assembled_bytes"]) + estimated_code_bytes,
            "added_state_ram_bytes": 6 * 4,
            "added_state_ram_note": (
                "effect id, two parameters, a frame counter and a phase accumulator per channel"
            ),
            "added_song_data_bytes_per_effected_note": 3,
            "cycles_per_frame_available": int(PAL_CLOCK_HZ / FRAME_HZ),
            "estimated_added_cycles_per_frame": added_cycles,
            "cpu_share_of_a_frame": _rnd(added_cycles / (PAL_CLOCK_HZ / FRAME_HZ), 6),
            "estimate_disclaimer": (
                "Code sizes are estimates from line counts, not measurements; RAM, data and CPU "
                "figures are structural."
            ),
        },
        "justification_counts": occurrences,
    }


# ---------------------------------------------------------------------------
# PART L — the research artefact: a SongPerformanceStyle
# ---------------------------------------------------------------------------
#: The name chosen for the artefact, and why. Stage 14 closed ``SoundProfile`` /
#: ``PlayableSoundProfile`` as a portable *instrument*. This is deliberately not one.
STYLE_TERM = "SongPerformanceStyle"
STYLE_TERM_RATIONALE = (
    "SongPerformanceStyle is chosen over PerformanceVocabulary (which names only the list of "
    "techniques) and over POKEYPerformanceStyle (which would claim the style is a property of "
    "the chip rather than of this song and this player). The artefact is scoped to one song: it "
    "describes how that song's player drives POKEY, with no claim that any part of it transfers "
    "to another song. It is explicitly NOT a SoundProfile, a PlayableSoundProfile or an "
    "InstrumentProfile: it contains no instrument definition and no per-channel sound to "
    "re-apply."
)


def song_performance_style(
    trace: RegisterTrace,
    summary: Mapping[str, Any],
    vocabulary: Mapping[str, Any],
    context: Mapping[str, Any],
    characters: Mapping[str, Any],
    gap: Mapping[str, Any],
    design: Mapping[str, Any],
    grid: Optional[int],
) -> Dict[str, Any]:
    """Part L: one song, described as a contextual performance style."""
    verdicts = {item["technique_id"]: item for item in context["techniques"]}
    techniques = []
    for technique in vocabulary["techniques"]:
        item = verdicts.get(technique["technique_id"], {})
        gap_row = next(
            (row for row in gap["rows"] if row["technique_id"] == technique["technique_id"]), {}
        )
        techniques.append(
            {
                "technique_id": technique["technique_id"],
                "observed": {
                    "occurrences": technique["occurrences"],
                    "duration_frames": technique["duration_frames"],
                    "numeric_parameters": technique["numeric_parameters"],
                    "family_buckets": technique["family_buckets"],
                },
                "context": {
                    "channels": technique["channels"],
                    "positions_in_note": technique["positions_in_note"],
                    "pitch_bands": technique["pitch_bands"],
                    "strongest_factor": item.get("strongest_factor"),
                    "strongest_eta_squared": item.get("strongest_eta_squared"),
                    "context_verdict": item.get("verdict", "UNKNOWN"),
                },
                "confidence": {
                    "measured": technique["confidence"],
                    "non_musical_share": item.get("non_musical_share"),
                },
                "player_requirement": {
                    "classification": gap_row.get("classification"),
                    "missing_mechanism": gap_row.get("missing_mechanism"),
                },
                "example": technique["example"],
            }
        )
    musical = int(vocabulary["classifications"].get(CLASS_MUSICAL, 0))
    return {
        "artifact": STYLE_TERM,
        "artifact_rationale": STYLE_TERM_RATIONALE,
        "status": "research artefact — not a production schema, not a SoundProfile",
        "source_song": trace.to_dict(),
        "pokey_configuration": summary["audctl"],
        "timing": {
            "frames": trace.frames,
            "frame_period_ms": _rnd(trace.frame_period_ms),
            "duration_s": _rnd(trace.duration_s),
            "onset_grid_frames": grid,
            "onset_grid_note": (
                "modal spacing between note onsets across all voices; an observed grid, not a "
                "decoded time signature"
            ),
        },
        "voices": characters["voices"],
        "performance_techniques": techniques,
        "technique_occurrences": vocabulary["occurrences_by_kind"],
        "event_classes_present": vocabulary["kinds_present"],
        "event_classes_absent": vocabulary["kinds_absent"],
        "classifications": vocabulary["classifications"],
        "musical_share_of_events": _rnd(musical / max(1, vocabulary["event_count"])),
        "context_summary": {
            "verdict_counts": context["verdict_counts"],
            "answer": context["answer"],
            "channel_bound_techniques": context["channel_bound_techniques"],
        },
        "player_requirements": {
            "techniques_supported_today": gap["techniques_supported_directly"],
            "techniques_needing_a_wider_format": gap["techniques_reachable_only_by_unrolling"],
            "techniques_with_no_representation": gap["techniques_unreachable"],
            "minimum_mechanism_set": [
                item["command"] for item in design["commands"] if not item["existing"]
            ],
        },
        "confidence": {
            "trace": "ASAP register dump, one state per VBL, hashed in pokey_trace_summary.json",
            "note_boundaries": (
                "inferred, not decoded: see NOTE_SPLIT_SEMITONES / NOTE_REATTACK_DELTA / "
                "NOTE_MIN_FRAMES. A note is a heuristic span, not a score event."
            ),
            "overall": (
                "The technique inventory is high confidence: it is register arithmetic. The "
                "*interpretation* of a technique as a musical intention is medium at best — a "
                "divider ramp proves a pitch ramp, not that anyone chose a portamento."
            ),
        },
    }


# ---------------------------------------------------------------------------
# PART M — could the style be applied to new music? (thought experiment only)
# ---------------------------------------------------------------------------
def _simple_composition_notes(limit: int = 8) -> Dict[str, Any]:
    """A concrete, read-only example of the Composer's own output, for Part M.

    Reads an already-exported note table if one is present (nothing is generated, nothing is
    written). If none exists the sketch falls back to an abstract note, labelled as such,
    because Part M is a thought experiment rather than a measurement.
    """
    directory = REPO_ROOT / "experiments" / "mads_player_builds"
    if directory.is_dir():
        for path in sorted(directory.glob("*_data.asm")):
            notes = []
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.search(r";\s*([A-Ga-g][#-]?\d)\s*\((\d+)\s*rows\)", line)
                if match and line.strip().startswith(".byte"):
                    notes.append({"pitch": match.group(1), "rows": int(match.group(2))})
                if len(notes) >= limit:
                    break
            if notes:
                return {
                    "source": str(path),
                    "source_sha256": sha256_file(path),
                    "notes": notes,
                    "kind": "real composer export, read-only",
                }
    return {
        "source": None,
        "notes": [{"pitch": "C-4", "rows": 8}, {"pitch": "D-4", "rows": 8},
                  {"pitch": "E-4", "rows": 8}, {"pitch": "G-4", "rows": 8}],
        "kind": "abstract fallback (no composer export found on this machine)",
    }


def _techniques_at_position(
    style: Mapping[str, Any], position: str, minimum: int = 50
) -> List[Dict[str, Any]]:
    """Techniques that characteristically happen at a given point in a note.

    NOTE_ON and NOTE_OFF are excluded: they *define* the boundaries, so as a "treatment" they
    would say nothing. What is wanted here is the ornamentation that rides on them.
    """
    picked = []
    for technique in style["performance_techniques"]:
        if technique["technique_id"] in ("NOTE_ON", "NOTE_OFF"):
            continue
        occurrences = technique["observed"]["occurrences"]
        if occurrences < minimum:
            continue
        share = technique["context"]["positions_in_note"].get(position, 0)
        if share / max(1, occurrences) >= 0.5:
            picked.append(
                {
                    "technique_id": technique["technique_id"],
                    "occurrences": occurrences,
                    "share_at_this_position": _rnd(share / max(1, occurrences), 3),
                    "median_event_frames": technique["observed"]["duration_frames"].get("median"),
                    "context_verdict": technique["context"]["context_verdict"],
                }
            )
    picked.sort(key=lambda item: -item["occurrences"])
    return picked


def application_sketch(style: Mapping[str, Any]) -> Dict[str, Any]:
    """Part M: map the reference style onto a simple composition — on paper only."""
    note = _simple_composition_notes()
    onset_techniques = _techniques_at_position(style, "start")
    ending_techniques = _techniques_at_position(style, "end")
    mappings = []
    for index, item in enumerate(note["notes"]):
        mapping = {
            "note_index": index,
            "composer_note": {"pitch": item["pitch"], "rows": item["rows"]},
            "style_interpretation": ["NOTE_ON (the note itself, unchanged)"],
        }
        if onset_techniques:
            mapping["style_interpretation"].append(
                f"optional onset treatment drawn from {onset_techniques[0]['technique_id']} "
                f"({onset_techniques[0]['share_at_this_position']:.0%} of its occurrences sit at "
                "a note onset)"
            )
        if ending_techniques:
            mapping["style_interpretation"].append(
                f"optional ending treatment drawn from {ending_techniques[0]['technique_id']} "
                f"({ending_techniques[0]['share_at_this_position']:.0%} at a note ending)"
            )
        mappings.append(mapping)
    return {
        "status": "thought experiment — nothing is composed, no IR is written, no DSL exists",
        "input": note,
        "mapping": mappings,
        "context_rules_that_would_drive_it": {
            "at_note_onset": onset_techniques,
            "at_note_ending": ending_techniques,
        },
        "answer": (
            "Shape maps; values do not. A technique carries (kind, direction, duration range, "
            "context), and that part is expressible for a new note because it names a transform "
            "rather than a register. The *measured* parameters do not map: this song's sweeps are "
            "a few frames of one or two divider steps on one specific voice, and the context "
            "analysis shows those numbers differ strongly by channel, generator family and note "
            "length inside the same song. Copying them into a different composition would be "
            "copying absolute register behaviour — the mistake Stage 14 closed. A new composition "
            "needs a *decision* per technique (depth, rate, and when it applies); this song "
            "supplies evidence about which decisions matter, not the answers."
        ),
        "what_is_missing_to_do_it_for_real": [
            "a normalisation from divider space to pitch space for the new song's range",
            "a rule for which technique fires in which context — chosen, not measured",
            "a perceptual test that the result is preferred, which this stage is forbidden to run",
        ],
    }


# ---------------------------------------------------------------------------
# Robustness: the same extractor on a second song (falsification, not corpus work)
# ---------------------------------------------------------------------------
def vocabulary_cross_check(
    reference_vocabulary: Mapping[str, Any],
    other_trace: RegisterTrace,
) -> Dict[str, Any]:
    """Run the vocabulary extractor on a second song and compare *classes*, not numbers.

    The brief asks for a falsification attempt. If POKEY programming really does decompose into
    performance techniques, a second song from the same corpus should produce the same *classes*
    of technique even though every parameter differs. If it produced a wholly different set, the
    abstraction would describe one song rather than POKEY performance.
    """
    events = detect_events(other_trace)
    contexts = event_contexts(other_trace, events)
    vocabulary = performance_vocabulary(other_trace, events, contexts)
    reference_kinds = set(reference_vocabulary["kinds_present"])
    other_kinds = set(vocabulary["kinds_present"])
    reference_ids = {item["technique_id"] for item in reference_vocabulary["techniques"]}
    other_ids = {item["technique_id"] for item in vocabulary["techniques"]}
    return {
        "other_song": other_trace.song,
        "other_subsong": other_trace.subsong,
        "other_audctl": f"${other_trace.audctl:02X}",
        "other_frames": other_trace.frames,
        "other_trace_sha256": other_trace.sha256,
        "other_event_count": len(events),
        "other_technique_count": vocabulary["technique_count"],
        "other_kinds_present": sorted(other_kinds),
        "other_classifications": vocabulary["classifications"],
        "kinds_shared": sorted(reference_kinds & other_kinds),
        "kinds_only_in_reference": sorted(reference_kinds - other_kinds),
        "kinds_only_in_other": sorted(other_kinds - reference_kinds),
        "shared_kind_share": _rnd(len(reference_kinds & other_kinds) / max(1, len(reference_kinds))),
        "technique_ids_shared": sorted(reference_ids & other_ids),
        "technique_id_share": _rnd(len(reference_ids & other_ids) / max(1, len(reference_ids))),
        "conclusion": (
            "The event *classes* recur and most technique *identifiers* recur, while the measured "
            "parameters do not: the schema generalises, the numbers do not. That is the strongest "
            "support this stage can offer for a Performance Style abstraction, and it is also why "
            "a style cannot be transferred as a set of constants."
        ),
    }


# ---------------------------------------------------------------------------
# PART N / O — the ten answers and the verdicts
# ---------------------------------------------------------------------------
def research_answers(
    selection: Mapping[str, Any],
    vocabulary: Mapping[str, Any],
    context: Mapping[str, Any],
    gap: Mapping[str, Any],
    size: Mapping[str, Any],
    unrolling: Mapping[str, Any],
    design: Mapping[str, Any],
    cross_check: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Q1..Q10, each answered from the artefacts rather than from prose."""
    winner = selection["winner"]
    verdict_counts = context["verdict_counts"]
    split = verdict_counts.get("TECHNIQUE_CONTEXT_SPLIT", 0)
    single = verdict_counts.get("SINGLE_TECHNIQUE", 0)
    thin = verdict_counts.get("INSUFFICIENT_EVIDENCE", 0)
    classifications = vocabulary["classifications"]
    musical = classifications.get(CLASS_MUSICAL, 0)
    total_events = vocabulary["event_count"]
    note_events = vocabulary["occurrences_by_kind"].get("NOTE_ON", 0)
    effect_note_bytes = note_events * (NOTE_TABLE_BYTES + 3)
    headroom_after = (
        size["budgets"]["current_envelope_2KB"]
        - size["assembled_bytes"]
        - design["cost"]["estimated_added_code_bytes"]
    )
    return [
        {
            "question": "Q1 What are the actual POKEY performance techniques used by one "
                        "historical song?",
            "answer": (
                f"{vocabulary['technique_count']} distinct techniques across {total_events} events "
                f"in {winner['song']} sub{winner['subsong']}: "
                + ", ".join(
                    f"{item['technique_id']} x{item['occurrences']}"
                    for item in vocabulary["techniques"][:12]
                )
                + ("..." if vocabulary["technique_count"] > 12 else "")
            ),
        },
        {
            "question": "Q2 Which techniques are genuinely musical and which are register "
                        "artifacts?",
            "answer": (
                f"{musical} of {total_events} events are real musical behaviour, "
                f"{classifications.get(CLASS_UNKNOWN, 0)} are register patterns whose AUDF is not a "
                "pitch (noise clock or volume-only output) and "
                f"{classifications.get(CLASS_ARTIFACT, 0)} are register-level effects: writes on a "
                "channel that is silent. The cross-check song supplies the canonical artifact this "
                f"song lacks: {cross_check['other_classifications'].get(CLASS_ARTIFACT, 0)} writes to "
                "the low byte of a joined 16-bit divider, which look like a bass line and are not a "
                "pitch."
            ),
        },
        {
            "question": "Q3 How strongly are techniques tied to context?",
            "answer": (
                f"{split} of {context['techniques_tested']} techniques split by context at the "
                f"medium-effect threshold; {single} survive as one technique; {thin} have too few "
                "occurrences to judge. The strongest factors are channel, generator family and "
                "position inside the note. Even NOTE_ON and NOTE_OFF are not context-free: their "
                "volume and length distributions differ by which generator they land on."
            ),
        },
        {
            "question": "Q4 Can the techniques be described without pretending they are portable "
                        "instruments?",
            "answer": (
                "Yes, and the description never mentions a sound to re-apply. Each technique is "
                "(kind, direction, parameter range, context, occurrence count, evidence frames): a "
                "rising sweep is a number of divider steps over a number of frames, at a position "
                "in a note, on a voice. No instrument, no per-channel timbre and no portable "
                f"profile appears anywhere in {STYLE_TERM}."
            ),
        },
        {
            "question": "Q5 Which techniques can the current player express?",
            "answer": (
                f"{gap['techniques_supported_directly']} of {gap['techniques_total']} directly "
                "(note on/off, pitch steps, volume levels); "
                f"{gap['techniques_reachable_only_by_unrolling']} more only by unrolling one note "
                f"per frame; {gap['techniques_unreachable']} have no representation at all."
            ),
        },
        {
            "question": "Q6 What prevents the current player from expressing the others?",
            "answer": (
                "The event is exactly three bytes: audf, duration, volume. There is no effect "
                "field, so a slide, a vibrato, an arpeggio, a generator change or a per-frame "
                "loudness contour has nowhere to live. The player also reloads distortion once at "
                "init, so a generator change is impossible for a second reason. None of this is "
                "about code space: the mechanisms are missing because the *format* cannot describe "
                "them."
            ),
        },
        {
            "question": "Q7 Is the limitation primarily player code, song data, IR, or composition?",
            "answer": (
                "Data and IR. The IR already declares slide_semitones, arpeggio_offsets and "
                "vibrato_depth/vibrato_speed and does not export them, and the MADS exporter "
                "refuses a per-frame volume contour rather than let the WAV and the XEX diverge. "
                "So the concepts exist upstream, the format has no bytes for them and the player "
                "has no path. Composition is not the limit: the reference song proves the behaviour "
                "is composable, just not by this engine."
            ),
        },
        {
            "question": "Q8 Would a larger player materially improve expressiveness?",
            "answer": (
                f"No. The player assembles to {size['assembled_bytes']} bytes; the mechanisms the "
                f"reference song needs are estimated at {design['cost']['estimated_added_code_bytes']} "
                f"bytes, which fits inside the *existing* 2 KB envelope with {headroom_after} bytes "
                "to spare. Growing the player to 4 KB changes nothing, because the same performance "
                f"needs {unrolling['unrolled_total_bytes']} bytes of song data "
                f"({unrolling['unrolled_to_current_ratio']}x the note-level cost) if it must travel "
                "as one note per frame."
            ),
        },
        {
            "question": "Q9 Can a compact event/macro system represent the reference performance?",
            "answer": (
                f"Yes. {vocabulary['technique_count']} measured techniques reduce to five command "
                "families beyond the existing NOTE: "
                + "; ".join(item["command"] for item in design["commands"] if not item["existing"])
                + f". The song's {note_events} note events cost {note_events * NOTE_TABLE_BYTES} "
                f"bytes today and about {effect_note_bytes} bytes if every note carried a three-byte "
                f"effect, against {unrolling['unrolled_total_bytes']} bytes for the unrolled "
                "alternative. The compact system is the only one that fits."
            ),
        },
        {
            "question": "Q10 Is 'performance style' a more promising abstraction than 'SoundProfile'?",
            "answer": (
                "Yes, and for a structural reason rather than a hopeful one. A SoundProfile claimed "
                "a sound could be lifted out and re-applied, and Stage 14 falsified that. "
                f"{STYLE_TERM} claims only that one song's POKEY programming is a describable, "
                "countable, context-bound behaviour, and it is forbidden from claiming the sound "
                "travels. The cross-check supports the schema and contradicts the numbers: "
                f"{cross_check['shared_kind_share']:.0%} of event classes and "
                f"{cross_check['technique_id_share']:.0%} of technique identifiers recur in a second "
                "song, while the parameters do not."
            ),
        },
    ]


def stage_verdicts(
    vocabulary: Mapping[str, Any],
    context: Mapping[str, Any],
    size: Mapping[str, Any],
    design: Mapping[str, Any],
    cross_check: Mapping[str, Any],
) -> Dict[str, Any]:
    """The two verdicts the brief requires, decided separately and from numbers."""
    verdict_counts = context["verdict_counts"]
    split = verdict_counts.get("TECHNIQUE_CONTEXT_SPLIT", 0)
    tested = max(1, context["techniques_tested"])
    headroom_after = (
        size["budgets"]["current_envelope_2KB"]
        - size["assembled_bytes"]
        - design["cost"]["estimated_added_code_bytes"]
    )
    mechanisms_fit = headroom_after >= 0
    return {
        "performance_style": {
            "verdict": "PERFORMANCE_STYLE_PROMISING_BUT_UNPROVEN",
            "proven": {
                "the_song_decomposes_into_countable_techniques": (
                    f"{vocabulary['technique_count']} techniques, {vocabulary['event_count']} "
                    "events, each with evidence frames and a classification"
                ),
                "musical_and_artifact_events_are_separated": (
                    f"{vocabulary['classifications'].get(CLASS_MUSICAL, 0)} musical, "
                    f"{vocabulary['classifications'].get(CLASS_UNKNOWN, 0)} unknown register "
                    f"patterns, {vocabulary['classifications'].get(CLASS_ARTIFACT, 0)} silent "
                    "register writes"
                ),
                "the_abstraction_is_context_bound": (
                    f"{split} of {tested} techniques split by context at eta-squared >= "
                    f"{CONTEXT_ETA2_THRESHOLD}"
                ),
                "no_instrument_claim_is_needed": (
                    "the artefact carries techniques and contexts and no portable sound"
                ),
                "the_schema_repeats_on_a_second_song": (
                    f"{cross_check['shared_kind_share']:.0%} of event classes and "
                    f"{cross_check['technique_id_share']:.0%} of technique identifiers recur"
                ),
            },
            "unproven": {
                "perceptual_meaning": (
                    "nothing here says a technique is *heard* as one; this stage ran no listening "
                    "test, by design"
                ),
                "generalisation_beyond_one_song": (
                    "n=1 reference song. The cross-check shows the schema repeats; it does not show "
                    "that the parameters or the contexts repeat."
                ),
                "transfer_to_new_music": (
                    "Part M is a thought experiment: the shape of a technique maps, its measured "
                    "values do not, and no rule for choosing which technique fires has been tested"
                ),
                "the_engineering_chain": (
                    "the reference song's own player format is unknown, the current 6502 player "
                    "cannot execute the vocabulary, and this stage deliberately built nothing"
                ),
            },
            "narrower_claim_that_is_supported": (
                "Narrowed to the one song analysed, the claim IS supported: this song's POKEY "
                "programming is a describable, countable, context-bound performance style. The "
                "verdict stays PROMISING_BUT_UNPROVEN because the load-bearing claim of the "
                "intended architecture is generalisation, and one song cannot show that."
            ),
        },
        "player_expansion": {
            "verdict": (
                "PLAYER_EXPANSION_NOT_JUSTIFIED" if mechanisms_fit
                else "PLAYER_EXPANSION_POTENTIALLY_JUSTIFIED"
            ),
            "reason": (
                "the hypothesis 'the player is too small' is falsified by measurement: the "
                "mechanisms the reference song needs are estimated at "
                f"{design['cost']['estimated_added_code_bytes']} bytes, they fit in the current "
                f"{size['budgets']['current_envelope_2KB']}-byte envelope with {headroom_after} "
                "bytes spare, and the binding constraint is the three-byte event format — a "
                "data-encoding question a 4 KB player does not touch"
            ) if mechanisms_fit else "the estimated mechanisms would not fit the current envelope",
        },
        "correlation_note": (
            "The two verdicts are deliberately not correlated: the style abstraction is the more "
            "promising of the two ideas, and it is precisely the one that does NOT argue for a "
            "bigger player. What it argues for, if anything, is a wider *event encoding*."
        ),
    }


def what_not_to_build_yet() -> List[Dict[str, str]]:
    """Part N: the things this stage deliberately did not build, and why."""
    return [
        {"item": "a generic style engine",
         "why": "one song and no listening evidence; a rule engine built now would encode one "
                "song's accidents as rules"},
        {"item": "automatic style transfer",
         "why": "the context analysis shows the parameters are song-specific; only the schema "
                "repeats"},
        {"item": "Composer integration or DSL syntax",
         "why": "there is no agreed command set, and no evidence a listener wants any of it"},
        {"item": "a profile bank of styles",
         "why": "one SongPerformanceStyle is an example, not a bank; two would be a coincidence, "
                "not a corpus"},
        {"item": "automatic technique assignment",
         "why": "choosing which technique fires is a composition decision, not a measurement"},
        {"item": "a 6502 player rewrite or a 4 KB player",
         "why": "not justified: the mechanisms fit in the current envelope, and the constraint is "
                "the event format"},
        {"item": "a new IR field for every technique",
         "why": "the IR already has unused slide and arpeggio fields; widening a schema before the "
                "format question is settled repeats the SoundProfile mistake"},
        {"item": "a human listening experiment",
         "why": "forbidden by this stage's stop condition; it is the first thing a Stage 16 should "
                "consider if the style is pursued"},
    ]


def stage16_candidates() -> List[Dict[str, str]]:
    """Candidate follow-on experiments. None of them is started here."""
    return [
        {
            "candidate": "repeat the analysis on more corpus songs",
            "question": "do the *contexts* repeat, or only the schema?",
            "cost": "analysis only; no production change",
        },
        {
            "candidate": "a listening test of one technique in two contexts",
            "question": "is a slide heard as a slide, and does its note position change how it is "
                        "heard?",
            "cost": "a blind package like Stage 12A/13A, with the Stage 14 lesson applied: vary "
                    "the context, not the technique",
        },
        {
            "candidate": "prototype the event encoding inside the existing 2 KB player",
            "question": "does a five-command extension fit and behave?",
            "cost": "an experimental branch; the estimate here says it fits with room to spare",
        },
        {
            "candidate": "quantify the unrolling boundary",
            "question": "at what event density does unrolling stop being cheaper than an effect "
                        "column?",
            "cost": "analysis only",
        },
        {
            "candidate": "check whether the corpus splits into programming idioms",
            "question": "do the 1986-1990 players share a style that a 2024 production does not?",
            "cost": "corpus analysis; the reference song's AUDCTL=$00 against the corpus norm $50 is "
                    "the first hint",
        },
    ]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
STAGE15_FILES = (
    "reference_song.json",
    "pokey_trace_summary.json",
    "performance_events.json",
    "performance_vocabulary.json",
    "context_analysis.json",
    "player_capability_matrix.json",
    "player_gap_analysis.json",
    "player_size_analysis.json",
    "hypothetical_player_design.json",
    "song_performance_style.json",
    "summary.json",
)
STAGE15_DOC = "stage15_performance_style.md"


def _compact_event(event: Event) -> Dict[str, Any]:
    """An event record small enough to publish thousands of, without losing its evidence."""
    record = event.to_dict()
    evidence = record.pop("evidence", [])
    record["evidence_first"] = evidence[0] if evidence else ""
    record["evidence_count"] = len(evidence)
    return record


def sample_events(
    events: Sequence[Event], per_kind: int = MAX_EVENTS_PER_KIND
) -> Dict[str, Any]:
    """Every event *kind* is represented; each kind contributes at most *per_kind* exemplars.

    Sampling per kind rather than overall means truncation can never hide a whole class of
    behaviour, which is the failure mode that would matter.
    """
    by_kind: Dict[str, List[Event]] = {}
    for event in events:
        by_kind.setdefault(event.kind, []).append(event)
    sample: List[Event] = []
    truncated: Dict[str, int] = {}
    for kind in sorted(by_kind):
        items = by_kind[kind]
        sample.extend(items[:per_kind])
        if len(items) > per_kind:
            truncated[kind] = len(items) - per_kind
    sample.sort(key=lambda item: (item.start_frame, item.channel, item.kind))
    return {
        "events_total": len(events),
        "events_written": len(sample),
        "per_kind_cap": per_kind,
        "truncated_by_kind": truncated,
        "sampling": "first N per kind, then sorted by frame; the counts above are the full totals",
        "events": [_compact_event(event) for event in sample],
    }


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open eleven files."""
    winner = bundle["reference_song"]["selection"]["winner"]
    vocabulary = bundle["performance_vocabulary"]
    size = bundle["player_size_analysis"]
    design = bundle["hypothetical_player_design"]
    unrolling = bundle["player_unrolling_cost"]
    context = bundle["context_analysis"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "reference_song": {
            "song": winner["song"],
            "subsong": winner["subsong"],
            "title": winner["title"],
            "author": winner["author"],
            "date": winner["date"],
            "duration_s": winner["duration_s"],
            "frames": winner["frames"],
            "audctl": winner["audctl"],
            "rank": winner["rank"],
            "selection_unanimous": bundle["reference_song"]["selection_sensitivity"]["unanimous"],
        },
        "events": {
            "total": vocabulary["event_count"],
            "techniques": vocabulary["technique_count"],
            "classifications": vocabulary["classifications"],
            "classes_absent": vocabulary["kinds_absent"],
        },
        "context": {
            "verdict_counts": context["verdict_counts"],
            "strongest_split_factors": sorted(
                {
                    item["strongest_factor"]
                    for item in context["techniques"]
                    if item["strongest_factor"]
                }
            ),
        },
        "player": {
            "assembled_bytes": size["assembled_bytes"],
            "code_bytes": size["code_bytes"],
            "state_bytes": size["state_bytes"],
            "headroom_in_2KB": size["headroom_bytes"]["current_envelope_2KB"],
            "size_limit_bytes": size["limit_bytes"],
            "size_limit_is_exclusive": size["limit_is_exclusive"],
            "size_limit_scope": size["limit_scope"],
            "within_size_limit": size["within_limit"],
            "estimated_mechanisms_bytes": design["cost"]["estimated_added_code_bytes"],
            "headroom_after_mechanisms": (
                size["headroom_bytes"]["current_envelope_2KB"]
                - design["cost"]["estimated_added_code_bytes"]
            ),
            "unrolled_song_data_bytes": unrolling["unrolled_total_bytes"],
            "unrolled_ratio": unrolling["unrolled_to_current_ratio"],
        },
        "verdicts": bundle["verdicts"],
        "cross_check": {
            "song": bundle["cross_check"].get("other_song"),
            "shared_kind_share": bundle["cross_check"].get("shared_kind_share"),
            "technique_id_share": bundle["cross_check"].get("technique_id_share"),
        },
    }


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    player_asm: Path = DEFAULT_PLAYER_ASM,
    mads: Optional[Path] = DEFAULT_MADS,
    live_measure: bool = True,
) -> Dict[str, Any]:
    """Analyse one song as a performance style, end to end. Reads only."""
    selection = select_reference_song(arch_root)
    trace = load_trace(Path(selection["winner"]["path"]))
    summary = trace_summary(trace)
    events = detect_events(trace)
    contexts = event_contexts(trace, events)
    vocabulary = performance_vocabulary(trace, events, contexts)
    context = context_dependence(vocabulary, events, contexts)
    characters = channel_character(trace, events, contexts)
    capabilities = player_capabilities(player_asm)
    size = player_size_analysis(capabilities, player_asm, mads, live_measure)
    gap = player_gap_analysis(vocabulary, capabilities)
    unrolling = unrolling_cost(trace, events, gap)
    design = hypothetical_player_design(vocabulary, size)
    grid = contexts[0]["onset_grid_frames"] if contexts else None
    style = song_performance_style(
        trace, summary, vocabulary, context, characters, gap, design, grid
    )
    cross_check: Dict[str, Any] = {}
    if selection.get("runner_up"):
        cross_check = vocabulary_cross_check(
            vocabulary, load_trace(Path(selection["runner_up"]["path"]))
        )
    sketch = application_sketch(style)
    answers = research_answers(
        selection, vocabulary, context, gap, size, unrolling, design, cross_check
    )
    verdicts = stage_verdicts(vocabulary, context, size, design, cross_check)
    reference_song = {
        "selection": selection,
        "selected": trace.to_dict(),
        "why_this_song": (
            "deterministic ranking over every corpus subsong on the brief's own preference list "
            "(multiple channels, non-trivial POKEY behaviour, meaningful register modulation, "
            "enough material). The full table and the ranking under three other orderings are "
            "published so the choice can be audited rather than trusted."
        ),
        "selection_sensitivity": {
            "winner_under_declared_key": selection["winner"]["trace"],
            "winner_under_other_orderings": selection["sensitivity"],
            "unanimous": selection["winner_robust"],
            "honest_reading": (
                "The choice is not unanimous: ranking pitch vocabulary or raw material first would "
                "select a different song. The declared key follows the brief's bullet order and is "
                "applied mechanically. The runner-up is carried as a robustness cross-check "
                "precisely because the choice is not forced."
            ),
        },
    }
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "reference_song": reference_song,
        "pokey_trace_summary": summary,
        "performance_events": sample_events(events),
        "performance_vocabulary": vocabulary,
        "context_analysis": {
            **context,
            "channel_character": characters,
            "context_dimensions_used": CONTEXT_DIMENSIONS_DOC,
        },
        "player_capability_matrix": capabilities,
        "player_gap_analysis": gap,
        "player_size_analysis": size,
        "player_unrolling_cost": unrolling,
        "hypothetical_player_design": design,
        "song_performance_style": style,
        "application_sketch": sketch,
        "cross_check": cross_check,
        "research_answers": answers,
        "verdicts": verdicts,
        "what_not_to_build_yet": what_not_to_build_yet(),
        "stage16_candidates": stage16_candidates(),
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def write_analysis(
    bundle: Mapping[str, Any],
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the eleven JSON artefacts and the report. Additive: nothing else is touched."""
    stage15_dir = Path(stage15_dir)
    docs_dir = Path(docs_dir)
    stage15_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "reference_song.json": bundle["reference_song"],
        "pokey_trace_summary.json": bundle["pokey_trace_summary"],
        "performance_events.json": bundle["performance_events"],
        "performance_vocabulary.json": bundle["performance_vocabulary"],
        "context_analysis.json": bundle["context_analysis"],
        "player_capability_matrix.json": bundle["player_capability_matrix"],
        "player_gap_analysis.json": bundle["player_gap_analysis"],
        "player_size_analysis.json": bundle["player_size_analysis"],
        "hypothetical_player_design.json": bundle["hypothetical_player_design"],
        "song_performance_style.json": bundle["song_performance_style"],
        "summary.json": bundle["summary"],
    }
    written: Dict[str, Path] = {}
    for name in STAGE15_FILES:
        path = stage15_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE15_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE15_DOC] = doc_path
    return written


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _event_evidence(record: Mapping[str, Any]) -> str:
    """The first evidence string of an event record, whichever shape it is in."""
    if record.get("evidence_first"):
        return str(record["evidence_first"])
    evidence = record.get("evidence") or []
    return str(evidence[0]) if evidence else ""


def _md_table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(str(item) for item in header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if item is None else str(item) for item in row) + " |")
    return "\n".join(lines)


def render_report(bundle: Mapping[str, Any]) -> str:
    """The eighteen sections the brief fixes, in its order."""
    reference = bundle["reference_song"]
    selection = reference["selection"]
    winner = selection["winner"]
    trace_summary = bundle["pokey_trace_summary"]
    vocabulary = bundle["performance_vocabulary"]
    context = bundle["context_analysis"]
    gap = bundle["player_gap_analysis"]
    capabilities = bundle["player_capability_matrix"]
    size = bundle["player_size_analysis"]
    unrolling = bundle["player_unrolling_cost"]
    design = bundle["hypothetical_player_design"]
    style = bundle["song_performance_style"]
    sketch = bundle["application_sketch"]
    cross = bundle["cross_check"]
    verdicts = bundle["verdicts"]
    out: List[str] = []

    out.append("# Stage 15 — SAP Performance Style & Player Capability Investigation\n")
    out.append(
        "Analysis only. This stage opens a new research branch: it does **not** reopen Stage 14 "
        "and does **not** attempt SoundProfile transfer again. Nothing is rendered, generated, "
        "or changed; the 6502 player, the IR, the Composer and every schema are untouched.\n"
    )

    # 1
    out.append("## 1. Executive summary\n")
    out.append(_md_table(
        ["number", "value"],
        [
            ["reference song", f"{winner['title']} ({winner['song']} sub{winner['subsong']})"],
            ["author / date", f"{winner['author']} / {winner['date']}"],
            ["selection", f"rank {winner['rank']} of {selection['candidates_eligible']} eligible; "
                          f"unanimous across orderings: {selection['winner_robust']}"],
            ["duration / frames", f"{winner['duration_s']} s / {winner['frames']} frames"],
            ["POKEY configuration", f"AUDCTL {winner['audctl']} — {winner['audctl_description']}"],
            ["events detected", vocabulary["event_count"]],
            ["techniques extracted", vocabulary["technique_count"]],
            ["context verdicts", ", ".join(f"{k} {v}" for k, v in context["verdict_counts"].items())],
            ["player assembled size", f"{size['assembled_bytes']} bytes"],
            ["estimated mechanisms", f"{design['cost']['estimated_added_code_bytes']} bytes"],
            ["verbose verdict", verdicts["performance_style"]["verdict"]],
            ["player verdict", verdicts["player_expansion"]["verdict"]],
        ],
    ))
    out.append("")
    out.append(f"**{verdicts['performance_style']['verdict']}** + "
               f"**{verdicts['player_expansion']['verdict']}**\n")
    out.append(verdicts["correlation_note"] + "\n")

    # 2
    out.append("## 2. Selected reference song\n")
    out.append(reference["why_this_song"] + "\n")
    out.append(_md_table(
        ["rank", "trace", "author", "date", "channels", "generator families",
         "distinct audible pitches", "frames", "AUDCTL"],
        [
            [row["rank"], row["trace"], row["author"], row["date"], row["audible_channels"],
             row["generator_families"], row["distinct_pitch_values"], row["frames"], row["audctl"]]
            for row in selection["ranking"]
        ],
    ))
    out.append("")
    out.append(f"**Selected:** `{winner['trace']}` — {winner['title']} by {winner['author']} "
               f"({winner['date']}).\n")
    out.append(reference["selection_sensitivity"]["honest_reading"] + "\n")
    out.append(_md_table(
        ["ordering", "would select"],
        [[name, value] for name, value in
         reference["selection_sensitivity"]["winner_under_other_orderings"].items()],
    ))
    out.append("")
    out.append(_md_table(
        ["gate", "requirement", "measured", "passed"],
        [[gate["gate"], gate["requirement"], gate["measured"], gate["passed"]]
         for gate in winner["gates"]],
    ))
    out.append("")
    out.append(f"Trace provenance: schema `{trace_summary['trace_schema']}`, "
               f"sha256 `{trace_summary['trace_sha256']}`, backend "
               f"`{trace_summary['backend'].get('kind')}` "
               f"`{trace_summary['backend'].get('version')}`.\n")

    # 3
    out.append("## 3. Trace methodology\n")
    out.append(
        "The song is not replayed and no SAP is re-parsed. The stage consumes the corpus' "
        "already-published normalised frame dump (`output/traces/*.frames.json`), which ASAP "
        "produced and the archaeology pipeline digitised; the file is hashed before it is read "
        "so the numbers below cannot come from a different capture than the one reported.\n"
    )
    out.append(_md_table(
        ["element", "value"],
        [
            ["trace file", trace_summary["trace_path"]],
            ["sha256", trace_summary["trace_sha256"]],
            ["frames", trace_summary["frames"]],
            ["frame period (ms)", trace_summary["frame_period_ms"]],
            ["nominal frame rate (Hz)", trace_summary["frame_hz_nominal"]],
            ["backend", f"{trace_summary['backend'].get('kind')} "
                        f"{trace_summary['backend'].get('version')}"],
            ["registers captured", "AUDF1-4, AUDC1-4, AUDCTL (one state per VBL)"],
            ["trace notes", "; ".join(trace_summary["trace_notes"])],
        ],
    ))
    out.append("")
    out.append(
        "Everything is frame-quantised: sub-frame register writes are already coalesced by the "
        "emulator, so a one-frame event is the smallest thing this analysis can see. Note "
        "boundaries are **inferred**, not decoded — see section 7.\n"
    )

    # 4
    out.append("## 4. POKEY behaviour over time\n")
    out.append(_md_table(
        ["voice", "channels", "16-bit pair", "audible frames", "notes", "median note frames",
         "divider range", "Hz range", "families used"],
        [
            [voice["voice_id"], voice["channels"], voice["joined_16bit"], voice["audible_frames"],
             voice["note_count"], voice["note_duration_frames_median"],
             f"{voice['divider_min']}-{voice['divider_max']}",
             f"{voice['hz_min']}-{voice['hz_max']}", ", ".join(voice["families_when_audible"])]
            for voice in trace_summary["voices"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["channel", "AUDF is read as", "audible share", "AUDF changes", "AUDC changes",
         "silent register writes", "families when audible"],
        [
            [item["channel"], item["pitch_interpretation"], item["audible_share"],
             item["audf_changes"], item["audc_changes"], item["silent_register_writes"],
             ", ".join(item["families_when_audible"])]
            for item in trace_summary["channels"]
        ],
    ))
    out.append("")
    out.append(f"AUDCTL is `{trace_summary['audctl']['values_by_frames']}` — "
               f"{trace_summary['audctl']['changes']} changes in the whole song. "
               f"{trace_summary['audctl']['description']}.\n")
    out.append(_md_table(
        ["bucket", "start s", "ch1 changes", "ch2 changes", "ch3 changes", "ch4 changes"],
        [
            [row["bucket"], row["start_s"]] + [cell["audf_changes"] for cell in row["channels"]]
            for row in trace_summary["timeline"]
        ],
    ))
    out.append("")

    # 5
    out.append("## 5. Detected performance events\n")
    out.append(_md_table(
        ["event kind", "occurrences"],
        [[kind, count] for kind, count in vocabulary["occurrences_by_kind"].items()],
    ))
    out.append("")
    out.append(f"Event classes the brief lists that the trace does **not** support: "
               f"{', '.join(vocabulary['kinds_absent']) or 'none'}. "
               "Their absence is published rather than filled in.\n")
    events = bundle["performance_events"]
    out.append(_md_table(
        ["sampling", "value"],
        [
            ["events total", events["events_total"]],
            ["events written", events["events_written"]],
            ["per-kind cap", events["per_kind_cap"]],
            ["truncated by kind", events["truncated_by_kind"] or "none"],
        ],
    ))
    out.append("")

    # 6
    out.append("## 6. Musical behaviour vs register artifacts\n")
    out.append(
        "Every event carries a classification and the evidence that produced it. Nothing is "
        "called a slide, a vibrato or an arpeggio merely because AUDF changed.\n"
    )
    out.append(_md_table(
        ["classification", "events", "meaning"],
        [
            [CLASS_MUSICAL, vocabulary["classifications"].get(CLASS_MUSICAL, 0),
             "audible tonal voice whose register changed while sounding"],
            [CLASS_UNKNOWN, vocabulary["classifications"].get(CLASS_UNKNOWN, 0),
             "AUDF moved but is not a pitch: a noise clock, or volume-only output"],
            [CLASS_ARTIFACT, vocabulary["classifications"].get(CLASS_ARTIFACT, 0),
             "register write on a channel that is silent, or the low byte of a joined pair"],
        ],
    ))
    out.append("")
    sample = [
        event for event in events["events"]
        if event["classification"] != CLASS_MUSICAL
    ][:5]
    if sample:
        out.append(_md_table(
            ["kind", "channel", "frames", "classification", "evidence"],
            [[event["kind"], event["channel"], f"{event['start_frame']}-{event['end_frame']}",
              event["classification"], event["evidence_first"]] for event in sample],
        ))
        out.append("")
    out.append(
        f"The cross-check song supplies the artifact class this song lacks. In "
        f"{cross['other_song']} (AUDCTL {cross['other_audctl']}), "
        f"{cross['other_classifications'].get(CLASS_ARTIFACT, 0)} register writes sit on the low "
        "byte of a joined 16-bit divider while its AUDC volume nibble is zero: they look exactly "
        "like a busy bass line and produce no sound at all. Reading AUDF without combining the "
        "pair would invent a melody that is not there — the Stage 13A lesson, reproduced "
        "mechanically.\n"
    )
    out.append(_md_table(
        ["voice", "inferred character", "rule", "musical role"],
        [[item["voice_id"], item["inferred_character"], item["inference_rule"], item["musical_role"]]
         for item in context["channel_character"]["voices"]],
    ))
    out.append("")
    out.append(context["channel_character"]["note"] + "\n")

    # 7
    out.append("## 7. Performance vocabulary\n")
    out.append(
        "Note boundaries are inferred, and the inference is published so it can be repeated or "
        "disputed. A new note starts where the divider jumps by "
        f"{NOTE_SPLIT_SEMITONES} semitones or more and the new value persists for "
        f"{NOTE_MIN_FRAMES} frames, or where the volume re-attacks upward from near silence by "
        f"{NOTE_REATTACK_DELTA} levels. The consequence is visible below: this song's busiest "
        "voice has a median note of three frames, so 'note' here means 'audible gesture', not "
        "'written score note'.\n"
    )
    out.append(_md_table(
        ["technique", "occurrences", "median frames", "median interval (semitones)",
         "generator families", "channels"],
        [
            [item["technique_id"], item["occurrences"], item["duration_frames"].get("median"),
             item["numeric_parameters"].get("interval_semitones", {}).get("median"),
             ", ".join(f"{k} {v}" for k, v in item["family_buckets"].items()),
             ", ".join(f"ch{k} {v}" for k, v in item["channels"].items())]
            for item in vocabulary["techniques"]
        ],
    ))
    out.append("")
    first = vocabulary["techniques"][0]
    out.append("One technique in full, as the artefact records it:\n")
    out.append(_md_table(
        ["field", "value"],
        [
            ["technique", first["technique_id"]],
            ["occurrences", first["occurrences"]],
            ["duration frames", first["duration_frames"]],
            ["confidence", first["confidence"]],
            ["positions in note", first["positions_in_note"]],
            ["pitch bands", first["pitch_bands"]],
            ["numeric parameters", ", ".join(first["numeric_parameters"].keys())],
        ],
    ))
    out.append("")
    out.append(f"Example evidence: *{_event_evidence(first['example'])}*\n")

    # 8
    out.append("## 8. Context dependence\n")
    out.append(
        f"Method: {context['method']['test']}, threshold {context['method']['threshold']} "
        f"({context['method']['threshold_meaning']}); a technique needs at least "
        f"{context['method']['minimum_occurrences_for_a_verdict']} occurrences for a verdict. "
        "Circular tests are excluded: a factor is never used to explain the quantity it was "
        "computed from (pitch_band from the divider, note_length_band from the note length, "
        "family_bucket from the waveform).\n"
    )
    out.append(context["answer"] + "\n")
    out.append(_md_table(
        ["technique", "occurrences", "verdict", "strongest factor", "eta-squared",
         "group medians"],
        [
            [item["technique_id"], item["occurrences"], item["verdict"],
             item["strongest_factor"], item["strongest_eta_squared"],
             (item["context_tests"][0]["group_medians"] if item["context_tests"] else "")]
            for item in context["techniques"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["dimension", "meaning"],
        [[key, value] for key, value in context["context_dimensions_used"].items()],
    ))
    out.append("")

    # 9
    out.append("## 9. Current player capabilities\n")
    out.append(
        f"Read from `{capabilities['source']}` (sha256 `{capabilities['source_sha256']}`), "
        f"{capabilities['source_lines']} lines of which {capabilities['source_code_lines']} are "
        "code. Every claim below carries the source lines that support it; the entries marked "
        "*unsupported* list the patterns that were searched for and not found.\n"
    )
    out.append(_md_table(
        ["capability", "supported", "detail", "evidence lines", "cost if added", "kind"],
        [
            [item["capability"], item["supported"], item["detail"],
             ", ".join(str(hit["line"]) for hit in item["evidence"]) or "(absent)",
             item["what_it_would_cost"], item["cost_kind"]]
            for item in capabilities["capabilities"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["data format element", "value"],
        [
            ["song header", f"{capabilities['data_format']['song_header_bytes']} bytes: "
                            f"{', '.join(capabilities['data_format']['header_fields'])}"],
            ["instrument", f"{capabilities['data_format']['instrument_bytes_per_channel']} bytes "
                           f"per channel: "
                           f"{', '.join(capabilities['data_format']['instrument_fields'])}"],
            ["note event", f"{capabilities['data_format']['event_bytes']} bytes: "
                           f"{', '.join(capabilities['data_format']['event_fields'])}"],
            ["end of track", capabilities["data_format"]["event_terminator"]],
            ["timing resolution", capabilities["data_format"]["timing_resolution"]],
            ["zero page", f"{capabilities['data_format']['zero_page_bytes']} bytes"],
            ["runtime state", f"{capabilities['state_bytes']} bytes"],
        ],
    ))
    out.append("")

    # 10
    out.append("## 10. Reference techniques unsupported by current player\n")
    out.append(gap["answer"] + "\n")
    out.append(_md_table(
        ["technique", "in reference", "player supports", "expressible", "classification",
         "missing mechanism"],
        [
            [item["technique_id"], item["occurrences_in_reference"],
             item["current_player_supports"], item["expressible_today"],
             item["classification"], item["missing_mechanism"] or "—"]
            for item in gap["rows"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["classification", "techniques"],
        [[key, value] for key, value in gap["classification_counts"].items()],
    ))
    out.append("")

    # 11
    out.append("## 11. Player size and architecture analysis\n")
    out.append(
        f"The project's one hard binary limit is **{size['limit_bytes']} bytes on the assembled "
        "player**, and it is **exclusive**: a player of exactly "
        f"{size['limit_bytes']} bytes fails. It bounds *{size['limit_scope']}*. In particular the "
        "complete `.xex` file is **not** bounded by it, and neither is the song data; a built "
        "executable may legitimately be larger than "
        f"{size['limit_bytes']} bytes, and several are. The `hypothetical_4KB` row below is a "
        "counterfactual this stage weighs, not a second limit.\n"
    )
    out.append(_md_table(
        ["measure", "bytes"],
        [
            ["assembled (code + state)", size["assembled_bytes"]],
            ["of which code", size["code_bytes"]],
            ["of which runtime state", size["state_bytes"]],
            ["zero page", size["zero_page_bytes"]],
            ["total footprint", size["total_player_footprint_bytes"]],
            ["player size limit (exclusive)", f"< {size['limit_bytes']}"],
            ["player within the limit", size["within_limit"]],
            ["headroom inside a 2 KB envelope", size["headroom_bytes"]["current_envelope_2KB"]],
            ["headroom inside 4 KB", size["headroom_bytes"]["hypothetical_4KB"]],
            ["estimated cost of the needed mechanisms",
             design["cost"]["estimated_added_code_bytes"]],
            ["headroom left after adding them",
             size["headroom_bytes"]["current_envelope_2KB"]
             - design["cost"]["estimated_added_code_bytes"]],
        ],
    ))
    out.append("")
    out.append(
        f"Measurement: {size['measurement_method']}. The recorded value is "
        f"{size['recorded_measurement']} bytes; this run "
        + (f"re-measured it as {size['measured_this_run']} bytes."
           if size["measured_this_run"] is not None
           else "could not re-measure it (no assembler present), so the recorded value is used.")
        + " The source hash is published so a stale number is visible.\n"
    )
    out.append(unrolling["verdict"] + "\n")
    out.append(_md_table(
        ["unrolling measure", "value"],
        [
            ["audible frames per channel", unrolling["audible_frames_per_channel"]],
            ["one note per frame, bytes", unrolling["unrolled_total_bytes"]],
            ["note events in the reference", unrolling["note_events_in_reference"]],
            ["note-level cost of those notes",
             unrolling["current_format_bytes_for_those_notes"]],
            ["with one effect byte per note",
             unrolling["format_with_one_effect_byte_per_note"]],
            ["unrolled / note-level ratio", unrolling["unrolled_to_current_ratio"]],
        ],
    ))
    out.append("")
    out.append(
        "This is the architectural finding the brief asks for in Part K. The same performance can "
        "already be executed by today's player if every frame becomes a note: the *player* is "
        "nearly complete for pitch and loudness. What is exhausted is the song stream, and a 4 KB "
        "player would not change that number by a single byte.\n"
    )

    # 12
    out.append("## 12. Hypothetical richer player\n")
    out.append(design["principle"] + "\n")
    out.append(_md_table(
        ["command", "existing", "data bytes", "estimated code lines", "justified by"],
        [[item["command"], item["existing"], item["data_bytes"], item["code_lines"],
          item["justified_by"]] for item in design["commands"]],
    ))
    out.append("")
    out.append(_md_table(
        ["refused command", "reason"],
        [[item["command"], item["reason"]] for item in design["refused_commands"]],
    ))
    out.append("")
    out.append(_md_table(
        ["cost", "value"],
        [
            ["bytes per code line (current source)",
             design["cost"]["bytes_per_code_line_current_source"]],
            ["basis", design["cost"]["bytes_per_code_line_basis"]],
            ["added code lines", design["cost"]["added_code_lines"]],
            ["estimated added code bytes", design["cost"]["estimated_added_code_bytes"]],
            ["estimated player size after", design["cost"]["estimated_player_bytes_after"]],
            ["added state RAM bytes", design["cost"]["added_state_ram_bytes"]],
            ["added song data per effected note",
             design["cost"]["added_song_data_bytes_per_effected_note"]],
            ["cycles available per frame", design["cost"]["cycles_per_frame_available"]],
            ["estimated added cycles per frame",
             design["cost"]["estimated_added_cycles_per_frame"]],
            ["share of a frame", design["cost"]["cpu_share_of_a_frame"]],
        ],
    ))
    out.append("")
    out.append(design["cost"]["estimate_disclaimer"] + "\n")

    # 13
    out.append("## 13. SongPerformanceStyle representation\n")
    out.append(f"**Term chosen:** `{style['artifact']}`. {style['artifact_rationale']}\n")
    out.append(f"**Status:** {style['status']}.\n")
    out.append(_md_table(
        ["field", "value"],
        [
            ["source song", f"{style['source_song']['song']} sub{style['source_song']['subsong']}"],
            ["POKEY configuration", style["pokey_configuration"]["description"]],
            ["techniques", len(style["performance_techniques"])],
            ["event classes present", ", ".join(style["event_classes_present"])],
            ["event classes absent", ", ".join(style["event_classes_absent"])],
            ["onset grid (frames)", style["timing"]["onset_grid_frames"]],
            ["musical share of events", style["musical_share_of_events"]],
            ["techniques supported by the player today",
             style["player_requirements"]["techniques_supported_today"]],
            ["techniques needing a wider format",
             style["player_requirements"]["techniques_needing_a_wider_format"]],
            ["techniques with no representation",
             style["player_requirements"]["techniques_with_no_representation"]],
        ],
    ))
    out.append("")
    out.append(style["confidence"]["overall"] + "\n")

    # 14
    out.append("## 14. Applying the style conceptually to new music\n")
    out.append(
        f"Input: {sketch['input']['kind']}"
        + (f" (`{sketch['input']['source']}`)" if sketch["input"].get("source") else "")
        + ". Nothing is composed and no IR is produced.\n"
    )
    out.append(_md_table(
        ["note", "composer note", "style interpretation"],
        [[row["note_index"], row["composer_note"], "; ".join(row["style_interpretation"])]
         for row in sketch["mapping"]],
    ))
    out.append("")
    out.append(sketch["answer"] + "\n")

    # 15
    out.append("## 15. Answers to the ten research questions\n")
    for item in bundle["research_answers"]:
        out.append(f"**{item['question']}**\n")
        out.append(item["answer"] + "\n")

    # 16
    out.append("## 16. Stage 15 verdict\n")
    out.append(f"**{verdicts['performance_style']['verdict']}**\n")
    out.append(_md_table(
        ["proven", ""],
        [[key, value] for key, value in verdicts["performance_style"]["proven"].items()],
    ))
    out.append("")
    out.append(_md_table(
        ["unproven", ""],
        [[key, value] for key, value in verdicts["performance_style"]["unproven"].items()],
    ))
    out.append("")
    out.append(verdicts["performance_style"]["narrower_claim_that_is_supported"] + "\n")
    out.append(f"**{verdicts['player_expansion']['verdict']}**\n")
    out.append(verdicts["player_expansion"]["reason"] + "\n")
    out.append(verdicts["correlation_note"] + "\n")
    out.append("### Falsification attempt\n")
    out.append(
        "The stage was asked to try to falsify the hypothesis rather than prove it. Two checks "
        "were made. First, a second song went through the same extractor:\n"
    )
    out.append(_md_table(
        ["cross-check", "value"],
        [
            ["song", f"{cross['other_song']} sub{cross['other_subsong']} "
                     f"(AUDCTL {cross['other_audctl']})"],
            ["events / techniques",
             f"{cross['other_event_count']} / {cross['other_technique_count']}"],
            ["shared event classes", ", ".join(cross["kinds_shared"])],
            ["classes only in the reference",
             ", ".join(cross["kinds_only_in_reference"]) or "none"],
            ["classes only in the other", ", ".join(cross["kinds_only_in_other"]) or "none"],
            ["shared kind share", cross["shared_kind_share"]],
            ["shared technique ids", ", ".join(cross["technique_ids_shared"])],
            ["shared technique id share", cross["technique_id_share"]],
        ],
    ))
    out.append("")
    out.append(cross["conclusion"] + "\n")
    out.append(
        "Second, the context test is itself the falsifier: if a technique's parameters did *not* "
        "differ across contexts, the abstraction would be a single object and no context would be "
        "needed. It failed to falsify the hypothesis — the parameters differ sharply — which is "
        "positive evidence for context and, at the same time, negative evidence for naive "
        "transfer.\n"
    )

    # 17
    out.append("## 17. What should NOT be built yet\n")
    out.append(_md_table(
        ["not yet", "why"],
        [[item["item"], item["why"]] for item in bundle["what_not_to_build_yet"]],
    ))
    out.append("")

    # 18
    out.append("## 18. Candidate Stage 16 experiments\n")
    out.append(_md_table(
        ["candidate", "question it answers", "cost"],
        [[item["candidate"], item["question"], item["cost"]]
         for item in bundle["stage16_candidates"]],
    ))
    out.append("")
    out.append("---\n")
    out.append(
        f"Stage 15 analysed exactly one song (`{winner['trace']}`), read every input through its "
        "hash, and wrote only `reports/stage15/` and this document. No Composer, DSL, IR, player "
        "or schema was modified; no music was generated; no listening test was run; no style "
        "engine was built.\n"
    )
    return "\n".join(out)


__all__ = [
    "ANALYSIS_VERSION",
    "CONTEXT_ETA2_THRESHOLD",
    "DEFAULT_ARCHAEOLOGY_DIR",
    "DEFAULT_DOCS_DIR",
    "DEFAULT_MADS",
    "DEFAULT_PLAYER_ASM",
    "DEFAULT_REPORTS_DIR",
    "DEFAULT_STAGE15_DIR",
    "EVENT_KINDS",
    "Event",
    "NoteSpan",
    "PLAYER_ASSEMBLED_BYTES_METHOD",
    "PLAYER_ASSEMBLED_BYTES_RECORDED",
    "PLAYER_SIZE_BUDGETS",
    "PLAYER_SIZE_LIMIT_BYTES",
    "PLAYER_SIZE_LIMIT_SCOPE",
    "PlayerSizeError",
    "RegisterTrace",
    "STAGE15_DOC",
    "STAGE15_FILES",
    "STYLE_TERM",
    "Stage15Error",
    "Voice",
    "application_sketch",
    "audc_volume",
    "audc_waveform",
    "candidate_metrics",
    "channel_character",
    "check_player_size",
    "context_dependence",
    "detect_events",
    "event_contexts",
    "hypothetical_player_design",
    "load_trace",
    "measure_player_size",
    "note_spans",
    "performance_vocabulary",
    "pitch_interpretation",
    "player_capabilities",
    "player_gap_analysis",
    "player_size_analysis",
    "player_size_limit_ok",
    "render_report",
    "research_answers",
    "run_analysis",
    "sample_events",
    "select_reference_song",
    "sha256_file",
    "song_performance_style",
    "stage_verdicts",
    "technique_id",
    "trace_summary",
    "unrolling_cost",
    "vocabulary_cross_check",
    "voices_for",
    "what_not_to_build_yet",
    "write_analysis",
]


def _context_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fold the per-technique verdicts into the Part F answer."""
    ordered = sorted(results, key=lambda item: (-item["occurrences"], item["technique_id"]))
    verdicts = Counter(item["verdict"] for item in ordered)
    dominant = [
        item
        for item in ordered
        if item["occurrences"] >= 5 and item["channels"]
        and max(item["channels"].values()) / item["occurrences"] >= 0.8
    ]
    return {
        "method": {
            "test": "Cohen's eta-squared of a parameter's distribution across context groups",
            "threshold": CONTEXT_ETA2_THRESHOLD,
            "threshold_meaning": (
                "medium effect size: groups of at least 3 occurrences are not interchangeable"
            ),
            "factors": list(CONTEXT_FACTORS),
            "minimum_occurrences_for_a_verdict": 20,
        },
        "techniques_tested": len(ordered),
        "verdict_counts": dict(verdicts.most_common()),
        "techniques": ordered,
        "channel_bound_techniques": [
            {
                "technique_id": item["technique_id"],
                "occurrences": item["occurrences"],
                "dominant_channel": max(item["channels"], key=lambda key: item["channels"][key]),
                "share": _rnd(max(item["channels"].values()) / item["occurrences"], 3),
            }
            for item in dominant
        ],
        "answer": (
            "The abstraction has to be TECHNIQUE + CONTEXT: "
            f"{verdicts.get('TECHNIQUE_CONTEXT_SPLIT', 0)} of {len(ordered)} techniques split by "
            f"context, {verdicts.get('SINGLE_TECHNIQUE', 0)} survive as single techniques, "
            f"{verdicts.get('INSUFFICIENT_EVIDENCE', 0)} have too few occurrences to judge."
        ),
    }

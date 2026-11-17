#!/usr/bin/env python
"""Unified Smart Batch Arrangement Script for Atari 8-bit POKEY Music.

Replaces separate 8-bit and 16-bit PowerShell wrappers with one Python tool that:
1. Queries ``atari-music.exe list-instruments --target xex_v2 --json`` for the live
   compatible SSOT instrument catalog.
2. Accepts Music DSL (``.dsl`` -> temporary JSON via ``atari-music.exe import-dsl``)
   or JSON (``AICompositionDoc`` or POKEY IR ``IRSong``).
3. Automatically detects 16-bit joined bass (CH1+CH2) vs. 8-bit bass and profiles
   each active channel (role, MIDI range, note count, duration, articulation,
   pitch diversity).
4. Scores, ranks, and selects diverse ``v2`` arrangement combinations tailored to
   the composition, plus a ``vanilla`` (``--player-version v1``) baseline when
   compatible.
5. Compiles ``<name>.wav`` and ``<name>.xex`` via ``atari-music.exe arrange`` and
   writes a detailed matching log (``arrangements.log``) in the output directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent

DEFAULT_MADS_REL = Path("tools/mads/mads.exe")
DEFAULT_MAX_VARIANTS = 6
LOG_FILENAME = "arrangements.log"

_NOTE_BASE_SEMITONES: Dict[str, int] = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}

_SHORT_TOKEN_MAP: Dict[str, str] = {
    "bass_16bit_pure": "16pure",
    "bass_16bit_poly5_growl": "16growl",
    "bass_15khz_pure": "15pure",
    "bass_poly4_punch": "poly4bass",
    "lead_pure_sustain": "sustain",
    "lead_pure_pluck": "pluck",
    "lead_c1_octave_pulse": "c1pulse",
    "lead_attack_bite": "bite",
    "lead_buzz_steady": "buzz",
    "harmony_soft_square": "softsq",
    "perc_snare_crisp": "snare",
    "perc_kick_tight": "kick",
    "perc_hihat_closed": "hihat",
    "perc_tom_pitched": "tom",
}


@dataclass(frozen=True)
class EnvelopeInfo:
    """Static linear ADSR parameters reported by ``atari-music list-instruments``."""

    attack_frames: int = 0
    decay_frames: int = 0
    sustain_vol: int = 8
    release_frames: int = 2
    peak_vol: int = 15


@dataclass(frozen=True)
class CatalogInstrumentInfo:
    """Catalog instrument metadata fetched from ``atari-music.exe``."""

    instrument_id: str
    display_name: str
    family: str
    intended_roles: Tuple[str, ...]
    distortion_hex: str
    divider_mode: str
    channels_allowed: Tuple[int, ...]
    midi_range: Tuple[int, int]
    waveform_family: str
    preferred_clock_hz: Optional[str]
    required_audctl_bits: int
    forbidden_audctl_bits: int
    poly4_safe_tuning: bool
    envelope: EnvelopeInfo
    behavior_id: Optional[str]
    tier: str
    compatible: bool
    status: str


@dataclass(frozen=True)
class ChannelAnalysis:
    """Musical statistics and inferred role for a single POKEY channel (1..4)."""

    channel: int
    active: bool
    reserved_for_16bit: bool
    role: str
    source_roles: Tuple[str, ...]
    note_count: int
    midi_min: Optional[int]
    midi_max: Optional[int]
    midi_median: Optional[float]
    avg_duration: float
    short_note_ratio: float
    distinct_pitches: int


@dataclass(frozen=True)
class CompositionAnalysis:
    """Extracted hardware and musical profile for an input composition."""

    source_path: Path
    source_kind: str
    title: str
    key: str
    mode: str
    tempo_bpm: int
    uses_16bit_bass: bool
    v1_compatible: bool
    v2_required_reasons: Tuple[str, ...]
    channels: Dict[int, ChannelAnalysis]


@dataclass(frozen=True)
class ScoredCandidate:
    """Fit score and human-readable reasons for one instrument on one channel."""

    instrument: CatalogInstrumentInfo
    score: float
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class PlannedVariant:
    """One output arrangement variant to render via ``atari-music.exe arrange``."""

    rank: Optional[int]
    name: str
    player_version: str
    channel_instruments: Dict[int, str]
    channel_scores: Dict[int, float]
    total_score: float
    selection_notes: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VariantRunResult:
    """Execution outcome for one planned variant."""

    variant: PlannedVariant
    status: str  # "OK", "SKIPPED", "FAILED", "DRY_RUN"
    command: Tuple[str, ...]
    exit_code: Optional[int]
    wav_path: Path
    xex_path: Path
    wav_bytes: int
    xex_bytes: int
    message: str = ""


def note_name_to_midi(name: Optional[str]) -> Optional[int]:
    """Parse note name like ``'C-4'``, ``'F#3'``, or ``'Bb2'`` into MIDI note number."""
    if not name or name.strip().upper() in ("", "---", "REST", "OFF", "SIL", "R"):
        return None
    cleaned = name.strip().replace("-", "").replace(" ", "")
    if len(cleaned) < 2:
        return None
    note_part = cleaned[:-1].upper()
    try:
        octave = int(cleaned[-1])
    except ValueError:
        return None
    semitone = _NOTE_BASE_SEMITONES.get(note_part)
    if semitone is None:
        return None
    return (octave + 1) * 12 + semitone


def resolve_atari_music_exe(requested: Optional[Path] = None) -> Path:
    """Locate ``atari-music.exe`` / ``atari-music`` CLI executable."""
    if requested is not None:
        candidate = requested.expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"Specified atari-music executable not found: {candidate}")
        return candidate.resolve()

    local_candidates = (
        REPO_ROOT / ".venv" / "Scripts" / "atari-music.exe",
        REPO_ROOT / ".venv" / "bin" / "atari-music",
        Path(sys.executable).resolve().parent / "atari-music.exe",
        Path(sys.executable).resolve().parent / "atari-music",
    )
    for cand in local_candidates:
        if cand.is_file():
            return cand.resolve()

    for cmd_name in ("atari-music.exe", "atari-music"):
        found = shutil.which(cmd_name)
        if found:
            return Path(found).resolve()

    raise FileNotFoundError(
        "atari-music executable not found in .venv or PATH. "
        "Activate .venv, install 'atari-music' in PATH, or pass --atari-music-path."
    )


def resolve_mads_exe(requested: Optional[Path] = None, *, allow_missing: bool = False) -> Path:
    """Locate MADS assembler executable."""
    if requested is not None:
        cand = requested.expanduser()
        if cand.is_file():
            return cand.resolve()
        if allow_missing:
            return cand.resolve()
        raise FileNotFoundError(f"MADS executable not found: {cand}")

    repo_default = REPO_ROOT / DEFAULT_MADS_REL
    if repo_default.is_file():
        return repo_default.resolve()

    for cmd_name in ("mads.exe", "mads"):
        found = shutil.which(cmd_name)
        if found:
            return Path(found).resolve()

    if allow_missing:
        return repo_default

    raise FileNotFoundError(
        f"MADS executable not found (checked {repo_default} and PATH). Pass --mads PATH."
    )


def _run_subprocess(cmd: Sequence[str], *, stream_output: bool = False) -> Tuple[int, str, str]:
    """Execute a subprocess deterministically, capturing stdout and stderr."""
    if not stream_output:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr

    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: List[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\r\n")
        print(line)
        lines.append(line)
    proc.wait()
    return proc.returncode, "\n".join(lines), ""


def _parse_catalog_row(row: Mapping[str, Any], inspect_payload: Optional[Mapping[str, Any]] = None) -> CatalogInstrumentInfo:
    """Normalize a catalog row from ``list-instruments --json`` (optionally enriched via inspect)."""
    prof = (inspect_payload or {}).get("profile", {})
    hc = prof.get("hardware_constraints", {})
    env_dict = row.get("envelope") or prof.get("envelope") or {}
    midi_raw = row.get("midi_range") or hc.get("midi_range") or [24, 108]

    return CatalogInstrumentInfo(
        instrument_id=str(row["instrument_id"]),
        display_name=str(row.get("display_name") or row["instrument_id"]),
        family=str(row.get("family") or prof.get("family") or "lead"),
        intended_roles=tuple(str(r) for r in (row.get("intended_roles") or prof.get("intended_roles") or ())),
        distortion_hex=str(row.get("distortion_hex") or "$A0"),
        divider_mode=str(row.get("divider_mode") or hc.get("divider_mode") or "8bit"),
        channels_allowed=tuple(int(c) for c in (row.get("channels_allowed") or hc.get("channels_allowed") or (1, 2, 3, 4))),
        midi_range=(int(midi_raw[0]), int(midi_raw[1])),
        waveform_family=str(row.get("waveform_family") or prof.get("waveform_family") or "pure"),
        preferred_clock_hz=row.get("preferred_clock_hz") if "preferred_clock_hz" in row else hc.get("preferred_clock_hz"),
        required_audctl_bits=int(
            row.get("required_audctl_bits")
            if row.get("required_audctl_bits") is not None
            else hc.get("required_audctl_bits", 0)
        ),
        forbidden_audctl_bits=int(hc.get("forbidden_audctl_bits", 0)),
        poly4_safe_tuning=bool(
            row.get("poly4_safe_tuning")
            if row.get("poly4_safe_tuning") is not None
            else hc.get("poly4_safe_tuning", False)
        ),
        envelope=EnvelopeInfo(
            attack_frames=int(env_dict.get("attack_frames", 0)),
            decay_frames=int(env_dict.get("decay_frames", 0)),
            sustain_vol=int(env_dict.get("sustain_vol", 8)),
            release_frames=int(env_dict.get("release_frames", 2)),
            peak_vol=int(env_dict.get("peak_vol", 15)),
        ),
        behavior_id=row.get("behavior_id"),
        tier=str(row.get("tier") or "core_v1"),
        compatible=bool(row.get("compatible", False)),
        status=str(row.get("status") or ""),
    )


def query_catalog_instruments(atari_music_exe: Path) -> List[CatalogInstrumentInfo]:
    """Query ``atari-music.exe list-instruments --target xex_v2 --json`` for compatible profiles."""
    cmd = [str(atari_music_exe), "list-instruments", "--target", "xex_v2", "--json"]
    rc, stdout, stderr = _run_subprocess(cmd)
    if rc != 0:
        raise RuntimeError(
            f"Failed to query instrument catalog via {' '.join(cmd)} (exit code {rc}):\n{stderr or stdout}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON returned by list-instruments --json: {exc}\n{stdout}") from exc

    rows = payload.get("instruments")
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected list-instruments --json payload: missing 'instruments' list.")

    compatible_instruments: List[CatalogInstrumentInfo] = []
    for row in rows:
        if not bool(row.get("compatible", False)):
            continue
        inspect_payload: Optional[Dict[str, Any]] = None
        if "midi_range" not in row or "envelope" not in row:
            inst_id = str(row["instrument_id"])
            irc, istdo, _ = _run_subprocess(
                [str(atari_music_exe), "inspect-instrument", inst_id, "--json"]
            )
            if irc == 0:
                try:
                    inspect_payload = json.loads(istdo)
                except json.JSONDecodeError:
                    inspect_payload = None
        compatible_instruments.append(_parse_catalog_row(row, inspect_payload))

    if not compatible_instruments:
        raise RuntimeError("No compatible instruments reported by atari-music list-instruments --target xex_v2.")
    return compatible_instruments


def _infer_role_from_ai_character(character: str) -> str:
    """Match ``atari_music.ai.composition.map_instrument_character`` role mapping using stdlib only."""
    char = (character or "bright_lead").strip().lower()
    if any(k in char for k in ("kick", "tom", "thud", "percussion", "noise", "drum", "snare", "hihat", "hat", "cymbal", "clap", "shake")):
        return "percussion"
    if "bass" in char:
        return "bass"
    if any(k in char for k in ("dark", "pad", "drone", "bell", "ornament", "high", "counter", "harmony")):
        return "harmony"
    return "melody"


def _normalize_ai_channel_idx(ch_key: Any, has_zero: bool) -> int:
    """Normalize AI Composition channel key (0..3 or 1..4) to 1-based channel 1..4."""
    val = int(str(ch_key).strip())
    if val == 0:
        return 1
    if val in (1, 2, 3):
        return (val + 1) if has_zero else val
    if val == 4:
        return 4
    raise ValueError(f"Invalid channel index {ch_key!r}; expected 0..3 or 1..4")


def _summarize_channel_stats(
    ch: int,
    *,
    uses_16bit_bass: bool,
    pitches: Sequence[int],
    durations: Sequence[int],
    roles_seen: Sequence[str],
    default_role: str,
) -> ChannelAnalysis:
    """Build per-channel analysis summary from extracted note stats."""
    reserved = uses_16bit_bass and ch == 2
    active = (len(pitches) > 0) and not reserved
    source_roles = tuple(dict.fromkeys(roles_seen))

    role = default_role
    if uses_16bit_bass and ch == 1:
        role = "bass"
    elif source_roles:
        role = source_roles[0]

    if not pitches:
        return ChannelAnalysis(
            channel=ch,
            active=active,
            reserved_for_16bit=reserved,
            role=role,
            source_roles=source_roles,
            note_count=0,
            midi_min=None,
            midi_max=None,
            midi_median=None,
            avg_duration=0.0,
            short_note_ratio=0.0,
            distinct_pitches=0,
        )

    short_count = sum(1 for d in durations if d <= 2)
    return ChannelAnalysis(
        channel=ch,
        active=active,
        reserved_for_16bit=reserved,
        role=role,
        source_roles=source_roles,
        note_count=len(pitches),
        midi_min=min(pitches),
        midi_max=max(pitches),
        midi_median=float(statistics.median(pitches)),
        avg_duration=float(sum(durations)) / len(durations),
        short_note_ratio=float(short_count) / len(durations),
        distinct_pitches=len(set(pitches)),
    )


def _refine_channel_roles(channels: Dict[int, ChannelAnalysis], uses_16bit_bass: bool) -> Dict[int, ChannelAnalysis]:
    """Refine ambiguous channel roles using MIDI register heuristics."""
    refined = dict(channels)
    active_non_perc = [
        c for c in refined.values() if c.active and c.role != "percussion" and c.midi_median is not None
    ]
    if not active_non_perc:
        return refined

    # Ensure there is a bass role if an 8-bit song failed to label one and has low notes
    if not uses_16bit_bass and not any(c.role == "bass" for c in active_non_perc):
        lowest = min(active_non_perc, key=lambda c: c.midi_median if c.midi_median is not None else 999.0)
        if lowest.midi_median is not None and lowest.midi_median <= 50.0:
            ch = lowest.channel
            refined[ch] = ChannelAnalysis(**{**lowest.__dict__, "role": "bass"})

    # Ensure there is a melody role if multiple harmony tracks exist without an explicit melody track
    active_non_perc = [
        c for c in refined.values() if c.active and c.role != "percussion" and c.midi_median is not None
    ]
    if not any(c.role == "melody" for c in active_non_perc):
        candidates = [c for c in active_non_perc if c.role != "bass"] or active_non_perc
        highest = max(candidates, key=lambda c: c.midi_median if c.midi_median is not None else -1.0)
        ch = highest.channel
        refined[ch] = ChannelAnalysis(**{**highest.__dict__, "role": "melody"})

    return refined


def analyze_composition(json_path: Path, source_path: Optional[Path] = None) -> CompositionAnalysis:
    """Analyze an ``AICompositionDoc`` or POKEY IR ``IRSong`` JSON file using stdlib only."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot parse composition JSON '{json_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in '{json_path}', got {type(data).__name__}")

    origin = source_path if source_path is not None else json_path
    pitches_by_ch: Dict[int, List[int]] = {ch: [] for ch in range(1, 5)}
    durs_by_ch: Dict[int, List[int]] = {ch: [] for ch in range(1, 5)}
    roles_by_ch: Dict[int, List[str]] = {ch: [] for ch in range(1, 5)}

    if data.get("format") == "atari-music-composition":
        meta = data.get("metadata") or {}
        hw = data.get("hardware") or {}
        uses_16bit_bass = bool(hw.get("use_16bit_bass", False))
        title = str(meta.get("title") or origin.stem)
        key = str(meta.get("key") or "C")
        mode = str(meta.get("mode") or "minor")
        tempo_bpm = int(meta.get("bpm") or 120)

        inst_roles: Dict[str, str] = {}
        inst_has_v2 = False
        for inst in data.get("instruments") or []:
            iid = str(inst.get("id") or "")
            if iid:
                inst_roles[iid] = _infer_role_from_ai_character(str(inst.get("character") or ""))
            if inst.get("catalog_id"):
                inst_has_v2 = True

        for pat in data.get("patterns") or []:
            ch_map = pat.get("channels") or {}
            has_zero = any(str(k).strip() == "0" for k in ch_map.keys())
            for raw_ch, events in ch_map.items():
                ch_idx = _normalize_ai_channel_idx(raw_ch, has_zero=has_zero)
                for ev in events or []:
                    midi = note_name_to_midi(ev.get("note"))
                    if midi is None:
                        continue
                    dur = max(1, int(ev.get("duration") or 1))
                    pitches_by_ch[ch_idx].append(midi)
                    durs_by_ch[ch_idx].append(dur)
                    ev_inst = str(ev.get("instrument") or "")
                    if ev_inst in inst_roles:
                        roles_by_ch[ch_idx].append(inst_roles[ev_inst])

        v2_reasons: List[str] = []
        if inst_has_v2:
            v2_reasons.append("AI composition specifies explicit catalog_id")
        source_kind = "ai-composition"
        default_roles = {1: "melody", 2: "harmony", 3: "bass", 4: "percussion"}
    elif "patterns" in data and ("uses_16bit_bass" in data or "tempo_bpm" in data):
        uses_16bit_bass = bool(data.get("uses_16bit_bass", False))
        title = str(data.get("title") or origin.stem)
        key = str(data.get("key") or "C")
        mode = str(data.get("mode") or "minor")
        tempo_bpm = int(data.get("tempo_bpm") or 120)

        ir_instruments = data.get("instruments") or []
        inst_by_id: Dict[int, Mapping[str, Any]] = {
            int(inst["id"]): inst for inst in ir_instruments if "id" in inst
        }
        v2_reasons = []
        if data.get("initial_channel_instruments") is not None:
            v2_reasons.append("IR specifies initial_channel_instruments")
        for inst in ir_instruments:
            macro = inst.get("macro") or []
            if any(isinstance(step, dict) and (step.get("distortion") is not None or step.get("audf_offset", 0) != 0 or step.get("fixed_audf") is not None) for step in macro):
                v2_reasons.append(f"instrument {inst.get('name', inst.get('id'))!r} carries a v2 macro")
            pe = inst.get("pitch_envelope")
            if isinstance(pe, dict) and int(pe.get("duration_frames") or 0) > 0:
                v2_reasons.append(f"instrument {inst.get('name', inst.get('id'))!r} carries a v2 pitch envelope")

        init_ch = data.get("initial_channel_instruments") or {}
        for pat in data.get("patterns") or []:
            tracks = pat.get("tracks") or {}
            for raw_ch, notes in tracks.items():
                ch_idx = int(raw_ch)
                if ch_idx not in (1, 2, 3, 4):
                    continue
                if str(ch_idx) in init_ch:
                    init_idx = int(init_ch[str(ch_idx)])
                    if 0 <= init_idx < len(ir_instruments):
                        r = str(ir_instruments[init_idx].get("role") or "").lower()
                        if r:
                            roles_by_ch[ch_idx].append(r)
                for note in notes or []:
                    if note.get("pending_program_changes"):
                        v2_reasons.append(f"channel {ch_idx} contains explicit PROGRAM_CHANGE commands")
                    if bool(note.get("is_rest", False)):
                        continue
                    midi = note.get("midi_pitch")
                    if midi is None:
                        midi = note_name_to_midi(note.get("pitch"))
                    if midi is None:
                        continue
                    dur = max(1, int(note.get("duration") or 1))
                    pitches_by_ch[ch_idx].append(int(midi))
                    durs_by_ch[ch_idx].append(dur)
                    nid = int(note.get("instrument_id", 0))
                    if nid in inst_by_id:
                        r = str(inst_by_id[nid].get("role") or "").lower()
                        if r:
                            roles_by_ch[ch_idx].append(r)

        source_kind = "pokey-ir"
        default_roles = {1: "bass", 2: "harmony", 3: "melody", 4: "percussion"}
    else:
        raise ValueError(
            f"Unsupported JSON schema in '{origin}': expected 'atari-music-composition' or POKEY IR 'IRSong'."
        )

    channels: Dict[int, ChannelAnalysis] = {
        ch: _summarize_channel_stats(
            ch,
            uses_16bit_bass=uses_16bit_bass,
            pitches=pitches_by_ch[ch],
            durations=durs_by_ch[ch],
            roles_seen=roles_by_ch[ch],
            default_role=default_roles[ch],
        )
        for ch in range(1, 5)
    }
    channels = _refine_channel_roles(channels, uses_16bit_bass=uses_16bit_bass)

    return CompositionAnalysis(
        source_path=origin,
        source_kind=source_kind,
        title=title,
        key=key,
        mode=mode,
        tempo_bpm=tempo_bpm,
        uses_16bit_bass=uses_16bit_bass,
        v1_compatible=(len(v2_reasons) == 0),
        v2_required_reasons=tuple(dict.fromkeys(v2_reasons)),
        channels=channels,
    )


def score_instrument_for_channel(
    inst: CatalogInstrumentInfo,
    ch_info: ChannelAnalysis,
    comp: CompositionAnalysis,
) -> Tuple[float, Tuple[str, ...]]:
    """Evaluate hardware compatibility and musical fit of *inst* for *ch_info*."""
    if not ch_info.active:
        return -1.0, ("channel inactive or reserved",)

    if not inst.compatible:
        return -1.0, (f"incompatible status={inst.status}",)

    if ch_info.channel not in inst.channels_allowed:
        return -1.0, (f"channel {ch_info.channel} not in channels_allowed={list(inst.channels_allowed)}",)

    if comp.uses_16bit_bass and ch_info.channel == 1:
        if inst.divider_mode != "16bit_ch12" or "bass" not in inst.intended_roles:
            return -1.0, ("CH1 requires 16bit_ch12 bass instrument when uses_16bit_bass=True",)
    else:
        if inst.divider_mode != "8bit":
            return -1.0, (f"divider_mode={inst.divider_mode!r} excluded on channel {ch_info.channel}",)

    role = ch_info.role
    if role == "bass" and "bass" not in inst.intended_roles:
        return -1.0, ("non-bass instrument excluded from bass channel",)
    if role == "percussion" and not any(r in inst.intended_roles for r in ("percussion", "rhythm")):
        return -1.0, ("non-percussion instrument excluded from percussion channel",)
    if role == "melody" and "melody" not in inst.intended_roles:
        return -1.0, ("instrument does not support 'melody' role",)
    if role == "harmony" and not any(r in inst.intended_roles for r in ("harmony", "melody")):
        return -1.0, ("instrument does not support 'harmony' or 'melody' role",)

    score = 0.0
    reasons: List[str] = []

    # 1. Exact role match bonus
    if role in inst.intended_roles:
        score += 20.0
        reasons.append(f"exact role '{role}' (+20.0)")
    else:
        score += 8.0
        reasons.append(f"compatible role fallback {list(inst.intended_roles)} (+8.0)")

    # 2. MIDI range coverage & center alignment
    if ch_info.midi_min is not None and ch_info.midi_max is not None:
        low, high = inst.midi_range
        if ch_info.midi_min >= low and ch_info.midi_max <= high:
            score += 40.0
            reasons.append(f"MIDI {ch_info.midi_min}..{ch_info.midi_max} fits [{low}..{high}] (+40.0)")
        else:
            below = max(0, low - ch_info.midi_min)
            above = max(0, ch_info.midi_max - high)
            penalty = min(45.0, float((below + above) * 3))
            score += 20.0 - penalty
            reasons.append(
                f"MIDI {ch_info.midi_min}..{ch_info.midi_max} exceeds [{low}..{high}] by {below + above} st ({20.0 - penalty:+.1f})"
            )

        if ch_info.midi_median is not None and high > low:
            center = (low + high) / 2.0
            half_span = max(1.0, (high - low) / 2.0)
            closeness = max(0.0, 1.0 - abs(ch_info.midi_median - center) / half_span)
            center_pts = round(closeness * 10.0, 1)
            score += center_pts
            reasons.append(f"register center match (+{center_pts:.1f})")

    # 3. 8-bit bass clock realism (64 kHz saturates below MIDI ~47; 15 kHz reaches MIDI 28 cleanly)
    if role == "bass" and not comp.uses_16bit_bass and ch_info.midi_min is not None:
        if ch_info.midi_min < 36 and inst.preferred_clock_hz == "15khz":
            score += 18.0
            reasons.append("15kHz clock handles sub-MIDI-36 bass cleanly (+18.0)")
        elif ch_info.midi_min < 46 and inst.preferred_clock_hz == "15khz":
            score += 12.0
            reasons.append("15kHz clock avoids 8-bit bass octave detuning (+12.0)")
        elif ch_info.midi_min >= 40 and ch_info.short_note_ratio >= 0.45 and inst.instrument_id == "bass_poly4_punch":
            score += 12.0
            reasons.append("punchy poly4 fits staccato upper bass (+12.0)")

    # 4. 16-bit bass timbre vs register/density
    if role == "bass" and comp.uses_16bit_bass and ch_info.midi_min is not None and ch_info.midi_max is not None:
        if ch_info.midi_max <= 55 and ch_info.avg_duration >= 3.5 and inst.instrument_id == "bass_16bit_poly5_growl":
            score += 8.0
            reasons.append("low sustained bass suits 16-bit Poly5 growl (+8.0)")
        elif inst.instrument_id == "bass_16bit_pure":
            score += 6.0
            reasons.append("pure 16-bit square provides widest clean bass coverage (+6.0)")

    # 5. Melody & harmony articulation / envelope fit
    if role in ("melody", "harmony"):
        iid = inst.instrument_id
        fast_line = ch_info.avg_duration <= 2.8 or ch_info.short_note_ratio >= 0.55
        sustained_line = ch_info.avg_duration >= 4.0 and ch_info.short_note_ratio < 0.40
        if fast_line:
            if role == "harmony" and iid == "harmony_soft_square":
                score += 12.0
                reasons.append(f"soft square pad fits harmony accompaniment avg_dur={ch_info.avg_duration:.1f} (+12.0)")
            elif iid in ("lead_pure_pluck", "lead_attack_bite", "lead_c1_octave_pulse"):
                score += 15.0
                reasons.append(f"crisp/short envelope suits fast notes avg_dur={ch_info.avg_duration:.1f} (+15.0)")
            elif iid == "lead_pure_sustain":
                score += 4.0
                reasons.append("sustain envelope acceptable fallback on fast line (+4.0)")
        elif sustained_line:
            if iid in ("lead_pure_sustain", "harmony_soft_square", "lead_buzz_steady"):
                score += 15.0
                reasons.append(f"sustain envelope suits long notes avg_dur={ch_info.avg_duration:.1f} (+15.0)")
            elif iid == "lead_attack_bite":
                score += 9.0
                reasons.append("transient bite + sustain suits melodic line (+9.0)")
        else:
            if iid in ("lead_attack_bite", "lead_pure_sustain", "lead_c1_octave_pulse", "harmony_soft_square"):
                score += 12.0
                reasons.append(f"balanced envelope fits avg_dur={ch_info.avg_duration:.1f} (+12.0)")
            else:
                score += 7.0
                reasons.append("compatible melodic timbre (+7.0)")

    # 6. Percussion rhythm & pitch-variety fit
    if role == "percussion":
        iid = inst.instrument_id
        if ch_info.distinct_pitches >= 3:
            if iid == "perc_tom_pitched":
                score += 18.0
                reasons.append(f"{ch_info.distinct_pitches} distinct pitches favor pitched tom (+18.0)")
            elif iid == "perc_kick_tight":
                score += 11.0
                reasons.append("multi-pitch rhythm works with tight kick (+11.0)")
            else:
                score += 7.0
                reasons.append("percussion macro compatible (+7.0)")
        elif ch_info.avg_duration <= 1.8 or ch_info.short_note_ratio >= 0.70:
            if iid == "perc_hihat_closed":
                score += 16.0
                reasons.append(f"dense fast hits avg_dur={ch_info.avg_duration:.1f} favor closed hi-hat (+16.0)")
            elif iid == "perc_snare_crisp":
                score += 14.0
                reasons.append("crisp noise snare fits brisk rhythm (+14.0)")
            else:
                score += 8.0
                reasons.append("percussion macro compatible (+8.0)")
        else:
            if iid == "perc_snare_crisp":
                score += 15.0
                reasons.append("crisp snare provides versatile general backbeat (+15.0)")
            elif iid == "perc_kick_tight":
                score += 13.0
                reasons.append("tight kick anchors steady beat (+13.0)")
            else:
                score += 9.0
                reasons.append("percussion macro compatible (+9.0)")

    return round(score, 2), tuple(reasons)


def _short_token(instrument_id: str) -> str:
    """Return a concise filesystem-safe slug token for *instrument_id*."""
    if instrument_id in _SHORT_TOKEN_MAP:
        return _SHORT_TOKEN_MAP[instrument_id]
    return re.sub(r"[^a-z0-9]+", "", instrument_id.lower())[:12] or "inst"


def _combo_is_hardware_compatible(assigned: Mapping[int, CatalogInstrumentInfo]) -> bool:
    """Verify cross-channel AUDCTL compatibility across all instruments in a variant."""
    req_audctl = 0
    forb_audctl = 0
    for inst in assigned.values():
        req_audctl |= inst.required_audctl_bits
        forb_audctl |= inst.forbidden_audctl_bits
    return (req_audctl & forb_audctl) == 0


def _build_variant_slug(
    comp: CompositionAnalysis,
    assigned: Mapping[int, CatalogInstrumentInfo],
) -> str:
    """Construct a readable slug ordered by role (bass, lead/harmony, perc)."""
    role_priority = {"bass": 0, "melody": 1, "harmony": 2, "percussion": 3}
    ordered_channels = sorted(
        assigned.keys(),
        key=lambda ch: (role_priority.get(comp.channels[ch].role, 9), ch),
    )
    tokens: List[str] = []
    seen_roles: set[str] = set()
    for ch in ordered_channels:
        role = comp.channels[ch].role
        if role == "harmony" and "melody" in seen_roles and len(ordered_channels) >= 3:
            # Keep filename compact by prioritizing bass, lead, perc when 4 channels active
            continue
        seen_roles.add(role)
        tokens.append(_short_token(assigned[ch].instrument_id))
    return "_".join(tokens) if tokens else "arranged"


def score_all_channels(
    comp: CompositionAnalysis,
    catalog: Sequence[CatalogInstrumentInfo],
) -> Dict[int, List[ScoredCandidate]]:
    """Score and sort all compatible catalog candidates for each active channel."""
    out: Dict[int, List[ScoredCandidate]] = {}
    for ch in sorted(comp.channels):
        ch_info = comp.channels[ch]
        if not ch_info.active:
            out[ch] = []
            continue
        scored: List[ScoredCandidate] = []
        for inst in catalog:
            pts, reasons = score_instrument_for_channel(inst, ch_info, comp)
            if pts >= 0.0:
                scored.append(ScoredCandidate(instrument=inst, score=pts, reasons=reasons))
        scored.sort(key=lambda c: (-c.score, c.instrument.instrument_id))
        out[ch] = scored
    return out


def build_ranked_variants(
    comp: CompositionAnalysis,
    scored_by_channel: Mapping[int, List[ScoredCandidate]],
    *,
    max_variants: int = DEFAULT_MAX_VARIANTS,
    include_vanilla: bool = True,
) -> List[PlannedVariant]:
    """Select up to *max_variants* top-ranked diverse ``v2`` variants plus ``vanilla`` (``v1``)."""
    active_channels = [ch for ch in sorted(comp.channels) if comp.channels[ch].active and scored_by_channel.get(ch)]
    if not active_channels:
        raise RuntimeError(f"No compatible catalog instruments found for any active channel in '{comp.source_path}'.")

    # Limit per-channel pool to keep Cartesian product bounded while preserving rich variety
    pool_limits = {"bass": 2, "melody": 5, "harmony": 3, "percussion": 4}
    pools: List[List[ScoredCandidate]] = []
    for ch in active_channels:
        limit = pool_limits.get(comp.channels[ch].role, 4)
        pools.append(scored_by_channel[ch][:limit])

    raw_combos: List[Tuple[float, Dict[int, ScoredCandidate]]] = []
    for choice_tuple in product(*pools):
        ch_cand_map = {ch: cand for ch, cand in zip(active_channels, choice_tuple)}
        inst_map = {ch: cand.instrument for ch, cand in ch_cand_map.items()}
        if not _combo_is_hardware_compatible(inst_map):
            continue
        base_score = sum(cand.score for cand in ch_cand_map.values())
        # Mild penalty if two melodic/harmony channels use identical instrument when alternatives exist
        used_ids = [inst.instrument_id for inst in inst_map.values()]
        dup_penalty = 6.0 * (len(used_ids) - len(set(used_ids)))
        total = round(base_score - dup_penalty, 2)
        raw_combos.append((total, ch_cand_map))

    if not raw_combos:
        raise RuntimeError("No hardware-compatible cross-channel instrument combinations found.")

    # Greedy diversity-preserving selection
    remaining = list(raw_combos)
    selected: List[Tuple[float, Dict[int, ScoredCandidate]]] = []
    usage_counts: Dict[Tuple[int, str], int] = {}
    role_div_weight = {"melody": 9.0, "bass": 7.5, "percussion": 5.0, "harmony": 4.0}

    while remaining and len(selected) < max_variants:
        best_idx = 0
        best_effective = -1e9
        for idx, (base_score, ch_map) in enumerate(remaining):
            penalty = sum(
                role_div_weight.get(comp.channels[ch].role, 5.0) * usage_counts.get((ch, cand.instrument.instrument_id), 0)
                for ch, cand in ch_map.items()
            )
            eff = base_score - penalty
            key_tie = tuple(ch_map[ch].instrument.instrument_id for ch in active_channels)
            best_tie = tuple(remaining[best_idx][1][ch].instrument.instrument_id for ch in active_channels)
            if eff > best_effective or (eff == best_effective and key_tie < best_tie):
                best_effective = eff
                best_idx = idx
        chosen_score, chosen_map = remaining.pop(best_idx)
        selected.append((chosen_score, chosen_map))
        for ch, cand in chosen_map.items():
            usage_counts[(ch, cand.instrument.instrument_id)] = usage_counts.get((ch, cand.instrument.instrument_id), 0) + 1

    # Strict descending rank order by true composition fitness score
    selected.sort(
        key=lambda item: (-item[0], tuple(item[1][ch].instrument.instrument_id for ch in active_channels))
    )

    planned: List[PlannedVariant] = []
    used_slugs: Dict[str, int] = {}
    for rank_idx, (total_score, ch_map) in enumerate(selected, start=1):
        inst_map = {ch: cand.instrument for ch, cand in ch_map.items()}
        slug = _build_variant_slug(comp, inst_map)
        count = used_slugs.get(slug, 0) + 1
        used_slugs[slug] = count
        if count > 1:
            slug = f"{slug}_{count}"
        name = f"{rank_idx:02d}_{slug}"
        notes = tuple(
            f"CH{ch}({comp.channels[ch].role}): {cand.instrument.instrument_id} [{cand.score:.1f} pts]"
            for ch, cand in sorted(ch_map.items())
        )
        planned.append(
            PlannedVariant(
                rank=rank_idx,
                name=name,
                player_version="v2",
                channel_instruments={ch: cand.instrument.instrument_id for ch, cand in sorted(ch_map.items())},
                channel_scores={ch: cand.score for ch, cand in sorted(ch_map.items())},
                total_score=total_score,
                selection_notes=notes,
            )
        )

    if include_vanilla:
        vanilla_notes = (
            ("Original composition instruments compiled with legacy v1 player",)
            if comp.v1_compatible
            else tuple(f"v1 skipped: {r}" for r in comp.v2_required_reasons)
        )
        planned.append(
            PlannedVariant(
                rank=None,
                name="vanilla",
                player_version="v1",
                channel_instruments={},
                channel_scores={},
                total_score=0.0,
                selection_notes=vanilla_notes,
            )
        )

    return planned


def format_log_report(
    comp: CompositionAnalysis,
    atari_music_exe: Path,
    mads_exe: Path,
    output_dir: Path,
    catalog: Sequence[CatalogInstrumentInfo],
    scored_by_channel: Mapping[int, List[ScoredCandidate]],
    results: Sequence[VariantRunResult],
) -> str:
    """Format detailed human-readable arrangement matching and execution log."""
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append("ATARI MUSIC COMPOSER - SMART BATCH ARRANGEMENT LOG")
    lines.append("=" * 78)
    lines.append(f"Timestamp:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"Input file:  {comp.source_path} (kind={comp.source_kind})")
    lines.append(f"Output dir:  {output_dir}")
    lines.append(f"CLI tool:    {atari_music_exe}")
    lines.append(f"MADS:        {mads_exe}")
    lines.append("")
    lines.append("[COMPOSITION PROFILE]")
    lines.append(f"  Title:      {comp.title}")
    lines.append(f"  Key / Mode: {comp.key} {comp.mode}")
    lines.append(f"  Tempo:      {comp.tempo_bpm} BPM")
    lines.append(f"  Bass mode:  {'16-bit CH1+CH2 joined' if comp.uses_16bit_bass else '8-bit independent channels'}")
    lines.append(f"  v1 compat:  {'Yes' if comp.v1_compatible else 'No (' + '; '.join(comp.v2_required_reasons) + ')'}")
    lines.append(f"  Catalog:    {len(catalog)} compatible instruments queried from atari-music.exe")
    lines.append("")
    lines.append("[CHANNEL ANALYSIS]")
    for ch in range(1, 5):
        c = comp.channels[ch]
        if c.reserved_for_16bit:
            lines.append(f"  CH{ch}: [RESERVED] Paired with CH1 for 16-bit bass")
        elif not c.active:
            lines.append(f"  CH{ch}: [INACTIVE] 0 notes")
        else:
            lines.append(
                f"  CH{ch}: role={c.role:<10} notes={c.note_count:<4} "
                f"midi={c.midi_min}..{c.midi_max} (med={c.midi_median:.1f}) "
                f"avg_dur={c.avg_duration:.2f} short_ratio={c.short_note_ratio:.2f} "
                f"distinct_pitches={c.distinct_pitches}"
            )
    lines.append("")
    lines.append("[PER-CHANNEL CANDIDATE RANKINGS]")
    for ch in range(1, 5):
        cands = scored_by_channel.get(ch, [])
        if not cands:
            continue
        lines.append(f"  Channel {ch} (detected role: {comp.channels[ch].role}):")
        for cand in cands:
            reason_str = "; ".join(cand.reasons)
            lines.append(f"    - {cand.instrument.instrument_id:<24} score={cand.score:5.1f} | {reason_str}")
    lines.append("")
    lines.append("[SELECTED RANKED VARIANTS & EXECUTION]")
    for res in results:
        v = res.variant
        rank_label = f"#{v.rank:02d}" if v.rank is not None else "BASELINE"
        score_str = f"score={v.total_score:.1f}" if v.rank is not None else "player=v1"
        lines.append(f"  [{v.name}] ({rank_label}, {score_str}, status={res.status})")
        if v.channel_instruments:
            for ch, inst_id in sorted(v.channel_instruments.items()):
                ch_pts = v.channel_scores.get(ch, 0.0)
                lines.append(f"    CH{ch} ({comp.channels[ch].role}): {inst_id} ({ch_pts:.1f} pts)")
        else:
            for note in v.selection_notes:
                lines.append(f"    {note}")
        if res.command:
            lines.append(f"    CMD: {' '.join(res.command)}")
        if res.message:
            lines.append(f"    NOTE: {res.message}")
        if res.status == "OK":
            lines.append(f"    OUT: {res.wav_path.name} ({res.wav_bytes} B), {res.xex_path.name} ({res.xex_bytes} B)")
    lines.append("")
    return "\n".join(lines)


def build_arrange_command(
    atari_music_exe: Path,
    input_json_path: Path,
    variant: PlannedVariant,
    wav_path: Path,
    xex_path: Path,
    mads_exe: Path,
) -> List[str]:
    """Construct exact ``atari-music.exe arrange`` CLI command for *variant*."""
    cmd: List[str] = [str(atari_music_exe), "arrange", str(input_json_path)]
    for ch, inst_id in sorted(variant.channel_instruments.items()):
        cmd.extend(["--channel-instrument", f"{ch}={inst_id}"])
    if variant.channel_instruments:
        cmd.extend(["--program-change-policy", "replace"])
    cmd.extend(
        [
            "--player-version",
            variant.player_version,
            "--output-wav",
            str(wav_path),
            "-o",
            str(xex_path),
            "--mads",
            str(mads_exe),
        ]
    )
    return cmd


def execute_batch(
    *,
    input_file: Path,
    output_dir: Path,
    mads_path: Optional[Path] = None,
    atari_music_path: Optional[Path] = None,
    max_variants: int = DEFAULT_MAX_VARIANTS,
    include_vanilla: bool = True,
    log_file: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Tuple[int, Path]:
    """Run full catalog discovery, composition profiling, ranking, compilation, and logging."""
    input_resolved = input_file.expanduser().resolve()
    if not input_resolved.is_file():
        raise FileNotFoundError(f"Input composition not found: {input_resolved}")

    output_resolved = output_dir.expanduser().resolve()
    log_resolved = log_file.expanduser().resolve() if log_file is not None else (output_resolved / LOG_FILENAME)

    atari_exe = resolve_atari_music_exe(atari_music_path)
    mads_exe = resolve_mads_exe(mads_path, allow_missing=dry_run)

    print("")
    print("Atari Music Composer - Smart Batch Arrangement")
    print("----------------------------------------------")
    rc_ver, ver_out, ver_err = _run_subprocess([str(atari_exe), "--version"])
    if rc_ver != 0:
        raise RuntimeError(f"CLI '{atari_exe}' failed '--version' check (exit code {rc_ver}): {ver_err}")
    print(f"CLI:      {atari_exe} ({ver_out.strip()})")
    print(f"Input:    {input_resolved}")
    print(f"Output:   {output_resolved}")
    print(f"MADS:     {mads_exe}")

    catalog = query_catalog_instruments(atari_exe)
    print(f"Catalog:  {len(catalog)} compatible xex_v2 instruments discovered")

    with tempfile.TemporaryDirectory(prefix="atari_music_batch_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        if input_resolved.suffix.lower() == ".dsl":
            arrange_input = tmp_dir / f"{input_resolved.stem}.json"
            print("Step:     Converting Music DSL -> temporary JSON via import-dsl...")
            dsl_rc, dsl_out, dsl_err = _run_subprocess(
                [str(atari_exe), "import-dsl", str(input_resolved), "--output-json", str(arrange_input)]
            )
            if dsl_rc != 0 or not arrange_input.is_file():
                raise RuntimeError(
                    f"Failed to convert DSL '{input_resolved}' (exit code {dsl_rc}):\n{dsl_err or dsl_out}"
                )
        else:
            arrange_input = input_resolved

        comp = analyze_composition(arrange_input, source_path=input_resolved)
        print(
            f"Detected: '{comp.title}' ({comp.key} {comp.mode}, {comp.tempo_bpm} BPM, "
            f"{'16-bit CH1+CH2 bass' if comp.uses_16bit_bass else '8-bit bass'})"
        )
        for ch in range(1, 5):
            ci = comp.channels[ch]
            if ci.active:
                print(f"  CH{ch}: {ci.role} (MIDI {ci.midi_min}..{ci.midi_max}, avg_dur={ci.avg_duration:.1f}, n={ci.note_count})")
            elif ci.reserved_for_16bit:
                print(f"  CH{ch}: reserved for 16-bit CH1+CH2 bass")

        scored = score_all_channels(comp, catalog)
        variants = build_ranked_variants(
            comp,
            scored,
            max_variants=max_variants,
            include_vanilla=include_vanilla,
        )

        output_resolved.mkdir(parents=True, exist_ok=True)
        run_results: List[VariantRunResult] = []
        failed_count = 0

        for var in variants:
            wav_path = output_resolved / f"{var.name}.wav"
            xex_path = output_resolved / f"{var.name}.xex"
            print(f"\n[{var.name}] ({var.player_version}, score={var.total_score:.1f})")
            for note in var.selection_notes:
                print(f"  {note}")

            if var.player_version == "v1" and not comp.v1_compatible:
                msg = "Composition requires v2 features; skipping legacy v1 baseline."
                print(f"  SKIPPED - {msg}")
                run_results.append(
                    VariantRunResult(
                        variant=var,
                        status="SKIPPED",
                        command=(),
                        exit_code=None,
                        wav_path=wav_path,
                        xex_path=xex_path,
                        wav_bytes=0,
                        xex_bytes=0,
                        message=msg,
                    )
                )
                continue

            cmd = build_arrange_command(atari_exe, arrange_input, var, wav_path, xex_path, mads_exe)
            if dry_run:
                print(f"  DRY_RUN: {' '.join(cmd)}")
                run_results.append(
                    VariantRunResult(
                        variant=var,
                        status="DRY_RUN",
                        command=tuple(cmd),
                        exit_code=None,
                        wav_path=wav_path,
                        xex_path=xex_path,
                        wav_bytes=0,
                        xex_bytes=0,
                        message="dry-run enabled",
                    )
                )
                continue

            if not force and (wav_path.exists() or xex_path.exists()):
                msg = "Output already exists (pass --force to overwrite)."
                print(f"  SKIPPED - {msg}")
                run_results.append(
                    VariantRunResult(
                        variant=var,
                        status="SKIPPED",
                        command=tuple(cmd),
                        exit_code=None,
                        wav_path=wav_path,
                        xex_path=xex_path,
                        wav_bytes=wav_path.stat().st_size if wav_path.is_file() else 0,
                        xex_bytes=xex_path.stat().st_size if xex_path.is_file() else 0,
                        message=msg,
                    )
                )
                continue

            rc, out_txt, _ = _run_subprocess(cmd, stream_output=True)
            wav_ok = wav_path.is_file() and wav_path.stat().st_size > 0
            xex_ok = xex_path.is_file() and xex_path.stat().st_size > 0
            if rc == 0 and wav_ok and xex_ok:
                run_results.append(
                    VariantRunResult(
                        variant=var,
                        status="OK",
                        command=tuple(cmd),
                        exit_code=rc,
                        wav_path=wav_path,
                        xex_path=xex_path,
                        wav_bytes=wav_path.stat().st_size,
                        xex_bytes=xex_path.stat().st_size,
                    )
                )
            else:
                failed_count += 1
                run_results.append(
                    VariantRunResult(
                        variant=var,
                        status="FAILED",
                        command=tuple(cmd),
                        exit_code=rc,
                        wav_path=wav_path,
                        xex_path=xex_path,
                        wav_bytes=wav_path.stat().st_size if wav_path.is_file() else 0,
                        xex_bytes=xex_path.stat().st_size if xex_path.is_file() else 0,
                        message=f"arrange exited with {rc}" if rc != 0 else "missing or empty WAV/XEX output",
                    )
                )

        log_text = format_log_report(
            comp,
            atari_exe,
            mads_exe,
            output_resolved,
            catalog,
            scored,
            run_results,
        )
        log_resolved.parent.mkdir(parents=True, exist_ok=True)
        log_resolved.write_text(log_text, encoding="utf-8")

    ok_cnt = sum(1 for r in run_results if r.status == "OK")
    skip_cnt = sum(1 for r in run_results if r.status == "SKIPPED")
    dry_cnt = sum(1 for r in run_results if r.status == "DRY_RUN")
    print("\n==============================================")
    print("SUMMARY")
    print("==============================================")
    print(f"Successful: {ok_cnt}")
    if dry_cnt:
        print(f"Dry-run:    {dry_cnt}")
    print(f"Skipped:    {skip_cnt}")
    print(f"Failed:     {failed_count}")
    print(f"Log file:   {log_resolved}")

    return (1 if failed_count > 0 else 0), log_resolved


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser for ``generate_arrangements.py``."""
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a Music DSL (.dsl) or JSON composition, query atari-music.exe "
            "for compatible instruments, rank best-fit arrangements, and render WAV + XEX."
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        "--input-file",
        dest="input_file",
        type=Path,
        required=True,
        help="Path to input .dsl or .json composition.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        "--output-directory",
        dest="output_dir",
        type=Path,
        required=True,
        help="Directory where ranked .wav, .xex, and arrangements.log will be written.",
    )
    parser.add_argument(
        "-m",
        "--mads",
        "--mads-path",
        dest="mads_path",
        type=Path,
        default=None,
        help="Path to mads.exe (default: tools/mads/mads.exe in repo or PATH).",
    )
    parser.add_argument(
        "--atari-music-path",
        type=Path,
        default=None,
        help="Optional explicit path to atari-music.exe.",
    )
    parser.add_argument(
        "--max-variants",
        type=int,
        default=DEFAULT_MAX_VARIANTS,
        help=f"Maximum number of ranked v2 arrangements to generate (default: {DEFAULT_MAX_VARIANTS}).",
    )
    parser.add_argument(
        "--no-vanilla",
        action="store_true",
        help="Skip generating the legacy v1 'vanilla' baseline.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help=f"Optional path to write matching log (default: <output-dir>/{LOG_FILENAME}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze, rank variants, and write arrangements.log without invoking arrange.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite existing .wav and .xex files.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point returning OS exit code."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.max_variants < 1:
        parser.error("--max-variants must be >= 1")
    try:
        exit_code, _ = execute_batch(
            input_file=args.input_file,
            output_dir=args.output_dir,
            mads_path=args.mads_path,
            atari_music_path=args.atari_music_path,
            max_variants=args.max_variants,
            include_vanilla=not args.no_vanilla,
            log_file=args.log_file,
            dry_run=args.dry_run,
            force=args.force,
        )
        return exit_code
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

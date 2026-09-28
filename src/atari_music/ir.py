"""Intermediate Representation (IR) for Procedural Atari POKEY Music.

A compact, symbolic music format that captures musical intent:
Song
├── tempo (BPM / frames_per_tick)
├── instruments (distortion, ADSR envelope, pitch offset, macro)
├── patterns (tracks 1..4 containing pitch, duration, volume, role, rest, ornaments)
└── sequence (order list of pattern indices)

Compiled to:
1. 50 Hz POKEY register frames (AUDF1..4, AUDC1..4, AUDCTL)
2. Compact 6502 tracker binary representation (< 2 KB budget)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_PURE_TONE,
    NOTE_NAMES,
    PAL_64KHZ_CLOCK,
)


class IREnvelope(BaseModel):
    """ADSR Volume Envelope in 50 Hz frames."""
    attack_frames: int = Field(default=1, ge=0)
    decay_frames: int = Field(default=3, ge=0)
    sustain_vol: int = Field(default=8, ge=0, le=15)
    release_frames: int = Field(default=2, ge=0)


class IRMacroStep(BaseModel):
    """Micro-envelope step for percussion or ornaments.

    RESERVED — not rendered and not exported. The 6502 player sets AUDC once per
    channel and has no per-frame pitch modulation, and the tracker format has no
    macro encoding, so macro steps would make the WAV preview diverge from what the
    Atari actually plays (see ``_render_note_to_frames``). Percussion is still
    audible because an unpitched hit now falls back to
    ``pokey_hw.PERCUSSION_DEFAULT_AUDF`` with the instrument's own distortion and
    envelope; only the per-step sweep/volume ramp is missing.
    """
    audf_offset: int = 0
    distortion: int = DISTORTION_PURE_TONE
    volume: int = 15


class IRInstrument(BaseModel):
    """POKEY Instrument Definition."""
    id: int
    name: str
    distortion: int = DISTORTION_PURE_TONE
    role: str = "melody"  # "melody", "bass", "harmony", "percussion"
    envelope: IREnvelope = Field(default_factory=IREnvelope)
    macro: Optional[List[IRMacroStep]] = None  # RESERVED: not rendered/exported, see IRMacroStep
    vibrato_depth: int = 0
    vibrato_speed: int = 0
    is_16bit: bool = False


class IRNote(BaseModel):
    """A symbolic note event inside a pattern track."""
    pitch: Optional[str] = None  # e.g. "C-4", "A-3", None for rest/hit
    midi_pitch: Optional[int] = None  # 0..127, e.g. 60 = C-4
    duration: int = 1  # duration in rows/ticks
    volume: int = 15  # 0..15 velocity / peak volume
    distortion: Optional[int] = None  # optional override
    instrument_id: int = 0
    channel_role: str = "melody"
    is_rest: bool = False
    slide_semitones: int = 0
    arpeggio_offsets: List[int] = Field(default_factory=list)


class IRPattern(BaseModel):
    """Pattern containing 4 tracks across a fixed number of rows (typically 16 or 32)."""
    id: int
    name: str = ""
    rows: int = 16
    # Channel index 1..4 -> list of notes covering total rows
    tracks: Dict[int, List[IRNote]] = Field(default_factory=dict)


class IRSong(BaseModel):
    """Complete Symbolic Intermediate Representation of an Atari POKEY song."""
    title: str
    author: str = "POKEY Procedural Engine"
    tempo_bpm: int = 125
    frames_per_tick: int = 4  # 4 frames = 80 ms per row at 50 Hz
    key: str = "C"
    mode: str = "minor"
    seed: int = 0
    instruments: List[IRInstrument] = Field(default_factory=list)
    patterns: List[IRPattern] = Field(default_factory=list)
    sequence: List[int] = Field(default_factory=list)  # Pattern ID per section/bar
    uses_16bit_bass: bool = False

    def to_json_file(self, path: Path) -> None:
        """Serialize song to pretty JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def from_json_file(cls, path: Path) -> "IRSong":
        """Load song from JSON."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Frequency & AUDF Conversion Utilities
# ---------------------------------------------------------------------------

def midi_to_note_name(midi_num: int) -> str:
    """Convert integer MIDI note number (e.g. 60) to name ('C-4')."""
    octave = (midi_num // 12) - 1
    name = NOTE_NAMES[midi_num % 12]
    return f"{name}-{octave}"


def midi_pitch_to_frequency(midi: int) -> float:
    """Convert MIDI number to frequency in Hz (A4 = 69 = 440 Hz)."""
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def note_name_to_midi(name: str) -> Optional[int]:
    """Parse note name like 'C-4', 'F#3', 'Bb2' to MIDI number."""
    if not name or name.upper() in ("---", "REST", "OFF", "SIL"):
        return None
    cleaned = name.strip().replace("-", "").replace(" ", "")
    if len(cleaned) < 2:
        return None
    
    note_part = cleaned[:-1].upper()
    try:
        octave = int(cleaned[-1])
    except ValueError:
        return None
    
    base_names = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3,
                  "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
                  "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
    if note_part not in base_names:
        return None
    
    return (octave + 1) * 12 + base_names[note_part]


def frequency_to_audf_8bit(freq_hz: float, base_clock: float = PAL_64KHZ_CLOCK) -> int:
    """Calculate 8-bit AUDF register value for a given frequency.

    Delegates to :mod:`atari_music.pokey_hw` so this is the single definition
    shared with the WAV renderer and the MADS exporter.
    """
    if base_clock == PAL_64KHZ_CLOCK:
        return pokey_hw.audf_from_hz_8bit(freq_hz)
    if freq_hz <= 0:
        return 255
    return max(0, min(255, int(round(base_clock / (2.0 * freq_hz))) - 1))


def frequency_to_audf_16bit(freq_hz: float, base_clock: float = PAL_64KHZ_CLOCK) -> Tuple[int, int]:
    """Calculate 16-bit joined AUDF values (low_ch1, high_ch2).

    Hardware divider is ``round(base/(2*f)) - 1`` (offset ``+1``), NOT ``-2``.
    """
    if base_clock == PAL_64KHZ_CLOCK:
        if freq_hz <= 0:
            return 255, 255
        return pokey_hw.split_audf16(pokey_hw.audf16_from_hz(freq_hz))
    if freq_hz <= 0:
        return 255, 255
    divider = max(0, min(65535, int(round(base_clock / (2.0 * freq_hz))) - 1))
    return pokey_hw.split_audf16(divider)


# ---------------------------------------------------------------------------
# IR to POKEY Register Frame Compilation
# ---------------------------------------------------------------------------

def compile_ir_to_pokey_frames(song: IRSong) -> np.ndarray:
    """Compile symbolic IRSong into (total_frames, 9) POKEY register stream.
    
    Columns: AUDF1, AUDC1, AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4, AUDCTL
    Frame rate: PAL 50.0 Hz.
    """
    pattern_map = {p.id: p for p in song.patterns}
    inst_map = {inst.id: inst for inst in song.instruments}

    total_rows = 0
    for pat_id in song.sequence:
        pat = pattern_map.get(pat_id)
        if pat:
            total_rows += pat.rows

    total_frames = total_rows * song.frames_per_tick
    frames = np.zeros((total_frames, 9), dtype=np.uint8)

    # Set AUDCTL flags
    audctl_val = 0
    if song.uses_16bit_bass:
        audctl_val |= AUDCTL_JOIN_1_2_16BIT  # Ch 1 & 2 joined for 16-bit bass
    frames[:, 8] = audctl_val

    # Expand patterns into linear note streams per channel
    # Channel 1..4
    for ch in range(1, 5):
        if song.uses_16bit_bass and ch == 2:
            # Channel 2 is hardware slave to Channel 1 in 16-bit bass mode;
            # already populated during ch=1 rendering.
            continue
        current_frame = 0
        for pat_id in song.sequence:
            pat = pattern_map.get(pat_id)
            if not pat:
                continue
            notes = pat.tracks.get(ch, [])
            row_idx = 0
            for note in notes:
                dur_rows = max(1, note.duration)
                note_frames = dur_rows * song.frames_per_tick
                start_f = current_frame + row_idx * song.frames_per_tick
                end_f = min(total_frames, start_f + note_frames)

                if start_f < total_frames:
                    _render_note_to_frames(
                        frames=frames,
                        ch=ch,
                        start_f=start_f,
                        end_f=end_f,
                        note=note,
                        inst_map=inst_map,
                        song=song,
                    )
                row_idx += dur_rows
            current_frame += pat.rows * song.frames_per_tick

    return frames


def find_pitch_range_issues(song: IRSong) -> List[Dict[str, Any]]:
    """List notes whose pitch cannot be represented in 8-bit POKEY mode.

    Only genuine out-of-range requests are reported (see
    :func:`atari_music.pokey_hw.describe_8bit_range_error`); ordinary AUDF rounding
    is never flagged. Channels joined as 16-bit bass are skipped because that pair
    has a much wider range.
    """
    issues: List[Dict[str, Any]] = []
    for pat in song.patterns:
        for ch, notes in pat.tracks.items():
            if song.uses_16bit_bass and ch in (1, 2):
                continue
            for note in notes:
                if note.is_rest:
                    continue
                midi = note.midi_pitch
                if midi is None and note.pitch:
                    midi = note_name_to_midi(str(note.pitch))
                if midi is None:
                    continue
                info = pokey_hw.describe_8bit_range_error(midi_pitch_to_frequency(midi))
                if info:
                    issues.append({
                        "pattern": pat.name,
                        "channel": ch,
                        "pitch": note.pitch,
                        "midi_pitch": midi,
                        **info,
                    })
    return issues


def _render_note_to_frames(
    frames: np.ndarray,
    ch: int,
    start_f: int,
    end_f: int,
    note: IRNote,
    inst_map: Dict[int, IRInstrument],
    song: IRSong,
) -> None:
    """Render a single note event across frame range into POKEY register buffer."""
    midi_val = note.midi_pitch
    if midi_val is None and note.pitch:
        midi_val = note_name_to_midi(str(note.pitch))
    unpitched_percussion = pokey_hw.is_unpitched_percussion(midi_val, note.channel_role)

    if note.is_rest or (midi_val is None and not unpitched_percussion):
        # Channel is silent
        audc_col = (ch - 1) * 2 + 1
        frames[start_f:end_f, audc_col] = 0
        return

    inst = inst_map.get(note.instrument_id)
    distortion = note.distortion if note.distortion is not None else (inst.distortion if inst else DISTORTION_PURE_TONE)
    peak_vol = min(15, max(0, note.volume))
    note_len = end_f - start_f

    # NOTE: IRNote.vibrato/slide/arpeggio and IRInstrument.macro are intentionally
    # NOT rendered. The 6502 player sets AUDC distortion once per channel and has
    # no per-frame pitch modulation, so applying them here would make the WAV
    # preview diverge from what real hardware plays. They are reserved fields.
    envelope = inst.envelope if inst else IREnvelope()
    volumes = pokey_hw.player_envelope_volumes(
        note_len,
        song.frames_per_tick,
        peak_vol,
        envelope.attack_frames,
        envelope.decay_frames,
        envelope.sustain_vol,
        envelope.release_frames,
    )
    current_freq = 0.0 if unpitched_percussion else midi_pitch_to_frequency(midi_val)

    audf_col = (ch - 1) * 2
    audc_col = (ch - 1) * 2 + 1

    for offset in range(note_len):
        f_idx = start_f + offset
        if f_idx >= end_f:
            break
        vol = volumes[offset]

        if unpitched_percussion:
            # Explicit fallback: a real percussive hit, never an implicit MIDI 60.
            frames[f_idx, audf_col] = pokey_hw.PERCUSSION_DEFAULT_AUDF
            frames[f_idx, audc_col] = (distortion & 0xE0) | vol
        elif song.uses_16bit_bass and (ch in (1, 2)):
            if ch == 1:
                # Channel 1 outputs low byte, muted volume
                div_low, div_hi = frequency_to_audf_16bit(current_freq)
                frames[f_idx, 0] = pokey_hw.clamp_audf_for_tracker(div_low)  # AUDF1
                frames[f_idx, 1] = 0        # AUDC1 (muted)
                frames[f_idx, 2] = pokey_hw.clamp_audf_for_tracker(div_hi)  # AUDF2
                frames[f_idx, 3] = (distortion & 0xE0) | vol  # AUDC2 (active)
        else:
            # Standard 8-bit channel
            audf_val = pokey_hw.clamp_audf_for_tracker(frequency_to_audf_8bit(current_freq))
            frames[f_idx, audf_col] = audf_val
            frames[f_idx, audc_col] = (distortion & 0xE0) | vol


def _calculate_envelope_volume(
    frame_offset: int,
    total_len: int,
    peak_vol: int,
    env: IREnvelope,
    frames_per_tick: int = 4,
) -> int:
    """Envelope volume 0..15 at a given frame offset, matching ``player.asm``.

    Kept as a thin wrapper over :func:`atari_music.pokey_hw.player_envelope_volumes`
    for backward compatibility; prefer the batched call in the frame compiler.
    """
    volumes = pokey_hw.player_envelope_volumes(
        max(1, total_len),
        frames_per_tick,
        peak_vol,
        env.attack_frames,
        env.decay_frames,
        env.sustain_vol,
        env.release_frames,
    )
    idx = max(0, min(len(volumes) - 1, frame_offset))
    return volumes[idx]


# ---------------------------------------------------------------------------
# Compact Binary Representation & Memory Budget Validation (< 2 KB)
# ---------------------------------------------------------------------------

def calculate_ir_binary_size(song: IRSong) -> int:
    """Calculate exact compact 6502 tracker memory footprint in bytes.
    
    Header:
      - tempo_bpm (1B)
      - frames_per_tick (1B)
      - num_instruments (1B)
      - num_patterns (1B)
      - sequence_length (1B)
      - flags (1B: 16bit, etc.)
      Total Header = 6 bytes.
      
    Instruments:
      - distortion (1B)
      - role (1B)
      - ADSR envelope (2B packed)
      - macro length (1B)
      - macro steps (2B per step)
      Average = 6..12 bytes per instrument.
      
    Sequence Order List:
      - 1 byte per sequence step x 4 channels = 4 * len(sequence) bytes.
      
    Patterns:
      - Tracker compact row encoding:
        Note event: Note byte (6 bits pitch, 2 bits flag) + Inst/Vol byte (4 bits inst, 4 bits vol) = 2 bytes.
        Empty / Rest row run (RLE compressed): 1 byte.
    """
    size = 6  # Header

    # Instruments
    for inst in song.instruments:
        size += 5  # distortion, role, env (2B), macro_len
        if inst.macro:
            size += len(inst.macro) * 2

    # Sequence
    size += len(song.sequence) * 4

    # Patterns
    for pat in song.patterns:
        size += 2  # pattern header (rows, track count)
        for ch in range(1, 5):
            notes = pat.tracks.get(ch, [])
            for note in notes:
                if note.is_rest or (not note.pitch and note.midi_pitch is None and note.channel_role != "percussion"):
                    # RLE rest
                    size += 1
                else:
                    # Active note event (Pitch byte + Vol/Inst byte)
                    size += 2
                    if note.arpeggio_offsets or note.slide_semitones != 0:
                        size += 1  # effect byte

    return size

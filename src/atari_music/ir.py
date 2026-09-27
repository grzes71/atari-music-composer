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
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    NOTE_NAMES,
    PAL_64KHZ_CLOCK,
    PAL_CLOCK_HZ,
)


class IREnvelope(BaseModel):
    """ADSR Volume Envelope in 50 Hz frames."""
    attack_frames: int = Field(default=1, ge=0)
    decay_frames: int = Field(default=3, ge=0)
    sustain_vol: int = Field(default=8, ge=0, le=15)
    release_frames: int = Field(default=2, ge=0)


class IRMacroStep(BaseModel):
    """Micro-envelope step for percussion or ornaments."""
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
    macro: Optional[List[IRMacroStep]] = None
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
    """Calculate 8-bit AUDF register value for a given frequency."""
    if freq_hz <= 0:
        return 255
    audf = int(round(base_clock / (2.0 * freq_hz))) - 1
    return max(0, min(255, audf))


def frequency_to_audf_16bit(freq_hz: float, base_clock: float = PAL_64KHZ_CLOCK) -> Tuple[int, int]:
    """Calculate 16-bit joined AUDF values (low_ch1, high_ch2)."""
    if freq_hz <= 0:
        return 255, 255
    div16 = int(round(base_clock / (2.0 * freq_hz))) - 2
    div16 = max(0, min(65535, div16))
    return (div16 & 0xFF), ((div16 >> 8) & 0xFF)


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
    if note.is_rest or (note.midi_pitch is None and not note.pitch and note.channel_role != "percussion"):
        # Channel is silent
        audc_col = (ch - 1) * 2 + 1
        frames[start_f:end_f, audc_col] = 0
        return

    inst = inst_map.get(note.instrument_id)
    distortion = note.distortion if note.distortion is not None else (inst.distortion if inst else DISTORTION_PURE_TONE)
    peak_vol = min(15, max(0, note.volume))
    note_len = end_f - start_f

    # Handle percussion macro if present
    if inst and inst.macro and len(inst.macro) > 0:
        macro_len = len(inst.macro)
        for offset in range(note_len):
            f_idx = start_f + offset
            if f_idx >= end_f:
                break
            step_idx = min(offset, macro_len - 1)
            step = inst.macro[step_idx]
            
            # Apply macro parameters
            audf_col = (ch - 1) * 2
            audc_col = (ch - 1) * 2 + 1
            
            macro_audf = max(0, min(255, step.audf_offset))
            macro_vol = min(15, max(0, step.volume))
            frames[f_idx, audf_col] = macro_audf
            frames[f_idx, audc_col] = (step.distortion & 0xE0) | macro_vol
        return

    # Standard melodic note
    base_midi = note.midi_pitch if note.midi_pitch is not None else (note_name_to_midi(note.pitch or "") or 60)
    envelope = inst.envelope if inst else IREnvelope()

    for offset in range(note_len):
        f_idx = start_f + offset
        if f_idx >= end_f:
            break

        # Calculate ADSR volume
        vol = _calculate_envelope_volume(offset, note_len, peak_vol, envelope)

        # Arpeggio / pitch offsets
        pitch_mod = 0
        if note.arpeggio_offsets and len(note.arpeggio_offsets) > 0:
            arp_idx = (offset // 2) % len(note.arpeggio_offsets)
            pitch_mod += note.arpeggio_offsets[arp_idx]

        # Pitch slide
        if note.slide_semitones != 0 and note_len > 1:
            pitch_mod += int(round(note.slide_semitones * (offset / (note_len - 1))))

        # Vibrato
        if inst and inst.vibrato_depth > 0 and inst.vibrato_speed > 0 and offset > envelope.attack_frames:
            vib_phase = (offset * inst.vibrato_speed * 0.3)
            vib_offset = math.sin(vib_phase) * (inst.vibrato_depth * 0.1)
        else:
            vib_offset = 0.0

        current_freq = midi_pitch_to_frequency(base_midi + pitch_mod + vib_offset)

        audf_col = (ch - 1) * 2
        audc_col = (ch - 1) * 2 + 1

        # Check 16-bit bass pairing (CH1 + CH2)
        if song.uses_16bit_bass and (ch in (1, 2)):
            if ch == 1:
                # Channel 1 outputs low byte, muted volume
                div_low, div_hi = frequency_to_audf_16bit(current_freq)
                frames[f_idx, 0] = div_low  # AUDF1
                frames[f_idx, 1] = 0        # AUDC1 (muted)
                frames[f_idx, 2] = div_hi   # AUDF2
                frames[f_idx, 3] = (distortion & 0xE0) | vol  # AUDC2 (active)
        else:
            # Standard 8-bit channel
            audf_val = frequency_to_audf_8bit(current_freq)
            frames[f_idx, audf_col] = audf_val
            frames[f_idx, audc_col] = (distortion & 0xE0) | vol


def _calculate_envelope_volume(
    frame_offset: int,
    total_len: int,
    peak_vol: int,
    env: IREnvelope,
) -> int:
    """Calculate envelope volume 0..15 at given frame offset."""
    if frame_offset < env.attack_frames:
        # Attack phase: 0 -> peak_vol
        frac = (frame_offset + 1) / max(1, env.attack_frames)
        return int(round(frac * peak_vol))

    decay_pos = frame_offset - env.attack_frames
    if decay_pos < env.decay_frames:
        # Decay phase: peak_vol -> sustain_vol
        frac = decay_pos / max(1, env.decay_frames)
        vol = peak_vol - frac * (peak_vol - env.sustain_vol)
        return int(round(vol))

    # Sustain phase
    remaining = total_len - frame_offset
    if remaining <= env.release_frames:
        # Release phase: sustain_vol -> 0
        frac = remaining / max(1, env.release_frames)
        return int(round(frac * env.sustain_vol))

    return env.sustain_vol


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

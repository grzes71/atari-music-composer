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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    #: A bound profile's measured volume contour: one AUDC volume level (0..15) per VBL
    #: frame, in the order the archaeology measured them. ``None`` means "no contour", which
    #: is the case for every instrument that was not bound, and for the nine profiles whose
    #: measurement carries none.
    #:
    #: It is *applied* by the frame compiler (see ``apply_volume_contour``) as a relative
    #: modulation of the composer's own envelope, never as a replacement for it. It reaches
    #: the WAV preview; the 6502 player cannot express a per-frame volume macro, so the MADS
    #: exporter refuses to export a song while this is set rather than let the preview and the
    #: hardware diverge (see ``mads_exporter``).
    volume_contour: Optional[List[int]] = None
    #: Explicit AUDCTL this instrument requires, when it was bound to a profile whose
    #: hardware configuration is known. ``None`` means "no requirement": the song's own
    #: ``uses_16bit_bass`` flag decides. Requirements of several instruments are OR-ed
    #: (see ``resolve_audctl_mode``); a profile's bits never silently replace another's.
    audctl: Optional[int] = None
    #: Provenance of a bound profile, so an artefact says which profile realized it.
    #: Empty when the instrument was not bound, which is the normal case.
    profile_id: Optional[str] = None
    profile_fingerprint: Optional[str] = None
    #: Per-channel modulation the 6502 player applies to this instrument's divider, as a
    #: descriptor from :mod:`atari_music.pokey_hw`. ``MODULATION_NONE`` (0) for every
    #: instrument the composer produces by itself, which is every instrument that did not
    #: come from a Lead Library entry that declares one.
    #:
    #: ``MODULATION_OCTAVE_PULSE`` is C1: the divider alternates ``N`` / ``N // 2`` once per
    #: 50 Hz frame for the whole note. It reaches both outputs — the WAV frame stream through
    #: :func:`_render_note_to_frames` and the XEX instrument table through
    #: :func:`atari_music.mads_exporter.export_mads_asm` — so the preview and the hardware
    #: cannot disagree about it.
    modulation: int = pokey_hw.MODULATION_NONE



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


def resolve_audctl_mode(song: IRSong) -> int:
    """The AUDCTL byte this song's frame stream uses.

    Three inputs, in this order:

    1. every instrument's explicit ``audctl`` requirement, OR-ed together — a profile
       that needs the 1+2 join and 1.79 MHz contributes ``$50``; a profile that needs
       plain 64 kHz contributes nothing, so it never cancels another instrument's bits;
    2. ``uses_16bit_bass``, which contributes the 1+2 join bit ``$10`` (the Composer's
       own 64 kHz 16-bit bass — unchanged when nothing is bound);
    3. otherwise ``$00``.

    OR-ing is deliberate: AUDCTL is one register for the whole chip, and the bits that
    matter for a channel are independent of the bits that matter for its neighbours.
    Whether a bound profile actually *gets* the configuration it needs is checked
    separately (see ``sound_profiles.binding``), because a set bit can also be a
    conflict.
    """
    audctl_val = 0
    for inst in song.instruments:
        if inst.audctl is not None:
            audctl_val |= int(inst.audctl) & 0xFF
    if song.uses_16bit_bass:
        audctl_val |= AUDCTL_JOIN_1_2_16BIT
    return audctl_val & 0xFF


def frequency_to_audf_8bit(
    freq_hz: float,
    base_clock: float = PAL_64KHZ_CLOCK,
    *,
    audctl: int = 0,
    channel: int = 1,
) -> int:
    """Calculate 8-bit AUDF register value for a given frequency.

    Delegates to :mod:`atari_music.pokey_hw` so this is the single definition
    shared with the WAV renderer and the MADS exporter.

    *audctl* and *channel* select the clock: a channel clocked from the CPU clock
    (1.79 MHz) uses the ``N + 4`` period, the base clocks use ``N + 1``. The default
    (``audctl=0``) is the 64 kHz behaviour every existing caller relied on.
    """
    if base_clock == PAL_64KHZ_CLOCK:
        return pokey_hw.audf_from_hz_8bit(freq_hz, audctl, channel)
    if freq_hz <= 0:
        return 255
    return max(0, min(255, int(round(base_clock / (2.0 * freq_hz))) - 1))


def frequency_to_audf_16bit(
    freq_hz: float,
    base_clock: float = PAL_64KHZ_CLOCK,
    *,
    audctl: int = 0,
    channel: int = 1,
) -> Tuple[int, int]:
    """Calculate 16-bit joined AUDF values (low_ch1, high_ch2).

    Hardware divider is ``round(base/(2*f)) - 1`` (offset ``+1``), NOT ``-2``; a pair
    clocked from the CPU clock uses ``N + 7``. *channel* selects the pair: 1 for
    CH1+CH2, 3 for CH3+CH4.
    """
    if base_clock == PAL_64KHZ_CLOCK:
        if freq_hz <= 0:
            return 255, 255
        return pokey_hw.split_audf16(pokey_hw.audf16_from_hz(freq_hz, audctl, channel))
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

    # Set AUDCTL flags: a bound profile's explicit requirement OR-ed with the song's
    # own 16-bit bass flag (see resolve_audctl_mode). With nothing bound this is
    # exactly the previous $00 / $10 behaviour.
    audctl_val = resolve_audctl_mode(song)
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
                        audctl=audctl_val,
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


#: POKEY register columns per frame row. The row is **interleaved**: one ``AUDF, AUDC`` pair
#: per channel, in channel order, with AUDCTL last — see :func:`_render_note_to_frames`,
#: which writes ``audf_col = (ch - 1) * 2`` and ``audc_col = (ch - 1) * 2 + 1``.
FRAME_COLUMNS = 9

#: The name of each frame column, in row order.
FRAME_COLUMN_NAMES: Tuple[str, ...] = (
    "AUDF1",
    "AUDC1",
    "AUDF2",
    "AUDC2",
    "AUDF3",
    "AUDC3",
    "AUDF4",
    "AUDC4",
    "AUDCTL",
)

#: The AUDC column (carrying distortion and per-frame volume) of one channel.
def audc_column(channel: int) -> int:
    """The frame column holding *channel*'s AUDC register (1..4)."""
    return (int(channel) - 1) * 2 + 1


#: The AUDF column (carrying the channel's divider) of one channel.
def audf_column(channel: int) -> int:
    """The frame column holding *channel*'s AUDF register (1..4)."""
    return (int(channel) - 1) * 2

#: The frame rate every artefact of this project is rendered at (PAL VBL, one register
#: write per frame). The archaeology measures its contours at the same physical rate
#: (``gesture.resolution.frame_period_ms`` ≈ 20.056 ms), so a measured contour frame maps
#: to exactly one register frame and no resampling is invented.
FRAME_RATE_HZ = 50.0


def apply_volume_contour(volumes: Sequence[int], contour: Sequence[int]) -> List[int]:
    """The composer's per-frame envelope, modulated by a profile's measured level contour.

    The profile's ``gesture.volume.runs`` is an **absolute** series of AUDC volume levels
    (0..15) sampled once per VBL frame in the source material. Applying it absolutely would
    delete the composition's dynamics, so it is applied as a **relative** shape:

    ``effective[i] = floor(volumes[i] * contour[i % span] / max(contour) + 0.5)``

    Three properties fall out of that, and all three are what the contract needs:

    * **velocity stays the ceiling.** ``c / max(contour) <= 1``, so no frame is louder than
      the composer's own envelope made it: the contour can only *attenuate*, never boost.
    * **a static contour is an exact no-op.** With every measured level equal, the factor is
      exactly 1 and the composer's envelope comes back unchanged.
    * **the profile's absolute loudness does not leak.** Dividing by the contour's own peak
      makes the shape transferable to any note velocity.

    The span repeats when a note is longer than the measured segment and is truncated when it
    is shorter; the contour restarts at every note onset, because it describes how *one*
    sounding gesture evolved rather than a timeline. ``max(contour) == 0`` (a measured silence)
    leaves the envelope untouched instead of dividing by zero.
    """
    if not contour:
        return list(volumes)
    peak = max(int(level) for level in contour)
    if peak <= 0:
        return list(volumes)
    span = len(contour)
    out: List[int] = []
    for index, volume in enumerate(volumes):
        level = int(contour[index % span])
        scaled = int(volume) * level / peak
        # floor(x + 0.5) rather than round(): banker's rounding would make the mapping
        # depend on the parity of a half-integer, which is not a property of the sound.
        out.append(max(0, min(15, int(scaled + 0.5))))
    return out


def _render_note_to_frames(
    frames: np.ndarray,
    ch: int,
    start_f: int,
    end_f: int,
    note: IRNote,
    inst_map: Dict[int, IRInstrument],
    song: IRSong,
    audctl: int = 0,
) -> None:
    """Render a single note event across frame range into POKEY register buffer.

    *audctl* is the frame stream's AUDCTL, which decides the clock a channel's divider
    is derived under (1.79 MHz uses ``N+4``, a joined pair ``N+7``, the base clocks
    ``N+1``). The composition owns the note; *audctl* only decides how that note is
    realized in registers.
    """
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
    if inst is not None and inst.volume_contour:
        # A bound profile's measured level contour shapes the composer's own envelope; it
        # never replaces it and never exceeds it (see apply_volume_contour).
        volumes = apply_volume_contour(volumes, inst.volume_contour)
    current_freq = 0.0 if unpitched_percussion else midi_pitch_to_frequency(midi_val)

    audf_col = (ch - 1) * 2
    audc_col = (ch - 1) * 2 + 1

    # C1: the divider moves inside the note. Only a channel with its own 8-bit divider can
    # carry it -- a joined 16-bit pair has one divider in two bytes and no paired form of the
    # rule, which is why the exporter refuses such a song rather than exporting an
    # approximation. A frame the channel is not sounding keeps the note's nominal divider,
    # which is what Experiment 28's ``apply_c1`` does: it never writes a register the baseline
    # did not write, and the player's ``apply_modulation`` gates on the same condition.
    modulating = bool(inst is not None and pokey_hw.is_octave_pulse(inst.modulation))

    for offset in range(note_len):
        f_idx = start_f + offset
        if f_idx >= end_f:
            break
        vol = volumes[offset]

        if unpitched_percussion:
            audf_val = pokey_hw.PERCUSSION_DEFAULT_AUDF
            if modulating and vol:
                audf_val = pokey_hw.octave_pulse_divider(audf_val, offset)
            frames[f_idx, audf_col] = audf_val
            frames[f_idx, audc_col] = (distortion & 0xE0) | vol
        elif song.uses_16bit_bass and (ch in (1, 2)):
            if ch == 1:
                # Channel 1 outputs low byte, muted volume
                div_low, div_hi = frequency_to_audf_16bit(current_freq, audctl=audctl, channel=1)
                frames[f_idx, 0] = pokey_hw.clamp_audf_for_tracker(div_low)  # AUDF1
                frames[f_idx, 1] = 0        # AUDC1 (muted)
                frames[f_idx, 2] = pokey_hw.clamp_audf_for_tracker(div_hi)  # AUDF2
                frames[f_idx, 3] = (distortion & 0xE0) | vol  # AUDC2 (active)
        else:
            # Standard 8-bit channel
            audf_val = pokey_hw.clamp_audf_for_tracker(
                frequency_to_audf_8bit(current_freq, audctl=audctl, channel=ch)
            )
            if modulating and vol:
                audf_val = pokey_hw.octave_pulse_divider(audf_val, offset)
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

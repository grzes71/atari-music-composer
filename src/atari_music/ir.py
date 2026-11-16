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
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field, model_validator

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    NOTE_NAMES,
    PAL_64KHZ_CLOCK,
)

if TYPE_CHECKING:
    from atari_music.instruments.models import (
        InstrumentBehavior,
        InstrumentProfile,
        PitchEnvelopeSpec,
        TransientMacroStep,
    )

# ---------------------------------------------------------------------------
# Binary Format v2 Limits & Constants
# ---------------------------------------------------------------------------

MAX_V2_INSTRUMENTS = 32
MAX_V2_MACRO_STEPS = 8
MAX_V2_CONSECUTIVE_COMMANDS = 4
MAX_V2_OPCODE = 0x01
OPCODE_PROGRAM_CHANGE = 0x01
MACRO_NO_OFFSET = 0xFF
MACRO_END_MARKER = 0x00

MACRO_FLAG_AUDF_FIXED = 0x01
MACRO_FLAG_USE_STEP_DIST = 0x02
MACRO_FLAG_USE_VOL_OVERRIDE = 0x04
INST_FLAG_MOD_OCTAVE_PULSE = 0x01


class IREnvelope(BaseModel):
    """ADSR Volume Envelope in 50 Hz frames."""
    attack_frames: int = Field(default=1, ge=0)
    decay_frames: int = Field(default=3, ge=0)
    sustain_vol: int = Field(default=8, ge=0, le=15)
    release_frames: int = Field(default=2, ge=0)


class IRMacroStep(BaseModel):
    """Active transient/percussion macro step for SONG_FORMAT_VERSION = 2.

    Supports both legacy attributes (``audf_offset``, ``distortion``, ``volume``) and
    full v2 semantics (``frames_per_step``, ``audf_mode``, ``fixed_audf``,
    ``audc_dist``, ``vol_override``). Exported to v2 only when requested explicitly;
    ``SONG_FORMAT_VERSION = 1`` continues to ignore/reject v2 macros safely.
    """

    audf_offset: int = 0
    distortion: int = DISTORTION_PURE_TONE
    volume: int = 15
    frames_per_step: int = Field(default=1, ge=1, le=255)
    audf_mode: Literal["offset", "fixed"] = "offset"
    fixed_audf: Optional[int] = Field(default=None, ge=0, le=0xFE)
    audc_dist: Optional[int] = None
    vol_override: Optional[int] = Field(default=None, ge=0, le=15)
    is_v2: Optional[bool] = None

    @model_validator(mode="after")
    def _infer_v2_marker(self) -> "IRMacroStep":
        if self.is_v2 is None:
            has_v2_field = (
                self.audc_dist is not None
                or self.vol_override is not None
                or self.fixed_audf is not None
                or self.audf_mode == "fixed"
                or self.frames_per_step != 1
            )
            self.is_v2 = bool(has_v2_field)
        return self

    def is_v2_step(self) -> bool:
        """True if this step carries active v2 behavior fields (not legacy placeholder)."""
        return bool(self.is_v2)

    @classmethod
    def from_transient_step(cls, step: "TransientMacroStep") -> "IRMacroStep":
        """Build an IRMacroStep from a validated Stage A ``TransientMacroStep``."""
        is_fixed = step.fixed_audf is not None
        return cls(
            frames_per_step=int(step.duration_frames),
            audc_dist=step.distortion_nibble,
            distortion=step.distortion_nibble if step.distortion_nibble is not None else DISTORTION_PURE_TONE,
            audf_mode="fixed" if is_fixed else "offset",
            fixed_audf=step.fixed_audf,
            audf_offset=int(step.audf_offset),
            vol_override=step.volume,
            volume=int(step.volume) if step.volume is not None else 15,
            is_v2=True,
        )


class IRPitchEnvelope(BaseModel):
    """Frame-timed initial pitch deviation / punch compatible with PitchEnvelopeSpec."""

    start_audf_delta: int = Field(ge=-127, le=127)
    duration_frames: int = Field(ge=0, le=15)
    step_delta: int = Field(ge=-16, le=16)

    @classmethod
    def from_spec(cls, spec: "PitchEnvelopeSpec") -> "IRPitchEnvelope":
        """Construct from SSOT ``PitchEnvelopeSpec``."""
        return cls(
            start_audf_delta=int(spec.start_audf_delta),
            duration_frames=int(spec.duration_frames),
            step_delta=int(spec.step_delta),
        )

    def to_spec(self) -> "PitchEnvelopeSpec":
        """Convert to SSOT ``PitchEnvelopeSpec``."""
        from atari_music.instruments.models import PitchEnvelopeSpec

        return PitchEnvelopeSpec(
            start_audf_delta=self.start_audf_delta,
            duration_frames=self.duration_frames,
            step_delta=self.step_delta,
        )


class IRInstrument(BaseModel):
    """POKEY Instrument Definition (v1 static fields + v2 behavior metadata)."""
    id: int
    name: str
    distortion: int = DISTORTION_PURE_TONE
    role: str = "melody"  # "melody", "bass", "harmony", "percussion"
    envelope: IREnvelope = Field(default_factory=IREnvelope)
    macro: Optional[List[IRMacroStep]] = None
    pitch_envelope: Optional[IRPitchEnvelope] = None
    behavior_id: Optional[str] = None
    vibrato_depth: int = 0
    vibrato_speed: int = 0
    is_16bit: bool = False
    volume_contour: Optional[List[int]] = None
    audctl: Optional[int] = None
    profile_id: Optional[str] = None
    profile_fingerprint: Optional[str] = None
    modulation: int = pokey_hw.MODULATION_NONE

    @classmethod
    def from_catalog_profile(
        cls,
        id_num: int,
        profile: "InstrumentProfile",
        behavior: Optional["InstrumentBehavior"] = None,
    ) -> "IRInstrument":
        """Construct an IRInstrument directly from a curated SSOT profile and behavior."""
        role = profile.intended_roles[0] if profile.intended_roles else "melody"
        env = IREnvelope(
            attack_frames=profile.envelope.attack_frames,
            decay_frames=profile.envelope.decay_frames,
            sustain_vol=profile.envelope.sustain_vol,
            release_frames=profile.envelope.release_frames,
        )
        mod = pokey_hw.MODULATION_NONE
        macro_steps: Optional[List[IRMacroStep]] = None
        pitch_env: Optional[IRPitchEnvelope] = None
        beh_id: Optional[str] = profile.behavior_id
        if behavior is not None:
            beh_id = behavior.behavior_id
            if behavior.modulation_mode == "octave_pulse":
                mod = pokey_hw.MODULATION_OCTAVE_PULSE
            if behavior.transient_macro is not None:
                macro_steps = [
                    IRMacroStep.from_transient_step(s) for s in behavior.transient_macro.steps
                ]
            if behavior.pitch_envelope is not None:
                pitch_env = IRPitchEnvelope.from_spec(behavior.pitch_envelope)

        hc = profile.hardware_constraints
        audctl_bits = int(hc.required_audctl_bits) if hc.required_audctl_bits else None
        return cls(
            id=id_num,
            name=profile.display_name,
            distortion=profile.base_distortion,
            role=role,
            envelope=env,
            macro=macro_steps,
            pitch_envelope=pitch_env,
            behavior_id=beh_id,
            is_16bit=(hc.divider_mode in ("16bit_ch12", "16bit_ch34")),
            audctl=audctl_bits,
            profile_id=profile.instrument_id,
            profile_fingerprint=profile.provenance.profile_fingerprint,
            modulation=mod,
        )


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
    pending_program_changes: Tuple[int, ...] = ()


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
    initial_channel_instruments: Optional[Dict[int, int]] = None

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

def _macro_dedup_key(
    macro: Sequence[IRMacroStep], base_distortion: int
) -> Tuple[Tuple[int, int, int, int, int], ...]:
    """Canonical deduplication key for an active transient macro sequence."""
    key_steps: List[Tuple[int, int, int, int, int]] = []
    for step in macro:
        use_step_dist = 1 if step.audc_dist is not None else 0
        dist_val = int(step.audc_dist) & 0xE0 if use_step_dist else int(base_distortion) & 0xE0
        is_fixed = 1 if step.audf_mode == "fixed" else 0
        audf_byte = int(step.fixed_audf or 0) & 0xFF if is_fixed else (int(step.audf_offset) & 0xFF)
        use_vol = 1 if step.vol_override is not None else 0
        vol_val = int(step.vol_override) & 0x0F if use_vol else 0
        flags = (is_fixed * MACRO_FLAG_AUDF_FIXED) | (use_step_dist * MACRO_FLAG_USE_STEP_DIST) | (use_vol * MACRO_FLAG_USE_VOL_OVERRIDE)
        key_steps.append((int(step.frames_per_step), flags, dist_val | vol_val, audf_byte, 0))
    return tuple(key_steps)


def resolve_initial_channel_instruments(song: IRSong) -> Dict[int, int]:
    """Resolve deterministic starting instrument index (0..N-1) per channel 1..4 for v2."""
    id_to_index = {inst.id: idx for idx, inst in enumerate(song.instruments)}
    max_idx = max(0, len(song.instruments) - 1)
    if song.initial_channel_instruments:
        resolved: Dict[int, int] = {}
        for ch in range(1, 5):
            raw_id = song.initial_channel_instruments.get(ch)
            if raw_id is None:
                raw_id = ch - 1
            if raw_id in id_to_index:
                resolved[ch] = id_to_index[raw_id]
            elif 0 <= raw_id <= max_idx:
                resolved[ch] = raw_id
            else:
                resolved[ch] = 0
        return resolved

    out: Dict[int, int] = {}
    for ch in range(1, 5):
        if song.uses_16bit_bass and ch == 2:
            out[ch] = out[1]
            continue
        chosen: Optional[int] = None
        for pat in song.patterns:
            for note in pat.tracks.get(ch, []):
                if not note.is_rest and note.instrument_id in id_to_index:
                    chosen = id_to_index[note.instrument_id]
                    break
            if chosen is not None:
                break
        if chosen is None:
            for pat in song.patterns:
                for note in pat.tracks.get(ch, []):
                    if note.instrument_id in id_to_index:
                        chosen = id_to_index[note.instrument_id]
                        break
                if chosen is not None:
                    break
        if chosen is None:
            for pat in song.patterns:
                for note in pat.tracks.get(ch, []):
                    if note.channel_role == "percussion":
                        for idx, inst in enumerate(song.instruments):
                            if inst.role == "percussion" or inst.distortion == DISTORTION_WHITE_NOISE:
                                chosen = idx
                                break
                        break
                if chosen is not None:
                    break
        if chosen is None:
            if (ch - 1) in id_to_index:
                chosen = id_to_index[ch - 1]
            elif song.instruments:
                chosen = 0
            else:
                chosen = 0
        out[ch] = chosen
    return out


def song_requires_v2(song: IRSong) -> List[str]:
    """Return reasons why *song* requires SONG_FORMAT_VERSION = 2 (empty if v1-compatible)."""
    reasons: List[str] = []
    if song.initial_channel_instruments is not None:
        reasons.append("song specifies explicit v2 initial_channel_instruments")

    for inst in song.instruments:
        if inst.macro and any(step.is_v2_step() for step in inst.macro):
            reasons.append(f"instrument {inst.name!r} carries a v2 transient macro")
        if inst.pitch_envelope is not None and inst.pitch_envelope.duration_frames > 0:
            reasons.append(f"instrument {inst.name!r} carries a v2 pitch envelope")

    init_ch = resolve_initial_channel_instruments(song)
    id_to_index = {inst.id: idx for idx, inst in enumerate(song.instruments)}
    used_indices: set[int] = set()
    for ch in range(1, 5):
        if song.uses_16bit_bass and ch == 2:
            continue
        cur_idx = init_ch[ch]
        for pat in song.patterns:
            for note in pat.tracks.get(ch, []):
                if note.pending_program_changes:
                    reasons.append(f"channel {ch} contains explicit PROGRAM_CHANGE commands")
                    used_indices.update(
                        id_to_index[i] for i in note.pending_program_changes if i in id_to_index
                    )
                if not note.is_rest and note.instrument_id in id_to_index:
                    note_idx = id_to_index[note.instrument_id]
                    used_indices.add(note_idx)
                    if note_idx != cur_idx:
                        inst_old = song.instruments[cur_idx]
                        inst_new = song.instruments[note_idx]
                        both_legacy_placeholder = (
                            bool(inst_old.macro)
                            and bool(inst_new.macro)
                            and not any(s.is_v2_step() for s in (inst_old.macro or []))
                            and not any(s.is_v2_step() for s in (inst_new.macro or []))
                        )
                        if not both_legacy_placeholder:
                            reasons.append(
                                f"channel {ch} switches instrument mid-track ({cur_idx} -> {note_idx})"
                            )
                        cur_idx = note_idx

    non_legacy_used = {
        idx
        for idx in used_indices
        if not (
            song.instruments[idx].macro
            and not any(s.is_v2_step() for s in (song.instruments[idx].macro or []))
        )
    }
    if len(non_legacy_used) > 4:
        reasons.append(f"song uses {len(non_legacy_used)} distinct instruments on tracks (v1 supports max 4)")

    return list(dict.fromkeys(reasons))


def plan_v2_pattern_streams(
    song: IRSong,
) -> Tuple[Dict[int, int], Dict[int, Dict[int, List[Tuple[str, Tuple[int, ...], str]]]]]:
    """Build deterministic v2 event sequences per unique pattern & channel.

    Returns ``(initial_ch_inst, pat_streams)`` where each channel stream is a list of
    ``(kind, raw_bytes, comment)`` tuples (``kind in {'cmd', 'note', 'end'}``) shared
    between :func:`calculate_ir_binary_size` and :func:`atari_music.mads_exporter.export_mads_asm`.
    """
    init_ch = resolve_initial_channel_instruments(song)
    id_to_index = {inst.id: idx for idx, inst in enumerate(song.instruments)}
    audctl_val = resolve_audctl_mode(song)
    pattern_map = {p.id: p for p in song.patterns}

    # Simulate two passes of seq_order (including loop wraparound) to know all possible
    # incoming instrument indices entering each pattern on each channel.
    seq_order = list(song.sequence) if song.sequence else sorted(pattern_map.keys())
    incoming_sets: Dict[int, Dict[int, set[int]]] = {
        pid: {c: set() for c in range(1, 5)} for pid in pattern_map
    }
    sim_ch_inst = dict(init_ch)
    for _pass in range(2):
        for pat_id in seq_order:
            pat = pattern_map.get(pat_id)
            if pat is None:
                continue
            for ch in range(1, 5):
                eff_ch = 1 if (song.uses_16bit_bass and ch == 2) else ch
                incoming_sets[pat_id][ch].add(sim_ch_inst[eff_ch])
            for ch in range(1, 5):
                if song.uses_16bit_bass and ch == 2:
                    continue
                for note in pat.tracks.get(ch, []):
                    if note.pending_program_changes:
                        last_raw = note.pending_program_changes[-1]
                        sim_ch_inst[ch] = id_to_index.get(last_raw, last_raw)
                    elif not note.is_rest and note.instrument_id in id_to_index:
                        sim_ch_inst[ch] = id_to_index[note.instrument_id]

    pat_streams: Dict[int, Dict[int, List[Tuple[str, Tuple[int, ...], str]]]] = {}
    for pat_id in sorted(pattern_map.keys()):
        pat = pattern_map[pat_id]
        ch_dict: Dict[int, List[Tuple[str, Tuple[int, ...], str]]] = {}

        for ch in range(1, 5):
            events: List[Tuple[str, Tuple[int, ...], str]] = []
            incoming = incoming_sets[pat_id][ch]
            if song.uses_16bit_bass and ch == 2:
                notes = pat.tracks.get(1, [])
                if not notes:
                    events.append(("note", (0x00, max(1, min(255, pat.rows)), 0x00), f"rest ({pat.rows} rows)"))
                    events.append(("end", (0xFF,), "end of track"))
                    ch_dict[ch] = events
                    continue
                cur_set: Optional[set[int]] = incoming
                cur_idx = next(iter(incoming)) if len(incoming) == 1 else init_ch[1]
                for note in notes:
                    if note.pending_program_changes:
                        for raw_id in note.pending_program_changes:
                            tgt = id_to_index.get(raw_id, raw_id)
                            events.append(("cmd", (0x00, 0x00, OPCODE_PROGRAM_CHANGE, tgt), f"PROGRAM_CHANGE inst={tgt}"))
                            cur_idx = tgt
                        cur_set = {cur_idx}
                    elif not note.is_rest and note.instrument_id in id_to_index:
                        tgt = id_to_index[note.instrument_id]
                        if (cur_set is not None and cur_set != {tgt}) or (cur_set is None and tgt != cur_idx):
                            events.append(("cmd", (0x00, 0x00, OPCODE_PROGRAM_CHANGE, tgt), f"PROGRAM_CHANGE inst={tgt}"))
                            cur_idx = tgt
                        cur_set = {tgt}
                    dur = max(1, min(255, int(note.duration)))
                    midi_val = note.midi_pitch
                    if midi_val is None and note.pitch and str(note.pitch).upper() not in ("---", "REST", "OFF", "SIL", ""):
                        midi_val = note_name_to_midi(str(note.pitch))
                    if note.is_rest or midi_val is None:
                        events.append(("note", (0x00, dur, 0x00), f"rest ({dur} rows)"))
                    else:
                        freq = midi_pitch_to_frequency(midi_val)
                        _, div_hi = frequency_to_audf_16bit(freq, audctl=audctl_val, channel=1)
                        audf = pokey_hw.clamp_audf_for_tracker(div_hi)
                        vol = min(15, max(0, int(note.volume)))
                        events.append(("note", (audf, dur, vol), f"16-bit hi {note.pitch or 'bass'} ({dur} rows)"))
                events.append(("end", (0xFF,), "end of track"))
                ch_dict[ch] = events
                continue

            notes = pat.tracks.get(ch, [])
            if not notes:
                events.append(("note", (0x00, max(1, min(255, pat.rows)), 0x00), f"rest ({pat.rows} rows)"))
                events.append(("end", (0xFF,), "end of track"))
                ch_dict[ch] = events
                continue

            cur_set = incoming
            cur_idx = next(iter(incoming)) if len(incoming) == 1 else init_ch[ch]
            for note in notes:
                if note.pending_program_changes:
                    for raw_id in note.pending_program_changes:
                        tgt = id_to_index.get(raw_id, raw_id)
                        events.append(("cmd", (0x00, 0x00, OPCODE_PROGRAM_CHANGE, tgt), f"PROGRAM_CHANGE inst={tgt}"))
                        cur_idx = tgt
                    cur_set = {cur_idx}
                elif not note.is_rest and note.instrument_id in id_to_index:
                    tgt = id_to_index[note.instrument_id]
                    if (cur_set is not None and cur_set != {tgt}) or (cur_set is None and tgt != cur_idx):
                        events.append(("cmd", (0x00, 0x00, OPCODE_PROGRAM_CHANGE, tgt), f"PROGRAM_CHANGE inst={tgt}"))
                        cur_idx = tgt
                    cur_set = {tgt}

                dur = max(1, min(255, int(note.duration)))
                midi_val = note.midi_pitch
                if midi_val is None and note.pitch and str(note.pitch).upper() not in ("---", "REST", "OFF", "SIL", ""):
                    midi_val = note_name_to_midi(str(note.pitch))
                unpitched_perc = pokey_hw.is_unpitched_percussion(midi_val, note.channel_role)
                if note.is_rest or (midi_val is None and not unpitched_perc):
                    audf = 0
                    vol = 0
                    comment = f"rest ({dur} rows)"
                elif unpitched_perc:
                    audf = pokey_hw.clamp_audf_for_tracker(pokey_hw.PERCUSSION_DEFAULT_AUDF)
                    vol = min(15, max(0, int(note.volume)))
                    comment = f"perc ({dur} rows)"
                else:
                    freq = midi_pitch_to_frequency(midi_val)
                    if song.uses_16bit_bass and ch == 1:
                        div_low, _ = frequency_to_audf_16bit(freq, audctl=audctl_val, channel=1)
                        audf = pokey_hw.clamp_audf_for_tracker(div_low)
                        vol = 0
                    else:
                        audf = pokey_hw.clamp_audf_for_tracker(
                            frequency_to_audf_8bit(freq, audctl=audctl_val, channel=ch)
                        )
                        vol = min(15, max(0, int(note.volume)))
                    comment = f"{note.pitch or 'note'} ({dur} rows)"
                events.append(("note", (audf, dur, vol), comment))
            events.append(("end", (0xFF,), "end of track"))
            ch_dict[ch] = events
        pat_streams[pat_id] = ch_dict

    return init_ch, pat_streams


def calculate_ir_binary_size(song: IRSong, format_version: int = 1) -> int:
    """Calculate exact MADS exported binary size in bytes for format v1 or v2.

    Matches the actual bytes emitted by :func:`atari_music.mads_exporter.export_mads_asm`:
    - v1: 6 B header + 25 B instrument block + sequence + unique pattern track tables & streams.
    - v2: 6 B header + 8 B v2 inst header + 10*N B SoA tables + macro directory/pool + sequence + patterns.
    """
    if format_version not in (1, 2):
        raise ValueError(f"unsupported format_version {format_version!r}; expected 1 or 2")

    seq_bytes = len(song.sequence) * 2 + 2

    if format_version == 1:
        size = 6 + 25 + seq_bytes
        for pat in song.patterns:
            size += 8  # 4 track .word pointers
            for ch in range(1, 5):
                if song.uses_16bit_bass and ch == 2:
                    notes = pat.tracks.get(1, [])
                else:
                    notes = pat.tracks.get(ch, [])
                event_count = len(notes) if notes else 1
                size += event_count * 3 + 1  # 3-byte events + $FF end marker
        return size

    # format_version == 2
    inst_count = max(1, len(song.instruments))
    soa_bytes = 6 + 8 + 10 * inst_count

    unique_macros: Dict[Tuple[Tuple[int, int, int, int, int], ...], int] = {}
    macro_pool_bytes = 0
    for inst in song.instruments:
        if inst.macro and any(s.is_v2_step() for s in inst.macro):
            key = _macro_dedup_key(inst.macro, inst.distortion)
            if key not in unique_macros:
                unique_macros[key] = len(unique_macros)
                macro_pool_bytes += len(inst.macro) * 4 + 1  # 4B per step + 1B $00 end
    macro_dir_bytes = len(unique_macros) * 2 if unique_macros else 2

    _, pat_streams = plan_v2_pattern_streams(song)
    pat_bytes = 0
    for pat_id in sorted(pat_streams.keys()):
        pat_bytes += 8  # 4 .word track pointers
        for ch in range(1, 5):
            for _kind, raw_bytes, _comment in pat_streams[pat_id][ch]:
                pat_bytes += len(raw_bytes)

    return soa_bytes + macro_dir_bytes + macro_pool_bytes + seq_bytes + pat_bytes

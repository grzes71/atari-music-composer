"""MADS 6502 Music Data Exporter for Atari POKEY Music Engine.

Converts MusicGenerationResult / IRSong into relocatable, high-performance
MADS assembly data (`music_data.asm`) for the 6502 music player.

Format Specification:
---------------------
1. Song Header (6 bytes):
   .byte frames_per_tick       ; Speed / tempo divisor (e.g. 3..6 at 50 Hz VBLANK)
   .byte audctl_mode           ; AUDCTL register value ($00 = 8-bit, $50 = 16-bit bass)
   .word instruments_ptr       ; Pointer to 4-channel instrument definitions
   .word sequence_ptr          ; Pointer to sequence pointer list

2. Format Version (1 byte):
   .byte version               ; 1 = the instrument records below are 6 bytes each.
                               ;   0 (songs exported before this existed) had no version
                               ;   byte and 5-byte records; player.asm refuses anything
                               ;   that is not the version it knows.

3. Instruments Table (4 x 6 = 24 bytes):
   Per channel 1..4:
   .byte distortion            ; AUDC high nibble ($A0 = pure, $C0 = poly bass, $80 = noise)
   .byte attack_frames         ; Attack ramp frames (0..15)
   .byte decay_frames          ; Decay ramp frames (0..15)
   .byte sustain_vol           ; Sustain volume (0..15)
   .byte release_frames        ; Release fade frames (0..15)
   .byte modulation            ; 0 = none, 1 = octave pulse (C1); see atari_music.pokey_hw

4. Sequence Table:
   .word pat_0_tracks, pat_1_tracks, ..., $FFFF (terminator / loop target)

5. Pattern Track Lists:
   .word ch1_data, ch2_data, ch3_data, ch4_data

6. Track Event Streams (RLE 3-byte events):
   .byte audf, duration_ticks, volume
   ...
   .byte $FF                   ; End of track marker
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from atari_music.api import MusicGenerationResult
from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.ir import (
    INST_FLAG_MOD_OCTAVE_PULSE,
    MACRO_END_MARKER,
    MACRO_FLAG_AUDF_FIXED,
    MACRO_FLAG_USE_STEP_DIST,
    MACRO_FLAG_USE_VOL_OVERRIDE,
    MACRO_NO_OFFSET,
    MAX_V2_CONSECUTIVE_COMMANDS,
    MAX_V2_INSTRUMENTS,
    MAX_V2_MACRO_STEPS,
    MAX_V2_OPCODE,
    OPCODE_PROGRAM_CHANGE,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRPattern,
    IRSong,
    _macro_dedup_key,
    find_pitch_range_issues,
    frequency_to_audf_16bit,
    frequency_to_audf_8bit,
    midi_pitch_to_frequency,
    note_name_to_midi,
    plan_v2_pattern_streams,
    resolve_audctl_mode,
    song_requires_v2,
)

logger = logging.getLogger(__name__)


class VolumeContourNotExpressibleError(Exception):
    """A song carries a per-frame volume contour that the 6502 player cannot reproduce.

    This exporter publishes a *note* table (``audf, duration_ticks, volume``) plus envelope
    parameters, and ``player.asm`` builds the per-frame volume itself at run time. A
    per-frame level contour measured from a reference recording has no place in that format,
    so exporting one would produce an XEX that plays something different from the WAV that
    was listened to. Refusing is the only honest option; there is no lossy fallback.
    """

    code = "VOLUME_CONTOUR_NOT_EXPRESSIBLE_IN_XEX"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        detail: Optional[Dict[str, object]] = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.detail: Dict[str, object] = dict(detail or {})


def find_volume_contour_instruments(song: IRSong) -> List[IRInstrument]:
    """Instruments carrying a per-frame volume contour, in song order."""
    return [inst for inst in song.instruments if getattr(inst, "volume_contour", None)]


#: The music-data format version this exporter writes and ``player.asm`` reads.
#:
#: * **1** — the header, the sequence table, the pattern track lists and the 3-byte note
#:   events are unchanged from version 0; the instrument table is preceded by this version
#:   byte and carries a sixth byte per channel (``IRInstrument.modulation``).
#: * **0** — what every song exported before this existed is: no version byte, a 5-byte
#:   instrument record. Its first instrument byte was always a generator (a multiple of
#:   ``$20``), so it can never be mistaken for version 1, whose marker is ``$01``.
#:
#: The player refuses a version it does not know, so a version-0 song played by a version-1
#: player is a loud refusal rather than a misread instrument table.
SONG_FORMAT_VERSION = 1
SONG_FORMAT_VERSION_2 = 2


class FormatVersionError(ValueError):
    """Raised when the requested export format version is unknown or incompatible with the song."""

    code = "UNSUPPORTED_SONG_FORMAT_VERSION"


class StreamValidationError(ValueError):
    """Raised when v2 song instruments, macros, or event streams violate structural bounds."""

    code = "INVALID_V2_STREAM"


def validate_v2_track_bytes(track_bytes: Sequence[int], instrument_count: int) -> None:
    """Validate a compiled v2 channel byte stream before ASM/XEX emission."""
    n = len(track_bytes)
    if n == 0:
        raise StreamValidationError("v2 track stream is empty (missing $FF terminator)")
    if track_bytes[-1] != 0xFF:
        raise StreamValidationError("v2 track stream must end with $FF terminator")

    idx = 0
    consecutive_cmds = 0
    note_or_rest_count = 0
    while idx < n:
        b0 = int(track_bytes[idx]) & 0xFF
        if b0 == 0xFF:
            if idx != n - 1:
                raise StreamValidationError(f"trailing bytes after $FF terminator at offset {idx}")
            break
        if idx + 1 >= n or track_bytes[idx + 1] == 0xFF:
            raise StreamValidationError(f"truncated record in v2 track stream at offset {idx}")
        b1 = int(track_bytes[idx + 1]) & 0xFF
        if b0 == 0 and b1 == 0:
            if idx + 3 >= n - 1:
                raise StreamValidationError(f"truncated 4-byte command at offset {idx}")
            opcode = int(track_bytes[idx + 2])
            param = int(track_bytes[idx + 3])
            if opcode < 1 or opcode > MAX_V2_OPCODE:
                raise StreamValidationError(f"unsupported v2 opcode 0x{opcode:02x} at offset {idx}")
            if param < 0 or param >= instrument_count:
                raise StreamValidationError(
                    f"PROGRAM_CHANGE target inst={param} out of bounds 0..{instrument_count - 1} at offset {idx}"
                )
            consecutive_cmds += 1
            if consecutive_cmds > MAX_V2_CONSECUTIVE_COMMANDS:
                raise StreamValidationError(
                    f"more than {MAX_V2_CONSECUTIVE_COMMANDS} consecutive commands before note/rest at offset {idx}"
                )
            idx += 4
        else:
            if idx + 2 >= n - 1:
                raise StreamValidationError(f"truncated 3-byte note/rest event at offset {idx}")
            audf = b0
            dur = b1
            vol = int(track_bytes[idx + 2])
            if audf > 0xFE:
                raise StreamValidationError(f"invalid AUDF 0x{audf:02x} > $FE at offset {idx}")
            if dur < 1 or dur > 255:
                raise StreamValidationError(f"invalid duration {dur} (must be 1..255) at offset {idx}")
            if vol < 0 or vol > 15:
                raise StreamValidationError(f"invalid volume {vol} (must be 0..15) at offset {idx}")
            consecutive_cmds = 0
            note_or_rest_count += 1
            idx += 3

    if note_or_rest_count == 0:
        raise StreamValidationError("v2 track stream has no note or rest before $FF")


def _validate_and_build_v2_tables(
    song: IRSong, audctl_val: int
) -> Tuple[
    Dict[int, int],
    List[Dict[str, int]],
    List[List[Tuple[int, int, int, int, str]]],
    Dict[int, Dict[int, List[Tuple[str, Tuple[int, ...], str]]]],
]:
    """Validate all v2 constraints upfront and return SoA rows, macro pool, and track streams."""
    if not (1 <= song.frames_per_tick <= 255):
        raise StreamValidationError(f"frames_per_tick must be 1..255, got {song.frames_per_tick}")
    if audctl_val & 0x06:
        raise StreamValidationError(
            f"HPF XOR bits ($02/$04) in AUDCTL=${audctl_val:02x} are deferred past v2 Iter 1"
        )
    if audctl_val & AUDCTL_JOIN_3_4_16BIT:
        raise StreamValidationError("16-bit CH3+CH4 ($08) is deferred past v2 Iter 1")

    inst_count = len(song.instruments)
    if inst_count < 1 or inst_count > MAX_V2_INSTRUMENTS:
        raise StreamValidationError(
            f"v2 song must define 1..{MAX_V2_INSTRUMENTS} instruments, got {inst_count}"
        )

    id_to_index: Dict[int, int] = {}
    for idx, inst in enumerate(song.instruments):
        if inst.id in id_to_index:
            raise StreamValidationError(f"duplicate instrument id {inst.id} in v2 song")
        id_to_index[inst.id] = idx
        if inst.vibrato_depth != 0 or inst.vibrato_speed != 0:
            raise StreamValidationError(
                f"instrument {inst.name!r} uses delayed vibrato, which is deferred to v2 Iter 2"
            )
        dist = int(inst.distortion)
        if dist < 0 or dist > 0xE0 or (dist & 0x1F) != 0:
            raise StreamValidationError(f"instrument {inst.name!r} invalid distortion 0x{dist:02x}")
        env = inst.envelope
        for field_name, val in (
            ("attack_frames", env.attack_frames),
            ("decay_frames", env.decay_frames),
            ("release_frames", env.release_frames),
        ):
            if val < 0 or val > 255:
                raise StreamValidationError(f"instrument {inst.name!r} {field_name}={val} out of 0..255")
        if env.sustain_vol < 0 or env.sustain_vol > 15:
            raise StreamValidationError(f"instrument {inst.name!r} sustain_vol={env.sustain_vol} out of 0..15")
        if inst.modulation < 0 or inst.modulation > pokey_hw.MODULATION_DEFINED_MAX:
            raise StreamValidationError(
                f"instrument {inst.name!r} unsupported modulation {inst.modulation}"
            )
        if inst.pitch_envelope is not None:
            pe = inst.pitch_envelope
            if not (-127 <= pe.start_audf_delta <= 127):
                raise StreamValidationError(f"instrument {inst.name!r} pitch start delta {pe.start_audf_delta} out of -127..127")
            if not (0 <= pe.duration_frames <= 15):
                raise StreamValidationError(f"instrument {inst.name!r} pitch duration {pe.duration_frames} out of 0..15")
            if not (-16 <= pe.step_delta <= 16):
                raise StreamValidationError(f"instrument {inst.name!r} pitch step {pe.step_delta} out of -16..16")

    if song.initial_channel_instruments is not None:
        for ch in range(1, 5):
            raw_id = song.initial_channel_instruments.get(ch)
            if raw_id is None or (raw_id not in id_to_index and not (0 <= raw_id < inst_count)):
                raise StreamValidationError(
                    f"initial_channel_instruments[{ch}]={raw_id!r} does not refer to a valid song instrument"
                )

    for pat in song.patterns:
        for ch, notes in pat.tracks.items():
            for n in notes:
                if n.arpeggio_offsets:
                    raise StreamValidationError("arpeggio_offsets are deferred past v2 Iter 1")
                if n.slide_semitones != 0:
                    raise StreamValidationError("slide_semitones are deferred past v2 Iter 1")
                if not n.is_rest and n.instrument_id not in id_to_index:
                    raise StreamValidationError(
                        f"pattern {pat.id} ch {ch} references unknown instrument_id={n.instrument_id}"
                    )
                for p_id in n.pending_program_changes:
                    if p_id not in id_to_index:
                        raise StreamValidationError(
                            f"pattern {pat.id} ch {ch} pending PROGRAM_CHANGE references unknown instrument_id={p_id}"
                        )

    if not song.sequence:
        raise StreamValidationError("v2 song must have a non-empty sequence")
    pat_ids = {p.id for p in song.patterns}
    for s_id in song.sequence:
        if s_id not in pat_ids:
            raise StreamValidationError(f"sequence references missing pattern id {s_id}")

    # Build deduplicated macro directory (offset = 2 * macro_index, $FF = no macro)
    unique_macros: Dict[Tuple[Tuple[int, int, int, int, int], ...], int] = {}
    macro_list: List[List[Tuple[int, int, int, int, str]]] = []
    soa_rows: List[Dict[str, int]] = []

    for inst in song.instruments:
        macro_off = MACRO_NO_OFFSET
        if inst.macro and any(s.is_v2_step() for s in inst.macro):
            if len(inst.macro) > MAX_V2_MACRO_STEPS:
                raise StreamValidationError(
                    f"instrument {inst.name!r} macro has {len(inst.macro)} steps (max {MAX_V2_MACRO_STEPS})"
                )
            for s_idx, step in enumerate(inst.macro):
                if not (1 <= step.frames_per_step <= 255):
                    raise StreamValidationError(
                        f"instrument {inst.name!r} macro step {s_idx} frames_per_step={step.frames_per_step} out of 1..255"
                    )
                if step.audc_dist is not None and (
                    step.audc_dist < 0 or step.audc_dist > 0xE0 or (step.audc_dist & 0x1F) != 0
                ):
                    raise StreamValidationError(
                        f"instrument {inst.name!r} macro step {s_idx} invalid audc_dist 0x{step.audc_dist:02x}"
                    )
                if step.audf_mode == "fixed":
                    if step.fixed_audf is None or not (0 <= step.fixed_audf <= 0xFE):
                        raise StreamValidationError(
                            f"instrument {inst.name!r} macro step {s_idx} fixed AUDF out of 0..$FE"
                        )
                else:
                    if not (-127 <= step.audf_offset <= 127):
                        raise StreamValidationError(
                            f"instrument {inst.name!r} macro step {s_idx} audf_offset={step.audf_offset} out of -127..127"
                        )
                if step.vol_override is not None and not (0 <= step.vol_override <= 15):
                    raise StreamValidationError(
                        f"instrument {inst.name!r} macro step {s_idx} vol_override={step.vol_override} out of 0..15"
                    )

            dedup_key = _macro_dedup_key(inst.macro, inst.distortion)
            if dedup_key not in unique_macros:
                m_idx = len(macro_list)
                unique_macros[dedup_key] = m_idx
                compiled_steps: List[Tuple[int, int, int, int, str]] = []
                for step in inst.macro:
                    is_fixed = 1 if step.audf_mode == "fixed" else 0
                    use_dist = 1 if step.audc_dist is not None else 0
                    use_vol = 1 if step.vol_override is not None else 0
                    flags = (
                        (MACRO_FLAG_AUDF_FIXED if is_fixed else 0)
                        | (MACRO_FLAG_USE_STEP_DIST if use_dist else 0)
                        | (MACRO_FLAG_USE_VOL_OVERRIDE if use_vol else 0)
                    )
                    dist_byte = (int(step.audc_dist) & 0xE0) if use_dist else (int(inst.distortion) & 0xE0)
                    vol_byte = (int(step.vol_override) & 0x0F) if use_vol else 0
                    audf_byte = (
                        int(step.fixed_audf or 0) & 0xFF
                        if is_fixed
                        else (int(step.audf_offset) & 0xFF)
                    )
                    desc = (
                        f"dur={step.frames_per_step} flags=${flags:02x} "
                        f"audc=${dist_byte | vol_byte:02x} "
                        f"{'fixed' if is_fixed else 'offset'}=${audf_byte:02x}"
                    )
                    compiled_steps.append(
                        (int(step.frames_per_step), flags, dist_byte | vol_byte, audf_byte, desc)
                    )
                macro_list.append(compiled_steps)
            macro_off = unique_macros[dedup_key] * 2
            if macro_off >= 2 * len(macro_list) or macro_off >= MACRO_NO_OFFSET:
                raise StreamValidationError(f"computed invalid macro directory offset 0x{macro_off:02x}")

        pe = inst.pitch_envelope
        p_start = (int(pe.start_audf_delta) & 0xFF) if pe and pe.duration_frames > 0 else 0
        p_dur = int(pe.duration_frames) if pe and pe.duration_frames > 0 else 0
        p_step = (int(pe.step_delta) & 0xFF) if pe and pe.duration_frames > 0 else 0
        inst_flags = INST_FLAG_MOD_OCTAVE_PULSE if pokey_hw.is_octave_pulse(inst.modulation) else 0
        if (audctl_val & AUDCTL_JOIN_1_2_16BIT) and inst_flags & INST_FLAG_MOD_OCTAVE_PULSE:
            # Check whether this instrument is ever used on paired CH1+2
            for pat in song.patterns:
                for ch_n in (1, 2):
                    if any(
                        (not n.is_rest and n.instrument_id == inst.id)
                        or (inst.id in n.pending_program_changes)
                        for n in pat.tracks.get(ch_n, [])
                    ):
                        raise ModulationNotExpressibleError(
                            f"instrument {inst.name!r} uses MOD_OCTAVE_PULSE on 16-bit paired channel {ch_n}"
                        )

        soa_rows.append(
            {
                "dist": int(inst.distortion) & 0xE0,
                "att": int(inst.envelope.attack_frames) & 0xFF,
                "dec": int(inst.envelope.decay_frames) & 0xFF,
                "sus": int(inst.envelope.sustain_vol) & 0x0F,
                "rel": int(inst.envelope.release_frames) & 0xFF,
                "flags": inst_flags,
                "macro_off": macro_off,
                "p_start": p_start,
                "p_dur": p_dur,
                "p_step": p_step,
            }
        )

    init_ch, pat_streams = plan_v2_pattern_streams(song)
    for pat_id, ch_map in pat_streams.items():
        for ch, evs in ch_map.items():
            flat_bytes = [b for _k, raw, _c in evs for b in raw]
            validate_v2_track_bytes(flat_bytes, inst_count)

    return init_ch, soa_rows, macro_list, pat_streams


class ModulationNotExpressibleError(Exception):
    """A song asks for a per-channel modulation this data format cannot encode.

    Format version 1 defines exactly one modulation — ``pokey_hw.MODULATION_OCTAVE_PULSE``,
    C1's octave pulse — and it moves a channel's own 8-bit divider. A channel joined into a
    16-bit pair has no single divider to move: its two AUDF bytes are one 16-bit number, and
    the player has no paired form of the rule. Exporting one would produce an XEX that plays
    something the WAV preview does not, so export is refused rather than approximated.
    """

    code = "MODULATION_NOT_EXPRESSIBLE_IN_XEX"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        detail: Optional[Dict[str, object]] = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.detail: Dict[str, object] = dict(detail or {})


def joined_channels(audctl_val: int) -> Tuple[int, ...]:
    """The 1-based channels a joined 16-bit pair owns, for the song's AUDCTL byte.

    Bit 4 joins channels 1+2, bit 3 joins 3+4. Only the 1+2 pair has a write path in
    ``player.asm``, but both are reported here because either one removes a channel's own
    divider, which is all a modulation needs.
    """
    joined: List[int] = []
    if int(audctl_val) & AUDCTL_JOIN_1_2_16BIT:
        joined += [1, 2]
    if int(audctl_val) & AUDCTL_JOIN_3_4_16BIT:
        joined += [3, 4]
    return tuple(joined)


def _sounding_instrument(
    song: IRSong, channel: int, inst_map: Dict[int, IRInstrument]
) -> Optional[IRInstrument]:
    """The instrument whose sounding notes *channel* carries, if any.

    ``_find_channel_instrument`` answers the opposite question and always answers it, falling
    back to some instrument for a channel with no notes so the table stays fully populated. That
    fallback is fine for a generator and an envelope -- an unoccupied channel never plays them --
    but it is not a statement about the modulation, which is the one field whose *emission* has a
    hardware consequence.
    """
    for pattern in song.patterns:
        for note in pattern.tracks.get(channel, []):
            if note.is_rest:
                continue
            instrument = inst_map.get(note.instrument_id)
            if instrument is not None:
                return instrument
    return None


def channel_modulations(song: IRSong) -> Dict[int, int]:
    """channel -> the modulation descriptor that channel's instrument record will carry.

    This is the single statement of *where* a modulation is emitted, used by both the emission
    and :func:`find_unsupported_modulations`, so the descriptor that is checked is always the
    descriptor that would be written.

    Two rules:

    * the descriptor comes from the instrument that **sounds** on the channel, so a channel with
      no notes carries none even though its generator and envelope still fall back to some
      instrument;
    * channel 2 of a 16-bit bass song is emitted as the pair's slave and always carries none --
      the pair's modulation, if any, is channel 1's.
    """
    inst_map = {inst.id: inst for inst in song.instruments}
    descriptors: Dict[int, int] = {}
    for channel in range(1, 5):
        if song.uses_16bit_bass and channel == 2:
            descriptors[channel] = pokey_hw.MODULATION_NONE
            continue
        instrument = _sounding_instrument(song, channel, inst_map)
        descriptors[channel] = (
            int(getattr(instrument, "modulation", pokey_hw.MODULATION_NONE) or 0)
            if instrument is not None
            else pokey_hw.MODULATION_NONE
        )
    return descriptors


def find_unsupported_modulations(
    song: IRSong, audctl_val: Optional[int] = None
) -> List[Dict[str, object]]:
    """Requested modulations this exporter cannot encode, each with its channel and reason.

    Walks the **channels the export will write**, through the same
    ``_find_channel_instrument`` mapping the instrument table uses, so the descriptor that is
    checked is the descriptor that would be emitted for that channel. An instrument's position in
    ``song.instruments`` is not a channel number and is never used as one.

    Two refusals, both about the *song* rather than about the format: a descriptor this version
    does not define (which the player would silently ignore, so exporting it would claim a
    modulation the XEX does not have), and a modulation on a channel a 16-bit pair owns (which
    has no single divider to move).
    """
    resolved_audctl = resolve_audctl_mode(song) if audctl_val is None else int(audctl_val)
    paired = joined_channels(resolved_audctl)
    unsupported: List[Dict[str, object]] = []
    for channel, descriptor in sorted(channel_modulations(song).items()):
        if descriptor == pokey_hw.MODULATION_NONE:
            continue
        if descriptor > pokey_hw.MODULATION_DEFINED_MAX:
            unsupported.append({
                "channel": channel,
                "instrument": _channel_instrument_name(song, channel),
                "modulation": descriptor,
                "reason": "undefined_descriptor",
            })
            continue
        if channel in paired:
            unsupported.append({
                "channel": channel,
                "instrument": _channel_instrument_name(song, channel),
                "modulation": descriptor,
                "reason": "joined_16bit_pair",
            })
    return unsupported


def _channel_instrument_name(song: IRSong, channel: int) -> str:
    """The name of the instrument that sounds on *channel*, for an error message."""
    inst_map = {inst.id: inst for inst in song.instruments}
    instrument = _sounding_instrument(song, channel, inst_map)
    return instrument.name if instrument is not None else f"channel {channel}"



def _note_to_midi(note: IRNote) -> Optional[int]:
    """Extract integer MIDI pitch from an IRNote, resolving pitch string if needed."""
    if note.midi_pitch is not None:
        return note.midi_pitch
    if note.pitch and str(note.pitch).upper() not in ("---", "REST", "OFF", "SIL", ""):
        return note_name_to_midi(str(note.pitch))
    return None


def _find_channel_instrument(song: IRSong, ch: int, inst_map: Dict[int, IRInstrument]) -> IRInstrument:
    """Determine the active instrument for a channel based on note assignments or role."""
    # 1. First non-rest note with valid instrument_id on this channel
    for pat in song.patterns:
        for note in pat.tracks.get(ch, []):
            if not note.is_rest and note.instrument_id is not None and note.instrument_id in inst_map:
                return inst_map[note.instrument_id]

    # 2. Any note (including rests) with valid instrument_id
    for pat in song.patterns:
        for note in pat.tracks.get(ch, []):
            if note.instrument_id is not None and note.instrument_id in inst_map:
                return inst_map[note.instrument_id]

    # 3. If any note on this channel has percussion role, look for percussion instrument
    for pat in song.patterns:
        for note in pat.tracks.get(ch, []):
            if note.channel_role == "percussion":
                for inst in inst_map.values():
                    if inst.role == "percussion" or inst.distortion == DISTORTION_WHITE_NOISE:
                        return inst
                return IRInstrument(
                    id=ch - 1,
                    name=f"Ch{ch}_Perc",
                    distortion=DISTORTION_WHITE_NOISE,
                    role="percussion",
                )

    # 4. Fallback: match by channel index ch - 1 if available in song.instruments
    if (ch - 1) in inst_map:
        return inst_map[ch - 1]
    if inst_map:
        return next(iter(inst_map.values()))
    return IRInstrument(id=ch - 1, name=f"Ch{ch}", distortion=DISTORTION_PURE_TONE)


def export_mads_asm(
    result: MusicGenerationResult | IRSong,
    output_path: Optional[str | Path] = None,
    song_label: str = "song_data",
    *,
    format_version: int = SONG_FORMAT_VERSION,
) -> str:
    """Export a song to relocatable MADS assembly code.
    
    Parameters
    ----------
    result : MusicGenerationResult or IRSong
        The song to export.
    output_path : Optional[str or Path]
        Path to save the generated assembly file.
    song_label : str
        Base label for the song data structure.
    format_version : int, default 1
        Target song format version (`1` for legacy/v1, `2` for SoA multi-instrument v2).
        
    Returns
    -------
    str
        Complete MADS assembly source code.
    """
    if format_version not in (SONG_FORMAT_VERSION, SONG_FORMAT_VERSION_2):
        raise FormatVersionError(
            f"unsupported export format_version {format_version!r}; expected 1 or 2"
        )

    song = result.pokey_ir if isinstance(result, MusicGenerationResult) else result

    audctl_val = resolve_audctl_mode(song)

    contoured = find_volume_contour_instruments(song)
    if contoured:
        raise VolumeContourNotExpressibleError(
            "this song carries a per-frame volume contour on "
            + ", ".join(f"{inst.name!r} ({len(inst.volume_contour)} frames)" for inst in contoured)
            + ". The MADS note table stores one volume per note and player.asm generates the "
            "per-frame envelope at run time, so the exported XEX could not reproduce the "
            "contour the WAV was rendered with. Export is refused rather than silently "
            "diverging from the rendered preview.",
            code=VolumeContourNotExpressibleError.code,
            detail={"instruments": [inst.name for inst in contoured]},
        )

    if format_version == SONG_FORMAT_VERSION:
        v2_reasons = song_requires_v2(song)
        if v2_reasons:
            raise FormatVersionError(
                "cannot export song in SONG_FORMAT_VERSION=1 because it uses v2 features: "
                + "; ".join(v2_reasons)
                + ". Pass format_version=2 explicitly to export v2 data."
            )

    if format_version == SONG_FORMAT_VERSION_2:
        return _export_mads_asm_v2(
            song=song,
            audctl_val=audctl_val,
            output_path=output_path,
            song_label=song_label,
        )

    unsupported_modulations = find_unsupported_modulations(song, audctl_val)
    if unsupported_modulations:
        described = ", ".join(
            f"channel {item['channel']} ({item['instrument']!r}, "
            f"{pokey_hw.describe_modulation(int(item['modulation']))})"
            for item in unsupported_modulations
        )
        reasons = {item["reason"] for item in unsupported_modulations}
        if "joined_16bit_pair" in reasons:
            why = (
                "the channel is joined into a 16-bit pair, so it has no divider of its own to "
                "move and player.asm has no paired form of the rule"
            )
        else:
            why = "this data format version does not define that modulation descriptor"
        raise ModulationNotExpressibleError(
            f"this song asks for a per-channel modulation the XEX format cannot encode: "
            f"{described}. {why}. Export is refused rather than producing an XEX that plays "
            "something the rendered preview does not.",
            code=ModulationNotExpressibleError.code,
            detail={"channels": unsupported_modulations},
        )

    lines: List[str] = []
    lines.append("; =============================================================================")
    lines.append(f"; Atari 8-bit POKEY Music Data — MADS Relocatable Format")
    lines.append(f"; Title: {song.title}")
    lines.append(f"; Author: {song.author}")
    lines.append(f"; Tempo: {song.tempo_bpm} BPM | frames_per_tick: {song.frames_per_tick} (50 Hz PAL)")
    lines.append(f"; Mode: AUDCTL=${audctl_val:02x} ({pokey_hw.describe_audctl(audctl_val)})")
    lines.append(f"; Format: version {SONG_FORMAT_VERSION} (6-byte instrument records; player.asm refuses any other version)")
    lines.append("; =============================================================================")
    lines.append("")

    # 1. Header
    lines.append(f"{song_label}:")
    lines.append(f"    .byte {song.frames_per_tick:<4} ; frames_per_tick")
    lines.append(f"    .byte ${audctl_val:02x}  ; audctl_mode")
    lines.append(f"    .word {song_label}_instruments")
    lines.append(f"    .word {song_label}_sequence")
    lines.append("")

    # 2. Instruments Table (Channels 1..4)
    inst_map = {inst.id: inst for inst in song.instruments}
    ch_instruments: Dict[int, IRInstrument] = {}
    for ch in range(1, 5):
        ch_instruments[ch] = _find_channel_instrument(song, ch, inst_map)

    lines.append(f"{song_label}_instruments:")
    # The format version sits immediately before the instrument records, which is also where
    # ``instruments_ptr`` points. Version 0 had no such byte, and its first instrument byte was
    # a generator -- always a multiple of $20 -- so a version-0 song can never present $01 here.
    lines.append(
        f"    .byte {SONG_FORMAT_VERSION:<4} ; format version (0 = no version byte, 5-byte records)"
    )
    # The modulation each channel's record carries, from the one helper that decides it, so the
    # emission and the refusals above cannot disagree.
    modulations = channel_modulations(song)
    for ch in range(1, 5):
        if song.uses_16bit_bass and ch == 2:
            # Channel 2 is the hardware frequency slave to Channel 1: it carries the
            # high divider byte and is the audible half of the pair. The frame compiler
            # writes Channel 1's instrument distortion into AUDC2, so the table must
            # publish that same value — hardcoding PURE_TONE here made the exported XEX
            # disagree with the rendered WAV whenever the pair's instrument was not a
            # pure tone (which is exactly what a profile-bound pair is).
            bass_inst = ch_instruments.get(1) or inst_map.get(1)
            dist = bass_inst.distortion if bass_inst else DISTORTION_PURE_TONE
            env = bass_inst.envelope if bass_inst else IRInstrument(id=1, name="Bass").envelope
            lines.append(
                f"    .byte ${dist:02x}, {env.attack_frames:>2}, {env.decay_frames:>2}, "
                f"{env.sustain_vol:>2}, {env.release_frames:>2}, "
                f"${modulations[ch]:02x}  "
                f"; Ch 2 (16-bit Bass Slave): dist, att, dec, sus, rel, modulation"
            )
            continue

        inst = ch_instruments[ch]
        env = inst.envelope
        dist = inst.distortion
        mod = modulations[ch]
        lines.append(
            f"    .byte ${dist:02x}, {env.attack_frames:>2}, {env.decay_frames:>2}, "
            f"{env.sustain_vol:>2}, {env.release_frames:>2}, ${mod:02x}  "
            f"; Ch {ch} ({inst.name}): dist, att, dec, sus, rel, "
            f"modulation ({pokey_hw.describe_modulation(mod)})"
        )
    lines.append("")

    # 3. Sequence Table
    lines.append(f"{song_label}_sequence:")
    for seq_idx, pat_id in enumerate(song.sequence):
        lines.append(f"    .word {song_label}_pat_{pat_id}_tracks  ; step {seq_idx} (pat {pat_id})")
    lines.append(f"    .word $ffff  ; end of sequence marker (loops to start)")
    lines.append("")

    # 4. Pattern Tracks Tables and Event Streams
    pattern_map = {p.id: p for p in song.patterns}
    unique_pat_ids = sorted(pattern_map.keys())

    for pat_id in unique_pat_ids:
        pat = pattern_map[pat_id]
        lines.append(f"; --- Pattern {pat_id} ({pat.name}) ---")
        lines.append(f"{song_label}_pat_{pat_id}_tracks:")
        for ch in range(1, 5):
            lines.append(f"    .word {song_label}_pat_{pat_id}_ch{ch}")
        lines.append("")

        for ch in range(1, 5):
            lines.append(f"{song_label}_pat_{pat_id}_ch{ch}:")
            if song.uses_16bit_bass and ch == 2:
                # 16-bit bass: Channel 2 is hardware slave to Channel 1.
                # Its track data contains the high divider (AUDF2) and active note volume.
                bass_notes = pat.tracks.get(1, [])
                if not bass_notes:
                    lines.append(f"    .byte $00, {pat.rows:>2}, $00  ; rest ({pat.rows} rows)")
                    lines.append(f"    .byte $ff           ; end of track")
                    lines.append("")
                    continue
                for note in bass_notes:
                    dur = max(1, min(255, note.duration))
                    midi_val = _note_to_midi(note)
                    if note.is_rest or midi_val is None:
                        lines.append(f"    .byte $00, {dur:>2}, $00  ; rest ({dur} rows)")
                    else:
                        freq = midi_pitch_to_frequency(midi_val)
                        _, div_hi = frequency_to_audf_16bit(freq, audctl=audctl_val, channel=1)
                        audf = pokey_hw.clamp_audf_for_tracker(div_hi)
                        vol = min(15, max(0, note.volume))
                        lines.append(f"    .byte ${audf:02x}, {dur:>2}, ${vol:02x}  ; 16-bit hi {note.pitch or 'bass'} ({dur} rows)")
                lines.append(f"    .byte $ff  ; end of track")
                lines.append("")
                continue

            track_notes = pat.tracks.get(ch, [])
            if not track_notes:
                # Empty channel: rest for the full pattern so channels stay aligned
                # (previously hardcoded to 32 rows regardless of pat.rows).
                lines.append(f"    .byte $00, {pat.rows:>2}, $00  ; rest ({pat.rows} rows)")
                lines.append(f"    .byte $ff           ; end of track")
                lines.append("")
                continue

            for note in track_notes:
                dur = max(1, min(255, note.duration))
                midi_val = _note_to_midi(note)
                unpitched_perc = pokey_hw.is_unpitched_percussion(midi_val, note.channel_role)
                if note.is_rest or (midi_val is None and not unpitched_perc):
                    # No resolvable pitch -> silence. Kept identical to the WAV frame
                    # compiler so both outputs agree (previously a hardcoded AUDF).
                    audf = 0
                    vol = 0
                elif unpitched_perc:
                    # Unpitched percussion: explicit fallback divider shared with the
                    # WAV frame compiler (previously silence here, MIDI 60 in the WAV).
                    audf = pokey_hw.clamp_audf_for_tracker(pokey_hw.PERCUSSION_DEFAULT_AUDF)
                    vol = min(15, max(0, note.volume))
                else:
                    freq = midi_pitch_to_frequency(midi_val)
                    if song.uses_16bit_bass and ch == 1:
                        # 16-bit bass channel 1: low byte divider, muted volume
                        div_low, _ = frequency_to_audf_16bit(freq, audctl=audctl_val, channel=1)
                        audf = pokey_hw.clamp_audf_for_tracker(div_low)
                        vol = 0
                    else:
                        audf = pokey_hw.clamp_audf_for_tracker(
                            frequency_to_audf_8bit(freq, audctl=audctl_val, channel=ch)
                        )
                        vol = min(15, max(0, note.volume))

                comment = f"; {note.pitch or 'rest'} ({dur} rows)" if not note.is_rest else f"; rest ({dur} rows)"
                lines.append(f"    .byte ${audf:02x}, {dur:>2}, ${vol:02x}  {comment}")

            lines.append(f"    .byte $ff  ; end of track")
            lines.append("")

    content = "\n".join(lines) + "\n"

    # Warn (never fail) when notes fall below the 8-bit range: POKEY will clamp them
    # to AUDF ``AUDF_TRACKER_MAX`` and the result is silently sharp.
    pitch_issues = find_pitch_range_issues(song)
    if pitch_issues:
        worst = max(pitch_issues, key=lambda issue: abs(float(issue["cents"])))
        logger.warning(
            "%d note(s) below the 8-bit POKEY range — e.g. %s: %.1f Hz requested, "
            "%.1f Hz representable (AUDF $%02x) = %+.0f cents in 8-bit mode; "
            "16-bit bass or a higher register would avoid the detuning.",
            len(pitch_issues),
            worst["pitch"],
            worst["requested_hz"],
            worst["representable_hz"],
            pokey_hw.AUDF_TRACKER_MAX,
            worst["cents"],
        )

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8")

    return content


def _export_mads_asm_v2(
    *,
    song: IRSong,
    audctl_val: int,
    output_path: Optional[str | Path],
    song_label: str,
) -> str:
    """Emit SONG_FORMAT_VERSION = 2 SoA instrument tables, macro pool, and v2 streams."""
    init_ch, soa_rows, macro_list, pat_streams = _validate_and_build_v2_tables(song, audctl_val)
    n_inst = len(soa_rows)

    lines: List[str] = []
    lines.append("; =============================================================================")
    lines.append("; Atari 8-bit POKEY Music Data — MADS Relocatable Format (v2 SoA)")
    lines.append(f"; Title: {song.title}")
    lines.append(f"; Author: {song.author}")
    lines.append(f"; Tempo: {song.tempo_bpm} BPM | frames_per_tick: {song.frames_per_tick} (50 Hz PAL)")
    lines.append(f"; Mode: AUDCTL=${audctl_val:02x} ({pokey_hw.describe_audctl(audctl_val)})")
    lines.append(f"; Format: version {SONG_FORMAT_VERSION_2} ({n_inst} SoA instruments, {len(macro_list)} macros)")
    lines.append("; =============================================================================")
    lines.append("")

    # 1. Song Header (6 bytes, compatible with v1)
    lines.append(f"{song_label}:")
    lines.append(f"    .byte {song.frames_per_tick:<4} ; frames_per_tick")
    lines.append(f"    .byte ${audctl_val:02x}  ; audctl_mode")
    lines.append(f"    .word {song_label}_instruments")
    lines.append(f"    .word {song_label}_sequence")
    lines.append("")

    # 2. Instruments v2 Header + SoA Tables
    lines.append(f"{song_label}_instruments:")
    lines.append(f"    .byte {SONG_FORMAT_VERSION_2:<4} ; format version 2")
    lines.append(f"    .byte {n_inst:<4} ; instrument_count (1..32)")
    lines.append(
        f"    .byte {init_ch[1]}, {init_ch[2]}, {init_ch[3]}, {init_ch[4]}  ; initial_ch_inst[0..3]"
    )
    lines.append(f"    .word {song_label}_macros")

    soa_fields = (
        ("inst_dist", "dist"),
        ("inst_att", "att"),
        ("inst_dec", "dec"),
        ("inst_sus", "sus"),
        ("inst_rel", "rel"),
        ("inst_flags", "flags"),
        ("inst_macro_off", "macro_off"),
        ("inst_p_start", "p_start"),
        ("inst_p_dur", "p_dur"),
        ("inst_p_step", "p_step"),
    )
    for label_suffix, key in soa_fields:
        vals = ", ".join(f"${row[key]:02x}" for row in soa_rows)
        lines.append(f"{song_label}_{label_suffix}:")
        lines.append(f"    .byte {vals}")
    lines.append("")

    # 3. Shared Macro Directory + Steps Pool
    lines.append(f"{song_label}_macros:")
    if macro_list:
        ptrs = ", ".join(f"{song_label}_macro_{i}" for i in range(len(macro_list)))
        lines.append(f"    .word {ptrs}")
        for m_idx, steps in enumerate(macro_list):
            lines.append(f"{song_label}_macro_{m_idx}:")
            for dur, flags, audc_b, audf_b, desc in steps:
                lines.append(
                    f"    .byte {dur:>3}, ${flags:02x}, ${audc_b:02x}, ${audf_b:02x}  ; {desc}"
                )
            lines.append(f"    .byte ${MACRO_END_MARKER:02x}  ; end of macro")
    else:
        lines.append("    .word $0000  ; no active macros")
    lines.append("")

    # 4. Sequence Table
    lines.append(f"{song_label}_sequence:")
    for seq_idx, pat_id in enumerate(song.sequence):
        lines.append(f"    .word {song_label}_pat_{pat_id}_tracks  ; step {seq_idx} (pat {pat_id})")
    lines.append("    .word $ffff  ; end of sequence marker (loops to start)")
    lines.append("")

    # 5. Pattern Tracks & Event Streams
    pattern_map = {p.id: p for p in song.patterns}
    for pat_id in sorted(pat_streams.keys()):
        pat = pattern_map[pat_id]
        lines.append(f"; --- Pattern {pat_id} ({pat.name}) ---")
        lines.append(f"{song_label}_pat_{pat_id}_tracks:")
        for ch in range(1, 5):
            lines.append(f"    .word {song_label}_pat_{pat_id}_ch{ch}")
        lines.append("")
        for ch in range(1, 5):
            lines.append(f"{song_label}_pat_{pat_id}_ch{ch}:")
            for _kind, raw, comment in pat_streams[pat_id][ch]:
                b_str = ", ".join(f"${b:02x}" for b in raw)
                lines.append(f"    .byte {b_str:<18} ; {comment}")
            lines.append("")

    content = "\n".join(lines) + "\n"

    pitch_issues = find_pitch_range_issues(song)
    if pitch_issues:
        worst = max(pitch_issues, key=lambda issue: abs(float(issue["cents"])))
        logger.warning(
            "%d note(s) below 8-bit POKEY range — e.g. %s: %.1f Hz requested, %.1f Hz representable",
            len(pitch_issues),
            worst["pitch"],
            worst["requested_hz"],
            worst["representable_hz"],
        )

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8")

    return content

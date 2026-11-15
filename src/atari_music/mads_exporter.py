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
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    find_pitch_range_issues,
    frequency_to_audf_16bit,
    frequency_to_audf_8bit,
    midi_pitch_to_frequency,
    note_name_to_midi,
    resolve_audctl_mode,
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
        
    Returns
    -------
    str
        Complete MADS assembly source code.
    """
    song = result.pokey_ir if isinstance(result, MusicGenerationResult) else result

    audctl_val = resolve_audctl_mode(song)

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

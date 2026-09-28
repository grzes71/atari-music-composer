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

2. Instruments Table (4 x 5 = 20 bytes):
   Per channel 1..4:
   .byte distortion            ; AUDC high nibble ($A0 = pure, $C0 = poly bass, $00 = noise)
   .byte attack_frames         ; Attack ramp frames (0..15)
   .byte decay_frames          ; Decay ramp frames (0..15)
   .byte sustain_vol           ; Sustain volume (0..15)
   .byte release_frames        ; Release fade frames (0..15)

3. Sequence Table:
   .word pat_0_tracks, pat_1_tracks, ..., $FFFF (terminator / loop target)

4. Pattern Track Lists:
   .word ch1_data, ch2_data, ch3_data, ch4_data

5. Track Event Streams (RLE 3-byte events):
   .byte audf, duration_ticks, volume
   ...
   .byte $FF                   ; End of track marker
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from atari_music.api import MusicGenerationResult
from atari_music.constants import (
    AUDCTL_CH1_179MHZ,
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    PAL_64KHZ_CLOCK,
)
from atari_music.ir import (
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    frequency_to_audf_16bit,
    frequency_to_audf_8bit,
    midi_pitch_to_frequency,
    note_name_to_midi,
)


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

    lines: List[str] = []
    lines.append("; =============================================================================")
    lines.append(f"; Atari 8-bit POKEY Music Data — MADS Relocatable Format")
    lines.append(f"; Title: {song.title}")
    lines.append(f"; Author: {song.author}")
    lines.append(f"; Tempo: {song.tempo_bpm} BPM | frames_per_tick: {song.frames_per_tick} (50 Hz PAL)")
    lines.append(f"; Mode: {'16-bit bass (AUDCTL=$50)' if song.uses_16bit_bass else 'Standard 4-channel 8-bit (AUDCTL=$00)'}")
    lines.append("; =============================================================================")
    lines.append("")

    # 1. Header
    audctl_val = AUDCTL_JOIN_1_2_16BIT if song.uses_16bit_bass else 0
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
    for ch in range(1, 5):
        if song.uses_16bit_bass and ch == 2:
            # Channel 2 is hardware slave to Channel 1 for 16-bit bass:
            # Uses pure tone distortion and shares the bass envelope from Channel 1
            bass_inst = ch_instruments.get(1) or inst_map.get(1)
            dist = DISTORTION_PURE_TONE
            env = bass_inst.envelope if bass_inst else IRInstrument(id=1, name="Bass").envelope
            lines.append(
                f"    .byte ${dist:02x}, {env.attack_frames:>2}, {env.decay_frames:>2}, {env.sustain_vol:>2}, {env.release_frames:>2}  "
                f"; Ch 2 (16-bit Bass Slave): dist, att, dec, sus, rel"
            )
            continue

        inst = ch_instruments[ch]
        env = inst.envelope
        dist = inst.distortion
        lines.append(
            f"    .byte ${dist:02x}, {env.attack_frames:>2}, {env.decay_frames:>2}, {env.sustain_vol:>2}, {env.release_frames:>2}  "
            f"; Ch {ch} ({inst.name}): dist, att, dec, sus, rel"
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
                    lines.append(f"    .byte $00, 32, $00  ; rest 32 ticks")
                    lines.append(f"    .byte $ff           ; end of track")
                    lines.append("")
                    continue
                for note in bass_notes:
                    dur = max(1, note.duration)
                    midi_val = _note_to_midi(note)
                    if note.is_rest or midi_val is None:
                        lines.append(f"    .byte $00, {dur:>2}, $00  ; rest ({dur} rows)")
                    else:
                        freq = midi_pitch_to_frequency(midi_val)
                        div_low, div_hi = frequency_to_audf_16bit(freq)
                        audf = min(254, div_hi)
                        vol = min(15, max(0, note.volume))
                        lines.append(f"    .byte ${audf:02x}, {dur:>2}, ${vol:02x}  ; 16-bit hi {note.pitch or 'bass'} ({dur} rows)")
                lines.append(f"    .byte $ff  ; end of track")
                lines.append("")
                continue

            track_notes = pat.tracks.get(ch, [])
            if not track_notes:
                # 32 rows of rest
                lines.append(f"    .byte $00, 32, $00  ; rest 32 ticks")
                lines.append(f"    .byte $ff           ; end of track")
                lines.append("")
                continue

            for note in track_notes:
                dur = max(1, note.duration)
                midi_val = _note_to_midi(note)
                if note.is_rest:
                    audf = 0
                    vol = 0
                elif midi_val is not None:
                    freq = midi_pitch_to_frequency(midi_val)
                    if song.uses_16bit_bass and ch == 1:
                        # 16-bit bass channel 1: low byte divider, muted volume
                        div_low, div_hi = frequency_to_audf_16bit(freq)
                        audf = min(254, div_low)
                        vol = 0
                    else:
                        audf = min(254, max(0, frequency_to_audf_8bit(freq)))
                        vol = min(15, max(0, note.volume))
                elif note.channel_role == "percussion":
                    vol = min(15, max(0, note.volume))
                    audf = 12 if vol >= 14 else (24 if vol >= 11 else 8)
                else:
                    audf = 0
                    vol = 0

                comment = f"; {note.pitch or 'rest'} ({dur} rows)" if not note.is_rest else f"; rest ({dur} rows)"
                lines.append(f"    .byte ${audf:02x}, {dur:>2}, ${vol:02x}  {comment}")

            lines.append(f"    .byte $ff  ; end of track")
            lines.append("")

    content = "\n".join(lines) + "\n"

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8")

    return content

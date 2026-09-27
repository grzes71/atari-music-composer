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
from typing import List, Optional

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
)


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
    lines.append(f"{song_label}_instruments:")
    for ch in range(1, 5):
        if song.uses_16bit_bass and ch == 2:
            # Channel 2 is hardware slave to Channel 1 for 16-bit bass:
            # Uses pure tone distortion and shares the bass envelope
            bass_inst = inst_map.get(1)
            dist = DISTORTION_PURE_TONE
            env = bass_inst.envelope if bass_inst else IRInstrument(id=1, name="Bass").envelope
            lines.append(
                f"    .byte ${dist:02x}, {env.attack_frames:>2}, {env.decay_frames:>2}, {env.sustain_vol:>2}, {env.release_frames:>2}  "
                f"; Ch 2 (16-bit Bass Slave): dist, att, dec, sus, rel"
            )
            continue

        # Default instrument IDs per channel
        def_inst_id = 1 if ch == 1 else (2 if ch == 2 else (0 if ch == 3 else 3))
        # Find if pattern tracks override
        inst = inst_map.get(def_inst_id)
        if not inst:
            inst = IRInstrument(id=def_inst_id, name=f"Ch{ch}", distortion=DISTORTION_PURE_TONE)

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
                    if note.is_rest or (note.midi_pitch is None and not note.pitch):
                        lines.append(f"    .byte $00, {dur:>2}, $00  ; rest ({dur} rows)")
                    else:
                        base_midi = note.midi_pitch or 36
                        freq = midi_pitch_to_frequency(base_midi)
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
                if note.is_rest or (note.midi_pitch is None and note.channel_role != "percussion"):
                    audf = 0
                    vol = 0
                elif song.uses_16bit_bass and ch == 1:
                    # 16-bit bass channel 1: low byte divider, muted volume
                    base_midi = note.midi_pitch or 36
                    freq = midi_pitch_to_frequency(base_midi)
                    div_low, div_hi = frequency_to_audf_16bit(freq)
                    audf = min(254, div_low)
                    vol = 0
                elif note.channel_role == "percussion":
                    vol = min(15, max(0, note.volume))
                    audf = 12 if vol >= 14 else (24 if vol >= 11 else 8)
                else:
                    base_midi = note.midi_pitch or 60
                    freq = midi_pitch_to_frequency(base_midi)
                    audf = min(254, max(0, frequency_to_audf_8bit(freq)))
                    vol = min(15, max(0, note.volume))

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

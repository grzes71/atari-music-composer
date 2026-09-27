"""Composition Interpreter: Converts AI Composition JSON into Symbolic Music IR and POKEY IR.

Transforms high-level, declarative AI compositions into:
    AI Composition JSON
             ↓
    Symbolic Music IR (MusicSong)
             ↓
       POKEY IR (IRSong)
             ↓
     MADS Exporter / WAV Synth
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from atari_music.ai.schema import (
    AICompositionDoc,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.ai.validation import normalize_channel_idx, validate_composition
from atari_music.constants import (
    DISTORTION_4BIT_POLY,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    midi_to_note_name,
    note_name_to_midi,
)
from atari_music.music_ir import (
    ChannelRole,
    MusicSong,
    SymbolicNote,
    SymbolicPattern,
    SymbolicTrack,
)


# =============================================================================
# Semantic Timbre Mapping
# =============================================================================

def map_instrument_character(
    inst_def: AIInstrumentDef,
    is_16bit_bass: bool = False,
) -> Tuple[int, IREnvelope, ChannelRole]:
    """Map semantic character string to POKEY distortion, ADSR envelope, and channel role."""
    char = (inst_def.character or "bright_lead").strip().lower()

    if "bass" in char:
        role = ChannelRole.BASS
        default_dist = DISTORTION_PURE_TONE if is_16bit_bass else DISTORTION_4BIT_POLY
        default_env = IREnvelope(attack_frames=0, decay_frames=4, sustain_vol=11, release_frames=2)
    elif "percussion" in char or "noise" in char or "drum" in char:
        role = ChannelRole.PERCUSSION
        default_dist = DISTORTION_WHITE_NOISE
        default_env = IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=8, release_frames=2)
    elif "dark" in char or "pad" in char or "drone" in char:
        role = ChannelRole.HARMONY
        default_dist = DISTORTION_PURE_TONE
        default_env = IREnvelope(attack_frames=2, decay_frames=6, sustain_vol=10, release_frames=4)
    elif "bell" in char or "ornament" in char or "high" in char:
        role = ChannelRole.HARMONY
        default_dist = DISTORTION_PURE_TONE
        default_env = IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=14, release_frames=1)
    elif "counter" in char or "harmony" in char:
        role = ChannelRole.HARMONY
        default_dist = DISTORTION_PURE_TONE
        default_env = IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=9, release_frames=2)
    else:  # bright_lead, lead, default
        role = ChannelRole.MELODY
        default_dist = DISTORTION_PURE_TONE
        default_env = IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=13, release_frames=2)

    # Apply explicit overrides if present
    dist = inst_def.distortion if inst_def.distortion is not None else default_dist
    att = inst_def.attack_frames if inst_def.attack_frames is not None else default_env.attack_frames
    dec = inst_def.decay_frames if inst_def.decay_frames is not None else default_env.decay_frames
    sus = inst_def.sustain_vol if inst_def.sustain_vol is not None else default_env.sustain_vol
    rel = inst_def.release_frames if inst_def.release_frames is not None else default_env.release_frames

    envelope = IREnvelope(attack_frames=att, decay_frames=dec, sustain_vol=sus, release_frames=rel)
    return dist, envelope, role


# =============================================================================
# Level 1 Translation: AI JSON -> Symbolic Music IR (MusicSong)
# =============================================================================

def interpret_composition_to_music_ir(doc: AICompositionDoc) -> MusicSong:
    """Translate validated AICompositionDoc into Symbolic Music IR (MusicSong).
    
    Converts step-based pattern channels into gapless sequential SymbolicNote tracks.
    """
    pattern_id_to_int: Dict[str, int] = {}
    symbolic_patterns: List[SymbolicPattern] = []

    # Map instruments to roles
    inst_role_map: Dict[str, ChannelRole] = {}
    for inst in doc.instruments:
        _, _, role = map_instrument_character(inst, doc.hardware.use_16bit_bass)
        inst_role_map[inst.id] = role

    for idx, pat in enumerate(doc.patterns):
        pattern_id_to_int[pat.id] = idx
        tracks_dict: Dict[int, SymbolicTrack] = {}

        # Organize events by 1-based channel index (1..4)
        ch_events_map: Dict[int, List[AIPatternChannelEvent]] = {ch: [] for ch in range(1, 5)}
        has_zero = any(str(k).strip() == "0" for k in pat.channels.keys())
        for ch_key, ev_list in pat.channels.items():
            ch_idx = normalize_channel_idx(ch_key, has_zero=has_zero)
            ch_events_map[ch_idx].extend(ev_list)

        for ch_idx in range(1, 5):
            events = sorted(ch_events_map[ch_idx], key=lambda e: e.step)
            track_notes: List[SymbolicNote] = []
            current_step = 0
            ev_idx = 0
            num_events = len(events)

            # Determine dominant channel role
            if events:
                first_inst = events[0].instrument
                track_role = inst_role_map.get(first_inst, ChannelRole.MELODY)
            elif ch_idx == 1:
                track_role = ChannelRole.BASS
            elif ch_idx == 4:
                track_role = ChannelRole.PERCUSSION
            elif ch_idx == 2:
                track_role = ChannelRole.HARMONY
            else:
                track_role = ChannelRole.MELODY

            while current_step < pat.length_steps:
                if ev_idx < num_events and events[ev_idx].step == current_step:
                    ev = events[ev_idx]
                    ev_idx += 1
                    dur = min(ev.duration, pat.length_steps - current_step)

                    is_rest = (ev.note is None) or str(ev.note).upper() in ("---", "REST", "OFF", "SIL", "")
                    midi_val = None if is_rest else note_name_to_midi(str(ev.note))
                    pitch_name = None if is_rest else (midi_to_note_name(midi_val) if midi_val is not None else str(ev.note))

                    note_role = inst_role_map.get(ev.instrument, track_role)
                    track_notes.append(
                        SymbolicNote(
                            pitch=midi_val,
                            pitch_name=pitch_name,
                            duration=dur,
                            velocity=ev.volume if ev.volume is not None else 14,
                            role=note_role,
                            is_rest=is_rest,
                            is_chord_tone=True,
                        )
                    )
                    current_step += dur
                else:
                    # Fill rest until next event or end of pattern
                    next_step = events[ev_idx].step if ev_idx < num_events else pat.length_steps
                    rest_dur = next_step - current_step
                    if rest_dur > 0:
                        track_notes.append(
                            SymbolicNote(
                                pitch=None,
                                pitch_name=None,
                                duration=rest_dur,
                                velocity=0,
                                role=track_role,
                                is_rest=True,
                                is_chord_tone=False,
                            )
                        )
                        current_step = next_step

            tracks_dict[ch_idx] = SymbolicTrack(
                channel_idx=ch_idx,
                role=track_role,
                notes=track_notes,
            )

        symbolic_patterns.append(
            SymbolicPattern(
                id=idx,
                name=pat.id,
                rows=pat.length_steps,
                tracks=tracks_dict,
            )
        )

    # Translate sequence string IDs to integer IDs
    numeric_sequence = [pattern_id_to_int[pid] for pid in doc.sequence]

    return MusicSong(
        title=doc.metadata.title,
        tempo_bpm=doc.metadata.bpm,
        meter="4/4",
        key=doc.metadata.key,
        mode=doc.metadata.mode,
        form=" ".join(doc.sequence),
        patterns=symbolic_patterns,
        sequence=numeric_sequence,
        min_channels=doc.hardware.channels,
        max_channels=doc.hardware.channels,
        style=doc.intent.style if doc.intent and doc.intent.style else "ai_composition",
    )


# =============================================================================
# Level 2 Translation: MusicSong + AI Doc -> POKEY IR (IRSong)
# =============================================================================

def compile_composition_to_pokey_ir(
    doc: AICompositionDoc,
    music_song: Optional[MusicSong] = None,
) -> IRSong:
    """Compile AI Composition into POKEY IR (IRSong) ready for synthesis and MADS export."""
    if music_song is None:
        music_song = interpret_composition_to_music_ir(doc)

    # 1. Map instruments to POKEY IR instruments
    inst_id_to_int: Dict[str, int] = {}
    ir_instruments: List[IRInstrument] = []

    for idx, inst_def in enumerate(doc.instruments):
        inst_id_to_int[inst_def.id] = idx
        dist, env, role = map_instrument_character(inst_def, doc.hardware.use_16bit_bass)
        ir_instruments.append(
            IRInstrument(
                id=idx,
                name=inst_def.name or inst_def.id,
                distortion=dist,
                role=role.value,
                envelope=env,
                is_16bit=(doc.hardware.use_16bit_bass and "bass" in inst_def.character.lower()),
            )
        )

    # Ensure at least standard channels have instrument mappings
    if not ir_instruments:
        # Default fallback instruments
        ir_instruments = [
            IRInstrument(id=0, name="Lead", distortion=DISTORTION_PURE_TONE, role="melody", envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=12, release_frames=2)),
            IRInstrument(id=1, name="Bass", distortion=DISTORTION_PURE_TONE if doc.hardware.use_16bit_bass else DISTORTION_4BIT_POLY, role="bass", envelope=IREnvelope(attack_frames=0, decay_frames=4, sustain_vol=11, release_frames=2)),
            IRInstrument(id=2, name="Harmony", distortion=DISTORTION_PURE_TONE, role="harmony", envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=9, release_frames=2)),
            IRInstrument(id=3, name="Percussion", distortion=DISTORTION_WHITE_NOISE, role="percussion", envelope=IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=8, release_frames=2)),
        ]

    # Map pattern events from AI Doc directly into IRNote tracks with matching instrument IDs
    ai_pat_map = {p.id: p for p in doc.patterns}
    pokey_patterns: List[IRPattern] = []

    for sp in music_song.patterns:
        ai_pat = ai_pat_map.get(sp.name)
        ir_tracks: Dict[int, List[IRNote]] = {}

        ai_has_zero = any(str(k).strip() == "0" for k in ai_pat.channels.keys()) if ai_pat else False
        for ch_idx, track in sp.tracks.items():
            ir_notes: List[IRNote] = []
            for n in track.notes:
                # Find matching instrument ID
                inst_id = 0
                if ai_pat and ch_idx in [normalize_channel_idx(k, has_zero=ai_has_zero) for k in ai_pat.channels.keys()]:
                    # Find instrument referenced by channel events
                    for orig_k, ev_list in ai_pat.channels.items():
                        if normalize_channel_idx(orig_k, has_zero=ai_has_zero) == ch_idx and ev_list:
                            first_inst_str = ev_list[0].instrument
                            inst_id = inst_id_to_int.get(first_inst_str, 0)
                            break
                else:
                    inst_id = 1 if ch_idx == 1 else (2 if ch_idx == 2 else (0 if ch_idx == 3 else 3))

                # Handle percussion role
                if track.role == ChannelRole.PERCUSSION:
                    inst_id = 3

                ir_notes.append(
                    IRNote(
                        pitch=n.pitch_name,
                        midi_pitch=n.pitch,
                        duration=n.duration,
                        volume=n.velocity,
                        instrument_id=inst_id,
                        channel_role=track.role.value,
                        is_rest=n.is_rest,
                    )
                )
            ir_tracks[ch_idx] = ir_notes
        pokey_patterns.append(IRPattern(id=sp.id, name=sp.name, rows=sp.rows, tracks=ir_tracks))

    # Calculate frames per tick from tempo
    if music_song.tempo_bpm <= 80:
        frames_per_tick = 6
    elif music_song.tempo_bpm <= 110:
        frames_per_tick = 5
    elif music_song.tempo_bpm <= 145:
        frames_per_tick = 4
    else:
        frames_per_tick = 3

    return IRSong(
        title=music_song.title,
        author=doc.metadata.author,
        tempo_bpm=music_song.tempo_bpm,
        frames_per_tick=frames_per_tick,
        key=music_song.key,
        mode=music_song.mode,
        instruments=ir_instruments,
        patterns=pokey_patterns,
        sequence=music_song.sequence,
        uses_16bit_bass=doc.hardware.use_16bit_bass,
    )

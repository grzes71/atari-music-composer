"""Composer v2: Controlled Procedural Music Generator for Atari POKEY.

Implements the multi-layer pipeline:
STYLE MODEL -> COMPOSER ENGINE -> MUSIC IR -> CONSTRAINT ENGINE -> POKEY COMPILER -> POKEY IR -> SYNTHESIZER

Key Features:
- Rule-based generation (Contours, Interval Grammar, Motivic Mutations A -> A' -> A'')
- Harmonic Progressions (Chord functions: Tonic, Predominant, Dominant, Resolution)
- Independent Bass (Counter-motion, Root, Walking, Ostinato)
- Decoupled Rhythm Engine (Meter, Density, Syncopation)
- Configurable Novelty parameter (0.0 .. 1.0)
- Hard Memory Constraint (Strictly <= 2048 B with active deduplication & sequence optimization)
- Channel flexibility (2-channel to 4-channel support)
- Generate-and-Test loop with up to max_attempts retries
- Transparent 11-metric Quality Report per song
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from atari_music.bass_engine import generate_bassline
from atari_music.constants import (
    DISTORTION_4BIT_POLY,
    DISTORTION_5BIT_POLY_1,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.contour_engine import generate_contour_intervals, realize_pitches_from_intervals
from atari_music.generator import KEY_BASE_MIDI, SCALES
from atari_music.harmony_engine import get_chord_tones, select_progression
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRPattern,
    IRSong,
    calculate_ir_binary_size,
    compile_ir_to_pokey_frames,
    midi_to_note_name,
)
from atari_music.music_ir import (
    ChannelRole,
    ChordStep,
    MelodicContour,
    MusicPhrase,
    MusicSong,
    SymbolicNote,
    SymbolicPattern,
    SymbolicTrack,
)
from atari_music.mutations import generate_phrase_variation
from atari_music.pokey_synth import render_pokey_to_wav
from atari_music.rhythm_engine import generate_rhythm_template


@dataclass
class ComposerV2Config:
    """Configurable profile for Composer v2."""
    seed: int = 42
    max_size: int = 2048
    min_channels: int = 2
    max_channels: int = 4
    duration: int = 25              # Target duration in seconds
    tempo: int = 130
    key: str = "C"
    mode: str = "minor"
    style: str = "atari_1980s"
    novelty: float = 0.50
    repetition: float = 0.65
    syncopation: float = 0.35
    max_attempts: int = 100


class QualityReport(BaseModel):
    """Detailed quality and structural metrics for a generated song."""
    memory_size: int
    under_budget: bool
    channels_used: int
    duration: float
    tempo: int
    pitch_range: int
    repetition: float
    novelty: float
    melodic_density: float
    rhythmic_density: float
    harmonic_complexity: float
    pattern_count: int
    attempts_needed: int


class ComposerV2Result(BaseModel):
    """Output bundle of Composer v2."""
    music_ir: MusicSong
    pokey_ir: IRSong
    quality_report: QualityReport
    wav_path: Optional[str] = None


def compose_song_v2(config: ComposerV2Config) -> ComposerV2Result:
    """Execute Generate-and-Test loop to compose an authentic POKEY song satisfying constraints."""
    rng = random.Random(config.seed)

    for attempt in range(1, config.max_attempts + 1):
        # 1. STYLE MODEL & HARMONY
        key = config.key
        mode = config.mode
        root_midi = KEY_BASE_MIDI.get(key, 60)
        scale = SCALES.get(mode, SCALES["minor"])
        progression = select_progression(mode, rng)

        # 2. FORM GENERATION (e.g. "A B A' B" or "A A' B A")
        form_templates = ["A B A B", "A B A' B", "A A' B A", "A A B B"]
        chosen_form = rng.choice(form_templates)
        form_labels = chosen_form.split()

        # 3. PHRASE GENERATION (Motif A -> Interval Grammar -> Mutations A' / A'')
        contour_a = rng.choice([
            MelodicContour.WAVE,
            MelodicContour.ARCH,
            MelodicContour.QUESTION_ANSWER,
            MelodicContour.ASCENDING,
        ])
        phrase_a_rhythm = generate_rhythm_template(
            total_rows=32,
            density="medium" if config.novelty < 0.7 else "high",
            syncopation=config.syncopation,
            rng=rng,
        )
        phrase_a_intervals = generate_contour_intervals(contour_a, len(phrase_a_rhythm), rng)
        phrase_a = MusicPhrase(id="A", contour=contour_a, intervals=phrase_a_intervals, rhythm=phrase_a_rhythm)

        # Phrase A' (Variation)
        phrase_a_prime = generate_phrase_variation(phrase_a, "A'", config.novelty, scale, rng)

        # Phrase B (Contrast)
        contour_b = rng.choice([MelodicContour.UP, MelodicContour.DESCENDING, MelodicContour.ARCH])
        phrase_b_rhythm = generate_rhythm_template(32, "high" if config.novelty >= 0.5 else "medium", config.syncopation, rng)
        phrase_b_intervals = generate_contour_intervals(contour_b, len(phrase_b_rhythm), rng)
        phrase_b = MusicPhrase(id="B", contour=contour_b, intervals=phrase_b_intervals, rhythm=phrase_b_rhythm)

        phrases_map = {"A": phrase_a, "A'": phrase_a_prime, "B": phrase_b}

        # 4. PATTERN GENERATION
        # Determine number of active channels
        channels_count = config.max_channels if config.max_channels == config.min_channels else rng.choice(
            list(range(config.min_channels, config.max_channels + 1))
        )
        uses_16bit = (channels_count >= 3) and (rng.random() < 0.40)

        patterns: List[SymbolicPattern] = []
        unique_phrase_ids = sorted(list(set(form_labels)))
        pat_id_map: Dict[str, int] = {}

        for p_idx, p_label in enumerate(unique_phrase_ids):
            phrase = phrases_map.get(p_label, phrase_a)
            pat = _build_symbolic_pattern(
                pat_id=p_idx,
                phrase=phrase,
                progression=progression,
                scale=scale,
                root_midi=root_midi,
                channels_count=channels_count,
                uses_16bit=uses_16bit,
                novelty=config.novelty,
                rng=rng,
            )
            patterns.append(pat)
            pat_id_map[p_label] = p_idx

        # 5. SEQUENCE GENERATION
        # Map form labels to pattern indices
        sequence = [pat_id_map[lbl] for lbl in form_labels]
        # Repeat form to fill target duration (e.g. 2 x form)
        target_sections = max(6, int(round(config.duration / 2.56)))
        while len(sequence) < target_sections:
            sequence.extend([pat_id_map[lbl] for lbl in form_labels])
        sequence = sequence[:target_sections]

        # 6. ASSEMBLE MUSIC IR
        music_song = MusicSong(
            title=f"ComposerV2 #{config.seed:03d} ({key} {mode}, Nov {config.novelty:.2f})",
            tempo_bpm=config.tempo,
            key=key,
            mode=mode,
            progression=progression,
            form=chosen_form,
            phrases=phrases_map,
            patterns=patterns,
            sequence=sequence,
            min_channels=config.min_channels,
            max_channels=config.max_channels,
            novelty=config.novelty,
            style=config.style,
        )

        # 7. COMPILE MUSIC IR -> POKEY IR
        pokey_song = _compile_music_to_pokey_ir(music_song, uses_16bit, channels_count, rng)

        # 8. CONSTRAINT CHECK & MEMORY OPTIMIZATION (< 2048 B)
        mem_size = calculate_ir_binary_size(pokey_song)

        if mem_size > config.max_size:
            # Active Optimization: deduplicate patterns & trim sequence
            pokey_song = _optimize_pokey_song_memory(pokey_song, config.max_size)
            mem_size = calculate_ir_binary_size(pokey_song)

        if mem_size <= config.max_size and config.min_channels <= channels_count <= config.max_channels:
            # Success! Build Quality Report
            quality = _calculate_quality_report(music_song, pokey_song, mem_size, channels_count, attempt, config)
            return ComposerV2Result(music_ir=music_song, pokey_ir=pokey_song, quality_report=quality)

        # If failed, loop mutates random state for next attempt
        rng.seed(config.seed + attempt * 17)

    # If loop exhausted without meeting constraints:
    raise RuntimeError(
        f"Generation failed after {config.max_attempts} attempts. Constraints could not be satisfied."
    )


def _build_symbolic_pattern(
    pat_id: int,
    phrase: MusicPhrase,
    progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    channels_count: int,
    uses_16bit: bool,
    novelty: float,
    rng: random.Random,
) -> SymbolicPattern:
    """Build a symbolic multi-track pattern adhering to the phrase contour and harmony."""
    tracks: Dict[int, SymbolicTrack] = {}

    # Realize melody pitches from relative intervals
    chord_tones = get_chord_tones(progression[0] if progression else ChordStep(degree=0, name="i"), scale)
    melody_pitches = realize_pitches_from_intervals(root_midi, phrase.intervals, scale, chord_tones)

    # Lead Melody Track (Channel 1 in 2-ch mode or Channel 3 in 4-ch mode)
    lead_ch = 2 if channels_count == 2 else 3
    lead_notes: List[SymbolicNote] = []
    for dur, pitch in zip(phrase.rhythm, melody_pitches):
        lead_notes.append(
            SymbolicNote(
                pitch=pitch,
                pitch_name=midi_to_note_name(pitch),
                duration=dur,
                velocity=15,
                role=ChannelRole.MELODY,
            )
        )
    tracks[lead_ch] = SymbolicTrack(channel_idx=lead_ch, role=ChannelRole.MELODY, notes=lead_notes)

    # Bassline Track (Channel 1)
    bass_role = rng.choice(["counter_motion", "ostinato", "octave", "walking", "root_bass"])
    bass_notes = generate_bassline(
        rows=32,
        base_midi=root_midi,
        chord_progression=progression,
        scale=scale,
        role_type=bass_role,
        melody_pitches=melody_pitches,
        uses_16bit=uses_16bit,
        rng=rng,
    )
    tracks[1] = SymbolicTrack(channel_idx=1, role=ChannelRole.BASS, notes=bass_notes)

    # 4-Channel Accompaniment and Percussion (if channels_count >= 3)
    if channels_count >= 3:
        if uses_16bit:
            # Channel 2 is slave for 16-bit bass
            tracks[2] = SymbolicTrack(
                channel_idx=2,
                role=ChannelRole.BASS,
                notes=[SymbolicNote(duration=32, is_rest=True, role=ChannelRole.BASS)],
            )
        else:
            # Channel 2: Arpeggiated harmony
            harm_notes: List[SymbolicNote] = []
            for step in range(16):
                chord_idx = (step * len(progression)) // 16
                tones = get_chord_tones(progression[chord_idx], scale)
                p = (root_midi - 12) + tones[step % len(tones)]
                harm_notes.append(SymbolicNote(pitch=p, duration=2, velocity=7, role=ChannelRole.HARMONY))
            tracks[2] = SymbolicTrack(channel_idx=2, role=ChannelRole.HARMONY, notes=harm_notes)

    if channels_count >= 4:
        # Channel 4: Percussion Track (Kick, Snare, Hi-Hat)
        drum_notes: List[SymbolicNote] = []
        for r in range(0, 32, 2):
            if r % 8 == 0:
                drum_notes.append(SymbolicNote(duration=2, velocity=15, role=ChannelRole.PERCUSSION))
            elif r % 8 == 4:
                drum_notes.append(SymbolicNote(duration=2, velocity=15, role=ChannelRole.PERCUSSION))
            else:
                drum_notes.append(SymbolicNote(duration=2, velocity=10, role=ChannelRole.PERCUSSION))
        tracks[4] = SymbolicTrack(channel_idx=4, role=ChannelRole.PERCUSSION, notes=drum_notes)

    return SymbolicPattern(id=pat_id, name=f"Pat {phrase.id}", rows=32, tracks=tracks)


def _compile_music_to_pokey_ir(
    music_song: MusicSong,
    uses_16bit: bool,
    channels_count: int,
    rng: random.Random,
) -> IRSong:
    """Compile MusicSong into hardware-aware POKEY IRSong."""
    # Build standard POKEY instruments
    instruments = [
        IRInstrument(
            id=0,
            name="Lead Tone",
            distortion=DISTORTION_PURE_TONE if rng.random() > 0.3 else DISTORTION_4BIT_POLY,
            role="melody",
            envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=12, release_frames=2),
            vibrato_depth=1 if music_song.novelty >= 0.5 else 0,
            vibrato_speed=2,
        ),
        IRInstrument(
            id=1,
            name="Bass Voice",
            distortion=DISTORTION_PURE_TONE if uses_16bit else DISTORTION_4BIT_POLY,
            role="bass",
            envelope=IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=9, release_frames=2),
            is_16bit=uses_16bit,
        ),
        IRInstrument(
            id=2,
            name="Harmony Arp",
            distortion=DISTORTION_PURE_TONE,
            role="harmony",
            envelope=IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=6, release_frames=1),
        ),
        IRInstrument(
            id=3,
            name="Kick Drum",
            distortion=DISTORTION_4BIT_POLY,
            role="percussion",
            macro=[
                IRMacroStep(audf_offset=44, distortion=DISTORTION_4BIT_POLY, volume=15),
                IRMacroStep(audf_offset=75, distortion=DISTORTION_4BIT_POLY, volume=12),
                IRMacroStep(audf_offset=120, distortion=DISTORTION_PURE_TONE, volume=6),
                IRMacroStep(audf_offset=160, distortion=DISTORTION_PURE_TONE, volume=0),
            ],
        ),
        IRInstrument(
            id=4,
            name="Snare Drum",
            distortion=DISTORTION_WHITE_NOISE,
            role="percussion",
            macro=[
                IRMacroStep(audf_offset=12, distortion=DISTORTION_4BIT_POLY, volume=15),
                IRMacroStep(audf_offset=16, distortion=0x80, volume=13),
                IRMacroStep(audf_offset=24, distortion=0x80, volume=7),
                IRMacroStep(audf_offset=30, distortion=0x80, volume=0),
            ],
        ),
        IRInstrument(
            id=5,
            name="Hi-Hat",
            distortion=0x80,
            role="percussion",
            macro=[
                IRMacroStep(audf_offset=3, distortion=0x80, volume=9),
                IRMacroStep(audf_offset=4, distortion=0x80, volume=0),
            ],
        ),
    ]

    # Convert SymbolicPatterns to IRPatterns
    pokey_patterns: List[IRPattern] = []
    for sp in music_song.patterns:
        ir_tracks: Dict[int, List[IRNote]] = {}
        for ch, track in sp.tracks.items():
            ir_notes: List[IRNote] = []
            for n in track.notes:
                inst_id = 0
                if track.role == ChannelRole.BASS:
                    inst_id = 1
                elif track.role == ChannelRole.HARMONY:
                    inst_id = 2
                elif track.role == ChannelRole.PERCUSSION:
                    # Alternating drum instruments
                    inst_id = 3 if n.velocity == 15 else 5

                ir_notes.append(
                    IRNote(
                        pitch=n.pitch_name,
                        midi_pitch=n.pitch,
                        duration=n.duration,
                        volume=n.velocity,
                        instrument_id=inst_id,
                        channel_role=track.role.value,
                        is_rest=n.is_rest or (n.pitch is None and track.role != ChannelRole.PERCUSSION),
                    )
                )
            ir_tracks[ch] = ir_notes
        pokey_patterns.append(IRPattern(id=sp.id, name=sp.name, rows=sp.rows, tracks=ir_tracks))

    frames_per_tick = 4 if music_song.tempo_bpm <= 135 else 3

    return IRSong(
        title=music_song.title,
        author="Composer v2 Engine",
        tempo_bpm=music_song.tempo_bpm,
        frames_per_tick=frames_per_tick,
        key=music_song.key,
        mode=music_song.mode,
        instruments=instruments,
        patterns=pokey_patterns,
        sequence=music_song.sequence,
        uses_16bit_bass=uses_16bit,
    )


def deduplicate_pokey_patterns(song: IRSong) -> Tuple[IRSong, int]:
    """Pattern deduplication: merge identical patterns and remap sequence entries."""
    unique_patterns: List[IRPattern] = []
    remap: Dict[int, int] = {}
    old_to_new_id: Dict[int, int] = {}

    for p in song.patterns:
        match = None
        for u in unique_patterns:
            if u.rows == p.rows and len(u.tracks) == len(p.tracks):
                if repr(u.tracks) == repr(p.tracks):
                    match = u.id
                    break
        if match is not None:
            remap[p.id] = match
        else:
            unique_patterns.append(p)
            remap[p.id] = p.id

    # Renumber unique patterns consecutively 0, 1, ...
    for new_idx, pat in enumerate(unique_patterns):
        old_id = pat.id
        old_to_new_id[old_id] = new_idx
        pat.id = new_idx

    final_sequence = []
    for seq_item in song.sequence:
        if isinstance(seq_item, list):
            final_sequence.append([old_to_new_id.get(remap.get(x, x), 0) for x in seq_item])
        else:
            final_sequence.append(old_to_new_id.get(remap.get(seq_item, seq_item), 0))

    removed_count = len(song.patterns) - len(unique_patterns)
    song.patterns = unique_patterns
    song.sequence = final_sequence
    return song, removed_count


def _optimize_pokey_song_memory(song: IRSong, max_size: int) -> IRSong:
    """Active memory optimization: pattern deduplication & sequence compaction."""
    # Deduplicate patterns first
    song, _ = deduplicate_pokey_patterns(song)

    # If song still exceeds budget, trim sequence length until within budget
    while calculate_ir_binary_size(song) > max_size and len(song.sequence) > 6:
        song.sequence = song.sequence[:-1]

    return song



def _calculate_quality_report(
    music_song: MusicSong,
    pokey_song: IRSong,
    mem_size: int,
    channels_count: int,
    attempt: int,
    config: ComposerV2Config,
) -> QualityReport:
    """Calculate the 11 transparent quality metrics."""
    frames = compile_ir_to_pokey_frames(pokey_song)
    duration_sec = round(frames.shape[0] / 50.0, 2)

    # Unique notes & pitch range
    all_midi = []
    for pat in pokey_song.patterns:
        for ch, notes in pat.tracks.items():
            for n in notes:
                if not n.is_rest and n.midi_pitch is not None:
                    all_midi.append(n.midi_pitch)

    pitch_range = (max(all_midi) - min(all_midi)) if all_midi else 0
    seq = pokey_song.sequence
    repetition = round(1.0 - (len(set(seq)) / max(1, len(seq))), 3)

    # Densities
    total_notes = len(all_midi)
    melodic_density = round(total_notes / max(1.0, duration_sec), 2)
    rhythmic_density = round(len(seq) * 32 / max(1.0, duration_sec), 2)
    harmonic_complexity = round(len(music_song.progression) / 4.0, 2)

    return QualityReport(
        memory_size=mem_size,
        under_budget=mem_size <= config.max_size,
        channels_used=channels_count,
        duration=duration_sec,
        tempo=pokey_song.tempo_bpm,
        pitch_range=pitch_range,
        repetition=max(0.0, repetition),
        novelty=config.novelty,
        melodic_density=melodic_density,
        rhythmic_density=rhythmic_density,
        harmonic_complexity=harmonic_complexity,
        pattern_count=len(pokey_song.patterns),
        attempts_needed=attempt,
    )

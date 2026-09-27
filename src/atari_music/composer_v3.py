"""Composer v3: Style-Driven Procedural Music Generator for Atari POKEY.

Implements the profile-governed multi-layer composition pipeline:
MUSIC PROFILE -> FORM PLANNER -> HARMONY & CONTOUR -> RHYTHM & BASS -> MUSIC IR -> CONSTRAINT OPTIMIZER -> POKEY IR -> PLAYER

Solves the diversity limitations discovered in Stage 6.6:
- True Multi-Section Forms: INTRO, A, B, A', C, OUTRO (cadential resolution, not infinite loops)
- Genuine Continuous Tempos: 65 to 185 BPM tailored to profile (Dungeon 65-90, Action 155-185, Title 75-100)
- Profile-Driven Rhythm Families: sparse, lyrical, driving, syncopated, ostinato, march, playful
- Specialized Harmonic Languages: modal pedal, Phrygian tension, fanfare major, Dorian, natural minor
- Profile-Tuned Bass & Percussion: pedal drone, dark ostinato, fanfare bass, driving pulse, bouncy staccato
- Active Memory Optimization with pattern deduplication guaranteeing <= 2048 B
- Strict Seed Determinism
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
from atari_music.contour_engine import (
    generate_archetype_intervals,
    generate_contour_intervals,
    realize_pitches_from_intervals,
)
from atari_music.generator import KEY_BASE_MIDI, SCALES
from atari_music.harmony_engine import (
    ChordStep,
    get_chord_tones,
    select_profile_progression,
    select_progression,
)
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
    HarmonicFunction,
    MelodicContour,
    MusicPhrase,
    MusicSong,
    SymbolicNote,
    SymbolicPattern,
    SymbolicTrack,
)
from atari_music.mutations import generate_phrase_variation
from atari_music.pokey_synth import render_pokey_to_wav
from atari_music.profiles import MusicProfile, get_profile
from atari_music.rhythm_engine import generate_profile_rhythm


@dataclass
class ComposerV3Config:
    """Configuration bundle for Composer v3."""
    profile: str | MusicProfile = "title"
    seed: int = 42
    tempo: Optional[int] = None
    key: Optional[str] = None
    mode: Optional[str] = None
    novelty: Optional[float] = None
    duration: Optional[int] = None
    max_size: int = 2048
    min_channels: Optional[int] = None
    max_channels: Optional[int] = None
    max_attempts: int = 100


class ComposerV3QualityReport(BaseModel):
    """Detailed structural and musical quality metrics for Composer v3."""
    profile_name: str
    memory_size: int
    under_budget: bool
    channels_used: int
    duration: float
    tempo: int
    form: str
    pitch_range: int
    repetition: float
    novelty: float
    melodic_density: float
    rhythmic_density: float
    harmonic_complexity: float
    pattern_count: int
    attempts_needed: int


class ComposerV3Result(BaseModel):
    """Result artifact of Composer v3 generation."""
    music_ir: MusicSong
    pokey_ir: IRSong
    profile_name: str
    quality_report: ComposerV3QualityReport
    wav_path: Optional[str] = None


def compose_song_v3(
    profile: str | MusicProfile = "title",
    seed: int = 42,
    tempo: Optional[int] = None,
    key: Optional[str] = None,
    mode: Optional[str] = None,
    novelty: Optional[float] = None,
    duration: Optional[int] = None,
    max_size: int = 2048,
    min_channels: Optional[int] = None,
    max_channels: Optional[int] = None,
    max_attempts: int = 100,
) -> ComposerV3Result:
    """Master entry point for Composer v3: Style-Driven Procedural Generator."""
    cfg = ComposerV3Config(
        profile=profile,
        seed=seed,
        tempo=tempo,
        key=key,
        mode=mode,
        novelty=novelty,
        duration=duration,
        max_size=max_size,
        min_channels=min_channels,
        max_channels=max_channels,
        max_attempts=max_attempts,
    )
    return _execute_composer_v3(cfg)


def _execute_composer_v3(config: ComposerV3Config) -> ComposerV3Result:
    """Generate-and-Test loop for Composer v3."""
    prof = get_profile(config.profile)
    rng = random.Random(config.seed)

    for attempt in range(1, config.max_attempts + 1):
        # 1. PARAMETER RESOLUTION FROM PROFILE
        # Tempo
        if config.tempo is not None:
            actual_tempo = config.tempo
        else:
            t_min, t_max = prof.tempo_range
            actual_tempo = rng.randint(t_min, t_max)

        # Mode & Key
        actual_mode = config.mode if config.mode else rng.choice(prof.allowed_modes)
        all_keys = ["C", "D", "E", "F", "G", "A", "B"]
        actual_key = config.key if config.key else rng.choice(all_keys)

        # Novelty
        if config.novelty is not None:
            actual_novelty = config.novelty
        else:
            n_min, n_max = prof.novelty_range
            actual_novelty = round(rng.uniform(n_min, n_max), 2)

        # Register & Root MIDI
        if prof.register == "low":
            root_midi = KEY_BASE_MIDI.get(actual_key, 60) - 12
            min_lead, max_lead = 45, 68
        elif prof.register == "high":
            root_midi = KEY_BASE_MIDI.get(actual_key, 60) + 7
            min_lead, max_lead = 62, 86
        elif prof.register == "wide":
            root_midi = KEY_BASE_MIDI.get(actual_key, 60)
            min_lead, max_lead = 48, 84
        else:  # mid
            root_midi = KEY_BASE_MIDI.get(actual_key, 60)
            min_lead, max_lead = 55, 80

        scale = SCALES.get(actual_mode, SCALES["minor"])

        # Channels count
        min_ch = config.min_channels if config.min_channels is not None else prof.min_channels
        max_ch = config.max_channels if config.max_channels is not None else prof.max_channels
        channels_count = max_ch if min_ch == max_ch else rng.choice(list(range(min_ch, max_ch + 1)))

        uses_16bit = (channels_count >= 3) and (rng.random() < prof.uses_16bit_bass_chance)

        # 2. HARMONY SELECTION
        progression = select_profile_progression(actual_mode, prof.name, rng)

        # 3. FORM SELECTION & MULTI-SECTION PLANNING
        chosen_form = rng.choice(prof.form_choices)
        form_sections = chosen_form.split()

        # 4. PHRASE COMPOSITION (INTRO, A, B, A', C, OUTRO)
        unique_sections = list(dict.fromkeys(form_sections))
        phrases_map: Dict[str, MusicPhrase] = {}

        # Base phrase A archetype & rhythm
        arch_a = rng.choice(prof.melodic_archetypes)
        rhythm_a = generate_profile_rhythm(prof.rhythm_family, 32, syncopation=0.2 + 0.4 * actual_novelty, rng=rng)
        intervals_a = generate_archetype_intervals(arch_a, len(rhythm_a), rng)
        phrases_map["A"] = MusicPhrase(id="A", intervals=intervals_a, rhythm=rhythm_a)

        # Phrase A' (Motivic variation of A)
        if "A'" in unique_sections or "A" in unique_sections:
            phrases_map["A'"] = generate_phrase_variation(
                base_phrase=phrases_map["A"],
                variation_id="A'",
                novelty=actual_novelty,
                scale=scale,
                rng=rng,
            )

        # Phrase B (Contrasting theme)
        if "B" in unique_sections:
            arch_b = rng.choice(prof.melodic_archetypes)
            rhythm_b = generate_profile_rhythm(prof.rhythm_family, 32, syncopation=0.3 + 0.3 * actual_novelty, rng=rng)
            intervals_b = generate_archetype_intervals(arch_b, len(rhythm_b), rng)
            phrases_map["B"] = MusicPhrase(id="B", intervals=intervals_b, rhythm=rhythm_b)

        # Phrase C (Climax / secondary contrast)
        if "C" in unique_sections:
            arch_c = "fanfare" if prof.name == "ending" else "ascending"
            rhythm_c = generate_profile_rhythm(prof.rhythm_family, 32, syncopation=0.4, rng=rng)
            intervals_c = generate_archetype_intervals(arch_c, len(rhythm_c), rng)
            phrases_map["C"] = MusicPhrase(id="C", intervals=intervals_c, rhythm=rhythm_c)

        # Section INTRO
        if "INTRO" in unique_sections:
            intro_rhythm = [8, 8, 8, 8] if prof.rhythm_family != "driving" else [4, 4, 4, 4, 8, 8]
            intro_intervals = [0, 2, 0, -2] if len(intro_rhythm) == 4 else [0, 2, 2, -2, 0]
            phrases_map["INTRO"] = MusicPhrase(id="INTRO", intervals=intro_intervals[:len(intro_rhythm)-1], rhythm=intro_rhythm)

        # Section OUTRO
        if "OUTRO" in unique_sections:
            outro_rhythm = [4, 4, 8, 16]  # Cadence leading to sustained tonic chord
            outro_intervals = [4, 3, -7]   # IV -> V -> I cadence
            phrases_map["OUTRO"] = MusicPhrase(id="OUTRO", intervals=outro_intervals, rhythm=outro_rhythm)

        # 5. SYMBOLIC PATTERN ASSEMBLY
        patterns: List[SymbolicPattern] = []
        pat_id_map: Dict[str, int] = {}

        for p_idx, s_label in enumerate(unique_sections):
            phrase = phrases_map.get(s_label, phrases_map["A"])
            pat = _build_profile_pattern(
                pat_id=p_idx,
                section_label=s_label,
                phrase=phrase,
                profile=prof,
                progression=progression,
                scale=scale,
                root_midi=root_midi,
                min_lead=min_lead,
                max_lead=max_lead,
                channels_count=channels_count,
                uses_16bit=uses_16bit,
                novelty=actual_novelty,
                rng=rng,
            )
            patterns.append(pat)
            pat_id_map[s_label] = p_idx

        # 6. SEQUENCE CONSTRUCTION
        # Architectural sequencing: INTRO -> Core Loop -> OUTRO
        target_dur = config.duration if config.duration is not None else prof.target_duration
        sequence = _construct_architectural_sequence(form_sections, pat_id_map, actual_tempo, target_dur)

        # 7. ASSEMBLE MUSIC IR
        music_song = MusicSong(
            title=f"ComposerV3 [{prof.name.upper()}] #{config.seed:03d} ({actual_key} {actual_mode})",
            tempo_bpm=actual_tempo,
            key=actual_key,
            mode=actual_mode,
            progression=progression,
            form=chosen_form,
            phrases=phrases_map,
            patterns=patterns,
            sequence=sequence,
            min_channels=min_ch,
            max_channels=max_ch,
            novelty=actual_novelty,
            style=prof.name,
        )

        # 8. COMPILE TO POKEY IR
        pokey_song = _compile_profile_to_pokey_ir(music_song, prof, uses_16bit, channels_count, rng)

        # 9. CONSTRAINT CHECK & MEMORY DEDUPLICATION (< 2048 B)
        from atari_music.composer_v2 import deduplicate_pokey_patterns
        pokey_song, _ = deduplicate_pokey_patterns(pokey_song)
        mem_size = calculate_ir_binary_size(pokey_song)

        if mem_size <= config.max_size and min_ch <= channels_count <= max_ch:
            # Build Quality Report
            quality = _calculate_v3_quality_report(
                music_song, pokey_song, mem_size, channels_count, prof, attempt, actual_novelty
            )
            return ComposerV3Result(
                music_ir=music_song,
                pokey_ir=pokey_song,
                profile_name=prof.name,
                quality_report=quality,
            )

        # Mutate seed for next attempt if budget exceeded
        rng.seed(config.seed + attempt * 23)

    raise RuntimeError(
        f"Generation failed after {config.max_attempts} attempts for profile '{prof.name}'. Constraints could not be satisfied."
    )


def _construct_architectural_sequence(
    form_sections: List[str],
    pat_id_map: Dict[str, int],
    tempo_bpm: int,
    target_duration_sec: int,
) -> List[int]:
    """Construct a full song sequence respecting Intro, Core Loop, and Outro."""
    has_intro = "INTRO" in form_sections
    has_outro = "OUTRO" in form_sections

    core_sections = [s for s in form_sections if s not in ("INTRO", "OUTRO")]
    if not core_sections:
        core_sections = form_sections

    # Calculate physical duration per pattern based on POKEY frames_per_tick
    if tempo_bpm <= 80:
        fpt = 6
    elif tempo_bpm <= 110:
        fpt = 5
    elif tempo_bpm <= 145:
        fpt = 4
    else:
        fpt = 3

    sec_per_pat = (32.0 * fpt) / 50.0
    target_patterns = max(6, int(round(target_duration_sec / sec_per_pat)))

    sequence: List[int] = []

    # 1. Add Intro if present
    if has_intro and "INTRO" in pat_id_map:
        sequence.append(pat_id_map["INTRO"])

    # 2. Add Core Loops
    reserved_for_outro = 1 if (has_outro and "OUTRO" in pat_id_map) else 0

    while (len(sequence) + len(core_sections)) <= (target_patterns - reserved_for_outro):
        for s in core_sections:
            sequence.append(pat_id_map[s])

    # Ensure at least one pass of core sections
    if not any(s in sequence for s in [pat_id_map[c] for c in core_sections]):
        for s in core_sections:
            sequence.append(pat_id_map[s])

    # 3. Add Outro if present
    if has_outro and "OUTRO" in pat_id_map:
        sequence.append(pat_id_map["OUTRO"])


    return sequence


def _build_profile_pattern(
    pat_id: int,
    section_label: str,
    phrase: MusicPhrase,
    profile: MusicProfile,
    progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    min_lead: int,
    max_lead: int,
    channels_count: int,
    uses_16bit: bool,
    novelty: float,
    rng: random.Random,
) -> SymbolicPattern:
    """Build multi-track pattern with section-specific roles and accompaniment."""
    tracks: Dict[int, SymbolicTrack] = {}

    chord_tones = get_chord_tones(progression[0] if progression else ChordStep(degree=0, name="i"), scale)
    melody_pitches = realize_pitches_from_intervals(
        root_midi=root_midi,
        intervals=phrase.intervals,
        scale=scale,
        chord_tones=chord_tones,
        min_midi=min_lead,
        max_midi=max_lead,
    )

    lead_ch = 2 if channels_count == 2 else 3
    lead_notes: List[SymbolicNote] = []

    # Section-specific lead volume / expression
    lead_vol = 12 if section_label == "INTRO" else (15 if section_label in ("C", "OUTRO") else 14)
    for dur, pitch in zip(phrase.rhythm, melody_pitches):
        lead_notes.append(
            SymbolicNote(
                pitch=pitch,
                pitch_name=midi_to_note_name(pitch),
                duration=dur,
                velocity=lead_vol,
                role=ChannelRole.MELODY,
            )
        )
    tracks[lead_ch] = SymbolicTrack(channel_idx=lead_ch, role=ChannelRole.MELODY, notes=lead_notes)

    # Bassline selection tuned to profile and section
    if section_label == "INTRO":
        bass_role = "pedal_drone" if profile.name == "dungeon" else "soft_pedal"
    elif section_label == "OUTRO":
        bass_role = "fanfare_bass" if profile.name == "ending" else "root_bass"
    else:
        bass_role = rng.choice(profile.bass_styles)

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

    # Channel 2: 16-bit slave, drone, or arpeggiated harmony
    if channels_count >= 3:
        if uses_16bit:
            tracks[2] = SymbolicTrack(
                channel_idx=2,
                role=ChannelRole.BASS,
                notes=[SymbolicNote(duration=32, is_rest=True, role=ChannelRole.BASS)],
            )
        else:
            if profile.name == "dungeon":
                # Static low drone on 5th
                drone_p = root_midi - 5
                tracks[2] = SymbolicTrack(
                    channel_idx=2,
                    role=ChannelRole.HARMONY,
                    notes=[SymbolicNote(pitch=drone_p, duration=32, velocity=6, role=ChannelRole.HARMONY)],
                )
            else:
                # Flowing modal harmony arpeggio
                harm_notes: List[SymbolicNote] = []
                step_dur = 4 if profile.rhythm_family == "sparse" else 2
                steps = 32 // step_dur
                for step in range(steps):
                    c_idx = (step * len(progression)) // steps
                    tones = get_chord_tones(progression[c_idx], scale)
                    p = (root_midi - 12) + tones[step % len(tones)]
                    harm_notes.append(SymbolicNote(pitch=p, duration=step_dur, velocity=7, role=ChannelRole.HARMONY))
                tracks[2] = SymbolicTrack(channel_idx=2, role=ChannelRole.HARMONY, notes=harm_notes)

    # Channel 4: Percussion tailored to profile intensity
    if channels_count >= 4:
        p_intensity = profile.percussion_intensity
        if section_label == "INTRO":
            p_intensity = "sparse" if p_intensity != "none" else "none"

        drum_notes: List[SymbolicNote] = []
        if p_intensity == "none":
            # No percussion; channel 4 used as secondary soft harmony
            sub_p = root_midi + 4
            drum_notes.append(SymbolicNote(pitch=sub_p, duration=32, velocity=4, role=ChannelRole.HARMONY))
            tracks[4] = SymbolicTrack(channel_idx=4, role=ChannelRole.HARMONY, notes=drum_notes)
        elif p_intensity == "sparse":
            for r in range(0, 32, 4):
                if r % 16 == 0:
                    drum_notes.append(SymbolicNote(duration=4, velocity=14, role=ChannelRole.PERCUSSION))
                else:
                    drum_notes.append(SymbolicNote(duration=4, is_rest=True, role=ChannelRole.PERCUSSION))
            tracks[4] = SymbolicTrack(channel_idx=4, role=ChannelRole.PERCUSSION, notes=drum_notes)
        elif p_intensity == "heavy":
            # Driving combat pulse (kick on 0, 8, 16, 24, snare on 4, 12, 20, 28, 16th hats)
            for r in range(0, 32, 2):
                if r % 8 == 0:
                    drum_notes.append(SymbolicNote(duration=2, velocity=15, role=ChannelRole.PERCUSSION))
                elif r % 8 == 4:
                    drum_notes.append(SymbolicNote(duration=2, velocity=15, role=ChannelRole.PERCUSSION))
                else:
                    drum_notes.append(SymbolicNote(duration=2, velocity=11, role=ChannelRole.PERCUSSION))
            tracks[4] = SymbolicTrack(channel_idx=4, role=ChannelRole.PERCUSSION, notes=drum_notes)
        else:  # medium
            for r in range(0, 32, 2):
                if r % 8 == 0:
                    drum_notes.append(SymbolicNote(duration=2, velocity=14, role=ChannelRole.PERCUSSION))
                elif r % 8 == 4:
                    drum_notes.append(SymbolicNote(duration=2, velocity=14, role=ChannelRole.PERCUSSION))
                else:
                    drum_notes.append(SymbolicNote(duration=2, velocity=8, role=ChannelRole.PERCUSSION))
            tracks[4] = SymbolicTrack(channel_idx=4, role=ChannelRole.PERCUSSION, notes=drum_notes)

    return SymbolicPattern(id=pat_id, name=f"Pat {section_label}", rows=32, tracks=tracks)


def _compile_profile_to_pokey_ir(
    music_song: MusicSong,
    profile: MusicProfile,
    uses_16bit: bool,
    channels_count: int,
    rng: random.Random,
) -> IRSong:
    """Compile MusicSong into hardware-accurate IRSong with profile timbres."""
    # Instruments tuned to profile
    if profile.name == "dungeon":
        lead_dist = DISTORTION_PURE_TONE
        lead_env = IREnvelope(attack_frames=2, decay_frames=6, sustain_vol=10, release_frames=4)
        vibrato_d, vibrato_s = 1, 1
    elif profile.name == "action":
        lead_dist = DISTORTION_PURE_TONE
        lead_env = IREnvelope(attack_frames=1, decay_frames=2, sustain_vol=13, release_frames=1)
        vibrato_d, vibrato_s = 1, 3
    elif profile.name == "funny":
        lead_dist = DISTORTION_PURE_TONE
        lead_env = IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=14, release_frames=1)
        vibrato_d, vibrato_s = 2, 4
    else:  # title, ending, exploration
        lead_dist = DISTORTION_PURE_TONE
        lead_env = IREnvelope(attack_frames=1, decay_frames=4, sustain_vol=12, release_frames=3)
        vibrato_d, vibrato_s = 1, 2

    instruments = [
        IRInstrument(
            id=0,
            name=f"{profile.name.capitalize()} Lead",
            distortion=lead_dist,
            role="melody",
            envelope=lead_env,
            vibrato_depth=vibrato_d,
            vibrato_speed=vibrato_s,
            is_16bit=False,
        ),
        IRInstrument(
            id=1,
            name="Bass Voice",
            distortion=DISTORTION_PURE_TONE if uses_16bit else DISTORTION_4BIT_POLY,
            role="bass",
            envelope=IREnvelope(attack_frames=0, decay_frames=4, sustain_vol=10, release_frames=2),
            is_16bit=uses_16bit,
        ),
        IRInstrument(
            id=2,
            name="Harmony Accompaniment",
            distortion=DISTORTION_PURE_TONE,
            role="harmony",
            envelope=IREnvelope(attack_frames=1, decay_frames=2, sustain_vol=7, release_frames=1),
            is_16bit=False,
        ),
        IRInstrument(
            id=3,
            name="Percussion Voice",
            distortion=DISTORTION_WHITE_NOISE,
            role="percussion",
            envelope=IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=8, release_frames=2),
            is_16bit=False,
        ),
    ]

    pokey_patterns: List[IRPattern] = []
    for sp in music_song.patterns:
        ir_tracks: Dict[int, List[IRNote]] = {}
        for ch, track in sp.tracks.items():
            ir_notes: List[IRNote] = []
            for n in track.notes:
                inst_id = 0 if track.role == ChannelRole.MELODY else (
                    1 if track.role == ChannelRole.BASS else (
                        2 if track.role == ChannelRole.HARMONY else 3
                    )
                )
                ir_notes.append(
                    IRNote(
                        pitch=midi_to_note_name(n.pitch) if n.pitch else None,
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

    # Accurate POKEY frames per tick based on BPM
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
        author="Composer v3 Engine",
        tempo_bpm=music_song.tempo_bpm,
        frames_per_tick=frames_per_tick,
        key=music_song.key,
        mode=music_song.mode,
        instruments=instruments,
        patterns=pokey_patterns,
        sequence=music_song.sequence,
        uses_16bit_bass=uses_16bit,
    )


def _calculate_v3_quality_report(
    music_song: MusicSong,
    pokey_song: IRSong,
    mem_size: int,
    channels_count: int,
    profile: MusicProfile,
    attempt: int,
    novelty: float,
) -> ComposerV3QualityReport:
    """Calculate transparent structural and musical metrics for Composer v3."""
    frames = compile_ir_to_pokey_frames(pokey_song)
    duration_sec = round(frames.shape[0] / 50.0, 2)

    all_midi: List[int] = []
    for pat in pokey_song.patterns:
        for ch, notes in pat.tracks.items():
            for n in notes:
                if not n.is_rest and n.midi_pitch is not None:
                    all_midi.append(n.midi_pitch)

    pitch_range = (max(all_midi) - min(all_midi)) if all_midi else 0
    seq = pokey_song.sequence
    repetition = round(1.0 - (len(set(seq)) / max(1, len(seq))), 3)

    melodic_density = round(len(all_midi) / max(1.0, duration_sec), 2)
    rhythmic_density = round(len(seq) * 32 / max(1.0, duration_sec), 2)
    harmonic_complexity = round(len(music_song.progression) / 4.0, 2)

    return ComposerV3QualityReport(
        profile_name=profile.name,
        memory_size=mem_size,
        under_budget=mem_size <= 2048,
        channels_used=channels_count,
        duration=duration_sec,
        tempo=pokey_song.tempo_bpm,
        form=music_song.form,
        pitch_range=pitch_range,
        repetition=max(0.0, repetition),
        novelty=novelty,
        melodic_density=melodic_density,
        rhythmic_density=rhythmic_density,
        harmonic_complexity=harmonic_complexity,
        pattern_count=len(pokey_song.patterns),
        attempts_needed=attempt,
    )

"""Composer v4: Full 4-Channel POKEY Arrangement Engine.

Implements the multi-layer architectural pipeline:
COMPOSITION
    ↓
MELODIC / RHYTHMIC MATERIAL
    ↓
ARRANGEMENT (Voice roles, dynamic orchestration, section densities)
    ↓
POKEY CHANNEL ASSIGNMENT (Logical voices -> Physical POKEY channels 1..4)
    ↓
POKEY IR (Active memory optimization <= 2048 B)
    ↓
POKEY COMPILER / SYNTH (Deterministic rendering)

Key Innovations over v3:
1. True 4-channel polyphonic arrangements without artificial padding.
2. Musically dependent COUNTER/HARMONY second voice (Call & Response, Harmonic Support,
   Parallel Motion, Rhythmic Counterpoint, Motif Echo).
3. Dynamic multi-style BASS with rhythmic diversity (Fifths, Walking, Ostinato, Pulse, Staccato).
4. Profile-tailored 4th voice: Percussion grooves (Action/Ending), Dark Ostinato (Dungeon),
   High Ornaments (Exploration/Title), Comic Accents (Funny).
5. Dynamic section orchestration: breathing density (intro/outro vs culmination).
6. 100% deterministic seed control and strict <= 2048 B memory guarantee.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


import numpy as np
from pydantic import BaseModel, Field

from atari_music.arrangement import (
    SongArrangement,
    VoiceRole,
    plan_song_arrangement,
    realize_arranged_pattern,
)
from atari_music.constants import (
    DISTORTION_4BIT_POLY,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    KEY_BASE_MIDI,
    SCALES,
)
from atari_music.contour_engine import (
    generate_archetype_intervals,
    realize_pitches_from_intervals,
)
from atari_music.harmony_engine import (
    ChordStep,
    get_chord_tones,
    select_profile_progression,
)
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    calculate_ir_binary_size,
    compile_ir_to_pokey_frames,
    midi_to_note_name,
)
from atari_music.music_ir import (
    ChannelRole,
    MusicPhrase,
    MusicSong,
    SymbolicNote,
    SymbolicPattern,
)
from atari_music.mutations import generate_phrase_variation
from atari_music.profiles import MusicProfile, get_profile
from atari_music.rhythm_engine import generate_profile_rhythm


@dataclass
class ComposerV4Config:
    """Configuration bundle for Composer v4."""
    profile: str | MusicProfile = "title"
    seed: int = 42
    tempo: Optional[int] = None
    key: Optional[str] = None
    mode: Optional[str] = None
    novelty: Optional[float] = None
    duration: Optional[int] = None
    max_size: int = 2048
    max_attempts: int = 100
    uses_16bit_bass: bool = False
    channel_instruments: Optional[Mapping[int | str, str]] = None
    program_changes: Optional[Sequence[Mapping[str, Any] | Any]] = None
    instrument_catalog_path: Optional[Path] = None
    player_version: str = "auto"


class ComposerV4QualityReport(BaseModel):
    """Detailed structural and musical quality metrics for Composer v4."""
    profile_name: str
    memory_size: int
    under_budget: bool
    channels_used: int
    active_channels_audio: int
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
    format_version: int = 1
    section_channel_counts: Dict[str, int] = Field(default_factory=dict)
    active_frame_pct: Dict[int, float] = Field(default_factory=dict)


class ComposerV4Result(BaseModel):
    """Result artifact of Composer v4 generation."""
    music_ir: MusicSong
    pokey_ir: IRSong
    profile_name: str
    arrangement: SongArrangement
    quality_report: ComposerV4QualityReport
    wav_path: Optional[str] = None
    sound_profiles: List[Dict[str, Any]] = Field(default_factory=list)


def compose_song_v4(
    profile: str | MusicProfile = "title",
    seed: int = 42,
    tempo: Optional[int] = None,
    key: Optional[str] = None,
    mode: Optional[str] = None,
    novelty: Optional[float] = None,
    duration: Optional[int] = None,
    max_size: int = 2048,
    max_attempts: int = 100,
    uses_16bit_bass: bool = False,
    channel_instruments: Optional[Mapping[int | str, str]] = None,
    program_changes: Optional[Sequence[Mapping[str, Any] | Any]] = None,
    instrument_catalog_path: Optional[Path] = None,
    player_version: str = "auto",
) -> ComposerV4Result:
    """Master entry point for Composer v4: Full 4-Channel Arrangement Engine."""
    cfg = ComposerV4Config(
        profile=profile,
        seed=seed,
        tempo=tempo,
        key=key,
        mode=mode,
        novelty=novelty,
        duration=duration,
        max_size=max_size,
        max_attempts=max_attempts,
        uses_16bit_bass=uses_16bit_bass,
        channel_instruments=channel_instruments,
        program_changes=program_changes,
        instrument_catalog_path=instrument_catalog_path,
        player_version=player_version,
    )
    return _execute_composer_v4(cfg)


def _execute_composer_v4(config: ComposerV4Config) -> ComposerV4Result:
    """Generate-and-Test loop for Composer v4."""
    from atari_music.instruments.planner import (
        InstrumentPlanError,
        normalize_player_version,
        resolve_channel_instrument_plan,
        resolve_export_format_version,
    )
    from atari_music.ir import song_requires_v2

    ver_choice = normalize_player_version(config.player_version)
    instrument_plan = None
    if config.channel_instruments is not None or config.program_changes:
        instrument_plan = resolve_channel_instrument_plan(
            config.channel_instruments,
            program_changes=config.program_changes,
            catalog_path=config.instrument_catalog_path,
            uses_16bit_bass=config.uses_16bit_bass,
            player_version=ver_choice,
        )
    effective_16bit = bool(
        config.uses_16bit_bass or (instrument_plan is not None and instrument_plan.uses_16bit_ch12)
    )

    prof = get_profile(config.profile)
    rng = random.Random(config.seed)

    for attempt in range(1, config.max_attempts + 1):
        # 1. PARAMETER RESOLUTION FROM PROFILE
        if config.tempo is not None:
            actual_tempo = config.tempo
        else:
            t_min, t_max = prof.tempo_range
            actual_tempo = rng.randint(t_min, t_max)

        actual_mode = config.mode if config.mode else rng.choice(prof.allowed_modes)
        all_keys = ["C", "D", "E", "F", "G", "A", "B"]
        actual_key = config.key if config.key else rng.choice(all_keys)

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

        # 2. HARMONY SELECTION
        progression = select_profile_progression(actual_mode, prof.name, rng)

        # 3. FORM SELECTION & MULTI-SECTION PLANNING
        chosen_form = rng.choice(prof.form_choices)
        form_sections = chosen_form.split()
        unique_sections = list(dict.fromkeys(form_sections))

        # 4. ARRANGEMENT LAYER PLANNING
        arrangement = plan_song_arrangement(
            profile=prof,
            unique_sections=unique_sections,
            uses_16bit_bass=effective_16bit,
            rng=rng,
        )

        # 5. MELODIC MATERIAL GENERATION (INTRO, A, B, A', C, OUTRO)
        phrases_map: Dict[str, MusicPhrase] = {}

        # Base phrase A
        arch_a = rng.choice(prof.melodic_archetypes)
        rhythm_a = generate_profile_rhythm(prof.rhythm_family, 32, syncopation=0.2 + 0.3 * actual_novelty, rng=rng)
        intervals_a = generate_archetype_intervals(arch_a, len(rhythm_a), rng)
        phrases_map["A"] = MusicPhrase(id="A", intervals=intervals_a, rhythm=rhythm_a)

        # Variation A'
        if "A'" in unique_sections or "A" in unique_sections:
            phrases_map["A'"] = generate_phrase_variation(
                base_phrase=phrases_map["A"],
                variation_id="A'",
                novelty=actual_novelty,
                scale=scale,
                rng=rng,
            )

        # Contrasting theme B
        if "B" in unique_sections:
            arch_b = rng.choice(prof.melodic_archetypes)
            rhythm_b = generate_profile_rhythm(prof.rhythm_family, 32, syncopation=0.3 + 0.2 * actual_novelty, rng=rng)
            intervals_b = generate_archetype_intervals(arch_b, len(rhythm_b), rng)
            phrases_map["B"] = MusicPhrase(id="B", intervals=intervals_b, rhythm=rhythm_b)

        # Climax theme C
        if "C" in unique_sections:
            arch_c = "fanfare" if prof.name == "ending" else "ascending"
            rhythm_c = generate_profile_rhythm(prof.rhythm_family, 32, syncopation=0.35, rng=rng)
            intervals_c = generate_archetype_intervals(arch_c, len(rhythm_c), rng)
            phrases_map["C"] = MusicPhrase(id="C", intervals=intervals_c, rhythm=rhythm_c)

        # Section INTRO
        if "INTRO" in unique_sections:
            intro_rhythm = [8, 8, 8, 8] if prof.rhythm_family != "driving" else [4, 4, 4, 4, 8, 8]
            intro_intervals = [0, 2, 0, -2] if len(intro_rhythm) == 4 else [0, 2, 2, -2, 0]
            phrases_map["INTRO"] = MusicPhrase(
                id="INTRO",
                intervals=intro_intervals[:len(intro_rhythm)-1],
                rhythm=intro_rhythm,
            )

        # Section OUTRO
        if "OUTRO" in unique_sections:
            outro_rhythm = [4, 4, 8, 16]
            outro_intervals = [4, 3, -7]  # IV -> V -> I resolution
            phrases_map["OUTRO"] = MusicPhrase(id="OUTRO", intervals=outro_intervals, rhythm=outro_rhythm)

        # 6. ASSEMBLE PATTERNS THROUGH ARRANGEMENT LAYER
        patterns: List[SymbolicPattern] = []
        pat_id_map: Dict[str, int] = {}

        for p_idx, s_label in enumerate(unique_sections):
            phrase = phrases_map.get(s_label, phrases_map["A"])
            chord_tones = get_chord_tones(progression[0] if progression else ChordStep(degree=0, name="i"), scale)
            lead_pitches = realize_pitches_from_intervals(
                root_midi=root_midi,
                intervals=phrase.intervals,
                scale=scale,
                chord_tones=chord_tones,
                min_midi=min_lead,
                max_midi=max_lead,
            )

            # Build lead notes
            lead_vol = 12 if s_label == "INTRO" else (15 if s_label in ("C", "OUTRO") else 14)
            lead_notes: List[SymbolicNote] = []
            for dur, pitch in zip(phrase.rhythm, lead_pitches):
                lead_notes.append(
                    SymbolicNote(
                        pitch=pitch,
                        pitch_name=midi_to_note_name(pitch),
                        duration=dur,
                        velocity=lead_vol,
                        role=ChannelRole.MELODY,
                    )
                )

            sec_arr = arrangement.sections[s_label]
            pat = realize_arranged_pattern(
                pat_id=p_idx,
                section_label=s_label,
                arrangement=sec_arr,
                lead_notes=lead_notes,
                progression=progression,
                scale=scale,
                root_midi=root_midi,
                profile=prof,
                uses_16bit_bass=effective_16bit,
                rng=rng,
            )
            patterns.append(pat)
            pat_id_map[s_label] = p_idx

        # 7. CONSTRUCT SONG SEQUENCE
        target_dur = config.duration if config.duration is not None else prof.target_duration
        sequence = _construct_v4_sequence(form_sections, pat_id_map, actual_tempo, target_dur)

        # 8. ASSEMBLE MUSIC IR
        music_song = MusicSong(
            title=f"ComposerV4 [{prof.name.upper()}] #{config.seed:03d} ({actual_key} {actual_mode})",
            tempo_bpm=actual_tempo,
            key=actual_key,
            mode=actual_mode,
            progression=progression,
            form=chosen_form,
            phrases=phrases_map,
            patterns=patterns,
            sequence=sequence,
            min_channels=3,
            max_channels=4,
            novelty=actual_novelty,
            style=prof.name,
        )

        # 9. COMPILE TO POKEY IR
        extra_profiles: List[Dict[str, Any]] = []
        pokey_song = _compile_v4_to_pokey_ir(
            music_song=music_song,
            profile=prof,
            uses_16bit=effective_16bit,
            rng=rng,
            instrument_plan=instrument_plan,
            player_version=ver_choice,
            catalog_path=config.instrument_catalog_path,
            extra_sound_profiles=extra_profiles,
        )

        # 10. CONSTRAINT CHECK & MEMORY DEDUPLICATION (< 2048 B)
        from atari_music.ir_optimizer import deduplicate_pokey_patterns
        pokey_song, _ = deduplicate_pokey_patterns(pokey_song)
        v2_reasons = song_requires_v2(pokey_song)
        if ver_choice == "v1" and v2_reasons:
            raise InstrumentPlanError(
                "selected song/instruments require format v2 (" + "; ".join(v2_reasons) + ")",
                code="FORMAT_VERSION_CONFLICT",
            )
        export_ver = resolve_export_format_version(pokey_song, ver_choice)
        mem_size = calculate_ir_binary_size(pokey_song, format_version=export_ver)

        if mem_size <= config.max_size:
            quality = _calculate_v4_quality_report(
                music_song=music_song,
                pokey_song=pokey_song,
                arrangement=arrangement,
                mem_size=mem_size,
                profile=prof,
                attempt=attempt,
                novelty=actual_novelty,
                format_version=export_ver,
            )
            combined_profiles = list(instrument_plan.sound_profiles_metadata) if instrument_plan else []
            combined_profiles.extend(extra_profiles)
            return ComposerV4Result(
                music_ir=music_song,
                pokey_ir=pokey_song,
                profile_name=prof.name,
                arrangement=arrangement,
                quality_report=quality,
                sound_profiles=combined_profiles,
            )

        rng.seed(config.seed + attempt * 31)

    raise RuntimeError(
        f"Composer v4 generation failed after {config.max_attempts} attempts for profile '{prof.name}'."
    )


def _construct_v4_sequence(
    form_sections: List[str],
    pat_id_map: Dict[str, int],
    tempo_bpm: int,
    target_duration_sec: int,
) -> List[int]:
    """Construct sequence maintaining Intro -> Core Loops -> Outro."""
    has_intro = "INTRO" in form_sections
    has_outro = "OUTRO" in form_sections
    core_sections = [s for s in form_sections if s not in ("INTRO", "OUTRO")]
    if not core_sections:
        core_sections = form_sections

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

    if has_intro and "INTRO" in pat_id_map:
        sequence.append(pat_id_map["INTRO"])

    reserved_for_outro = 1 if (has_outro and "OUTRO" in pat_id_map) else 0

    while (len(sequence) + len(core_sections)) <= (target_patterns - reserved_for_outro):
        for s in core_sections:
            sequence.append(pat_id_map[s])

    if not any(s in sequence for s in [pat_id_map[c] for c in core_sections]):
        for s in core_sections:
            sequence.append(pat_id_map[s])

    if has_outro and "OUTRO" in pat_id_map:
        sequence.append(pat_id_map["OUTRO"])

    return sequence


def _build_profile_meta(ir_id: int, prof: Any, beh: Any) -> Dict[str, Any]:
    return {
        "ir_instrument_id": ir_id,
        "instrument_id": prof.instrument_id,
        "display_name": prof.display_name,
        "family": prof.family,
        "behavior_id": prof.behavior_id,
        "required_runtime_tier": beh.required_runtime_tier if beh else "core_v1",
        "profile_fingerprint": prof.provenance.profile_fingerprint,
    }


def _compile_v4_to_pokey_ir(
    music_song: MusicSong,
    profile: MusicProfile,
    uses_16bit: bool,
    rng: random.Random,
    instrument_plan: Optional[Any] = None,
    *,
    player_version: str = "auto",
    catalog_path: Optional[Path] = None,
    extra_sound_profiles: Optional[List[Dict[str, Any]]] = None,
) -> IRSong:
    """Compile MusicSong into IRSong with authentic POKEY timbres (legacy or v2 catalog)."""
    # Profile-tuned lead timbre
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
    else:
        lead_dist = DISTORTION_PURE_TONE
        lead_env = IREnvelope(attack_frames=1, decay_frames=4, sustain_vol=12, release_frames=3)
        vibrato_d, vibrato_s = 1, 2

    # Bass timbre: 16-bit pure tone or 8-bit poly
    bass_dist = DISTORTION_PURE_TONE if uses_16bit else DISTORTION_4BIT_POLY

    if instrument_plan is None:
        default_perc_inst: Optional[IRInstrument] = None
        has_perc_notes = any(
            tr.role == ChannelRole.PERCUSSION
            for sp in music_song.patterns
            for tr in sp.tracks.values()
        )
        if player_version == "v2" and has_perc_notes:
            from atari_music.instruments.catalog import load_instrument_catalog
            from atari_music.instruments.planner import default_percussion_instrument_id

            cat = load_instrument_catalog(catalog_path)
            perc_cid = default_percussion_instrument_id(cat, player_version="v2", channel=4)
            if perc_cid is not None:
                p_prof, p_beh = cat.resolve_profile_behavior(perc_cid)
                default_perc_inst = IRInstrument.from_catalog_profile(3, p_prof, p_beh)
                if extra_sound_profiles is not None:
                    extra_sound_profiles.append(_build_profile_meta(3, p_prof, p_beh))

        use_v2_default_perc = default_perc_inst is not None
        instruments = [
            # Inst 0: Lead
            IRInstrument(
                id=0,
                name=f"{profile.name.capitalize()} Lead",
                distortion=lead_dist,
                role="melody",
                envelope=lead_env,
                vibrato_depth=0 if use_v2_default_perc else vibrato_d,
                vibrato_speed=0 if use_v2_default_perc else vibrato_s,
                is_16bit=False,
            ),
            # Inst 1: Bass
            IRInstrument(
                id=1,
                name="Bass Voice",
                distortion=bass_dist,
                role="bass",
                envelope=IREnvelope(attack_frames=0, decay_frames=4, sustain_vol=11, release_frames=2),
                is_16bit=uses_16bit,
            ),
            # Inst 2: Counter / Harmony Voice
            IRInstrument(
                id=2,
                name="Counter Harmony",
                distortion=DISTORTION_PURE_TONE,
                role="harmony",
                envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=9, release_frames=2),
                is_16bit=False,
            ),
            # Inst 3: Percussion Voice (rhytmizer_closed_hihat in v2 mode, static ADSR in v1)
            default_perc_inst
            if default_perc_inst is not None
            else IRInstrument(
                id=3,
                name="Percussion Voice",
                distortion=DISTORTION_WHITE_NOISE,
                role="percussion",
                envelope=IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=8, release_frames=2),
                is_16bit=False,
            ),
            # Inst 4: Melodic Ornament Voice (pure tone)
            IRInstrument(
                id=4,
                name="Ornament Voice",
                distortion=DISTORTION_PURE_TONE,
                role="harmony",
                envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=8, release_frames=2),
                is_16bit=False,
            ),
        ]

        pokey_patterns: List[IRPattern] = []
        for sp in music_song.patterns:
            ir_tracks: Dict[int, List[IRNote]] = {}
            for ch, track in sp.tracks.items():
                ir_notes: List[IRNote] = []
                for n in track.notes:
                    # Assign instrument based on channel role & characteristics
                    if track.role == ChannelRole.MELODY:
                        inst_id = 0
                    elif track.role == ChannelRole.BASS:
                        inst_id = 1
                    elif track.role == ChannelRole.PERCUSSION:
                        inst_id = 3
                    else:  # HARMONY / COUNTER / ORNAMENT
                        if ch == 4 and n.pitch is not None and n.pitch >= 70:
                            inst_id = 4  # High ornament
                        elif ch == 4 and n.pitch is not None and n.pitch < 65:
                            inst_id = 4  # Dark ostinato
                        else:
                            inst_id = 2  # Counterpoint harmony

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
        initial_ch_map: Optional[Dict[int, int]] = (
            {1: 1, 2: 2, 3: 0, 4: 3} if use_v2_default_perc else None
        )
    else:
        from atari_music.instruments.planner import InstrumentPlanError, default_percussion_instrument_id

        instruments = list(instrument_plan.ir_instruments)
        ch4_has_perc = any(
            tr.role == ChannelRole.PERCUSSION
            for sp in music_song.patterns
            for c, tr in sp.tracks.items()
            if c == 4
        )
        default_ch4_cid: Optional[str] = None
        if (
            4 not in instrument_plan.initial_channel_profiles
            and ch4_has_perc
            and (player_version == "v2" or instrument_plan.requires_v2)
        ):
            default_ch4_cid = default_percussion_instrument_id(
                instrument_plan.catalog,
                player_version="v2",
                channel=4,
                required_audctl_bits=instrument_plan.effective_audctl,
            )

        needs_v2_bank = bool(instrument_plan.requires_v2) or (default_ch4_cid is not None)

        def _ensure_fallback(role_name: str, name: str, dist: int, env: IREnvelope, is16: bool = False) -> int:
            for existing in instruments:
                if existing.role == role_name and existing.profile_id is None and existing.is_16bit == is16:
                    return existing.id
            new_id = len(instruments)
            instruments.append(
                IRInstrument(
                    id=new_id,
                    name=name,
                    distortion=dist,
                    role=role_name,
                    envelope=env,
                    vibrato_depth=0 if needs_v2_bank else (vibrato_d if role_name == "melody" else 0),
                    vibrato_speed=0 if needs_v2_bank else (vibrato_s if role_name == "melody" else 0),
                    is_16bit=is16,
                )
            )
            return new_id

        fallback_ids: Dict[int, int] = {}
        init_ch_resolved: Dict[int, int] = {}
        for ch in range(1, 5):
            prof_id = instrument_plan.initial_channel_profiles.get(ch)
            if prof_id is not None:
                init_ch_resolved[ch] = instrument_plan.profile_to_ir_index[prof_id]
            elif ch == 1:
                init_ch_resolved[ch] = _ensure_fallback(
                    "bass", "Bass Voice", bass_dist,
                    IREnvelope(attack_frames=0, decay_frames=4, sustain_vol=11, release_frames=2), uses_16bit
                )
            elif ch == 2:
                init_ch_resolved[ch] = init_ch_resolved[1] if uses_16bit else _ensure_fallback(
                    "harmony", "Counter Harmony", DISTORTION_PURE_TONE,
                    IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=9, release_frames=2),
                )
            elif ch == 3:
                init_ch_resolved[ch] = _ensure_fallback(
                    "melody", f"{profile.name.capitalize()} Lead", lead_dist, lead_env,
                )
            elif default_ch4_cid is not None:
                p4_prof, p4_beh = instrument_plan.catalog.resolve_profile_behavior(default_ch4_cid)
                new_id = len(instruments)
                instruments.append(IRInstrument.from_catalog_profile(new_id, p4_prof, p4_beh))
                init_ch_resolved[ch] = new_id
                if extra_sound_profiles is not None:
                    extra_sound_profiles.append(_build_profile_meta(new_id, p4_prof, p4_beh))
            else:
                init_ch_resolved[ch] = _ensure_fallback(
                    "percussion", "Percussion Voice", DISTORTION_WHITE_NOISE,
                    IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=8, release_frames=2),
                )
            fallback_ids[ch] = init_ch_resolved[ch]

        # Build lookup for ProgramChangeSpec -> (pat_idx, ch) -> {note_idx: ir_inst_id}
        pc_map: Dict[Tuple[int, int], Dict[int, int]] = {}
        available_sections = [sp.name[4:] if sp.name.startswith("Pat ") else sp.name for sp in music_song.patterns]
        for pc in instrument_plan.program_changes:
            target_ir_id = instrument_plan.profile_to_ir_index[pc.instrument_id]
            matched_indices: List[int] = []
            if pc.pattern_index is not None:
                if pc.pattern_index >= len(music_song.patterns):
                    raise InstrumentPlanError(
                        f"program_change pattern_index={pc.pattern_index} out of range 0..{len(music_song.patterns) - 1}",
                        code="INVALID_PROGRAM_CHANGE_TARGET",
                    )
                matched_indices.append(pc.pattern_index)
            elif pc.section is not None:
                sec_norm = pc.section.strip().upper()
                if sec_norm.startswith("PAT "):
                    sec_norm = sec_norm[4:].strip()
                for p_idx, sp in enumerate(music_song.patterns):
                    sp_norm = sp.name.upper()
                    if sp_norm.startswith("PAT "):
                        sp_norm = sp_norm[4:].strip()
                    if sp_norm == sec_norm:
                        matched_indices.append(p_idx)
                if not matched_indices:
                    raise InstrumentPlanError(
                        f"program_change section {pc.section!r} does not exist in generated form "
                        f"(available sections: {available_sections})",
                        code="INVALID_PROGRAM_CHANGE_SECTION",
                    )
            for p_idx in matched_indices:
                pc_map.setdefault((p_idx, pc.channel), {})[pc.note_index] = target_ir_id

        pokey_patterns = []
        for p_idx, sp in enumerate(music_song.patterns):
            ir_tracks = {}
            for ch, track in sp.tracks.items():
                base_ch_inst = init_ch_resolved.get(ch, fallback_ids.get(ch, 0))
                pat_changes = pc_map.get((p_idx, ch), {})
                active_inst = base_ch_inst
                notes_list = track.notes
                if pat_changes and notes_list:
                    max_req = max(pat_changes.keys())
                    if max_req >= len(notes_list):
                        raise InstrumentPlanError(
                            f"program_change note_index={max_req} exceeds channel {ch} note count ({len(notes_list)}) in {sp.name!r}",
                            code="INVALID_PROGRAM_CHANGE_TARGET",
                        )
                ir_notes = []
                target_inst_obj = instruments[base_ch_inst]
                for n_idx, n in enumerate(notes_list):
                    pending_pc: Tuple[int, ...] = ()
                    if n_idx in pat_changes:
                        active_inst = pat_changes[n_idx]
                        pending_pc = (active_inst,)
                        target_inst_obj = instruments[active_inst]
                    is_perc = (
                        target_inst_obj.role == "percussion"
                        or track.role == ChannelRole.PERCUSSION
                    )
                    ir_notes.append(
                        IRNote(
                            pitch=midi_to_note_name(n.pitch) if n.pitch else None,
                            midi_pitch=n.pitch,
                            duration=n.duration,
                            volume=n.velocity,
                            instrument_id=active_inst,
                            channel_role=("percussion" if (is_perc and n.pitch is None) else track.role.value),
                            is_rest=n.is_rest or (n.pitch is None and track.role != ChannelRole.PERCUSSION),
                            pending_program_changes=pending_pc,
                        )
                    )
                ir_tracks[ch] = ir_notes
            pokey_patterns.append(IRPattern(id=sp.id, name=sp.name, rows=sp.rows, tracks=ir_tracks))

        initial_ch_map = dict(init_ch_resolved) if needs_v2_bank else None

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
        author="Composer v4 Engine",
        tempo_bpm=music_song.tempo_bpm,
        frames_per_tick=frames_per_tick,
        key=music_song.key,
        mode=music_song.mode,
        instruments=instruments,
        patterns=pokey_patterns,
        sequence=music_song.sequence,
        uses_16bit_bass=uses_16bit,
        initial_channel_instruments=initial_ch_map,
    )


def _calculate_v4_quality_report(
    music_song: MusicSong,
    pokey_song: IRSong,
    arrangement: SongArrangement,
    mem_size: int,
    profile: MusicProfile,
    attempt: int,
    novelty: float,
    format_version: int = 1,
) -> ComposerV4QualityReport:
    """Calculate thorough structural and audio quality metrics."""
    if format_version == 2:
        from atari_music.frame_simulator import simulate_ir_song_frames
        frames = simulate_ir_song_frames(pokey_song, format_version=2)
    else:
        frames = compile_ir_to_pokey_frames(pokey_song)
    duration_sec = round(frames.shape[0] / 50.0, 2)
    total_frames = frames.shape[0]

    all_midi: List[int] = []
    pattern_map = {p.id: p for p in pokey_song.patterns}
    ch_active_notes = {1: 0, 2: 0, 3: 0, 4: 0}

    for pat_id in pokey_song.sequence:
        pat = pattern_map.get(pat_id)
        if not pat:
            continue
        for ch in range(1, 5):
            notes = pat.tracks.get(ch, [])
            for n in notes:
                if not n.is_rest and (n.midi_pitch is not None or n.channel_role == "percussion"):
                    ch_active_notes[ch] += 1
                if not n.is_rest and n.midi_pitch is not None:
                    all_midi.append(n.midi_pitch)

    ir_channels_used = sum(1 for ch in range(1, 5) if ch_active_notes[ch] > 0)

    # Audio active frame percentage
    active_frame_pct = {}
    audio_ch_count = 0
    for ch in range(1, 5):
        audc_col = (ch - 1) * 2 + 1
        active_f = np.count_nonzero(frames[:, audc_col] & 0x0F > 0)
        pct = round((active_f / total_frames) * 100.0, 1) if total_frames > 0 else 0.0
        active_frame_pct[ch] = pct
        if pct > 0:
            audio_ch_count += 1

    pitch_range = (max(all_midi) - min(all_midi)) if all_midi else 0
    seq = pokey_song.sequence
    repetition = round(1.0 - (len(set(seq)) / max(1, len(seq))), 3)

    melodic_density = round(len(all_midi) / max(1.0, duration_sec), 2)
    rhythmic_density = round(len(seq) * 32 / max(1.0, duration_sec), 2)
    harmonic_complexity = round(len(music_song.progression) / 4.0, 2)

    sec_ch_counts = {
        sec_name: sec_arr.active_channel_count
        for sec_name, sec_arr in arrangement.sections.items()
    }

    return ComposerV4QualityReport(
        profile_name=profile.name,
        memory_size=mem_size,
        under_budget=mem_size <= 2048,
        channels_used=ir_channels_used,
        active_channels_audio=audio_ch_count,
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
        format_version=format_version,
        section_channel_counts=sec_ch_counts,
        active_frame_pct=active_frame_pct,
    )

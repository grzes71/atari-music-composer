"""Arrangement Layer for Composer v4: Atari POKEY Music Engine.

Explicitly decouples Composition from Hardware Channel Assignment:
COMPOSITION
    ↓
MELODIC / RHYTHMIC MATERIAL
    ↓
ARRANGEMENT (Voice roles, dynamic orchestration, section densities)
    ↓
POKEY CHANNEL ASSIGNMENT (Logical voices -> Physical POKEY channels 1..4)
    ↓
POKEY IR
    ↓
POKEY COMPILER / SYNTH
"""

from __future__ import annotations

from enum import Enum
import random
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from atari_music.counterpoint import generate_counterpoint
from atari_music.bass_engine import generate_bassline
from atari_music.rhythm_ornament import generate_rhythm_or_ornament
from atari_music.harmony_engine import ChordStep
from atari_music.music_ir import ChannelRole, SymbolicNote, SymbolicPattern, SymbolicTrack
from atari_music.profiles import MusicProfile


class VoiceRole(str, Enum):
    LEAD = "lead"
    COUNTER = "counter"
    BASS = "bass"
    RHYTHM_ORNAMENT = "rhythm_ornament"


class SectionVoiceConfig(BaseModel):
    """Configuration of a single voice within a section."""
    active: bool
    role: VoiceRole
    style_or_strategy: str  # e.g. "call_response", "walking", "percussion", etc.
    target_channel: int     # Physical POKEY channel (1..4)
    octave_offset: int = 0


class SectionArrangement(BaseModel):
    """Orchestration and voice assignment for a specific musical section."""
    section_label: str
    active_channel_count: int
    voices: Dict[VoiceRole, SectionVoiceConfig]


class SongArrangement(BaseModel):
    """Full architectural arrangement of the song across all sections."""
    profile_name: str
    sections: Dict[str, SectionArrangement]


def plan_song_arrangement(
    profile: MusicProfile,
    unique_sections: List[str],
    uses_16bit_bass: bool,
    rng: random.Random,
) -> SongArrangement:
    """Plan section-by-section dynamic voice orchestration tailored to profile."""
    p_name = profile.name.lower()
    sec_plans: Dict[str, SectionArrangement] = {}

    for sec in unique_sections:
        voices: Dict[VoiceRole, SectionVoiceConfig] = {}

        # 1. LEAD: Always active in main sections, melody role on Ch 3
        voices[VoiceRole.LEAD] = SectionVoiceConfig(
            active=True,
            role=VoiceRole.LEAD,
            style_or_strategy="lead",
            target_channel=3,
        )

        # 2. BASS: Active on Ch 1
        # Style varies dynamically across sections
        if sec == "INTRO":
            bass_st = "pedal_drone" if p_name in ("dungeon", "title", "exploration") else "root_bass"
        elif sec in ("OUTRO", "C"):
            bass_st = "fanfare_bass" if p_name == "ending" else "walking"
        else:
            bass_st = rng.choice(profile.bass_styles)

        voices[VoiceRole.BASS] = SectionVoiceConfig(
            active=True,
            role=VoiceRole.BASS,
            style_or_strategy=bass_st,
            target_channel=1,
        )

        # 3. COUNTER / HARMONY: Channel 2
        # Determine counterpoint strategy and section activity
        # In Intro / Outro, counter can rest for contrast, or play harmonic support
        if sec == "INTRO":
            # Sparse intro: counter active in action/ending, resting in title/dungeon
            if p_name in ("action", "ending"):
                counter_active = True
                counter_strat = "call_response"
            else:
                counter_active = False
                counter_strat = "harmonic_support"
        elif sec == "OUTRO":
            counter_active = True
            counter_strat = "harmonic_support" if p_name != "ending" else "parallel"
        elif sec == "B":
            # Culmination section: full polyphony
            counter_active = True
            if p_name == "funny":
                counter_strat = "call_response"
            elif p_name in ("action", "ending"):
                counter_strat = "parallel"
            elif p_name == "exploration":
                counter_strat = "motif_echo"
            else:
                counter_strat = "harmonic_support"
        elif sec == "A'":
            counter_active = True
            counter_strat = "rhythmic_counterpoint" if p_name in ("action", "funny") else "call_response"
        else:  # Section A, C, etc.
            counter_active = True
            if p_name == "dungeon":
                counter_strat = "call_response"
            elif p_name == "funny":
                counter_strat = "call_response"
            elif p_name == "exploration":
                counter_strat = "motif_echo"
            else:
                counter_strat = "harmonic_support"

        voices[VoiceRole.COUNTER] = SectionVoiceConfig(
            active=counter_active,
            role=VoiceRole.COUNTER,
            style_or_strategy=counter_strat,
            target_channel=2,
        )

        # 4. RHYTHM / PERCUSSION / ORNAMENT: Channel 4
        # Dynamic appearance: builds up in B / culmination sections
        if p_name == "action":
            # Action has rhythm active in almost all sections
            rhythm_active = True
            rhythm_st = "percussion"
        elif p_name == "dungeon":
            # Dungeon only activates dark ostinato in section B or C (culmination)
            if sec in ("B", "C"):
                rhythm_active = True
                rhythm_st = "dark_ostinato"
            else:
                rhythm_active = False
                rhythm_st = "rest"
        elif p_name == "ending":
            # Ending introduces march snare in A/B and full fanfare in Outro
            if sec in ("B", "C", "OUTRO"):
                rhythm_active = True
                rhythm_st = "percussion"
            elif sec == "A":
                rhythm_active = rng.choice([True, False])
                rhythm_st = "percussion"
            else:
                rhythm_active = False
                rhythm_st = "rest"
        elif p_name == "exploration":
            # Exploration has delicate high ornaments in B or C
            if sec in ("B", "C", "A'"):
                rhythm_active = True
                rhythm_st = "ornament"
            else:
                rhythm_active = False
                rhythm_st = "rest"
        elif p_name == "funny":
            # Funny has comic accents / pops in B and A'
            if sec in ("B", "A'"):
                rhythm_active = True
                rhythm_st = rng.choice(["percussion", "comic_accents"])
            else:
                rhythm_active = False
                rhythm_st = "rest"
        else:  # title
            # Title has subtle ornament / soft pulse in B
            if sec in ("B", "A'"):
                rhythm_active = True
                rhythm_st = rng.choice(["ornament", "percussion"])
            else:
                rhythm_active = False
                rhythm_st = "rest"

        voices[VoiceRole.RHYTHM_ORNAMENT] = SectionVoiceConfig(
            active=rhythm_active,
            role=VoiceRole.RHYTHM_ORNAMENT,
            style_or_strategy=rhythm_st,
            target_channel=4,
        )

        # If 16-bit bass is used, physical channel 2 is joined with channel 1,
        # so COUNTER is mapped to Channel 4 (if not occupied) or 8-bit bass is preferred.
        # However, to preserve all 4 voices, 8-bit bass is standard for 4-channel polyphony.
        if uses_16bit_bass:
            # Re-route voices for 16-bit hardware constraint:
            # Ch 1+2 = Bass (16-bit)
            # Ch 3 = Lead
            # Ch 4 = Counter or Ornament
            voices[VoiceRole.COUNTER].target_channel = 4
            if rhythm_active and counter_active:
                # If both counter and ornament want ch 4, merge or prioritize counter
                voices[VoiceRole.RHYTHM_ORNAMENT].active = False

        active_count = sum(1 for v in voices.values() if v.active)
        sec_plans[sec] = SectionArrangement(
            section_label=sec,
            active_channel_count=active_count,
            voices=voices,
        )

    return SongArrangement(profile_name=p_name, sections=sec_plans)


def realize_arranged_pattern(
    pat_id: int,
    section_label: str,
    arrangement: SectionArrangement,
    lead_notes: List[SymbolicNote],
    progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    profile: MusicProfile,
    uses_16bit_bass: bool,
    rng: random.Random,
) -> SymbolicPattern:
    """Realize arranged voices into a SymbolicPattern with mapped POKEY channels."""
    tracks: Dict[int, SymbolicTrack] = {}
    total_rows = 32

    # 1. Lead Melody
    lead_cfg = arrangement.voices[VoiceRole.LEAD]
    lead_ch = lead_cfg.target_channel
    tracks[lead_ch] = SymbolicTrack(
        channel_idx=lead_ch,
        role=ChannelRole.MELODY,
        notes=lead_notes,
    )

    # 2. Bass Voice
    bass_cfg = arrangement.voices[VoiceRole.BASS]
    melody_pitches = [n.pitch for n in lead_notes if n.pitch is not None]
    if bass_cfg.active:
        bass_notes = generate_bassline(
            rows=total_rows,
            base_midi=root_midi,
            chord_progression=progression,
            scale=scale,
            role_type=bass_cfg.style_or_strategy,
            melody_pitches=melody_pitches,
            uses_16bit=uses_16bit_bass,
            rng=rng,
        )
    else:
        bass_notes = [SymbolicNote(duration=total_rows, is_rest=True, role=ChannelRole.BASS)]
    tracks[bass_cfg.target_channel] = SymbolicTrack(
        channel_idx=bass_cfg.target_channel,
        role=ChannelRole.BASS,
        notes=bass_notes,
    )

    # 3. Counter / Harmony Voice
    counter_cfg = arrangement.voices[VoiceRole.COUNTER]
    if counter_cfg.active:
        counter_notes = generate_counterpoint(
            strategy=counter_cfg.style_or_strategy,
            melody_notes=lead_notes,
            total_rows=total_rows,
            chord_progression=progression,
            scale=scale,
            root_midi=root_midi,
            rng=rng,
        )
    else:
        counter_notes = [SymbolicNote(duration=total_rows, is_rest=True, role=ChannelRole.HARMONY)]

    # If 16-bit bass is used and target channel is 4, don't write to channel 2
    if not (uses_16bit_bass and counter_cfg.target_channel == 2):
        tracks[counter_cfg.target_channel] = SymbolicTrack(
            channel_idx=counter_cfg.target_channel,
            role=ChannelRole.HARMONY,
            notes=counter_notes,
        )

    # 4. Rhythm / Percussion / Ornament Voice
    rhythm_cfg = arrangement.voices[VoiceRole.RHYTHM_ORNAMENT]
    if rhythm_cfg.active and not (uses_16bit_bass and rhythm_cfg.target_channel == 4 and counter_cfg.active):
        rhythm_notes = generate_rhythm_or_ornament(
            style=rhythm_cfg.style_or_strategy,
            total_rows=total_rows,
            chord_progression=progression,
            scale=scale,
            root_midi=root_midi,
            profile_name=profile.name,
            rng=rng,
        )
        tracks[rhythm_cfg.target_channel] = SymbolicTrack(
            channel_idx=rhythm_cfg.target_channel,
            role=ChannelRole.PERCUSSION if rhythm_cfg.style_or_strategy == "percussion" else ChannelRole.HARMONY,
            notes=rhythm_notes,
        )
    elif 4 not in tracks:
        # Channel 4 silent if not active
        tracks[4] = SymbolicTrack(
            channel_idx=4,
            role=ChannelRole.PERCUSSION,
            notes=[SymbolicNote(duration=total_rows, is_rest=True, role=ChannelRole.PERCUSSION)],
        )

    # If channel 2 is unused (e.g. 16-bit bass slave), ensure rest track exists
    if 2 not in tracks:
        tracks[2] = SymbolicTrack(
            channel_idx=2,
            role=ChannelRole.BASS if uses_16bit_bass else ChannelRole.HARMONY,
            notes=[SymbolicNote(duration=total_rows, is_rest=True, role=ChannelRole.HARMONY)],
        )

    return SymbolicPattern(id=pat_id, name=f"Pat {section_label}", rows=total_rows, tracks=tracks)

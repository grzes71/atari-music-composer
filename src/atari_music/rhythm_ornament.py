"""Rhythm, Percussion, and Ornament Engine for Atari POKEY Music.

Controls the 4th logical voice based on profile and musical section:
- percussion (Action driving pulse, Ending march, Funny syncopated pops, Title subtle pulse)
- dark_ostinato (Dungeon sinister low/mid repeating motif)
- ornament (Exploration delicate high chimes, Title melodic sparkles)
- comic_accents (Funny quirky staccato interjections)
- rest (Tactical silence for structural contrast)
"""

from __future__ import annotations

import random
from typing import List, Optional

from atari_music.harmony_engine import ChordStep, get_chord_tones
from atari_music.music_ir import ChannelRole, SymbolicNote


def generate_rhythm_or_ornament(
    style: str,
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    profile_name: str,
    rng: Optional[random.Random] = None,
) -> List[SymbolicNote]:
    """Generate notes for the 4th voice: percussion, ornament, or ostinato."""
    if rng is None:
        rng = random.Random(42)

    style = style.lower().strip()

    if style == "rest" or style == "none":
        return [
            SymbolicNote(
                pitch=None,
                duration=total_rows,
                velocity=0,
                role=ChannelRole.PERCUSSION,
                is_rest=True,
            )
        ]

    if style == "percussion":
        return _generate_profile_percussion(total_rows, profile_name, rng)
    elif style == "dark_ostinato":
        return _generate_dark_ostinato(total_rows, chord_progression, scale, root_midi, rng)
    elif style == "ornament":
        return _generate_high_ornament(total_rows, chord_progression, scale, root_midi, rng)
    elif style == "comic_accents":
        return _generate_comic_accents(total_rows, chord_progression, scale, root_midi, rng)
    else:
        # Default fallback
        if profile_name == "dungeon":
            return _generate_dark_ostinato(total_rows, chord_progression, scale, root_midi, rng)
        elif profile_name in ("action", "ending"):
            return _generate_profile_percussion(total_rows, profile_name, rng)
        else:
            return _generate_high_ornament(total_rows, chord_progression, scale, root_midi, rng)


def _generate_profile_percussion(
    total_rows: int,
    profile_name: str,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Generate authentic POKEY noise groove tailored to profile."""
    notes: List[SymbolicNote] = []

    if profile_name == "action":
        # Driving 16th combat pulse (kick on 0, 8, 16, 24, snare on 4, 12, 20, 28, hi-hats in between)
        for r in range(0, total_rows, 2):
            beat = r % 8
            if beat == 0:
                # Kick hit
                notes.append(SymbolicNote(duration=2, velocity=15, role=ChannelRole.PERCUSSION))
            elif beat == 4:
                # Snare hit
                notes.append(SymbolicNote(duration=2, velocity=15, role=ChannelRole.PERCUSSION))
            else:
                # Hi-hat 16th tick
                notes.append(SymbolicNote(duration=2, velocity=10, role=ChannelRole.PERCUSSION))

    elif profile_name == "ending":
        # Ceremonial military march snare: [accent, roll, roll, accent]
        for r in range(0, total_rows, 4):
            bar_pos = r % 16
            if bar_pos == 0:
                notes.append(SymbolicNote(duration=4, velocity=15, role=ChannelRole.PERCUSSION))
            elif bar_pos in (4, 8):
                # Double-tap roll
                notes.append(SymbolicNote(duration=2, velocity=11, role=ChannelRole.PERCUSSION))
                notes.append(SymbolicNote(duration=2, velocity=13, role=ChannelRole.PERCUSSION))
            elif bar_pos == 12:
                notes.append(SymbolicNote(duration=4, velocity=14, role=ChannelRole.PERCUSSION))
            else:
                notes.append(SymbolicNote(duration=4, velocity=9, role=ChannelRole.PERCUSSION))

    elif profile_name == "funny":
        # Whimsical syncopated noise pops
        for r in range(0, total_rows, 4):
            if (r // 4) % 2 == 1:
                notes.append(SymbolicNote(duration=2, velocity=13, role=ChannelRole.PERCUSSION))
                notes.append(SymbolicNote(duration=2, is_rest=True, role=ChannelRole.PERCUSSION))
            else:
                notes.append(SymbolicNote(duration=4, is_rest=True, role=ChannelRole.PERCUSSION))

    else:  # title or default
        # Subtle downbeat tick on bar boundaries (every 16 rows)
        for r in range(0, total_rows, 8):
            if r % 16 == 0:
                notes.append(SymbolicNote(duration=4, velocity=10, role=ChannelRole.PERCUSSION))
                notes.append(SymbolicNote(duration=4, is_rest=True, role=ChannelRole.PERCUSSION))
            else:
                notes.append(SymbolicNote(duration=8, is_rest=True, role=ChannelRole.PERCUSSION))

    return _trim_or_pad(notes, total_rows)


def _generate_dark_ostinato(
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Sinister modal ostinato for DUNGEON (pure tone low/mid voice, e.g. Phrygian 2nd)."""
    notes: List[SymbolicNote] = []
    # 4-row notes (8 steps across 32 rows)
    step_dur = 4
    steps = total_rows // step_dur
    ost_pattern = [0, 1, 0, -2, 0, 3, 1, 0]  # Sinister modal intervals

    for i in range(steps):
        semi = ost_pattern[i % len(ost_pattern)]
        pitch = root_midi + semi
        pitch = max(38, min(62, pitch))
        # Atmospheric pulsing velocity
        vol = 9 if i % 2 == 0 else 7
        notes.append(
            SymbolicNote(
                pitch=pitch,
                duration=step_dur,
                velocity=vol,
                role=ChannelRole.HARMONY,
            )
        )
    return _trim_or_pad(notes, total_rows)


def _generate_high_ornament(
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Delicate high register chime / arpeggiated sparkle for EXPLORATION and TITLE."""
    notes: List[SymbolicNote] = []
    step_dur = 4
    steps = total_rows // step_dur

    high_root = root_midi + 24  # High octave
    while high_root < 72:
        high_root += 12
    while high_root > 86:
        high_root -= 12

    for i in range(steps):
        chord_idx = (i * len(chord_progression)) // steps if chord_progression else 0
        chord = chord_progression[chord_idx] if chord_progression else ChordStep(degree=0, name="i")
        tones = get_chord_tones(chord, scale)

        # Sparkle occurs every 2nd or 3rd beat
        if i % 2 == 1:
            deg = tones[(i // 2) % len(tones)]
            pitch = high_root + deg
            pitch = max(68, min(92, pitch))
            notes.append(
                SymbolicNote(
                    pitch=pitch,
                    duration=step_dur,
                    velocity=8,  # Delicate pure tone
                    role=ChannelRole.HARMONY,
                )
            )
        else:
            notes.append(
                SymbolicNote(
                    pitch=None,
                    duration=step_dur,
                    velocity=0,
                    role=ChannelRole.HARMONY,
                    is_rest=True,
                )
            )

    return _trim_or_pad(notes, total_rows)


def _generate_comic_accents(
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Playful staccato comic interjections for FUNNY profile."""
    notes: List[SymbolicNote] = []
    step_dur = 2
    steps = total_rows // step_dur

    for i in range(steps):
        # Comic syncopated 'boing' on beat off-beats
        if i % 8 == 6:
            pitch = root_midi + 19  # High 5th
            notes.append(
                SymbolicNote(
                    pitch=pitch,
                    duration=step_dur,
                    velocity=14,
                    role=ChannelRole.HARMONY,
                )
            )
        else:
            notes.append(
                SymbolicNote(
                    pitch=None,
                    duration=step_dur,
                    velocity=0,
                    role=ChannelRole.HARMONY,
                    is_rest=True,
                )
            )

    return _trim_or_pad(notes, total_rows)


def _trim_or_pad(notes: List[SymbolicNote], target_rows: int) -> List[SymbolicNote]:
    """Ensure sum of durations strictly matches target_rows."""
    s = sum(n.duration for n in notes)
    if s == target_rows:
        return notes
    elif s < target_rows:
        notes.append(
            SymbolicNote(
                pitch=None,
                duration=target_rows - s,
                velocity=0,
                role=ChannelRole.HARMONY,
                is_rest=True,
            )
        )
        return notes
    else:
        trimmed: List[SymbolicNote] = []
        accum = 0
        for n in notes:
            if accum + n.duration <= target_rows:
                trimmed.append(n)
                accum += n.duration
            else:
                left = target_rows - accum
                if left > 0:
                    trimmed.append(
                        SymbolicNote(
                            pitch=n.pitch,
                            duration=left,
                            velocity=n.velocity,
                            role=n.role,
                            is_rest=n.is_rest,
                        )
                    )
                break
        return trimmed

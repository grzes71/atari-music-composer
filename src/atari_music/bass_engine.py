"""Advanced Bassline Generation Engine for Atari POKEY Music.

Supports rich harmonic and rhythmic bassline styles:
- root_bass: solid harmonic foundation on chord roots
- fifths: classic root-fifth alternating movement (I - V)
- walking: scalar diatonic transitions smoothly connecting chord roots
- counter_motion: contrary motion against lead melodic contour
- driving_pulse: high-energy arcade pulse with syncopated octave accents
- bouncy_staccato: comic/playful staccato leaps with rests
- pedal_drone: sustained modal low root anchor
- dark_ostinato: sinister minor/Phrygian repeating motif
- fanfare_bass: triumphant I-V-I march leaps
- soft_pedal: gentle rhythmic pulse for reflective themes
"""

from __future__ import annotations

import random
from typing import List, Optional

from atari_music.harmony_engine import ChordStep
from atari_music.music_ir import ChannelRole, SymbolicNote


def generate_bassline(
    rows: int,
    base_midi: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    role_type: str,
    melody_pitches: Optional[List[int]] = None,
    uses_16bit: bool = False,
    rng: Optional[random.Random] = None,
) -> List[SymbolicNote]:
    """Generate dynamic, musically appropriate bassline for a pattern of `rows` rows."""
    if rng is None:
        rng = random.Random(42)

    # Determine base octave: 16-bit bass can reach lower safely down to MIDI 24 (C1)
    root = (base_midi - 24) if uses_16bit else (base_midi - 12)
    while root > 45:
        root -= 12
    while root < 33 and not uses_16bit:
        root += 12

    chord_count = len(chord_progression) if chord_progression else 1

    # Choose rhythmic subdivisions based on style
    if role_type in ("pedal_drone", "soft_pedal"):
        # Long sustained notes: e.g. two 16-row notes or four 8-row notes
        rhythms = [16, 16] if rows == 32 else [rows]
    elif role_type in ("walking", "fanfare_bass"):
        # 4-row notes (quarter notes in 4/4)
        rhythms = [4] * (rows // 4)
    elif role_type == "bouncy_staccato":
        # Alternating note and rest patterns
        rhythms = [2, 2, 2, 2] * (rows // 8)
    elif role_type == "driving_pulse":
        # 2-row notes with occasional 4-row syncopations
        rhythms = [2] * (rows // 2)
    elif role_type in ("ostinato", "dark_ostinato"):
        # Rhythmic 4-step or 2-step cells
        rhythms = [2] * (rows // 2)
    else:  # root_bass, counter_motion, fifths
        rhythms = [4] * (rows // 4)

    notes: List[SymbolicNote] = []
    current_row = 0

    for step_idx, dur in enumerate(rhythms):
        # Active chord for current position in pattern
        chord_idx = (current_row * chord_count) // rows
        chord = chord_progression[chord_idx] if chord_progression else ChordStep(degree=0, name="i")
        chord_root_deg = scale[chord.degree % len(scale)]

        base_pitch = root + chord_root_deg
        is_rest = False
        vol = 13

        if role_type == "counter_motion" and melody_pitches and step_idx < len(melody_pitches):
            if step_idx > 0:
                mel_dir = melody_pitches[step_idx] - melody_pitches[step_idx - 1]
                if mel_dir > 0:
                    pitch = base_pitch - rng.choice([2, 4, 5])
                elif mel_dir < 0:
                    pitch = base_pitch + rng.choice([2, 4, 5])
                else:
                    pitch = base_pitch
            else:
                pitch = base_pitch

        elif role_type == "fifths":
            # Alternate between root and fifth (7 semitones)
            pitch = base_pitch if (step_idx % 2 == 0) else (base_pitch + 7)

        elif role_type == "walking":
            # Walk diatonically towards the next chord
            next_chord_idx = ((current_row + dur) * chord_count) // rows
            next_chord = chord_progression[next_chord_idx % chord_count] if chord_progression else chord
            next_root_deg = scale[next_chord.degree % len(scale)]
            next_pitch = root + next_root_deg

            step_in_chord = step_idx % 4
            if step_in_chord == 0:
                pitch = base_pitch
            elif step_in_chord == 1:
                # 3rd or passing scale tone
                deg_offset = (chord.degree + 2) % len(scale)
                pitch = root + scale[deg_offset]
            elif step_in_chord == 2:
                # 5th
                deg_offset = (chord.degree + 4) % len(scale)
                pitch = root + scale[deg_offset]
            else:
                # Leading note / chromatic approach to next pitch
                pitch = next_pitch - 1 if next_pitch > base_pitch else next_pitch + 1

        elif role_type == "ostinato":
            # 4-step motif: root, root, 5th, 4th
            ost = [0, 0, 7, 5]
            pitch = base_pitch + ost[step_idx % len(ost)]

        elif role_type == "dark_ostinato":
            # Sinister low modal ostinato: root, minor 2nd, root, flat 7th
            dark_pat = [0, 1, 0, -2]
            pitch = base_pitch + dark_pat[step_idx % len(dark_pat)]

        elif role_type == "fanfare_bass":
            # Majestic fanfare cadence: root, fifth, octave, root
            fanfare_pat = [0, 7, 12, 7]
            pitch = base_pitch + fanfare_pat[step_idx % len(fanfare_pat)]

        elif role_type == "bouncy_staccato":
            # Playful leaps with staccato rests
            bounce_pat = [0, 12, 7, 12]
            pitch = base_pitch + bounce_pat[step_idx % len(bounce_pat)]
            if step_idx % 2 == 1:
                is_rest = True  # Staccato space

        elif role_type == "driving_pulse":
            # Driving arcade 8ths: octave pop on upbeat of every 2nd beat
            if step_idx % 4 == 3:
                pitch = base_pitch + 12
                vol = 15
            else:
                pitch = base_pitch
                vol = 13 if step_idx % 2 == 0 else 11

        elif role_type in ("pedal_drone", "soft_pedal"):
            pitch = root
            vol = 8 if role_type == "soft_pedal" else 10

        else:  # root_bass
            pitch = base_pitch
            vol = 14 if step_idx % 2 == 0 else 12

        # Safe POKEY register bounds:
        min_p = 24 if uses_16bit else 33
        max_p = 60
        pitch = max(min_p, min(max_p, pitch))

        notes.append(
            SymbolicNote(
                pitch=pitch if not is_rest else None,
                duration=dur,
                velocity=vol,
                role=ChannelRole.BASS,
                is_chord_tone=True,
                is_rest=is_rest,
            )
        )
        current_row += dur

    return notes

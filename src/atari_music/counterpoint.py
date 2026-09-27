"""Counterpoint and Second Voice Engine for Atari POKEY Music.

Implements 5 core counterpoint strategies for COUNTER/HARMONY:
1. Call & Response: Answers in gaps and sustained notes of the main lead melody.
2. Harmonic Support: Diatonic 3rds, 6ths, and chord tones in tenor/alto register.
3. Parallel Motion: Melodic parallel doubling at consonant diatonic intervals.
4. Rhythmic Counterpoint: Interlocking / complementary rhythm filling rests between lead notes.
5. Motif Echo: Delayed canonical echo of lead motif with register shift or simplification.
"""

from __future__ import annotations

import random
from typing import List, Optional

from atari_music.harmony_engine import ChordStep, get_chord_tones
from atari_music.music_ir import ChannelRole, SymbolicNote


def generate_counterpoint(
    strategy: str,
    melody_notes: List[SymbolicNote],
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: Optional[random.Random] = None,
) -> List[SymbolicNote]:
    """Generate a second voice musically dependent on the lead melody and harmony."""
    if rng is None:
        rng = random.Random(42)

    strategy = strategy.lower().strip()
    if strategy == "call_response":
        return _generate_call_and_response(melody_notes, total_rows, chord_progression, scale, root_midi, rng)
    elif strategy == "harmonic_support":
        return _generate_harmonic_support(melody_notes, total_rows, chord_progression, scale, root_midi, rng)
    elif strategy == "parallel":
        return _generate_parallel_motion(melody_notes, total_rows, chord_progression, scale, root_midi, rng)
    elif strategy == "rhythmic_counterpoint":
        return _generate_rhythmic_counterpoint(melody_notes, total_rows, chord_progression, scale, root_midi, rng)
    elif strategy == "motif_echo":
        return _generate_motif_echo(melody_notes, total_rows, chord_progression, scale, root_midi, rng)
    else:
        # Default fallback to harmonic support
        return _generate_harmonic_support(melody_notes, total_rows, chord_progression, scale, root_midi, rng)


def _find_closest_scale_pitch(target_pitch: int, root_midi: int, scale: List[int]) -> int:
    """Snap any MIDI pitch to the closest pitch in the given scale."""
    octave = (target_pitch - root_midi) // 12
    semi_in_oct = (target_pitch - root_midi) % 12
    best_deg = min(scale, key=lambda d: abs(d - semi_in_oct))
    return root_midi + octave * 12 + best_deg


def _get_chord_at_row(row: int, total_rows: int, progression: List[ChordStep]) -> ChordStep:
    """Retrieve active chord step at a specific row index."""
    if not progression:
        return ChordStep(degree=0, name="i")
    idx = (row * len(progression)) // total_rows
    return progression[min(idx, len(progression) - 1)]


def _generate_call_and_response(
    melody_notes: List[SymbolicNote],
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Strategy A: Call & Response.
    
    When melody is busy with short notes, counter rests.
    When melody sustains a long note or has rests, counter enters with a response phrase.
    """
    notes: List[SymbolicNote] = []
    
    # Map melody timeline
    current_row = 0
    for note in melody_notes:
        dur = note.duration
        chord = _get_chord_at_row(current_row, total_rows, chord_progression)
        chord_tones = get_chord_tones(chord, scale)

        if dur <= 3 and not note.is_rest:
            # Lead is actively talking: counter rests to avoid muddy collision
            notes.append(
                SymbolicNote(
                    pitch=None,
                    duration=dur,
                    velocity=0,
                    role=ChannelRole.HARMONY,
                    is_rest=True,
                )
            )
        else:
            # Lead is resting or holding a long note (dur >= 4): Counter answers!
            # Divide long duration into an answering phrase (e.g. 2 notes or 1 note + rest)
            lead_pitch = note.pitch or (root_midi + 12)
            answer_pitch_base = lead_pitch - rng.choice([3, 4, 7, 8])
            answer_pitch = _find_closest_scale_pitch(answer_pitch_base, root_midi, scale)
            answer_pitch = max(45, min(72, answer_pitch))

            if dur >= 6:
                half_dur = dur // 2
                rem_dur = dur - half_dur
                # Note 1
                notes.append(
                    SymbolicNote(
                        pitch=answer_pitch,
                        duration=half_dur,
                        velocity=11,
                        role=ChannelRole.HARMONY,
                    )
                )
                # Note 2: Stepwise resolution to chord tone
                step_offset = rng.choice([-2, 1, 2])
                res_pitch = _find_closest_scale_pitch(answer_pitch + step_offset, root_midi, scale)
                res_pitch = max(45, min(72, res_pitch))
                notes.append(
                    SymbolicNote(
                        pitch=res_pitch,
                        duration=rem_dur,
                        velocity=10,
                        role=ChannelRole.HARMONY,
                    )
                )
            else:
                notes.append(
                    SymbolicNote(
                        pitch=answer_pitch,
                        duration=dur,
                        velocity=11,
                        role=ChannelRole.HARMONY,
                    )
                )
        current_row += dur

    return _normalize_total_duration(notes, total_rows)


def _generate_harmonic_support(
    melody_notes: List[SymbolicNote],
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Strategy B: Harmonic Support.
    
    Pairs melody with diatonic 3rds/6ths and chord tones in tenor/alto register.
    Groups fast 1-2 row notes into smoother 4-row harmonic blocks.
    """
    notes: List[SymbolicNote] = []
    current_row = 0

    idx = 0
    while idx < len(melody_notes):
        n = melody_notes[idx]
        chord = _get_chord_at_row(current_row, total_rows, chord_progression)
        chord_tones = get_chord_tones(chord, scale)

        if n.is_rest or n.pitch is None:
            notes.append(
                SymbolicNote(
                    pitch=None,
                    duration=n.duration,
                    velocity=0,
                    role=ChannelRole.HARMONY,
                    is_rest=True,
                )
            )
            current_row += n.duration
            idx += 1
            continue

        # Look ahead: if notes are short (dur <= 2), can combine into a 4-row harmonic note
        dur = n.duration
        if dur <= 2 and (idx + 1) < len(melody_notes) and melody_notes[idx + 1].duration <= 2:
            combined_dur = dur + melody_notes[idx + 1].duration
            lead_p = n.pitch
            # Target 3rd or 6th below
            target_p = lead_p - rng.choice([3, 4, 8, 9])
            harm_pitch = _find_closest_scale_pitch(target_p, root_midi, scale)
            harm_pitch = max(45, min(70, harm_pitch))

            notes.append(
                SymbolicNote(
                    pitch=harm_pitch,
                    duration=combined_dur,
                    velocity=10,
                    role=ChannelRole.HARMONY,
                    is_chord_tone=True,
                )
            )
            current_row += combined_dur
            idx += 2
        else:
            lead_p = n.pitch
            target_p = lead_p - rng.choice([3, 4, 7, 8])
            harm_pitch = _find_closest_scale_pitch(target_p, root_midi, scale)
            harm_pitch = max(45, min(70, harm_pitch))

            notes.append(
                SymbolicNote(
                    pitch=harm_pitch,
                    duration=dur,
                    velocity=10,
                    role=ChannelRole.HARMONY,
                    is_chord_tone=True,
                )
            )
            current_row += dur
            idx += 1

    return _normalize_total_duration(notes, total_rows)


def _generate_parallel_motion(
    melody_notes: List[SymbolicNote],
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Strategy C: Parallel Motion.
    
    Duplicates melodic contour strictly at a diatonic 3rd (or 6th) below.
    Ideal for triumphant fanfares (ENDING) and hero climaxes (ACTION).
    """
    notes: List[SymbolicNote] = []
    interval_choice = rng.choice([3, 4, 8, 9])  # 3rd or 6th

    for n in melody_notes:
        if n.is_rest or n.pitch is None:
            notes.append(
                SymbolicNote(
                    pitch=None,
                    duration=n.duration,
                    velocity=0,
                    role=ChannelRole.HARMONY,
                    is_rest=True,
                )
            )
        else:
            target_p = n.pitch - interval_choice
            parallel_pitch = _find_closest_scale_pitch(target_p, root_midi, scale)
            parallel_pitch = max(45, min(75, parallel_pitch))
            notes.append(
                SymbolicNote(
                    pitch=parallel_pitch,
                    duration=n.duration,
                    velocity=10,  # Softer than lead
                    role=ChannelRole.HARMONY,
                )
            )

    return _normalize_total_duration(notes, total_rows)


def _generate_rhythmic_counterpoint(
    melody_notes: List[SymbolicNote],
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Strategy D: Rhythmic Counterpoint.
    
    Interlocking complementary rhythm: plays active syncopated beats
    off-phase from the lead melody, providing rhythmic drive.
    """
    # Grid of total_rows (typically 32 ticks)
    grid_melody = [False] * total_rows
    pos = 0
    for n in melody_notes:
        if not n.is_rest:
            for r in range(pos, min(total_rows, pos + n.duration)):
                grid_melody[r] = True
        pos += n.duration

    notes: List[SymbolicNote] = []
    # Build counterpoint in 2-row chunks
    step_dur = 2
    for row in range(0, total_rows, step_dur):
        chord = _get_chord_at_row(row, total_rows, chord_progression)
        chord_tones = get_chord_tones(chord, scale)
        chord_pitch = root_midi + chord_tones[row % len(chord_tones)]
        chord_pitch = max(45, min(70, chord_pitch))

        # Check if melody has sound here
        mel_active = any(grid_melody[min(total_rows - 1, row + offset)] for offset in range(step_dur))

        if not mel_active:
            # Melody is quiet: play prominent counterpoint note
            notes.append(
                SymbolicNote(
                    pitch=chord_pitch,
                    duration=step_dur,
                    velocity=12,
                    role=ChannelRole.HARMONY,
                )
            )
        else:
            # Melody is active: play light off-beat hit or rest
            if (row // step_dur) % 2 == 1:
                notes.append(
                    SymbolicNote(
                        pitch=chord_pitch - 5,
                        duration=step_dur,
                        velocity=8,
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

    return _normalize_total_duration(notes, total_rows)


def _generate_motif_echo(
    melody_notes: List[SymbolicNote],
    total_rows: int,
    chord_progression: List[ChordStep],
    scale: List[int],
    root_midi: int,
    rng: random.Random,
) -> List[SymbolicNote]:
    """Strategy E: Motif Echo.
    
    Echoes the opening motive with a 4 or 8-row delay and lower octave/velocity.
    Particularly effective in EXPLORATION, TITLE, and DUNGEON.
    """
    delay_rows = 4 if total_rows >= 16 else 2
    notes: List[SymbolicNote] = []

    # Initial rest for delay
    notes.append(
        SymbolicNote(
            pitch=None,
            duration=delay_rows,
            velocity=0,
            role=ChannelRole.HARMONY,
            is_rest=True,
        )
    )

    remaining_rows = total_rows - delay_rows
    pos = 0
    for n in melody_notes:
        if pos >= remaining_rows:
            break
        take_dur = min(n.duration, remaining_rows - pos)
        if n.is_rest or n.pitch is None:
            notes.append(
                SymbolicNote(
                    pitch=None,
                    duration=take_dur,
                    velocity=0,
                    role=ChannelRole.HARMONY,
                    is_rest=True,
                )
            )
        else:
            # Echo: pitch shifted down 7 or 12 semitones, softer velocity
            echo_pitch = n.pitch - rng.choice([7, 12])
            echo_pitch = _find_closest_scale_pitch(echo_pitch, root_midi, scale)
            echo_pitch = max(45, min(70, echo_pitch))
            notes.append(
                SymbolicNote(
                    pitch=echo_pitch,
                    duration=take_dur,
                    velocity=8,  # Delicate echo
                    role=ChannelRole.HARMONY,
                )
            )
        pos += take_dur

    return _normalize_total_duration(notes, total_rows)


def _normalize_total_duration(notes: List[SymbolicNote], target_rows: int) -> List[SymbolicNote]:
    """Ensure sum of note durations exactly matches target_rows."""
    current_sum = sum(n.duration for n in notes)
    if current_sum == target_rows:
        return notes
    elif current_sum < target_rows:
        diff = target_rows - current_sum
        notes.append(
            SymbolicNote(
                pitch=None,
                duration=diff,
                velocity=0,
                role=ChannelRole.HARMONY,
                is_rest=True,
            )
        )
        return notes
    else:
        # Trim excess
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
                            is_chord_tone=n.is_chord_tone,
                        )
                    )
                break
        return trimmed

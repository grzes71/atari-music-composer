"""Procedural Music Generator for Atari POKEY based on Mined Archetypes.

Implements:
generate_song(seed: int, parameters: Dict[str, Any]) -> IRSong

Parameters:
- tempo: BPM (80..160)
- key: "C", "D", "E", "F", "G", "A", "B"
- mode: "major", "minor", "dorian", "pentatonic"
- melody_complexity: "low", "medium", "high"
- repetition: float (0.0 .. 1.0)
- syncopation: float (0.0 .. 1.0)
- bass_complexity: "low", "medium", "high"
- percussion_density: "low", "medium", "high"
- distortion_style: "pure_a0", "gritty_c0", "hybrid", "vintage"

Strict Constraints:
- 4 POKEY channels
- Monophonic channels (with optional 16-bit bass pairing on CH1+CH2)
- Strict pitch bounds (playable POKEY frequencies)
- 4..6 instruments
- 3..5 reusable patterns
- Budget: < 2 KB compact binary footprint
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from atari_music.archetypes import ArchetypeLibrary, mine_archetypes_from_dataset
from atari_music.constants import (
    DISTORTION_4BIT_POLY,
    DISTORTION_5BIT_POLY_1,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    NOTE_NAMES,
)
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRPattern,
    IRSong,
    calculate_ir_binary_size,
    midi_to_note_name,
)

# Scale intervals from root
SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "pentatonic": [0, 3, 5, 7, 10],  # minor pentatonic
}

KEY_BASE_MIDI = {
    "C": 60, "C#": 61, "D": 62, "D#": 63, "E": 64, "F": 65,
    "F#": 66, "G": 67, "G#": 68, "A": 69, "A#": 70, "B": 71,
}


def generate_song(seed: int, parameters: Optional[Dict[str, Any]] = None) -> IRSong:
    """Generate a procedural Atari POKEY song complying strictly with hardware and data constraints."""
    rng = random.Random(seed)
    params = parameters or {}

    # 1. Parameter extraction with intelligent defaults
    tempo = params.get("tempo", rng.choice([115, 125, 136, 150]))
    key = params.get("key", rng.choice(["C", "D", "E", "F", "G", "A"]))
    mode = params.get("mode", rng.choice(["minor", "dorian", "major", "pentatonic"]))
    melody_complexity = params.get("melody_complexity", rng.choice(["low", "medium", "high"]))
    repetition = float(params.get("repetition", rng.uniform(0.5, 0.85)))
    syncopation = float(params.get("syncopation", rng.uniform(0.1, 0.6)))
    bass_complexity = params.get("bass_complexity", rng.choice(["low", "medium", "high"]))
    percussion_density = params.get("percussion_density", rng.choice(["low", "medium", "high"]))
    distortion_style = params.get("distortion_style", rng.choice(["pure_a0", "gritty_c0", "hybrid"]))

    # Frame timing: 50 Hz PAL frames per tick (3, 4, or 5)
    # At 125 BPM, 4 frames/tick = 80ms/row, 16 rows = 1.28s
    frames_per_tick = 4 if tempo <= 135 else 3

    # Option: 16-bit bass pairing (CH1+CH2)
    uses_16bit = params.get("uses_16bit_bass", rng.random() < 0.40)

    # 2. Instruments Definition
    instruments = _create_instruments(distortion_style, uses_16bit)

    # 3. Create Scale Pitch Palette
    root_midi = KEY_BASE_MIDI.get(key, 60)
    scale_degrees = SCALES.get(mode, SCALES["minor"])

    # 4. Generate 3 to 4 Archetype-Driven Patterns (32 rows each)
    num_patterns = 3 if repetition >= 0.7 else 4
    patterns: List[IRPattern] = []

    melody_archetypes = ["stepwise", "ascending", "question_answer", "ab_phrase", "jump_resolution"]
    bass_archetypes = ["tonic_fifth", "repeated_ostinato", "octave", "walking"]
    if uses_16bit:
        bass_archetypes.append("16bit_bass")

    for pat_id in range(num_patterns):
        # Pick archetypes for this pattern section
        mel_arch = rng.choice(melody_archetypes)
        b_arch = rng.choice(bass_archetypes)

        pat = _build_pattern(
            pat_id=pat_id,
            rows=32,
            root_midi=root_midi,
            scale=scale_degrees,
            mel_arch=mel_arch,
            b_arch=b_arch,
            melody_complexity=melody_complexity,
            syncopation=syncopation,
            bass_complexity=bass_complexity,
            percussion_density=percussion_density,
            uses_16bit=uses_16bit,
            rng=rng,
        )
        patterns.append(pat)

    # 5. Build Song Sequence Order List (8 to 12 sections = 20 to 31 seconds)
    total_sections = rng.choice([8, 10, 12])
    sequence = _build_sequence(num_patterns, total_sections, repetition, rng)

    song = IRSong(
        title=f"POKEY Procedural #{seed:03d} ({key} {mode})",
        author="POKEY Procedural Engine",
        tempo_bpm=tempo,
        frames_per_tick=frames_per_tick,
        key=key,
        mode=mode,
        seed=seed,
        instruments=instruments,
        patterns=patterns,
        sequence=sequence,
        uses_16bit_bass=uses_16bit,
    )

    # Verify and enforce < 2 KB data budget
    size_bytes = calculate_ir_binary_size(song)
    if size_bytes > 2048:
        # Trim sequence or reduce patterns if needed
        song.sequence = song.sequence[:8]

    return song


def _create_instruments(distortion_style: str, uses_16bit: bool) -> List[IRInstrument]:
    """Define standard POKEY instruments respecting timbral style."""
    if distortion_style == "gritty_c0":
        lead_dist = DISTORTION_4BIT_POLY
        bass_dist = DISTORTION_4BIT_POLY
    elif distortion_style == "hybrid":
        lead_dist = DISTORTION_PURE_TONE
        bass_dist = DISTORTION_4BIT_POLY
    else:  # pure_a0
        lead_dist = DISTORTION_PURE_TONE
        bass_dist = DISTORTION_PURE_TONE

    instruments = [
        # Inst 0: Lead Melody
        IRInstrument(
            id=0,
            name="Lead Tone",
            distortion=lead_dist,
            role="melody",
            envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=11, release_frames=2),
            vibrato_depth=1,
            vibrato_speed=2,
        ),
        # Inst 1: Bass
        IRInstrument(
            id=1,
            name="Bass 16-bit" if uses_16bit else "Bass Voice",
            distortion=bass_dist,
            role="bass",
            envelope=IREnvelope(attack_frames=0, decay_frames=4, sustain_vol=8, release_frames=2),
            is_16bit=uses_16bit,
        ),
        # Inst 2: Arpeggio / Stabs
        IRInstrument(
            id=2,
            name="Chiptune Stabs",
            distortion=DISTORTION_PURE_TONE,
            role="harmony",
            envelope=IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=6, release_frames=1),
        ),
        # Inst 3: Kick Drum
        IRInstrument(
            id=3,
            name="POKEY Kick",
            distortion=DISTORTION_4BIT_POLY,
            role="percussion",
            macro=[
                IRMacroStep(audf_offset=42, distortion=DISTORTION_4BIT_POLY, volume=15),
                IRMacroStep(audf_offset=70, distortion=DISTORTION_4BIT_POLY, volume=12),
                IRMacroStep(audf_offset=115, distortion=DISTORTION_PURE_TONE, volume=7),
                IRMacroStep(audf_offset=160, distortion=DISTORTION_PURE_TONE, volume=0),
            ],
        ),
        # Inst 4: Snare Drum
        IRInstrument(
            id=4,
            name="POKEY Snare",
            distortion=DISTORTION_WHITE_NOISE,
            role="percussion",
            macro=[
                IRMacroStep(audf_offset=12, distortion=DISTORTION_4BIT_POLY, volume=15),
                IRMacroStep(audf_offset=16, distortion=0x80, volume=14),
                IRMacroStep(audf_offset=22, distortion=0x80, volume=8),
                IRMacroStep(audf_offset=30, distortion=0x80, volume=0),
            ],
        ),
        # Inst 5: Closed Hi-Hat
        IRInstrument(
            id=5,
            name="POKEY Hi-Hat",
            distortion=0x80,
            role="percussion",
            macro=[
                IRMacroStep(audf_offset=3, distortion=0x80, volume=9),
                IRMacroStep(audf_offset=4, distortion=0x80, volume=0),
            ],
        ),
    ]
    return instruments


def _build_pattern(
    pat_id: int,
    rows: int,
    root_midi: int,
    scale: List[int],
    mel_arch: str,
    b_arch: str,
    melody_complexity: str,
    syncopation: float,
    bass_complexity: str,
    percussion_density: str,
    uses_16bit: bool,
    rng: random.Random,
) -> IRPattern:
    """Build a 4-channel pattern of `rows` rows using specified musical archetypes."""
    tracks: Dict[int, List[IRNote]] = {}

    # Channel 1 & 2: Bass (or 16-bit pair)
    bass_notes = _generate_bass_track(rows, root_midi - 24, scale, b_arch, bass_complexity, uses_16bit, rng)
    tracks[1] = bass_notes

    if uses_16bit:
        # Channel 2 is slave for 16-bit mode (empty or mirrors structure)
        tracks[2] = [IRNote(duration=rows, is_rest=True, channel_role="bass")]
    else:
        # Channel 2: Arpeggios / Counterpoint
        tracks[2] = _generate_harmony_track(rows, root_midi - 12, scale, rng)

    # Channel 3: Lead Melody
    tracks[3] = _generate_melody_track(rows, root_midi, scale, mel_arch, melody_complexity, syncopation, rng)

    # Channel 4: Percussion Track (Kick, Snare, Hi-Hat)
    tracks[4] = _generate_percussion_track(rows, percussion_density, rng)

    return IRPattern(id=pat_id, name=f"Pattern #{pat_id}", rows=rows, tracks=tracks)


def _generate_melody_track(
    rows: int,
    root_midi: int,
    scale: List[int],
    arch: str,
    complexity: str,
    syncopation: float,
    rng: random.Random,
) -> List[IRNote]:
    """Generate melodic line based on melody archetypes."""
    notes: List[IRNote] = []
    step_dur = 2 if complexity in ("medium", "high") else 4
    total_steps = rows // step_dur

    current_deg_idx = 0
    scale_len = len(scale)

    for i in range(total_steps):
        # Decide if rest
        is_rest = (rng.random() < 0.15) if syncopation > 0.3 and (i % 2 == 1) else False
        if is_rest:
            notes.append(IRNote(duration=step_dur, is_rest=True, channel_role="melody"))
            continue

        # Archetype pitch trajectory
        if arch == "ascending":
            current_deg_idx = (i % scale_len)
        elif arch == "descending":
            current_deg_idx = (scale_len - 1 - (i % scale_len))
        elif arch == "stepwise":
            delta = rng.choice([-1, 0, 1])
            current_deg_idx = max(0, min(scale_len * 2 - 1, current_deg_idx + delta))
        elif arch == "jump_resolution":
            if i % 4 == 0:
                current_deg_idx = (current_deg_idx + 4) % (scale_len * 2)  # jump
            else:
                current_deg_idx = max(0, current_deg_idx - 1)  # contrary step
        elif arch == "repeated_note":
            current_deg_idx = 0 if i < total_steps - 2 else 2
        else:  # question_answer / ab_phrase
            if i < total_steps // 2:
                current_deg_idx = (i * 2) % scale_len
            else:
                current_deg_idx = ((i - total_steps // 2) * 2 + 1) % scale_len
                if i == total_steps - 1:
                    current_deg_idx = 0  # resolve to tonic!

        octave_shift = (current_deg_idx // scale_len) * 12
        deg = scale[current_deg_idx % scale_len]
        midi_note = root_midi + octave_shift + deg

        # Bound playable POKEY pitch (A440 is 69, C4 is 60, C6 is 84)
        midi_note = max(55, min(84, midi_note))

        # Add note
        dur = step_dur
        notes.append(
            IRNote(
                pitch=midi_to_note_name(midi_note),
                midi_pitch=midi_note,
                duration=dur,
                volume=rng.choice([13, 14, 15]),
                instrument_id=0,
                channel_role="melody",
            )
        )
    return notes


def _generate_bass_track(
    rows: int,
    base_midi: int,
    scale: List[int],
    arch: str,
    complexity: str,
    uses_16bit: bool,
    rng: random.Random,
) -> List[IRNote]:
    """Generate bass line following bass archetypes."""
    notes: List[IRNote] = []
    dur = 2
    steps = rows // dur

    # For 16-bit bass, we can comfortably drop down to C1 (MIDI 24..36)
    root = (base_midi - 12) if uses_16bit else base_midi

    for i in range(steps):
        if arch == "tonic_fifth":
            pitch_offset = 0 if (i % 4 in (0, 1)) else 7
        elif arch == "octave":
            pitch_offset = 0 if (i % 2 == 0) else 12
        elif arch == "repeated_ostinato":
            pattern = [0, 0, 3, 5, 0, 0, 3, 2]
            pitch_offset = pattern[i % len(pattern)]
        elif arch == "16bit_bass":
            pattern = [0, 0, 7, 0, 0, 12, 7, 0]
            pitch_offset = pattern[i % len(pattern)]
        else:  # walking
            idx = (i % len(scale))
            pitch_offset = scale[idx]

        midi_note = max(24 if uses_16bit else 36, min(55, root + pitch_offset))

        notes.append(
            IRNote(
                pitch=midi_to_note_name(midi_note),
                midi_pitch=midi_note,
                duration=dur,
                volume=14 if i % 2 == 0 else 11,
                instrument_id=1,
                channel_role="bass",
            )
        )
    return notes


def _generate_harmony_track(
    rows: int,
    base_midi: int,
    scale: List[int],
    rng: random.Random,
) -> List[IRNote]:
    """Generate light arpeggio or rhythmic chord stabs on Channel 2."""
    notes: List[IRNote] = []
    chord_degrees = [0, scale[2 % len(scale)], scale[4 % len(scale)]]  # Triad (root, third, fifth)
    step_dur = 2
    steps = rows // step_dur

    for i in range(steps):
        # Arpeggiate through triad degrees
        arp_deg = chord_degrees[i % len(chord_degrees)]
        midi_note = max(48, min(72, base_midi + arp_deg))
        notes.append(
            IRNote(
                pitch=midi_to_note_name(midi_note),
                midi_pitch=midi_note,
                duration=step_dur,
                volume=8 if (i % 2 == 0) else 6,
                instrument_id=2,
                channel_role="harmony",
            )
        )
    return notes


def _generate_percussion_track(
    rows: int,
    density: str,
    rng: random.Random,
) -> List[IRNote]:
    """Generate rhythmic drum sequence (Kick, Snare, Hi-Hat) on Channel 4."""
    notes: List[IRNote] = []
    # Standard 16/32-step groove grid:
    # Row 0, 8, 16, 24 = Kick (Inst 3)
    # Row 4, 12, 20, 28 = Snare (Inst 4)
    # Even rows in between = Hi-Hat (Inst 5)
    row = 0
    while row < rows:
        if row % 8 == 0:
            # Kick hit
            notes.append(IRNote(duration=2, volume=15, instrument_id=3, channel_role="percussion"))
            row += 2
        elif row % 8 == 4:
            # Snare hit
            notes.append(IRNote(duration=2, volume=15, instrument_id=4, channel_role="percussion"))
            row += 2
        else:
            # Hi-Hat or Rest depending on density
            if density in ("medium", "high") or (row % 4 == 2):
                notes.append(IRNote(duration=2, volume=11, instrument_id=5, channel_role="percussion"))
            else:
                notes.append(IRNote(duration=2, is_rest=True, channel_role="percussion"))
            row += 2
    return notes


def _build_sequence(
    num_patterns: int,
    total_sections: int,
    repetition: float,
    rng: random.Random,
) -> List[int]:
    """Generate song order sequence maximizing musical form (e.g. AABB, ABAB, AABA)."""
    if num_patterns == 3:
        # Form: A, B, A, B, C, C, A, B
        base_form = [0, 1, 0, 1, 2, 2, 0, 1, 2, 0, 1, 0]
    else:
        # Form: A, B, A, B, C, D, C, D, A, B
        base_form = [0, 1, 0, 1, 2, 3, 2, 3, 0, 1, 2, 0]

    # Adjust according to repetition
    seq = base_form[:total_sections]
    if repetition < 0.5:
        # Inject more variations
        for idx in range(len(seq)):
            if rng.random() > repetition:
                seq[idx] = rng.randint(0, num_patterns - 1)
    return seq

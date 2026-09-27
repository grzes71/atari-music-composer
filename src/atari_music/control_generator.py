"""Control (Naive) Procedural Music Generator.

Designed as an unguided baseline (GROUP C - CONTROL) for listening tests:
- Strictly respects POKEY hardware limits (4 monophonic channels, valid registers)
- Operates in the same tempo range and standard musical scales
- BUT deliberately DOES NOT use the mined archetypes:
    * No directional melodic archetypes (stepwise, ascending, jump-resolution)
    * No question-answer or antecedent-consequent phrasing
    * No rhythmic motifs (syncopation, dotted grooves) -> uniform / random ticks
    * No bass archetypes (tonic-fifth, octave, ostinato) -> naive random scale degree walk
    * No percussion micro-patterns (attack->noise->decay) -> naive flat noise/tone pulses
    * No tracker song form (AABB/ABAB) -> random pattern sequence
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from atari_music.constants import (
    DISTORTION_4BIT_POLY,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.generator import KEY_BASE_MIDI, SCALES
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    calculate_ir_binary_size,
    midi_to_note_name,
)


def generate_control_song(seed: int, parameters: Optional[Dict[str, Any]] = None) -> IRSong:
    """Generate a control song without musical archetypes."""
    rng = random.Random(seed)
    params = parameters or {}

    tempo = params.get("tempo", rng.choice([115, 125, 136]))
    key = params.get("key", rng.choice(["C", "D", "E", "F", "G", "A"]))
    mode = params.get("mode", rng.choice(["minor", "major"]))
    root_midi = KEY_BASE_MIDI.get(key, 60)
    scale = SCALES.get(mode, SCALES["minor"])

    frames_per_tick = 4 if tempo <= 130 else 3

    # Naive instruments with flat/uniform envelopes
    instruments = [
        IRInstrument(
            id=0,
            name="Control Lead",
            distortion=DISTORTION_PURE_TONE,
            role="melody",
            envelope=IREnvelope(attack_frames=0, decay_frames=1, sustain_vol=12, release_frames=1),
        ),
        IRInstrument(
            id=1,
            name="Control Bass",
            distortion=DISTORTION_PURE_TONE,
            role="bass",
            envelope=IREnvelope(attack_frames=0, decay_frames=1, sustain_vol=12, release_frames=1),
        ),
        IRInstrument(
            id=2,
            name="Control Accompaniment",
            distortion=DISTORTION_PURE_TONE,
            role="harmony",
            envelope=IREnvelope(attack_frames=0, decay_frames=1, sustain_vol=8, release_frames=1),
        ),
        IRInstrument(
            id=3,
            name="Control Noise",
            distortion=DISTORTION_WHITE_NOISE,
            role="percussion",
            envelope=IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=0, release_frames=1),
        ),
    ]

    # Generate 4 unstructured patterns (32 rows each)
    num_patterns = 4
    patterns: List[IRPattern] = []
    for pat_id in range(num_patterns):
        pat = _build_control_pattern(pat_id, rows=32, root_midi=root_midi, scale=scale, rng=rng)
        patterns.append(pat)

    # Completely random sequence order (no AABB / ABAB structure)
    total_sections = 8  # 8 sections x 32 rows x 4 frames/tick = 1024 frames ≈ 20.48 s
    sequence = [rng.randint(0, num_patterns - 1) for _ in range(total_sections)]

    song = IRSong(
        title=f"Control Baseline #{seed:03d}",
        author="Naive Control Generator",
        tempo_bpm=tempo,
        frames_per_tick=frames_per_tick,
        key=key,
        mode=mode,
        seed=seed,
        instruments=instruments,
        patterns=patterns,
        sequence=sequence,
        uses_16bit_bass=False,
    )

    size_bytes = calculate_ir_binary_size(song)
    if size_bytes > 2048:
        song.sequence = song.sequence[:6]

    return song


def _build_control_pattern(
    pat_id: int,
    rows: int,
    root_midi: int,
    scale: List[int],
    rng: random.Random,
) -> IRPattern:
    """Build pattern with naive random note choices and no archetype structures."""
    tracks: Dict[int, List[IRNote]] = {}

    # Channel 1: Bass - random scale degrees, monotonous duration
    bass_notes: List[IRNote] = []
    step = 4
    for _ in range(rows // step):
        deg = rng.choice(scale)
        midi_note = (root_midi - 24) + deg
        bass_notes.append(
            IRNote(
                pitch=midi_to_note_name(midi_note),
                midi_pitch=midi_note,
                duration=step,
                volume=12,
                instrument_id=1,
                channel_role="bass",
            )
        )
    tracks[1] = bass_notes

    # Channel 2: Random accompaniment stabs
    ch2_notes: List[IRNote] = []
    for _ in range(rows // step):
        if rng.random() < 0.4:
            ch2_notes.append(IRNote(duration=step, is_rest=True, channel_role="harmony"))
        else:
            deg = rng.choice(scale)
            midi_note = (root_midi - 12) + deg
            ch2_notes.append(
                IRNote(
                    pitch=midi_to_note_name(midi_note),
                    midi_pitch=midi_note,
                    duration=step,
                    volume=8,
                    instrument_id=2,
                    channel_role="harmony",
                )
            )
    tracks[2] = ch2_notes

    # Channel 3: Melody - random pitch selection without directional contours or phrasing
    lead_notes: List[IRNote] = []
    r = 0
    while r < rows:
        dur = rng.choice([2, 4])
        if r + dur > rows:
            dur = rows - r
        if rng.random() < 0.2:
            lead_notes.append(IRNote(duration=dur, is_rest=True, channel_role="melody"))
        else:
            deg = rng.choice(scale) + rng.choice([0, 12])
            midi_note = root_midi + deg
            midi_note = max(55, min(84, midi_note))
            lead_notes.append(
                IRNote(
                    pitch=midi_to_note_name(midi_note),
                    midi_pitch=midi_note,
                    duration=dur,
                    volume=rng.choice([11, 14]),
                    instrument_id=0,
                    channel_role="melody",
                )
            )
        r += dur
    tracks[3] = lead_notes

    # Channel 4: Naive random noise pulses (no attack-decay kick/snare pattern)
    ch4_notes: List[IRNote] = []
    step = 2
    for _ in range(rows // step):
        if rng.random() < 0.35:
            ch4_notes.append(IRNote(duration=step, volume=10, instrument_id=3, channel_role="percussion"))
        else:
            ch4_notes.append(IRNote(duration=step, is_rest=True, channel_role="percussion"))
    tracks[4] = ch4_notes

    return IRPattern(id=pat_id, name=f"Control Pat #{pat_id}", rows=rows, tracks=tracks)

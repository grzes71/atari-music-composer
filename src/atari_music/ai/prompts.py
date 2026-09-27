"""Prompt engineering for AI Music Composition on Atari 8-bit POKEY platform.

Strictly instructs the model to act as a composer, generating declarative JSON
without low-level 6502/MADS/POKEY register details.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atari_music.ai.providers.base import CompositionRequest


def build_system_prompt() -> str:
    """Generate system instructions for the LLM composer."""
    return """You are an expert retro game composer creating authentic chiptune music for the 1980s Atari 8-bit computer family (Atari 800 XL / 65 XE) equipped with the POKEY sound chip.

YOUR ROLE:
You are purely the COMPOSER. You describe high-level musical structure, notes, timing, instruments, and macro-structural arrangement.

ABSOLUTE RESTRICTIONS:
1. NEVER output MOS 6502 assembly code, machine code, or MADS directives (.byte, .word, org, icl).
2. NEVER output low-level POKEY hardware register values (AUDF, AUDC, AUDCTL) or RAM addresses.
3. Output MUST be ONLY a single valid, well-formed JSON document adhering strictly to the 'atari-music-composition' schema version 1. No conversational text, no markdown backticks.

POKEY HARDWARE CHARACTERISTICS:
- 4 monophonic audio channels (Channels 0, 1, 2, 3 or 1, 2, 3, 4).
- Authentic semantic instruments:
  * "bright_lead": Pure tone melody voice with crisp punch.
  * "dark_lead" / "soft_pad": Mellow pure tone pad/chords with longer attack.
  * "bass": Distinctive 4-bit polyphonic chiptune bass or 16-bit deep pure bass.
  * "percussion" / "noise": White noise percussion for snares, kicks, and hi-hats.
  * "bell" / "ornament": Pure tone high-register staccato arpeggios and accents.
  * "harmony" / "counter": Counterpoint voice supporting the lead melody.

16-BIT BASS MODE:
- When use_16bit_bass is true, Channel 0 (Ch 1) and Channel 1 (Ch 2) are hardware coupled for a pure 16-bit bass generator.
- All bass notes are written to Channel 0. Channel 1 must remain silent/empty (as it acts as the frequency slave).

MUSICAL ARRANGEMENT & VARIATION PRINCIPLES:
- A great chiptune piece is NOT just a single 8-bar loop repeated 15 times!
- Plan a rich macro-structure using the optional `form_plan`:
  * Core Themes: Primary theme A, contrasting theme B or C.
  * Thematic Variations (e.g. A', B'): Keep recognizable melodic/harmonic motifs of the theme, but alter the cadence/ending, rhythm, register (octave), or ornamentation. Mark pattern with `variation_of: "themeA"`.
  * Transitions & Fills: Short patterns (8 or 16 steps) featuring drum rolls, ascending/descending runs, or momentary pauses before a new section starts. Mark with `role: "fill"` or `role: "transition"`.
  * Texture Changes & Breakdowns: Drop or silence voices (e.g. drop lead for a punchy solo bass & drum groove, or strip drums for a delicate harmonic breakdown) to create dynamic tension before the full theme returns.
  * Dynamic Sequence: Weave themes, variations, fills, and breakdowns into an engaging long-form journey (e.g. Intro -> A -> A_var -> Fill -> B -> A -> Breakdown -> B_var -> Outro).

NOTE NOTATION:
- Pitch names use standard format: 'C4', 'A#2', 'Eb3', 'G-2', 'F#4'.
- Silence / pauses are specified as 'REST' or null.
- Step numbers are 0-indexed integer offsets within each pattern.
- Duration is specified in integer steps (>= 1).
- Volume is an integer between 0 (silent) and 15 (maximum).

JSON DOCUMENT CONTRACT SCHEMA:
{
  "format": "atari-music-composition",
  "version": 1,
  "metadata": {
    "title": "Composition Title",
    "author": "AI Composer",
    "key": "C",
    "mode": "minor",
    "bpm": 120,
    "duration_seconds": 24.0
  },
  "form_plan": {
    "form_type": "rondo_variation",
    "primary_theme_description": "Energetic staccato synth lead over walking bass in C minor.",
    "contrast_theme_description": "Lyrical countermelody in Eb major with half-time drums.",
    "sections": [
      {"section_id": "Intro", "pattern_id": "intro", "role": "intro", "description": "Atmospheric arpeggios building tension"},
      {"section_id": "Theme A", "pattern_id": "themeA", "role": "theme", "description": "Full driving statement of primary theme"},
      {"section_id": "Variation A'", "pattern_id": "themeA_var", "role": "variation", "variation_of": "themeA", "description": "Theme A with syncopated rhythm and altered cadence"},
      {"section_id": "Fill 1", "pattern_id": "fill1", "role": "fill", "description": "16-step snare roll and rising lead flourish"},
      {"section_id": "Theme B", "pattern_id": "themeB", "role": "contrast", "description": "Contrasting lyrical melody in relative major"},
      {"section_id": "Breakdown", "pattern_id": "breakdown", "role": "breakdown", "description": "Stripped texture with solo bass and quiet percussion"},
      {"section_id": "Outro", "pattern_id": "outro", "role": "outro", "description": "Decelerating final cadence"}
    ]
  },
  "hardware": {
    "channels": 4,
    "use_16bit_bass": false
  },
  "instruments": [
    {"id": "lead", "name": "Lead Synth", "character": "bright_lead"},
    {"id": "bass", "name": "Bass Voice", "character": "bass"},
    {"id": "drums", "name": "Drums", "character": "percussion"}
  ],
  "patterns": [
    {
      "id": "intro",
      "length_steps": 16,
      "role": "intro",
      "channels": {
        "0": [{"step": 0, "note": "C4", "instrument": "lead", "duration": 2, "volume": 14}],
        "1": [{"step": 0, "note": "C2", "instrument": "bass", "duration": 4, "volume": 12}],
        "2": [],
        "3": [{"step": 0, "note": "REST", "instrument": "drums", "duration": 2}, {"step": 2, "note": "C4", "instrument": "drums", "duration": 2, "volume": 15}]
      }
    }
  ],
  "sequence": ["intro", "intro"],
  "loop_point": 0,
  "intent": {
    "style": "80s chiptune action",
    "mood": ["driving", "energetic"],
    "structure": "Intro-A-A'-B-Break-A-Outro",
    "composition_notes": "Energetic thematic journey with variations and breakdowns."
  }
}
"""


def build_user_prompt(request: CompositionRequest) -> str:
    """Generate the user prompt conveying desired musical parameters."""
    lines = [
        f"Compose an authentic Atari 8-bit piece with the following musical parameters:",
        f"- Style / Archetype: {request.style}",
        f"- Target Duration: approximately {request.duration_seconds} seconds",
        f"- Channels: {request.channels} channels",
        f"- 16-bit POKEY bass: {'REQUIRED / ENABLED' if request.use_16bit_bass else 'false / standard 8-bit'}",
    ]
    if request.bpm:
        lines.append(f"- Tempo: {request.bpm} BPM")
    if request.key:
        lines.append(f"- Root Key: {request.key}")
    if request.mode:
        lines.append(f"- Musical Mode / Scale: {request.mode}")
    if request.mood:
        lines.append(f"- Mood Keywords: {', '.join(request.mood)}")
    if request.structure:
        lines.append(f"- Form Structure: {request.structure}")
    if request.notes:
        lines.append(f"- Compositional Notes: {request.notes}")

    if request.duration_seconds and request.duration_seconds >= 50:
        bpm = request.bpm or 120
        fpt = 6 if bpm <= 80 else (5 if bpm <= 110 else (4 if bpm <= 145 else 3))
        step_duration = fpt / 50.0
        target_total_steps = int(round(request.duration_seconds / step_duration))
        rec_pat_len = 32
        target_seq_len = int(round(target_total_steps / rec_pat_len))
        lines.extend([
            f"- FULL-LENGTH TRACKER STRUCTURE & VARIATION GUIDELINES (60-120s):",
            f"  * Exact playback duration = (sum of pattern lengths in sequence) * {fpt} / 50.0 seconds.",
            f"  * Target duration {request.duration_seconds}s requires approximately {target_total_steps} total sequence steps.",
            f"  * Plan your musical form first in `form_plan`. Avoid mindless repetition of the same 2-3 patterns!",
            f"  * Create 6 to 9 distinct patterns comprising:",
            f"    - Core themes: e.g. Theme A, Theme B",
            f"    - Thematic variations: e.g. A' (altered melody cadence/rhythm, octave shift), B' (counterpoint change)",
            f"    - Short transition/fill patterns: (8 or 16 steps) with percussion rolls or melodic flourishes between sections",
            f"    - Texture change / Breakdown: at least one section with reduced instrumentation (e.g. solo bass/percussion or solo melody)",
            f"  * Structure an engaging sequence of ~{target_seq_len} pattern references (e.g. Intro -> A -> A' -> Fill -> B -> A -> Breakdown -> B' -> Outro).",
            f"  * Ensure total sequence step count satisfies 60s <= (total_steps * {fpt} / 50.0) <= 120s.",
            f"  * Set metadata.duration_seconds to match the calculated runtime duration.",
        ])

    lines.append("\nReturn ONLY the JSON document conforming to format 'atari-music-composition' version 1.")
    return "\n".join(lines)


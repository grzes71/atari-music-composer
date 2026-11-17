"""Opt-in "rich" prompt profile for AI composition.

The ``classic`` profile (``atari_music.ai.prompts``) stays byte-for-byte unchanged.
This module adds composer craft knowledge on top of it:

* a ground-truth rhythmic grid derived from the real PAL frames-per-tick mapping,
* concrete chiptune/POKEY arranging techniques,
* style idioms per game-music archetype,
* a richer, validated few-shot example (DSL; JSON excerpt derived from it).

All functions are pure and return prompt text sections.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from atari_music.ai.analysis import calculate_bpm_frames_per_tick

if TYPE_CHECKING:
    from atari_music.ai.providers.base import CompositionRequest

PAL_FRAME_RATE = 50.0
PROMPT_PROFILES: Tuple[str, ...] = ("classic", "rich")
MIN_STEPS_PER_BEAT = 2
MAX_STEPS_PER_BEAT = 12
BPM_SEARCH_RANGE = range(40, 251)


# =============================================================================
# Rhythmic grid (ground truth)
# =============================================================================

def step_duration_seconds(bpm: int) -> float:
    """Return the real duration of one sequencer step in seconds at ``bpm``."""
    return calculate_bpm_frames_per_tick(bpm) / PAL_FRAME_RATE


def recommended_steps_per_beat(bpm: int) -> int:
    """Return the integer steps-per-beat closest to the requested tempo."""
    exact = (60.0 / bpm) / step_duration_seconds(bpm)
    return max(MIN_STEPS_PER_BEAT, min(MAX_STEPS_PER_BEAT, int(round(exact))))


def effective_bpm(bpm: int, steps_per_beat: int) -> float:
    """Return the audible tempo when ``steps_per_beat`` steps form one beat."""
    return 60.0 / (steps_per_beat * step_duration_seconds(bpm))


def exact_grid_tempos(steps_per_beat: int) -> List[int]:
    """Return integer BPM values whose step grid is exact for ``steps_per_beat``."""
    result: List[int] = []
    for bpm in BPM_SEARCH_RANGE:
        if abs(effective_bpm(bpm, steps_per_beat) - bpm) < 0.5:
            result.append(bpm)
    return result


def _subdivisions(spb: int) -> List[str]:
    parts = [f"quarter = {spb} steps"]
    if spb % 2 == 0:
        parts.append(f"eighth = {spb // 2}")
    if spb % 4 == 0:
        parts.append(f"sixteenth = {spb // 4}")
    if spb % 3 == 0:
        parts.append(f"eighth-triplet = {spb // 3}")
    if spb % 6 == 0:
        parts.append(f"sixteenth-triplet = {spb // 6}")
    return parts


def build_timing_grid_section(bpm: Optional[int], tempo_grid: str = "describe") -> str:
    """Describe the real step grid so durations line up with the requested tempo."""
    bpm = bpm or 120
    fpt = calculate_bpm_frames_per_tick(bpm)
    step_ms = step_duration_seconds(bpm) * 1000.0
    spb = recommended_steps_per_beat(bpm)
    eff = effective_bpm(bpm, spb)
    eff4 = effective_bpm(bpm, 4)
    lines = [
        "RHYTHMIC GRID (ground truth on PAL 50 Hz - read carefully):",
        f"- At BPM {bpm} the engine plays 1 step = {fpt} frames = {step_ms:.0f} ms.",
        f"- Use {spb} steps per beat: {', '.join(_subdivisions(spb))}.",
        f"  This gives an audible tempo of ~{eff:.0f} BPM. One 4/4 bar = {4 * spb} steps; a 4-bar phrase = {16 * spb} steps.",
        f"- Do NOT assume 4 steps per beat: at this tempo that would actually sound at ~{eff4:.0f} BPM.",
        f"- Keep every channel of a pattern exactly a whole number of bars long ({4 * spb}-step multiples) so all channels stay aligned.",
        "- Put strong accents on beat starts (step 0 of each beat), syncopations between them.",
    ]
    exact = exact_grid_tempos(spb)
    if exact and bpm not in exact:
        lines.append(f"- BPM values with a perfectly exact {spb}-step grid: {', '.join(str(b) for b in exact[:6])}.")
        if tempo_grid == "exact":
            nearest = min(exact, key=lambda b: abs(b - bpm))
            lines.append(
                f"- Exact tempo-grid mode requested: prefer setting metadata BPM to {nearest} so nominal BPM and audible PAL grid match 1:1."
            )
    return "\n".join(lines)


# =============================================================================
# Composer craft
# =============================================================================

CRAFT_SECTION = """COMPOSER CRAFT FOR POKEY CHIPTUNE (techniques, use when they serve the piece):
- MOTIF & DEVELOPMENT: build sections from a short 1-2 bar motif with a memorable rhythm and contour. Develop it instead of inventing unrelated material: literal repeat, sequence (same shape transposed), changed ending (question/answer), rhythmic displacement, inversion, fragmentation in fills.
- PHRASING: think in 2- and 4-bar phrases; end phrases on chord tones, longer notes or rests. Let the melody breathe with short rests.
- HARMONY FIRST: decide an explicit chord progression per section (e.g. i-VI-III-VII, i-iv-V-i, I-V-vi-IV). Bass plays roots/fifths on strong beats; the lead lands on chord tones on strong beats and uses passing/neighbour tones in between.
- CHORD ARPEGGIO: a single channel can imply full chords by cycling chord tones rapidly (1-2 steps per note, e.g. A4 C5 E5 A4 C5 E5 ...). Classic Atari/C64 technique; keep it quieter than the lead.
- ECHO VOICE: copy the lead onto a free channel delayed by 2-3 steps at volume 4-6 lower for space and width.
- BASS PATTERNS: octave bouncing (A2 A3 A2 A3), root-fifth, walking lines into the next chord, syncopated pushes before the downbeat.
- PERCUSSION ON ONE NOISE CHANNEL: vary pitch per hit - low = loose/kick-like hit, mid = snare, high = closed hi-hat. Build a steady groove (kick on beats 1/3, snare on 2/4, hats on off-beats) and add a fill every 4 or 8 bars.
- DYNAMICS: use per-note volume accents (DSL `note/dur:vol`, JSON `volume`) - accent downbeats and melodic peaks, softer verses, louder chorus, drop channels out for breakdowns.
- CONTRAST BETWEEN SECTIONS: change at least two of register, rhythm density, harmony, active channels or dynamics between A and B.
- REGISTER: lead mostly C4-C6, bass C2-C3, arpeggio between them; avoid parallel unisons between lead and arpeggio.
- REUSE WISELY: repetition makes loops catchy, but every 4-8 bars something should change (variation pattern, fill, new counter-line)."""


def build_craft_section() -> str:
    """Return concrete composer-craft guidance."""
    return CRAFT_SECTION


# =============================================================================
# Style idioms
# =============================================================================

STYLE_IDIOMS: Dict[str, str] = {
    "title": "Title/menu theme: confident memorable hook, A-B-A' loop, medium-fast tempo, full texture (bass + arpeggio + lead + light drums), major or dorian/aeolian minor.",
    "menu": "Menu loop: relaxed, light texture, short seamless 4-8 bar loop, gentle arpeggios, sparse percussion.",
    "action": "Action/level: driving bass in eighths, syncopated lead, constant hi-hat groove, minor key, fills every 4 bars, energetic dynamics.",
    "boss": "Boss fight: fast tempo, chromatic or phrygian tension, ostinato bass, aggressive accents, short repeated riffs, tritone/minor-second colour, dense drums.",
    "dungeon": "Dungeon/exploration: slow-medium tempo, sparse texture, low drone or slow bass, modal minor (dorian/aeolian/phrygian), long notes, silences, echo voice.",
    "ambient": "Ambient: very sparse, long sustained notes, slow arpeggios, little or no percussion, dynamic swells.",
    "victory": "Victory/fanfare: major key, ascending arpeggio fanfare figures, short (4-8 bars), strong final cadence on the tonic.",
    "game_over": "Game over: short, slow, descending minor line ending on a long tonic, minimal percussion.",
    "puzzle": "Puzzle: playful staccato lead, bouncy bass, light percussion, major or mixolydian, clear repeated motif.",
}


def build_style_idioms_section(style: Optional[str], mood: Optional[Sequence[str]] = None) -> str:
    """Return style idioms matching ``style``/``mood`` keywords (general advice otherwise)."""
    text = " ".join([style or "", *(mood or [])]).lower().replace("-", "_").replace(" ", "_")
    matched = [hint for key, hint in STYLE_IDIOMS.items() if key in text]
    if not matched:
        matched = ["No specific archetype matched: derive tempo feel, texture density and form from the style and mood words; keep a clear hook and groove."]
    return "STYLE IDIOMS:\n" + "\n".join(f"- {m}" for m in matched)


# =============================================================================
# Rich few-shot example (validated in tests)
# =============================================================================

RICH_DSL_EXAMPLE = """TITLE "Neon Citadel"
KEY A
MODE MINOR
BPM 125
CHANNELS 4
LOOP 0

# 125 BPM -> 6 steps per beat, 24 steps per bar. A = Am | F, B = Dm | E.
SEQUENCE A A B A

[PATTERN A]
CH1 BASS V12
A2/3 A3/3 A2/3 A3/3 A2/3 A3/3 E2/3 G2/3
F2/3 F3/3 F2/3 F3/3 F2/3 F3/3 C3/3 E3/3

CH2 ARP V7
A4/2 C5/2 E5/2 A4/2 C5/2 E5/2 A4/2 C5/2 E5/2 A4/2 C5/2 E5/2
F4/2 A4/2 C5/2 F4/2 A4/2 C5/2 F4/2 A4/2 C5/2 F4/2 A4/2 C5/2

CH3 LEAD V13
E5/6:15 D5/3 C5/3 B4/3 C5/3 A4/6
R/3 A4/3 C5/3 F5/6:15 E5/3 C5/6

CH4 PERC V9
C2/3:12 C6/3:5 G4/3:11 C6/3:5 C2/3:12 C6/3:5 G4/3:11 C6/3:5
C2/3:12 C6/3:5 G4/3:11 C6/3:5 C2/3:12 C6/3:5 G4/3:11 C6/3:5

[PATTERN B]
CH1 BASS V12
D2/3 D3/3 D2/3 D3/3 D2/3 D3/3 A2/3 C3/3
E2/3 E3/3 E2/3 E3/3 E2/3 E3/3 G#2/3 B2/3

# CH2 becomes an echo of the lead: 3 steps late, quieter.
CH2 ARP V7
R/3 D5/6 C5/3 B4/3 A4/3 B4/3 F4/6
E4/3 G#4/3 B4/3 E5/9 R/3

# Motif sequenced one step down, answered by a rising E-major arpeggio.
CH3 LEAD V13
D5/6:15 C5/3 B4/3 A4/3 B4/3 F4/6
E4/3 G#4/3 B4/3 E5/9:15 R/6

CH4 PERC V9
C2/3:12 C6/3:5 G4/3:11 C6/3:5 C2/3:12 C6/3:5 G4/3:11 C6/3:5
C2/3:12 C6/3:5 G4/3:11 C6/3:5 G4/2:9 G4/2:10 G4/2:11 G4/2:12 G4/2:13 G4/2:15
"""

DSL_INSTRUMENT_DIRECTIVE_HELP = """5. Optional instrument shaping (header area, before SEQUENCE):
   INSTRUMENT <id> [character=<role>] [att=<frames>] [dec=<frames>] [sus=<0..15>] [rel=<frames>]
   e.g. INSTRUMENT arp character=bell dec=3 sus=4 rel=1   (short plucky arpeggio)
   Use the same <id> in channel headers (CH2 ARP V7). Omit it to use defaults inferred from the id name."""


@lru_cache(maxsize=1)
def rich_json_example() -> str:
    """Return a compact JSON excerpt (pattern A) derived from ``RICH_DSL_EXAMPLE``."""
    from atari_music.ai.dsl import parse_music_dsl

    doc = parse_music_dsl(RICH_DSL_EXAMPLE, validate=True)
    data = doc.model_dump(mode="json", exclude_none=True)
    data["patterns"] = [p for p in data["patterns"] if p["id"] == "A"]
    data["sequence"] = ["A", "A"]
    data["loop_point"] = 0
    data.pop("form_plan", None)
    data.pop("intent", None)
    # One note object per line keeps the excerpt readable and compact.
    pattern = data.pop("patterns")[0]
    head = json.dumps(data, separators=(", ", ": "))
    ch_lines = []
    for ch, notes in pattern["channels"].items():
        rows = ",\n        ".join(json.dumps(n, separators=(",", ":")) for n in notes)
        ch_lines.append(f'      "{ch}": [\n        {rows}\n      ]')
    pat_meta = {k: v for k, v in pattern.items() if k != "channels"}
    pat_json = json.dumps(pat_meta, separators=(", ", ": "))[:-1]
    patterns_txt = f'  "patterns": [\n    {pat_json}, "channels": {{\n' + ",\n".join(ch_lines) + "\n    }}\n  ]"
    return head[:-1] + ",\n" + patterns_txt + "\n}"


# =============================================================================
# Assembled rich prompts
# =============================================================================

def build_rich_system_prompt(fmt: str = "json", dsl_version: str = "v1.1") -> str:
    """Return classic system prompt (unchanged rules) extended with craft knowledge."""
    from atari_music.ai.prompts import build_dsl_system_prompt, build_system_prompt

    if fmt == "dsl":
        base = build_dsl_system_prompt(version=dsl_version)
        example = (
            "RICH EXAMPLE (study the techniques - motif, sequence, arpeggio, echo, groove, fill, accents - do not copy the notes):\n"
            + RICH_DSL_EXAMPLE
        )
        extra = [DSL_INSTRUMENT_DIRECTIVE_HELP, build_craft_section(), example]
    else:
        base = build_system_prompt()
        example = (
            "RICH EXAMPLE EXCERPT (one pattern; study arpeggio, octave bass, motif, accents and drum groove - do not copy the notes):\n"
            + rich_json_example()
        )
        extra = [build_craft_section(), example]
    return base.rstrip() + "\n\n" + "\n\n".join(extra) + "\n"


def format_musical_brief_section(brief: Dict[str, object]) -> str:
    """Render a pre-composition ``MusicalBrief`` dict as prompt instructions."""
    return (
        "COMPOSITION BRIEF (follow this harmonic, motivic, and structural plan):\n"
        + json.dumps(brief, indent=2)
    )


def build_brief_system_prompt() -> str:
    """System prompt for Phase 4 pre-composition planning (`MusicalBrief` JSON)."""
    return (
        "You are an Atari 8-bit POKEY chiptune music architect. "
        "Before writing notes, produce ONLY a compact JSON planning brief matching the MusicalBrief schema "
        "(key, mode, effective_bpm, form, sections[{id, bars, chords, texture, dynamics}], "
        "motif{rhythm, contour, description}, channel_roles{1..4}). "
        "Output raw JSON only without markdown fences."
    )


def build_brief_user_prompt(request: "CompositionRequest") -> str:
    """User prompt for Phase 4 pre-composition planning."""
    bpm = request.bpm or 120
    spb = recommended_steps_per_beat(bpm)
    lines = [
        f"Plan an Atari 8-bit POKEY composition for style '{request.style}':",
        f"- Duration: ~{request.duration_seconds}s, Tempo: {bpm} BPM ({spb} steps/beat, {4 * spb} steps/bar)",
        f"- Key: {request.key or 'choose fitting key'}, Mode: {request.mode or 'choose fitting mode'}",
        f"- Mood: {', '.join(request.mood) if request.mood else 'energetic'}",
        f"- Structure: {request.structure or 'A-A-B-A'}",
        f"- 16-bit bass: {'enabled (CH1 master, CH2 empty)' if request.use_16bit_bass else 'standard 8-bit'}",
    ]
    if request.notes:
        lines.append(f"- Notes: {request.notes}")
    lines.append("Return ONLY the MusicalBrief JSON object.")
    return "\n".join(lines)


def build_default_musical_brief(request: "CompositionRequest") -> Dict[str, object]:
    """Build a deterministic ``MusicalBrief`` dictionary (used by mock provider or fallback)."""
    from atari_music.ai.schema import MusicalBrief, MusicalBriefMotif, MusicalBriefSection

    bpm = request.bpm or 125
    spb = recommended_steps_per_beat(bpm)
    half = max(1, spb // 2)
    key = request.key or "A"
    mode = request.mode or "minor"
    if request.use_16bit_bass:
        roles = {
            "1": "16-bit bass master (roots, fifths, octave leaps)",
            "2": "SILENT hardware 16-bit frequency slave (must remain empty)",
            "3": "lead melody with dynamic accents and chord arpeggios",
            "4": "percussion groove (kick/snare/hihat + turnaround fill)",
        }
    else:
        roles = {
            "1": "bass (octave bounce on roots/fifths)",
            "2": "chord arpeggio in section A, delayed echo voice in section B",
            "3": "lead melody with dynamic accents",
            "4": "percussion groove (kick/snare/hihat + 4-bar fill)",
        }
    brief = MusicalBrief(
        key=key,
        mode=mode,
        effective_bpm=int(round(effective_bpm(bpm, spb))),
        form=["A", "A", "B", "A"],
        sections=[
            MusicalBriefSection(
                id="A",
                bars=2,
                chords=[f"{key}m", "F", "C", "E"] if "min" in mode.lower() else [key, "F", "G", key],
                texture="full groove (bass + arpeggio + lead + drums)",
                dynamics="mf with accented downbeats",
            ),
            MusicalBriefSection(
                id="B",
                bars=2,
                chords=["Dm", "Am", "E", f"{key}m"],
                texture="contrasting section with delayed lead echo and drum fill at end",
                dynamics="mp building to f",
            ),
        ],
        motif=MusicalBriefMotif(
            rhythm=f"{spb}-{half}-{half}-{spb}",
            contour="leap up to 5th then stepwise descent to root",
            description="Stated in A on tonic, sequenced a step lower in B with cadence fill",
        ),
        channel_roles=roles,
    )
    return brief.model_dump(mode="json")


def build_rich_user_prompt(request: "CompositionRequest") -> str:
    """Return classic user prompt extended with grid, style idioms and a planning checklist."""
    from atari_music.ai.prompts import build_dsl_user_prompt, build_user_prompt

    is_dsl = getattr(request, "format", "json") == "dsl"
    base = build_dsl_user_prompt(request) if is_dsl else build_user_prompt(request)
    body, _, closing = base.rpartition("\n\n")
    tempo_grid = getattr(request, "tempo_grid", "describe")
    sections = [
        build_timing_grid_section(request.bpm, tempo_grid=tempo_grid),
        build_style_idioms_section(request.style, request.mood),
    ]
    brief = getattr(request, "musical_brief", None)
    if brief:
        sections.append(format_musical_brief_section(brief))
    else:
        sections.append(
            "BEFORE WRITING NOTES, decide silently: (1) chord progression per section, "
            "(2) the main motif rhythm and contour, (3) role of each channel per section, "
            "(4) what changes between sections. Then write the piece so these decisions are audible."
        )
    return body + "\n\n" + "\n\n".join(sections) + "\n\n" + closing

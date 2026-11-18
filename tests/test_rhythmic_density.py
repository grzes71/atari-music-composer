"""Regression tests for opt-in --rhythmic-density analysis, prompts, critique, and CLI."""

from __future__ import annotations

import statistics

from click.testing import CliRunner
import pytest

from atari_music.ai.analysis import analyze_composition
from atari_music.ai.client import generate_composition_with_retry
from atari_music.ai.composition import infer_character_from_id, map_instrument_character
from atari_music.ai.critique import MusicalCritique
from atari_music.ai.dsl import _infer_character_from_id, parse_music_dsl
from atari_music.constants import DISTORTION_PURE_TONE, DISTORTION_WHITE_NOISE
from atari_music.music_ir import ChannelRole
from atari_music.ai.prompt_library import (
    build_rhythmic_density_section,
    recommended_steps_per_beat,
)
from atari_music.ai.prompts import get_system_prompt, get_user_prompt
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)
from atari_music.cli import cli
from scripts.benchmark_prompts import format_markdown_table, run_profile_benchmark

pytestmark = pytest.mark.core

SHADOW_PROTOCOL_DSL = """TITLE "Shadow Protocol Repro"
KEY E
MODE MINOR
BPM 140
CHANNELS 4
LOOP 1

SEQUENCE INTRO A B A

[PATTERN INTRO length=80 role=intro]
CH1 BASS V12
E2/5 E2/5 E2/5 E2/5 E2/5 E2/5 E2/5 E2/5
E2/5 E2/5 E2/5 E2/5 E2/5 E2/5 E2/5 E2/5
CH2 ARP V7
E4/2 G4/2 B4/2 E5/2 B4/2 G4/2 E4/2 G4/2 B4/2 E5/2
E4/2 G4/2 B4/2 E5/2 B4/2 G4/2 E4/2 G4/2 B4/2 E5/2
E4/2 G4/2 B4/2 E5/2 B4/2 G4/2 E4/2 G4/2 B4/2 E5/2
E4/2 G4/2 B4/2 E5/2 B4/2 G4/2 E4/2 G4/2 B4/2 E5/2
CH3 LEAD V13
R/20 R/20 R/20 R/20
CH4 PERC V9
C2/5 C6/5 G4/5 C6/5 C2/5 C6/5 G4/5 C6/5
C2/5 C6/5 G4/5 C6/5 C2/5 C6/5 G4/5 C6/5

[PATTERN A length=40 role=theme]
CH1 BASS V12
E2/5 E3/5 B2/5 E2/5 E2/5 E3/5 B2/5 E2/5
CH2 ARP V7
E4/2 G4/2 B4/2 E5/2 B4/2 E4/2 G4/2 B4/2 E5/2 B4/2
E4/2 G4/2 B4/2 E5/2 B4/2 E4/2 G4/2 B4/2 E5/2 B4/2
CH3 LEAD V13
B4/6:14 C5/5:12 E5/7:15 D5/5:13 B4/6:12 G4/6:11 E4/5:14
CH4 PERC V9
C2/5:12 C6/5:6 G4/5:11 C6/5:6 C2/5:12 C6/5:6 G4/5:11 C6/5:6

[PATTERN B length=40 role=contrast]
CH1 BASS V12
C2/5 C3/5 G2/5 C2/5 D2/5 D3/5 A2/5 D2/5
CH2 ARP V7
C4/2 E4/2 G4/2 C5/2 G4/2 C4/2 E4/2 G4/2 C5/2 G4/2
D4/2 F#4/2 A4/2 D5/2 A4/2 D4/2 F#4/2 A4/2 D5/2 A4/2
CH3 LEAD V13
G5/6:15 F#5/5:13 E5/7:14 D5/5:12 C5/6:11 B4/5:13 A4/6:14
CH4 PERC V9
C2/5:12 C6/5:6 G4/5:11 C6/5:6 C2/5:12 C6/5:6 G4/5:11 C6/5:6
"""

FAST_REVISED_DSL = """TITLE "Shadow Protocol Fixed"
KEY E
MODE MINOR
BPM 140
CHANNELS 4
LOOP 1

SEQUENCE INTRO A B A

[PATTERN INTRO length=20 role=intro]
CH1 BASS V12
E2/3 E2/2 E3/3 B2/2 E2/3 E2/2 E3/3 B2/2
CH2 ARP V7
E4/2 G4/2 B4/2 E5/2 B4/2 E4/2 G4/2 B4/2 E5/2 B4/2
CH3 LEAD V13
R/5 E5/3:15 G5/2:13 F#5/3:14 E5/2:12 B4/3:13 E5/2:14
CH4 PERC V9
C2/3:12 C6/2:6 G4/3:11 C6/2:6 C2/3:12 C6/2:6 G4/3:11 C6/2:6

[PATTERN A length=40 role=theme]
CH1 BASS V12
E2/3 E3/2 E2/3 B2/2 E2/3 E3/2 E2/3 B2/2
E2/3 E3/2 E2/3 B2/2 G2/3 B2/2 D3/3 B2/2
CH2 ARP V7
E4/2 G4/2 B4/2 E5/2 B4/2 E4/2 G4/2 B4/2 E5/2 B4/2
E4/2 G4/2 B4/2 E5/2 B4/2 E4/2 G4/2 B4/2 E5/2 B4/2
CH3 LEAD V13
B4/2:14 E5/3:15 G5/2:14 F#5/3:13 E5/2:12 D5/3:14 B4/2:12 E5/3:15
G5/2:15 A5/3:14 G5/2:13 F#5/3:12 E5/2:11 D5/3:13 B4/2:12 E5/3:15
CH4 PERC V9
C2/3:12 C6/2:6 G4/3:11 C6/2:6 C2/3:12 C6/2:6 G4/3:11 C6/2:6
C2/3:12 C6/2:6 G4/3:11 C6/2:6 G4/2:9 G4/2:11 G4/2:13 G4/2:15

[PATTERN B length=40 role=contrast]
CH1 BASS V12
C2/3 C3/2 G2/3 C2/2 D2/3 D3/2 A2/3 D2/2
C2/3 C3/2 G2/3 C2/2 B1/3 B2/2 F#2/3 B2/2
CH2 ARP V7
C4/2 E4/2 G4/2 C5/2 G4/2 D4/2 F#4/2 A4/2 D5/2 A4/2
C4/2 E4/2 G4/2 C5/2 G4/2 B3/2 D#4/2 F#4/2 B4/2 F#4/2
CH3 LEAD V13
C5/2:13 E5/3:14 G5/2:15 F#5/3:14 D5/2:12 B4/3:13 A4/2:11 D5/3:14
C5/2:13 B4/3:12 G4/2:11 A4/3:13 B4/2:14 D5/3:15 F#5/2:14 E5/3:15
CH4 PERC V9
C2/3:12 C6/2:6 G4/3:11 C6/2:6 C2/3:12 C6/2:6 G4/3:11 C6/2:6
C2/3:12 C6/2:6 G4/3:11 C6/2:6 B4/2:10 G4/2:12 C6/2:14 G4/2:15
"""


def test_shadow_protocol_detection_not_masked_by_arpeggio() -> None:
    doc = parse_music_dsl(SHADOW_PROTOCOL_DSL, validate=True)
    report = analyze_composition(doc)
    rhythm = report.rhythm

    # Arpeggio on CH2 is fast (dur=2, 12.5 notes/s), while lead on CH3 is slow (5-7 steps)
    lead = rhythm.role_rhythm["lead"]
    arp = rhythm.role_rhythm["arpeggio"]
    assert rhythm.lead_channel == 3
    assert arp.avg_note_steps == pytest.approx(2.0)
    assert arp.notes_per_sec > 6.0

    assert 5.0 <= lead.avg_note_steps <= 7.0
    assert lead.median_note_steps >= 5.0
    assert lead.short_note_ratio == 0.0
    assert lead.first_onset_step == 80
    assert lead.longest_silence_steps == 80

    # INTRO diagnostics: CH1/CH2 start at step 0, but lead melody waits 80 steps (6.4s)
    assert rhythm.intro_melody.has_explicit_intro is True
    assert rhythm.intro_melody.intro_pattern_ids == ("INTRO",)
    assert rhythm.intro_melody.intro_total_steps == 80
    assert rhythm.intro_melody.first_melody_onset_step_in_intro is None
    assert rhythm.intro_melody.intro_melody_delay_steps == 80
    assert rhythm.intro_melody.intro_melody_delay_seconds == pytest.approx(6.4)
    assert rhythm.intro_melody.intro_melody_rest_ratio == 1.0

    critique = MusicalCritique.from_doc(doc, rhythmic_density="high")
    assert critique.metrics_summary["density_penalty"] > 25.0
    joined = "\n".join(critique.findings)
    assert "80 steps" in joined
    assert "6.40s" in joined
    assert "avg=" in joined
    assert "notes/s" in joined


def test_semantic_role_resolution_effective_inheritance_and_mid_channel_switch() -> None:
    # Case 1: fast 1-2 step melody on CH1 (NOT CH3!), multi-role catalog arp on CH3,
    # and event with empty instrument inheriting active channel instrument.
    doc = AICompositionDoc.model_construct(
        format="atari-music-composition",
        version=1,
        metadata=AICompositionMetadata(title="Roles & Inheritance", key="A", mode="minor", bpm=140),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=False),
        instruments=[
            AIInstrumentDef(id="inst_lead", name="Fast Lead", character="bright_lead", catalog_id="lead_attack_bite"),
            AIInstrumentDef(id="inst_arp", name="Bell Arp", character="bell", catalog_id="ornament_bell_arp"),
            AIInstrumentDef(id="inst_bass", name="Bass", character="bass"),
        ],
        patterns=[
            AIPatternDef.model_construct(
                id="A",
                length_steps=8,
                channels={
                    # CH1 plays fast 1-2 step lead; second event intentionally leaves instrument empty ("")
                    "0": [
                        AIPatternChannelEvent.model_construct(step=0, note="A4", instrument="inst_lead", duration=1, volume=14),
                        AIPatternChannelEvent.model_construct(step=1, note="C5", instrument="", duration=2, volume=14),
                        AIPatternChannelEvent.model_construct(step=3, note="E5", instrument="inst_lead", duration=1, volume=14),
                    ],
                    # CH3 holds multi-role ornament_bell_arp (intended_roles=["harmony", "melody"], family="harmony") -> arpeggio
                    "2": [
                        AIPatternChannelEvent.model_construct(step=0, note="A3", instrument="inst_arp", duration=6, volume=8),
                    ],
                },
            ),
            AIPatternDef.model_construct(
                id="B",
                length_steps=8,
                channels={
                    # Mid-sequence switch on CH1 from inst_lead -> inst_bass
                    "0": [
                        AIPatternChannelEvent.model_construct(step=0, note="A2", instrument="inst_bass", duration=4, volume=12),
                        AIPatternChannelEvent.model_construct(step=4, note="E2", instrument="", duration=4, volume=12),
                    ],
                },
            ),
        ],
        sequence=["A", "B"],
        loop_point=0,
    )
    rep = analyze_composition(doc)
    assert rep.rhythm.lead_channel == 1
    assert rep.rhythm.role_rhythm["lead"].notes_count == 3  # includes empty-instrument step=1 note!
    assert rep.rhythm.role_rhythm["arpeggio"].notes_count == 1  # not misclassified despite 6-step hold!
    assert rep.rhythm.role_rhythm["bass"].notes_count == 2  # step=4 inherited inst_bass from step=0!
    assert set(rep.rhythm.channel_rhythm[1].roles_present) == {"bass", "lead"}


def test_metric_precision_overlaps_ioi_empty_single_and_repeated_patterns() -> None:
    # Overlapping notes on CH1 (steps 0..4 and 2..6), regular spacing IOIs on CH2, empty CH3, single note CH4
    doc = AICompositionDoc.model_construct(
        format="atari-music-composition",
        version=1,
        metadata=AICompositionMetadata(title="Precision Metrics", key="C", mode="major", bpm=125),
        hardware=AIHardwareConfig(channels=4, use_16bit_bass=False),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
            AIInstrumentDef(id="harm", name="Harm", character="harmony"),
            AIInstrumentDef(id="perc", name="Perc", character="percussion"),
        ],
        patterns=[
            AIPatternDef.model_construct(
                id="P1",
                length_steps=16,
                channels={
                    # Overlapping notes [0..4) and [2..6): union active_steps = 6 (NOT 8!)
                    "0": [
                        AIPatternChannelEvent.model_construct(step=0, note="C5", instrument="lead", duration=4, volume=12),
                        AIPatternChannelEvent.model_construct(step=2, note="E5", instrument="lead", duration=4, volume=12),
                    ],
                    # Onsets at steps 0, 3, 6, 9, 12 with varied durations -> IOIs are all 3 -> variation == 0.0!
                    "1": [
                        AIPatternChannelEvent.model_construct(step=0, note="C4", instrument="harm", duration=1, volume=10),
                        AIPatternChannelEvent.model_construct(step=3, note="E4", instrument="harm", duration=3, volume=10),
                        AIPatternChannelEvent.model_construct(step=6, note="G4", instrument="harm", duration=2, volume=10),
                        AIPatternChannelEvent.model_construct(step=9, note="C5", instrument="harm", duration=3, volume=10),
                        AIPatternChannelEvent.model_construct(step=12, note="G4", instrument="harm", duration=2, volume=10),
                    ],
                    # CH4 single note -> onset_interval_mean == 0.0, onset_interval_variation == 0.0
                    "3": [
                        AIPatternChannelEvent.model_construct(step=2, note="C2", instrument="perc", duration=2, volume=12),
                    ],
                },
            ),
            AIPatternDef.model_construct(
                id="P2",
                length_steps=16,
                channels={
                    # Rests across boundary: P1 ch1 stops at step 6 (10 silent at end) + P2 starts silent 16 steps = 26 steps!
                },
            ),
        ],
        sequence=["P1", "P2", "P2"],
        loop_point=0,
    )
    rep = analyze_composition(doc)
    ch1 = rep.rhythm.channel_rhythm[1]
    assert ch1.active_steps == 6
    assert 0.0 <= ch1.rest_ratio <= 1.0
    assert ch1.longest_silence_steps == 42  # 10 trailing in P1 + 16 in P2 + 16 in P2
    assert ch1.onset_interval_mean == pytest.approx(2.0)

    ch2 = rep.rhythm.channel_rhythm[2]
    assert ch2.onset_interval_mean == pytest.approx(3.0)
    assert ch2.onset_interval_variation == 0.0

    ch3 = rep.rhythm.channel_rhythm[3]
    assert ch3.notes_count == 0
    assert ch3.longest_silence_steps == 48
    assert ch3.first_onset_step is None

    ch4 = rep.rhythm.channel_rhythm[4]
    assert ch4.notes_count == 1
    assert ch4.onset_interval_mean == 0.0
    assert ch4.onset_interval_variation == 0.0


def test_regular_pulse_not_penalized_and_density_penalty_monotonicity() -> None:
    # Steady 2-step lead notes (perfectly regular IOIs -> onset_interval_variation == 0.0)
    regular_dsl = """TITLE "Regular Pulse"
KEY A
MODE MINOR
BPM 125
CHANNELS 4

SEQUENCE A A

[PATTERN A length=24 role=theme]
CH1 BASS V12
A2/3 A3/3 A2/3 A3/3 A2/3 A3/3 A2/3 A3/3
CH3 LEAD V14
A4/2 C5/2 E5/2 A5/2 G5/2 E5/2 C5/2 A4/2 A4/2 C5/2 E5/2 G5/2
CH4 PERC V10
C2/3 C6/3 G4/3 C6/3 C2/3 C6/3 G4/3 C6/3
"""
    reg_doc = parse_music_dsl(regular_dsl, validate=True)
    reg_rep = analyze_composition(reg_doc)
    assert reg_rep.rhythm.role_rhythm["lead"].onset_interval_variation == 0.0
    reg_critique = MusicalCritique.from_doc(reg_doc, rhythmic_density="high")
    assert reg_critique.metrics_summary["density_penalty"] == 0.0

    # Monotonicity of density_penalty: Shadow (slow+delayed) -> Partial (early slow) -> Fixed (fast+early)
    shadow_doc = parse_music_dsl(SHADOW_PROTOCOL_DSL, validate=True)
    early_slow_doc = parse_music_dsl(
        SHADOW_PROTOCOL_DSL.replace("CH3 LEAD V13\nR/20 R/20 R/20 R/20", "CH3 LEAD V13\nE5/10 B4/10 E5/10 G5/10 E5/10 B4/10 E5/10 G5/10"),
        validate=True,
    )
    fast_doc = parse_music_dsl(FAST_REVISED_DSL, validate=True)

    pen_shadow = MusicalCritique.from_doc(shadow_doc, rhythmic_density="high").metrics_summary["density_penalty"]
    pen_mid = MusicalCritique.from_doc(early_slow_doc, rhythmic_density="high").metrics_summary["density_penalty"]
    pen_fast = MusicalCritique.from_doc(fast_doc, rhythmic_density="high").metrics_summary["density_penalty"]
    assert pen_shadow > pen_mid > pen_fast
    assert pen_fast == 0.0


def test_quality_pass_promotes_faster_revision_under_rhythmic_density() -> None:
    class _TwoStageDslProvider:
        provider_name = "stub_density"

        def __init__(self) -> None:
            self.calls = 0
            self.feedbacks: list[str | None] = []

        def generate_composition_dsl(self, request, feedback=None, previous_dsl=None) -> str:
            self.calls += 1
            self.feedbacks.append(feedback)
            if self.calls == 1:
                return SHADOW_PROTOCOL_DSL
            return FAST_REVISED_DSL

    prov = _TwoStageDslProvider()
    req = CompositionRequest(
        style="action",
        bpm=140,
        duration_seconds=30,
        format="dsl",
        prompt_profile="rich",
        rhythmic_density="high",
        quality_passes=1,
    )
    doc, history = generate_composition_with_retry(req, prov, return_history=True)
    assert prov.calls == 2
    assert prov.feedbacks[1] is not None
    assert "INTRO melody delay" in prov.feedbacks[1]
    assert "Lead melody" in prov.feedbacks[1]
    assert doc.metadata.title == "Shadow Protocol Fixed"
    assert history[-1].critique_score > history[0].critique_score


def test_low_profile_does_not_penalize_ambient_or_dungeon() -> None:
    ambient_dsl = """TITLE "Cavern Mist"
KEY D
MODE DORIAN
BPM 90
CHANNELS 3

SEQUENCE INTRO A

[PATTERN INTRO length=64 role=intro]
CH1 BASS V10
D2/32 A1/32
CH3 LEAD V11
R/48 D4/16

[PATTERN A length=64 role=theme]
CH1 BASS V10
D2/32 F2/32
CH3 LEAD V11
A4/16 R/8 F4/16 R/8 D4/16
"""
    amb_doc = parse_music_dsl(ambient_dsl, validate=True)
    c_none = MusicalCritique.from_doc(amb_doc, rhythmic_density=None)
    c_low = MusicalCritique.from_doc(amb_doc, rhythmic_density="low")
    assert c_low.metrics_summary["density_penalty"] == 0.0
    assert c_low.score == c_none.score
    assert c_low.findings == c_none.findings


def test_rhythmic_theory_grid_descriptions_in_prompts() -> None:
    assert recommended_steps_per_beat(140) == 5
    sec_140 = build_rhythmic_density_section(140, "high")
    assert "5 steps/beat" in sec_140
    assert "approximation" in sec_140.lower()
    assert "2+3" in sec_140

    assert recommended_steps_per_beat(125) == 6
    sec_125 = build_rhythmic_density_section(125, "high")
    assert "eighth-triplet" in sec_125
    assert "1/6 beat" in sec_125

    assert recommended_steps_per_beat(250) == 4
    sec_250 = build_rhythmic_density_section(250, "high")
    assert "exact sixteenth" in sec_250
    assert "187.5" not in sec_250


def test_backwards_compatibility_and_cli_and_benchmark() -> None:
    for profile in ("classic", "rich"):
        for fmt in ("json", "dsl"):
            r_old = CompositionRequest(style="action", bpm=140, format=fmt, prompt_profile=profile)
            r_none = CompositionRequest(
                style="action", bpm=140, format=fmt, prompt_profile=profile, rhythmic_density=None
            )
            assert get_system_prompt(r_old) == get_system_prompt(r_none)
            assert get_user_prompt(r_old) == get_user_prompt(r_none)

    shadow_doc = parse_music_dsl(SHADOW_PROTOCOL_DSL, validate=True)
    c_default = MusicalCritique.from_doc(shadow_doc)
    c_none = MusicalCritique.from_doc(shadow_doc, rhythmic_density=None)
    assert c_default.score == c_none.score
    assert c_default.findings == c_none.findings

    runner = CliRunner()
    help_res = runner.invoke(cli, ["ai-compose", "--help"])
    assert help_res.exit_code == 0
    assert "--rhythmic-density" in help_res.output
    assert "--energy" not in help_res.output

    bad_energy = runner.invoke(cli, ["ai-compose", "--energy", "high"])
    assert bad_energy.exit_code != 0

    bench = run_profile_benchmark(
        "rich",
        "mock",
        runs=1,
        style="action",
        bpm=140,
        fmt="dsl",
        rhythmic_density="high",
    )
    assert "lead" in bench["role_means"]
    md = format_markdown_table([bench])
    assert "| Profile | Role | Notes/s |" in md
    assert "| rich+dens:high | lead |" in md


def test_perc_character_and_id_classification_and_dsl_parity() -> None:
    # Unified alias resolution between DSL parser and map_instrument_character
    assert infer_character_from_id("perc") == "percussion"
    assert _infer_character_from_id("perc") == "percussion"
    assert infer_character_from_id("arp") == "bell"
    assert _infer_character_from_id("arp") == "bell"

    perc_char_inst = AIInstrumentDef(id="snare_hit", name="Snare", character="perc")
    dist_char, _env_char, role_char = map_instrument_character(perc_char_inst)
    assert role_char == ChannelRole.PERCUSSION
    assert dist_char == DISTORTION_WHITE_NOISE

    perc_id_inst = AIInstrumentDef(id="perc", name="Perc", character="perc")
    dist_id, _env_id, role_id = map_instrument_character(perc_id_inst)
    assert role_id == ChannelRole.PERCUSSION
    assert dist_id == DISTORTION_WHITE_NOISE

    arp_char_inst = AIInstrumentDef(id="chord_arp", name="Arp", character="arp")
    dist_arp, _env_arp, role_arp = map_instrument_character(arp_char_inst)
    assert role_arp == ChannelRole.HARMONY
    assert dist_arp == DISTORTION_PURE_TONE

    dsl_text = """TITLE "Perc Regression"
KEY E
MODE MINOR
BPM 140
CHANNELS 4
LOOP 0

SEQUENCE A

INSTRUMENT lead character=lead
INSTRUMENT perc character=perc
INSTRUMENT arp character=arp

[PATTERN A length=16 role=theme]
CH3 lead V13
E4/4 G4/4 A4/4 B4/4
CH4 perc V10
C2/1 G3/1 C2/1 G3/1 C2/1 G3/1 C2/1 G3/1 C2/1 G3/1 C2/1 G3/1 C2/1 G3/1 C2/1 G3/1
CH2 arp V7
E3/2 G3/2 B3/2 E4/2 E3/2 G3/2 B3/2 E4/2
"""
    doc = parse_music_dsl(dsl_text, validate=True)
    report = analyze_composition(doc)
    rhythm = report.rhythm
    # CH4 perc must stay strictly in percussion, never polluting lead
    assert rhythm.role_rhythm["lead"].notes_count == 4
    assert rhythm.role_rhythm["percussion"].notes_count == 16
    assert rhythm.role_rhythm["arpeggio"].notes_count == 8
    assert rhythm.channel_rhythm[4].dominant_role == "percussion"
    assert rhythm.channel_rhythm[3].dominant_role == "lead"
    assert rhythm.lead_channel == 3


def test_echo_semantic_role_follows_declared_character_not_id() -> None:
    base_body = """TITLE "Echo Semantics"
KEY D
MODE MINOR
BPM 140
CHANNELS 4
LOOP 0

SEQUENCE B1

INSTRUMENT lead character=bright_lead
INSTRUMENT echo character={echo_char}

[PATTERN B1 length=16 role=theme]
CH3 lead V15
A4/5 G4/2 F4/2 E4/2 D4/5
CH2 echo V6
R/3 A4/5 G4/2 F4/2 E4/2 D4/2
"""
    # When AI declares echo with character=bright_lead, model semantics assign it to lead (no id-name hack)
    doc_as_lead = parse_music_dsl(base_body.format(echo_char="bright_lead"), validate=True)
    rep_lead = analyze_composition(doc_as_lead)
    assert rep_lead.rhythm.channel_rhythm[2].dominant_role == "lead"
    assert rep_lead.rhythm.role_rhythm["lead"].notes_count == 10

    # When AI / catalog declares echo semantically as counter/harmony, it separates cleanly from lead
    doc_as_harmony = parse_music_dsl(base_body.format(echo_char="counter"), validate=True)
    rep_harmony = analyze_composition(doc_as_harmony)
    assert rep_harmony.rhythm.channel_rhythm[2].dominant_role == "harmony"
    assert rep_harmony.rhythm.role_rhythm["lead"].notes_count == 5
    assert rep_harmony.rhythm.role_rhythm["harmony"].notes_count == 5

    # Explicit character=echo maps to ChannelRole.HARMONY in POKEY IR and dedicated 'echo' rhythm bucket
    echo_inst = AIInstrumentDef(id="reply_voice", name="Delayed Reply", character="echo")
    dist_echo, env_echo, role_echo = map_instrument_character(echo_inst)
    assert role_echo == ChannelRole.HARMONY
    assert dist_echo == DISTORTION_PURE_TONE
    assert env_echo.sustain_vol == 8

    doc_as_echo = parse_music_dsl(base_body.format(echo_char="echo"), validate=True)
    rep_echo = analyze_composition(doc_as_echo)
    assert rep_echo.rhythm.channel_rhythm[2].dominant_role == "echo"
    assert rep_echo.rhythm.role_rhythm["lead"].notes_count == 5
    assert rep_echo.rhythm.role_rhythm["echo"].notes_count == 5


def test_ch3_lead_and_ch2_delayed_echo_report_separate_metrics() -> None:
    # Regression (non-echo ID 'reply_voice' + existing catalog profile 'harmony_soft_square'):
    # CH3 plays lead (4 notes @ dur=4..5 -> avg=4.25), CH2 plays delayed rapid echo (7 notes @ dur=1..2).
    # Echo must never inflate lead metrics or lead_channel, and must report separate stats under role_rhythm['echo'].
    dsl_text = """TITLE "Echo Separation Regression"
KEY E
MODE MINOR
BPM 140
CHANNELS 4
LOOP 0

SEQUENCE A

INSTRUMENT melody_main character=bright_lead
INSTRUMENT reply_voice character=echo

[PATTERN A length=20 role=theme]
CH3 melody_main V14
E5/5 G5/4 F#5/4 E5/4
CH2 reply_voice V7
R/3 E5/2 G5/2 F#5/2 E5/1 E5/2 G5/2 F#5/2
"""
    doc = parse_music_dsl(dsl_text, validate=True)
    rep = analyze_composition(doc)
    rhy = rep.rhythm

    assert rhy.lead_channel == 3
    assert rhy.channel_rhythm[3].dominant_role == "lead"
    assert rhy.channel_rhythm[2].dominant_role == "echo"

    lead = rhy.role_rhythm["lead"]
    echo = rhy.role_rhythm["echo"]
    ch3 = rhy.channel_rhythm[3]
    ch2 = rhy.channel_rhythm[2]

    assert lead.notes_count == 4 == ch3.notes_count
    assert lead.avg_note_steps == pytest.approx(4.25)
    assert lead.notes_per_sec == pytest.approx(ch3.notes_per_sec)

    assert echo.notes_count == 7 == ch2.notes_count
    assert echo.avg_note_steps == pytest.approx(round(13 / 7, 4)) == ch2.avg_note_steps
    assert echo.notes_per_sec == pytest.approx(ch2.notes_per_sec)
    assert echo.notes_per_sec > lead.notes_per_sec

    # Same semantic separation when backed by an existing SSOT catalog harmony profile (e.g. harmony_soft_square)
    cat_echo_doc = AICompositionDoc.model_construct(
        format="atari-music-composition",
        version=1,
        metadata=doc.metadata,
        hardware=doc.hardware,
        instruments=[
            AIInstrumentDef(id="melody_main", name="Lead", character="bright_lead", catalog_id="lead_attack_bite"),
            AIInstrumentDef(
                id="reply_voice",
                name="Catalog Echo",
                character="echo",
                catalog_id="harmony_soft_square",
            ),
        ],
        patterns=doc.patterns,
        sequence=doc.sequence,
        loop_point=0,
    )
    cat_rep = analyze_composition(cat_echo_doc)
    assert cat_rep.rhythm.lead_channel == 3
    assert cat_rep.rhythm.role_rhythm["lead"].notes_count == 4
    assert cat_rep.rhythm.role_rhythm["echo"].notes_count == 7

    # Prompts instruct ECHO VOICE to declare character=echo (never character=lead / bright_lead)
    rich_dsl_prompt = get_system_prompt(CompositionRequest(format="dsl", prompt_profile="rich"))
    rich_json_prompt = get_system_prompt(CompositionRequest(format="json", prompt_profile="rich"))
    assert "character=echo" in rich_dsl_prompt
    assert "NEVER character=lead or bright_lead" in rich_dsl_prompt
    assert "character=echo" in rich_json_prompt
    assert '"echo"' in rich_json_prompt

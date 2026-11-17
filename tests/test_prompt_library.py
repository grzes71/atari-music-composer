"""Unit and integration tests for the opt-in rich prompt library, planning brief, and musical critique."""

from __future__ import annotations

import json
from click.testing import CliRunner
import pytest

from atari_music.ai.analysis import calculate_bpm_frames_per_tick
from atari_music.ai.client import generate_composition_with_retry
from atari_music.ai.critique import MusicalCritique
from atari_music.ai.dsl import parse_music_dsl
from atari_music.ai.prompt_library import (
    PAL_FRAME_RATE,
    RICH_DSL_EXAMPLE,
    build_rich_system_prompt,
    build_timing_grid_section,
    effective_bpm,
    recommended_steps_per_beat,
    rich_json_example,
    step_duration_seconds,
)
from atari_music.ai.prompts import (
    build_dsl_user_prompt,
    get_system_prompt,
    get_user_prompt,
)
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.validation import validate_composition
from atari_music.cli import cli

pytestmark = pytest.mark.core


def test_rich_system_prompt_preserves_classic_rules_and_adds_craft():
    """Verify rich system prompts retain all classic invariants and include craft sections."""
    for fmt in ("json", "dsl"):
        req = CompositionRequest(format=fmt, prompt_profile="rich")
        prompt = get_system_prompt(req)
        assert prompt == build_rich_system_prompt(fmt=fmt)
        assert "purely the COMPOSER" in prompt
        assert "4 monophonic audio channels" in prompt
        assert "16-BIT BASS MODE" in prompt
        assert "COMPOSER CRAFT FOR POKEY CHIPTUNE" in prompt
        assert "CHORD ARPEGGIO" in prompt
        assert "ECHO VOICE" in prompt
        if fmt == "dsl":
            assert "INSTRUMENT <id>" in prompt
            assert "Neon Citadel" in prompt


@pytest.mark.parametrize("bpm", [70, 100, 136, 180])
def test_timing_grid_section_matches_ground_truth_formula(bpm: int):
    """Verify timing grid numbers are derived from calculate_bpm_frames_per_tick."""
    fpt = calculate_bpm_frames_per_tick(bpm)
    expected_step_ms = (fpt / PAL_FRAME_RATE) * 1000.0
    spb = recommended_steps_per_beat(bpm)
    expected_eff = effective_bpm(bpm, spb)

    assert abs(step_duration_seconds(bpm) - (fpt / PAL_FRAME_RATE)) < 1e-9
    section = build_timing_grid_section(bpm)
    assert f"1 step = {fpt} frames = {expected_step_ms:.0f} ms" in section
    assert f"Use {spb} steps per beat" in section
    assert f"~{expected_eff:.0f} BPM" in section
    assert f"One 4/4 bar = {4 * spb} steps" in section


def test_timing_grid_exact_mode_suggests_nearest_exact_bpm():
    """Verify tempo_grid='exact' adds an explicit exact-grid BPM recommendation."""
    section_desc = build_timing_grid_section(136, tempo_grid="describe")
    section_exact = build_timing_grid_section(136, tempo_grid="exact")
    assert "Exact tempo-grid mode requested" not in section_desc
    assert "Exact tempo-grid mode requested: prefer setting metadata BPM to 125" in section_exact


def test_rich_few_shot_examples_are_valid():
    """Verify both RICH_DSL_EXAMPLE and rich_json_example() pass full 3-tier validation."""
    dsl_doc = parse_music_dsl(RICH_DSL_EXAMPLE, validate=True)
    validated_dsl = validate_composition(dsl_doc)
    assert validated_dsl.metadata.title == "Neon Citadel"

    json_dict = json.loads(rich_json_example())
    validated_json = validate_composition(json_dict)
    assert validated_json.format == "atari-music-composition"


def test_dsl_user_prompt_catalog_parity_is_opt_in():
    """Verify DSL user prompt includes SSOT catalog guidance only when opted in."""
    req_default = CompositionRequest(format="dsl", style="action")
    assert "Production Instrument Catalog" not in build_dsl_user_prompt(req_default)

    req_catalog = CompositionRequest(format="dsl", style="action", enable_catalog_instruments=True)
    prompt_cat = build_dsl_user_prompt(req_catalog)
    assert "Production Instrument Catalog" in prompt_cat
    assert "bass_16bit_pure" in prompt_cat


def test_plan_first_attaches_brief_and_injects_into_user_prompt():
    """Verify plan_first=True generates a MusicalBrief and embeds it into the user prompt."""
    req = CompositionRequest(style="boss fight", bpm=150, prompt_profile="rich", plan_first=True)
    provider = MockAICompositionProvider()
    doc = generate_composition_with_retry(req, provider)
    assert req.musical_brief is not None
    assert "sections" in req.musical_brief
    assert "motif" in req.musical_brief

    user_prompt = get_user_prompt(req)
    assert "COMPOSITION BRIEF" in user_prompt
    assert doc.metadata.bpm == 150


def test_musical_critique_scores_rich_example_above_monotonous_piece():
    """Verify MusicalCritique differentiates a rich multi-voice piece from a flat 1-voice loop."""
    flat_dsl = """
    TITLE "Flat"
    KEY C
    MODE MINOR
    BPM 120
    CHANNELS 4
    SEQUENCE A A A A
    [PATTERN A]
    CH1 LEAD V14
    C4/4 C4/4 C4/4 C4/4 C4/4 C4/4 C4/4 C4/4
    """
    flat_doc = parse_music_dsl(flat_dsl, validate=True)
    rich_doc = parse_music_dsl(RICH_DSL_EXAMPLE, validate=True)

    flat_critique = MusicalCritique.from_doc(flat_doc)
    rich_critique = MusicalCritique.from_doc(rich_doc)

    assert rich_critique.score > flat_critique.score
    assert len(flat_critique.findings) >= 3
    feedback = flat_critique.format_revision_feedback()
    assert "refine its MUSICALITY" in feedback


def test_quality_passes_keeps_best_valid_composition():
    """Verify quality_passes records critique scores and never degrades if a revision is invalid or weaker."""
    flat_dict = parse_music_dsl(
        'TITLE "Flat"\nKEY A\nMODE MINOR\nBPM 125\nCHANNELS 4\nSEQUENCE A\n[PATTERN A]\n'
        "CH1 LEAD V14\nA4/4 A4/4 A4/4 A4/4 A4/4 A4/4 A4/4 A4/4\n",
        validate=True,
    ).model_dump(mode="json")
    rich_dict = parse_music_dsl(RICH_DSL_EXAMPLE, validate=True).model_dump(mode="json")

    # Pass 0: flat_dict, Pass 1 (revision): rich_dict -> should upgrade to rich_dict
    provider = MockAICompositionProvider(sequence=[flat_dict, rich_dict])
    req = CompositionRequest(style="action", quality_passes=1)
    best_doc, history = generate_composition_with_retry(req, provider, return_history=True)
    assert len(history) == 2
    assert history[0].critique_score is not None
    assert history[1].critique_score is not None
    assert history[1].critique_score > history[0].critique_score
    assert best_doc.metadata.title == "Neon Citadel"


def test_cli_ai_compose_supports_new_options(tmp_path):
    """Verify ai-compose CLI accepts --prompt-profile, --key, --mode, --notes, --plan-first, --quality-passes."""
    runner = CliRunner()
    out_dsl = tmp_path / "rich_out.dsl"
    result = runner.invoke(
        cli,
        [
            "ai-compose",
            "--provider",
            "mock",
            "--format",
            "dsl",
            "--prompt-profile",
            "rich",
            "--style",
            "title",
            "--key",
            "A",
            "--mode",
            "minor",
            "--bpm",
            "125",
            "--notes",
            "Arpeggio and echo test",
            "--tempo-grid",
            "exact",
            "--plan-first",
            "--quality-passes",
            "1",
            "-o",
            str(out_dsl),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_dsl.exists()
    parsed = parse_music_dsl(out_dsl.read_text(encoding="utf-8"), validate=True)
    assert parsed.metadata.key == "A"

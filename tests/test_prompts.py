"""Unit tests for AI composer prompt generation and properties."""

import json
import re
import pytest

from atari_music.ai.prompts import build_system_prompt, build_user_prompt
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.validation import validate_composition


def test_system_prompt_separation_of_responsibilities():
    """Verify system prompt clearly defines composer role and engine execution role."""
    prompt = build_system_prompt()
    assert "purely the COMPOSER" in prompt
    assert "software application handles all low-level technical execution" in prompt
    assert "Do NOT attempt to calculate or implement low-level engine details" in prompt


def test_system_prompt_absolute_restrictions():
    """Verify system prompt maintains strict output and low-level restrictions."""
    prompt = build_system_prompt()
    assert "ONLY a single valid, well-formed JSON document" in prompt
    assert "atari-music-composition" in prompt
    assert "Do NOT wrap output in markdown backticks" in prompt
    assert "NEVER output MOS 6502 assembly" in prompt
    assert "NEVER output low-level POKEY hardware register addresses" in prompt


def test_system_prompt_hardware_rules_and_channel_economics():
    """Verify system prompt incorporates POKEY hardware limits and channel discipline."""
    prompt = build_system_prompt()
    # 4 channels & monophonic
    assert "4 monophonic audio channels" in prompt
    assert "Overlapping notes on the same channel are illegal" in prompt

    # Explicit channel guidelines
    assert "Do not use all four channels merely because they are available" in prompt
    assert "Silence is a valid compositional choice" in prompt

    # 16-bit bass pairing
    assert "16-BIT BASS MODE" in prompt
    assert "Channel 0" in prompt and "Channel 1" in prompt
    assert "frequency slave" in prompt


def test_system_prompt_no_rigid_structural_dogma():
    """Verify system prompt does not mandate rigid structural templates or patronizing rules."""
    prompt = build_system_prompt()
    # Should not have rigid mandatory templates or patronizing phrases
    assert "repeated 15 times" not in prompt
    assert "Intro -> A -> A_var -> Fill -> B" not in prompt
    assert "Create 6 to 9 distinct patterns" not in prompt
    # Should encourage musical freedom and flexible forms
    assert "form_plan" in prompt
    assert "optional" in prompt.lower()


def test_system_prompt_embedded_schema_is_valid_and_compiles():
    """Verify the minimal JSON schema illustration inside the prompt is valid and passes validation."""
    prompt = build_system_prompt()
    # Extract JSON block from prompt
    json_match = re.search(r"(\{[\s\S]*\"format\":\s*\"atari-music-composition\"[\s\S]*\})", prompt)
    assert json_match is not None, "Failed to locate JSON schema illustration in system prompt"

    doc_dict = json.loads(json_match.group(1))
    assert doc_dict["format"] == "atari-music-composition"
    assert doc_dict["version"] == 1

    # Validate that the embedded example passes composition validation without errors
    validated_doc = validate_composition(doc_dict)
    assert validated_doc.format == "atari-music-composition"
    assert validated_doc.version == 1


def test_user_prompt_includes_request_parameters_and_declarative_duration():
    """Verify user prompt presents parameters and treats duration as declarative."""
    req = CompositionRequest(
        style="dungeon exploration",
        duration_seconds=30,
        bpm=110,
        key="D",
        mode="dorian",
        mood=["mysterious", "dark"],
        structure="A-B-A",
        notes="Sparse atmospheric bells over low drone",
        channels=4,
        use_16bit_bass=True,
    )
    prompt = build_user_prompt(req)

    assert "dungeon exploration" in prompt
    assert "30 seconds" in prompt
    assert "Tempo: 110 BPM" in prompt
    assert "Root Key: D" in prompt
    assert "Musical Mode / Scale: dorian" in prompt
    assert "mysterious, dark" in prompt
    assert "A-B-A" in prompt
    assert "Sparse atmospheric bells over low drone" in prompt
    assert "REQUIRED / ENABLED" in prompt

    # Declarative duration & scale guidance
    assert "metadata.duration_seconds` is declarative" in prompt
    assert "engine computes exact PAL 50Hz duration" in prompt
    # No forced 6-9 pattern recipe
    assert "Create 6 to 9 distinct patterns" not in prompt

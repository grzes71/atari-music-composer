"""Unit and integration tests for Stage 13: Real LLM Integration & Structured Composition."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from atari_music.ai.schema import (
    AICompositionDoc,
    AIProviderAPIError,
    AIProviderDependencyError,
    AIProviderMissingKeyError,
    AIProviderStructuredOutputError,
    MusicCompositionError,
    MusicCompositionSchemaError,
    MusicCompositionValidationError,
    MusicIRValidationError,
)
from atari_music.ai.validation import validate_composition, validate_musical
from atari_music.ai.composition import (
    interpret_composition_to_music_ir,
    compile_composition_to_pokey_ir,
)
from atari_music.ai.client import (
    build_xex_from_composition,
    generate_music_from_composition,
    load_composition_json,
    request_ai_composition,
)
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.providers.openai import OpenAICompositionProvider


@pytest.fixture
def base_valid_doc() -> dict:
    """Fixture providing a strictly valid baseline AI composition dictionary."""
    return {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {
            "title": "Stage 13 Baseline",
            "author": "Test Author",
            "key": "A",
            "mode": "dorian",
            "bpm": 125,
            "duration_seconds": 16.0,
        },
        "hardware": {
            "channels": 4,
            "use_16bit_bass": False,
        },
        "instruments": [
            {"id": "lead", "name": "Lead Synth", "character": "bright_lead"},
            {"id": "bass", "name": "Bass Voice", "character": "bass"},
            {"id": "perc", "name": "Noise Drum", "character": "percussion"},
        ],
        "patterns": [
            {
                "id": "P1",
                "length_steps": 16,
                "channels": {
                    "1": [
                        {"step": 0, "note": "A3", "instrument": "lead", "duration": 4},
                        {"step": 4, "note": "C4", "instrument": "lead", "duration": 4},
                        {"step": 8, "note": "E4", "instrument": "lead", "duration": 4},
                        {"step": 12, "note": "G4", "instrument": "lead", "duration": 4},
                    ],
                    "2": [
                        {"step": 0, "note": "A2", "instrument": "bass", "duration": 8},
                        {"step": 8, "note": "G2", "instrument": "bass", "duration": 8},
                    ],
                    "3": [],
                    "4": [
                        {"step": 4, "note": "C5", "instrument": "perc", "duration": 2},
                        {"step": 12, "note": "C5", "instrument": "perc", "duration": 2},
                    ],
                },
            }
        ],
        "sequence": ["P1", "P1"],
        "loop_point": 0,
        "intent": {
            "style": "arcade action",
            "mood": ["energetic"],
            "structure": "P1-P1",
        },
    }


# =============================================================================
# 1. OPTIONAL DEPENDENCY TESTS (OpenAI is strictly optional)
# =============================================================================

def test_import_atari_music_without_openai():
    """Verify that atari_music and all subpackages import cleanly even without openai installed."""
    with patch.dict(sys.modules, {"openai": None}):
        import atari_music
        import atari_music.ai
        import atari_music.api
        import atari_music.composer_v4
        import atari_music.serialization

        assert hasattr(atari_music, "generate_music")
        assert hasattr(atari_music.ai, "load_composition_json")
        assert hasattr(atari_music.ai, "MockAICompositionProvider")


def test_mock_provider_works_completely_without_openai():
    """MockAICompositionProvider must generate valid compositions offline with no openai."""
    with patch.dict(sys.modules, {"openai": None}):
        provider = MockAICompositionProvider()
        req = CompositionRequest(style="dark dungeon", use_16bit_bass=True)
        raw_doc = provider.generate_composition(req)
        doc = validate_composition(raw_doc)
        assert doc.format == "atari-music-composition"
        assert len(doc.patterns) >= 1


def test_core_composer_v4_pipeline_unaffected_by_missing_openai():
    """Composer v4 procedural generation runs without openai."""
    with patch.dict(sys.modules, {"openai": None}):
        from atari_music.api import generate_music
        res = generate_music(profile="action", seed=42)
        assert res.metadata.channels_used == 4
        assert res.metadata.memory_size_bytes <= 2048


def test_openai_provider_missing_dependency_raises_clear_error():
    """Instantiating or running OpenAI provider without openai package raises AIProviderDependencyError."""
    with patch.dict(sys.modules, {"openai": None}):
        provider = OpenAICompositionProvider(api_key="sk-testkey1234567890")
        req = CompositionRequest(style="action")
        with pytest.raises(AIProviderDependencyError) as exc_info:
            provider.generate_composition(req)
        assert "pip install openai" in str(exc_info.value)
        assert isinstance(exc_info.value, MusicCompositionError)


# =============================================================================
# 2. MONOPHONY OVERLAP VALIDATION (POKEY Monophonic Voice Semantics)
# =============================================================================

def test_monophony_sequential_notes_pass(base_valid_doc):
    """Sequential non-overlapping notes pass validation."""
    doc = validate_composition(base_valid_doc)
    assert len(doc.patterns) == 1


def test_monophony_touching_boundaries_pass(base_valid_doc):
    """Notes whose boundaries touch exactly ([0..4) and [4..8)) pass validation."""
    bad_doc = dict(base_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "P1",
            "length_steps": 16,
            "channels": {
                "1": [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 4},
                    {"step": 4, "note": "E4", "instrument": "lead", "duration": 4},
                    {"step": 8, "note": "G4", "instrument": "lead", "duration": 8},
                ],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    doc = validate_composition(bad_doc)
    assert doc.patterns[0].length_steps == 16


def test_monophony_partial_overlap_rejected(base_valid_doc):
    """Partial overlap ([0..8) and [4..8)) must be rejected with informative error message."""
    bad_doc = dict(base_valid_doc)
    bad_doc["sequence"] = ["A"]
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "0": [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 8},
                    {"step": 4, "note": "E4", "instrument": "lead", "duration": 4},
                ],
                "1": [], "2": [], "3": [],
            },
        }
    ]
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    err = str(exc_info.value)
    assert "Overlapping notes in pattern 'A', channel 0" in err
    assert "C4" in err and "[0..8)" in err
    assert "E4" in err and "[4..8)" in err
    assert "overlaps" in err


def test_monophony_same_step_rejected(base_valid_doc):
    """Two active notes starting on the exact same step on one channel must be rejected."""
    bad_doc = dict(base_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "P1",
            "length_steps": 16,
            "channels": {
                "1": [
                    {"step": 4, "note": "C4", "instrument": "lead", "duration": 4},
                    {"step": 4, "note": "G4", "instrument": "lead", "duration": 2},
                ],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    err = str(exc_info.value)
    assert "Overlapping notes in pattern 'P1', channel 1" in err
    assert "overlaps" in err


def test_monophony_rest_does_not_conflict(base_valid_doc):
    """A rest (silence) between notes does not trigger an overlap conflict."""
    bad_doc = dict(base_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "P1",
            "length_steps": 16,
            "channels": {
                "1": [
                    {"step": 0, "note": "C4", "instrument": "lead", "duration": 4},
                    {"step": 4, "note": "REST", "instrument": "lead", "duration": 4},
                    {"step": 8, "note": "G4", "instrument": "lead", "duration": 4},
                ],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    doc = validate_composition(bad_doc)
    assert len(doc.patterns) == 1


def test_monophony_pattern_boundaries_isolated(base_valid_doc):
    """Overlaps are strictly validated within each pattern, not cross-pattern."""
    doc_data = dict(base_valid_doc)
    doc_data["patterns"] = [
        {
            "id": "P1",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 12, "note": "C4", "instrument": "lead", "duration": 4}],
                "2": [], "3": [], "4": [],
            },
        },
        {
            "id": "P2",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 0, "note": "D4", "instrument": "lead", "duration": 4}],
                "2": [], "3": [], "4": [],
            },
        },
    ]
    doc_data["sequence"] = ["P1", "P2"]
    # P1 ends at 16, P2 starts at 0: Valid!
    doc = validate_composition(doc_data)
    assert len(doc.patterns) == 2


# =============================================================================
# 3. STRUCTURED OUTPUTS & PARSING
# =============================================================================

def test_structured_output_json_schema_valid():
    """Verify that AICompositionDoc produces a valid, complete JSON schema."""
    schema = AICompositionDoc.model_json_schema()
    assert schema["title"] == "AICompositionDoc"
    assert "format" in schema["properties"]
    assert "version" in schema["properties"]
    assert "patterns" in schema["properties"]
    assert "sequence" in schema["properties"]


def test_parse_json_content_with_markdown_fences():
    """Defensive markdown fence stripping in OpenAI provider."""
    provider = OpenAICompositionProvider(api_key="sk-testkey")
    raw = "```json\n{\"format\": \"atari-music-composition\", \"version\": 1}\n```"
    parsed = provider._parse_json_content(raw)
    assert parsed["format"] == "atari-music-composition"
    assert parsed["version"] == 1


def test_parse_json_content_malformed_raises_structured_output_error():
    """Malformed non-JSON output raises AIProviderStructuredOutputError."""
    provider = OpenAICompositionProvider(api_key="sk-testkey")
    with pytest.raises(AIProviderStructuredOutputError):
        provider._parse_json_content("Not valid json at all")


# =============================================================================
# 4. PROVIDER SECURITY & KEY MASKING
# =============================================================================

def test_openai_missing_api_key_raises_missing_key_error():
    """Calling generate_composition without an API key raises AIProviderMissingKeyError."""
    with patch.dict(os.environ, {}, clear=True):
        provider = OpenAICompositionProvider(api_key=None)
        req = CompositionRequest(style="dungeon")
        with pytest.raises(AIProviderMissingKeyError) as exc_info:
            provider.generate_composition(req)
        assert "OPENAI_API_KEY" in str(exc_info.value)
        assert isinstance(exc_info.value, MusicCompositionError)


def test_openai_repr_masks_api_key():
    """Provider string representation must mask the secret key."""
    provider = OpenAICompositionProvider(api_key="sk-proj-SecretKey1234567890ABCD")
    rep = repr(provider)
    assert "sk-proj-SecretKey1234567890ABCD" not in rep
    assert "...ABCD" in rep


def test_openai_api_error_masks_api_key():
    """Errors from OpenAI client containing the API key must have the key masked."""
    fake_key = "sk-super-secret-key-999"
    provider = OpenAICompositionProvider(api_key=fake_key)

    mock_client = MagicMock()
    mock_client.beta.chat.completions.parse.side_effect = RuntimeError(f"Connection error with {fake_key}")

    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value = mock_client

    with patch.dict(sys.modules, {"openai": mock_openai}):
        req = CompositionRequest(style="title")
        with pytest.raises(AIProviderAPIError) as exc_info:
            provider.generate_composition(req)
        err = str(exc_info.value)
        assert fake_key not in err
        assert "******" in err


# =============================================================================
# 5. END-TO-END: MOCK PROVIDER -> MUSIC IR -> POKEY IR -> XEX
# =============================================================================

def test_e2e_mock_provider_to_xex_compilation(tmp_path):
    """End-to-end integration test: Mock Provider -> Validated AI JSON -> Music IR -> POKEY IR -> Atari XEX."""
    from conftest import require_local_artifact

    mads_exe = Path("tools/mads/mads.exe")
    require_local_artifact(mads_exe)

    provider = MockAICompositionProvider()
    req = CompositionRequest(
        style="dark dungeon",
        use_16bit_bass=True,
        bpm=90,
        channels=4,
    )
    raw_doc = provider.generate_composition(req)

    # 1. 3-Tier validation
    comp_doc = validate_composition(raw_doc)
    assert comp_doc.hardware.use_16bit_bass is True

    # 2. Compile directly into Atari XEX
    xex_out = tmp_path / "e2e_test_stage13.xex"
    res_xex = build_xex_from_composition(
        comp_doc,
        output_path=xex_out,
        player_address=0x6000,
        music_address=0x8000,
        zp_base=0x80,
        mads_bin=mads_exe,
    )

    assert res_xex.exists()
    xex_bytes = res_xex.read_bytes()
    # Check Atari DOS binary header $FFFF
    assert xex_bytes[0] == 0xFF and xex_bytes[1] == 0xFF
    # Verify memory budget
    assert 500 <= len(xex_bytes) <= 2048


# =============================================================================
# 6. OPTIONAL LIVE OPENAI TEST (Marked 'live', requires OPENAI_API_KEY)
# =============================================================================

@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY environment variable not set")
def test_live_openai_generation_and_validation():
    """Live integration test querying real OpenAI API with Structured Outputs (runs only when OPENAI_API_KEY is present)."""
    try:
        import openai  # noqa: F401
    except ImportError:
        pytest.skip("openai package not installed")

    provider = OpenAICompositionProvider(model="gpt-4o-mini")
    req = CompositionRequest(
        style="fast action chiptune",
        mood=["energetic", "driving"],
        duration_seconds=15.0,
        bpm=140,
        channels=4,
        use_16bit_bass=False,
    )

    raw_doc = provider.generate_composition(req)
    # Validate through the strict 3-tier validation engine
    doc = validate_composition(raw_doc)
    assert doc.format == "atari-music-composition"
    assert doc.version == 1
    assert len(doc.patterns) >= 1

    # Interpret to Symbolic Music IR
    music_ir = interpret_composition_to_music_ir(doc)
    assert len(music_ir.patterns) >= 1

    # Compile to POKEY IR
    pokey_ir = compile_composition_to_pokey_ir(doc, music_ir)
    assert len(pokey_ir.patterns) >= 1
    assert len(pokey_ir.sequence) >= 1

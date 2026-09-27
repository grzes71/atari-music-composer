"""Unit and integration tests for Stage 12: AI Music Composition Import Layer."""

import json
from pathlib import Path
import pytest

from atari_music.ai.schema import (
    AICompositionDoc,
    MusicCompositionError,
    MusicCompositionSchemaError,
    MusicCompositionValidationError,
    MusicIRValidationError,
)
from atari_music.ai.validation import (
    validate_schema,
    validate_musical,
    validate_hardware,
    validate_composition,
)
from atari_music.ai.composition import (
    interpret_composition_to_music_ir,
    compile_composition_to_pokey_ir,
)
from atari_music.ai.client import (
    load_composition_json,
    generate_music_from_composition,
    generate_music_from_json,
    build_xex_from_composition,
)
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.providers.openai import OpenAICompositionProvider
from atari_music.ai.providers.base import CompositionRequest
from atari_music.serialization import (
    music_ir_to_dict,
    music_ir_from_dict,
    music_ir_to_json,
    music_ir_from_json,
)
from atari_music.music_ir import (
    ChannelRole,
    MusicPhrase,
    MusicSong,
    SymbolicNote,
    SymbolicPattern,
    SymbolicTrack,
)


@pytest.fixture
def minimal_valid_doc() -> dict:
    """Fixture providing a minimal valid AI composition dictionary."""
    return {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {
            "title": "Minimal Test",
            "author": "Test Author",
            "key": "C",
            "mode": "minor",
            "bpm": 120,
            "duration_seconds": 10.0,
        },
        "hardware": {
            "channels": 4,
            "use_16bit_bass": False,
        },
        "instruments": [
            {
                "id": "lead",
                "name": "Lead Voice",
                "character": "bright_lead",
            },
            {
                "id": "bass",
                "name": "Bass Voice",
                "character": "bass",
            },
        ],
        "patterns": [
            {
                "id": "A",
                "length_steps": 16,
                "channels": {
                    "1": [
                        {"step": 0, "note": "C4", "instrument": "lead", "duration": 4},
                        {"step": 4, "note": "D#4", "instrument": "lead", "duration": 4},
                        {"step": 8, "note": "G4", "instrument": "lead", "duration": 4},
                        {"step": 12, "note": "A#4", "instrument": "lead", "duration": 4},
                    ],
                    "2": [
                        {"step": 0, "note": "C3", "instrument": "bass", "duration": 8},
                        {"step": 8, "note": "G3", "instrument": "bass", "duration": 8},
                    ],
                    "3": [],
                    "4": [],
                },
            }
        ],
        "sequence": ["A", "A"],
        "loop_point": 0,
        "intent": {
            "style": "minimal exploration",
            "mood": ["test"],
            "structure": "A-A",
        },
    }


# =========================================================================
# A. JSON SCHEMA TESTS
# =========================================================================

def test_schema_valid_minimal(minimal_valid_doc):
    """Test A.1: Valid document passes schema validation."""
    doc = validate_schema(minimal_valid_doc)
    assert isinstance(doc, AICompositionDoc)
    assert doc.version == 1
    assert doc.metadata.bpm == 120
    assert len(doc.patterns) == 1


def test_schema_missing_required_fields(minimal_valid_doc):
    """Test A.2: Missing required top-level fields raises MusicCompositionSchemaError."""
    bad_doc = dict(minimal_valid_doc)
    del bad_doc["format"]
    with pytest.raises(MusicCompositionSchemaError) as exc_info:
        validate_schema(bad_doc)
    assert "format" in str(exc_info.value).lower()

    bad_doc2 = dict(minimal_valid_doc)
    del bad_doc2["patterns"]
    with pytest.raises(MusicCompositionSchemaError):
        validate_schema(bad_doc2)


def test_schema_wrong_types(minimal_valid_doc):
    """Test A.3: Wrong data types raise MusicCompositionSchemaError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["metadata"] = dict(minimal_valid_doc["metadata"])
    bad_doc["metadata"]["bpm"] = "very_fast_string"  # invalid type
    with pytest.raises(MusicCompositionSchemaError):
        validate_schema(bad_doc)


def test_schema_out_of_range_values(minimal_valid_doc):
    """Test A.4: Out of range numerical values raise MusicCompositionSchemaError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["hardware"] = dict(minimal_valid_doc["hardware"])
    bad_doc["hardware"]["channels"] = 6  # Atari POKEY has max 4 channels
    with pytest.raises(MusicCompositionSchemaError):
        validate_schema(bad_doc)

    bad_doc2 = dict(minimal_valid_doc)
    bad_doc2["metadata"] = dict(minimal_valid_doc["metadata"])
    bad_doc2["metadata"]["bpm"] = 0  # BPM must be positive
    with pytest.raises(MusicCompositionSchemaError):
        validate_schema(bad_doc2)


# =========================================================================
# B. SERIALIZATION TESTS
# =========================================================================

def test_music_ir_serialization_roundtrip():
    """Test B: Music IR -> Dict/JSON -> Music IR preserves all musical information."""
    song = MusicSong(
        title="Roundtrip Test",
        tempo_bpm=135,
        meter="4/4",
        key="D",
        mode="dorian",
        patterns=[
            SymbolicPattern(
                id=0,
                name="A",
                rows=16,
                tracks={
                    1: SymbolicTrack(
                        channel_idx=1,
                        role=ChannelRole.MELODY,
                        notes=[
                            SymbolicNote(pitch=62, duration=2, velocity=15, role=ChannelRole.MELODY),
                            SymbolicNote(pitch=65, duration=2, velocity=14, role=ChannelRole.MELODY),
                            SymbolicNote(pitch=None, duration=4, velocity=0, is_rest=True, role=ChannelRole.MELODY),
                        ],
                    ),
                    2: SymbolicTrack(channel_idx=2, role=ChannelRole.BASS, notes=[]),
                    3: SymbolicTrack(channel_idx=3, role=ChannelRole.HARMONY, notes=[]),
                    4: SymbolicTrack(channel_idx=4, role=ChannelRole.PERCUSSION, notes=[]),
                },
            )
        ],
        sequence=[0, 0],
        min_channels=2,
        max_channels=4,
    )

    # 1. Test dict round-trip
    d = music_ir_to_dict(song)
    restored_dict = music_ir_from_dict(d)
    assert restored_dict.title == song.title
    assert restored_dict.tempo_bpm == song.tempo_bpm
    assert restored_dict.key == song.key
    assert restored_dict.mode == song.mode
    assert len(restored_dict.patterns) == len(song.patterns)
    assert len(restored_dict.patterns[0].tracks[1].notes) == len(song.patterns[0].tracks[1].notes)
    for n1, n2 in zip(song.patterns[0].tracks[1].notes, restored_dict.patterns[0].tracks[1].notes):
        assert n1.pitch == n2.pitch
        assert n1.duration == n2.duration
        assert n1.velocity == n2.velocity
        assert n1.is_rest == n2.is_rest

    # 2. Test JSON string round-trip
    j_str = music_ir_to_json(song)
    restored_json = music_ir_from_json(j_str)
    assert restored_json.title == song.title
    assert restored_json.sequence == song.sequence
    assert restored_json.patterns[0].tracks[1].role == ChannelRole.MELODY


# =========================================================================
# C. MUSICAL VALIDATION TESTS
# =========================================================================

def test_musical_unknown_instrument(minimal_valid_doc):
    """Test C.1: Referencing undefined instrument raises MusicCompositionValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 0, "note": "C4", "instrument": "non_existent_inst", "duration": 2}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "non_existent_inst" in str(exc_info.value)


def test_musical_unknown_pattern_in_sequence(minimal_valid_doc):
    """Test C.2: Sequence referencing undefined pattern raises MusicCompositionValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["sequence"] = ["A", "B", "A"]  # B does not exist
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "undefined pattern" in str(exc_info.value).lower() and "'B'" in str(exc_info.value)


def test_musical_invalid_note_name(minimal_valid_doc):
    """Test C.3: Invalid note strings raise MusicCompositionValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 0, "note": "H4", "instrument": "lead", "duration": 2}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "invalid note" in str(exc_info.value).lower() and "'H4'" in str(exc_info.value)


def test_musical_step_out_of_bounds(minimal_valid_doc):
    """Test C.4: Event step >= pattern length_steps raises MusicCompositionValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 16, "note": "C4", "instrument": "lead", "duration": 2}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "out of bounds" in str(exc_info.value).lower()


def test_musical_invalid_loop_point(minimal_valid_doc):
    """Test C.5: Loop point outside sequence range raises MusicCompositionValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["loop_point"] = 5  # sequence length is 2
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "loop_point" in str(exc_info.value)


# =========================================================================
# D. HARDWARE VALIDATION TESTS
# =========================================================================

def test_hardware_volume_out_of_range(minimal_valid_doc):
    """Test D.1: Volume > 15 raises MusicIRValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 0, "note": "C4", "instrument": "lead", "duration": 2, "volume": 18}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    with pytest.raises(MusicIRValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "volume" in str(exc_info.value).lower()


def test_hardware_invalid_distortion(minimal_valid_doc):
    """Test D.2: Unsupported POKEY distortion raises MusicIRValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["instruments"] = [
        {
            "id": "bad_inst",
            "name": "Bad Distortion",
            "character": "lead",
            "distortion": 3,  # Odd distortion is invalid on POKEY
        }
    ]
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "1": [{"step": 0, "note": "C4", "instrument": "bad_inst", "duration": 2}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    with pytest.raises(MusicIRValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "distortion" in str(exc_info.value).lower()


def test_hardware_16bit_bass_collision(minimal_valid_doc):
    """Test D.3: Independent notes on Channel 2 during 16-bit bass mode raise MusicIRValidationError."""
    bad_doc = dict(minimal_valid_doc)
    bad_doc["hardware"] = dict(minimal_valid_doc["hardware"])
    bad_doc["hardware"]["use_16bit_bass"] = True
    # In 16-bit bass mode, Channel 2 is hardware slave to Channel 1
    # If channel 2 has an independent note on step 4 while channel 1 has no bass note, collision!
    bad_doc["patterns"] = [
        {
            "id": "A",
            "length_steps": 16,
            "channels": {
                "1": [
                    {"step": 0, "note": "C2", "instrument": "bass", "duration": 4},
                ],
                "2": [
                    {"step": 4, "note": "G4", "instrument": "lead", "duration": 4},  # Collision!
                ],
                "3": [],
                "4": [],
            },
        }
    ]
    with pytest.raises(MusicIRValidationError) as exc_info:
        validate_composition(bad_doc)
    assert "16-bit bass collision" in str(exc_info.value)


# =========================================================================
# E. INTERPRETER TESTS
# =========================================================================

def test_interpreter_single_channel_composition(minimal_valid_doc):
    """Test E.1: Single channel composition compiles properly and fills rests."""
    doc_dict = dict(minimal_valid_doc)
    doc_dict["patterns"] = [
        {
            "id": "A",
            "length_steps": 8,
            "channels": {
                "1": [{"step": 0, "note": "C4", "instrument": "lead", "duration": 2}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    doc = validate_composition(doc_dict)
    music_ir = interpret_composition_to_music_ir(doc)
    assert len(music_ir.patterns) == 1
    ch1_notes = music_ir.patterns[0].tracks[1].notes
    # Check that note exists and remainder is padded with rest
    assert ch1_notes[0].pitch == 60  # C4
    assert ch1_notes[0].duration == 2
    assert ch1_notes[1].is_rest is True   # rest
    assert ch1_notes[1].duration == 6


def test_interpreter_4_channels_with_all_instruments(minimal_valid_doc):
    """Test E.2: 4-channel composition compiles into full POKEY IRSong."""
    doc = validate_composition(minimal_valid_doc)
    pokey_ir = compile_composition_to_pokey_ir(doc)
    assert len(pokey_ir.instruments) >= 2
    assert len(pokey_ir.patterns) == 1
    assert len(pokey_ir.patterns[0].tracks) == 4
    assert len(pokey_ir.sequence) == 2


def test_interpreter_16bit_bass_flag_propagation(minimal_valid_doc):
    """Test E.3: 16-bit bass mode sets uses_16bit_bass in resulting POKEY IRSong."""
    doc_dict = dict(minimal_valid_doc)
    doc_dict["hardware"]["use_16bit_bass"] = True
    doc_dict["patterns"] = [
        {
            "id": "A",
            "length_steps": 8,
            "channels": {
                "1": [{"step": 0, "note": "C2", "instrument": "bass", "duration": 8}],
                "2": [], "3": [], "4": [],
            },
        }
    ]
    doc = validate_composition(doc_dict)
    pokey_ir = compile_composition_to_pokey_ir(doc)
    assert pokey_ir.uses_16bit_bass is True


# =========================================================================
# F. PROVIDER TESTS
# =========================================================================

def test_mock_provider_all_styles():
    """Test F.1: Mock provider produces valid compositions for all requested styles."""
    provider = MockAICompositionProvider()
    for style in ["dark dungeon", "action fast", "funny prl", "ambient ending"]:
        req = CompositionRequest(style=style, duration_seconds=15.0)
        raw_doc = provider.generate_composition(req)
        comp = validate_composition(raw_doc)
        assert comp.format == "atari-music-composition"
        assert len(comp.patterns) >= 1
        assert len(comp.sequence) >= 1


def test_openai_provider_missing_key_security():
    """Test F.2: OpenAI provider fails gracefully when API key is missing without leaking env."""
    provider = OpenAICompositionProvider(api_key=None)
    req = CompositionRequest(style="dungeon")
    with pytest.raises(MusicCompositionError) as exc_info:
        provider.generate_composition(req)
    assert "OPENAI_API_KEY" in str(exc_info.value)


# =========================================================================
# G. END-TO-END MADS & XEX COMPILATION TESTS
# =========================================================================

def test_end_to_end_example_artifacts_compilation():
    """Test G: End-to-end verification that all example JSONs compile to valid Atari XEX binaries."""
    from conftest import require_local_artifact

    mads_exe = Path("tools/mads/mads.exe")
    require_local_artifact(mads_exe)

    examples_dir = Path("examples/ai")
    require_local_artifact(examples_dir)
    json_files = ["dungeon_dark.json", "action_fast.json", "funny_prl.json"]

    for jf in json_files:
        path = examples_dir / jf
        assert path.exists(), f"Example JSON {path} must exist"
        
        comp = load_composition_json(path)
        xex_out = Path(f"experiments/test_ai_{path.stem}.xex")
        
        # Test compilation
        result_xex = build_xex_from_composition(comp, output_path=xex_out, mads_bin=mads_exe)
        assert result_xex.exists()
        
        # Check binary headers & size
        data = result_xex.read_bytes()
        assert len(data) >= 500, f"XEX too small ({len(data)} bytes)"
        assert len(data) <= 2048, f"XEX exceeds memory budget ({len(data)} bytes)"
        assert data[0] == 0xFF and data[1] == 0xFF, "Invalid Atari DOS header (must begin with $FFFF)"

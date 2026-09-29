"""Unit and integration tests for Music DSL parser, serializer, and equivalence."""

import json
from pathlib import Path
import pytest

from atari_music.ai.dsl import (
    DSLSyntaxError,
    export_music_dsl,
    parse_music_dsl,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    MusicCompositionError,
    MusicCompositionValidationError,
    MusicIRValidationError,
)
from atari_music.ai.composition import (
    compile_composition_to_pokey_ir,
    interpret_composition_to_music_ir,
)
from atari_music.ai.client import (
    generate_music_from_composition,
)
from atari_music.mads_exporter import export_mads_asm


# =============================================================================
# A. SYNTAX & PARSING TESTS
# =============================================================================

def test_dsl_parse_minimal():
    """Verify minimal valid DSL compiles into a valid AICompositionDoc."""
    dsl = """
    TITLE "Minimal Piece"
    KEY C
    MODE MINOR
    BPM 120

    SEQUENCE P1

    [PATTERN P1]
    CH1 LEAD V14
    C4/4 D4/4 E4/4 F4/4
    """
    doc = parse_music_dsl(dsl)
    assert isinstance(doc, AICompositionDoc)
    assert doc.metadata.title == "Minimal Piece"
    assert doc.metadata.key == "C"
    assert doc.metadata.mode == "minor"
    assert doc.metadata.bpm == 120
    assert doc.sequence == ["P1"]
    assert len(doc.patterns) == 1
    assert doc.patterns[0].id == "P1"
    assert doc.patterns[0].length_steps == 16  # 4 * 4 = 16
    assert len(doc.patterns[0].channels["1"]) == 4


def test_dsl_parse_multichannel_and_rests():
    """Verify multi-channel DSL with rests and volume overrides."""
    dsl = """
    TITLE "Multi Voice"
    AUTHOR "Chiptune Hero"
    KEY A
    MODE DORIAN
    BPM 130
    CHANNELS 4
    LOOP 1

    SEQUENCE P1 P2 P1

    [PATTERN P1 length=16 role=theme]
    CH1 BASS V12
    A2/4 R/4 E2/4 R/4

    CH3 LEAD V14
    A4/4 C5/4:15 E5/4 A4/4

    CH4 PERC V10
    C4/2 R/2 C4/2 R/2 C4/4 R/4

    [PATTERN P2 length=16 role=variation]
    CH1 BASS V12
    G2/4 R/4 D2/4 R/4

    CH3 LEAD V14
    B4/4 D5/4 G5/4 B4/4
    """
    doc = parse_music_dsl(dsl)
    assert doc.metadata.author == "Chiptune Hero"
    assert doc.metadata.mode == "dorian"
    assert doc.loop_point == 1
    assert len(doc.sequence) == 3
    assert len(doc.patterns) == 2

    p1 = doc.patterns[0]
    assert p1.length_steps == 16
    assert p1.role == "theme"

    # Ch1 has 4 events: A2(4), REST(4), E2(4), REST(4)
    ch1_evs = p1.channels["1"]
    assert len(ch1_evs) == 4
    assert ch1_evs[0].note == "A2"
    assert ch1_evs[0].step == 0
    assert ch1_evs[1].note == "REST"
    assert ch1_evs[1].step == 4
    assert ch1_evs[2].note == "E2"
    assert ch1_evs[2].step == 8

    # Ch3 event 1 has volume override :15
    ch3_evs = p1.channels["3"]
    assert ch3_evs[1].note == "C5"
    assert ch3_evs[1].volume == 15
    assert ch3_evs[0].volume == 14


def test_dsl_16bit_bass():
    """Verify 16-bit bass directive and channel constraints."""
    dsl = """
    TITLE "Deep Sub"
    BPM 100
    BASS 16BIT

    SEQUENCE A

    [PATTERN A]
    CH1 BASS V14
    C2/8 G1/8

    CH3 LEAD V12
    C4/4 E4/4 G4/4 C5/4
    """
    doc = parse_music_dsl(dsl)
    assert doc.hardware.use_16bit_bass is True
    # Ch2 must be empty in 16-bit bass
    assert doc.patterns[0].channels["2"] == []


def test_dsl_custom_instruments():
    """Verify custom instrument definitions with ADSR and distortion."""
    dsl = """
    TITLE "Custom Sound"
    BPM 110

    INSTRUMENT lead character=bright_lead att=2 dec=4 sus=10 rel=3 dist=$a0
    INSTRUMENT bass character=bass att=0 dec=2 sus=12 rel=1 dist=$00

    SEQUENCE P1

    [PATTERN P1]
    CH1 BASS V12
    A2/16

    CH2 LEAD V14
    A4/16
    """
    doc = parse_music_dsl(dsl)
    inst_map = {i.id: i for i in doc.instruments}
    assert "lead" in inst_map
    assert inst_map["lead"].distortion == 0xA0
    assert inst_map["lead"].attack_frames == 2
    assert inst_map["lead"].decay_frames == 4
    assert inst_map["lead"].sustain_vol == 10
    assert inst_map["lead"].release_frames == 3

    assert "bass" in inst_map
    assert inst_map["bass"].distortion == 0x00


def test_dsl_comments_and_whitespace():
    """Verify comments (#) both as full lines and trailing comments are ignored."""
    dsl = """
    # Global setup
    TITLE "Commented Song"  # End-line comment
    KEY E                   # Root key
    MODE MINOR
    BPM 125                 # Standard tempo

    SEQUENCE M1             # 1-pattern loop

    # Pattern block
    [PATTERN M1]
    # Melody channel
    CH1 LEAD V14
    E4/4 G4/4 # first half
    B4/4 E5/4 # second half
    """
    doc = parse_music_dsl(dsl)
    assert doc.metadata.title == "Commented Song"
    assert doc.metadata.key == "E"
    assert len(doc.patterns[0].channels["1"]) == 4


# =============================================================================
# B. SYNTAX ERROR DIAGNOSTICS TESTS
# =============================================================================

def test_dsl_error_unknown_directive():
    """Verify unknown directive raises DSLSyntaxError with line number."""
    dsl = """
    TITLE "Bad"
    INVALID_DIRECTIVE 123
    """
    with pytest.raises(DSLSyntaxError) as exc_info:
        parse_music_dsl(dsl)
    assert "Line 3" in str(exc_info.value)
    assert "INVALID_DIRECTIVE" in str(exc_info.value)


def test_dsl_error_missing_duration():
    """Verify note without duration raises DSLSyntaxError."""
    dsl = """
    TITLE "No Duration"
    SEQUENCE A

    [PATTERN A]
    CH1 LEAD V14
    C4
    """
    with pytest.raises(DSLSyntaxError) as exc_info:
        parse_music_dsl(dsl)
    assert "Missing duration in note 'C4'" in str(exc_info.value)


def test_dsl_error_invalid_note_pitch():
    """Verify invalid pitch notation raises DSLSyntaxError."""
    dsl = """
    TITLE "Bad Pitch"
    SEQUENCE A

    [PATTERN A]
    CH1 LEAD V14
    H4/4
    """
    with pytest.raises(DSLSyntaxError) as exc_info:
        parse_music_dsl(dsl)
    assert "Invalid note pitch 'H4'" in str(exc_info.value)


def test_dsl_error_zero_duration():
    """Verify zero duration raises DSLSyntaxError."""
    dsl = """
    TITLE "Zero Duration"
    SEQUENCE A

    [PATTERN A]
    CH1 LEAD V14
    C4/0
    """
    with pytest.raises(DSLSyntaxError) as exc_info:
        parse_music_dsl(dsl)
    assert "Invalid duration in note 'C4/0'" in str(exc_info.value)


def test_dsl_error_unknown_pattern_in_sequence():
    """Verify referencing non-existent pattern in SEQUENCE raises validation error."""
    dsl = """
    TITLE "Missing Pattern"
    SEQUENCE A B

    [PATTERN A]
    CH1 LEAD V14
    C4/16
    """
    with pytest.raises(MusicCompositionValidationError) as exc_info:
        parse_music_dsl(dsl)
    assert "references undefined pattern 'B'" in str(exc_info.value)


def test_dsl_error_channel_outside_pattern():
    """Verify defining a channel before any [PATTERN ...] raises DSLSyntaxError."""
    dsl = """
    TITLE "Orphan Channel"
    CH1 LEAD V14
    C4/4
    """
    with pytest.raises(DSLSyntaxError) as exc_info:
        parse_music_dsl(dsl)
    assert "outside of any [PATTERN" in str(exc_info.value)


# =============================================================================
# C. ROUND-TRIP SERIALIZATION & EQUIVALENCE TESTS
# =============================================================================

def test_dsl_round_trip_equivalence():
    """Verify doc -> export_music_dsl -> parse_music_dsl produces equivalent POKEY IR."""
    dsl_source = """
    TITLE "Equivalence Test"
    AUTHOR "Tester"
    KEY D
    MODE MINOR
    BPM 120

    SEQUENCE A B A

    [PATTERN A length=16 role=theme]
    CH1 BASS V13
    D2/4 F2/4 C2/4 D2/4

    CH2 LEAD V14
    D4/4 F4/4 A4/4 D5/4

    [PATTERN B length=16 role=contrast]
    CH1 BASS V13
    G2/4 Bb2/4 F2/4 G2/4

    CH2 LEAD V14
    G4/4 Bb4/4 D5/4 G5/4
    """
    # 1. Parse original DSL
    doc1 = parse_music_dsl(dsl_source)

    # 2. Export to DSL
    exported_dsl = export_music_dsl(doc1)

    # 3. Parse exported DSL back
    doc2 = parse_music_dsl(exported_dsl)

    # 4. Compare resulting POKEY IR
    res1 = generate_music_from_composition(doc1)
    res2 = generate_music_from_composition(doc2)

    assert res1.pokey_ir.title == res2.pokey_ir.title
    assert res1.pokey_ir.tempo_bpm == res2.pokey_ir.tempo_bpm
    assert res1.pokey_ir.frames_per_tick == res2.pokey_ir.frames_per_tick
    assert len(res1.pokey_ir.patterns) == len(res2.pokey_ir.patterns)
    assert res1.pokey_ir.sequence == res2.pokey_ir.sequence

    # Compare pattern note streams
    for p1, p2 in zip(res1.pokey_ir.patterns, res2.pokey_ir.patterns):
        assert p1.name == p2.name
        assert p1.rows == p2.rows
        for ch in range(1, 5):
            notes1 = p1.tracks.get(ch, [])
            notes2 = p2.tracks.get(ch, [])
            assert len(notes1) == len(notes2)
            for n1, n2 in zip(notes1, notes2):
                assert n1.pitch == n2.pitch
                assert n1.duration == n2.duration
                assert n1.volume == n2.volume
                assert n1.is_rest == n2.is_rest

    # 5. Compare generated MADS ASM
    asm1 = export_mads_asm(res1.pokey_ir)
    asm2 = export_mads_asm(res2.pokey_ir)
    assert asm1 == asm2


def test_json_to_dsl_to_json_equivalence_4channels():
    """Verify that a 4-channel JSON composition survives round-trip with identical POKEY IR."""
    json_doc = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {
            "title": "Quad Test",
            "author": "Composer",
            "key": "G",
            "mode": "minor",
            "bpm": 125,
        },
        "hardware": {
            "channels": 4,
            "use_16bit_bass": False,
        },
        "instruments": [
            {"id": "lead", "name": "Lead Voice", "character": "bright_lead"},
            {"id": "bass", "name": "Bass Voice", "character": "bass"},
            {"id": "harm", "name": "Harmony Voice", "character": "harmony"},
            {"id": "drum", "name": "Drum Voice", "character": "percussion"},
        ],
        "patterns": [
            {
                "id": "Intro",
                "length_steps": 16,
                "channels": {
                    "1": [
                        {"step": 0, "note": "G4", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 4, "note": "Bb4", "instrument": "lead", "duration": 4, "volume": 14},
                        {"step": 8, "note": "D5", "instrument": "lead", "duration": 8, "volume": 14},
                    ],
                    "2": [
                        {"step": 0, "note": "G2", "instrument": "bass", "duration": 8, "volume": 12},
                        {"step": 8, "note": "D2", "instrument": "bass", "duration": 8, "volume": 12},
                    ],
                    "3": [
                        {"step": 0, "note": "D4", "instrument": "harm", "duration": 16, "volume": 9},
                    ],
                    "4": [
                        {"step": 0, "note": "C4", "instrument": "drum", "duration": 4, "volume": 10},
                        {"step": 4, "note": "REST", "instrument": "drum", "duration": 4, "volume": 0},
                        {"step": 8, "note": "C4", "instrument": "drum", "duration": 4, "volume": 10},
                        {"step": 12, "note": "REST", "instrument": "drum", "duration": 4, "volume": 0},
                    ],
                },
            }
        ],
        "sequence": ["Intro", "Intro"],
        "loop_point": 0,
    }

    # 1. Parse JSON to AICompositionDoc
    doc_json = AICompositionDoc.model_validate(json_doc)

    # 2. Export to DSL
    dsl_text = export_music_dsl(doc_json)

    # 3. Parse DSL to AICompositionDoc
    doc_dsl = parse_music_dsl(dsl_text)

    # 4. Compare generated POKEY IR
    res_json = generate_music_from_composition(doc_json)
    res_dsl = generate_music_from_composition(doc_dsl)

    assert res_json.pokey_ir.title == res_dsl.pokey_ir.title
    assert res_json.pokey_ir.tempo_bpm == res_dsl.pokey_ir.tempo_bpm
    assert res_json.pokey_ir.sequence == res_dsl.pokey_ir.sequence

    asm_json = export_mads_asm(res_json.pokey_ir)
    asm_dsl = export_mads_asm(res_dsl.pokey_ir)
    assert asm_json == asm_dsl


def test_json_to_dsl_to_json_equivalence_16bit_bass():
    """Verify that a 16-bit bass JSON composition survives round-trip with identical POKEY IR and ASM."""
    json_doc = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {
            "title": "Bass16 Equivalence",
            "author": "Bassmaster",
            "key": "D",
            "mode": "minor",
            "bpm": 100,
        },
        "hardware": {
            "channels": 4,
            "use_16bit_bass": True,
        },
        "instruments": [
            {"id": "lead", "name": "Lead Voice", "character": "bright_lead"},
            {"id": "bass", "name": "Deep Bass", "character": "bass"},
        ],
        "patterns": [
            {
                "id": "PatA",
                "length_steps": 16,
                "channels": {
                    "1": [
                        {"step": 0, "note": "D1", "instrument": "bass", "duration": 8, "volume": 14},
                        {"step": 8, "note": "A1", "instrument": "bass", "duration": 8, "volume": 14},
                    ],
                    "2": [],
                    "3": [
                        {"step": 0, "note": "D4", "instrument": "lead", "duration": 4, "volume": 12},
                        {"step": 4, "note": "F4", "instrument": "lead", "duration": 4, "volume": 12},
                        {"step": 8, "note": "A4", "instrument": "lead", "duration": 4, "volume": 12},
                        {"step": 12, "note": "D5", "instrument": "lead", "duration": 4, "volume": 12},
                    ],
                    "4": [],
                },
            }
        ],
        "sequence": ["PatA", "PatA"],
        "loop_point": 0,
    }
    doc_json = AICompositionDoc.model_validate(json_doc)
    dsl_text = export_music_dsl(doc_json)
    doc_dsl = parse_music_dsl(dsl_text)

    res_json = generate_music_from_composition(doc_json)
    res_dsl = generate_music_from_composition(doc_dsl)

    assert res_json.pokey_ir.uses_16bit_bass is True
    assert res_dsl.pokey_ir.uses_16bit_bass is True
    assert res_json.pokey_ir.sequence == res_dsl.pokey_ir.sequence
    assert len(res_json.pokey_ir.patterns) == len(res_dsl.pokey_ir.patterns)

    # Compare tracks
    p_json = res_json.pokey_ir.patterns[0]
    p_dsl = res_dsl.pokey_ir.patterns[0]
    for ch in range(1, 5):
        assert len(p_json.tracks.get(ch, [])) == len(p_dsl.tracks.get(ch, []))

    asm_json = export_mads_asm(res_json.pokey_ir)
    asm_dsl = export_mads_asm(res_dsl.pokey_ir)
    assert asm_json == asm_dsl


def test_wav_rendering_identity_between_json_and_dsl(tmp_path):
    """Verify that WAV frames synthesized from JSON and DSL are identical."""
    from atari_music.ir import compile_ir_to_pokey_frames
    import numpy as np

    dsl = """
    TITLE "WAV Test"
    KEY C
    MODE MINOR
    BPM 120

    SEQUENCE A A

    [PATTERN A length=16]
    CH1 BASS V13
    C2/4 D#2/4 G2/4 C3/4

    CH2 LEAD V14
    C4/4 D#4/4 G4/4 C5/4
    """
    doc_dsl = parse_music_dsl(dsl)
    res_dsl = generate_music_from_composition(doc_dsl)

    # Export doc_dsl to JSON dict and reload to ensure JSON pipeline
    json_dict = doc_dsl.model_dump(mode="json")
    doc_json = AICompositionDoc.model_validate(json_dict)
    res_json = generate_music_from_composition(doc_json)

    # 1. Compile POKEY frames and verify array equality
    frames_json = compile_ir_to_pokey_frames(res_json.pokey_ir)
    frames_dsl = compile_ir_to_pokey_frames(res_dsl.pokey_ir)
    np.testing.assert_array_equal(frames_json, frames_dsl)

    # 2. Render WAV audio and compare bytes
    wav_json_path = tmp_path / "test_json.wav"
    wav_dsl_path = tmp_path / "test_dsl.wav"
    res_json.render_wav(wav_json_path)
    res_dsl.render_wav(wav_dsl_path)

    assert wav_json_path.read_bytes() == wav_dsl_path.read_bytes()


# =============================================================================
# E. CLIENT REPAIR LOOP & CLI INTEGRATION TESTS
# =============================================================================

def test_dsl_repair_loop_syntax_error_then_valid():
    """Verify repair loop handles DSL syntax error on first attempt and succeeds on second."""
    from atari_music.ai.client import request_ai_composition
    from atari_music.ai.providers import CompositionRequest, MockAICompositionProvider

    provider = MockAICompositionProvider(scenario="dsl_syntax_error_then_valid")
    req = CompositionRequest(style="dungeon", format="dsl")

    doc = request_ai_composition(req, provider=provider, max_retries=2)
    assert doc.metadata.title == "Fixed"
    assert provider.call_count == 2
    # Verify feedback was sent on second attempt
    assert provider.received_feedbacks[1] is not None
    assert "DSL_SYNTAX_ERROR" in provider.received_feedbacks[1]


def test_dsl_repair_loop_semantic_error_then_valid():
    """Verify repair loop handles semantic validation error on DSL and succeeds on second attempt."""
    from atari_music.ai.client import request_ai_composition
    from atari_music.ai.providers import CompositionRequest, MockAICompositionProvider

    provider = MockAICompositionProvider(scenario="invalid_then_valid")
    req = CompositionRequest(style="dungeon", format="dsl")

    doc = request_ai_composition(req, provider=provider, max_retries=2)
    assert doc.metadata.title == "Test"
    assert provider.call_count == 2
    assert provider.received_feedbacks[1] is not None
    assert "UNKNOWN_PATTERN" in provider.received_feedbacks[1]


def test_load_composition_auto_detect_file(tmp_path):
    """Verify load_composition correctly parses .dsl and .json files based on extension."""
    from atari_music.ai.client import load_composition

    # DSL file
    dsl_file = tmp_path / "song.dsl"
    dsl_file.write_text('TITLE "File DSL"\nKEY C\nMODE MINOR\nBPM 120\nSEQUENCE A\n[PATTERN A]\nCH1 LEAD V14\nC4/4\n', encoding="utf-8")
    doc_dsl = load_composition(dsl_file)
    assert doc_dsl.metadata.title == "File DSL"

    # JSON file
    json_file = tmp_path / "song.json"
    json_file.write_text(json.dumps(doc_dsl.model_dump(mode="json")), encoding="utf-8")
    doc_json = load_composition(json_file)
    assert doc_json.metadata.title == "File DSL"


def test_cli_ai_compose_format_dsl():
    """Verify click CLI ai-compose command supports --format dsl."""
    from click.testing import CliRunner
    from atari_music.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["ai-compose", "--provider", "mock", "--format", "dsl"])
    assert result.exit_code == 0
    # Output should contain DSL keywords, not JSON
    assert "TITLE" in result.output
    assert "SEQUENCE" in result.output
    assert "[PATTERN" in result.output
    assert "CH1" in result.output
    assert "{" not in result.output.strip()[:10]  # Not JSON at start


def test_build_xex_directly_from_dsl_file(tmp_path: Path):
    """Verify build_xex_from_composition compiles .dsl file directly to Atari XEX binary."""
    from conftest import require_local_artifact
    from atari_music.ai.client import build_xex_from_composition
    require_local_artifact(Path("tools/mads/mads.exe"))

    dsl_file = tmp_path / "track.dsl"
    dsl_file.write_text(
        'TITLE "DSL XEX Test"\n'
        'KEY C\n'
        'MODE MINOR\n'
        'BPM 120\n'
        'CHANNELS 2\n'
        'SEQUENCE A\n'
        '[PATTERN A length=16]\n'
        'CH1 LEAD V14\n'
        'C4/4 D4/4 E4/4 G4/4\n'
        'CH2 BASS V12\n'
        'C2/8 G2/8\n',
        encoding="utf-8",
    )

    xex_out = tmp_path / "track.xex"
    res_path = build_xex_from_composition(dsl_file, output_path=xex_out)
    assert res_path.exists()
    assert res_path.stat().st_size > 0



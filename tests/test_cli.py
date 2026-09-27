"""Unit and regression tests for the Atari Music Composer public CLI."""

import json
from pathlib import Path
from click.testing import CliRunner

from atari_music.cli import cli
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)


def _create_minimal_composition() -> AICompositionDoc:
    """Helper creating a valid minimal AI composition document for CLI testing."""
    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="CLI Test Track",
            bpm=120,
            key="C",
            mode="minor",
        ),
        hardware=AIHardwareConfig(
            channels=4,
            use_16bit_bass=False,
        ),
        instruments=[
            AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
            AIInstrumentDef(id="bass", name="Bass", character="bass"),
            AIInstrumentDef(id="harm", name="Harmony", character="soft_pad"),
            AIInstrumentDef(id="perc", name="Drums", character="percussion"),
        ],
        patterns=[
            AIPatternDef(
                id="A",
                length_steps=16,
                channels={
                    "1": [AIPatternChannelEvent(step=0, note="C4", instrument="lead", duration=4, volume=14)],
                    "2": [AIPatternChannelEvent(step=0, note="G3", instrument="harm", duration=8, volume=10)],
                    "3": [AIPatternChannelEvent(step=0, note="C2", instrument="bass", duration=8, volume=12)],
                    "4": [AIPatternChannelEvent(step=0, note="C4", instrument="perc", duration=2, volume=15)],
                },
            ),
        ],
        sequence=["A", "A"],
        loop_point=0,
    )


def test_cli_public_commands_in_help():
    """Verify atari-music --help displays exactly the 6 canonical public commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0

    # Must contain the 6 public commands
    assert "compose" in result.output
    assert "ai-compose" in result.output
    assert "import-json" in result.output
    assert "analyze" in result.output
    assert "export-mads" in result.output
    assert "build-xex" in result.output

    # Hidden / research commands must NOT be exposed in public --help
    hidden_commands = [
        "extract",
        "report",
        "stage3",
        "mine-archetypes",
        "generate-song",
        "run-experiment",
        "stage4-report",
        "prepare-listening-test",
        "stage5-report",
        "investigate-memorization",
        "compose-v2",
        "run-composer-v2-experiment",
        "stage6-report",
        "prepare-listening-test-v2",
        "validate-listening-test-v2",
        "stage6-5-report",
        "audit-diversity",
        "compose-v3",
        "run-composer-v3-experiment",
        "stage7-report",
        "prepare-listening-test-v3",
        "stage7-1-report",
        "compose-v4",
        "run-composer-v4-experiment",
        "stage8-report",
        "reanalyze-raw",
    ]
    for cmd in hidden_commands:
        assert f"  {cmd} " not in result.output, f"Hidden command '{cmd}' should not appear in --help"


def test_cli_hidden_commands_still_callable():
    """Verify hidden commands remain callable for backward compatibility and research reproduction."""
    runner = CliRunner()
    for cmd in ["compose-v4", "compose-v3", "extract", "reanalyze-raw", "stage8-report"]:
        res = runner.invoke(cli, [cmd, "--help"])
        assert res.exit_code == 0, f"Hidden command '{cmd}' should be callable with --help"
        assert "Usage:" in res.output


def test_cli_analyze_human_readable(tmp_path: Path):
    """Verify analyze outputs a structured human-readable diagnostic report."""
    runner = CliRunner()
    comp_file = tmp_path / "test_composition.json"
    doc = _create_minimal_composition()
    comp_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    result = runner.invoke(cli, ["analyze", str(comp_file)])
    assert result.exit_code == 0
    assert "Composition Analysis: CLI Test Track" in result.output
    assert "Fingerprint (SHA-256):" in result.output
    assert "Key/Mode:             C minor" in result.output
    assert "[Rhythm & Notes]" in result.output
    assert "[Melody & Harmony]" in result.output
    assert "[POKEY Hardware Utilization]" in result.output
    assert "Hardware Warnings:    None" in result.output


def test_cli_analyze_with_structure(tmp_path: Path):
    """Verify analyze --structure appends macro-structural form analysis."""
    runner = CliRunner()
    comp_file = tmp_path / "test_composition.json"
    doc = _create_minimal_composition()
    comp_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    result = runner.invoke(cli, ["analyze", str(comp_file), "--structure"])
    assert result.exit_code == 0
    assert "[Macro-Structure & Form]" in result.output
    assert "Deduced Form:" in result.output
    assert "Material Reuse Ratio:" in result.output
    assert "Shannon Diversities:" in result.output


def test_cli_analyze_json_output(tmp_path: Path):
    """Verify analyze --json produces valid, machine-readable JSON on stdout."""
    runner = CliRunner()
    comp_file = tmp_path / "test_composition.json"
    doc = _create_minimal_composition()
    comp_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    result = runner.invoke(cli, ["analyze", str(comp_file), "--json"])
    assert result.exit_code == 0

    parsed = json.loads(result.output)
    assert "fingerprint" in parsed
    assert len(parsed["fingerprint"]) == 64
    assert "rhythm" in parsed
    assert "melody" in parsed
    assert "harmony" in parsed
    assert "structure" in parsed
    assert "pokey" in parsed
    assert "summary" in parsed
    assert parsed["summary"]["title"] == "CLI Test Track"


def test_cli_analyze_json_with_structure(tmp_path: Path):
    """Verify analyze --json --structure embeds macro_structure in JSON output."""
    runner = CliRunner()
    comp_file = tmp_path / "test_composition.json"
    doc = _create_minimal_composition()
    comp_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    result = runner.invoke(cli, ["analyze", str(comp_file), "--json", "--structure"])
    assert result.exit_code == 0

    parsed = json.loads(result.output)
    assert "macro_structure" in parsed
    assert "form" in parsed["macro_structure"]
    assert "material_reuse_ratio" in parsed["macro_structure"]


def test_cli_analyze_output_json_file(tmp_path: Path):
    """Verify analyze -o <path> writes the JSON analysis report to disk."""
    runner = CliRunner()
    comp_file = tmp_path / "test_composition.json"
    out_json = tmp_path / "report.json"
    doc = _create_minimal_composition()
    comp_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    result = runner.invoke(cli, ["analyze", str(comp_file), "-o", str(out_json)])
    assert result.exit_code == 0
    assert out_json.exists()

    saved_data = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved_data["fingerprint"] is not None
    assert "Analysis saved to" in result.output


def test_cli_analyze_nonexistent_file():
    """Verify analyze returns error code when input file does not exist."""
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", "nonexistent_file_12345.json"])
    assert result.exit_code != 0

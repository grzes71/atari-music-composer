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

    # Must contain the public commands
    assert "compose" in result.output
    assert "ai-compose" in result.output
    assert "import-json" in result.output
    assert "import-dsl" in result.output
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


def test_cli_version_flag():
    """Verify that -v and --version options display the application version and exit cleanly."""
    from atari_music import __version__

    runner = CliRunner()
    for flag in ["-v", "--version"]:
        result = runner.invoke(cli, [flag])
        assert result.exit_code == 0
        assert "atari-music" in result.output
        assert __version__ in result.output


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


def test_cli_build_xex_help_shows_player_asm():
    """Verify build-xex --help displays the --player-asm option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["build-xex", "--help"])
    assert result.exit_code == 0
    assert "--player-asm" in result.output
    assert "Path to player.asm" in result.output
    assert "defaults to current directory" in result.output


def test_client_build_xex_explicit_player_asm_not_found(tmp_path: Path):
    """Verify build_xex_from_composition raises FileNotFoundError when player_asm does not exist."""
    import pytest
    from atari_music.ai.client import build_xex_from_composition

    doc = _create_minimal_composition()
    with pytest.raises(FileNotFoundError, match="player.asm not found at"):
        build_xex_from_composition(doc, output_path=tmp_path / "out.xex", player_asm=tmp_path / "missing_player.asm")


def test_client_build_xex_cwd_player_asm_lookup(tmp_path: Path, monkeypatch):
    """Verify build_xex_from_composition prioritizes player.asm in current working directory."""
    import pytest
    from atari_music.ai.client import build_xex_from_composition

    # Create dummy player.asm in a temporary directory
    custom_player = tmp_path / "player.asm"
    custom_player.write_text("; Custom player in cwd\n", encoding="utf-8")

    # Change current working directory to tmp_path
    monkeypatch.chdir(tmp_path)

    doc = _create_minimal_composition()
    # Expect failure at mads executable or mads build, but player.asm is resolved from cwd
    with pytest.raises(FileNotFoundError) as excinfo:
        # Pass nonexistent mads to stop execution after player.asm lookup
        build_xex_from_composition(doc, output_path=tmp_path / "out.xex", mads_bin=tmp_path / "missing_mads.exe")
    assert "MADS assembler not found" in str(excinfo.value)


def test_cli_build_xex_subprocess_execution(tmp_path: Path, monkeypatch):
    """Verify build-xex invokes subprocess.run successfully without NameError."""
    import subprocess
    from unittest.mock import MagicMock

    runner = CliRunner()
    comp_file = tmp_path / "track.json"
    doc = _create_minimal_composition()
    comp_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    dummy_mads = tmp_path / "mads.exe"
    dummy_mads.write_text("dummy binary", encoding="utf-8")
    out_xex = tmp_path / "track.xex"

    # Mock subprocess.run to simulate successful MADS compilation
    def fake_subprocess_run(cmd, capture_output=True, text=True):
        out_xex.write_bytes(b"\xff\xff\x00\x40\x10\x40")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Compiled 100 bytes"
        mock_proc.stderr = ""
        return mock_proc

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    result = runner.invoke(cli, ["build-xex", str(comp_file), "-o", str(out_xex), "--mads", str(dummy_mads)])
    assert result.exit_code == 0
    assert "Successfully compiled XEX" in result.output
    assert out_xex.exists()


def test_cli_import_json_success(tmp_path: Path):
    """Verify import-json imports a valid JSON composition and generates outputs."""
    runner = CliRunner()
    doc = _create_minimal_composition()
    json_path = tmp_path / "song.json"
    json_path.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    out_asm = tmp_path / "song.asm"
    out_ir = tmp_path / "song_ir.json"

    result = runner.invoke(cli, ["import-json", str(json_path), "--output-asm", str(out_asm), "--output-ir", str(out_ir)])
    assert result.exit_code == 0
    assert "Loaded successfully!" in result.output
    assert "CLI Test Track" in result.output
    assert out_asm.exists()
    assert out_ir.exists()


def test_cli_import_json_rejects_dsl_or_invalid(tmp_path: Path):
    """Verify import-json fails with ClickException when non-JSON content is provided."""
    runner = CliRunner()
    dsl_path = tmp_path / "song.dsl"
    dsl_path.write_text("TITLE 'Song'\n[PATTERN A len=16]\nCH1 C4/4\n", encoding="utf-8")

    result = runner.invoke(cli, ["import-json", str(dsl_path)])
    assert result.exit_code != 0
    assert "Failed to parse JSON" in result.output


def test_cli_import_dsl_success(tmp_path: Path):
    """Verify import-dsl imports a valid Music DSL composition, exports canonical JSON and ASM."""
    from atari_music.ai.dsl import export_music_dsl

    runner = CliRunner()
    doc = _create_minimal_composition()
    dsl_text = export_music_dsl(doc)
    dsl_path = tmp_path / "song.dsl"
    dsl_path.write_text(dsl_text, encoding="utf-8")

    out_json = tmp_path / "canonical.json"
    out_asm = tmp_path / "song.asm"
    out_ir = tmp_path / "song_ir.json"

    result = runner.invoke(
        cli,
        [
            "import-dsl",
            str(dsl_path),
            "--output-json",
            str(out_json),
            "--output-asm",
            str(out_asm),
            "--output-ir",
            str(out_ir),
        ],
    )
    assert result.exit_code == 0
    assert "Loaded successfully!" in result.output
    assert "CLI Test Track" in result.output
    assert out_json.exists()
    assert out_asm.exists()
    assert out_ir.exists()

    # Validate exported JSON is valid canonical composition
    canonical_data = json.loads(out_json.read_text(encoding="utf-8"))
    assert canonical_data["metadata"]["title"] == "CLI Test Track"


def test_cli_import_dsl_rejects_json_or_invalid(tmp_path: Path):
    """Verify import-dsl fails with ClickException when JSON or invalid syntax is provided."""
    runner = CliRunner()
    json_path = tmp_path / "song.json"
    doc = _create_minimal_composition()
    json_path.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")

    result = runner.invoke(cli, ["import-dsl", str(json_path)])
    assert result.exit_code != 0
    assert "Failed to parse/validate Music DSL" in result.output


def test_cli_build_xex_with_explicit_format(tmp_path: Path, monkeypatch):
    """Verify build-xex respects explicit --format dsl and --format json."""
    import subprocess
    from unittest.mock import MagicMock
    from atari_music.ai.dsl import export_music_dsl

    runner = CliRunner()
    doc = _create_minimal_composition()

    # 1. DSL format
    dsl_file = tmp_path / "tune.txt"  # Arbitrary extension to prove it does not rely on .dsl
    dsl_file.write_text(export_music_dsl(doc), encoding="utf-8")
    out_xex_dsl = tmp_path / "dsl_tune.xex"

    dummy_mads = tmp_path / "mads.exe"
    dummy_mads.write_text("dummy binary", encoding="utf-8")

    def fake_subprocess_run(cmd, capture_output=True, text=True):
        out_p = None
        for arg in cmd:
            if arg.startswith("-o:"):
                out_p = Path(arg[3:])
        if out_p:
            out_p.write_bytes(b"\xff\xff\x00\x40\x10\x40")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "OK"
        mock_proc.stderr = ""
        return mock_proc

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    res_dsl = runner.invoke(
        cli,
        ["build-xex", str(dsl_file), "-o", str(out_xex_dsl), "--format", "dsl", "--mads", str(dummy_mads)],
    )
    assert res_dsl.exit_code == 0
    assert "(DSL)" in res_dsl.output
    assert out_xex_dsl.exists()

    # 2. JSON format
    json_file = tmp_path / "tune_json.txt"  # Arbitrary extension
    json_file.write_text(json.dumps(doc.model_dump(mode="json")), encoding="utf-8")
    out_xex_json = tmp_path / "json_tune.xex"

    res_json = runner.invoke(
        cli,
        ["build-xex", str(json_file), "-o", str(out_xex_json), "--format", "json", "--mads", str(dummy_mads)],
    )
    assert res_json.exit_code == 0
    assert "(JSON)" in res_json.output
    assert out_xex_json.exists()



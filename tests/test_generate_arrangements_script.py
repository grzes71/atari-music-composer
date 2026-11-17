"""Tests for generate_arrangements.py smart batch arrangement pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pytest
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import generate_arrangements as ga  # noqa: E402
from atari_music.ai.dsl import parse_music_dsl  # noqa: E402
from atari_music.api import generate_music  # noqa: E402
from atari_music.cli import cli  # noqa: E402

pytestmark = pytest.mark.core


def _live_catalog_from_cli() -> Tuple[str, List[ga.CatalogInstrumentInfo]]:
    """Fetch the real SSOT catalog payload using Click's offline CliRunner."""
    res = CliRunner().invoke(cli, ["list-instruments", "--target", "xex_v2", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    catalog = [
        ga._parse_catalog_row(row)
        for row in data["instruments"]
        if bool(row.get("compatible", False))
    ]
    return res.output, catalog


def test_analyze_composition_detects_16bit_and_8bit_and_nonstandard_channel_roles(
    tmp_path: Path,
) -> None:
    # 1. 16-bit DSL converted to AI Composition JSON
    dsl_path = REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl"
    dsl_doc = parse_music_dsl(dsl_path.read_text(encoding="utf-8"))
    w2_json = tmp_path / "wybierak-2.json"
    w2_json.write_text(dsl_doc.model_dump_json(indent=2), encoding="utf-8")

    comp_w2 = ga.analyze_composition(w2_json, source_path=dsl_path)
    assert comp_w2.uses_16bit_bass is True
    assert comp_w2.v1_compatible is True
    assert comp_w2.channels[1].role == "bass"
    assert comp_w2.channels[1].active is True
    assert comp_w2.channels[2].reserved_for_16bit is True
    assert comp_w2.channels[2].active is False
    assert comp_w2.channels[3].role == "melody"
    assert comp_w2.channels[4].role == "percussion"

    # 2. 8-bit AI JSON with non-default layout (CH1=melody, CH2=bass, CH3=harmony, CH4=percussion)
    af_path = REPO_ROOT / "examples" / "ai" / "action_fast.json"
    comp_af = ga.analyze_composition(af_path)
    assert comp_af.uses_16bit_bass is False
    assert comp_af.channels[1].role == "melody"
    assert comp_af.channels[2].role == "bass"
    assert comp_af.channels[2].midi_min == 36
    assert comp_af.channels[2].midi_max == 43
    assert comp_af.channels[3].role == "harmony"
    assert comp_af.channels[4].role == "percussion"

    # 3. 16-bit AI JSON where CH4 is harmony (NOT percussion)
    dz2_path = REPO_ROOT / "examples" / "songs" / "dziki2.json"
    comp_dz2 = ga.analyze_composition(dz2_path)
    assert comp_dz2.uses_16bit_bass is True
    assert comp_dz2.channels[1].role == "bass"
    assert comp_dz2.channels[2].active is False
    assert comp_dz2.channels[3].role == "melody"
    assert comp_dz2.channels[4].role == "harmony"

    # 4. POKEY IR JSON schema
    ir_res = generate_music(profile="dungeon", seed=42, uses_16bit_bass=False)
    ir_json = tmp_path / "ir_song.json"
    ir_res.save_json(ir_json)
    comp_ir = ga.analyze_composition(ir_json)
    assert comp_ir.source_kind == "pokey-ir"
    assert comp_ir.uses_16bit_bass is False
    assert comp_ir.v1_compatible is True


def test_score_and_rank_variants_respects_midi_range_and_roles(tmp_path: Path) -> None:
    _, catalog = _live_catalog_from_cli()

    # 8-bit composition with low bass (MIDI 30..45) -> bass_15khz_pure [28..60] beats bass_poly4_punch [36..67]
    af_comp = ga.analyze_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    low_bass_ch2 = ga.ChannelAnalysis(**{**af_comp.channels[2].__dict__, "midi_min": 30, "midi_max": 45, "midi_median": 38.0})
    low_comp = ga.CompositionAnalysis(**{**af_comp.__dict__, "channels": {**af_comp.channels, 2: low_bass_ch2}})
    scored_8bit = ga.score_all_channels(low_comp, catalog)

    assert scored_8bit[2][0].instrument.instrument_id == "bass_15khz_pure"
    assert scored_8bit[3][0].instrument.instrument_id == "harmony_soft_square"
    assert all("perc_" not in c.instrument.instrument_id for c in scored_8bit[2])

    # 16-bit composition with high bass notes exceeding MIDI 55 -> bass_16bit_pure [24..60] beats bass_16bit_poly5_growl [24..55]
    dz2_comp = ga.analyze_composition(REPO_ROOT / "examples" / "songs" / "dziki2.json")
    high_bass_ch1 = ga.ChannelAnalysis(**{**dz2_comp.channels[1].__dict__, "midi_min": 36, "midi_max": 58, "midi_median": 46.0})
    high_16_comp = ga.CompositionAnalysis(**{**dz2_comp.__dict__, "channels": {**dz2_comp.channels, 1: high_bass_ch1}})
    scored_16bit = ga.score_all_channels(high_16_comp, catalog)

    assert scored_16bit[1][0].instrument.instrument_id == "bass_16bit_pure"
    assert scored_16bit[4][0].instrument.instrument_id == "harmony_soft_square"

    # Build numbered variants + vanilla
    variants = ga.build_ranked_variants(low_comp, scored_8bit, max_variants=6, include_vanilla=True)
    v2_vars = [v for v in variants if v.player_version == "v2"]
    v1_vars = [v for v in variants if v.player_version == "v1"]

    assert len(v2_vars) == 6
    assert [v.name[:3] for v in v2_vars] == ["01_", "02_", "03_", "04_", "05_", "06_"]
    assert all(v2_vars[i].total_score >= v2_vars[i + 1].total_score for i in range(len(v2_vars) - 1))
    assert len(v1_vars) == 1
    assert v1_vars[0].name == "vanilla"
    assert v1_vars[0].channel_instruments == {}


def test_dry_run_and_log_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_json, _ = _live_catalog_from_cli()
    fake_cli = tmp_path / "atari-music.exe"
    fake_cli.write_text("stub", encoding="utf-8")
    out_dir = tmp_path / "out_dry"

    def fake_run(cmd: Sequence[str], *, stream_output: bool = False) -> Tuple[int, str, str]:
        args = list(cmd)
        if "--version" in args:
            return 0, "atari-music, version test", ""
        if "list-instruments" in args:
            return 0, catalog_json, ""
        raise AssertionError(f"Unexpected subprocess call during --dry-run: {args}")

    monkeypatch.setattr(ga, "_run_subprocess", fake_run)

    rc = ga.main(
        [
            "-i",
            str(REPO_ROOT / "examples" / "ai" / "action_fast.json"),
            "-o",
            str(out_dir),
            "--atari-music-path",
            str(fake_cli),
            "--dry-run",
        ]
    )
    assert rc == 0
    log_path = out_dir / "arrangements.log"
    assert log_path.is_file()
    log_text = log_path.read_text(encoding="utf-8")
    assert "[COMPOSITION PROFILE]" in log_text
    assert "[CHANNEL ANALYSIS]" in log_text
    assert "[PER-CHANNEL CANDIDATE RANKINGS]" in log_text
    assert "[SELECTED RANKED VARIANTS & EXECUTION]" in log_text
    assert "CH2 (bass): bass_15khz_pure" in log_text
    assert "[vanilla]" in log_text


def test_end_to_end_execution_with_mocked_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog_json, _ = _live_catalog_from_cli()
    fake_cli = tmp_path / "atari-music.exe"
    fake_mads = tmp_path / "mads.exe"
    fake_cli.write_text("stub", encoding="utf-8")
    fake_mads.write_text("stub", encoding="utf-8")
    out_dir = tmp_path / "out_dsl"
    recorded_cmds: List[List[str]] = []

    dsl_path = REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl"
    dsl_doc = parse_music_dsl(dsl_path.read_text(encoding="utf-8"))

    def fake_run(cmd: Sequence[str], *, stream_output: bool = False) -> Tuple[int, str, str]:
        args = list(cmd)
        recorded_cmds.append(args)
        if "--version" in args:
            return 0, "atari-music, version test", ""
        if "list-instruments" in args:
            return 0, catalog_json, ""
        if "import-dsl" in args:
            out_json = Path(args[args.index("--output-json") + 1])
            out_json.write_text(dsl_doc.model_dump_json(indent=2), encoding="utf-8")
            return 0, "Saved JSON", ""
        if "arrange" in args:
            wav_p = Path(args[args.index("--output-wav") + 1])
            xex_p = Path(args[args.index("-o") + 1])
            wav_p.write_bytes(b"RIFFfakewav")
            xex_p.write_bytes(b"\xff\xff\x00\x60test")
            return 0, "OK", ""
        raise AssertionError(f"Unexpected subprocess command: {args}")

    monkeypatch.setattr(ga, "_run_subprocess", fake_run)

    rc, log_path = ga.execute_batch(
        input_file=dsl_path,
        output_dir=out_dir,
        mads_path=fake_mads,
        atari_music_path=fake_cli,
        max_variants=3,
        include_vanilla=True,
    )
    assert rc == 0
    assert log_path.is_file()

    arrange_cmds = [c for c in recorded_cmds if "arrange" in c]
    assert len(arrange_cmds) == 4  # 3 ranked v2 + vanilla v1
    v1_cmds = [c for c in arrange_cmds if c[c.index("--player-version") + 1] == "v1"]
    assert len(v1_cmds) == 1
    assert "--channel-instrument" not in v1_cmds[0]

    v2_cmds = [c for c in arrange_cmds if c[c.index("--player-version") + 1] == "v2"]
    assert len(v2_cmds) == 3
    for cmd in v2_cmds:
        # 16-bit bass must NEVER assign CH2
        assert not any(arg.startswith("2=") for arg in cmd)

    wavs = sorted(p.name for p in out_dir.glob("*.wav"))
    xexs = sorted(p.name for p in out_dir.glob("*.xex"))
    assert len(wavs) == 4
    assert len(xexs) == 4
    assert "vanilla.wav" in wavs
    assert "vanilla.xex" in xexs
    assert sum(1 for w in wavs if w.startswith(("01_", "02_", "03_"))) == 3

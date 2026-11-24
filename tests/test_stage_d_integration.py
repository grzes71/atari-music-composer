"""CORE tests for Stage D: Composer v4, AI generator, and CLI v2 instrument integration."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest
from click.testing import CliRunner

from atari_music.ai.client import (
    build_xex_from_composition,
    generate_music_from_composition,
    request_ai_composition,
)
from atari_music.ai.composition import compile_composition_to_pokey_ir
from atari_music.ai.prompts import build_user_prompt
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.validation import validate_composition_report
from atari_music.api import generate_music
from atari_music.cli import cli
from atari_music.composer_v4 import compose_song_v4
from atari_music.instruments import (
    InstrumentPlanError,
    ProgramChangeSpec,
    load_instrument_catalog,
    resolve_export_format_version,
)
from atari_music.ir import IRSong, song_requires_v2
from atari_music.mads_exporter import SONG_FORMAT_VERSION, SONG_FORMAT_VERSION_2, export_mads_asm

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"


# ===========================================================================
# 1. Composer v4 Regression (v1) + 4-Channel Catalog & PROGRAM_CHANGE (v2)
# ===========================================================================


def test_composer_v4_default_unchanged_and_exports_v1() -> None:
    """Default Composer v4 / generate_music without catalog params must remain bit-for-bit v1."""
    r1 = compose_song_v4(profile="action", seed=42)
    r2 = generate_music(profile="action", seed=42)

    assert r1.quality_report.format_version == 1
    assert r2.metadata.format_version == 1
    assert r2.metadata.sound_profiles == []
    assert r1.pokey_ir.initial_channel_instruments is None
    assert song_requires_v2(r1.pokey_ir) == []
    assert resolve_export_format_version(r1.pokey_ir, "auto") == 1

    asm_default = export_mads_asm(r1.pokey_ir)
    asm_v1 = export_mads_asm(r1.pokey_ir, format_version=SONG_FORMAT_VERSION)
    assert asm_default == asm_v1
    assert "; format version (0 = no version byte" in asm_default


def test_composer_v4_static_core_v1_catalog_stays_v1_under_auto() -> None:
    """Pure core_v1 catalog profiles (one per channel, no switch/macro/pitch) stay v1 under auto."""
    res = generate_music(
        profile="exploration",
        seed=77,
        channel_instruments={
            1: "bass_15khz_pure",
            2: "harmony_soft_square",
            3: "lead_pure_pluck",
            4: "lead_pure_sustain",
        },
        player_version="auto",
    )
    assert res.metadata.format_version == 1
    assert res.pokey_ir.initial_channel_instruments is None
    assert song_requires_v2(res.pokey_ir) == []
    assert len(res.metadata.sound_profiles) == 4
    asm_text = export_mads_asm(res, format_version=resolve_export_format_version(res.pokey_ir, "auto"))
    assert "    .byte 1    ; format version" in asm_text


def test_composer_v4_four_channel_v2_instruments_and_program_change(tmp_path: Path) -> None:
    """Composer v4 supports 4 distinct v2 catalog instruments plus mid-song PROGRAM_CHANGE."""
    res = generate_music(
        profile="action",
        seed=42,
        channel_instruments={
            1: "bass_poly4_punch",
            2: "harmony_soft_square",
            3: "lead_pure_sustain",
            4: "perc_kick_tight",
        },
        program_changes=[
            ProgramChangeSpec(channel=3, section="B", instrument_id="lead_attack_bite", note_index=0),
            ProgramChangeSpec(channel=4, section="B", instrument_id="perc_snare_crisp", note_index=1),
        ],
    )
    assert res.metadata.format_version == 2
    assert song_requires_v2(res.pokey_ir)
    assert resolve_export_format_version(res.pokey_ir, "auto") == 2
    assert res.pokey_ir.initial_channel_instruments is not None
    profile_ids = {p["instrument_id"] for p in res.metadata.sound_profiles}
    assert profile_ids == {
        "bass_poly4_punch",
        "harmony_soft_square",
        "lead_pure_sustain",
        "lead_attack_bite",
        "perc_kick_tight",
        "perc_snare_crisp",
    }
    assert res.quality_report.under_budget is True

    # Verify MADS v2 export embeds SoA macros & PROGRAM_CHANGE ($00, $00, $01, inst)
    asm_path = tmp_path / "composer_v2.asm"
    asm_text = export_mads_asm(res.pokey_ir, asm_path, format_version=SONG_FORMAT_VERSION_2)
    assert "format version 2" in asm_text
    assert "; PROGRAM_CHANGE inst=" in asm_text

    # Verify WAV synthesis succeeds cleanly on v2 result
    wav_path = tmp_path / "composer_v2.wav"
    res.render_wav(wav_path)
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnframes() > 22050

    # End-to-end MADS + py65 parity on Composer v4 v2 output
    if MADS.is_file():
        import numpy as np
        from atari_music import frame_simulator
        from tests.test_stage_c_player_v2_parity import _compile_and_run_py65

        frames_py65, syms, _, mpu = _compile_and_run_py65(res.pokey_ir, tmp_path, "comp_v4_v2_e2e", 48)
        frames_oracle = frame_simulator.simulate_v2_binary_frames(mpu.memory, syms["song_data"], 48)
        assert np.array_equal(frames_py65, frames_oracle)


def test_composer_v4_validation_rejects_unknown_deferred_or_conflicting_instruments() -> None:
    """Out-of-catalog, deferred, and hardware-conflicting assignments raise InstrumentPlanError."""
    with pytest.raises(InstrumentPlanError, match="not found in catalog"):
        generate_music(channel_instruments={3: "totally_nonexistent_synth"})

    with pytest.raises(InstrumentPlanError, match="DEFERRED|deferred|tier"):
        generate_music(channel_instruments={3: "ornament_bell_arp"})

    with pytest.raises(InstrumentPlanError, match="channel 2 cannot be assigned"):
        generate_music(
            channel_instruments={1: "bass_16bit_pure", 2: "harmony_soft_square"}
        )

    with pytest.raises(InstrumentPlanError, match="channels .*4.*cannot bind to channel 1"):
        generate_music(channel_instruments={1: "perc_kick_tight"})

    with pytest.raises(InstrumentPlanError, match="does not exist"):
        generate_music(
            profile="action",
            seed=42,
            channel_instruments={3: "lead_pure_sustain"},
            program_changes=[ProgramChangeSpec(channel=3, section="NONEXISTENT_SEC", instrument_id="lead_attack_bite")],
        )

    with pytest.raises(InstrumentPlanError, match="xex_v1|BEHAVIOR_NOT_IN_TARGET_TIER|require format v2"):
        generate_music(
            profile="action",
            seed=42,
            channel_instruments={3: "lead_attack_bite"},
            player_version="v1",
        )


# ===========================================================================
# 2. AI Generator Integration (Catalog + Legacy v1 Preservation)
# ===========================================================================


def test_ai_generator_default_legacy_v1_preserved() -> None:
    """AI composition without catalog options stays strictly in legacy v1 style."""
    req = CompositionRequest(style="action", duration_seconds=12, bpm=140, channels=4)
    prompt = build_user_prompt(req)
    assert "src/atari_music/instruments/catalog.json" not in prompt

    doc = request_ai_composition(req, provider_name="mock")
    assert all(inst.catalog_id is None for inst in doc.instruments)

    res = generate_music_from_composition(doc)
    assert res.metadata.format_version == 1
    assert res.metadata.sound_profiles == []
    assert song_requires_v2(res.pokey_ir) == []
    assert resolve_export_format_version(res.pokey_ir, "auto") == 1


def test_ai_generator_uses_ssot_catalog_channels_and_musical_program_change(tmp_path: Path) -> None:
    """Opt-in AI catalog mode exposes SSOT profiles, builds coherent multi-inst v2 & compiles XEX."""
    req = CompositionRequest(
        style="action",
        duration_seconds=12,
        bpm=138,
        channels=4,
        channel_instruments={1: "bass_poly4_punch", 2: "harmony_soft_square"},
        enable_catalog_instruments=True,
    )
    prompt = build_user_prompt(req)
    assert "src/atari_music/instruments/catalog.json" in prompt
    assert "lead_attack_bite" in prompt
    assert "bass_poly4_punch" in prompt
    assert "Never randomly cycle instruments note-to-note" in prompt

    doc = request_ai_composition(req, provider_name="mock")
    catalog = load_instrument_catalog()
    cat_ids = [inst.catalog_id for inst in doc.instruments]
    assert all(cid is not None and catalog.has_profile(cid) for cid in cat_ids)
    assert "bass_poly4_punch" in cat_ids
    assert "harmony_soft_square" in cat_ids
    # Musically meaningful drum kit & contrasting lead section B
    assert "perc_kick_tight" in cat_ids and "perc_snare_crisp" in cat_ids
    assert "lead_pure_sustain" in cat_ids and "lead_attack_bite" in cat_ids

    res = generate_music_from_composition(doc)
    assert res.metadata.format_version == 2
    assert song_requires_v2(res.pokey_ir)
    assert res.pokey_ir.initial_channel_instruments is not None
    assert any(inst.macro or inst.pitch_envelope for inst in res.pokey_ir.instruments)

    # AI validation blocks bad/deferred catalog_id explicitly
    bad_doc = doc.model_copy(deep=True)
    bad_doc.instruments[0].catalog_id = "invalid_fake_instrument"
    bad_rep = validate_composition_report(bad_doc)
    assert not bad_rep.valid
    assert any(i.code == "UNKNOWN_CATALOG_INSTRUMENT" for i in bad_rep.issues)

    # Compile to real Atari XEX via MADS
    if MADS.is_file():
        xex_path = build_xex_from_composition(doc, output_path=tmp_path / "ai_cat_v2.xex", mads_bin=MADS)
        assert xex_path.is_file() and xex_path.stat().st_size > 1800


def test_ai_compile_with_use_catalog_flag_without_explicit_catalog_ids() -> None:
    """compile_composition_to_pokey_ir(..., use_catalog=True) enriches plain AI docs from catalog."""
    mock = MockAICompositionProvider()
    doc_dict = mock.generate_composition(CompositionRequest(style="funny", channels=4))
    doc = validate_composition_report(doc_dict)
    assert doc.valid

    from atari_music.ai.schema import AICompositionDoc

    parsed_doc = AICompositionDoc.model_validate(doc_dict)
    ir_song = compile_composition_to_pokey_ir(parsed_doc, use_catalog=True)
    assert all(inst.profile_id is not None for inst in ir_song.instruments)
    assert song_requires_v2(ir_song)


# ===========================================================================
# 3. CLI Integration (list, inspect, validate, compose, ai-compose, export-mads, build-xex)
# ===========================================================================


@pytest.mark.audio
def test_cli_instruments_workflow_and_backward_compatibility(tmp_path: Path) -> None:
    runner = CliRunner()

    # 1. Catalog browsing, inspection & validation
    res_list = runner.invoke(cli, ["list-instruments", "--family", "percussion"])
    assert res_list.exit_code == 0, res_list.output
    assert "perc_kick_tight" in res_list.output
    assert "lead_pure_sustain" not in res_list.output

    res_list_json = runner.invoke(cli, ["list-instruments", "--json"])
    assert res_list_json.exit_code == 0, res_list_json.output
    payload = json.loads(res_list_json.output)
    assert len(payload["instruments"]) >= 16
    assert "midi_range" in payload["instruments"][0]
    assert "envelope" in payload["instruments"][0]

    res_insp = runner.invoke(cli, ["inspect-instrument", "lead_attack_bite"])
    assert res_insp.exit_code == 0, res_insp.output
    assert "beh_transient_attack_bite" in res_insp.output
    assert "Transient Macro" in res_insp.output

    res_insp_bad = runner.invoke(cli, ["inspect-instrument", "does_not_exist"])
    assert res_insp_bad.exit_code != 0
    assert "INSTRUMENT_NOT_FOUND" in res_insp_bad.output

    res_val = runner.invoke(cli, ["validate-instruments"])
    assert res_val.exit_code == 0, res_val.output
    assert "VALID" in res_val.output

    # 2. compose default -> keeps format v1 & exact existing CLI flags working
    v1_json = tmp_path / "comp_v1.json"
    v1_asm = tmp_path / "comp_v1.asm"
    res_v1 = runner.invoke(
        cli,
        ["compose", "-p", "action", "-s", "42", "--output-json", str(v1_json), "--output-asm", str(v1_asm)],
    )
    assert res_v1.exit_code == 0, res_v1.output
    assert "Format: v1" in res_v1.output
    assert "; format version (0 = no version byte" in v1_asm.read_text(encoding="utf-8")

    # 3. compose with 4 catalog instruments + PROGRAM_CHANGE -> v2 + WAV + export-mads auto
    v2_json = tmp_path / "comp_v2.json"
    v2_asm = tmp_path / "comp_v2.asm"
    v2_wav = tmp_path / "comp_v2.wav"
    res_v2 = runner.invoke(
        cli,
        [
            "compose",
            "-p", "action",
            "-s", "42",
            "--channel-instrument", "1=bass_poly4_punch",
            "--channel-instrument", "2=harmony_soft_square",
            "--channel-instrument", "3=lead_pure_sustain",
            "--channel-instrument", "4=perc_kick_tight",
            "--program-change", "3@B=lead_attack_bite",
            "--output-json", str(v2_json),
            "--output-asm", str(v2_asm),
            "--output-wav", str(v2_wav),
        ],
    )
    assert res_v2.exit_code == 0, res_v2.output
    assert "Format: v2" in res_v2.output
    assert v2_asm.is_file() and "format version 2" in v2_asm.read_text(encoding="utf-8")
    assert v2_wav.is_file() and v2_wav.stat().st_size > 44000

    # export-mads --player-version auto chooses v2 for v2_json and v1 for v1_json; refuses v1 on v2_json
    exp_v2_asm = tmp_path / "reexport_v2.asm"
    res_exp_auto = runner.invoke(cli, ["export-mads", str(v2_json), "-o", str(exp_v2_asm)])
    assert res_exp_auto.exit_code == 0, res_exp_auto.output
    assert "(v2)" in res_exp_auto.output

    res_exp_force_v1 = runner.invoke(
        cli, ["export-mads", str(v2_json), "-o", str(tmp_path / "bad.asm"), "--player-version", "v1"]
    )
    assert res_exp_force_v1.exit_code != 0

    # Bad catalog instrument fails cleanly
    res_bad_comp = runner.invoke(
        cli, ["compose", "--channel-instrument", "3=not_in_catalog"]
    )
    assert res_bad_comp.exit_code != 0
    assert "not_in_catalog" in res_bad_comp.output

    # 4. ai-compose default (stdout JSON) vs catalog v2 + build-xex
    res_ai_def = runner.invoke(cli, ["ai-compose", "--provider", "mock", "--style", "action"])
    assert res_ai_def.exit_code == 0, res_ai_def.output
    ai_def_doc = json.loads(res_ai_def.stdout)
    assert all("catalog_id" not in i or i["catalog_id"] is None for i in ai_def_doc["instruments"])

    ai_json = tmp_path / "ai_cat.json"
    ai_asm = tmp_path / "ai_cat.asm"
    res_ai_cat = runner.invoke(
        cli,
        [
            "ai-compose",
            "--provider", "mock",
            "--style", "action",
            "--channel-instrument", "1=bass_poly4_punch",
            "--channel-instrument", "3=lead_attack_bite",
            "--use-instrument-catalog",
            "-o", str(ai_json),
            "--output-asm", str(ai_asm),
        ],
    )
    assert res_ai_cat.exit_code == 0, res_ai_cat.output
    ai_doc = json.loads(ai_json.read_text(encoding="utf-8"))
    cids = {i.get("catalog_id") for i in ai_doc["instruments"]}
    assert "bass_poly4_punch" in cids and "lead_attack_bite" in cids
    assert "format version 2" in ai_asm.read_text(encoding="utf-8")

    if MADS.is_file():
        xex_out = tmp_path / "ai_cli_v2.xex"
        res_xex = runner.invoke(cli, ["build-xex", str(ai_json), "-o", str(xex_out)])
        assert res_xex.exit_code == 0, res_xex.output
        assert xex_out.is_file() and xex_out.stat().st_size > 1800


def test_cli_list_and_inspect_instruments_reflect_implemented_xex_v2_and_wav_v2() -> None:
    """CLI list-instruments and inspect-instrument report consistent v2 XEX & WAV capabilities."""
    runner = CliRunner()
    core_v2_iter1_ids = {
        "lead_attack_bite",
        "bass_poly4_punch",
        "perc_kick_tight",
        "perc_snare_crisp",
        "perc_hihat_closed",
        "perc_tom_pitched",
    }

    # list-instruments --target wav accepts all 6 core_v2_iter1 instruments and still blocks deferred
    res_wav = runner.invoke(cli, ["list-instruments", "--target", "wav", "--json"])
    assert res_wav.exit_code == 0, res_wav.output
    wav_rows = {row["instrument_id"]: row for row in json.loads(res_wav.stdout)["instruments"]}
    for iid in core_v2_iter1_ids:
        assert wav_rows[iid]["compatible"] is True, iid
        assert wav_rows[iid]["status"] == "FULL_HARDWARE_V2_ITER1", iid
    assert wav_rows["lead_hpf_pwm"]["compatible"] is False
    assert wav_rows["ornament_bell_arp"]["compatible"] is False

    # list-instruments --target xex_v1 keeps rejecting all 6 core_v2_iter1 instruments
    res_v1 = runner.invoke(cli, ["list-instruments", "--target", "xex_v1", "--json"])
    assert res_v1.exit_code == 0, res_v1.output
    v1_rows = {row["instrument_id"]: row for row in json.loads(res_v1.stdout)["instruments"]}
    for iid in core_v2_iter1_ids:
        assert v1_rows[iid]["compatible"] is False, iid

    # inspect-instrument reports zero false TARGET_NOT_IMPLEMENTED diagnostics for xex_v2 & wav
    res_insp = runner.invoke(cli, ["inspect-instrument", "lead_attack_bite", "--json"])
    assert res_insp.exit_code == 0, res_insp.output
    compat = json.loads(res_insp.stdout)["compatibility"]
    assert compat["xex_v1"]["compatible"] is False
    assert compat["xex_v2"]["compatible"] is True
    assert compat["xex_v2"]["diagnostics"] == []
    assert compat["wav"]["compatible"] is True
    assert compat["wav"]["diagnostics"] == []

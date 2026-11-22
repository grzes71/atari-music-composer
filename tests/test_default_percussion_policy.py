"""Regression tests for default percussion selection policy (rhytmizer_closed_hihat for v2)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner
import pytest

from atari_music.ai.client import (
    generate_music_from_composition,
    request_ai_composition,
)
from atari_music.ai.composition import compile_composition_to_pokey_ir
from atari_music.ai.prompts import build_user_prompt
from atari_music.ai.providers.base import CompositionRequest
from atari_music.ai.providers.mock import MockAICompositionProvider
from atari_music.ai.schema import AICompositionDoc
from atari_music.api import generate_music
from atari_music.cli import cli
from atari_music.constants import AUDCTL_15KHZ, DISTORTION_WHITE_NOISE
from atari_music.instruments import (
    DEFAULT_V2_PERCUSSION_INSTRUMENT_ID,
    InstrumentPlanError,
    default_percussion_instrument_id,
    load_instrument_catalog,
    select_ai_catalog_instrument_id,
)
from atari_music.ir import song_requires_v2
from atari_music.studio import InstrumentService, load_studio_composition

pytestmark = [pytest.mark.core]


def _make_offscreen_qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_planner_default_percussion_policy_v2_vs_v1_and_audctl_conflict() -> None:
    cat = load_instrument_catalog()

    assert DEFAULT_V2_PERCUSSION_INSTRUMENT_ID == "rhytmizer_closed_hihat"
    assert default_percussion_instrument_id(cat, player_version="v2") == "rhytmizer_closed_hihat"
    assert default_percussion_instrument_id(cat, player_version="auto") == "rhytmizer_closed_hihat"
    assert default_percussion_instrument_id(cat, player_version="v1") is None
    assert (
        default_percussion_instrument_id(
            cat, player_version="v2", required_audctl_bits=AUDCTL_15KHZ
        )
        is None
    )

    for role in ("percussion", "hihat", "cymbal", "noise", "drum"):
        assert select_ai_catalog_instrument_id(cat, role, player_version="v2") == "rhytmizer_closed_hihat"
    assert select_ai_catalog_instrument_id(cat, "kick", player_version="v2") == "perc_kick_tight"
    assert select_ai_catalog_instrument_id(cat, "snare", player_version="v2") == "perc_snare_crisp"
    assert select_ai_catalog_instrument_id(cat, "tom", player_version="v2") == "perc_tom_pitched"

    # Under 15 kHz AUDCTL=$01, skip rhytmizer_closed_hihat cleanly
    fallback_15k = select_ai_catalog_instrument_id(
        cat, "percussion", player_version="v2", required_audctl_bits=AUDCTL_15KHZ
    )
    assert fallback_15k != "rhytmizer_closed_hihat"
    assert fallback_15k is not None


def test_composer_v4_and_api_new_v2_default_vs_v1_and_explicit_override() -> None:
    # 1. Explicit v2 without CH4 override selects rhytmizer_closed_hihat from catalog
    res_v2 = generate_music(profile="action", seed=42, player_version="v2")
    assert res_v2.metadata.format_version == 2
    assert song_requires_v2(res_v2.pokey_ir)
    assert res_v2.pokey_ir.instruments[3].profile_id == "rhytmizer_closed_hihat"
    assert res_v2.pokey_ir.instruments[3].behavior_id == "beh_rhytmizer_closed_hihat_v2"
    assert any(p["instrument_id"] == "rhytmizer_closed_hihat" for p in res_v2.metadata.sound_profiles)

    # 2. v1 preserves existing static percussion default (no macro downgrade/stripping)
    res_v1 = generate_music(profile="action", seed=42, player_version="v1")
    assert res_v1.metadata.format_version == 1
    assert song_requires_v2(res_v1.pokey_ir) == []
    assert res_v1.pokey_ir.instruments[3].profile_id is None
    assert res_v1.pokey_ir.instruments[3].macro is None
    assert res_v1.pokey_ir.instruments[3].distortion == DISTORTION_WHITE_NOISE

    # 3. Auto without catalog assignments preserves v1 compatibility
    res_auto = generate_music(profile="action", seed=42, player_version="auto")
    assert res_auto.metadata.format_version == 1
    assert song_requires_v2(res_auto.pokey_ir) == []

    # 4. v2 song where user assigns CH3 only -> unassigned CH4 defaults to rhytmizer_closed_hihat
    res_ch3_only = generate_music(
        profile="action",
        seed=42,
        channel_instruments={3: "lead_attack_bite"},
        player_version="auto",
    )
    assert res_ch3_only.metadata.format_version == 2
    ch4_ids = {p["instrument_id"] for p in res_ch3_only.metadata.sound_profiles}
    assert "lead_attack_bite" in ch4_ids
    assert "rhytmizer_closed_hihat" in ch4_ids

    # 5. Explicit user CH4 selection overrides default
    res_override = generate_music(
        profile="action",
        seed=42,
        channel_instruments={4: "perc_snare_crisp"},
        player_version="v2",
    )
    ids_override = {p["instrument_id"] for p in res_override.metadata.sound_profiles}
    assert "perc_snare_crisp" in ids_override
    assert "rhytmizer_closed_hihat" not in ids_override

    # 6. CH1 using 15 kHz ($01) skips incompatible default without raising AUDCTL conflict
    res_15k = generate_music(
        profile="action",
        seed=42,
        channel_instruments={1: "bass_15khz_pure"},
        player_version="v2",
    )
    ids_15k = {p["instrument_id"] for p in res_15k.metadata.sound_profiles}
    assert "bass_15khz_pure" in ids_15k
    assert "rhytmizer_closed_hihat" not in ids_15k

    # 7. Explicit rhytmizer_closed_hihat with player_version="v1" fails with clear diagnostic
    with pytest.raises(InstrumentPlanError, match="core_v2_iter1|BEHAVIOR_NOT_IN_TARGET_TIER|xex_v1"):
        generate_music(
            profile="action",
            seed=42,
            channel_instruments={4: "rhytmizer_closed_hihat"},
            player_version="v1",
        )


def test_ai_generation_v2_default_v1_fallback_and_explicit_override() -> None:
    # 1. Explicit player_version="v2" activates v2 catalog generation with rhytmizer_closed_hihat
    req_v2 = CompositionRequest(style="action", duration_seconds=12, bpm=138, player_version="v2")
    prompt_v2 = build_user_prompt(req_v2)
    assert "rhytmizer_closed_hihat" in prompt_v2

    doc_v2 = request_ai_composition(req_v2, provider_name="mock")
    cids_v2 = [i.catalog_id for i in doc_v2.instruments]
    assert "rhytmizer_closed_hihat" in cids_v2
    assert "perc_hihat_closed" not in cids_v2
    res_v2 = generate_music_from_composition(doc_v2)
    assert res_v2.metadata.format_version == 2
    assert any(inst.profile_id == "rhytmizer_closed_hihat" for inst in res_v2.pokey_ir.instruments)

    # 2. Explicit CH4 override takes precedence in AI catalog mode
    req_ov = CompositionRequest(
        style="action",
        duration_seconds=12,
        channel_instruments={4: "perc_tom_pitched"},
        enable_catalog_instruments=True,
    )
    doc_ov = request_ai_composition(req_ov, provider_name="mock")
    cids_ov = {i.catalog_id for i in doc_ov.instruments}
    assert "perc_tom_pitched" in cids_ov
    assert "rhytmizer_closed_hihat" not in cids_ov

    # 3. player_version="v1" keeps v1-compatible output without v2 macro percussion
    req_v1 = CompositionRequest(style="action", duration_seconds=12, player_version="v1")
    doc_v1 = request_ai_composition(req_v1, provider_name="mock")
    res_v1 = generate_music_from_composition(doc_v1)
    assert res_v1.metadata.format_version == 1
    assert not any(inst.profile_id == "rhytmizer_closed_hihat" for inst in res_v1.pokey_ir.instruments)

    # 4. compile_composition_to_pokey_ir use_catalog=True vs False
    plain_dict = MockAICompositionProvider().generate_composition(
        CompositionRequest(style="action", duration_seconds=12)
    )
    plain_dict["instruments"] = [
        {"id": "lead", "name": "Lead", "character": "bright_lead"},
        {"id": "bass", "name": "Bass", "character": "bass"},
        {"id": "drums", "name": "Drums", "character": "percussion"},
    ]
    plain_doc = AICompositionDoc.model_validate(plain_dict)
    ir_cat = compile_composition_to_pokey_ir(plain_doc, use_catalog=True)
    ir_legacy = compile_composition_to_pokey_ir(plain_doc, use_catalog=False)
    assert any(i.profile_id == "rhytmizer_closed_hihat" for i in ir_cat.instruments)
    assert all(i.profile_id is None for i in ir_legacy.instruments)


def test_cli_compose_and_ai_compose_default_percussion_policy(tmp_path: Path) -> None:
    runner = CliRunner()

    # 1. CLI compose v2 -> defaults CH4 to rhytmizer_closed_hihat
    comp_v2_json = tmp_path / "cli_v2.json"
    comp_v2_asm = tmp_path / "cli_v2.asm"
    res_v2 = runner.invoke(
        cli,
        [
            "compose",
            "-p", "action",
            "-s", "42",
            "--player-version", "v2",
            "--output-json", str(comp_v2_json),
            "--output-asm", str(comp_v2_asm),
        ],
    )
    assert res_v2.exit_code == 0, res_v2.output
    assert "Format: v2" in res_v2.output
    ir_v2 = json.loads(comp_v2_json.read_text(encoding="utf-8"))
    assert any(inst.get("profile_id") == "rhytmizer_closed_hihat" for inst in ir_v2["instruments"])
    assert ".byte   1, $07, $84, $00" in comp_v2_asm.read_text(encoding="utf-8")

    # 2. CLI compose v1 -> preserves static percussion default
    comp_v1_json = tmp_path / "cli_v1.json"
    res_v1 = runner.invoke(
        cli,
        [
            "compose",
            "-p", "action",
            "-s", "42",
            "--player-version", "v1",
            "--output-json", str(comp_v1_json),
        ],
    )
    assert res_v1.exit_code == 0, res_v1.output
    assert "Format: v1" in res_v1.output
    ir_v1 = json.loads(comp_v1_json.read_text(encoding="utf-8"))
    assert all(inst.get("profile_id") != "rhytmizer_closed_hihat" for inst in ir_v1["instruments"])

    # 3. Explicit --channel-instrument overrides default
    comp_ov_json = tmp_path / "cli_ov.json"
    res_ov = runner.invoke(
        cli,
        [
            "compose",
            "-p", "action",
            "-s", "42",
            "--channel-instrument", "4=perc_kick_tight",
            "--player-version", "v2",
            "--output-json", str(comp_ov_json),
        ],
    )
    assert res_ov.exit_code == 0, res_ov.output
    ir_ov = json.loads(comp_ov_json.read_text(encoding="utf-8"))
    assert {i.get("profile_id") for i in ir_ov["instruments"]} >= {"perc_kick_tight"}
    assert "rhytmizer_closed_hihat" not in {i.get("profile_id") for i in ir_ov["instruments"]}

    # 4. Explicit rhytmizer_closed_hihat with --player-version v1 gives clear diagnostic failure
    res_bad = runner.invoke(
        cli,
        [
            "compose",
            "-p", "action",
            "-s", "42",
            "--channel-instrument", "4=rhytmizer_closed_hihat",
            "--player-version", "v1",
        ],
    )
    assert res_bad.exit_code != 0
    assert "core_v2_iter1" in res_bad.output or "v2" in res_bad.output.lower()

    # 5. CLI ai-compose --player-version v2 vs v1 vs invalid explicit v1
    ai_v2_out = tmp_path / "ai_v2.json"
    res_ai_v2 = runner.invoke(
        cli,
        ["ai-compose", "--provider", "mock", "--style", "action", "--player-version", "v2", "-o", str(ai_v2_out)],
    )
    assert res_ai_v2.exit_code == 0, res_ai_v2.output
    ai_v2_doc = json.loads(ai_v2_out.read_text(encoding="utf-8"))
    assert any(i.get("catalog_id") == "rhytmizer_closed_hihat" for i in ai_v2_doc["instruments"])

    ai_v1_out = tmp_path / "ai_v1.json"
    res_ai_v1 = runner.invoke(
        cli,
        ["ai-compose", "--provider", "mock", "--style", "action", "--player-version", "v1", "-o", str(ai_v1_out)],
    )
    assert res_ai_v1.exit_code == 0, res_ai_v1.output
    ai_v1_doc = json.loads(ai_v1_out.read_text(encoding="utf-8"))
    assert all(i.get("catalog_id") is None for i in ai_v1_doc["instruments"])

    res_ai_bad = runner.invoke(
        cli,
        [
            "ai-compose",
            "--provider", "mock",
            "--channel-instrument", "4=rhytmizer_closed_hihat",
            "--player-version", "v1",
        ],
    )
    assert res_ai_bad.exit_code != 0
    assert "core_v2_iter1" in res_ai_bad.output or "v2" in res_ai_bad.output.lower()


def test_existing_saved_compositions_loaded_without_modification(tmp_path: Path) -> None:
    # Saved legacy v1 composition
    legacy_v1 = generate_music(profile="action", seed=17, player_version="v1")
    legacy_path = tmp_path / "saved_legacy_v1.json"
    legacy_v1.save_json(legacy_path)

    # Saved v2 composition explicitly using perc_hihat_closed
    old_hh = generate_music(
        profile="action",
        seed=17,
        channel_instruments={4: "perc_hihat_closed"},
        player_version="v2",
    )
    old_hh_path = tmp_path / "saved_old_hihat_v2.json"
    old_hh.save_json(old_hh_path)

    # Saved plain AI composition without catalog_id
    plain_dict = MockAICompositionProvider().generate_composition(
        CompositionRequest(style="action", duration_seconds=12)
    )
    plain_path = tmp_path / "saved_plain_ai.json"
    plain_path.write_text(json.dumps(plain_dict, indent=2), encoding="utf-8")

    st_legacy = load_studio_composition(legacy_path)
    assert st_legacy.channels[4].initial_instrument_name == "Percussion Voice"
    assert all(i.profile_id is None for i in st_legacy.base_pokey_ir.instruments)

    st_old_hh = load_studio_composition(old_hh_path)
    assert st_old_hh.base_pokey_ir.instruments[0].profile_id == "perc_hihat_closed"
    assert "rhytmizer_closed_hihat" not in [i.profile_id for i in st_old_hh.base_pokey_ir.instruments]
    assert st_old_hh.channels[4].initial_instrument_name == "Closed Poly Hi-Hat"

    res_ai_loaded = generate_music_from_composition(plain_path)
    assert res_ai_loaded.metadata.format_version == 1
    assert all(i.profile_id is None for i in res_ai_loaded.pokey_ir.instruments)


def test_studio_new_v2_default_existing_revert_and_v1_target_switch(tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from atari_music.studio.ui.main_window import MainWindow

    app = _make_offscreen_qapp()

    # 1. Load a newly generated v2 composition into Studio MainWindow
    new_v2 = generate_music(profile="action", seed=42, player_version="v2")
    new_v2_path = tmp_path / "new_v2.json"
    new_v2.save_json(new_v2_path)

    old_v1 = generate_music(
        profile="action",
        seed=42,
        channel_instruments={4: "perc_hihat_closed"},
        player_version="v2",
    )
    old_v1_path = tmp_path / "existing_old_hh.json"
    old_v1.save_json(old_v1_path)

    win = MainWindow()
    try:
        win.load_composition_file(new_v2_path)
        app.processEvents()
        assert win.evaluation is not None
        assert win.evaluation.is_valid is True
        assert win.evaluation.effective_format_version == 2
        assert "Rhytmizer Closed Hi-Hat (V2 Macro)" in win.evaluation.channels[4].effective_instrument_label

        # Picker displays rhytmizer_closed_hihat
        picker_ids = [
            win._inspector._list.item(i).data(0x0100)  # Qt.ItemDataRole.UserRole
            for i in range(win._inspector._list.count())
        ]
        assert "rhytmizer_closed_hihat" in picker_ids

        # Switch target backend to xex_v1 -> blocks invalid unsupported instrument
        idx_v1 = win._target_combo.findData("xex_v1")
        assert idx_v1 >= 0
        win._target_combo.setCurrentIndex(idx_v1)
        app.processEvents()
        assert win.evaluation.is_valid is False
        assert win.evaluation.blocking_errors
        assert win._render_btn.isEnabled() is False

        # 2. Load existing composition, override CH4, then revert_to_original()
        win.load_composition_file(old_v1_path)
        app.processEvents()
        assert "Closed Poly Hi-Hat" in win.evaluation.channels[4].effective_instrument_label

        win.set_channel_instrument(4, "rhytmizer_closed_hihat")
        app.processEvents()
        assert "Rhytmizer Closed Hi-Hat (V2 Macro)" in win.evaluation.channels[4].effective_instrument_label

        win.revert_to_original()
        app.processEvents()
        assert "Closed Poly Hi-Hat" in win.evaluation.channels[4].effective_instrument_label
        assert win.working_config == win.state.baseline_config
    finally:
        win.close()
        app.processEvents()

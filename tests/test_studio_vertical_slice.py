"""Tests for headless Studio vertical-slice services (PySide6-free)."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import wave

import pytest

from atari_music.api import generate_music
from atari_music.studio import (
    CompositionFidelityError,
    InstrumentService,
    RenderService,
    StudioArrangementConfig,
    load_studio_composition,
)

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loader_supports_dsl_ai_json_and_ir_json_and_preserves_source(tmp_path: Path) -> None:
    # 1. Music DSL (16-bit)
    dsl_src = REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl"
    before_bytes = dsl_src.read_bytes()
    st_dsl = load_studio_composition(dsl_src)
    assert st_dsl.source_kind == "dsl"
    assert st_dsl.base_uses_16bit_bass is True
    assert st_dsl.channels[1].role == "bass"
    assert st_dsl.channels[2].active is False
    assert st_dsl.channels[3].role == "melody"
    assert st_dsl.channels[4].role == "percussion"
    assert dsl_src.read_bytes() == before_bytes

    # 2. AICompositionDoc JSON (8-bit with CH2 bass)
    af_src = REPO_ROOT / "examples" / "ai" / "action_fast.json"
    st_ai = load_studio_composition(af_src)
    assert st_ai.source_kind == "ai-composition"
    assert st_ai.base_uses_16bit_bass is False
    assert st_ai.channels[1].role == "melody"
    assert st_ai.channels[2].role == "bass"
    assert st_ai.channels[2].midi_min == 36
    assert st_ai.channels[2].midi_max == 43

    # 3. POKEY IR JSON with explicit PROGRAM_CHANGE
    ir_res = generate_music(
        profile="action",
        seed=42,
        uses_16bit_bass=False,
        channel_instruments={
            1: "bass_15khz_pure",
            2: "harmony_soft_square",
            3: "lead_pure_sustain",
            4: "perc_snare_crisp",
        },
        program_changes=[{"channel": 3, "pattern_index": 0, "note_index": 1, "instrument_id": "lead_pure_pluck"}],
        player_version="v2",
    )
    ir_path = tmp_path / "song_ir.json"
    ir_res.save_json(ir_path)
    st_ir = load_studio_composition(ir_path)
    assert st_ir.source_kind == "pokey-ir"
    assert st_ir.channels[3].has_program_changes is True
    assert st_ir.channels[3].program_change_count >= 1
    assert st_ir.base_v1_compatible is False


def test_loader_rejects_lossy_mid_channel_instrument_switches(tmp_path: Path) -> None:
    lossy_doc = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {"title": "Switch Test", "key": "A", "mode": "minor", "bpm": 120},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [
            {"id": "lead_a", "name": "Lead A", "character": "bright_lead"},
            {"id": "lead_b", "name": "Lead B", "character": "dark"},
        ],
        "patterns": [
            {
                "id": "A",
                "length_steps": 8,
                "channels": {
                    "1": [
                        {"step": 0, "note": "A4", "instrument": "lead_a", "duration": 4, "volume": 12},
                        {"step": 4, "note": "C5", "instrument": "lead_b", "duration": 4, "volume": 12},
                    ]
                },
            }
        ],
        "sequence": ["A"],
    }
    p = tmp_path / "lossy.json"
    p.write_text(json.dumps(lossy_doc), encoding="utf-8")

    with pytest.raises(CompositionFidelityError, match="silent"):
        load_studio_composition(p)


def test_loader_preserves_catalog_program_changes_in_ai_composition(tmp_path: Path) -> None:
    cat_doc = {
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {"title": "Catalog PC Test", "key": "A", "mode": "minor", "bpm": 120},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [
            {"id": "lead_a", "name": "Lead A", "character": "bright_lead", "catalog_id": "lead_pure_sustain"},
            {"id": "lead_b", "name": "Lead B", "character": "bright_lead", "catalog_id": "lead_pure_pluck"},
        ],
        "patterns": [
            {
                "id": "A",
                "length_steps": 8,
                "channels": {
                    "1": [
                        {"step": 0, "note": "A4", "instrument": "lead_a", "duration": 4, "volume": 12},
                        {"step": 4, "note": "C5", "instrument": "lead_b", "duration": 4, "volume": 12},
                    ]
                },
            }
        ],
        "sequence": ["A"],
    }
    p = tmp_path / "catalog_pc.json"
    p.write_text(json.dumps(cat_doc), encoding="utf-8")

    state = load_studio_composition(p)
    assert state.channels[1].has_program_changes is True
    assert state.channels[1].program_change_count == 1
    assert state.channels[1].distinct_instruments_count == 2


def test_instrument_service_dynamic_ch2_lock_and_runtime_validation() -> None:
    svc = InstrumentService()

    # 16-bit DSL -> CH2 is locked by baseline 16-bit pair
    st_16 = load_studio_composition(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
    eval_base = svc.evaluate_arrangement(st_16, st_16.baseline_config)
    assert eval_base.is_valid is True
    assert eval_base.channels[2].available_for_assignment is False
    assert eval_base.channels[2].lock_reason is not None

    # Assigning CH2 directly while CH1 stays 16-bit fails validation
    bad_cfg = st_16.baseline_config.with_channel(2, "harmony_soft_square")
    eval_bad = svc.evaluate_arrangement(st_16, bad_cfg, include_catalog_options=False)
    assert eval_bad.is_valid is False
    assert any("Channel 2" in err or "16-bit" in err for err in eval_bad.blocking_errors)

    # Assigning 8-bit bass profile on CH1 when CH2 has NO notes unlocks CH2 dynamically via divider_mode
    cfg_8bit_override = st_16.baseline_config.with_channel(1, "bass_15khz_pure")
    eval_unlocked = svc.evaluate_arrangement(st_16, cfg_8bit_override, include_catalog_options=False)
    assert eval_unlocked.is_valid is True
    assert eval_unlocked.effective_uses_16bit_bass is False
    assert eval_unlocked.channels[2].available_for_assignment is True

    # 8-bit song WITH CH2 notes: assigning 16bit_ch12 on CH1 is rejected by runtime/planner
    st_8 = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    cfg_conflict_16 = st_8.baseline_config.with_channel(1, "bass_16bit_pure")
    eval_conflict = svc.evaluate_arrangement(st_8, cfg_conflict_16, include_catalog_options=False)
    assert eval_conflict.is_valid is False
    assert eval_conflict.blocking_errors

    # v1 player rejects core_v2_iter1 profile
    cfg_v1_err = st_8.baseline_config.with_channel(4, "perc_snare_crisp").model_copy(
        update={"player_version": "v1"}
    )
    eval_v1_err = svc.evaluate_arrangement(st_8, cfg_v1_err, include_catalog_options=False)
    assert eval_v1_err.is_valid is False
    assert eval_v1_err.blocking_errors


def test_render_service_caches_validates_and_preserves_program_changes(tmp_path: Path) -> None:
    svc = InstrumentService()
    renderer = RenderService(svc)
    try:
        # Build IR song with PROGRAM_CHANGE on CH3
        ir_res = generate_music(
            profile="action",
            seed=11,
            uses_16bit_bass=False,
            channel_instruments={
                1: "bass_15khz_pure",
                2: "harmony_soft_square",
                3: "lead_pure_sustain",
                4: "perc_snare_crisp",
            },
            program_changes=[{"channel": 3, "pattern_index": 0, "note_index": 1, "instrument_id": "lead_pure_pluck"}],
            player_version="v2",
        )
        ir_path = tmp_path / "pc_song.json"
        ir_res.save_json(ir_path)
        state = load_studio_composition(ir_path)
        snapshot_before = copy.deepcopy(state.base_pokey_ir.model_dump(mode="json"))

        # Override CH1 while leaving CH3 PROGRAM_CHANGE untouched -> preserved
        cfg_a = state.baseline_config.with_channel(1, "bass_poly4_punch")
        assert renderer.get_cached(state, cfg_a) is None

        entry1 = renderer.render_preview(state, cfg_a)
        assert entry1.from_cache is False
        assert entry1.wav_path.is_file()
        assert entry1.wav_path.stat().st_size > 44
        with wave.open(str(entry1.wav_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 44100
            assert wf.getnframes() > 0

        # Original baseline immutable
        assert state.base_pokey_ir.model_dump(mode="json") == snapshot_before

        # Repeat render -> instant cache hit
        entry2 = renderer.render_preview(state, cfg_a)
        assert entry2.from_cache is True
        assert entry2.wav_path == entry1.wav_path

        # Changing policy invalidates cache key cleanly
        cfg_b = cfg_a.model_copy(update={"program_change_policy": "remove"})
        assert renderer.build_cache_key(state, cfg_a).digest() != renderer.build_cache_key(state, cfg_b).digest()

        # Invalid configuration must refuse to render
        invalid_cfg = state.baseline_config.model_copy(update={"player_version": "v1"})
        with pytest.raises(ValueError, match="Cannot render invalid configuration"):
            renderer.render_preview(state, invalid_cfg)
    finally:
        renderer.cleanup()
        assert not renderer.cache_dir.exists()


def test_headless_backend_never_imports_pyside6() -> None:
    """Assert headless studio backend modules have zero PySide6 or studio.ui imports."""
    studio_dir = REPO_ROOT / "src" / "atari_music" / "studio"
    for py_file in sorted(studio_dir.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("PySide6"), py_file.name
                    assert "studio.ui" not in alias.name, py_file.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("PySide6"), py_file.name
                assert "studio.ui" not in node.module, py_file.name

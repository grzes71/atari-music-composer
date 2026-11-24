"""Tests for headless Studio XEX export, validation, and atomic commit (PySide6-free)."""

from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path
import struct

import pytest

from atari_music import xex_layout
from atari_music.api import generate_music
from atari_music.instruments.planner import LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION
from atari_music.instruments.runtime import (
    TARGET_SAP_V1_PLANNED,
    TARGET_SAP_V2_ITER1_PLANNED,
    TARGET_V1_XEX,
    TARGET_V2_ITER1_XEX,
    TARGET_WAV_PREVIEW,
    POKEYRuntime,
    ChannelAssignmentRequest,
    RuntimeDiagnostic,
)
from atari_music.ir import IRInstrument, IRNote, IRPattern, IRSong
from atari_music.studio import (
    ExportService,
    InstrumentService,
    RenderService,
    StudioArrangementConfig,
    XexExportOptions,
    load_studio_composition,
    parse_atari_address,
)
from atari_music.studio.exporter import _commit_staged_pairs
import atari_music.studio.instruments as studio_instruments_mod
from atari_music.xex_layout import XexLayoutError
from conftest import require_local_artifact

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS_EXE = REPO_ROOT / "tools" / "mads" / "mads.exe"
PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"


def _minimal_valid_xex(
    player_addr: int = 0x6000,
    music_addr: int = 0x8000,
) -> bytes:
    p_bytes = b"\x00" * 16
    m_bytes = b"\x01" * 16
    r_bytes = struct.pack("<H", player_addr)

    def _blk(start: int, payload: bytes, mark: bool = False) -> bytes:
        end = start + len(payload) - 1
        hdr = struct.pack("<HH", start, end)
        return (b"\xff\xff" if mark else b"") + hdr + payload

    return (
        _blk(player_addr, p_bytes, mark=True)
        + _blk(music_addr, m_bytes)
        + _blk(0x02E0, r_bytes)
    )


def _create_fake_mads(tmp_path: Path) -> Path:
    fake = tmp_path / ("fake_mads.cmd" if os.name == "nt" else "fake_mads.sh")
    fake.write_text("# stub mads placeholder\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(fake, 0o755)
    return fake


def _write_wav_only_catalog(tmp_path: Path) -> Path:
    base_cat = json.loads(
        (REPO_ROOT / "src" / "atari_music" / "instruments" / "catalog.json").read_text("utf-8")
    )
    base_cat["behaviors"].append(
        {
            "behavior_id": "beh_wav_only_contour_test",
            "version": 1,
            "required_runtime_tier": "wav_only",
            "modulation_mode": "none",
            "uses_wav_only_contour": True,
            "allow_per_note_switch": False,
        }
    )
    base_cat["instruments"].append(
        {
            "instrument_id": "lead_wav_contour_test",
            "display_name": "WAV Contour Test Lead",
            "version": "1.0",
            "family": "lead",
            "intended_roles": ["melody"],
            "base_distortion": 160,
            "envelope": {
                "attack_frames": 2,
                "decay_frames": 2,
                "sustain_vol": 10,
                "release_frames": 2,
                "peak_vol": 14,
            },
            "waveform_family": "pure",
            "hardware_constraints": {
                "divider_mode": "8bit",
                "preferred_clock_hz": "64khz",
                "required_audctl_bits": 0,
                "forbidden_audctl_bits": 0,
                "poly4_safe_tuning": False,
                "midi_range": [48, 96],
                "channels_allowed": [1, 2, 3, 4],
            },
            "behavior_id": "beh_wav_only_contour_test",
            "provenance": {
                "source_kind": "sound_design_demo",
                "notes": "Synthetic wav_only profile for XEX refusal testing.",
            },
        }
    )
    cat_path = tmp_path / "catalog_with_wav_only.json"
    cat_path.write_text(json.dumps(base_cat, indent=2), encoding="utf-8")
    return cat_path


def _make_ir_json_with_pc(tmp_path: Path) -> Path:
    res = generate_music(
        profile="action",
        seed=7,
        uses_16bit_bass=False,
        channel_instruments={
            1: "bass_15khz_pure",
            2: "harmony_soft_square",
            3: "lead_pure_sustain",
            4: "perc_snare_crisp",
        },
        program_changes=[
            {"channel": 3, "pattern_index": 0, "note_index": 1, "instrument_id": "lead_pure_pluck"}
        ],
        player_version="v2",
    )
    p = tmp_path / "ir_pc.json"
    res.save_json(p)
    return p


def _make_contoured_ir_json(tmp_path: Path) -> Path:
    song = IRSong(
        title="Contoured Test",
        author="Test",
        tempo_bpm=120,
        frames_per_tick=12,
        uses_16bit_bass=False,
        instruments=[
            IRInstrument(id=0, name="Bass", distortion=0xA0),
            IRInstrument(id=1, name="Harm", distortion=0xA0),
            IRInstrument(id=2, name="ContouredLead", distortion=0xA0, volume_contour=(14, 10, 6)),
            IRInstrument(id=3, name="Perc", distortion=0x80),
        ],
        patterns=[
            IRPattern(
                id=0,
                name="A",
                rows=2,
                tracks={
                    1: [IRNote(audf=0x40, duration_ticks=2, volume=10, instrument_id=0)],
                    2: [IRNote(audf=0x30, duration_ticks=2, volume=8, instrument_id=1)],
                    3: [IRNote(audf=0x20, duration_ticks=2, volume=12, instrument_id=2)],
                    4: [IRNote(audf=0x10, duration_ticks=2, volume=10, instrument_id=3)],
                },
            )
        ],
        sequence=[0],
    )
    p = tmp_path / "contoured.json"
    song.to_json_file(p)
    return p


def test_parse_atari_address_and_zp_options() -> None:
    assert parse_atari_address("$6000") == 0x6000
    assert parse_atari_address("0x8000") == 0x8000
    assert parse_atari_address("24576") == 0x6000
    assert parse_atari_address(0x0400) == 0x0400

    with pytest.raises(ValueError):
        parse_atari_address("")
    with pytest.raises(ValueError):
        parse_atari_address("$ZZZZ")
    with pytest.raises(ValueError):
        parse_atari_address(True)
    with pytest.raises(ValueError):
        parse_atari_address("$10000")

    # Segment bounds ($0400-$BFFF / $C000+) are syntactically accepted by XexExportOptions so
    # xex_layout.validate_xex_layout remains the single authority for segment memory checks.
    opts_rom = XexExportOptions(output_path=Path("out.xex"), player_address="$C000", music_address="")
    assert opts_rom.player_address == 0xC000
    assert opts_rom.music_address is None

    # ZP equate bounds are enforced pre-compile ($80-$F2 for PLAYER_ZP_BASE+0..13)
    with pytest.raises(ValueError, match="Zero Page"):
        XexExportOptions(output_path=Path("out.xex"), zp_base="$7F")
    with pytest.raises(ValueError, match="Zero Page"):
        XexExportOptions(output_path=Path("out.xex"), zp_base="$F3")


def test_player_version_auto_v1_v2_resolution_and_rejection(tmp_path: Path) -> None:
    svc = InstrumentService()
    exporter = ExportService(svc)
    state = load_studio_composition(_make_ir_json_with_pc(tmp_path))

    # 1. With preserved PROGRAM_CHANGE and player_version='auto', resolves to v2
    prep_auto_v2 = exporter.prepare_xex_export(
        state, state.baseline_config.model_copy(update={"player_version": "auto"})
    )
    assert prep_auto_v2.is_exportable is True
    assert prep_auto_v2.effective_format_version == 2
    assert prep_auto_v2.resolved_target_backend == "xex_v2"

    # 2. Removing PROGRAM_CHANGE and setting core_v1 instruments lets 'auto' resolve to v1!
    cfg_v1_auto = StudioArrangementConfig(
        channel_instruments={
            1: "bass_15khz_pure",
            2: "harmony_soft_square",
            3: "lead_pure_sustain",
            4: "lead_pure_pluck",
        },
        program_change_policy="remove",
        player_version="auto",
    )
    prep_auto_v1 = exporter.prepare_xex_export(state, cfg_v1_auto)
    assert prep_auto_v1.is_exportable is True
    assert prep_auto_v1.effective_format_version == 1
    assert prep_auto_v1.resolved_target_backend == "xex_v1"

    # 3. Explicit player_version='v1' when v2 features remain must be refused
    prep_bad_v1 = exporter.prepare_xex_export(
        state, state.baseline_config.model_copy(update={"player_version": "v1"})
    )
    assert prep_bad_v1.is_exportable is False
    assert prep_bad_v1.blocking_errors


def test_wav_only_rejected_even_when_target_backend_is_wav(tmp_path: Path) -> None:
    cat_path = _write_wav_only_catalog(tmp_path)
    svc = InstrumentService(catalog_path=cat_path)
    exporter = ExportService(svc)
    state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")

    # target_backend='wav' with wav_only instrument must be refused for XEX
    cfg_wav_only = StudioArrangementConfig(
        channel_instruments={1: "lead_wav_contour_test", 2: "bass_15khz_pure", 3: None, 4: None},
        target_backend="wav",
        player_version="auto",
    )
    prep_blocked = exporter.prepare_xex_export(state, cfg_wav_only)
    assert prep_blocked.is_exportable is False
    assert any("wav_only" in err or "WAV_ONLY" in err for err in prep_blocked.blocking_errors)

    # target_backend='wav' with XEX-compatible instruments succeeds for XEX export preparation
    cfg_wav_target_xex_ok = StudioArrangementConfig(
        channel_instruments={1: "lead_pure_sustain", 2: "bass_15khz_pure", 3: None, 4: None},
        target_backend="wav",
        player_version="auto",
    )
    prep_ok = exporter.prepare_xex_export(state, cfg_wav_target_xex_ok)
    assert prep_ok.is_exportable is True
    assert prep_ok.effective_format_version == 1


def test_volume_contour_validated_after_arrangement(tmp_path: Path) -> None:
    svc = InstrumentService()
    exporter = ExportService(svc)
    state = load_studio_composition(_make_contoured_ir_json(tmp_path))

    # Contoured original IR instrument retained when CH3 left unassigned -> refused
    prep_retained = exporter.prepare_xex_export(state, state.baseline_config)
    assert prep_retained.is_exportable is False
    assert any("contour" in e.lower() for e in prep_retained.blocking_errors)

    # Overriding CH3 with clean catalog instrument + policy='remove' clears contour -> exportable
    cfg_cleaned = StudioArrangementConfig(
        channel_instruments={1: None, 2: None, 3: "lead_pure_sustain", 4: None},
        program_change_policy="remove",
        player_version="auto",
    )
    prep_clean = exporter.prepare_xex_export(state, cfg_cleaned)
    assert prep_clean.is_exportable is True


def test_xex_v2_implemented_no_false_stage_a_warning_and_genuine_warnings_preserved(
    tmp_path: Path,
) -> None:
    # 1. Stale Stage-A workaround helper is removed; TARGET_V2_ITER1_XEX is genuinely implemented
    assert not hasattr(studio_instruments_mod, "_is_stale_stage_a_xex_v2_notice")
    assert TARGET_V2_ITER1_XEX.is_implemented is True
    assert TARGET_SAP_V1_PLANNED.is_implemented is False
    assert TARGET_SAP_V2_ITER1_PLANNED.is_implemented is False

    svc = InstrumentService()
    exporter = ExportService(svc)

    # 2. Opening a v1 composition with target_backend='xex_v2' emits zero TARGET_NOT_IMPLEMENTED warnings
    v1_state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    v1_eval = svc.evaluate_arrangement(v1_state, v1_state.baseline_config)
    assert v1_eval.is_valid is True
    assert not any(d.code == "TARGET_NOT_IMPLEMENTED" for d in v1_eval.diagnostics)
    assert not any("not yet implemented" in w.lower() for w in v1_eval.warnings)

    # 3. Opening a v2 composition with target_backend='xex_v2' emits zero TARGET_NOT_IMPLEMENTED warnings
    v2_state = load_studio_composition(_make_ir_json_with_pc(tmp_path))
    v2_eval = svc.evaluate_arrangement(v2_state, v2_state.baseline_config)
    assert v2_eval.is_valid is True
    assert v2_eval.effective_format_version == 2
    assert not any(d.code == "TARGET_NOT_IMPLEMENTED" for d in v2_eval.diagnostics)
    assert not any("not yet implemented" in w.lower() for w in v2_eval.warnings)

    # 4. On an arrangement triggering xex_v2 + MIDI_RANGE_EXCEEDED:
    # evaluate_arrangement() and prepare_xex_export() agree — zero TARGET_NOT_IMPLEMENTED,
    # while genuine MIDI_RANGE_EXCEEDED warning remains visible in both!
    cfg = StudioArrangementConfig(
        channel_instruments={1: None, 2: "lead_attack_bite", 3: None, 4: None},
        player_version="auto",
        target_backend="xex_v2",
    )
    ev = svc.evaluate_arrangement(v1_state, cfg, include_catalog_options=False)
    prep = exporter.prepare_xex_export(v1_state, cfg)
    assert ev.is_valid is True and prep.is_exportable is True
    assert ev.effective_format_version == 2 and prep.effective_format_version == 2
    assert not any(d.code == "TARGET_NOT_IMPLEMENTED" for d in ev.diagnostics)
    assert not any(d.code == "TARGET_NOT_IMPLEMENTED" for d in prep.diagnostics)
    assert any(d.code == "MIDI_RANGE_EXCEEDED" for d in ev.diagnostics)
    assert any(d.code == "MIDI_RANGE_EXCEEDED" for d in prep.diagnostics)
    assert any("MIDI span" in w for w in ev.warnings)
    assert any("MIDI span" in w for w in prep.warnings)

    # 5. Genuine unimplemented SAP targets still emit TARGET_NOT_IMPLEMENTED
    rep_sap = POKEYRuntime.resolve(
        [ChannelAssignmentRequest(channel=3, instrument_ids=("lead_pure_sustain",))],
        svc.catalog,
        TARGET_SAP_V2_ITER1_PLANNED,
    )
    assert any(d.code == "TARGET_NOT_IMPLEMENTED" and d.severity == "WARNING" for d in rep_sap.diagnostics)


def test_selector_consistency_target_backend_vs_player_version_and_wav_separation(
    tmp_path: Path,
) -> None:
    svc = InstrumentService()
    exporter = ExportService(svc)
    v2_state = load_studio_composition(_make_ir_json_with_pc(tmp_path))

    # 1. target_backend='xex_v1' + player_version='auto' narrows strictly to v1 in BOTH
    # evaluate_arrangement() and ExportService.prepare_xex_export() (rejects v2 PC song!)
    cfg_xex_v1_auto = StudioArrangementConfig(
        channel_instruments={1: None, 2: None, 3: None, 4: None},
        program_change_policy="preserve",
        player_version="auto",
        target_backend="xex_v1",
    )
    ev_v1_auto = svc.evaluate_arrangement(v2_state, cfg_xex_v1_auto, include_catalog_options=False)
    prep_v1_auto = exporter.prepare_xex_export(v2_state, cfg_xex_v1_auto)
    assert ev_v1_auto.is_valid is False
    assert prep_v1_auto.is_exportable is False
    assert ev_v1_auto.blocking_errors and prep_v1_auto.blocking_errors

    # 2. Contradictory target_backend='xex_v1' + player_version='v2' is rejected with TARGET_FORMAT_CONFLICT
    # in BOTH evaluate_arrangement() and prepare_xex_export()
    v1_state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    cfg_conflict = StudioArrangementConfig(
        channel_instruments={1: None, 2: None, 3: None, 4: None},
        player_version="v2",
        target_backend="xex_v1",
    )
    ev_conflict = svc.evaluate_arrangement(v1_state, cfg_conflict, include_catalog_options=False)
    prep_conflict = exporter.prepare_xex_export(v1_state, cfg_conflict)
    assert ev_conflict.is_valid is False
    assert prep_conflict.is_exportable is False
    assert any(d.code == "TARGET_FORMAT_CONFLICT" for d in ev_conflict.diagnostics)
    assert any(d.code == "TARGET_FORMAT_CONFLICT" for d in prep_conflict.diagnostics)

    # 3. target_backend='xex_v2' + player_version='v1' narrows to xex_v1 consistently
    cfg_v2_force_v1 = StudioArrangementConfig(
        channel_instruments={1: None, 2: None, 3: "lead_attack_bite", 4: None},
        player_version="v1",
        target_backend="xex_v2",
    )
    ev_v2_v1 = svc.evaluate_arrangement(v1_state, cfg_v2_force_v1, include_catalog_options=False)
    prep_v2_v1 = exporter.prepare_xex_export(v1_state, cfg_v2_force_v1)
    assert ev_v2_v1.is_valid is False
    assert prep_v2_v1.is_exportable is False

    # 4. Contoured IR song: under target_backend='xex_v2', evaluate_arrangement() AGREES with
    # prepare_xex_export() and blocks; under target_backend='wav', WAV preview stays valid (with warning)
    # while prepare_xex_export() still rejects XEX export!
    contoured_state = load_studio_composition(_make_contoured_ir_json(tmp_path))
    cfg_xex_contour = contoured_state.baseline_config.model_copy(update={"target_backend": "xex_v2"})
    ev_xex_c = svc.evaluate_arrangement(contoured_state, cfg_xex_contour, include_catalog_options=False)
    prep_xex_c = exporter.prepare_xex_export(contoured_state, cfg_xex_contour)
    assert ev_xex_c.is_valid is False
    assert prep_xex_c.is_exportable is False
    assert any("contour" in e.lower() for e in ev_xex_c.blocking_errors)

    cfg_wav_contour = contoured_state.baseline_config.model_copy(update={"target_backend": "wav"})
    ev_wav_c = svc.evaluate_arrangement(contoured_state, cfg_wav_contour, include_catalog_options=False)
    prep_wav_c = exporter.prepare_xex_export(contoured_state, cfg_wav_contour)
    assert ev_wav_c.is_valid is True
    assert any(d.code == "WAV_PREVIEW_ONLY_NOT_XEX_EXPORTABLE" for d in ev_wav_c.diagnostics)
    assert prep_wav_c.is_exportable is False

    # 5. wav_only catalog profile under target_backend='wav': valid for Studio evaluation & WAV preview,
    # strictly blocked for XEX export!
    cat_path = _write_wav_only_catalog(tmp_path)
    wav_svc = InstrumentService(catalog_path=cat_path)
    wav_exporter = ExportService(wav_svc)
    wav_renderer = RenderService(wav_svc)
    try:
        cfg_wav_only = StudioArrangementConfig(
            channel_instruments={1: "lead_wav_contour_test", 2: "bass_15khz_pure", 3: None, 4: None},
            target_backend="wav",
            player_version="auto",
        )
        ev_wo = wav_svc.evaluate_arrangement(v1_state, cfg_wav_only, include_catalog_options=False)
        assert ev_wo.is_valid is True
        assert any(d.code == "WAV_PREVIEW_ONLY_NOT_XEX_EXPORTABLE" for d in ev_wo.diagnostics)
        entry = wav_renderer.render_preview(v1_state, cfg_wav_only)
        assert entry.wav_path.is_file() and entry.wav_path.stat().st_size > 44
        prep_wo = wav_exporter.prepare_xex_export(v1_state, cfg_wav_only)
        assert prep_wo.is_exportable is False
    finally:
        wav_renderer.cleanup()


def test_studio_vibrato_promotion_emits_explicit_warning_in_eval_and_export(
    tmp_path: Path,
) -> None:
    # Legacy v1 song from generate_music carries vibrato_depth/vibrato_speed on CH3 lead
    legacy_res = generate_music(profile="action", seed=42)
    ir_path = tmp_path / "legacy_vib.json"
    legacy_res.save_json(ir_path)
    state = load_studio_composition(ir_path)

    svc = InstrumentService()
    exporter = ExportService(svc)

    # Promoting to v2 via CH4 percussion triggers explicit LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION warning
    cfg_promote = StudioArrangementConfig(
        channel_instruments={1: None, 2: None, 3: None, 4: "perc_kick_tight"},
        player_version="auto",
        target_backend="xex_v2",
    )
    ev = svc.evaluate_arrangement(state, cfg_promote, include_catalog_options=False)
    prep = exporter.prepare_xex_export(state, cfg_promote)
    assert ev.is_valid is True and prep.is_exportable is True
    assert ev.effective_format_version == 2 and prep.effective_format_version == 2
    for diags, warns in ((ev.diagnostics, ev.warnings), (prep.diagnostics, prep.warnings)):
        vib_diags = [d for d in diags if d.code == LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION]
        assert len(vib_diags) == 1
        assert vib_diags[0].severity == "WARNING"
        assert vib_diags[0].channel == 3
        assert "vibrato_depth" in vib_diags[0].message
        assert "vibrato_speed" in vib_diags[0].message
        assert "v2 Iter 1" in vib_diags[0].message
        assert any("vibrato" in w.lower() for w in warns)

    # Staying in v1 (core_v1 override on CH4) preserves vibrato with zero vibrato warning
    cfg_stay_v1 = StudioArrangementConfig(
        channel_instruments={1: None, 2: None, 3: None, 4: "lead_pure_pluck"},
        player_version="auto",
        target_backend="xex_v2",
    )
    ev_v1 = svc.evaluate_arrangement(state, cfg_stay_v1, include_catalog_options=False)
    prep_v1 = exporter.prepare_xex_export(state, cfg_stay_v1)
    assert ev_v1.is_valid is True and prep_v1.is_exportable is True
    assert ev_v1.effective_format_version == 1 and prep_v1.effective_format_version == 1
    assert not any(d.code == LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION for d in ev_v1.diagnostics)
    assert not any(d.code == LEGACY_VIBRATO_STRIPPED_ON_V2_PROMOTION for d in prep_v1.diagnostics)


def test_single_arranged_ir_preserves_pc_and_source_immutability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import atari_music.studio.exporter as exporter_mod
    from atari_music.api import MusicGenerationResult

    svc = InstrumentService()
    exporter = ExportService(svc)
    state = load_studio_composition(_make_ir_json_with_pc(tmp_path))
    before_snapshot = copy.deepcopy(state.base_pokey_ir.model_dump(mode="json"))

    arrange_calls = 0
    real_arrange = exporter_mod.arrange_song

    def _spy_arrange(*args, **kwargs):
        nonlocal arrange_calls
        arrange_calls += 1
        return real_arrange(*args, **kwargs)

    monkeypatch.setattr(exporter_mod, "arrange_song", _spy_arrange)

    built_ir_ids: list[int] = []
    seen_pending_pcs: list[int] = []

    def _stub_build_xex(self, output_path, **kwargs):
        built_ir_ids.append(id(self.pokey_ir))
        pcs = [
            n
            for pat in self.pokey_ir.patterns
            for n in pat.tracks.get(3, ())
            if n.pending_program_changes
        ]
        seen_pending_pcs.append(len(pcs))
        out_p = Path(output_path)
        out_p.write_bytes(_minimal_valid_xex())
        if kwargs.get("keep_asm", True):
            out_p.with_suffix(".asm").write_text("; mock asm\n", encoding="utf-8")
        return out_p

    monkeypatch.setattr(MusicGenerationResult, "build_xex", _stub_build_xex)

    cfg = state.baseline_config.with_channel(1, "bass_poly4_punch")
    out_xex = tmp_path / "single_source.xex"
    fake_mads = _create_fake_mads(tmp_path)

    res = exporter.export_xex(
        state,
        cfg,
        XexExportOptions(output_path=out_xex, mads_bin=fake_mads, player_asm=PLAYER_ASM),
    )
    assert arrange_calls == 1
    assert len(built_ir_ids) == 1
    assert seen_pending_pcs[0] >= 1
    assert res.xex_path.is_file()
    assert res.asm_path is not None and res.asm_path.is_file()
    assert state.base_pokey_ir.model_dump(mode="json") == before_snapshot


def test_missing_mads_or_player_asm_preflight_creates_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = InstrumentService()
    exporter = ExportService(svc)
    state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    out_xex = tmp_path / "should_not_exist.xex"

    # Missing MADS
    monkeypatch.setattr(
        "atari_music.studio.exporter.resolve_default_mads_path", lambda: None
    )
    with pytest.raises(FileNotFoundError, match="MADS"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(output_path=out_xex, mads_bin=tmp_path / "missing_mads.exe"),
        )
    assert not out_xex.exists()

    # Missing player.asm
    fake_mads = _create_fake_mads(tmp_path)
    with pytest.raises(FileNotFoundError, match="player.asm"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(
                output_path=out_xex,
                mads_bin=fake_mads,
                player_asm=tmp_path / "missing_player.asm",
            ),
        )
    assert not out_xex.exists()


def test_safe_multi_file_commit_overwrite_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from atari_music.api import MusicGenerationResult

    svc = InstrumentService()
    exporter = ExportService(svc)
    state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    fake_mads = _create_fake_mads(tmp_path)

    out_xex = tmp_path / "song.xex"
    out_asm = tmp_path / "song.asm"
    orig_xex_bytes = b"ORIGINAL_XEX_BYTES"
    orig_asm_text = "; ORIGINAL_ASM_CONTENT\n"
    out_xex.write_bytes(orig_xex_bytes)
    out_asm.write_text(orig_asm_text, encoding="utf-8")

    # 1. Validation failure (XexLayoutError) preserves pre-existing .xex and .asm untouched
    def _fail_layout(self, output_path, **kwargs):
        raise XexLayoutError("Simulated ROM overlap $C000")

    monkeypatch.setattr(MusicGenerationResult, "build_xex", _fail_layout)
    with pytest.raises(XexLayoutError):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(output_path=out_xex, keep_asm=True, mads_bin=fake_mads, player_asm=PLAYER_ASM),
        )
    assert out_xex.read_bytes() == orig_xex_bytes
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text

    # 2. Succeed build_xex in staging, then test failures at EACH commit step
    new_xex_bytes = _minimal_valid_xex()
    new_asm_text = "; NEW_ASM_CONTENT\n"

    def _ok_build(self, output_path, **kwargs):
        p = Path(output_path)
        p.write_bytes(new_xex_bytes)
        if kwargs.get("keep_asm", True):
            p.with_suffix(".asm").write_text(new_asm_text, encoding="utf-8")
        return p

    monkeypatch.setattr(MusicGenerationResult, "build_xex", _ok_build)

    # 2a. Simulate failure during backup of second file (.asm) after .xex was backed up
    real_replace = os.replace

    def _fail_second_backup(src, dst):
        if Path(src) == out_asm:
            raise OSError("Simulated lock on song.asm backup")
        return real_replace(src, dst)

    monkeypatch.setattr("atari_music.studio.exporter.os.replace", _fail_second_backup)
    with pytest.raises(OSError, match="song.asm backup"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(output_path=out_xex, keep_asm=True, mads_bin=fake_mads, player_asm=PLAYER_ASM),
        )
    assert out_xex.read_bytes() == orig_xex_bytes
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text

    # 2b. Simulate failure during commit of .xex (Phase B step 1)
    def _fail_commit_xex(src, dst):
        if Path(dst) == out_xex and ".bak_" not in str(src):
            raise OSError("Simulated replace failure on song.xex")
        return real_replace(src, dst)

    monkeypatch.setattr("atari_music.studio.exporter.os.replace", _fail_commit_xex)
    with pytest.raises(OSError, match="song.xex"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(output_path=out_xex, keep_asm=True, mads_bin=fake_mads, player_asm=PLAYER_ASM),
        )
    assert out_xex.read_bytes() == orig_xex_bytes
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text

    # 2c. Simulate failure during commit of .asm AFTER .xex was committed (Phase B step 2)
    def _fail_commit_asm(src, dst):
        if Path(dst) == out_asm and ".bak_" not in str(src):
            raise OSError("Simulated replace failure on song.asm")
        return real_replace(src, dst)

    monkeypatch.setattr("atari_music.studio.exporter.os.replace", _fail_commit_asm)
    with pytest.raises(OSError, match="song.asm"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(output_path=out_xex, keep_asm=True, mads_bin=fake_mads, player_asm=PLAYER_ASM),
        )
    assert out_xex.read_bytes() == orig_xex_bytes
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text

    # 2d. Failure when output.xex didn't exist yet while output.asm did -> cleans new .xex and restores .asm
    out_xex.unlink()
    with pytest.raises(OSError, match="song.asm"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(output_path=out_xex, keep_asm=True, mads_bin=fake_mads, player_asm=PLAYER_ASM),
        )
    assert not out_xex.exists()
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text

    # 3. keep_asm=False MUST update .xex while leaving pre-existing .asm untouched!
    monkeypatch.setattr("atari_music.studio.exporter.os.replace", real_replace)
    out_json = tmp_path / "song.arrangement.json"
    orig_json_text = '{"preexisting": true}\n'
    out_json.write_text(orig_json_text, encoding="utf-8")

    # 3a. Simulate failure during commit of .arrangement.json AFTER .xex and .asm were committed
    def _fail_commit_json(src, dst):
        if Path(dst) == out_json and ".bak_" not in str(src):
            raise OSError("Simulated replace failure on song.arrangement.json")
        return real_replace(src, dst)

    out_xex.write_bytes(orig_xex_bytes)
    monkeypatch.setattr("atari_music.studio.exporter.os.replace", _fail_commit_json)
    with pytest.raises(OSError, match="song.arrangement.json"):
        exporter.export_xex(
            state,
            state.baseline_config,
            XexExportOptions(
                output_path=out_xex,
                keep_asm=True,
                keep_arrangement_json=True,
                mads_bin=fake_mads,
                player_asm=PLAYER_ASM,
            ),
        )
    assert out_xex.read_bytes() == orig_xex_bytes
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text
    assert out_json.read_text(encoding="utf-8") == orig_json_text

    # 3b. keep_asm=False and keep_arrangement_json=False leaves pre-existing .asm and .arrangement.json untouched
    monkeypatch.setattr("atari_music.studio.exporter.os.replace", real_replace)
    res_no_companions = exporter.export_xex(
        state,
        state.baseline_config,
        XexExportOptions(
            output_path=out_xex,
            keep_asm=False,
            keep_arrangement_json=False,
            mads_bin=fake_mads,
            player_asm=PLAYER_ASM,
        ),
    )
    assert res_no_companions.asm_path is None
    assert res_no_companions.arrangement_json_path is None
    assert out_xex.read_bytes() == new_xex_bytes
    assert out_asm.read_text(encoding="utf-8") == orig_asm_text
    assert out_json.read_text(encoding="utf-8") == orig_json_text

    # 4. Exporting into same directory as source <stem>.json writes <stem>.arrangement.json and never clobbers source
    src_song_json = tmp_path / "same_stem.json"
    src_raw = (REPO_ROOT / "examples" / "ai" / "action_fast.json").read_text(encoding="utf-8")
    src_song_json.write_text(src_raw, encoding="utf-8")
    same_state = load_studio_composition(src_song_json)
    same_cfg = same_state.baseline_config.with_channel(1, "lead_attack_bite")
    res_same = exporter.export_xex(
        same_state,
        same_cfg,
        XexExportOptions(
            output_path=tmp_path / "same_stem.xex",
            keep_asm=True,
            keep_arrangement_json=True,
            mads_bin=fake_mads,
            player_asm=PLAYER_ASM,
        ),
    )
    assert src_song_json.read_text(encoding="utf-8") == src_raw
    assert res_same.arrangement_json_path == tmp_path / "same_stem.arrangement.json"
    assert res_same.arrangement_json_path.is_file()
    manifest = json.loads(res_same.arrangement_json_path.read_text(encoding="utf-8"))
    assert manifest["schema_id"] == "atari-music/xex-arrangement-manifest/1"
    assert manifest["composition"]["title"] == same_state.title
    assert manifest["arrangement"]["channel_assignments"]["1"] == "lead_attack_bite"
    assert manifest["arrangement"]["channels"]["1"]["assignment_mode"] == "catalog_override"
    assert manifest["arrangement"]["channels"]["1"]["catalog_profile"]["instrument_id"] == "lead_attack_bite"
    assert manifest["export"]["xex_file"] == "same_stem.xex"
    assert manifest["export"]["asm_file"] == "same_stem.asm"
    assert manifest["export"]["arrangement_json_file"] == "same_stem.arrangement.json"
    assert manifest["export"]["player_address_hex"] == "$6000"
    assert manifest["export"]["music_address_hex"] == "$8000"
    assert len(manifest["export"]["segments"]) == 3


def test_exporter_module_has_no_pyside6_imports() -> None:
    exporter_file = REPO_ROOT / "src" / "atari_music" / "studio" / "exporter.py"
    tree = ast.parse(exporter_file.read_text(encoding="utf-8"), filename=str(exporter_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("PySide6")
                assert "studio.ui" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("PySide6")
            assert "studio.ui" not in node.module


def test_real_mads_integration_dsl_and_json_export(tmp_path: Path) -> None:
    require_local_artifact(MADS_EXE)
    require_local_artifact(PLAYER_ASM)

    svc = InstrumentService()
    exporter = ExportService(svc)

    # 1. Real 16-bit v2 .dsl composition with modified CH3 catalog instrument
    dsl_state = load_studio_composition(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
    dsl_cfg = dsl_state.baseline_config.with_channel(3, "lead_attack_bite")
    dsl_xex = tmp_path / "wybierak_studio.xex"
    res_dsl = exporter.export_xex(
        dsl_state,
        dsl_cfg,
        XexExportOptions(output_path=dsl_xex, keep_asm=True, mads_bin=MADS_EXE, player_asm=PLAYER_ASM),
    )
    assert res_dsl.xex_path.is_file()
    assert res_dsl.asm_path is not None and res_dsl.asm_path.is_file()
    assert res_dsl.arrangement_json_path is not None and res_dsl.arrangement_json_path.is_file()
    dsl_manifest = json.loads(res_dsl.arrangement_json_path.read_text(encoding="utf-8"))
    assert dsl_manifest["schema_id"] == "atari-music/xex-arrangement-manifest/1"
    assert dsl_manifest["arrangement"]["effective_format_version"] == 2
    assert dsl_manifest["arrangement"]["effective_uses_16bit_bass"] is True
    assert dsl_manifest["arrangement"]["channels"]["2"]["assignment_mode"] == "locked_16bit_slave"
    assert dsl_manifest["arrangement"]["channels"]["3"]["assigned_instrument_id"] == "lead_attack_bite"
    assert res_dsl.format_version == 2
    assert res_dsl.uses_16bit_bass is True
    assert xex_layout.validate_xex_file(
        res_dsl.xex_path, player_address=0x6000, music_address=0x8000
    )

    # 2. Real v1-compatible AI JSON -> keep_asm=False, keep_arrangement_json=False
    ai_state = load_studio_composition(REPO_ROOT / "examples" / "ai" / "action_fast.json")
    ai_xex = tmp_path / "action_studio.xex"
    res_ai = exporter.export_xex(
        ai_state,
        ai_state.baseline_config,
        XexExportOptions(
            output_path=ai_xex,
            keep_asm=False,
            keep_arrangement_json=False,
            mads_bin=MADS_EXE,
            player_asm=PLAYER_ASM,
        ),
    )
    assert res_ai.xex_path.is_file()
    assert res_ai.asm_path is None
    assert res_ai.arrangement_json_path is None
    assert not ai_xex.with_suffix(".asm").exists()
    assert not ai_xex.with_suffix(".arrangement.json").exists()
    assert res_ai.format_version == 1
    assert xex_layout.validate_xex_file(
        res_ai.xex_path, player_address=0x6000, music_address=0x8000
    )

    # 3. Real MADS layout refusal when player placed in OS ROM ($C000) does not write .xex
    rom_xex = tmp_path / "rom_fail.xex"
    with pytest.raises(XexLayoutError):
        exporter.export_xex(
            ai_state,
            ai_state.baseline_config,
            XexExportOptions(
                output_path=rom_xex,
                player_address="$C000",
                music_address=None,
                keep_asm=True,
                mads_bin=MADS_EXE,
                player_asm=PLAYER_ASM,
            ),
        )
    assert not rom_xex.exists()

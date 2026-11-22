"""Production integration tests for CMC+ Open Hi-Hat (cmc_hihat_open)."""
from __future__ import annotations

import os
from pathlib import Path
import wave

from click.testing import CliRunner
import numpy as np
import pytest

from atari_music import frame_simulator
from atari_music.api import MusicGenerationResult, arrange_song, generate_music
from atari_music.cli import cli
from atari_music.constants import AUDCTL_15KHZ, AUDCTL_CH1_179MHZ, AUDCTL_JOIN_1_2_16BIT, DISTORTION_WHITE_NOISE
from atari_music.instruments import (
    ChannelAssignmentRequest,
    POKEYRuntime,
    TARGET_V1_XEX,
    TARGET_V2_ITER1_XEX,
    default_percussion_instrument_id,
    load_instrument_catalog,
)
from atari_music.ir import IRInstrument, IRNote, IRPattern, IRSong
from atari_music.mads_exporter import FormatVersionError, export_mads_asm
from atari_music.player_budget import PLAYER_SIZE_LIMIT_BYTES, measure_player_size
from atari_music.studio import (
    ExportService,
    InstrumentService,
    RenderService,
    XexExportOptions,
    load_studio_composition,
)
from conftest import require_local_artifact
from test_xex_e2e_py65 import MADS_EXE, PLAYER_ASM, run_xex_in_py65

pytestmark = [pytest.mark.core]


def _make_single_open_hihat_ir(
    *,
    channel: int = 4,
    frames_per_tick: int = 1,
    hit_duration: int = 8,
    rest_duration: int = 8,
    volume: int = 15,
) -> IRSong:
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("cmc_hihat_open")
    hh = IRInstrument.from_catalog_profile(0, prof, beh)
    total = hit_duration + rest_duration
    tracks = {}
    for ch in (1, 2, 3, 4):
        if ch == channel:
            tracks[ch] = [
                IRNote(duration=hit_duration, volume=volume, instrument_id=0, channel_role="percussion"),
                IRNote(is_rest=True, duration=rest_duration, volume=0, instrument_id=0, channel_role="percussion"),
            ]
        else:
            tracks[ch] = [IRNote(is_rest=True, duration=total, volume=0, instrument_id=0, channel_role="melody")]
    return IRSong(
        title=f"CMC Open HH CH{channel}",
        frames_per_tick=frames_per_tick,
        instruments=[hh],
        patterns=[IRPattern(id=0, name="OHH", rows=total, tracks=tracks)],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )


def _export_xex_v2(song: IRSong, tmp_path: Path, stem: str) -> Path:
    require_local_artifact(MADS_EXE)
    ir_path = tmp_path / f"{stem}.json"
    song.to_json_file(ir_path)
    state = load_studio_composition(ir_path)
    svc = InstrumentService()
    exporter = ExportService(svc)
    cfg = state.baseline_config.model_copy(update={"target_backend": "xex_v2", "player_version": "v2"})
    out_xex = tmp_path / f"{stem}.xex"
    res = exporter.export_xex(
        state,
        cfg,
        XexExportOptions(
            output_path=out_xex,
            player_address="$6000",
            music_address="$8000",
            keep_asm=True,
            mads_bin=MADS_EXE,
            player_asm=PLAYER_ASM,
        ),
    )
    assert res.format_version == 2
    assert res.xex_path.is_file()
    return res.xex_path


def _read_wav_pcm(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        sr = wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    return pcm, sr


def test_catalog_loads_cmc_hihat_open_and_default_remains_rhytmizer() -> None:
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("cmc_hihat_open")

    assert prof.instrument_id == "cmc_hihat_open"
    assert prof.display_name == "CMC+ Open Hi-Hat (V2 Macro)"
    assert prof.family == "percussion"
    assert prof.intended_roles == ("percussion", "rhythm")
    assert prof.base_distortion == DISTORTION_WHITE_NOISE
    assert prof.waveform_family == "poly17_noise"
    assert (
        prof.envelope.attack_frames,
        prof.envelope.decay_frames,
        prof.envelope.sustain_vol,
        prof.envelope.release_frames,
        prof.envelope.peak_vol,
    ) == (0, 0, 0, 0, 6)

    hc = prof.hardware_constraints
    assert hc.divider_mode == "8bit"
    assert hc.preferred_clock_hz == "64khz"
    assert hc.required_audctl_bits == 0x00
    assert hc.forbidden_audctl_bits == AUDCTL_15KHZ
    assert hc.channels_allowed == (1, 2, 3, 4)

    assert prof.provenance.source_kind == "curated_preset"
    assert prof.provenance.validation_status == "PLAYABLE"
    assert prof.provenance.notes is not None
    assert "Chaos Music Composer Plus" in prof.provenance.notes
    assert "#59" in prof.provenance.notes
    assert "hihat op" in prof.provenance.notes
    assert "experiments/chaos_music_composer_plus/" in prof.provenance.notes

    assert beh is not None
    assert beh.behavior_id == "beh_cmc_hihat_open_v2"
    assert beh.required_runtime_tier == "core_v2_iter1"
    assert beh.modulation_mode == "none"
    assert beh.allow_per_note_switch is True
    assert beh.transient_macro is not None
    assert beh.transient_macro.loop is False
    steps = beh.transient_macro.steps
    assert len(steps) == 5
    expected_steps = [
        (1, DISTORTION_WHITE_NOISE, 63, 6),
        (1, DISTORTION_WHITE_NOISE, 63, 4),
        (1, DISTORTION_WHITE_NOISE, 63, 2),
        (2, DISTORTION_WHITE_NOISE, 63, 1),
        (1, DISTORTION_WHITE_NOISE, 63, 0),
    ]
    assert [
        (s.duration_frames, s.distortion_nibble, s.fixed_audf, s.volume)
        for s in steps
    ] == expected_steps

    # Default v2 percussion instrument must remain rhytmizer_closed_hihat
    assert default_percussion_instrument_id(player_version="v2") == "rhytmizer_closed_hihat"
    rhyt_prof, rhyt_beh = cat.resolve_profile_behavior("rhytmizer_closed_hihat")
    assert rhyt_beh is not None and rhyt_beh.transient_macro is not None
    assert len(rhyt_beh.transient_macro.steps) == 2
    assert rhyt_prof.envelope.peak_vol == 4


def test_runtime_v2_all_channels_v1_rejection_and_audctl_rules() -> None:
    cat = load_instrument_catalog()

    for ch in (1, 2, 3, 4):
        rep_v2 = POKEYRuntime.resolve(
            [ChannelAssignmentRequest(channel=ch, instrument_ids=("cmc_hihat_open",))],
            cat,
            TARGET_V2_ITER1_XEX,
        )
        assert rep_v2.is_compatible is True
        assert rep_v2.status == "FULL_HARDWARE_V2_ITER1"
        assert rep_v2.effective_audctl == 0x00

        rep_v1 = POKEYRuntime.resolve(
            [ChannelAssignmentRequest(channel=ch, instrument_ids=("cmc_hihat_open",))],
            cat,
            TARGET_V1_XEX,
        )
        assert rep_v1.is_compatible is False
        assert rep_v1.status == "DEFERRED_FEATURE"
        assert any("core_v2_iter1" in d.message or d.code == "TIER_UNSUPPORTED" for d in rep_v1.diagnostics)

    # Coexists cleanly with 16-bit bass on CH1+CH2 (CH4 receives 64 kHz)
    rep_16bit = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_16bit_pure",)),
            ChannelAssignmentRequest(channel=4, instrument_ids=("cmc_hihat_open",)),
        ],
        cat,
        TARGET_V2_ITER1_XEX,
    )
    assert rep_16bit.is_compatible is True
    assert rep_16bit.effective_audctl == (AUDCTL_CH1_179MHZ | AUDCTL_JOIN_1_2_16BIT)

    # Rejects global 15 kHz base clock conflict ($01)
    rep_15k = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_15khz_pure",)),
            ChannelAssignmentRequest(channel=4, instrument_ids=("cmc_hihat_open",)),
        ],
        cat,
        TARGET_V2_ITER1_XEX,
    )
    assert rep_15k.is_compatible is False
    assert rep_15k.status == "BLOCKED_CONFLICT"
    assert any(d.code == "AUDCTL_CLOCK_CONFLICT" for d in rep_15k.diagnostics)

    # Direct v1 export refuses v2 macro instrument
    song = _make_single_open_hihat_ir(channel=4)
    with pytest.raises(FormatVersionError):
        export_mads_asm(song, format_version=1)


def test_studio_service_diagnostics_and_render_preview(tmp_path: Path) -> None:
    base = generate_music(profile="action", seed=7, uses_16bit_bass=False)
    ir_path = tmp_path / "studio_comp.json"
    base.save_json(ir_path)
    state = load_studio_composition(ir_path)

    svc = InstrumentService()
    cfg_v2 = state.baseline_config.model_copy(
        update={
            "channel_instruments": {4: "cmc_hihat_open"},
            "target_backend": "xex_v2",
            "player_version": "auto",
        }
    )
    eval_v2 = svc.evaluate_arrangement(state, cfg_v2, include_catalog_options=True)
    assert eval_v2.is_valid is True
    assert eval_v2.effective_format_version == 2
    for ch in (1, 2, 3, 4):
        opts = {o.instrument_id: o for o in eval_v2.channels[ch].options}
        assert opts["cmc_hihat_open"].compatible is True
        assert opts["cmc_hihat_open"].family == "percussion"
        assert opts["cmc_hihat_open"].display_name == "CMC+ Open Hi-Hat (V2 Macro)"

    cfg_v1 = state.baseline_config.model_copy(
        update={
            "channel_instruments": {4: "cmc_hihat_open"},
            "target_backend": "xex_v1",
            "player_version": "v1",
        }
    )
    eval_v1 = svc.evaluate_arrangement(state, cfg_v1, include_catalog_options=True)
    assert eval_v1.is_valid is False
    assert any("core_v2_iter1" in err or "v1" in err.lower() for err in eval_v1.blocking_errors)
    opt_v1 = {o.instrument_id: o for o in eval_v1.channels[4].options}["cmc_hihat_open"]
    assert opt_v1.compatible is False
    assert opt_v1.reason and "core_v2_iter1" in opt_v1.reason

    renderer = RenderService(svc)
    try:
        entry = renderer.render_preview(state, cfg_v2)
        assert entry.format_version == 2
        assert entry.wav_path.is_file()
        pcm, sr = _read_wav_pcm(entry.wav_path)
        assert sr == 44100
        assert len(pcm) > 4410
        assert float(np.max(np.abs(pcm))) > 0.05
    finally:
        renderer.cleanup()


def test_studio_instrument_picker_ui_visibility_and_selection(tmp_path: Path) -> None:
    PySide6 = pytest.importorskip("PySide6")
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from atari_music.studio.ui.instrument_picker import InstrumentCatalogInspector

    _ = PySide6
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    base = generate_music(profile="action", seed=11, uses_16bit_bass=False)
    ir_path = tmp_path / "picker_comp.json"
    base.save_json(ir_path)
    state = load_studio_composition(ir_path)

    svc = InstrumentService()
    inspector = InstrumentCatalogInspector(svc.catalog)

    eval_v2 = svc.evaluate_arrangement(
        state,
        state.baseline_config.model_copy(update={"target_backend": "xex_v2", "player_version": "auto"}),
        include_catalog_options=True,
    )
    inspector.set_slot_evaluation(eval_v2.channels[4])

    fam_idx = inspector._family_filter.findData("percussion")
    assert fam_idx >= 0
    inspector._family_filter.setCurrentIndex(fam_idx)
    app.processEvents()

    row_by_id = {
        inspector._list.item(i).data(Qt.ItemDataRole.UserRole): i
        for i in range(inspector._list.count())
    }
    assert "cmc_hihat_open" in row_by_id
    assert "rhytmizer_closed_hihat" in row_by_id

    inspector._list.setCurrentRow(row_by_id["cmc_hihat_open"])
    app.processEvents()

    details = inspector._details.toPlainText()
    assert "CMC+ Open Hi-Hat (V2 Macro)" in details
    assert "Family:        percussion" in details
    assert "Macro Steps: 5" in details
    assert "AUDCTL Req/Fb: $00 / $01" in details
    assert inspector._apply_btn.isEnabled() is True

    emitted = []
    inspector.apply_requested.connect(lambda ch, iid: emitted.append((ch, iid)))
    inspector._apply_btn.click()
    app.processEvents()
    assert emitted == [(4, "cmc_hihat_open")]

    eval_v1 = svc.evaluate_arrangement(
        state,
        state.baseline_config.model_copy(update={"target_backend": "xex_v1", "player_version": "v1"}),
        include_catalog_options=True,
    )
    inspector.set_slot_evaluation(eval_v1.channels[4])
    app.processEvents()
    row_v1 = {
        inspector._list.item(i).data(Qt.ItemDataRole.UserRole): i
        for i in range(inspector._list.count())
    }["cmc_hihat_open"]
    inspector._list.setCurrentRow(row_v1)
    app.processEvents()
    assert inspector._apply_btn.isEnabled() is False
    assert "Unavailable on CH4" in inspector._diag_label.text()
    assert "core_v2_iter1" in inspector._diag_label.text()


def test_cli_catalog_inspect_compose_and_arrange(tmp_path: Path) -> None:
    runner = CliRunner()

    res_val = runner.invoke(cli, ["validate-instruments"])
    assert res_val.exit_code == 0, res_val.output

    res_list_v2 = runner.invoke(cli, ["list-instruments", "--target", "xex_v2", "--family", "percussion"])
    assert res_list_v2.exit_code == 0, res_list_v2.output
    assert "cmc_hihat_open" in res_list_v2.output
    assert "[OK]" in res_list_v2.output

    res_list_v1 = runner.invoke(cli, ["list-instruments", "--target", "xex_v1", "--family", "percussion"])
    assert res_list_v1.exit_code == 0, res_list_v1.output
    assert "cmc_hihat_open" in res_list_v1.output
    assert "[DEFERRED_FEATURE]" in res_list_v1.output

    res_insp = runner.invoke(cli, ["inspect-instrument", "cmc_hihat_open"])
    assert res_insp.exit_code == 0, res_insp.output
    assert "beh_cmc_hihat_open_v2" in res_insp.output
    assert "CMC+ Open Hi-Hat" in res_insp.output
    assert "$01" in res_insp.output

    out_json = tmp_path / "cli_v2.json"
    out_wav = tmp_path / "cli_v2.wav"
    out_asm = tmp_path / "cli_v2.asm"
    res_comp_v2 = runner.invoke(
        cli,
        [
            "compose",
            "--profile",
            "action",
            "--seed",
            "5",
            "--channel-instrument",
            "4=cmc_hihat_open",
            "--player-version",
            "v2",
            "--output-json",
            str(out_json),
            "--output-wav",
            str(out_wav),
            "--output-asm",
            str(out_asm),
        ],
    )
    assert res_comp_v2.exit_code == 0, res_comp_v2.output
    assert out_json.is_file() and out_wav.is_file() and out_asm.is_file()
    assert "; Format: version 2" in out_asm.read_text(encoding="utf-8")

    res_comp_v1 = runner.invoke(
        cli,
        [
            "compose",
            "--profile",
            "action",
            "--seed",
            "5",
            "--channel-instrument",
            "4=cmc_hihat_open",
            "--player-version",
            "v1",
        ],
    )
    assert res_comp_v1.exit_code != 0

    arr_wav = tmp_path / "arr_v2.wav"
    res_arr = runner.invoke(
        cli,
        [
            "arrange",
            str(out_json),
            "--channel-instrument",
            "2=cmc_hihat_open",
            "--player-version",
            "auto",
            "--output-wav",
            str(arr_wav),
        ],
    )
    assert res_arr.exit_code == 0, res_arr.output
    assert arr_wav.is_file()


def test_wav_preview_open_hihat_decay_and_silence(tmp_path: Path) -> None:
    base = generate_music(profile="action", seed=3, uses_16bit_bass=False)
    single_song = _make_single_open_hihat_ir(channel=4, frames_per_tick=1, hit_duration=8, rest_duration=12)
    res = MusicGenerationResult(
        music_ir=base.music_ir,
        pokey_ir=single_song,
        metadata=base.metadata.model_copy(update={"format_version": 2}),
        quality_report=base.quality_report,
    )
    wav_path = res.render_wav(tmp_path / "single_ohh_preview.wav")
    assert wav_path.is_file()

    pcm, sr = _read_wav_pcm(wav_path)
    assert sr == 44100
    # 20 frames @ 50 Hz = 0.40s; F0..F4 = 0..100ms (0..4410 samples), F7+ (>140ms) = silent tail
    first_100ms_rms = float(np.sqrt(np.mean(pcm[:4410] ** 2)))
    tail_after_140ms_rms = float(np.sqrt(np.mean(pcm[6174:] ** 2)))
    assert first_100ms_rms > 0.02
    assert tail_after_140ms_rms < 1e-4


def test_xex_v2_py65_exact_cmc_pokey_sequence_and_retrigger(tmp_path: Path) -> None:
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("cmc_hihat_open")
    hh = IRInstrument.from_catalog_profile(0, prof, beh)

    # Single hit (8f) + rest (2f) + repeated hit (6f): 16 frames total
    song_rep = IRSong(
        title="XEX OHH Single & Repeated",
        frames_per_tick=1,
        instruments=[hh],
        patterns=[
            IRPattern(
                id=0,
                name="Rep",
                rows=16,
                tracks={
                    4: [
                        IRNote(duration=8, volume=15, instrument_id=0, channel_role="percussion"),
                        IRNote(is_rest=True, duration=2, volume=0, instrument_id=0, channel_role="percussion"),
                        IRNote(duration=6, volume=15, instrument_id=0, channel_role="percussion"),
                    ]
                },
            )
        ],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )
    xex_rep = _export_xex_v2(song_rep, tmp_path, "ohh_rep")
    run_rep = run_xex_in_py65(xex_rep, num_frames=16, player_address=0x6000, music_address=0x8000)
    expected_rep = frame_simulator.simulate_ir_song_frames(song_rep, format_version=2, num_frames=16)
    assert not run_rep.illegal_writes
    assert np.array_equal(run_rep.pokey_frames, expected_rep)

    # Exact CMC+ #59 'hihat op' POKEY frames: F0..F4 = ($3F,$86),($3F,$84),($3F,$82),($3F,$81),($3F,$81); F5+ vol=0
    expected_first_5 = [(0x3F, 0x86), (0x3F, 0x84), (0x3F, 0x82), (0x3F, 0x81), (0x3F, 0x81)]
    for f_idx, pair in enumerate(expected_first_5):
        assert (int(run_rep.pokey_frames[f_idx, 6]), int(run_rep.pokey_frames[f_idx, 7])) == pair
        assert (int(run_rep.pokey_frames[10 + f_idx, 6]), int(run_rep.pokey_frames[10 + f_idx, 7])) == pair
    assert (int(run_rep.pokey_frames[5, 6]), int(run_rep.pokey_frames[5, 7])) == (0x3F, 0x00)
    for f_idx in (6, 7, 8, 9, 15):
        assert int(run_rep.pokey_frames[f_idx, 7]) == 0x00


@pytest.mark.parametrize("channel", [1, 2, 3, 4])
def test_xex_v2_py65_all_four_channels(tmp_path: Path, channel: int) -> None:
    song = _make_single_open_hihat_ir(channel=channel, frames_per_tick=1, hit_duration=8, rest_duration=8)
    xex_path = _export_xex_v2(song, tmp_path, f"ohh_ch{channel}")
    run = run_xex_in_py65(xex_path, num_frames=16, player_address=0x6000, music_address=0x8000)
    expected = frame_simulator.simulate_ir_song_frames(song, format_version=2, num_frames=16)

    assert not run.illegal_writes
    assert np.array_equal(run.pokey_frames, expected)

    audf_col = (channel - 1) * 2
    audc_col = audf_col + 1
    expected_first_5 = [(0x3F, 0x86), (0x3F, 0x84), (0x3F, 0x82), (0x3F, 0x81), (0x3F, 0x81)]
    for f_idx, pair in enumerate(expected_first_5):
        assert (int(run.pokey_frames[f_idx, audf_col]), int(run.pokey_frames[f_idx, audc_col])) == pair
    for f_idx in range(5, 16):
        assert int(run.pokey_frames[f_idx, audc_col]) == 0x00

    for other in (1, 2, 3, 4):
        if other == channel:
            continue
        o_c = (other - 1) * 2 + 1
        assert np.all(run.pokey_frames[:, o_c] == 0)


def test_xex_v2_py65_open_choked_by_closed_hh_and_program_change(tmp_path: Path) -> None:
    cat = load_instrument_catalog()
    ohh_prof, ohh_beh = cat.resolve_profile_behavior("cmc_hihat_open")
    chh_prof, chh_beh = cat.resolve_profile_behavior("rhytmizer_closed_hihat")
    lead_prof, lead_beh = cat.resolve_profile_behavior("lead_pure_sustain")
    ohh = IRInstrument.from_catalog_profile(0, ohh_prof, ohh_beh)
    chh = IRInstrument.from_catalog_profile(1, chh_prof, chh_beh)
    lead = IRInstrument.from_catalog_profile(2, lead_prof, lead_beh)

    # Open HH plays 2 frames (F0..F1), choked on F2 by Closed HH (F2=$84, F3=$00), then switches to lead C-4
    song = IRSong(
        title="OHH Choke & Program Change",
        frames_per_tick=1,
        instruments=[ohh, chh, lead],
        patterns=[
            IRPattern(
                id=0,
                name="Choke",
                rows=8,
                tracks={
                    4: [
                        IRNote(duration=2, volume=15, instrument_id=0, channel_role="percussion"),
                        IRNote(
                            duration=2,
                            volume=15,
                            instrument_id=1,
                            channel_role="percussion",
                            pending_program_changes=(1,),
                        ),
                        IRNote(
                            pitch="C-4",
                            midi_pitch=60,
                            duration=4,
                            volume=12,
                            instrument_id=2,
                            channel_role="melody",
                            pending_program_changes=(2,),
                        ),
                    ]
                },
            )
        ],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 2, 2: 2, 3: 2, 4: 0},
    )
    xex_path = _export_xex_v2(song, tmp_path, "ohh_choke_pc")
    run = run_xex_in_py65(xex_path, num_frames=8, player_address=0x6000, music_address=0x8000)
    expected = frame_simulator.simulate_ir_song_frames(song, format_version=2, num_frames=8)
    assert not run.illegal_writes
    assert np.array_equal(run.pokey_frames, expected)

    assert (int(run.pokey_frames[0, 6]), int(run.pokey_frames[0, 7])) == (0x3F, 0x86)
    assert (int(run.pokey_frames[1, 6]), int(run.pokey_frames[1, 7])) == (0x3F, 0x84)
    assert (int(run.pokey_frames[2, 6]), int(run.pokey_frames[2, 7])) == (0x00, 0x84)
    assert int(run.pokey_frames[3, 7]) == 0x00
    assert (int(run.pokey_frames[4, 7]) & 0xE0) == 0xA0


def test_player_asm_budget_unchanged() -> None:
    require_local_artifact(MADS_EXE)
    size = measure_player_size(PLAYER_ASM, MADS_EXE)
    assert size == 1785
    assert size < PLAYER_SIZE_LIMIT_BYTES


def test_arrange_song_production_integration() -> None:
    base = generate_music(profile="action", seed=9, uses_16bit_bass=False)
    arranged = arrange_song(
        base.pokey_ir,
        channel_instruments={4: "cmc_hihat_open"},
        player_version="auto",
        target=TARGET_V2_ITER1_XEX,
    )
    assert arranged.metadata.format_version == 2
    assert any(inst.profile_id == "cmc_hihat_open" for inst in arranged.pokey_ir.instruments)

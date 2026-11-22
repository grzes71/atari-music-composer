"""Production integration tests for Rhytmizer Closed Hi-Hat (rhytmizer_closed_hihat)."""
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


def _make_single_hihat_ir(
    *,
    channel: int = 4,
    frames_per_tick: int = 1,
    hit_duration: int = 4,
    rest_duration: int = 4,
    volume: int = 15,
) -> IRSong:
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("rhytmizer_closed_hihat")
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
        title=f"Rhytmizer HH CH{channel}",
        frames_per_tick=frames_per_tick,
        instruments=[hh],
        patterns=[IRPattern(id=0, name="HH", rows=total, tracks=tracks)],
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


def test_catalog_loads_rhytmizer_closed_hihat_and_behavior() -> None:
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("rhytmizer_closed_hihat")

    assert prof.instrument_id == "rhytmizer_closed_hihat"
    assert prof.display_name == "Rhytmizer Closed Hi-Hat (V2 Macro)"
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
    ) == (0, 0, 0, 0, 4)

    hc = prof.hardware_constraints
    assert hc.divider_mode == "8bit"
    assert hc.preferred_clock_hz == "64khz"
    assert hc.required_audctl_bits == 0x00
    assert hc.forbidden_audctl_bits == AUDCTL_15KHZ
    assert hc.channels_allowed == (1, 2, 3, 4)

    assert prof.provenance.source_kind == "curated_preset"
    assert prof.provenance.validation_status == "PLAYABLE"
    assert prof.provenance.notes is not None
    assert "Rhytmizer" in prof.provenance.notes
    assert "MUNSIE" in prof.provenance.notes

    assert beh is not None
    assert beh.behavior_id == "beh_rhytmizer_closed_hihat_v2"
    assert beh.required_runtime_tier == "core_v2_iter1"
    assert beh.modulation_mode == "none"
    assert beh.allow_per_note_switch is True
    assert beh.transient_macro is not None
    assert beh.transient_macro.loop is False
    steps = beh.transient_macro.steps
    assert len(steps) == 2
    assert (steps[0].duration_frames, steps[0].distortion_nibble, steps[0].fixed_audf, steps[0].volume) == (
        1,
        DISTORTION_WHITE_NOISE,
        0,
        4,
    )
    assert (steps[1].duration_frames, steps[1].distortion_nibble, steps[1].fixed_audf, steps[1].volume) == (
        1,
        DISTORTION_WHITE_NOISE,
        0,
        0,
    )


def test_runtime_v2_all_channels_v1_rejection_and_audctl_rules() -> None:
    cat = load_instrument_catalog()

    # Accepted on all 4 channels in v2
    for ch in (1, 2, 3, 4):
        rep_v2 = POKEYRuntime.resolve(
            [ChannelAssignmentRequest(channel=ch, instrument_ids=("rhytmizer_closed_hihat",))],
            cat,
            TARGET_V2_ITER1_XEX,
        )
        assert rep_v2.is_compatible is True
        assert rep_v2.status == "FULL_HARDWARE_V2_ITER1"
        assert rep_v2.effective_audctl == 0x00

        # Rejected cleanly in v1
        rep_v1 = POKEYRuntime.resolve(
            [ChannelAssignmentRequest(channel=ch, instrument_ids=("rhytmizer_closed_hihat",))],
            cat,
            TARGET_V1_XEX,
        )
        assert rep_v1.is_compatible is False
        assert rep_v1.status == "DEFERRED_FEATURE"
        assert any("core_v2_iter1" in d.message or d.code == "TIER_UNSUPPORTED" for d in rep_v1.diagnostics)

    # Coexists cleanly with 16-bit bass on CH1+CH2 (CH3 or CH4 receives 64 kHz)
    rep_16bit = POKEYRuntime.resolve(
        [
            ChannelAssignmentRequest(channel=1, instrument_ids=("bass_16bit_pure",)),
            ChannelAssignmentRequest(channel=4, instrument_ids=("rhytmizer_closed_hihat",)),
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
            ChannelAssignmentRequest(channel=4, instrument_ids=("rhytmizer_closed_hihat",)),
        ],
        cat,
        TARGET_V2_ITER1_XEX,
    )
    assert rep_15k.is_compatible is False
    assert rep_15k.status == "BLOCKED_CONFLICT"
    assert any(d.code == "AUDCTL_CLOCK_CONFLICT" for d in rep_15k.diagnostics)

    # Direct v1 export refuses v2 macro instrument
    song = _make_single_hihat_ir(channel=4)
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
            "channel_instruments": {4: "rhytmizer_closed_hihat"},
            "target_backend": "xex_v2",
            "player_version": "auto",
        }
    )
    eval_v2 = svc.evaluate_arrangement(state, cfg_v2, include_catalog_options=True)
    assert eval_v2.is_valid is True
    assert eval_v2.effective_format_version == 2
    for ch in (1, 2, 3, 4):
        opts = {o.instrument_id: o for o in eval_v2.channels[ch].options}
        assert opts["rhytmizer_closed_hihat"].compatible is True
        assert opts["rhytmizer_closed_hihat"].family == "percussion"
        assert opts["rhytmizer_closed_hihat"].display_name == "Rhytmizer Closed Hi-Hat (V2 Macro)"

    # Selecting xex_v1 rejects rhytmizer_closed_hihat with a clear diagnostic reason
    cfg_v1 = state.baseline_config.model_copy(
        update={
            "channel_instruments": {4: "rhytmizer_closed_hihat"},
            "target_backend": "xex_v1",
            "player_version": "v1",
        }
    )
    eval_v1 = svc.evaluate_arrangement(state, cfg_v1, include_catalog_options=True)
    assert eval_v1.is_valid is False
    assert any("core_v2_iter1" in err or "v1" in err.lower() for err in eval_v1.blocking_errors)
    opt_v1 = {o.instrument_id: o for o in eval_v1.channels[4].options}["rhytmizer_closed_hihat"]
    assert opt_v1.compatible is False
    assert opt_v1.reason and "core_v2_iter1" in opt_v1.reason

    # RenderService preview produces valid v2 WAV
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
    assert "rhytmizer_closed_hihat" in row_by_id

    inspector._list.setCurrentRow(row_by_id["rhytmizer_closed_hihat"])
    app.processEvents()

    details = inspector._details.toPlainText()
    assert "Rhytmizer Closed Hi-Hat (V2 Macro)" in details
    assert "Family:        percussion" in details
    assert "Macro Steps: 2" in details
    assert "AUDCTL Req/Fb: $00 / $01" in details
    assert inspector._apply_btn.isEnabled() is True

    emitted = []
    inspector.apply_requested.connect(lambda ch, iid: emitted.append((ch, iid)))
    inspector._apply_btn.click()
    app.processEvents()
    assert emitted == [(4, "rhytmizer_closed_hihat")]

    # Under xex_v1 target, picker marks rhytmizer_closed_hihat incompatible and shows clear diagnostic
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
    }["rhytmizer_closed_hihat"]
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
    assert "rhytmizer_closed_hihat" in res_list_v2.output
    assert "[OK]" in res_list_v2.output

    res_list_v1 = runner.invoke(cli, ["list-instruments", "--target", "xex_v1", "--family", "percussion"])
    assert res_list_v1.exit_code == 0, res_list_v1.output
    assert "rhytmizer_closed_hihat" in res_list_v1.output
    assert "[DEFERRED_FEATURE]" in res_list_v1.output

    res_insp = runner.invoke(cli, ["inspect-instrument", "rhytmizer_closed_hihat"])
    assert res_insp.exit_code == 0, res_insp.output
    assert "beh_rhytmizer_closed_hihat_v2" in res_insp.output
    assert "Rhytmizer" in res_insp.output
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
            "4=rhytmizer_closed_hihat",
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

    # Attempting compose or arrange with v1 rejects cleanly
    res_comp_v1 = runner.invoke(
        cli,
        [
            "compose",
            "--profile",
            "action",
            "--seed",
            "5",
            "--channel-instrument",
            "4=rhytmizer_closed_hihat",
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
            "2=rhytmizer_closed_hihat",
            "--player-version",
            "auto",
            "--output-wav",
            str(arr_wav),
        ],
    )
    assert res_arr.exit_code == 0, res_arr.output
    assert arr_wav.is_file()


def test_wav_preview_short_noise_transient(tmp_path: Path) -> None:
    base = generate_music(profile="action", seed=3, uses_16bit_bass=False)
    single_song = _make_single_hihat_ir(channel=4, frames_per_tick=1, hit_duration=6, rest_duration=10)
    res = MusicGenerationResult(
        music_ir=base.music_ir,
        pokey_ir=single_song,
        metadata=base.metadata.model_copy(update={"format_version": 2}),
        quality_report=base.quality_report,
    )
    wav_path = res.render_wav(tmp_path / "single_hh_preview.wav")
    assert wav_path.is_file()

    pcm, sr = _read_wav_pcm(wav_path)
    assert sr == 44100
    # 16 frames @ 50 Hz = 0.32s = 14112 samples; F0 = 0..20ms (0..882 samples), F1+ = silence
    first_20ms_rms = float(np.sqrt(np.mean(pcm[:882] ** 2)))
    tail_after_40ms_rms = float(np.sqrt(np.mean(pcm[1764:] ** 2)))
    assert first_20ms_rms > 0.02
    assert tail_after_40ms_rms < 1e-4


def test_xex_v2_py65_exact_pokey_sequence_retrigger_and_consecutive(tmp_path: Path) -> None:
    cat = load_instrument_catalog()
    prof, beh = cat.resolve_profile_behavior("rhytmizer_closed_hihat")
    hh = IRInstrument.from_catalog_profile(0, prof, beh)

    # 1. Single isolated hit + repeated hit with rest (fpt=1)
    # Frames: 0 (HH), 1..3 (rest inside dur=4), 4..5 (explicit rest), 6 (HH), 7..9 (tail)
    song_rep = IRSong(
        title="XEX HH Single & Repeated",
        frames_per_tick=1,
        instruments=[hh],
        patterns=[
            IRPattern(
                id=0,
                name="Rep",
                rows=10,
                tracks={
                    4: [
                        IRNote(duration=4, volume=15, instrument_id=0, channel_role="percussion"),
                        IRNote(is_rest=True, duration=2, volume=0, instrument_id=0, channel_role="percussion"),
                        IRNote(duration=4, volume=15, instrument_id=0, channel_role="percussion"),
                    ]
                },
            )
        ],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )
    xex_rep = _export_xex_v2(song_rep, tmp_path, "hh_rep")
    run_rep = run_xex_in_py65(xex_rep, num_frames=10, player_address=0x6000, music_address=0x8000)
    expected_rep = frame_simulator.simulate_ir_song_frames(song_rep, format_version=2, num_frames=10)
    assert not run_rep.illegal_writes
    assert np.array_equal(run_rep.pokey_frames, expected_rep)

    # F0: ($00, $84), F1: ($00, $00), F2+: AUDC=$00, F6 retrigger: ($00, $84), F7: ($00, $00), F8+: AUDC=$00
    assert (int(run_rep.pokey_frames[0, 6]), int(run_rep.pokey_frames[0, 7])) == (0x00, 0x84)
    assert (int(run_rep.pokey_frames[1, 6]), int(run_rep.pokey_frames[1, 7])) == (0x00, 0x00)
    assert (int(run_rep.pokey_frames[6, 6]), int(run_rep.pokey_frames[6, 7])) == (0x00, 0x84)
    assert (int(run_rep.pokey_frames[7, 6]), int(run_rep.pokey_frames[7, 7])) == (0x00, 0x00)
    for f_idx in (2, 3, 4, 5, 8, 9):
        assert int(run_rep.pokey_frames[f_idx, 7]) == 0x00

    # 2. Immediate consecutive notes with NO intervening rest (fpt=2 and fpt=1)
    for fpt in (1, 2):
        song_consec = IRSong(
            title=f"XEX HH Consec fpt={fpt}",
            frames_per_tick=fpt,
            instruments=[hh],
            patterns=[
                IRPattern(
                    id=0,
                    name="Consec",
                    rows=5,
                    tracks={
                        4: [
                            IRNote(duration=1, volume=15, instrument_id=0, channel_role="percussion"),
                            IRNote(duration=1, volume=15, instrument_id=0, channel_role="percussion"),
                            IRNote(duration=1, volume=15, instrument_id=0, channel_role="percussion"),
                            IRNote(is_rest=True, duration=2, volume=0, instrument_id=0, channel_role="percussion"),
                        ]
                    },
                )
            ],
            sequence=[0],
            uses_16bit_bass=False,
            initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
        )
        n_frames = 5 * fpt
        xex_c = _export_xex_v2(song_consec, tmp_path, f"hh_consec_{fpt}")
        run_c = run_xex_in_py65(xex_c, num_frames=n_frames, player_address=0x6000, music_address=0x8000)
        expected_c = frame_simulator.simulate_ir_song_frames(song_consec, format_version=2, num_frames=n_frames)
        assert not run_c.illegal_writes
        assert np.array_equal(run_c.pokey_frames, expected_c)
        onsets = {0, fpt, 2 * fpt}
        for f_idx in range(n_frames):
            audf4, audc4 = int(run_c.pokey_frames[f_idx, 6]), int(run_c.pokey_frames[f_idx, 7])
            if f_idx in onsets:
                assert (audf4, audc4) == (0x00, 0x84)
            else:
                assert audc4 == 0x00


@pytest.mark.parametrize("channel", [1, 2, 3, 4])
def test_xex_v2_py65_all_four_channels(tmp_path: Path, channel: int) -> None:
    song = _make_single_hihat_ir(channel=channel, frames_per_tick=1, hit_duration=4, rest_duration=4)
    xex_path = _export_xex_v2(song, tmp_path, f"hh_ch{channel}")
    run = run_xex_in_py65(xex_path, num_frames=8, player_address=0x6000, music_address=0x8000)
    expected = frame_simulator.simulate_ir_song_frames(song, format_version=2, num_frames=8)

    assert not run.illegal_writes
    assert np.array_equal(run.pokey_frames, expected)

    audf_col = (channel - 1) * 2
    audc_col = audf_col + 1
    assert (int(run.pokey_frames[0, audf_col]), int(run.pokey_frames[0, audc_col])) == (0x00, 0x84)
    assert (int(run.pokey_frames[1, audf_col]), int(run.pokey_frames[1, audc_col])) == (0x00, 0x00)
    for f_idx in range(2, 8):
        assert int(run.pokey_frames[f_idx, audc_col]) == 0x00

    for other in (1, 2, 3, 4):
        if other == channel:
            continue
        o_c = (other - 1) * 2 + 1
        assert np.all(run.pokey_frames[:, o_c] == 0)


def test_xex_v2_py65_program_change_no_macro_state_leakage(tmp_path: Path) -> None:
    cat = load_instrument_catalog()
    hh_prof, hh_beh = cat.resolve_profile_behavior("rhytmizer_closed_hihat")
    lead_prof, lead_beh = cat.resolve_profile_behavior("lead_pure_sustain")
    hh = IRInstrument.from_catalog_profile(0, hh_prof, hh_beh)
    lead = IRInstrument.from_catalog_profile(1, lead_prof, lead_beh)

    # Switch immediately after 1-frame HH hit -> lead_pure_sustain -> HH -> lead_pure_sustain
    song = IRSong(
        title="HH Program Change Parity",
        frames_per_tick=1,
        instruments=[hh, lead],
        patterns=[
            IRPattern(
                id=0,
                name="PC",
                rows=10,
                tracks={
                    4: [
                        IRNote(duration=1, volume=15, instrument_id=0, channel_role="percussion"),
                        IRNote(
                            pitch="C-4",
                            midi_pitch=60,
                            duration=3,
                            volume=12,
                            instrument_id=1,
                            channel_role="melody",
                            pending_program_changes=(1,),
                        ),
                        IRNote(
                            duration=2,
                            volume=15,
                            instrument_id=0,
                            channel_role="percussion",
                            pending_program_changes=(0,),
                        ),
                        IRNote(
                            pitch="E-4",
                            midi_pitch=64,
                            duration=4,
                            volume=12,
                            instrument_id=1,
                            channel_role="melody",
                            pending_program_changes=(1,),
                        ),
                    ]
                },
            )
        ],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 1, 2: 1, 3: 1, 4: 0},
    )
    xex_path = _export_xex_v2(song, tmp_path, "hh_pc")
    run = run_xex_in_py65(xex_path, num_frames=10, player_address=0x6000, music_address=0x8000)
    expected = frame_simulator.simulate_ir_song_frames(song, format_version=2, num_frames=10)
    assert not run.illegal_writes
    assert np.array_equal(run.pokey_frames, expected)

    # Reference song without any HH on CH4 for exact melodic register comparison
    ref_song = IRSong(
        title="Lead Ref",
        frames_per_tick=1,
        instruments=[hh, lead],
        patterns=[
            IRPattern(
                id=0,
                name="Ref",
                rows=7,
                tracks={
                    4: [
                        IRNote(pitch="C-4", midi_pitch=60, duration=3, volume=12, instrument_id=1, channel_role="melody"),
                        IRNote(pitch="E-4", midi_pitch=64, duration=4, volume=12, instrument_id=1, channel_role="melody"),
                    ]
                },
            )
        ],
        sequence=[0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 1, 2: 1, 3: 1, 4: 1},
    )
    expected_ref = frame_simulator.simulate_ir_song_frames(ref_song, format_version=2, num_frames=7)

    # F0 = HH; F1..F3 = exact C-4 reference; F4..F5 = HH + silence; F6..F9 = exact E-4 reference
    assert (int(run.pokey_frames[0, 6]), int(run.pokey_frames[0, 7])) == (0x00, 0x84)
    assert np.array_equal(run.pokey_frames[1:4, 6:8], expected_ref[0:3, 6:8])
    assert (int(run.pokey_frames[4, 6]), int(run.pokey_frames[4, 7])) == (0x00, 0x84)
    assert int(run.pokey_frames[5, 7]) == 0x00
    assert np.array_equal(run.pokey_frames[6:10, 6:8], expected_ref[3:7, 6:8])


def test_player_asm_budget_unchanged() -> None:
    require_local_artifact(MADS_EXE)
    size = measure_player_size(PLAYER_ASM, MADS_EXE)
    assert size == 1785
    assert size < PLAYER_SIZE_LIMIT_BYTES


def test_arrange_song_production_integration() -> None:
    base = generate_music(profile="action", seed=9, uses_16bit_bass=False)
    arranged = arrange_song(
        base.pokey_ir,
        channel_instruments={4: "rhytmizer_closed_hihat"},
        player_version="auto",
        target=TARGET_V2_ITER1_XEX,
    )
    assert arranged.metadata.format_version == 2
    assert any(inst.profile_id == "rhytmizer_closed_hihat" for inst in arranged.pokey_ir.instruments)

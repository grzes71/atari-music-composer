"""PySide6 UI vertical-slice tests for Atari Music Composer Studio."""

from __future__ import annotations

import math
import os
from pathlib import Path
import struct
import time
from typing import Callable, Optional
import wave

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox  # noqa: E402
from atari_music.studio.models import (  # noqa: E402
    PRESET_SCHEMA_ID,
    CachedRenderEntry,
    ComparisonSlotStatus,
    ComparisonVariant,
    StudioArrangementConfig,
    XexExportOptions,
)
from atari_music.studio.presets import PresetRepository  # noqa: E402
from atari_music.studio.renderer import RenderService  # noqa: E402
from atari_music.studio.ui.ab_panel import ABComparisonPanel  # noqa: E402
from atari_music.studio.ui.audio_player import (  # noqa: E402
    AUDIO_ERR_NO_DEVICE,
    AudioPlaybackError,
    DualPcmStreamDevice,
    PcmFormatSpec,
    QtAudio,
    WavPcmData,
    convert_pcm_data,
    negotiate_device_format,
)
from atari_music.studio.ui.main_window import MainWindow  # noqa: E402
from atari_music.studio.ui.preset_bar import SavePresetDialog  # noqa: E402
from atari_music.studio.ui.transport_bar import TransportBar, format_time_ms  # noqa: E402
from atari_music.studio.ui.xex_export_dialog import XexExportDialog  # noqa: E402

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _wait_until(app: QApplication, predicate, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for background render / Qt condition")


class _FakeUiAudioBackend:
    """Minimal hardware-free AudioSinkBackend for UI transport & MainWindow tests."""

    def __init__(self, *, has_device: bool = True, buffer_ms: int = 100) -> None:
        self.has_device = has_device
        self.buffer_ms = buffer_ms
        self._callback: Optional[Callable[[QtAudio.State, QtAudio.Error], None]] = None
        self._stream: Optional[DualPcmStreamDevice] = None
        self._spec: Optional[PcmFormatSpec] = None
        self._state: QtAudio.State = QtAudio.State.StoppedState
        self._error: QtAudio.Error = QtAudio.Error.NoError
        self._buffer_size_bytes: int = 0
        self._queued = bytearray()
        self._processed_bytes: int = 0
        self._volume: float = 1.0
        self.load_calls: int = 0
        self.start_calls: int = 0
        self.suspend_calls: int = 0
        self.resume_calls: int = 0
        self.stop_calls: int = 0
        self.reset_calls: int = 0
        self.release_calls: int = 0

    def has_output_device(self) -> bool:
        return self.has_device

    def set_state_callback(self, callback: Callable[[QtAudio.State, QtAudio.Error], None]) -> None:
        self._callback = callback

    def negotiate_and_prepare(self, wav: WavPcmData, stream: DualPcmStreamDevice) -> PcmFormatSpec:
        self.load_calls += 1
        if not self.has_device:
            raise AudioPlaybackError("No audio output device is available.", code=AUDIO_ERR_NO_DEVICE)
        spec = negotiate_device_format(wav, is_supported_fn=lambda _s: True)
        pcm = convert_pcm_data(wav, spec)
        if not stream.isOpen():
            stream.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        stream.set_pcm_data(pcm, spec.frame_bytes)
        self._spec = spec
        self._stream = stream
        raw_buf = int(round((spec.bytes_per_second * self.buffer_ms) / 1000.0))
        self._buffer_size_bytes = max(spec.frame_bytes, (raw_buf // spec.frame_bytes) * spec.frame_bytes)
        self._queued.clear()
        self._processed_bytes = 0
        self._error = QtAudio.Error.NoError
        self._state = QtAudio.State.StoppedState
        return spec

    def _emit_state(self, st: QtAudio.State, err: QtAudio.Error = QtAudio.Error.NoError) -> None:
        self._state = st
        self._error = err
        if self._callback is not None:
            self._callback(st, err)

    def _fill(self) -> None:
        if self._stream is None or self._buffer_size_bytes <= 0:
            return
        space = self._buffer_size_bytes - len(self._queued)
        if space > 0 and not self._stream.atEnd():
            chunk = self._stream.read(space)
            if chunk:
                self._queued.extend(chunk)

    def start(self, stream: DualPcmStreamDevice) -> None:
        self.start_calls += 1
        self._stream = stream
        self._processed_bytes = 0
        self._queued.clear()
        self._fill()
        self._emit_state(QtAudio.State.ActiveState)

    def advance_ms(self, delta_ms: int) -> None:
        if self._state != QtAudio.State.ActiveState or self._spec is None:
            return
        step_bytes = int(round((delta_ms * self._spec.bytes_per_second) / 1000.0))
        step_bytes = (step_bytes // self._spec.frame_bytes) * self._spec.frame_bytes
        rem = step_bytes
        while rem > 0:
            self._fill()
            if not self._queued:
                break
            take = min(rem, len(self._queued))
            del self._queued[:take]
            self._processed_bytes += take
            rem -= take
        self._fill()
        if not self._queued and (self._stream is None or self._stream.atEnd()):
            self._emit_state(QtAudio.State.IdleState)

    def suspend(self) -> None:
        self.suspend_calls += 1
        if self._state == QtAudio.State.ActiveState:
            self._emit_state(QtAudio.State.SuspendedState)

    def resume(self) -> None:
        self.resume_calls += 1
        if self._state == QtAudio.State.SuspendedState:
            self._emit_state(QtAudio.State.ActiveState)

    def stop(self) -> None:
        self.stop_calls += 1
        self._queued.clear()
        self._emit_state(QtAudio.State.StoppedState)

    def reset(self) -> None:
        self.reset_calls += 1
        self._queued.clear()
        self._processed_bytes = 0
        self._state = QtAudio.State.StoppedState

    def processed_usecs(self) -> int:
        if self._spec is None or self._spec.bytes_per_second <= 0:
            return 0
        return int(round((self._processed_bytes * 1_000_000.0) / self._spec.bytes_per_second))

    def buffer_size(self) -> int:
        return self._buffer_size_bytes

    def bytes_free(self) -> int:
        return max(0, self._buffer_size_bytes - len(self._queued))

    def state(self) -> QtAudio.State:
        return self._state

    def error(self) -> QtAudio.Error:
        return self._error

    def set_volume(self, volume: float) -> None:
        self._volume = volume

    def release(self) -> None:
        self.release_calls += 1
        self._queued.clear()
        self._processed_bytes = 0
        self._state = QtAudio.State.StoppedState


def _write_test_wav(path: Path, *, duration_s: float = 2.0, sample_rate: int = 44100) -> Path:
    frames = max(1, int(round(sample_rate * duration_s)))
    buf = bytearray()
    for i in range(frames):
        s = int(0.25 * 32767 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
        buf.extend(struct.pack("<h", s))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))
    return path


def test_ui_load_dsl_ch2_lock_and_no_auto_render(qapp: QApplication) -> None:
    win = MainWindow(audio_backend=_FakeUiAudioBackend())
    try:
        win.load_composition_file(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
        assert win.state is not None
        assert win.state.base_uses_16bit_bass is True
        assert not win._channel_strips[2]._combo.isEnabled()
        assert not win._channel_strips[2]._lock_label.isHidden()
        assert "16-bit" in win._channel_strips[2]._lock_label.text()
        assert win.last_rendered_entry is None
        assert win._render_btn.isEnabled() is True

        # Assigning CH3 must NOT trigger auto-render
        win.set_channel_instrument(3, "lead_attack_bite")
        qapp.processEvents()
        assert win.working_config.channel_instruments[3] == "lead_attack_bite"
        assert win.last_rendered_entry is None
        assert not win._is_rendering
    finally:
        win.close()


def test_ui_render_outdated_invalid_guard_and_revert(qapp: QApplication) -> None:
    backend = _FakeUiAudioBackend()
    win = MainWindow(audio_backend=backend)
    try:
        win.load_composition_file(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        assert win.state is not None

        # Change multiple channels before rendering
        win.set_channel_instrument(1, "lead_attack_bite")
        win.set_channel_instrument(2, "bass_15khz_pure")
        assert win.last_rendered_entry is None

        # Explicit Render Preview in background worker
        win.render_current_preview()
        _wait_until(qapp, lambda: (not win._is_rendering) and (win.last_rendered_entry is not None))

        first_entry = win.last_rendered_entry
        assert first_entry is not None
        assert first_entry.wav_path.is_file()
        assert "UP TO DATE" in win._transport._sync_label.text()
        assert win._transport._play_btn.isEnabled() is True

        # Play / Stop transport smoke
        win._transport.play()
        qapp.processEvents()
        win._transport.stop()
        qapp.processEvents()

        # Modifying CH4 marks preview OUTDATED without auto-rendering
        win.set_channel_instrument(4, "perc_snare_crisp")
        qapp.processEvents()
        assert win.last_rendered_entry is first_entry
        assert "OUTDATED" in win._transport._sync_label.text()

        # Selecting invalid player_version='v1' with v2 instruments blocks rendering
        idx_v1 = win._player_ver_combo.findData("v1")
        win._player_ver_combo.setCurrentIndex(idx_v1)
        qapp.processEvents()
        assert win.evaluation is not None and win.evaluation.is_valid is False
        assert win._render_btn.isEnabled() is False
        assert not win._diag_banner.isHidden()
        assert "Validation Error:" in win._diag_banner.text()

        # Revert Original restores valid baseline cleanly
        win.revert_to_original()
        qapp.processEvents()
        assert win.working_config == win.state.baseline_config
        assert win.evaluation.is_valid is True
        assert win._render_btn.isEnabled() is True
    finally:
        win.close()
        assert not win._render_service.cache_dir.exists()


def _stub_xex_bytes(player_addr: int = 0x6000) -> bytes:
    def _seg(start: int, payload: bytes, mark: bool = False) -> bytes:
        hdr = struct.pack("<HH", start, start + len(payload) - 1)
        return (b"\xff\xff" if mark else b"") + hdr + payload

    return (
        _seg(player_addr, b"\x00" * 16, mark=True)
        + _seg(0x8000, b"\x01" * 16)
        + _seg(0x02E0, struct.pack("<H", player_addr))
    )


def test_ui_xex_export_dialog_validation_overwrite_and_background_worker(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from atari_music.api import MusicGenerationResult

    fake_mads = tmp_path / ("mads.cmd" if os.name == "nt" else "mads")
    fake_mads.write_text("# stub mads\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(fake_mads, 0o755)
    player_asm = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"

    win = MainWindow(audio_backend=_FakeUiAudioBackend())
    try:
        # Before load, Export XEX... is disabled
        assert win._export_xex_btn.isEnabled() is False

        win.load_composition_file(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
        assert win.state is not None
        assert win._export_xex_btn.isEnabled() is True
        assert win.last_rendered_entry is None

        # Render WAV preview first so we verify XEX export does NOT disrupt WAV cache/playback
        win.set_channel_instrument(3, "lead_attack_bite")
        win.render_current_preview()
        _wait_until(qapp, lambda: (not win._is_rendering) and (win.last_rendered_entry is not None))
        wav_entry = win.last_rendered_entry
        assert wav_entry is not None and wav_entry.wav_path.is_file()

        # 1. Dialog defaults and invalid input guards
        prepared = win._export_service.prepare_xex_export(win.state, win.working_config)
        assert prepared.is_exportable is True
        dlg = XexExportDialog(
            win.state,
            prepared,
            win._current_preview_sync_note(),
            initial_mads=fake_mads,
            initial_player_asm=player_asm,
            parent=win,
        )
        assert dlg._player_addr_edit.text() == "$6000"
        assert dlg._music_addr_edit.text() == "$8000"
        assert dlg._zp_base_edit.text() == "$80"
        assert dlg._keep_asm_check.isChecked() is True
        assert dlg._export_btn.isEnabled() is True

        # Invalid ZP address disables Export button with clear diagnostic
        dlg._zp_base_edit.setText("$7F")
        qapp.processEvents()
        assert dlg._export_btn.isEnabled() is False
        assert not dlg._error_label.isHidden()

        # Restore valid ZP and test overwrite prompt (No keeps dialog open, Yes accepts)
        dlg._zp_base_edit.setText("$80")
        target_xex = tmp_path / "ui_out.xex"
        target_xex.write_bytes(b"PREEXISTING_XEX")
        dlg._output_edit.setText(str(target_xex))
        qapp.processEvents()
        assert dlg._export_btn.isEnabled() is True

        prompts: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda _parent, _title, text, *_args: (
                prompts.append(text),
                QMessageBox.StandardButton.No,
            )[1],
        )
        dlg._on_export_clicked()
        assert len(prompts) == 1
        assert "PREEXISTING_XEX" == target_xex.read_bytes().decode("ascii")
        assert dlg.result() != int(QDialog.DialogCode.Accepted)

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args: QMessageBox.StandardButton.Yes,
        )
        dlg._on_export_clicked()
        assert dlg.result() == int(QDialog.DialogCode.Accepted)
        opts = dlg.build_options()

        # 2. Invalid prepared arrangement (explicit v1 on v2 song) disables export button cleanly
        bad_cfg = win.working_config.model_copy(update={"player_version": "v1"})
        bad_prep = win._export_service.prepare_xex_export(win.state, bad_cfg)
        assert bad_prep.is_exportable is False
        bad_dlg = XexExportDialog(
            win.state,
            bad_prep,
            "OUTDATED",
            initial_mads=fake_mads,
            initial_player_asm=player_asm,
            parent=win,
        )
        assert bad_dlg._export_btn.isEnabled() is False
        assert not bad_dlg._error_label.isHidden()

        # 3. Background ExportXexWorker execution succeeds & preserves loaded WAV cache
        def _stub_build_xex(self, output_path, **kwargs):
            p = Path(output_path)
            p.write_bytes(_stub_xex_bytes())
            if kwargs.get("keep_asm", True):
                p.with_suffix(".asm").write_text("; ui stub asm\n", encoding="utf-8")
            return p

        monkeypatch.setattr(MusicGenerationResult, "build_xex", _stub_build_xex)
        win.export_xex(opts)
        _wait_until(qapp, lambda: (not win._is_exporting) and (win.last_exported_result is not None))

        assert win.last_exported_result is not None
        assert win.last_exported_result.xex_path == target_xex
        assert "Exported XEX" in win._diag_banner.text()
        assert target_xex.read_bytes() == _stub_xex_bytes()
        assert target_xex.with_suffix(".asm").is_file()
        assert win.last_rendered_entry is wav_entry
        assert win._transport._loaded_wav == wav_entry.wav_path

        # 4. Background worker failure emits error banner without crashing
        def _fail_build_xex(self, output_path, **kwargs):
            raise RuntimeError("Simulated MADS error")

        monkeypatch.setattr(MusicGenerationResult, "build_xex", _fail_build_xex)
        fail_errs: list[str] = []
        win.xex_export_failed.connect(fail_errs.append)
        fail_opts = XexExportOptions(
            output_path=tmp_path / "ui_fail.xex",
            mads_bin=fake_mads,
            player_asm=player_asm,
        )
        win.export_xex(fail_opts)
        _wait_until(qapp, lambda: (not win._is_exporting) and len(fail_errs) == 1)
        assert "Simulated MADS error" in win._diag_banner.text()
        assert not (tmp_path / "ui_fail.xex").exists()
    finally:
        win.close()
        assert not win._render_service.cache_dir.exists()


def test_ui_presets_load_vs_apply_save_rename_delete_and_confirmations(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    presets_dir = tmp_path / "presets"
    seed_repo = PresetRepository(presets_dir=presets_dir)
    seed_cfg_keep_orig = StudioArrangementConfig(
        channel_instruments={1: "lead_pure_pluck", 2: None, 3: None, 4: None},
        program_change_policy="remove",
        player_version="auto",
        target_backend="wav",
    )
    seed_repo.save_preset("Keep Orig Mix", seed_cfg_keep_orig, description="CH1 pluck only")
    seed_repo.save_preset("Disposable", StudioArrangementConfig())

    win = MainWindow(presets_dir=presets_dir)
    try:
        bar = win._preset_bar
        # Before composition is loaded: Save and Apply disabled; Rename/Delete available when selected
        assert bar._save_btn.isEnabled() is False
        assert bar._apply_btn.isEnabled() is False
        assert bar.select_preset_id("disposable") is True
        bar.selection_changed.emit("disposable")
        qapp.processEvents()
        assert bar._load_btn.isEnabled() is True
        assert bar._rename_btn.isEnabled() is True
        assert bar._delete_btn.isEnabled() is True

        # Load Disposable before composition -> Apply still disabled until composition opens
        bar._load_btn.click()
        qapp.processEvents()
        assert win.loaded_preset is not None and win.loaded_preset.preset_id == "disposable"
        assert bar._apply_btn.isEnabled() is False

        # Rename without loaded composition preserves selection and preset data
        monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kw: ("Disposable Renamed", True))
        bar._rename_btn.click()
        qapp.processEvents()
        assert bar.selected_preset_id() == "disposable-renamed"
        assert win.loaded_preset is not None and win.loaded_preset.preset.name == "Disposable Renamed"

        # Delete confirmation No keeps file; Yes deletes file
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
        bar._delete_btn.click()
        qapp.processEvents()
        assert (presets_dir / "disposable-renamed.json").is_file()

        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
        bar._delete_btn.click()
        qapp.processEvents()
        assert not (presets_dir / "disposable-renamed.json").exists()
        assert win.loaded_preset is None

        # Load composition and render initial WAV preview
        win.load_composition_file(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        assert bar._save_btn.isEnabled() is True
        win.set_channel_instrument(1, "lead_attack_bite")
        win.set_channel_instrument(2, "bass_15khz_pure")
        win.set_channel_instrument(4, "perc_snare_crisp")
        qapp.processEvents()

        win.render_current_preview()
        _wait_until(qapp, lambda: (not win._is_rendering) and (win.last_rendered_entry is not None))
        rendered_entry = win.last_rendered_entry
        assert rendered_entry is not None
        assert "UP TO DATE" in win._transport._sync_label.text()

        # Select 'Keep Orig Mix' and click Load -> must NOT change working_config or mark preview outdated!
        idx = bar._combo.findData("keep-orig-mix")
        assert idx >= 0
        bar._combo.setCurrentIndex(idx)
        qapp.processEvents()
        assert win.working_config.channel_instruments[2] == "bass_15khz_pure"
        assert bar._apply_btn.isEnabled() is False  # Requires explicit Load first

        render_calls: list[int] = []
        orig_render = RenderService.render_preview

        def _spy_render(self, state, config):
            render_calls.append(1)
            return orig_render(self, state, config)

        monkeypatch.setattr(RenderService, "render_preview", _spy_render)

        bar._load_btn.click()
        qapp.processEvents()
        assert win.loaded_preset is not None and win.loaded_preset.preset_id == "keep-orig-mix"
        assert bar._apply_btn.isEnabled() is True
        assert win.working_config.channel_instruments[2] == "bass_15khz_pure"
        assert win.last_rendered_entry is rendered_entry
        assert "UP TO DATE" in win._transport._sync_label.text()
        assert render_calls == []

        # Save current _working_config (NOT loaded preset!) via Save dialog
        monkeypatch.setattr(SavePresetDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
        monkeypatch.setattr(SavePresetDialog, "preset_name", lambda self: "Current Working Mix")
        monkeypatch.setattr(SavePresetDialog, "preset_description", lambda self: "Saved from UI")
        bar._save_btn.click()
        qapp.processEvents()
        assert bar.selected_preset_id() == "current-working-mix"
        saved_on_disk = seed_repo.load_preset("current-working-mix")
        assert saved_on_disk.preset.arrangement == win.working_config
        assert saved_on_disk.preset.arrangement != seed_cfg_keep_orig

        # Overwrite prompt on duplicate save: No cancels, Yes overwrites
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
        assert win.save_current_preset("Current Working Mix", "Should Cancel") is None
        assert seed_repo.load_preset("current-working-mix").preset.description == "Saved from UI"

        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
        overwritten = win.save_current_preset("Current Working Mix", "Overwritten Desc")
        assert overwritten is not None
        assert seed_repo.load_preset("current-working-mix").preset.description == "Overwritten Desc"

        # Now load & explicitly Apply 'Keep Orig Mix': replaces working_config (None restores Keep Original),
        # marks OUTDATED PREVIEW, and triggers ZERO rendering!
        bar._combo.setCurrentIndex(bar._combo.findData("keep-orig-mix"))
        qapp.processEvents()
        bar._load_btn.click()
        qapp.processEvents()
        bar._apply_btn.click()
        qapp.processEvents()

        assert win.working_config == seed_cfg_keep_orig
        assert win.working_config.channel_instruments[2] is None
        assert win._channel_strips[2]._combo.currentIndex() == 0
        assert win._channel_strips[4]._combo.currentIndex() == 0
        assert win.last_rendered_entry is rendered_entry
        assert "OUTDATED" in win._transport._sync_label.text()
        assert not win._is_rendering
        assert render_calls == []

        # Deleting a preset does NOT change active working_config
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
        bar._delete_btn.click()
        qapp.processEvents()
        assert not (presets_dir / "keep-orig-mix.json").exists()
        assert win.working_config == seed_cfg_keep_orig
    finally:
        win.close()


def test_ui_presets_malformed_files_warnings_unknown_catalog_and_16bit_lock(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    import json

    presets_dir = tmp_path / "presets"
    repo = PresetRepository(presets_dir=presets_dir)
    repo.save_preset(
        "Unknown Catalog",
        StudioArrangementConfig(channel_instruments={1: None, 2: None, 3: "no_such_lead", 4: None}),
    )
    repo.save_preset(
        "CH2 Harmony Conflict",
        StudioArrangementConfig(channel_instruments={1: None, 2: "harmony_soft_square", 3: "lead_pure_sustain", 4: None}),
    )
    repo.save_preset(
        "Clean 16-bit Bass",
        StudioArrangementConfig(channel_instruments={1: "bass_16bit_pure", 2: None, 3: "lead_attack_bite", 4: "perc_kick_tight"}),
    )

    # Plant malformed and unsupported files alongside valid presets
    (presets_dir / "broken.json").write_text("{bad json", encoding="utf-8")
    (presets_dir / "future.json").write_text(
        json.dumps({"schema_id": "atari-music/arrangement-preset/99", "name": "Future", "arrangement": {}}),
        encoding="utf-8",
    )
    assert PRESET_SCHEMA_ID == "atari-music/arrangement-preset/1"

    win = MainWindow(presets_dir=presets_dir)
    try:
        bar = win._preset_bar
        # Malformed files reported as persistent warning while valid presets stay available
        assert not bar._warning_label.isHidden()
        assert "broken.json" in bar._warning_label.text()
        assert "future.json" in bar._warning_label.text()
        assert bar._combo.findData("unknown-catalog") >= 0
        assert bar._combo.findData("ch2-harmony-conflict") >= 0
        assert bar._combo.findData("clean-16-bit-bass") >= 0

        # Load 16-bit composition (wybierak-2.dsl); warning must survive UI refreshes!
        win.load_composition_file(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
        qapp.processEvents()
        assert not bar._warning_label.isHidden()

        # Applying preset with unknown catalog_id is rejected and leaves working_config unchanged
        win.set_channel_instrument(3, "lead_pure_sustain")
        qapp.processEvents()
        before_cfg = win.working_config
        bar.select_preset_id("unknown-catalog")
        win.load_preset("unknown-catalog")
        assert win.apply_loaded_preset() is None
        assert win.working_config == before_cfg
        assert "rejected" in bar._status_label.text().lower()
        assert not bar._warning_label.isHidden()

        # Applying preset with CH2 override on 16-bit song preserves CH2 in config, shows error, blocks Render
        win.load_preset("ch2-harmony-conflict")
        apply_conflict = win.apply_loaded_preset()
        assert apply_conflict is not None
        assert win.working_config.channel_instruments[2] == "harmony_soft_square"
        assert win.evaluation is not None and win.evaluation.is_valid is False
        assert win._render_btn.isEnabled() is False
        assert not win._diag_banner.isHidden()
        assert "Validation Error:" in win._diag_banner.text()
        assert not bar._warning_label.isHidden()

        # Load sparse 8-bit song (empty CH2) and Apply 'Clean 16-bit Bass' -> locks CH2 cleanly, zero auto-render
        sparse_dsl = tmp_path / "sparse_8bit.dsl"
        sparse_dsl.write_text(
            'TITLE "Sparse"\nKEY E\nMODE MINOR\nBPM 120\nCHANNELS 4\nLOOP 0\n'
            'SEQUENCE A\nINSTRUMENT bass character=bass\nINSTRUMENT lead character=bright_lead\n'
            'INSTRUMENT perc character=percussion\n'
            '[PATTERN A length=8]\nCH1 bass V12\nE2/4 B2/4\nCH3 lead V13\nE5/4 B4/4\nCH4 perc V9\nC4/4 R/4\n',
            encoding="utf-8",
        )
        win.load_composition_file(sparse_dsl)
        win.load_preset("clean-16-bit-bass")
        apply_16bit = win.apply_loaded_preset()
        qapp.processEvents()
        assert apply_16bit is not None and apply_16bit.evaluation.is_valid is True
        assert not win._channel_strips[2]._combo.isEnabled()
        assert not win._channel_strips[2]._lock_label.isHidden()
        assert "16bit_ch12" in win._channel_strips[2]._lock_label.text()
        assert win._render_btn.isEnabled() is True
        assert win.last_rendered_entry is None
        assert not bar._warning_label.isHidden()
    finally:
        win.close()


def test_transport_bar_playback_pause_resume_stop_seek_time_and_eof(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert format_time_ms(-50) == "00:00"
    assert format_time_ms(0) == "00:00"
    assert format_time_ms(65_000) == "01:05"
    assert format_time_ms(3_665_000) == "61:05"

    wav_a = _write_test_wav(tmp_path / "song_a.wav", duration_s=3.0)
    wav_b = _write_test_wav(tmp_path / "song_b.wav", duration_s=1.2)

    backend = _FakeUiAudioBackend(buffer_ms=100)
    bar = TransportBar(audio_backend=backend)
    assert bar.audio_player.__class__.__name__ == "StudioAudioPlayer"

    render_requests: list[int] = []
    eofs: list[int] = []
    errors: list[str] = []
    bar.render_requested.connect(lambda: render_requests.append(1))
    bar.end_of_media.connect(lambda: eofs.append(1))
    bar.playback_error.connect(errors.append)

    try:
        # 1. Load WAV A (3000 ms)
        assert bar.set_rendered_wav(wav_a) is True
        assert bar._seek_slider.minimum() == 0
        assert bar._seek_slider.maximum() == 3000
        assert bar._seek_slider.value() == 0
        assert bar._seek_slider.isEnabled() is True
        assert bar._time_label.text() == "00:00 / 00:03"
        assert bar._play_btn.isEnabled() is True
        assert bar._pause_btn.isEnabled() is False
        assert bar._stop_btn.isEnabled() is False

        # 2. Pre-play Seek -> enables Stop, Play starts from seek offset (not 0)
        assert bar.seek(1000) == 1000
        assert bar._seek_slider.value() == 1000
        assert bar._time_label.text() == "00:01 / 00:03"
        assert bar._stop_btn.isEnabled() is True

        bar._play_btn.click()
        assert bar.audio_player.is_playing() is True
        assert bar._play_btn.isEnabled() is False
        assert bar._pause_btn.isEnabled() is True
        assert bar._pause_btn.text() == "Pause"
        assert bar._stop_btn.isEnabled() is True

        backend.advance_ms(400)
        bar.audio_player._on_poll_tick()
        qapp.processEvents()
        assert bar._seek_slider.value() >= 1200

        # 3. Pause -> Seek during Pause -> clicking Play resumes rather than restarting from 0
        bar._pause_btn.click()
        assert bar.audio_player.is_paused() is True
        assert bar._pause_btn.text() == "Resume"
        assert bar._play_btn.isEnabled() is True
        assert bar._stop_btn.isEnabled() is True

        assert bar.seek(2100) == 2100
        assert bar.audio_player.is_paused() is True
        assert bar._seek_slider.value() == 2100
        assert bar._time_label.text() == "00:02 / 00:03"

        bar._play_btn.click()
        assert bar.audio_player.is_playing() is True
        assert bar.audio_player.position() >= 2100
        assert bar._pause_btn.text() == "Pause"

        # 4. Slider drag separation: zero seeks during drag; backend updates do not fight drag; single seek on release
        seek_calls: list[int] = []
        orig_seek = bar.audio_player.seek

        def _spy_seek(ms: int) -> int:
            seek_calls.append(ms)
            return orig_seek(ms)

        monkeypatch.setattr(bar.audio_player, "seek", _spy_seek)

        bar._seek_slider.sliderPressed.emit()
        bar._seek_slider.setValue(800)
        bar._seek_slider.sliderMoved.emit(800)
        bar._seek_slider.setValue(1400)
        bar._seek_slider.sliderMoved.emit(1400)
        # Backend position tick while scrubbing must NOT yank slider or label back
        bar.audio_player.position_changed.emit(2450)
        qapp.processEvents()
        assert seek_calls == []
        assert bar._seek_slider.value() == 1400
        assert bar._time_label.text() == "00:01 / 00:03"

        bar._seek_slider.sliderReleased.emit()
        assert seek_calls == [1400]
        assert bar.audio_player.is_playing() is True

        # 5. Stop -> resets position cleanly to 00:00, stops playback, no spurious Play
        bar._stop_btn.click()
        assert bar.audio_player.playback_state() == "stopped"
        assert bar._seek_slider.value() == 0
        assert bar._time_label.text() == "00:00 / 00:03"
        assert bar._play_btn.isEnabled() is True
        assert bar._pause_btn.isEnabled() is False
        assert bar._stop_btn.isEnabled() is False

        # 6. Seek near end -> Play to natural EOF -> updates UI, no render_requested, replay from 0 works
        bar.seek(2750)
        bar._play_btn.click()
        backend.advance_ms(600)
        qapp.processEvents()
        assert len(eofs) == 1
        assert bar.audio_player.at_end() is True
        assert bar.audio_player.playback_state() == "stopped"
        assert bar._seek_slider.value() == 3000
        assert bar._time_label.text() == "00:03 / 00:03"
        assert "Finished" in bar._status_label.text()
        assert bar._play_btn.isEnabled() is True
        assert bar._pause_btn.isEnabled() is False
        assert bar._stop_btn.isEnabled() is False
        assert render_requests == []

        bar._play_btn.click()
        assert bar.audio_player.is_playing() is True
        assert bar.audio_player.position() < 500

        # 7. Reloading WAV B replaces previous stream/resources cleanly
        releases_before = backend.release_calls
        assert bar.set_rendered_wav(wav_b) is True
        assert backend.release_calls > releases_before
        assert bar._seek_slider.maximum() == 1200
        assert bar._seek_slider.value() == 0
        assert bar._time_label.text() == "00:00 / 00:01"
        assert errors == []

        # 8. shutdown() releases backend and detaches signal handlers safely
        bar.shutdown()
        assert bar.audio_player.is_loaded() is False
        assert bar._play_btn.isEnabled() is False
        status_snapshot = bar._status_label.text()
        backend._emit_state(QtAudio.State.ActiveState)
        assert bar._status_label.text() == status_snapshot
    finally:
        bar.shutdown()


def test_transport_bar_error_handling_missing_device_and_corrupt_wav(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    good_wav = _write_test_wav(tmp_path / "good.wav", duration_s=0.5)
    bad_wav = tmp_path / "bad.wav"
    bad_wav.write_text("NOT A RIFF WAVE FILE", encoding="utf-8")

    # Missing audio output device
    no_dev_backend = _FakeUiAudioBackend(has_device=False)
    bar = TransportBar(audio_backend=no_dev_backend)
    bar_errs: list[str] = []
    bar.playback_error.connect(bar_errs.append)
    try:
        assert bar.set_rendered_wav(good_wav) is False
        assert len(bar_errs) == 1
        assert AUDIO_ERR_NO_DEVICE in bar_errs[0]
        assert "Traceback" not in bar_errs[0]
        assert bar._play_btn.isEnabled() is False
        assert bar._seek_slider.isEnabled() is False

        # Corrupt WAV on working device
        dev_backend = _FakeUiAudioBackend(has_device=True)
        bar2 = TransportBar(audio_backend=dev_backend)
        bar2_errs: list[str] = []
        bar2.playback_error.connect(bar2_errs.append)
        try:
            assert bar2.set_rendered_wav(bad_wav) is False
            assert len(bar2_errs) == 1
            assert "INVALID_WAV" in bar2_errs[0]
            assert bar2.audio_player.is_loaded() is False
        finally:
            bar2.shutdown()
    finally:
        bar.shutdown()

    # MainWindow surfaces audio device error legibly instead of masking it or calling it Render failed
    win = MainWindow(audio_backend=_FakeUiAudioBackend(has_device=False))
    try:
        win.load_composition_file(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        win.render_current_preview()
        _wait_until(qapp, lambda: (not win._is_rendering) and (win.last_rendered_entry is not None))
        assert win._transport.audio_player.is_loaded() is False
        assert win._transport._play_btn.isEnabled() is False
        assert "Audio playback error:" in win._transport._status_label.text()
        assert "Render failed" not in win._transport._status_label.text()
        assert not win._diag_banner.isHidden()
        assert AUDIO_ERR_NO_DEVICE in win._diag_banner.text()
    finally:
        win.close()


def test_main_window_render_error_preserves_wav_rerender_replaces_and_close_releases(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeUiAudioBackend()
    win = MainWindow(audio_backend=backend)
    try:
        win.load_composition_file(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        win.render_current_preview()
        _wait_until(qapp, lambda: (not win._is_rendering) and (win.last_rendered_entry is not None))

        first_entry = win.last_rendered_entry
        assert first_entry is not None
        assert backend.load_calls == 1
        assert win._transport.audio_player.is_loaded() is True
        assert win._transport._seek_slider.maximum() > 0

        # Start playback of first WAV
        win._transport.play()
        assert win._transport.audio_player.is_playing() is True

        # Trigger a failing re-render on modified arrangement
        win.set_channel_instrument(4, "perc_snare_crisp")
        orig_render_preview = RenderService.render_preview

        def _failing_render(self, state, config):
            raise RuntimeError("Simulated synth error")

        monkeypatch.setattr(RenderService, "render_preview", _failing_render)
        win.render_current_preview()
        _wait_until(qapp, lambda: not win._is_rendering)

        # Previous WAV must stay loaded/playable, error clearly shown, sync stays OUTDATED
        assert win.last_rendered_entry is first_entry
        assert win._transport._loaded_wav == first_entry.wav_path
        assert win._transport.audio_player.is_loaded() is True
        assert "OUTDATED" in win._transport._sync_label.text()
        assert "Render failed: Simulated synth error" in win._transport._status_label.text()
        assert not win._diag_banner.isHidden()
        assert "Simulated synth error" in win._diag_banner.text()

        # Successful re-render releases first WAV resources and loads second WAV at 0
        monkeypatch.setattr(RenderService, "render_preview", orig_render_preview)
        releases_before = backend.release_calls
        win.render_current_preview()
        _wait_until(
            qapp,
            lambda: (not win._is_rendering)
            and (win.last_rendered_entry is not None)
            and (win.last_rendered_entry is not first_entry),
        )
        second_entry = win.last_rendered_entry
        assert second_entry is not None
        assert backend.load_calls == 2
        assert backend.release_calls > releases_before
        assert win._transport._loaded_wav == second_entry.wav_path
        assert win._transport.audio_player.position() == 0
        assert "UP TO DATE" in win._transport._sync_label.text()

        # Start playing again and close window -> backend released cleanly, signals detached
        win._transport.play()
        assert win._transport.audio_player.is_playing() is True
    finally:
        win.close()

    assert win._transport.audio_player.is_loaded() is False
    assert backend.state() == QtAudio.State.StoppedState
    assert not win._render_service.cache_dir.exists()
    # Late signal from backend after shutdown must NOT mutate disposed TransportBar
    prev_text = win._transport._status_label.text()
    backend._emit_state(QtAudio.State.ActiveState)
    assert win._transport._status_label.text() == prev_text


def test_ab_comparison_panel_presentation_states_and_signals(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    panel = ABComparisonPanel()
    saved: list[str] = []
    loaded: list[str] = []
    rendered: list[str] = []
    listened: list[str] = []
    switched: list[int] = []

    panel.save_slot_requested.connect(saved.append)
    panel.load_slot_requested.connect(loaded.append)
    panel.render_slot_requested.connect(rendered.append)
    panel.listen_slot_requested.connect(listened.append)
    panel.switch_ab_requested.connect(lambda: switched.append(1))

    card_a = panel.slot_card("A")
    card_b = panel.slot_card("B")

    # 1. Without composition loaded, all controls are disabled and slots report Empty
    assert panel._switch_btn.isEnabled() is False
    for card in (card_a, card_b):
        assert card._render_status_label.text() == "Empty"
        assert card._save_btn.isEnabled() is False
        assert card._load_btn.isEnabled() is False
        assert card._render_btn.isEnabled() is False
        assert card._listen_btn.isEnabled() is False
        assert card._listen_badge.isHidden() is True

    cfg_a = StudioArrangementConfig(
        channel_instruments={1: "lead_pure_sustain", 2: "bass_15khz_pure", 3: None, 4: None}
    )
    cfg_b = StudioArrangementConfig(
        channel_instruments={1: "bass_16bit_pure", 2: "harmony_soft_square", 3: None, 4: None}
    )
    dummy_wav_a = tmp_path / "var_a.wav"
    dummy_wav_a.write_bytes(b"RIFF")
    entry_a = CachedRenderEntry(
        cache_key="a_digest",
        wav_path=dummy_wav_a,
        duration_seconds=2.5,
        format_version=2,
        uses_16bit_bass=False,
        memory_size_bytes=512,
        config=cfg_a,
        arranged_ir_sha256="ir_a",
    )

    # 2. A Not rendered + valid, B Empty
    st_a_not_rend = ComparisonSlotStatus(
        slot="A",
        render_status="not_rendered",
        variant=ComparisonVariant(slot="A", config=cfg_a, label="Sustain Mix", rendered_entry=None),
        active_listen=False,
        matches_editor=True,
        is_valid_arrangement=True,
    )
    st_b_empty = ComparisonSlotStatus(slot="B", render_status="empty")
    panel.set_panel_state(has_composition=True, status_a=st_a_not_rend, status_b=st_b_empty)

    assert card_a._title_label.text() == "Sustain Mix"
    assert card_a._render_status_label.text() == "Not rendered"
    assert card_a._match_label.text() == "Matches editor"
    assert card_a._save_btn.isEnabled() is True
    assert card_a._load_btn.isEnabled() is True
    assert card_a._render_btn.isEnabled() is True
    assert card_a._listen_btn.isEnabled() is False
    assert card_b._save_btn.isEnabled() is True
    assert card_b._load_btn.isEnabled() is False
    assert panel._switch_btn.isEnabled() is False

    # 3. A Ready + Listening, B Outdated + Invalid blocking error
    st_a_ready = ComparisonSlotStatus(
        slot="A",
        render_status="ready",
        variant=ComparisonVariant(slot="A", config=cfg_a, label="Sustain Mix", rendered_entry=entry_a),
        active_listen=True,
        matches_editor=False,
        is_valid_arrangement=True,
    )
    st_b_invalid = ComparisonSlotStatus(
        slot="B",
        render_status="outdated",
        variant=ComparisonVariant(slot="B", config=cfg_b, label="Conflict Mix", rendered_entry=entry_a),
        active_listen=False,
        matches_editor=False,
        is_valid_arrangement=False,
        blocking_errors=("CH2 is reserved for 16-bit bass on CH1.",),
    )
    panel.set_panel_state(has_composition=True, status_a=st_a_ready, status_b=st_b_invalid)

    assert card_a._render_status_label.text() == "Ready"
    assert card_a._match_label.text() == "Differs from editor"
    assert card_a._listen_badge.isHidden() is False
    assert card_a._listen_btn.isEnabled() is True
    assert card_a._listen_btn.isChecked() is True
    assert "Active listening: A" in panel._active_summary_label.text()

    assert card_b._render_status_label.text() == "Outdated"
    assert "Blocked:" in card_b._detail_label.text()
    assert card_b._render_btn.isEnabled() is False
    assert "16-bit bass" in card_b._render_btn.toolTip()
    assert card_b._listen_btn.isEnabled() is False
    assert panel._switch_btn.isEnabled() is False

    # 4. Both A and B Ready + Queued/Rendering badges + Switch A/B enabled
    st_b_ready = ComparisonSlotStatus(
        slot="B",
        render_status="ready",
        variant=ComparisonVariant(slot="B", config=cfg_b, label="Punch Mix", rendered_entry=entry_a),
        active_listen=False,
        matches_editor=True,
        is_valid_arrangement=True,
    )
    panel.set_panel_state(
        has_composition=True,
        status_a=st_a_ready,
        status_b=st_b_ready,
        rendering_slot="B",
        queued_slots={"A", "B"},
        status_message="Rendering Variant B in background...",
        status_kind="info",
    )
    assert card_b._render_status_label.text() == "Rendering..."
    assert card_b._render_btn.isEnabled() is False
    assert card_a._render_status_label.text() == "Queued"
    assert card_a._render_btn.isEnabled() is False
    assert panel._switch_btn.isEnabled() is True
    assert "Rendering Variant B" in panel._status_label.text()

    # Clear rendering flags and verify every UI signal routes cleanly without managing state
    panel.set_panel_state(has_composition=True, status_a=st_a_ready, status_b=st_b_ready)
    card_a._save_btn.click()
    card_b._save_btn.click()
    card_a._load_btn.click()
    card_b._load_btn.click()
    card_a._render_btn.click()
    card_b._render_btn.click()
    card_a._listen_btn.click()
    card_b._listen_btn.click()
    panel._switch_btn.click()

    assert saved == ["A", "B"]
    assert loaded == ["A", "B"]
    assert rendered == ["A", "B"]
    assert listened == ["A", "B"]
    assert len(switched) == 1


def test_transport_bar_switch_wav_preserving_state_all_scenarios(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    wav_long = _write_test_wav(tmp_path / "long_3s.wav", duration_s=3.0)
    wav_short = _write_test_wav(tmp_path / "short_1s.wav", duration_s=1.0)
    wav_tiny = _write_test_wav(tmp_path / "tiny_40ms.wav", duration_s=0.04)
    wav_bad = tmp_path / "corrupt.wav"
    wav_bad.write_text("CORRUPT", encoding="utf-8")

    backend = _FakeUiAudioBackend(buffer_ms=100)
    bar = TransportBar(audio_backend=backend)
    state_events: list[str] = []
    pos_events: list[int] = []
    errors: list[str] = []
    eofs: list[int] = []
    bar.playback_state_changed.connect(state_events.append)
    bar.position_changed.connect(pos_events.append)
    bar.playback_error.connect(errors.append)
    bar.end_of_media.connect(lambda: eofs.append(1))

    try:
        # Baseline: ordinary set_rendered_wav still loads stopped at 0 ms
        assert bar.set_rendered_wav(wav_long) is True
        assert bar.audio_player.playback_state() == "stopped"
        assert bar.audio_player.position() == 0

        # 1. Playing -> Playing (longer -> shorter clamps to max(0, dur - 100) without immediate EOF)
        bar.seek(2500)
        bar.play()
        assert bar.audio_player.is_playing() is True
        state_events.clear()
        pos_events.clear()

        assert bar.switch_wav_preserving_state(wav_short) is True
        assert bar.audio_player.is_playing() is True
        assert bar._loaded_wav == wav_short
        assert bar._seek_slider.maximum() == 1000
        # Clamped to 1000 - 100 = 900 ms (not EOF!)
        assert 850 <= bar.audio_player.position() <= 900
        assert bar.audio_player.at_end() is False
        assert eofs == []
        # Clean state transition without bouncing through "stopped"
        assert "stopped" not in state_events
        assert state_events == ["playing"]

        # Advancing short tail reaches natural EOF cleanly
        backend.advance_ms(250)
        qapp.processEvents()
        assert len(eofs) == 1
        assert bar.audio_player.at_end() is True

        # 2. EOF -> Stopped at 0 ms (MUST NOT auto-play even with auto_play_if_stopped=True!)
        starts_before = backend.start_calls
        assert bar.switch_wav_preserving_state(wav_long, auto_play_if_stopped=True) is True
        assert backend.start_calls == starts_before
        assert bar.audio_player.playback_state() == "stopped"
        assert bar.audio_player.at_end() is False
        assert bar.audio_player.position() == 0
        assert bar._seek_slider.value() == 0
        assert bar._time_label.text() == "00:00 / 00:03"
        assert bar._play_btn.isEnabled() is True

        # 3. Shorter -> Longer preserves position accurately while Playing
        assert bar.set_rendered_wav(wav_short) is True
        bar.seek(450)
        bar.play()
        backend.advance_ms(200)  # audible position advances ~550 ms
        expected_pos = bar.audio_player.position()
        assert bar.switch_wav_preserving_state(wav_long) is True
        assert bar.audio_player.is_playing() is True
        assert bar._seek_slider.maximum() == 3000
        assert abs(bar.audio_player.position() - expected_pos) <= 5

        # 4. Very short WAV (< 100 ms): duration_ms - 100 clamped safely to 0 ms (never negative)
        bar.seek(2400)
        assert bar.switch_wav_preserving_state(wav_tiny) is True
        assert bar.audio_player.is_playing() is True
        assert bar.audio_player.position() == 0
        assert bar._seek_slider.value() == 0

        # 5. Paused -> Paused preserves pause WITHOUT ever calling backend.start()!
        assert bar.set_rendered_wav(wav_long) is True
        bar.play()
        backend.advance_ms(700)
        bar.pause()
        paused_pos = bar.audio_player.position()
        assert paused_pos > 0
        starts_before_pause_switch = backend.start_calls
        state_events.clear()

        assert bar.switch_wav_preserving_state(wav_short) is True
        # Clamped if paused_pos > 900, otherwise exact paused_pos; sink.start NEVER called!
        assert backend.start_calls == starts_before_pause_switch
        assert bar.audio_player.is_paused() is True
        assert bar._pause_btn.isEnabled() is True
        assert bar._pause_btn.text() == "Resume"
        assert bar._stop_btn.isEnabled() is True
        expected_paused = min(paused_pos, max(0, 1000 - 100))
        assert abs(bar.audio_player.position() - expected_paused) <= 2
        assert state_events == ["paused"]

        # Resume continues cleanly at prepared offset
        bar.resume()
        assert backend.start_calls == starts_before_pause_switch + 1
        assert bar.audio_player.is_playing() is True
        assert abs(bar.audio_player.position() - expected_paused) <= 5

        # 6. Stopped -> Stopped (with prior stopped seek NOT carried over!) & Stopped -> Playing
        bar.stop()
        bar.seek(1200)
        starts_stopped = backend.start_calls
        assert bar.switch_wav_preserving_state(wav_short, auto_play_if_stopped=False) is True
        assert backend.start_calls == starts_stopped
        assert bar.audio_player.playback_state() == "stopped"
        assert bar.audio_player.position() == 0
        assert bar._seek_slider.value() == 0

        assert bar.switch_wav_preserving_state(wav_long, auto_play_if_stopped=True) is True
        assert backend.start_calls == starts_stopped + 1
        assert bar.audio_player.is_playing() is True
        assert bar.audio_player.position() == 0

        # 7. Invalid / corrupt / missing WAV MUST preserve current active playback intact
        bar.seek(900)
        active_wav_before = bar._loaded_wav
        active_pos_before = bar.audio_player.position()
        assert bar.switch_wav_preserving_state(wav_bad) is False
        assert bar.switch_wav_preserving_state(tmp_path / "does_not_exist.wav") is False
        assert bar.switch_wav_preserving_state(None) is False
        assert len(errors) == 3
        assert bar._loaded_wav == active_wav_before
        assert bar.audio_player.is_playing() is True
        assert bar.audio_player.position() == active_pos_before

        # 8. Repeated A <-> B switching cycles leave sink/stream counts & state healthy
        errors.clear()
        for idx in range(10):
            nxt = wav_short if idx % 2 == 0 else wav_long
            assert bar.switch_wav_preserving_state(nxt) is True
        assert errors == []
        assert bar.audio_player.is_playing() is True
        assert bar.audio_player.is_loaded() is True
    finally:
        bar.shutdown()


def test_main_window_xex_v2_hides_stale_stage_a_warning_and_keeps_genuine_warnings(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """Opening v1 or v2 songs with target_backend='xex_v2' produces no false Stage-A banner."""
    from atari_music.api import generate_music

    win = MainWindow(audio_backend=_FakeUiAudioBackend())
    try:
        # 1. Load v1 composition (action_fast.json) with default target_backend='xex_v2'
        win.load_composition_file(REPO_ROOT / "examples" / "ai" / "action_fast.json")
        qapp.processEvents()
        assert win._working_config.target_backend == "xex_v2"
        assert win._diag_banner.isHidden() is True
        assert "not yet implemented" not in win._diag_details.toPlainText().lower()

        # 2. Assigning a v2 instrument (lead_attack_bite on CH3) keeps banner hidden (zero false warning)
        win._channel_strips[3].assignment_changed.emit(3, "lead_attack_bite")
        qapp.processEvents()
        assert win._evaluation is not None and win._evaluation.is_valid is True
        assert win._evaluation.effective_format_version == 2
        assert win._diag_banner.isHidden() is True

        # 3. Genuine MIDI_RANGE_EXCEEDED warning (lead_attack_bite on low CH2 bass) DOES show banner!
        win._channel_strips[2].assignment_changed.emit(2, "lead_attack_bite")
        qapp.processEvents()
        assert win._diag_banner.isHidden() is False
        assert "Hardware Warnings:" in win._diag_banner.text()
        assert "MIDI span" in win._diag_banner.text()
        assert "not yet implemented" not in win._diag_banner.text().lower()

        # 4. Load v2 composition with PROGRAM_CHANGE -> no false Stage-A warning
        v2_res = generate_music(
            profile="action",
            seed=9,
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
        v2_path = tmp_path / "studio_v2_ui.json"
        v2_res.save_json(v2_path)
        win.load_composition_file(v2_path)
        qapp.processEvents()
        assert win._evaluation is not None and win._evaluation.is_valid is True
        assert win._evaluation.effective_format_version == 2
        assert win._diag_banner.isHidden() is True
    finally:
        win.close()

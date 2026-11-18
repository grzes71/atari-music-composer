"""PySide6 UI vertical-slice tests for Atari Music Composer Studio."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import time

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402
from atari_music.studio.models import XexExportOptions  # noqa: E402
from atari_music.studio.ui.main_window import MainWindow  # noqa: E402
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


def test_ui_load_dsl_ch2_lock_and_no_auto_render(qapp: QApplication) -> None:
    win = MainWindow()
    try:
        win.load_composition_file(REPO_ROOT / "examples" / "songs" / "wybierak-2.dsl")
        assert win.state is not None
        assert win.state.base_uses_16bit_bass is True
        assert not win._channel_strips[2]._combo.isEnabled()
        assert not win._channel_strips[2]._lock_label.isHidden()
        assert "16-bit" in win._channel_strips[2]._lock_label.text()
        assert win.last_rendered_entry is None
        assert win._transport._render_btn.isEnabled() is True

        # Assigning CH3 must NOT trigger auto-render
        win.set_channel_instrument(3, "lead_attack_bite")
        qapp.processEvents()
        assert win.working_config.channel_instruments[3] == "lead_attack_bite"
        assert win.last_rendered_entry is None
        assert not win._is_rendering
    finally:
        win.close()


def test_ui_render_outdated_invalid_guard_and_revert(qapp: QApplication) -> None:
    win = MainWindow()
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
        assert win._transport._render_btn.isEnabled() is False
        assert not win._diag_banner.isHidden()
        assert "Validation Error:" in win._diag_banner.text()

        # Revert Original restores valid baseline cleanly
        win.revert_to_original()
        qapp.processEvents()
        assert win.working_config == win.state.baseline_config
        assert win.evaluation.is_valid is True
        assert win._transport._render_btn.isEnabled() is True
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

    win = MainWindow()
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

"""PySide6 UI vertical-slice tests for Atari Music Composer Studio."""

from __future__ import annotations

import os
from pathlib import Path
import time

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402
from atari_music.studio.ui.main_window import MainWindow  # noqa: E402

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

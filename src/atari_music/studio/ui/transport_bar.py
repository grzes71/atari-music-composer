"""Simple Play/Stop audio preview and background render status bar (Vertical Slice)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class TransportBar(QFrame):
    """Explicit Render Preview + Play/Stop audio controls and sync/progress indicator."""

    render_requested = Signal()
    playback_error = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._loaded_wav: Optional[Path] = None

        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        controls_row = QHBoxLayout()
        self._render_btn = QPushButton("Render Preview")
        self._render_btn.setEnabled(False)
        self._render_btn.clicked.connect(self.render_requested.emit)
        controls_row.addWidget(self._render_btn)

        self._play_btn = QPushButton("Play")
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self.play)
        controls_row.addWidget(self._play_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop)
        controls_row.addWidget(self._stop_btn)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(180)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        controls_row.addWidget(self._progress)

        self._status_label = QLabel("Load a composition to begin.")
        self._status_label.setWordWrap(True)
        controls_row.addWidget(self._status_label, stretch=1)
        root.addLayout(controls_row)

        self._sync_label = QLabel("Rendered preview: None")
        self._sync_label.setWordWrap(True)
        root.addWidget(self._sync_label)

    def set_render_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._render_btn.setEnabled(enabled)
        self._render_btn.setToolTip(tooltip)

    def set_rendering(self, busy: bool, status_text: Optional[str] = None) -> None:
        if busy:
            self._progress.setRange(0, 0)
            self._render_btn.setEnabled(False)
            self._status_label.setText(status_text or "Rendering WAV preview in background...")
        else:
            self._progress.setRange(0, 1)
            self._progress.setValue(1 if self._loaded_wav is not None else 0)
            if status_text is not None:
                self._status_label.setText(status_text)

    def set_rendered_wav(self, wav_path: Optional[Path]) -> None:
        self.stop_and_release()
        self._loaded_wav = wav_path
        if wav_path is not None and wav_path.is_file():
            self._player.setSource(QUrl.fromLocalFile(str(wav_path)))
            self._play_btn.setEnabled(True)
            self._progress.setRange(0, 1)
            self._progress.setValue(1)
        else:
            self._play_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            self._progress.setRange(0, 1)
            self._progress.setValue(0)

    def set_sync_status(self, message: str, *, state_kind: str = "neutral") -> None:
        self._sync_label.setText(message)
        if state_kind == "up_to_date":
            self._sync_label.setStyleSheet("color: #1b6e1b; font-weight: bold;")
        elif state_kind == "outdated":
            self._sync_label.setStyleSheet("color: #9e4700; font-weight: bold;")
        elif state_kind == "error":
            self._sync_label.setStyleSheet("color: #b00020; font-weight: bold;")
        else:
            self._sync_label.setStyleSheet("")

    def set_status_text(self, message: str) -> None:
        self._status_label.setText(message)

    def play(self) -> None:
        if self._loaded_wav is None or not self._loaded_wav.is_file():
            return
        if self._player.source().isEmpty():
            self._player.setSource(QUrl.fromLocalFile(str(self._loaded_wav)))
        self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def stop_and_release(self) -> None:
        """Stop playback and clear source so OS file handles on temp WAVs are released."""
        self._player.stop()
        self._player.setSource(QUrl())
        self._stop_btn.setEnabled(False)

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._stop_btn.setEnabled(is_playing)
        self._play_btn.setEnabled((self._loaded_wav is not None) and not is_playing)
        if is_playing:
            self._status_label.setText(f"Playing: {self._loaded_wav.name if self._loaded_wav else ''}")
        elif self._loaded_wav is not None:
            self._status_label.setText(f"Stopped ({self._loaded_wav.name})")

    def _on_player_error(self, _error: QMediaPlayer.Error, error_string: str) -> None:
        if error_string:
            self._status_label.setText(f"Audio playback error: {error_string}")
            self.playback_error.emit(error_string)

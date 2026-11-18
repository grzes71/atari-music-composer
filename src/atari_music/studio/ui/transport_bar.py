"""PCM audio preview transport and background render status bar."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from atari_music.studio.ui.audio_player import (
    AudioPlaybackError,
    AudioSinkBackend,
    StudioAudioPlayer,
    load_wav_pcm,
)


def format_time_ms(ms: int) -> str:
    """Format milliseconds as ``MM:SS``, supporting tracks longer than 59 minutes."""
    total_seconds = max(0, int(ms) // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


class TransportBar(QFrame):
    """PCM audio transport controls (Play/Pause/Stop/Seek) and render progress/sync indicator."""

    render_requested = Signal()  # Legacy compatibility signal; Render Preview lives in Global Action Bar.
    playback_error = Signal(str)
    playback_state_changed = Signal(str)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    end_of_media = Signal()

    def __init__(
        self,
        parent=None,
        *,
        audio_player: Optional[StudioAudioPlayer] = None,
        audio_backend: Optional[AudioSinkBackend] = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._player: StudioAudioPlayer = (
            audio_player
            if audio_player is not None
            else StudioAudioPlayer(backend=audio_backend, parent=self)
        )
        self._loaded_wav: Optional[Path] = None
        self._is_scrubbing: bool = False
        self._suppress_player_updates: bool = False
        self._disposed: bool = False

        self._player.playback_state_changed.connect(self._on_playback_state_changed)
        self._player.position_changed.connect(self._on_position_changed)
        self._player.duration_changed.connect(self._on_duration_changed)
        self._player.end_of_media.connect(self._on_end_of_media)
        self._player.error_occurred.connect(self._on_player_error)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        controls_row = QHBoxLayout()
        self._play_btn = QPushButton("Play")
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self.play)
        controls_row.addWidget(self._play_btn)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self.toggle_pause)
        controls_row.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop)
        controls_row.addWidget(self._stop_btn)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(130)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        controls_row.addWidget(self._progress)

        self._status_label = QLabel("Load a composition to begin.")
        self._status_label.setWordWrap(True)
        controls_row.addWidget(self._status_label, stretch=1)
        root.addLayout(controls_row)

        seek_row = QHBoxLayout()
        seek_caption = QLabel("Seek:")
        seek_row.addWidget(seek_caption)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setEnabled(False)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.setValue(0)
        self._seek_slider.setSingleStep(500)
        self._seek_slider.setPageStep(2000)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        self._seek_slider.valueChanged.connect(self._on_slider_value_changed)
        seek_row.addWidget(self._seek_slider, stretch=1)

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setMinimumWidth(96)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self._time_label)
        root.addLayout(seek_row)

        self._sync_label = QLabel("Rendered preview: None")
        self._sync_label.setWordWrap(True)
        root.addWidget(self._sync_label)

    @property
    def audio_player(self) -> StudioAudioPlayer:
        return self._player

    def set_rendering(self, busy: bool, status_text: Optional[str] = None) -> None:
        if busy:
            self._progress.setRange(0, 0)
            self._status_label.setText(status_text or "Rendering WAV preview in background...")
        else:
            self._progress.setRange(0, 1)
            self._progress.setValue(1 if self._loaded_wav is not None else 0)
            if status_text is not None:
                self._status_label.setText(status_text)

    def set_rendered_wav(self, wav_path: Optional[Path]) -> bool:
        self.stop_and_release()
        if wav_path is None:
            return False
        if not wav_path.is_file():
            self._on_player_error(f"Rendered WAV file not found: '{wav_path}'.")
            return False

        self._loaded_wav = wav_path
        ok = self._player.load(wav_path)
        if not ok:
            self._loaded_wav = None
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
            with QSignalBlocker(self._seek_slider):
                self._seek_slider.setRange(0, 0)
                self._seek_slider.setValue(0)
            self._update_time_label(0, 0)
            self._update_controls()
            return False

        dur_ms = self._player.duration()
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setRange(0, dur_ms)
            self._seek_slider.setValue(0)
        self._update_time_label(0, dur_ms)
        self._update_controls()
        return True

    def _report_non_destructive_error(self, message: str) -> None:
        if message:
            self._status_label.setText(f"Audio playback error: {message}")
            self.playback_error.emit(message)

    def switch_wav_preserving_state(
        self,
        wav_path: Optional[Path],
        *,
        auto_play_if_stopped: bool = True,
    ) -> bool:
        """Load *wav_path* while preserving active playback/pause state and clamped time position.

        Validates the candidate WAV and device availability before touching the active stream
        so an invalid/missing target never interrupts or corrupts current playback.
        """
        if self._disposed:
            return False
        if wav_path is None:
            self._report_non_destructive_error("Cannot switch audio: no WAV file provided.")
            return False

        try:
            load_wav_pcm(wav_path)
        except AudioPlaybackError as exc:
            self._report_non_destructive_error(str(exc))
            return False

        if not self._player.has_output_device():
            self._report_non_destructive_error("No audio output device is available on this system.")
            return False

        prev_loaded = self._player.is_loaded()
        prev_state = self._player.playback_state() if prev_loaded else "stopped"
        prev_pos_ms = self._player.position() if prev_loaded else 0
        was_at_end = self._player.at_end() if prev_loaded else False

        self._is_scrubbing = False
        self._suppress_player_updates = True
        try:
            ok = self._player.load(wav_path)
        finally:
            self._suppress_player_updates = False

        if not ok:
            self._loaded_wav = None
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
            with QSignalBlocker(self._seek_slider):
                self._seek_slider.setRange(0, 0)
                self._seek_slider.setValue(0)
            self._update_time_label(0, 0)
            self._update_controls()
            err = self._player.last_error() or "Failed to initialize audio output."
            self._report_non_destructive_error(err)
            return False

        self._loaded_wav = wav_path
        dur_ms = self._player.duration()
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setRange(0, dur_ms)
            self._seek_slider.setValue(0)
        self.duration_changed.emit(dur_ms)

        if prev_state == "playing":
            target_ms = min(max(0, prev_pos_ms), max(0, dur_ms - 100))
            if target_ms > 0:
                self._suppress_player_updates = True
                try:
                    self._player.seek(target_ms)
                finally:
                    self._suppress_player_updates = False
            started = self._player.play()
            if not started:
                self._update_controls()
                return False
            return True

        if prev_state == "paused":
            target_ms = min(max(0, prev_pos_ms), max(0, dur_ms - 100))
            self._player.prepare_paused_at(target_ms)
            return True

        # Previous track ended at EOF or was stopped cleanly: start target at 0 ms (never carry stopped cursor or EOF).
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setValue(0)
        self._update_time_label(0, dur_ms)

        if (not was_at_end) and auto_play_if_stopped:
            return self._player.play()

        self._update_controls()
        self._status_label.setText(f"Stopped ({wav_path.name})")
        self.position_changed.emit(0)
        self.playback_state_changed.emit("stopped")
        return True

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
        if self._disposed or not self._player.is_loaded():
            return
        self._player.play()

    def pause(self) -> None:
        if self._disposed or not self._player.is_loaded():
            return
        self._player.pause()

    def resume(self) -> None:
        if self._disposed or not self._player.is_loaded():
            return
        self._player.resume()

    def toggle_pause(self) -> None:
        if self._disposed or not self._player.is_loaded():
            return
        if self._player.is_paused():
            self.resume()
        elif self._player.is_playing():
            self.pause()

    def stop(self) -> None:
        if self._disposed:
            return
        self._is_scrubbing = False
        self._player.stop()

    def seek(self, position_ms: int) -> int:
        if self._disposed or not self._player.is_loaded():
            return 0
        aligned = self._player.seek(position_ms)
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setValue(aligned)
        self._update_time_label(aligned, self._player.duration())
        self._update_controls()
        return aligned

    def stop_and_release(self) -> None:
        """Stop playback, release audio sink/device handles, and reset transport controls."""
        self._is_scrubbing = False
        self._loaded_wav = None
        self._suppress_player_updates = True
        try:
            self._player.release()
        finally:
            self._suppress_player_updates = False
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setRange(0, 0)
            self._seek_slider.setValue(0)
        self._update_time_label(0, 0)
        self._update_controls()

    def shutdown(self) -> None:
        """Release audio resources and disconnect player signals permanently on widget teardown."""
        if self._disposed:
            return
        self.stop_and_release()
        self._disposed = True
        for sig, slot in (
            (self._player.playback_state_changed, self._on_playback_state_changed),
            (self._player.position_changed, self._on_position_changed),
            (self._player.duration_changed, self._on_duration_changed),
            (self._player.end_of_media, self._on_end_of_media),
            (self._player.error_occurred, self._on_player_error),
        ):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_and_release()
        super().closeEvent(event)

    def _update_time_label(self, pos_ms: int, dur_ms: int) -> None:
        dur_safe = max(0, int(dur_ms))
        pos_safe = max(0, min(int(pos_ms), dur_safe) if dur_safe > 0 else int(pos_ms))
        self._time_label.setText(f"{format_time_ms(pos_safe)} / {format_time_ms(dur_safe)}")

    def _update_controls(self) -> None:
        loaded = (not self._disposed) and self._player.is_loaded() and (self._loaded_wav is not None)
        state = self._player.playback_state()
        is_playing = state == "playing"
        is_paused = state == "paused"

        self._play_btn.setEnabled(loaded and not is_playing)
        self._pause_btn.setText("Resume" if is_paused else "Pause")
        self._pause_btn.setEnabled(loaded and (is_playing or is_paused))

        can_stop = loaded and (
            is_playing
            or is_paused
            or (not self._player.at_end() and self._player.position() > 0)
        )
        self._stop_btn.setEnabled(can_stop)
        self._seek_slider.setEnabled(loaded and self._player.duration() > 0)

    def _on_slider_pressed(self) -> None:
        if self._disposed or not self._player.is_loaded():
            return
        self._is_scrubbing = True

    def _on_slider_moved(self, value: int) -> None:
        if self._disposed or not self._player.is_loaded():
            return
        # Update visual clock only while dragging; actual seek commits on release.
        self._update_time_label(value, self._player.duration())

    def _on_slider_released(self) -> None:
        if self._disposed:
            return
        was_scrubbing = self._is_scrubbing
        self._is_scrubbing = False
        if not self._player.is_loaded():
            return
        if was_scrubbing or self._seek_slider.isEnabled():
            self.seek(self._seek_slider.value())

    def _on_slider_value_changed(self, value: int) -> None:
        if self._disposed or not self._player.is_loaded():
            return
        if self._is_scrubbing or self._seek_slider.isSliderDown():
            self._update_time_label(value, self._player.duration())
            return
        # Discrete user action without drag (track click / keyboard arrow / page step)
        self.seek(value)

    def _on_playback_state_changed(self, state: str) -> None:
        if self._disposed or self._suppress_player_updates:
            return
        self._update_controls()
        name = self._loaded_wav.name if self._loaded_wav is not None else ""
        if state == "playing":
            self._status_label.setText(f"Playing: {name}" if name else "Playing")
        elif state == "paused":
            self._status_label.setText(f"Paused: {name}" if name else "Paused")
        elif state == "stopped" and self._loaded_wav is not None:
            if self._player.at_end():
                self._status_label.setText(f"Finished ({name})")
            else:
                self._status_label.setText(f"Stopped ({name})")
        self.playback_state_changed.emit(state)

    def _on_position_changed(self, pos_ms: int) -> None:
        if self._disposed or self._suppress_player_updates:
            return
        if not self._is_scrubbing and not self._seek_slider.isSliderDown():
            with QSignalBlocker(self._seek_slider):
                self._seek_slider.setValue(max(0, int(pos_ms)))
            self._update_time_label(pos_ms, self._player.duration())
        if self._player.playback_state() == "stopped":
            self._update_controls()
        self.position_changed.emit(pos_ms)

    def _on_duration_changed(self, dur_ms: int) -> None:
        if self._disposed or self._suppress_player_updates:
            return
        safe_dur = max(0, int(dur_ms))
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setRange(0, safe_dur)
        if not self._is_scrubbing:
            self._update_time_label(self._player.position(), safe_dur)
        self._update_controls()
        self.duration_changed.emit(safe_dur)

    def _on_end_of_media(self) -> None:
        if self._disposed or self._suppress_player_updates:
            return
        self._is_scrubbing = False
        dur_ms = self._player.duration()
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setValue(dur_ms)
        self._update_time_label(dur_ms, dur_ms)
        self._update_controls()
        if self._loaded_wav is not None:
            self._status_label.setText(f"Finished ({self._loaded_wav.name})")
        self.end_of_media.emit()

    def _on_player_error(self, error_string: str) -> None:
        if self._disposed or self._suppress_player_updates:
            return
        self._is_scrubbing = False
        self._update_controls()
        if error_string:
            self._status_label.setText(f"Audio playback error: {error_string}")
            self.playback_error.emit(error_string)

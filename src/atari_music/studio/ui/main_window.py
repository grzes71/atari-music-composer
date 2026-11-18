"""PySide6 MainWindow for Atari Music Composer Studio — Vertical Slice MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from atari_music.studio.exporter import ExportService, PreparedXexArrangement
from atari_music.studio.instruments import InstrumentService
from atari_music.studio.loader import load_studio_composition
from atari_music.studio.models import (
    ArrangementEvaluation,
    CachedRenderEntry,
    LoadedCompositionState,
    StudioArrangementConfig,
    XexExportOptions,
    XexExportResult,
)
from atari_music.studio.renderer import RenderService
from atari_music.studio.ui.channel_strip import ChannelStripWidget
from atari_music.studio.ui.instrument_picker import InstrumentCatalogInspector
from atari_music.studio.ui.transport_bar import TransportBar
from atari_music.studio.ui.worker import ExportXexWorker, RenderWorker
from atari_music.studio.ui.xex_export_dialog import XexExportDialog


def _format_config_summary(config: StudioArrangementConfig) -> str:
    parts = [
        f"CH{ch}={config.channel_instruments.get(ch) or 'orig'}"
        for ch in (1, 2, 3, 4)
    ]
    return (
        f"{', '.join(parts)} | pc={config.program_change_policy} | "
        f"player={config.player_version} | target={config.target_backend}"
    )


class MainWindow(QMainWindow):
    """Instrument Explorer main window (explicit Render Preview, zero auto-render)."""

    xex_export_succeeded = Signal(object)  # XexExportResult
    xex_export_failed = Signal(str)  # error_message

    def __init__(
        self,
        *,
        catalog_path: Optional[Path] = None,
        initial_file: Optional[Path] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atari Music Composer Studio — Instrument Explorer")
        self.resize(1120, 740)

        self._instrument_service = InstrumentService(catalog_path=catalog_path)
        self._render_service = RenderService(self._instrument_service)
        self._export_service = ExportService(self._instrument_service)
        self._thread_pool = QThreadPool.globalInstance()

        self._state: Optional[LoadedCompositionState] = None
        self._working_config: StudioArrangementConfig = StudioArrangementConfig()
        self._evaluation: Optional[ArrangementEvaluation] = None
        self._last_rendered_entry: Optional[CachedRenderEntry] = None
        self._last_exported_result: Optional[XexExportResult] = None
        self._selected_channel: int = 1
        self._active_request_id: int = 0
        self._active_export_request_id: int = 0
        self._is_rendering: bool = False
        self._is_exporting: bool = False
        self._updating_controls: bool = False
        self._open_workers: Dict[int, RenderWorker] = {}
        self._open_export_workers: Dict[int, ExportXexWorker] = {}
        self._custom_mads_bin: Optional[Path] = None
        self._custom_player_asm: Optional[Path] = None

        self._build_ui()
        if initial_file is not None:
            self.load_composition_file(initial_file)

    @property
    def state(self) -> Optional[LoadedCompositionState]:
        return self._state

    @property
    def working_config(self) -> StudioArrangementConfig:
        return self._working_config

    @property
    def evaluation(self) -> Optional[ArrangementEvaluation]:
        return self._evaluation

    @property
    def last_rendered_entry(self) -> Optional[CachedRenderEntry]:
        return self._last_rendered_entry

    @property
    def last_exported_result(self) -> Optional[XexExportResult]:
        return self._last_exported_result

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Toolbar row
        top_bar = QHBoxLayout()
        self._open_btn = QPushButton("Open Composition (.json / .dsl)...")
        self._open_btn.clicked.connect(self._on_open_clicked)
        top_bar.addWidget(self._open_btn)

        self._revert_btn = QPushButton("Revert Original")
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self.revert_to_original)
        top_bar.addWidget(self._revert_btn)

        self._export_xex_btn = QPushButton("Export XEX...")
        self._export_xex_btn.setEnabled(False)
        self._export_xex_btn.setToolTip("Load a composition first.")
        self._export_xex_btn.clicked.connect(self._on_export_xex_clicked)
        top_bar.addWidget(self._export_xex_btn)

        top_bar.addStretch(1)
        root.addLayout(top_bar)

        # Metadata banner
        meta_frame = QFrame()
        meta_frame.setFrameShape(QFrame.Shape.StyledPanel)
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setContentsMargins(8, 6, 8, 6)
        self._meta_label = QLabel("No composition loaded. Click 'Open Composition' to load a .json or .dsl file.")
        self._meta_label.setWordWrap(True)
        meta_layout.addWidget(self._meta_label)

        self._config_diff_label = QLabel("Selected config: - | Last rendered: None")
        self._config_diff_label.setWordWrap(True)
        meta_layout.addWidget(self._config_diff_label)
        root.addWidget(meta_frame)

        # Main split: Left (4 Channels + policy controls) | Right (Catalog Inspector)
        splitter = QSplitter()
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        self._channel_strips: Dict[int, ChannelStripWidget] = {}
        for ch in (1, 2, 3, 4):
            strip = ChannelStripWidget(ch)
            strip.assignment_changed.connect(self.set_channel_instrument)
            strip.selected_for_inspect.connect(self.select_channel_for_inspect)
            self._channel_strips[ch] = strip
            left_layout.addWidget(strip)

        # Arrangement policy / player / target controls
        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("PROGRAM_CHANGE policy:"))
        self._pc_policy_combo = QComboBox()
        for pol in ("preserve", "replace", "remove"):
            self._pc_policy_combo.addItem(pol, pol)
        self._pc_policy_combo.currentIndexChanged.connect(self._on_policy_changed)
        policy_row.addWidget(self._pc_policy_combo)

        policy_row.addWidget(QLabel("Player:"))
        self._player_ver_combo = QComboBox()
        for pv in ("auto", "v1", "v2"):
            self._player_ver_combo.addItem(pv, pv)
        self._player_ver_combo.currentIndexChanged.connect(self._on_player_ver_changed)
        policy_row.addWidget(self._player_ver_combo)

        policy_row.addWidget(QLabel("Target:"))
        self._target_combo = QComboBox()
        for tgt in ("xex_v2", "xex_v1", "wav"):
            self._target_combo.addItem(tgt, tgt)
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)
        policy_row.addWidget(self._target_combo)
        policy_row.addStretch(1)
        left_layout.addLayout(policy_row)
        left_layout.addStretch(1)

        splitter.addWidget(left_panel)

        self._inspector = InstrumentCatalogInspector(self._instrument_service.catalog)
        self._inspector.apply_requested.connect(self.set_channel_instrument)
        splitter.addWidget(self._inspector)
        splitter.setSizes([560, 520])
        root.addWidget(splitter, stretch=1)

        # Validation diagnostics banner
        self._diag_banner = QLabel("")
        self._diag_banner.setWordWrap(True)
        self._diag_banner.setVisible(False)
        root.addWidget(self._diag_banner)

        # Bottom audio preview & transport
        self._transport = TransportBar()
        self._transport.render_requested.connect(self.render_current_preview)
        self._transport.playback_error.connect(self._show_error_banner)
        root.addWidget(self._transport)

        self._refresh_channel_selection_highlight()

    def _on_open_clicked(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Open Atari Music Composition",
            str(Path.cwd()),
            "Compositions (*.json *.dsl);;Music DSL (*.dsl);;JSON (*.json);;All Files (*)",
        )
        if chosen:
            try:
                self.load_composition_file(Path(chosen))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Failed to Open Composition", str(exc))

    def load_composition_file(self, path: Path) -> None:
        state = load_studio_composition(path)
        self._active_request_id += 1  # Invalidate any in-flight render
        self._active_export_request_id += 1  # Invalidate any in-flight XEX export
        self._is_rendering = False
        self._is_exporting = False
        self._transport.stop_and_release()
        self._transport.set_rendered_wav(None)
        self._transport.set_rendering(False, "Composition loaded. Click 'Render Preview' to synthesize WAV.")

        self._state = state
        self._working_config = state.baseline_config
        self._last_rendered_entry = None
        self._last_exported_result = None
        self._selected_channel = 1 if state.channels[1].active else 3
        self._revert_btn.setEnabled(True)
        self._export_xex_btn.setEnabled(True)
        self._export_xex_btn.setText("Export XEX...")

        self._sync_policy_combos_from_config()
        self._reevaluate_and_refresh_ui()

    def set_channel_instrument(self, channel: int, instrument_id: Optional[str]) -> None:
        if self._state is None:
            return
        updated = self._working_config.with_channel(channel, instrument_id)
        if updated == self._working_config:
            return
        self._working_config = updated
        # Note: deliberately does NOT trigger automatic rendering!
        self._reevaluate_and_refresh_ui()

    def select_channel_for_inspect(self, channel: int) -> None:
        self._selected_channel = int(channel)
        self._refresh_channel_selection_highlight()
        if self._evaluation is not None:
            self._inspector.set_slot_evaluation(self._evaluation.channels.get(self._selected_channel))

    def revert_to_original(self) -> None:
        if self._state is None:
            return
        self._working_config = self._state.baseline_config
        self._sync_policy_combos_from_config()
        self._reevaluate_and_refresh_ui()

    def _on_policy_changed(self, _idx: int) -> None:
        if self._updating_controls or self._state is None:
            return
        pol = self._pc_policy_combo.currentData()
        self._working_config = self._working_config.model_copy(update={"program_change_policy": pol})
        self._reevaluate_and_refresh_ui()

    def _on_player_ver_changed(self, _idx: int) -> None:
        if self._updating_controls or self._state is None:
            return
        pv = self._player_ver_combo.currentData()
        self._working_config = self._working_config.model_copy(update={"player_version": pv})
        self._reevaluate_and_refresh_ui()

    def _on_target_changed(self, _idx: int) -> None:
        if self._updating_controls or self._state is None:
            return
        tgt = self._target_combo.currentData()
        self._working_config = self._working_config.model_copy(update={"target_backend": tgt})
        self._reevaluate_and_refresh_ui()

    def _sync_policy_combos_from_config(self) -> None:
        self._updating_controls = True
        try:
            for combo, val in (
                (self._pc_policy_combo, self._working_config.program_change_policy),
                (self._player_ver_combo, self._working_config.player_version),
                (self._target_combo, self._working_config.target_backend),
            ):
                idx = combo.findData(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        finally:
            self._updating_controls = False

    def _refresh_channel_selection_highlight(self) -> None:
        for ch, strip in self._channel_strips.items():
            strip.set_selected(ch == self._selected_channel)

    def _reevaluate_and_refresh_ui(self) -> None:
        if self._state is None:
            for strip in self._channel_strips.values():
                strip.clear_state()
            self._inspector.set_slot_evaluation(None)
            self._transport.set_render_enabled(False, "Load a composition first.")
            self._export_xex_btn.setEnabled(False)
            self._export_xex_btn.setToolTip("Load a composition first.")
            return

        evaluation = self._instrument_service.evaluate_arrangement(self._state, self._working_config)
        self._evaluation = evaluation

        # Update metadata banner
        mode_str = "16-bit CH1+CH2" if evaluation.effective_uses_16bit_bass else "8-bit"
        fmt_str = f"v{evaluation.effective_format_version}" if evaluation.effective_format_version else "invalid"
        pc_total = sum(c.program_change_count for c in self._state.channels.values())
        self._meta_label.setText(
            f"Title: {self._state.title} | Author: {self._state.author} | Source: {self._state.source_kind} | "
            f"Key: {self._state.key} {self._state.mode} | BPM: {self._state.tempo_bpm} | "
            f"Patterns: {self._state.pattern_count} | Seq: {self._state.sequence_length} | "
            f"Mode: {mode_str} | Format: {fmt_str} | AUDCTL: ${evaluation.effective_audctl:02X} | "
            f"PROGRAM_CHANGE events: {pc_total}"
        )

        # Keep inspected channel valid if CH2 became locked
        if not evaluation.channels[self._selected_channel].available_for_assignment:
            self._selected_channel = 1
        self._refresh_channel_selection_highlight()

        for ch in (1, 2, 3, 4):
            self._channel_strips[ch].update_state(
                self._state.channels[ch],
                evaluation.channels[ch],
                self._working_config.channel_instruments.get(ch),
            )
        self._inspector.set_slot_evaluation(evaluation.channels[self._selected_channel])

        # Diagnostics banner
        if evaluation.blocking_errors:
            self._diag_banner.setText("Validation Error: " + " | ".join(evaluation.blocking_errors))
            self._diag_banner.setStyleSheet(
                "background-color: #fdecea; color: #900018; padding: 6px; border: 1px solid #f5c6cb;"
            )
            self._diag_banner.setVisible(True)
        elif evaluation.warnings:
            self._diag_banner.setText("Hardware Warnings: " + " | ".join(evaluation.warnings))
            self._diag_banner.setStyleSheet(
                "background-color: #fff8e1; color: #7a4b00; padding: 6px; border: 1px solid #ffe082;"
            )
            self._diag_banner.setVisible(True)
        else:
            self._diag_banner.setVisible(False)

        # Compare working config vs last rendered preview
        working_key = self._render_service.build_cache_key(self._state, self._working_config).digest()
        working_summary = _format_config_summary(self._working_config)
        if self._last_rendered_entry is None:
            self._config_diff_label.setText(
                f"Selected: {working_summary}\nLast rendered: None (click 'Render Preview' to generate WAV)"
            )
            self._transport.set_sync_status(
                "No rendered preview yet — audio will be synthesized when you click 'Render Preview'.",
                state_kind="neutral",
            )
        elif self._last_rendered_entry.cache_key == working_key:
            rend_summary = _format_config_summary(self._last_rendered_entry.config)
            self._config_diff_label.setText(
                f"Selected: {working_summary}\nLast rendered: {rend_summary} "
                f"({self._last_rendered_entry.duration_seconds:.2f}s, v{self._last_rendered_entry.format_version})"
            )
            self._transport.set_sync_status(
                f"Preview UP TO DATE — matches current selection "
                f"(Format v{self._last_rendered_entry.format_version}, {self._last_rendered_entry.duration_seconds:.2f}s).",
                state_kind="up_to_date",
            )
        else:
            rend_summary = _format_config_summary(self._last_rendered_entry.config)
            self._config_diff_label.setText(
                f"Selected: {working_summary}\nLast rendered (prior): {rend_summary}"
            )
            self._transport.set_sync_status(
                "OUTDATED PREVIEW — current instrument selection has changed since the last render. "
                "Click 'Render Preview' to hear updated instruments.",
                state_kind="outdated",
            )

        # Render & XEX export button guards
        if self._is_rendering:
            self._transport.set_render_enabled(False, "Render already in progress...")
        elif not evaluation.is_valid:
            self._transport.set_render_enabled(
                False,
                "Cannot render invalid configuration:\n" + "\n".join(evaluation.blocking_errors),
            )
        else:
            self._transport.set_render_enabled(True, "Arrange and synthesize WAV for current selection.")

        if self._is_exporting:
            self._export_xex_btn.setEnabled(False)
            self._export_xex_btn.setText("Exporting XEX...")
            self._export_xex_btn.setToolTip("XEX compilation in progress...")
        else:
            self._export_xex_btn.setEnabled(True)
            self._export_xex_btn.setText("Export XEX...")
            self._export_xex_btn.setToolTip(
                "Compile the current working configuration to an Atari .xex binary via MADS."
            )

    def _current_preview_sync_note(self) -> str:
        if self._state is None:
            return "No composition loaded"
        if self._last_rendered_entry is None:
            return "No WAV preview rendered yet (export uses current working configuration)"
        working_key = self._render_service.build_cache_key(self._state, self._working_config).digest()
        if self._last_rendered_entry.cache_key == working_key:
            return "UP TO DATE with current working configuration"
        return "OUTDATED WAV preview (export uses current working configuration)"

    def _on_export_xex_clicked(self) -> None:
        if self._state is None or self._is_exporting:
            return
        prepared = self._export_service.prepare_xex_export(self._state, self._working_config)
        dialog = XexExportDialog(
            self._state,
            prepared,
            self._current_preview_sync_note(),
            initial_mads=self._custom_mads_bin,
            initial_player_asm=self._custom_player_asm,
            parent=self,
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self._custom_mads_bin = dialog.selected_mads_bin()
        self._custom_player_asm = dialog.selected_player_asm()
        self.export_prepared_xex(prepared, dialog.build_options())

    def export_xex(self, options: XexExportOptions) -> None:
        """Prepare the current working configuration once and compile XEX in background."""
        if self._state is None:
            return
        prepared = self._export_service.prepare_xex_export(self._state, self._working_config)
        self.export_prepared_xex(prepared, options)

    def export_prepared_xex(
        self,
        prepared: PreparedXexArrangement,
        options: XexExportOptions,
    ) -> None:
        """Execute background MADS compilation and atomic commit for *prepared*."""
        if self._state is None or self._is_exporting:
            return
        self._active_export_request_id += 1
        req_id = self._active_export_request_id
        self._is_exporting = True
        self._reevaluate_and_refresh_ui()
        self.statusBar().showMessage(f"Exporting XEX to {options.output_path.name} in background...")

        worker = ExportXexWorker(req_id, self._export_service, prepared, options)
        self._open_export_workers[req_id] = worker
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.failed.connect(self._on_export_failed)
        self._thread_pool.start(worker)

    def _on_export_finished(self, request_id: int, result: XexExportResult) -> None:
        self._open_export_workers.pop(request_id, None)
        if request_id != self._active_export_request_id:
            return
        self._is_exporting = False
        self._last_exported_result = result
        seg_txt = ", ".join(f"${start:04X}-${end:04X}" for start, end, _role in result.segments)
        asm_note = f" | ASM: {result.asm_path.name}" if result.asm_path is not None else ""
        msg = (
            f"Exported XEX -> {result.xex_path} ({result.size_bytes} bytes, Format v{result.format_version}"
            f"{asm_note}) | Segments: {seg_txt}"
        )
        self.statusBar().showMessage(msg)
        self._show_info_banner(msg)
        self._reevaluate_and_refresh_ui()
        self.xex_export_succeeded.emit(result)

    def _on_export_failed(self, request_id: int, error_message: str) -> None:
        self._open_export_workers.pop(request_id, None)
        if request_id != self._active_export_request_id:
            return
        self._is_exporting = False
        self.statusBar().showMessage(f"XEX export failed: {error_message}")
        self._show_error_banner(f"XEX export failed: {error_message}")
        self._reevaluate_and_refresh_ui()
        self.xex_export_failed.emit(error_message)

    def _show_info_banner(self, message: str) -> None:
        self._diag_banner.setText(message)
        self._diag_banner.setStyleSheet(
            "background-color: #e8f5e9; color: #1b5e20; padding: 6px; border: 1px solid #a5d6a7;"
        )
        self._diag_banner.setVisible(True)

    def render_current_preview(self) -> None:
        if self._state is None or self._evaluation is None:
            return
        if not self._evaluation.is_valid:
            return

        # Fast-path cache check avoids spawning worker if identical WAV already cached
        cached = self._render_service.get_cached(self._state, self._working_config)
        if cached is not None:
            self._active_request_id += 1
            self._on_render_finished(self._active_request_id, cached)
            return

        self._active_request_id += 1
        req_id = self._active_request_id
        self._is_rendering = True
        self._transport.set_rendering(True, "Rendering WAV preview in background...")

        worker = RenderWorker(req_id, self._render_service, self._state, self._working_config)
        self._open_workers[req_id] = worker
        worker.signals.finished.connect(self._on_render_finished)
        worker.signals.failed.connect(self._on_render_failed)
        self._thread_pool.start(worker)

    def _on_render_finished(self, request_id: int, entry: CachedRenderEntry) -> None:
        self._open_workers.pop(request_id, None)
        if request_id != self._active_request_id:
            return  # Stale render superseded by newer song load or request
        self._is_rendering = False
        self._last_rendered_entry = entry
        self._transport.set_rendered_wav(entry.wav_path)
        cache_note = " (from cache)" if entry.from_cache else ""
        self._transport.set_rendering(
            False,
            f"Rendered {entry.wav_path.name}{cache_note} — {entry.duration_seconds:.2f}s, Format v{entry.format_version}",
        )
        self._reevaluate_and_refresh_ui()

    def _on_render_failed(self, request_id: int, error_message: str) -> None:
        self._open_workers.pop(request_id, None)
        if request_id != self._active_request_id:
            return
        self._is_rendering = False
        self._transport.set_rendering(False, f"Render failed: {error_message}")
        self._show_error_banner(error_message)
        self._reevaluate_and_refresh_ui()

    def _show_error_banner(self, message: str) -> None:
        self._diag_banner.setText(f"Error: {message}")
        self._diag_banner.setStyleSheet(
            "background-color: #fdecea; color: #900018; padding: 6px; border: 1px solid #f5c6cb;"
        )
        self._diag_banner.setVisible(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._active_request_id += 1
        self._active_export_request_id += 1
        self._transport.stop_and_release()
        self._render_service.cleanup()
        super().closeEvent(event)

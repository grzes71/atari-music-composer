"""PySide6 MainWindow for Atari Music Composer Studio — Vertical Slice MVP."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Literal, Optional, Set

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from atari_music.studio.comparison import ComparisonError, ComparisonSession
from atari_music.studio.exporter import ExportService, PreparedXexArrangement
from atari_music.studio.instruments import InstrumentService
from atari_music.studio.loader import load_studio_composition
from atari_music.studio.models import (
    ArrangementEvaluation,
    CachedRenderEntry,
    ComparisonSlotStatus,
    LoadedCompositionState,
    PresetApplyResult,
    PresetRecord,
    PresetScanResult,
    StudioArrangementConfig,
    VariantSlot,
    XexExportOptions,
    XexExportResult,
)
from atari_music.studio.presets import (
    PRESET_ALREADY_EXISTS,
    PresetError,
    PresetRepository,
    apply_preset_to_state,
)
from atari_music.studio.renderer import RenderService
from atari_music.studio.ui.ab_panel import ABComparisonPanel
from atari_music.studio.ui.audio_player import AudioSinkBackend
from atari_music.studio.ui.channel_strip import ChannelStripWidget
from atari_music.studio.ui.instrument_picker import InstrumentCatalogInspector
from atari_music.studio.ui.preset_bar import PresetBarWidget, SavePresetDialog
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


@dataclass(frozen=True)
class _RenderJob:
    """Queued or running background WAV synthesis job for Editor or A/B slots."""

    request_id: int
    target: Literal["editor", "A", "B"]
    composition_generation: int
    composition_sha256: str
    state: LoadedCompositionState
    config: StudioArrangementConfig
    expected_cache_key: str


class MainWindow(QMainWindow):
    """Instrument Explorer main window (explicit Render Preview, zero auto-render)."""

    xex_export_succeeded = Signal(object)  # XexExportResult
    xex_export_failed = Signal(str)  # error_message

    def __init__(
        self,
        *,
        catalog_path: Optional[Path] = None,
        initial_file: Optional[Path] = None,
        presets_dir: Optional[Path] = None,
        audio_backend: Optional[AudioSinkBackend] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atari Music Composer Studio — Instrument Explorer")
        self.setMinimumSize(840, 580)
        self.resize(1120, 760)

        self._instrument_service = InstrumentService(catalog_path=catalog_path)
        self._render_service = RenderService(self._instrument_service)
        self._export_service = ExportService(self._instrument_service)
        self._preset_repository = PresetRepository(presets_dir=presets_dir)
        self._comparison_session = ComparisonSession(self._instrument_service, self._render_service)
        self._thread_pool = QThreadPool.globalInstance()

        self._state: Optional[LoadedCompositionState] = None
        self._working_config: StudioArrangementConfig = StudioArrangementConfig()
        self._evaluation: Optional[ArrangementEvaluation] = None
        self._last_rendered_entry: Optional[CachedRenderEntry] = None
        self._active_listen_entry: Optional[CachedRenderEntry] = None
        self._active_listen_slot: Optional[VariantSlot] = None
        self._last_exported_result: Optional[XexExportResult] = None
        self._loaded_preset: Optional[PresetRecord] = None
        self._last_preset_scan: PresetScanResult = PresetScanResult()
        self._selected_channel: int = 1
        self._composition_generation: int = 0
        self._active_request_id: int = 0
        self._active_export_request_id: int = 0
        self._is_rendering: bool = False
        self._is_exporting: bool = False
        self._closing: bool = False
        self._updating_controls: bool = False
        self._active_render_job: Optional[_RenderJob] = None
        self._pending_render_queue: Deque[_RenderJob] = deque()
        self._render_jobs_by_id: Dict[int, _RenderJob] = {}
        self._open_workers: Dict[int, RenderWorker] = {}
        self._open_export_workers: Dict[int, ExportXexWorker] = {}
        self._custom_mads_bin: Optional[Path] = None
        self._custom_player_asm: Optional[Path] = None
        self._audio_backend: Optional[AudioSinkBackend] = audio_backend

        self._build_ui()
        self.refresh_presets()
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
    def active_listen_slot(self) -> Optional[VariantSlot]:
        return self._active_listen_slot

    @property
    def active_listen_entry(self) -> Optional[CachedRenderEntry]:
        return self._active_listen_entry

    @property
    def comparison_session(self) -> ComparisonSession:
        return self._comparison_session

    @property
    def last_exported_result(self) -> Optional[XexExportResult]:
        return self._last_exported_result

    @property
    def preset_repository(self) -> PresetRepository:
        return self._preset_repository

    @property
    def loaded_preset(self) -> Optional[PresetRecord]:
        return self._loaded_preset

    @property
    def last_preset_scan(self) -> PresetScanResult:
        return self._last_preset_scan

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # A. Global Action Bar (always visible)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        self._open_btn = QPushButton("Open Composition (.json / .dsl)...")
        self._open_btn.clicked.connect(self._on_open_clicked)
        top_bar.addWidget(self._open_btn)

        self._revert_btn = QPushButton("Revert Original")
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self.revert_to_original)
        top_bar.addWidget(self._revert_btn)

        self._render_btn = QPushButton("Render Preview")
        self._render_btn.setEnabled(False)
        self._render_btn.setToolTip("Load a composition first.")
        self._render_btn.clicked.connect(self.render_current_preview)
        top_bar.addWidget(self._render_btn)

        self._export_xex_btn = QPushButton("Export XEX...")
        self._export_xex_btn.setEnabled(False)
        self._export_xex_btn.setToolTip("Load a composition first.")
        self._export_xex_btn.clicked.connect(self._on_export_xex_clicked)
        top_bar.addWidget(self._export_xex_btn)

        top_bar.addStretch(1)
        root.addLayout(top_bar)

        # B. Global Preset Bar (always visible across tabs)
        self._preset_bar = PresetBarWidget()
        self._preset_bar.selection_changed.connect(self._on_preset_selection_changed)
        self._preset_bar.load_requested.connect(self._on_load_preset_clicked)
        self._preset_bar.apply_requested.connect(self._on_apply_preset_clicked)
        self._preset_bar.save_requested.connect(self._on_save_preset_clicked)
        self._preset_bar.rename_requested.connect(self._on_rename_preset_clicked)
        self._preset_bar.delete_requested.connect(self._on_delete_preset_clicked)
        root.addWidget(self._preset_bar)

        # C. Main Workspace (Tab-based)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabBar::tab { padding: 6px 14px; } "
            "QTabBar::tab:selected { font-weight: bold; border-bottom: 2px solid #2b6cb0; }"
        )
        self._tabs.addTab(self._build_instruments_tab(), "Instruments")
        self._tabs.addTab(self._build_ab_tab(), "A/B Comparison")
        self._tabs.addTab(self._build_arrangement_tab(), "Arrangement")
        self._tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        self._tabs.setCurrentIndex(0)
        root.addWidget(self._tabs, stretch=1)

        # Alert diagnostics banner (0 px when hidden, surfaces validation/audio/export errors immediately)
        self._diag_banner = QLabel("")
        self._diag_banner.setWordWrap(True)
        self._diag_banner.setVisible(False)
        root.addWidget(self._diag_banner)

        # D. Bottom audio preview & transport (always visible across tabs)
        self._transport = TransportBar(audio_backend=self._audio_backend)
        self._transport.playback_error.connect(self._show_error_banner)
        root.addWidget(self._transport)

        self._refresh_channel_selection_highlight()

    def _wrap_scroll_tab(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_instruments_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Compact metadata & editor sync header
        meta_frame = QFrame()
        meta_frame.setFrameShape(QFrame.Shape.StyledPanel)
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setContentsMargins(8, 5, 8, 5)
        meta_layout.setSpacing(3)
        self._meta_label = QLabel("No composition loaded. Click 'Open Composition' to load a .json or .dsl file.")
        self._meta_label.setWordWrap(True)
        meta_layout.addWidget(self._meta_label)

        self._config_diff_label = QLabel("Selected config: - | Last rendered: None")
        self._config_diff_label.setWordWrap(True)
        meta_layout.addWidget(self._config_diff_label)
        layout.addWidget(meta_frame)

        # Split: Left (scrollable 4 Channels) | Right (Catalog Inspector)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        self._channel_strips: Dict[int, ChannelStripWidget] = {}
        for ch in (1, 2, 3, 4):
            strip = ChannelStripWidget(ch)
            strip.assignment_changed.connect(self.set_channel_instrument)
            strip.selected_for_inspect.connect(self.select_channel_for_inspect)
            self._channel_strips[ch] = strip
            left_layout.addWidget(strip)
        left_layout.addStretch(1)

        left_scroll = self._wrap_scroll_tab(left_container)
        left_scroll.setMinimumWidth(340)
        splitter.addWidget(left_scroll)

        self._inspector = InstrumentCatalogInspector(self._instrument_service.catalog)
        self._inspector.apply_requested.connect(self.set_channel_instrument)
        splitter.addWidget(self._inspector)
        splitter.setSizes([540, 520])
        layout.addWidget(splitter, stretch=1)
        return tab

    def _build_ab_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._ab_panel = ABComparisonPanel()
        self._ab_panel.save_slot_requested.connect(self.save_comparison_slot)
        self._ab_panel.load_slot_requested.connect(self.load_comparison_slot)
        self._ab_panel.render_slot_requested.connect(self.render_comparison_slot)
        self._ab_panel.listen_slot_requested.connect(self.listen_comparison_slot)
        self._ab_panel.switch_ab_requested.connect(self.switch_ab_listen)
        layout.addWidget(self._ab_panel)
        layout.addStretch(1)
        return self._wrap_scroll_tab(container)

    def _build_arrangement_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        policy_frame = QFrame()
        policy_frame.setFrameShape(QFrame.Shape.StyledPanel)
        form = QFormLayout(policy_frame)
        form.setContentsMargins(10, 8, 10, 8)
        form.setSpacing(8)

        self._pc_policy_combo = QComboBox()
        for pol in ("preserve", "replace", "remove"):
            self._pc_policy_combo.addItem(pol, pol)
        self._pc_policy_combo.currentIndexChanged.connect(self._on_policy_changed)
        form.addRow("PROGRAM_CHANGE policy:", self._pc_policy_combo)

        self._player_ver_combo = QComboBox()
        for pv in ("auto", "v1", "v2"):
            self._player_ver_combo.addItem(pv, pv)
        self._player_ver_combo.currentIndexChanged.connect(self._on_player_ver_changed)
        form.addRow("Player version:", self._player_ver_combo)

        self._target_combo = QComboBox()
        for tgt in ("xex_v2", "xex_v1", "wav"):
            self._target_combo.addItem(tgt, tgt)
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)
        form.addRow("Target backend:", self._target_combo)
        layout.addWidget(policy_frame)

        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(10, 8, 10, 8)
        summary_title = QLabel("Effective Arrangement State")
        summary_title.setStyleSheet("font-weight: bold;")
        summary_layout.addWidget(summary_title)
        self._arr_summary_label = QLabel("Load a composition to inspect arrangement policies and hardware mode.")
        self._arr_summary_label.setWordWrap(True)
        summary_layout.addWidget(self._arr_summary_label)
        layout.addWidget(summary_frame)
        layout.addStretch(1)
        return self._wrap_scroll_tab(container)

    def _build_diagnostics_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._diag_tab_summary = QLabel("Load a composition to view validation, compatibility, render, and export diagnostics.")
        self._diag_tab_summary.setWordWrap(True)
        layout.addWidget(self._diag_tab_summary)

        self._diag_details = QTextEdit()
        self._diag_details.setReadOnly(True)
        self._diag_details.setPlainText("No diagnostics recorded yet.")
        layout.addWidget(self._diag_details, stretch=1)
        return tab

    def _set_render_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self._render_btn.setEnabled(enabled)
        self._render_btn.setToolTip(tooltip)

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
        self._composition_generation += 1
        self._active_request_id += 1  # Invalidate any in-flight editor render
        self._active_export_request_id += 1  # Invalidate any in-flight XEX export
        self._pending_render_queue.clear()
        self._is_rendering = False
        self._is_exporting = False
        self._transport.stop_and_release()
        self._transport.set_rendered_wav(None)
        self._transport.set_rendering(False, "Composition loaded. Click 'Render Preview' to synthesize WAV.")

        self._state = state
        self._working_config = state.baseline_config
        self._last_rendered_entry = None
        self._active_listen_entry = None
        self._active_listen_slot = None
        self._last_exported_result = None
        self._comparison_session.clear()
        self._comparison_session.bind_composition(state)
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
        self._update_preset_button_states()
        if self._state is None:
            for strip in self._channel_strips.values():
                strip.clear_state()
            self._inspector.set_slot_evaluation(None)
            self._set_render_enabled(False, "Load a composition first.")
            self._export_xex_btn.setEnabled(False)
            self._export_xex_btn.setToolTip("Load a composition first.")
            self._arr_summary_label.setText("Load a composition to inspect arrangement policies and hardware mode.")
            self._refresh_ab_panel()
            self._refresh_diagnostics_tab()
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
            self._set_render_enabled(False, "Render already in progress...")
        elif not evaluation.is_valid:
            self._set_render_enabled(
                False,
                "Cannot render invalid configuration:\n" + "\n".join(evaluation.blocking_errors),
            )
        else:
            self._set_render_enabled(True, "Arrange and synthesize WAV for current selection.")

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

        v2_txt = ", ".join(evaluation.v2_reasons) if evaluation.v2_reasons else "None"
        self._arr_summary_label.setText(
            f"Summary: {working_summary}\n"
            f"Hardware Mode: {mode_str} | Format: {fmt_str} | AUDCTL: ${evaluation.effective_audctl:02X}\n"
            f"PROGRAM_CHANGE events in baseline: {pc_total} | v2 features: {v2_txt}\n"
            f"Valid arrangement: {'Yes' if evaluation.is_valid else 'No (blocking errors present)'}"
        )
        self._refresh_ab_panel()
        self._refresh_diagnostics_tab()

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

    def _sync_editor_rendering_flag(self) -> None:
        has_active_editor = self._active_render_job is not None and self._active_render_job.target == "editor"
        has_queued_editor = any(job.target == "editor" for job in self._pending_render_queue)
        self._is_rendering = has_active_editor or has_queued_editor

    def _drop_pending_jobs_for_target(self, target: Literal["editor", "A", "B"]) -> None:
        self._pending_render_queue = deque(
            job for job in self._pending_render_queue if job.target != target
        )
        self._sync_editor_rendering_flag()

    def _enqueue_render_job(
        self,
        target: Literal["editor", "A", "B"],
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> _RenderJob:
        self._drop_pending_jobs_for_target(target)
        self._active_request_id += 1
        req_id = self._active_request_id
        expected_key = self._render_service.build_cache_key(state, config).digest()
        job = _RenderJob(
            request_id=req_id,
            target=target,
            composition_generation=self._composition_generation,
            composition_sha256=state.base_ir_sha256,
            state=state,
            config=config.model_copy(deep=True),
            expected_cache_key=expected_key,
        )
        self._pending_render_queue.append(job)
        self._sync_editor_rendering_flag()
        if target == "editor":
            self._transport.set_rendering(True, "Queued WAV preview render...")
            self._reevaluate_and_refresh_ui()
        else:
            self._refresh_ab_panel(
                status_message=f"Variant {target} queued for rendering...",
                status_kind="info",
            )
        self._pump_render_queue()
        return job

    def _pump_render_queue(self) -> None:
        if self._closing or self._active_render_job is not None or not self._pending_render_queue:
            self._sync_editor_rendering_flag()
            return

        job = self._pending_render_queue.popleft()
        self._active_render_job = job
        self._sync_editor_rendering_flag()

        if job.target == "editor":
            self._transport.set_rendering(True, "Rendering WAV preview in background...")
        else:
            self._refresh_ab_panel(
                status_message=f"Rendering Variant {job.target} in background...",
                status_kind="info",
            )

        worker = RenderWorker(job.request_id, self._render_service, job.state, job.config)
        self._open_workers[job.request_id] = worker
        self._render_jobs_by_id[job.request_id] = job
        worker.signals.finished.connect(self._on_render_finished)
        worker.signals.failed.connect(self._on_render_failed)
        self._thread_pool.start(worker)

    def _apply_editor_render_result(self, entry: CachedRenderEntry) -> None:
        self._last_rendered_entry = entry
        self._active_listen_entry = None
        self._active_listen_slot = None
        self._comparison_session.clear_active_listen()
        self._comparison_session.sync_from_cache(self._state)
        self._reevaluate_and_refresh_ui()
        cache_note = " (from cache)" if entry.from_cache else ""
        summary_text = (
            f"Rendered {entry.wav_path.name}{cache_note} — "
            f"{entry.duration_seconds:.2f}s, Format v{entry.format_version}"
        )
        self._transport.set_rendering(False, summary_text)
        if self._transport.set_rendered_wav(entry.wav_path):
            self._transport.set_status_text(summary_text)

    def render_current_preview(self) -> None:
        if self._state is None or self._evaluation is None or self._is_rendering:
            return
        if not self._evaluation.is_valid:
            return

        # Fast-path cache check avoids spawning worker if identical WAV already cached
        cached = self._render_service.get_cached(self._state, self._working_config)
        if cached is not None:
            self._drop_pending_jobs_for_target("editor")
            self._active_request_id += 1
            self._apply_editor_render_result(cached)
            return

        self._enqueue_render_job("editor", self._state, self._working_config)

    def _on_render_finished(self, request_id: int, entry: CachedRenderEntry) -> None:
        job = self._render_jobs_by_id.pop(request_id, None)
        self._open_workers.pop(request_id, None)
        if self._active_render_job is job:
            self._active_render_job = None
        self._sync_editor_rendering_flag()

        if self._closing:
            return

        if (
            job is None
            or job.composition_generation != self._composition_generation
            or self._state is None
            or job.composition_sha256 != self._state.base_ir_sha256
        ):
            self._refresh_ab_panel()
            self._pump_render_queue()
            return

        if job.target == "editor":
            self._apply_editor_render_result(entry)
        else:
            accepted = self._comparison_session.record_rendered_entry(job.target, self._state, entry)
            if accepted:
                self._comparison_session.sync_from_cache(self._state)
                self._refresh_ab_panel(
                    status_message=f"Variant {job.target} rendered ({entry.duration_seconds:.2f}s).",
                    status_kind="info",
                )
            else:
                self._refresh_ab_panel(
                    status_message=f"Ignored stale render for Variant {job.target} (configuration changed).",
                    status_kind="warning",
                )

        self._pump_render_queue()

    def _on_render_failed(self, request_id: int, error_message: str) -> None:
        job = self._render_jobs_by_id.pop(request_id, None)
        self._open_workers.pop(request_id, None)
        if self._active_render_job is job:
            self._active_render_job = None
        self._sync_editor_rendering_flag()

        if self._closing:
            return

        if (
            job is None
            or job.composition_generation != self._composition_generation
            or self._state is None
            or job.composition_sha256 != self._state.base_ir_sha256
        ):
            self._refresh_ab_panel()
            self._pump_render_queue()
            return

        if job.target == "editor":
            self._reevaluate_and_refresh_ui()
            self._transport.set_rendering(False, f"Render failed: {error_message}")
            self._show_error_banner(error_message)
        else:
            self._refresh_ab_panel(
                status_message=f"Render {job.target} failed: {error_message}",
                status_kind="error",
            )
            self._show_error_banner(f"Render {job.target} failed: {error_message}")

        self._pump_render_queue()

    def _show_error_banner(self, message: str) -> None:
        self._diag_banner.setText(f"Error: {message}")
        self._diag_banner.setStyleSheet(
            "background-color: #fdecea; color: #900018; padding: 6px; border: 1px solid #f5c6cb;"
        )
        self._diag_banner.setVisible(True)
        self._refresh_diagnostics_tab()

    def _refresh_diagnostics_tab(self) -> None:
        sections = []
        ev = self._evaluation
        if self._state is None or ev is None:
            self._diag_tab_summary.setText("No composition loaded.")
            sections.append("No composition loaded.")
        else:
            err_n = len(ev.blocking_errors)
            warn_n = len(ev.warnings)
            self._diag_tab_summary.setText(
                f"Validation: {'VALID' if ev.is_valid else 'INVALID'} | "
                f"Blocking errors: {err_n} | Hardware warnings: {warn_n} | "
                f"Format: v{ev.effective_format_version or 'invalid'}"
            )
            sections.append("=== Validation & Hardware Warnings ===")
            if ev.blocking_errors:
                for msg in ev.blocking_errors:
                    sections.append(f"[ERROR] {msg}")
            else:
                sections.append("Blocking errors: None")
            if ev.warnings:
                for msg in ev.warnings:
                    sections.append(f"[WARNING] {msg}")
            else:
                sections.append("Hardware warnings: None")
            if ev.v2_reasons:
                sections.append(f"v2 Features Required: {', '.join(ev.v2_reasons)}")
            if ev.diagnostics:
                for d in ev.diagnostics:
                    sections.append(f"[{d.severity.upper()}] {d.message}")

            sections.append("")
            sections.append("=== Channel Compatibility (CH1-CH4) ===")
            for ch in (1, 2, 3, 4):
                slot_ev = ev.channels.get(ch)
                if slot_ev is None:
                    continue
                lock_txt = f" (LOCKED: {slot_ev.lock_reason})" if slot_ev.lock_reason else ""
                sections.append(f"CH{ch}: {slot_ev.effective_instrument_label}{lock_txt}")
                for d in slot_ev.diagnostics:
                    sections.append(f"  - [{d.severity.upper()}] {d.message}")

        sections.append("")
        sections.append("=== Render & Playback Diagnostics ===")
        if self._last_rendered_entry is not None:
            sections.append(
                f"Last Editor Preview: {self._last_rendered_entry.wav_path.name} "
                f"({self._last_rendered_entry.duration_seconds:.2f}s, Format v{self._last_rendered_entry.format_version})"
            )
            for msg in self._last_rendered_entry.diagnostics:
                sections.append(f"  - {msg}")
        else:
            sections.append("Last Editor Preview: None")
        if self._active_listen_entry is not None and self._active_listen_slot is not None:
            sections.append(
                f"Active A/B Playback: Variant {self._active_listen_slot} "
                f"({self._active_listen_entry.wav_path.name})"
            )
        audio_err = self._transport.audio_player.last_error()
        if audio_err:
            sections.append(f"[AUDIO ERROR] {audio_err}")

        if self._last_exported_result is not None:
            sections.append("")
            sections.append("=== Last XEX Export ===")
            sections.append(f"Path: {self._last_exported_result.xex_path}")
            for w in self._last_exported_result.warnings:
                sections.append(f"  - [WARNING] {w}")

        if self._last_preset_scan.errors:
            sections.append("")
            sections.append("=== Preset Scan Issues ===")
            for issue in self._last_preset_scan.errors:
                sections.append(f"[{issue.code}] {issue.path.name}: {issue.message}")

        self._diag_details.setPlainText("\n".join(sections))

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._composition_generation += 1
        self._active_request_id += 1
        self._active_export_request_id += 1
        self._pending_render_queue.clear()
        self._sync_editor_rendering_flag()
        self._transport.shutdown()
        self._render_service.cleanup()
        super().closeEvent(event)

    # -----------------------------------------------------------------
    # A/B Comparison Integration (Phase 3 Stage 4.3)
    # -----------------------------------------------------------------

    def _refresh_ab_panel(
        self,
        *,
        status_message: Optional[str] = None,
        status_kind: str = "neutral",
    ) -> None:
        if self._state is None:
            self._ab_panel.set_panel_state(
                has_composition=False,
                status_a=None,
                status_b=None,
                rendering_slot=None,
                queued_slots=frozenset(),
                status_message=status_message,
                status_kind=status_kind,
            )
            return

        status_a = self._comparison_session.slot_status(
            "A",
            state=self._state,
            working_config=self._working_config,
            evaluate_arrangement=True,
        )
        status_b = self._comparison_session.slot_status(
            "B",
            state=self._state,
            working_config=self._working_config,
            evaluate_arrangement=True,
        )
        rendering_slot: Optional[VariantSlot] = (
            self._active_render_job.target
            if self._active_render_job is not None and self._active_render_job.target in ("A", "B")
            else None
        )
        queued_slots: Set[VariantSlot] = {
            job.target
            for job in self._pending_render_queue
            if job.target in ("A", "B")
        }
        self._ab_panel.set_panel_state(
            has_composition=True,
            status_a=status_a,
            status_b=status_b,
            rendering_slot=rendering_slot,
            queued_slots=queued_slots,
            status_message=status_message,
            status_kind=status_kind,
        )

    def save_comparison_slot(self, slot: str) -> Optional[ComparisonSlotStatus]:
        if self._state is None:
            self._ab_panel.set_status("Load a composition before saving A/B variants.", kind="warning")
            return None
        try:
            norm_check = str(slot).strip().upper()
            if norm_check in ("A", "B"):
                self._drop_pending_jobs_for_target(norm_check)  # type: ignore[arg-type]
            status = self._comparison_session.save_slot(slot, self._state, self._working_config)
        except ComparisonError as exc:
            self._ab_panel.set_status(str(exc), kind="error")
            return None

        self._comparison_session.sync_from_cache(self._state)
        refreshed = self._comparison_session.slot_status(
            status.slot,
            state=self._state,
            working_config=self._working_config,
            evaluate_arrangement=True,
        )
        if refreshed.can_listen:
            msg = f"Saved current arrangement to Variant {refreshed.slot} (Ready from shared cache)."
            kind = "info"
        elif refreshed.is_valid_arrangement is False:
            msg = f"Saved current arrangement to Variant {refreshed.slot} with validation errors (cannot render)."
            kind = "warning"
        else:
            msg = f"Saved current arrangement to Variant {refreshed.slot} ({refreshed.render_status}; not rendered)."
            kind = "neutral"
        self._refresh_ab_panel(status_message=msg, status_kind=kind)
        return refreshed

    def load_comparison_slot(self, slot: str) -> Optional[StudioArrangementConfig]:
        if self._state is None:
            self._ab_panel.set_status("Load a composition first.", kind="warning")
            return None
        try:
            cfg_copy, label = self._comparison_session.load_slot_config(slot)
        except ComparisonError as exc:
            self._ab_panel.set_status(str(exc), kind="warning")
            return None

        self._working_config = cfg_copy
        self._sync_policy_combos_from_config()
        # Does NOT trigger rendering and does NOT disturb active playback or slots!
        self._reevaluate_and_refresh_ui()
        self._refresh_ab_panel(
            status_message=f"Loaded Variant {slot.upper()} ('{label}') into editor (no render started).",
            status_kind="info",
        )
        return cfg_copy

    def render_comparison_slot(self, slot: str) -> None:
        if self._state is None:
            self._ab_panel.set_status("Load a composition first.", kind="warning")
            return
        try:
            status = self._comparison_session.slot_status(
                slot,
                state=self._state,
                working_config=self._working_config,
                evaluate_arrangement=True,
            )
        except ComparisonError as exc:
            self._ab_panel.set_status(str(exc), kind="error")
            return

        if status.variant is None:
            self._ab_panel.set_status(f"Variant {status.slot} is empty; save an arrangement first.", kind="warning")
            return
        if not status.is_valid_arrangement:
            reason = status.blocking_errors[0] if status.blocking_errors else "Invalid configuration."
            self._ab_panel.set_status(f"Cannot render Variant {status.slot}: {reason}", kind="error")
            return

        cached = self._render_service.get_cached(self._state, status.variant.config)
        if cached is not None:
            self._drop_pending_jobs_for_target(status.slot)
            self._comparison_session.record_rendered_entry(status.slot, self._state, cached)
            self._comparison_session.sync_from_cache(self._state)
            self._refresh_ab_panel(
                status_message=f"Variant {status.slot} ready from shared cache ({cached.duration_seconds:.2f}s).",
                status_kind="info",
            )
            return

        self._enqueue_render_job(status.slot, self._state, status.variant.config)

    def _restore_previous_listen_selection(
        self,
        prev_slot: Optional[VariantSlot],
        prev_entry: Optional[CachedRenderEntry],
    ) -> None:
        if prev_slot is not None and self._state is not None:
            try:
                self._comparison_session.select_listen_slot(prev_slot, self._state)
                self._active_listen_slot = prev_slot
                self._active_listen_entry = prev_entry
                return
            except ComparisonError:
                pass
        self._comparison_session.clear_active_listen()
        self._active_listen_slot = None
        self._active_listen_entry = None

    def listen_comparison_slot(self, slot: str) -> bool:
        if self._state is None:
            self._ab_panel.set_status("Load a composition first.", kind="warning")
            return False

        prev_slot = self._comparison_session.active_listen_slot
        prev_entry = self._active_listen_entry
        try:
            entry = self._comparison_session.select_listen_slot(slot, self._state)
        except ComparisonError as exc:
            self._refresh_ab_panel(status_message=str(exc), status_kind="warning")
            return False

        norm = self._comparison_session.active_listen_slot
        if not self._transport.switch_wav_preserving_state(entry.wav_path, auto_play_if_stopped=True):
            self._restore_previous_listen_selection(prev_slot, prev_entry)
            self._refresh_ab_panel(
                status_message=f"Failed to switch playback to Variant {norm or slot}; previous playback preserved.",
                status_kind="error",
            )
            return False

        self._active_listen_slot = norm
        self._active_listen_entry = entry
        variant = self._comparison_session.get_variant(norm) if norm is not None else None
        label = variant.label if variant is not None else f"Variant {norm}"
        self._refresh_ab_panel(
            status_message=f"Listening to {label} ({norm}) — {entry.duration_seconds:.2f}s.",
            status_kind="info",
        )
        return True

    def switch_ab_listen(self) -> bool:
        if self._state is None:
            self._ab_panel.set_status("Load a composition first.", kind="warning")
            return False

        current = self._comparison_session.active_listen_slot
        if current == "A":
            target: VariantSlot = "B"
        elif current == "B":
            target = "A"
        else:
            st_a = self._comparison_session.slot_status("A", state=self._state, evaluate_arrangement=False)
            target = "A" if st_a.can_listen else "B"

        return self.listen_comparison_slot(target)

    # -----------------------------------------------------------------
    # Arrangement Presets (Phase 2: Load != Apply, zero auto-render)
    # -----------------------------------------------------------------

    def _update_preset_button_states(self) -> None:
        self._preset_bar.set_action_states(
            has_composition=(self._state is not None),
            loaded_preset=self._loaded_preset,
        )

    def refresh_presets(self, *, select_preset_id: Optional[str] = None) -> PresetScanResult:
        keep_id = select_preset_id if select_preset_id is not None else self._preset_bar.selected_preset_id()
        try:
            scan = self._preset_repository.list_presets()
        except PresetError as exc:
            scan = PresetScanResult()
            self._last_preset_scan = scan
            self._preset_bar.set_presets(scan)
            self._preset_bar.set_status(f"Failed to scan presets: {exc}", kind="error")
            self._update_preset_button_states()
            return scan

        self._last_preset_scan = scan
        self._preset_bar.set_presets(scan, select_preset_id=keep_id)
        self._update_preset_button_states()
        self._refresh_diagnostics_tab()
        return scan

    def _on_preset_selection_changed(self, preset_id: Optional[str]) -> None:
        if self._loaded_preset is not None and preset_id != self._loaded_preset.preset_id:
            self._loaded_preset = None
        if preset_id is None:
            if self._loaded_preset is None:
                self._preset_bar.set_status("No preset loaded.", kind="neutral")
        else:
            name = self._preset_bar.selected_preset_name() or preset_id
            if self._loaded_preset is None or self._loaded_preset.preset_id != preset_id:
                self._preset_bar.set_status(
                    f"Selected '{name}'. Click 'Load' to load it (current arrangement unchanged).",
                    kind="neutral",
                )
        self._update_preset_button_states()

    def load_preset(self, preset_id: Optional[str] = None) -> Optional[PresetRecord]:
        target_id = preset_id if preset_id is not None else self._preset_bar.selected_preset_id()
        if not target_id:
            self._preset_bar.set_status("Select a preset first.", kind="warning")
            return None

        try:
            record = self._preset_repository.load_preset(target_id)
        except PresetError as exc:
            self._preset_bar.set_status(f"Load failed: {exc}", kind="error")
            self.statusBar().showMessage(f"Preset load failed: {exc}")
            self.refresh_presets()
            return None

        self._loaded_preset = record
        self._preset_bar.select_preset_id(record.preset_id)
        summary = _format_config_summary(record.preset.arrangement)
        self._preset_bar.set_status(
            f"Loaded preset '{record.preset.name}' (not yet applied): {summary}. Click 'Apply' to apply.",
            kind="info",
        )
        self.statusBar().showMessage(
            f"Loaded preset '{record.preset.name}' — working arrangement unchanged until Apply."
        )
        self._update_preset_button_states()
        return record

    def apply_loaded_preset(self) -> Optional[PresetApplyResult]:
        if self._state is None:
            self._preset_bar.set_status("Load a composition before applying a preset.", kind="warning")
            return None
        if self._loaded_preset is None:
            self._preset_bar.set_status("Load a preset first before clicking Apply.", kind="warning")
            return None

        preset = self._loaded_preset.preset
        try:
            result = apply_preset_to_state(
                self._state,
                preset,
                instrument_service=self._instrument_service,
            )
        except PresetError as exc:
            # e.g. PRESET_UNKNOWN_INSTRUMENT: working configuration stays untouched
            self._preset_bar.set_status(f"Apply rejected: {exc}", kind="error")
            self.statusBar().showMessage(f"Preset apply rejected: {exc}")
            return None

        self._working_config = result.config
        self._sync_policy_combos_from_config()
        # Deliberately updates diagnostics & OUTDATED PREVIEW state without triggering auto-render!
        self._reevaluate_and_refresh_ui()

        if result.evaluation.is_valid:
            self._preset_bar.set_status(
                f"Applied preset '{preset.name}' to working arrangement.",
                kind="info",
            )
            self.statusBar().showMessage(f"Applied preset '{preset.name}'.")
        else:
            self._preset_bar.set_status(
                f"Applied preset '{preset.name}' with validation error(s) — see diagnostics below.",
                kind="warning",
            )
            self.statusBar().showMessage(
                f"Applied preset '{preset.name}' with validation error(s)."
            )
        return result

    def save_current_preset(
        self,
        name: str,
        description: Optional[str] = None,
        *,
        overwrite: Optional[bool] = None,
    ) -> Optional[PresetRecord]:
        if self._state is None:
            self._preset_bar.set_status("Load a composition before saving a preset.", kind="warning")
            return None

        try:
            saved = self._preset_repository.save_preset(
                name,
                self._working_config,
                description=description,
                overwrite=bool(overwrite) if overwrite is not None else False,
            )
        except PresetError as exc:
            if exc.code == PRESET_ALREADY_EXISTS and overwrite is None:
                answer = QMessageBox.question(
                    self,
                    "Overwrite Preset",
                    f"Preset '{name.strip()}' already exists ({exc.path.name if exc.path else ''}). Overwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self._preset_bar.set_status("Preset save cancelled.", kind="neutral")
                    return None
                try:
                    saved = self._preset_repository.save_preset(
                        name,
                        self._working_config,
                        description=description,
                        overwrite=True,
                    )
                except PresetError as retry_exc:
                    self._preset_bar.set_status(f"Save failed: {retry_exc}", kind="error")
                    self.statusBar().showMessage(f"Preset save failed: {retry_exc}")
                    return None
            else:
                self._preset_bar.set_status(f"Save failed: {exc}", kind="error")
                self.statusBar().showMessage(f"Preset save failed: {exc}")
                return None

        self._loaded_preset = saved
        self.refresh_presets(select_preset_id=saved.preset_id)
        self._preset_bar.set_status(f"Saved preset '{saved.preset.name}'.", kind="info")
        self.statusBar().showMessage(f"Saved preset '{saved.preset.name}' -> {saved.path.name}")
        return saved

    def rename_preset(
        self,
        preset_id: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> Optional[PresetRecord]:
        target_id = preset_id if preset_id is not None else self._preset_bar.selected_preset_id()
        if not target_id:
            self._preset_bar.set_status("Select a preset to rename.", kind="warning")
            return None
        if new_name is None:
            return None

        was_loaded = self._loaded_preset is not None and self._loaded_preset.preset_id == target_id
        try:
            renamed = self._preset_repository.rename_preset(target_id, new_name, overwrite=False)
        except PresetError as exc:
            self._preset_bar.set_status(f"Rename failed: {exc}", kind="error")
            self.statusBar().showMessage(f"Preset rename failed: {exc}")
            return None

        if was_loaded:
            self._loaded_preset = renamed
        self.refresh_presets(select_preset_id=renamed.preset_id)
        self._preset_bar.set_status(f"Renamed preset to '{renamed.preset.name}'.", kind="info")
        self.statusBar().showMessage(f"Renamed preset to '{renamed.preset.name}'.")
        return renamed

    def delete_preset(
        self,
        preset_id: Optional[str] = None,
        *,
        confirm: Optional[bool] = None,
    ) -> Optional[Path]:
        target_id = preset_id if preset_id is not None else self._preset_bar.selected_preset_id()
        if not target_id:
            self._preset_bar.set_status("Select a preset to delete.", kind="warning")
            return None

        display_name = target_id
        for rec in self._last_preset_scan.presets:
            if rec.preset_id == target_id:
                display_name = rec.preset.name
                break

        if confirm is None:
            answer = QMessageBox.question(
                self,
                "Delete Preset",
                f"Delete preset '{display_name}' from storage?\n(Your current composition arrangement will remain intact.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._preset_bar.set_status("Preset deletion cancelled.", kind="neutral")
                return None
        elif not confirm:
            self._preset_bar.set_status("Preset deletion cancelled.", kind="neutral")
            return None

        try:
            removed = self._preset_repository.delete_preset(target_id)
        except PresetError as exc:
            self._preset_bar.set_status(f"Delete failed: {exc}", kind="error")
            self.statusBar().showMessage(f"Preset delete failed: {exc}")
            return None

        if self._loaded_preset is not None and self._loaded_preset.preset_id == target_id:
            self._loaded_preset = None
        self.refresh_presets(select_preset_id=None)
        self._preset_bar.set_status(f"Deleted preset '{display_name}'.", kind="info")
        self.statusBar().showMessage(f"Deleted preset '{display_name}'.")
        return removed

    def _on_load_preset_clicked(self) -> None:
        self.load_preset()

    def _on_apply_preset_clicked(self) -> None:
        self.apply_loaded_preset()

    def _on_save_preset_clicked(self) -> None:
        if self._state is None:
            return
        initial_name = ""
        initial_desc = ""
        selected_id = self._preset_bar.selected_preset_id()
        for rec in self._last_preset_scan.presets:
            if rec.preset_id == selected_id:
                initial_name = rec.preset.name
                initial_desc = rec.preset.description or ""
                break
        dlg = SavePresetDialog(
            initial_name=initial_name,
            initial_description=initial_desc,
            parent=self,
        )
        if dlg.exec() == int(QDialog.DialogCode.Accepted):
            self.save_current_preset(dlg.preset_name(), dlg.preset_description())

    def _on_rename_preset_clicked(self) -> None:
        target_id = self._preset_bar.selected_preset_id()
        if not target_id:
            return
        current_name = self._preset_bar.selected_preset_name() or target_id
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Preset",
            "New preset name:",
            text=current_name,
        )
        if ok and new_name.strip():
            self.rename_preset(target_id, new_name)

    def _on_delete_preset_clicked(self) -> None:
        self.delete_preset()

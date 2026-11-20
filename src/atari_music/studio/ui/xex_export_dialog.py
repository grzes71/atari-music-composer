"""Modal dialog for configuring and validating Atari XEX export in Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from atari_music.studio.exporter import (
    ExportService,
    PreparedXexArrangement,
    companion_arrangement_json_path,
)
from atari_music.studio.models import LoadedCompositionState, ToolchainPaths, XexExportOptions


class XexExportDialog(QDialog):
    """Collects output path, memory addresses, toolchain overrides, and confirms overwrites."""

    def __init__(
        self,
        state: LoadedCompositionState,
        prepared: PreparedXexArrangement,
        sync_note: str,
        *,
        initial_mads: Optional[Path] = None,
        initial_player_asm: Optional[Path] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Atari XEX")
        self.setMinimumWidth(580)

        self._state = state
        self._prepared = prepared
        self._sync_note = sync_note
        self._initial_toolchain: ToolchainPaths = ExportService.preflight_toolchain(
            mads_bin=initial_mads,
            player_asm=initial_player_asm,
        )
        self._built_options: Optional[XexExportOptions] = None

        self._build_ui()
        self._refresh_validation_state()

    def _default_output_path(self) -> Path:
        if self._state.source_path is not None:
            return self._state.source_path.with_suffix(".xex")
        return Path.cwd() / "output.xex"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Arrangement & format summary
        fmt = (
            f"v{self._prepared.effective_format_version}"
            if self._prepared.effective_format_version is not None
            else "invalid"
        )
        mode_str = "16-bit CH1+CH2" if self._prepared.effective_uses_16bit_bass else "8-bit"
        self._summary_label = QLabel(
            f"<b>Composition:</b> {self._state.title}<br/>"
            f"<b>Resolved Export Format:</b> {fmt} ({mode_str}, AUDCTL=${self._prepared.effective_audctl:02X})<br/>"
            f"<b>WAV Preview Sync:</b> {self._sync_note}"
        )
        self._summary_label.setWordWrap(True)
        root.addWidget(self._summary_label)

        self._warn_label = QLabel("")
        self._warn_label.setWordWrap(True)
        self._warn_label.setStyleSheet(
            "background-color: #fff8e1; color: #7a4b00; padding: 6px; border: 1px solid #ffe082;"
        )
        if self._prepared.warnings:
            self._warn_label.setText("Warnings: " + " | ".join(self._prepared.warnings))
            self._warn_label.setVisible(True)
        else:
            self._warn_label.setVisible(False)
        root.addWidget(self._warn_label)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            "background-color: #fdecea; color: #900018; padding: 6px; border: 1px solid #f5c6cb;"
        )
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        # Output file selector
        out_group = QGroupBox("Output Target")
        out_form = QFormLayout(out_group)
        out_row = QHBoxLayout()
        self._output_edit = QLineEdit(str(self._default_output_path()))
        self._output_edit.textChanged.connect(self._refresh_validation_state)
        out_row.addWidget(self._output_edit, stretch=1)
        self._browse_out_btn = QPushButton("Browse...")
        self._browse_out_btn.clicked.connect(self._on_browse_output)
        out_row.addWidget(self._browse_out_btn)
        out_form.addRow("Output .xex:", out_row)

        self._keep_asm_check = QCheckBox("Keep companion .asm file beside .xex (recommended)")
        self._keep_asm_check.setChecked(True)
        out_form.addRow("", self._keep_asm_check)

        self._keep_json_check = QCheckBox(
            "Keep companion .arrangement.json file with arrangement details (recommended)"
        )
        self._keep_json_check.setChecked(True)
        out_form.addRow("", self._keep_json_check)
        root.addWidget(out_group)

        # Memory & toolchain settings
        adv_group = QGroupBox("Memory Layout && MADS Toolchain")
        adv_form = QFormLayout(adv_group)

        self._player_addr_edit = QLineEdit("$6000")
        self._player_addr_edit.textChanged.connect(self._refresh_validation_state)
        adv_form.addRow("Player address:", self._player_addr_edit)

        self._music_addr_edit = QLineEdit("$8000")
        self._music_addr_edit.setPlaceholderText("Leave empty for contiguous segment after player")
        self._music_addr_edit.textChanged.connect(self._refresh_validation_state)
        adv_form.addRow("Music address:", self._music_addr_edit)

        self._zp_base_edit = QLineEdit("$80")
        self._zp_base_edit.textChanged.connect(self._refresh_validation_state)
        adv_form.addRow("ZP base ($80-$F2):", self._zp_base_edit)

        mads_row = QHBoxLayout()
        mads_text = str(self._initial_toolchain.mads_bin) if self._initial_toolchain.mads_bin else ""
        self._mads_edit = QLineEdit(mads_text)
        self._mads_edit.setPlaceholderText("Auto-detect tools/mads/mads.exe or PATH")
        self._mads_edit.textChanged.connect(self._refresh_validation_state)
        mads_row.addWidget(self._mads_edit, stretch=1)
        self._browse_mads_btn = QPushButton("Browse...")
        self._browse_mads_btn.clicked.connect(self._on_browse_mads)
        mads_row.addWidget(self._browse_mads_btn)
        adv_form.addRow("MADS binary:", mads_row)

        asm_row = QHBoxLayout()
        asm_text = str(self._initial_toolchain.player_asm) if self._initial_toolchain.player_asm else ""
        self._player_asm_edit = QLineEdit(asm_text)
        self._player_asm_edit.setPlaceholderText("Auto-detect player.asm")
        self._player_asm_edit.textChanged.connect(self._refresh_validation_state)
        asm_row.addWidget(self._player_asm_edit, stretch=1)
        self._browse_asm_btn = QPushButton("Browse...")
        self._browse_asm_btn.clicked.connect(self._on_browse_player_asm)
        asm_row.addWidget(self._browse_asm_btn)
        adv_form.addRow("player.asm:", asm_row)

        self._toolchain_status_label = QLabel("")
        self._toolchain_status_label.setWordWrap(True)
        adv_form.addRow("Toolchain status:", self._toolchain_status_label)

        root.addWidget(adv_group)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._export_btn = QPushButton("Export XEX")
        self._export_btn.setDefault(True)
        self._export_btn.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self._export_btn)
        root.addLayout(btn_row)

    def _on_browse_output(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Save Atari XEX Executable",
            self._output_edit.text().strip() or str(self._default_output_path()),
            "Atari XEX (*.xex);;All Files (*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if chosen:
            p = Path(chosen)
            if p.suffix.lower() != ".xex":
                p = p.with_suffix(".xex")
            self._output_edit.setText(str(p))

    def _on_browse_mads(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select MADS Assembler Executable",
            self._mads_edit.text().strip() or str(Path.cwd()),
            "Executables (*.exe *);;All Files (*)",
        )
        if chosen:
            self._mads_edit.setText(chosen)

    def _on_browse_player_asm(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select player.asm",
            self._player_asm_edit.text().strip() or str(Path.cwd()),
            "MADS Assembly (*.asm);;All Files (*)",
        )
        if chosen:
            self._player_asm_edit.setText(chosen)

    def _current_mads_override(self) -> Optional[Path]:
        txt = self._mads_edit.text().strip()
        return Path(txt) if txt else None

    def _current_player_asm_override(self) -> Optional[Path]:
        txt = self._player_asm_edit.text().strip()
        return Path(txt) if txt else None

    def selected_mads_bin(self) -> Optional[Path]:
        return self._current_mads_override()

    def selected_player_asm(self) -> Optional[Path]:
        return self._current_player_asm_override()

    def _evaluate_inputs(self) -> tuple[Optional[XexExportOptions], ToolchainPaths, list[str]]:
        errors: list[str] = []
        if not self._prepared.is_exportable:
            errors.extend(self._prepared.blocking_errors or ("Arrangement is not valid for XEX export.",))

        toolchain = ExportService.preflight_toolchain(
            mads_bin=self._current_mads_override(),
            player_asm=self._current_player_asm_override(),
        )
        if toolchain.mads_error:
            errors.append(toolchain.mads_error)
        if toolchain.player_asm_error:
            errors.append(toolchain.player_asm_error)

        options: Optional[XexExportOptions] = None
        out_txt = self._output_edit.text().strip()
        if not out_txt:
            errors.append("Output .xex file path is required.")
        else:
            try:
                options = XexExportOptions(
                    output_path=Path(out_txt),
                    player_address=self._player_addr_edit.text().strip(),
                    music_address=self._music_addr_edit.text().strip() or None,
                    zp_base=self._zp_base_edit.text().strip(),
                    keep_asm=self._keep_asm_check.isChecked(),
                    keep_arrangement_json=self._keep_json_check.isChecked(),
                    mads_bin=toolchain.mads_bin,
                    player_asm=toolchain.player_asm,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        return options, toolchain, errors

    def _refresh_validation_state(self) -> None:
        options, toolchain, errors = self._evaluate_inputs()
        if toolchain.is_ready:
            self._toolchain_status_label.setText(
                f"Ready — MADS: {toolchain.mads_bin} | player.asm: {toolchain.player_asm}"
            )
            self._toolchain_status_label.setStyleSheet("color: #1b6e1b;")
        else:
            probs = [p for p in (toolchain.mads_error, toolchain.player_asm_error) if p]
            self._toolchain_status_label.setText(" | ".join(probs))
            self._toolchain_status_label.setStyleSheet("color: #b00020;")

        if errors:
            self._error_label.setText("Cannot Export XEX:\n• " + "\n• ".join(errors))
            self._error_label.setVisible(True)
            self._export_btn.setEnabled(False)
            self._export_btn.setToolTip("\n".join(errors))
            self._built_options = None
        else:
            self._error_label.setVisible(False)
            self._export_btn.setEnabled(options is not None)
            self._export_btn.setToolTip("Compile arranged song to Atari .xex using MADS.")
            self._built_options = options

    def _confirm_overwrite_if_needed(self, options: XexExportOptions) -> bool:
        xex_exists = options.output_path.exists()
        asm_target = options.output_path.with_suffix(".asm")
        asm_will_overwrite = options.keep_asm and asm_target.exists()
        json_target = companion_arrangement_json_path(options.output_path)
        json_will_overwrite = options.keep_arrangement_json and json_target.exists()
        if not xex_exists and not asm_will_overwrite and not json_will_overwrite:
            return True

        targets = []
        if xex_exists:
            targets.append(str(options.output_path))
        if asm_will_overwrite:
            targets.append(str(asm_target))
        if json_will_overwrite:
            targets.append(str(json_target))
        msg = "The following existing file(s) will be overwritten:\n\n" + "\n".join(targets)
        if not options.keep_asm and asm_target.exists():
            msg += f"\n\nExisting companion ASM ({asm_target.name}) will NOT be modified or deleted."
        if not options.keep_arrangement_json and json_target.exists():
            msg += (
                f"\n\nExisting companion JSON ({json_target.name}) will NOT be modified or deleted."
            )
        msg += "\n\nContinue with XEX export?"

        reply = QMessageBox.question(
            self,
            "Confirm Overwrite",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_export_clicked(self) -> None:
        self._refresh_validation_state()
        if self._built_options is None:
            return
        if not self._confirm_overwrite_if_needed(self._built_options):
            return
        self.accept()

    def build_options(self) -> XexExportOptions:
        """Return validated ``XexExportOptions`` configured by the dialog."""
        if self._built_options is not None:
            return self._built_options
        options, _toolchain, errors = self._evaluate_inputs()
        if options is None or errors:
            raise ValueError("; ".join(errors) or "Invalid XEX export options.")
        return options

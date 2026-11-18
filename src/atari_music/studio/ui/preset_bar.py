"""Compact preset management bar and save dialog for Studio UI."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from atari_music.studio.models import PresetRecord, PresetScanResult


class SavePresetDialog(QDialog):
    """Modal prompt collecting a preset name and optional description."""

    def __init__(
        self,
        *,
        initial_name: str = "",
        initial_description: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Arrangement Preset")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel("Preset name:"))
        self._name_edit = QLineEdit(initial_name)
        self._name_edit.setPlaceholderText("e.g. Action 16-bit Punch")
        root.addWidget(self._name_edit)

        root.addWidget(QLabel("Description (optional):"))
        self._desc_edit = QLineEdit(initial_description)
        self._desc_edit.setPlaceholderText("Channel roles, target notes, etc.")
        root.addWidget(self._desc_edit)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_btn is not None:
            self._ok_btn.setText("Save")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._name_edit.textChanged.connect(self._refresh_ok_state)
        self._refresh_ok_state()

    def _refresh_ok_state(self) -> None:
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(bool(self._name_edit.text().strip()))

    def preset_name(self) -> str:
        return self._name_edit.text().strip()

    def preset_description(self) -> Optional[str]:
        cleaned = self._desc_edit.text().strip()
        return cleaned if cleaned else None


class PresetBarWidget(QFrame):
    """Compact preset toolbar row with repository selector, actions, and persistent notices."""

    selection_changed = Signal(object)  # Optional[str] preset_id
    load_requested = Signal()
    apply_requested = Signal()
    save_requested = Signal()
    rename_requested = Signal()
    delete_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Preset:"))

        self._combo = QComboBox()
        self._combo.setMinimumWidth(220)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        row.addWidget(self._combo, stretch=1)

        self._load_btn = QPushButton("Load")
        self._load_btn.setToolTip("Load the selected preset from repository without changing current arrangement.")
        self._load_btn.clicked.connect(self.load_requested.emit)
        row.addWidget(self._load_btn)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setToolTip("Apply the loaded preset to the current composition arrangement.")
        self._apply_btn.clicked.connect(self.apply_requested.emit)
        row.addWidget(self._apply_btn)

        self._save_btn = QPushButton("Save...")
        self._save_btn.setToolTip("Save current working channel arrangement as a reusable preset.")
        self._save_btn.clicked.connect(self.save_requested.emit)
        row.addWidget(self._save_btn)

        self._rename_btn = QPushButton("Rename...")
        self._rename_btn.setToolTip("Rename the selected preset.")
        self._rename_btn.clicked.connect(self.rename_requested.emit)
        row.addWidget(self._rename_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setToolTip("Delete the selected preset from storage.")
        self._delete_btn.clicked.connect(self.delete_requested.emit)
        row.addWidget(self._delete_btn)

        root.addLayout(row)

        self._status_label = QLabel("No preset loaded.")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #444444; font-size: 11px;")
        root.addWidget(self._status_label)

        self._warning_label = QLabel("")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "background-color: #fff8e1; color: #7a4b00; padding: 4px; "
            "border: 1px solid #ffe082; font-size: 11px;"
        )
        self._warning_label.setVisible(False)
        root.addWidget(self._warning_label)

        self.set_presets(PresetScanResult())
        self.set_action_states(has_composition=False, loaded_preset=None)

    def selected_preset_id(self) -> Optional[str]:
        idx = self._combo.currentIndex()
        if idx < 0:
            return None
        data = self._combo.itemData(idx)
        return str(data) if data else None

    def selected_preset_name(self) -> Optional[str]:
        if self.selected_preset_id() is None:
            return None
        return self._combo.currentText()

    def select_preset_id(self, preset_id: Optional[str]) -> bool:
        self._updating = True
        try:
            if preset_id is None:
                self._combo.setCurrentIndex(0)
                return True
            idx = self._combo.findData(preset_id)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
                return True
            self._combo.setCurrentIndex(0)
            return False
        finally:
            self._updating = False

    def set_presets(
        self,
        scan_result: PresetScanResult,
        *,
        select_preset_id: Optional[str] = None,
    ) -> None:
        self._updating = True
        try:
            self._combo.clear()
            self._combo.addItem("(Select preset...)", None)
            for rec in scan_result.presets:
                self._combo.addItem(rec.preset.name, rec.preset_id)
                idx = self._combo.count() - 1
                if rec.preset.description:
                    self._combo.setItemData(idx, rec.preset.description, Qt.ItemDataRole.ToolTipRole)

            if select_preset_id is not None:
                idx = self._combo.findData(select_preset_id)
                self._combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                self._combo.setCurrentIndex(0)
        finally:
            self._updating = False

        if scan_result.errors:
            preview = "; ".join(
                f"{issue.path.name} ({issue.code})" for issue in scan_result.errors[:3]
            )
            extra = (
                f" (+{len(scan_result.errors) - 3} more)"
                if len(scan_result.errors) > 3
                else ""
            )
            self._warning_label.setText(
                f"Preset storage warning: skipped {len(scan_result.errors)} invalid file(s): "
                f"{preview}{extra}."
            )
            self._warning_label.setVisible(True)
        else:
            self._warning_label.setText("")
            self._warning_label.setVisible(False)

    def set_action_states(
        self,
        *,
        has_composition: bool,
        loaded_preset: Optional[PresetRecord],
    ) -> None:
        has_selection = self.selected_preset_id() is not None
        self._load_btn.setEnabled(has_selection)
        self._rename_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._save_btn.setEnabled(has_composition)
        self._apply_btn.setEnabled(has_composition and loaded_preset is not None)

    def set_status(self, message: str, *, kind: str = "neutral") -> None:
        styles = {
            "neutral": "color: #444444; font-size: 11px;",
            "info": "color: #1b5e20; font-size: 11px; font-weight: bold;",
            "warning": "color: #8a5300; font-size: 11px; font-weight: bold;",
            "error": "color: #900018; font-size: 11px; font-weight: bold;",
        }
        self._status_label.setStyleSheet(styles.get(kind, styles["neutral"]))
        self._status_label.setText(message)

    def _on_combo_changed(self, idx: int) -> None:
        if self._updating or idx < 0:
            return
        self.selection_changed.emit(self.selected_preset_id())

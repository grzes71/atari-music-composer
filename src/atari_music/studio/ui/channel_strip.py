"""Four-channel POKEY strip widget displaying channel state and assignment dropdown."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from atari_music.studio.models import (
    ChannelAnalysis,
    ChannelSlotEvaluation,
)


class ChannelStripWidget(QFrame):
    """Displays metadata, coupling state, and instrument selector for one channel (1..4)."""

    assignment_changed = Signal(int, object)  # (channel, Optional[str] inst_id)
    selected_for_inspect = Signal(int)  # (channel)

    def __init__(self, channel: int, parent=None) -> None:
        super().__init__(parent)
        self.channel = int(channel)
        self._updating = False
        self._selected = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        top_row = QHBoxLayout()
        self._header_label = QLabel(f"CH{self.channel}")
        self._header_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_row.addWidget(self._header_label)

        self._pc_badge = QLabel("")
        self._pc_badge.setStyleSheet("color: #0b5394; font-size: 11px;")
        top_row.addWidget(self._pc_badge)
        top_row.addStretch(1)

        self._inspect_btn = QPushButton("Inspect")
        self._inspect_btn.setToolTip(f"Select CH{self.channel} as target in Catalog Inspector")
        self._inspect_btn.clicked.connect(lambda: self.selected_for_inspect.emit(self.channel))
        top_row.addWidget(self._inspect_btn)
        root.addLayout(top_row)

        self._stats_label = QLabel("No composition loaded")
        self._stats_label.setWordWrap(True)
        root.addWidget(self._stats_label)

        self._effective_label = QLabel("Effective: -")
        self._effective_label.setWordWrap(True)
        root.addWidget(self._effective_label)

        self._combo = QComboBox()
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        root.addWidget(self._combo)

        self._lock_label = QLabel("")
        self._lock_label.setWordWrap(True)
        self._lock_label.setStyleSheet("color: #9e4700; font-style: italic;")
        self._lock_label.setVisible(False)
        root.addWidget(self._lock_label)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        if self._selected:
            self.setStyleSheet("ChannelStripWidget { border: 2px solid #2b6cb0; border-radius: 4px; }")
        else:
            self.setStyleSheet("")

    def update_state(
        self,
        analysis: ChannelAnalysis,
        slot_eval: ChannelSlotEvaluation,
        assigned_id: Optional[str],
    ) -> None:
        self._updating = True
        try:
            midi_span = (
                f"MIDI {analysis.midi_min}..{analysis.midi_max}"
                if analysis.midi_min is not None and analysis.midi_max is not None
                else "empty"
            )
            self._header_label.setText(f"CH{self.channel}  [{analysis.role}]")
            if analysis.has_program_changes:
                self._pc_badge.setText(
                    f"PROGRAM_CHANGE: {analysis.program_change_count} ({analysis.distinct_instruments_count} insts)"
                )
            else:
                self._pc_badge.setText("")

            self._stats_label.setText(
                f"Notes: {analysis.note_count} | {midi_span} | Avg dur: {analysis.avg_duration:.1f} | "
                f"Orig: {analysis.initial_instrument_name}"
            )
            self._effective_label.setText(f"Active: {slot_eval.effective_instrument_label}")

            self._combo.clear()
            self._combo.addItem(f"(Keep Original: {analysis.initial_instrument_name})", None)
            selected_idx = 0

            for opt in slot_eval.options:
                if opt.compatible:
                    suffix = f" [warn]" if opt.midi_warning else ""
                    text = f"{opt.instrument_id} — {opt.display_name}{suffix}"
                else:
                    text = f"[Blocked] {opt.instrument_id} — {opt.display_name}"
                self._combo.addItem(text, opt.instrument_id)
                idx = self._combo.count() - 1

                tip_parts = [
                    f"Family: {opt.family} | Roles: {', '.join(opt.intended_roles)}",
                    f"Mode: {opt.divider_mode} | Tier: {opt.tier} | MIDI: {opt.midi_range[0]}..{opt.midi_range[1]}",
                ]
                if opt.reason:
                    tip_parts.append(f"Blocked: {opt.reason}")
                if opt.midi_warning:
                    tip_parts.append(f"Warning: {opt.midi_warning}")
                self._combo.setItemData(idx, "\n".join(tip_parts), Qt.ItemDataRole.ToolTipRole)

                if not opt.compatible:
                    self._combo.setItemData(idx, QBrush(QColor("#888888")), Qt.ItemDataRole.ForegroundRole)
                elif opt.midi_warning:
                    self._combo.setItemData(idx, QBrush(QColor("#a15c00")), Qt.ItemDataRole.ForegroundRole)

                if assigned_id is not None and opt.instrument_id == assigned_id:
                    selected_idx = idx

            self._combo.setCurrentIndex(selected_idx)
            self._combo.setEnabled(slot_eval.available_for_assignment)
            self._inspect_btn.setEnabled(slot_eval.available_for_assignment)

            if not slot_eval.available_for_assignment and slot_eval.lock_reason:
                self._lock_label.setText(slot_eval.lock_reason)
                self._lock_label.setVisible(True)
            else:
                self._lock_label.setVisible(False)
        finally:
            self._updating = False

    def clear_state(self) -> None:
        self._updating = True
        try:
            self._header_label.setText(f"CH{self.channel}")
            self._pc_badge.setText("")
            self._stats_label.setText("No composition loaded")
            self._effective_label.setText("Effective: -")
            self._combo.clear()
            self._combo.setEnabled(False)
            self._inspect_btn.setEnabled(False)
            self._lock_label.setVisible(False)
        finally:
            self._updating = False

    def _on_combo_changed(self, idx: int) -> None:
        if self._updating or idx < 0:
            return
        inst_id = self._combo.itemData(idx)
        self.assignment_changed.emit(self.channel, inst_id)

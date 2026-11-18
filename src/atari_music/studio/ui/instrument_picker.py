"""Dynamic SSOT instrument catalog browser & hardware metadata inspector."""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from atari_music.instruments.catalog import InstrumentCatalog
from atari_music.studio.models import (
    CatalogOptionStatus,
    ChannelSlotEvaluation,
)


class InstrumentCatalogInspector(QWidget):
    """Presents all SSOT catalog instruments dynamically with constraints for the active channel."""

    apply_requested = Signal(int, str)  # (channel, instrument_id)

    def __init__(self, catalog: InstrumentCatalog, parent=None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._target_channel: int = 1
        self._slot_eval: Optional[ChannelSlotEvaluation] = None
        self._options_by_id: Dict[str, CatalogOptionStatus] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        self._title_label = QLabel("Instrument Catalog (Target: CH1)")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        root.addWidget(self._title_label)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Family:"))
        self._family_filter = QComboBox()
        families = sorted({prof.family for prof in catalog.instruments})
        self._family_filter.addItem("All", None)
        for fam in families:
            self._family_filter.addItem(fam, fam)
        self._family_filter.currentIndexChanged.connect(self._refresh_list)
        filter_row.addWidget(self._family_filter)

        self._compat_only_chk = QCheckBox("Compatible only")
        self._compat_only_chk.toggled.connect(self._refresh_list)
        filter_row.addWidget(self._compat_only_chk)
        filter_row.addStretch(1)
        root.addLayout(filter_row)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_item_selected)
        self._list.itemDoubleClicked.connect(self._on_apply_clicked)
        root.addWidget(self._list, stretch=2)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(170)
        root.addWidget(self._details, stretch=2)

        btn_row = QHBoxLayout()
        self._diag_label = QLabel("Select an instrument to inspect compatibility.")
        self._diag_label.setWordWrap(True)
        btn_row.addWidget(self._diag_label, stretch=1)

        self._apply_btn = QPushButton("Apply to CH1")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self._apply_btn)
        root.addLayout(btn_row)

    def set_slot_evaluation(self, slot_eval: Optional[ChannelSlotEvaluation]) -> None:
        self._slot_eval = slot_eval
        if slot_eval is not None:
            self._target_channel = slot_eval.channel
            self._title_label.setText(f"Instrument Catalog (Target: CH{self._target_channel})")
            self._apply_btn.setText(f"Apply to CH{self._target_channel}")
            self._options_by_id = {opt.instrument_id: opt for opt in slot_eval.options}
        else:
            self._options_by_id = {}
        self._refresh_list()

    def _refresh_list(self) -> None:
        prev_id = None
        if self._list.currentItem() is not None:
            prev_id = self._list.currentItem().data(Qt.ItemDataRole.UserRole)

        self._list.clear()
        fam_filter = self._family_filter.currentData()
        compat_only = self._compat_only_chk.isChecked()

        if self._slot_eval is None:
            self._details.setPlainText("Load a composition to inspect channel compatibility.")
            self._apply_btn.setEnabled(False)
            return

        selected_row = -1
        for opt in self._slot_eval.options:
            if fam_filter is not None and opt.family != fam_filter:
                continue
            if compat_only and not opt.compatible:
                continue

            status_tag = "OK" if opt.compatible else opt.status
            label = f"{opt.instrument_id}  [{opt.family}] ({status_tag})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, opt.instrument_id)
            if not opt.compatible:
                item.setForeground(QBrush(QColor("#888888")))
            elif opt.midi_warning:
                item.setForeground(QBrush(QColor("#a15c00")))
            self._list.addItem(item)
            if prev_id == opt.instrument_id:
                selected_row = self._list.count() - 1

        if self._list.count() > 0:
            self._list.setCurrentRow(max(0, selected_row))
        else:
            self._details.setPlainText("No catalog instruments match the current filter.")
            self._diag_label.setText("")
            self._apply_btn.setEnabled(False)

    def _on_item_selected(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None:
            self._apply_btn.setEnabled(False)
            return
        inst_id = current.data(Qt.ItemDataRole.UserRole)
        opt = self._options_by_id.get(inst_id)
        if opt is None:
            return
        prof, beh = self._catalog.resolve_profile_behavior(inst_id)
        hc = prof.hardware_constraints
        env = prof.envelope

        lines = [
            f"ID:            {prof.instrument_id}",
            f"Display Name:  {prof.display_name}",
            f"Family:        {prof.family}",
            f"Roles:         {', '.join(prof.intended_roles)}",
            f"Waveform:      {prof.waveform_family} (AUDC ${prof.base_distortion:02X})",
            f"Divider Mode:  {hc.divider_mode} | Preferred Clock: {hc.preferred_clock_hz or 'default'}",
            f"AUDCTL Req/Fb: ${hc.required_audctl_bits:02X} / ${hc.forbidden_audctl_bits:02X} | Poly4 Safe: {hc.poly4_safe_tuning}",
            f"Channels:      {list(hc.channels_allowed)} | MIDI Range: {hc.midi_range[0]}..{hc.midi_range[1]}",
            f"ADSR Envelope: A={env.attack_frames} D={env.decay_frames} S={env.sustain_vol} R={env.release_frames} Peak={env.peak_vol}",
            f"Behavior:      {beh.behavior_id if beh else 'None'} (Tier: {opt.tier})",
        ]
        if beh is not None:
            macro_n = len(beh.transient_macro.steps) if beh.transient_macro else 0
            pe_desc = (
                f"start={beh.pitch_envelope.start_audf_delta}, dur={beh.pitch_envelope.duration_frames}"
                if beh.pitch_envelope
                else "None"
            )
            lines.append(
                f"Modulation:    {beh.modulation_mode} | Macro Steps: {macro_n} | Pitch Env: {pe_desc}"
            )
        if prof.provenance.notes:
            lines.append(f"Notes:         {prof.provenance.notes}")
        self._details.setPlainText("\n".join(lines))

        can_apply = bool(
            self._slot_eval is not None
            and self._slot_eval.available_for_assignment
            and opt.compatible
        )
        self._apply_btn.setEnabled(can_apply)

        if not opt.compatible and opt.reason:
            self._diag_label.setText(f"Unavailable on CH{self._target_channel}: {opt.reason}")
            self._diag_label.setStyleSheet("color: #b00020;")
        elif opt.midi_warning:
            self._diag_label.setText(f"Compatible with warning: {opt.midi_warning}")
            self._diag_label.setStyleSheet("color: #9e4700;")
        else:
            self._diag_label.setText(f"Compatible on CH{self._target_channel} ({opt.status}).")
            self._diag_label.setStyleSheet("color: #1b6e1b;")

    def _on_apply_clicked(self, *_args) -> None:
        if self._slot_eval is None or not self._slot_eval.available_for_assignment:
            return
        cur = self._list.currentItem()
        if cur is None:
            return
        inst_id = cur.data(Qt.ItemDataRole.UserRole)
        opt = self._options_by_id.get(inst_id)
        if opt is not None and opt.compatible:
            self.apply_requested.emit(self._target_channel, inst_id)

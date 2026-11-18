"""Compact presentational A/B Comparison panel for Studio UI (no session/render ownership)."""

from __future__ import annotations

from typing import AbstractSet, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from atari_music.studio.models import ComparisonSlotStatus, StudioArrangementConfig, VariantSlot


def _format_variant_summary(config: StudioArrangementConfig) -> str:
    parts = [f"CH{ch}={config.channel_instruments.get(ch) or 'orig'}" for ch in (1, 2, 3, 4)]
    return (
        f"{', '.join(parts)} | pc={config.program_change_policy}, "
        f"player={config.player_version}, target={config.target_backend}"
    )


def _render_status_badge(
    render_status: str,
    *,
    is_rendering: bool,
    is_queued: bool,
) -> tuple[str, str]:
    if is_rendering:
        return "Rendering...", "color: #0b5394; font-weight: bold;"
    if is_queued:
        return "Queued", "color: #0b5394; font-weight: bold;"
    if render_status == "ready":
        return "Ready", "color: #1b6e1b; font-weight: bold;"
    if render_status == "outdated":
        return "Outdated", "color: #9e4700; font-weight: bold;"
    if render_status == "not_rendered":
        return "Not rendered", "color: #555555; font-weight: bold;"
    return "Empty", "color: #777777;"


class _ComparisonSlotCard(QFrame):
    """Single compact slot card presenting Variant A or Variant B status and controls."""

    save_clicked = Signal(str)
    load_clicked = Signal(str)
    render_clicked = Signal(str)
    listen_clicked = Signal(str)

    def __init__(self, slot: VariantSlot, parent=None) -> None:
        super().__init__(parent)
        self._slot: VariantSlot = slot
        self.setObjectName(f"abSlotCard_{slot}")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)

        self._title_label = QLabel(f"Variant {slot}")
        self._title_label.setStyleSheet("font-weight: bold;")
        header.addWidget(self._title_label)

        self._listen_badge = QLabel("LISTENING")
        self._listen_badge.setStyleSheet(
            "background-color: #e8f5e9; color: #1b5e20; border: 1px solid #81c784; "
            "padding: 1px 5px; font-size: 10px; font-weight: bold;"
        )
        self._listen_badge.setVisible(False)
        header.addWidget(self._listen_badge)

        header.addStretch(1)

        self._match_label = QLabel("")
        self._match_label.setStyleSheet("color: #555555; font-size: 11px;")
        header.addWidget(self._match_label)

        self._render_status_label = QLabel("Empty")
        self._render_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._render_status_label)
        root.addLayout(header)

        self._config_label = QLabel("No arrangement saved.")
        self._config_label.setWordWrap(True)
        self._config_label.setStyleSheet("color: #333333; font-size: 11px;")
        root.addWidget(self._config_label)

        self._detail_label = QLabel("Click 'Save to " + slot + "' to snapshot current editor setup.")
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet("color: #555555; font-size: 11px;")
        root.addWidget(self._detail_label)

        actions = QHBoxLayout()
        actions.setSpacing(4)

        self._save_btn = QPushButton(f"Save to {slot}")
        self._save_btn.clicked.connect(lambda: self.save_clicked.emit(self._slot))
        actions.addWidget(self._save_btn)

        self._load_btn = QPushButton(f"Load {slot}")
        self._load_btn.clicked.connect(lambda: self.load_clicked.emit(self._slot))
        actions.addWidget(self._load_btn)

        self._render_btn = QPushButton(f"Render {slot}")
        self._render_btn.clicked.connect(lambda: self.render_clicked.emit(self._slot))
        actions.addWidget(self._render_btn)

        self._listen_btn = QPushButton(f"Listen {slot}")
        self._listen_btn.setCheckable(True)
        self._listen_btn.clicked.connect(lambda: self.listen_clicked.emit(self._slot))
        actions.addWidget(self._listen_btn)

        root.addLayout(actions)

    def apply_status(
        self,
        status: Optional[ComparisonSlotStatus],
        *,
        has_composition: bool,
        is_rendering: bool = False,
        is_queued: bool = False,
    ) -> None:
        slot = self._slot
        if not has_composition or status is None or status.variant is None or status.render_status == "empty":
            self._title_label.setText(f"Variant {slot}")
            self._listen_badge.setVisible(False)
            self._match_label.setText("")
            badge_text, badge_style = _render_status_badge("empty", is_rendering=False, is_queued=False)
            self._render_status_label.setText(badge_text)
            self._render_status_label.setStyleSheet(badge_style)
            self._config_label.setText("No arrangement saved.")
            self._detail_label.setText(
                f"Save current editor arrangement to Variant {slot}." if has_composition else "Load a composition first."
            )
            self._detail_label.setStyleSheet("color: #555555; font-size: 11px;")

            self._save_btn.setEnabled(has_composition)
            self._save_btn.setToolTip(
                f"Snapshot current editor arrangement into Variant {slot} (does not render)."
                if has_composition
                else "Load a composition first."
            )
            self._load_btn.setEnabled(False)
            self._load_btn.setToolTip(f"Variant {slot} is empty.")
            self._render_btn.setEnabled(False)
            self._render_btn.setToolTip(f"Save an arrangement to Variant {slot} before rendering.")
            self._listen_btn.setChecked(False)
            self._listen_btn.setEnabled(False)
            self._listen_btn.setToolTip(f"Variant {slot} has no rendered audio yet.")
            self.setStyleSheet("")
            return

        variant = status.variant
        self._title_label.setText(variant.label or f"Variant {slot}")
        self._listen_badge.setVisible(status.active_listen)
        self._match_label.setText("Matches editor" if status.matches_editor else "Differs from editor")

        badge_text, badge_style = _render_status_badge(
            status.render_status,
            is_rendering=is_rendering,
            is_queued=is_queued,
        )
        self._render_status_label.setText(badge_text)
        self._render_status_label.setStyleSheet(badge_style)
        self._config_label.setText(_format_variant_summary(variant.config))

        if status.is_valid_arrangement is False:
            err_msg = status.blocking_errors[0] if status.blocking_errors else "Invalid configuration."
            self._detail_label.setText(f"Blocked: {err_msg}")
            self._detail_label.setStyleSheet("color: #b00020; font-size: 11px; font-weight: bold;")
        elif is_rendering:
            self._detail_label.setText(f"Rendering Variant {slot} in background...")
            self._detail_label.setStyleSheet("color: #0b5394; font-size: 11px;")
        elif is_queued:
            self._detail_label.setText(f"Variant {slot} queued for rendering...")
            self._detail_label.setStyleSheet("color: #0b5394; font-size: 11px;")
        elif status.render_status == "ready" and variant.rendered_entry is not None:
            entry = variant.rendered_entry
            self._detail_label.setText(
                f"WAV ready: {entry.duration_seconds:.2f}s, Format v{entry.format_version}"
            )
            self._detail_label.setStyleSheet("color: #1b6e1b; font-size: 11px;")
        elif status.render_status == "outdated" and variant.rendered_entry is not None:
            entry = variant.rendered_entry
            self._detail_label.setText(
                f"Saved config changed since prior render ({entry.duration_seconds:.2f}s); click 'Render {slot}'."
            )
            self._detail_label.setStyleSheet("color: #9e4700; font-size: 11px;")
        else:
            self._detail_label.setText(f"Not yet rendered. Click 'Render {slot}' to synthesize WAV.")
            self._detail_label.setStyleSheet("color: #555555; font-size: 11px;")

        self._save_btn.setEnabled(True)
        self._save_btn.setToolTip(
            f"Overwrite Variant {slot} with current editor arrangement (does not render)."
        )
        self._load_btn.setEnabled(True)
        self._load_btn.setToolTip(
            f"Copy Variant {slot}'s saved arrangement into the editor (does not render)."
        )

        can_render_now = status.can_render and not is_rendering and not is_queued
        self._render_btn.setEnabled(can_render_now)
        if is_rendering or is_queued:
            self._render_btn.setToolTip(f"Render already in progress/queued for Variant {slot}.")
        elif status.is_valid_arrangement is False:
            self._render_btn.setToolTip(
                "Cannot render invalid variant:\n" + "\n".join(status.blocking_errors)
            )
        else:
            self._render_btn.setToolTip(f"Render Variant {slot} via shared cache (does not stop playback).")

        self._listen_btn.setChecked(status.active_listen)
        self._listen_btn.setEnabled(status.can_listen)
        if status.can_listen:
            self._listen_btn.setToolTip(
                f"Play Variant {slot}'s rendered WAV without re-rendering."
            )
        elif status.render_status == "outdated":
            self._listen_btn.setToolTip(f"Variant {slot} is outdated — render Variant {slot} before listening.")
        else:
            self._listen_btn.setToolTip(f"Render Variant {slot} first before listening.")

        if status.active_listen:
            self.setStyleSheet(
                f"QFrame#abSlotCard_{slot} {{ border: 2px solid #2e7d32; border-radius: 3px; }}"
            )
        else:
            self.setStyleSheet("")


class ABComparisonPanel(QFrame):
    """Purely presentational A/B Comparison bar emitting explicit slot intent signals."""

    save_slot_requested = Signal(str)
    load_slot_requested = Signal(str)
    render_slot_requested = Signal(str)
    listen_slot_requested = Signal(str)
    switch_ab_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        heading = QLabel("A/B Comparison")
        heading.setStyleSheet("font-weight: bold;")
        top_row.addWidget(heading)

        self._active_summary_label = QLabel("Active listening: None")
        self._active_summary_label.setStyleSheet("color: #444444; font-size: 11px;")
        top_row.addWidget(self._active_summary_label, stretch=1)

        self._switch_btn = QPushButton("Switch A/B")
        self._switch_btn.setEnabled(False)
        self._switch_btn.clicked.connect(self.switch_ab_requested.emit)
        top_row.addWidget(self._switch_btn)
        root.addLayout(top_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        self._cards: Dict[VariantSlot, _ComparisonSlotCard] = {
            "A": _ComparisonSlotCard("A"),
            "B": _ComparisonSlotCard("B"),
        }
        for slot in ("A", "B"):
            card = self._cards[slot]
            card.save_clicked.connect(self.save_slot_requested.emit)
            card.load_clicked.connect(self.load_slot_requested.emit)
            card.render_clicked.connect(self.render_slot_requested.emit)
            card.listen_clicked.connect(self.listen_slot_requested.emit)
            cards_row.addWidget(card, stretch=1)
        root.addLayout(cards_row)

        self._status_label = QLabel("Load a composition to compare A/B arrangements.")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #444444; font-size: 11px;")
        root.addWidget(self._status_label)

        self.set_panel_state(has_composition=False, status_a=None, status_b=None)

    def slot_card(self, slot: VariantSlot) -> _ComparisonSlotCard:
        return self._cards[slot]

    def set_status(self, message: str, *, kind: str = "neutral") -> None:
        self._status_label.setText(message)
        if kind == "error":
            self._status_label.setStyleSheet("color: #b00020; font-size: 11px; font-weight: bold;")
        elif kind == "warning":
            self._status_label.setStyleSheet("color: #9e4700; font-size: 11px; font-weight: bold;")
        elif kind == "info":
            self._status_label.setStyleSheet("color: #1b6e1b; font-size: 11px; font-weight: bold;")
        else:
            self._status_label.setStyleSheet("color: #444444; font-size: 11px;")

    def set_panel_state(
        self,
        *,
        has_composition: bool,
        status_a: Optional[ComparisonSlotStatus],
        status_b: Optional[ComparisonSlotStatus],
        rendering_slot: Optional[VariantSlot] = None,
        queued_slots: AbstractSet[VariantSlot] = frozenset(),
        status_message: Optional[str] = None,
        status_kind: str = "neutral",
    ) -> None:
        statuses: Dict[VariantSlot, Optional[ComparisonSlotStatus]] = {"A": status_a, "B": status_b}
        for slot in ("A", "B"):
            self._cards[slot].apply_status(
                statuses[slot],
                has_composition=has_composition,
                is_rendering=(rendering_slot == slot),
                is_queued=(slot in queued_slots and rendering_slot != slot),
            )

        a_listen = bool(status_a is not None and status_a.active_listen and status_a.can_listen)
        b_listen = bool(status_b is not None and status_b.active_listen and status_b.can_listen)
        a_ready = bool(status_a is not None and status_a.can_listen)
        b_ready = bool(status_b is not None and status_b.can_listen)

        if not has_composition:
            self._active_summary_label.setText("Active listening: None")
            self._switch_btn.setEnabled(False)
            self._switch_btn.setToolTip("Load a composition first.")
            if status_message is None:
                self.set_status("Load a composition to compare A/B arrangements.", kind="neutral")
        else:
            if a_listen:
                label_a = status_a.variant.label if status_a and status_a.variant else "Variant A"
                self._active_summary_label.setText(f"Active listening: A ({label_a})")
                can_switch = b_ready
                tip = (
                    "Switch listening from Variant A to Variant B preserving position."
                    if can_switch
                    else "Render Variant B first to switch from A to B."
                )
            elif b_listen:
                label_b = status_b.variant.label if status_b and status_b.variant else "Variant B"
                self._active_summary_label.setText(f"Active listening: B ({label_b})")
                can_switch = a_ready
                tip = (
                    "Switch listening from Variant B to Variant A preserving position."
                    if can_switch
                    else "Render Variant A first to switch from B to A."
                )
            else:
                self._active_summary_label.setText("Active listening: Editor / None")
                can_switch = a_ready or b_ready
                tip = (
                    "Switch playback to the first ready A/B variant."
                    if can_switch
                    else "Save and render at least one A/B variant first."
                )

            self._switch_btn.setEnabled(can_switch)
            self._switch_btn.setToolTip(tip)

        if status_message is not None:
            self.set_status(status_message, kind=status_kind)

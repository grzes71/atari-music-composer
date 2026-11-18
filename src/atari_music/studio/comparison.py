"""Headless A/B arrangement comparison session management for Studio (PySide6-free)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from atari_music.studio.instruments import InstrumentService
from atari_music.studio.models import (
    CachedRenderEntry,
    ComparisonSlotStatus,
    ComparisonVariant,
    LoadedCompositionState,
    StudioArrangementConfig,
    VariantRenderStatus,
    VariantSlot,
)
from atari_music.studio.renderer import RenderService

VALID_SLOTS: Tuple[VariantSlot, VariantSlot] = ("A", "B")


class ComparisonError(ValueError):
    """Structured error raised on invalid A/B comparison operations."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


def _normalize_slot(slot: str) -> VariantSlot:
    norm = str(slot).strip().upper()
    if norm not in ("A", "B"):
        raise ComparisonError(
            f"Invalid comparison slot {slot!r}; expected 'A' or 'B'.",
            code="INVALID_SLOT",
        )
    return norm  # type: ignore[return-value]


class ComparisonSession:
    """Manages independent A/B arrangement variants over a shared ``RenderService`` cache.

    Invariants:
    - Does not mutate ``LoadedCompositionState`` or ``base_pokey_ir``.
    - Each slot holds its own deep copy of ``StudioArrangementConfig``.
    - Editing the working configuration never mutates slot A or B automatically.
    - Switching the active listening slot uses existing cache entries and never triggers rendering.
    - Rendered worker results are accepted only when both composition SHA-256 and expected
      ``RenderCacheKey`` match the target slot's current configuration.
    """

    def __init__(
        self,
        instrument_service: InstrumentService,
        render_service: RenderService,
    ) -> None:
        self._instrument_service = instrument_service
        self._render_service = render_service
        self._composition_sha256: Optional[str] = None
        self._slots: Dict[VariantSlot, Optional[ComparisonVariant]] = {"A": None, "B": None}
        self._active_listen_slot: Optional[VariantSlot] = None

    @property
    def composition_sha256(self) -> Optional[str]:
        return self._composition_sha256

    @property
    def active_listen_slot(self) -> Optional[VariantSlot]:
        return self._active_listen_slot

    def bind_composition(self, state: Optional[LoadedCompositionState]) -> None:
        """Bind session to *state*, clearing prior A/B slots whenever the composition changes."""
        new_sha = state.base_ir_sha256 if state is not None else None
        if new_sha != self._composition_sha256:
            self.clear()
            self._composition_sha256 = new_sha

    def clear(self) -> None:
        """Reset both A/B slots and active listening selection."""
        self._slots = {"A": None, "B": None}
        self._active_listen_slot = None

    def get_variant(self, slot: str) -> Optional[ComparisonVariant]:
        norm = _normalize_slot(slot)
        return self._slots[norm]

    def save_slot(
        self,
        slot: str,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
        *,
        label: Optional[str] = None,
    ) -> ComparisonSlotStatus:
        """Snapshot a deep copy of *config* into *slot* without triggering rendering."""
        self.bind_composition(state)
        norm = _normalize_slot(slot)
        cfg_copy = config.model_copy(deep=True)
        cached = self._render_service.get_cached(state, cfg_copy)

        prior = self._slots[norm]
        if cached is not None:
            rendered_entry: Optional[CachedRenderEntry] = cached
        elif prior is not None and prior.rendered_entry is not None:
            # Preserve prior entry so status explicitly reports 'outdated' until re-rendered.
            rendered_entry = prior.rendered_entry
        else:
            rendered_entry = None

        clean_label = (label or f"Variant {norm}").strip() or f"Variant {norm}"
        self._slots[norm] = ComparisonVariant(
            slot=norm,
            config=cfg_copy,
            label=clean_label,
            rendered_entry=rendered_entry,
        )
        return self.slot_status(norm, state=state, working_config=cfg_copy)

    def load_slot_config(self, slot: str) -> Tuple[StudioArrangementConfig, str]:
        """Return an independent deep copy of *slot*'s saved configuration for the editor."""
        norm = _normalize_slot(slot)
        variant = self._slots[norm]
        if variant is None:
            raise ComparisonError(
                f"Comparison slot {norm} is empty.",
                code="SLOT_EMPTY",
            )
        return variant.config.model_copy(deep=True), variant.label

    def record_rendered_entry(
        self,
        slot: str,
        state: LoadedCompositionState,
        entry: CachedRenderEntry,
    ) -> bool:
        """Attach *entry* to *slot* only if composition SHA-256 and slot cache key match."""
        if state.base_ir_sha256 != self._composition_sha256:
            return False
        norm = _normalize_slot(slot)
        variant = self._slots[norm]
        if variant is None:
            return False

        expected_digest = self._render_service.build_cache_key(state, variant.config).digest()
        if entry.cache_key != expected_digest:
            return False

        self._slots[norm] = ComparisonVariant(
            slot=norm,
            config=variant.config,
            label=variant.label,
            rendered_entry=entry,
        )
        return True

    def sync_from_cache(self, state: Optional[LoadedCompositionState]) -> None:
        """Refresh slot render links from ``RenderService`` cache without rendering."""
        if state is None or state.base_ir_sha256 != self._composition_sha256:
            return
        for norm in VALID_SLOTS:
            variant = self._slots[norm]
            if variant is None:
                continue
            cached = self._render_service.get_cached(state, variant.config)
            if cached is not None and cached != variant.rendered_entry:
                self._slots[norm] = ComparisonVariant(
                    slot=norm,
                    config=variant.config,
                    label=variant.label,
                    rendered_entry=cached,
                )

    def select_listen_slot(
        self,
        slot: str,
        state: LoadedCompositionState,
    ) -> CachedRenderEntry:
        """Select *slot* for A/B playback using existing rendered audio (never renders)."""
        if state.base_ir_sha256 != self._composition_sha256:
            raise ComparisonError(
                "Comparison session belongs to a different composition.",
                code="COMPOSITION_MISMATCH",
            )
        norm = _normalize_slot(slot)
        status = self.slot_status(norm, state=state)
        if status.render_status == "empty" or status.variant is None:
            raise ComparisonError(
                f"Cannot listen to slot {norm}: slot is empty.",
                code="SLOT_EMPTY",
            )
        if status.render_status != "ready" or status.variant.rendered_entry is None:
            raise ComparisonError(
                f"Cannot listen to slot {norm}: status is '{status.render_status}' (render slot {norm} first).",
                code="SLOT_NOT_READY",
            )
        self._active_listen_slot = norm
        return status.variant.rendered_entry

    def clear_active_listen(self) -> None:
        """Clear active A/B listen marker (e.g. when switching back to ad-hoc editor preview)."""
        self._active_listen_slot = None

    def slot_status(
        self,
        slot: str,
        *,
        state: Optional[LoadedCompositionState],
        working_config: Optional[StudioArrangementConfig] = None,
        evaluate_arrangement: bool = True,
    ) -> ComparisonSlotStatus:
        """Compute deterministic ``Empty / Not rendered / Ready / Outdated`` status for *slot*."""
        norm = _normalize_slot(slot)
        variant = self._slots[norm]
        if variant is None:
            return ComparisonSlotStatus(
                slot=norm,
                render_status="empty",
                variant=None,
                active_listen=(self._active_listen_slot == norm),
                matches_editor=False,
                is_valid_arrangement=None,
                blocking_errors=(),
            )

        matches_editor = bool(working_config is not None and variant.config == working_config)

        if state is None or state.base_ir_sha256 != self._composition_sha256:
            return ComparisonSlotStatus(
                slot=norm,
                render_status="outdated" if variant.rendered_entry is not None else "not_rendered",
                variant=variant,
                active_listen=(self._active_listen_slot == norm),
                matches_editor=matches_editor,
                is_valid_arrangement=None,
                blocking_errors=(),
            )

        expected_digest = self._render_service.build_cache_key(state, variant.config).digest()
        cached = self._render_service.get_cached(state, variant.config)
        if cached is not None:
            if cached != variant.rendered_entry:
                variant = ComparisonVariant(
                    slot=norm,
                    config=variant.config,
                    label=variant.label,
                    rendered_entry=cached,
                )
                self._slots[norm] = variant
            render_status: VariantRenderStatus = "ready"
        elif (
            variant.rendered_entry is not None
            and variant.rendered_entry.cache_key == expected_digest
            and variant.rendered_entry.wav_path.is_file()
        ):
            render_status = "ready"
        elif variant.rendered_entry is not None:
            render_status = "outdated"
        else:
            render_status = "not_rendered"

        is_valid: Optional[bool] = None
        blocking_errors: Tuple[str, ...] = ()
        if evaluate_arrangement:
            ev = self._instrument_service.evaluate_arrangement(
                state,
                variant.config,
                include_catalog_options=False,
            )
            is_valid = ev.is_valid
            blocking_errors = ev.blocking_errors

        return ComparisonSlotStatus(
            slot=norm,
            render_status=render_status,
            variant=variant,
            active_listen=(self._active_listen_slot == norm),
            matches_editor=matches_editor,
            is_valid_arrangement=is_valid,
            blocking_errors=blocking_errors,
        )

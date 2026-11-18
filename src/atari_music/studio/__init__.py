"""Headless services and optional PySide6 UI for Atari Music Composer Studio."""

from __future__ import annotations

from atari_music.studio.instruments import InstrumentService
from atari_music.studio.loader import load_studio_composition
from atari_music.studio.models import (
    ArrangementEvaluation,
    CachedRenderEntry,
    CatalogOptionStatus,
    ChannelAnalysis,
    ChannelSlotEvaluation,
    CompositionFidelityError,
    LoadedCompositionState,
    RenderCacheKey,
    StudioArrangementConfig,
)
from atari_music.studio.renderer import RenderService

__all__ = [
    "ArrangementEvaluation",
    "CachedRenderEntry",
    "CatalogOptionStatus",
    "ChannelAnalysis",
    "ChannelSlotEvaluation",
    "CompositionFidelityError",
    "InstrumentService",
    "LoadedCompositionState",
    "RenderCacheKey",
    "RenderService",
    "StudioArrangementConfig",
    "load_studio_composition",
]

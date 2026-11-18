"""Headless services and optional PySide6 UI for Atari Music Composer Studio."""

from __future__ import annotations

from atari_music.studio.exporter import (
    ExportService,
    PreparedXexArrangement,
    resolve_default_mads_path,
    resolve_default_player_asm,
)
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
    ToolchainPaths,
    XexExportOptions,
    XexExportResult,
    parse_atari_address,
)
from atari_music.studio.renderer import RenderService

__all__ = [
    "ArrangementEvaluation",
    "CachedRenderEntry",
    "CatalogOptionStatus",
    "ChannelAnalysis",
    "ChannelSlotEvaluation",
    "CompositionFidelityError",
    "ExportService",
    "InstrumentService",
    "LoadedCompositionState",
    "PreparedXexArrangement",
    "RenderCacheKey",
    "RenderService",
    "StudioArrangementConfig",
    "ToolchainPaths",
    "XexExportOptions",
    "XexExportResult",
    "load_studio_composition",
    "parse_atari_address",
    "resolve_default_mads_path",
    "resolve_default_player_asm",
]

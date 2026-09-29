"""Atari 8-bit Music Analysis, Composition & POKEY Dataset Toolkit."""

from atari_music.ai import (
    AICompositionDoc,
    build_xex_from_composition,
    export_music_dsl,
    generate_music_from_composition,
    generate_music_from_dsl,
    generate_music_from_json,
    load_composition,
    load_composition_dsl,
    load_composition_json,
    parse_music_dsl,
    request_ai_composition,
)
from atari_music.api import (
    MusicGenerationMetadata,
    MusicGenerationResult,
    generate_music,
)
from atari_music.mads_exporter import export_mads_asm
from atari_music.serialization import (
    music_ir_from_dict,
    music_ir_from_json,
    music_ir_to_dict,
    music_ir_to_json,
)

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("atari-music")
except (PackageNotFoundError, ImportError):
    __version__ = "0.6.0"

__all__ = [
    "generate_music",
    "MusicGenerationResult",
    "MusicGenerationMetadata",
    "export_mads_asm",
    # Serialization
    "music_ir_to_dict",
    "music_ir_from_dict",
    "music_ir_to_json",
    "music_ir_from_json",
    # AI Composition
    "AICompositionDoc",
    "load_composition",
    "load_composition_dsl",
    "load_composition_json",
    "parse_music_dsl",
    "export_music_dsl",
    "generate_music_from_composition",
    "generate_music_from_dsl",
    "generate_music_from_json",
    "request_ai_composition",
    "build_xex_from_composition",
    # Logging
    "setup_logging",
    "get_logger",
]

from atari_music.logging_config import get_logger, setup_logging


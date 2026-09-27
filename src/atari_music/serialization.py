"""Lossless serialization and deserialization for Symbolic Music IR (MusicSong).

Ensures lossless round-trip:
    MusicSong -> JSON -> MusicSong
    original == deserialize(serialize(original))
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

from atari_music.music_ir import MusicSong


def music_ir_to_dict(song: MusicSong) -> Dict[str, Any]:
    """Convert a MusicSong instance to a JSON-serializable dictionary."""
    if not isinstance(song, MusicSong):
        raise TypeError(f"Expected MusicSong instance, got {type(song).__name__}")
    return song.model_dump(mode="json")


def music_ir_from_dict(data: Dict[str, Any]) -> MusicSong:
    """Reconstruct a MusicSong instance from a dictionary."""
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict, got {type(data).__name__}")
    return MusicSong.model_validate(data)


def music_ir_to_json(song: MusicSong, indent: int = 2) -> str:
    """Serialize a MusicSong instance to a formatted JSON string."""
    if not isinstance(song, MusicSong):
        raise TypeError(f"Expected MusicSong instance, got {type(song).__name__}")
    return song.model_dump_json(indent=indent)


def music_ir_from_json(json_source: Union[str, Path]) -> MusicSong:
    """Deserialize a MusicSong instance from a JSON string or file path."""
    if isinstance(json_source, Path):
        content = json_source.read_text(encoding="utf-8")
    elif isinstance(json_source, str):
        # Check if it's a file path
        p = Path(json_source)
        if len(json_source) < 512 and p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8")
        else:
            content = json_source
    else:
        raise TypeError(f"Expected str or Path, got {type(json_source).__name__}")

    return MusicSong.model_validate_json(content)

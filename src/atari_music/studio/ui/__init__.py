"""Optional PySide6 desktop GUI layer for Atari Music Composer Studio."""

from __future__ import annotations

__all__ = ["MainWindow", "main"]


def __getattr__(name: str):
    if name == "MainWindow":
        from atari_music.studio.ui.main_window import MainWindow

        return MainWindow
    if name == "main":
        from atari_music.studio.ui.app import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

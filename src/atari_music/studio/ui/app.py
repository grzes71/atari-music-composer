"""Application entry point for Atari Music Composer Studio (PySide6)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Launch the Atari Music Composer Studio Qt GUI."""
    parser = argparse.ArgumentParser(
        description="Atari Music Composer Studio — Instrument Explorer"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        default=None,
        help="Optional initial composition file (.json or .dsl) to open on startup.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional SSOT instrument catalog JSON path.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(
            "PySide6 is required for Atari Music Composer Studio.\n"
            "Install optional Studio dependencies with:\n"
            '  pip install -e ".[studio]"',
            file=sys.stderr,
        )
        return 1

    from atari_music.studio.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Atari Music Composer Studio")
    window = MainWindow(catalog_path=args.catalog, initial_file=args.input_file)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())

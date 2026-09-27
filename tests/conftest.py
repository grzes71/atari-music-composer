"""Shared pytest fixtures/helpers for the test suite."""

from pathlib import Path

import pytest


def require_local_artifact(path: Path) -> None:
    """Skip a test when a locally-generated or local-only tool/asset isn't present.

    Directories like `dataset/`, `music/`, `listening_test*/`, `experiments/`,
    `stage11_xex/`, generated `stage*.md` reports, and the `tools/` third-party
    binaries (MADS, ASAP) are intentionally excluded from the public repository
    via `.gitignore`, so they won't exist in a fresh checkout (e.g. CI/release
    workflow runs).
    """
    if not path.exists():
        pytest.skip(f"local artifact not present (gitignored): {path}")

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


def fake_xex_bytes(start: int = 0x4000, length: int = 17, run: int = 0x4000) -> bytes:
    """A well-formed XEX container, for tests that stub the assembler out.

    Tests that monkeypatch ``subprocess.run`` to simulate MADS must still hand the build
    something the loader could actually read: the build validates the container it was given
    (``atari_music.xex_layout``), so a bare ``$FF $FF`` marker with a header and no payload is
    rejected as truncated — correctly, because that is what it is.

    Layout: one load segment of *length* bytes at *start*, then the DOS RUN vector. Both are
    inside the permitted user RAM region.
    """
    end = start + length - 1
    return (
        b"\xff\xff"
        + start.to_bytes(2, "little")
        + end.to_bytes(2, "little")
        + b"\x00" * length
        + (0x02E0).to_bytes(2, "little")
        + (0x02E1).to_bytes(2, "little")
        + run.to_bytes(2, "little")
    )


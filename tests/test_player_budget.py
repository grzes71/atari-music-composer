"""Unit tests for production player size budget policy and MADS measurement."""

from __future__ import annotations

from pathlib import Path

import pytest

from atari_music import player_budget, stage15
from atari_music.player_budget import (
    DEFAULT_MADS,
    DEFAULT_PLAYER_ASM,
    PLAYER_SIZE_BUDGETS,
    PLAYER_SIZE_LIMIT_BYTES,
    PLAYER_SIZE_LIMIT_SCOPE,
    PlayerSizeError,
    check_player_size,
    measure_player_size,
    player_size_limit_ok,
)

pytestmark = [pytest.mark.core, pytest.mark.audio]


def test_player_budget_limit_and_check_exclusive() -> None:
    """Verify exact < 2048 B boundary and PlayerSizeError behavior."""
    assert PLAYER_SIZE_LIMIT_BYTES == 2048
    assert PLAYER_SIZE_BUDGETS["current_envelope_2KB"] == PLAYER_SIZE_LIMIT_BYTES
    assert "player" in PLAYER_SIZE_LIMIT_SCOPE.lower()
    assert player_size_limit_ok(PLAYER_SIZE_LIMIT_BYTES - 1) is True
    assert player_size_limit_ok(PLAYER_SIZE_LIMIT_BYTES) is False
    assert check_player_size(PLAYER_SIZE_LIMIT_BYTES - 1) == PLAYER_SIZE_LIMIT_BYTES - 1

    with pytest.raises(PlayerSizeError, match="exclusive"):
        check_player_size(PLAYER_SIZE_LIMIT_BYTES)


def test_measure_player_size_missing_assembler_returns_none(tmp_path: Path) -> None:
    """Verify missing assembler cleanly degrades to None without raising."""
    assert measure_player_size(DEFAULT_PLAYER_ASM, tmp_path / "no_mads.exe") is None


def test_measure_player_size_live_mads_and_no_leftover_files() -> None:
    """Verify real MADS player measurement stays below 2048 B and leaves no temp artifacts."""
    measured = measure_player_size(DEFAULT_PLAYER_ASM, DEFAULT_MADS)
    if measured is None:
        pytest.skip("tools/mads/mads.exe not present in this checkout")
    assert check_player_size(measured) == measured
    assert sorted(p.name for p in DEFAULT_PLAYER_ASM.parent.iterdir()) == ["player.asm"]


def test_stage15_reexports_player_budget_symbols() -> None:
    """Verify backward-compatible re-exports remain identical in stage15."""
    assert stage15.PLAYER_SIZE_LIMIT_BYTES == player_budget.PLAYER_SIZE_LIMIT_BYTES
    assert stage15.PLAYER_SIZE_LIMIT_SCOPE == player_budget.PLAYER_SIZE_LIMIT_SCOPE
    assert stage15.PLAYER_SIZE_BUDGETS == player_budget.PLAYER_SIZE_BUDGETS
    assert stage15.PlayerSizeError is player_budget.PlayerSizeError
    assert stage15.player_size_limit_ok is player_budget.player_size_limit_ok
    assert stage15.check_player_size is player_budget.check_player_size
    assert stage15.measure_player_size is player_budget.measure_player_size

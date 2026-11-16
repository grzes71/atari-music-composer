"""Production 6502 player binary budget policy and MADS assembly measurement."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"
DEFAULT_MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"

#: Zero-page bytes the player consumes from the caller (``PLAYER_ZP_BASE + 0..9``).
PLAYER_ZERO_PAGE_BYTES = 10

#: The project's one hard binary limit. It bounds the **player**, not the file.
#:
#: It is **exclusive**: a player of exactly ``PLAYER_SIZE_LIMIT_BYTES`` bytes fails. A player of
#: ``PLAYER_SIZE_LIMIT_BYTES - 1`` bytes passes.
#:
#: The limit was previously applied to the complete XEX file. That was a proxy for this rule and
#: the proxy stopped being equivalent when the C1 per-channel modulation grew the player; the
#: whole-file rule was removed on 2026-10-09 (see ``HISTORY.md``) and nothing replaced it, because
#: no byte budget on the file was ever justified by the hardware.
PLAYER_SIZE_LIMIT_BYTES = 2048

#: What ``PLAYER_SIZE_LIMIT_BYTES`` does and does not bound. Written down once, here, because the
#: four quantities below are easy to conflate and only the first is a policy limit:
#:
#: * **player** — the assembled ``player.asm`` (code + runtime state), as measured by
#:   :func:`measure_player_size`. **Strictly below** the limit. This is the only quantity the
#:   limit governs.
#: * **song data** — the exported MADS data block (patterns, sequence, instrument table). Bounded
#:   by its own, far smaller POKEY-IR budget (``composer_v*.max_size``), never by this limit.
#: * **XEX file** — the complete DOS binary (harness + player + song data). **Not bounded at all.**
#: * **loaded segments** — the start address and length of each ``org`` block. Bounded by the
#:   Atari memory map, not by a byte budget.
PLAYER_SIZE_LIMIT_SCOPE = (
    "the assembled player (code + runtime state), strictly below the limit; the complete XEX "
    "file and the song data are not bounded by it"
)

#: Budget reference table. ``current_envelope_2KB`` is defined from ``PLAYER_SIZE_LIMIT_BYTES``
#: so the two cannot drift.
PLAYER_SIZE_BUDGETS = {
    "current_envelope_2KB": PLAYER_SIZE_LIMIT_BYTES,
    "hypothetical_4KB": 4096,
    "atari_minimum_free_ram_16KB": 16384,
}


class PlayerSizeError(ValueError):
    """The assembled player reached or exceeded :data:`PLAYER_SIZE_LIMIT_BYTES`."""


def player_size_limit_ok(assembled_bytes: int) -> bool:
    """The single statement of the player-size policy: **strictly** below the limit.

    Exclusive by construction, so ``2047`` is ``True`` and ``2048`` is ``False``. Every caller
    that needs to know whether a player fits asks here rather than comparing against 2048
    itself, so the boundary is stated once and cannot drift between callers.
    """
    return int(assembled_bytes) < PLAYER_SIZE_LIMIT_BYTES


def check_player_size(assembled_bytes: int) -> int:
    """Return *assembled_bytes* when it fits the player limit, else raise.

    Raises
    ------
    PlayerSizeError
        When the player is at or above the limit. The message names both numbers, because the
        boundary is exclusive and "2048 > 2048" is the kind of thing that reads like a bug.
    """
    size = int(assembled_bytes)
    if not player_size_limit_ok(size):
        raise PlayerSizeError(
            f"assembled player is {size} bytes; the player limit is "
            f"{PLAYER_SIZE_LIMIT_BYTES} bytes and is exclusive (a player of exactly "
            f"{PLAYER_SIZE_LIMIT_BYTES} bytes fails). The limit applies to the player, not to "
            f"the XEX file or the song data."
        )
    return size


def measure_player_size(asm_path: Path, mads: Path) -> Optional[int]:
    """Re-measure the assembled player size, if MADS is present.

    Everything happens in a throwaway directory: the player source is copied in and the wrapper
    includes the copy, so a "read-only" stage never writes into the source tree. Returns
    ``None`` when the assembler is missing or fails, so the analysis degrades to the recorded
    measurement instead of failing.
    """
    if not Path(mads).is_file():
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="stage15_measure_") as workspace:
            directory = Path(workspace)
            (directory / "player.asm").write_text(
                Path(asm_path).read_text(encoding="utf-8"), encoding="utf-8"
            )
            (directory / "measure.asm").write_text(
                "    org $6000\nplayer_start:\n    icl 'player.asm'\n", encoding="utf-8"
            )
            binary = directory / "measure.bin"
            result = subprocess.run(
                [str(mads), "measure.asm", "-b:$6000", "-o:measure.bin"],
                capture_output=True, text=True, check=False, cwd=str(directory),
            )
            if result.returncode != 0 or not binary.is_file():
                return None
            return binary.stat().st_size
    except OSError:
        return None

"""Atari XEX container parsing and memory-layout validation.

Why this exists
---------------
The build used to police a single number: the complete ``.xex`` file had to be under 2048
bytes. That rule was removed on 2026-10-09 (``HISTORY.md``) because it was a proxy for the
*player* size limit, and the C1 per-channel modulation made the proxy wrong. Removing it
left the pipeline with no check on where a binary actually loads, so a build could put the
song data on top of the player, or place code inside the OS ROM, and still "succeed".

This module is that check. It reads the container the assembler emitted and judges the
**address ranges**, never the file size.

Container format
----------------
Per this environment's XEX reference (``atari8bit/system/storage`` §7.4):

.. code-block:: text

    first segment:  $FF $FF  start_lo start_hi end_lo end_hi  <end-start+1 bytes>
    later segments:          start_lo start_hi end_lo end_hi  <end-start+1 bytes>

``$FF $FF`` is a marker before the *first* block, not a per-block command byte. Later
segments may repeat it, and the assembler this project uses does not. Both spellings are
accepted. The end address is **inclusive**, and a segment's payload length is implied by its
declared range — which is what makes a deterministic, self-terminating walk possible.

The last block these builds emit is ``$02E0-$02E1``: the DOS RUN vector that ``run``
produces. It is loader protocol rather than user data, and is exempt from the user-RAM
policy (see ``LOADER_VECTOR_RANGES``).

Memory policy
-------------
``USER_RAM_START`` and ``USER_RAM_END`` come from *this project's* rules, not from a generic
Atari map:

* ``.agents/AGENTS.md`` §3.1 — with OS ROM enabled (which is this project's model: the
  harness reads RTCLOK ``$14`` and the SDLSTL shadow ``$59`` and writes the COLOR2/COLOR4
  shadows ``$02C6``/``$02C8`` and ``CH`` ``$02FC``), ``$C000-$CFFF`` (OS kernel) and
  ``$D000-$DFFF`` (hardware registers, including the POKEY registers the player drives)
  must never be used as RAM, and all user code and data must end at or below ``$BFFF``.
* ``atari8bit/system/memory-map/base-map.md`` — ``$0000-$00FF`` zero page,
  ``$0100-$01FF`` hardware stack, ``$0200-$02FF`` DOS control block. The vectors and
  shadows this project's own binary depends on live there: the RUN vector ``$02E0/$02E1``
  the loader writes, the IOCBs at ``$0340-$03BF``, and the zero page the player reserves
  (``PLAYER_ZP_BASE + 0..9``, default ``$80-$89``).

So a user load segment must lie entirely inside ``$0400-$BFFF``.

``$A000-$BFFF`` is the BASIC ROM window on a stock machine but is **permitted** here: the
project relocates there deliberately (``scripts/verify_stage11_runtime.py``), and
``AGENTS.md`` states no upper bound below ``$BFFF``. A range is not rejected for looking
unusual.

Overlap is judged on the emitted ranges, because those are what the loader acts on. The
project's ``org``-must-ascend rule (``AGENTS.md`` §3.3) exists "to prevent XEX segment
overwrites during boot loading", and an overwrite *is* an overlap; a descending but disjoint
layout causes no overwrite and is therefore not rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

#: The marker that identifies an Atari binary load file. Required before the first segment.
XEX_MARKER = b"\xff\xff"

#: A segment header is ``start_lo start_hi end_lo end_hi`` (inclusive end).
SEGMENT_HEADER_BYTES = 4

#: Marker plus header, i.e. what the first segment must begin with.
MARKED_HEADER_BYTES = len(XEX_MARKER) + SEGMENT_HEADER_BYTES

#: The 6502 address space. Nothing may be loaded outside it.
ADDRESS_SPACE_END = 0xFFFF

#: The only region a user load segment may occupy. See the module docstring for the evidence.
USER_RAM_START = 0x0400
USER_RAM_END = 0xBFFF

#: DOS loader vectors. ``run`` writes RUNAD, ``ini`` writes INITAD; both are 2-byte
#: segments below user RAM and are protocol, not program data.
RUN_VECTOR = (0x02E0, 0x02E1)
INIT_VECTOR = (0x02E2, 0x02E3)
LOADER_VECTOR_RANGES: Tuple[Tuple[int, int], ...] = (RUN_VECTOR, INIT_VECTOR)

#: Start addresses that introduce a SpartaDOS X relocatable block rather than a DOS load
#: segment. This project emits plain DOS binaries, so seeing one means the file is not the
#: container we think it is and the walk would misread it.
SDX_BLOCK_STARTS = (0xFFFA, 0xFFFD, 0xFFFE)

#: Human-readable statement of the policy, published so callers can quote it verbatim.
USER_RAM_POLICY = (
    f"user code and data must load inside ${USER_RAM_START:04X}-${USER_RAM_END:04X}: "
    f"${USER_RAM_START - 1:04X} and below is zero page, the hardware stack and the DOS/OS "
    f"vectors this binary itself uses, and ${USER_RAM_END + 1:04X} and above is OS kernel "
    f"ROM, hardware registers and OS ROM"
)


class XexLayoutError(ValueError):
    """A generated XEX is malformed, or its memory layout is unsafe.

    A ``ValueError`` so callers can treat "the build produced something unusable" uniformly;
    the message always names the offending range and the reason it was rejected.
    """


@dataclass(frozen=True)
class XexSegment:
    """One load segment of a XEX container, with the range the loader will write."""

    start: int
    end: int
    payload_offset: int
    marked: bool
    role: str = ""

    @property
    def length(self) -> int:
        """Bytes the segment writes (the end address is inclusive)."""
        return self.end - self.start + 1

    @property
    def is_loader_vector(self) -> bool:
        """True for the DOS RUN/INIT vector blocks, which are protocol rather than data."""
        return (self.start, self.end) in LOADER_VECTOR_RANGES

    @property
    def is_user_ram(self) -> bool:
        """True when the whole range lies inside the permitted user region."""
        return self.start >= USER_RAM_START and self.end <= USER_RAM_END

    def describe(self) -> str:
        """``"player at $6000-$6775 (1910 bytes)"`` — the form used in error messages."""
        label = f"{self.role} at " if self.role else ""
        return f"{label}${self.start:04X}-${self.end:04X} ({self.length} bytes)"

    def overlaps(self, other: "XexSegment") -> bool:
        return self.start <= other.end and other.start <= self.end

    def overlap_range(self, other: "XexSegment") -> Optional[Tuple[int, int]]:
        """The shared range, or ``None`` when the two segments are disjoint."""
        low = max(self.start, other.start)
        high = min(self.end, other.end)
        return (low, high) if low <= high else None


def format_range(low: int, high: int) -> str:
    """``"$6000-$608E"``."""
    return f"${low:04X}-${high:04X}"


def _read_u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos:pos + 2], "little")


def assign_roles(
    segments: Sequence[XexSegment],
    *,
    player_address: Optional[int] = None,
    music_address: Optional[int] = None,
) -> List[XexSegment]:
    """Label segments with what they are, so errors can name them instead of numbering them.

    The labels are positional, because that is what the pipeline guarantees: the generated
    assembly emits the player's ``org`` first and the song data's second, and the assembler
    preserves that order. A single user segment means the two blocks were emitted
    contiguously (no separate music address was requested, or the assembler coalesced them),
    which the label says rather than pretending to split it.

    ``player_address`` and ``music_address`` are accepted for cross-checking callers that know
    the requested layout, but they do not decide the labels: a wrong request is still a wrong
    request, and the container is the authority on where the bytes actually go.
    """
    labelled: List[XexSegment] = []
    user_seen = 0
    user_total = sum(1 for seg in segments if not seg.is_loader_vector)

    for seg in segments:
        if seg.is_loader_vector:
            labelled.append(replace(seg, role="DOS RUN/INIT vector"))
            continue
        if user_total == 1:
            role = "player and song data (one segment)"
        elif user_seen == 0:
            role = "player (harness + player code)"
        elif user_seen == 1:
            role = "song data"
        else:
            role = f"extra load segment {user_seen + 1}"
        user_seen += 1
        labelled.append(replace(seg, role=role))

    return labelled


def validate_xex_layout(
    data: bytes,
    *,
    player_address: Optional[int] = None,
    music_address: Optional[int] = None,
) -> List[XexSegment]:
    """Parse a built XEX and reject any layout the loader must not perform.

    This is the whole check the pipeline needs after assembly: structure first, then where
    each segment lands. The file's *size* is deliberately not examined — the only byte limit
    in this project applies to the assembled player (``player_budget.PLAYER_SIZE_LIMIT_BYTES``).

    Returns
    -------
    List[XexSegment]
        The parsed segments, labelled by role, so a caller can report where things went.

    Raises
    ------
    XexLayoutError
        If the container is malformed, or a user segment falls outside the permitted region,
        or two segments claim the same memory.
    """
    segments = assign_roles(
        parse_xex(data), player_address=player_address, music_address=music_address,
    )

    # 1. Every user load segment must land in user RAM. Loader vectors are protocol.
    for seg in segments:
        if seg.is_loader_vector:
            continue
        if seg.start < USER_RAM_START or seg.end > USER_RAM_END:
            raise XexLayoutError(
                f"XEX layout error: the {seg.describe()} loads outside the permitted user "
                f"RAM region. {USER_RAM_POLICY}. "
                f"Choose a player/music address whose whole range fits inside "
                f"${USER_RAM_START:04X}-${USER_RAM_END:04X}."
            )

    # 2. No two segments may claim the same memory. This is what the project's
    #    org-must-ascend rule protects against, and it is the failure a same-address or
    #    partially overlapping music address produces.
    for i, first in enumerate(segments):
        for second in segments[i + 1:]:
            shared = first.overlap_range(second)
            if shared is None:
                continue
            raise XexLayoutError(
                f"XEX layout error: the {second.describe()} overlaps the "
                f"{first.describe()}; they both claim {format_range(*shared)}. The loader "
                f"writes segments in file order, so the later one silently destroys the "
                f"earlier one. Player and song data must occupy disjoint ranges."
            )

    return segments


def validate_xex_file(
    path: Union[str, Path],
    *,
    player_address: Optional[int] = None,
    music_address: Optional[int] = None,
) -> List[XexSegment]:
    """Read *path* and validate it as a built XEX. See :func:`validate_xex_layout`."""
    return validate_xex_layout(
        Path(path).read_bytes(),
        player_address=player_address,
        music_address=music_address,
    )


def parse_xex(data: bytes) -> List[XexSegment]:
    """Walk a XEX container and return its load segments in file order.

    The walk is deterministic rather than a scan: each segment declares its own extent, so
    the next header is always exactly where the previous payload ended. That means a payload
    containing ``$FF $FF`` cannot be mistaken for a header, and a file that does not divide
    evenly is a malformed file rather than an ambiguous one.

    Raises
    ------
    XexLayoutError
        For an empty file, a missing leading ``$FF $FF``, a truncated header or payload, a
        segment whose end precedes its start (a range that wraps the 16-bit address space),
        or a SpartaDOS X block header where a DOS segment was expected.
    """
    if not data:
        raise XexLayoutError("XEX layout error: the file is empty")

    if data[:2] != XEX_MARKER:
        found = data[:2].hex(" ").upper()
        raise XexLayoutError(
            f"XEX layout error: not an Atari binary load file — it must begin with the "
            f"$FF $FF marker, but begins with {found}"
        )

    segments: List[XexSegment] = []
    pos = 0
    while pos < len(data):
        marked = data[pos:pos + 2] == XEX_MARKER
        if marked:
            pos += len(XEX_MARKER)

        if pos + SEGMENT_HEADER_BYTES > len(data):
            remaining = len(data) - pos
            raise XexLayoutError(
                f"XEX layout error: truncated segment header at byte {pos} — "
                f"{remaining} byte(s) left, need {SEGMENT_HEADER_BYTES} "
                f"(start_lo start_hi end_lo end_hi)"
            )

        start = _read_u16(data, pos)
        end = _read_u16(data, pos + 2)
        header_at = pos
        pos += SEGMENT_HEADER_BYTES

        if start in SDX_BLOCK_STARTS:
            raise XexLayoutError(
                f"XEX layout error: byte {header_at} declares a SpartaDOS X block header "
                f"(${start:04X}), not a DOS load segment. This project emits plain DOS "
                f"binaries, so this file cannot be walked as one."
            )

        if end < start:
            raise XexLayoutError(
                f"XEX layout error: segment header at byte {header_at} declares "
                f"${start:04X}-${end:04X}, whose end precedes its start — the range wraps "
                f"past the 16-bit address-space boundary ${ADDRESS_SPACE_END:04X}"
            )

        length = end - start + 1
        if pos + length > len(data):
            raise XexLayoutError(
                f"XEX layout error: segment ${start:04X}-${end:04X} at byte {header_at} "
                f"declares {length} bytes of payload but only {len(data) - pos} remain — "
                f"the file is truncated"
            )

        segments.append(XexSegment(
            start=start, end=end, payload_offset=pos, marked=marked,
        ))
        pos += length

    return segments


__all__ = [
    "ADDRESS_SPACE_END",
    "INIT_VECTOR",
    "LOADER_VECTOR_RANGES",
    "MARKED_HEADER_BYTES",
    "RUN_VECTOR",
    "SDX_BLOCK_STARTS",
    "SEGMENT_HEADER_BYTES",
    "USER_RAM_END",
    "USER_RAM_POLICY",
    "USER_RAM_START",
    "XEX_MARKER",
    "XexLayoutError",
    "XexSegment",
    "assign_roles",
    "format_range",
    "parse_xex",
    "validate_xex_file",
    "validate_xex_layout",
]

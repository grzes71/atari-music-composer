"""XEX memory-layout validation (``atari_music.xex_layout``).

The build used to police the *complete file size* (under 2048 bytes). That rule was removed
on 2026-10-09 because it was a proxy for the player-size limit; what replaced it is this:
the container is parsed and the **address ranges** are judged. These tests pin both halves —
the container format the assembler actually emits, and the memory policy the project runs
under.

The policy, and where each part of it comes from:

* a user load segment must lie entirely inside ``$0400-$BFFF``;
* ``$0400`` and below is zero page, the hardware stack, the DOS control block and the OS
  vectors this project's own binary depends on (RUN vector ``$02E0/$02E1``, IOCBs
  ``$0340-$03BF``, the ``$02C6``/``$02C8``/``$02FC`` shadows the harness writes, the zero
  page the player reserves at ``PLAYER_ZP_BASE``) — ``atari8bit/system/memory-map/base-map.md``;
* ``$C000`` and above is OS kernel ROM, hardware registers and OS ROM — ``.agents/AGENTS.md``
  §3.1: "All user code, graphics, data, and tables MUST end at or below ``$BFFF``";
* ``$A000-$BFFF`` is the BASIC ROM window but is deliberately permitted here, because the
  project relocates there (``scripts/verify_stage11_runtime.py``);
* the DOS RUN/INIT vector blocks are loader protocol, not user data, and are exempt;
* two segments must never claim the same memory — the hazard ``AGENTS.md`` §3.3 describes as
  "XEX segment overwrites during boot loading".

The file-size rule is deliberately *not* re-tested as a limit anywhere: ``test_a_valid_
container_larger_than_2048_bytes_is_accepted`` and the real-build test assert the opposite.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pytest
from click.testing import CliRunner

from atari_music import player_budget, xex_layout
from atari_music.ai.client import build_xex_from_composition, load_composition_json
from atari_music.cli import cli
from atari_music.xex_layout import XexLayoutError
from conftest import require_local_artifact

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO = Path(__file__).resolve().parent.parent
MADS = REPO / "tools" / "mads" / "mads.exe"
EXAMPLES = REPO / "examples" / "ai"

Segment = Tuple[int, int, bytes]


def seg(start: int, end: int, fill: int = 0x00) -> Segment:
    """A ``(start, end, payload)`` triple of the right length for that inclusive range."""
    return (start, end, bytes([fill]) * (end - start + 1))


def container(*segments: Segment, marker: bool = False) -> bytes:
    """A XEX container: ``$FF $FF`` then ``start/end`` and payload, repeated.

    *marker* repeats the ``$FF $FF`` before every segment instead of only the first, which is
    the tolerant spelling the format reference mentions; the assembler emits the other one.
    """
    out = bytearray()
    for index, (start, end, payload) in enumerate(segments):
        if index == 0 or marker:
            out += b"\xff\xff"
        out += start.to_bytes(2, "little") + end.to_bytes(2, "little") + payload
    return bytes(out)


def ranges(segments) -> List[Tuple[int, int]]:
    return [(s.start, s.end) for s in segments]


# ---------------------------------------------------------------------------
# 1. The container format the assembler emits
# ---------------------------------------------------------------------------
class TestContainerParsing:
    def test_the_walk_finds_every_segment(self) -> None:
        blob = container(seg(0x6000, 0x600F), seg(0x8000, 0x800F))
        parsed = xex_layout.parse_xex(blob)
        assert ranges(parsed) == [(0x6000, 0x600F), (0x8000, 0x800F)]

    def test_only_the_first_segment_needs_the_marker(self) -> None:
        """This is what the assembler emits: one ``$FF $FF``, then bare headers."""
        parsed = xex_layout.parse_xex(container(seg(0x6000, 0x600F), seg(0x8000, 0x800F)))
        assert [s.marked for s in parsed] == [True, False]

    def test_a_repeated_marker_is_also_accepted(self) -> None:
        parsed = xex_layout.parse_xex(
            container(seg(0x6000, 0x600F), seg(0x8000, 0x800F), marker=True)
        )
        assert [s.marked for s in parsed] == [True, True]

    def test_a_payload_containing_the_marker_is_not_a_header(self) -> None:
        """The walk follows declared lengths, so it cannot resynchronise inside a payload."""
        payload = b"\xff\xff" + b"\x00" * 14
        blob = container((0x6000, 0x600F, payload), seg(0x8000, 0x800F))
        parsed = xex_layout.parse_xex(blob)
        assert ranges(parsed) == [(0x6000, 0x600F), (0x8000, 0x800F)]

    def test_the_end_address_is_inclusive(self) -> None:
        parsed = xex_layout.parse_xex(container(seg(0x6000, 0x6000)))
        assert parsed[0].length == 1

    def test_the_loader_vectors_are_recognised(self) -> None:
        parsed = xex_layout.parse_xex(container(seg(0x6000, 0x600F), seg(0x02E0, 0x02E1)))
        assert parsed[1].is_loader_vector is True
        assert parsed[0].is_loader_vector is False

    @pytest.mark.parametrize(
        "blob, fragment",
        [
            (b"", "empty"),
            (b"\x00\x60\x0f\x60", "must begin with"),
            (b"\xff\xff" + b"\x00\x60", "truncated segment header"),
            (b"\xff\xff" + (0x6000).to_bytes(2, "little") + (0x600F).to_bytes(2, "little") + b"\x00" * 4,
             "declares 16 bytes of payload"),
            (b"\xff\xff" + (0xFFF0).to_bytes(2, "little") + (0x000F).to_bytes(2, "little") + b"\x00" * 4,
             "wraps past the 16-bit address-space boundary"),
            (b"\xff\xff" + (0xFFFA).to_bytes(2, "little") + (0x6000).to_bytes(2, "little") + b"\x00",
             "SpartaDOS X"),
        ],
    )
    def test_malformed_containers_are_refused(self, blob: bytes, fragment: str) -> None:
        with pytest.raises(XexLayoutError) as excinfo:
            xex_layout.parse_xex(blob)
        assert fragment in str(excinfo.value)

    def test_trailing_bytes_after_a_valid_segment_are_refused(self) -> None:
        blob = container(seg(0x6000, 0x600F)) + b"\x01\x02"
        with pytest.raises(XexLayoutError) as excinfo:
            xex_layout.parse_xex(blob)
        assert "truncated segment header" in str(excinfo.value)

    def test_a_real_build_is_consumed_exactly(self, tmp_path: Path) -> None:
        """The invariant that makes the walk trustworthy, checked against real MADS output."""
        require_local_artifact(MADS)
        require_local_artifact(EXAMPLES)
        path = build_xex_from_composition(
            load_composition_json(EXAMPLES / "dungeon_dark.json"),
            output_path=tmp_path / "exact.xex", mads_bin=MADS,
        )
        data = path.read_bytes()
        parsed = xex_layout.parse_xex(data)
        # Every declared range must account for exactly the bytes on disk: no slack, no
        # guesswork. If this ever fails, the parser is guessing rather than reading.
        assert sum(s.length for s in parsed) + 6 + 4 * (len(parsed) - 1) == len(data)


# ---------------------------------------------------------------------------
# 2. The memory policy: what may be loaded where
# ---------------------------------------------------------------------------
class TestMemoryRegionPolicy:
    def test_the_permitted_region_is_the_projects_own(self) -> None:
        assert (xex_layout.USER_RAM_START, xex_layout.USER_RAM_END) == (0x0400, 0xBFFF)

    def test_the_policy_states_both_bounds_and_why(self) -> None:
        policy = xex_layout.USER_RAM_POLICY
        assert "$0400-$BFFF" in policy
        assert "$03FF" in policy  # what the lower bound keeps out
        assert "$C000" in policy  # what the upper bound keeps out

    @pytest.mark.parametrize(
        "start, end",
        [
            (0x0400, 0x04FF),   # the lowest permitted address
            (0x4000, 0x40FF),   # the project's default player address
            (0xA000, 0xA0FF),   # the BASIC ROM window: permitted on purpose
            (0xBF00, 0xBFFF),   # the highest permitted address
        ],
    )
    def test_permitted_ranges_are_accepted(self, start: int, end: int) -> None:
        parsed = xex_layout.validate_xex_layout(container(seg(start, end)))
        assert ranges(parsed) == [(start, end)]

    @pytest.mark.parametrize(
        "start, end",
        [
            (0xC000, 0xC0FF),   # OS kernel ROM
            (0xD200, 0xD20F),   # POKEY: the registers the player itself writes
            (0xE000, 0xE0FF),   # OS ROM
            (0xFF00, 0xFFFF),   # OS ROM top
            (0x0000, 0x00FF),   # zero page
            (0x0100, 0x01FF),   # hardware stack
            (0x0200, 0x02FF),   # DOS control block
            (0x0300, 0x03FF),   # OS vectors and shadows
        ],
    )
    def test_forbidden_ranges_are_refused(self, start: int, end: int) -> None:
        with pytest.raises(XexLayoutError) as excinfo:
            xex_layout.validate_xex_layout(container(seg(start, end)))
        message = str(excinfo.value)
        assert "outside the permitted user RAM region" in message
        assert f"${start:04X}-${end:04X}" in message
        assert xex_layout.USER_RAM_POLICY in message

    @pytest.mark.parametrize(
        "start, end",
        [
            (0xBF00, 0xC0FF),   # straddles the OS boundary upward
            (0x03F0, 0x0410),   # straddles the low boundary downward
        ],
    )
    def test_a_range_that_straddles_a_boundary_is_refused(self, start: int, end: int) -> None:
        with pytest.raises(XexLayoutError):
            xex_layout.validate_xex_layout(container(seg(start, end)))

    def test_the_loader_vector_is_exempt_but_a_user_range_there_is_not(self) -> None:
        """``$02E0-$02E1`` is the DOS RUN vector; anything else down there is a conflict."""
        parsed = xex_layout.validate_xex_layout(
            container(seg(0x6000, 0x600F), seg(0x02E0, 0x02E1))
        )
        assert parsed[-1].is_loader_vector is True
        assert parsed[-1].role == "DOS RUN/INIT vector"

        with pytest.raises(XexLayoutError):
            # Same neighbourhood, but not the vector's exact range: user data over the OS.
            xex_layout.validate_xex_layout(container(seg(0x02E0, 0x02E5)))

    def test_an_unusually_low_address_is_not_refused_for_looking_unusual(self) -> None:
        """``$0500`` is neither a default nor a ROM window; it is simply free RAM."""
        assert ranges(xex_layout.validate_xex_layout(container(seg(0x0500, 0x05FF)))) == [
            (0x0500, 0x05FF)
        ]


# ---------------------------------------------------------------------------
# 3. Overlap: two segments may never claim the same memory
# ---------------------------------------------------------------------------
class TestOverlap:
    def test_the_same_range_twice_is_refused(self) -> None:
        blob = container(seg(0x6000, 0x60FF), seg(0x6000, 0x60FF))
        with pytest.raises(XexLayoutError) as excinfo:
            xex_layout.validate_xex_layout(blob)
        message = str(excinfo.value)
        assert "overlaps" in message
        assert "$6000-$60FF" in message

    def test_a_partial_overlap_is_refused(self) -> None:
        blob = container(seg(0x6000, 0x60FF), seg(0x6080, 0x60FF))
        with pytest.raises(XexLayoutError) as excinfo:
            xex_layout.validate_xex_layout(blob)
        # The message names the shared range, not just the two segments.
        assert "$6080-$60FF" in str(excinfo.value)

    def test_a_third_segment_overlapping_the_second_is_refused(self) -> None:
        blob = container(
            seg(0x6000, 0x60FF), seg(0x8000, 0x80FF), seg(0x8080, 0x80FF),
        )
        with pytest.raises(XexLayoutError) as excinfo:
            xex_layout.validate_xex_layout(blob)
        assert "overlaps" in str(excinfo.value)

    def test_a_segment_swallowing_another_is_refused(self) -> None:
        blob = container(seg(0x6000, 0x6FFF), seg(0x6100, 0x61FF))
        with pytest.raises(XexLayoutError):
            xex_layout.validate_xex_layout(blob)

    def test_adjacent_ranges_do_not_overlap(self) -> None:
        """One byte apart is legal: the end address is inclusive."""
        blob = container(seg(0x6000, 0x60FF), seg(0x6100, 0x61FF))
        assert ranges(xex_layout.validate_xex_layout(blob)) == [
            (0x6000, 0x60FF), (0x6100, 0x61FF)
        ]

    def test_a_descending_but_disjoint_layout_is_not_an_overlap(self) -> None:
        """``AGENTS.md`` ties the ascend rule to overwrites; disjoint means no overwrite."""
        blob = container(seg(0x8000, 0x80FF), seg(0x6000, 0x60FF))
        assert ranges(xex_layout.validate_xex_layout(blob)) == [
            (0x8000, 0x80FF), (0x6000, 0x60FF)
        ]


# ---------------------------------------------------------------------------
# 4. The file size is not a criterion
# ---------------------------------------------------------------------------
class TestFileSizeIsNotCriterion:
    def test_a_valid_container_larger_than_2048_bytes_is_accepted(self) -> None:
        """A 4 KB segment is fine: the 2048-byte limit bounds the player, not the file."""
        blob = container(seg(0x4000, 0x4FFF), seg(0x8000, 0x8FFF))
        assert len(blob) > 2048
        parsed = xex_layout.validate_xex_layout(blob)
        assert ranges(parsed) == [(0x4000, 0x4FFF), (0x8000, 0x8FFF)]

    def test_a_64k_worth_of_segments_is_still_only_judged_by_range(self) -> None:
        """Two 16 KB halves of user RAM: accepted because both ranges are legal."""
        blob = container(seg(0x0400, 0x43FF), seg(0x4400, 0x83FF))
        assert len(blob) > 2048
        assert len(xex_layout.validate_xex_layout(blob)) == 2


# ---------------------------------------------------------------------------
# 5. The real build path: assemble, then judge what MADS produced
# ---------------------------------------------------------------------------
needs_mads = pytest.mark.skipif(
    not MADS.is_file() or not EXAMPLES.is_dir(),
    reason="MADS and/or the example compositions are not present on this machine",
)


def _build(tmp_path: Path, player: int, music, name: str = "out"):
    """Build one example through the real pipeline and return the path."""
    return build_xex_from_composition(
        load_composition_json(EXAMPLES / "dungeon_dark.json"),
        output_path=tmp_path / f"{name}.xex",
        player_address=player,
        music_address=music,
        mads_bin=MADS,
    )


@needs_mads
class TestRealBuilds:
    def test_a_valid_split_layout_is_accepted_and_reported(self, tmp_path: Path) -> None:
        path = _build(tmp_path, 0x6000, 0x8000)
        parsed = xex_layout.validate_xex_file(path, player_address=0x6000, music_address=0x8000)
        assert len(parsed) == 3
        assert parsed[0].role == "player (harness + player code)"
        assert parsed[1].role == "song data"
        assert parsed[2].is_loader_vector is True
        assert parsed[0].start == 0x6000
        assert parsed[1].start == 0x8000

    def test_the_example_exceeds_2048_bytes_and_is_still_accepted(self, tmp_path: Path) -> None:
        """The whole point of the policy correction, asserted on a real binary."""
        path = _build(tmp_path, 0x6000, 0x8000)
        data = path.read_bytes()
        assert len(data) > 2048
        assert xex_layout.validate_xex_layout(data)  # accepted, because the ranges are legal

    def test_the_same_address_for_player_and_song_data_is_refused(self, tmp_path: Path) -> None:
        out = tmp_path / "same.xex"
        with pytest.raises(XexLayoutError) as excinfo:
            _build(tmp_path, 0x6000, 0x6000, name="same")
        message = str(excinfo.value)
        assert "overlaps" in message
        assert "$6000" in message
        assert not out.exists(), "a build that cannot be loaded must not leave a binary behind"

    def test_a_partial_overlap_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(XexLayoutError) as excinfo:
            _build(tmp_path, 0x6000, 0x6100, name="partial")
        assert "overlaps" in str(excinfo.value)
        assert not (tmp_path / "partial.xex").exists()

    def test_an_os_rom_address_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(XexLayoutError) as excinfo:
            _build(tmp_path, 0xC000, 0x8000, name="rom")
        assert "outside the permitted user RAM region" in str(excinfo.value)
        assert not (tmp_path / "rom.xex").exists()

    def test_a_song_data_address_in_rom_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(XexLayoutError) as excinfo:
            _build(tmp_path, 0x3000, 0xC000, name="romdata")
        assert "outside the permitted user RAM region" in str(excinfo.value)

    def test_a_range_that_crosses_into_rom_is_refused(self, tmp_path: Path) -> None:
        """The player starts below $C000 but does not fit below it."""
        with pytest.raises(XexLayoutError) as excinfo:
            _build(tmp_path, 0xBC00, 0x3000, name="cross")
        assert "outside the permitted user RAM region" in str(excinfo.value)

    def test_the_basic_rom_window_is_accepted(self, tmp_path: Path) -> None:
        """``$A000`` is BASIC ROM on a stock machine; the project relocates there on purpose."""
        parsed = xex_layout.validate_xex_file(_build(tmp_path, 0xA000, 0x8500))
        assert parsed[0].start == 0xA000

    def test_a_descending_but_disjoint_layout_is_accepted(self, tmp_path: Path) -> None:
        parsed = xex_layout.validate_xex_file(_build(tmp_path, 0x8000, 0x6000))
        assert ranges(parsed)[:2] == [(0x8000, 0x8A76), (0x6000, 0x608E)]

    def test_a_single_segment_layout_is_accepted(self, tmp_path: Path) -> None:
        """No music address: the song data follows the player in one segment."""
        path = _build(tmp_path, 0x6000, None, name="single")
        parsed = xex_layout.validate_xex_file(path)
        assert len(parsed) == 2  # one user segment plus the RUN vector
        assert parsed[0].role == "player and song data (one segment)"


# ---------------------------------------------------------------------------
# 6. The player-size rule, through the same validation path
# ---------------------------------------------------------------------------
@needs_mads
class TestPlayerSizeLimit:
    """The strict ``< 2048`` rule, exercised through the build's own validation.

    The assembled player is 1144 bytes and cannot be grown to the boundary on demand, so only
    the *measurement* is controlled here; everything after it is real — MADS assembles the
    container, and the check is the one the pipeline runs.
    """

    def test_the_real_player_passes(self, tmp_path: Path) -> None:
        assert _build(tmp_path, 0x6000, 0x8000).exists()

    def test_a_player_of_exactly_2048_bytes_is_refused(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(player_budget, "measure_player_size", lambda *a, **k: 2048)
        out = tmp_path / "over.xex"
        with pytest.raises(player_budget.PlayerSizeError) as excinfo:
            _build(tmp_path, 0x6000, 0x8000, name="over")
        assert "2048" in str(excinfo.value)
        assert "exclusive" in str(excinfo.value)
        assert not out.exists(), "an over-limit player must not leave a binary behind"

    def test_a_player_of_2047_bytes_passes_when_the_layout_is_valid(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(player_budget, "measure_player_size", lambda *a, **k: 2047)
        assert _build(tmp_path, 0x6000, 0x8000, name="just_fits").exists()

    def test_the_limit_itself_is_strict(self) -> None:
        assert player_budget.PLAYER_SIZE_LIMIT_BYTES == 2048
        assert player_budget.player_size_limit_ok(2047) is True
        assert player_budget.player_size_limit_ok(2048) is False


# ---------------------------------------------------------------------------
# 7. The CLI reports a bad layout as an error, not as a traceback
# ---------------------------------------------------------------------------
@needs_mads
class TestCliReporting:
    def test_an_overlapping_layout_is_reported_cleanly(self, tmp_path: Path) -> None:
        out = tmp_path / "cli.xex"
        result = CliRunner().invoke(cli, [
            "build-xex", str(EXAMPLES / "dungeon_dark.json"),
            "-o", str(out), "--mads", str(MADS),
            "--player-address", "0x6000", "--music-address", "0x6000",
        ])
        assert result.exit_code != 0
        assert "XEX layout error" in result.output
        assert "overlaps" in result.output
        assert "Traceback" not in result.output
        assert not out.exists()

    def test_an_os_rom_layout_is_reported_cleanly(self, tmp_path: Path) -> None:
        out = tmp_path / "rom.xex"
        result = CliRunner().invoke(cli, [
            "build-xex", str(EXAMPLES / "dungeon_dark.json"),
            "-o", str(out), "--mads", str(MADS),
            "--player-address", "0xC000", "--music-address", "0x8000",
        ])
        assert result.exit_code != 0
        assert "outside the permitted user RAM region" in result.output
        assert "Traceback" not in result.output
        assert not out.exists()

    def test_a_valid_layout_still_builds(self, tmp_path: Path) -> None:
        out = tmp_path / "ok.xex"
        result = CliRunner().invoke(cli, [
            "build-xex", str(EXAMPLES / "dungeon_dark.json"),
            "-o", str(out), "--mads", str(MADS),
            "--player-address", "0x6000", "--music-address", "0x8000",
        ])
        assert result.exit_code == 0, result.output
        assert "Successfully compiled XEX" in result.output
        assert out.exists()
        assert out.stat().st_size > 2048

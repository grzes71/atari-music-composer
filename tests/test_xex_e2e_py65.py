"""End-to-end verification of production-generated Atari XEX files in py65.

Unlike unit tests that assemble synthetic ``JSR music_init`` / ``JSR music_update``
wrappers, this suite builds real Atari DOS ``.xex`` binaries through the production
Studio ``ExportService`` -> ``build_xex_from_result()`` -> MADS pipeline, validates
their container structure with ``xex_layout``, loads every segment into ``py65``,
executes ``INITAD`` / ``RUNAD`` directly, drives the real interactive ANTIC Mode 2
harness through its ``RTCLOK`` (``$14``) VBLANK loop, and verifies:

1. Exact POKEY ``$D200-$D208`` register parity against ``frame_simulator.py`` for both
   Format v1 and Format v2 (4 active channels, multiple instruments, ``PROGRAM_CHANGE``,
   transient macros, volume overrides, pitch envelopes, C1 octave pulse, 16-bit bass).
2. Harness VU meter accuracy on v2 macro ``vol_override`` frames (``ch_out_vol,x``) and
   v1 compatibility, inspected directly from emulated Graphics 0 screen RAM (``SAVMSC``).
3. Interactive keyboard controls (``1``-``4`` channel mute/unmute, ``Space`` pause/resume)
   through the real ``CH`` (``$02FC``) shadow register.
4. Zero writes into OS ROM or unpermitted hardware register space, bounded cycle budgets,
   and Atari DOS ``INITAD`` / ``RUNAD`` loader semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pytest

from atari_music import frame_simulator, pokey_hw, xex_layout
from atari_music.api import MusicGenerationResult, generate_music
from atari_music.constants import (
    AUDCTL_CH1_179MHZ,
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_PURE_TONE,
)
from atari_music.instruments import load_instrument_catalog
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRPattern,
    IRSong,
)
from atari_music.player_budget import (
    DEFAULT_MADS,
    DEFAULT_PLAYER_ASM,
    PLAYER_SIZE_LIMIT_BYTES,
    check_player_size,
    measure_player_size,
)
from atari_music.studio import (
    ExportService,
    InstrumentService,
    StudioArrangementConfig,
    XexExportOptions,
    load_studio_composition,
)
from conftest import require_local_artifact

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS_EXE = REPO_ROOT / "tools" / "mads" / "mads.exe"
PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"

# Atari OS / Hardware addresses exercised by the production harness
RTCLOK_LO = 0x0014
SAVMSC_LO = 0x0058
SAVMSC_HI = 0x0059
COLOR1_SHADOW = 0x02C5
COLOR2_SHADOW = 0x02C6
COLOR4_SHADOW = 0x02C8
RUNAD_LO = 0x02E0
RUNAD_HI = 0x02E1
INITAD_LO = 0x02E2
INITAD_HI = 0x02E3
CH_KEY_SHADOW = 0x02FC

DEFAULT_SAVMSC = 0xBC40  # Standard 64KB XL/XE OS Graphics 0 screen RAM ($BC40-$BFFF, 960 B)
INIT_RETURN_TRAP = 0x03FD  # Unused OS page-3 slot used solely as RTS trap for INITAD calls

# Atari internal key codes read from CH ($02FC) by the production harness
KEY_CH1 = 0x1F  # '1'
KEY_CH2 = 0x1E  # '2'
KEY_CH3 = 0x1A  # '3'
KEY_CH4 = 0x18  # '4'
KEY_SPACE = 0x21  # 'Space'

# Hardware addresses the production harness + player are legally allowed to write in $C000-$FFFF
PERMITTED_HW_WRITES = frozenset(
    {
        0xD017,  # COLPF1 (GTIA)
        0xD018,  # COLPF2 (GTIA)
        0xD01A,  # COLBK  (GTIA)
        0xD200,  # AUDF1  (POKEY)
        0xD201,  # AUDC1  (POKEY)
        0xD202,  # AUDF2  (POKEY)
        0xD203,  # AUDC2  (POKEY)
        0xD204,  # AUDF3  (POKEY)
        0xD205,  # AUDC3  (POKEY)
        0xD206,  # AUDF4  (POKEY)
        0xD207,  # AUDC4  (POKEY)
        0xD208,  # AUDCTL (POKEY)
        0xD40E,  # NMIEN  (ANTIC)
    }
)


class XexExecutionTimeoutError(TimeoutError):
    """Raised when a loaded XEX exceeds its bounded cycle/instruction budget."""


@dataclass
class XexExecutionResult:
    """Complete trace captured from executing an actual XEX file in py65."""

    xex_path: Path
    segments: List[xex_layout.XexSegment]
    runad: int
    initad_calls: List[Tuple[int, int]]  # (init_addr, cycles)
    pokey_frames: np.ndarray  # shape (num_frames, 9), uint8: AUDF1..AUDC4, AUDCTL
    init_pokey_writes: List[Tuple[int, int]]  # (addr, val) written before frame 0 VBLANK wait
    frame_pokey_writes: List[List[Tuple[int, int]]]  # per-frame (addr, val) writes
    hw_writes: List[Tuple[int, int]]  # non-POKEY permitted HW writes (GTIA/ANTIC)
    illegal_writes: List[Tuple[int, int, int]]  # (pc, addr, val)
    screen_snapshots: List[bytes]  # 960-byte Graphics 0 screen RAM after each frame
    frame_cycles: List[int]
    init_cycles: int
    total_cycles: int
    stop_reason: str
    final_pc: int
    memory: bytearray = field(repr=False)


def _antic_row_to_ascii(screen_ram: bytes, row: int) -> str:
    """Decode one 40-column ANTIC Mode 2 screen row into readable ASCII (inverted -> '#')."""
    base = row * 40
    chars: List[str] = []
    for b in screen_ram[base : base + 40]:
        if b == 0x80:
            chars.append("#")
        else:
            raw = b & 0x7F
            if raw < 64:
                chars.append(chr(raw + 32))
            elif raw < 96:
                chars.append(chr(raw))
            else:
                chars.append("?")
    return "".join(chars)


def _extract_vu_bar_counts(screen_ram: bytes) -> Tuple[int, int, int, int]:
    """Read the 4 channel VU meter bar counts (0..16 solid '$80' blocks at rows 10..13, cols 8..23)."""
    counts: List[int] = []
    for ch_idx in range(4):
        row_start = (10 + ch_idx) * 40
        meter = screen_ram[row_start + 8 : row_start + 24]
        solid = sum(1 for b in meter if b == 0x80)
        dashes = sum(1 for b in meter if b == 13)
        assert solid + dashes == 16, f"unexpected VU cells on CH{ch_idx + 1}: {list(meter)}"
        # All solid blocks must be left-aligned before dashes
        assert all(b == 0x80 for b in meter[:solid]) and all(b == 13 for b in meter[solid:])
        counts.append(solid)
    return (counts[0], counts[1], counts[2], counts[3])


def _extract_channel_on_off(screen_ram: bytes) -> Tuple[str, str, str, str]:
    """Decode the 3-char 'ON '/'OFF' indicator at rows 10..13, cols 26..28."""
    labels: List[str] = []
    for ch_idx in range(4):
        row_txt = _antic_row_to_ascii(screen_ram, 10 + ch_idx)
        labels.append(row_txt[26:29].strip())
    return (labels[0], labels[1], labels[2], labels[3])


def run_xex_in_py65(
    xex_path: Path,
    num_frames: int,
    *,
    player_address: Optional[int] = None,
    music_address: Optional[int] = None,
    savmsc: int = DEFAULT_SAVMSC,
    key_schedule: Optional[Mapping[int, int]] = None,
    max_init_cycles: int = 250_000,
    max_frame_cycles: int = 100_000,
    max_total_cycles: int = 10_000_000,
) -> XexExecutionResult:
    """Parse, validate, load, and execute an actual Atari DOS ``.xex`` file in ``py65``.

    Implements genuine Atari DOS binary load semantics:
    - Validates container framing, segment ranges (``$0400-$BFFF``), and disjointness via
      ``xex_layout.validate_xex_layout``.
    - Copies each segment payload to its exact 6502 load address in file order.
    - Immediately executes any ``INITAD`` (``$02E2-$02E3``) routine until ``RTS`` before
      loading subsequent segments, then clears ``INITAD``.
    - Enters execution at the actual ``RUNAD`` (``$02E0-$02E1``) vector and advances the
      emulated ``RTCLOK`` (``$14``) only when the program enters its real VBLANK wait loop.
    """
    pytest.importorskip("py65")
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory

    raw_bytes = Path(xex_path).read_bytes()
    segments = xex_layout.validate_xex_layout(
        raw_bytes,
        player_address=player_address,
        music_address=music_address,
    )

    backing = bytearray(0x10000)
    mem = ObservableMemory(subject=backing)
    mpu = MPU(memory=mem)

    # Minimal Atari XL/XE OS state expected by the standalone XEX harness
    backing[RTCLOK_LO] = 0
    backing[SAVMSC_LO] = savmsc & 0xFF
    backing[SAVMSC_HI] = (savmsc >> 8) & 0xFF
    backing[CH_KEY_SHADOW] = 0xFF
    backing[INIT_RETURN_TRAP] = 0x00  # BRK sentinel (we halt on pc == INIT_RETURN_TRAP)

    initad_calls: List[Tuple[int, int]] = []
    runad: Optional[int] = None

    def _run_subroutine(entry_addr: int, budget_cycles: int, label: str) -> int:
        ret = INIT_RETURN_TRAP - 1
        backing[0x01FF] = (ret >> 8) & 0xFF
        backing[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = entry_addr
        c0 = mpu.processorCycles
        while mpu.pc != INIT_RETURN_TRAP:
            mpu.step()
            if mpu.processorCycles - c0 > budget_cycles:
                raise XexExecutionTimeoutError(
                    f"{label} at ${entry_addr:04X} exceeded {budget_cycles} cycles "
                    f"(stuck at PC=${mpu.pc:04X})"
                )
        return mpu.processorCycles - c0

    # 1. Load segments in exact Atari DOS file order, honoring INITAD and RUNAD vectors
    for seg in segments:
        payload = raw_bytes[seg.payload_offset : seg.payload_offset + seg.length]
        backing[seg.start : seg.end + 1] = payload

        if seg.start <= INITAD_HI and seg.end >= INITAD_LO:
            init_addr = backing[INITAD_LO] | (backing[INITAD_HI] << 8)
            if not (xex_layout.USER_RAM_START <= init_addr <= xex_layout.USER_RAM_END):
                raise AssertionError(f"INITAD vector ${init_addr:04X} outside user RAM")
            cy = _run_subroutine(init_addr, max_init_cycles, "INITAD")
            initad_calls.append((init_addr, cy))
            backing[INITAD_LO] = 0
            backing[INITAD_HI] = 0

        if seg.start <= RUNAD_HI and seg.end >= RUNAD_LO:
            runad = backing[RUNAD_LO] | (backing[RUNAD_HI] << 8)

    if runad is None:
        raise AssertionError("XEX container did not define a RUNAD ($02E0-$02E1) entry vector")
    if not (xex_layout.USER_RAM_START <= runad <= xex_layout.USER_RAM_END):
        raise AssertionError(f"RUNAD vector ${runad:04X} outside user RAM")

    # 2. Attach hardware/memory write observers and RTCLOK VBLANK gate
    init_pokey_writes: List[Tuple[int, int]] = []
    frame_pokey_writes: List[List[Tuple[int, int]]] = []
    hw_writes: List[Tuple[int, int]] = []
    illegal_writes: List[Tuple[int, int, int]] = []

    pokey_frames = np.zeros((num_frames, 9), dtype=np.uint8)
    screen_snapshots: List[bytes] = []
    frame_cycles: List[int] = []

    current_frame = -1  # -1 during boot/init prior to first VBLANK wait
    rtclok_reads_this_wait = 0
    frame_start_cycle = mpu.processorCycles
    init_cycles = 0
    stop_reason = ""
    done = False

    def _on_high_mem_write(addr: int, val: int) -> None:
        if 0xD200 <= addr <= 0xD208:
            if current_frame < 0:
                init_pokey_writes.append((addr, val))
            elif current_frame < num_frames:
                frame_pokey_writes[current_frame].append((addr, val))
            return
        if addr in PERMITTED_HW_WRITES:
            hw_writes.append((addr, val))
            return
        illegal_writes.append((mpu.pc, addr, val))

    mem.subscribe_to_write(range(0xC000, 0x10000), _on_high_mem_write)

    def _on_rtclok_read(_addr: int) -> Optional[int]:
        nonlocal current_frame, rtclok_reads_this_wait, frame_start_cycle, init_cycles, done, stop_reason
        rtclok_reads_this_wait += 1
        # In main_loop: read #1 is `lda $14`, read #2 is `@wait_vblank: cmp $14`.
        # On read #2, the previous frame (or boot init) has finished cleanly and the CPU
        # is waiting for the next 50 Hz PAL VBLANK tick.
        if rtclok_reads_this_wait < 2:
            return None

        rtclok_reads_this_wait = 0
        now = mpu.processorCycles
        if current_frame < 0:
            init_cycles = now - run_start_cycle
        else:
            for col in range(9):
                pokey_frames[current_frame, col] = backing[0xD200 + col]
            if savmsc:
                screen_snapshots.append(bytes(backing[savmsc : savmsc + 960]))
            frame_cycles.append(now - frame_start_cycle)

        current_frame += 1
        if current_frame >= num_frames:
            done = True
            stop_reason = "completed_requested_frames"
            return None

        frame_pokey_writes.append([])
        frame_start_cycle = now
        if key_schedule and current_frame in key_schedule:
            backing[CH_KEY_SHADOW] = key_schedule[current_frame] & 0xFF
        backing[RTCLOK_LO] = (backing[RTCLOK_LO] + 1) & 0xFF
        return backing[RTCLOK_LO]

    mem.subscribe_to_read([RTCLOK_LO], _on_rtclok_read)

    # 3. Execute from real RUNAD entry point with strict cycle bounds
    mpu.sp = 0xFF
    mpu.pc = runad
    run_start_cycle = mpu.processorCycles
    frame_start_cycle = run_start_cycle

    while not done:
        mpu.step()
        elapsed_total = mpu.processorCycles - run_start_cycle
        if elapsed_total > max_total_cycles:
            raise XexExecutionTimeoutError(
                f"XEX execution exceeded total budget ({max_total_cycles} cycles) "
                f"at frame={current_frame}, PC=${mpu.pc:04X}"
            )
        if current_frame < 0:
            if mpu.processorCycles - run_start_cycle > max_init_cycles:
                raise XexExecutionTimeoutError(
                    f"XEX initialization exceeded {max_init_cycles} cycles before first VBLANK "
                    f"(PC=${mpu.pc:04X})"
                )
        else:
            if mpu.processorCycles - frame_start_cycle > max_frame_cycles:
                raise XexExecutionTimeoutError(
                    f"XEX frame {current_frame} exceeded {max_frame_cycles} cycles "
                    f"(PC=${mpu.pc:04X})"
                )

    return XexExecutionResult(
        xex_path=Path(xex_path),
        segments=segments,
        runad=runad,
        initad_calls=initad_calls,
        pokey_frames=pokey_frames,
        init_pokey_writes=init_pokey_writes,
        frame_pokey_writes=frame_pokey_writes,
        hw_writes=hw_writes,
        illegal_writes=illegal_writes,
        screen_snapshots=screen_snapshots,
        frame_cycles=frame_cycles,
        init_cycles=init_cycles,
        total_cycles=mpu.processorCycles - run_start_cycle,
        stop_reason=stop_reason,
        final_pc=mpu.pc,
        memory=backing,
    )


def _export_ir_via_studio(
    song: IRSong,
    tmp_path: Path,
    stem: str,
    *,
    player_version: str = "auto",
    player_address: str = "$6000",
    music_address: str = "$8000",
) -> Tuple[Path, Path, int]:
    """Save *song* as IR JSON and export a real XEX (+ companion ASM) through Studio ExportService."""
    ir_path = tmp_path / f"{stem}.json"
    song.to_json_file(ir_path)
    state = load_studio_composition(ir_path)
    svc = InstrumentService()
    exporter = ExportService(svc)
    cfg = state.baseline_config.model_copy(
        update={
            "player_version": player_version,
            "target_backend": "xex_v1" if player_version == "v1" else "xex_v2",
        }
    )
    out_xex = tmp_path / f"{stem}.xex"
    res = exporter.export_xex(
        state,
        cfg,
        XexExportOptions(
            output_path=out_xex,
            player_address=player_address,
            music_address=music_address,
            keep_asm=True,
            mads_bin=MADS_EXE,
            player_asm=PLAYER_ASM,
        ),
    )
    assert res.asm_path is not None and res.asm_path.is_file()
    return res.xex_path, res.asm_path, res.format_version


def _build_v2_8bit_rich_song() -> IRSong:
    """Build a deterministic 4-channel v2 8-bit song covering all Iter-1 features.

    - CH1: bass_poly4_punch (pitch envelope)
    - CH2: lead_c1_octave_pulse (C1 octave pulse modulation)
    - CH3: lead_pure_sustain -> PROGRAM_CHANGE -> lead_attack_bite (2-step transient macro)
    - CH4: perc_kick_tight (5-step macro + pitch env + vol_override) -> PROGRAM_CHANGE ->
           perc_snare_crisp (4-step macro + vol_override) -> PROGRAM_CHANGE ->
           perc_hihat_closed (3-step macro + vol_override)
    """
    cat = load_instrument_catalog()
    ids = [
        "bass_poly4_punch",
        "lead_c1_octave_pulse",
        "lead_pure_sustain",
        "lead_attack_bite",
        "perc_kick_tight",
        "perc_snare_crisp",
        "perc_hihat_closed",
    ]
    insts = [
        IRInstrument.from_catalog_profile(idx, *cat.resolve_profile_behavior(pid))
        for idx, pid in enumerate(ids)
    ]
    pat0 = IRPattern(
        id=0,
        name="MainA",
        rows=8,
        tracks={
            1: [
                IRNote(pitch="A-2", midi_pitch=45, duration=4, volume=14, instrument_id=0),
                IRNote(pitch="E-2", midi_pitch=40, duration=4, volume=14, instrument_id=0),
            ],
            2: [
                IRNote(pitch="E-4", midi_pitch=64, duration=4, volume=11, instrument_id=1),
                IRNote(pitch="G-4", midi_pitch=67, duration=4, volume=11, instrument_id=1),
            ],
            3: [
                IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=13, instrument_id=2),
                IRNote(
                    pitch="C-5",
                    midi_pitch=72,
                    duration=4,
                    volume=14,
                    instrument_id=3,
                    pending_program_changes=(3,),
                ),
            ],
            4: [
                IRNote(duration=2, volume=15, instrument_id=4, channel_role="percussion"),
                IRNote(
                    duration=2,
                    volume=13,
                    instrument_id=6,
                    channel_role="percussion",
                    pending_program_changes=(6,),
                ),
                IRNote(
                    duration=2,
                    volume=14,
                    instrument_id=5,
                    channel_role="percussion",
                    pending_program_changes=(5,),
                ),
                IRNote(
                    duration=2,
                    volume=13,
                    instrument_id=6,
                    channel_role="percussion",
                    pending_program_changes=(6,),
                ),
            ],
        },
    )
    return IRSong(
        title="Stage2 V2 8bit",
        author="Stage2 Test",
        tempo_bpm=150,
        frames_per_tick=4,
        key="A",
        mode="minor",
        instruments=insts,
        patterns=[pat0],
        sequence=[0, 0],
        uses_16bit_bass=False,
        initial_channel_instruments={1: 0, 2: 1, 3: 2, 4: 4},
    )


def _build_v2_16bit_song() -> IRSong:
    """Build a deterministic v2 song with 16-bit CH1+CH2 bass ($50), macro lead, and drum switches."""
    cat = load_instrument_catalog()
    ids = [
        "bass_16bit_pure",
        "lead_attack_bite",
        "perc_kick_tight",
        "perc_snare_crisp",
    ]
    insts = [
        IRInstrument.from_catalog_profile(idx, *cat.resolve_profile_behavior(pid))
        for idx, pid in enumerate(ids)
    ]
    pat0 = IRPattern(
        id=0,
        name="Bass16",
        rows=8,
        tracks={
            1: [
                IRNote(pitch="A-1", midi_pitch=33, duration=4, volume=14, instrument_id=0),
                IRNote(pitch="G-1", midi_pitch=31, duration=4, volume=14, instrument_id=0),
            ],
            3: [
                IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=13, instrument_id=1),
                IRNote(pitch="B-4", midi_pitch=71, duration=4, volume=13, instrument_id=1),
            ],
            4: [
                IRNote(duration=4, volume=15, instrument_id=2, channel_role="percussion"),
                IRNote(
                    duration=4,
                    volume=14,
                    instrument_id=3,
                    channel_role="percussion",
                    pending_program_changes=(3,),
                ),
            ],
        },
    )
    return IRSong(
        title="Stage2 V2 16bit",
        author="Stage2 Test",
        tempo_bpm=140,
        frames_per_tick=4,
        key="A",
        mode="minor",
        instruments=insts,
        patterns=[pat0],
        sequence=[0],
        uses_16bit_bass=True,
        initial_channel_instruments={1: 0, 2: 0, 3: 1, 4: 2},
    )


def test_real_xex_v1_end_to_end_py65_parity(tmp_path: Path) -> None:
    """Export real v1 XEX via Studio ExportService, boot from RUNAD in py65, verify POKEY parity."""
    require_local_artifact(MADS_EXE)
    require_local_artifact(PLAYER_ASM)

    # Confirm player size remains strictly below 2048 B
    player_sz = measure_player_size(DEFAULT_PLAYER_ASM, DEFAULT_MADS)
    assert player_sz is not None
    assert check_player_size(player_sz) < PLAYER_SIZE_LIMIT_BYTES

    song = generate_music(profile="action", seed=42).pokey_ir
    xex_path, asm_path, fmt_ver = _export_ir_via_studio(song, tmp_path, "real_v1", player_version="v1")
    assert fmt_ver == 1
    assert "; format version (0 = no version byte" in asm_path.read_text(encoding="utf-8")

    num_frames = 60
    run = run_xex_in_py65(xex_path, num_frames, player_address=0x6000, music_address=0x8000)

    assert run.stop_reason == "completed_requested_frames"
    assert run.runad == 0x6000
    assert run.illegal_writes == []
    # Initialization wrote NMIEN=$40 and GTIA colors, and silenced POKEY during music_init
    assert (0xD40E, 0x40) in run.hw_writes
    assert (0xD018, 0xC4) in run.hw_writes
    assert any(addr == 0xD208 and val == 0 for addr, val in run.init_pokey_writes)

    # Screen header and status were genuinely drawn by init_screen_layout + update_screen_ui
    row1 = _antic_row_to_ascii(run.screen_snapshots[0], 1)
    row6 = _antic_row_to_ascii(run.screen_snapshots[0], 6)
    assert "ATARI POKEY MUSIC PLAYER" in row1
    assert "[PLAYING]" in row6

    # Bit-exact $D200-$D208 register parity with independent Python oracle
    oracle_frames = frame_simulator.simulate_ir_song_frames(song, num_frames, format_version=1)
    assert np.array_equal(run.pokey_frames, oracle_frames), (
        f"real v1 XEX POKEY trace diverged from frame_simulator oracle; "
        f"first mismatch frame={int(np.argmax(np.any(run.pokey_frames != oracle_frames, axis=1)))}"
    )


def test_real_xex_v2_8bit_multi_inst_macro_pitch_c1_and_pc_py65_parity(tmp_path: Path) -> None:
    """Export real v2 8-bit 4-ch XEX via Studio ExportService and verify bit-exact py65 parity."""
    require_local_artifact(MADS_EXE)
    require_local_artifact(PLAYER_ASM)

    song = _build_v2_8bit_rich_song()
    xex_path, asm_path, fmt_ver = _export_ir_via_studio(song, tmp_path, "real_v2_8bit", player_version="v2")
    assert fmt_ver == 2
    asm_txt = asm_path.read_text(encoding="utf-8")
    assert "format version 2" in asm_txt
    assert "; PROGRAM_CHANGE inst=" in asm_txt

    num_frames = 64  # Full 2-pattern sequence (2 * 8 rows * 4 frames/tick = 64 frames)
    run = run_xex_in_py65(xex_path, num_frames, player_address=0x6000, music_address=0x8000)

    assert run.stop_reason == "completed_requested_frames"
    assert run.runad == 0x6000
    assert run.illegal_writes == []
    assert len(run.segments) == 3  # player+harness ($6000), song_data ($8000), RUNAD ($02E0-$02E1)

    # Bit-exact $D200-$D208 parity against independent Python oracle
    oracle_frames = frame_simulator.simulate_ir_song_frames(song, num_frames, format_version=2)
    assert np.array_equal(run.pokey_frames, oracle_frames), (
        f"real v2 8-bit XEX POKEY trace diverged from oracle; "
        f"first mismatch frame={int(np.argmax(np.any(run.pokey_frames != oracle_frames, axis=1)))}"
    )

    # Confirm all 4 POKEY channels actually produced non-zero audible output
    for ch_idx in range(4):
        audc_col = ch_idx * 2 + 1
        assert np.any((run.pokey_frames[:, audc_col] & 0x0F) > 0), f"CH{ch_idx + 1} stayed silent"

    # Confirm C1 octave pulse alternation on CH2 (frame 0 vs frame 1 divider N vs N//2)
    assert int(run.pokey_frames[0, 2]) // 2 == int(run.pokey_frames[1, 2])
    assert int(run.pokey_frames[0, 2]) != int(run.pokey_frames[1, 2])

    # Confirm CH1 pitch envelope sweeps AUDF1 across early frames
    assert len({int(run.pokey_frames[f, 0]) for f in range(4)}) >= 3

    # Confirm CH3 PROGRAM_CHANGE switched to lead_attack_bite macro at frame 16 (tick 4 * 4 fpt)
    assert int(run.pokey_frames[16, 5]) & 0xE0 != int(run.pokey_frames[0, 5]) & 0xE0


def test_real_xex_v2_16bit_bass_and_program_change_py65_parity(tmp_path: Path) -> None:
    """Export real v2 16-bit CH1+CH2 bass XEX ($50) via Studio ExportService and verify py65 parity."""
    require_local_artifact(MADS_EXE)
    require_local_artifact(PLAYER_ASM)

    song = _build_v2_16bit_song()
    xex_path, _asm_path, fmt_ver = _export_ir_via_studio(song, tmp_path, "real_v2_16bit", player_version="v2")
    assert fmt_ver == 2

    num_frames = 32
    run = run_xex_in_py65(xex_path, num_frames, player_address=0x6000, music_address=0x8000)
    assert run.stop_reason == "completed_requested_frames"
    assert run.illegal_writes == []

    oracle_frames = frame_simulator.simulate_ir_song_frames(song, num_frames, format_version=2)
    assert np.array_equal(run.pokey_frames, oracle_frames)

    # Hardware 16-bit CH1+CH2 invariants: AUDCTL=$50, AUDC1 muted ($00), AUDC2 carries audible bass
    expected_audctl = AUDCTL_JOIN_1_2_16BIT | AUDCTL_CH1_179MHZ
    assert set(int(v) for v in run.pokey_frames[:, 8]) == {expected_audctl}
    assert set(int(v) for v in run.pokey_frames[:, 1]) == {0}
    assert np.any((run.pokey_frames[:, 3] & 0x0F) > 0)


def test_xex_harness_vu_meter_reflects_v2_macro_volume_override_and_keyboard_controls(
    tmp_path: Path,
) -> None:
    """Verify harness uses ch_out_vol,x (macro vol_override visible on VU) and 1-4 / Space keys work."""
    require_local_artifact(MADS_EXE)
    require_local_artifact(PLAYER_ASM)

    # Instrument with slow low-volume ADSR (attack=6, sustain=3) but macro vol_override=15 on frames 0..1
    # and vol_override=2 on frames 2..3 -> sharply separates ch_out_vol from ch_cur_vol!
    override_inst = IRInstrument(
        id=0,
        name="MacroVolLead",
        distortion=DISTORTION_PURE_TONE,
        envelope=IREnvelope(attack_frames=6, decay_frames=0, sustain_vol=3, release_frames=0),
        macro=[
            IRMacroStep(frames_per_step=2, audc_dist=DISTORTION_4BIT_POLY, audf_mode="offset", audf_offset=0, vol_override=15),
            IRMacroStep(frames_per_step=2, audc_dist=None, audf_mode="offset", audf_offset=0, vol_override=2),
        ],
    )
    plain_inst = IRInstrument(
        id=1,
        name="PlainTone",
        distortion=DISTORTION_PURE_TONE,
        envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=10, release_frames=0),
    )
    song = IRSong(
        title="VU Override Test",
        author="Stage2",
        tempo_bpm=125,
        frames_per_tick=4,
        instruments=[override_inst, plain_inst],
        patterns=[
            IRPattern(
                id=0,
                name="P0",
                rows=4,
                tracks={
                    1: [IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=10, instrument_id=1)],
                    3: [IRNote(pitch="C-5", midi_pitch=72, duration=4, volume=6, instrument_id=0)],
                },
            )
        ],
        sequence=[0],
        initial_channel_instruments={1: 1, 2: 1, 3: 0, 4: 1},
    )

    xex_path, asm_path, fmt_ver = _export_ir_via_studio(song, tmp_path, "vu_override", player_version="v2")
    assert fmt_ver == 2
    asm_txt = asm_path.read_text(encoding="utf-8")
    assert "lda ch_out_vol,x" in asm_txt
    assert "lda ch_cur_vol,x" not in asm_txt

    # Inject keys: frame 6 mute CH1 ('1'), frame 8 unmute CH1 ('1'), frame 10 Space (pause), frame 13 Space (resume)
    run = run_xex_in_py65(
        xex_path,
        num_frames=16,
        player_address=0x6000,
        music_address=0x8000,
        key_schedule={
            6: KEY_CH1,
            8: KEY_CH1,
            10: KEY_SPACE,
            13: KEY_SPACE,
        },
    )
    assert run.illegal_writes == []

    # Frames 0..1: CH3 macro vol_override=15 (while ADSR ch_cur_vol was only 1..2!) -> VU must draw 15 bars!
    vu_f0 = _extract_vu_bar_counts(run.screen_snapshots[0])
    vu_f1 = _extract_vu_bar_counts(run.screen_snapshots[1])
    assert vu_f0[2] == 15, f"expected CH3 VU=15 during macro vol_override=15, got {vu_f0[2]}"
    assert vu_f1[2] == 15, f"expected CH3 VU=15 on macro frame 1, got {vu_f1[2]}"
    assert int(run.pokey_frames[0, 5]) & 0x0F == 15

    # Frames 2..3: CH3 macro vol_override=2 -> VU drops to 2 bars
    vu_f2 = _extract_vu_bar_counts(run.screen_snapshots[2])
    assert vu_f2[2] == 2, f"expected CH3 VU=2 during macro vol_override=2, got {vu_f2[2]}"
    assert int(run.pokey_frames[2, 5]) & 0x0F == 2

    # Frame 4: macro expired -> CH3 VU returns to ADSR envelope output matching AUDC3 volume
    vu_f4 = _extract_vu_bar_counts(run.screen_snapshots[4])
    assert vu_f4[2] == (int(run.pokey_frames[4, 5]) & 0x0F)

    # CH1 plain instrument (sustain=10) draws 10 bars while unmuted
    assert vu_f0[0] == 10

    # Frame 6: key '1' muted CH1 -> AUDC1 silenced, VU=0, label='OFF'
    assert int(run.pokey_frames[6, 1]) == 0
    assert _extract_vu_bar_counts(run.screen_snapshots[6])[0] == 0
    assert _extract_channel_on_off(run.screen_snapshots[6])[0] == "OFF"

    # Frame 8: second key '1' unmutes CH1 -> AUDC1 active again, label='ON'
    assert (int(run.pokey_frames[8, 1]) & 0x0F) == 10
    assert _extract_channel_on_off(run.screen_snapshots[8])[0] == "ON"

    # Frame 10..12: Space paused playback -> [PAUSED ] on screen (9-char padded overwrite) and POKEY silenced
    assert "[PAUSED ]" in _antic_row_to_ascii(run.screen_snapshots[10], 6)
    assert all(int(run.pokey_frames[f, 1]) == 0 and int(run.pokey_frames[f, 5]) == 0 for f in (10, 11, 12))

    # Frame 13: second Space resumed playback -> [PLAYING] on screen and POKEY active again
    assert "[PLAYING]" in _antic_row_to_ascii(run.screen_snapshots[13], 6)
    assert (int(run.pokey_frames[13, 1]) & 0x0F) > 0

    # Also verify v1 XEX VU meter continues matching AUDC effective output volume
    v1_song = generate_music(profile="action", seed=42).pokey_ir
    v1_xex, v1_asm, v1_fmt = _export_ir_via_studio(v1_song, tmp_path, "vu_v1_compat", player_version="v1")
    assert v1_fmt == 1
    assert "lda ch_out_vol,x" in v1_asm.read_text(encoding="utf-8")
    v1_run = run_xex_in_py65(v1_xex, num_frames=8, player_address=0x6000, music_address=0x8000)
    for f_idx in range(8):
        vu = _extract_vu_bar_counts(v1_run.screen_snapshots[f_idx])
        for ch_idx in range(4):
            assert vu[ch_idx] == (int(v1_run.pokey_frames[f_idx, ch_idx * 2 + 1]) & 0x0F)


def test_xex_loader_initad_semantics_and_timeout_protection(tmp_path: Path) -> None:
    """Verify DOS INITAD ($02E2) runs before later segments and infinite loops hit bounded timeout."""
    pytest.importorskip("py65")

    def _seg(start: int, payload: bytes, mark: bool = False) -> bytes:
        end = start + len(payload) - 1
        return (b"\xff\xff" if mark else b"") + struct.pack("<HH", start, end) + payload

    # 1. Tiny XEX with INITAD ($4000: LDA #$5A; STA $0500; RTS) followed by main RUNAD ($4010)
    #    that loops reading RTCLOK twice per frame (minimal VBLANK wait).
    init_code = bytes([0xA9, 0x5A, 0x8D, 0x00, 0x05, 0x60])  # LDA #$5A; STA $0500; RTS
    # main at $4010: LDA $14; @w: CMP $14; BEQ @w; JMP $4010
    main_code = bytes([0xA5, 0x14, 0xC5, 0x14, 0xF0, 0xFC, 0x4C, 0x10, 0x40])
    init_xex = tmp_path / "with_initad.xex"
    init_xex.write_bytes(
        _seg(0x4000, init_code, mark=True)
        + _seg(0x02E2, struct.pack("<H", 0x4000))
        + _seg(0x4010, main_code)
        + _seg(0x02E0, struct.pack("<H", 0x4010))
    )
    res = run_xex_in_py65(init_xex, num_frames=2, savmsc=0)
    assert res.initad_calls and res.initad_calls[0][0] == 0x4000
    assert res.memory[0x0500] == 0x5A
    assert res.runad == 0x4010

    # 2. Hang XEX (JMP $4000) must raise XexExecutionTimeoutError cleanly within bounded cycles
    hang_xex = tmp_path / "hang.xex"
    hang_xex.write_bytes(
        _seg(0x4000, bytes([0x4C, 0x00, 0x40]), mark=True)
        + _seg(0x02E0, struct.pack("<H", 0x4000))
    )
    with pytest.raises(XexExecutionTimeoutError, match="exceeded"):
        run_xex_in_py65(hang_xex, num_frames=1, savmsc=0, max_init_cycles=1_000)

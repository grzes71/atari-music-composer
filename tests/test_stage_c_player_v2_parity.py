"""CORE/AUDIO Etap C parity, py65 6502 execution, ASAP 8.0.0, and resource tests."""

from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pytest

from atari_music import frame_simulator, pokey_hw
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_5BIT_POLY_1,
    DISTORTION_5_AND_4BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.instruments import load_instrument_catalog
from atari_music.ir import (
    IREnvelope,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRPattern,
    IRPitchEnvelope,
    IRSong,
)
from atari_music.mads_exporter import SONG_FORMAT_VERSION_2, export_mads_asm
from atari_music.player_budget import (
    DEFAULT_MADS,
    DEFAULT_PLAYER_ASM,
    PLAYER_SIZE_LIMIT_BYTES,
    PLAYER_ZERO_PAGE_BYTES,
    check_player_size,
    measure_player_size,
)

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"
ASAPCONV = REPO_ROOT / "tools" / "asap_all" / "asapconv.exe"
PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"
ROOT_PLAYER_ASM = REPO_ROOT / "player.asm"
RETURN_TRAP = 0x0200


def _load_xex_into(mpu, data: bytes) -> None:
    idx = 0
    while idx < len(data):
        if data[idx : idx + 2] == b"\xff\xff":
            idx += 2
        if idx >= len(data):
            break
        start = data[idx] | (data[idx + 1] << 8)
        end = data[idx + 2] | (data[idx + 3] << 8)
        idx += 4
        size = end - start + 1
        for i, byte in enumerate(data[idx : idx + size]):
            mpu.memory[start + i] = byte
        idx += size


def _parse_mads_labels(lab_path: Path) -> Dict[str, int]:
    symbols: Dict[str, int] = {}
    for line in lab_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            addr_s, name = parts
        elif len(parts) >= 3:
            addr_s, name = parts[1], parts[2]
        else:
            continue
        try:
            symbols[name.lower()] = int(addr_s, 16)
        except ValueError:
            continue
    return symbols


def _compile_and_run_py65(
    song: IRSong,
    tmp_path: Path,
    name: str,
    num_frames: int,
    *,
    format_version: int = SONG_FORMAT_VERSION_2,
    patch_fn=None,
) -> Tuple[np.ndarray, Dict[str, int], List[int], object]:
    """Assemble player + song, execute in py65, and return (frames, symbols, cycles, mpu)."""
    pytest.importorskip("py65")
    from py65.devices.mpu6502 import MPU

    if not MADS.is_file():
        pytest.skip("tools/mads/mads.exe not present")

    data_asm = tmp_path / f"{name}_data.asm"
    export_mads_asm(song, data_asm, song_label="song_data", format_version=format_version)

    harness_asm = tmp_path / f"{name}.asm"
    xex_path = tmp_path / f"{name}.xex"
    lab_path = tmp_path / f"{name}.lab"
    harness_asm.write_text(
        f"""
    org $4000
start:
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    rts

frame_tick:
    jsr music_update
    rts

    icl '{PLAYER_ASM.as_posix()}'
    icl '{data_asm.as_posix()}'
    run start
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(MADS), str(harness_asm), f"-o:{xex_path}", f"-t:{lab_path}"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    symbols = _parse_mads_labels(lab_path)

    mpu = MPU()
    _load_xex_into(mpu, xex_path.read_bytes())
    mpu.memory[RETURN_TRAP] = 0x00

    if patch_fn is not None:
        patch_fn(mpu, symbols)

    def _call(addr: int) -> int:
        ret = RETURN_TRAP - 1
        mpu.memory[0x01FF] = (ret >> 8) & 0xFF
        mpu.memory[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = addr
        c0 = mpu.processorCycles
        while mpu.pc != RETURN_TRAP:
            mpu.step()
            assert mpu.processorCycles - c0 < 100000, f"subroutine exceeded 100k cycle guard at pc=${mpu.pc:04x}"
        return mpu.processorCycles - c0

    _call(symbols["start"])

    reg_addrs = (0xD200, 0xD201, 0xD202, 0xD203, 0xD204, 0xD205, 0xD206, 0xD207, 0xD208)
    frames = np.zeros((num_frames, 9), dtype=np.uint8)
    cycles: List[int] = []
    for f_idx in range(num_frames):
        c = _call(symbols["frame_tick"])
        cycles.append(c)
        for col, addr in enumerate(reg_addrs):
            frames[f_idx, col] = mpu.memory[addr] & 0xFF

    return frames, symbols, cycles, mpu


def _catalog_ir_instruments() -> Dict[int, IRInstrument]:
    cat = load_instrument_catalog()
    mapping = {
        0: "lead_pure_sustain",
        1: "bass_poly4_punch",
        2: "lead_attack_bite",
        3: "perc_kick_tight",
        4: "perc_snare_crisp",
        5: "perc_hihat_closed",
        6: "perc_tom_pitched",
        7: "lead_c1_octave_pulse",
    }
    return {
        idx: IRInstrument.from_catalog_profile(idx, *cat.resolve_profile_behavior(pid))
        for idx, pid in mapping.items()
    }


def _assert_triple_parity(song: IRSong, tmp_path: Path, name: str, num_frames: int) -> List[int]:
    py65_frames, syms, cycles, mpu = _compile_and_run_py65(song, tmp_path, name, num_frames)
    bin_oracle = frame_simulator.simulate_v2_binary_frames(mpu.memory, syms["song_data"], num_frames)
    ir_oracle = frame_simulator.simulate_ir_song_frames(song, num_frames, format_version=2)

    assert np.array_equal(py65_frames, bin_oracle), f"{name}: py65 vs binary oracle mismatch"
    assert np.array_equal(py65_frames, ir_oracle), f"{name}: py65 vs IR oracle mismatch"
    return cycles


# ===========================================================================
# 10 Mandatory Exact $D200..$D208 Parity Cases (py65 == Python Oracles)
# ===========================================================================


def test_parity_01_program_change_between_notes(tmp_path: Path) -> None:
    insts = _catalog_ir_instruments()
    lead = insts[0]
    bass = IRInstrument(id=1, name="Bass4", distortion=DISTORTION_4BIT_POLY, envelope=IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=10, release_frames=1))
    notes = [
        IRNote(pitch="A-4", midi_pitch=69, duration=2, volume=14, instrument_id=0),
        IRNote(pitch="A-3", midi_pitch=57, duration=2, volume=14, instrument_id=1),
    ]
    song = IRSong(
        title="p1", frames_per_tick=4,
        instruments=[lead, bass],
        patterns=[IRPattern(id=0, rows=4, tracks={1: notes})],
        sequence=[0],
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )
    _assert_triple_parity(song, tmp_path, "case01", 20)


def test_parity_02_program_change_at_pattern_start_and_loop(tmp_path: Path) -> None:
    i0 = IRInstrument(id=0, name="Pure", distortion=DISTORTION_PURE_TONE, envelope=IREnvelope(attack_frames=0, decay_frames=1, sustain_vol=12, release_frames=0))
    i1 = IRInstrument(id=1, name="Poly54", distortion=DISTORTION_5_AND_4BIT, envelope=IREnvelope(attack_frames=1, decay_frames=2, sustain_vol=9, release_frames=1))
    p0 = IRPattern(id=0, rows=2, tracks={1: [IRNote(pitch="A-4", midi_pitch=69, duration=2, volume=14, instrument_id=1)]})
    p1 = IRPattern(id=1, rows=2, tracks={1: [IRNote(pitch="C-5", midi_pitch=72, duration=2, volume=13, instrument_id=0)]})
    song = IRSong(
        title="p2", frames_per_tick=3,
        instruments=[i0, i1],
        patterns=[p0, p1],
        sequence=[0, 1],
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )
    # 18 frames covers Pat0 -> Pat1 -> loop back to Pat0 -> Pat1
    _assert_triple_parity(song, tmp_path, "case02", 18)


@pytest.mark.parametrize(
    "case_name,inst_idx",
    [
        ("case03_kick", 3),
        ("case04_snare", 4),
        ("case05_hihat", 5),
        ("case06_tom", 6),
        ("case07_attack_bite", 2),
    ],
)
def test_parity_03_to_07_catalog_percussion_and_attack_bite(
    tmp_path: Path, case_name: str, inst_idx: int
) -> None:
    insts = _catalog_ir_instruments()
    inst = insts[inst_idx]
    song = IRSong(
        title=case_name, frames_per_tick=4,
        instruments=[insts[0], inst],
        patterns=[IRPattern(id=0, rows=4, tracks={4: [IRNote(pitch="A-4", midi_pitch=69, duration=3, volume=15, instrument_id=inst_idx), IRNote(is_rest=True, duration=1, volume=0, instrument_id=0)]})],
        sequence=[0],
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: inst_idx},
    )
    _assert_triple_parity(song, tmp_path, case_name, 20)


def test_parity_08_simultaneous_4ch_macros_and_worst_case_cycles(tmp_path: Path) -> None:
    insts = _catalog_ir_instruments()
    p0 = IRPattern(
        id=0,
        rows=2,
        tracks={
            1: [IRNote(pitch="A-2", midi_pitch=45, duration=2, volume=14, instrument_id=1)],
            2: [IRNote(pitch="E-4", midi_pitch=64, duration=2, volume=13, instrument_id=2)],
            3: [IRNote(pitch="A-4", midi_pitch=69, duration=2, volume=14, instrument_id=2)],
            4: [IRNote(pitch="C-4", midi_pitch=60, duration=2, volume=15, instrument_id=3)],
        },
    )
    # Pattern 1 forces simultaneous PROGRAM_CHANGE across all 4 channels onto macro/pitch instruments
    p1 = IRPattern(
        id=1,
        rows=2,
        tracks={
            1: [IRNote(pitch="G-2", midi_pitch=43, duration=2, volume=14, instrument_id=2, pending_program_changes=(2,))],
            2: [IRNote(pitch="D-4", midi_pitch=62, duration=2, volume=13, instrument_id=6, pending_program_changes=(6,))],
            3: [IRNote(pitch="C-5", midi_pitch=72, duration=2, volume=14, instrument_id=4, pending_program_changes=(4,))],
            4: [IRNote(pitch="D-4", midi_pitch=62, duration=2, volume=15, instrument_id=5, pending_program_changes=(5,))],
        },
    )
    song = IRSong(
        title="p8_4ch", frames_per_tick=4,
        instruments=[insts[i] for i in range(8)],
        patterns=[p0, p1],
        sequence=[0, 1],
        initial_channel_instruments={1: 1, 2: 2, 3: 2, 4: 3},
    )
    cycles = _assert_triple_parity(song, tmp_path, "case08", 20)
    # Verify simultaneous PROGRAM_CHANGE frame (frame 8) cycle budget is bounded & recorded
    assert max(cycles) < 6000
    # Steady active 4-ch macro/pitch frame without PROGRAM_CHANGE stays tight (< 2200 cycles)
    assert min(cycles[1:4]) < 2200


def test_parity_09_program_change_interrupting_active_macro(tmp_path: Path) -> None:
    insts = _catalog_ir_instruments()
    # Note 0 uses 5-step kick (7 frames total) with 1-tick duration (3 frames) -> switches cleanly before macro ends!
    p0 = IRPattern(
        id=0,
        rows=4,
        tracks={
            4: [
                IRNote(pitch="C-4", midi_pitch=60, duration=1, volume=15, instrument_id=3),
                IRNote(pitch="A-4", midi_pitch=69, duration=3, volume=12, instrument_id=0),
            ]
        },
    )
    song = IRSong(
        title="p9", frames_per_tick=3,
        instruments=[insts[0], insts[3]],
        patterns=[p0],
        sequence=[0],
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 3},
    )
    _assert_triple_parity(song, tmp_path, "case09", 15)


def test_parity_10_combined_adsr_macro_pitch_envelope_and_audf_clamping(tmp_path: Path) -> None:
    # Extreme deltas hitting both lower clamp (0) and upper clamp (255), plus C1 octave pulse + macro + ADSR!
    i_combo = IRInstrument(
        id=0, name="Combo", distortion=DISTORTION_PURE_TONE,
        envelope=IREnvelope(attack_frames=2, decay_frames=3, sustain_vol=8, release_frames=2),
        macro=[
            IRMacroStep(frames_per_step=2, audc_dist=DISTORTION_4BIT_POLY, audf_mode="offset", audf_offset=-120, vol_override=15),
            IRMacroStep(frames_per_step=2, audc_dist=None, audf_mode="offset", audf_offset=120, vol_override=None),
        ],
        pitch_envelope=IRPitchEnvelope(start_audf_delta=-120, duration_frames=5, step_delta=-16),
        modulation=pokey_hw.MODULATION_OCTAVE_PULSE,
    )
    i_hi = IRInstrument(
        id=1, name="HiClamp", distortion=DISTORTION_PURE_TONE,
        envelope=IREnvelope(attack_frames=0, decay_frames=1, sustain_vol=10, release_frames=1),
        pitch_envelope=IRPitchEnvelope(start_audf_delta=127, duration_frames=4, step_delta=16),
    )
    song = IRSong(
        title="p10", frames_per_tick=5,
        instruments=[i_combo, i_hi],
        patterns=[IRPattern(id=0, rows=4, tracks={
            1: [IRNote(pitch="C-7", midi_pitch=96, duration=2, volume=14, instrument_id=0),
                IRNote(pitch="C-3", midi_pitch=48, duration=2, volume=14, instrument_id=1)],
        })],
        sequence=[0],
        initial_channel_instruments={1: 0, 2: 0, 3: 0, 4: 0},
    )
    _assert_triple_parity(song, tmp_path, "case10", 24)


# ===========================================================================
# Safety Guards, Version Refusal, Budget & Cycle Reports (§8.2, §9)
# ===========================================================================


def test_player_v2_runtime_safety_guards_invalid_opcode_inst_and_cmd_limit(tmp_path: Path) -> None:
    i0 = IRInstrument(id=0, name="Base", distortion=DISTORTION_PURE_TONE, envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=0))
    song = IRSong(
        title="guards", frames_per_tick=2,
        instruments=[i0],
        patterns=[IRPattern(id=0, rows=2, tracks={
            1: [IRNote(pitch="A-4", midi_pitch=69, duration=2, volume=14, instrument_id=0)],
            2: [IRNote(pitch="E-4", midi_pitch=64, duration=2, volume=14, instrument_id=0)],
        })],
        sequence=[0],
    )

    # Patch CH2 stream with bad OPCODE=$02 -> CH2 stays silent while CH1 plays cleanly!
    def _patch_bad_opcode(mpu, syms):
        ch2_addr = syms["song_data_pat_0_ch2"]
        for off, b in enumerate((0x00, 0x00, 0x02, 0x00, 0xFF)):
            mpu.memory[ch2_addr + off] = b

    frames_op, syms, _, mpu = _compile_and_run_py65(song, tmp_path, "guard_op", 4, patch_fn=_patch_bad_opcode)
    oracle_op = frame_simulator.simulate_v2_binary_frames(mpu.memory, syms["song_data"], 4)
    assert np.array_equal(frames_op, oracle_op)
    assert all(int(frames_op[f, 3]) == 0 for f in range(4))
    assert all((int(frames_op[f, 1]) & 0x0F) > 0 for f in range(4))

    # Patch CH2 stream with out-of-range PARAM (inst=5 >= inst_count=1) -> safe mute
    def _patch_bad_inst(mpu, syms):
        ch2_addr = syms["song_data_pat_0_ch2"]
        for off, b in enumerate((0x00, 0x00, 0x01, 0x05, 0xFF)):
            mpu.memory[ch2_addr + off] = b

    frames_inst, syms2, _, mpu2 = _compile_and_run_py65(song, tmp_path, "guard_inst", 4, patch_fn=_patch_bad_inst)
    oracle_inst = frame_simulator.simulate_v2_binary_frames(mpu2.memory, syms2["song_data"], 4)
    assert np.array_equal(frames_inst, oracle_inst)
    assert all(int(frames_inst[f, 3]) == 0 for f in range(4))

    # Patch CH2 with 9 consecutive commands (exceeds MAX_V2_PARSE_COMMANDS=8) -> muted safely without loop hang!
    def _patch_9_cmds(mpu, syms):
        ch2_addr = syms["song_data_pat_0_ch2"]
        payload = [0x00, 0x00, 0x01, 0x00] * 9 + [71, 2, 14, 0xFF]
        for off, b in enumerate(payload):
            mpu.memory[ch2_addr + off] = b

    frames_9, syms3, _, mpu3 = _compile_and_run_py65(song, tmp_path, "guard_9cmd", 4, patch_fn=_patch_9_cmds)
    oracle_9 = frame_simulator.simulate_v2_binary_frames(mpu3.memory, syms3["song_data"], 4)
    assert np.array_equal(frames_9, oracle_9)
    # After 8 commands on tick 0, player safely breaks with 1-tick rest (frames 0..1 muted) instead of hanging,
    # then resumes cleanly on tick 1 (frames 2..3) to process command #9 and note 71.
    assert int(frames_9[0, 3]) == 0 and int(frames_9[1, 3]) == 0
    assert (int(frames_9[2, 3]) & 0x0F) > 0

    # Patch unknown format version = 3 -> complete refusal & silence
    def _patch_ver3(mpu, syms):
        mpu.memory[syms["song_data_instruments"]] = 3

    frames_v3, _, _, _ = _compile_and_run_py65(song, tmp_path, "guard_v3", 4, patch_fn=_patch_ver3)
    assert not np.any(frames_v3)


def test_player_resource_budgets_rom_zp_ram_and_cycles(tmp_path: Path) -> None:
    """Measure ROM (< 2048 B), ZP ($80..$89 only), and BSS RAM directly via MADS."""
    if not MADS.is_file():
        pytest.skip("tools/mads/mads.exe not present")
    assert PLAYER_ASM.read_bytes() == ROOT_PLAYER_ASM.read_bytes()
    measured_rom = measure_player_size(DEFAULT_PLAYER_ASM, DEFAULT_MADS)
    assert measured_rom is not None
    assert check_player_size(measured_rom) < PLAYER_SIZE_LIMIT_BYTES
    assert PLAYER_ZERO_PAGE_BYTES == 10

    # Verify zero-page & BSS bounds on full assemble
    song = _catalog_ir_instruments()
    v2_song = IRSong(
        title="res", frames_per_tick=4,
        instruments=[song[0], song[1]],
        patterns=[IRPattern(id=0, rows=2, tracks={1: [IRNote(pitch="A-4", midi_pitch=69, duration=2, volume=14, instrument_id=0)]})],
        sequence=[0],
    )
    _, syms, _, _ = _compile_and_run_py65(v2_song, tmp_path, "res_check", 4)
    assert syms["zp_ch1_ptr"] == 0x80
    assert syms["zp_tmp_ptr"] == 0x88
    bss_bytes = syms["tmp_m_audf"] - syms["music_playing"] + 1
    assert 100 <= bss_bytes <= 256


# ===========================================================================
# ASAP 8.0.0 V2 Integration & Playback Verification (§8.5)
# ===========================================================================


@pytest.mark.skipif(
    not (MADS.is_file() and ASAPCONV.is_file()),
    reason="MADS or ASAP tools not installed in tools/",
)
def test_asap_8_0_0_renders_v2_song_with_pitch_punch_macros_and_program_change(tmp_path: Path) -> None:
    """Assemble a full v2 song + player.asm into SAP TYPE B and verify audible playback in ASAP."""
    insts = _catalog_ir_instruments()
    p0 = IRPattern(
        id=0,
        rows=8,
        tracks={
            1: [IRNote(pitch="A-2", midi_pitch=45, duration=8, volume=14, instrument_id=1)],  # bass_sub_punch
            3: [
                IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=14, instrument_id=2),  # lead_attack_bite
                IRNote(pitch="C-5", midi_pitch=72, duration=4, volume=13, instrument_id=0),  # PROGRAM_CHANGE -> pure
            ],
            4: [
                IRNote(duration=2, volume=15, instrument_id=3, channel_role="percussion"),  # Kick
                IRNote(duration=2, volume=14, instrument_id=5, channel_role="percussion"),  # PROGRAM_CHANGE -> HiHat
                IRNote(duration=2, volume=14, instrument_id=4, channel_role="percussion"),  # PROGRAM_CHANGE -> Snare
                IRNote(duration=2, volume=14, instrument_id=5, channel_role="percussion"),  # PROGRAM_CHANGE -> HiHat
            ],
        },
    )
    song = IRSong(
        title="StageC ASAP V2",
        frames_per_tick=4,
        instruments=[insts[0], insts[1], insts[2], insts[3], insts[4], insts[5]],
        patterns=[p0],
        sequence=[0],
        initial_channel_instruments={1: 1, 2: 0, 3: 2, 4: 3},
    )
    data_asm = tmp_path / "v2_sap_data.asm"
    export_mads_asm(song, data_asm, song_label="song_data", format_version=2)

    sap_asm = tmp_path / "v2_sap.asm"
    sap_xex = tmp_path / "v2_sap.xex"
    sap_file = tmp_path / "v2_sap.sap"
    wav_file = tmp_path / "v2_sap.wav"
    sap_asm.write_text(
        f"""
    org $2000
    jmp sap_init
    jmp music_update
sap_init:
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    rts
    icl '{PLAYER_ASM.as_posix()}'
    icl '{data_asm.as_posix()}'
""",
        encoding="utf-8",
    )
    subprocess.run([str(MADS), str(sap_asm), f"-o:{sap_xex}"], check=True, capture_output=True)
    hdr = b"SAP\r\nTYPE B\r\nINIT 2000\r\nPLAYER 2003\r\nTIME 00:01.00\r\n\r\n"
    sap_file.write_bytes(hdr + sap_xex.read_bytes())
    subprocess.run([str(ASAPCONV), "-o", str(wav_file), str(sap_file)], check=True, capture_output=True)

    with wave.open(str(wav_file), "rb") as wf:
        assert wf.getnchannels() == 1 and wf.getframerate() == 44100
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

    assert len(pcm) >= 44000
    # Song is active and non-silent across early kick/attack-bite, mid snare/PROGRAM_CHANGE, and tail
    for start_s, end_s in ((0.04, 0.25), (0.30, 0.55), (0.60, 0.90)):
        seg = pcm[int(start_s * 44100) : int(end_s * 44100)].astype(np.float64)
        assert float(np.std(seg)) > 1500.0


def test_v2_multiple_consecutive_commands_consume_zero_ticks(tmp_path: Path) -> None:
    """Up to 4 consecutive PROGRAM_CHANGE commands execute in 0 ticks; final instrument wins immediately."""
    insts = [
        IRInstrument(id=0, name="Inst0", distortion=DISTORTION_PURE_TONE, envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=0)),
        IRInstrument(id=1, name="Inst1", distortion=DISTORTION_4BIT_POLY, envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=0)),
        IRInstrument(id=2, name="Inst2", distortion=DISTORTION_WHITE_NOISE, envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=0)),
        IRInstrument(id=3, name="Inst3", distortion=DISTORTION_5BIT_POLY_1, envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=0)),
    ]
    song = IRSong(
        title="4cmd0tick",
        frames_per_tick=3,
        instruments=insts,
        patterns=[
            IRPattern(
                id=0,
                rows=4,
                tracks={1: [IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=14, instrument_id=0)]},
            )
        ],
        sequence=[0],
    )

    def _patch_4_cmds(mpu, syms):
        addr = syms["song_data_pat_0_ch1"]
        payload = [
            0x00, 0x00, 0x01, 0x00,
            0x00, 0x00, 0x01, 0x01,
            0x00, 0x00, 0x01, 0x02,
            0x00, 0x00, 0x01, 0x03,
            71, 4, 14,
            0xFF,
        ]
        for off, b in enumerate(payload):
            mpu.memory[addr + off] = b

    frames_py65, syms, cycles, mpu = _compile_and_run_py65(
        song, tmp_path, "multi_cmd", 12, patch_fn=_patch_4_cmds
    )
    frames_oracle = frame_simulator.simulate_v2_binary_frames(mpu.memory, syms["song_data"], 12)
    assert np.array_equal(frames_py65, frames_oracle)
    # Final PROGRAM_CHANGE -> Inst3 (DISTORTION_5BIT_POLY_1 = 0x20) is active on frame 0 with 0 tick delay
    assert int(frames_py65[0, 1]) & 0xE0 == DISTORTION_5BIT_POLY_1
    assert (int(frames_py65[0, 1]) & 0x0F) == 14
    assert max(cycles) < 10000


def test_v1_backward_compatibility_py65_and_asap_parity(tmp_path: Path) -> None:
    """Verify legacy Composer v4 / default format_version=1 songs play identically under player v2 & ASAP."""
    from atari_music.api import generate_music

    song = generate_music("action", seed=42).pokey_ir
    data_asm = tmp_path / "legacy_v1_data.asm"
    export_mads_asm(song, data_asm, song_label="song_data")  # default format_version=1

    frames_py65, syms, v1_cycles, mpu = _compile_and_run_py65(
        song, tmp_path, "v1_compat", 96, format_version=1
    )
    frames_bin = frame_simulator.simulate_v2_binary_frames(mpu.memory, syms["song_data"], 96)
    frames_ir = frame_simulator.simulate_ir_song_frames(song, 96, format_version=1)
    assert np.array_equal(frames_py65, frames_bin)
    assert np.array_equal(frames_py65, frames_ir)
    assert max(v1_cycles) < 3500

    if ASAPCONV.is_file():
        sap_asm = tmp_path / "v1_sap.asm"
        sap_xex = tmp_path / "v1_sap.xex"
        sap_file = tmp_path / "v1_sap.sap"
        wav_file = tmp_path / "v1_sap.wav"
        sap_asm.write_text(
            f"""
    org $2000
    jmp sap_init
    jmp music_update
sap_init:
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    rts
    icl '{PLAYER_ASM.as_posix()}'
    icl '{data_asm.as_posix()}'
""",
            encoding="utf-8",
        )
        subprocess.run([str(MADS), str(sap_asm), f"-o:{sap_xex}"], check=True, capture_output=True)
        sap_file.write_bytes(b"SAP\r\nTYPE B\r\nINIT 2000\r\nPLAYER 2003\r\nTIME 00:01.00\r\n\r\n" + sap_xex.read_bytes())
        subprocess.run([str(ASAPCONV), "-o", str(wav_file), str(sap_file)], check=True, capture_output=True)
        with wave.open(str(wav_file), "rb") as wf:
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert float(np.std(pcm.astype(np.float64))) > 1500.0

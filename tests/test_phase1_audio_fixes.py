"""Phase 1 regression tests: ADSR envelope state machine & POKEY channel muting.

Covers Section 2C requirements across both the Python reference model
(``pokey_hw.player_envelope_volumes``) and real MADS-assembled 6502 machine code
executed via ``py65`` while observing every write to ``$D200-$D208``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pytest

from atari_music import ir, pokey_hw
from atari_music.constants import (
    DISTORTION_4BIT_POLY,
    DISTORTION_5_AND_4BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.ir import IREnvelope, IRInstrument, IRNote, IRPattern, IRSong
from atari_music.mads_exporter import export_mads_asm

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"
PLAYER_ASM = REPO_ROOT / "player.asm"
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
    """Parse MADS ``-t`` label table (``00\\tXXXX\\tNAME`` or ``XXXX\\tNAME``)."""
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


def _assemble_and_boot(song: IRSong, tmp_path: Path, name: str):
    """Export *song* to MADS ASM, compile with ``player.asm``, and load into ``py65``."""
    pytest.importorskip("py65")
    from conftest import require_local_artifact
    from py65.devices.mpu6502 import MPU

    require_local_artifact(MADS)

    data_asm = tmp_path / f"{name}_data.asm"
    export_mads_asm(song, data_asm, song_label="song_data")

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
    assert proc.returncode == 0, f"MADS failed: {proc.stderr or proc.stdout}"
    symbols = _parse_mads_labels(lab_path)

    mpu = MPU()
    _load_xex_into(mpu, xex_path.read_bytes())
    mpu.memory[RETURN_TRAP] = 0x00

    def call(addr: int, x: int = 0, y: int = 0) -> List[Tuple[int, int]]:
        writes: List[Tuple[int, int]] = []
        ret = RETURN_TRAP - 1
        mpu.memory[0x01FF] = (ret >> 8) & 0xFF
        mpu.memory[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = addr
        mpu.x = x
        mpu.y = y
        guard = 0
        while mpu.pc != RETURN_TRAP:
            if mpu.memory[mpu.pc] == 0x8D:  # STA abs
                target = mpu.memory[mpu.pc + 1] | (mpu.memory[mpu.pc + 2] << 8)
                if 0xD200 <= target <= 0xD208:
                    writes.append((target, mpu.a))
            mpu.step()
            guard += 1
            assert guard < 200_000, "6502 subroutine did not return"
        return writes

    call(symbols["start"])
    return mpu, symbols, call


def _step_frames(
    mpu,
    symbols: Dict[str, int],
    call,
    n_frames: int,
    mute_schedule: Optional[Dict[int, Sequence[int]]] = None,
) -> List[Dict[int, int]]:
    """Run *n_frames* calls to ``music_update``, applying optional ``ch_mute_mask`` changes."""
    mute_base = symbols["ch_mute_mask"]
    update_addr = symbols["music_update"]
    trace: List[Dict[int, int]] = []
    for frame_idx in range(n_frames):
        if mute_schedule and frame_idx in mute_schedule:
            mask = mute_schedule[frame_idx]
            for ch in range(4):
                mpu.memory[mute_base + ch] = mask[ch]
        writes = call(update_addr)
        regs = {addr: val for addr, val in writes}
        for reg in range(0xD200, 0xD209):
            assert reg in regs, f"frame {frame_idx} missed write to ${reg:04X}"
        trace.append(regs)
    return trace


def _single_note_song(
    *,
    attack: int = 0,
    decay: int = 0,
    sustain: int = 10,
    release: int = 0,
    peak_vol: int = 15,
    duration_ticks: int = 16,
    frames_per_tick: int = 4,
    distortion: int = DISTORTION_PURE_TONE,
    midi: int = 69,
    channel: int = 1,
) -> IRSong:
    bpm = max(40, round(60 * 50 / (frames_per_tick * 4)))
    note = IRNote(
        midi_pitch=midi,
        pitch=ir.midi_to_note_name(midi),
        duration=duration_ticks,
        volume=peak_vol,
        instrument_id=0,
    )
    inst = IRInstrument(
        id=0,
        name="TestInst",
        distortion=distortion,
        role="melody",
        envelope=IREnvelope(
            attack_frames=attack,
            decay_frames=decay,
            sustain_vol=sustain,
            release_frames=release,
        ),
    )
    return IRSong(
        title="phase1 test",
        author="pytest",
        tempo_bpm=bpm,
        frames_per_tick=frames_per_tick,
        instruments=[inst],
        patterns=[IRPattern(id=1, name="P1", rows=duration_ticks, tracks={channel: [note]})],
        sequence=[1],
        uses_16bit_bass=False,
    )


def _four_channel_song(
    *,
    note_ticks: int = 4,
    repeats: int = 4,
    frames_per_tick: int = 4,
    uses_16bit_bass: bool = False,
) -> IRSong:
    instruments = [
        IRInstrument(
            id=0,
            name="Bass",
            distortion=DISTORTION_PURE_TONE if uses_16bit_bass else DISTORTION_4BIT_POLY,
            role="bass",
            is_16bit=uses_16bit_bass,
            envelope=IREnvelope(attack_frames=1, decay_frames=3, sustain_vol=10, release_frames=2),
        ),
        IRInstrument(
            id=1,
            name="Harm",
            distortion=DISTORTION_5_AND_4BIT,
            role="harmony",
            envelope=IREnvelope(attack_frames=2, decay_frames=4, sustain_vol=9, release_frames=2),
        ),
        IRInstrument(
            id=2,
            name="Lead",
            distortion=DISTORTION_PURE_TONE,
            role="melody",
            envelope=IREnvelope(attack_frames=3, decay_frames=4, sustain_vol=11, release_frames=3),
        ),
        IRInstrument(
            id=3,
            name="Perc",
            distortion=DISTORTION_WHITE_NOISE,
            role="percussion",
            envelope=IREnvelope(attack_frames=0, decay_frames=3, sustain_vol=8, release_frames=2),
        ),
    ]
    total_rows = note_ticks * repeats
    ch1 = [
        IRNote(midi_pitch=45 + (i % 2) * 3, pitch="A-2", duration=note_ticks, volume=14, instrument_id=0, channel_role="bass")
        for i in range(repeats)
    ]
    ch3 = [
        IRNote(midi_pitch=69 + (i % 3) * 2, pitch="A-4", duration=note_ticks, volume=15, instrument_id=2, channel_role="melody")
        for i in range(repeats)
    ]
    ch4 = [
        IRNote(midi_pitch=None, pitch=None, duration=note_ticks, volume=13, instrument_id=3, channel_role="percussion")
        for _ in range(repeats)
    ]
    tracks = {1: ch1, 3: ch3, 4: ch4}
    if not uses_16bit_bass:
        tracks[2] = [
            IRNote(midi_pitch=60 + (i % 2) * 4, pitch="C-4", duration=note_ticks, volume=12, instrument_id=1, channel_role="harmony")
            for i in range(repeats)
        ]
    return IRSong(
        title="4ch mute test",
        author="pytest",
        tempo_bpm=188,
        frames_per_tick=frames_per_tick,
        instruments=instruments,
        patterns=[IRPattern(id=1, name="P1", rows=total_rows, tracks=tracks)],
        sequence=[1],
        uses_16bit_bass=uses_16bit_bass,
    )


# ===========================================================================
# 1. ADSR Envelope Phases, Smooth Transitions & Edge Cases
# ===========================================================================


class TestAdsrPhases:
    def test_all_four_adsr_phases_and_transitions_python_model(self) -> None:
        # 24 frames (6 ticks x 4 frames/tick):
        # Attack=4 -> [3, 7, 11, 15]
        # Decay=4 to sustain=7 -> [13, 11, 9] then Sustain=7 starting frame 7
        # Release=3 on last 3 frames (21, 22, 23) -> [6, 5, 4]
        vols = pokey_hw.player_envelope_volumes(24, 4, 15, attack=4, decay=4, sustain=7, release=3)
        assert len(vols) == 24
        assert vols[0:4] == [3, 7, 11, 15]
        assert vols[4:7] == [13, 11, 9]
        assert vols[7:21] == [7] * 14
        assert vols[21:24] == [6, 5, 4]
        assert all(0 <= v <= 15 for v in vols)

    def test_attack_is_monotone_multi_step_without_zero_drop(self) -> None:
        for peak in (1, 5, 10, 15):
            for att in (1, 2, 3, 5, 8, 15):
                vols = pokey_hw.player_envelope_volumes(32, 4, peak, attack=att, decay=0, sustain=peak, release=0)
                att_slice = vols[:att]
                assert att_slice == sorted(att_slice), (peak, att, att_slice)
                assert min(att_slice) >= 1, (peak, att, att_slice)
                assert att_slice[-1] == peak, (peak, att, att_slice)
                if att >= 3 and peak >= 4:
                    assert len(set(att_slice)) >= 3, (peak, att, att_slice)

    def test_decay_has_true_downward_slope_to_sustain(self) -> None:
        vols = pokey_hw.player_envelope_volumes(20, 4, 15, attack=0, decay=6, sustain=3, release=0)
        decay_slice = vols[:7]  # frame 0 = 15, frames 1..5 ramp down, frame 6 = 3
        assert decay_slice == [15, 13, 11, 9, 7, 5, 3]
        assert decay_slice == sorted(decay_slice, reverse=True)
        assert vols[6:] == [3] * 14

    def test_release_timing_uses_vbi_frames_across_all_frames_per_tick(self) -> None:
        # Total note duration = 24 VBI frames regardless of frames_per_tick (1, 3, 4, 6)
        for fpt in (1, 3, 4, 6):
            vols = pokey_hw.player_envelope_volumes(24, fpt, 15, attack=0, decay=0, sustain=10, release=4)
            assert vols[0] == 15
            assert vols[1:20] == [10] * 19
            assert vols[20:24] == [9, 8, 7, 6]

    def test_min_max_and_clamped_sustain_never_jump_up_or_underflow(self) -> None:
        # Peak=0 -> silent
        assert pokey_hw.player_envelope_volumes(8, 4, 0, 5, 5, 10, 3) == [0] * 8
        # Peak < Sustain: effective sustain must clamp to peak (never jump from 6 up to 14!)
        vols_clamped = pokey_hw.player_envelope_volumes(16, 4, 6, attack=2, decay=4, sustain=14, release=2)
        assert max(vols_clamped) == 6
        assert vols_clamped == [3, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 4]
        # Release longer than sustain level fades cleanly to 0 without negative / wrap
        vols_rel_zero = pokey_hw.player_envelope_volumes(20, 4, 15, attack=0, decay=0, sustain=4, release=8)
        assert vols_rel_zero[-8:] == [3, 2, 1, 0, 0, 0, 0, 0]
        assert all(0 <= v <= 15 for v in vols_rel_zero)
        # Max ADSR parameters (15, 15, 15, 15) on sustain=0
        vols_max = pokey_hw.player_envelope_volumes(48, 4, 15, attack=15, decay=15, sustain=0, release=15)
        assert vols_max[0] == 1
        assert vols_max[14] == 15
        assert vols_max[29] == 0
        assert all(0 <= v <= 15 for v in vols_max)

    def test_short_and_long_notes_behave_cleanly(self) -> None:
        # 1-frame ultra-short note
        assert pokey_hw.player_envelope_volumes(1, 1, 15, 0, 0, 10, 2) == [15]
        # 2-frame short note with att=0, dec=0, rel=2 -> peak then release step
        assert pokey_hw.player_envelope_volumes(2, 1, 15, 0, 0, 10, 2) == [15, 9]
        # 300-frame long note (> 255 VBI frames): steady sustain until last 5 frames
        vols_long = pokey_hw.player_envelope_volumes(300, 5, 15, 2, 4, 9, 5)
        assert len(vols_long) == 300
        assert vols_long[0:2] == [7, 15]
        assert vols_long[6:295] == [9] * 289
        assert vols_long[295:] == [8, 7, 6, 5, 4]


# ===========================================================================
# 2. 6502 Emulation Parity: Player Assembly vs Python Reference Model
# ===========================================================================


@pytest.mark.parametrize(
    "att,dec,sus,rel,peak,ticks,fpt,dist",
    [
        (4, 4, 7, 3, 15, 6, 4, DISTORTION_PURE_TONE),      # Full A->D->S->R
        (3, 6, 4, 4, 15, 8, 4, DISTORTION_5_AND_4BIT),     # Multi-step slopes
        (0, 0, 10, 2, 15, 2, 4, DISTORTION_PURE_TONE),     # Fixed VBI Release (not tick-based)
        (0, 1, 12, 1, 15, 1, 2, DISTORTION_PURE_TONE),     # Very short 2-frame note
        (15, 15, 5, 15, 15, 12, 5, DISTORTION_4BIT_POLY),      # Max 15/15 ADSR params
        (2, 4, 14, 2, 6, 4, 4, DISTORTION_PURE_TONE),      # peak_vol (6) < sustain_vol (14) clamp
        (15, 0, 1, 0, 1, 5, 4, DISTORTION_PURE_TONE),      # min peak_vol = 1 with long attack
        (3, 4, 9, 5, 15, 60, 5, DISTORTION_PURE_TONE),     # Long 300-frame (>255) note!
        (0, 0, 0, 0, 15, 4, 3, DISTORTION_WHITE_NOISE),    # Zero parameters -> peak then 0
    ],
)
def test_6502_player_adsr_matches_model_bit_for_bit(
    tmp_path: Path, att: int, dec: int, sus: int, rel: int, peak: int, ticks: int, fpt: int, dist: int
) -> None:
    song = _single_note_song(
        attack=att,
        decay=dec,
        sustain=sus,
        release=rel,
        peak_vol=peak,
        duration_ticks=ticks,
        frames_per_tick=fpt,
        distortion=dist,
    )
    mpu, symbols, call = _assemble_and_boot(song, tmp_path, f"adsr_{att}_{dec}_{sus}_{rel}_{peak}_{ticks}_{fpt}")
    total_frames = ticks * fpt
    trace = _step_frames(mpu, symbols, call, total_frames)

    actual_vols = [regs[0xD201] & 0x0F for regs in trace]
    expected_vols = pokey_hw.player_envelope_volumes(total_frames, fpt, peak, att, dec, sus, rel)
    assert actual_vols == expected_vols, (
        f"6502 vs Python mismatch for att={att}, dec={dec}, sus={sus}, rel={rel}, peak={peak}, ticks={ticks}, fpt={fpt}\n"
        f"6502  ={actual_vols}\nPython={expected_vols}"
    )
    # Whenever volume > 0, AUDC high nibble must carry exact distortion; when volume == 0, AUDC == $00
    for frame_idx, regs in enumerate(trace):
        audc1 = regs[0xD201]
        if (audc1 & 0x0F) == 0:
            assert audc1 == 0x00, f"silent frame {frame_idx} wrote non-zero AUDC1=${audc1:02X}"
        else:
            assert (audc1 & 0xE0) == dist, f"frame {frame_idx} distortion mismatch: ${audc1:02X}"


# ===========================================================================
# 3. POKEY Channel Muting (ch_mute_mask -> AUDC = $00) & Unmute Recovery
# ===========================================================================


class TestChannelMuting6502:
    AUDC_ADDRS = (0xD201, 0xD203, 0xD205, 0xD207)

    @pytest.mark.parametrize("muted_ch", [0, 1, 2, 3])
    def test_single_channel_mute_writes_zero_and_spares_others(self, tmp_path: Path, muted_ch: int) -> None:
        song = _four_channel_song(note_ticks=4, repeats=2, frames_per_tick=4, uses_16bit_bass=False)
        n_frames = 4 * 2 * 4

        mpu_ref, sym_ref, call_ref = _assemble_and_boot(song, tmp_path, f"ref_ch{muted_ch}")
        ref_trace = _step_frames(mpu_ref, sym_ref, call_ref, n_frames)

        mask = [1 if i == muted_ch else 0 for i in range(4)]
        mpu_m, sym_m, call_m = _assemble_and_boot(song, tmp_path, f"mute_ch{muted_ch}")
        mute_trace = _step_frames(mpu_m, sym_m, call_m, n_frames, mute_schedule={0: mask})

        # Baseline sanity: channel was actually audible when unmuted
        audc_addr = self.AUDC_ADDRS[muted_ch]
        assert any(r[audc_addr] != 0 for r in ref_trace)

        for frame_idx, (r_ref, r_m) in enumerate(zip(ref_trace, mute_trace)):
            for ch in range(4):
                c_addr = self.AUDC_ADDRS[ch]
                if ch == muted_ch:
                    assert r_m[c_addr] == 0x00, (
                        f"frame {frame_idx}: muted ch{ch+1} wrote AUDC=${r_m[c_addr]:02X} instead of $00"
                    )
                else:
                    assert r_m[c_addr] == r_ref[c_addr], (
                        f"frame {frame_idx}: muting ch{muted_ch+1} altered unmuted ch{ch+1} "
                        f"(${r_m[c_addr]:02X} != ${r_ref[c_addr]:02X})"
                    )

    @pytest.mark.parametrize(
        "mask",
        [
            (1, 0, 1, 0),
            (0, 1, 0, 1),
            (1, 1, 1, 0),
            (1, 1, 1, 1),
            (0x80, 0xFF, 0x02, 0x00),  # non-1 truthy mask bytes must ALSO write $00, not mask value!
        ],
    )
    def test_multi_channel_and_arbitrary_mask_writes_exact_zero(self, tmp_path: Path, mask: Tuple[int, ...]) -> None:
        song = _four_channel_song(note_ticks=4, repeats=2, frames_per_tick=4, uses_16bit_bass=False)
        n_frames = 4 * 2 * 4

        mpu_ref, sym_ref, call_ref = _assemble_and_boot(song, tmp_path, "multi_ref")
        ref_trace = _step_frames(mpu_ref, sym_ref, call_ref, n_frames)

        mpu_m, sym_m, call_m = _assemble_and_boot(song, tmp_path, "multi_mute")
        mute_trace = _step_frames(mpu_m, sym_m, call_m, n_frames, mute_schedule={0: mask})

        for frame_idx, (r_ref, r_m) in enumerate(zip(ref_trace, mute_trace)):
            for ch in range(4):
                c_addr = self.AUDC_ADDRS[ch]
                if mask[ch] != 0:
                    assert r_m[c_addr] == 0x00, f"frame {frame_idx} ch{ch+1}: wrote ${r_m[c_addr]:02X}"
                else:
                    assert r_m[c_addr] == r_ref[c_addr], f"frame {frame_idx} ch{ch+1}: altered"

    def test_unmute_restores_playback_mid_note_and_across_note_transitions(self, tmp_path: Path) -> None:
        song = _four_channel_song(note_ticks=4, repeats=4, frames_per_tick=4, uses_16bit_bass=False)
        n_frames = 4 * 4 * 4  # 64 frames = 4 consecutive notes per channel

        mpu_ref, sym_ref, call_ref = _assemble_and_boot(song, tmp_path, "unmute_ref")
        ref_trace = _step_frames(mpu_ref, sym_ref, call_ref, n_frames)

        # Mute CH3 (lead) on frame 6 (mid note 1), keep muted across note 2 boundary (frame 16..31),
        # then unmute mid note 3 (frame 36) and check clean reactivation through note 4 (frames 48..63)
        schedule = {
            6: (0, 0, 1, 0),
            36: (0, 0, 0, 0),
        }
        mpu_m, sym_m, call_m = _assemble_and_boot(song, tmp_path, "unmute_test")
        mute_trace = _step_frames(mpu_m, sym_m, call_m, n_frames, mute_schedule=schedule)

        # Frames 0..5: unmuted, identical to reference
        for f in range(0, 6):
            assert mute_trace[f][0xD205] == ref_trace[f][0xD205]
            assert mute_trace[f][0xD205] != 0x00

        # Frames 6..35: muted across note boundary at frame 16 and 32 -> strictly $00 every frame
        for f in range(6, 36):
            assert mute_trace[f][0xD205] == 0x00, f"frame {f}: expected $00 while muted"

        # Frames 36..63: unmuted -> exact match with unmuted reference, including note 4 onset at frame 48!
        assert any(mute_trace[f][0xD205] != 0x00 for f in range(36, 48))
        for f in range(36, n_frames):
            assert mute_trace[f][0xD205] == ref_trace[f][0xD205], f"frame {f}: failed to restore AUDC3"
            assert mute_trace[f][0xD204] == ref_trace[f][0xD204], f"frame {f}: AUDF3 mismatch after unmute"

        # Channels 1, 2, 4 were never affected at any point
        for f in range(n_frames):
            for c_addr in (0xD201, 0xD203, 0xD207):
                assert mute_trace[f][c_addr] == ref_trace[f][c_addr]

    def test_16bit_bass_mode_muting_and_unmuting(self, tmp_path: Path) -> None:
        song = _four_channel_song(note_ticks=4, repeats=2, frames_per_tick=4, uses_16bit_bass=True)
        n_frames = 32

        mpu_ref, sym_ref, call_ref = _assemble_and_boot(song, tmp_path, "bass16_ref")
        ref_trace = _step_frames(mpu_ref, sym_ref, call_ref, n_frames)
        assert any(r[0xD203] != 0x00 for r in ref_trace)

        schedule = {
            4: (1, 0, 0, 0),   # mute CH1 (low byte of 16-bit bass) -> silences AUDC2 too
            12: (0, 0, 0, 0),  # unmute
            16: (0, 1, 0, 0),  # mute CH2 (high byte) -> silences AUDC2
            24: (0, 0, 0, 0),  # unmute
        }
        mpu_m, sym_m, call_m = _assemble_and_boot(song, tmp_path, "bass16_mute")
        mute_trace = _step_frames(mpu_m, sym_m, call_m, n_frames, mute_schedule=schedule)

        for f in range(n_frames):
            assert mute_trace[f][0xD201] == 0x00  # AUDC1 always $00 in 16-bit join
            if 4 <= f < 12 or 16 <= f < 24:
                assert mute_trace[f][0xD203] == 0x00, f"frame {f}: muted 16-bit bass wrote ${mute_trace[f][0xD203]:02X}"
            else:
                assert mute_trace[f][0xD203] == ref_trace[f][0xD203], f"frame {f}: 16-bit bass did not restore"
            # CH3 & CH4 untouched
            assert mute_trace[f][0xD205] == ref_trace[f][0xD205]
            assert mute_trace[f][0xD207] == ref_trace[f][0xD207]

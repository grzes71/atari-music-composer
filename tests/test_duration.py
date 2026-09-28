"""Unit and Regression Tests for Ground-Truth Duration Calculation and Invariants (Etap 15.1)."""

from pathlib import Path
import pytest

from atari_music.ai.analysis import (
    calculate_bpm_frames_per_tick,
    calculate_composition_duration,
    calculate_loop_duration,
    verify_duration_invariant,
)
from atari_music.ai.schema import (
    AICompositionDoc,
    AICompositionMetadata,
    AIHardwareConfig,
    AIInstrumentDef,
    AIPatternChannelEvent,
    AIPatternDef,
)


def _make_composition(
    patterns_def: list[tuple[str, int]],  # (pattern_id, length_steps)
    sequence: list[str],
    bpm: int = 120,
    declared_duration: float | None = None,
    loop_point: int = 0,
    use_16bit_bass: bool = False,
    include_rests: bool = False,
) -> AICompositionDoc:
    """Helper to build a valid AICompositionDoc with precise structural parameters."""
    insts = [
        AIInstrumentDef(id="lead", name="Lead", character="bright_lead"),
        AIInstrumentDef(id="bass", name="Bass", character="bass"),
    ]

    pats = []
    for pat_id, length in patterns_def:
        channels_dict = {
            "1": [
                AIPatternChannelEvent(
                    step=0,
                    note="C4",
                    instrument="lead",
                    duration=min(4, length),
                    volume=14,
                ),
            ],
            "2": [],
            "3": [
                AIPatternChannelEvent(
                    step=0,
                    note="C2",
                    instrument="bass",
                    duration=min(8, length),
                    volume=12,
                ),
            ],
            "4": [],
        }
        if include_rests:
            channels_dict["1"].append(
                AIPatternChannelEvent(
                    step=min(4, length - 1),
                    note="REST",
                    instrument="lead",
                    duration=1,
                    volume=0,
                )
            )
        pats.append(AIPatternDef(id=pat_id, length_steps=length, channels=channels_dict))

    return AICompositionDoc(
        metadata=AICompositionMetadata(
            title="Duration Test Piece",
            bpm=bpm,
            key="C",
            mode="minor",
            duration_seconds=declared_duration,
        ),
        hardware=AIHardwareConfig(
            channels=4,
            use_16bit_bass=use_16bit_bass,
        ),
        instruments=insts,
        patterns=pats,
        sequence=sequence,
        loop_point=loop_point,
    )


def test_short_pattern_correct_duration():
    """1. Single short pattern (16 steps) at 120 BPM: 4 frames/tick = 80 ms per step.
    16 steps * 0.08 s = 1.28 s.
    """
    doc = _make_composition(patterns_def=[("A", 16)], sequence=["A"], bpm=120)
    dur = calculate_composition_duration(doc)
    assert dur == pytest.approx(1.28, abs=0.01)


def test_two_patterns_correct_duration():
    """2. Two distinct patterns (16 and 32 steps) played sequentially:
    (16 + 32) steps * 0.08 s = 3.84 s.
    """
    doc = _make_composition(
        patterns_def=[("A", 16), ("B", 32)],
        sequence=["A", "B"],
        bpm=120,
    )
    dur = calculate_composition_duration(doc)
    assert dur == pytest.approx(3.84, abs=0.01)


def test_sequence_with_repetition():
    """3. Sequence with multiple repetitions: A(16) -> B(32) -> A(16) -> A(16) -> B(32).
    Total steps = 16 + 32 + 16 + 16 + 32 = 112 steps.
    112 * 0.08 s = 8.96 s.
    """
    doc = _make_composition(
        patterns_def=[("A", 16), ("B", 32)],
        sequence=["A", "B", "A", "A", "B"],
        bpm=120,
    )
    dur = calculate_composition_duration(doc)
    assert dur == pytest.approx(8.96, abs=0.01)


def test_different_bpms_timing_divisors():
    """4. BPM quantizes to exact 50 Hz VBLANK frames_per_tick:
    - 75 BPM  -> 6 frames/tick (120 ms/step)
    - 95 BPM  -> 5 frames/tick (100 ms/step)
    - 130 BPM -> 4 frames/tick (80 ms/step)
    - 160 BPM -> 3 frames/tick (60 ms/step)
    """
    assert calculate_bpm_frames_per_tick(75) == 6
    assert calculate_bpm_frames_per_tick(95) == 5
    assert calculate_bpm_frames_per_tick(130) == 4
    assert calculate_bpm_frames_per_tick(160) == 3

    # Test 32 steps across different BPMs
    doc_slow = _make_composition([("A", 32)], ["A"], bpm=75)
    assert calculate_composition_duration(doc_slow) == pytest.approx(32 * 6 / 50.0)  # 3.84s

    doc_mid = _make_composition([("A", 32)], ["A"], bpm=95)
    assert calculate_composition_duration(doc_mid) == pytest.approx(32 * 5 / 50.0)  # 3.20s

    doc_norm = _make_composition([("A", 32)], ["A"], bpm=130)
    assert calculate_composition_duration(doc_norm) == pytest.approx(32 * 4 / 50.0)  # 2.56s

    doc_fast = _make_composition([("A", 32)], ["A"], bpm=160)
    assert calculate_composition_duration(doc_fast) == pytest.approx(32 * 3 / 50.0)  # 1.92s


def test_loop_point_duration():
    """5. Loop duration isolates the repeating tail of the sequence from intro."""
    # Sequence: Intro(16) -> A(32) -> B(32) with loop_point = 1 (loop starts at A)
    doc = _make_composition(
        patterns_def=[("Intro", 16), ("A", 32), ("B", 32)],
        sequence=["Intro", "A", "B"],
        bpm=120,
        loop_point=1,
    )
    full_dur = calculate_composition_duration(doc)
    loop_dur = calculate_loop_duration(doc)

    assert full_dur == pytest.approx((16 + 32 + 32) * 0.08)  # 6.40s
    assert loop_dur == pytest.approx((32 + 32) * 0.08)        # 5.12s


def test_rests_do_not_alter_runtime_duration():
    """6. Rests inside channels do not affect song duration (time advances step by step)."""
    doc_without_rests = _make_composition([("A", 32)], ["A"], bpm=120, include_rests=False)
    doc_with_rests = _make_composition([("A", 32)], ["A"], bpm=120, include_rests=True)

    dur1 = calculate_composition_duration(doc_without_rests)
    dur2 = calculate_composition_duration(doc_with_rests)
    assert dur1 == dur2 == pytest.approx(2.56)


def test_multi_channel_duration_consistency():
    """7. All 4 channels advance synchronously in lockstep per pattern length."""
    doc = _make_composition(
        patterns_def=[("A", 32)],
        sequence=["A", "A"],
        bpm=120,
    )
    dur = calculate_composition_duration(doc)
    assert dur == pytest.approx(64 * 0.08)


def test_16bit_bass_hardware_mode_duration():
    """8. 16-bit bass mode retains identical PAL 50 Hz frame timing."""
    doc_16 = _make_composition(
        patterns_def=[("A", 32)],
        sequence=["A", "A"],
        bpm=100,  # 5 frames/tick (100 ms/step)
        use_16bit_bass=True,
    )
    dur = calculate_composition_duration(doc_16)
    assert dur == pytest.approx(64 * 5 / 50.0)  # 6.40s


def test_duration_metadata_mismatch_detection():
    """9. Invariant detects significant discrepancy between declared and actual runtime."""
    # Actual duration: 16 steps at 120 BPM = 1.28 s
    # Declared duration: 90.0 s (massive mismatch)
    doc_mismatch = _make_composition(
        patterns_def=[("A", 16)],
        sequence=["A"],
        bpm=120,
        declared_duration=90.0,
    )
    res = verify_duration_invariant(doc_mismatch, min_seconds=1.0, max_seconds=10.0)
    assert res["matches_declared"] is False
    assert res["status"] == "FAIL"
    assert res["difference_percent"] > 90.0


def test_composition_in_range_60_to_120_seconds():
    """10. Full-length composition in 60..120s range passes verification."""
    # 35 repetitions of 32-step patterns at 120 BPM (4 frames/tick = 0.08s)
    # 35 * 32 = 1120 steps. 1120 * 0.08s = 89.60 seconds!
    seq = ["A" if i % 2 == 0 else "B" for i in range(35)]
    doc = _make_composition(
        patterns_def=[("A", 32), ("B", 32)],
        sequence=seq,
        bpm=120,
        declared_duration=89.6,
    )
    dur = calculate_composition_duration(doc)
    assert dur == pytest.approx(89.6, abs=0.05)

    res = verify_duration_invariant(doc, min_seconds=60.0, max_seconds=120.0)
    assert res["in_target_range"] is True
    assert res["matches_declared"] is True
    assert res["status"] == "PASS"


def test_composition_below_60_seconds_fails_range():
    """11. Actual runtime duration below 60 seconds fails the full-length criterion."""
    # 10 repetitions of 32-step patterns = 320 steps * 0.08s = 25.60 seconds
    seq = ["A"] * 10
    doc = _make_composition(
        patterns_def=[("A", 32)],
        sequence=seq,
        bpm=120,
        declared_duration=25.6,
    )
    dur = calculate_composition_duration(doc)
    assert dur < 60.0

    res = verify_duration_invariant(doc, min_seconds=60.0, max_seconds=120.0)
    assert res["in_target_range"] is False
    assert res["status"] == "FAIL"


def test_composition_above_120_seconds_fails_range():
    """12. Actual runtime duration above 120 seconds fails the full-length criterion."""
    # 55 repetitions of 32-step patterns = 1760 steps * 0.08s = 140.80 seconds
    seq = ["A"] * 55
    doc = _make_composition(
        patterns_def=[("A", 32)],
        sequence=seq,
        bpm=120,
        declared_duration=140.8,
    )
    dur = calculate_composition_duration(doc)
    assert dur > 120.0

    res = verify_duration_invariant(doc, min_seconds=60.0, max_seconds=120.0)
    assert res["in_target_range"] is False
    assert res["status"] == "FAIL"


def test_6502_player_multi_pattern_sequence_advance_regression(tmp_path):
    """13. Regression test: 6502 player advances patterns without clobbering X or truncating."""
    pytest.importorskip("py65")
    from pathlib import Path
    from conftest import require_local_artifact

    require_local_artifact(Path("tools/mads/mads.exe"))
    from py65.devices.mpu6502 import MPU
    from atari_music.ai.client import build_xex_from_composition

    # 3 patterns in sequence: A, B, A
    doc = _make_composition(
        patterns_def=[("A", 16), ("B", 16)],
        sequence=["A", "B", "A"],
        bpm=120,
    )
    xex_out = tmp_path / "seq_test.xex"
    build_xex_from_composition(doc, output_path=xex_out)
    assert xex_out.exists()

    # Load into py65
    raw_data = xex_out.read_bytes()
    mpu = MPU()
    idx = 0
    while idx < len(raw_data):
        if raw_data[idx:idx+2] == b"\xff\xff":
            idx += 2
        if idx >= len(raw_data):
            break
        start = raw_data[idx] | (raw_data[idx+1] << 8)
        end = raw_data[idx+2] | (raw_data[idx+3] << 8)
        idx += 4
        size = end - start + 1
        for i, b in enumerate(raw_data[idx:idx+size]):
            mpu.memory[start + i] = b
        idx += size

    # Emulate boot
    RETURN_TRAP = 0x0200
    mpu.memory[RETURN_TRAP] = 0x00

    def call_sub(addr, x=0, y=0):
        mpu.sp = 0xFF
        ret = RETURN_TRAP - 1
        mpu.memory[0x01FF] = (ret >> 8) & 0xFF
        mpu.memory[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = addr
        mpu.x = x
        mpu.y = y
        while mpu.pc != RETURN_TRAP:
            mpu.step()

    init_addr = mpu.memory[0x4012] | (mpu.memory[0x4013] << 8)
    play_addr = mpu.memory[0x4015] | (mpu.memory[0x4016] << 8)
    song_data = mpu.memory[0x400E] | (mpu.memory[0x4010] << 8)
    # Find update_addr dynamically from harness main_loop JSR music_update
    update_addr = None
    for p in range(0x4000, 0x4100):
        if mpu.memory[p] == 0x49 and mpu.memory[p+1] == 0x01:  # eor #1 (ch_mute_mask toggle)
            jsr_addr = p + 5  # follows sta ch_mute_mask,x
            update_addr = mpu.memory[jsr_addr+1] | (mpu.memory[jsr_addr+2] << 8)
            break
    assert update_addr is not None

    # Find seq_step_idx address via load_pattern_ptrs STA
    seq_idx_addr = None
    for p in range(0x4000, 0x4800):
        if mpu.memory[p] == 0x18 and mpu.memory[p+1] == 0xAD and mpu.memory[p+4] == 0x6D:
            seq_idx_addr = mpu.memory[p+5] | (mpu.memory[p+6] << 8)
            break
    assert seq_idx_addr is not None

    call_sub(init_addr, song_data & 0xFF, (song_data >> 8) & 0xFF)
    call_sub(play_addr)

    # 16 steps at 4 frames/tick = 64 frames per pattern
    steps_observed = set()
    for f in range(200):  # covers steps 0, 1, 2
        call_sub(update_addr)
        steps_observed.add(mpu.memory[seq_idx_addr])

    # Must have transitioned from step 0 (idx 0) to step 1 (idx 2) and step 2 (idx 4)
    assert 0 in steps_observed
    assert 2 in steps_observed
    assert 4 in steps_observed


def test_xex_harness_graphical_timer_display(tmp_path):
    """14. Verifies graphical timer and layout metadata is generated in XEX harness."""
    from pathlib import Path
    from conftest import require_local_artifact
    from atari_music.ai.client import build_xex_from_composition

    require_local_artifact(Path("tools/mads/mads.exe"))

    doc = _make_composition(
        patterns_def=[("P1", 32)],
        sequence=["P1"] * 3,
        bpm=120,
    )
    doc.metadata.title = "Timer Test Song"

    xex_out = tmp_path / "timer_test.xex"
    build_xex_from_composition(doc, output_path=xex_out)
    assert xex_out.exists()
    asm_out = tmp_path / "timer_test.asm"
    assert asm_out.exists()

    asm_text = asm_out.read_text(encoding="utf-8")
    assert "init_screen_layout:" in asm_text
    assert "update_screen_ui:" in asm_text
    assert "ui_timer_frames:" in asm_text
    assert "lbl_time:" in asm_text
    assert "lbl_step:" in asm_text


def test_xex_harness_channel_mute_and_colors(tmp_path: Path):
    """Verify XEX harness includes channel muting via keys 1-4 and dark green background/border ($C4)."""
    from conftest import require_local_artifact
    from atari_music.ai.client import build_xex_from_composition
    require_local_artifact(Path("tools/mads/mads.exe"))

    doc = _make_composition(
        patterns_def=[("P1", 16)],
        sequence=["P1"],
        bpm=120,
    )
    doc.metadata.title = "Mute Test"

    xex_out = tmp_path / "mute_test.xex"
    build_xex_from_composition(doc, output_path=xex_out)
    assert xex_out.exists()
    assert xex_out.stat().st_size > 0

    asm_out = tmp_path / "mute_test.asm"
    asm_text = asm_out.read_text(encoding="utf-8")

    # Dark green background and border ($C4)
    assert "lda #$C4" in asm_text
    assert "sta $02C6" in asm_text  # COLOR2 text background
    assert "sta $02C8" in asm_text  # COLOR4 border
    assert "sta $D018" in asm_text  # COLPF2 immediate
    assert "sta $D01A" in asm_text  # COLBK immediate

    # Channel muting via keys 1-4
    assert "key_table:" in asm_text
    assert "cmp key_table,x" in asm_text
    assert ".byte $1E, $1D, $19, $18" in asm_text  # Keys '1', '2', '3', '4'
    assert "ch_mute_mask" in asm_text


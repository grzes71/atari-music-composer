"""CORE tests for Etap C IR v2 models, binary size math, and MADS Exporter v2 validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atari_music import composer_v4, pokey_hw
from atari_music.constants import (
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_5BIT_POLY_1,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.instruments import load_instrument_catalog
from atari_music.ir import (
    MAX_V2_INSTRUMENTS,
    IREnvelope,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRPattern,
    IRPitchEnvelope,
    IRSong,
    calculate_ir_binary_size,
    resolve_initial_channel_instruments,
    song_requires_v2,
)
from atari_music.mads_exporter import (
    SONG_FORMAT_VERSION,
    SONG_FORMAT_VERSION_2,
    FormatVersionError,
    ModulationNotExpressibleError,
    StreamValidationError,
    VolumeContourNotExpressibleError,
    export_mads_asm,
    validate_v2_track_bytes,
)

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[1]
MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"


def _assemble_payload_size(asm_text: str, tmp_path: Path, name: str) -> int:
    if not MADS.is_file():
        pytest.skip("tools/mads/mads.exe not present")
    src = tmp_path / f"{name}.asm"
    xex = tmp_path / f"{name}.xex"
    src.write_text("    org $4000\n" + asm_text, encoding="utf-8")
    proc = subprocess.run(
        [str(MADS), str(src), f"-o:{xex}"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    raw = xex.read_bytes()
    # Subtract 6-byte Atari DOS XEX segment header ($FF $FF start_lo start_hi end_lo end_hi)
    return len(raw) - 6


def _sample_v2_song(num_instruments: int = 4) -> IRSong:
    insts = []
    for i in range(num_instruments):
        macro = None
        pe = None
        if i == 0:
            macro = [
                IRMacroStep(frames_per_step=1, audc_dist=DISTORTION_5BIT_POLY_1, audf_offset=-2, vol_override=15)
            ]
        elif i == 1:
            pe = IRPitchEnvelope(start_audf_delta=-18, duration_frames=3, step_delta=6)
        elif i == 2:
            macro = [
                IRMacroStep(frames_per_step=1, audc_dist=DISTORTION_4BIT_POLY, audf_mode="fixed", fixed_audf=28, vol_override=15),
                IRMacroStep(frames_per_step=2, audc_dist=DISTORTION_PURE_TONE, audf_mode="fixed", fixed_audf=88, vol_override=9),
            ]
        insts.append(
            IRInstrument(
                id=i,
                name=f"Inst{i}",
                distortion=DISTORTION_PURE_TONE,
                envelope=IREnvelope(attack_frames=0, decay_frames=2, sustain_vol=10, release_frames=1),
                macro=macro,
                pitch_envelope=pe,
            )
        )
    pat0 = IRPattern(
        id=0,
        name="Pat0",
        rows=8,
        tracks={
            1: [IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=14, instrument_id=0),
                IRNote(pitch="C-5", midi_pitch=72, duration=4, volume=13, instrument_id=1)],
            2: [IRNote(pitch="E-4", midi_pitch=64, duration=8, volume=12, instrument_id=min(1, num_instruments - 1))],
            3: [IRNote(pitch="A-3", midi_pitch=57, duration=8, volume=11, instrument_id=min(2, num_instruments - 1))],
            4: [IRNote(duration=8, volume=15, instrument_id=min(2, num_instruments - 1), channel_role="percussion")],
        },
    )
    return IRSong(
        title="StageC V2",
        frames_per_tick=4,
        instruments=insts,
        patterns=[pat0],
        sequence=[0],
        initial_channel_instruments={1: 0, 2: min(1, num_instruments - 1), 3: min(2, num_instruments - 1), 4: min(2, num_instruments - 1)},
    )


def test_ir_v2_catalog_conversion_and_max_32_instruments(tmp_path: Path) -> None:
    cat = load_instrument_catalog()
    prof_kick, beh_kick = cat.resolve_profile_behavior("perc_kick_tight")
    ir_kick = IRInstrument.from_catalog_profile(0, prof_kick, beh_kick)
    assert ir_kick.profile_id == "perc_kick_tight"
    assert ir_kick.behavior_id == "beh_perc_kick"
    assert ir_kick.macro is not None and len(ir_kick.macro) == 5
    assert ir_kick.pitch_envelope is not None and ir_kick.pitch_envelope.start_audf_delta == -24

    # Boundary: 32 instruments succeeds
    song_32 = _sample_v2_song(num_instruments=MAX_V2_INSTRUMENTS)
    asm_32 = export_mads_asm(song_32, format_version=SONG_FORMAT_VERSION_2)
    assert f"    .byte {MAX_V2_INSTRUMENTS:<4} ; instrument_count" in asm_32
    assert calculate_ir_binary_size(song_32, format_version=2) == _assemble_payload_size(asm_32, tmp_path, "v2_32")

    # 33 instruments rejected
    song_33 = _sample_v2_song(num_instruments=MAX_V2_INSTRUMENTS + 1)
    with pytest.raises(StreamValidationError, match="1..32 instruments"):
        export_mads_asm(song_33, format_version=2)

    # 0 instruments rejected in v2
    song_0 = _sample_v2_song(num_instruments=1).model_copy(update={"instruments": [], "initial_channel_instruments": None})
    with pytest.raises(StreamValidationError, match="1..32 instruments"):
        export_mads_asm(song_0, format_version=2)


def test_calculate_ir_binary_size_exact_parity_for_v1_and_v2(tmp_path: Path) -> None:
    # v1 song from Composer v4
    res = composer_v4.compose_song_v4(seed=42)
    v1_song = res.pokey_ir
    v1_asm = export_mads_asm(v1_song, format_version=1)
    assert calculate_ir_binary_size(v1_song, format_version=1) == _assemble_payload_size(v1_asm, tmp_path, "v1_exact")

    # Multi-pattern v2 song with deduplicated macro pool, PROGRAM_CHANGE, and pitch envelope
    s_v2 = _sample_v2_song(num_instruments=6)
    p1 = IRPattern(
        id=1,
        name="Pat1",
        rows=4,
        tracks={
            1: [IRNote(pitch="G-4", midi_pitch=67, duration=4, volume=15, instrument_id=3)],
            4: [IRNote(is_rest=True, duration=4, volume=0, instrument_id=0)],
        },
    )
    s_v2_multi = s_v2.model_copy(update={"patterns": [s_v2.patterns[0], p1], "sequence": [0, 1, 0]})
    v2_asm = export_mads_asm(s_v2_multi, format_version=2)
    assert calculate_ir_binary_size(s_v2_multi, format_version=2) == _assemble_payload_size(v2_asm, tmp_path, "v2_exact")


def test_macro_1_to_8_steps_and_parameter_validation() -> None:
    # 1 step and 8 steps accepted
    for n_steps in (1, 8):
        steps = [
            IRMacroStep(frames_per_step=1, audc_dist=DISTORTION_PURE_TONE, audf_offset=i - 3, vol_override=15 - i)
            for i in range(n_steps)
        ]
        inst = IRInstrument(id=0, name=f"M{n_steps}", macro=steps)
        song = IRSong(
            title="m",
            instruments=[inst],
            patterns=[IRPattern(id=0, rows=4, tracks={1: [IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=15, instrument_id=0)]})],
            sequence=[0],
        )
        asm = export_mads_asm(song, format_version=2)
        assert f"    .byte {SONG_FORMAT_VERSION_2:<4} ; format version 2" in asm

    # 9 steps rejected
    too_many = [IRMacroStep(frames_per_step=1, audc_dist=DISTORTION_PURE_TONE) for _ in range(9)]
    song_9 = IRSong(
        title="m9",
        instruments=[IRInstrument(id=0, name="M9", macro=too_many)],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=15, instrument_id=0)]})],
        sequence=[0],
    )
    with pytest.raises(StreamValidationError, match="max 8"):
        export_mads_asm(song_9, format_version=2)

    # Bad audc_dist or audf_offset out of -127..127 rejected
    bad_step = IRMacroStep(frames_per_step=1, audc_dist=0x10)
    song_bad = IRSong(
        title="mb",
        instruments=[IRInstrument(id=0, name="MB", macro=[bad_step])],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=15, instrument_id=0)]})],
        sequence=[0],
    )
    with pytest.raises(StreamValidationError, match="invalid audc_dist"):
        export_mads_asm(song_bad, format_version=2)


def test_v2_stream_validator_guards_all_corruption_cases() -> None:
    # Valid stream: [0,0,1,2] (PROGRAM_CHANGE), [71,4,15], [$FF]
    validate_v2_track_bytes([0, 0, 1, 2, 71, 4, 15, 0xFF], instrument_count=4)

    # Empty / missing $FF / trailing byte
    with pytest.raises(StreamValidationError, match="empty"):
        validate_v2_track_bytes([], 4)
    with pytest.raises(StreamValidationError, match="end with \\$FF"):
        validate_v2_track_bytes([71, 4, 15], 4)
    with pytest.raises(StreamValidationError, match="trailing bytes"):
        validate_v2_track_bytes([71, 4, 15, 0xFF, 0x00, 0xFF], 4)

    # Truncated command or note before $FF
    with pytest.raises(StreamValidationError, match="truncated"):
        validate_v2_track_bytes([0, 0, 1, 0xFF], 4)
    with pytest.raises(StreamValidationError, match="truncated"):
        validate_v2_track_bytes([71, 4, 0xFF], 4)

    # Bad opcode, out-of-range instrument index
    with pytest.raises(StreamValidationError, match="opcode"):
        validate_v2_track_bytes([0, 0, 2, 0, 71, 4, 15, 0xFF], 4)
    with pytest.raises(StreamValidationError, match="out of bounds"):
        validate_v2_track_bytes([0, 0, 1, 4, 71, 4, 15, 0xFF], 4)

    # > 4 consecutive commands rejected
    with pytest.raises(StreamValidationError, match="consecutive commands"):
        validate_v2_track_bytes([0, 0, 1, 0] * 5 + [71, 4, 15, 0xFF], 4)

    # Command-only track with no note/rest before $FF rejected
    with pytest.raises(StreamValidationError, match="no note or rest"):
        validate_v2_track_bytes([0, 0, 1, 1, 0xFF], 4)

    # Bad DUR / VOL / mid-stream $FF terminator bounds
    with pytest.raises(StreamValidationError, match="trailing bytes"):
        validate_v2_track_bytes([0xFF, 4, 15, 0xFF], 4)
    with pytest.raises(StreamValidationError, match="invalid duration"):
        validate_v2_track_bytes([71, 0, 15, 0xFF], 4)
    with pytest.raises(StreamValidationError, match="invalid volume"):
        validate_v2_track_bytes([71, 4, 16, 0xFF], 4)


def test_v1_refuses_v2_songs_explicitly_and_default_export_stays_v1() -> None:
    s_v2 = _sample_v2_song(num_instruments=4)
    assert song_requires_v2(s_v2)

    # Default export (format_version=1) refuses v2 song loudly
    with pytest.raises(FormatVersionError, match="SONG_FORMAT_VERSION=1"):
        export_mads_asm(s_v2)

    # Plain v1 song still defaults to format version 1 and Composer v4 stays unchanged
    comp = composer_v4.compose_song_v4(seed=42)
    assert song_requires_v2(comp.pokey_ir) == []
    asm_v1 = export_mads_asm(comp.pokey_ir)
    assert f"    .byte {SONG_FORMAT_VERSION:<4} ; format version" in asm_v1

    # Deferred Iter-2 / unsupported features blocked explicitly in v2 Iter 1
    bad_vib = _sample_v2_song(1)
    bad_vib.instruments[0].vibrato_depth = 2
    with pytest.raises(StreamValidationError, match="vibrato"):
        export_mads_asm(bad_vib, format_version=2)

    bad_hpf = _sample_v2_song(1)
    bad_hpf.instruments[0].audctl = AUDCTL_HIPASS_CH1_CH3
    with pytest.raises(StreamValidationError, match="HPF XOR"):
        export_mads_asm(bad_hpf, format_version=2)

    bad_ch34 = _sample_v2_song(1)
    bad_ch34.instruments[0].audctl = AUDCTL_JOIN_3_4_16BIT
    with pytest.raises(StreamValidationError, match="16-bit CH3\\+CH4"):
        export_mads_asm(bad_ch34, format_version=2)

    bad_contour = _sample_v2_song(1)
    bad_contour.instruments[0].volume_contour = [15, 10, 5]
    with pytest.raises(VolumeContourNotExpressibleError):
        export_mads_asm(bad_contour, format_version=2)

    bad_c1_16 = IRSong(
        title="c1_16",
        uses_16bit_bass=True,
        instruments=[IRInstrument(id=0, name="B", audctl=AUDCTL_JOIN_1_2_16BIT, modulation=pokey_hw.MODULATION_OCTAVE_PULSE)],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [IRNote(pitch="A-2", midi_pitch=45, duration=4, volume=14, instrument_id=0)]})],
        sequence=[0],
    )
    with pytest.raises(ModulationNotExpressibleError):
        export_mads_asm(bad_c1_16, format_version=2)

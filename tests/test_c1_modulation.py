"""C1 (``c1_octave_pulse``) per-channel modulation: format, behaviour, and the real player.

Three layers of evidence, in increasing strength:

* the **format** — the version byte, the 6-byte instrument record, and the refusals;
* the **rule** — the WAV frame stream against an independently written expectation of the
  divider per frame, not against the code that produced it;
* the **player** — the machine code MADS assembled, executed on a 6502 emulator, its POKEY
  writes compared frame by frame with the WAV stream. py65 emulates the CPU only, so this
  establishes the register writes, not the audio.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pytest
from click.testing import CliRunner

from atari_music import ir, pokey_hw
from atari_music.ai.client import (
    generate_music_from_composition,
    load_composition_dsl,
)
from atari_music.cli import cli
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_5_AND_4BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.ir import IREnvelope, IRInstrument, IRNote, IRPattern, IRSong
from atari_music.mads_exporter import (
    SONG_FORMAT_VERSION,
    ModulationNotExpressibleError,
    export_mads_asm,
    find_unsupported_modulations,
    joined_channels,
)

pytestmark = [pytest.mark.core, pytest.mark.audio]

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYER_COPIES = (REPO_ROOT / "player.asm", REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm")
MADS = REPO_ROOT / "tools" / "mads" / "mads.exe"
REFERENCE_SONG = REPO_ROOT / "examples" / "songs" / "Vaults-of-Nhyrmeth.dsl"

FRAMES_PER_TICK = 4
runner = CliRunner()


def _one_note_song(
    midi: int = 69,
    rows: int = 8,
    modulation: int = pokey_hw.MODULATION_NONE,
    distortion: int = DISTORTION_PURE_TONE,
    channel: int = 1,
    volume: int = 15,
    is_rest: bool = False,
    uses_16bit_bass: bool = False,
) -> IRSong:
    """A song with exactly one note on one channel, so its frames are easy to reason about."""
    note = IRNote(
        midi_pitch=None if is_rest else midi,
        pitch=None if is_rest else ir.midi_to_note_name(midi),
        duration=rows,
        volume=0 if is_rest else volume,
        instrument_id=0,
        is_rest=is_rest,
    )
    instrument = IRInstrument(
        id=0,
        name="Voice",
        distortion=distortion,
        role="melody",
        envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=2),
        modulation=modulation,
    )
    return IRSong(
        title="c1 test",
        author="test",
        tempo_bpm=120,
        frames_per_tick=FRAMES_PER_TICK,
        instruments=[instrument],
        patterns=[IRPattern(id=1, name="A", rows=rows, tracks={channel: [note]})],
        sequence=[1],
        uses_16bit_bass=uses_16bit_bass,
    )


def _phrase_song(
    notes: Sequence[Tuple[int, int]],
    modulation: int = pokey_hw.MODULATION_OCTAVE_PULSE,
    channel: int = 1,
) -> IRSong:
    """``(midi, rows)`` per note on one channel; each note's onset resets the schedule."""
    events = [
        IRNote(
            midi_pitch=int(midi),
            pitch=ir.midi_to_note_name(int(midi)),
            duration=int(rows),
            volume=15,
            instrument_id=0,
        )
        for midi, rows in notes
    ]
    total = sum(rows for _midi, rows in notes)
    return IRSong(
        title="c1 phrase",
        author="test",
        tempo_bpm=120,
        frames_per_tick=FRAMES_PER_TICK,
        instruments=[IRInstrument(
            id=0, name="Voice", distortion=DISTORTION_5_AND_4BIT,
            envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=12, release_frames=2),
            modulation=modulation,
        )],
        patterns=[IRPattern(id=1, name="A", rows=total, tracks={channel: events})],
        sequence=[1],
    )


def _audf(song: IRSong, channel: int = 1) -> List[int]:
    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    return [int(v) for v in frames[:, ir.audf_column(channel)]]


def _audc(song: IRSong, channel: int = 1) -> List[int]:
    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    return [int(v) for v in frames[:, ir.audc_column(channel)]]


def _nominal_divider(midi: int) -> int:
    """The divider the compiler writes for a pitch, derived independently of the modulation."""
    freq = ir.midi_pitch_to_frequency(int(midi))
    return pokey_hw.clamp_audf_for_tracker(ir.frequency_to_audf_8bit(freq, audctl=0, channel=1))


def _instrument_section(asm: str) -> List[str]:
    """The emitted instrument table: the version byte followed by the four channel records."""
    lines = asm.splitlines()
    out: List[str] = []
    inside = False
    for line in lines:
        if "song_data_instruments:" in line:
            inside = True
            continue
        if inside:
            if line.strip() == "" or line.startswith("song_data_"):
                break
            out.append(line.strip())
    return out


# =============================================================================
# 1. Format: the version byte and the 6-byte instrument record
# =============================================================================


def test_the_export_declares_the_format_version_it_writes() -> None:
    asm = export_mads_asm(_one_note_song())
    section = _instrument_section(asm)
    assert len(section) == 5, section
    assert section[0].startswith(f".byte {SONG_FORMAT_VERSION}")
    assert SONG_FORMAT_VERSION == 1


def test_every_instrument_record_carries_six_bytes_and_a_modulation() -> None:
    asm = export_mads_asm(_one_note_song())
    records = _instrument_section(asm)[1:]
    assert len(records) == 4
    for record in records:
        payload = record.split(";")[0].replace(".byte", "")
        assert len([t for t in payload.split(",") if t.strip()]) == 6, record


def test_a_song_without_modulation_carries_zero_descriptors() -> None:
    song = _one_note_song()
    asm = export_mads_asm(song)
    records = _instrument_section(asm)[1:]
    assert all(record.rstrip().endswith("(no modulation)") for record in records), records
    assert all(re.search(r", \$00\s+;", record) for record in records), records


def test_the_note_event_record_is_still_three_bytes() -> None:
    """The modulation is per channel, so nothing per note changed."""
    asm = export_mads_asm(_one_note_song(modulation=pokey_hw.MODULATION_OCTAVE_PULSE))
    events = [line for line in asm.splitlines() if line.strip().startswith(".byte $")]
    note_events = [line for line in events if "rows)" in line]
    assert note_events, asm
    for line in note_events:
        payload = line.split(";")[0].replace(".byte", "")
        assert len([t for t in payload.split(",") if t.strip()]) == 3, line


def test_a_version_0_first_instrument_byte_can_never_look_like_a_version_byte() -> None:
    """The safety argument for putting the version where version 0 had a generator.

    Version 0's first instrument byte was always an AUDC generator, i.e. a multiple of ``$20``.
    ``$01`` is therefore a value no version-0 song can present, which is what lets the player
    detect the old layout instead of misreading it.
    """
    from atari_music.constants import DISTORTION_DESCRIPTIONS

    generators = set(DISTORTION_DESCRIPTIONS) | {0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0}
    assert SONG_FORMAT_VERSION not in generators
    assert all(value % 0x20 == 0 for value in generators)


def test_every_repository_song_has_a_generator_where_the_version_byte_now_sits() -> None:
    """Check the safety argument against real songs, not just the constant list."""
    import atari_music.ai.validation as validation

    allowed = {0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0}
    for dsl in sorted((REPO_ROOT / "examples").rglob("*.dsl")):
        composition = load_composition_dsl(dsl)
        result = generate_music_from_composition(composition)
        # The first instrument byte the version-0 exporter would have written is channel 1's
        # generator; every instrument the composer produces uses an allowed value.
        for inst in result.pokey_ir.instruments:
            assert inst.distortion in allowed, (dsl.name, inst.name, inst.distortion)
    assert SONG_FORMAT_VERSION not in allowed
    assert validation.INVALID_DISTORTION == "INVALID_DISTORTION"


# =============================================================================
# 2. Refusals the exporter makes
# =============================================================================


def test_an_undefined_descriptor_is_refused() -> None:
    song = _one_note_song(modulation=0x42)
    unsupported = find_unsupported_modulations(song)
    assert {item["reason"] for item in unsupported} == {"undefined_descriptor"}
    with pytest.raises(ModulationNotExpressibleError) as excinfo:
        export_mads_asm(song)
    assert excinfo.value.code == "MODULATION_NOT_EXPRESSIBLE_IN_XEX"
    assert "does not define that modulation descriptor" in str(excinfo.value)


def test_a_modulation_on_a_joined_16_bit_channel_is_refused() -> None:
    song = _one_note_song(
        midi=45, modulation=pokey_hw.MODULATION_OCTAVE_PULSE, uses_16bit_bass=True, channel=1
    )
    unsupported = find_unsupported_modulations(song)
    assert unsupported, "a joined pair must not accept a modulation"
    assert {item["reason"] for item in unsupported} == {"joined_16bit_pair"}
    with pytest.raises(ModulationNotExpressibleError):
        export_mads_asm(song)


def test_joined_channels_follow_the_audctl_bits() -> None:
    assert joined_channels(0x00) == ()
    assert joined_channels(AUDCTL_JOIN_1_2_16BIT) == (1, 2)
    assert joined_channels(0x08) == (3, 4)
    assert joined_channels(0x18) == (1, 2, 3, 4)


def test_an_unmodulated_song_is_never_refused() -> None:
    for bass in (False, True):
        assert find_unsupported_modulations(_one_note_song(uses_16bit_bass=bass)) == []
        assert export_mads_asm(_one_note_song(uses_16bit_bass=bass))


def test_the_channel_of_a_refusal_is_a_channel_not_an_instrument_index() -> None:
    """The instrument list's position is not a channel number.

    A song whose *second* instrument is the modulated one, sounding on channel 3, must be
    accepted: reading the instrument's list index as a channel would wrongly refuse it.
    """
    notes = [IRNote(midi_pitch=60, pitch="C-4", duration=4, volume=15, instrument_id=1)]
    song = IRSong(
        title="t", frames_per_tick=FRAMES_PER_TICK,
        instruments=[
            IRInstrument(id=0, name="Bass", distortion=0xC0),
            IRInstrument(id=1, name="Lead", distortion=DISTORTION_5_AND_4BIT,
                         modulation=pokey_hw.MODULATION_OCTAVE_PULSE),
        ],
        patterns=[IRPattern(id=1, rows=4, tracks={3: notes})],
        sequence=[1],
    )
    assert find_unsupported_modulations(song) == []
    assert export_mads_asm(song)


# =============================================================================
# 3. The rule: the WAV frame stream against an independent expectation
# =============================================================================


def test_the_divider_alternates_n_and_half_n_every_frame() -> None:
    midi, rows = 69, 8
    song = _one_note_song(midi=midi, rows=rows, modulation=pokey_hw.MODULATION_OCTAVE_PULSE)
    nominal = _nominal_divider(midi)
    expected = [
        nominal if offset % 2 == 0 else nominal // 2
        for offset in range(rows * FRAMES_PER_TICK)
    ]
    assert _audf(song) == expected


def test_the_first_frame_of_a_note_carries_the_nominal_divider() -> None:
    """The phase claim the 6502 and Python must share."""
    song = _phrase_song([(69, 2), (72, 2), (76, 4)])
    audf = _audf(song)
    for start, midi in ((0, 69), (2 * FRAMES_PER_TICK, 72), (4 * FRAMES_PER_TICK, 76)):
        assert audf[start] == _nominal_divider(midi), (start, midi)


def test_the_phase_restarts_at_every_note_onset() -> None:
    """Two notes at the *same* pitch must each start on N; a free-running phase would not."""
    song = _phrase_song([(69, 2), (69, 2), (69, 2)])
    audf = _audf(song)
    span = 2 * FRAMES_PER_TICK
    nominal = _nominal_divider(69)
    for note_index in range(3):
        start = note_index * span
        expected = [nominal if o % 2 == 0 else nominal // 2 for o in range(span)]
        assert audf[start:start + span] == expected, note_index


def test_a_silent_frame_keeps_the_nominal_divider() -> None:
    """Experiment 28's ``apply_c1`` never writes a register the baseline did not write.

    The release ramp reaches zero before the note ends, and those frames must keep the note's
    nominal divider rather than keep alternating.
    """
    note = IRNote(midi_pitch=69, pitch="A-4", duration=4, volume=15, instrument_id=0)
    song = IRSong(
        title="silent tail",
        frames_per_tick=FRAMES_PER_TICK,
        instruments=[IRInstrument(
            id=0, name="Voice", distortion=DISTORTION_5_AND_4BIT,
            envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=3,
                                release_frames=5),
            modulation=pokey_hw.MODULATION_OCTAVE_PULSE,
        )],
        patterns=[IRPattern(id=1, rows=4, tracks={1: [note]})],
        sequence=[1],
    )
    audf = _audf(song)
    audc = _audc(song)
    nominal = _nominal_divider(69)

    silent = [i for i, value in enumerate(audc) if (value & 0x0F) == 0]
    assert silent, f"the release ramp should reach silence before the note ends: {audc}"
    for i in silent:
        assert audf[i] == nominal, (i, audf)

    # ...and the alternation was really running before the fade, so the check is not vacuous
    audible = [i for i, value in enumerate(audc) if (value & 0x0F) != 0]
    assert len({audf[i] for i in audible}) == 2, audf


def test_a_rest_never_carries_a_divider() -> None:
    song = _one_note_song(rows=4, is_rest=True, modulation=pokey_hw.MODULATION_OCTAVE_PULSE)
    assert set(_audf(song)) == {0}
    assert set(_audc(song)) == {0}


@pytest.mark.parametrize("nominal", [0, 1, 2, 3, 4, 5, 0xFE])
def test_the_octave_value_is_exact_integer_halving_at_the_boundaries(nominal: int) -> None:
    for offset in range(8):
        expected = nominal if offset % 2 == 0 else nominal // 2
        assert pokey_hw.octave_pulse_divider(nominal, offset) == expected
        assert 0 <= expected <= pokey_hw.AUDF_TRACKER_MAX


def test_the_octave_of_a_real_pitch_is_integer_halving() -> None:
    """The octave is ``N // 2`` for every N the tracker can carry, never a rounding rule."""
    for midi in range(24, 108):
        nominal = _nominal_divider(midi)
        assert pokey_hw.octave_pulse_divider(nominal, 1) == nominal // 2
        assert pokey_hw.octave_pulse_divider(nominal, 0) == nominal


def test_short_and_long_notes_both_alternate() -> None:
    for rows in (1, 2, 3, 5, 20):
        song = _one_note_song(midi=69, rows=rows, modulation=pokey_hw.MODULATION_OCTAVE_PULSE)
        nominal = _nominal_divider(69)
        expected = [
            nominal if offset % 2 == 0 else nominal // 2
            for offset in range(rows * FRAMES_PER_TICK)
        ]
        assert _audf(song) == expected, rows


def test_frames_per_tick_one_still_alternates_once_per_frame() -> None:
    """The schedule is per frame, not per row: a 1-frame tick must not skip a step."""
    song = _one_note_song(midi=69, rows=6, modulation=pokey_hw.MODULATION_OCTAVE_PULSE)
    song = song.model_copy(update={"frames_per_tick": 1})
    nominal = _nominal_divider(69)
    assert _audf(song) == [nominal if i % 2 == 0 else nominal // 2 for i in range(6)]


def test_modulation_does_not_touch_audc_or_the_envelope() -> None:
    plain = _one_note_song(midi=69, rows=6)
    modulated = _one_note_song(midi=69, rows=6, modulation=pokey_hw.MODULATION_OCTAVE_PULSE)
    assert _audc(plain) == _audc(modulated)
    frames_plain = np.asarray(ir.compile_ir_to_pokey_frames(plain))
    frames_mod = np.asarray(ir.compile_ir_to_pokey_frames(modulated))
    differing = {
        i for i in range(frames_plain.shape[1])
        if not np.array_equal(frames_plain[:, i], frames_mod[:, i])
    }
    assert differing == {ir.audf_column(1)}


def test_modulation_does_not_touch_audctl() -> None:
    for bass in (False, True):
        plain = _one_note_song(midi=45, rows=4, uses_16bit_bass=bass)
        modulated = _one_note_song(
            midi=45, rows=4, uses_16bit_bass=bass, channel=3,
            modulation=pokey_hw.MODULATION_OCTAVE_PULSE,
        )
        f0 = np.asarray(ir.compile_ir_to_pokey_frames(plain))
        f1 = np.asarray(ir.compile_ir_to_pokey_frames(modulated))
        assert np.array_equal(f0[:, 8], f1[:, 8])


def test_other_channels_are_untouched() -> None:
    """A modulated channel changes its own AUDF column and nothing else."""
    notes_a = [IRNote(midi_pitch=69, pitch="A-4", duration=4, volume=15, instrument_id=0)]
    notes_b = [IRNote(midi_pitch=45, pitch="A-2", duration=4, volume=12, instrument_id=1)]

    def build(mod: int) -> IRSong:
        return IRSong(
            title="t", frames_per_tick=FRAMES_PER_TICK,
            instruments=[
                IRInstrument(id=0, name="Lead", distortion=DISTORTION_5_AND_4BIT, modulation=mod),
                IRInstrument(id=1, name="Harm", distortion=DISTORTION_PURE_TONE),
            ],
            patterns=[IRPattern(id=1, rows=4, tracks={1: notes_a, 2: notes_b})],
            sequence=[1],
        )

    plain = np.asarray(ir.compile_ir_to_pokey_frames(build(pokey_hw.MODULATION_NONE)))
    modulated = np.asarray(ir.compile_ir_to_pokey_frames(
        build(pokey_hw.MODULATION_OCTAVE_PULSE)
    ))
    for column in (2, 3, 4, 5, 6, 7, 8):
        assert np.array_equal(plain[:, column], modulated[:, column]), column


def test_percussion_is_untouched_when_nothing_is_modulated() -> None:
    hit = IRNote(midi_pitch=None, pitch=None, duration=2, volume=15, instrument_id=0,
                 channel_role="percussion")
    song = IRSong(
        title="t", frames_per_tick=FRAMES_PER_TICK,
        instruments=[IRInstrument(id=0, name="Perc", distortion=DISTORTION_WHITE_NOISE,
                                  role="percussion")],
        patterns=[IRPattern(id=1, rows=2, tracks={4: [hit]})],
        sequence=[1],
    )
    assert set(_audf(song, channel=4)) == {pokey_hw.PERCUSSION_DEFAULT_AUDF}


def test_percussion_is_modulated_only_if_its_own_instrument_asks() -> None:
    """C1 on a percussion channel is legal at register level, and the rule is applied to it.

    Nothing in the CLI offers this (C1 is a lead instrument and its library entry records
    channel 3), but the renderer must not special-case it into silence.
    """
    hit = IRNote(midi_pitch=None, pitch=None, duration=2, volume=15, instrument_id=0,
                 channel_role="percussion")
    song = IRSong(
        title="t", frames_per_tick=FRAMES_PER_TICK,
        instruments=[IRInstrument(id=0, name="Perc", distortion=DISTORTION_WHITE_NOISE,
                                  role="percussion",
                                  modulation=pokey_hw.MODULATION_OCTAVE_PULSE)],
        patterns=[IRPattern(id=1, rows=2, tracks={4: [hit]})],
        sequence=[1],
    )
    nominal = pokey_hw.PERCUSSION_DEFAULT_AUDF
    assert _audf(song, channel=4) == [
        nominal if i % 2 == 0 else nominal // 2 for i in range(2 * FRAMES_PER_TICK)
    ]


def test_the_16_bit_pair_is_untouched_by_an_unmodulated_song() -> None:
    song = _one_note_song(midi=45, rows=4, uses_16bit_bass=True)
    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    assert frames[:, 1].tolist() == [0] * frames.shape[0]      # AUDC1 muted
    assert len(set(frames[:, 0].tolist())) == 1                # AUDF1 constant
    assert len(set(frames[:, 2].tolist())) == 1                # AUDF2 constant


# =============================================================================
# 4. The real player: MADS output executed on a 6502
# =============================================================================
#
# py65 emulates the CPU, not POKEY, so these tests establish the *register writes* the machine
# code makes -- which is exactly what "does the XEX play what the WAV renders" reduces to here.
# They say nothing about the audio.

_RUNTIME_DSL = """TITLE "c1 runtime"
AUTHOR "test"
KEY A
MODE MINOR
BPM 120

SEQUENCE A

INSTRUMENT lead character=bright_lead
INSTRUMENT harm character=soft_pad

[PATTERN A length=8]
CH1 lead V15
A4/2 C5/2 E5/4

CH2 harm V10
E3/8
"""

_RETURN_TRAP = 0x0200


def _require_runtime_tools() -> None:
    pytest.importorskip("py65")
    from conftest import require_local_artifact

    require_local_artifact(MADS)


def _build_xex(dsl_text: str, tmp_path: Path, name: str, extra: Sequence[str] = ()) -> Path:
    dsl = tmp_path / f"{name}.dsl"
    dsl.write_text(dsl_text, encoding="utf-8")
    out = tmp_path / f"{name}.xex"
    result = runner.invoke(cli, [
        "build-xex", str(dsl), "--format", "dsl", "--mads", str(MADS),
        "--output", str(out), *extra,
    ])
    assert result.exit_code == 0, result.output
    return out


def _load_xex_into(mpu, data: bytes) -> None:
    idx = 0
    while idx < len(data):
        if data[idx:idx + 2] == b"\xff\xff":
            idx += 2
        if idx >= len(data):
            break
        start = data[idx] | (data[idx + 1] << 8)
        end = data[idx + 2] | (data[idx + 3] << 8)
        idx += 4
        size = end - start + 1
        for i, byte in enumerate(data[idx:idx + size]):
            mpu.memory[start + i] = byte
        idx += size


def _run_player(xex: Path, frames: int, version_patch: Optional[int] = None):
    """Execute ``music_update`` *frames* times; return (AUDF, AUDC) per frame, 4 channels each.

    The entry points are located structurally rather than by fixed address, so the test does
    not depend on where the harness places the player.
    """
    from py65.devices.mpu6502 import MPU

    mpu = MPU()
    _load_xex_into(mpu, xex.read_bytes())
    mpu.memory[_RETURN_TRAP] = 0x00

    def call(addr: int, x: int = 0, y: int = 0) -> None:
        ret = _RETURN_TRAP - 1
        mpu.memory[0x01FF] = (ret >> 8) & 0xFF
        mpu.memory[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = addr
        mpu.x = x
        mpu.y = y
        guard = 0
        while mpu.pc != _RETURN_TRAP:
            mpu.step()
            guard += 1
            assert guard < 200_000, "call did not terminate"

    # ``ldx #<song_data / ldy #>song_data / jsr music_init / jsr music_play``
    init_addr = play_addr = song_data = None
    for p in range(0x2000, 0xC000):
        if (mpu.memory[p] == 0xA2 and mpu.memory[p + 2] == 0xA0
                and mpu.memory[p + 4] == 0x20 and mpu.memory[p + 7] == 0x20):
            song_data = mpu.memory[p + 1] | (mpu.memory[p + 3] << 8)
            init_addr = mpu.memory[p + 5] | (mpu.memory[p + 6] << 8)
            play_addr = mpu.memory[p + 8] | (mpu.memory[p + 9] << 8)
            break
    assert init_addr is not None, "could not locate music_init/music_play"

    # ``lda ch_mute_mask,x / eor #1 / sta ch_mute_mask,x / jsr music_update``
    update_addr = None
    for p in range(0x2000, 0xC000):
        if (mpu.memory[p] == 0x49 and mpu.memory[p + 1] == 0x01
                and mpu.memory[p + 2] == 0x9D and mpu.memory[p + 5] == 0x20):
            update_addr = mpu.memory[p + 6] | (mpu.memory[p + 7] << 8)
            break
    assert update_addr is not None, "could not locate music_update"

    if version_patch is not None:
        # Overwrite the format version byte the exporter wrote, to simulate old data.
        instruments_ptr = mpu.memory[song_data + 2] | (mpu.memory[song_data + 3] << 8)
        mpu.memory[instruments_ptr] = version_patch

    call(init_addr, song_data & 0xFF, (song_data >> 8) & 0xFF)
    call(play_addr)

    audf_frames: List[List[Optional[int]]] = []
    audc_frames: List[List[Optional[int]]] = []
    for _ in range(frames):
        audf: List[Optional[int]] = [None] * 4
        audc: List[Optional[int]] = [None] * 4
        ret = _RETURN_TRAP - 1
        mpu.memory[0x01FF] = (ret >> 8) & 0xFF
        mpu.memory[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = update_addr
        guard = 0
        while mpu.pc != _RETURN_TRAP:
            if mpu.memory[mpu.pc] == 0x8D:                       # sta abs
                addr = mpu.memory[mpu.pc + 1] | (mpu.memory[mpu.pc + 2] << 8)
                if 0xD200 <= addr <= 0xD207:
                    channel = (addr - 0xD200) // 2
                    if addr % 2 == 0:
                        audf[channel] = mpu.a
                    else:
                        audc[channel] = mpu.a
            mpu.step()
            guard += 1
            assert guard < 200_000, "frame did not terminate"
        audf_frames.append(audf)
        audc_frames.append(audc)
    return audf_frames, audc_frames


def _bound_ir(dsl_path: Path, assignment: Optional[str]):
    """The IR the CLI itself would build for this composition and ``--instrument`` value."""
    from atari_music.cli import _apply_selections, _parse_instrument_assignments

    composition = load_composition_dsl(dsl_path)
    base = generate_music_from_composition(composition)
    assignments = _parse_instrument_assignments((assignment,)) if assignment else ()
    return _apply_selections(base, composition, None, None, assignments, None).pokey_ir


def test_the_real_player_writes_the_same_divider_sequence_as_the_renderer(tmp_path: Path) -> None:
    """The XEX and the WAV must agree frame by frame, or C1 is a different sound in each.

    The expectation is the WAV frame stream -- what ``import-dsl --output-wav`` would render --
    and the subject is the machine code MADS assembled, executed on a 6502.
    """
    _require_runtime_tools()
    xex = _build_xex(_RUNTIME_DSL, tmp_path, "c1", ["--instrument", "lead=c1_octave_pulse"])
    song = _bound_ir(tmp_path / "c1.dsl", "lead=c1_octave_pulse")
    assert song.instruments[0].modulation == pokey_hw.MODULATION_OCTAVE_PULSE

    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    audf_frames, audc_frames = _run_player(xex, frames.shape[0])

    player_audf = [f[0] for f in audf_frames]
    wav_audf = [int(v) for v in frames[:, ir.audf_column(1)]]
    assert player_audf == wav_audf
    assert [f[0] for f in audc_frames] == [int(v) for v in frames[:, ir.audc_column(1)]]

    # The equality must not be trivially "both constant".
    assert len(set(player_audf)) >= 4, player_audf
    nominal = _nominal_divider(69)
    assert player_audf[0] == nominal
    assert player_audf[1] == nominal // 2


def test_the_real_player_is_unchanged_without_a_modulation(tmp_path: Path) -> None:
    _require_runtime_tools()
    xex = _build_xex(_RUNTIME_DSL, tmp_path, "plain", [])
    song = _bound_ir(tmp_path / "plain.dsl", None)

    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    audf_frames, audc_frames = _run_player(xex, frames.shape[0])

    player_audf = [f[0] for f in audf_frames]
    assert player_audf == [int(v) for v in frames[:, ir.audf_column(1)]]
    assert [f[0] for f in audc_frames] == [int(v) for v in frames[:, ir.audc_column(1)]]
    # Only the notes' own dividers -- no halved value ever appears.
    assert set(player_audf) <= {_nominal_divider(m) for m in (69, 72, 76)}


def test_the_real_player_keeps_the_other_channels_out_of_it(tmp_path: Path) -> None:
    _require_runtime_tools()
    xex = _build_xex(_RUNTIME_DSL, tmp_path, "indep", ["--instrument", "lead=c1_octave_pulse"])
    song = _bound_ir(tmp_path / "indep.dsl", "lead=c1_octave_pulse")
    frames = np.asarray(ir.compile_ir_to_pokey_frames(song))
    audf_frames, _audc_frames = _run_player(xex, frames.shape[0])

    for channel in (2, 3, 4):
        player = [f[channel - 1] for f in audf_frames]
        assert player == [int(v) for v in frames[:, ir.audf_column(channel)]], channel


@pytest.mark.parametrize("version", [0, 2, 0xA0, 0xC0, 0xFF])
def test_the_real_player_refuses_a_format_version_it_does_not_know(
    tmp_path: Path, version: int
) -> None:
    """An unknown version must silence the player, not play a misread instrument table.

    ``$A0`` and ``$C0`` are what version 0's first instrument byte looks like in that position.
    """
    _require_runtime_tools()
    xex = _build_xex(_RUNTIME_DSL, tmp_path, f"ver{version:02x}", [])
    audf_frames, audc_frames = _run_player(xex, 8, version_patch=version)

    assert all(value is None for frame in audf_frames for value in frame), audf_frames
    assert all(value is None for frame in audc_frames for value in frame), audc_frames


def test_the_refusal_cannot_be_overridden_by_calling_play_afterwards(tmp_path: Path) -> None:
    """The harness calls ``music_init`` and then ``music_play``; the refusal must survive it."""
    _require_runtime_tools()
    xex = _build_xex(_RUNTIME_DSL, tmp_path, "ver_play", [])
    # _run_player always calls play; a version-0 patch must still produce no writes at all.
    audf_frames, _ = _run_player(xex, 4, version_patch=0)
    assert all(value is None for frame in audf_frames for value in frame)


# =============================================================================
# 5. The CLI: selecting C1, and everything that must not change
# =============================================================================

_SMALL_DSL = """TITLE "cli"
AUTHOR "test"
KEY C
MODE MINOR
BPM 120

SEQUENCE A

INSTRUMENT lead character=bright_lead
INSTRUMENT bass character=bass

[PATTERN A length=4]
CH1 lead V14
C4/4

CH3 bass V12
C2/4
"""

BANK_DIR = REPO_ROOT / "tests" / "data" / "sound_profiles" / "bank"


def _write_dsl(tmp_path: Path, name: str = "song.dsl") -> Path:
    path = tmp_path / name
    path.write_text(_SMALL_DSL, encoding="utf-8")
    return path


def test_the_library_entry_is_accepted_on_import_dsl(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output
    assert "c1_octave_pulse" in result.output


def test_the_library_entry_is_accepted_on_import_json(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    converted = tmp_path / "song.json"
    convert = runner.invoke(cli, ["import-dsl", str(dsl), "--output-json", str(converted)])
    assert convert.exit_code == 0, convert.output
    result = runner.invoke(cli, ["import-json", str(converted),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output


def test_the_library_entry_is_accepted_on_build_xex(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    result = runner.invoke(cli, ["build-xex", str(dsl), "--format", "dsl", "--mads", str(MADS),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output", str(tmp_path / "o.xex")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "o.xex").is_file()


def test_the_selected_entry_reaches_the_ir_as_a_descriptor_and_a_generator(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    ir_path = tmp_path / "o.ir.json"
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-ir", str(ir_path)])
    assert result.exit_code == 0, result.output

    document = json.loads(ir_path.read_text(encoding="utf-8"))
    lead = [i for i in document["instruments"] if i["name"] == "Lead"][0]
    bass = [i for i in document["instruments"] if i["name"] == "Bass"][0]
    assert lead["modulation"] == pokey_hw.MODULATION_OCTAVE_PULSE
    assert lead["distortion"] == DISTORTION_5_AND_4BIT      # $40, the library's own generator
    assert lead["profile_id"] is None, "no profile may be invented for C1"
    assert lead["profile_fingerprint"] is None
    assert bass["modulation"] == pokey_hw.MODULATION_NONE


def test_the_exported_data_carries_the_descriptor(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    asm = tmp_path / "o.asm"
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-asm", str(asm)])
    assert result.exit_code == 0, result.output
    records = _instrument_section(asm.read_text(encoding="utf-8"))[1:]
    assert records[0].startswith(".byte $40"), records[0]
    assert records[0].rstrip().endswith("(octave pulse (N / N//2 every frame))"), records[0]
    assert all(r.rstrip().endswith("(no modulation)") for r in records[1:]), records


def test_the_note_events_are_byte_identical_with_and_without_the_selection(tmp_path: Path) -> None:
    """The modulation is per channel, so nothing in the note stream may move."""
    dsl = _write_dsl(tmp_path)
    plain = tmp_path / "plain.asm"
    picked = tmp_path / "picked.asm"
    assert runner.invoke(cli, ["import-dsl", str(dsl), "--output-asm", str(plain)]).exit_code == 0
    assert runner.invoke(cli, ["import-dsl", str(dsl),
                               "--instrument", "lead=c1_octave_pulse",
                               "--output-asm", str(picked)]).exit_code == 0

    def events(path: Path) -> List[str]:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if "rows)" in line]

    assert events(plain) == events(picked)


def test_the_three_bank_instruments_are_unchanged(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    expected = {"pure_sustain": "pokey_ref_25f94201",
                "pure_pluck": "pokey_ref_9daa0429",
                "buzz_steady": "pokey_ref_2b83db43"}
    for instrument_id, profile_id in expected.items():
        ir_path = tmp_path / f"{instrument_id}.ir.json"
        result = runner.invoke(cli, ["import-dsl", str(dsl),
                                     "--instrument", f"lead={instrument_id}",
                                     "--output-ir", str(ir_path)])
        assert result.exit_code == 0, result.output
        lead = [i for i in json.loads(ir_path.read_text(encoding="utf-8"))["instruments"]
                if i["name"] == "Lead"][0]
        assert lead["profile_id"] == profile_id
        assert lead["modulation"] == pokey_hw.MODULATION_NONE
        assert lead["profile_fingerprint"]


def test_a_modulation_on_a_joined_16_bit_channel_is_refused_by_the_cli(tmp_path: Path) -> None:
    # The bass must be alone on channel 1 for the 1+2 join to own it.
    dsl = tmp_path / "bass16.dsl"
    dsl.write_text("""TITLE "bass16"
AUTHOR "test"
KEY C
MODE MINOR
BPM 120
BASS 16BIT

SEQUENCE A

INSTRUMENT lead character=bright_lead
INSTRUMENT bass character=bass

[PATTERN A length=4]
CH1 bass V12
C2/4

CH3 lead V14
C4/4
""", encoding="utf-8")
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--instrument", "bass=c1_octave_pulse",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 1
    assert "[INSTRUMENT_NOT_APPLICABLE]" in result.output
    assert "16-bit pair" in result.output
    assert not (tmp_path / "o.ir.json").exists()


def test_an_explicit_conflicting_generator_is_refused(tmp_path: Path) -> None:
    dsl = tmp_path / "conflict.dsl"
    dsl.write_text(_SMALL_DSL.replace("character=bright_lead", "character=bright_lead dist=$C0"),
                   encoding="utf-8")
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 1
    assert "[PROFILE_DISTORTION_CONFLICT]" in result.output


def test_a_profile_binding_and_a_modulation_on_one_part_conflict(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    binding = tmp_path / "b.json"
    binding.write_text(json.dumps({
        "schema": "atari-music/sound-profile-binding/1",
        "instruments": {"lead": "pokey_ref_25f94201"},
    }), encoding="utf-8")
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--profile-bindings", str(binding),
                                 "--sound-bank", str(BANK_DIR),
                                 "--instrument", "lead=c1_octave_pulse",
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 1
    assert "[INSTRUMENT_BINDING_CONFLICT]" in result.output


def test_a_profile_binding_alone_is_still_unchanged(tmp_path: Path) -> None:
    dsl = _write_dsl(tmp_path)
    binding = tmp_path / "b.json"
    binding.write_text(json.dumps({
        "schema": "atari-music/sound-profile-binding/1",
        "instruments": {"lead": "pokey_ref_25f94201"},
    }), encoding="utf-8")
    result = runner.invoke(cli, ["import-dsl", str(dsl),
                                 "--profile-bindings", str(binding),
                                 "--sound-bank", str(BANK_DIR),
                                 "--output-ir", str(tmp_path / "o.ir.json")])
    assert result.exit_code == 0, result.output
    lead = [i for i in json.loads((tmp_path / "o.ir.json").read_text(encoding="utf-8"))["instruments"]
            if i["name"] == "Lead"][0]
    assert lead["profile_id"] == "pokey_ref_25f94201"
    assert lead["modulation"] == pokey_hw.MODULATION_NONE


def test_a_library_entry_whose_schedule_the_player_lacks_is_refused() -> None:
    """Only the schedule this player implements may be accepted; nothing is approximated."""
    from atari_music.cli import _modulation_from_library_entry

    assert _modulation_from_library_entry({}) is None
    assert _modulation_from_library_entry({"identity": {"source": {"kind": "bank_profile"}}}) is None
    base = {"identity": {"source": {"kind": "experiment", "implementation": {
        "generator_byte": "$40",
        "schedule_parameters": {"hold_frames": 1, "active_frames": None, "active_notes": []},
    }}}}
    assert _modulation_from_library_entry(base) == (pokey_hw.MODULATION_OCTAVE_PULSE, 0x40)

    for mutation in ({"hold_frames": 4}, {"active_frames": 8}, {"active_notes": [0, 2]}):
        entry = json.loads(json.dumps(base))
        entry["identity"]["source"]["implementation"]["schedule_parameters"].update(mutation)
        assert _modulation_from_library_entry(entry) is None, mutation

    for bad_generator in ("$45", "$FF", "nonsense", 0x40):
        entry = json.loads(json.dumps(base))
        entry["identity"]["source"]["implementation"]["generator_byte"] = bad_generator
        assert _modulation_from_library_entry(entry) is None, bad_generator


def test_the_real_library_entry_is_the_one_this_classifier_accepts() -> None:
    from atari_music.cli import _modulation_from_library_entry

    document = json.loads(
        (REPO_ROOT / "data" / "instrument_libraries" / "lead" / "v0.1" / "library.json")
        .read_text(encoding="utf-8")
    )
    by_id = {entry["instrument_id"]: entry for entry in document["instruments"]}
    assert _modulation_from_library_entry(by_id["c1_octave_pulse"]) == (
        pokey_hw.MODULATION_OCTAVE_PULSE, DISTORTION_5_AND_4BIT
    )
    for bank_instrument in ("pure_sustain", "pure_pluck", "buzz_steady"):
        assert _modulation_from_library_entry(by_id[bank_instrument]) is None


# =============================================================================
# 6. The two player copies, and the shape of the change
# =============================================================================


def test_both_player_copies_exist_and_are_identical() -> None:
    for path in PLAYER_COPIES:
        assert path.is_file(), path
    digests = {hashlib.sha256(path.read_bytes()).hexdigest() for path in PLAYER_COPIES}
    assert len(digests) == 1, "the two player.asm copies have diverged"


def test_the_player_keeps_the_interface_the_harness_calls() -> None:
    text = PLAYER_COPIES[0].read_text(encoding="utf-8")
    for label in ("music_init", "music_play", "music_stop", "music_update", "music_is_playing"):
        assert f".proc {label}" in text, label
    assert ".proc apply_modulation" in text
    assert "SONG_FORMAT_VERSION = 1" in text


def test_the_modulation_runs_between_the_envelope_and_the_register_write() -> None:
    """Order matters: it must change ch_audf before write_pokey_registers publishes it."""
    text = PLAYER_COPIES[0].read_text(encoding="utf-8")
    update = text.split(".proc music_update", 1)[1].split(".endp", 1)[0]
    order = [update.index(name) for name in ("jsr update_envelopes", "jsr apply_modulation",
                                             "jsr write_pokey_registers")]
    assert order == sorted(order)


def test_the_modulation_state_is_per_channel() -> None:
    text = PLAYER_COPIES[0].read_text(encoding="utf-8")
    for array in ("ch_mod", "ch_mod_phase", "ch_audf_base"):
        declaration = [line for line in text.splitlines() if line.strip().startswith(f"{array} ")]
        assert declaration, array
        payload = declaration[0].split(";")[0].split(".byte", 1)[1]
        assert len([t for t in payload.split(",") if t.strip()]) == 4, declaration[0]


def test_the_player_never_uses_the_instrument_index_as_a_channel() -> None:
    """Guards the bug this implementation actually had: the pair check used the list index."""
    from atari_music.mads_exporter import find_unsupported_modulations

    notes = [IRNote(midi_pitch=60, pitch="C-4", duration=4, volume=15, instrument_id=1)]
    song = IRSong(
        title="t", frames_per_tick=FRAMES_PER_TICK, uses_16bit_bass=True,
        instruments=[
            IRInstrument(id=0, name="Bass", distortion=0xC0),
            IRInstrument(id=1, name="Lead", distortion=DISTORTION_5_AND_4BIT,
                         modulation=pokey_hw.MODULATION_OCTAVE_PULSE),
        ],
        patterns=[IRPattern(id=1, rows=4, tracks={3: [notes[0]]})],
        sequence=[1],
    )
    # The modulated instrument sounds on channel 3, which the 1+2 join does not own.
    assert find_unsupported_modulations(song) == []

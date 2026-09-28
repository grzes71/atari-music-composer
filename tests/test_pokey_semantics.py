"""Golden reference tests for POKEY semantics.

These tests are deliberately written against hardware truth, NOT against the
production helpers. Expected values are either:

* derived from the two reference emulators (atari800 ``pokeysnd.c`` /
  ``mzpokeysnd.c``), or
* computed by hand from the PAL clock (``1773447 / 28`` Hz base divider).

They must not call the function under test to produce its own expectation.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_4BIT_POLY,
    DISTORTION_5BIT_POLY_1,
    DISTORTION_5BIT_POLY_2,
    DISTORTION_5_AND_4BIT,
    DISTORTION_5_AND_17BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_PURE_TONE_ALT,
    DISTORTION_WHITE_NOISE,
)
from atari_music.ir import (
    IRInstrument,
    IRNote,
    IRPattern,
    IRSong,
    IREnvelope,
    compile_ir_to_pokey_frames,
    find_pitch_range_issues,
)
from atari_music.mads_exporter import export_mads_asm
from atari_music.pokey_synth import render_pokey_samples
from atari_music import pokey_synth

# Hardware reference: PAL CPU clock and the 64 kHz divider (both from pokey.h:
# POKEY_DIV_64 = 28). Written literally so the test is independent of constants.py.
PAL_CPU_HZ = 1773447.0
BASE_64K = PAL_CPU_HZ / 28.0
SR = 44100
FR = 50.0


def _midi_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _render_one_channel(audf: int, audc: int, audctl: int = 0, nframes: int = 30, ch: int = 0):
    f = np.zeros((nframes, 9), dtype=np.uint8)
    f[:, ch * 2] = audf
    f[:, ch * 2 + 1] = audc
    f[:, 8] = audctl
    return render_pokey_samples(f, SR, FR)


def _dominant_hz(samples: np.ndarray) -> float:
    x = samples.astype(np.float64)
    x = x - x.mean()
    w = np.hanning(len(x))
    sp = np.abs(np.fft.rfft(x * w))
    fr = np.fft.rfftfreq(len(x), 1.0 / SR)
    sp[:3] = 0
    return float(fr[int(np.argmax(sp))])


# ===========================================================================
# Case 1-4: AUDC distortion semantics (hardware truth table)
# ===========================================================================

def test_audc_decode_matches_hardware_truth_table():
    """Hardware decode: PURETONE outranks POLY4, so $E0==$A0 and $60==$20."""
    assert pokey_hw.decode_audc(0xA0) == pokey_hw.Waveform.PURE_TONE
    assert pokey_hw.decode_audc(0xE0) == pokey_hw.Waveform.PURE_TONE          # == $A0!
    assert pokey_hw.decode_audc(0x80) == pokey_hw.Waveform.POLY9_17           # real noise
    assert pokey_hw.decode_audc(0xC0) == pokey_hw.Waveform.POLY4
    assert pokey_hw.decode_audc(0x20) == pokey_hw.Waveform.POLY5_GATED_PURE
    assert pokey_hw.decode_audc(0x60) == pokey_hw.Waveform.POLY5_GATED_PURE   # == $20!
    assert pokey_hw.decode_audc(0x40) == pokey_hw.Waveform.POLY5_GATED_POLY4
    assert pokey_hw.decode_audc(0x00) == pokey_hw.Waveform.POLY5_GATED_POLY9_17
    assert pokey_hw.decode_audc(0xA0 | 0x10) == pokey_hw.Waveform.VOLUME_ONLY


def test_distortion_constants_have_correct_hardware_values():
    assert DISTORTION_PURE_TONE == 0xA0
    assert DISTORTION_PURE_TONE_ALT == 0xE0
    assert DISTORTION_WHITE_NOISE == 0x80
    assert DISTORTION_4BIT_POLY == 0xC0
    assert DISTORTION_5BIT_POLY_1 == 0x20
    assert DISTORTION_5BIT_POLY_2 == 0x60
    assert DISTORTION_5_AND_4BIT == 0x40
    assert DISTORTION_5_AND_17BIT == 0x00


def test_renderer_treats_e0_as_pure_tone_not_noise():
    """$E0 must render identically to $A0 (pure tone), and differently from $80 (noise)."""
    s_a0 = _render_one_channel(71, DISTORTION_PURE_TONE | 0x0F)
    s_e0 = _render_one_channel(71, DISTORTION_PURE_TONE_ALT | 0x0F)
    s_80 = _render_one_channel(71, DISTORTION_WHITE_NOISE | 0x0F)
    assert np.array_equal(s_a0, s_e0), "$E0 must be audibly identical to $A0"
    assert not np.array_equal(s_a0, s_80), "$E0 must NOT be rendered as noise"
    # $80 is bare noise: its spectrum is broadband, a pure tone's is not.
    def _flatness(x):
        sp = np.abs(np.fft.rfft(x.astype(np.float64) - x.mean()))[1:]
        sp = sp[sp > 0]
        return float(np.exp(np.mean(np.log(sp))) / np.mean(sp))
    assert _flatness(s_80) > _flatness(s_a0)


def test_renderer_implements_40_poly5_gated_poly4():
    """$40 is poly5-gated poly4, distinct from both $20 (poly5) and $A0 (pure)."""
    s40 = _render_one_channel(24, DISTORTION_5_AND_4BIT | 0x0F)
    s20 = _render_one_channel(24, DISTORTION_5BIT_POLY_1 | 0x0F)
    s_a0 = _render_one_channel(24, DISTORTION_PURE_TONE | 0x0F)
    assert not np.array_equal(s40, s_a0), "$40 must not fall back to a square wave"
    assert not np.array_equal(s40, s20), "$40 (poly5+poly4) must differ from $20 (poly5)"


def test_renderer_60_equals_20():
    s60 = _render_one_channel(30, DISTORTION_5BIT_POLY_2 | 0x0F)
    s20 = _render_one_channel(30, DISTORTION_5BIT_POLY_1 | 0x0F)
    assert np.array_equal(s60, s20), "$60 and $20 are both poly5-gated pure tone"


# ===========================================================================
# Case 5: 8-bit AUDF / frequency
# ===========================================================================

@pytest.mark.parametrize("name,midi,expected_audf", [
    ("A3", 57, 143),    # round(63337.39/440.00) - 1 = 144 - 1 = 143
    ("A4", 69, 71),     # round(63337.39/880.00) - 1 = 72 - 1 = 71
    ("C4", 60, 120),    # round(63337.39/523.25) - 1 = 121 - 1 = 120
    ("C5", 72, 60),     # round(63337.39/1046.50) - 1 = 61 - 1 = 60
])
def test_8bit_audf_hand_computed(name, midi, expected_audf):
    hz = _midi_hz(midi)
    # Hand-computed from the hardware formula: AUDF = round(base/(2*f)) - 1
    hand = max(0, min(255, round(BASE_64K / (2.0 * hz)) - 1))
    assert hand == expected_audf, f"{name}: hand-computed AUDF mismatch"
    assert pokey_hw.audf_from_hz_8bit(hz) == expected_audf


def test_8bit_a4_is_71_and_plays_440():
    hz = 440.0
    assert pokey_hw.audf_from_hz_8bit(hz) == 71
    # f = base / (2 * (AUDF + 1)) -> base / 144
    assert pokey_hw.hz_from_audf_8bit(71) == pytest.approx(BASE_64K / (2 * 72), rel=1e-9)
    # And the renderer must actually produce ~440 Hz.
    samples = _render_one_channel(71, DISTORTION_PURE_TONE | 0x0C, nframes=40)
    assert _dominant_hz(samples) == pytest.approx(440.0, abs=1.5)


def test_8bit_hs_clock_uses_offset_4():
    """1.79 MHz single channel: f = CPU_CLOCK / (2 * (AUDF + 4))."""
    from atari_music.constants import AUDCTL_CH1_179MHZ
    # At 1.79 MHz an 8-bit divider is only useful for high frequencies.
    assert pokey_hw.hz_from_audf_8bit(100, AUDCTL_CH1_179MHZ, channel=1) == pytest.approx(
        PAL_CPU_HZ / (2.0 * 104), rel=1e-9
    )
    assert pokey_hw.audf_from_hz_8bit(PAL_CPU_HZ / (2.0 * 104), AUDCTL_CH1_179MHZ, channel=1) == 100


# ===========================================================================
# Case 6: 16-bit divider (hardware offset +1, NOT +2)
# ===========================================================================

@pytest.mark.parametrize("name,midi,expected_div", [
    ("A2", 45, 287),   # round(63337.39/220) - 1 = 288 - 1 = 287
    ("C3", 48, 241),   # round(63337.39/261.63) - 1 = 242 - 1 = 241
    ("A4", 69, 71),    # round(63337.39/880) - 1 = 72 - 1 = 71
    ("C5", 72, 60),    # round(63337.39/1046.50) - 1 = 61 - 1 = 60
])
def test_16bit_divider_hand_computed(name, midi, expected_div):
    hz = _midi_hz(midi)
    hand = round(BASE_64K / (2.0 * hz)) - 1
    assert hand == expected_div, f"{name}: hand-computed divider mismatch"
    assert pokey_hw.audf16_from_hz(hz) == expected_div


def test_16bit_frequency_matches_hardware_offset():
    """Hardware: f = base / (2 * (N + 1)). For A2 (N=287) that is base/576."""
    assert pokey_hw.hz_from_audf_16bit(287) == pytest.approx(BASE_64K / 576.0, rel=1e-9)
    assert pokey_hw.hz_from_audf_16bit(287) == pytest.approx(110.0, abs=0.1)
    lo, hi = pokey_hw.split_audf16(287)
    assert (lo, hi) == (0x1F, 0x01)  # AUDF1 = LSB, AUDF2 = MSB


def test_16bit_renderer_frequency_matches_hardware():
    """The WAV renderer must use the same 16-bit divider math as the hardware."""
    f = np.zeros((40, 9), dtype=np.uint8)
    f[:, 0] = 0x1F          # AUDF1 = low byte
    f[:, 1] = 0               # AUDC1 muted
    f[:, 2] = 0x01          # AUDF2 = high byte
    f[:, 3] = DISTORTION_PURE_TONE | 0x0F
    f[:, 8] = AUDCTL_JOIN_1_2_16BIT
    samples = render_pokey_samples(f, SR, FR)
    assert _dominant_hz(samples) == pytest.approx(109.96, abs=2.0)


# ===========================================================================
# Case 7: $FF tracker clamp and WAV <-> ASM consistency
# ===========================================================================

def test_audf_tracker_clamp():
    assert pokey_hw.AUDF_TRACKER_MAX == 0xFE
    assert pokey_hw.clamp_audf_for_tracker(0xFF) == 0xFE
    assert pokey_hw.clamp_audf_for_tracker(0x47) == 0x47
    assert pokey_hw.clamp_audf_for_tracker(-5) == 0


def test_ff_edge_wav_and_asm_agree():
    """A2 (110 Hz) needs AUDF 287 -> clamped to $FE in BOTH paths (not $FF in one)."""
    song = IRSong(
        title="ff", frames_per_tick=4,
        instruments=[IRInstrument(id=0, name="B", distortion=DISTORTION_4BIT_POLY)],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [IRNote(pitch="A-2", midi_pitch=45, duration=4, volume=10, instrument_id=0)]})],
        sequence=[0],
    )
    frames = compile_ir_to_pokey_frames(song)
    frame_audf = int(frames[0, 0])
    asm = export_mads_asm(song)
    m = re.search(r"_pat_0_ch1:\n\s*\.byte \$([0-9a-f]{2}),", asm)
    asm_audf = int(m.group(1), 16)
    assert frame_audf == 0xFE
    assert asm_audf == 0xFE
    assert frame_audf == asm_audf


def test_wav_and_asm_auDF_agree_for_mid_and_high_notes():
    """Same IRSong -> identical AUDF in the WAV register stream and the ASM export."""
    song = IRSong(
        title="consistency", frames_per_tick=4,
        instruments=[IRInstrument(id=0, name="L", distortion=DISTORTION_PURE_TONE)],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [
            IRNote(pitch="A-4", midi_pitch=69, duration=4, volume=12, instrument_id=0)
        ]})],
        sequence=[0],
    )
    frames = compile_ir_to_pokey_frames(song)
    asm = export_mads_asm(song)
    m = re.search(r"_pat_0_ch1:\n\s*\.byte \$([0-9a-f]{2}),", asm)
    assert int(frames[0, 0]) == int(m.group(1), 16) == 0x47


# ===========================================================================
# Case 8: percussion character mapping
# ===========================================================================

@pytest.mark.parametrize("character,expected_dist,expected_role", [
    ("percussion", 0x80, "percussion"),
    ("noise", 0x80, "percussion"),
    ("drum", 0x80, "percussion"),
    ("snare", 0x80, "percussion"),
    ("hihat", 0x80, "percussion"),
    ("kick", 0xC0, "percussion"),
    ("tom", 0xC0, "percussion"),
    ("bass", 0xC0, "bass"),
    ("bright_lead", 0xA0, "melody"),
])
def test_percussion_character_mapping(character, expected_dist, expected_role):
    from atari_music.ai.composition import map_instrument_character
    from atari_music.ai.schema import AIInstrumentDef

    inst = AIInstrumentDef(id="x", name="x", character=character)
    dist, _env, role = map_instrument_character(inst, False)
    assert dist == expected_dist, f"{character} -> ${dist:02x}"
    assert role.value == expected_role


# ===========================================================================
# Case 9: envelope model (matches player.asm)
# ===========================================================================

def test_envelope_attack_is_two_step_like_the_player():
    # attack=3, peak=15 -> (15>>1)|1 = 7, 7, then peak 15
    vols = pokey_hw.player_envelope_volumes(12, 4, 15, 3, 0, 8, 0)
    assert vols[:3] == [7, 7, 15]


def test_envelope_attack_zero_jumps_to_peak():
    vols = pokey_hw.player_envelope_volumes(8, 4, 15, 0, 0, 8, 0)
    assert vols[0] == 15


def test_envelope_decay_jumps_to_sustain_without_slope():
    # decay must NOT ramp: first frame after attack is already sustain
    vols = pokey_hw.player_envelope_volumes(12, 4, 15, 0, 4, 6, 0)
    assert vols[0] == 15
    assert vols[1] == 6
    assert vols[2] == 6


def test_envelope_release_starts_only_when_ticks_remain_below_release():
    """``player.asm`` releases on ``ch_dur < ch_rel`` (strict), so a note whose
    remaining ticks *equal* ``release`` must still be sustaining.

    Hand-derived from the player state machine: attack=0 jumps straight to the peak,
    then decay=0 jumps to sustain=10. ``total_ticks = 8 / 4 = 2``, so the first tick
    has 2 ticks remaining (not yet < 2 -> sustain) and the second has 1 (-> release).
    """
    vols = pokey_hw.player_envelope_volumes(8, 4, 15, 0, 0, 10, 2)
    assert vols == [15, 10, 10, 10, 10, 9, 8, 7]
    # the release tail is a linear -1 per frame fade from the sustain level
    assert vols[-3:] == [9, 8, 7]


def test_envelope_release_holds_sustain_for_the_whole_first_tick():
    """Regression for the old off-by-one: release used to start on frame 0 here."""
    vols = pokey_hw.player_envelope_volumes(8, 4, 15, 0, 0, 10, 2)
    assert vols[0] == 15
    assert vols[1] == 10
    assert vols[2] == 10
    assert vols[3] == 10


def test_envelope_release_on_last_tick_only():
    """16 rows x 4 frames = 64 frames, release=2 -> release begins on the final tick."""
    vols = pokey_hw.player_envelope_volumes(64, 4, 15, 0, 0, 10, 2)
    assert len(vols) == 64
    assert vols[0] == 15
    assert vols[1:61] == [10] * 60
    assert vols[61:] == [9, 8, 7]


def test_envelope_release_zero_never_ramps():
    vols = pokey_hw.player_envelope_volumes(8, 4, 15, 0, 0, 10, 0)
    assert vols == [15, 10, 10, 10, 10, 10, 10, 10]


# ===========================================================================
# Case 10: noise generator properties (independent of the generator code)
# ===========================================================================

@pytest.mark.parametrize("seq,n,poly", [
    (pokey_synth.POLY4_SEQ, 4, "x^4+x^3+1"),
    (pokey_synth.POLY5_SEQ, 5, "x^5+x^3+1"),
    (pokey_synth.POLY9_SEQ, 9, "x^9+x^4+1"),
    (pokey_synth.POLY17_SEQ, 17, "x^17+x^12+1"),
])
def test_poly_sequences_are_maximal_length(seq, n, poly):
    length = (1 << n) - 1
    assert len(seq) == length
    vals = set(np.round(seq).astype(int).tolist())
    if vals <= {0, 1}:
        ones = int(np.sum(seq))
    else:
        ones = int(np.sum(seq == 1))
    assert ones == length - ones + 1, f"{poly}: m-sequence must have one extra 1"
    # full period (no smaller repeating period)
    period = length
    for p in range(1, length):
        if length % p == 0 and np.array_equal(seq[:p], np.tile(seq[:p], length // p)):
            period = p
            break
    assert period == length


def test_valid_distortion_accepts_only_real_audc_bytes():
    from atari_music.ai.validation import validate_hardware
    from atari_music.ai.schema import AICompositionDoc

    base = {
        "format": "atari-music-composition", "version": 1,
        "metadata": {"title": "t", "bpm": 120},
        "hardware": {"channels": 4},
        "instruments": [{"id": "i", "name": "i", "character": "bright_lead", "distortion": 0x80}],
        "patterns": [{"id": "P", "length_steps": 4, "channels": {"1": [{"step": 0, "note": "C4", "instrument": "i", "duration": 1}]}}],
        "sequence": ["P"],
    }
    validate_hardware(AICompositionDoc.model_validate(base))  # 0x80 allowed

    for bad in (2, 4, 6, 8, 10, 12, 14, 3):
        doc = dict(base)
        doc["instruments"] = [{**base["instruments"][0], "distortion": bad}]
        with pytest.raises(Exception):
            validate_hardware(AICompositionDoc.model_validate(doc))


# ===========================================================================
# Case 10: end-to-end pipeline (AI JSON -> IR -> WAV + MADS)
# ===========================================================================

def test_end_to_end_semantics_are_preserved(tmp_path):
    """A full composition keeps instruments, pitch, duration, AUDC, AUDF and AUDCTL."""
    from atari_music.ai.schema import AICompositionDoc
    from atari_music.ai.composition import compile_composition_to_pokey_ir
    from atari_music.pokey_synth import render_pokey_to_wav

    doc = AICompositionDoc.model_validate({
        "format": "atari-music-composition", "version": 1,
        "metadata": {"title": "E2E", "bpm": 120},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [
            {"id": "lead", "name": "Lead", "character": "bright_lead"},
            {"id": "bass", "name": "Bass", "character": "bass"},
            {"id": "perc", "name": "Perc", "character": "percussion"},
        ],
        "patterns": [{"id": "P1", "length_steps": 16, "channels": {
            "1": [{"step": 0, "note": "A4", "instrument": "lead", "duration": 4, "volume": 12},
                  {"step": 4, "note": "C5", "instrument": "lead", "duration": 4, "volume": 12}],
            "2": [{"step": 0, "note": "A2", "instrument": "bass", "duration": 8, "volume": 11}],
            "3": [{"step": 0, "note": "A2", "instrument": "perc", "duration": 2, "volume": 10}],
        }}],
        "sequence": ["P1"], "loop_point": 0,
    })
    song = compile_composition_to_pokey_ir(doc)

    # 1. Instruments and distortions preserved with correct hardware values
    by_name = {i.name: i.distortion for i in song.instruments}
    assert by_name["Lead"] == 0xA0
    assert by_name["Bass"] == 0xC0
    assert by_name["Perc"] == 0x80

    # 2. Exactly one instrument per channel, and no note lost
    total_rows = {1: 0, 2: 0, 3: 0}
    for pat in song.patterns:
        for ch, notes in pat.tracks.items():
            assert len({n.instrument_id for n in notes}) == 1, "channel must use one instrument"
            total_rows[ch] = sum(n.duration for n in notes)
    assert total_rows[1] == 16 and total_rows[2] == 16 and total_rows[3] == 16

    # 3. Register stream: AUDCTL, and the distortion high-nibble per channel
    frames = compile_ir_to_pokey_frames(song)
    assert int(frames[0, 8]) == 0x00
    assert int(frames[0, 1]) & 0xE0 == 0xA0          # lead = pure tone
    assert int(frames[0, 3]) & 0xE0 == 0xC0          # bass = poly4
    assert int(frames[0, 5]) & 0xE0 == 0x80          # perc = real noise
    assert int(frames[0, 0]) == 71                   # lead A4 -> $47

    # 4. MADS export agrees with the frame stream (same AUDF, same distortion nibble)
    asm = export_mads_asm(song)
    m = re.search(r"_pat_0_ch1:\n\s*\.byte \$([0-9a-f]{2}),", asm)
    assert int(m.group(1), 16) == int(frames[0, 0])
    assert ".byte $80," in asm or ".byte $80, " in asm    # percussion instrument distortion

    # 5. WAV renders from the same register stream
    wav = tmp_path / "e2e.wav"
    render_pokey_to_wav(frames, wav)
    assert wav.exists() and wav.stat().st_size > 0


# ===========================================================================
# Case 11: post-implementation regression fixes
#   F-1 unpitched percussion, F-2 release off-by-one, F-3 8-bit AUDF floor,
#   F-5 hardcoded rest length in the 16-bit slave track
# ===========================================================================

def _percussion_song(unpitched: bool = True) -> IRSong:
    """One percussion note on channel 1, either unpitched (a drum hit) or pitched."""
    inst = IRInstrument(
        id=0,
        name="Perc",
        distortion=DISTORTION_WHITE_NOISE,
        role="percussion",
        envelope=IREnvelope(attack_frames=0, decay_frames=0, sustain_vol=10, release_frames=0),
    )
    note = IRNote(
        duration=4,
        volume=15,
        instrument_id=0,
        channel_role="percussion",
        pitch=None if unpitched else "A-4",
        midi_pitch=None if unpitched else 69,
    )
    return IRSong(
        title="perc",
        frames_per_tick=4,
        instruments=[inst],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [note]})],
        sequence=[0],
    )


def test_unpitched_percussion_is_a_real_hit_not_midi_60():
    """F-1: an unpitched percussion note must be an explicit hit in BOTH outputs.

    Before the fix the WAV register stream silently played the implicit MIDI 60
    (AUDF $47, C-4) while the exported tracker bytes carried AUDF $00 with volume 0
    (silence), so the preview and the Atari disagreed.
    """
    song = _percussion_song(unpitched=True)
    frames = compile_ir_to_pokey_frames(song)
    asm = export_mads_asm(song)

    assert pokey_hw.PERCUSSION_DEFAULT_AUDF == 0x50
    assert int(frames[0, 0]) == pokey_hw.PERCUSSION_DEFAULT_AUDF
    assert int(frames[0, 0]) != 0x47, "unpitched percussion must not silently become MIDI 60"

    # ... and it must be audible: percussion distortion plus full volume.
    assert int(frames[0, 1]) & 0xE0 == DISTORTION_WHITE_NOISE
    assert int(frames[0, 1]) & 0x0F == 15

    # The exported tracker bytes must carry exactly the same semantics.
    m = re.search(r"_pat_0_ch1:\n\s*\.byte \$([0-9a-f]{2}),\s*(\d+),\s*\$([0-9a-f]{2})", asm)
    assert m, asm
    assert int(m.group(1), 16) == int(frames[0, 0])
    assert int(m.group(2)) == 4
    assert int(m.group(3), 16) == (int(frames[0, 1]) & 0x0F)


def test_pitched_percussion_keeps_its_pitch():
    """The fallback must only apply to unpitched hits."""
    song = _percussion_song(unpitched=False)
    frames = compile_ir_to_pokey_frames(song)
    assert int(frames[0, 0]) == 0x47          # A-4 = 440 Hz -> AUDF $47
    assert int(frames[0, 0]) != pokey_hw.PERCUSSION_DEFAULT_AUDF


def test_rest_still_silences_the_channel():
    inst = IRInstrument(id=0, name="L", distortion=DISTORTION_PURE_TONE)
    song = IRSong(
        title="rest",
        frames_per_tick=4,
        instruments=[inst],
        patterns=[IRPattern(id=0, rows=4, tracks={1: [
            IRNote(duration=4, volume=15, instrument_id=0, is_rest=True)
        ]})],
        sequence=[0],
    )
    frames = compile_ir_to_pokey_frames(song)
    assert int(frames[0, 1]) == 0
    asm = export_mads_asm(song)
    assert re.search(r"_pat_0_ch1:\n\s*\.byte \$00,\s*4,\s*\$00", asm), asm


def test_procedural_percussion_is_not_midi_60_and_not_silent():
    """F-1 end-to-end on the real trigger: ``generator.generate_song`` emits percussion
    notes with no pitch, which used to become AUDF $47 in the WAV stream and $00
    (silence) in the exported tracker data."""
    from atari_music.generator import generate_song

    song = generate_song(seed=42)
    frames = compile_ir_to_pokey_frames(song)
    asm = export_mads_asm(song)

    def _is_unpitched_hit(note: IRNote) -> bool:
        return note.channel_role == "percussion" and note.midi_pitch is None and not note.is_rest

    hits = [n for pat in song.patterns for notes in pat.tracks.values() for n in notes if _is_unpitched_hit(n)]
    assert hits, "seed 42 must produce unpitched percussion for this regression to be meaningful"
    perc_channels = {
        ch
        for pat in song.patterns
        for ch, notes in pat.tracks.items()
        if any(_is_unpitched_hit(n) for n in notes)
    }

    for ch in perc_channels:
        col = (ch - 1) * 2
        active = [i for i in range(len(frames)) if int(frames[i, col + 1]) & 0x0F > 0]
        assert active, f"channel {ch} percussion must be audible in the WAV register stream"
        assert all(int(frames[i, col]) == pokey_hw.PERCUSSION_DEFAULT_AUDF for i in active)
        assert all(int(frames[i, col]) != 0x47 for i in active), "must not be an implicit MIDI 60"

        for m in re.finditer(rf"_pat_(\d+)_ch{ch}:\n((?:\s*\.byte[^\n]*\n)+)", asm):
            audfs = [int(x, 16) for x in re.findall(r"\.byte \$([0-9a-f]{2}),", m.group(2))]
            assert audfs, m.group(2)
            assert 0x47 not in audfs, "exported percussion must not contain the MIDI 60 divider"
            assert pokey_hw.PERCUSSION_DEFAULT_AUDF in audfs
            assert set(audfs) <= {0x00, pokey_hw.PERCUSSION_DEFAULT_AUDF}


# ---------------------------------------------------------------------------
# F-2: the model must reproduce what player.asm actually writes.
# ---------------------------------------------------------------------------

ENV_PARITY_CASES = [
    (0, 0, 10, 2, 120),
    (0, 0, 10, 1, 120),
    (0, 0, 10, 0, 120),
    (0, 0, 10, 4, 120),
    (2, 3, 8, 2, 120),
    (0, 0, 10, 2, 60),     # bpm 60  -> frames_per_tick 6
    (0, 0, 10, 2, 160),    # bpm 160 -> frames_per_tick 3
]


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
        for i, b in enumerate(data[idx:idx + size]):
            mpu.memory[start + i] = b
        idx += size


@pytest.mark.parametrize("att,dec,sus,rel,bpm", ENV_PARITY_CASES)
def test_emulated_player_envelope_matches_model(tmp_path, att, dec, sus, rel, bpm):
    """F-2 oracle: run the real ``player.asm`` on a 6502 and compare AUDC1 per frame.

    The expectation comes from the emulated player, not from the model, so the two
    cannot agree merely by construction. py65 emulates the CPU (not POKEY), so this
    validates the player's register writes, not the generated audio waveform.
    """
    pytest.importorskip("py65")
    from pathlib import Path
    from conftest import require_local_artifact

    require_local_artifact(Path("tools/mads/mads.exe"))

    from py65.devices.mpu6502 import MPU
    from atari_music.ai.client import build_xex_from_composition
    from atari_music.ai.composition import compile_composition_to_pokey_ir
    from atari_music.ai.schema import AICompositionDoc

    steps = 16
    doc = AICompositionDoc.model_validate({
        "format": "atari-music-composition",
        "version": 1,
        "metadata": {"title": "env-parity", "bpm": bpm},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [{
            "id": "lead", "name": "Lead", "character": "bright_lead",
            "attack_frames": att, "decay_frames": dec,
            "sustain_vol": sus, "release_frames": rel,
        }],
        "patterns": [{"id": "P1", "length_steps": steps, "channels": {
            "1": [{"step": 0, "note": "A4", "instrument": "lead",
                   "duration": steps, "volume": 15}],
        }}],
        "sequence": ["P1"],
        "loop_point": 0,
    })
    fpt = compile_composition_to_pokey_ir(doc).frames_per_tick
    nframes = steps * fpt

    xex = tmp_path / f"env_{att}_{dec}_{sus}_{rel}_{bpm}.xex"
    build_xex_from_composition(doc, output_path=xex)
    mpu = MPU()
    _load_xex_into(mpu, xex.read_bytes())

    RETURN_TRAP = 0x0200
    mpu.memory[RETURN_TRAP] = 0x00

    def call(addr, x=0, y=0):
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
    update_addr = None
    for p in range(0x4000, 0x4100):
        if mpu.memory[p] == 0x49 and mpu.memory[p + 1] == 0x01:   # eor #1 (mute toggle)
            update_addr = mpu.memory[p + 6] | (mpu.memory[p + 7] << 8)
            break
    assert update_addr is not None, "could not locate music_update in the harness"

    call(init_addr, song_data & 0xFF, (song_data >> 8) & 0xFF)
    call(play_addr)

    player_audc: list[int] = []
    for _ in range(nframes):
        audc = None
        ret = RETURN_TRAP - 1
        mpu.memory[0x01FF] = (ret >> 8) & 0xFF
        mpu.memory[0x01FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = update_addr
        guard = 0
        while mpu.pc != RETURN_TRAP:
            if mpu.memory[mpu.pc] == 0x8D:                      # sta abs
                addr = mpu.memory[mpu.pc + 1] | (mpu.memory[mpu.pc + 2] << 8)
                if addr == 0xD201:                              # AUDC1
                    audc = mpu.a
            mpu.step()
            guard += 1
            assert guard < 100000, "player frame loop did not terminate"
        assert audc is not None, "player never wrote AUDC1"
        player_audc.append(audc)

    expected = pokey_hw.player_envelope_volumes(nframes, fpt, 15, att, dec, sus, rel)
    actual = [a & 0x0F for a in player_audc]
    assert actual == expected, (
        f"player vs model mismatch for att={att} dec={dec} sus={sus} rel={rel} bpm={bpm}\n"
        f"player={actual}\nmodel ={expected}"
    )
    # the distortion nibble is written once per channel and must not drift while audible
    assert {a & 0xF0 for a in player_audc if a & 0x0F} == {0xA0}


# ---------------------------------------------------------------------------
# F-3: 8-bit AUDF floor diagnostics
# ---------------------------------------------------------------------------

def test_eight_bit_floor_is_derived_from_the_pal_clock():
    """Lowest encodable 8-bit frequency = base clock / (2 * (AUDF_TRACKER_MAX + 1))."""
    expected_floor = BASE_64K / (2.0 * (pokey_hw.AUDF_TRACKER_MAX + 1))
    assert pokey_hw.eight_bit_floor_hz() == pytest.approx(expected_floor, rel=1e-12)
    assert expected_floor == pytest.approx(124.19, abs=0.01)


def test_eight_bit_range_boundary_is_exact():
    """Hand-derived: AUDF = round(BASE / (2f)) - 1 reaches 255 (unencodable) at f <= 123.95 Hz."""
    assert 63337.39 <= BASE_64K <= 63337.40
    assert pokey_hw.describe_8bit_range_error(124.0) is None       # AUDF 254 -> encodable
    assert pokey_hw.describe_8bit_range_error(123.9) is not None   # AUDF 255 -> clamped


@pytest.mark.parametrize("name,in_range", [
    ("A-4", True),     # 440.00 Hz
    ("C-3", True),     # 130.81 Hz
    ("F-3", True),     # 174.61 Hz
    ("B-2", False),    # 123.47 Hz - just below the floor
    ("D-2", False),    # 73.42 Hz  - the real-world case from the audit
])
def test_eight_bit_range_detection(name, in_range):
    from atari_music.ir import note_name_to_midi

    midi = note_name_to_midi(name)
    assert midi is not None
    freq = 440.0 * 2.0 ** ((midi - 69) / 12.0)
    assert (pokey_hw.describe_8bit_range_error(freq) is None) == in_range


def test_eight_bit_range_error_reports_the_detune_in_cents():
    d2_hz = 440.0 * 2.0 ** ((38 - 69) / 12.0)          # D-2 is MIDI 38
    assert d2_hz == pytest.approx(73.42, abs=0.01)

    info = pokey_hw.describe_8bit_range_error(d2_hz)
    assert info is not None
    assert info["mode"] == "8-bit"
    assert info["divider"] > pokey_hw.AUDF_TRACKER_MAX
    # the reported value is rounded to 3 decimals on purpose
    assert info["representable_hz"] == pytest.approx(pokey_hw.eight_bit_floor_hz(), abs=0.001)

    hand_derived_cents = 1200.0 * np.log2(info["representable_hz"] / d2_hz)
    assert info["cents"] == pytest.approx(hand_derived_cents, abs=0.05)
    assert info["cents"] == pytest.approx(910, abs=1)


def _range_song(note_name: str, midi: int, ch: int = 2, uses_16bit: bool = False) -> IRSong:
    inst = IRInstrument(id=0, name="Bass", distortion=DISTORTION_4BIT_POLY, role="bass")
    return IRSong(
        title="range",
        frames_per_tick=4,
        uses_16bit_bass=uses_16bit,
        instruments=[inst],
        patterns=[IRPattern(id=0, rows=4, tracks={ch: [
            IRNote(pitch=note_name, midi_pitch=midi, duration=4, volume=15,
                   instrument_id=0, channel_role="bass")
        ]})],
        sequence=[0],
    )


def test_find_pitch_range_issues_flags_only_clamped_notes():
    assert find_pitch_range_issues(_range_song("C-3", 48)) == []

    issues = find_pitch_range_issues(_range_song("D-2", 38))
    assert len(issues) == 1
    assert issues[0]["midi_pitch"] == 38
    assert issues[0]["channel"] == 2
    assert issues[0]["requested_hz"] == pytest.approx(73.42, abs=0.01)
    assert issues[0]["cents"] == pytest.approx(910, abs=1)


def test_find_pitch_range_issues_skips_16bit_bass_pair():
    assert find_pitch_range_issues(_range_song("D-2", 38, ch=1, uses_16bit=True)) == []


def test_low_pitch_is_a_warning_never_an_error():
    """F-3: clamping is lossy but still playable, so validation must stay ``valid``."""
    from atari_music.ai.validation import PITCH_OUT_OF_8BIT_RANGE, validate_composition_report

    report = validate_composition_report({
        "format": "atari-music-composition", "version": 1,
        "metadata": {"title": "Low", "bpm": 120},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [{"id": "bass", "name": "Bass", "character": "bass"}],
        "patterns": [{"id": "P", "length_steps": 4, "channels": {
            "1": [{"step": 0, "note": "D-2", "instrument": "bass", "duration": 4, "volume": 15}],
        }}],
        "sequence": ["P"], "loop_point": 0,
    })

    assert report.valid is True, "a clamped pitch must not invalidate the composition"
    assert report.issues == []
    assert len(report.warnings) == 1
    warning = report.warnings[0]
    assert warning.code == PITCH_OUT_OF_8BIT_RANGE
    assert warning.category == "hardware"
    assert warning.details["mode"] == "8-bit"
    assert warning.details["cents"] == pytest.approx(910, abs=1)
    assert "AUDF $fe" in warning.message


def test_in_range_pitch_produces_no_warning():
    from atari_music.ai.validation import validate_composition_report

    report = validate_composition_report({
        "format": "atari-music-composition", "version": 1,
        "metadata": {"title": "Ok", "bpm": 120},
        "hardware": {"channels": 4, "use_16bit_bass": False},
        "instruments": [{"id": "bass", "name": "Bass", "character": "bass"}],
        "patterns": [{"id": "P", "length_steps": 4, "channels": {
            "1": [{"step": 0, "note": "A-3", "instrument": "bass", "duration": 4, "volume": 15}],
        }}],
        "sequence": ["P"], "loop_point": 0,
    })

    assert report.valid is True
    assert report.warnings == []


def test_16bit_bass_mode_produces_no_8bit_range_warning():
    from atari_music.ai.validation import validate_composition_report

    report = validate_composition_report({
        "format": "atari-music-composition", "version": 1,
        "metadata": {"title": "16bit", "bpm": 120},
        "hardware": {"channels": 4, "use_16bit_bass": True},
        "instruments": [{"id": "bass", "name": "Bass", "character": "bass"}],
        "patterns": [{"id": "P", "length_steps": 4, "channels": {
            "1": [{"step": 0, "note": "D-2", "instrument": "bass", "duration": 4, "volume": 15}],
        }}],
        "sequence": ["P"], "loop_point": 0,
    })

    assert report.valid is True
    assert report.warnings == []


# ---------------------------------------------------------------------------
# F-5: the 16-bit slave track must rest for the real pattern length
# ---------------------------------------------------------------------------

def _slave_rest_song(rows: int) -> IRSong:
    inst = IRInstrument(id=0, name="Bass", distortion=DISTORTION_PURE_TONE, role="bass")
    return IRSong(
        title="slave",
        frames_per_tick=4,
        uses_16bit_bass=True,
        instruments=[inst],
        patterns=[IRPattern(id=0, rows=rows, tracks={3: [
            IRNote(pitch="A-3", midi_pitch=57, duration=rows, volume=15, instrument_id=0)
        ]})],
        sequence=[0],
    )


@pytest.mark.parametrize("rows", [8, 16, 32])
def test_16bit_slave_rest_uses_the_real_pattern_length(rows):
    """F-5: the empty 16-bit slave track used to hardcode a 32-row rest."""
    asm = export_mads_asm(_slave_rest_song(rows))
    assert re.search(rf"_pat_0_ch2:\n\s*\.byte \$00,\s*{rows},\s*\$00", asm), asm
    if rows != 32:
        assert ", 32, $00" not in asm

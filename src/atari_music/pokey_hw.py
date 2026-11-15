"""Single source of truth for POKEY hardware semantics.

Every module that turns musical intent (a note and an instrument) into POKEY
register values MUST go through this module, so that the WAV renderer and the
MADS/6502 export cannot drift apart. It contains:

* AUDC distortion decoding   (``decode_audc``)  — which generator POKEY uses.
* Clock / divider arithmetic (``hz_from_audf_*``, ``audf_from_hz_*``).
* The tracker AUDF clamp     (``AUDF_TRACKER_MAX`` / ``clamp_audf_for_tracker``).
* The player's ADSR envelope (``player_envelope_volumes``), so the WAV preview
  reproduces what ``player.asm`` will actually output.

References (authoritative, two independent implementations):
* atari800 ``pokeysnd.c``   — Ron Fries, 1996
* atari800 ``mzpokeysnd.c`` — Michael Borisov / Krzysztof Nikiel
* ``pokey.h``               — AUDC / AUDCTL bit definitions
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Optional

from atari_music.constants import (
    AUDC_NOTPOLY5,
    AUDC_POLY4,
    AUDC_PURETONE,
    AUDC_VOLUME_ONLY,
    AUDCTL_15KHZ,
    AUDCTL_9BIT_POLY,
    AUDCTL_CH1_179MHZ,
    AUDCTL_CH3_179MHZ,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    PAL_15KHZ_CLOCK,
    PAL_64KHZ_CLOCK,
    PAL_CLOCK_HZ,
)


class Waveform(str, Enum):
    """The generator POKEY actually uses for a given AUDC value."""

    VOLUME_ONLY = "volume_only"
    PURE_TONE = "pure_tone"
    POLY4 = "poly4"
    POLY9_17 = "poly9_17"
    POLY5_GATED_PURE = "poly5_gated_pure"
    POLY5_GATED_POLY4 = "poly5_gated_poly4"
    POLY5_GATED_POLY9_17 = "poly5_gated_poly9_17"


def decode_audc(audc: int) -> Waveform:
    """Map an AUDC register value to the generator POKEY uses.

    Bit order matters: PURETONE (bit 5) is tested before POLY4 (bit 6), so
    ``$E0 == $A0`` and ``$60 == $20`` (hardware truth, both reference emulators).
    """
    if audc & AUDC_VOLUME_ONLY:
        return Waveform.VOLUME_ONLY
    if audc & AUDC_NOTPOLY5:
        if audc & AUDC_PURETONE:
            return Waveform.PURE_TONE
        if audc & AUDC_POLY4:
            return Waveform.POLY4
        return Waveform.POLY9_17
    if audc & AUDC_PURETONE:
        return Waveform.POLY5_GATED_PURE
    if audc & AUDC_POLY4:
        return Waveform.POLY5_GATED_POLY4
    return Waveform.POLY5_GATED_POLY9_17


def is_noise_waveform(waveform: Waveform) -> bool:
    """True if the waveform is unpitched noise (used by analysis/reporting)."""
    return waveform in (Waveform.POLY9_17, Waveform.POLY5_GATED_POLY9_17)


# ---------------------------------------------------------------------------
# Clock / divider arithmetic
# ---------------------------------------------------------------------------
#
# Hardware timer periods, in CPU clock cycles (N = divider register value):
#     64 kHz / 15 kHz :  (N + 1) * base_divisor
#     1.79 MHz, 8-bit :   N + 4
#     1.79 MHz, 16-bit:   N + 7
# where f_out = CPU_CLOCK / (2 * period).
# The two reference emulators implement exactly these offsets:
#   pokeysnd.c   : AUDCTL&0x40 -> AUDF+4 ; CH1_CH2 & CH1_179 -> AUDF2*256+AUDF1+7
#   mzpokeysnd.c : c0divstart = c0diva + 4 ; c1divstart = c0diva+256*c1diva+7

AUDF_MIN = 0
AUDF_MAX_8BIT = 0xFF
AUDF_MAX_16BIT = 0xFFFF

# The 6502 tracker stores each event as `.byte audf, duration, volume` and marks
# the end of a track with an AUDF byte of $FF. $FF therefore cannot be used as a
# real AUDF value in the exported data, so the semantic model clamps AUDF to
# $FE in BOTH the WAV register stream and the exported ASM. This keeps the two
# outputs bit-identical instead of silently diverging (WAV $FF vs ASM $FE).
AUDF_TRACKER_MAX = 0xFE


def clamp_audf_for_tracker(value: int) -> int:
    """Clamp a hardware AUDF value to the range the tracker format can encode."""
    return max(AUDF_MIN, min(AUDF_TRACKER_MAX, int(value)))


# ---------------------------------------------------------------------------
# Per-channel modulation descriptors (music-data format version 1)
# ---------------------------------------------------------------------------
# The instrument table's sixth byte. Version 1 of the song data format defines exactly one
# descriptor; every song that does not ask for a modulation carries ``MODULATION_NONE``, which
# is what the composer writes unless something explicitly sets ``IRInstrument.modulation``.
#
#: No modulation: the channel holds one divider for the whole note. The default, and what
#: every song exported before this existed is equivalent to.
MODULATION_NONE = 0
#: C1 (``c1_octave_pulse``): alternate the channel divider between ``N`` and ``N // 2`` once
#: per 50 Hz frame, for the whole note, on every note of the channel. See
#: :func:`octave_pulse_divider`.
MODULATION_OCTAVE_PULSE = 1
#: The largest descriptor value this format version defines. Anything above it is reserved.
MODULATION_DEFINED_MAX = MODULATION_OCTAVE_PULSE
#: The byte the MADS exporter writes when a descriptor is not one this format version defines.
MODULATION_UNSUPPORTED = 0xFF

MODULATION_DESCRIPTIONS = {
    MODULATION_NONE: "no modulation",
    MODULATION_OCTAVE_PULSE: "octave pulse (N / N//2 every frame)",
}


def describe_modulation(descriptor: int) -> str:
    """Human-readable name of a modulation descriptor, for reports and error messages."""
    return MODULATION_DESCRIPTIONS.get(
        int(descriptor), f"undefined modulation descriptor ${int(descriptor) & 0xFF:02X}"
    )


def octave_pulse_divider(nominal: int, frame_offset: int) -> int:
    """C1's divider for one frame inside a note: ``N`` on even offsets, ``N // 2`` on odd.

    This is the single statement of the rule in Python. The 6502 player computes the same
    thing with ``lsr``, which is ``// 2`` for every value in ``0..255``, so the two cannot
    disagree about a *value* — only about where the alternation restarts, and both restart it
    on the note's first frame (see ``apply_modulation`` in ``player.asm``).

    ``nominal`` is already clamped to the tracker range by :func:`clamp_audf_for_tracker`, and
    ``N // 2`` of a value in ``0..254`` is in ``0..127``, so nothing here can fall out of range.
    The octave is exact when ``N`` is odd; for even ``N`` it is flat by up to ~12 cents at the
    bottom of the range, which is the behaviour Experiment 26/27 established and not a rounding
    bug (see ``docs/c1_player_extension_design.md`` §2.4).
    """
    value = int(nominal)
    return value if int(frame_offset) % 2 == 0 else value // 2


def is_octave_pulse(descriptor: int) -> bool:
    """True when a modulation descriptor is the one this format version defines."""
    return int(descriptor) == MODULATION_OCTAVE_PULSE



def _base_clock_hz(audctl: int) -> float:
    return PAL_15KHZ_CLOCK if (audctl & AUDCTL_15KHZ) else PAL_64KHZ_CLOCK


def describe_audctl(audctl: int) -> str:
    """Human-readable description of an AUDCTL byte.

    Used wherever a value is printed (export headers, binding reports) so a comment can
    never claim a configuration the data does not implement.
    """
    audctl = int(audctl) & 0xFF
    parts: List[str] = []
    if audctl & AUDCTL_JOIN_1_2_16BIT:
        clock = "1.79 MHz" if audctl & AUDCTL_CH1_179MHZ else "64 kHz"
        parts.append(f"16-bit pair Ch1+Ch2 at {clock}")
    elif audctl & AUDCTL_JOIN_3_4_16BIT:
        clock = "1.79 MHz" if audctl & AUDCTL_CH3_179MHZ else "64 kHz"
        parts.append(f"16-bit pair Ch3+Ch4 at {clock}")
    else:
        parts.append("4 independent 8-bit channels")
    if audctl & AUDCTL_15KHZ:
        parts.append("15 kHz base clock")
    if not (audctl & AUDCTL_JOIN_1_2_16BIT) and (audctl & AUDCTL_CH1_179MHZ):
        parts.append("Ch1 at 1.79 MHz")
    if not (audctl & AUDCTL_JOIN_3_4_16BIT) and (audctl & AUDCTL_CH3_179MHZ):
        parts.append("Ch3 at 1.79 MHz")
    if audctl & AUDCTL_HIPASS_CH1_CH3:
        parts.append("Ch1 high-pass clocked by Ch3")
    if audctl & AUDCTL_HIPASS_CH2_CH4:
        parts.append("Ch2 high-pass clocked by Ch4")
    if audctl & AUDCTL_9BIT_POLY:
        parts.append("9-bit poly noise")
    return ", ".join(parts)


def _uses_hs_clock(audctl: int, channel: int) -> bool:
    """True if the channel is clocked from the CPU clock (1.79 MHz PAL).

    Only channel 1 (AUDCTL bit 6) and channel 3 (AUDCTL bit 5) have their own
    high-speed clock source; channels 2/4 are either joined to their partner or
    run from the base clock.
    """
    if channel == 1:
        return bool(audctl & AUDCTL_CH1_179MHZ)
    if channel == 3:
        return bool(audctl & AUDCTL_CH3_179MHZ)
    return False


def _pair_uses_hs_clock(audctl: int, channel: int) -> bool:
    """High-speed clock of a joined pair: bit 6 for CH1+CH2, bit 5 for CH3+CH4."""
    if channel == 3:
        return bool(audctl & AUDCTL_CH3_179MHZ)
    return bool(audctl & AUDCTL_CH1_179MHZ)


def hz_from_audf_8bit(audf: int, audctl: int = 0, channel: int = 1) -> float:
    """Effective frequency of a single (non-joined) channel."""
    if _uses_hs_clock(audctl, channel):
        return PAL_CLOCK_HZ / (2.0 * (audf + 4))
    return _base_clock_hz(audctl) / (2.0 * (audf + 1))


def hz_from_audf_16bit(divider: int, audctl: int = 0, channel: int = 1) -> float:
    """Effective frequency of a joined 16-bit pair (N = AUDF_lsb | AUDF_msb<<8).

    ``channel`` selects the pair: 1 for CH1+CH2, 3 for CH3+CH4.
    """
    if _pair_uses_hs_clock(audctl, channel):
        return PAL_CLOCK_HZ / (2.0 * (divider + 7))
    return _base_clock_hz(audctl) / (2.0 * (divider + 1))


def raw_audf_8bit(freq_hz: float, audctl: int = 0, channel: int = 1) -> int:
    """Unclamped 8-bit divider (may fall outside 0..255)."""
    if freq_hz <= 0:
        return AUDF_MAX_8BIT
    if _uses_hs_clock(audctl, channel):
        return int(round(PAL_CLOCK_HZ / (2.0 * freq_hz))) - 4
    return int(round(_base_clock_hz(audctl) / (2.0 * freq_hz))) - 1


def audf_from_hz_8bit(freq_hz: float, audctl: int = 0, channel: int = 1) -> int:
    """Inverse of :func:`hz_from_audf_8bit`, clamped to 0..255."""
    return max(AUDF_MIN, min(AUDF_MAX_8BIT, raw_audf_8bit(freq_hz, audctl, channel)))


def eight_bit_floor_hz(audctl: int = 0, channel: int = 1) -> float:
    """Lowest frequency the tracker can encode in 8-bit mode (AUDF = AUDF_TRACKER_MAX)."""
    return hz_from_audf_8bit(AUDF_TRACKER_MAX, audctl, channel)


def describe_8bit_range_error(
    freq_hz: float, audctl: int = 0, channel: int = 1
) -> Optional[Dict[str, Any]]:
    """Diagnostics when ``freq_hz`` is below the 8-bit encodable range, else ``None``.

    Distinguishes a genuine out-of-range request from ordinary AUDF rounding: only
    frequencies whose unclamped divider exceeds :data:`AUDF_TRACKER_MAX` are reported.
    """
    if freq_hz <= 0:
        return None
    divider = raw_audf_8bit(freq_hz, audctl, channel)
    if divider <= AUDF_TRACKER_MAX:
        return None
    representable = hz_from_audf_8bit(AUDF_TRACKER_MAX, audctl, channel)
    cents = 1200.0 * math.log2(representable / freq_hz) if representable > 0 else 0.0
    return {
        "mode": "8-bit",
        "requested_hz": round(freq_hz, 3),
        "divider": divider,
        "representable_hz": round(representable, 3),
        "cents": round(cents, 1),
    }


# ---------------------------------------------------------------------------
# Unpitched percussion
# ---------------------------------------------------------------------------
#
# A percussion note with no resolvable pitch is a real drum hit: not a rest, and not
# an implicit MIDI 60. The WAV frame compiler and the MADS exporter both use this
# explicit fallback divider so the two outputs stay identical.
PERCUSSION_DEFAULT_AUDF = 0x50


def is_unpitched_percussion(midi_pitch: Optional[int], channel_role: str) -> bool:
    """True for a percussion hit that carries no resolvable pitch."""
    return midi_pitch is None and channel_role == "percussion"


def audf16_from_hz(freq_hz: float, audctl: int = 0, channel: int = 1) -> int:
    """Inverse of :func:`hz_from_audf_16bit`, clamped to 0..65535."""
    if freq_hz <= 0:
        return AUDF_MAX_16BIT
    if _pair_uses_hs_clock(audctl, channel):
        divider = int(round(PAL_CLOCK_HZ / (2.0 * freq_hz))) - 7
    else:
        divider = int(round(_base_clock_hz(audctl) / (2.0 * freq_hz))) - 1
    return max(0, min(AUDF_MAX_16BIT, divider))


def split_audf16(divider: int) -> tuple[int, int]:
    """Split a 16-bit divider into (AUDF_lsb, AUDF_msb)."""
    divider = max(0, min(AUDF_MAX_16BIT, int(divider)))
    return divider & 0xFF, (divider >> 8) & 0xFF


# ---------------------------------------------------------------------------
# Player ADSR envelope model
# ---------------------------------------------------------------------------

def player_envelope_volumes(
    note_len_frames: int,
    frames_per_tick: int,
    peak_vol: int,
    attack: int,
    decay: int,
    sustain: int,
    release: int,
) -> List[int]:
    """Reproduce ``player.asm``'s ``update_envelopes`` state machine, one value per frame.

    Matches the Phase-1 fixed 6502 ADSR state machine frame-for-frame using the
    exact same integer arithmetic:

    * attack  : linear multi-step integer ramp across ``attack`` VBI frames:
                ``max(1, (env_frame * peak_vol) // attack)`` for ``env_frame < attack``,
                reaching ``peak_vol`` at ``env_frame == attack`` (or immediately if ``attack <= 1``).
    * decay   : linear multi-step integer ramp from ``peak_vol`` down to
                ``eff_sustain = min(peak_vol, sustain)`` across ``decay`` VBI frames:
                ``peak_vol - ((env_frame * (peak_vol - eff_sustain)) // decay)``.
                Zero-frame decay enters Sustain immediately without emitting an extra hold frame.
    * sustain : holds ``eff_sustain`` stably until remaining VBI frames
                ``(ticks_remaining - 1) * frames_per_tick + tick_counter <= release``.
    * release : linear ``-1`` per VBI frame towards ``0``.
    """
    if note_len_frames <= 0:
        return []
    peak_vol = max(0, min(15, int(peak_vol)))
    if peak_vol == 0:
        return [0] * int(note_len_frames)
    attack = max(0, int(attack))
    decay = max(0, int(decay))
    sustain = min(peak_vol, max(0, min(15, int(sustain))))
    release = max(0, int(release))
    fpt = max(1, int(frames_per_tick))
    total_ticks = max(1, int(math.ceil(note_len_frames / fpt)))

    volumes: List[int] = []
    phase = 1          # 1=attack, 2=decay, 3=sustain, 4=release
    env_frame = 0
    cur = 0
    for i in range(note_len_frames):
        ticks_remaining = max(1, total_ticks - (i // fpt))
        tick_counter = fpt - (i % fpt)
        frames_remaining = (ticks_remaining - 1) * fpt + tick_counter
        if phase == 1:  # attack
            if attack == 0:
                phase, env_frame, cur = 2, 0, peak_vol
            else:
                env_frame += 1
                if env_frame < attack:
                    cur = max(1, (env_frame * peak_vol) // attack)
                else:
                    phase, env_frame, cur = 2, 0, peak_vol
        elif phase == 2:  # decay
            if decay == 0:
                phase = 3
            else:
                env_frame += 1
                if env_frame < decay:
                    cur = peak_vol - ((env_frame * (peak_vol - sustain)) // decay)
                else:
                    phase = 3
        if phase == 3:  # sustain (runs on entry from decay or while sustaining)
            cur = sustain
            if release > 0 and frames_remaining <= release:
                phase = 4
        if phase == 4:  # release (runs on entry from sustain or while releasing)
            if cur > 0:
                cur -= 1
        volumes.append(max(0, min(15, cur)))
    return volumes

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
    AUDCTL_CH1_179MHZ,
    AUDCTL_CH3_179MHZ,
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


def _base_clock_hz(audctl: int) -> float:
    return PAL_15KHZ_CLOCK if (audctl & AUDCTL_15KHZ) else PAL_64KHZ_CLOCK


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

    The 6502 player does NOT implement a multi-step ramp:

    * attack  : volume jumps to ``(peak >> 1) | 1`` and stays there until the last
                attack frame, then jumps to ``peak`` (2 discrete levels).
    * decay   : volume jumps immediately to ``sustain`` (no slope; ``decay`` only
                delays the transition to the sustain phase).
    * sustain : holds ``sustain``.
    * release : linear ``-1`` per frame, triggered when the remaining note length
                (measured in row ticks) drops *below* ``release`` — the player uses
                ``ch_dur < ch_rel`` (strict), verified frame-by-frame against
                ``player.asm`` under a 6502 emulator.

    The WAV preview uses this function so the rendered envelope matches what the
    Atari player will actually produce.
    """
    peak_vol = max(0, min(15, int(peak_vol)))
    attack = max(0, int(attack))
    decay = max(0, int(decay))
    sustain = max(0, min(15, int(sustain)))
    release = max(0, int(release))
    fpt = max(1, int(frames_per_tick))
    total_ticks = max(1, int(math.ceil(note_len_frames / fpt)))

    volumes: List[int] = []
    phase = 1          # 1=attack, 2=decay, 3=sustain, 4=release
    env_frame = 0
    cur = 0
    for i in range(note_len_frames):
        if phase == 1:  # attack
            if attack == 0:
                phase, env_frame, cur = 2, 0, peak_vol
            else:
                env_frame += 1
                if env_frame < attack:
                    cur = (peak_vol >> 1) | 1
                else:
                    phase, env_frame, cur = 2, 0, peak_vol
        elif phase == 2:  # decay
            if decay == 0:
                phase, cur = 3, sustain
            else:
                env_frame += 1
                if env_frame < decay:
                    cur = sustain
                else:
                    phase, cur = 3, sustain
        elif phase == 3:  # sustain
            cur = sustain
            ticks_remaining = total_ticks - (i // fpt)
            if ticks_remaining < release:
                phase = 4
        else:  # release
            if cur > 0:
                cur -= 1
        volumes.append(cur)
    return volumes

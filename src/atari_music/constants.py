"""Atari 8-bit and POKEY Hardware Constants."""

from __future__ import annotations

# System Clocks
PAL_CLOCK_HZ: float = 1773447.0
NTSC_CLOCK_HZ: float = 1789772.0

PAL_64KHZ_CLOCK: float = PAL_CLOCK_HZ / 28.0   # ~63920.89 Hz
PAL_15KHZ_CLOCK: float = PAL_CLOCK_HZ / 114.0  # ~15696.0 Hz

# POKEY Audio Register Names in standard dump order
POKEY_REGS = [
    "AUDF1", "AUDC1",
    "AUDF2", "AUDC2",
    "AUDF3", "AUDC3",
    "AUDF4", "AUDC4",
    "AUDCTL",
]

# Distortion / Noise Modes — hardware-accurate (AUDC bits 5..7).
#
# Verified against two independent reference emulators: atari800 `pokeysnd.c`
# (Ron Fries) and `mzpokeysnd.c` (Borisov / Nikiel). Both decode AUDC bits as:
#
#   bit7 NOTPOLY5 = 1:  bit5 PURETONE=1 -> pure tone
#                       else bit6 POLY4=1 -> poly4
#                       else              -> poly9/poly17 (noise)
#   bit7 NOTPOLY5 = 0:  bit5 PURETONE=1 -> poly5-gated pure tone
#                       else bit6 POLY4=1 -> poly5-gated poly4
#                       else              -> poly5-gated poly9/poly17
#
# Consequences that matter for this project:
#   * $A0 and $E0 are AUDIBLY IDENTICAL (PURETONE outranks POLY4) -> both pure tone.
#     POKEY has NO white-noise mode at $E0.
#   * $20 and $60 are AUDIBLY IDENTICAL (both poly5-gated pure tone).
#   * $80 is the ONLY true ungated noise mode (poly9/poly17 direct).
DISTORTION_5_AND_17BIT = 0x00   # poly5-gated poly9/17 (gated noise)
DISTORTION_5BIT_POLY_1 = 0x20   # poly5-gated pure tone
DISTORTION_5_AND_4BIT = 0x40    # poly5-gated poly4
DISTORTION_5BIT_POLY_2 = 0x60   # poly5-gated pure tone (== $20)
DISTORTION_WHITE_NOISE = 0x80   # poly9/poly17 direct — the real noise mode
DISTORTION_17BIT_ONLY = 0x80    # legacy alias of DISTORTION_WHITE_NOISE
DISTORTION_PURE_TONE = 0xA0     # pure tone (clean square)
DISTORTION_4BIT_POLY = 0xC0     # poly4 direct (15-step buzz)
DISTORTION_PURE_TONE_ALT = 0xE0  # pure tone (== $A0)

# AUDC bit masks
AUDC_VOLUME_MASK = 0x0F
AUDC_VOLUME_ONLY = 0x10
AUDC_PURETONE = 0x20
AUDC_POLY4 = 0x40
AUDC_NOTPOLY5 = 0x80

DISTORTION_DESCRIPTIONS = {
    0x00: "poly5-gated poly9/17 (gated noise)",
    0x20: "poly5-gated pure tone (buzzy)",
    0x40: "poly5-gated poly4",
    0x60: "poly5-gated pure tone (== $20)",
    0x80: "poly9/17 direct (ungated noise)",
    0xA0: "pure tone (clean square)",
    0xC0: "poly4 direct (15-step buzz)",
    0xE0: "pure tone (== $A0)",
}

# AUDCTL Control Bits
AUDCTL_15KHZ = 0x01           # Bit 0: 15 kHz clock instead of 64 kHz
AUDCTL_HIPASS_CH2_CH4 = 0x02  # Bit 1: High-pass filter Ch 2 clocked by Ch 4
AUDCTL_HIPASS_CH1_CH3 = 0x04  # Bit 2: High-pass filter Ch 1 clocked by Ch 3
AUDCTL_JOIN_3_4_16BIT = 0x08  # Bit 3: Ch 3 & Ch 4 joined for 16-bit
AUDCTL_JOIN_1_2_16BIT = 0x10  # Bit 4: Ch 1 & Ch 2 joined for 16-bit
AUDCTL_CH3_179MHZ = 0x20      # Bit 5: Ch 3 clocked by 1.77/1.79 MHz
AUDCTL_CH1_179MHZ = 0x40      # Bit 6: Ch 1 clocked by 1.77/1.79 MHz
AUDCTL_9BIT_POLY = 0x80       # Bit 7: 9-bit poly noise instead of 17-bit

# Note Names
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

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

# Distortion / Noise Modes (AUDC bits 5..7: 0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0)
DISTORTION_PURE_TONE = 0xA0
DISTORTION_WHITE_NOISE = 0xE0
DISTORTION_4BIT_POLY = 0xC0
DISTORTION_5BIT_POLY_1 = 0x20
DISTORTION_5BIT_POLY_2 = 0x60
DISTORTION_5_AND_4BIT = 0x40
DISTORTION_5_AND_17BIT = 0x00
DISTORTION_17BIT_ONLY = 0x80

DISTORTION_DESCRIPTIONS = {
    0x00: "5-bit + 17-bit poly (buzzy rumble / bass)",
    0x20: "5-bit poly (metallic gritty lead/bass)",
    0x40: "5-bit + 4-bit poly (flute/buzz)",
    0x60: "5-bit poly (metallic lead)",
    0x80: "17-bit poly (deep noise)",
    0xA0: "Pure Tone (clean melodic square wave)",
    0xC0: "4-bit poly (smooth buzz / chiptune lead/snare)",
    0xE0: "17-bit / 9-bit white noise (hi-hat / cymbal / drum)",
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

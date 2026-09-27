"""Visualization Suite for Atari 8-bit POKEY Music.

Generates comprehensive multi-panel graphical dashboards:
Piano roll, channel volume dynamics, distortion/timbre map,
hardware AUDCTL routing, and structural pattern boundaries.
Also renders validation audio WAV files.
"""

from __future__ import annotations

import gzip
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
import numpy as np

from atari_music.constants import (
    AUDCTL_15KHZ,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
    DISTORTION_4BIT_POLY,
    POKEY_REGS,
)
from atari_music.events import parse_dump_tokens
from atari_music.features import interpret_voice_state, midi_to_note_name
from atari_music.models import ChannelVoiceState, DatasetRecord


CHANNEL_COLORS = [
    "#1f77b4",  # CH1: Blue
    "#2ca02c",  # CH2: Green
    "#ff7f0e",  # CH3: Orange
    "#d62728",  # CH4: Red
    "#9467bd",  # CH5: Purple (Stereo)
    "#8c564b",  # CH6: Brown (Stereo)
    "#e377c2",  # CH7: Pink (Stereo)
    "#7f7f7f",  # CH8: Gray (Stereo)
]

DISTORTION_COLORS = {
    0xA0: "#00d2d3",  # Pure Tone: Cyan
    0xC0: "#5f27cd",  # 4-bit Poly: Purple
    0xE0: "#8395a7",  # White noise: Gray
    0x20: "#ff9f43",  # 5-bit Poly: Amber
    0x60: "#ee5253",  # 5-bit Poly: Red/Orange
    0x00: "#341f97",  # 17-bit: Dark Navy
    0x80: "#222f3e",  # 17-bit: Deep Black/Blue
}


def render_audio_wav(
    sap_path: Path,
    subsong: int,
    output_wav_path: Path,
    max_duration_sec: float = 20.0,
    asapconv_bin: str = r"C:\Program Files\ASAP\asapconv.exe",
) -> bool:
    """Render short WAV audio file from SAP for auditory validation."""
    if not os.path.exists(asapconv_bin):
        return False

    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    mins = int(max_duration_sec // 60)
    secs = int(max_duration_sec % 60)
    time_str = f"{mins:02d}:{secs:02d}"

    try:
        res = subprocess.run(
            [asapconv_bin, "-s", str(subsong), "-t", time_str, "-o", str(output_wav_path), str(sap_path)],
            capture_output=True,
            timeout=10,
        )
        return res.returncode == 0 and output_wav_path.exists()
    except Exception:
        return False


def generate_song_dashboard(
    record: DatasetRecord,
    dataset_dir: Path,
    output_dir: Path,
    max_frames: int = 1500,  # ~30 seconds of playback for ultra-clear resolution
) -> Path:
    """Render comprehensive 4-panel visual dashboard for an individual track."""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = Path(record.raw_dump_path)

    times_sec: List[float] = []
    audctls0: List[int] = []
    audctls1: List[int] = []
    voices_history: List[List[ChannelVoiceState]] = []

    num_channels = 8 if record.meta.is_stereo else 4

    with gzip.open(raw_path, "rt", encoding="ascii") as f:
        frame_idx = 0
        for line in f:
            parsed = parse_dump_tokens(line)
            if not parsed:
                continue
            time_sec, p0, p1 = parsed
            times_sec.append(time_sec)
            audctl0 = p0[8]
            audctls0.append(audctl0)

            frame_voices = []
            for ch in range(1, 5):
                audf = p0[(ch - 1) * 2]
                audc = p0[(ch - 1) * 2 + 1]
                pair_low = p0[0] if ch == 2 else (p0[4] if ch == 4 else None)
                v = interpret_voice_state(ch, 0, audf, audc, audctl0, pair_low)
                frame_voices.append(v)

            if p1 is not None:
                audctl1 = p1[8]
                audctls1.append(audctl1)
                for ch in range(1, 5):
                    audf = p1[(ch - 1) * 2]
                    audc = p1[(ch - 1) * 2 + 1]
                    pair_low = p1[0] if ch == 2 else (p1[4] if ch == 4 else None)
                    v = interpret_voice_state(ch, 1, audf, audc, audctl1, pair_low)
                    frame_voices.append(v)

            voices_history.append(frame_voices)
            frame_idx += 1
            if frame_idx >= max_frames:
                break

    if not times_sec:
        return output_dir / f"{record.id}_dashboard.png"

    # Set up multi-panel Matplotlib figure
    fig = plt.figure(figsize=(16, 12), dpi=120)
    gs = fig.add_gridspec(4, 1, height_ratios=[3.0, 1.8, 1.4, 1.0], hspace=0.30)

    ax_piano = fig.add_subplot(gs[0])
    ax_volume = fig.add_subplot(gs[1], sharex=ax_piano)
    ax_dist = fig.add_subplot(gs[2], sharex=ax_piano)
    ax_ctl = fig.add_subplot(gs[3], sharex=ax_piano)

    max_t = times_sec[-1]
    title_str = (
        f"{record.meta.title or 'Unknown'} (Subsong {record.meta.subsong_index}) — {record.meta.author or 'Unknown'}\n"
        f"Category: {record.analysis.music_category.upper()} | Rate: {record.meta.playback_rate_hz} Hz | "
        f"16-bit: {record.features.uses_16bit} | Repetition: {record.analysis.repetition_ratio*100:.1f}%"
    )
    fig.suptitle(title_str, fontsize=13, fontweight="bold", y=0.98)

    # 1. PIANO ROLL
    ax_piano.set_title("1. Melodic Piano Roll (POKEY Voices, Pitch & Register Mapping)", fontsize=11, loc="left", fontweight="bold")
    ax_piano.set_ylabel("MIDI Pitch (Semitones)")
    ax_piano.grid(True, linestyle="--", alpha=0.3)

    min_plotted_pitch = 127
    max_plotted_pitch = 0
    has_notes = False

    for ch_idx in range(num_channels):
        p_ch = ch_idx % 4 + 1
        color = CHANNEL_COLORS[ch_idx]
        for f_idx, t in enumerate(times_sec):
            v = voices_history[f_idx][ch_idx]
            if v.is_active and v.midi_pitch is not None and not v.is_noise:
                has_notes = True
                p = v.midi_pitch
                min_plotted_pitch = min(min_plotted_pitch, int(p))
                max_plotted_pitch = max(max_plotted_pitch, int(p))
                dt = 0.02
                lw = max(1.5, (v.volume / 15.0) * 4.5)
                ax_piano.plot([t, t + dt], [p, p], color=color, linewidth=lw, solid_capstyle="butt")

    if has_notes:
        ax_piano.set_ylim(max(12, min_plotted_pitch - 3), min(120, max_plotted_pitch + 4))
        yticks = range(max(12, min_plotted_pitch - 2), min(120, max_plotted_pitch + 4), 6)
        ax_piano.set_yticks(yticks)
        ax_piano.set_yticklabels([f"{midi_to_note_name(y)} ({y})" for y in yticks])
    else:
        ax_piano.set_ylim(20, 80)
        ax_piano.text(max_t / 2, 50, "No standard melodic pitches detected (Noise / DAC Samples / Arpeggio sweep)", ha="center", fontsize=11, color="red")

    # Add bar repeat lines
    bar_frames = 16
    for b in range(0, len(times_sec), bar_frames * 2):
        ax_piano.axvline(times_sec[b], color="gray", linestyle=":", alpha=0.35)

    # 2. VOLUME ENVELOPES (ADSR Dynamic Changes)
    ax_volume.set_title("2. Channel Volume Envelopes (Software ADSR / Modulation co 20 ms)", fontsize=11, loc="left", fontweight="bold")
    ax_volume.set_ylabel("Volume (0-15)")
    ax_volume.set_ylim(-0.5, 16.0)
    ax_volume.set_yticks([0, 4, 8, 12, 15])
    ax_volume.grid(True, linestyle="--", alpha=0.3)

    for ch_idx in range(num_channels):
        vols = [voices_history[f][ch_idx].volume for f in range(len(times_sec))]
        label = f"CH{ch_idx + 1}"
        ax_volume.plot(times_sec, vols, color=CHANNEL_COLORS[ch_idx], label=label, linewidth=1.2, alpha=0.85)

    ax_volume.legend(loc="upper right", ncol=min(num_channels, 8), fontsize=9)

    # 3. DISTORTION / TIMBRE MAP
    ax_dist.set_title("3. Timbre & Noise Generator Distribution (AUDC upper bits)", fontsize=11, loc="left", fontweight="bold")
    ax_dist.set_ylabel("Channel")
    ax_dist.set_yticks(range(num_channels))
    ax_dist.set_yticklabels([f"CH{i+1}" for i in range(num_channels)])
    ax_dist.set_ylim(-0.6, num_channels - 0.4)

    for ch_idx in range(num_channels):
        for f_idx, t in enumerate(times_sec):
            v = voices_history[f_idx][ch_idx]
            if v.is_active:
                d = v.distortion
                col = DISTORTION_COLORS.get(d, "#bdc3c7")
                ax_dist.plot([t, t + 0.02], [ch_idx, ch_idx], color=col, linewidth=4.0, solid_capstyle="butt")

    # Legend for distortions
    dist_patches = [
        mpatches.Patch(color=DISTORTION_COLORS[0xA0], label="Pure Tone $A0"),
        mpatches.Patch(color=DISTORTION_COLORS[0xC0], label="4-bit Poly $C0 (Lead/Snare)"),
        mpatches.Patch(color=DISTORTION_COLORS[0xE0], label="Noise $E0 (Cymbals/Drums)"),
        mpatches.Patch(color=DISTORTION_COLORS[0x20], label="5-bit Poly $20 (Metallic Bass)"),
        mpatches.Patch(color=DISTORTION_COLORS[0x00], label="17-bit $00/$80"),
    ]
    ax_dist.legend(handles=dist_patches, loc="upper right", ncol=5, fontsize=8)

    # 4. AUDCTL HARDWARE ROUTING
    ax_ctl.set_title("4. AUDCTL Hardware Routing & 16-bit Pairing Flags", fontsize=11, loc="left", fontweight="bold")
    ax_ctl.set_xlabel("Time (seconds)")
    ax_ctl.set_ylabel("Features")
    ax_ctl.set_yticks([0, 1, 2, 3])
    ax_ctl.set_yticklabels(["16-bit (1+2)", "16-bit (3+4)", "15 kHz Clock", "High-Pass"])
    ax_ctl.set_ylim(-0.5, 3.5)

    is_16_12 = [(c & AUDCTL_JOIN_1_2_16BIT) > 0 for c in audctls0]
    is_16_34 = [(c & AUDCTL_JOIN_3_4_16BIT) > 0 for c in audctls0]
    is_15k = [(c & AUDCTL_15KHZ) > 0 for c in audctls0]
    is_hp = [(c & (AUDCTL_HIPASS_CH1_CH3 | AUDCTL_HIPASS_CH2_CH4)) > 0 for c in audctls0]

    for f_idx, t in enumerate(times_sec):
        if is_16_12[f_idx]: ax_ctl.plot([t, t + 0.02], [0, 0], color="#e74c3c", linewidth=5)
        if is_16_34[f_idx]: ax_ctl.plot([t, t + 0.02], [1, 1], color="#e67e22", linewidth=5)
        if is_15k[f_idx]:   ax_ctl.plot([t, t + 0.02], [2, 2], color="#27ae60", linewidth=5)
        if is_hp[f_idx]:    ax_ctl.plot([t, t + 0.02], [3, 3], color="#2980b9", linewidth=5)

    ax_piano.set_xlim(0, max_t)

    out_img = output_dir / f"{record.id}_dashboard.png"
    plt.savefig(out_img, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return out_img

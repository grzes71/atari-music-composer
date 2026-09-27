"""Multi-Level Pattern Discovery and Structural Evaluation.

Compares four representation levels for discovery of musical structure:
LEVEL 1: Raw POKEY register state
LEVEL 2: Pitch + duration
LEVEL 3: Pitch + duration + distortion (timbre)
LEVEL 4: Channel musical role + pitch + rhythm
"""

from __future__ import annotations

import gzip
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from atari_music.classifier import classify_channel_activity
from atari_music.constants import POKEY_REGS
from atari_music.events import parse_dump_tokens
from atari_music.features import interpret_voice_state
from atari_music.models import ChannelVoiceState, DatasetRecord


def evaluate_pattern_levels(
    record: DatasetRecord,
    dataset_dir: Path,
    bar_frames: int = 16,
) -> Dict[str, Any]:
    """Compare pattern discovery metrics across 4 levels of representation."""
    raw_path = Path(record.raw_dump_path)
    if not raw_path.exists():
        return {}

    times_sec: List[float] = []
    p0_history: List[List[int]] = []
    voices_history: List[List[ChannelVoiceState]] = []

    with gzip.open(raw_path, "rt", encoding="ascii") as f:
        for line in f:
            parsed = parse_dump_tokens(line)
            if not parsed:
                continue
            time_sec, p0, p1 = parsed
            times_sec.append(time_sec)
            p0_history.append(list(p0))

            frame_voices = []
            audctl0 = p0[8]
            for ch in range(1, 5):
                audf = p0[(ch - 1) * 2]
                audc = p0[(ch - 1) * 2 + 1]
                pair_low = p0[0] if ch == 2 else (p0[4] if ch == 4 else None)
                v = interpret_voice_state(ch, 0, audf, audc, audctl0, pair_low)
                frame_voices.append(v)
            voices_history.append(frame_voices)

    total_frames = len(times_sec)
    if total_frames < bar_frames:
        return {}

    total_bars = total_frames // bar_frames

    # Determine channel roles for Level 4
    num_channels = 4
    channel_roles = []
    is_16_joined = (record.features.uses_16bit)
    for ch in range(num_channels):
        timeline = [voices_history[f][ch] for f in range(total_frames)]
        role, _ = classify_channel_activity(timeline, ch + 1, is_16_joined and ch in (0, 1))
        channel_roles.append(role)

    # 1. LEVEL 1: RAW POKEY state tokens
    l1_signatures = []
    for b in range(total_bars):
        start = b * bar_frames
        end = start + bar_frames
        tokens = [tuple(p0_history[f]) for f in range(start, end)]
        l1_signatures.append(hash(tuple(tokens)))

    # 2. LEVEL 2: Pitch + duration tokens
    l2_signatures = []
    for b in range(total_bars):
        start = b * bar_frames
        end = start + bar_frames
        tokens = []
        for f in range(start, end):
            f_tokens = []
            for ch in range(num_channels):
                v = voices_history[f][ch]
                f_tokens.append(v.note if v.is_active and not v.is_noise else "SIL")
            tokens.append(tuple(f_tokens))
        l2_signatures.append(hash(tuple(tokens)))

    # 3. LEVEL 3: Pitch + duration + distortion
    l3_signatures = []
    for b in range(total_bars):
        start = b * bar_frames
        end = start + bar_frames
        tokens = []
        for f in range(start, end):
            f_tokens = []
            for ch in range(num_channels):
                v = voices_history[f][ch]
                if v.is_active:
                    f_tokens.append((v.note or "NOISE", v.distortion))
                else:
                    f_tokens.append(("SIL", 0))
            tokens.append(tuple(f_tokens))
        l3_signatures.append(hash(tuple(tokens)))

    # 4. LEVEL 4: Channel role + pitch + rhythm
    l4_signatures = []
    for b in range(total_bars):
        start = b * bar_frames
        end = start + bar_frames
        tokens = []
        for f in range(start, end):
            f_tokens = []
            for ch in range(num_channels):
                v = voices_history[f][ch]
                r_name = channel_roles[ch]
                if v.is_active:
                    f_tokens.append((r_name, v.note if r_name in ("melody", "bass") else "PERC"))
                else:
                    f_tokens.append((r_name, "OFF"))
            tokens.append(tuple(f_tokens))
        l4_signatures.append(hash(tuple(tokens)))

    u1 = len(set(l1_signatures))
    u2 = len(set(l2_signatures))
    u3 = len(set(l3_signatures))
    u4 = len(set(l4_signatures))

    rep1 = round(1.0 - (u1 / total_bars), 3)
    rep2 = round(1.0 - (u2 / total_bars), 3)
    rep3 = round(1.0 - (u3 / total_bars), 3)
    rep4 = round(1.0 - (u4 / total_bars), 3)

    return {
        "total_bars": total_bars,
        "channel_roles": channel_roles,
        "level1_raw": {"unique_patterns": u1, "repetition_ratio": max(0.0, rep1)},
        "level2_pitch": {"unique_patterns": u2, "repetition_ratio": max(0.0, rep2)},
        "level3_pitch_dist": {"unique_patterns": u3, "repetition_ratio": max(0.0, rep3)},
        "level4_role_pitch_rhythm": {"unique_patterns": u4, "repetition_ratio": max(0.0, rep4)},
    }

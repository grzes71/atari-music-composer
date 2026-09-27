"""POKEY Register Dump & Event Extractor (Proof of Concept).

Extracts cycle-accurate POKEY register events and frames from SAP files
using asapscan backend. Captures per-frame state, register deltas,
channel activity, and stereo configurations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


POKEY_REGS = [
    "AUDF1", "AUDC1",
    "AUDF2", "AUDC2",
    "AUDF3", "AUDC3",
    "AUDF4", "AUDC4",
    "AUDCTL",
]


@dataclass
class ChannelState:
    audf: int
    audc: int
    volume: int
    distortion: int
    is_active: bool


@dataclass
class FrameEvent:
    frame: int
    time_ms: float
    time_sec: float
    # Current full state of POKEY 1
    pokey1: Dict[str, int]
    # Current full state of POKEY 2 (if stereo)
    pokey2: Optional[Dict[str, int]]
    # Only the registers that changed this frame
    deltas1: Dict[str, int]
    deltas2: Optional[Dict[str, int]]
    # Active voice count
    active_channels_count: int


@dataclass
class ExtractionResult:
    song_path: str
    filename: str
    title: Optional[str]
    author: Optional[str]
    subsong: int
    is_stereo: bool
    playback_rate_hz: float
    total_frames: int
    duration_ms: float
    features_detected: List[str]
    unique_states_count: int
    frames: List[FrameEvent]


def parse_dump_line(line: str) -> Optional[Tuple[float, List[int], Optional[List[int]]]]:
    """Parse one output line from asapscan -d.
    
    Example mono:
      0.04: 61 00  67 AC  00 00  00 00  78
    Example stereo:
      0.00: 0E C4  00 A5  00 A4  01 10  02  |  0E C4  00 A5  00 A4  01 10  00
    """
    line = line.strip()
    if not line or ":" not in line:
        return None

    time_part, regs_part = line.split(":", 1)
    try:
        time_sec = float(time_part.strip())
    except ValueError:
        return None

    if "|" in regs_part:
        part1, part2 = regs_part.split("|", 1)
        tokens1 = [int(tok, 16) for tok in part1.split() if tok]
        tokens2 = [int(tok, 16) for tok in part2.split() if tok]
        if len(tokens1) == 9 and len(tokens2) == 9:
            return time_sec, tokens1, tokens2
    else:
        tokens1 = [int(tok, 16) for tok in regs_part.split() if tok]
        if len(tokens1) == 9:
            return time_sec, tokens1, None

    return None


def get_detected_features(asapscan_bin: str, sap_path: str) -> List[str]:
    """Run asapscan -f to query special POKEY hardware features."""
    try:
        res = subprocess.run([asapscan_bin, "-f", sap_path], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    except Exception:
        pass
    return []


def extract_pokey_timeline(
    sap_path: str,
    asapscan_bin: str,
    subsong: int = 0,
    max_frames: Optional[int] = None,
    max_seconds: Optional[float] = None,
) -> ExtractionResult:
    """Run asapscan -d and parse POKEY registers frame-by-frame into structured timeline."""
    cmd = [asapscan_bin, "-d", "-s", str(subsong), sap_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    frames: List[FrameEvent] = []
    prev_regs1 = [-1] * 9
    prev_regs2 = [-1] * 9
    unique_states = set()
    is_stereo = False

    frame_idx = 0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            parsed = parse_dump_line(line)
            if not parsed:
                continue

            time_sec, regs1, regs2 = parsed
            time_ms = round(time_sec * 1000.0, 2)

            if regs2 is not None:
                is_stereo = True

            # Register deltas
            deltas1: Dict[str, int] = {}
            for name, curr, prev in zip(POKEY_REGS, regs1, prev_regs1):
                if curr != prev:
                    deltas1[name] = curr
            prev_regs1 = list(regs1)

            deltas2: Optional[Dict[str, int]] = None
            if regs2 is not None:
                deltas2 = {}
                for name, curr, prev in zip(POKEY_REGS, regs2, prev_regs2):
                    if curr != prev:
                        deltas2[name] = curr
                prev_regs2 = list(regs2)

            # Active voices (volume > 0)
            active_count = 0
            for i in range(4):
                vol1 = regs1[i * 2 + 1] & 0x0F
                if vol1 > 0:
                    active_count += 1
                if regs2 is not None:
                    vol2 = regs2[i * 2 + 1] & 0x0F
                    if vol2 > 0:
                        active_count += 1

            # Hash state for unique states tracking
            state_key = tuple(regs1) + (tuple(regs2) if regs2 is not None else ())
            unique_states.add(state_key)

            pokey1_dict = dict(zip(POKEY_REGS, regs1))
            pokey2_dict = dict(zip(POKEY_REGS, regs2)) if regs2 is not None else None

            frames.append(
                FrameEvent(
                    frame=frame_idx,
                    time_ms=time_ms,
                    time_sec=time_sec,
                    pokey1=pokey1_dict,
                    pokey2=pokey2_dict,
                    deltas1=deltas1,
                    deltas2=deltas2,
                    active_channels_count=active_count,
                )
            )

            frame_idx += 1
            if max_frames and frame_idx >= max_frames:
                break
            if max_seconds and time_sec >= max_seconds:
                break

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Calculate playback rate from frame intervals
    rate_hz = 50.0
    if len(frames) >= 2:
        interval = (frames[-1].time_sec - frames[0].time_sec) / (len(frames) - 1)
        if interval > 0:
            rate_hz = round(1.0 / interval, 2)

    total_duration_ms = frames[-1].time_ms if frames else 0.0
    features = get_detected_features(asapscan_bin, sap_path)

    return ExtractionResult(
        song_path=sap_path,
        filename=os.path.basename(sap_path),
        title=None,
        author=None,
        subsong=subsong,
        is_stereo=is_stereo,
        playback_rate_hz=rate_hz,
        total_frames=len(frames),
        duration_ms=total_duration_ms,
        features_detected=features,
        unique_states_count=len(unique_states),
        frames=frames,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Proof of Concept POKEY Extractor.")
    parser.add_argument("input_files", nargs="+", help="Path(s) to SAP files")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("poc_output"),
        help="Directory to save extracted JSON timelines",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=10.0,
        help="Max seconds to capture per track (default 10s for POC demo)",
    )
    parser.add_argument(
        "--asapscan",
        type=str,
        default="tools/asap/asapscan.exe",
        help="Path to asapscan executable",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for sap_path in args.input_files:
        print(f"Extracting {sap_path} (max {args.max_seconds}s)...")
        result = extract_pokey_timeline(
            sap_path=sap_path,
            asapscan_bin=args.asapscan,
            subsong=0,
            max_seconds=args.max_seconds,
        )

        out_name = f"{Path(sap_path).stem}_pokey_poc.json"
        out_file = args.output_dir / out_name

        data = asdict(result)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        print(
            f"  -> Captured {result.total_frames} frames ({result.duration_ms / 1000.0:.2f}s), "
            f"stereo={result.is_stereo}, rate={result.playback_rate_hz} Hz, "
            f"unique states={result.unique_states_count}, features={result.features_detected}"
        )
        print(f"  -> Saved to {out_file}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

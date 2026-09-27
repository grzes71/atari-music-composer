"""RAW POKEY Dump Extractor.

Executes asapscan -d on SAP files, captures raw stdout text without destructive
transformation, compresses it with gzip into dataset/raw/, and records loop metadata.
"""

from __future__ import annotations

import gzip
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from atari_music.models import RawDumpMeta


def parse_time_string(time_str: str) -> Tuple[float, bool]:
    """Parse SAP TIME format (e.g. '01:40.09 LOOP' or '00:09.64') into seconds and loop flag."""
    is_loop = "LOOP" in time_str.upper()
    clean = re.sub(r"[^0-9:.]", "", time_str.split()[0]).strip()
    
    parts = clean.split(":")
    if len(parts) == 2:
        minutes = float(parts[0])
        seconds = float(parts[1])
        total_sec = minutes * 60.0 + seconds
    elif len(parts) == 1:
        total_sec = float(parts[0])
    else:
        total_sec = 60.0

    return max(total_sec, 0.1), is_loop


def query_hardware_features(asapscan_bin: str, sap_path: str) -> List[str]:
    """Run asapscan -f to identify special POKEY hardware features."""
    try:
        res = subprocess.run(
            [asapscan_bin, "-f", sap_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    except Exception:
        pass
    return []


def detect_loop_asapscan(asapscan_bin: str, sap_path: str, subsong: int) -> Optional[float]:
    """Run asapscan -t to query loop duration from emulator."""
    try:
        res = subprocess.run(
            [asapscan_bin, "-t", "-s", str(subsong), sap_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and "LOOP" in res.stdout:
            for line in res.stdout.splitlines():
                if "TIME" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        sec, _ = parse_time_string(parts[1])
                        return sec
    except Exception:
        pass
    return None


def extract_raw_dump(
    sap_path: Path,
    subsong: int,
    declared_time_str: str,
    output_raw_path: Path,
    asapscan_bin: str = "tools/asap/asapscan.exe",
    max_duration_cap_sec: float = 300.0,
    author: Optional[str] = None,
    title: Optional[str] = None,
    date: Optional[str] = None,
    sap_type: Optional[str] = None,
    fastplay_scanlines: Optional[int] = None,
) -> RawDumpMeta:
    """Stream asapscan -d output to a .dump.gz raw file, capturing complete POKEY behavior."""
    declared_sec, is_loop = parse_time_string(declared_time_str)
    
    # Check if asapscan detects loop or silence
    detected_loop_sec = detect_loop_asapscan(asapscan_bin, str(sap_path), subsong)
    
    # Duration to record: declared duration + small margin (e.g. 1 second or 50 frames)
    # Capped at max_duration_cap_sec to avoid runaway files
    target_duration_sec = min(declared_sec + 0.5, max_duration_cap_sec)

    cmd = [asapscan_bin, "-d", "-s", str(subsong), str(sap_path)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    output_raw_path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = 0
    last_time_sec = 0.0
    first_time_sec: Optional[float] = None
    is_stereo = False

    with gzip.open(output_raw_path, "wt", encoding="ascii") as gz_out:
        assert proc.stdout is not None
        for line in proc.stdout:
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue

            time_part, regs_part = stripped.split(":", 1)
            try:
                curr_sec = float(time_part.strip())
            except ValueError:
                continue

            if first_time_sec is None:
                first_time_sec = curr_sec
            last_time_sec = curr_sec

            if "|" in regs_part:
                is_stereo = True

            gz_out.write(line)
            total_frames += 1

            if curr_sec >= target_duration_sec:
                break

    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Calculate playback rate
    playback_rate_hz = 50.0
    if total_frames > 1 and first_time_sec is not None:
        span = last_time_sec - first_time_sec
        if span > 0:
            playback_rate_hz = round(total_frames / span, 2)

    features = query_hardware_features(asapscan_bin, str(sap_path))

    loop_start_ms = 0.0 if is_loop else None
    loop_end_ms = round(declared_sec * 1000.0, 2) if is_loop else None

    return RawDumpMeta(
        song_file=sap_path.as_posix(),
        subsong_index=subsong,
        author=author,
        title=title,
        date=date,
        sap_type=sap_type,
        declared_duration=declared_time_str,
        duration_ms=round(last_time_sec * 1000.0, 2),
        is_looping=is_loop,
        loop_start_ms=loop_start_ms,
        loop_end_ms=loop_end_ms,
        is_stereo=is_stereo,
        playback_rate_hz=playback_rate_hz,
        fastplay_scanlines=fastplay_scanlines,
        total_frames=total_frames,
        features_detected=features,
    )

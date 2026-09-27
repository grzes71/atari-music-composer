"""POKEY Events Layer (Layer 2).

Transforms RAW dump streams into discrete PokeyEvent objects and provides
exact, deterministic state reconstruction at any arbitrary frame or timestamp.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from atari_music.constants import POKEY_REGS
from atari_music.models import PokeyEvent


def parse_dump_tokens(line: str) -> Optional[Tuple[float, List[int], Optional[List[int]]]]:
    """Parse one line from asapscan -d into time_sec and register byte arrays."""
    stripped = line.strip()
    if not stripped or ":" not in stripped:
        return None

    time_part, regs_part = stripped.split(":", 1)
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


def raw_to_events_stream(raw_dump_path: Path) -> Iterator[PokeyEvent]:
    """Stream PokeyEvent changes from a gzip-compressed or raw text dump."""
    prev_p0 = [-1] * 9
    prev_p1 = [-1] * 9

    opener = gzip.open if str(raw_dump_path).endswith(".gz") else open

    frame_idx = 0
    with opener(raw_dump_path, "rt", encoding="ascii") as f:
        for line in f:
            parsed = parse_dump_tokens(line)
            if not parsed:
                continue

            time_sec, p0, p1 = parsed
            time_ms = round(time_sec * 1000.0, 2)

            # Check POKEY 0 changes
            for reg_idx, reg_name in enumerate(POKEY_REGS):
                val = p0[reg_idx]
                old_val = prev_p0[reg_idx]
                if old_val == -1 or val != old_val:
                    yield PokeyEvent(
                        frame=frame_idx,
                        time_ms=time_ms,
                        pokey=0,
                        register=reg_name,
                        old=max(old_val, 0),
                        new=val,
                    )
            prev_p0 = list(p0)

            # Check POKEY 1 changes (Stereo)
            if p1 is not None:
                for reg_idx, reg_name in enumerate(POKEY_REGS):
                    val = p1[reg_idx]
                    old_val = prev_p1[reg_idx]
                    if old_val == -1 or val != old_val:
                        yield PokeyEvent(
                            frame=frame_idx,
                            time_ms=time_ms,
                            pokey=1,
                            register=reg_name,
                            old=max(old_val, 0),
                            new=val,
                        )
                prev_p1 = list(p1)

            frame_idx += 1


class PokeyStateReconstructor:
    """Maintains state and reconstructs full POKEY register sets at any frame."""

    def __init__(self, is_stereo: bool = False):
        self.is_stereo = is_stereo
        self.p0 = [0] * 9
        self.p1 = [0] * 9 if is_stereo else None
        self.current_frame = -1
        self.current_time_ms = 0.0

    def apply_event(self, event: PokeyEvent) -> None:
        """Apply a discrete PokeyEvent to advance current state."""
        self.current_frame = event.frame
        self.current_time_ms = event.time_ms
        reg_idx = POKEY_REGS.index(event.reg_name)
        if event.pokey == 0:
            self.p0[reg_idx] = event.new
        elif event.pokey == 1:
            if self.p1 is None:
                self.p1 = [0] * 9
                self.is_stereo = True
            self.p1[reg_idx] = event.new

    def get_state_dict(self) -> Dict[str, Any]:
        """Return full register state dictionary for both POKEY chips."""
        res: Dict[str, Any] = {
            "frame": self.current_frame,
            "time_ms": self.current_time_ms,
            "pokey0": dict(zip(POKEY_REGS, self.p0)),
        }
        if self.p1 is not None:
            res["pokey1"] = dict(zip(POKEY_REGS, self.p1))
        else:
            res["pokey1"] = None
        return res


def export_events(events: List[PokeyEvent], output_path: Path) -> None:
    """Save event stream as gzip-compressed JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dicts = [e.model_dump() for e in events]
    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        json.dump(raw_dicts, f)

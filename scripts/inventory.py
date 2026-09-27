"""SAP Collection Inventory Generator.

Scans all SAP files in the dataset, parses headers, detects player types,
computes playback rates, and generates inventory.json and inventory.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class SAPMetadata:
    filename: str
    relative_path: str
    composer_dir: str
    file_size_bytes: int
    sap_type: Optional[str]
    author: Optional[str]
    title: Optional[str]
    date: Optional[str]
    init_address: Optional[str]
    player_address: Optional[str]
    music_address: Optional[str]
    channels: str
    playback_rate_hz: float
    fastplay_scanlines: Optional[int]
    songs_count: int
    default_subsong: int
    durations: List[str]
    detected_player: Optional[str]


def parse_sap_header(path: Path) -> SAPMetadata:
    """Parse SAP text header according to SAP format specifications."""
    file_size = path.stat().st_size
    composer_dir = path.parent.name
    rel_path = path.as_posix()

    author: Optional[str] = None
    title: Optional[str] = None
    date: Optional[str] = None
    sap_type: Optional[str] = None
    init_address: Optional[str] = None
    player_address: Optional[str] = None
    music_address: Optional[str] = None
    is_stereo: bool = False
    fastplay: Optional[int] = None
    songs_count: int = 1
    defsong: int = 0
    durations: List[str] = []

    with open(path, "rb") as f:
        while True:
            line_bytes = f.readline()
            if not line_bytes:
                break
            if line_bytes.startswith(b"\xff\xff"):
                break
            if line_bytes in (b"\r\n", b"\n", b"\r"):
                break

            try:
                line_str = line_bytes.decode("latin1").strip()
            except Exception:
                break

            if not line_str:
                continue

            parts = line_str.split(None, 1)
            tag = parts[0].upper()
            val = parts[1].strip() if len(parts) > 1 else ""

            if tag == "SAP":
                continue
            elif tag == "AUTHOR":
                author = val.strip('"') or None
            elif tag == "NAME":
                title = val.strip('"') or None
            elif tag == "DATE":
                date = val.strip('"') or None
            elif tag == "TYPE":
                sap_type = val.split()[0].upper() if val else None
            elif tag == "INIT":
                init_val = val.split()[0].upper() if val else ""
                init_address = f"0x{init_val}" if init_val else None
            elif tag == "PLAYER":
                player_val = val.split()[0].upper() if val else ""
                player_address = f"0x{player_val}" if player_val else None
            elif tag == "MUSIC":
                music_val = val.split()[0].upper() if val else ""
                music_address = f"0x{music_val}" if music_val else None
            elif tag == "STEREO":
                is_stereo = True
            elif tag == "FASTPLAY":
                try:
                    fastplay = int(val.split()[0])
                except ValueError:
                    fastplay = None
            elif tag == "SONGS":
                try:
                    songs_count = int(val.split()[0])
                except ValueError:
                    songs_count = 1
            elif tag == "DEFSONG":
                try:
                    defsong = int(val.split()[0])
                except ValueError:
                    defsong = 0
            elif tag == "TIME":
                durations.append(val)

    # Playback rate calculation: PAL has 312 scanlines per 50Hz frame
    # If FASTPLAY is specified: rate = (312 / FASTPLAY) * 50 Hz
    # e.g., FASTPLAY 312 -> 50 Hz, FASTPLAY 156 -> 100 Hz, FASTPLAY 78 -> 200 Hz, FASTPLAY 31 -> ~503 Hz
    if fastplay is not None and fastplay > 0:
        playback_rate = round(15600.0 / fastplay, 2)
    else:
        playback_rate = 50.0

    channels_str = "stereo" if is_stereo else "mono"

    return SAPMetadata(
        filename=path.name,
        relative_path=rel_path,
        composer_dir=composer_dir,
        file_size_bytes=file_size,
        sap_type=sap_type,
        author=author,
        title=title,
        date=date,
        init_address=init_address,
        player_address=player_address,
        music_address=music_address,
        channels=channels_str,
        playback_rate_hz=playback_rate,
        fastplay_scanlines=fastplay,
        songs_count=songs_count,
        default_subsong=defsong,
        durations=durations,
        detected_player=None,
    )


def detect_player_type(meta: SAPMetadata, asapconv_path: Optional[str] = None) -> str:
    """Identify the music engine / tracker format used by the song."""
    # Fast check via asapconv if available
    if asapconv_path and os.path.exists(asapconv_path):
        scratch_dir = Path("tools/scratch_detect")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        # Check prominent tracker formats
        for fmt, label in [("rmt", "Raster Music Tracker (RMT)"), ("cmc", "Chaos Music Composer (CMC)")]:
            out_file = scratch_dir / f"test.{fmt}"
            if out_file.exists():
                out_file.unlink()
            try:
                res = subprocess.run(
                    [asapconv_path, "-o", str(out_file), meta.relative_path],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if res.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                    return label
            except Exception:
                pass

    # Heuristics based on SAP Type. Composer identities are intentionally not
    # embedded here; hand-coded engines are identified generically by type.
    if meta.sap_type == "D":
        return "Digital / Sample Player (Type D)"
    elif meta.sap_type == "C":
        return "Standard Tracker Module (Type C)"
    elif meta.sap_type == "B":
        return "Custom Embedded Driver (Type B)"

    return "Unknown / Custom Player"


def build_inventory(music_dir: Path, asapconv_path: Optional[str] = None) -> List[SAPMetadata]:
    """Scan all .sap files in directory and produce complete metadata inventory."""
    sap_files = sorted(music_dir.glob("*/*.sap"))
    inventory: List[SAPMetadata] = []

    scratch_dir = Path("tools/scratch_detect")
    scratch_dir.mkdir(parents=True, exist_ok=True)

    for p in sap_files:
        meta = parse_sap_header(p)
        meta.detected_player = detect_player_type(meta, asapconv_path)
        inventory.append(meta)

    if scratch_dir.exists():
        for f in scratch_dir.glob("*"):
            f.unlink()
        try:
            scratch_dir.rmdir()
        except OSError:
            pass

    return inventory


def export_inventory(
    inventory: List[SAPMetadata], json_path: Path, csv_path: Path
) -> None:
    """Export inventory to JSON and CSV formats."""
    # JSON export
    raw_dicts = [asdict(item) for item in inventory]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_dicts, f, indent=2, ensure_ascii=False)

    # CSV export
    fieldnames = [
        "filename",
        "relative_path",
        "composer_dir",
        "author",
        "title",
        "date",
        "sap_type",
        "init_address",
        "player_address",
        "music_address",
        "channels",
        "playback_rate_hz",
        "fastplay_scanlines",
        "songs_count",
        "default_subsong",
        "durations",
        "file_size_bytes",
        "detected_player",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in raw_dicts:
            row = dict(item)
            # Format list of durations into readable string for CSV
            row["durations"] = "; ".join(row["durations"]) if row["durations"] else ""
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Atari SAP collection.")
    parser.add_argument(
        "--music-dir",
        type=Path,
        default=Path("music"),
        help="Path to music directory containing composer subdirectories",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("inventory.json"),
        help="Path to output JSON file",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("inventory.csv"),
        help="Path to output CSV file",
    )
    parser.add_argument(
        "--asapconv",
        type=str,
        default=r"C:\Program Files\ASAP\asapconv.exe",
        help="Path to asapconv binary for tracker format detection",
    )

    args = parser.parse_args()

    asapconv = args.asapconv if os.path.exists(args.asapconv) else None
    print(f"Scanning SAP collection in {args.music_dir}...")
    inventory = build_inventory(args.music_dir, asapconv)
    print(f"Found and parsed {len(inventory)} SAP files.")

    export_inventory(inventory, args.output_json, args.output_csv)
    print(f"Exported inventory to {args.output_json} and {args.output_csv}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

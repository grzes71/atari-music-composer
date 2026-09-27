"""Dataset Builder and Orchestrator.

Processes SAP files across all 3 layers (RAW -> EVENTS -> FEATURES),
serializes intermediate files, and generates unified dataset.jsonl.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from atari_music.analyzer import run_repetition_and_memory_analysis
from atari_music.constants import POKEY_REGS
from atari_music.events import export_events, parse_dump_tokens, raw_to_events_stream
from atari_music.extractor import extract_raw_dump
from atari_music.features import interpret_voice_state, summarize_musical_features
from atari_music.models import (
    ChannelVoiceState,
    DatasetRecord,
    MusicalFeaturesSummary,
    RawDumpMeta,
    RepetitionAndMemory,
)


def slugify(text: str) -> str:
    """Create filesystem-safe slug identifier."""
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in text)


def process_single_subsong(
    sap_path: Path,
    subsong: int,
    declared_time_str: str,
    dataset_dir: Path,
    asapscan_bin: str = "tools/asap/asapscan.exe",
    author: Optional[str] = None,
    title: Optional[str] = None,
    date: Optional[str] = None,
    sap_type: Optional[str] = None,
    fastplay_scanlines: Optional[int] = None,
) -> DatasetRecord:
    """Process a single SAP subsong across all 3 layers and return DatasetRecord."""
    composer = sap_path.parent.name
    song_stem = sap_path.stem
    slug = f"{slugify(composer)}__{slugify(song_stem)}__sub{subsong}"

    raw_path = dataset_dir / "raw" / f"{slug}.dump.gz"
    events_path = dataset_dir / "events" / f"{slug}.events.json.gz"
    features_path = dataset_dir / "features" / f"{slug}.features.json"

    # Layer 1: RAW dump capture
    meta: RawDumpMeta = extract_raw_dump(
        sap_path=sap_path,
        subsong=subsong,
        declared_time_str=declared_time_str,
        output_raw_path=raw_path,
        asapscan_bin=asapscan_bin,
        author=author,
        title=title,
        date=date,
        sap_type=sap_type,
        fastplay_scanlines=fastplay_scanlines,
    )

    # Layer 2: POKEY Events Stream
    events_list = list(raw_to_events_stream(raw_path))
    export_events(events_list, events_path)

    # Layer 3: Musical Interpretation & Features
    frames_voices: List[List[ChannelVoiceState]] = []
    audctls: List[int] = []

    with gzip.open(raw_path, "rt", encoding="ascii") as f:
        for line in f:
            parsed = parse_dump_tokens(line)
            if not parsed:
                continue
            time_sec, p0, p1 = parsed
            audctl0 = p0[8]
            audctls.append(audctl0)

            # Interpret POKEY 0 voices (channels 1..4)
            voices: List[ChannelVoiceState] = []
            for ch in range(1, 5):
                audf = p0[(ch - 1) * 2]
                audc = p0[(ch - 1) * 2 + 1]
                pair_low = p0[0] if ch == 2 else (p0[4] if ch == 4 else None)
                v = interpret_voice_state(ch, 0, audf, audc, audctl0, pair_low)
                voices.append(v)

            # If stereo, interpret POKEY 1 voices (channels 1..4)
            if p1 is not None:
                audctl1 = p1[8]
                audctls.append(audctl1)
                for ch in range(1, 5):
                    audf = p1[(ch - 1) * 2]
                    audc = p1[(ch - 1) * 2 + 1]
                    pair_low = p1[0] if ch == 2 else (p1[4] if ch == 4 else None)
                    v = interpret_voice_state(ch, 1, audf, audc, audctl1, pair_low)
                    voices.append(v)

            frames_voices.append(voices)

    # High-level musical features summary
    features: MusicalFeaturesSummary = summarize_musical_features(frames_voices, audctls)
    if "Ultrasound" in meta.features_detected:
        features.uses_ultrasound = True

    # Structural repetition and memory analysis
    raw_file_size = sap_path.stat().st_size
    analysis: RepetitionAndMemory = run_repetition_and_memory_analysis(
        meta=meta,
        features=features,
        frames_voices=frames_voices,
        total_events_count=len(events_list),
        raw_sap_file_bytes=raw_file_size,
    )

    # Save per-song features file
    features_payload = {
        "id": slug,
        "meta": meta.model_dump(),
        "features": features.model_dump(),
        "analysis": analysis.model_dump(),
    }
    features_path.parent.mkdir(parents=True, exist_ok=True)
    with open(features_path, "w", encoding="utf-8") as f:
        json.dump(features_payload, f, indent=2)

    return DatasetRecord(
        id=slug,
        meta=meta,
        features=features,
        analysis=analysis,
        raw_dump_path=raw_path.as_posix(),
        events_path=events_path.as_posix(),
    )


def build_full_dataset(
    inventory_path: Path,
    dataset_dir: Path,
    asapscan_bin: str = "tools/asap/asapscan.exe",
    max_subsongs: Optional[int] = None,
) -> Tuple[int, int, List[str]]:
    """Iterate through inventory, process all subsongs, and write dataset.jsonl.
    
    Returns:
        (successful_count, failed_count, failed_files_list)
    """
    with open(inventory_path, "r", encoding="utf-8") as f:
        inventory = json.load(f)

    dataset_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = dataset_dir / "dataset.jsonl"

    success_count = 0
    fail_count = 0
    failed_items: List[str] = []

    with open(jsonl_path, "w", encoding="utf-8") as jsonl_out:
        processed_total = 0
        for item in inventory:
            sap_path = Path(item["relative_path"])
            durations: List[str] = item.get("durations", [])
            songs_count: int = item.get("songs_count", 1)

            for subsong_idx in range(songs_count):
                if max_subsongs and processed_total >= max_subsongs:
                    return success_count, fail_count, failed_items

                declared_time = durations[subsong_idx] if subsong_idx < len(durations) else "01:00.00"

                try:
                    record = process_single_subsong(
                        sap_path=sap_path,
                        subsong=subsong_idx,
                        declared_time_str=declared_time,
                        dataset_dir=dataset_dir,
                        asapscan_bin=asapscan_bin,
                        author=item.get("author"),
                        title=item.get("title"),
                        date=item.get("date"),
                        sap_type=item.get("sap_type"),
                        fastplay_scanlines=item.get("fastplay_scanlines"),
                    )

                    jsonl_out.write(record.model_dump_json() + "\n")
                    jsonl_out.flush()
                    success_count += 1
                except Exception as ex:
                    fail_count += 1
                    failed_items.append(f"{sap_path.as_posix()}:sub{subsong_idx} ({str(ex)})")

                processed_total += 1

    return success_count, fail_count, failed_items


def reanalyze_dataset_from_raw(dataset_dir: Path) -> int:
    """Fast re-analysis of features and dataset.jsonl directly from existing RAW dump files."""
    jsonl_path = dataset_dir / "dataset.jsonl"
    existing_records: List[Dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                existing_records.append(json.loads(line))

    updated_records: List[DatasetRecord] = []

    for item in existing_records:
        meta_dict = item["meta"]
        meta = RawDumpMeta(**meta_dict)
        slug = item["id"]
        raw_path = dataset_dir / "raw" / f"{slug}.dump.gz"
        events_path = dataset_dir / "events" / f"{slug}.events.json.gz"
        features_path = dataset_dir / "features" / f"{slug}.features.json"

        if not raw_path.exists():
            continue

        frames_voices: List[List[ChannelVoiceState]] = []
        audctls: List[int] = []

        with gzip.open(raw_path, "rt", encoding="ascii") as f:
            for line in f:
                parsed = parse_dump_tokens(line)
                if not parsed:
                    continue
                time_sec, p0, p1 = parsed
                audctl0 = p0[8]
                audctls.append(audctl0)

                voices: List[ChannelVoiceState] = []
                for ch in range(1, 5):
                    audf = p0[(ch - 1) * 2]
                    audc = p0[(ch - 1) * 2 + 1]
                    pair_low = p0[0] if ch == 2 else (p0[4] if ch == 4 else None)
                    v = interpret_voice_state(ch, 0, audf, audc, audctl0, pair_low)
                    voices.append(v)

                if p1 is not None:
                    audctl1 = p1[8]
                    audctls.append(audctl1)
                    for ch in range(1, 5):
                        audf = p1[(ch - 1) * 2]
                        audc = p1[(ch - 1) * 2 + 1]
                        pair_low = p1[0] if ch == 2 else (p1[4] if ch == 4 else None)
                        v = interpret_voice_state(ch, 1, audf, audc, audctl1, pair_low)
                        voices.append(v)

                frames_voices.append(voices)

        features = summarize_musical_features(frames_voices, audctls)
        if "Ultrasound" in meta.features_detected:
            features.uses_ultrasound = True

        sap_file = Path(meta.song_file)
        raw_size = sap_file.stat().st_size if sap_file.exists() else 4096
        total_events = item["analysis"]["event_stream_bytes"] // 4

        analysis = run_repetition_and_memory_analysis(
            meta=meta,
            features=features,
            frames_voices=frames_voices,
            total_events_count=total_events,
            raw_sap_file_bytes=raw_size,
        )

        rec = DatasetRecord(
            id=slug,
            meta=meta,
            features=features,
            analysis=analysis,
            raw_dump_path=raw_path.as_posix(),
            events_path=events_path.as_posix(),
        )
        updated_records.append(rec)

        features_payload = {
            "id": slug,
            "meta": meta.model_dump(),
            "features": features.model_dump(),
            "analysis": analysis.model_dump(),
        }
        with open(features_path, "w", encoding="utf-8") as f:
            json.dump(features_payload, f, indent=2)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in updated_records:
            f.write(rec.model_dump_json() + "\n")

    return len(updated_records)

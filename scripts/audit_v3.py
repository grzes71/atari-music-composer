"""Audit script for Composer v3 18 tracks."""

import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np

from atari_music.ir import (
    IRSong,
    calculate_ir_binary_size,
    compile_ir_to_pokey_frames,
)
from atari_music.features import midi_to_note_name

def audit_v3():
    base_dir = Path("experiments/composer_v3")
    summary_path = base_dir / "summary.json"
    
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
        
    profiles = ["title", "exploration", "action", "funny", "dungeon", "ending"]
    
    track_reports = []
    
    for prof in profiles:
        for t_meta in summary[prof]:
            t_id = t_meta["track_id"]
            json_p = Path(t_meta["json_path"])
            song = IRSong.from_json_file(json_p)
            frames = compile_ir_to_pokey_frames(song)
            total_frames = frames.shape[0]
            dur_sec = total_frames / 50.0
            
            # Frame-level active channel percentage (AUDC volume & 0x0F > 0)
            # Physical channels 1..4: AUDC are cols 1, 3, 5, 7
            active_frame_pct = {}
            active_channels_count = 0
            for ch in range(1, 5):
                audc_col = (ch - 1) * 2 + 1
                active_frames = np.count_nonzero(frames[:, audc_col] & 0x0F > 0)
                pct = (active_frames / total_frames) * 100.0 if total_frames > 0 else 0.0
                active_frame_pct[ch] = pct
                if active_frames > 0:
                    active_channels_count += 1
            
            # Track-level analysis across sequence
            # Reconstruct sequence of notes
            pattern_map = {p.id: p for p in song.patterns}
            ch_notes_count = {1: 0, 2: 0, 3: 0, 4: 0}
            ch_roles = {1: set(), 2: set(), 3: set(), 4: set()}
            ch_pitches = {1: [], 2: [], 3: [], 4: []}
            
            total_notes = 0
            for pat_id in song.sequence:
                pat = pattern_map.get(pat_id)
                if not pat:
                    continue
                for ch in range(1, 5):
                    notes = pat.tracks.get(ch, [])
                    for n in notes:
                        if not n.is_rest:
                            ch_notes_count[ch] += 1
                            total_notes += 1
                            ch_roles[ch].add(n.channel_role)
                            if n.midi_pitch is not None:
                                ch_pitches[ch].append(n.midi_pitch)
            
            ch_pitch_range = {}
            for ch in range(1, 5):
                if ch_pitches[ch]:
                    min_p = min(ch_pitches[ch])
                    max_p = max(ch_pitches[ch])
                    ch_pitch_range[ch] = f"{midi_to_note_name(min_p)}-{midi_to_note_name(max_p)} ({max_p - min_p} st)"
                else:
                    ch_pitch_range[ch] = "None"
            
            mem_size = calculate_ir_binary_size(song)
            note_density = total_notes / dur_sec if dur_sec > 0 else 0.0
            
            report = {
                "profile": prof,
                "track_id": t_id,
                "title": song.title,
                "form": t_meta.get("form", "N/A"),
                "duration_sec": dur_sec,
                "mem_size_bytes": mem_size,
                "uses_16bit_bass": song.uses_16bit_bass,
                "active_channels_audio": active_channels_count,
                "channels_in_ir": t_meta.get("channels_used", 0),
                "active_frame_pct": active_frame_pct,
                "note_counts": ch_notes_count,
                "total_notes": total_notes,
                "roles": {ch: list(r) if r else ["none"] for ch, r in ch_roles.items()},
                "pitch_ranges": ch_pitch_range,
                "note_density": round(note_density, 2),
            }
            track_reports.append(report)
            
    print(json.dumps(track_reports, indent=2))

if __name__ == "__main__":
    audit_v3()

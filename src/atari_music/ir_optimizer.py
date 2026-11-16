"""POKEY IR pattern optimization and memory-footprint passes."""

from __future__ import annotations

from typing import Dict, List, Tuple

from atari_music.ir import IRPattern, IRSong


def deduplicate_pokey_patterns(song: IRSong) -> Tuple[IRSong, int]:
    """Pattern deduplication: merge identical patterns and remap sequence entries."""
    unique_patterns: List[IRPattern] = []
    remap: Dict[int, int] = {}
    old_to_new_id: Dict[int, int] = {}

    for p in song.patterns:
        match = None
        for u in unique_patterns:
            if u.rows == p.rows and len(u.tracks) == len(p.tracks):
                if repr(u.tracks) == repr(p.tracks):
                    match = u.id
                    break
        if match is not None:
            remap[p.id] = match
        else:
            unique_patterns.append(p)
            remap[p.id] = p.id

    # Renumber unique patterns consecutively 0, 1, ...
    for new_idx, pat in enumerate(unique_patterns):
        old_id = pat.id
        old_to_new_id[old_id] = new_idx
        pat.id = new_idx

    final_sequence = []
    for seq_item in song.sequence:
        if isinstance(seq_item, list):
            final_sequence.append([old_to_new_id.get(remap.get(x, x), 0) for x in seq_item])
        else:
            final_sequence.append(old_to_new_id.get(remap.get(seq_item, seq_item), 0))

    removed_count = len(song.patterns) - len(unique_patterns)
    song.patterns = unique_patterns
    song.sequence = final_sequence
    return song, removed_count

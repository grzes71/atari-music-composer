"""Generate detailed Etap 8.1 Audit Report for Composer v3 18 tracks."""

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

def analyze_track(t_meta: Dict[str, Any]) -> Dict[str, Any]:
    json_p = Path(t_meta["json_path"])
    song = IRSong.from_json_file(json_p)
    frames = compile_ir_to_pokey_frames(song)
    total_frames = frames.shape[0]
    dur_sec = total_frames / 50.0

    # 1. Physical audio activity (frames where AUDC > 0)
    audio_ch_active = {}
    for ch in range(1, 5):
        audc_col = (ch - 1) * 2 + 1
        active_f = np.count_nonzero(frames[:, audc_col] & 0x0F > 0)
        pct = (active_f / total_frames) * 100.0 if total_frames > 0 else 0.0
        audio_ch_active[ch] = round(pct, 1)

    # 2. IR-level channel activity (rows where note is active, not rest)
    pattern_map = {p.id: p for p in song.patterns}
    total_seq_rows = len(song.sequence) * 32
    
    ch_active_rows = {1: 0, 2: 0, 3: 0, 4: 0}
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
                if not n.is_rest and (n.midi_pitch is not None or n.channel_role == "percussion"):
                    ch_notes_count[ch] += 1
                    ch_active_rows[ch] += n.duration
                    total_notes += 1
                    ch_roles[ch].add(n.channel_role)
                    if n.midi_pitch is not None:
                        ch_pitches[ch].append(n.midi_pitch)

    # IR active time %
    ir_ch_active_pct = {
        ch: round((ch_active_rows[ch] / total_seq_rows) * 100.0, 1) if total_seq_rows > 0 else 0.0
        for ch in range(1, 5)
    }

    # Number of active channels:
    # A channel is active in IR if it has at least 1 note
    ir_active_channels_count = sum(1 for ch in range(1, 5) if ch_notes_count[ch] > 0)
    audio_active_channels_count = sum(1 for ch in range(1, 5) if audio_ch_active[ch] > 0.0)

    ch_pitch_range = {}
    for ch in range(1, 5):
        if ch_pitches[ch]:
            min_p = min(ch_pitches[ch])
            max_p = max(ch_pitches[ch])
            ch_pitch_range[ch] = f"{midi_to_note_name(min_p)}-{midi_to_note_name(max_p)} ({max_p - min_p} st)"
        else:
            ch_pitch_range[ch] = "—"

    mem_size = calculate_ir_binary_size(song)
    note_density = round(total_notes / dur_sec, 2) if dur_sec > 0 else 0.0

    # Activity ratio: ch1 : ch2 : ch3 : ch4 %
    activity_ratio = f"{ir_ch_active_pct[1]}% : {ir_ch_active_pct[2]}% : {ir_ch_active_pct[3]}% : {ir_ch_active_pct[4]}%"
    audio_activity_ratio = f"{audio_ch_active[1]}% : {audio_ch_active[2]}% : {audio_ch_active[3]}% : {audio_ch_active[4]}%"

    return {
        "profile": t_meta["profile"],
        "track_id": t_meta["track_id"],
        "seed": t_meta["seed"],
        "title": song.title,
        "form": t_meta.get("form", "N/A"),
        "duration_sec": round(dur_sec, 1),
        "tempo_bpm": song.tempo_bpm,
        "mem_size_bytes": mem_size,
        "uses_16bit_bass": song.uses_16bit_bass,
        "ir_active_channels": ir_active_channels_count,
        "audio_active_channels": audio_active_channels_count,
        "ir_ch_active_pct": ir_ch_active_pct,
        "audio_ch_active_pct": audio_ch_active,
        "activity_ratio": activity_ratio,
        "audio_activity_ratio": audio_activity_ratio,
        "note_counts": ch_notes_count,
        "total_notes": total_notes,
        "roles": {ch: "/".join(ch_roles[ch]) if ch_roles[ch] else "—" for ch in range(1, 5)},
        "pitch_ranges": ch_pitch_range,
        "note_density": note_density,
    }

def main():
    base_dir = Path("experiments/composer_v3")
    summary_path = base_dir / "summary.json"
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    profiles = ["title", "exploration", "action", "funny", "dungeon", "ending"]
    all_tracks = []
    by_profile = {p: [] for p in profiles}

    for prof in profiles:
        for t_meta in summary[prof]:
            info = analyze_track(t_meta)
            all_tracks.append(info)
            by_profile[prof].append(info)

    # Aggregates
    ir_ch_dist = {1: 0, 2: 0, 3: 0, 4: 0}
    audio_ch_dist = {1: 0, 2: 0, 3: 0, 4: 0}

    for t in all_tracks:
        ir_ch_dist[t["ir_active_channels"]] += 1
        audio_ch_dist[t["audio_active_channels"]] += 1

    lines = []
    lines.append("# AUDYT COMPOSER v3 (Etap 8.1)")
    lines.append("")
    lines.append("## 1. Wnioski ogólne i kluczowe odkrycia")
    lines.append("")
    lines.append("Audyt ujawnił **dwa fundamentalne problemy** Composer v3:")
    lines.append("1. **Problem architektoniczno-muzyczny:** W generatorze v3 kanały są statyczne — brak prawdziwego drugiego głosu (`COUNTER/HARMONY`). Kanał 2 był albo pusty (dummy rest przy 16-bit bass), albo grał statyczny dron (Dungeon: pojedynczy dźwięk przez cały utwór), albo mechaniczny arpeggiator `step % len(tones)`. Kanał 4 (perkusja) był albo wyłączony, albo grał sztywny, jednostajny pattern. Trzy utwory (`funny_03`, `dungeon_02`, `exploration_03`) zostały wygenerowane z zaledwie dwoma kanałami.")
    lines.append("2. **Błąd w syntezie 16-bit bass (`ir.py`):** Przy `uses_16bit_bass = True`, kanał 1 i 2 tworzyły parę 16-bitową, ale w pętli renderowania `ch=2` (który w IR zawierał nuty pauzy dla trackerowego tracku 2) zerował rejestr `AUDC2`, wyciszając bas do zera! W rezultacie utwory z basem 16-bitowym w audio miały **o 1 kanał mniej** (np. Dungeon track 1 i 3 miały fizycznie tylko 1 słyszalny kanał audio!).")
    lines.append("")
    lines.append("## 2. Podsumowanie aktywności kanałów")
    lines.append("")
    lines.append("### A. Z perspektywy zapisu w Music/POKEY IR (zamierzone głosy):")
    for k in [1, 2, 3, 4]:
        lines.append(f"- **{k} aktywny kanał:** {ir_ch_dist[k]} utworów ({ir_ch_dist[k]/18*100:.1f}%)")
    lines.append("")
    lines.append("### B. Z perspektywy rzeczywistego odsłuchu audio (przez wyciszenie 16-bit bass):")
    for k in [1, 2, 3, 4]:
        lines.append(f"- **{k} aktywny kanał:** {audio_ch_dist[k]} utworów ({audio_ch_dist[k]/18*100:.1f}%)")
    lines.append("")
    lines.append("### C. Rozkład kanałów IR wg profili:")
    lines.append("| Profil | 1 kanał | 2 kanały | 3 kanały | 4 kanały | Średnia ch IR | Średnia ch Audio |")
    lines.append("|---|---|---|---|---|---|---|")
    for p in profiles:
        ir_c = [t["ir_active_channels"] for t in by_profile[p]]
        aud_c = [t["audio_active_channels"] for t in by_profile[p]]
        c1 = sum(1 for c in ir_c if c == 1)
        c2 = sum(1 for c in ir_c if c == 2)
        c3 = sum(1 for c in ir_c if c == 3)
        c4 = sum(1 for c in ir_c if c == 4)
        lines.append(f"| **{p.upper()}** | {c1} | {c2} | {c3} | {c4} | {np.mean(ir_c):.1f} | {np.mean(aud_c):.1f} |")
    lines.append("")
    lines.append("## 3. Szczegółowe metryki wszystkich 18 utworów v3")
    lines.append("")
    lines.append("| Utwór | Forma | Dur [s] | IR Ch | Aud Ch | Aktywne nuty (Ch1/2/3/4) | Role (Ch1 / Ch2 / Ch3 / Ch4) | Zakresy wysokości | Gęstość [n/s] | POKEY IR [B] | Stosunek akt. IR (1:2:3:4) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for t in all_tracks:
        nc = f"{t['note_counts'][1]}/{t['note_counts'][2]}/{t['note_counts'][3]}/{t['note_counts'][4]}"
        roles = f"{t['roles'][1]} / {t['roles'][2]} / {t['roles'][3]} / {t['roles'][4]}"
        pr = f"C1:{t['pitch_ranges'][1]}<br>C2:{t['pitch_ranges'][2]}<br>C3:{t['pitch_ranges'][3]}<br>C4:{t['pitch_ranges'][4]}"
        lines.append(f"| **{t['profile'].upper()}** {t['track_id']} | {t['form']} | {t['duration_sec']} | {t['ir_active_channels']} | {t['audio_active_channels']} | {nc} | {roles} | {pr} | {t['note_density']} | {t['mem_size_bytes']} | {t['activity_ratio']} |")
    
    lines.append("")
    out_path = Path("experiments/composer_v3/audit_report.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Audit report saved to {out_path}")
    print("\n".join(lines[:60]))

if __name__ == "__main__":
    main()

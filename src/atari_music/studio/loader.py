"""Immutable composition loader and fidelity verification for Studio."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from atari_music.ai.client import (
    generate_music_from_composition,
    load_composition_dsl,
    load_composition_json,
)
from atari_music.ai.schema import AICompositionDoc
from atari_music.ai.validation import normalize_channel_idx
from atari_music.api import _load_song_input_for_arrange
from atari_music.instruments.planner import composition_musical_fingerprint
from atari_music.ir import (
    IRSong,
    note_name_to_midi,
    resolve_initial_channel_instruments,
    song_requires_v2,
)
from atari_music.studio.models import (
    ChannelAnalysis,
    CompositionFidelityError,
    LoadedCompositionState,
    StudioArrangementConfig,
)

_REST_TOKENS = frozenset({"", "---", "REST", "OFF", "SIL"})


def canonical_ir_sha256(song: IRSong) -> str:
    """Compute a deterministic SHA-256 hash over the complete IRSong payload."""
    payload = song.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_ai_rest(note_val: Optional[str]) -> bool:
    if note_val is None:
        return True
    return str(note_val).strip().upper() in _REST_TOKENS


def _verify_ai_to_ir_fidelity(doc: AICompositionDoc, ir_song: IRSong) -> None:
    """Verify AICompositionDoc -> IRSong compilation lost no instrument switches or 16-bit flag."""
    if bool(doc.hardware.use_16bit_bass) and not bool(ir_song.uses_16bit_bass):
        raise CompositionFidelityError(
            "16-bit bass hardware flag was not preserved during IRSong compilation."
        )
    if len(doc.sequence) != len(ir_song.sequence):
        raise CompositionFidelityError(
            f"Sequence length mismatch after IRSong compilation: expected {len(doc.sequence)}, got {len(ir_song.sequence)}."
        )
    if len(doc.patterns) != len(ir_song.patterns):
        raise CompositionFidelityError(
            f"Pattern count mismatch after IRSong compilation: expected {len(doc.patterns)}, got {len(ir_song.patterns)}."
        )

    inst_id_to_idx: Dict[str, int] = {inst.id: idx for idx, inst in enumerate(doc.instruments)}
    ir_id_to_idx: Dict[int, int] = {inst.id: idx for idx, inst in enumerate(ir_song.instruments)}

    for pat_idx, ai_pat in enumerate(doc.patterns):
        ir_pat = ir_song.patterns[pat_idx]
        ch_map = ai_pat.channels or {}
        has_zero = any(str(k).strip() == "0" for k in ch_map.keys())
        by_ch: Dict[int, List[Any]] = {1: [], 2: [], 3: [], 4: []}
        for raw_k, ev_list in ch_map.items():
            ch_num = normalize_channel_idx(raw_k, has_zero=has_zero)
            by_ch[ch_num].extend(ev_list)

        for ch_num in (1, 2, 3, 4):
            ai_events = [
                ev
                for ev in sorted(by_ch[ch_num], key=lambda e: e.step)
                if ev.step < ai_pat.length_steps and not _is_ai_rest(ev.note)
            ]
            ai_seq = [inst_id_to_idx[ev.instrument] for ev in ai_events if ev.instrument in inst_id_to_idx]
            ir_notes = [n for n in ir_pat.tracks.get(ch_num, ()) if not n.is_rest]
            ir_seq = [ir_id_to_idx.get(n.instrument_id, n.instrument_id) for n in ir_notes]

            if len(ai_events) == len(ai_seq) and ai_seq != ir_seq:
                used_names = list(dict.fromkeys(ev.instrument for ev in ai_events))
                raise CompositionFidelityError(
                    f"Pattern {ai_pat.id!r} channel {ch_num} uses multiple instruments ({used_names}), "
                    "which compile_composition_to_pokey_ir() collapsed because catalog_id is unset. "
                    "Studio refuses to discard mid-channel instrument switches silently."
                )


def _analyze_channels(ir_song: IRSong) -> Dict[int, ChannelAnalysis]:
    """Summarize musical metrics and PROGRAM_CHANGE usage per channel 1..4."""
    init_idx_map = resolve_initial_channel_instruments(ir_song)
    id_to_inst = {inst.id: inst for inst in ir_song.instruments}
    idx_to_inst = {idx: inst for idx, inst in enumerate(ir_song.instruments)}

    analyses: Dict[int, ChannelAnalysis] = {}
    for ch in (1, 2, 3, 4):
        pitches: List[int] = []
        durations: List[int] = []
        inst_names: List[str] = []
        inst_ids_used: List[int] = []
        pc_count = 0

        for pat in ir_song.patterns:
            for note in pat.tracks.get(ch, ()):
                if note.pending_program_changes:
                    pc_count += len(note.pending_program_changes)
                    for pid in note.pending_program_changes:
                        if pid not in inst_ids_used:
                            inst_ids_used.append(pid)
                        inst_obj = id_to_inst.get(pid)
                        if inst_obj is not None and inst_obj.name not in inst_names:
                            inst_names.append(inst_obj.name)
                if note.is_rest:
                    continue
                durations.append(int(note.duration))
                midi = note.midi_pitch
                if midi is None and note.pitch:
                    midi = note_name_to_midi(note.pitch)
                if midi is not None:
                    pitches.append(int(midi))
                if note.instrument_id not in inst_ids_used:
                    inst_ids_used.append(note.instrument_id)
                inst_obj = id_to_inst.get(note.instrument_id)
                if inst_obj is not None and inst_obj.name not in inst_names:
                    inst_names.append(inst_obj.name)

        init_idx = init_idx_map.get(ch, 0)
        init_inst = idx_to_inst.get(init_idx)
        init_name = init_inst.name if init_inst is not None else "Default"
        if init_name not in inst_names:
            inst_names.insert(0, init_name)

        role = init_inst.role if init_inst is not None else (
            "bass" if ch == 1 else "harmony" if ch == 2 else "melody" if ch == 3 else "percussion"
        )
        # Count explicit pending_program_changes OR mid-song instrument_id switches from initial
        has_switches = pc_count > 0 or len(set(inst_ids_used)) > 1
        avg_dur = (float(sum(durations)) / len(durations)) if durations else 0.0

        analyses[ch] = ChannelAnalysis(
            channel=ch,
            note_count=len(durations),
            active=len(durations) > 0,
            role=role,
            initial_instrument_name=init_name,
            original_instrument_names=tuple(inst_names),
            midi_min=min(pitches) if pitches else None,
            midi_max=max(pitches) if pitches else None,
            avg_duration=round(avg_dur, 2),
            has_program_changes=has_switches,
            program_change_count=pc_count,
            distinct_instruments_count=len(set(inst_ids_used)),
        )
    return analyses


def load_studio_composition(source: Path | str) -> LoadedCompositionState:
    """Load `.dsl`, `AICompositionDoc` JSON, or `IRSong` JSON into an immutable Studio state."""
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Composition file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")
    stripped = raw_text.lstrip()
    is_dsl = path.suffix.lower() == ".dsl" or (path.suffix.lower() != ".json" and not stripped.startswith("{"))

    source_ai_doc: Optional[AICompositionDoc] = None
    if is_dsl:
        source_kind: str = "dsl"
        doc = load_composition_dsl(path)
        source_ai_doc = doc.model_copy(deep=True)
        compiled = generate_music_from_composition(doc)
        _verify_ai_to_ir_fidelity(doc, compiled.pokey_ir)
        base_ir = compiled.pokey_ir.model_copy(deep=True)
        base_music = compiled.music_ir.model_copy(deep=True)
    else:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected JSON object in '{path}', got {type(parsed).__name__}")
        if parsed.get("format") == "atari-music-composition":
            source_kind = "ai-composition"
            doc = load_composition_json(parsed)
            source_ai_doc = doc.model_copy(deep=True)
            compiled = generate_music_from_composition(doc)
            _verify_ai_to_ir_fidelity(doc, compiled.pokey_ir)
            base_ir = compiled.pokey_ir.model_copy(deep=True)
            base_music = compiled.music_ir.model_copy(deep=True)
        else:
            source_kind = "pokey-ir"
            ir_song = IRSong.from_json_file(path)
            base_ir, base_music, _ = _load_song_input_for_arrange(ir_song)

    v2_reasons = tuple(song_requires_v2(base_ir))
    channels = _analyze_channels(base_ir)
    baseline_cfg = StudioArrangementConfig()

    return LoadedCompositionState(
        source_path=path,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_ai_doc=source_ai_doc,
        base_pokey_ir=base_ir,
        base_music_ir=base_music,
        base_ir_sha256=canonical_ir_sha256(base_ir),
        musical_fingerprint=composition_musical_fingerprint(base_ir),
        title=base_ir.title,
        author=base_ir.author,
        key=base_ir.key,
        mode=base_ir.mode,
        tempo_bpm=int(base_ir.tempo_bpm),
        pattern_count=len(base_ir.patterns),
        sequence_length=len(base_ir.sequence),
        frames_per_tick=int(base_ir.frames_per_tick),
        base_uses_16bit_bass=bool(base_ir.uses_16bit_bass),
        base_v1_compatible=(len(v2_reasons) == 0),
        base_v2_reasons=v2_reasons,
        channels=channels,
        baseline_config=baseline_cfg,
    )

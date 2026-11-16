"""Independent Python frame-accurate POKEY player v1/v2 oracle simulator.

Simulates both:
1. Compiled 6502 binary song payloads directly from 6502 memory bytes
   (``simulate_v2_binary_frames`` — zero dependency on exporter Python objects).
2. Symbolic ``IRSong`` structures directly (``simulate_ir_song_frames``).

Produces per-frame snapshots of POKEY hardware registers ``($D200..$D208)`` matching
``src/atari_music/asm/player.asm`` byte-for-byte with zero tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_JOIN_1_2_16BIT,
    DISTORTION_PURE_TONE,
    DISTORTION_WHITE_NOISE,
)
from atari_music.ir import (
    INST_FLAG_MOD_OCTAVE_PULSE,
    MACRO_END_MARKER,
    MACRO_FLAG_AUDF_FIXED,
    MACRO_FLAG_USE_STEP_DIST,
    MACRO_FLAG_USE_VOL_OVERRIDE,
    MACRO_NO_OFFSET,
    MAX_V2_INSTRUMENTS,
    MAX_V2_OPCODE,
    OPCODE_PROGRAM_CHANGE,
    IRInstrument,
    IRMacroStep,
    IRNote,
    IRSong,
    frequency_to_audf_16bit,
    frequency_to_audf_8bit,
    midi_pitch_to_frequency,
    note_name_to_midi,
    plan_v2_pattern_streams,
    resolve_audctl_mode,
    resolve_initial_channel_instruments,
)

MAX_V2_PARSE_COMMANDS = 8

POKEY_REG_ORDER: Tuple[int, ...] = (
    0xD200,  # AUDF1
    0xD201,  # AUDC1
    0xD202,  # AUDF2
    0xD203,  # AUDC2
    0xD204,  # AUDF3
    0xD205,  # AUDC3
    0xD206,  # AUDF4
    0xD207,  # AUDC4
    0xD208,  # AUDCTL
)


@dataclass
class _CompiledInstrument:
    dist: int
    att: int
    dec: int
    sus: int
    rel: int
    flags: int
    macro_steps: Tuple[Tuple[int, int, int, int], ...]  # (dur, flags, audc_val, signed/fixed audf)
    pitch_start: int  # signed -127..127
    pitch_dur: int    # 0..15
    pitch_step: int   # signed -16..16


@dataclass
class _ChannelState:
    inst_idx: int = 0
    dist: int = DISTORTION_PURE_TONE
    att: int = 0
    dec: int = 0
    sus: int = 0
    rel: int = 0
    mod_flags: int = 0
    macro_steps: Tuple[Tuple[int, int, int, int], ...] = ()
    p_start: int = 0
    p_dur: int = 0
    p_step: int = 0

    audf: int = 0
    audf_base: int = 0
    dur: int = 0
    peak_vol: int = 0
    cur_vol: int = 0
    sus_lvl: int = 0
    env_phase: int = 0
    env_frame: int = 0
    mute_mask: int = 0
    mod_phase: int = 1

    out_dist: int = 0
    out_vol: int = 0

    macro_active: bool = False
    macro_step_idx: int = 0
    macro_cnt: int = 0
    pitch_rem: int = 0
    pitch_delta: int = 0

    # Stream cursor used during simulation: either memory address or list index
    ptr: int = 0


def _u8(val: int) -> int:
    return int(val) & 0xFF


def _s8(byte_val: int) -> int:
    v = int(byte_val) & 0xFF
    return v - 256 if v >= 128 else v


def _clamp_s8(val: int) -> int:
    """Two's complement signed 8-bit saturation matching 6502 BVC clamp ($80..$7F)."""
    if val < -128:
        return -128
    if val > 127:
        return 127
    return val


def _add_signed_clamp_u8(base_u8: int, signed_delta: int) -> int:
    """Clamp unsigned 8-bit register value + signed offset cleanly to 0..255."""
    total = (int(base_u8) & 0xFF) + int(signed_delta)
    if total < 0:
        return 0
    if total > 255:
        return 255
    return total


def _step_channel_envelope(ch: _ChannelState, tempo_divider: int, tick_counter: int) -> None:
    """Update ADSR envelope for one VBI frame, matching ``player.asm`` bit-for-bit."""
    phase = ch.env_phase
    if phase == 0:
        ch.cur_vol = 0
        return
    if phase == 1:  # Attack
        if ch.att == 0:
            ch.env_phase = 2
            ch.env_frame = 0
            ch.cur_vol = ch.peak_vol
            return
        ch.env_frame = (ch.env_frame + 1) & 0xFF
        if ch.env_frame < ch.att:
            val = (ch.env_frame * ch.peak_vol) // ch.att
            ch.cur_vol = 1 if val == 0 else val
            return
        ch.env_phase = 2
        ch.env_frame = 0
        ch.cur_vol = ch.peak_vol
        return
    if phase == 2:  # Decay
        if ch.dec == 0:
            ch.env_phase = 3
            phase = 3
        else:
            ch.env_frame = (ch.env_frame + 1) & 0xFF
            if ch.env_frame < ch.dec:
                drop = (ch.env_frame * (ch.peak_vol - ch.sus_lvl)) // ch.dec
                ch.cur_vol = max(0, ch.peak_vol - drop)
                return
            ch.env_phase = 3
            phase = 3
    if phase == 3:  # Sustain
        ch.cur_vol = ch.sus_lvl
        if ch.rel > 0:
            if ch.rel >= ch.dur:
                if ch.dur == 0:
                    ch.env_phase = 4
                    phase = 4
                else:
                    frames_remaining = (ch.dur - 1) * tempo_divider + tick_counter
                    if frames_remaining <= ch.rel:
                        ch.env_phase = 4
                        phase = 4
    if phase == 4:  # Release
        if ch.cur_vol > 0:
            ch.cur_vol -= 1


def _step_channel_behavior(ch: _ChannelState, is_v2: bool) -> None:
    """Apply C1 modulation + v2 pitch envelope + v2 transient macro for one frame."""
    ch.out_dist = ch.dist
    ch.out_vol = ch.cur_vol

    if ch.mod_flags & INST_FLAG_MOD_OCTAVE_PULSE:
        ch.mod_phase ^= 1
        if ch.mod_phase != 0 and ch.cur_vol != 0:
            ch.audf = ch.audf_base >> 1
        else:
            ch.audf = ch.audf_base
    else:
        ch.audf = ch.audf_base

    if not is_v2:
        return
    if ch.env_phase == 0 and not ch.macro_active:
        return

    # 1. Pitch Envelope
    if ch.pitch_rem > 0:
        ch.audf = _add_signed_clamp_u8(ch.audf, ch.pitch_delta)
        ch.pitch_rem -= 1
        if ch.pitch_rem == 0:
            ch.pitch_delta = 0
        else:
            ch.pitch_delta = _clamp_s8(ch.pitch_delta + ch.p_step)

    # 2. Transient Macro Engine
    if ch.macro_active and ch.macro_step_idx < len(ch.macro_steps):
        _dur, m_flags, m_audc, m_audf = ch.macro_steps[ch.macro_step_idx]
        if m_flags & MACRO_FLAG_USE_STEP_DIST:
            ch.out_dist = m_audc & 0xE0
        if m_flags & MACRO_FLAG_USE_VOL_OVERRIDE:
            ch.out_vol = m_audc & 0x0F
        if m_flags & MACRO_FLAG_AUDF_FIXED:
            ch.audf = m_audf & 0xFF
        else:
            ch.audf = _add_signed_clamp_u8(ch.audf, _s8(m_audf))

        ch.macro_cnt -= 1
        if ch.macro_cnt == 0:
            ch.macro_step_idx += 1
            if ch.macro_step_idx >= len(ch.macro_steps):
                ch.macro_active = False
            else:
                ch.macro_cnt = ch.macro_steps[ch.macro_step_idx][0]


def _apply_instrument_to_channel(
    ch: _ChannelState, inst_idx: int, inst: _CompiledInstrument
) -> None:
    ch.inst_idx = inst_idx
    ch.dist = inst.dist
    ch.att = inst.att
    ch.dec = inst.dec
    ch.sus = inst.sus
    ch.rel = inst.rel
    ch.mod_flags = inst.flags
    ch.macro_steps = inst.macro_steps
    ch.p_start = inst.pitch_start
    ch.p_dur = inst.pitch_dur
    ch.p_step = inst.pitch_step


def _trigger_note_on_channel(
    ch: _ChannelState, audf: int, dur: int, peak_vol: int, is_v2: bool
) -> None:
    ch.audf = audf & 0xFF
    ch.audf_base = audf & 0xFF
    ch.dur = dur & 0xFF
    ch.peak_vol = peak_vol & 0xFF
    ch.mod_phase = 1
    ch.macro_active = False
    ch.pitch_rem = 0
    ch.pitch_delta = 0

    if ch.audf == 0 or ch.peak_vol == 0:
        ch.env_phase = 0
        ch.cur_vol = 0
        return

    ch.sus_lvl = min(ch.sus, ch.peak_vol)
    ch.env_phase = 1
    ch.env_frame = 0
    ch.cur_vol = 0

    if is_v2:
        if ch.p_dur > 0:
            ch.pitch_rem = ch.p_dur
            ch.pitch_delta = ch.p_start
        if ch.macro_steps and ch.macro_steps[0][0] > 0:
            ch.macro_active = True
            ch.macro_step_idx = 0
            ch.macro_cnt = ch.macro_steps[0][0]


def _snapshot_pokey_row(channels: Sequence[_ChannelState], audctl_mode: int) -> np.ndarray:
    """Compute exact POKEY ($D200..$D208) byte snapshot for one frame."""
    row = np.zeros(9, dtype=np.uint8)
    row[8] = audctl_mode & 0xFF
    if audctl_mode & AUDCTL_JOIN_1_2_16BIT:
        row[0] = channels[0].audf & 0xFF
        row[1] = 0
        row[2] = channels[1].audf & 0xFF
        muted_16 = (channels[0].mute_mask != 0) or (channels[1].mute_mask != 0) or (channels[1].out_vol == 0)
        row[3] = 0 if muted_16 else ((channels[1].out_dist & 0xE0) | (channels[1].out_vol & 0x0F))
    else:
        for idx in (0, 1):
            row[idx * 2] = channels[idx].audf & 0xFF
            muted = (channels[idx].mute_mask != 0) or (channels[idx].out_vol == 0)
            row[idx * 2 + 1] = 0 if muted else ((channels[idx].out_dist & 0xE0) | (channels[idx].out_vol & 0x0F))

    for idx in (2, 3):
        row[idx * 2] = channels[idx].audf & 0xFF
        muted = (channels[idx].mute_mask != 0) or (channels[idx].out_vol == 0)
        row[idx * 2 + 1] = 0 if muted else ((channels[idx].out_dist & 0xE0) | (channels[idx].out_vol & 0x0F))
    return row


def simulate_v2_binary_frames(
    memory: Union[Sequence[int], Mapping[int, int], bytearray, bytes],
    song_addr: int,
    num_frames: int,
    *,
    mute_schedule: Optional[Mapping[int, Tuple[int, int, int, int]]] = None,
) -> np.ndarray:
    """Simulate a compiled v1 or v2 POKEY song binary directly from 6502 RAM bytes.

    Independently parses headers, SoA instrument tables, macro pool, sequence list,
    ``PROGRAM_CHANGE`` commands, macros, pitch envelopes, and ADSR from raw memory.
    """
    if num_frames <= 0:
        return np.zeros((0, 9), dtype=np.uint8)

    def _u8_at(addr: int) -> int:
        return int(memory[addr & 0xFFFF]) & 0xFF

    def _u16_at(addr: int) -> int:
        return _u8_at(addr) | (_u8_at(addr + 1) << 8)

    tempo_divider = _u8_at(song_addr + 0)
    audctl_mode = _u8_at(song_addr + 1)
    inst_ptr = _u16_at(song_addr + 2)
    seq_ptr = _u16_at(song_addr + 4)

    version = _u8_at(inst_ptr)
    if version not in (1, 2):
        # Unsupported version: player refuses to start and keeps POKEY silent
        return np.zeros((num_frames, 9), dtype=np.uint8)

    is_v2 = version == 2
    instruments: List[_CompiledInstrument] = []
    init_inst_ids = [0, 1, 2, 3]

    if not is_v2:
        for ch_idx in range(4):
            base = inst_ptr + 1 + ch_idx * 6
            instruments.append(
                _CompiledInstrument(
                    dist=_u8_at(base + 0),
                    att=_u8_at(base + 1),
                    dec=_u8_at(base + 2),
                    sus=_u8_at(base + 3),
                    rel=_u8_at(base + 4),
                    flags=_u8_at(base + 5),
                    macro_steps=(),
                    pitch_start=0,
                    pitch_dur=0,
                    pitch_step=0,
                )
            )
    else:
        inst_count = _u8_at(inst_ptr + 1)
        if inst_count == 0 or inst_count > MAX_V2_INSTRUMENTS:
            return np.zeros((num_frames, 9), dtype=np.uint8)
        init_inst_ids = [_u8_at(inst_ptr + 2 + i) for i in range(4)]
        if any(idx >= inst_count for idx in init_inst_ids):
            return np.zeros((num_frames, 9), dtype=np.uint8)
        macros_ptr = _u16_at(inst_ptr + 6)
        soa_base = inst_ptr + 8

        def _soa(row_idx: int, inst_idx: int) -> int:
            return _u8_at(soa_base + row_idx * inst_count + inst_idx)

        for idx in range(inst_count):
            macro_off = _soa(6, idx)
            steps_list: List[Tuple[int, int, int, int]] = []
            if macro_off != MACRO_NO_OFFSET:
                step_addr = _u16_at(macros_ptr + macro_off)
                if step_addr != 0:
                    while True:
                        s_dur = _u8_at(step_addr)
                        if s_dur == MACRO_END_MARKER:
                            break
                        s_flags = _u8_at(step_addr + 1)
                        s_audc = _u8_at(step_addr + 2)
                        s_audf = _u8_at(step_addr + 3)
                        steps_list.append((s_dur, s_flags, s_audc, s_audf))
                        step_addr += 4
            instruments.append(
                _CompiledInstrument(
                    dist=_soa(0, idx),
                    att=_soa(1, idx),
                    dec=_soa(2, idx),
                    sus=_soa(3, idx),
                    rel=_soa(4, idx),
                    flags=_soa(5, idx),
                    macro_steps=tuple(steps_list),
                    pitch_start=_s8(_soa(7, idx)),
                    pitch_dur=_soa(8, idx),
                    pitch_step=_s8(_soa(9, idx)),
                )
            )

    channels = [_ChannelState() for _ in range(4)]
    for ch_idx in range(4):
        _apply_instrument_to_channel(channels[ch_idx], init_inst_ids[ch_idx], instruments[init_inst_ids[ch_idx]])

    seq_step_idx = 0

    def _load_pattern_ptrs() -> None:
        nonlocal seq_step_idx
        while True:
            pat_tracks_addr = _u16_at(seq_ptr + seq_step_idx)
            if pat_tracks_addr == 0xFFFF:
                seq_step_idx = 0
                continue
            for i in range(4):
                channels[i].ptr = _u16_at(pat_tracks_addr + i * 2)
            return

    def _early_end_track(ch: _ChannelState) -> None:
        ch.audf = 0
        ch.audf_base = 0
        ch.peak_vol = 0
        ch.cur_vol = 0
        ch.env_phase = 0
        ch.macro_active = False
        ch.pitch_rem = 0
        ch.pitch_delta = 0
        ch.dur = 1

    def _fetch_channel_note(ch_idx: int) -> None:
        nonlocal seq_step_idx
        ch = channels[ch_idx]
        cmd_guard = MAX_V2_PARSE_COMMANDS + 1
        while True:
            b0 = _u8_at(ch.ptr)
            if b0 == 0xFF:
                if ch_idx != 0:
                    _early_end_track(ch)
                    return
                seq_step_idx += 2
                _load_pattern_ptrs()
                cmd_guard = MAX_V2_PARSE_COMMANDS + 1
                continue
            if is_v2 and b0 == 0:
                b1 = _u8_at(ch.ptr + 1)
                if b1 == 0:
                    cmd_guard -= 1
                    if cmd_guard == 0:
                        _early_end_track(ch)
                        return
                    opcode = _u8_at(ch.ptr + 2)
                    param = _u8_at(ch.ptr + 3)
                    if opcode != OPCODE_PROGRAM_CHANGE or param >= len(instruments):
                        _early_end_track(ch)
                        return
                    ch.macro_active = False
                    ch.pitch_rem = 0
                    ch.pitch_delta = 0
                    ch.env_phase = 0
                    ch.cur_vol = 0
                    ch.mod_phase = 1
                    ch.ptr += 4
                    _apply_instrument_to_channel(ch, param, instruments[param])
                    continue

            dur = _u8_at(ch.ptr + 1)
            vol = _u8_at(ch.ptr + 2)
            ch.ptr += 3
            _trigger_note_on_channel(ch, b0, dur, vol, is_v2)
            return

    _load_pattern_ptrs()
    tick_counter = 1
    frames_out = np.zeros((num_frames, 9), dtype=np.uint8)

    for frame_idx in range(num_frames):
        if mute_schedule and frame_idx in mute_schedule:
            masks = mute_schedule[frame_idx]
            for i in range(4):
                channels[i].mute_mask = int(masks[i]) & 0xFF

        tick_counter = (tick_counter - 1) & 0xFF
        if tick_counter == 0:
            tick_counter = tempo_divider
            for ch_idx in range(4):
                if channels[ch_idx].dur == 0:
                    _fetch_channel_note(ch_idx)
                else:
                    channels[ch_idx].dur -= 1
                    if channels[ch_idx].dur == 0:
                        _fetch_channel_note(ch_idx)

        for ch_idx in range(4):
            _step_channel_envelope(channels[ch_idx], tempo_divider, tick_counter)
        for ch_idx in range(4):
            _step_channel_behavior(channels[ch_idx], is_v2)

        frames_out[frame_idx] = _snapshot_pokey_row(channels, audctl_mode)

    return frames_out


def simulate_ir_song_frames(
    song: IRSong,
    num_frames: Optional[int] = None,
    *,
    format_version: int = 2,
    mute_schedule: Optional[Mapping[int, Tuple[int, int, int, int]]] = None,
) -> np.ndarray:
    """Independently simulate symbolic ``IRSong`` directly into exact POKEY ``$D200..$D208`` frames."""
    if format_version not in (1, 2):
        raise ValueError(f"unsupported format_version {format_version!r}")

    if num_frames is None:
        pat_map = {p.id: p for p in song.patterns}
        total_rows = sum(pat_map[pid].rows for pid in song.sequence if pid in pat_map)
        num_frames = max(0, total_rows * int(song.frames_per_tick))
    if num_frames <= 0:
        return np.zeros((0, 9), dtype=np.uint8)

    audctl_mode = resolve_audctl_mode(song)
    tempo_divider = int(song.frames_per_tick)
    is_v2 = format_version == 2

    instruments: List[_CompiledInstrument] = []
    if not is_v2:
        inst_map = {inst.id: inst for inst in song.instruments}
        for ch_n in range(1, 5):
            if song.uses_16bit_bass and ch_n == 2:
                chosen = _resolve_v1_channel_inst(song, 1, inst_map)
                mod = pokey_hw.MODULATION_NONE
            else:
                chosen = _resolve_v1_channel_inst(song, ch_n, inst_map)
                mod = int(chosen.modulation)
            instruments.append(
                _CompiledInstrument(
                    dist=int(chosen.distortion) & 0xE0,
                    att=int(chosen.envelope.attack_frames),
                    dec=int(chosen.envelope.decay_frames),
                    sus=int(chosen.envelope.sustain_vol),
                    rel=int(chosen.envelope.release_frames),
                    flags=INST_FLAG_MOD_OCTAVE_PULSE if pokey_hw.is_octave_pulse(mod) else 0,
                    macro_steps=(),
                    pitch_start=0,
                    pitch_dur=0,
                    pitch_step=0,
                )
            )
        init_ids = [0, 1, 2, 3]
        stream_by_pat = _symbolic_v1_streams(song, audctl_mode)
    else:
        for inst in song.instruments:
            steps: List[Tuple[int, int, int, int]] = []
            if inst.macro and any(s.is_v2_step() for s in inst.macro):
                for s in inst.macro:
                    is_fix = 1 if s.audf_mode == "fixed" else 0
                    use_d = 1 if s.audc_dist is not None else 0
                    use_v = 1 if s.vol_override is not None else 0
                    flags = (
                        (MACRO_FLAG_AUDF_FIXED if is_fix else 0)
                        | (MACRO_FLAG_USE_STEP_DIST if use_d else 0)
                        | (MACRO_FLAG_USE_VOL_OVERRIDE if use_v else 0)
                    )
                    d_b = (int(s.audc_dist) & 0xE0) if use_d else (int(inst.distortion) & 0xE0)
                    v_b = (int(s.vol_override) & 0x0F) if use_v else 0
                    a_b = int(s.fixed_audf or 0) & 0xFF if is_fix else (int(s.audf_offset) & 0xFF)
                    steps.append((int(s.frames_per_step), flags, d_b | v_b, a_b))
            pe = inst.pitch_envelope
            p_s = int(pe.start_audf_delta) if (pe and pe.duration_frames > 0) else 0
            p_d = int(pe.duration_frames) if (pe and pe.duration_frames > 0) else 0
            p_st = int(pe.step_delta) if (pe and pe.duration_frames > 0) else 0
            instruments.append(
                _CompiledInstrument(
                    dist=int(inst.distortion) & 0xE0,
                    att=int(inst.envelope.attack_frames),
                    dec=int(inst.envelope.decay_frames),
                    sus=int(inst.envelope.sustain_vol),
                    rel=int(inst.envelope.release_frames),
                    flags=INST_FLAG_MOD_OCTAVE_PULSE if pokey_hw.is_octave_pulse(inst.modulation) else 0,
                    macro_steps=tuple(steps),
                    pitch_start=p_s,
                    pitch_dur=p_d,
                    pitch_step=p_st,
                )
            )
        init_map, raw_pat_streams = plan_v2_pattern_streams(song)
        init_ids = [init_map[c] for c in range(1, 5)]
        stream_by_pat = {
            pid: {
                ch: [b for _k, raw, _c in evs for b in raw]
                for ch, evs in ch_map.items()
            }
            for pid, ch_map in raw_pat_streams.items()
        }

    channels = [_ChannelState() for _ in range(4)]
    for ch_idx in range(4):
        _apply_instrument_to_channel(channels[ch_idx], init_ids[ch_idx], instruments[init_ids[ch_idx]])

    seq_pos = 0
    active_streams: List[List[int]] = [[], [], [], []]

    def _load_pat() -> None:
        nonlocal seq_pos
        if not song.sequence:
            for c in range(4):
                active_streams[c] = [0xFF]
                channels[c].ptr = 0
            return
        if seq_pos >= len(song.sequence):
            seq_pos = 0
        pat_id = song.sequence[seq_pos]
        for c in range(4):
            active_streams[c] = stream_by_pat[pat_id][c + 1]
            channels[c].ptr = 0

    def _fetch(ch_idx: int) -> None:
        nonlocal seq_pos
        ch = channels[ch_idx]
        while True:
            buf = active_streams[ch_idx]
            b0 = buf[ch.ptr] if ch.ptr < len(buf) else 0xFF
            if b0 == 0xFF:
                if ch_idx != 0:
                    ch.audf = ch.audf_base = ch.peak_vol = ch.cur_vol = ch.env_phase = 0
                    ch.macro_active = False
                    ch.pitch_rem = ch.pitch_delta = 0
                    ch.dur = 1
                    return
                seq_pos += 1
                _load_pat()
                continue
            if is_v2 and b0 == 0 and ch.ptr + 3 < len(buf) and buf[ch.ptr + 1] == 0:
                opcode = buf[ch.ptr + 2]
                param = buf[ch.ptr + 3]
                if opcode != OPCODE_PROGRAM_CHANGE or param >= len(instruments):
                    ch.audf = ch.audf_base = ch.peak_vol = ch.cur_vol = ch.env_phase = 0
                    ch.macro_active = False
                    ch.pitch_rem = ch.pitch_delta = 0
                    ch.dur = 1
                    return
                ch.macro_active = False
                ch.pitch_rem = ch.pitch_delta = 0
                ch.env_phase = ch.cur_vol = 0
                ch.mod_phase = 1
                ch.ptr += 4
                _apply_instrument_to_channel(ch, param, instruments[param])
                continue
            dur = buf[ch.ptr + 1]
            vol = buf[ch.ptr + 2]
            ch.ptr += 3
            _trigger_note_on_channel(ch, b0, dur, vol, is_v2)
            return

    _load_pat()
    tick_counter = 1
    out = np.zeros((num_frames, 9), dtype=np.uint8)
    for f_idx in range(num_frames):
        if mute_schedule and f_idx in mute_schedule:
            masks = mute_schedule[f_idx]
            for i in range(4):
                channels[i].mute_mask = int(masks[i]) & 0xFF
        tick_counter = (tick_counter - 1) & 0xFF
        if tick_counter == 0:
            tick_counter = tempo_divider
            for ch_idx in range(4):
                if channels[ch_idx].dur == 0:
                    _fetch(ch_idx)
                else:
                    channels[ch_idx].dur -= 1
                    if channels[ch_idx].dur == 0:
                        _fetch(ch_idx)
        for ch_idx in range(4):
            _step_channel_envelope(channels[ch_idx], tempo_divider, tick_counter)
        for ch_idx in range(4):
            _step_channel_behavior(channels[ch_idx], is_v2)
        out[f_idx] = _snapshot_pokey_row(channels, audctl_mode)

    return out


def _resolve_v1_channel_inst(
    song: IRSong, ch: int, inst_map: Mapping[int, IRInstrument]
) -> IRInstrument:
    for pat in song.patterns:
        for n in pat.tracks.get(ch, []):
            if not n.is_rest and n.instrument_id in inst_map:
                return inst_map[n.instrument_id]
    for pat in song.patterns:
        for n in pat.tracks.get(ch, []):
            if n.instrument_id in inst_map:
                return inst_map[n.instrument_id]
    for pat in song.patterns:
        for n in pat.tracks.get(ch, []):
            if n.channel_role == "percussion":
                for inst in inst_map.values():
                    if inst.role == "percussion" or inst.distortion == DISTORTION_WHITE_NOISE:
                        return inst
                return IRInstrument(id=ch - 1, name=f"Ch{ch}_Perc", distortion=DISTORTION_WHITE_NOISE, role="percussion")
    if (ch - 1) in inst_map:
        return inst_map[ch - 1]
    if inst_map:
        return next(iter(inst_map.values()))
    return IRInstrument(id=ch - 1, name=f"Ch{ch}", distortion=DISTORTION_PURE_TONE)


def _symbolic_v1_streams(song: IRSong, audctl_val: int) -> Dict[int, Dict[int, List[int]]]:
    out: Dict[int, Dict[int, List[int]]] = {}
    for pat in song.patterns:
        ch_map: Dict[int, List[int]] = {}
        for ch in range(1, 5):
            raw: List[int] = []
            notes = pat.tracks.get(1, []) if (song.uses_16bit_bass and ch == 2) else pat.tracks.get(ch, [])
            if not notes:
                raw.extend((0x00, max(1, min(255, pat.rows)), 0x00, 0xFF))
                ch_map[ch] = raw
                continue
            for n in notes:
                dur = max(1, min(255, int(n.duration)))
                midi_val = n.midi_pitch
                if midi_val is None and n.pitch and str(n.pitch).upper() not in ("---", "REST", "OFF", "SIL", ""):
                    midi_val = note_name_to_midi(str(n.pitch))
                unpitched = pokey_hw.is_unpitched_percussion(midi_val, n.channel_role)
                if n.is_rest or (midi_val is None and not unpitched):
                    raw.extend((0, dur, 0))
                elif unpitched:
                    raw.extend((pokey_hw.clamp_audf_for_tracker(pokey_hw.PERCUSSION_DEFAULT_AUDF), dur, min(15, max(0, n.volume))))
                elif song.uses_16bit_bass and ch == 2:
                    _, hi = frequency_to_audf_16bit(midi_pitch_to_frequency(midi_val), audctl=audctl_val, channel=1)
                    raw.extend((pokey_hw.clamp_audf_for_tracker(hi), dur, min(15, max(0, n.volume))))
                elif song.uses_16bit_bass and ch == 1:
                    lo, _ = frequency_to_audf_16bit(midi_pitch_to_frequency(midi_val), audctl=audctl_val, channel=1)
                    raw.extend((pokey_hw.clamp_audf_for_tracker(lo), dur, 0))
                else:
                    raw.extend((pokey_hw.clamp_audf_for_tracker(frequency_to_audf_8bit(midi_pitch_to_frequency(midi_val), audctl=audctl_val, channel=ch)), dur, min(15, max(0, n.volume))))
            raw.append(0xFF)
            ch_map[ch] = raw
        out[pat.id] = ch_map
    return out

"""Hardware-accurate Software Synthesizer for Atari POKEY Audio.

Simulates POKEY hardware audio generation directly from a stream of 50 Hz register writes:
- CPU-clocked timer events (64 kHz / 15 kHz / 1.79 MHz) via :mod:`atari_music.pokey_hw`
- Hardware-true LFSR progression and gating:
    * $A0 / $E0: pure tone toggle
    * $C0:       poly4 direct (15-step LFSR clocked at 1.77 MHz; reproduces mod-3/5 stalls)
    * $20 / $60: poly5-gated pure tone (31-step XNOR active-gate polarity -> 62-tick cycle)
    * $40:       poly5-gated poly4 (sample-and-hold on CPU timer ticks)
    * $80:       poly9/poly17 direct (unpitched noise clocked at 1.77 MHz)
    * $00:       poly5-gated poly9/poly17
    * bit 4 $10: volume-only 4-bit DAC output
- Digital High-Pass Filter (HPF XOR D-latch):
    * AUDCTL $02 (bit 1): CH2 filtered by CH4 timer ticks
    * AUDCTL $04 (bit 2): CH1 filtered by CH3 timer ticks
- 16-bit channel joining:
    * AUDCTL $10: CH1 + CH2 joined (CH2 outputs)
    * AUDCTL $08: CH3 + CH4 joined (CH4 outputs)
- Opt-in static CORE_V1 InstrumentCatalog / POKEYRuntime WAV preview synthesis
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Tuple
import wave

import numpy as np

from atari_music import pokey_hw
from atari_music.constants import (
    AUDCTL_9BIT_POLY,
    AUDCTL_HIPASS_CH1_CH3,
    AUDCTL_HIPASS_CH2_CH4,
    AUDCTL_JOIN_1_2_16BIT,
    AUDCTL_JOIN_3_4_16BIT,
    PAL_CLOCK_HZ,
)

if TYPE_CHECKING:
    from atari_music.instruments import (
        InstrumentCatalog,
        RuntimeDiagnostic,
        TargetCapability,
    )

# Public m-sequences preserved verbatim for existing tests & experiment parity.
POLY4_SEQ = np.array(
    pokey_hw.generate_lfsr4_sequence(legacy_polarity=True), dtype=np.float32
)
POLY5_SEQ = np.array(
    pokey_hw.generate_lfsr5_sequence(active_gate_polarity=False, legacy_order=True),
    dtype=np.float32,
)


def _generate_lfsr17_sequence() -> np.ndarray:
    """Generate 17-bit POKEY LFSR maximal-length bitstream (131071 states, poly: 1 + x^12 + x^17)."""
    bits = np.asarray(pokey_hw.generate_lfsr17_sequence(), dtype=np.float32)
    return bits * 2.0 - 1.0


def _generate_lfsr9_sequence() -> np.ndarray:
    """Generate 9-bit POKEY LFSR maximal-length bitstream (511 states, poly: 1 + x^4 + x^9)."""
    bits = np.asarray(pokey_hw.generate_lfsr9_sequence(), dtype=np.float32)
    return bits * 2.0 - 1.0


POLY17_SEQ = _generate_lfsr17_sequence()
POLY9_SEQ = _generate_lfsr9_sequence()

# Internal uint8 lookup tables matching real POKEY silicon / ASAP bit order & polarity.
_POLY4_BITS = np.asarray(
    pokey_hw.generate_lfsr4_sequence(legacy_polarity=False), dtype=np.uint8
)
_POLY5_HW_GATE = np.asarray(
    pokey_hw.generate_lfsr5_sequence(active_gate_polarity=True), dtype=np.uint8
)
_POLY9_BITS = (POLY9_SEQ > 0.0).astype(np.uint8)
_POLY17_BITS = (POLY17_SEQ > 0.0).astype(np.uint8)

# POKEY Non-Linear Resistor Ladder DAC (16 volume levels 0..15)
POKEY_DAC = np.array(
    [
        0.0000, 0.0075, 0.0170, 0.0290, 0.0460, 0.0680, 0.0980, 0.1370,
        0.1880, 0.2520, 0.3340, 0.4400, 0.5750, 0.7480, 0.8800, 1.0000,
    ],
    dtype=np.float32,
)


class InstrumentRenderError(ValueError):
    """Raised when a profile or binding cannot be rendered without silent degradation."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Tuple[RuntimeDiagnostic, ...] = (),
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def _gated_sample_and_hold(poly_bits: np.ndarray, gate: np.ndarray, init_bit: int) -> np.ndarray:
    """Latch ``poly_bits`` whenever ``gate`` is 1, holding previous bit when ``gate`` is 0."""
    n = len(poly_bits)
    if n == 0:
        return np.empty(0, dtype=np.uint8)
    all_bits = np.empty(n + 1, dtype=np.uint8)
    all_bits[0] = init_bit & 1
    all_bits[1:] = poly_bits
    mask = np.empty(n + 1, dtype=bool)
    mask[0] = True
    mask[1:] = gate.astype(bool)
    hold_idx = np.maximum.accumulate(np.where(mask, np.arange(n + 1, dtype=np.int64), 0))
    return all_bits[hold_idx[1:]]


def _evaluate_channel_ticks(
    ticks_cycle: np.ndarray,
    waveform: pokey_hw.Waveform,
    out_bit: int,
    use_9bit: bool,
) -> Tuple[np.ndarray, int]:
    """Compute output bit (0 or 1) at each CPU timer underflow in ``ticks_cycle``."""
    k = len(ticks_cycle)
    if k == 0:
        return np.empty(0, dtype=np.uint8), out_bit

    if waveform == pokey_hw.Waveform.PURE_TONE:
        bits = (out_bit ^ 1 ^ (np.arange(k, dtype=np.uint8) & 1)).astype(np.uint8)
    elif waveform == pokey_hw.Waveform.POLY4:
        bits = _POLY4_BITS[ticks_cycle % pokey_hw.POLY4_PERIOD]
    elif waveform == pokey_hw.Waveform.POLY9_17:
        noise = _POLY9_BITS if use_9bit else _POLY17_BITS
        bits = noise[ticks_cycle % len(noise)]
    elif waveform == pokey_hw.Waveform.POLY5_GATED_PURE:
        gate = _POLY5_HW_GATE[ticks_cycle % pokey_hw.POLY5_PERIOD]
        bits = ((out_bit + np.cumsum(gate, dtype=np.int64)) & 1).astype(np.uint8)
    elif waveform == pokey_hw.Waveform.POLY5_GATED_POLY4:
        gate = _POLY5_HW_GATE[ticks_cycle % pokey_hw.POLY5_PERIOD]
        poly = _POLY4_BITS[ticks_cycle % pokey_hw.POLY4_PERIOD]
        bits = _gated_sample_and_hold(poly, gate, out_bit)
    elif waveform == pokey_hw.Waveform.POLY5_GATED_POLY9_17:
        gate = _POLY5_HW_GATE[ticks_cycle % pokey_hw.POLY5_PERIOD]
        noise = _POLY9_BITS if use_9bit else _POLY17_BITS
        poly = noise[ticks_cycle % len(noise)]
        bits = _gated_sample_and_hold(poly, gate, out_bit)
    else:  # VOLUME_ONLY
        bits = np.ones(k, dtype=np.uint8)

    return bits, int(bits[-1])


def _apply_hpf_xor(
    ticks_src: np.ndarray,
    bits_src: np.ndarray,
    ticks_ctl: np.ndarray,
    src_init: int,
    latch_init: int,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """Apply POKEY digital HPF (D-latch on control channel ticks XORed with source output)."""
    if len(ticks_ctl) == 0:
        if len(bits_src) == 0:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.uint8), latch_init
        return ticks_src, (bits_src ^ (latch_init & 1)).astype(np.uint8), latch_init

    if len(ticks_src) == 0:
        # Source did not transition this frame; control ticks latch current src_init.
        ev_bits = np.full(len(ticks_ctl), (src_init ^ src_init) & 1, dtype=np.uint8)
        return ticks_ctl, ev_bits, src_init

    # Merge source transitions (kind=0) and control clocks (kind=1) stably by CPU cycle.
    n_src = len(ticks_src)
    n_ctl = len(ticks_ctl)
    all_t = np.concatenate((ticks_src, ticks_ctl))
    all_kind = np.concatenate((np.zeros(n_src, dtype=np.uint8), np.ones(n_ctl, dtype=np.uint8)))
    all_src_idx = np.concatenate(
        (np.arange(n_src, dtype=np.int64), np.full(n_ctl, -1, dtype=np.int64))
    )
    order = np.argsort(all_t, kind="mergesort")
    ev_t = all_t[order]
    ev_kind = all_kind[order]
    ev_idx = all_src_idx[order]

    cur_src = src_init & 1
    cur_latch = latch_init & 1
    ev_out = np.empty(len(ev_t), dtype=np.uint8)
    for i in range(len(ev_t)):
        if ev_kind[i] == 0:
            cur_src = int(bits_src[int(ev_idx[i])])
        else:
            cur_latch = cur_src
        ev_out[i] = cur_src ^ cur_latch
    return ev_t, ev_out, cur_latch


def _box_integrate_events(
    ev_t: np.ndarray,
    ev_bits: np.ndarray,
    t0: float,
    t1: float,
    n_samples: int,
    bit_before: int,
) -> np.ndarray:
    """Analytically average piecewise-constant digital transitions across each audio sample."""
    val_before = 1.0 if (bit_before & 1) else -1.0
    if len(ev_t) == 0:
        return np.full(n_samples, val_before, dtype=np.float32)

    cps = (t1 - t0) / float(n_samples)
    sample_edges = t0 + np.arange(n_samples + 1, dtype=np.float64) * cps

    t_all = np.empty(len(ev_t) + 2, dtype=np.float64)
    t_all[0] = t0
    t_all[1:-1] = ev_t
    t_all[-1] = t1

    v_seg = np.empty(len(ev_bits) + 1, dtype=np.float64)
    v_seg[0] = val_before
    v_seg[1:] = np.where(ev_bits > 0, 1.0, -1.0)

    dt = np.diff(t_all)
    prefix = np.empty(len(t_all), dtype=np.float64)
    prefix[0] = 0.0
    np.cumsum(v_seg * dt, out=prefix[1:])

    idx = np.searchsorted(t_all, sample_edges, side="right") - 1
    idx = np.clip(idx, 0, len(v_seg) - 1)
    integrated = prefix[idx] + v_seg[idx] * (sample_edges - t_all[idx])
    return (np.diff(integrated) / cps).astype(np.float32)


def _validate_profile_bindings_for_frames(
    frames: np.ndarray,
    profile_assignments: Mapping[int, str],
    catalog: Optional["InstrumentCatalog"],
    target: Optional["TargetCapability"],
) -> None:
    """Verify opt-in bindings via POKEYRuntime without mutating or downgrading frames."""
    from atari_music.instruments import (
        TARGET_WAV_PREVIEW,
        ChannelAssignmentRequest,
        POKEYRuntime,
        load_instrument_catalog,
    )

    cat = catalog if catalog is not None else load_instrument_catalog()
    resolved_target = TARGET_WAV_PREVIEW if target is None else target
    requests = [
        ChannelAssignmentRequest(channel=ch, instrument_ids=(inst_id,))
        for ch, inst_id in sorted(profile_assignments.items())
    ]
    report = POKEYRuntime.resolve(requests, cat, resolved_target)
    if not report.is_compatible:
        msgs = "; ".join(f"[{d.code}] {d.message}" for d in report.diagnostics if d.severity == "ERROR")
        raise InstrumentRenderError(
            f"profile assignments incompatible with target {resolved_target.backend!r}: {msgs}",
            diagnostics=report.diagnostics,
        )
    if len(frames) > 0:
        unique_audctl = {int(v) for v in frames[:, 8]}
        if unique_audctl != {report.effective_audctl}:
            raise InstrumentRenderError(
                f"frame stream AUDCTL {sorted(hex(v) for v in unique_audctl)} disagrees with "
                f"resolved profile AUDCTL 0x{report.effective_audctl:02x}",
                diagnostics=report.diagnostics,
            )


def render_pokey_to_wav(
    frames: np.ndarray,
    output_wav_path: Path,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
    *,
    profile_assignments: Optional[Mapping[int, str]] = None,
    catalog: Optional["InstrumentCatalog"] = None,
    target: Optional["TargetCapability"] = None,
) -> None:
    """Render ``(total_frames, 9)`` POKEY register stream into 44.1 kHz 16-bit WAV."""
    samples = render_pokey_samples(
        frames,
        sample_rate,
        frame_rate_hz,
        profile_assignments=profile_assignments,
        catalog=catalog,
        target=target,
    )

    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def render_pokey_samples(
    frames: np.ndarray,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
    *,
    profile_assignments: Optional[Mapping[int, str]] = None,
    catalog: Optional["InstrumentCatalog"] = None,
    target: Optional["TargetCapability"] = None,
) -> np.ndarray:
    """Render POKEY registers into hardware-accurate PCM audio buffer (int16)."""
    if frames.ndim != 2 or frames.shape[1] != 9:
        raise ValueError(f"frames must have shape (N, 9), got {frames.shape!r}")
    if profile_assignments is not None:
        _validate_profile_bindings_for_frames(frames, profile_assignments, catalog, target)

    num_frames = int(frames.shape[0])
    if num_frames == 0:
        return np.zeros(0, dtype=np.int16)

    samples_per_frame = int(round(sample_rate / frame_rate_hz))
    total_samples = num_frames * samples_per_frame
    audio_mix = np.zeros(total_samples, dtype=np.float32)

    cycles_per_frame = PAL_CLOCK_HZ / float(frame_rate_hz)

    # Fresh per-render chip state so subsequent renders never leak phase or LFSR state.
    next_tick_cycle = np.zeros(4, dtype=np.float64)
    prev_periods = np.zeros(4, dtype=np.int64)
    was_ticking = np.zeros(4, dtype=bool)
    out_bits = np.zeros(4, dtype=np.uint8)
    hpf_latches = np.zeros(2, dtype=np.uint8)  # [0]: CH1<-CH3 ($04), [1]: CH2<-CH4 ($02)

    for f_idx in range(num_frames):
        f_row = frames[f_idx]
        audctl = int(f_row[8]) & 0xFF
        audf_regs = (int(f_row[0]), int(f_row[2]), int(f_row[4]), int(f_row[6]))
        audc_regs = (int(f_row[1]), int(f_row[3]), int(f_row[5]), int(f_row[7]))

        t0 = f_idx * cycles_per_frame
        t1 = (f_idx + 1) * cycles_per_frame
        s_start = f_idx * samples_per_frame
        s_end = s_start + samples_per_frame

        is_16bit_12 = bool(audctl & AUDCTL_JOIN_1_2_16BIT)
        is_16bit_34 = bool(audctl & AUDCTL_JOIN_3_4_16BIT)
        hpf_1_by_3 = bool(audctl & AUDCTL_HIPASS_CH1_CH3)
        hpf_2_by_4 = bool(audctl & AUDCTL_HIPASS_CH2_CH4)
        use_9bit = bool(audctl & AUDCTL_9BIT_POLY)

        # Determine which timers must advance in hardware (audible OR HPF clock source).
        need_ticks = [False, False, False, False]
        audible = [False, False, False, False]
        for ch in range(4):
            vol = audc_regs[ch] & 0x0F
            is_lsb_slave = (is_16bit_12 and ch == 0) or (is_16bit_34 and ch == 2)
            if vol > 0 and not is_lsb_slave:
                audible[ch] = True
                if pokey_hw.decode_audc(audc_regs[ch]) != pokey_hw.Waveform.VOLUME_ONLY:
                    need_ticks[ch] = True

        # HPF XOR ($04 CH1<-CH3, $02 CH2<-CH4) clocks D-latch on paired channel's timer even when muted.
        if hpf_1_by_3 and audible[0]:
            need_ticks[2] = True
        if hpf_2_by_4 and audible[1]:
            need_ticks[3] = True

        ch_ticks: List[Optional[np.ndarray]] = [None, None, None, None]
        ch_bits: List[Optional[np.ndarray]] = [None, None, None, None]
        ch_prev_out = [int(out_bits[0]), int(out_bits[1]), int(out_bits[2]), int(out_bits[3])]

        for ch in range(4):
            if not need_ticks[ch]:
                was_ticking[ch] = False
                prev_periods[ch] = 0
                continue

            period = pokey_hw.channel_period_cpu_cycles(audf_regs, audctl, ch + 1)
            if not was_ticking[ch]:
                next_tick_cycle[ch] = t0 + float(period)
                was_ticking[ch] = True
            elif prev_periods[ch] != period and next_tick_cycle[ch] > t0 + float(period):
                next_tick_cycle[ch] = t0 + float(period)
            prev_periods[ch] = period

            first_c = next_tick_cycle[ch]
            if first_c < t1:
                k = int(math.floor((t1 - first_c) / float(period))) + 1
                ticks_f = first_c + np.arange(k, dtype=np.float64) * float(period)
                # Guard against rounding boundary touching t1
                if k > 0 and ticks_f[-1] >= t1:
                    ticks_f = ticks_f[:-1]
                    k -= 1
                next_tick_cycle[ch] = first_c + k * float(period)
            else:
                ticks_f = np.empty(0, dtype=np.float64)
                k = 0

            ch_ticks[ch] = ticks_f
            if k > 0 and audible[ch]:
                ticks_cycle = np.rint(ticks_f).astype(np.int64)
                waveform = pokey_hw.decode_audc(audc_regs[ch])
                bits, last_bit = _evaluate_channel_ticks(
                    ticks_cycle,
                    waveform,
                    int(out_bits[ch]),
                    use_9bit,
                )
                ch_bits[ch] = bits
                out_bits[ch] = last_bit
            else:
                ch_bits[ch] = np.empty(0, dtype=np.uint8)

        # Render audible channels onto sample buffer.
        for ch in range(4):
            if not audible[ch]:
                continue

            amp = POKEY_DAC[audc_regs[ch] & 0x0F]
            waveform = pokey_hw.decode_audc(audc_regs[ch])
            if waveform == pokey_hw.Waveform.VOLUME_ONLY:
                audio_mix[s_start:s_end] += amp
                continue

            ev_t = ch_ticks[ch]
            ev_b = ch_bits[ch]
            assert ev_t is not None and ev_b is not None

            if ch == 0 and hpf_1_by_3:
                ctl_t = ch_ticks[2]
                assert ctl_t is not None
                bit_before = ch_prev_out[0] ^ int(hpf_latches[0])
                ev_t, ev_b, new_latch = _apply_hpf_xor(
                    ev_t, ev_b, ctl_t, ch_prev_out[0], int(hpf_latches[0])
                )
                hpf_latches[0] = new_latch
            elif ch == 1 and hpf_2_by_4:
                ctl_t = ch_ticks[3]
                assert ctl_t is not None
                bit_before = ch_prev_out[1] ^ int(hpf_latches[1])
                ev_t, ev_b, new_latch = _apply_hpf_xor(
                    ev_t, ev_b, ctl_t, ch_prev_out[1], int(hpf_latches[1])
                )
                hpf_latches[1] = new_latch
            else:
                bit_before = ch_prev_out[ch]

            wave_samples = _box_integrate_events(ev_t, ev_b, t0, t1, samples_per_frame, bit_before)
            audio_mix[s_start:s_end] += wave_samples * amp

    # Single-pole DC blocking filter (y[n] = x[n] - x[n-1] + R * y[n-1], R=0.995)
    dc_blocked = np.zeros_like(audio_mix)
    r = 0.995
    for i in range(1, len(audio_mix)):
        dc_blocked[i] = audio_mix[i] - audio_mix[i - 1] + r * dc_blocked[i - 1]

    peak = float(np.max(np.abs(dc_blocked)))
    if peak > 0.0:
        norm_audio = dc_blocked / peak * 0.90
    else:
        norm_audio = dc_blocked

    return (norm_audio * 32767.0).astype(np.int16)


# ---------------------------------------------------------------------------
# Opt-in CORE_V1 InstrumentProfile integration (Stage B)
# ---------------------------------------------------------------------------

def _static_catalog_subset(
    profile_assignments: Mapping[int, str],
    catalog: "InstrumentCatalog",
) -> "InstrumentCatalog":
    """Build a static-behavior view (behavior_id=None) when caller requests static-only rendering."""
    from atari_music.instruments import (
        CATALOG_SCHEMA_ID,
        InstrumentCatalog,
        InstrumentCatalogDocument,
        InstrumentProfile,
    )

    profiles: List[InstrumentProfile] = []
    seen: set[str] = set()
    for inst_id in profile_assignments.values():
        if inst_id in seen:
            continue
        seen.add(inst_id)
        prof = catalog.get_profile(inst_id)
        profiles.append(prof.model_copy(update={"behavior_id": None}))
    doc = InstrumentCatalogDocument(
        schema_id=CATALOG_SCHEMA_ID,
        catalog_version=catalog.catalog_version,
        behaviors=(),
        instruments=tuple(profiles),
    )
    return InstrumentCatalog(doc)


def compile_core_v1_profiles_to_frames(
    channel_notes: Mapping[int, Sequence[Tuple[Optional[int], int, int]]],
    profile_assignments: Mapping[int, str],
    *,
    frames_per_tick: int = 4,
    catalog: Optional["InstrumentCatalog"] = None,
    target: Optional["TargetCapability"] = None,
    allow_static_only: bool = False,
) -> np.ndarray:
    """Compile channel note events ``(midi_or_None, duration_ticks, volume)`` using SSOT profiles.

    Validates every channel, profile, behavior tier, and hardware AUDCTL constraint through
    :class:`POKEYRuntime`. Profiles requiring unsupported or deferred behaviors are refused
    unless ``allow_static_only=True`` explicitly requests static-profile rendering only (in
    which case hard ``HardwareConstraints`` like HPF XOR or 16-bit CH3+4 are still enforced).
    """
    from atari_music.instruments import (
        TARGET_WAV_PREVIEW,
        ChannelAssignmentRequest,
        POKEYRuntime,
        load_instrument_catalog,
    )

    if frames_per_tick < 1:
        raise ValueError(f"frames_per_tick must be >= 1, got {frames_per_tick}")
    for ch in channel_notes:
        if ch not in profile_assignments:
            raise InstrumentRenderError(
                f"channel {ch} has notes but no assigned instrument profile"
            )

    resolved_target = TARGET_WAV_PREVIEW if target is None else target
    base_catalog = catalog if catalog is not None else load_instrument_catalog()
    eval_catalog = (
        _static_catalog_subset(profile_assignments, base_catalog)
        if allow_static_only
        else base_catalog
    )

    requests: List[ChannelAssignmentRequest] = []
    for ch, inst_id in sorted(profile_assignments.items()):
        notes = channel_notes.get(ch, ())
        pitched = [n[0] for n in notes if n[0] is not None]
        requests.append(
            ChannelAssignmentRequest(
                channel=ch,
                instrument_ids=(inst_id,),
                midi_min=min(pitched) if pitched else None,
                midi_max=max(pitched) if pitched else None,
            )
        )

    report = POKEYRuntime.resolve(requests, eval_catalog, resolved_target)
    if not report.is_compatible:
        msgs = "; ".join(f"[{d.code}] {d.message}" for d in report.diagnostics if d.severity == "ERROR")
        raise InstrumentRenderError(
            f"cannot compile profile assignments for {resolved_target.backend!r}: {msgs}",
            diagnostics=report.diagnostics,
        )

    audctl = report.effective_audctl
    ch_frame_lengths = {
        ch: sum(max(1, int(dur)) * frames_per_tick for _, dur, _ in notes)
        for ch, notes in channel_notes.items()
    }
    total_frames = max(ch_frame_lengths.values(), default=0)
    if total_frames == 0:
        return np.zeros((0, 9), dtype=np.uint8)

    frames = np.zeros((total_frames, 9), dtype=np.uint8)
    frames[:, 8] = audctl & 0xFF

    for ch, inst_id in sorted(profile_assignments.items()):
        profile, behavior = eval_catalog.resolve_profile_behavior(inst_id)
        mod_is_octave = behavior is not None and behavior.modulation_mode == "octave_pulse"
        notes = channel_notes.get(ch, ())
        cursor = 0
        for midi_pitch, duration_ticks, note_vol in notes:
            ticks = max(1, int(duration_ticks))
            note_len = ticks * frames_per_tick
            if cursor >= total_frames:
                break
            if midi_pitch is None or note_vol <= 0:
                cursor += note_len
                continue

            peak = min(15, max(0, int(note_vol), 0))
            peak = min(peak, profile.envelope.peak_vol)
            vols = pokey_hw.player_envelope_volumes(
                note_len_frames=note_len,
                frames_per_tick=frames_per_tick,
                peak_vol=peak,
                attack=profile.envelope.attack_frames,
                decay=profile.envelope.decay_frames,
                sustain=profile.envelope.sustain_vol,
                release=profile.envelope.release_frames,
            )

            freq_hz = 440.0 * (2.0 ** ((int(midi_pitch) - 69) / 12.0))
            if profile.hardware_constraints.divider_mode == "16bit_ch12":
                div16 = pokey_hw.audf16_from_hz(freq_hz, audctl=audctl, channel=1)
                lsb, msb = pokey_hw.split_audf16(div16)
                for f_off, v in enumerate(vols):
                    idx = cursor + f_off
                    if idx >= total_frames:
                        break
                    frames[idx, 0] = lsb
                    frames[idx, 1] = 0x00
                    frames[idx, 2] = msb
                    frames[idx, 3] = (profile.base_distortion & 0xE0) | (v & 0x0F)
            else:
                if profile.hardware_constraints.poly4_safe_tuning:
                    nominal_audf = pokey_hw.audf_for_poly4_8bit(freq_hz, audctl=audctl, channel=ch)
                else:
                    nominal_audf = pokey_hw.clamp_audf_for_tracker(
                        pokey_hw.audf_from_hz_8bit(freq_hz, audctl=audctl, channel=ch)
                    )
                audf_col = (ch - 1) * 2
                audc_col = audf_col + 1
                for f_off, v in enumerate(vols):
                    idx = cursor + f_off
                    if idx >= total_frames:
                        break
                    audf_val = (
                        pokey_hw.octave_pulse_divider(nominal_audf, f_off)
                        if mod_is_octave
                        else nominal_audf
                    )
                    frames[idx, audf_col] = audf_val & 0xFF
                    frames[idx, audc_col] = (profile.base_distortion & 0xE0) | (v & 0x0F)

            cursor += note_len

    return frames


def render_core_v1_profiles_samples(
    channel_notes: Mapping[int, Sequence[Tuple[Optional[int], int, int]]],
    profile_assignments: Mapping[int, str],
    *,
    frames_per_tick: int = 4,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
    catalog: Optional["InstrumentCatalog"] = None,
    target: Optional["TargetCapability"] = None,
    allow_static_only: bool = False,
) -> np.ndarray:
    """Compile SSOT CORE_V1 profiles to register frames and render PCM audio."""
    frames = compile_core_v1_profiles_to_frames(
        channel_notes,
        profile_assignments,
        frames_per_tick=frames_per_tick,
        catalog=catalog,
        target=target,
        allow_static_only=allow_static_only,
    )
    return render_pokey_samples(frames, sample_rate=sample_rate, frame_rate_hz=frame_rate_hz)


def render_core_v1_profiles_to_wav(
    channel_notes: Mapping[int, Sequence[Tuple[Optional[int], int, int]]],
    profile_assignments: Mapping[int, str],
    output_wav_path: Path,
    *,
    frames_per_tick: int = 4,
    sample_rate: int = 44100,
    frame_rate_hz: float = 50.0,
    catalog: Optional["InstrumentCatalog"] = None,
    target: Optional["TargetCapability"] = None,
    allow_static_only: bool = False,
) -> None:
    """Compile SSOT CORE_V1 profiles to register frames and write 16-bit mono WAV."""
    samples = render_core_v1_profiles_samples(
        channel_notes,
        profile_assignments,
        frames_per_tick=frames_per_tick,
        sample_rate=sample_rate,
        frame_rate_hz=frame_rate_hz,
        catalog=catalog,
        target=target,
        allow_static_only=allow_static_only,
    )
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())

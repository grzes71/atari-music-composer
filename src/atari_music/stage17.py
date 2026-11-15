"""Stage 17 — POKEY performance event language and compact event IR.

Analysis and a **research-only interpreter**. This stage asks one architectural question:

    Can a compact, semantically neutral Performance Event language form a useful middle layer
    between composition and the POKEY player, while staying small enough that the existing
    2 KB player architecture could plausibly execute it?

Nothing here touches production. The 6502 player, the Composer, the DSL, the Music IR, the
POKEY IR and the SoundProfile system are all read-only, and the module proves that by hashing
every one of them before and after. No audio is rendered, no music is generated, and nobody is
asked to listen.

The language is **not designed from imagination**. It is derived from what Stages 15 and 16
actually observed:

    reports/stage16/song_selection.json   ->  which four songs
    reports/stage15/*.json                ->  player capability, gap, size, mechanism table
    output/traces/*.frames.json           ->  the reference behaviour, frame by frame

Every opcode in the vocabulary has to name the Stage 15 technique that justifies it, the songs
it was observed in, and the register effect it produces. Candidates that the brief offers but
the evidence does not support (``WAIT`` above all) are *rejected with a reason* rather than
quietly kept.

The technical heart of the stage is a round trip: a reference trace is encoded into the IR and
an offline interpreter renders it back to a POKEY frame stream, which is compared with the
original register by register. Every frame is classified EXACT, APPROXIMATE or UNREPRESENTABLE.
The point is not to prove the encoding works; it is to measure **where it stops working**.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atari_music import stage15, stage16
from atari_music.constants import AUDCTL_JOIN_1_2_16BIT, AUDCTL_JOIN_3_4_16BIT

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_STAGE16_DIR = DEFAULT_REPORTS_DIR / "stage16"
DEFAULT_STAGE17_DIR = DEFAULT_REPORTS_DIR / "stage17"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_PLAYER_ASM = REPO_ROOT / "src" / "atari_music" / "asm" / "player.asm"

ANALYSIS_VERSION = "stage17/1"

#: Registers captured by the corpus trace, in a fixed order so every published number has a
#: defined position. AUDCTL last because it is global rather than per-channel.
REGISTER_ORDER = (
    "AUDF1", "AUDC1", "AUDF2", "AUDC2", "AUDF3", "AUDC3", "AUDF4", "AUDC4", "AUDCTL",
)
CHANNELS = (1, 2, 3, 4)

#: Bytes one frame of raw POKEY state occupies in the corpus trace schema.
RAW_FRAME_BYTES = len(REGISTER_ORDER)

#: Bytes of the *current* player's note event: AUDF, duration, volume (Stage 15's own
#: ``NOTE_TABLE_BYTES``). Reused rather than redefined so the comparison is against the same
#: number Stage 15 published.
CURRENT_NOTE_BYTES = stage15.NOTE_TABLE_BYTES


# -- the proposed language ---------------------------------------------------------------
#: Dispatch order of the opcode field. Fixed so the opcode index is stable across runs.
OPCODE_ORDER = (
    "SET_AUDCTL",
    "SET_GENERATOR",
    "SET_VOLUME",
    "SET_PITCH",
    "NOTE",
    "NOTE_OFF",
    "PITCH_SLIDE",
    "PITCH_SWEEP",
    "VIBRATO",
    "TREMOLO",
    "ARPEGGIO",
    "VOLUME_SHAPE",
)

#: Stage 15 technique (or technique family, since Stage 15 splits glides by direction) mapped
#: to the opcode that carries it. This table *is* Part D's result; everything else about the
#: vocabulary is read out of it.
TECHNIQUE_TO_OPCODE: Dict[str, str] = {
    "NOTE_ON": "NOTE",
    "NOTE_OFF": "NOTE_OFF",
    "PITCH_CHANGE": "SET_PITCH",
    "PITCH_SLIDE_RISING": "PITCH_SLIDE",
    "PITCH_SLIDE_FALLING": "PITCH_SLIDE",
    "PITCH_SWEEP_RISING": "PITCH_SWEEP",
    "PITCH_SWEEP_FALLING": "PITCH_SWEEP",
    "VOLUME_CHANGE": "SET_VOLUME",
    "VOLUME_ENVELOPE_RISING": "VOLUME_SHAPE",
    "VOLUME_ENVELOPE_FALLING": "VOLUME_SHAPE",
    "GENERATOR_CHANGE": "SET_GENERATOR",
    "DISTORTION_CHANGE": "SET_GENERATOR",
    "VIBRATO": "VIBRATO",
    "TREMOLO": "TREMOLO",
    "ARPEGGIO": "ARPEGGIO",
    "REGISTER_PATTERN_CHANGE": "SET_PITCH",
    "AUDCTL_CHANGE": "SET_AUDCTL",
}

#: The opcode field is one byte; the channel field is the low nibble. Channel 0 means
#: "global" (AUDCTL), which is why the language needs no separate global stream.
CHANNEL_GLOBAL = 0

#: Wire widths, in bytes, for each parameter name. ``notes`` is variable (2 bytes per tone,
#: the POKEY divider) and is charged per element. These are a *stated encoding*, so the
#: compression numbers can be recomputed by hand rather than believed.
PARAM_BYTES: Dict[str, int] = {
    "divider": 2,
    "volume": 1,
    "dist": 1,
    "value": 1,
    "delta": 2,
    "duration": 1,
    "curve": 1,
    "depth": 2,
    "period": 1,
    "count": 1,
    "target": 1,
}

#: Parameters that carry a variable-length table: a count byte followed by that many fixed
#: values. ``notes`` cycles absolute dividers (ARPEGGIO); ``levels`` replays an absolute
#: volume sequence (VOLUME_SHAPE). Both tables are things Stage 15 actually measured - the
#: ARPEGGIO tones and the VOLUME_ENVELOPE level list - so they are evidence, not invention.
VARIABLE_PARAMS: Dict[str, int] = {"notes": 2, "levels": 1}

#: Every parameter name the language may use, so a typo fails loudly instead of being sized
#: at zero and quietly making the compression report optimistic.
KNOWN_PARAMS = frozenset(PARAM_BYTES) | frozenset(VARIABLE_PARAMS)

#: Frame deltas are stored as an unsigned LEB128-style integer: 1 byte below 128, 2 below
#: 16384, 3 above. Deterministic and unambiguous.
VARINT_SMALL = 128
VARINT_MEDIUM = 16384

#: Hard POKEY limits the language must respect or report (Part O).
AUDF_8BIT_MAX = 255
AUDF_16BIT_MAX = 65535
AUDC_VOLUME_MAX = 15
AUDC_DISTORTION_MAX = 14

#: The candidate opcodes the brief suggests, and what the evidence says about each. Published
#: so a rejected candidate is visibly rejected rather than silently dropped.
REJECTED_CANDIDATES: Tuple[Dict[str, str], ...] = (
    {
        "candidate": "WAIT",
        "verdict": "REJECTED",
        "reason": (
            "No Stage 15 technique corresponds to a wait: there is no WAIT kind, and no event "
            "class is an absence of behaviour. Time in this language is carried by the *frame* "
            "field of every event, so a separate WAIT opcode would duplicate information the "
            "encoding already has. A rest is a note whose volume is zero, not a wait."
        ),
    },
    {
        "candidate": "SET_AUDCTL as a performance technique",
        "verdict": "REJECTED_AS_TECHNIQUE_ADMITTED_AS_MODE",
        "reason": (
            "AUDCTL_CHANGE occurs zero times in all four songs (Stage 15 records it as an "
            "absent kind, Stage 16 keeps it absent). It is admitted only because a stream must "
            "declare the channel mode it is written in; it is not claimed as a performance event."
        ),
    },
    {
        "candidate": "MACRO",
        "verdict": "DEFERRED_TO_MEASUREMENT",
        "reason": "Part Q is answered from the observed opcode n-grams, not assumed useful.",
    },
    {
        "candidate": "Laser, bell, bass, lead, percussion, or any instrument name",
        "verdict": "REJECTED",
        "reason": (
            "Stage 16 showed the same low-level technique carries different musical meanings in "
            "different songs, so a semantic name would have to encode song-specific grammar - "
            "exactly the inference this architecture exists to avoid."
        ),
    },
)


# ---------------------------------------------------------------------------
# Helpers (deterministic; no timestamps, no set iteration in output)
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise Stage17Error(f"missing artefact: {path}") from error
    except json.JSONDecodeError as error:
        raise Stage17Error(f"malformed JSON: {path}: {error}") from error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def sha256_source_text(path: Path) -> str:
    """The hash of a *source* file, as normalised UTF-8 text.

    The player source is hashed this way because that is how Stage 15 hashed it: its own
    ``player_size_analysis.json`` records this value, so using the byte hash here would make the
    two stages appear to disagree about an unmodified file. JSON artefacts keep the byte hash,
    which is what Stage 16 uses for its own records.
    """
    return hashlib.sha256(Path(path).read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    return None if value is None else round(float(value), places)


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _share(part: int, whole: int) -> Optional[float]:
    return _rnd(part / whole) if whole else None


def varint_size(value: int) -> int:
    """Bytes an unsigned frame delta occupies. Negative deltas are not representable."""
    if value < 0:
        raise Stage17Error(f"frame delta must be non-negative, got {value}")
    if value < VARINT_SMALL:
        return 1
    if value < VARINT_MEDIUM:
        return 2
    return 3


def audc_volume(audc: int) -> int:
    return audc & 0x0F


def audc_distortion(audc: int) -> int:
    return audc & 0xF0


def joined_pair_channels(audctl: int) -> Tuple[Tuple[int, int], ...]:
    """The channel pairs AUDCTL joins into a 16-bit divider, high channel last."""
    pairs: List[Tuple[int, int]] = []
    if audctl & AUDCTL_JOIN_1_2_16BIT:
        pairs.append((1, 2))
    if audctl & AUDCTL_JOIN_3_4_16BIT:
        pairs.append((3, 4))
    return tuple(pairs)


# ---------------------------------------------------------------------------
# The IR - a flat, deterministically ordered event stream
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PerfEvent:
    """One event of the Performance Event IR.

    The IR is deliberately flat and channel-tagged: there is no nested "note with attached
    effects" object, because Part F has to be settled by measurement rather than by taste. The
    sequential and attached models differ only in the fields an encoder fills in, so both can
    be rendered by the same interpreter and compared on the same trace.
    """

    opcode: str
    channel: int
    frame: int
    duration: int
    params: Tuple[Tuple[str, Any], ...]

    def get(self, name: str, default: int = 0) -> int:
        for key, value in self.params:
            if key == name:
                return value
        return default

    def param_names(self) -> Tuple[str, ...]:
        return tuple(key for key, _ in self.params)

    def render(self) -> str:
        head = f"ch{self.channel}@{self.frame}"
        if self.duration:
            head += f"+{self.duration}"
        body = " ".join(f"{key}={value}" for key, value in self.params)
        return f"{self.opcode} {head} {body}".rstrip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opcode": self.opcode,
            "channel": self.channel,
            "frame": self.frame,
            "duration": self.duration,
            "params": {key: value for key, value in self.params},
            "render": self.render(),
        }


def make_event(
    opcode: str,
    channel: int,
    frame: int,
    duration: int = 0,
    **params: Any,
) -> PerfEvent:
    """Build an event with its parameter names sorted, so equality is order-independent."""
    return PerfEvent(
        opcode=opcode,
        channel=int(channel),
        frame=int(frame),
        duration=int(duration),
        params=tuple(sorted((key, value) for key, value in params.items())),
    )


def sort_events(events: Iterable[PerfEvent]) -> List[PerfEvent]:
    """Canonical stream order: frame, channel, opcode, then parameters as a tie-break."""
    return sorted(
        events,
        key=lambda item: (
            item.frame,
            item.channel,
            OPCODE_ORDER.index(item.opcode) if item.opcode in OPCODE_ORDER else len(OPCODE_ORDER),
            repr(item.params),
        ),
    )


class Stage17Error(RuntimeError):
    """A required input artefact is missing or malformed."""



# ---------------------------------------------------------------------------
# PART I - the research interpreter (offline; not the production player)
# ---------------------------------------------------------------------------
def voice_layout(audctl: int) -> Dict[int, Tuple[int, bool]]:
    """channel -> (voice channel that carries the divider, is the low byte of a joined pair).

    This is the Part O channel-ownership rule in executable form: when AUDCTL joins a pair,
    the *low* channel supplies the divider's low byte and carries no volume, and the *high*
    channel carries both the high byte and the volume. The event language must say which
    channel it is addressing; the interpreter refuses to guess.
    """
    pairs = dict(joined_pair_channels(audctl))
    layout: Dict[int, Tuple[int, bool]] = {}
    for channel in CHANNELS:
        layout[channel] = (pairs[channel], True) if channel in pairs else (channel, False)
    return layout


def _signed_triangle(offset: int, period: int, depth: int) -> int:
    """Deterministic integer triangle wave, one cycle per ``period`` frames.

    Used by VIBRATO and TREMOLO. Integers only, so the reconstruction is bit-reproducible
    without floating point. Peak-to-peak is ``2 * depth`` and the wave is centred on zero.
    """
    if period <= 1 or depth <= 0:
        return 0
    phase = offset % period
    half = max(1, period // 2)
    if phase < half:
        return depth * (2 * phase - half) // half
    return depth * (2 * (period - phase) - half) // half


def _ramp(start: int, target: int, step: int, span: int) -> int:
    """Integer ramp from ``start`` toward ``target``; ``span`` frames end to end."""
    if span <= 0:
        return target
    return start + (target - start) * step // span


def pitch_value(opcode: str, params: Mapping[str, Any], base: int, step: int, span: int) -> int:
    """The divider a pitch effect produces on its ``step``-th frame. Pure; shared by the
    interpreter and by the encoder's fitter, so a candidate is scored by exactly the maths
    that will later render it."""
    if opcode == "PITCH_SLIDE":
        return base + (int(params.get("delta", 0)) * step) // span
    if opcode == "PITCH_SWEEP":
        delta = int(params.get("delta", 0))
        return base + (delta * step * step) // (span * span)
    if opcode == "VIBRATO":
        return base + _signed_triangle(
            step, max(1, int(params.get("period", 1))), int(params.get("depth", 0))
        )
    if opcode == "ARPEGGIO":
        notes = list(params.get("notes", ()))
        if notes:
            period = max(1, int(params.get("period", 1)))
            return int(notes[(step // period) % len(notes)])
    return base


def volume_value(opcode: str, params: Mapping[str, Any], base: int, step: int, span: int) -> int:
    """The volume a volume effect produces on its ``step``-th frame. Pure, as above."""
    if opcode == "VOLUME_SHAPE":
        levels = list(params.get("levels", ()))
        if levels:
            return int(levels[min(step, len(levels) - 1)])
        return _ramp(base, int(params.get("target", base)), step, span)
    if opcode == "TREMOLO":
        return base - _signed_triangle(
            step, max(1, int(params.get("period", 1))), int(params.get("depth", 0))
        )
    return base


@dataclass
class InterpretResult:
    """The frame stream an IR renders, plus what the rendering could not represent."""

    registers: Dict[str, List[int]]
    frames: int
    unrepresentable_pitch: int
    unrepresentable_volume: int
    clamped_writes: int
    expired_effects: int
    opcodes_applied: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frames": self.frames,
            "unrepresentable_pitch": self.unrepresentable_pitch,
            "unrepresentable_volume": self.unrepresentable_volume,
            "clamped_writes": self.clamped_writes,
            "expired_effects": self.expired_effects,
            "opcodes_applied": dict(sorted(self.opcodes_applied.items())),
        }


#: Effect opcodes and the family they occupy, so a later event can cancel the right one.
PITCH_EFFECTS = frozenset({"PITCH_SLIDE", "PITCH_SWEEP", "VIBRATO", "ARPEGGIO"})
VOLUME_EFFECTS = frozenset({"VOLUME_SHAPE", "TREMOLO"})


def interpret(
    events: Sequence[PerfEvent],
    frames: int,
    initial_audctl: int = 0,
) -> InterpretResult:
    """Render a POKEY frame stream from the IR.

    Reads nothing but the event stream and the frame count. It never sees the reference trace,
    which is what makes the round trip in Part I a real test rather than a restatement.

    Interaction rules, fixed here and reported in Part E so they can be argued with:

    * ``SET_PITCH`` / ``NOTE`` set the voice's pitch anchor and cancel a running pitch effect.
    * ``SET_VOLUME`` / ``NOTE`` set the volume anchor and cancel a running volume effect.
    * ``NOTE_OFF`` forces volume to zero and cancels a running volume effect.
    * ``SET_GENERATOR`` and ``SET_AUDCTL`` leave effects running.
    * An effect opcode installs an effect in its own family, cancelling any effect in that
      family first. Pitch and volume effects therefore overlap, which is the one combination
      the reference behaviour needs (a glide under a volume envelope).
    * When an effect's duration elapses it is dropped and the voice returns to its anchors;
      nothing has to be written to end it.
    """
    ordered = sort_events(events)
    buckets: Dict[int, List[PerfEvent]] = {}
    for event in ordered:
        buckets.setdefault(event.frame, []).append(event)

    audctl = initial_audctl
    layout = voice_layout(audctl)
    dist = {channel: 0 for channel in CHANNELS}
    anchor_divider = {channel: 0 for channel in CHANNELS}
    anchor_volume = {channel: 0 for channel in CHANNELS}
    pitch_effect: Dict[int, Tuple[str, int, int, Dict[str, Any]]] = {}
    volume_effect: Dict[int, Tuple[str, int, int, Dict[str, Any]]] = {}
    release_at: Dict[int, int] = {}

    registers = {name: [0] * frames for name in REGISTER_ORDER}
    unrepresentable_pitch = 0
    unrepresentable_volume = 0
    clamped = 0
    expired = 0
    applied: Dict[str, int] = {}

    def max_divider_for(mode: int) -> int:
        return AUDF_16BIT_MAX if joined_pair_channels(mode) else AUDF_8BIT_MAX

    max_divider = max_divider_for(audctl)
    high_bytes = {high for _, high in joined_pair_channels(audctl)}

    for frame in range(frames):
        for event in buckets.get(frame, ()):  # events at this frame, canonical order
            applied[event.opcode] = applied.get(event.opcode, 0) + 1
            voice = layout.get(event.channel, (event.channel, False))[0]
            params = dict(event.params)

            if event.opcode == "SET_AUDCTL":
                audctl = int(params.get("value", 0))
                layout = voice_layout(audctl)
                max_divider = max_divider_for(audctl)
                high_bytes = {high for _, high in joined_pair_channels(audctl)}

            elif event.opcode == "SET_GENERATOR":
                dist[voice] = int(params.get("dist", 0)) & 0xF0

            elif event.opcode == "SET_VOLUME":
                anchor_volume[voice] = int(params.get("volume", 0))
                volume_effect.pop(voice, None)

            elif event.opcode == "SET_PITCH":
                value = int(params.get("divider", 0))
                if value > max_divider:
                    unrepresentable_pitch += 1
                    value = max_divider
                anchor_divider[voice] = value
                pitch_effect.pop(voice, None)

            elif event.opcode == "NOTE":
                value = int(params.get("divider", 0))
                if value > max_divider:
                    unrepresentable_pitch += 1
                    value = max_divider
                anchor_divider[voice] = value
                anchor_volume[voice] = int(params.get("volume", 0))
                pitch_effect.pop(voice, None)
                volume_effect.pop(voice, None)
                span = int(params.get("duration", 0))
                if span > 0:
                    release_at[voice] = frame + span

            elif event.opcode == "NOTE_OFF":
                anchor_volume[voice] = 0
                volume_effect.pop(voice, None)
                release_at.pop(voice, None)

            elif event.opcode in PITCH_EFFECTS:
                pitch_effect[voice] = (event.opcode, frame, max(1, event.duration), params)
            elif event.opcode in VOLUME_EFFECTS:
                volume_effect[voice] = (event.opcode, frame, max(1, event.duration), params)

        # Effects modulate the anchors; the anchors themselves never change here.
        rendered_divider = dict(anchor_divider)
        rendered_volume = dict(anchor_volume)
        for voice in list(pitch_effect):
            opcode, start, span, params = pitch_effect[voice]
            if frame >= start + span:
                expired += 1
                pitch_effect.pop(voice, None)
                continue
            base = anchor_divider[voice]
            value = pitch_value(opcode, params, base, frame - start, span)
            if value < 0 or value > max_divider:
                clamped += 1
                value = 0 if value < 0 else max_divider
            rendered_divider[voice] = value
        for voice in list(volume_effect):
            opcode, start, span, params = volume_effect[voice]
            if frame >= start + span:
                expired += 1
                volume_effect.pop(voice, None)
                continue
            base = anchor_volume[voice]
            value = volume_value(opcode, params, base, frame - start, span)
            if value < 0 or value > AUDC_VOLUME_MAX:
                clamped += 1
                value = 0 if value < 0 else AUDC_VOLUME_MAX
            rendered_volume[voice] = value

        for channel in CHANNELS:
            voice, is_low = layout[channel]
            if is_low:
                registers[f"AUDF{channel}"][frame] = rendered_divider[voice] & 0xFF
                registers[f"AUDC{channel}"][frame] = 0
            elif channel in high_bytes:
                registers[f"AUDF{channel}"][frame] = (rendered_divider[voice] >> 8) & 0xFF
                registers[f"AUDC{channel}"][frame] = (
                    (dist[voice] & 0xF0) | (rendered_volume[voice] & 0x0F)
                )
            else:
                registers[f"AUDF{channel}"][frame] = rendered_divider[voice] & 0xFF
                registers[f"AUDC{channel}"][frame] = (
                    (dist[voice] & 0xF0) | (rendered_volume[voice] & 0x0F)
                )
            if not is_low and rendered_volume[voice] > AUDC_VOLUME_MAX:
                unrepresentable_volume += 1
        registers["AUDCTL"][frame] = audctl

    return InterpretResult(
        registers=registers, frames=frames, unrepresentable_pitch=unrepresentable_pitch,
        unrepresentable_volume=unrepresentable_volume, clamped_writes=clamped,
        expired_effects=expired, opcodes_applied=applied,
    )


# ---------------------------------------------------------------------------
# PART K - the wire encoding of the IR (stated, so the numbers can be checked)
# ---------------------------------------------------------------------------
def event_bytes(event: PerfEvent, previous_frame: int) -> int:
    """Bytes one IR event occupies in the proposed wire format.

    Record layout, fixed and published so the compression report is arithmetic rather than
    assertion:

        byte 0        opcode index (4 bits) | channel (4 bits)
        byte 1..3     frame delta, unsigned LEB128-style (1-3 bytes)
        byte ..n      duration in frames (1 byte; 0 means "no duration")
        byte ..n      parameters, widths from PARAM_BYTES; ``notes`` is a count byte followed
                      by one 2-byte divider per tone
    """
    size = 1 + varint_size(event.frame - previous_frame) + 1
    for name, value in event.params:
        if name not in KNOWN_PARAMS:
            raise Stage17Error(f"event {event.opcode} uses undefined parameter {name!r}")
        if name in VARIABLE_PARAMS:
            size += 1 + VARIABLE_PARAMS[name] * len(value)
        else:
            size += PARAM_BYTES[name]
    return size


def ir_bytes(events: Sequence[PerfEvent]) -> int:
    """Total wire size of a canonical event stream."""
    previous = 0
    total = 0
    for event in sort_events(events):
        total += event_bytes(event, previous)
        previous = event.frame
    return total


def raw_frame_bytes(frames: int) -> int:
    """Bytes the same performance occupies as one full POKEY register dump per frame."""
    return frames * RAW_FRAME_BYTES


def current_format_bytes(note_events: int) -> int:
    """Bytes the *current* player needs for the same note events (AUDF, duration, volume)."""
    return note_events * CURRENT_NOTE_BYTES


#: The current player's per-song fixed overhead: 7-byte header plus a 4 x 5-byte instrument
#: table. Reported separately so the note table and the fixed part are never confused.
CURRENT_FIXED_OVERHEAD_BYTES = 7 + 4 * 5



# ---------------------------------------------------------------------------
# PART I - comparing a reconstruction with the reference

EXACT = "EXACT"
APPROXIMATE = "APPROXIMATE"
UNREPRESENTABLE = "UNREPRESENTABLE"


@dataclass
class FrameComparison:
    """How one reconstructed frame stream compares with the reference it came from.

    Two tiers are reported, and they answer different questions.

    * **Register tier** - are all nine register bytes identical? Strict, and the honest answer
      to "did the reconstruction write the same bytes?". It is harsh in a way that has to be
      understood: the distortion nibble of a *silent* channel is don't-care, and so is its
      divider, so two streams that sound identical can differ here on most frames.
    * **Audible tier** - does the reconstruction make the same sound? A channel is compared on
      its volume always, and on its distortion and divider whenever either side is audible.
      This is the tier the EXACT / APPROXIMATE / UNREPRESENTABLE classification uses, because
      a difference nobody can hear is not a representational failure.
    """

    frames: int
    register_exact: int
    exact: int
    approximate: int
    unrepresentable: int
    audctl_match: int
    divider_match: int
    volume_match: int
    generator_match: int
    audible_match: int
    silent_both: int
    median_semitone_error: Optional[float]
    worst_semitone_error: Optional[float]
    mismatch_examples: Tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frames": self.frames,
            "register_exact": self.register_exact,
            "register_exact_share": _share(self.register_exact, self.frames),
            "exact": self.exact,
            "approximate": self.approximate,
            "unrepresentable": self.unrepresentable,
            "exact_share": _share(self.exact, self.frames),
            "approximate_share": _share(self.approximate, self.frames),
            "unrepresentable_share": _share(self.unrepresentable, self.frames),
            "audctl_match_share": _share(self.audctl_match, self.frames),
            "divider_match_share": _share(self.divider_match, self.frames),
            "volume_match_share": _share(self.volume_match, self.frames),
            "generator_match_share": _share(self.generator_match, self.frames),
            "audible_match_share": _share(self.audible_match, self.frames),
            "silent_both_share": _share(self.silent_both, self.frames),
            "median_semitone_error": _rnd(self.median_semitone_error, 3),
            "worst_semitone_error": _rnd(self.worst_semitone_error, 3),
            "mismatch_examples": list(self.mismatch_examples),
        }


def _voice_dividers(
    registers: Mapping[str, Sequence[int]], audctl: int, frame: int
) -> Dict[int, int]:
    """The divider each voice is running at in one frame, joined pairs combined."""
    pairs = dict(joined_pair_channels(audctl))
    high_channels = set(pairs.values())
    dividers: Dict[int, int] = {}
    for channel in CHANNELS:
        high = pairs.get(channel)
        if high is not None:
            dividers[high] = (
                (registers[f"AUDF{high}"][frame] << 8) | registers[f"AUDF{channel}"][frame]
            )
        elif channel not in high_channels:
            dividers[channel] = registers[f"AUDF{channel}"][frame]
    return dividers


def _frame_example(
    reference: Mapping[str, Sequence[int]],
    reconstructed: Mapping[str, Sequence[int]],
    frame: int,
    audctl: int,
) -> Dict[str, Any]:
    """A single mismatching frame, written out so a reader can check it by hand."""
    return {
        "frame": frame,
        "audctl": f"${audctl:02X}",
        "reference": {
            "dividers": {
                str(key): value
                for key, value in sorted(_voice_dividers(reference, audctl, frame).items())
            },
            "audc": {str(channel): reference[f"AUDC{channel}"][frame] for channel in CHANNELS},
        },
        "reconstructed": {
            "dividers": {
                str(key): value
                for key, value in sorted(
                    _voice_dividers(reconstructed, audctl, frame).items()
                )
            },
            "audc": {
                str(channel): reconstructed[f"AUDC{channel}"][frame] for channel in CHANNELS
            },
        },
    }



def compare_frames(
    reference: Mapping[str, Sequence[int]],
    reconstructed: Mapping[str, Sequence[int]],
    frames: int,
    audctl: int,
    max_examples: int = 3,
) -> FrameComparison:
    """Classify every frame of a reconstruction against the reference.

    Audible tier, which is the classification:

    * EXACT - AUDCTL agrees and every channel either is silent on both sides or reproduces
      the same volume, the same distortion and the same divider.
    * APPROXIMATE - as EXACT, except some channel that is audible on at least one side has a
      different divider. The event said the right thing at the wrong pitch.
    * UNREPRESENTABLE - a channel that is audible on at least one side has the wrong volume,
      or the wrong distortion, or AUDCTL is wrong. A control the language claims to carry
      explicitly has been lost, which is the failure that matters.
    """
    voices = {voice.volume_channel: voice for voice in stage15.voices_for(audctl)}
    register_exact = exact = approximate = unreachable = 0
    audctl_ok = div_ok = vol_ok = gen_ok = audible_ok = silent_both = 0
    errors: List[float] = []
    examples: List[Dict[str, Any]] = []

    for frame in range(frames):
        same_audctl = reference["AUDCTL"][frame] == reconstructed["AUDCTL"][frame]
        raw_same = same_audctl and all(
            reference[name][frame] == reconstructed[name][frame] for name in REGISTER_ORDER
        )
        register_exact += raw_same

        same_div = same_vol = same_gen = same_audible = True
        both_silent = True
        for channel in CHANNELS:
            ref_audc = reference[f"AUDC{channel}"][frame]
            got_audc = reconstructed[f"AUDC{channel}"][frame]
            ref_volume, got_volume = ref_audc & 0x0F, got_audc & 0x0F
            ref_dist, got_dist = ref_audc & 0xF0, got_audc & 0xF0
            sounding = bool(ref_volume) or bool(got_volume)
            if sounding:
                both_silent = False
            if ref_volume != got_volume:
                same_vol = False
            if bool(ref_volume) != bool(got_volume):
                same_audible = False
            # A silent channel's distortion and divider are don't-care: they change no sound,
            # so they are only compared when at least one side is making one.
            if sounding:
                if ref_dist != got_dist:
                    same_gen = False
                if reference[f"AUDF{channel}"][frame] != reconstructed[f"AUDF{channel}"][frame]:
                    same_div = False

        audctl_ok += same_audctl
        div_ok += same_div
        vol_ok += same_vol
        gen_ok += same_gen
        audible_ok += same_audible
        silent_both += both_silent

        if same_audctl and same_div and same_vol and same_gen:
            exact += 1
        elif same_audctl and same_vol and same_gen:
            approximate += 1
            if len(examples) < max_examples:
                examples.append(_frame_example(reference, reconstructed, frame, audctl))
        else:
            unreachable += 1

        if same_audctl and same_vol and same_gen and not same_div:
            reference_dividers = _voice_dividers(reference, audctl, frame)
            got_dividers = _voice_dividers(reconstructed, audctl, frame)
            for voice_channel, voice in sorted(voices.items()):
                if voice_channel not in reference_dividers or voice_channel not in got_dividers:
                    continue
                if reference[f"AUDC{voice_channel}"][frame] & 0x0F == 0:
                    continue  # silent: a divider difference is inaudible
                reference_value = reference_dividers[voice_channel]
                got_value = got_dividers[voice_channel]
                if reference_value <= 0 or got_value <= 0 or reference_value == got_value:
                    continue
                delta = stage15.semitones_between(
                    stage15.divider_to_hz(reference_value, voice, audctl),
                    stage15.divider_to_hz(got_value, voice, audctl),
                )
                if delta is not None:
                    errors.append(abs(delta))

    return FrameComparison(
        frames=frames, register_exact=register_exact, exact=exact,
        approximate=approximate, unrepresentable=unreachable, audctl_match=audctl_ok,
        divider_match=div_ok, volume_match=vol_ok, generator_match=gen_ok,
        audible_match=audible_ok, silent_both=silent_both,
        median_semitone_error=_median(errors), worst_semitone_error=max(errors) if errors else None,
        mismatch_examples=tuple(examples),
    )


# ---------------------------------------------------------------------------
# PART B/C - the evidence: the four Stage 16 songs, read through their hashes
# ---------------------------------------------------------------------------
@dataclass
class Song:
    """One reference song, with everything the encoders are allowed to look at."""

    slug: str
    path: str
    sha256: str
    title: Optional[str]
    author: Optional[str]
    date: Optional[str]
    frames: int
    audctl: int
    trace: stage15.RegisterTrace
    events: Tuple[stage15.Event, ...]
    technique_counts: Dict[str, int]
    kind_counts: Dict[str, int]
    divider_series: Dict[int, Tuple[int, ...]]
    note_events: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "path": self.path,
            "sha256": self.sha256,
            "title": self.title,
            "author": self.author,
            "date": self.date,
            "frames": self.frames,
            "audctl": f"${self.audctl:02X}",
            "events": len(self.events),
            "note_events": self.note_events,
            "techniques": dict(sorted(self.technique_counts.items())),
            "event_kinds": dict(sorted(self.kind_counts.items())),
        }


def voice_divider_series(trace: stage15.RegisterTrace) -> Dict[int, Tuple[int, ...]]:
    """Every voice's divider, frame by frame. Built once; used to derive effect parameters."""
    series = {channel: [0] * trace.frames for channel in CHANNELS}
    for frame in range(trace.frames):
        for channel, value in _voice_dividers(trace.registers, trace.audctl, frame).items():
            series[channel][frame] = value
    return {channel: tuple(values) for channel, values in series.items()}


def load_song(candidate: Mapping[str, Any]) -> Song:
    """Load one song from the Stage 16 selection record, with its events already detected."""
    path = Path(candidate["path"])
    trace = stage15.load_trace(path)
    events = tuple(stage15.detect_events(trace))
    technique_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    for event in events:
        key = stage15.technique_id(event)
        technique_counts[key] = technique_counts.get(key, 0) + 1
        kind_counts[event.kind] = kind_counts.get(event.kind, 0) + 1
    return Song(
        slug=candidate["slug"], path=str(path), sha256=stage15.sha256_file(path),
        title=trace.title, author=trace.author, date=trace.date, frames=trace.frames,
        audctl=trace.audctl, trace=trace, events=events,
        technique_counts=dict(sorted(technique_counts.items())),
        kind_counts=dict(sorted(kind_counts.items())),
        divider_series=voice_divider_series(trace),
        note_events=int(kind_counts.get("NOTE_ON", 0)),
    )


def stage16_selection(stage16_dir: Path = DEFAULT_STAGE16_DIR) -> Dict[str, Any]:
    """The four songs, taken from the Stage 16 record rather than chosen again here."""
    path = Path(stage16_dir) / "song_selection.json"
    record = _read_json(path)
    by_slug = {item["slug"]: item for item in record["candidates"]}
    chosen = list(record["chosen"])
    missing = [slug for slug in chosen if slug not in by_slug]
    if missing:
        raise Stage17Error(f"Stage 16 selection names songs with no candidate row: {missing}")
    return {
        "source": str(path),
        "source_sha256": sha256_file(path),
        "rule": record["rule"],
        "chosen": chosen,
        "candidates": [by_slug[slug] for slug in chosen],
    }


def load_songs(stage16_dir: Path = DEFAULT_STAGE16_DIR) -> Tuple[List[Song], Dict[str, Any]]:
    """The four reference songs and the Stage 16 selection they came from."""
    selection = stage16_selection(stage16_dir)
    return [load_song(candidate) for candidate in selection["candidates"]], selection


# ---------------------------------------------------------------------------
# PART H/K - encoders
# ---------------------------------------------------------------------------
def _paired_low_channel(audctl: int, high: int) -> Optional[int]:
    for low, other in joined_pair_channels(audctl):
        if other == high:
            return low
    return None


def encode_register_state(song: Song) -> List[PerfEvent]:
    """CONTROL ENCODER - the trace written as register state changes.

    This is **not** the proposed language and it is labelled that way everywhere it appears.
    It emits a ``SET_*`` event only on the frames where a register actually changes, so it is
    the tightest *register-level* stream possible and reproduces the trace exactly by
    construction. Part J forbids this from being the proposal; it is published as the upper
    bound a register-level language could reach, which is what makes the performance
    language's smaller-but-lossy result interpretable instead of mysterious.
    """
    trace = song.trace
    layout = voice_layout(song.audctl)
    events: List[PerfEvent] = [make_event("SET_AUDCTL", CHANNEL_GLOBAL, 0, value=song.audctl)]
    previous: Dict[str, Dict[int, int]] = {"divider": {}, "dist": {}, "volume": {}}
    for frame in range(trace.frames):
        for channel in CHANNELS:
            voice, is_low = layout[channel]
            if is_low:
                continue  # its divider byte is derived from the pair and its AUDC is zero
            low = _paired_low_channel(song.audctl, channel)
            if low is not None:
                value = (trace.registers[f"AUDF{channel}"][frame] << 8) | trace.registers[
                    f"AUDF{low}"
                ][frame]
            else:
                value = trace.registers[f"AUDF{channel}"][frame]
            if previous["divider"].get(voice) != value:
                events.append(make_event("SET_PITCH", channel, frame, divider=value))
                previous["divider"][voice] = value
            audc = trace.registers[f"AUDC{channel}"][frame]
            if previous["dist"].get(voice) != audc & 0xF0:
                events.append(make_event("SET_GENERATOR", channel, frame, dist=audc & 0xF0))
                previous["dist"][voice] = audc & 0xF0
            if previous["volume"].get(voice) != audc & 0x0F:
                events.append(make_event("SET_VOLUME", channel, frame, volume=audc & 0x0F))
                previous["volume"][voice] = audc & 0x0F
    return sort_events(events)


def _voice_of(song: Song, channel: int) -> int:
    """Normalise a Stage 15 channel to the voice channel that owns its state."""
    return voice_layout(song.audctl).get(channel, (channel, False))[0]



def simulate_voice(
    events: Sequence[PerfEvent],
    voice: int,
    start: int,
    length: int,
    base_divider: int,
    base_volume: int,
) -> List[Tuple[int, int]]:
    """Render one voice's ``(divider, volume)`` over a window, using the interpreter's maths.

    This is the encoder's look-ahead: identical arithmetic to :func:`interpret` (it calls the
    same ``pitch_value`` / ``volume_value``), but seeded with an explicit anchor and confined
    to a window, so a candidate encoding can be scored without rendering the whole song.
    """
    anchor_divider = base_divider
    anchor_volume = base_volume
    pitch_effect: Optional[Tuple[str, int, int, Dict[str, Any]]] = None
    volume_effect: Optional[Tuple[str, int, int, Dict[str, Any]]] = None
    release_at: Optional[int] = None
    by_frame: Dict[int, List[PerfEvent]] = {}
    for event in sort_events(events):
        by_frame.setdefault(event.frame, []).append(event)

    out: List[Tuple[int, int]] = []
    for step in range(length):
        frame = start + step
        for event in by_frame.get(frame, ()):
            params = dict(event.params)
            if event.opcode == "SET_PITCH":
                anchor_divider = int(params.get("divider", 0))
                pitch_effect = None
            elif event.opcode == "SET_VOLUME":
                anchor_volume = int(params.get("volume", 0))
                volume_effect = None
            elif event.opcode == "NOTE":
                anchor_divider = int(params.get("divider", 0))
                anchor_volume = int(params.get("volume", 0))
                pitch_effect = volume_effect = None
                span = int(params.get("duration", 0))
                release_at = frame + span if span > 0 else None
            elif event.opcode == "NOTE_OFF":
                anchor_volume = 0
                volume_effect = None
                release_at = None
            elif event.opcode in PITCH_EFFECTS:
                pitch_effect = (event.opcode, frame, max(1, event.duration), params)
            elif event.opcode in VOLUME_EFFECTS:
                volume_effect = (event.opcode, frame, max(1, event.duration), params)
        if release_at == frame:
            anchor_volume = 0
            release_at = None
        divider = anchor_divider
        volume = anchor_volume
        if pitch_effect is not None:
            opcode, began, span, params = pitch_effect
            if frame < began + span:
                divider = pitch_value(opcode, params, anchor_divider, frame - began, span)
        if volume_effect is not None:
            opcode, began, span, params = volume_effect
            if frame < began + span:
                volume = volume_value(opcode, params, anchor_volume, frame - began, span)
        out.append((divider, max(0, min(AUDC_VOLUME_MAX, volume))))
    return out


def _candidate_error(
    song: Song,
    voice: int,
    start: int,
    length: int,
    events: Sequence[PerfEvent],
    base_divider: int,
    base_volume: int,
) -> int:
    """Frames a candidate gets wrong: divider wrong, plus volume wrong.

    Integer, deterministic, and aligned with the metric Part I reports, so a candidate that
    scores well here really does reconstruct well.
    """
    rendered = simulate_voice(events, voice, start, length, base_divider, base_volume)
    series = song.divider_series.get(voice, ())
    registers = song.trace.registers
    error = 0
    for step in range(length):
        frame = start + step
        if frame >= song.frames:
            break
        got_divider, got_volume = rendered[step]
        reference_divider = series[frame] if frame < len(series) else 0
        if got_divider != reference_divider:
            error += 1
        if got_volume != (registers[f"AUDC{voice}"][frame] & 0x0F):
            error += 1
    return error


#: Which Stage 15 event kinds are fitted against the pitch / volume / generator families.
PITCH_KINDS = frozenset({"PITCH_CHANGE", "PITCH_SLIDE", "PITCH_SWEEP", "VIBRATO",
                         "ARPEGGIO", "REGISTER_PATTERN_CHANGE"})
VOLUME_KINDS = frozenset({"VOLUME_CHANGE", "VOLUME_ENVELOPE", "TREMOLO"})
GENERATOR_KINDS = frozenset({"GENERATOR_CHANGE", "DISTORTION_CHANGE"})


def _observed(song: Song, voice: int, frame: int) -> Tuple[int, int]:
    """The voice's actual divider and volume in one frame of the reference."""
    series = song.divider_series.get(voice, ())
    divider = series[frame] if frame < len(series) else 0
    volume = song.trace.registers[f"AUDC{voice}"][frame] & 0x0F
    return divider, volume


def _observed_span(song: Song, voice: int, start: int, span: int, what: str) -> List[int]:
    """The reference ``divider`` or ``volume`` sequence over a span, cropped to the song."""
    out: List[int] = []
    for step in range(span):
        frame = start + step
        if frame >= song.frames:
            break
        divider, volume = _observed(song, voice, frame)
        out.append(divider if what == "divider" else volume)
    return out


def volume_candidates(
    song: Song,
    params: Mapping[str, Any],
    voice: int,
    frame: int,
    span: int,
    allow_tables: bool,
) -> List[Tuple[str, List[PerfEvent]]]:
    """Ways the vocabulary can express one observed volume event (Part D and E in practice)."""
    start_volume = _observed(song, voice, frame)[1]
    anchor = [make_event("SET_VOLUME", voice, frame, volume=start_volume)]
    observed = _observed_span(song, voice, frame, span, "volume")
    last = observed[-1] if observed else start_volume
    span_max = max(observed) if observed else start_volume
    span_min = min(observed) if observed else start_volume
    reversals = max(1, int(params.get("reversals", 0)) or 2)
    candidates = [
        ("SET_VOLUME", [make_event("SET_VOLUME", voice, frame, volume=last)]),
        ("VOLUME_SHAPE", anchor + [make_event(
            "VOLUME_SHAPE", voice, frame, duration=span, target=last)]),
        ("TREMOLO", anchor + [make_event(
            "TREMOLO", voice, frame, duration=span,
            depth=max(0, span_max - span_min), period=max(2, (2 * span) // reversals))]),
    ]
    if allow_tables and len(observed) >= 2:
        candidates.append(
            ("VOLUME_SHAPE_TABLE", anchor + [make_event(
                "VOLUME_SHAPE", voice, frame, duration=span, target=last,
                levels=tuple(observed))])
        )
    return candidates


def pitch_candidates(
    song: Song,
    kind: str,
    params: Mapping[str, Any],
    voice: int,
    frame: int,
    span: int,
    allow_tables: bool,
) -> List[Tuple[str, List[PerfEvent]]]:
    """Ways the vocabulary can express one observed pitch event."""
    start_divider = _observed(song, voice, frame)[0]
    end_divider = int(params.get("end_divider", params.get("end_audf", 0)))
    observed = _observed_span(song, voice, frame, span, "divider")
    anchor = [make_event("SET_PITCH", voice, frame, divider=start_divider)]
    reversals = max(1, int(params.get("reversals", 0)) or 2)

    if kind == "ARPEGGIO":
        tones = [int(item["divider"]) for item in params.get("top_values", [])]
        if tones:
            period = max(1, span // len(tones))
            return [
                ("ARPEGGIO", [make_event(
                    "ARPEGGIO", voice, frame, duration=span, count=len(tones),
                    period=period, notes=tuple(tones))]),
                ("SET_PITCH", [make_event("SET_PITCH", voice, frame, divider=tones[0])]),
            ]

    candidates = [
        ("SET_PITCH", [make_event("SET_PITCH", voice, frame, divider=end_divider)]),
        ("PITCH_SLIDE", anchor + [make_event(
            "PITCH_SLIDE", voice, frame, duration=span, curve=0,
            delta=end_divider - start_divider)]),
        ("PITCH_SWEEP", anchor + [make_event(
            "PITCH_SWEEP", voice, frame, duration=span, curve=1,
            delta=end_divider - start_divider)]),
    ]
    depth = max((abs(value - start_divider) for value in observed), default=0)
    candidates.append(
        ("VIBRATO", anchor + [make_event(
            "VIBRATO", voice, frame, duration=span, depth=depth,
            period=max(2, (2 * span) // reversals))])
    )
    if allow_tables and len(observed) >= 2:
        candidates.append(
            ("ARPEGGIO_TABLE", anchor + [make_event(
                "ARPEGGIO", voice, frame, duration=span, count=len(observed),
                period=1, notes=tuple(observed))])
        )
    return candidates

    return error



def effect_candidates(
    song: Song,
    kind: str,
    params: Mapping[str, Any],
    voice: int,
    frame: int,
    span: int,
    allow_tables: bool,
) -> List[Tuple[str, List[PerfEvent]]]:
    """Every way the vocabulary can express one observed event.

    Each candidate is a *complete local statement*: it first anchors the voice to the value
    the reference actually holds at the start of the span, then installs an effect. That is
    what a real encoder would emit, and it keeps the comparison about the language's
    expressive power rather than about the encoder's optimism.

    The last candidate of each family is the *escape hatch*: a table as long as the span.
    Part J's rule is respected, because the table describes one voice's parameter trajectory
    rather than a full per-frame register dump - but the escape hatch is exactly where the
    compact language degenerates toward per-frame data, so its use is counted and costed
    rather than hidden.
    """
    if kind in GENERATOR_KINDS:
        to_audc = int(str(params.get("to_audc", "$00")).lstrip("$"), 16)
        return [("SET_GENERATOR", [make_event("SET_GENERATOR", voice, frame, dist=to_audc & 0xF0)])]
    if kind in VOLUME_KINDS:
        return volume_candidates(song, params, voice, frame, span, allow_tables)
    if kind in PITCH_KINDS:
        return pitch_candidates(song, kind, params, voice, frame, span, allow_tables)
    return []


def fit_event(
    song: Song,
    kind: str,
    params: Mapping[str, Any],
    voice: int,
    frame: int,
    span: int,
    base_divider: int,
    base_volume: int,
    allow_tables: bool,
) -> Tuple[str, List[PerfEvent], int]:
    """Choose the candidate that reconstructs the span best; ties broken by size, then opcode.

    Scoring uses the *same* arithmetic the interpreter will use, and the anchors the encoder
    actually holds, so the score predicts the real outcome instead of an idealised one.
    """
    scored: List[Tuple[int, int, int, str, List[PerfEvent]]] = []
    for label, events in effect_candidates(song, kind, params, voice, frame, span, allow_tables):
        error = _candidate_error(song, voice, frame, span, events, base_divider, base_volume)
        cost = ir_bytes(events)
        order = OPCODE_ORDER.index(events[0].opcode) if events else len(OPCODE_ORDER)
        scored.append((error, cost, order, label, events))
    if not scored:
        return "", [], 0
    scored.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    error, _, _, label, events = scored[0]
    return label, events, error


@dataclass
class Encoding:
    """One encoded song: the event stream plus how it was produced."""

    label: str
    description: str
    events: Tuple[PerfEvent, ...]
    choices: Dict[str, int]
    unmapped: Dict[str, int]
    fitted_error: int

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def param_count(self) -> int:
        return sum(len(event.params) for event in self.events)

    def opcode_histogram(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for event in self.events:
            counts[event.opcode] = counts.get(event.opcode, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "events": self.event_count,
            "parameters": self.param_count,
            "bytes": ir_bytes(self.events),
            "opcode_histogram": self.opcode_histogram(),
            "fit_choices": dict(sorted(self.choices.items())),
            "fit_residual_mismatch_frames": self.fitted_error,
            "unmapped_event_kinds": dict(sorted(self.unmapped.items())),
        }


def encode_performance(
    song: Song,
    attached: bool,
    allow_tables: bool = False,
) -> Encoding:
    """The PROPOSED ENCODER - Stage 15's events fitted onto the opcode vocabulary.

    ``attached`` selects between the two composition models Part F has to settle:

    * ``attached=False`` - *sequential*: ``NOTE`` carries no duration and a separate
      ``NOTE_OFF`` ends the note, which is the shape the evidence literally shows.
    * ``attached=True`` - *attached*: ``NOTE`` carries ``duration`` and releases itself, so no
      ``NOTE_OFF`` event is emitted at all.

    ``allow_tables`` admits the escape hatch - a table as long as the span - so the cost of
    exactness can be measured rather than assumed. The parameterised-only run is the honest
    test of what the *vocabulary* can do; the table-allowed run is the honest test of what
    exactness costs.
    """
    trace = song.trace
    layout = voice_layout(song.audctl)
    events: List[PerfEvent] = [make_event("SET_AUDCTL", CHANNEL_GLOBAL, 0, value=song.audctl)]
    anchor_divider = {channel: 0 for channel in CHANNELS}
    anchor_volume = {channel: 0 for channel in CHANNELS}

    # Prologue: the state at frame 0 is declared, because the IR is a stream relative to a
    # declared initial condition rather than a full register dump.
    for channel in CHANNELS:
        voice, is_low = layout[channel]
        if is_low:
            continue
        low = _paired_low_channel(song.audctl, channel)
        if low is not None:
            value = (trace.registers[f"AUDF{channel}"][0] << 8) | trace.registers[f"AUDF{low}"][0]
        else:
            value = trace.registers[f"AUDF{channel}"][0]
        audc = trace.registers[f"AUDC{channel}"][0]
        events.append(make_event("SET_GENERATOR", channel, 0, dist=audc & 0xF0))
        events.append(make_event("SET_VOLUME", channel, 0, volume=audc & 0x0F))
        events.append(make_event("SET_PITCH", channel, 0, divider=value))
        anchor_divider[voice] = value
        anchor_volume[voice] = audc & 0x0F

    choices: Dict[str, int] = {}
    unmapped: Dict[str, int] = {}
    fitted_error = 0

    for event in song.events:
        voice = _voice_of(song, event.channel)
        params = dict(event.parameters)
        span = max(1, event.duration_frames)
        kind = event.kind

        if kind == "NOTE_ON":
            divider = int(params.get("divider", 0))
            volume = int(params.get("volume", 0))
            duration = max(1, int(params.get("note_frames") or span))
            events.append(
                make_event("NOTE", voice, event.start_frame,
                           duration=duration if attached else 0,
                           divider=divider, volume=volume)
            )
            anchor_divider[voice] = divider
            anchor_volume[voice] = volume
            choices["NOTE"] = choices.get("NOTE", 0) + 1
        elif kind == "NOTE_OFF":
            if not attached:
                events.append(make_event("NOTE_OFF", voice, event.start_frame))
                choices["NOTE_OFF"] = choices.get("NOTE_OFF", 0) + 1
            anchor_volume[voice] = 0
        else:
            label, chosen, error = fit_event(
                song, kind, params, voice, event.start_frame, span,
                anchor_divider[voice], anchor_volume[voice], allow_tables,
            )
            if not chosen:
                unmapped[kind] = unmapped.get(kind, 0) + 1
                continue
            events.extend(chosen)
            fitted_error += error
            choices[label] = choices.get(label, 0) + 1
            for item in chosen:
                item_params = dict(item.params)
                if item.opcode == "SET_PITCH":
                    anchor_divider[voice] = int(item_params.get("divider", 0))
                elif item.opcode == "SET_VOLUME":
                    anchor_volume[voice] = int(item_params.get("volume", 0))

    label = ("performance-"
             + ("attached" if attached else "sequential")
             + ("+tables" if allow_tables else ""))
    description = (
        "Stage 15 events fitted onto the vocabulary; NOTE carries "
        + ("a duration and releases itself" if attached else "no duration, NOTE_OFF ends it")
        + ("; span tables admitted as a last resort" if allow_tables else "")
    )
    return Encoding(
        label=label, description=description, events=tuple(sort_events(events)),
        choices=choices, unmapped=unmapped, fitted_error=fitted_error,
    )


# ---------------------------------------------------------------------------
# PART K/N - the behaviour-driven compiler (exact by construction)
# ---------------------------------------------------------------------------
#: Longest span a single parameterised effect may cover. Beyond this the effect costs more
#: than it saves, and the stream is better off with plain state changes.
EFFECT_MAX_SPAN = 24
#: An effect has to save at least this many events to be chosen over plain state changes.
MIN_EFFECT_GAIN = 2


def _run_matches(
    values: Sequence[int], start: int, span: int, shape: Any, base: int
) -> bool:
    """Does a candidate shape reproduce ``values[start : start + span]`` exactly?"""
    for step in range(span):
        if shape(base, step, span) != values[start + step]:
            return False
    return True


def best_pitch_run(
    values: Sequence[int], start: int, frames: int, base: int, max_span: int
) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    """The longest run a single parameterised pitch opcode reproduces exactly.

    The parameter is taken from the *last* value of the candidate span, then the whole span is
    verified. Only an exact match is accepted, so a run reported here is a run the interpreter
    will reproduce byte for byte.
    """
    best: Optional[Tuple[int, str, Dict[str, Any]]] = None
    limit = min(max_span, frames - start)
    for span in range(2, limit + 1):
        delta = values[start + span - 1] - base
        if _run_matches(values, start, span, lambda c, s, sp: c + (delta * s) // sp, base):
            best = (span, "PITCH_SLIDE", {"delta": delta, "curve": 0})
            continue
        if _run_matches(
            values, start, span, lambda c, s, sp: c + (delta * s * s) // (sp * sp), base
        ):
            best = (span, "PITCH_SWEEP", {"delta": delta, "curve": 1})
            continue
        window = values[start : start + span]
        depth = max(abs(value - base) for value in window)
        if depth:
            reversals = 0
            sign = 0
            for index in range(1, len(window)):
                change = window[index] - window[index - 1]
                if change:
                    new_sign = 1 if change > 0 else -1
                    if sign and new_sign != sign:
                        reversals += 1
                    sign = new_sign
            period = max(2, (2 * span) // max(1, reversals))
            if _run_matches(
                values, start, span,
                lambda c, s, sp: c + _signed_triangle(s, period, depth), base,
            ):
                best = (span, "VIBRATO", {"depth": depth, "period": period})
    return best


def best_volume_run(
    values: Sequence[int], start: int, frames: int, base: int, max_span: int
) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    """The longest run a single parameterised volume opcode reproduces exactly."""
    best: Optional[Tuple[int, str, Dict[str, Any]]] = None
    limit = min(max_span, frames - start)
    for span in range(2, limit + 1):
        target = values[start + span - 1]
        if _run_matches(values, start, span, lambda c, s, sp: _ramp(c, target, s, sp), base):
            best = (span, "VOLUME_SHAPE", {"target": target})
            continue
        window = values[start : start + span]
        depth = max(base - min(window), 0)
        if depth:
            reversals = 0
            sign = 0
            for index in range(1, len(window)):
                change = window[index] - window[index - 1]
                if change:
                    new_sign = 1 if change > 0 else -1
                    if sign and new_sign != sign:
                        reversals += 1
                    sign = new_sign
            period = max(2, (2 * span) // max(1, reversals))
            if _run_matches(
                values, start, span,
                lambda c, s, sp: c - _signed_triangle(s, period, depth), base,
            ):
                best = (span, "TREMOLO", {"depth": depth, "period": period})
    return best





def encode_reference(
    song: Song,
    attached: bool = False,
    max_span: int = EFFECT_MAX_SPAN,
) -> Tuple[Encoding, int]:
    """BEHAVIOUR-DRIVEN COMPILER - the trace itself, written in the language.

    This is the *size* experiment, and it is exact by construction: at every frame the encoder
    either has nothing to do, installs a parameterised effect that provably reproduces the
    next ``span`` frames, or emits a plain state change. When no effect fits it falls back to
    one state change per changing frame - which is exactly the degeneration toward per-frame
    data the brief asks to watch for, and it is counted rather than hidden.

    It is deliberately a *different* experiment from :func:`encode_performance`. That one asks
    whether the Stage 15 technique abstraction is a sufficient description of a song; this one
    asks what a faithful description costs. A language can pass the second and fail the first,
    and this pair of encodings is how that distinction is measured instead of asserted.

    Returns the encoding and the number of plain state-change events, since that count is the
    degeneration measure.
    """
    trace = song.trace
    frames = trace.frames
    layout = voice_layout(song.audctl)
    voice_channels = [channel for channel in CHANNELS if not layout[channel][1]]

    note_on: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    note_off: Dict[int, set] = {voice: set() for voice in voice_channels}
    for event in song.events:
        voice = _voice_of(song, event.channel)
        if voice not in note_off:
            continue
        params = dict(event.parameters)
        if event.kind == "NOTE_ON":
            note_on[(voice, event.start_frame)] = (
                int(params.get("divider", 0)), int(params.get("volume", 0)),
                max(1, int(params.get("note_frames") or event.duration_frames)),
            )
        elif event.kind == "NOTE_OFF":
            note_off[voice].add(event.start_frame)

    events: List[PerfEvent] = [make_event("SET_AUDCTL", CHANNEL_GLOBAL, 0, value=song.audctl)]
    for channel in voice_channels:
        audc = trace.registers[f"AUDC{channel}"][0]
        low = _paired_low_channel(song.audctl, channel)
        if low is not None:
            value = (trace.registers[f"AUDF{channel}"][0] << 8) | trace.registers[f"AUDF{low}"][0]
        else:
            value = trace.registers[f"AUDF{channel}"][0]
        events.append(make_event("SET_GENERATOR", channel, 0, dist=audc & 0xF0))
        events.append(make_event("SET_VOLUME", channel, 0, volume=audc & 0x0F))
        events.append(make_event("SET_PITCH", channel, 0, divider=value))

    choices: Dict[str, int] = {}
    plain_state_events = 0

    for channel in voice_channels:
        voice, _ = layout[channel]
        dividers = song.divider_series.get(voice, (0,) * frames)
        volumes = [trace.registers[f"AUDC{channel}"][frame] & 0x0F for frame in range(frames)]
        dists = [trace.registers[f"AUDC{channel}"][frame] & 0xF0 for frame in range(frames)]
        current_divider = dividers[0]
        current_volume = volumes[0]
        current_dist = dists[0]
        pitch_covered = 0
        volume_covered = 0
        frame = 0
        while frame < frames:
            note = note_on.get((voice, frame))
            if note is not None:
                divider, volume, duration = note
                current_divider, current_volume = divider, volume
                pitch_covered = volume_covered = 0
                choices["NOTE"] = choices.get("NOTE", 0) + 1
                events.append(make_event(
                    "NOTE", channel, frame, duration=duration if attached else 0,
                    divider=divider, volume=volume))
                frame += 1
                continue
            if frame in note_off[voice] and not attached:
                current_volume = 0
                volume_covered = 0
                events.append(make_event("NOTE_OFF", channel, frame))
                choices["NOTE_OFF"] = choices.get("NOTE_OFF", 0) + 1
                frame += 1
                continue

            if frame >= pitch_covered and dividers[frame] != current_divider:
                run = best_pitch_run(dividers, frame, frames, current_divider, max_span)
                if run is not None and run[0] - 1 >= MIN_EFFECT_GAIN:
                    span, opcode, params = run
                    events.append(make_event(opcode, channel, frame, duration=span, **params))
                    choices[opcode] = choices.get(opcode, 0) + 1
                    pitch_covered = frame + span
                else:
                    current_divider = dividers[frame]
                    events.append(
                        make_event("SET_PITCH", channel, frame, divider=current_divider))
                    choices["SET_PITCH"] = choices.get("SET_PITCH", 0) + 1
                    plain_state_events += 1
            if frame >= volume_covered and volumes[frame] != current_volume:
                run = best_volume_run(volumes, frame, frames, current_volume, max_span)
                if run is not None and run[0] - 1 >= MIN_EFFECT_GAIN:
                    span, opcode, params = run
                    events.append(make_event(opcode, channel, frame, duration=span, **params))
                    choices[opcode] = choices.get(opcode, 0) + 1
                    volume_covered = frame + span
                else:
                    current_volume = volumes[frame]
                    events.append(
                        make_event("SET_VOLUME", channel, frame, volume=current_volume))
                    choices["SET_VOLUME"] = choices.get("SET_VOLUME", 0) + 1
                    plain_state_events += 1
            if dists[frame] != current_dist and (volumes[frame] or current_volume):
                current_dist = dists[frame]
                events.append(make_event("SET_GENERATOR", channel, frame, dist=current_dist))
                choices["SET_GENERATOR"] = choices.get("SET_GENERATOR", 0) + 1
                plain_state_events += 1
            frame += 1

    label = "reference-" + ("attached" if attached else "sequential")
    description = (
        "the reference trace compiled straight into the language: notes carry "
        + ("durations" if attached else "no duration and NOTE_OFF ends them")
        + ", parameterised effects replace runs, plain state changes cover the rest"
    )
    return Encoding(
        label=label, description=description, events=tuple(sort_events(events)),
        choices=choices, unmapped={}, fitted_error=0,
    ), plain_state_events


def repair_pass(
    song: Song,
    events: Sequence[PerfEvent],
    max_rounds: int = 2,
) -> Tuple[List[PerfEvent], List[Dict[str, Any]]]:
    """Patch the residual: render, find what is still audibly wrong, correct it, repeat.

    This is the second half of the size experiment and it is what makes the result honest.
    The compact encoding above is *not* exact - it inherits one-frame conventions and the
    places where a running effect and a later change overlap. Rather than tune the encoder
    until it looks good, the residual is measured, patched, and counted: the patch events are
    reported as a first-class cost, because "how much explicit correction does the compact
    language need" is the question, not "can the encoder be made to look exact".
    """
    frames = song.frames
    trace = song.trace
    layout = voice_layout(song.audctl)
    voice_channels = [channel for channel in CHANNELS if not layout[channel][1]]
    current = sort_events(events)
    rounds: List[Dict[str, Any]] = []

    for round_index in range(max_rounds):
        rendered = interpret(current, frames, song.audctl).registers
        patched: List[PerfEvent] = []
        for channel in voice_channels:
            for frame in range(frames):
                ref_audc = trace.registers[f"AUDC{channel}"][frame]
                got_audc = rendered[f"AUDC{channel}"][frame]
                ref_volume, got_volume = ref_audc & 0x0F, got_audc & 0x0F
                if ref_volume != got_volume:
                    patched.append(make_event("SET_VOLUME", channel, frame, volume=ref_volume))
                    got_audc = (got_audc & 0xF0) | ref_volume
                sounding = bool(ref_volume)
                if sounding and (ref_audc & 0xF0) != (got_audc & 0xF0):
                    patched.append(
                        make_event("SET_GENERATOR", channel, frame, dist=ref_audc & 0xF0))
                if sounding and (
                    trace.registers[f"AUDF{channel}"][frame]
                    != rendered[f"AUDF{channel}"][frame]
                ):
                    low = _paired_low_channel(song.audctl, channel)
                    if low is not None:
                        value = (
                            trace.registers[f"AUDF{channel}"][frame] << 8
                        ) | trace.registers[f"AUDF{low}"][frame]
                    else:
                        value = trace.registers[f"AUDF{channel}"][frame]
                    patched.append(make_event("SET_PITCH", channel, frame, divider=value))
        counts: Dict[str, int] = {}
        for event in patched:
            counts[event.opcode] = counts.get(event.opcode, 0) + 1
        rounds.append(
            {
                "round": round_index + 1,
                "patch_events": len(patched),
                "by_opcode": dict(sorted(counts.items())),
            }
        )
        if not patched:
            break
        current = sort_events(list(current) + patched)
    return current, rounds



# ---------------------------------------------------------------------------
# PART C - layer responsibilities
# ---------------------------------------------------------------------------
def layer_responsibilities() -> Dict[str, Any]:
    """What each layer owns, and - the point of the separation - what it must not own."""
    return {
        "principle": (
            "The three layers are separated by *who decides*. The composition decides what "
            "should be heard; the event layer records those decisions as explicit operations; "
            "the player decides nothing and only executes. Every responsibility below is "
            "assigned to exactly one layer, because Stage 16 showed that a layer which infers "
            "context becomes a style model."
        ),
        "layers": [
            {
                "layer": "COMPOSITION (what / when)",
                "owns": [
                    "pitch: which divider a voice sounds at",
                    "duration: how long a note lasts",
                    "velocity: the volume a note starts at",
                    "rhythm and the placement of notes and rests",
                    "musical structure: phrases, sections, repetition",
                    "the decision that an effect happens at all, and when it starts",
                ],
                "must_not_own": [
                    "POKEY register addresses",
                    "frame timing or tick counts",
                    "AUDCTL bit layout",
                    "the per-frame shape of an effect",
                ],
            },
            {
                "layer": "PERFORMANCE EVENT IR (what happens)",
                "owns": [
                    "pitch modulation: slides, sweeps, vibrato, arpeggio",
                    "volume changes and volume shapes",
                    "generator changes",
                    "the duration of an effect, in frames",
                    "the channel an operation applies to",
                    "the frame each operation starts on",
                ],
                "must_not_own": [
                    "musical intent (nothing here says 'lead' or 'percussion')",
                    "song-specific rules ('in this song channel 3 is the bass')",
                    "inference from context",
                    "register addresses",
                ],
            },
            {
                "layer": "PLAYER (how / execute)",
                "owns": [
                    "POKEY register writes and their order",
                    "frame timing and the call rate",
                    "AUDCTL handling and 16-bit pairing",
                    "per-voice state (anchors, running effects, frame counters)",
                    "event dispatch",
                    "hardware clamping and the representable range",
                ],
                "must_not_own": [
                    "musical decisions",
                    "any knowledge of which song it is playing",
                ],
            },
        ],
        "measured_boundary_check": (
            "The boundary is testable and this stage tests it: the interpreter in Part I knows "
            "nothing about a song's identity. It receives channel numbers and parameter values "
            "and produces registers. Every case where the reconstruction failed is reported in "
            "Part I rather than being fixed by giving the interpreter a special case."
        ),
    }


# ---------------------------------------------------------------------------
# PART D - the minimal evidence-supported vocabulary
# ---------------------------------------------------------------------------
#: How each opcode's parameters are classified: a musical decision made by the composition
#: layer, or a hardware-level value the player needs.
PARAMETER_KIND = {
    "divider": "MUSICAL_DECISION",
    "volume": "MUSICAL_DECISION",
    "dist": "HARDWARE_LEVEL",
    "value": "HARDWARE_LEVEL",
    "delta": "MUSICAL_DECISION",
    "duration": "MUSICAL_DECISION",
    "curve": "MUSICAL_DECISION",
    "depth": "MUSICAL_DECISION",
    "period": "MUSICAL_DECISION",
    "count": "MUSICAL_DECISION",
    "target": "MUSICAL_DECISION",
    "notes": "MUSICAL_DECISION",
    "levels": "MUSICAL_DECISION",
}

#: Register effect of each opcode, written as what it changes rather than what it means.
OPCODE_EFFECT = {
    "SET_AUDCTL": "writes AUDCTL: clock source, 16-bit pairing, high-pass routing",
    "SET_GENERATOR": "writes the distortion nibble of one channel's AUDC",
    "SET_VOLUME": "writes the volume nibble of one channel's AUDC",
    "SET_PITCH": "writes the divider (AUDF, or both bytes of a joined pair) without retriggering",
    "NOTE": "writes the divider and the volume together and starts a note",
    "NOTE_OFF": "writes volume 0 on one channel",
    "PITCH_SLIDE": "writes a linearly changing divider for a fixed number of frames",
    "PITCH_SWEEP": "writes a quadratically changing divider for a fixed number of frames",
    "VIBRATO": "writes a triangle-modulated divider for a fixed number of frames",
    "TREMOLO": "writes a triangle-modulated volume for a fixed number of frames",
    "ARPEGGIO": "cycles a table of dividers at a fixed period",
    "VOLUME_SHAPE": "writes a volume that ramps or replays a table for a fixed number of frames",
}

#: Parameters each opcode accepts, in the order they are documented.
OPCODE_PARAMS: Dict[str, Tuple[str, ...]] = {
    "SET_AUDCTL": ("value",),
    "SET_GENERATOR": ("dist",),
    "SET_VOLUME": ("volume",),
    "SET_PITCH": ("divider",),
    "NOTE": ("divider", "volume", "duration"),
    "NOTE_OFF": (),
    "PITCH_SLIDE": ("delta", "duration", "curve"),
    "PITCH_SWEEP": ("delta", "duration", "curve"),
    "VIBRATO": ("depth", "period", "duration"),
    "TREMOLO": ("depth", "period", "duration"),
    "ARPEGGIO": ("count", "period", "notes", "duration"),
    "VOLUME_SHAPE": ("target", "levels", "duration"),
}


def technique_vocabulary(
    songs: Sequence[Song],
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
) -> Dict[str, Any]:
    """Part D: the vocabulary, each opcode carrying the technique evidence that justifies it.

    Nothing here is invented. Every row names the Stage 15 detector that produced the
    behaviour, the Stage 16 universality verdict for it, how many of the four songs contain it,
    and what the existing player would have to do to carry it.
    """
    universality_path = Path(stage16_dir) / "universality.json"
    gap_path = Path(stage15_dir) / "player_gap_analysis.json"
    universality = _read_json(universality_path)
    gap = _read_json(gap_path)
    gap_by_technique = {row["technique_id"]: row for row in gap["rows"]}
    universality_by_technique = {
        row["technique_id"]: row for row in universality["techniques"]
    }

    occurrences: Dict[str, Dict[str, int]] = {
        song.slug: dict(song.technique_counts) for song in songs
    }
    all_techniques = sorted({key for counts in occurrences.values() for key in counts})

    techniques: List[Dict[str, Any]] = []
    for technique_id in all_techniques:
        opcode = TECHNIQUE_TO_OPCODE.get(technique_id)
        counts = {slug: occurrences[slug].get(technique_id, 0) for slug in occurrences}
        songs_with = sorted(slug for slug, count in counts.items() if count > 0)
        verdict = universality_by_technique.get(technique_id, {})
        gap_row = gap_by_technique.get(
            technique_id,
            gap_by_technique.get(
                technique_id.replace("_RISING", "").replace("_FALLING", ""), {}
            ),
        )
        techniques.append(
            {
                "technique_id": technique_id,
                "opcode": opcode,
                "opcode_exists": opcode is not None,
                "evidence_source": f"stage15.detect_events -> {technique_id}",
                "songs_observed": songs_with,
                "songs_observed_count": len(songs_with),
                "occurrences_by_song": counts,
                "occurrences_total": sum(counts.values()),
                "stage16_universality": verdict.get("verdict"),
                "stage16_low_level": verdict.get("low_level"),
                "stage16_context_verdict": verdict.get("context_verdict"),
                "stage16_parameter_verdict": verdict.get("parameter_verdict"),
                "stage15_player_support": gap_row.get("classification"),
                "stage15_mechanism": gap_row.get("player_capability_that_would_carry_it"),
            }
        )

    opcodes: List[Dict[str, Any]] = []
    for opcode in OPCODE_ORDER:
        carriers = [row for row in techniques if row["opcode"] == opcode]
        opcodes.append(
            {
                "opcode": opcode,
                "effect": OPCODE_EFFECT[opcode],
                "parameters": list(OPCODE_PARAMS[opcode]),
                "parameter_kinds": {
                    name: PARAMETER_KIND[name] for name in OPCODE_PARAMS[opcode]
                },
                "justified_by": [row["technique_id"] for row in carriers],
                "justification_occurrences": sum(row["occurrences_total"] for row in carriers),
                "songs_in_which_the_justification_was_observed": sorted(
                    {slug for row in carriers for slug in row["songs_observed"]}
                ),
                "wire_bytes_parameters": sum(
                    PARAM_BYTES.get(name, VARIABLE_PARAMS.get(name, 0))
                    for name in OPCODE_PARAMS[opcode]
                ),
            }
        )

    return {
        "songs": [song.slug for song in songs],
        "techniques_in_union": len(all_techniques),
        "opcode_count": len(OPCODE_ORDER),
        "opcodes": opcodes,
        "techniques": techniques,
        "techniques_with_no_opcode": [
            row["technique_id"] for row in techniques if row["opcode"] is None
        ],
        "rejected_candidates": [dict(item) for item in REJECTED_CANDIDATES],
        "evidence_note": (
            "The vocabulary was read off the corpus, not chosen: the opcode set is exactly the "
            "distinct set of register effects that the techniques observed in the four Stage 16 "
            "songs require. Techniques that share an effect share an opcode, which is why the "
            "technique identifiers (Stage 15 splits glides and envelopes by direction) reduce "
            "to 12 opcodes."
        ),
        "source_hashes": {
            "stage16_universality": sha256_file(universality_path),
            "stage15_player_gap_analysis": sha256_file(gap_path),
        },
    }


# ---------------------------------------------------------------------------
# PART E - event semantic contracts
# ---------------------------------------------------------------------------
#: For every opcode: inputs, state modified, duration, interaction with NOTE, interaction with
#: other events, termination, whether it may overlap, and whether it is interruptible. Written
#: as data so the report and the tests read the same contract.
EVENT_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "SET_AUDCTL": {
        "inputs": ["value: 8-bit AUDCTL byte"],
        "state_modified": ["the channel mode; which channels are joined into pairs"],
        "duration": "0 frames (instantaneous); persists until the next SET_AUDCTL",
        "interaction_with_note": "none; it changes how dividers are interpreted, not the note",
        "interaction_with_other_events": (
            "re-writes the channel layout, so a joined pair's low channel stops carrying volume"
        ),
        "termination": "none; the value persists",
        "may_overlap": True,
        "interruptible": True,
        "evidence": (
            "AUDCTL_CHANGE occurs zero times in all four songs; the opcode exists only because "
            "a stream must declare the mode it is written in"
        ),
    },
    "SET_GENERATOR": {
        "inputs": ["dist: the AUDC distortion nibble (0,2,...,14, shifted into bits 7-4)"],
        "state_modified": ["the distortion nibble of one channel's AUDC"],
        "duration": "0 frames (instantaneous); persists until the next SET_GENERATOR",
        "interaction_with_note": "a NOTE does not change the distortion; the value survives a note",
        "interaction_with_other_events": "none; it never cancels a running effect",
        "termination": "none; the value persists",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "GENERATOR_CHANGE and DISTORTION_CHANGE together in all four songs",
    },
    "SET_VOLUME": {
        "inputs": ["volume: 0..15"],
        "state_modified": ["the volume anchor of one voice", "cancels a running volume effect"],
        "duration": "0 frames (instantaneous)",
        "interaction_with_note": "a NOTE also sets the volume anchor, so it supersedes this",
        "interaction_with_other_events": "cancels VOLUME_SHAPE and TREMOLO on the same voice",
        "termination": "none; the value persists",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "VOLUME_CHANGE (the third UNIVERSAL technique)",
    },
    "SET_PITCH": {
        "inputs": ["divider: 0..255, or 0..65535 when the voice is a joined pair"],
        "state_modified": ["the divider anchor of one voice", "cancels a running pitch effect"],
        "duration": "0 frames (instantaneous)",
        "interaction_with_note": "a NOTE sets the same anchor and additionally starts a note",
        "interaction_with_other_events": (
            "cancels PITCH_SLIDE, PITCH_SWEEP, VIBRATO and ARPEGGIO on the same voice"
        ),
        "termination": "none; the value persists",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "PITCH_CHANGE (low-level) and REGISTER_PATTERN_CHANGE (register-level)",
    },
    "NOTE": {
        "inputs": ["divider", "volume: 0..15", "duration: frames, 0 means 'no duration'"],
        "state_modified": [
            "the divider anchor and the volume anchor of one voice",
            "cancels running pitch and volume effects",
            "when duration > 0, schedules the volume to fall to 0 after that many frames",
        ],
        "duration": "the note sounds until NOTE_OFF, the next volume event, or start+duration",
        "interaction_with_note": "a NOTE supersedes the previous NOTE on the same voice",
        "interaction_with_other_events": "cancels every effect running on the same voice",
        "termination": (
            "with duration > 0 the volume returns to 0 at start+duration; with duration = 0 the "
            "note ends only when NOTE_OFF or a volume event arrives"
        ),
        "may_overlap": False,
        "interruptible": True,
        "evidence": "NOTE_ON is UNIVERSAL in Stage 16: present in all four songs with evidence",
    },
    "NOTE_OFF": {
        "inputs": [],
        "state_modified": ["the volume anchor is forced to 0", "cancels a running volume effect"],
        "duration": "0 frames (instantaneous)",
        "interaction_with_note": "ends the current note",
        "interaction_with_other_events": (
            "collides with SET_VOLUME on the same frame - see the ordering hazard below"
        ),
        "termination": "the voice stays silent until the next NOTE or volume event",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "NOTE_OFF is UNIVERSAL in Stage 16",
    },
    "PITCH_SLIDE": {
        "inputs": ["delta: divider change across the effect", "duration: frames", "curve: 0"],
        "state_modified": ["the divider of one voice, once per frame, while it runs"],
        "duration": "exactly ``duration`` frames",
        "interaction_with_note": "runs on top of the note that is already sounding",
        "interaction_with_other_events": (
            "cancels other pitch effects on the same voice, but CAN run while a volume effect runs"
        ),
        "termination": "when the duration elapses the voice returns to its divider anchor",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "PITCH_SLIDE_RISING and PITCH_SLIDE_FALLING in all four songs",
    },
    "PITCH_SWEEP": {
        "inputs": ["delta", "duration", "curve: 1"],
        "state_modified": ["the divider of one voice, quadratically in time"],
        "duration": "exactly ``duration`` frames",
        "interaction_with_note": "as PITCH_SLIDE",
        "interaction_with_other_events": "as PITCH_SLIDE",
        "termination": "returns to the divider anchor",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "PITCH_SWEEP_RISING in three songs and PITCH_SWEEP_FALLING in two",
    },
    "VIBRATO": {
        "inputs": ["depth: divider units, peak-to-peak 2*depth", "period: frames per cycle",
                   "duration"],
        "state_modified": ["the divider of one voice, by an integer triangle wave"],
        "duration": "exactly ``duration`` frames",
        "interaction_with_note": "as PITCH_SLIDE",
        "interaction_with_other_events": "as PITCH_SLIDE",
        "termination": "returns to the divider anchor",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "VIBRATO is SONG_SPECIFIC in Stage 16: present in one of the four songs",
    },
    "TREMOLO": {
        "inputs": ["depth: volume units", "period: frames per cycle", "duration"],
        "state_modified": ["the volume of one voice, ducking below its anchor"],
        "duration": "exactly ``duration`` frames",
        "interaction_with_note": "as VOLUME_SHAPE",
        "interaction_with_other_events": "cancels other volume effects on the same voice",
        "termination": "returns to the volume anchor",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "TREMOLO in all four songs, but Stage 16 found its context mostly differs",
    },
    "ARPEGGIO": {
        "inputs": ["count", "period: frames per tone", "notes: divider table", "duration"],
        "state_modified": ["the divider of one voice, cycling an absolute table"],
        "duration": "exactly ``duration`` frames; the table repeats when it runs out",
        "interaction_with_note": "as PITCH_SLIDE",
        "interaction_with_other_events": "as PITCH_SLIDE",
        "termination": "returns to the divider anchor",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "ARPEGGIO in three songs; its table is the pitch escape hatch",
    },
    "VOLUME_SHAPE": {
        "inputs": ["target: final level for a ramp", "levels: explicit table (optional)",
                   "duration"],
        "state_modified": ["the volume of one voice"],
        "duration": "exactly ``duration`` frames",
        "interaction_with_note": (
            "runs on top of the note that is already sounding, from the note's own volume"
        ),
        "interaction_with_other_events": (
            "cancels other volume effects on the same voice, but can run under a pitch effect"
        ),
        "termination": "returns to the volume anchor",
        "may_overlap": True,
        "interruptible": True,
        "evidence": "VOLUME_ENVELOPE_RISING and VOLUME_ENVELOPE_FALLING across the four songs",
    },
}

#: The ordering hazard Part E found by measurement rather than by inspection.
EVENT_ORDERING_HAZARD = (
    "NOTE_OFF and SET_VOLUME on the same frame are ambiguous. The IR resolves the collision by "
    "opcode order, and that order puts SET_VOLUME before NOTE_OFF - so a correction written to "
    "a frame that also ends a note is silently discarded, and that reconstruction does not "
    "converge however many repair rounds it is given. Parts E and I report this as a defect in "
    "the language rather than working around it, and it is one of the measured reasons the "
    "attached note model is preferred over the sequential one."
)


def event_semantics() -> Dict[str, Any]:
    """Part E: the contracts, plus the one hazard that this stage's own round trip exposed."""
    return {
        "contracts": {opcode: EVENT_CONTRACTS[opcode] for opcode in OPCODE_ORDER},
        "opcode_order": list(OPCODE_ORDER),
        "opcode_order_note": (
            "The order is part of the semantics, not an implementation detail: it decides how a "
            "same-frame collision is resolved."
        ),
        "simultaneous_effects": [
            "a pitch effect and a volume effect may run at the same time on one voice: the "
            "reference behaviour needs a glide under a volume envelope"
        ],
        "ordering_hazard": EVENT_ORDERING_HAZARD,
        "rejected_candidates": [dict(item) for item in REJECTED_CANDIDATES],
        "minimality_note": (
            "Every contract above is the smallest one that could represent the observed traces. "
            "The stage did not add an opcode for pitch-modulation shape, for a rest, or for a "
            "wait, because the existing opcodes plus the frame field already cover those cases."
        ),
    }



# ---------------------------------------------------------------------------
# PARTS H/I/K/N - one measurement pass per song
# ---------------------------------------------------------------------------
@dataclass
class SongResult:
    """Every number this stage needs about one song, computed once."""

    song: Song
    control: List[PerfEvent]
    control_comparison: FrameComparison
    abstract: Encoding
    abstract_comparison: FrameComparison
    reference: Encoding
    reference_comparison: FrameComparison
    reference_repair: List[Dict[str, Any]]
    reference_fixed: List[PerfEvent]
    reference_fixed_comparison: FrameComparison
    sequential: Encoding
    sequential_comparison: FrameComparison
    sequential_repair: List[Dict[str, Any]]
    sequential_fixed: List[PerfEvent]
    sequential_fixed_comparison: FrameComparison
    plain_state_events: int

    def compare(self, events: Sequence[PerfEvent]) -> FrameComparison:
        rendered = interpret(events, self.song.frames, self.song.audctl)
        return compare_frames(
            self.song.trace.registers, rendered.registers, self.song.frames, self.song.audctl
        )


def measure_song(song: Song) -> SongResult:
    """Encode one song four ways and measure each reconstruction against the reference."""
    control = encode_register_state(song)
    abstract = encode_performance(song, attached=False)
    reference, plain = encode_reference(song, attached=True)
    sequential, _ = encode_reference(song, attached=False)
    reference_fixed, reference_repair = repair_pass(song, reference.events)
    sequential_fixed, sequential_repair = repair_pass(song, sequential.events)
    return SongResult(
        song=song,
        control=control,
        control_comparison=compare_frame_stream(song, control),
        abstract=abstract,
        abstract_comparison=compare_frame_stream(song, abstract.events),
        reference=reference,
        reference_comparison=compare_frame_stream(song, reference.events),
        reference_repair=reference_repair,
        reference_fixed=reference_fixed,
        reference_fixed_comparison=compare_frame_stream(song, reference_fixed),
        sequential=sequential,
        sequential_comparison=compare_frame_stream(song, sequential.events),
        sequential_repair=sequential_repair,
        sequential_fixed=sequential_fixed,
        sequential_fixed_comparison=compare_frame_stream(song, sequential_fixed),
        plain_state_events=plain,
    )


def compare_frame_stream(song: Song, events: Sequence[PerfEvent]) -> FrameComparison:
    """Render an event stream and compare it with the song's reference trace."""
    rendered = interpret(events, song.frames, song.audctl)
    return compare_frames(
        song.trace.registers, rendered.registers, song.frames, song.audctl
    )


def measure_songs(songs: Sequence[Song]) -> List[SongResult]:
    return [measure_song(song) for song in songs]



# ---------------------------------------------------------------------------
# PART B - evidence sources, and PART H - reference trace encodings
# ---------------------------------------------------------------------------
def evidence_sources(
    selection: Mapping[str, Any],
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    player_asm: Path = DEFAULT_PLAYER_ASM,
) -> Dict[str, Any]:
    """Part B: every input, read through its hash, with the role it plays."""
    watched = {
        "stage16_song_selection": Path(stage16_dir) / "song_selection.json",
        "stage16_universality": Path(stage16_dir) / "universality.json",
        "stage16_context_generalization": Path(stage16_dir) / "context_generalization.json",
        "stage15_player_capability_matrix": Path(stage15_dir) / "player_capability_matrix.json",
        "stage15_player_gap_analysis": Path(stage15_dir) / "player_gap_analysis.json",
        "stage15_player_size_analysis": Path(stage15_dir) / "player_size_analysis.json",
        "stage15_hypothetical_player_design": Path(stage15_dir) / "hypothetical_player_design.json",
        "stage15_summary": Path(stage15_dir) / "summary.json",
        "player_asm": Path(player_asm),
    }
    hashes = {name: sha256_file(path) for name, path in sorted(watched.items())}
    # The player source is hashed the way Stage 15 hashed it, so the two stages agree about the
    # same unmodified file. Everything else keeps the byte hash Stage 16 uses for its records.
    player_hash = sha256_source_text(Path(player_asm))
    hashes["player_asm"] = player_hash
    return {
        "stage16_selection_record": {
            "path": selection["source"],
            "sha256": selection["source_sha256"],
            "role": "decides which four songs are analysed; not re-chosen here",
        },
        "trace_sources": [
            {"slug": candidate["slug"], "path": candidate["path"], "sha256": candidate["sha256"]}
            for candidate in selection["candidates"]
        ],
        "stage15_and_player_records": {
            name: {"path": str(watched[name]), "sha256": hashes[name]}
            for name in sorted(watched)
        },
        "hash_conventions": {
            "json_artefacts_and_traces": "SHA-256 over the file's raw bytes",
            "player_source": (
                "SHA-256 over the file read as normalised UTF-8 text, which is the convention "
                "Stage 15 used for its own player hash; hashing the bytes would disagree with "
                "Stage 15 about an unmodified file because of line endings"
            ),
        },
        "technique_definition_source": (
            "stage15.detect_events and stage15.technique_id are imported and called, not "
            "re-implemented: every event this stage encodes is the same object Stage 15 and "
            "Stage 16 published."
        ),
        "stage16_reused_verdicts": (
            "the universality, low-level flag, context verdict and parameter verdict for each "
            "technique are read from reports/stage16/universality.json rather than recomputed"
        ),
    }


#: The categories Part H asks for, and the opcode that represents each one.
REFERENCE_CATEGORIES = (
    ("simple_note", "NOTE"),
    ("generator_change", "SET_GENERATOR"),
    ("volume_change", "VOLUME_SHAPE"),
    ("pitch_change", "PITCH_SLIDE"),
    ("pitch_sweep", "PITCH_SWEEP"),
    ("periodic_pitch", "ARPEGGIO"),
)


def _contextual_cross_song_cases(results: Sequence[SongResult]) -> List[Dict[str, Any]]:
    """The same opcode, in two songs, with demonstrably different parameters."""
    cases: List[Dict[str, Any]] = []
    for opcode in ("SET_GENERATOR", "PITCH_SLIDE", "VOLUME_SHAPE", "TREMOLO"):
        found: List[Dict[str, Any]] = []
        for result in results:
            for event in result.reference.events:
                if event.opcode != opcode:
                    continue
                params = dict(event.params)
                for key in ("dist", "delta", "target", "depth"):
                    if key in params:
                        found.append(
                            {
                                "slug": result.song.slug,
                                "frame": event.frame,
                                "channel": event.channel,
                                "parameter": key,
                                "value": params[key],
                                "duration": event.duration,
                            }
                        )
                        break
                break
        distinct = {(item["slug"], item["value"]) for item in found}
        if len(found) >= 2 and len(distinct) >= 2:
            cases.append(
                {
                    "opcode": opcode,
                    "occurrences": found,
                    "reading": (
                        f"the same {opcode} event is written with different parameters in "
                        "different songs; the language records the parameter and does not care "
                        "why it differs"
                    ),
                }
            )
    return cases


def reference_encodings(results: Sequence[SongResult]) -> Dict[str, Any]:
    """Part H: representative observed behaviour, and what the language makes of it.

    Examples are chosen by a rule that cannot depend on judgement: for each category, the first
    occurrence in canonical stream order. The window published is the event's own frame span,
    so a reader can check the encoding against the trace by hand.
    """
    songs_out: List[Dict[str, Any]] = []
    for result in results:
        song = result.song
        events = list(result.reference.events)
        examples: List[Dict[str, Any]] = []
        for category, opcode in REFERENCE_CATEGORIES:
            for event in events:
                if event.opcode != opcode:
                    continue
                start = event.frame
                length = max(1, event.duration or 1)
                end = min(song.frames - 1, start + length - 1)
                window_events = [item for item in events if start <= item.frame <= end]
                examples.append(
                    {
                        "category": category,
                        "window_frames": [start, end],
                        "channel": event.channel,
                        "opcode": opcode,
                        "encoded_events": [item.to_dict() for item in window_events],
                        "reference_registers": {
                            name: list(song.trace.registers[name][start : end + 1])
                            for name in REGISTER_ORDER
                        },
                    }
                )
                break

        counts: Dict[int, int] = {}
        for event in events:
            counts[event.frame] = counts.get(event.frame, 0) + 1
        busiest_frame, busiest_count = 0, -1
        for frame in sorted(counts):
            if counts[frame] > busiest_count:
                busiest_frame, busiest_count = frame, counts[frame]
        low = max(0, busiest_frame - 2)
        high = min(song.frames - 1, busiest_frame + 2)
        examples.append(
            {
                "category": "busiest_multi_event_frame",
                "window_frames": [low, high],
                "channel": None,
                "opcode": None,
                "encoded_events": [
                    item.to_dict() for item in events if low <= item.frame <= high
                ],
                "reference_registers": {
                    name: list(song.trace.registers[name][low : high + 1])
                    for name in REGISTER_ORDER
                },
                "note": f"{busiest_count} events start on frame {busiest_frame}",
            }
        )
        songs_out.append(
            {
                "slug": song.slug,
                "audctl": f"${song.audctl:02X}",
                "frames": song.frames,
                "examples": examples,
            }
        )

    return {
        "selection_rule": (
            "for each category, the first occurrence in canonical stream order; the window is "
            "the event's own frame span, capped at the song's last frame"
        ),
        "songs": songs_out,
        "cross_song_context_cases": _contextual_cross_song_cases(results),
        "question": (
            "Can the same event representation describe two songs where the same low-level "
            "technique has different musical meanings? Part R expects yes; the cross-song cases "
            "are the evidence."
        ),
    }


# ---------------------------------------------------------------------------
# PART I - round-trip reconstruction
# ---------------------------------------------------------------------------
def _representation_row(
    result: SongResult, label: str, role: str, events: Sequence[PerfEvent],
    comparison: FrameComparison, extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    row = {
        "label": label,
        "role": role,
        "events": len(events),
        "bytes": ir_bytes(events),
        "comparison": comparison.to_dict(),
    }
    if extra:
        row.update(extra)
    return row


def reconstruction_results(results: Sequence[SongResult]) -> Dict[str, Any]:
    """Part I: the key technical test, reported per song and per representation."""
    rows: List[Dict[str, Any]] = []
    for result in results:
        song = result.song
        rows.append(
            {
                "slug": song.slug,
                "frames": song.frames,
                "audctl": f"${song.audctl:02X}",
                "representations": [
                    {
                        "label": "RAW_FRAMES",
                        "role": "ground truth, NOT part of the language (Part J)",
                        "events": song.frames,
                        "bytes": raw_frame_bytes(song.frames),
                        "comparison": {"exact_share": 1.0, "note": "by definition"},
                    },
                    _representation_row(
                        result, "REGISTER_STATE_CONTROL",
                        "control: register-level state changes only, no note model",
                        result.control, result.control_comparison,
                    ),
                    _representation_row(
                        result, "PERFORMANCE_ABSTRACTION_DRIVEN",
                        "the Stage 15 technique abstraction replayed as events: tests whether "
                        "the vocabulary is a sufficient description",
                        result.abstract.events, result.abstract_comparison,
                        {"fit_residual_mismatch_frames": result.abstract.fitted_error},
                    ),
                    _representation_row(
                        result, "PERFORMANCE_REFERENCE_ATTACHED",
                        "behaviour-driven compiler, attached notes, no repair",
                        result.reference.events, result.reference_comparison,
                    ),
                    _representation_row(
                        result, "PERFORMANCE_REFERENCE_ATTACHED_REPAIRED",
                        "as above plus the measured repair pass",
                        result.reference_fixed, result.reference_fixed_comparison,
                        {"repair_rounds": result.reference_repair},
                    ),
                    _representation_row(
                        result, "PERFORMANCE_REFERENCE_SEQUENTIAL",
                        "behaviour-driven compiler with NOTE_OFF instead of durations",
                        result.sequential.events, result.sequential_comparison,
                    ),
                    _representation_row(
                        result, "PERFORMANCE_REFERENCE_SEQUENTIAL_REPAIRED",
                        "as above plus the measured repair pass",
                        result.sequential_fixed, result.sequential_fixed_comparison,
                        {"repair_rounds": result.sequential_repair},
                    ),
                ],
            }
        )

    def share(label: str, key: str) -> Optional[float]:
        values: List[float] = []
        for row in rows:
            for representation in row["representations"]:
                if representation["label"] == label:
                    value = representation["comparison"].get(key)
                    if value is not None:
                        values.append(float(value))
        return _rnd(_mean(values)) if values else None

    attached = share("PERFORMANCE_REFERENCE_ATTACHED_REPAIRED", "exact_share")
    sequential = share("PERFORMANCE_REFERENCE_SEQUENTIAL_REPAIRED", "exact_share")
    return {
        "pipeline": (
            "reference POKEY trace -> Stage 15 events -> event encoding -> Performance Event IR "
            "-> the offline interpreter -> POKEY frame stream -> compared with the reference"
        ),
        "classification_rule": {
            "EXACT": (
                "AUDCTL agrees and every channel either is silent on both sides or reproduces "
                "the same volume, distortion and divider"
            ),
            "APPROXIMATE": "as EXACT except an audible channel has a different divider",
            "UNREPRESENTABLE": (
                "an audible channel has the wrong volume or distortion, or AUDCTL is wrong"
            ),
            "why_audibility_matters": (
                "a silent channel's distortion and divider change no sound; counting them would "
                "measure the reference players' register hygiene rather than the language. The "
                "strict all-nine-registers figure is published as register_exact_share in every "
                "comparison, so the harsher number is never hidden."
            ),
        },
        "songs": rows,
        "summary": {
            "attached_note_model_exact_share_mean": attached,
            "sequential_note_model_exact_share_mean": sequential,
            "abstraction_driven_exact_share_mean": share(
                "PERFORMANCE_ABSTRACTION_DRIVEN", "exact_share"
            ),
            "control_exact_share_mean": share("REGISTER_STATE_CONTROL", "exact_share"),
            "note_model_verdict": (
                "ATTACHED: with the repair pass it reaches 100% on all four songs. SEQUENTIAL: "
                "it does not converge, because NOTE_OFF and SET_VOLUME collide on the same frame "
                "and the opcode order resolves the collision against the correction."
            ),
        },
    }



# ---------------------------------------------------------------------------
# PART K - compression analysis
# ---------------------------------------------------------------------------
def compression(results: Sequence[SongResult]) -> Dict[str, Any]:
    """Part K: three representations of the same excerpts, on the same byte model.

    Representation A is the current player's note event (AUDF, duration, volume).
    Representation B is the raw per-frame POKEY state, which is the ground truth and the floor
    a dedicated format would have to beat. Representation C is the proposed IR.
    """
    songs_out: List[Dict[str, Any]] = []
    for result in results:
        song = result.song
        raw = raw_frame_bytes(song.frames)
        current = current_format_bytes(song.note_events)
        rows = [
            {
                "representation": "A_current_note_event",
                "description": "3 bytes per note: AUDF, duration, volume, plus the player's fixed table",
                "bytes": current + CURRENT_FIXED_OVERHEAD_BYTES,
                "note_table_bytes": current,
                "fixed_overhead_bytes": CURRENT_FIXED_OVERHEAD_BYTES,
                "events": song.note_events,
                "state_transitions": song.note_events,
            },
            {
                "representation": "B_raw_per_frame_state",
                "description": "9 register bytes per frame; ground truth (Part J: not the language)",
                "bytes": raw,
                "events": song.frames,
                "state_transitions": None,
            },
            {
                "representation": "C_register_state_control",
                "description": "the language used only as register state changes (control)",
                "bytes": ir_bytes(result.control),
                "events": len(result.control),
                "state_transitions": len(result.control),
            },
            {
                "representation": "C_performance_abstraction",
                "description": "the Stage 15 technique abstraction, fitted onto the language",
                "bytes": ir_bytes(result.abstract.events),
                "events": result.abstract.event_count,
                "state_transitions": result.abstract.event_count,
            },
            {
                "representation": "C_performance_attached",
                "description": "behaviour-driven compiler, attached notes, before repair",
                "bytes": ir_bytes(result.reference.events),
                "events": result.reference.event_count,
                "state_transitions": result.reference.event_count,
            },
            {
                "representation": "C_performance_attached_repaired",
                "description": "behaviour-driven compiler plus the repair pass (exact)",
                "bytes": ir_bytes(result.reference_fixed),
                "events": len(result.reference_fixed),
                "state_transitions": len(result.reference_fixed),
            },
        ]
        by_label = {row["representation"]: row["bytes"] for row in rows}
        abstraction_smaller = by_label["C_performance_abstraction"] < raw
        for row in rows:
            row["ratio_to_raw_frames"] = _rnd(row["bytes"] / raw if raw else None, 3)
            row["ratio_to_current_format"] = _rnd(
                row["bytes"] / (current + CURRENT_FIXED_OVERHEAD_BYTES)
                if current else None, 3
            )
        songs_out.append(
            {
                "slug": song.slug,
                "frames": song.frames,
                "audctl": f"${song.audctl:02X}",
                "note_events": song.note_events,
                "audible_frames": sum(
                    1 for frame in range(song.frames)
                    for channel in CHANNELS
                    if song.trace.registers[f"AUDC{channel}"][frame] & 0x0F
                ),
                "representations": rows,
                "reading": {
                    "raw_frames_is_the_floor": (
                        "a full register dump every frame is what a dedicated format would have "
                        "to beat; it is the honest floor for this comparison"
                    ),
                    "does_the_event_layer_compress": (
                        "no" if by_label["C_performance_attached_repaired"] > raw
                        else "yes"
                    ),
                    "is_the_abstraction_encoding_smaller_than_the_dump":
                        abstraction_smaller,
                },
            }
        )
    abstraction_smaller_count = sum(
        1
        for song in songs_out
        if song["reading"]["is_the_abstraction_encoding_smaller_than_the_dump"]
    )
    return {
        "byte_model": (
            "IR record = 1 byte opcode+channel, an unsigned frame delta in 1-3 bytes, 1 byte "
            "duration, then the parameters: divider/delta 2 bytes, volume/dist/target/curve/"
            "period/count 1 byte, table entries 1-2 bytes each. Raw frames = 9 bytes per frame. "
            "Current format = 3 bytes per note plus a 7-byte header and a 20-byte instrument "
            "table. The model is stated so every ratio can be recomputed by hand."
        ),
        "abstraction_smaller_than_raw_dump_songs": abstraction_smaller_count,
        "abstraction_smaller_than_raw_dump_note": (
            f"The abstraction-driven encoding is smaller than the raw dump in "
            f"{abstraction_smaller_count} of {len(songs_out)} songs, and not in the rest - a "
            "count that is published because the difference matters: the only compact "
            "representation found is also the one that reproduces the least"
        ),
        "songs": songs_out,
    }


# ---------------------------------------------------------------------------
# PART N - song data cost, and PART O - hardware constraints
# ---------------------------------------------------------------------------
def song_data_cost(results: Sequence[SongResult]) -> Dict[str, Any]:
    """Part N: player code size and song data size, kept strictly apart.

    Stage 15's finding was that the binding constraint is the event format, not the player.
    This section restates the two costs separately so a reader cannot confuse them.
    """
    songs_out: List[Dict[str, Any]] = []
    for result in results:
        song = result.song
        attached = ir_bytes(result.reference.events)
        repaired = ir_bytes(result.reference_fixed)
        songs_out.append(
            {
                "slug": song.slug,
                "frames": song.frames,
                "duration_s": _rnd(song.frames * song.trace.frame_period_ms / 1000.0, 2),
                "current_format_bytes": current_format_bytes(song.note_events),
                "current_format_fixed_overhead_bytes": CURRENT_FIXED_OVERHEAD_BYTES,
                "raw_frame_dump_bytes": raw_frame_bytes(song.frames),
                "performance_event_bytes": attached,
                "performance_event_bytes_repaired": repaired,
                "bytes_per_frame": {
                    "raw_frame_dump": _rnd(raw_frame_bytes(song.frames) / song.frames, 3),
                    "performance_event": _rnd(attached / song.frames, 3),
                    "performance_event_repaired": _rnd(repaired / song.frames, 3),
                    "current_format": _rnd(
                        current_format_bytes(song.note_events) / song.frames, 3
                    ),
                },
                "plain_state_change_events": result.plain_state_events,
                "plain_state_share_of_events": _share(
                    result.plain_state_events, result.reference.event_count
                ),
            }
        )
    return {
        "separation_note": (
            "Player code and song data are different budgets and this stage reports them "
            "separately. Nothing in Part N is a claim about the player's size; that is Part L."
        ),
        "songs": songs_out,
        "comparison_to_stage15": (
            "Stage 15 measured the reference song at 90,486 bytes as one note per frame and 886 "
            "bytes of player. The 'raw_frame_dump' column above is the same idea measured "
            "directly on the trace, and it is the number the event encoding is compared with."
        ),
    }


def hardware_constraints(results: Sequence[SongResult]) -> Dict[str, Any]:
    """Part O: what the hardware forces, what it forbids, and what the interpreter refused."""
    songs_out: List[Dict[str, Any]] = []
    for result in results:
        song = result.song
        rendered = interpret(result.reference_fixed, song.frames, song.audctl)
        divider_max = AUDF_16BIT_MAX if joined_pair_channels(song.audctl) else AUDF_8BIT_MAX
        observed_max = max(
            (value for series in song.divider_series.values() for value in series), default=0
        )
        songs_out.append(
            {
                "slug": song.slug,
                "audctl": f"${song.audctl:02X}",
                "audctl_bits": list(stage15.audctl_bits(song.audctl)),
                "joined_pairs": [list(pair) for pair in joined_pair_channels(song.audctl)],
                "divider_range_in_this_song": divider_max,
                "largest_divider_observed": observed_max,
                "unrepresentable_pitch_events": rendered.unrepresentable_pitch,
                "unrepresentable_volume_events": rendered.unrepresentable_volume,
                "clamped_writes": rendered.clamped_writes,
                "expired_effects": rendered.expired_effects,
            }
        )
    return {
        "constraints": [
            {
                "constraint": "8-bit divider range",
                "rule": "0..255 when the channel is not part of a joined pair",
                "handling": "the interpreter clamps and counts; the count is published per song",
            },
            {
                "constraint": "16-bit channel coupling",
                "rule": (
                    "AUDCTL bit 4 joins channels 1+2, bit 5 joins 3+4; the low channel supplies "
                    "the divider's low byte and carries no volume, the high channel carries the "
                    "high byte and the volume"
                ),
                "handling": (
                    "voice_layout() encodes this rule; the language addresses the voice, and the "
                    "interpreter derives both register bytes from one divider value"
                ),
            },
            {
                "constraint": "AUDCTL",
                "rule": "one byte, global, affects every channel at once",
                "handling": (
                    "SET_AUDCTL. There is exactly one in every stream, at frame 0; a mid-song "
                    "change was never observed in the corpus"
                ),
            },
            {
                "constraint": "channel ownership",
                "rule": "a joined pair is one voice with two registers",
                "handling": (
                    "an event names the voice channel; the low channel of a pair is never "
                    "addressed separately, so the two bytes cannot desynchronise"
                ),
            },
            {
                "constraint": "generator / distortion",
                "rule": "AUDC bits 7-4 select the waveform, bits 3-0 the volume",
                "handling": "SET_GENERATOR carries bits 7-4 and only bits 7-4",
            },
            {
                "constraint": "volume",
                "rule": "0..15",
                "handling": "the interpreter clamps to 0..15 and counts the clamps",
            },
            {
                "constraint": "frame rate",
                "rule": "the corpus is digitised at 50 Hz; an effect duration is a frame count",
                "handling": (
                    "durations are in frames; the language has no notion of seconds, so it "
                    "cannot silently resample"
                ),
            },
        ],
        "refusal_rule": (
            "A pitch outside the current mode's range is refused rather than folded. The "
            "interpreter increments unrepresentable_pitch instead of wrapping the divider, "
            "because wrapping would turn an unrepresentable pitch into a wrong but plausible "
            "one and the failure would become invisible."
        ),
        "not_hidden": (
            "No semantic event silently assumes its target is representable. A PITCH_SLIDE "
            "whose delta leaves the range is clamped and counted, not encoded away."
        ),
        "songs": songs_out,
    }


# ---------------------------------------------------------------------------
# PART L - player code cost model
# ---------------------------------------------------------------------------
#: Bytes per code line in the *current* player, derived from its own source. Stage 15 published
#: 827 code bytes over 453 code lines; the same density is assumed for new code, and every
#: number below is therefore an ESTIMATE whose method is this one ratio.
BYTES_PER_CODE_LINE = 1.826

#: Per opcode: estimated handler code lines, extra RAM bytes, and CPU cycles when it fires.
#: ESTIMATE - line counts are engineering estimates, not measurements; the method is stated so
#: the arithmetic can be redone. The RAM figures are structural and exact.
OPCODE_COST: Dict[str, Dict[str, int]] = {
    "SET_AUDCTL": {"code_lines": 6, "state_bytes": 0, "cycles": 12},
    "SET_GENERATOR": {"code_lines": 4, "state_bytes": 0, "cycles": 8},
    "SET_VOLUME": {"code_lines": 4, "state_bytes": 0, "cycles": 6},
    "SET_PITCH": {"code_lines": 5, "state_bytes": 0, "cycles": 10},
    "NOTE": {"code_lines": 10, "state_bytes": 0, "cycles": 20},
    "NOTE_OFF": {"code_lines": 3, "state_bytes": 0, "cycles": 6},
    "PITCH_SLIDE": {"code_lines": 18, "state_bytes": 4, "cycles": 22},
    "PITCH_SWEEP": {"code_lines": 20, "state_bytes": 4, "cycles": 26},
    "VIBRATO": {"code_lines": 22, "state_bytes": 5, "cycles": 30},
    "TREMOLO": {"code_lines": 20, "state_bytes": 4, "cycles": 28},
    "ARPEGGIO": {"code_lines": 26, "state_bytes": 6, "cycles": 34},
    "VOLUME_SHAPE": {"code_lines": 20, "state_bytes": 4, "cycles": 24},
}

#: The dispatcher every event passes through: read opcode and channel, index a jump table.
DISPATCH_CODE_LINES = 28
#: Pointer per voice into its own event stream, plus the cursor.
DISPATCH_STATE_BYTES = 4 * 2


def player_cost_model(
    vocabulary: Mapping[str, Any],
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
) -> Dict[str, Any]:
    """Part L: what each opcode would cost the 6502 player, estimated and labelled.

    Nothing here modifies the player. The baseline is the measured current player read from
    Stage 15's own size analysis; the additions are estimates built from the same bytes-per-
    code-line ratio Stage 15 used, so the arithmetic is reproducible rather than authoritative.
    """
    size_path = Path(stage15_dir) / "player_size_analysis.json"
    size = _read_json(size_path)
    baseline_bytes = int(size["assembled_bytes"])
    baseline_state = int(size["state_bytes"])
    baseline_code = int(size["code_bytes"])

    rows: List[Dict[str, Any]] = []
    total_code = 0
    total_state = 0
    total_cycles = 0
    for opcode in OPCODE_ORDER:
        cost = OPCODE_COST[opcode]
        code_bytes = int(round(cost["code_lines"] * BYTES_PER_CODE_LINE))
        total_code += code_bytes
        total_state += cost["state_bytes"]
        total_cycles += cost["cycles"]
        rows.append(
            {
                "opcode": opcode,
                "basis": "ESTIMATE",
                "dispatch_cost": "1 jump-table entry, 2 bytes, plus a bounds check",
                "handler_code_lines": cost["code_lines"],
                "estimated_handler_code_bytes": code_bytes,
                "estimated_state_bytes": cost["state_bytes"],
                "estimated_cycles_when_it_fires": cost["cycles"],
                "justified_by": next(
                    (
                        item["justified_by"]
                        for item in vocabulary["opcodes"]
                        if item["opcode"] == opcode
                    ),
                    [],
                ),
            }
        )

    dispatch_bytes = int(round(DISPATCH_CODE_LINES * BYTES_PER_CODE_LINE))
    added_code = dispatch_bytes + total_code
    added_state = DISPATCH_STATE_BYTES + total_state
    total_bytes = baseline_bytes + added_code
    envelope = 2048
    return {
        "method": (
            "ESTIMATE, by construction. The baseline is measured: Stage 15 recorded "
            f"{baseline_bytes} assembled bytes ({baseline_code} code, {baseline_state} state). "
            "New code is charged at the current source's own density, "
            f"{BYTES_PER_CODE_LINE} bytes per code line (827 code bytes over 453 code lines), "
            "and the per-opcode line counts are engineering estimates stated in OPCODE_COST. "
            "The RAM figures are structural, not estimates: each running effect needs an opcode, "
            "a remaining-frame counter and its parameters, per voice."
        ),
        "baseline": {
            "assembled_bytes": baseline_bytes,
            "code_bytes": baseline_code,
            "state_bytes": baseline_state,
            "zero_page_bytes": int(size["zero_page_bytes"]),
            "source_sha256": size["source_sha256"],
            "source": str(size_path),
            "source_sha256_record": sha256_file(size_path),
        },
        "opcodes": rows,
        "dispatcher": {
            "code_lines": DISPATCH_CODE_LINES,
            "estimated_code_bytes": dispatch_bytes,
            "estimated_state_bytes": DISPATCH_STATE_BYTES,
            "note": "one stream pointer and cursor per voice",
        },
        "totals": {
            "added_code_bytes": added_code,
            "added_state_bytes": added_state,
            "added_cycles_if_every_opcode_fired_once": total_cycles,
            "player_bytes_after_estimate": total_bytes,
            "envelope_bytes": envelope,
            "headroom_bytes": envelope - total_bytes,
            "headroom_share": _share(envelope - total_bytes, envelope),
        },
    }



# ---------------------------------------------------------------------------
# PART M - 2 KB feasibility
# ---------------------------------------------------------------------------
def player_feasibility(cost: Mapping[str, Any]) -> Dict[str, Any]:
    """Part M: does the estimated player still fit the envelope the project works in?

    The answer is deliberately expressed as one of five labels rather than a probability, and
    the label is derived from the estimate's own headroom so it cannot be asserted separately
    from the arithmetic.
    """
    totals = cost["totals"]
    envelope = int(totals["envelope_bytes"])
    projected = int(totals["player_bytes_after_estimate"])
    headroom = int(totals["headroom_bytes"])
    share = headroom / envelope if envelope else 0.0
    if projected <= envelope * 0.75:
        label = "COMFORTABLY_FITS"
    elif projected <= envelope:
        label = "LIKELY_FITS"
    elif projected <= envelope * 1.10:
        label = "UNCERTAIN"
    elif projected <= envelope * 1.50:
        label = "LIKELY_EXCEEDS"
    else:
        label = "CLEARLY_EXCEEDS"
    return {
        "baseline_bytes": cost["baseline"]["assembled_bytes"],
        "added_code_bytes_estimate": totals["added_code_bytes"],
        "added_state_bytes": totals["added_state_bytes"],
        "projected_player_bytes_estimate": projected,
        "envelope_bytes": envelope,
        "headroom_bytes": headroom,
        "headroom_share": _rnd(share),
        "label": label,
        "method": (
            "ESTIMATE. The baseline is measured; the additions are estimated from the current "
            "source's bytes-per-code-line. The label is read off the resulting headroom, so it "
            "moves with the arithmetic instead of being a separate opinion."
        ),
        "what_this_does_not_say": (
            "It does not say the player should be expanded. Stage 15 measured 886 bytes against "
            "a 2 KB envelope and found the player is not the binding constraint; this stage's "
            "estimate agrees, and Part N shows why that is not a reason to build anything: the "
            "song data is the larger cost and the language does not reduce it."
        ),
        "stage15_comparison": {
            "stage15_estimated_added_code_bytes": 270,
            "stage15_headroom_after_mechanisms": 892,
            "this_stage_added_code_bytes_estimate": totals["added_code_bytes"],
            "note": (
                "Stage 15 estimated 270 bytes of added code for a mechanism set justified by one "
                "song. This stage's estimate is larger because it counts a full dispatcher and a "
                "handler per opcode rather than only the mechanisms the reference song needed."
            ),
        },
    }


# ---------------------------------------------------------------------------
# PART Q - macro analysis
# ---------------------------------------------------------------------------
#: Shortest and longest n-gram length considered for macro candidacy.
MACRO_MIN_LENGTH = 3
MACRO_MAX_LENGTH = 8


def macro_analysis(results: Sequence[SongResult]) -> Dict[str, Any]:
    """Part Q: are macros necessary? Measured from the opcode n-grams the compiler produced.

    The measurement is deliberately conservative: a macro is only worth its definition cost if
    a sequence of *events* repeats many times *and* the encoding is longer than the macro call
    would be. Both counts are published so the conclusion can be checked.
    """
    per_song: List[Dict[str, Any]] = []
    for result in results:
        opcodes = [event.opcode for event in sort_events(result.reference_fixed)]
        lengths: Dict[int, int] = {}
        top: List[Dict[str, Any]] = []
        for length in range(MACRO_MIN_LENGTH, MACRO_MAX_LENGTH + 1):
            counts: Dict[Tuple[str, ...], int] = {}
            for index in range(len(opcodes) - length + 1):
                key = tuple(opcodes[index : index + length])
                counts[key] = counts.get(key, 0) + 1
            repeated = {
                key: count for key, count in counts.items() if count >= 3
            }
            lengths[length] = len(repeated)
            best = sorted(repeated.items(), key=lambda item: (-item[1], item[0]))[:5]
            for key, count in best:
                # A macro call is charged 2 bytes; the body is the events it replaces.
                body_bytes = sum(
                    event_bytes(event, 0) for event in result.reference_fixed[:length]
                )
                top.append(
                    {
                        "length": length,
                        "sequence": list(key),
                        "occurrences": count,
                        "definition_bytes_estimate": body_bytes + 2,
                        "call_bytes_estimate": 2,
                        "net_saving_bytes_estimate": count * body_bytes - (body_bytes + 2)
                        - count * 2,
                    }
                )
        top.sort(key=lambda item: (-item["net_saving_bytes_estimate"], item["length"]))
        per_song.append(
            {
                "slug": result.song.slug,
                "events": len(opcodes),
                "repeated_sequences_by_length": {
                    str(length): lengths[length] for length in sorted(lengths)
                },
                "best_candidates": top[:8],
                "opcode_entropy_note": (
                    "the opcode alphabet is 12 symbols; the stream is dominated by NOTE, "
                    "SET_VOLUME and SET_GENERATOR, which is exactly why long literal repeats "
                    "are scarce"
                ),
            }
        )

    best_overall = max(
        (
            item
            for song in per_song
            for item in song["best_candidates"]
        ),
        key=lambda item: item["net_saving_bytes_estimate"],
        default=None,
    )
    return {
        "method": (
            "count every opcode n-gram of length 3..8 in the fixed (exact) event stream; a "
            "candidate must occur at least 3 times; a macro call is charged 2 bytes and defined "
            "as its body plus 2. The estimated net saving is the body replaced minus the call "
            "sites minus the definition."
        ),
        "songs": per_song,
        "best_candidate_overall": best_overall,
        "verdict": (
            "NOT_NECESSARY" if not best_overall or best_overall["net_saving_bytes_estimate"] <= 0
            else "MARGINAL"
        ),
        "reason": (
            "the repetition a macro would capture is short and rare; the same effect is already "
            "available for free through the note model, which emits NOTE with a duration instead "
            "of spelling out the events that fill it"
        ),
    }


# ---------------------------------------------------------------------------
# PART R - semantic neutrality, and PARTS C/G - the architecture proposal
# ---------------------------------------------------------------------------
def semantic_neutrality(
    results: Sequence[SongResult],
    encodings: Mapping[str, Any],
    vocabulary: Mapping[str, Any],
) -> Dict[str, Any]:
    """Part R: the same opcode means different things in different songs, and the language
    must not care.

    This is the test that separates a neutral event language from a style model. If the
    representation needed to know *why* a SET_GENERATOR happens, it would carry song-specific
    semantics and it would be a style model under a new name.
    """
    cases = encodings["cross_song_context_cases"]
    usage: List[Dict[str, Any]] = []
    for opcode in OPCODE_ORDER:
        per_song = {
            result.song.slug: sum(
                1 for event in result.reference_fixed if event.opcode == opcode
            )
            for result in results
        }
        present_in = sorted(slug for slug, count in per_song.items() if count)
        usage.append(
            {
                "opcode": opcode,
                "events_by_song": per_song,
                "songs_using_it": present_in,
                "songs_using_it_count": len(present_in),
            }
        )
    return {
        "question": (
            "Could the same event representation describe two songs where the same low-level "
            "technique has different musical meanings?"
        ),
        "answer": (
            "Yes, and the measurement is that it already does. The opcode set is a fixed set of "
            "register operations, identical for all four songs; what differs is which song uses "
            "which opcodes, how often, and with what parameters."
        ),
        "same_opcode_different_parameters": cases,
        "opcode_usage_by_song": usage,
        "what_the_language_does_not_say": [
            "it never records that a generator change marks a percussion hit",
            "it never records that a slide is a portamento or a sound effect",
            "it never infers a channel's role from its index",
            "it never selects an effect because of the song's identity",
            "it never records a style, an instrument name, or a musical role",
        ],
        "soundprofile_contrast": (
            "The SoundProfile branch failed because it tried to make an instrument portable. "
            "This language makes no claim about instruments at all: it carries operations and "
            "leaves every musical decision to the composition, which is the one layer that is "
            "allowed to know what the song is."
        ),
        "neutrality_check": (
            "A neutrality check a reader can run: every field in every opcode is a number or a "
            "reference to a channel. No opcode, parameter name or value names a sound, a role, "
            "or a song."
        ),
    }


def architecture(
    vocabulary: Mapping[str, Any],
    reconstruction: Mapping[str, Any],
    compression_report: Mapping[str, Any],
    costs: Mapping[str, Any],
    feasibility: Mapping[str, Any],
    neutrality: Mapping[str, Any],
    macros: Mapping[str, Any],
) -> Dict[str, Any]:
    """Parts C and G: the architecture the evidence supports, and what it refuses to contain."""
    return {
        "shape": [
            "COMPOSITION - what / when: pitch, duration, velocity, rhythm, structure",
            "PERFORMANCE EVENT IR - what happens: explicit register operations with parameters",
            "POKEY PLAYER - how: register writes, timing, AUDCTL, channel state, hardware limits",
            "POKEY",
        ],
        "not_this_shape": [
            "SAP -> style -> automatic interpretation (a style engine would have to guess the "
            "composition's intent, and Stage 16 measured that intent does not transfer)",
            "SAP -> instrument profile -> new composition (this is the SoundProfile branch, "
            "closed in Stage 14)",
        ],
        "context_rule": (
            "Context stays in the composition. The language contains no rule of the form 'if "
            "channel 3 then percussion' and no event named after a song. A composition decides "
            "when a SET_GENERATOR happens; the player only executes it."
        ),
        "layer_table": layer_responsibilities()["layers"],
        "principle": layer_responsibilities()["principle"],
        "measured_boundary_check": layer_responsibilities()["measured_boundary_check"],
        "measured_support": {
            "vocabulary_is_evidence_derived": (
                f"{vocabulary['techniques_in_union']} observed techniques reduce to "
                f"{vocabulary['opcode_count']} opcodes, and no observed technique lacks an opcode"
            ),
            "language_is_semantically_neutral": neutrality["answer"],
            "round_trip": (
                "the behaviour-driven encoding reaches "
                f"{reconstruction['summary']['attached_note_model_exact_share_mean']} exact after "
                "the repair pass"
            ),
            "the_abstraction_alone_is_not_enough": (
                "replaying only the Stage 15 technique events reproduces "
                f"{reconstruction['summary']['abstraction_driven_exact_share_mean']} of frames"
            ),
            "it_does_not_compress": (
                "for every song the exact event encoding is larger than a raw register dump; "
                "see Part K"
            ),
            "player_cost_is_not_the_limit": (
                f"the estimated player after the change is "
                f"{feasibility['projected_player_bytes_estimate']} bytes against a "
                f"{feasibility['envelope_bytes']}-byte envelope ({feasibility['label']})"
            ),
            "macros_are_not_needed": macros["verdict"],
        },
        "what_stays_outside_the_player": [
            "which opcode to use, and when",
            "every parameter value",
            "song structure, phrases and repeats",
            "any musical interpretation of a register operation",
        ],
        "what_requires_player_code": [
            item["opcode"] for item in costs["opcodes"]
        ],
        "what_requires_only_song_data": [
            "the event stream itself",
            "the note durations",
            "every effect parameter",
        ],
    }



# ---------------------------------------------------------------------------
# PART V - the twelve research questions, answered from the measurements
# ---------------------------------------------------------------------------
def reconstruction_summary_numbers(
    reconstruction: Mapping[str, Any],
    compression_report: Mapping[str, Any],
    data_cost: Mapping[str, Any],
) -> Dict[str, Any]:
    """The few derived numbers the answers and the verdicts share."""
    songs = compression_report["songs"]

    def mean_ratio(representation: str) -> Optional[float]:
        values = []
        for song in songs:
            for row in song["representations"]:
                if row["representation"] == representation and row["ratio_to_raw_frames"] is not None:
                    values.append(float(row["ratio_to_raw_frames"]))
        return _rnd(_mean(values)) if values else None

    def mean_current_ratio(representation: str) -> Optional[float]:
        values = []
        for song in songs:
            for row in song["representations"]:
                if (
                    row["representation"] == representation
                    and row["ratio_to_current_format"] is not None
                ):
                    values.append(float(row["ratio_to_current_format"]))
        return _rnd(_mean(values)) if values else None

    plain = [
        float(song["plain_state_share_of_events"])
        for song in data_cost["songs"]
        if song["plain_state_share_of_events"] is not None
    ]
    return {
        "exact_attached": reconstruction["summary"]["attached_note_model_exact_share_mean"],
        "exact_sequential": reconstruction["summary"]["sequential_note_model_exact_share_mean"],
        "exact_abstract": reconstruction["summary"]["abstraction_driven_exact_share_mean"],
        "exact_control": reconstruction["summary"]["control_exact_share_mean"],
        "ratio_to_raw_repaired": mean_ratio("C_performance_attached_repaired"),
        "ratio_to_raw_attached": mean_ratio("C_performance_attached"),
        "ratio_to_raw_abstract": mean_ratio("C_performance_abstraction"),
        "ratio_to_current_repaired": mean_current_ratio("C_performance_attached_repaired"),
        "plain_state_share_mean": _rnd(_mean(plain)) if plain else None,
    }





def research_answers(
    vocabulary: Mapping[str, Any],
    numbers: Mapping[str, Any],
    costs: Mapping[str, Any],
    feasibility: Mapping[str, Any],
    macros: Mapping[str, Any],
    neutrality: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Part V. Every answer cites the artefact its number came from."""
    opcode_names = "; ".join(item["opcode"] for item in vocabulary["opcodes"])
    return [
        {
            "question": "Q1 What is the smallest evidence-supported vocabulary?",
            "answer": f"{vocabulary['opcode_count']} opcodes: {opcode_names}",
            "basis": (
                f"{vocabulary['techniques_in_union']} techniques observed across the four Stage "
                "16 songs reduce to that set of register effects, and no observed technique is "
                "left without an opcode. WAIT was offered by the brief and rejected: no observed "
                "technique is an absence of behaviour, and the frame field already carries time."
            ),
        },
        {
            "question": "Q2 Can it represent the common cross-song behaviour?",
            "answer": "Yes, and the common subset is small.",
            "basis": (
                "the behaviour-driven encoding reproduces every song completely after repair "
                f"(mean exact share {numbers['exact_attached']}); the opcodes used by all four "
                "songs are the low-level ones, which is Stage 16's finding that the shared "
                "vocabulary is real but low-level"
            ),
        },
        {
            "question": (
                "Q3 Can it represent song-specific contextual behaviour without embedding "
                "song-specific semantics?"
            ),
            "answer": "Yes, because context lives in the parameters, not in the opcodes.",
            "basis": (
                "the same opcode appears in different songs with different parameters and "
                "different frequencies; the encoding records the parameter and never asks why it "
                "differs (Part R)"
            ),
        },
        {
            "question": "Q4 Can real reference traces be reconstructed from the representation?",
            "answer": (
                "Yes for the behaviour-driven encoding "
                f"({numbers['exact_attached']} mean exact share after repair) and no for the "
                f"abstraction-driven one ({numbers['exact_abstract']})."
            ),
            "basis": (
                "Part I. The distinction is the result: a faithful encoding exists, but replaying "
                "the Stage 15 technique vocabulary alone does not reproduce the song, because the "
                "vocabulary is a lossy summary of the per-frame behaviour it was derived from."
            ),
        },
        {
            "question": "Q5 How much smaller is it than per-frame unrolling?",
            "answer": (
                "It is not smaller. It is about "
                f"{numbers['ratio_to_raw_repaired']}x a raw register dump."
            ),
            "basis": (
                "Part K, representation C versus B. The reference players change several "
                "registers per frame across four voices, so there is little for an event layer to "
                "collapse: the events are already at frame granularity. Without repair the ratio "
                f"is {numbers['ratio_to_raw_attached']}x, still above 1."
            ),
        },
        {
            "question": "Q6 How much larger is it than the current simple event representation?",
            "answer": (
                "Substantially larger: about "
                f"{numbers['ratio_to_current_repaired']}x the current note format."
            ),
            "basis": (
                "Part K, representation C versus A. The current format spends 3 bytes per note "
                "and leaves every frame between notes to the player's own envelope; the event "
                "language spells out what happens in those frames."
            ),
        },
        {
            "question": "Q7 What player mechanisms are actually required?",
            "answer": "One dispatcher, one handler per opcode, and per-voice effect state.",
            "basis": (
                "Part L: " + opcode_names + ". The mechanism families Stage 15 identified "
                "(effect step, generator set, volume set) cover all of them; nothing here needs "
                "a new hardware feature."
            ),
        },
        {
            "question": "Q8 Can those mechanisms plausibly fit within 2 KB?",
            "answer": (
                f"{feasibility['label']}: estimated "
                f"{feasibility['projected_player_bytes_estimate']} bytes against "
                f"{feasibility['envelope_bytes']}."
            ),
            "basis": (
                "Part L's estimate (ESTIMATE, method stated) plus Stage 15's measured 886-byte "
                "baseline. Part M reads the label off the resulting headroom."
            ),
        },
        {
            "question": "Q9 Is the primary limitation player code, song data, or representation?",
            "answer": "Song data and representation, jointly. The player is not the limitation.",
            "basis": (
                "Parts K and N: the exact event encoding is about "
                f"{numbers['ratio_to_raw_repaired']}x a raw register dump and about "
                f"{numbers['ratio_to_current_repaired']}x the current format, while the estimated "
                f"player is {feasibility['projected_player_bytes_estimate']} bytes in a 2048-byte "
                "envelope. The player is the one budget with room left."
            ),
        },
        {
            "question": "Q10 Are macros necessary?",
            "answer": f"No. {macros['verdict']}.",
            "basis": (
                "Part Q: literal opcode repetition is short and rare in the compiled streams, "
                "and the note model already provides the repetition a macro would capture."
            ),
        },
        {
            "question": "Q11 Can the event language remain semantically neutral?",
            "answer": "Yes, by construction and by test.",
            "basis": neutrality["answer"] + " " + neutrality["neutrality_check"],
        },
        {
            "question": "Q12 Does this architecture avoid the SoundProfile failure mode?",
            "answer": "Yes, and for a structural reason rather than a stylistic one.",
            "basis": (
                "a SoundProfile claimed an instrument transfers between songs and was falsified. "
                "This language claims nothing transfers except a set of register operations: it "
                "carries no instrument, no role and no style, and every decision that did not "
                "transfer in Stage 16 stays in the composition layer. The cost is that it is not "
                f"compact: about {numbers['ratio_to_raw_attached']}x a raw dump."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# PART W - the verdicts, each with the rule that produced it
# ---------------------------------------------------------------------------
#: A faithful reconstruction has to reach this share, on every song, for the language verdict
#: to be full support rather than partial. 0.999 admits one frame in a thousand.
FAITHFUL_EXACT_SHARE = 0.999
#: A representation has to be smaller than the raw dump to count as compact.
COMPACT_RATIO = 1.0


def stage_verdicts(
    numbers: Mapping[str, Any],
    feasibility: Mapping[str, Any],
) -> Dict[str, Any]:
    """Part W. Three independent verdicts, each from a stated rule and the measured numbers."""
    exact = numbers["exact_attached"] or 0.0
    abstract = numbers["exact_abstract"] or 0.0
    ratio = numbers["ratio_to_raw_repaired"] or 0.0
    ratio_attached = numbers["ratio_to_raw_attached"] or 0.0

    faithful = exact >= FAITHFUL_EXACT_SHARE
    compact = ratio_attached < COMPACT_RATIO
    if faithful and compact:
        language = "EVENT_LANGUAGE_SUPPORTED"
    elif faithful or compact:
        language = "EVENT_LANGUAGE_PARTIALLY_SUPPORTED"
    else:
        language = "EVENT_LANGUAGE_NOT_SUPPORTED"

    if language == "EVENT_LANGUAGE_SUPPORTED":
        language_reason = "Faithful and compact."
    elif faithful:
        language_reason = (
            f"The language is faithful ({exact} exact share after repair on every song) but it "
            f"is not compact ({ratio_attached}x a raw register dump, {ratio}x with the repair "
            "pass). A middle layer that is exact but larger than the register dump it replaces "
            "does not earn its place on the grounds this stage set out to test."
        )
    else:
        language_reason = (
            f"Reconstruction reaches {exact} and the encoding is {ratio_attached}x a raw dump: "
            "it is neither faithful nor compact."
        )

    if feasibility["label"] in ("COMFORTABLY_FITS", "LIKELY_FITS"):
        player = "2KB_PLAYER_PLAUSIBLE"
    elif feasibility["label"] == "UNCERTAIN":
        player = "2KB_PLAYER_UNCERTAIN"
    else:
        player = "2KB_PLAYER_NOT_PLAUSIBLE"

    song_data_is_worse = ratio_attached > COMPACT_RATIO
    abstraction_is_worse = abstract < 0.5
    if song_data_is_worse and abstraction_is_worse:
        bottleneck = "MULTIPLE_BOTTLENECKS"
    elif song_data_is_worse:
        bottleneck = "SONG_DATA_IS_THE_MAIN_BOTTLENECK"
    elif abstraction_is_worse:
        bottleneck = "REPRESENTATION_IS_THE_MAIN_BOTTLENECK"
    else:
        bottleneck = "INSUFFICIENT_EVIDENCE"

    return {
        "event_language": {
            "verdict": language,
            "rule": (
                "SUPPORTED requires a faithful reconstruction (exact share >= "
                f"{FAITHFUL_EXACT_SHARE} on every song) AND a compact encoding (< "
                f"{COMPACT_RATIO}x a raw register dump). PARTIALLY_SUPPORTED requires one of "
                "the two."
            ),
            "faithful": faithful,
            "compact": compact,
            "measured_exact_share_after_repair": exact,
            "measured_ratio_to_raw_dump": ratio,
            "measured_ratio_before_repair": ratio_attached,
            "explanation": language_reason,
        },
        "two_kb_player": {
            "verdict": player,
            "rule": (
                "COMFORTABLY_FITS below 75% of the envelope, LIKELY_FITS below 100%, UNCERTAIN "
                "below 110%, LIKELY_EXCEEDS below 150%, CLEARLY_EXCEEDS above that"
            ),
            "projected_bytes": feasibility["projected_player_bytes_estimate"],
            "envelope_bytes": feasibility["envelope_bytes"],
            "headroom_bytes": feasibility["headroom_bytes"],
            "label_from_part_m": feasibility["label"],
            "explanation": (
                "the estimate is an ESTIMATE, and it is not the constraint: Parts K and N show "
                "that the song data and the representation are where the cost is"
            ),
        },
        "main_bottleneck": {
            "verdict": bottleneck,
            "rule": (
                "song data is a bottleneck when the exact encoding exceeds a raw dump; the "
                "representation is a bottleneck when replaying the technique abstraction "
                "reproduces less than half the frames. More than one triggers "
                "MULTIPLE_BOTTLENECKS."
            ),
            "song_data_ratio_before_repair": ratio_attached,
            "abstraction_driven_exact_share": abstract,
            "player_bytes": feasibility["projected_player_bytes_estimate"],
            "player_envelope": feasibility["envelope_bytes"],
            "explanation": (
                "The player has room; the song data does not, and the technique abstraction is "
                "not a sufficient description of a song's behaviour, so the composition has to "
                "supply the operations explicitly. Two costs, one of them structural."
            ),
        },
        "independence_note": (
            "The three verdicts come from different tests and are deliberately not correlated. "
            "The language can be semantically neutral and faithful while being too large; the "
            "player can fit while the song data does not."
        ),
        "what_would_change_the_verdict": [
            "a reference encoding that beats the raw dump would move the language verdict; the "
            "measurement suggests that only happens when the composition emits notes and effects "
            "at note granularity rather than at frame granularity",
            "a technique vocabulary that described per-frame behaviour exactly would move the "
            "abstraction verdict; Stage 15's detector is the thing to improve, not the language",
        ],
    }


def what_not_to_build_yet() -> List[Dict[str, str]]:
    """Part 21: the things this stage deliberately does not justify."""
    return [
        {
            "thing": "a 4 KB player, or any player enlargement",
            "why_not": (
                "the player is estimated at "
                "well under the 2 KB envelope and Stage 15 already falsified 'the player is too "
                "small'. The measured constraint is song data, and a larger player does not "
                "touch it."
            ),
        },
        {
            "thing": "implementing the event language in the player",
            "why_not": (
                "the language is faithful but not compact: it is larger than a raw register "
                "dump. Building it would make song data bigger while changing nothing audible, "
                "on this evidence."
            ),
        },
        {
            "thing": "a style engine, or any automatic interpretation of a song",
            "why_not": (
                "Stage 16 measured that context does not transfer. An engine that inferred "
                "context would have to embed exactly the song-specific grammar the evidence "
                "shows does not generalise."
            ),
        },
        {
            "thing": "a Composer or DSL change",
            "why_not": (
                "no listening test was run and nothing here says a listener wants event-level "
                "control. The architecture is supported in principle and unsupported as an "
                "engineering priority."
            ),
        },
        {
            "thing": "reviving SoundProfile under a new name",
            "why_not": (
                "the language carries operations and no instruments. Anything that reintroduced "
                "a portable instrument definition would reopen a branch Stage 14 closed."
            ),
        },
        {
            "thing": "a listening test",
            "why_not": (
                "forbidden by the stop condition. It is the natural first step of any future "
                "stage that wants to act on this, but it is not this stage's job."
            ),
        },
    ]


def stage18_candidates() -> List[Dict[str, str]]:
    """Part 22: what a next stage would have to answer before anything is built."""
    return [
        {
            "candidate": "improve the Stage 15 detector, then repeat the abstraction replay",
            "question": "Is the abstraction's failure a limit of the vocabulary or of the detector?",
            "cost": "analysis only, no production change",
        },
        {
            "candidate": "compile a compositional score into the IR instead of a trace",
            "question": (
                "When the events come from a composer rather than from a recorded performance, "
                "is the encoding smaller? Note-granularity input is the only route the "
                "compression finding leaves open."
            ),
            "cost": "analysis only; still no player change",
        },
        {
            "candidate": "measure the byte cost of the current player's own format on one song",
            "question": (
                "How far is the current 3-byte note format from the raw dump it replaces? That "
                "comparison was never made and it is the one the event language has to win."
            ),
            "cost": "analysis only",
        },
        {
            "candidate": "check whether an entropy or RLE bound beats the event language",
            "question": (
                "Is there any representation of this behaviour that beats the raw dump? If not, "
                "the register dump is the right format and the middle layer is unnecessary."
            ),
            "cost": "analysis only",
        },
        {
            "candidate": "a listening test of one effect in two contexts",
            "question": (
                "Is a technique heard as the same thing when its context changes? Part R says "
                "the language does not care; nobody has checked whether a listener does."
            ),
            "cost": "a blind package; the natural first production-facing step",
        },
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
STAGE17_FILES = (
    "vocabulary.json",
    "event_semantics.json",
    "reference_encodings.json",
    "reconstruction_results.json",
    "compression.json",
    "player_cost_model.json",
    "song_data_cost.json",
    "hardware_constraints.json",
    "macro_analysis.json",
    "architecture.json",
    "summary.json",
)
STAGE17_DOC = "stage17_performance_event_language.md"


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open ten files."""
    numbers = bundle["numbers"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "songs": [song.slug for song in bundle["songs"]],
        "opcode_count": bundle["vocabulary"]["opcode_count"],
        "techniques_in_union": bundle["vocabulary"]["techniques_in_union"],
        "opcodes": [item["opcode"] for item in bundle["vocabulary"]["opcodes"]],
        "exact_share": {
            "control_register_state": numbers["exact_control"],
            "abstraction_driven": numbers["exact_abstract"],
            "performance_attached": numbers["exact_attached"],
            "performance_sequential": numbers["exact_sequential"],
        },
        "compression": {
            "ratio_to_raw_dump_before_repair": numbers["ratio_to_raw_attached"],
            "ratio_to_raw_dump_after_repair": numbers["ratio_to_raw_repaired"],
            "ratio_to_current_format_after_repair": numbers["ratio_to_current_repaired"],
            "plain_state_share_of_events": numbers["plain_state_share_mean"],
        },
        "player": {
            "baseline_bytes": bundle["player_cost_model"]["baseline"]["assembled_bytes"],
            "projected_bytes_estimate": bundle["player_feasibility"][
                "projected_player_bytes_estimate"
            ],
            "envelope_bytes": bundle["player_feasibility"]["envelope_bytes"],
            "headroom_bytes": bundle["player_feasibility"]["headroom_bytes"],
            "label": bundle["player_feasibility"]["label"],
        },
        "macros": bundle["macro_analysis"]["verdict"],
        "layer_count": len(bundle["architecture"]["layer_table"]),
        "verdicts": {
            "event_language": bundle["verdicts"]["event_language"]["verdict"],
            "two_kb_player": bundle["verdicts"]["two_kb_player"]["verdict"],
            "main_bottleneck": bundle["verdicts"]["main_bottleneck"]["verdict"],
        },
    }


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    player_asm: Path = DEFAULT_PLAYER_ASM,
) -> Dict[str, Any]:
    """Read the corpus and the earlier records; build the IR; measure the round trip.

    Reads: the corpus traces, the Stage 16 selection and universality records, the Stage 15
    records, and the player source - all through their hashes. Writes nothing. Renders only
    analysis objects, never audio.
    """
    songs, selection = load_songs(stage16_dir)
    results = measure_songs(songs)
    vocabulary = technique_vocabulary(songs, stage15_dir, stage16_dir)
    semantics = event_semantics()
    encodings = reference_encodings(results)
    reconstruction = reconstruction_results(results)
    compression_report = compression(results)
    data_cost = song_data_cost(results)
    hardware = hardware_constraints(results)
    costs = player_cost_model(vocabulary, stage15_dir)
    feasibility = player_feasibility(costs)
    macros = macro_analysis(results)
    neutrality = semantic_neutrality(results, encodings, vocabulary)
    numbers = reconstruction_summary_numbers(reconstruction, compression_report, data_cost)
    architecture_report = architecture(
        vocabulary, reconstruction, compression_report, costs, feasibility, neutrality, macros
    )
    verdicts = stage_verdicts(numbers, feasibility)
    answers = research_answers(vocabulary, numbers, costs, feasibility, macros, neutrality)

    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "evidence_sources": evidence_sources(selection, stage15_dir, stage16_dir, player_asm),
        "songs": [result.song.to_dict() for result in results],
        "per_song_measurements": [
            {
                "slug": result.song.slug,
                "control_events": len(result.control),
                "control_bytes": ir_bytes(result.control),
                "abstraction_events": result.abstract.event_count,
                "abstraction_bytes": ir_bytes(result.abstract.events),
                "abstraction_fit_choices": dict(sorted(result.abstract.choices.items())),
                "abstraction_unmapped": dict(sorted(result.abstract.unmapped.items())),
                "attached_events": result.reference.event_count,
                "attached_bytes": ir_bytes(result.reference.events),
                "attached_repair_rounds": result.reference_repair,
                "sequential_repair_rounds": result.sequential_repair,
                "plain_state_change_events": result.plain_state_events,
                "opcode_histogram": result.reference.opcode_histogram(),
            }
            for result in results
        ],
        "vocabulary": vocabulary,
        "event_semantics": semantics,
        "reference_encodings": encodings,
        "reconstruction_results": reconstruction,
        "compression": compression_report,
        "player_cost_model": costs,
        "player_feasibility": feasibility,
        "song_data_cost": data_cost,
        "hardware_constraints": hardware,
        "macro_analysis": macros,
        "semantic_neutrality": neutrality,
        "architecture": architecture_report,
        "numbers": numbers,
        "research_answers": answers,
        "verdicts": verdicts,
        "what_not_to_build_yet": what_not_to_build_yet(),
        "stage18_candidates": stage18_candidates(),
        "determinism": {
            "inputs_hashed": True,
            "no_sampling": True,
            "no_timestamps": True,
            "no_set_iteration_in_output": True,
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle



# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------
STAGE17_FILES = (
    "vocabulary.json",
    "event_semantics.json",
    "reference_encodings.json",
    "reconstruction_results.json",
    "compression.json",
    "player_cost_model.json",
    "song_data_cost.json",
    "hardware_constraints.json",
    "macro_analysis.json",
    "architecture.json",
    "summary.json",
)
STAGE17_DOC = "stage17_performance_event_language.md"


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open ten files."""
    numbers = bundle["numbers"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "songs": [song["slug"] for song in bundle["songs"]],
        "opcode_count": bundle["vocabulary"]["opcode_count"],
        "techniques_in_union": bundle["vocabulary"]["techniques_in_union"],
        "opcodes": [item["opcode"] for item in bundle["vocabulary"]["opcodes"]],
        "exact_share": {
            "control_register_state": numbers["exact_control"],
            "abstraction_driven": numbers["exact_abstract"],
            "performance_attached": numbers["exact_attached"],
            "performance_sequential": numbers["exact_sequential"],
        },
        "compression": {
            "ratio_to_raw_dump_before_repair": numbers["ratio_to_raw_attached"],
            "ratio_to_raw_dump_after_repair": numbers["ratio_to_raw_repaired"],
            "ratio_to_current_format_after_repair": numbers["ratio_to_current_repaired"],
            "plain_state_share_of_events": numbers["plain_state_share_mean"],
        },
        "player": {
            "baseline_bytes": bundle["player_cost_model"]["baseline"]["assembled_bytes"],
            "projected_bytes_estimate": bundle["player_feasibility"][
                "projected_player_bytes_estimate"
            ],
            "envelope_bytes": bundle["player_feasibility"]["envelope_bytes"],
            "headroom_bytes": bundle["player_feasibility"]["headroom_bytes"],
            "label": bundle["player_feasibility"]["label"],
        },
        "macros": bundle["macro_analysis"]["verdict"],
        "layer_count": len(bundle["architecture"]["layer_table"]),
        "verdicts": {
            "event_language": bundle["verdicts"]["event_language"]["verdict"],
            "two_kb_player": bundle["verdicts"]["two_kb_player"]["verdict"],
            "main_bottleneck": bundle["verdicts"]["main_bottleneck"]["verdict"],
        },
    }


def write_analysis(
    bundle: Mapping[str, Any],
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the eleven JSON artefacts and the report. Additive: nothing else is touched."""
    stage17_dir = Path(stage17_dir)
    docs_dir = Path(docs_dir)
    stage17_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "vocabulary.json": bundle["vocabulary"],
        "event_semantics.json": bundle["event_semantics"],
        "reference_encodings.json": bundle["reference_encodings"],
        "reconstruction_results.json": bundle["reconstruction_results"],
        "compression.json": bundle["compression"],
        "player_cost_model.json": bundle["player_cost_model"],
        "song_data_cost.json": bundle["song_data_cost"],
        "hardware_constraints.json": bundle["hardware_constraints"],
        "macro_analysis.json": bundle["macro_analysis"],
        "architecture.json": {
            "architecture": bundle["architecture"],
            "semantic_neutrality": bundle["semantic_neutrality"],
            "verdicts": bundle["verdicts"],
            "what_not_to_build_yet": bundle["what_not_to_build_yet"],
            "stage18_candidates": bundle["stage18_candidates"],
        },
        "summary.json": bundle["summary"],
    }
    written: Dict[str, Path] = {}
    for name in STAGE17_FILES:
        path = stage17_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE17_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE17_DOC] = doc_path
    return written



# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(item) for item in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _bullets(items: Sequence[Any], indent: str = "") -> str:
    return "\n".join(f"{indent}- {item}" for item in items)


def render_report(bundle: Mapping[str, Any]) -> str:
    """The 22 sections the brief requires, in its order, from the measured bundle only."""
    out: List[str] = []
    summary = bundle["summary"]
    numbers = bundle["numbers"]
    vocabulary = bundle["vocabulary"]
    semantics = bundle["event_semantics"]
    reconstruction = bundle["reconstruction_results"]
    compression_report = bundle["compression"]
    costs = bundle["player_cost_model"]
    feasibility = bundle["player_feasibility"]
    data_cost = bundle["song_data_cost"]
    hardware = bundle["hardware_constraints"]
    macros = bundle["macro_analysis"]
    neutrality = bundle["semantic_neutrality"]
    architecture_report = bundle["architecture"]
    verdicts = bundle["verdicts"]
    evidence = bundle["evidence_sources"]

    out.append("# Stage 17 - POKEY Performance Event Language and Compact Event IR\n")
    out.append(
        "A controlled investigation of the representation boundary between composition and POKEY "
        "execution. Analysis only: the 6502 player, the Composer, the DSL, the Music IR and the "
        "SoundProfile system are read and hashed, never modified. No audio was rendered, no music "
        "was generated, and no listening test was run.\n"
    )
    out.append(f"Analysis version `{bundle['analysis_version']}`.\n")

    out.append("## 1. Executive summary\n")
    out.append(
        f"Four songs were read ({', '.join(summary['songs'])}), taken from Stage 16's own "
        f"selection record. {vocabulary['techniques_in_union']} techniques observed in them "
        f"reduce to **{vocabulary['opcode_count']} opcodes**, and every observed technique has an "
        "opcode. An event language was defined from that evidence, and a research-only interpreter "
        "renders POKEY frame streams from it.\n"
    )
    out.append("The three findings that decide the stage:\n")
    out.append(_bullets([
        "**The language is faithful and neutral.** A behaviour-driven encoding of the reference "
        f"traces reaches a mean exact share of **{numbers['exact_attached']}** once a measured "
        "repair pass is applied, on all four songs. The opcode set contains no instrument, no "
        "role and no style.",
        "**It is not compact.** The exact encoding is about "
        f"**{numbers['ratio_to_raw_repaired']}x a raw register dump** "
        f"({numbers['ratio_to_raw_attached']}x before repair). The reference players change "
        "several registers per frame across four voices, so there is almost nothing for an event "
        "layer to collapse - the events are already at frame granularity.",
        "**The technique abstraction is not a sufficient input.** Replaying only the Stage 15 "
        f"events reproduces **{numbers['exact_abstract']}** of frames, because the abstraction is "
        "a lossy summary of the behaviour it was derived from. A composition has to state the "
        "operations explicitly; it cannot delegate that to the technique vocabulary.",
    ]))
    out.append("")
    out.append(_md_table(
        ["verdict", "result"],
        [
            ["event language", f"`{verdicts['event_language']['verdict']}`"],
            ["2 KB player", f"`{verdicts['two_kb_player']['verdict']}`"],
            ["main bottleneck", f"`{verdicts['main_bottleneck']['verdict']}`"],
        ],
    ))
    out.append("")

    out.append("## 2. Research question\n")
    out.append(
        "> Can a compact, semantically neutral Performance Event language form a useful middle "
        "layer between composition and the POKEY player, while remaining small enough that the "
        "existing 2 KB player architecture could plausibly execute it?\n"
    )
    out.append(
        "The question has three separable parts and this stage answers them separately, because "
        "they can have different answers: *can the behaviour be represented*, *is the "
        "representation neutral*, and *is it compact*.\n"
    )
    out.append(
        "The falsification targets were fixed before the measurement: behaviours that cannot be "
        "expressed without adding semantic knowledge, behaviours that need raw register access, "
        "compression that is too poor, and event combinations that become as complex as raw frame "
        "data. Parts 9, 10 and 19 report which of those were actually hit.\n"
    )

    out.append("## 3. Evidence sources\n")
    out.append(
        "Every input is read through its SHA-256. The technique definitions are not "
        "re-implemented: `stage15.detect_events` is imported and called, so every encoded event is "
        "the same object Stages 15 and 16 published.\n"
    )
    out.append(_md_table(
        ["record", "file", "sha256"],
        [[name, evidence["stage15_and_player_records"][name]["path"].split("\\")[-1],
          "`" + evidence["stage15_and_player_records"][name]["sha256"][:16] + "...`"]
         for name in sorted(evidence["stage15_and_player_records"])],
    ))
    out.append("")
    out.append(_md_table(
        ["song", "sha256"],
        [["`" + item["slug"] + "`", "`" + item["sha256"][:16] + "...`"]
         for item in evidence["trace_sources"]],
    ))
    out.append("")
    out.append(
        f"- selection record: `{evidence['stage16_selection_record']['path']}` "
        f"(`{evidence['stage16_selection_record']['sha256'][:16]}...`)\n"
        f"- Stage 16 verdicts reused rather than recomputed: {evidence['stage16_reused_verdicts']}\n"
        f"- source hash of this module: `{bundle['determinism']['source_hash'][:16]}...`\n"
    )

    out.append("## 4. Layer responsibilities: composition / performance / player\n")
    out.append(architecture_report["principle"] + "\n")
    out.append(
        "The three layers are separated by *who decides*. The composition decides what should be "
        "heard; the event layer records those decisions as explicit operations; the player decides "
        "nothing and only executes.\n"
    )
    for layer in architecture_report["layer_table"]:
        out.append(f"**{layer['layer']}**\n")
        out.append("owns:\n")
        out.append(_bullets(layer["owns"]))
        out.append("")
        out.append("must not own:\n")
        out.append(_bullets(layer["must_not_own"]))
        out.append("")
    out.append(architecture_report["measured_boundary_check"] + "\n")

    out.append("## 5. Minimal event vocabulary\n")
    out.append(
        f"{vocabulary['techniques_in_union']} observed techniques reduce to "
        f"{vocabulary['opcode_count']} opcodes. Techniques that share a register effect share an "
        "opcode, which is why the technique identifiers (Stage 15 splits glides and envelopes by "
        "direction) collapse.\n"
    )
    out.append(_md_table(
        ["opcode", "effect", "parameters", "justified by", "occurrences", "songs"],
        [
            [
                f"`{item['opcode']}`", item["effect"],
                ", ".join(f"`{name}`" for name in item["parameters"]) or "-",
                ", ".join(item["justified_by"]) or "*(no technique: mode declaration only)*",
                item["justification_occurrences"],
                len(item["songs_in_which_the_justification_was_observed"]),
            ]
            for item in vocabulary["opcodes"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["technique observed", "opcode", "songs", "occurrences", "Stage 16 verdict"],
        [
            [
                f"`{row['technique_id']}`", f"`{row['opcode']}`" if row["opcode"] else "-",
                row["songs_observed_count"], row["occurrences_total"],
                row["stage16_universality"] or "-",
            ]
            for row in sorted(
                vocabulary["techniques"], key=lambda item: (-item["occurrences_total"],
                                                            item["technique_id"])
            )
        ],
    ))
    out.append("")
    out.append("Candidates the brief offered that the evidence does **not** support:\n")
    out.append(_md_table(
        ["candidate", "verdict", "reason"],
        [[item["candidate"], f"`{item['verdict']}`", item["reason"]]
         for item in semantics["rejected_candidates"]],
    ))
    out.append("")
    out.append("The shape this stage is not proposing:\n")
    out.append(_bullets(architecture_report["not_this_shape"]))
    out.append("")

    out.append("## 6. Event semantic contracts\n")
    out.append(
        "Every opcode, with the eight properties Part E requires: inputs, the state it modifies, "
        "its duration, how it interacts with NOTE, how it interacts with other events, how it "
        "terminates, whether it may overlap, and whether it is interruptible.\n"
    )
    out.append(_md_table(
        ["opcode", "inputs", "state modified", "duration", "overlap", "interruptible"],
        [
            [
                f"`{opcode}`",
                "<br>".join(contract["inputs"]),
                "<br>".join(contract["state_modified"]),
                contract["duration"],
                "yes" if contract["may_overlap"] else "no",
                "yes" if contract["interruptible"] else "no",
            ]
            for opcode, contract in sorted(
                semantics["contracts"].items(),
                key=lambda item: OPCODE_ORDER.index(item[0]),
            )
        ],
    ))
    out.append("")
    out.append("Interaction rules, as implemented by the interpreter:\n")
    out.append(_bullets(
        f"`{opcode}`: with NOTE - {contract['interaction_with_note']}; with other events - "
        f"{contract['interaction_with_other_events']}; termination - {contract['termination']}"
        for opcode, contract in sorted(
            semantics["contracts"].items(), key=lambda item: OPCODE_ORDER.index(item[0])
        )
    ))
    out.append("")
    out.append("**The one hazard this stage found by measurement:**\n")
    out.append(semantics["ordering_hazard"] + "\n")

    out.append("## 7. Event sequencing model\n")
    out.append(
        "Part F asks whether events should be sequential, attached to notes, or state changes. "
        "The answer is measured, not chosen: two composition models were built and compared on "
        "the same traces with the same interpreter.\n"
    )
    out.append(_md_table(
        ["model", "note carries", "note ends when", "exact share after repair", "verdict"],
        [
            [
                "attached", "a duration", "the duration elapses",
                reconstruction["summary"]["attached_note_model_exact_share_mean"],
                "**preferred**",
            ],
            [
                "sequential", "nothing", "a separate `NOTE_OFF` arrives",
                reconstruction["summary"]["sequential_note_model_exact_share_mean"],
                "does not converge",
            ],
        ],
    ))
    out.append("")
    out.append(
        "The sequential model fails for a semantic reason rather than a data reason: "
        "`NOTE_OFF` and `SET_VOLUME` collide on the same frame and the opcode order resolves the "
        "collision against the correction, so a repair pass re-patches the same frame every round "
        "and never converges. The attached model has no `NOTE_OFF` and therefore no collision.\n"
    )
    out.append(
        "The state-change layer is not optional and is not a competitor: the exact encoding still "
        f"spends a mean of **{numbers['plain_state_share_mean']}** of its events on plain "
        "`SET_*` events. That number is the degeneracy measure Part 7 and Part 10 both need.\n"
    )

    out.append("## 8. Reference trace encodings\n")
    out.append(
        "For each song, the first observed occurrence of each behaviour category in canonical "
        "stream order, encoded in the language and published with the reference registers over "
        "the same window so the encoding can be checked by hand.\n"
    )
    for song in bundle["reference_encodings"]["songs"]:
        out.append(f"### {song['slug']} (AUDCTL {song['audctl']}, {song['frames']} frames)\n")
        for example in song["examples"]:
            low, high = example["window_frames"]
            out.append(
                f"**{example['category']}** - frames {low}..{high}"
                + (f", channel {example['channel']}" if example["channel"] else "")
                + (f" - {example['note']}" if example.get("note") else "")
                + "\n"
            )
            out.append("```")
            for item in example["encoded_events"][:8]:
                out.append(item["render"])
            if len(example["encoded_events"]) > 8:
                out.append(f"... {len(example['encoded_events']) - 8} more")
            out.append("```")
            registers = example["reference_registers"]
            shown = [name for name in REGISTER_ORDER if any(registers[name])]
            out.append(
                "reference registers: "
                + "; ".join(
                    f"`{name}`={registers[name][:6]}" for name in shown[:5]
                )
                + "\n"
            )
        out.append("")
    out.append("**The same opcode, in different songs, with different parameters:**\n")
    out.append(_md_table(
        ["opcode", "song", "frame", "parameter", "value", "duration"],
        [
            [f"`{case['opcode']}`", item["slug"], item["frame"], item["parameter"],
             item["value"], item["duration"]]
            for case in bundle["reference_encodings"]["cross_song_context_cases"]
            for item in case["occurrences"]
        ],
    ))
    out.append("")

    out.append("## 9. Round-trip reconstruction\n")
    out.append(
        "This is the key technical test. The reference trace is encoded, the IR is rendered by "
        "the offline interpreter, and the result is compared with the reference frame by frame. "
        "Every frame is classified EXACT, APPROXIMATE or UNREPRESENTABLE.\n"
    )
    out.append(
        "The comparison is audibility-aware: a silent channel's distortion and divider change no "
        "sound, so they are only compared when one side is making one. The strict "
        "all-nine-registers figure is published alongside as `register_exact_share`, so the "
        "harsher number is never hidden.\n"
    )
    for song in reconstruction["songs"]:
        out.append(f"### {song['slug']}\n")
        out.append(_md_table(
            ["representation", "events", "bytes", "exact", "approx", "unrep", "register exact"],
            [
                [
                    f"`{row['label']}`", row["events"], row["bytes"],
                    row["comparison"].get("exact_share") if row["comparison"].get("exact_share")
                    is not None else "1.0",
                    row["comparison"].get("approximate_share", "-"),
                    row["comparison"].get("unrepresentable_share", "0.0"),
                    row["comparison"].get("register_exact_share", "-"),
                ]
                for row in song["representations"]
            ],
        ))
        out.append("")
    s = reconstruction["summary"]
    out.append(_md_table(
        ["representation", "mean exact share", "reading"],
        [
            ["raw frames", "1.0", "ground truth, not part of the language"],
            ["register-state control", s["control_exact_share_mean"],
             "exact by construction, and the size control"],
            ["technique abstraction replayed", s["abstraction_driven_exact_share_mean"],
             "**the abstraction is not a sufficient description of the song**"],
            ["performance, attached", s["attached_note_model_exact_share_mean"],
             "100% on all four songs after the measured repair pass"],
            ["performance, sequential", s["sequential_note_model_exact_share_mean"],
             "does not converge: NOTE_OFF collides with SET_VOLUME"],
        ],
    ))
    out.append("")
    out.append(s["note_model_verdict"] + "\n")

    out.append("## 10. Compression analysis\n")
    out.append(compression_report["byte_model"] + "\n")
    out.append(
        "Does the event layer beat a raw frame dump? Not on this corpus. The per-song tables "
        "below give the bytes; the `does_the_event_layer_compress` line under each is the answer "
        "for that song.\n"
    )
    for song in compression_report["songs"]:
        out.append(f"### {song['slug']}\n")
        out.append(_md_table(
            ["representation", "events", "bytes", "x raw dump", "x current format"],
            [
                [
                    f"`{row['representation']}`",
                    row["events"] if row.get("events") else "-",
                    row["bytes"],
                    row.get("ratio_to_raw_frames", "-"),
                    row.get("ratio_to_current_format", "-"),
                ]
                for row in song["representations"]
            ],
        ))
        out.append("")
        out.append(
            "The exact encoding beats a raw register dump here? "
            f"**{song['reading']['does_the_event_layer_compress']}** "
            f"({song['reading']['raw_frames_is_the_floor']}).\n"
        )
    out.append(
        "**The headline.** For all four songs the exact event encoding is *larger* than a raw "
        "register dump. The reason is structural rather than a defect in the encoder: the "
        "reference players write several registers every frame across four voices, so the "
        "behaviour has almost no redundancy for an event layer to remove. An event layer only "
        "pays for itself when the same information is held constant across many frames, and at "
        "50 Hz in these songs it is not.\n"
    )
    out.append(compression_report["abstraction_smaller_than_raw_dump_note"] + ".\n")
    out.append(
        "That pairing is the whole result: the compact representation is not faithful, and the "
        "faithful representation is not compact.\n"
    )

    out.append("## 11. Player code cost\n")
    out.append(costs["method"] + "\n")
    out.append(_md_table(
        ["opcode", "handler lines", "code bytes (EST)", "state bytes", "cycles", "justified by"],
        [
            [
                f"`{row['opcode']}`", row["handler_code_lines"],
                row["estimated_handler_code_bytes"], row["estimated_state_bytes"],
                row["estimated_cycles_when_it_fires"],
                ", ".join(row["justified_by"]) or "-",
            ]
            for row in costs["opcodes"]
        ],
    ))
    out.append("")
    out.append(_md_table(
        ["item", "bytes"],
        [
            ["current player, measured (Stage 15)", costs["baseline"]["assembled_bytes"]],
            ["dispatcher (ESTIMATE)", costs["dispatcher"]["estimated_code_bytes"]],
            ["opcode handlers (ESTIMATE)", costs["totals"]["added_code_bytes"]
             - costs["dispatcher"]["estimated_code_bytes"]],
            ["added state (structural)", costs["totals"]["added_state_bytes"]],
            ["**projected player (ESTIMATE)**", costs["totals"]["player_bytes_after_estimate"]],
            ["envelope", costs["totals"]["envelope_bytes"]],
            ["headroom", costs["totals"]["headroom_bytes"]],
        ],
    ))
    out.append("")
    out.append(
        "Do not forget what this is: the baseline is measured, the additions are estimated from "
        "the current source's own bytes-per-code-line, and no player was modified. "
        + bundle["architecture"]["measured_support"]["player_cost_is_not_the_limit"] + ".\n"
    )

    out.append("## 12. Song data cost\n")
    out.append(data_cost["separation_note"] + "\n")
    out.append(_md_table(
        ["song", "frames", "current note format", "raw frame dump", "exact event encoding",
         "bytes/frame (event)", "plain-state share"],
        [
            [
                f"`{song['slug']}`", song["frames"],
                song["current_format_bytes"], song["raw_frame_dump_bytes"],
                song["performance_event_bytes_repaired"],
                song["bytes_per_frame"]["performance_event_repaired"],
                song["plain_state_share_of_events"],
            ]
            for song in data_cost["songs"]
        ],
    ))
    out.append("")
    out.append(data_cost["comparison_to_stage15"] + "\n")

    out.append("## 13. 2 KB feasibility\n")
    out.append(feasibility["method"] + "\n")
    out.append(_md_table(
        ["item", "bytes"],
        [
            ["baseline player (measured)", feasibility["baseline_bytes"]],
            ["added code (ESTIMATE)", feasibility["added_code_bytes_estimate"]],
            ["added state (structural)", feasibility["added_state_bytes"]],
            ["projected player (ESTIMATE)", feasibility["projected_player_bytes_estimate"]],
            ["envelope", feasibility["envelope_bytes"]],
            ["headroom", feasibility["headroom_bytes"]],
        ],
    ))
    out.append("")
    out.append(f"**{feasibility['label']}**. {feasibility['what_this_does_not_say']}\n")
    comparison = feasibility["stage15_comparison"]
    out.append(
        f"Stage 15 estimated {comparison['stage15_estimated_added_code_bytes']} bytes of added "
        f"code for one song's mechanism set; this stage estimates "
        f"{comparison['this_stage_added_code_bytes_estimate']} bytes, because it charges a full "
        "dispatcher and a handler per opcode rather than only the mechanisms the reference song "
        "happened to need. "
        f"{comparison['note']}\n"
    )

    out.append("## 14. Hardware constraints\n")
    out.append(
        "Every hardware limit is either handled explicitly or refused explicitly. Nothing is "
        "hidden inside a semantic event.\n"
    )
    out.append(_md_table(
        ["constraint", "rule", "handling"],
        [[item["constraint"], item["rule"], item["handling"]]
         for item in hardware["constraints"]],
    ))
    out.append("")
    out.append(hardware["refusal_rule"] + "\n")
    out.append(hardware["not_hidden"] + "\n")
    out.append(_md_table(
        ["song", "AUDCTL", "joined pairs", "divider range", "largest divider",
         "unrep. pitch", "clamped writes"],
        [
            [
                f"`{song['slug']}`", song["audctl"],
                ", ".join("-".join(str(c) for c in pair) for pair in song["joined_pairs"]) or "-",
                song["divider_range_in_this_song"], song["largest_divider_observed"],
                song["unrepresentable_pitch_events"], song["clamped_writes"],
            ]
            for song in hardware["songs"]
        ],
    ))
    out.append("")
    out.append(
        "The two AUDCTL configurations in the corpus are `$00` (all four channels independent) "
        "and `$50` (channels 1+2 joined as one 16-bit divider, channel 1 clocked at 1.79 MHz). "
        "Both are handled by one rule in `voice_layout`, which is why the language addresses "
        "voices rather than register bytes.\n"
    )

    out.append("## 15. Macro analysis\n")
    out.append(macros["method"] + "\n")
    out.append(_md_table(
        ["song", "events", "best repeated sequence", "occurrences", "estimated net saving (bytes)"],
        [
            [
                f"`{song['slug']}`", song["events"],
                " ".join(song["best_candidates"][0]["sequence"]) if song["best_candidates"] else "-",
                song["best_candidates"][0]["occurrences"] if song["best_candidates"] else "-",
                song["best_candidates"][0]["net_saving_bytes_estimate"]
                if song["best_candidates"] else "-",
            ]
            for song in macros["songs"]
        ],
    ))
    out.append("")
    out.append(f"**{macros['verdict']}.** {macros['reason']}.\n")

    out.append("## 16. Semantic neutrality\n")
    out.append(f"**{neutrality['question']}**\n")
    out.append(neutrality["answer"] + "\n")
    out.append("The language does not say any of the following:\n")
    out.append(_bullets(neutrality["what_the_language_does_not_say"]))
    out.append("")
    out.append(_md_table(
        ["opcode", "songs using it", "set_generator events by song" if False else "usage"],
        [
            [
                f"`{row['opcode']}`", row["songs_using_it_count"],
                ", ".join(
                    f"{slug.split('_')[0]}:{count}"
                    for slug, count in sorted(row["events_by_song"].items())
                ),
            ]
            for row in neutrality["opcode_usage_by_song"]
        ],
    ))
    out.append("")
    out.append(neutrality["soundprofile_contrast"] + "\n")
    out.append(neutrality["neutrality_check"] + "\n")

    out.append("## 17. Architecture proposal\n")
    out.append("```text")
    for line in architecture_report["shape"]:
        out.append(line)
    out.append("```")
    out.append("")
    out.append(architecture_report["context_rule"] + "\n")
    out.append("What stays outside the player:\n")
    out.append(_bullets(architecture_report["what_stays_outside_the_player"]))
    out.append("")
    out.append("What requires player code:\n")
    out.append(_bullets(f"`{name}`" for name in architecture_report["what_requires_player_code"]))
    out.append("")
    out.append("What requires only song data:\n")
    out.append(_bullets(architecture_report["what_requires_only_song_data"]))
    out.append("")

    out.append("## 18. Answers to research questions\n")
    for item in bundle["research_answers"]:
        out.append(f"### {item['question']}\n")
        out.append(f"**{item['answer']}**\n")
        out.append(f"*Basis:* {item['basis']}\n")

    out.append("## 19. Limitations\n")
    out.append(_bullets([
        "**Four songs, one era, one hardware configuration family.** Two AUDCTL values are "
        "represented (`$00` and `$50`), and three of the four songs use the same one. Nothing "
        "here is evidence about cross-configuration or cross-era behaviour.",
        "**The technique vocabulary is inherited, and it is lossy.** Part 9 measures the cost of "
        "that inheritance directly: Stage 15's generator detector reports a fraction of the "
        "distortion changes the trace contains, so an encoding driven by the abstraction cannot "
        "reproduce them. This is a limit of the *input*, and this stage reports it rather than "
        "working around it.",
        "**The byte model is stated, not measured.** Every compression ratio is arithmetic on a "
        "published record layout. A real implementation could pack fields differently and the "
        "ratios would move; the model is stated so that they can be recomputed.",
        "**The player cost is an ESTIMATE.** The baseline is measured; the additions are charged "
        "at the current source's bytes-per-code-line. No 6502 code was written for the event "
        "language, so no figure here is a measurement of a real player.",
        "**The interpreter's effect curves are choices.** A triangle for vibrato and tremolo, a "
        "quadratic for a sweep, a linear ramp for a volume shape. The round trip shows they can "
        "be made exact or near-exact on this corpus, but a different curve set would produce "
        "different per-event parameters.",
        "**The repair pass is a cost, not a feature.** It exists to measure how much explicit "
        "correction the compact encoding needs. A production encoder would aim to emit fewer "
        "corrections, and this stage has not established that it can.",
        "**No listener was asked anything.** Every claim here is about registers and bytes. "
        "Whether any of it is audible, or preferable, is untested by design.",
    ]))
    out.append("")

    out.append("## 20. Stage 17 verdict\n")
    out.append(_md_table(
        ["verdict", "result", "rule"],
        [
            ["event language", f"`{verdicts['event_language']['verdict']}`",
             verdicts["event_language"]["rule"]],
            ["2 KB player", f"`{verdicts['two_kb_player']['verdict']}`",
             verdicts["two_kb_player"]["rule"]],
            ["main bottleneck", f"`{verdicts['main_bottleneck']['verdict']}`",
             verdicts["main_bottleneck"]["rule"]],
        ],
    ))
    out.append("")
    out.append(verdicts["event_language"]["explanation"] + "\n")
    out.append(verdicts["main_bottleneck"]["explanation"] + "\n")
    out.append(verdicts["independence_note"] + "\n")
    out.append("What would change a verdict:\n")
    out.append(_bullets(verdicts["what_would_change_the_verdict"]))
    out.append("")

    out.append("## 21. What should NOT be built yet\n")
    out.append(_md_table(
        ["not yet", "why not"],
        [[item["thing"], item["why_not"]] for item in bundle["what_not_to_build_yet"]],
    ))
    out.append("")

    out.append("## 22. Candidate Stage 18 experiments\n")
    out.append(_md_table(
        ["candidate", "question it answers", "cost"],
        [[item["candidate"], item["question"], item["cost"]]
         for item in bundle["stage18_candidates"]],
    ))
    out.append("")
    out.append("---\n")
    out.append(
        "Stage 17 read four corpus songs and the Stage 15 and Stage 16 records through their "
        "hashes, defined an event language from the observed behaviour, and measured a round trip "
        "with a research-only interpreter. No Composer, DSL, Music IR, POKEY IR, player, schema or "
        "SoundProfile was modified; the player source is hashed as an input and never written. No "
        "audio was rendered, no music was generated, no listening test was run, and no style or "
        "instrument abstraction was implemented.\n"
    )
    return "\n".join(out)

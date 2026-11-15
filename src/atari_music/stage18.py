"""Stage 18 - temporal compression of the POKEY performance history.

A falsification experiment. Stage 17 showed that a neutral performance-event language is
faithful but does not compress, because at 50 Hz the reference players already write several
registers per frame. Stage 18 asks the narrower, purely structural question that leaves:

    Does the historical POKEY stream at 50 Hz contain real temporal redundancy that a neutral,
    lossless, practically decodable format could exploit - without introducing any semantic
    notion such as "instrument", "melody" or "effect"?

The answer is not assumed. Every codec in this module is a **real byte format**: it produces
bytes, those bytes are decoded again, and the decoded result is compared with the canonical raw
representation byte for byte. A codec that is not exactly reversible is reported as
``LOSSLESS = FALSE`` and cannot be presented as a solution, whatever its size.

Nothing here is semantic. The vocabulary of the encoders is: state, register, value, delta,
frame, sequence, run, motif, dictionary, reference. No codec knows what a note is.

Analysis only. The 6502 player, the Composer, the DSL, the Music IR, the POKEY IR, the
production schemas and the SoundProfile system are read and hashed, never modified. No audio is
rendered, no music is generated, no instrument is transferred, and no listening test is run.
The pipeline this stage reads is upstream and is never corrected to improve a Stage 18 number.

The canonical byte order is imported from Stage 17 rather than redefined, so the two stages
agree about what "a frame of POKEY state" is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atari_music import stage15, stage17

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_STAGE16_DIR = DEFAULT_REPORTS_DIR / "stage16"
DEFAULT_STAGE17_DIR = DEFAULT_REPORTS_DIR / "stage17"
DEFAULT_STAGE18_DIR = DEFAULT_REPORTS_DIR / "stage18"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage15.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_PLAYER_ASM = stage17.DEFAULT_PLAYER_ASM

ANALYSIS_VERSION = "stage18/1"

#: The register order of one frame, taken from Stage 17 so the two stages cannot disagree.
REGISTER_ORDER: Tuple[str, ...] = tuple(stage17.REGISTER_ORDER)
FRAME_BYTES = len(REGISTER_ORDER)

#: Every codec in this module shares one container header, so the header is a constant across
#: the comparison and cannot bias a ranking. It is still counted in every total, because a
#: decoder needs it:
#:     magic 'P8' (2) | codec id (1) | flags (1) | frame count u32 LE (4) | period us u32 LE (4)
CONTAINER_MAGIC = b"P8"
CONTAINER_HEADER_BYTES = 12

#: Frames are 50 Hz; the trace records its own measured period in milliseconds.
MICROSECONDS = 1_000_000


class Stage18Error(RuntimeError):
    """A required input artefact is missing, malformed, or a stream is corrupt."""


# ---------------------------------------------------------------------------
# Byte-level primitives (shared by every codec, so a cost can never be hidden)
# ---------------------------------------------------------------------------
def uvarint(value: int) -> bytes:
    """Unsigned LEB128. 1 byte below 128, 2 below 16384, 3 below 2M, and so on."""
    if value < 0:
        raise Stage18Error(f"uvarint cannot encode a negative value: {value}")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def read_uvarint(buf: bytes, pos: int) -> Tuple[int, int]:
    """Read an unsigned LEB128 value; raises on a truncated or overlong encoding."""
    shift = 0
    value = 0
    while True:
        if pos >= len(buf):
            raise Stage18Error("truncated uvarint")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise Stage18Error("uvarint is too long")


def zigzag(value: int) -> int:
    """Map a signed integer to an unsigned one so small magnitudes stay small."""
    return value * 2 if value >= 0 else -value * 2 - 1


def unzigzag(value: int) -> int:
    return value // 2 if value % 2 == 0 else -(value // 2) - 1


def uvarint_bytes(value: int) -> int:
    """Bytes ``uvarint(value)`` would occupy, without building it."""
    size = 1
    value >>= 7
    while value:
        size += 1
        value >>= 7
    return size


# ---------------------------------------------------------------------------
# Small statistics helpers (deterministic; no sampling, no set ordering in output)
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise Stage18Error(f"missing artefact: {path}") from error
    except json.JSONDecodeError as error:
        raise Stage18Error(f"malformed JSON: {path}: {error}") from error


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _summary_stats(values: Sequence[float], places: int = 6) -> Dict[str, Optional[float]]:
    """mean / median / min / max, which the brief requires instead of a bare average."""
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": _rnd(_mean(values), places),
        "median": _rnd(_median(values), places),
        "min": _rnd(min(values), places),
        "max": _rnd(max(values), places),
    }


def ratio(compressed: int, raw: int) -> Optional[float]:
    return _rnd(compressed / raw) if raw else None


def saving_percent(compressed: int, raw: int) -> Optional[float]:
    return _rnd(100.0 * (1.0 - compressed / raw)) if raw else None


# ---------------------------------------------------------------------------
# SECTION 3 - the canonical raw representation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FrameStream:
    """One song's POKEY history, in the canonical register order.

    This is the object every codec encodes and the object every decoder must reproduce. It is
    deliberately the *absolute state* of every register in every frame: no deltas, no runs, no
    implicit carry-over, and AUDCTL repeated in every frame even when constant. A decoder cannot
    know that AUDCTL never changes, so a representation that assumes it would be hiding
    information. Whether that assumption is *worth making* is what the delta and dictionary
    codecs measure; it is never assumed for free.
    """

    slug: str
    frames: int
    frame_period_us: int
    registers: Mapping[str, Tuple[int, ...]]

    def frame_bytes(self, index: int) -> bytes:
        return bytes(self.registers[name][index] for name in REGISTER_ORDER)

    def payload(self) -> bytes:
        """The canonical raw payload: ``frames * 9`` bytes, absolute state, no compression."""
        out = bytearray(self.frames * FRAME_BYTES)
        pos = 0
        for index in range(self.frames):
            for name in REGISTER_ORDER:
                out[pos] = self.registers[name][index]
                pos += 1
        return bytes(out)

    def to_registers(self) -> Dict[str, List[int]]:
        return {name: list(self.registers[name]) for name in REGISTER_ORDER}


def stream_from_payload(slug: str, frames: int, period_us: int, payload: bytes) -> FrameStream:
    """Rebuild a :class:`FrameStream` from a canonical raw payload."""
    if len(payload) != frames * FRAME_BYTES:
        raise Stage18Error(
            f"{slug}: payload is {len(payload)} bytes, expected {frames * FRAME_BYTES}"
        )
    registers: Dict[str, List[int]] = {name: [] for name in REGISTER_ORDER}
    pos = 0
    for _ in range(frames):
        for name in REGISTER_ORDER:
            registers[name].append(payload[pos])
            pos += 1
    return FrameStream(
        slug=slug, frames=frames, frame_period_us=period_us,
        registers={name: tuple(registers[name]) for name in REGISTER_ORDER},
    )


# ---------------------------------------------------------------------------
# The shared container, and the codec interface every experiment uses
# ---------------------------------------------------------------------------
#: Codec identifiers inside the container. Stable: a container is self-describing.
CODEC_IDS: Dict[str, int] = {
    "raw": 0,
    "rle_frame": 1,
    "rle_register": 2,
    "delta_fixed": 3,
    "delta_gap": 4,
    "ramps": 5,
    "lz": 6,
    "dictionary": 7,
    "hybrid": 8,
}


def make_container(codec_id: int, frames: int, period_us: int, payload: bytes) -> bytes:
    """magic | codec id | flags | frame count u32 | period us u32 | payload."""
    return (
        CONTAINER_MAGIC
        + bytes([codec_id & 0xFF, 0x00])
        + frames.to_bytes(4, "little")
        + period_us.to_bytes(4, "little")
        + payload
    )


def parse_container(data: bytes) -> Tuple[int, int, int, int, bytes]:
    """Split a container back into (codec id, flags, frames, period us, payload)."""
    if len(data) < CONTAINER_HEADER_BYTES:
        raise Stage18Error("container is shorter than its header")
    if data[:2] != CONTAINER_MAGIC:
        raise Stage18Error(f"bad container magic: {data[:2]!r}")
    codec_id, flags = data[2], data[3]
    frames = int.from_bytes(data[4:8], "little")
    period_us = int.from_bytes(data[8:12], "little")
    return codec_id, flags, frames, period_us, data[CONTAINER_HEADER_BYTES:]


@dataclass
class Codec:
    """One real byte format: an encoder, a decoder, and the parameters they were built with."""

    key: str
    group: str
    description: str
    encode: Callable[[FrameStream], bytes]
    decode: Callable[[bytes, int], bytes]
    params: Mapping[str, Any] = field(default_factory=dict)
    needs_training: bool = False

    @property
    def label(self) -> str:
        if not self.params:
            return self.key
        rendered = ",".join(f"{name}={self.params[name]}" for name in sorted(self.params))
        return f"{self.key}[{rendered}]"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codec": self.key,
            "label": self.label,
            "group": self.group,
            "description": self.description,
            "parameters": dict(sorted(self.params.items())),
            "codec_id": CODEC_IDS.get(self.key),
        }


def registers_to_payload(columns: Mapping[str, Sequence[int]], frames: int) -> bytes:
    """Interleave per-register column arrays back into one canonical payload."""
    out = bytearray(frames * FRAME_BYTES)
    pos = 0
    for index in range(frames):
        for name in REGISTER_ORDER:
            value = columns[name][index]
            if not 0 <= value <= 255:
                raise Stage18Error(f"register {name} value out of range at frame {index}: {value}")
            out[pos] = value
            pos += 1
    return bytes(out)


def payload_to_columns(payload: bytes) -> Dict[str, List[int]]:
    """Split a canonical payload into per-register column arrays."""
    columns: Dict[str, List[int]] = {name: [] for name in REGISTER_ORDER}
    pos = 0
    while pos < len(payload):
        for name in REGISTER_ORDER:
            columns[name].append(payload[pos])
            pos += 1
    return columns


def _group_runs(values: Sequence[int]) -> List[Tuple[int, int]]:
    """Maximal runs of equal values, as ``(length, value)`` pairs, in order."""
    runs: List[Tuple[int, int]] = []
    if not values:
        return runs
    current = values[0]
    length = 1
    for value in values[1:]:
        if value == current:
            length += 1
        else:
            runs.append((length, current))
            current, length = value, 1
    runs.append((length, current))
    return runs


# ---------------------------------------------------------------------------
# Canonical raw baseline (SECTION 3)
# ---------------------------------------------------------------------------
def encode_raw(stream: FrameStream) -> bytes:
    """The baseline itself: 9 absolute bytes per frame, every register, every frame."""
    return stream.payload()


def decode_raw(payload: bytes, frames: int) -> bytes:
    if len(payload) != frames * FRAME_BYTES:
        raise Stage18Error("raw payload length does not match the frame count")
    return payload


RAW_CODEC = Codec(
    key="raw",
    group="baseline",
    description=(
        "canonical raw: the absolute state of all nine registers in every frame, no compression"
    ),
    encode=encode_raw,
    decode=decode_raw,
)


# ---------------------------------------------------------------------------
# EXPERIMENT A - run-length encoding (SECTION 4)
# ---------------------------------------------------------------------------
def encode_rle_frame(stream: FrameStream) -> bytes:
    """A1: whole-frame RLE. One record per maximal run of identical frames."""
    runs: List[Tuple[int, bytes]] = []
    previous: Optional[bytes] = None
    length = 0
    for index in range(stream.frames):
        state = stream.frame_bytes(index)
        if previous is not None and state == previous:
            length += 1
            continue
        if previous is not None:
            runs.append((length, previous))
        previous, length = state, 1
    if previous is not None:
        runs.append((length, previous))
    out = bytearray(uvarint(len(runs)))
    for run_length, state in runs:
        out += uvarint(run_length)
        out += state
    return bytes(out)


def decode_rle_frame(payload: bytes, frames: int) -> bytes:
    count, pos = read_uvarint(payload, 0)
    out = bytearray()
    for _ in range(count):
        run_length, pos = read_uvarint(payload, pos)
        if pos + FRAME_BYTES > len(payload):
            raise Stage18Error("truncated frame state in an RLE stream")
        out += payload[pos : pos + FRAME_BYTES] * run_length
        pos += FRAME_BYTES
    if len(out) != frames * FRAME_BYTES:
        raise Stage18Error("RLE stream decodes to the wrong number of frames")
    return bytes(out)


def encode_rle_register(stream: FrameStream) -> bytes:
    """A2: per-register RLE. Nine independent run streams, each with its own run count."""
    out = bytearray()
    for name in REGISTER_ORDER:
        runs = _group_runs(stream.registers[name])
        out += uvarint(len(runs))
        for run_length, value in runs:
            out += uvarint(run_length)
            out.append(value)
    return bytes(out)


def decode_rle_register(payload: bytes, frames: int) -> bytes:
    pos = 0
    columns: Dict[str, List[int]] = {}
    for name in REGISTER_ORDER:
        count, pos = read_uvarint(payload, pos)
        values: List[int] = []
        for _ in range(count):
            run_length, pos = read_uvarint(payload, pos)
            if pos >= len(payload):
                raise Stage18Error("truncated register run")
            values.extend([payload[pos]] * run_length)
            pos += 1
        if len(values) != frames:
            raise Stage18Error(f"register {name} decodes to {len(values)} frames, want {frames}")
        columns[name] = values
    return registers_to_payload(columns, frames)


RLE_CODECS: Tuple[Codec, ...] = (
    Codec("rle_frame", "RLE", "A1 whole-frame RLE: STATE + RUN_LENGTH",
          encode_rle_frame, decode_rle_frame),
    Codec("rle_register", "RLE", "A2 per-register RLE: nine independent run streams",
          encode_rle_register, decode_rle_register),
)


def load_frame_stream(candidate: Mapping[str, Any]) -> FrameStream:
    """Read one corpus subsong's register trace into the canonical representation."""
    path = Path(candidate["path"])
    trace = stage15.load_trace(path)
    period_us = int(round(trace.frame_period_ms * 1000.0))
    return FrameStream(
        slug=candidate["slug"],
        frames=trace.frames,
        frame_period_us=period_us,
        registers={
            name: tuple(int(value) & 0xFF for value in trace.registers[name])
            for name in REGISTER_ORDER
        },
    )


def load_dataset(stage16_dir: Path = DEFAULT_STAGE16_DIR) -> Tuple[List[FrameStream], Dict[str, Any]]:
    """The four Stage 16 songs, read as frame streams rather than re-chosen here."""
    selection = stage17.stage16_selection(Path(stage16_dir))
    streams = [load_frame_stream(candidate) for candidate in selection["candidates"]]
    return streams, selection



# ---------------------------------------------------------------------------
# EXPERIMENT B - delta encoding (SECTION 5)
# ---------------------------------------------------------------------------
def encode_delta_fixed(stream: FrameStream) -> bytes:
    """B1: fixed-width signed deltas. A diagnostic, not a compressor.

    Frame 0 is absolute; every later frame stores ``(value - previous) mod 256`` for each of the
    nine registers. It costs exactly what raw costs, and it exists to answer one question: does
    the delta distribution have structure, independent of whether the container exploits it?
    """
    if stream.frames == 0:
        return b""
    out = bytearray(stream.frame_bytes(0))
    previous = list(stream.frame_bytes(0))
    for index in range(1, stream.frames):
        current = stream.frame_bytes(index)
        for offset in range(FRAME_BYTES):
            out.append((current[offset] - previous[offset]) & 0xFF)
        previous = list(current)
    return bytes(out)


def decode_delta_fixed(payload: bytes, frames: int) -> bytes:
    if len(payload) != frames * FRAME_BYTES:
        raise Stage18Error("delta stream length does not match the frame count")
    out = bytearray(payload[:FRAME_BYTES])
    previous = list(payload[:FRAME_BYTES])
    pos = FRAME_BYTES
    for _ in range(1, frames):
        current = [(previous[offset] + payload[pos + offset]) & 0xFF
                   for offset in range(FRAME_BYTES)]
        out += bytes(current)
        previous = current
        pos += FRAME_BYTES
    return bytes(out)


def encode_delta_gap(stream: FrameStream) -> bytes:
    """B2: delta with a zero-run. Only frames that differ from their predecessor are stored.

    For each changed frame: the gap in frames since the previous change, a bitmap of which of
    the nine registers changed, then one absolute byte per changed register. A frame that does
    not change costs nothing at all - which is exactly why AUDCTL, constant in this corpus, stops
    being paid for 6,000 times. The bitmap is itself a uvarint, so the common "one or two
    registers changed" case costs one byte of mask, not two.
    """
    if stream.frames == 0:
        return b""
    out = bytearray(stream.frame_bytes(0))
    previous = list(stream.frame_bytes(0))
    changed: List[Tuple[int, int, List[int]]] = []
    for index in range(1, stream.frames):
        current = stream.frame_bytes(index)
        mask = 0
        values: List[int] = []
        for offset in range(FRAME_BYTES):
            if current[offset] != previous[offset]:
                mask |= 1 << offset
                values.append(current[offset])
        if mask:
            changed.append((index, mask, values))
            previous = list(current)
    out += uvarint(len(changed))
    last = 0
    for index, mask, values in changed:
        out += uvarint(index - last)
        out += uvarint(mask)
        out += bytes(values)
        last = index
    return bytes(out)


def decode_delta_gap(payload: bytes, frames: int) -> bytes:
    if frames == 0:
        return b""
    if len(payload) < FRAME_BYTES:
        raise Stage18Error("delta-gap stream is shorter than one frame")
    out = bytearray(payload[:FRAME_BYTES])
    previous = list(payload[:FRAME_BYTES])
    count, pos = read_uvarint(payload, FRAME_BYTES)
    current_index = 0
    for _ in range(count):
        gap, pos = read_uvarint(payload, pos)
        mask, pos = read_uvarint(payload, pos)
        current_index += gap
        if current_index >= frames:
            raise Stage18Error("delta-gap change index runs past the end of the stream")
        state = list(previous)
        for offset in range(FRAME_BYTES):
            if mask & (1 << offset):
                if pos >= len(payload):
                    raise Stage18Error("truncated delta-gap value list")
                state[offset] = payload[pos]
                pos += 1
        while len(out) // FRAME_BYTES < current_index:
            out += bytes(previous)
        out += bytes(state)
        previous = state
    while len(out) // FRAME_BYTES < frames:
        out += bytes(previous)
    if len(out) != frames * FRAME_BYTES:
        raise Stage18Error("delta-gap stream decodes to the wrong number of frames")
    return bytes(out)


def delta_histograms(stream: FrameStream) -> Dict[str, Any]:
    """Diagnostic only: the shape of the delta distribution, per register.

    Reported as evidence about whether simple delta coding can pay, and explicitly *not* used as
    a size estimate: an entropy figure is not a representation.
    """
    import math

    per_register: Dict[str, Any] = {}
    for name in REGISTER_ORDER:
        values = stream.registers[name]
        signed = [values[index] - values[index - 1] for index in range(1, stream.frames)]
        counts: Dict[int, int] = {}
        for delta in signed:
            counts[delta] = counts.get(delta, 0) + 1
        total = len(signed)
        entropy = 0.0
        for delta in sorted(counts):
            probability = counts[delta] / total if total else 0.0
            if probability:
                entropy -= probability * math.log2(probability)
        zeros = counts.get(0, 0)
        per_register[name] = {
            "changes": total - zeros,
            "zero_deltas": zeros,
            "zero_share": _rnd(zeros / total) if total else None,
            "distinct_deltas": len(counts),
            "entropy_bits": _rnd(entropy, 4),
            "most_common": [
                {"delta": delta, "count": counts[delta]}
                for delta in sorted(counts, key=lambda item: (-counts[item], item))[:5]
            ],
        }
    return {
        "slug": stream.slug,
        "note": (
            "diagnostic only. The entropy column is bits per delta and is NOT a byte size: a "
            "representation still has to store the value, and every codec's real cost is measured "
            "by encoding and decoding it."
        ),
        "registers": per_register,
    }


DELTA_CODECS: Tuple[Codec, ...] = (
    Codec("delta_fixed", "delta",
          "B1 fixed-width signed deltas (diagnostic; the same size as raw)",
          encode_delta_fixed, decode_delta_fixed),
    Codec("delta_gap", "delta",
          "B2 delta with zero-run: gap + change bitmap + changed values",
          encode_delta_gap, decode_delta_gap),
)


# ---------------------------------------------------------------------------
# EXPERIMENT C - temporal ramps (SECTION 6)
# ---------------------------------------------------------------------------
#: Segment tags. CONST and LINEAR and QUAD are *models*; LITERAL is the escape that stores the
#: values verbatim, and it is always charged at one byte per value.
SEG_CONST = 0
SEG_LINEAR = 1
SEG_QUAD = 2
SEG_LITERAL = 3
SEGMENT_TAGS = (SEG_CONST, SEG_LINEAR, SEG_QUAD, SEG_LITERAL)


def _const_length(values: Sequence[int], start: int) -> int:
    end = start + 1
    limit = len(values)
    while end < limit and values[end] == values[start]:
        end += 1
    return end - start


def _linear_length(values: Sequence[int], start: int) -> int:
    """Length of the maximal run with a constant first difference, modulo 256."""
    limit = len(values)
    if start + 1 >= limit:
        return 1
    delta = (values[start + 1] - values[start]) & 0xFF
    end = start + 2
    previous = values[start + 1]
    while end < limit and ((values[end] - previous) & 0xFF) == delta:
        previous = values[end]
        end += 1
    return end - start


def _quad_length(values: Sequence[int], start: int) -> int:
    """Length of the maximal run with a constant second difference, modulo 256.

    The model is the iterated recurrence ``v[0]=start; d[0]=d1; v[i+1]=v[i]+d[i];
    d[i+1]=d[i]+d2``, all modulo 256, so it is exactly invertible on a byte stream.
    """
    limit = len(values)
    if start + 2 >= limit:
        return 1
    d1 = (values[start + 1] - values[start]) & 0xFF
    d2 = ((values[start + 2] - values[start + 1]) - d1) & 0xFF
    end = start + 2
    previous = values[start + 1]
    previous_delta = d1
    while end < limit:
        expected_delta = (previous_delta + d2) & 0xFF
        expected_value = (previous + expected_delta) & 0xFF
        if values[end] != expected_value:
            break
        previous, previous_delta = values[end], expected_delta
        end += 1
    return end - start


def _segment_params(tag: int, values: Sequence[int], index: int) -> List[int]:
    """Encoder-side segment parameters: ``[start, delta, ...]``, derived from the data."""
    if tag == SEG_CONST:
        return [values[index]]
    if tag == SEG_LINEAR:
        return [values[index], (values[index + 1] - values[index]) & 0xFF]
    d1 = (values[index + 1] - values[index]) & 0xFF
    d2 = ((values[index + 2] - values[index + 1]) - d1) & 0xFF
    return [values[index], d1, d2]


def _segment_cost(tag: int, length: int, params: Sequence[int]) -> int:
    """Bytes a segment occupies, including its one-byte tag. Must match the writer exactly."""
    cost = 1 + uvarint_bytes(length)
    if tag == SEG_CONST:
        return cost + 1
    if tag == SEG_LINEAR:
        return cost + 1 + uvarint_bytes(zigzag(params[1]))
    if tag == SEG_QUAD:
        return (
            cost + 1 + uvarint_bytes(zigzag(params[1])) + uvarint_bytes(zigzag(params[2]))
        )
    return cost + length


def write_segment(out: bytearray, tag: int, length: int, params: Sequence[int]) -> None:
    out.append(tag)
    out += uvarint(length)
    if tag == SEG_CONST:
        out.append(params[0])
    elif tag == SEG_LINEAR:
        out.append(params[0])
        out += uvarint(zigzag(params[1]))
    elif tag == SEG_QUAD:
        out.append(params[0])
        out += uvarint(zigzag(params[1]))
        out += uvarint(zigzag(params[2]))
    else:
        out += bytes(params)


def read_segment(payload: bytes, pos: int) -> Tuple[int, int, List[int], int]:
    """Decoder-side segment reader, the exact inverse of :func:`write_segment`."""
    if pos >= len(payload):
        raise Stage18Error("truncated ramp segment")
    tag = payload[pos]
    pos += 1
    length, pos = read_uvarint(payload, pos)
    if tag == SEG_CONST:
        if pos >= len(payload):
            raise Stage18Error("truncated CONST segment")
        value = payload[pos]
        return tag, length, [value], pos + 1
    if tag == SEG_LINEAR:
        if pos + 1 > len(payload):
            raise Stage18Error("truncated LINEAR segment")
        start = payload[pos]
        delta, pos = read_uvarint(payload, pos + 1)
        return tag, length, [start, unzigzag(delta) & 0xFF], pos
    if tag == SEG_QUAD:
        if pos + 1 > len(payload):
            raise Stage18Error("truncated QUAD segment")
        start = payload[pos]
        d1, pos = read_uvarint(payload, pos + 1)
        d2, pos = read_uvarint(payload, pos)
        return tag, length, [start, unzigzag(d1) & 0xFF, unzigzag(d2) & 0xFF], pos
    if tag == SEG_LITERAL:
        if pos + length > len(payload):
            raise Stage18Error("truncated LITERAL segment")
        literal = list(payload[pos : pos + length])
        return tag, length, literal, pos + length
    raise Stage18Error(f"unknown segment tag {tag}")


def segment_values(tag: int, length: int, params: Sequence[int]) -> List[int]:
    """Expand a segment back into the values it stands for."""
    if tag == SEG_CONST:
        return [params[0]] * length
    if tag == SEG_LINEAR:
        start, delta = params[0], params[1]
        return [(start + step * delta) & 0xFF for step in range(length)]
    if tag == SEG_QUAD:
        start, d1, d2 = params[0], params[1], params[2]
        out: List[int] = []
        value, delta = start, d1
        for _ in range(length):
            out.append(value)
            value = (value + delta) & 0xFF
            delta = (delta + d2) & 0xFF
        return out
    return list(params)


def segment_register(values: Sequence[int], min_length: int) -> List[Tuple[int, int, List[int]]]:
    """Greedy segmentation of one register stream into exact model segments and literals.

    A model segment is only taken when it is strictly *cheaper* than the literal bytes it would
    replace, so a segment can never make the stream larger. Ties are broken deterministically by
    tag order and then by the longer span, so two runs of this function always agree.
    """
    limit = len(values)
    segments: List[Tuple[int, int, List[int]]] = []
    pending: List[int] = []

    def flush() -> None:
        if pending:
            segments.append((SEG_LITERAL, len(pending), list(pending)))
            pending.clear()

    index = 0
    while index < limit:
        best_tag, best_length, best_params, best_saving = -1, 0, [], 0
        for tag, finder in ((SEG_CONST, _const_length),
                            (SEG_LINEAR, _linear_length),
                            (SEG_QUAD, _quad_length)):
            length = finder(values, index)
            if length < min_length:
                continue
            params = _segment_params(tag, values, index)
            cost = _segment_cost(tag, length, params)
            saving = length - cost
            if saving <= 0:
                continue
            if saving > best_saving or (saving == best_saving and length > best_length):
                best_tag, best_length, best_params, best_saving = tag, length, params, saving
        if best_tag >= 0:
            flush()
            segments.append((best_tag, best_length, best_params))
            index += best_length
        else:
            pending.append(values[index])
            index += 1
    flush()
    return segments





def encode_ramps_stream(stream: FrameStream, min_length: int) -> bytes:
    """Per register: a segment list of model runs and literal escapes."""
    out = bytearray()
    for name in REGISTER_ORDER:
        segments = segment_register(stream.registers[name], min_length)
        out += uvarint(len(segments))
        for tag, length, params in segments:
            write_segment(out, tag, length, params)
    return bytes(out)


def decode_ramps_stream(payload: bytes, frames: int) -> bytes:
    pos = 0
    columns: Dict[str, List[int]] = {}
    for name in REGISTER_ORDER:
        count, pos = read_uvarint(payload, pos)
        values: List[int] = []
        for _ in range(count):
            tag, length, params, pos = read_segment(payload, pos)
            values.extend(segment_values(tag, length, params))
        if len(values) != frames:
            raise Stage18Error(f"register {name} decodes to {len(values)} frames, want {frames}")
        columns[name] = values
    return registers_to_payload(columns, frames)


def ramp_codecs(min_lengths: Sequence[int] = (2, 3, 4, 5, 6, 8)) -> Tuple[Codec, ...]:
    """One codec per minimum segment length the brief asks to sweep."""
    codecs: List[Codec] = []
    for min_length in min_lengths:
        codecs.append(Codec(
            key="ramps",
            group="ramps",
            description=(
                "C temporal ramps: per-register greedy segments of CONST / LINEAR / QUAD runs "
                "with a literal escape, taken only when strictly cheaper than the literals"
            ),
            encode=(lambda stream, m=min_length: encode_ramps_stream(stream, m)),
            decode=decode_ramps_stream,
            params={"min_length": min_length},
        ))
    return tuple(codecs)


# ---------------------------------------------------------------------------
# EXPERIMENT E - backreferences / dictionary compression (SECTION 8)
# ---------------------------------------------------------------------------
TOKEN_LITERAL = 0x00
TOKEN_MATCH = 0x01
TOKEN_DICT = 0x02

#: How many candidate positions to try at each frame. A bounded search is a deterministic
#: choice, and it is stated rather than hidden: an unbounded search would be quadratic on a
#: stream where one frame value repeats for thousands of frames.
LZ_MAX_CANDIDATES = 16


def encode_lz(stream: FrameStream, window: int, min_match: int) -> bytes:
    """Frame-aligned LZ: literal runs and ``(offset, length)`` backreferences, in frames.

    Matches are aligned to frame boundaries, so an offset is a frame distance and a length is a
    frame count. Overlapping matches are legal and are used: the decoder copies one frame at a
    time, so a match whose length exceeds its offset still refers only to frames already
    produced. That is what lets a repeating frame pattern cost one reference per period.
    """
    frames = stream.frames
    if frames == 0:
        return b""
    frame_bytes = [stream.frame_bytes(index) for index in range(frames)]
    out = bytearray()
    literals = bytearray()
    index: Dict[bytes, List[int]] = {}

    def flush() -> None:
        if literals:
            out.append(TOKEN_LITERAL)
            out.extend(uvarint(len(literals) // FRAME_BYTES))
            out.extend(literals)
            literals.clear()

    pos = 0
    while pos < frames:
        key = frame_bytes[pos]
        best_length, best_offset = 0, 0
        candidates = index.get(key)
        if candidates:
            for candidate in candidates[-LZ_MAX_CANDIDATES:][::-1]:
                offset = pos - candidate
                if offset <= 0 or offset > window:
                    continue
                length = 1
                limit = frames - pos
                while length < limit and frame_bytes[candidate + length] == frame_bytes[pos + length]:
                    length += 1
                if length > best_length:
                    best_length, best_offset = length, offset
        if best_length >= min_match:
            flush()
            out.append(TOKEN_MATCH)
            out.extend(uvarint(best_offset))
            out.extend(uvarint(best_length))
            for step in range(best_length):
                index.setdefault(frame_bytes[pos + step], []).append(pos + step)
            pos += best_length
        else:
            literals.extend(key)
            index.setdefault(key, []).append(pos)
            pos += 1
    flush()
    return bytes(out)


def decode_lz(payload: bytes, frames: int) -> bytes:
    out = bytearray()
    pos = 0
    while pos < len(payload):
        token = payload[pos]
        pos += 1
        if token == TOKEN_LITERAL:
            count, pos = read_uvarint(payload, pos)
            if pos + count * FRAME_BYTES > len(payload):
                raise Stage18Error("truncated LZ literal run")
            out += payload[pos : pos + count * FRAME_BYTES]
            pos += count * FRAME_BYTES
        elif token == TOKEN_MATCH:
            offset, pos = read_uvarint(payload, pos)
            length, pos = read_uvarint(payload, pos)
            if offset <= 0:
                raise Stage18Error("LZ match offset must be positive")
            if offset * FRAME_BYTES > len(out):
                raise Stage18Error("LZ match points before the start of the stream")
            for _ in range(length):
                source = len(out) - offset * FRAME_BYTES
                out += out[source : source + FRAME_BYTES]
        else:
            raise Stage18Error(f"unknown LZ token {token}")
    if len(out) != frames * FRAME_BYTES:
        raise Stage18Error("LZ stream decodes to the wrong number of frames")
    return bytes(out)


def lz_codecs(
    windows: Sequence[int] = (64, 256, 1024),
    min_matches: Sequence[int] = (2, 4, 8),
) -> Tuple[Codec, ...]:
    """The window and minimum-match sweep the brief asks for."""
    codecs: List[Codec] = []
    for window in windows:
        for min_match in min_matches:
            codecs.append(Codec(
                key="lz",
                group="dictionary",
                description=(
                    "E frame-aligned LZ backreferences: literal runs and (offset, length) "
                    "matches in frames, with a bounded candidate search"
                ),
                encode=(lambda stream, w=window, m=min_match: encode_lz(stream, w, m)),
                decode=decode_lz,
                params={"window_frames": window, "min_match_frames": min_match,
                        "max_candidates": LZ_MAX_CANDIDATES},
            ))
    return tuple(codecs)



# ---------------------------------------------------------------------------
# EXPERIMENT D - repeated temporal motifs (SECTION 7)
# ---------------------------------------------------------------------------
#: Motif lengths the brief asks to test, in frames.
MOTIF_LENGTHS = (2, 3, 4, 5, 8, 16, 32)


def motif_statistics(stream: FrameStream) -> Dict[str, Any]:
    """Detection only: how often short frame sequences actually repeat in one song.

    The frame counts here are *not* a compression result. Part 7 of the brief is explicit that
    the number of found repetitions is not the metric; the metric is the compressed size
    including the dictionary, the references and the stream metadata, and that is measured by
    :func:`encode_dictionary`, not here.

    The coverage figure is a true union of positions, not a sum of occurrences: summing
    overlapping occurrences saturates at 1.0 for every length and invites misreading. Two
    *optimistic* byte figures are also reported, both labelled upper bounds, because they show
    immediately whether naming the repetition could ever pay: ``table_cost_bytes`` is what storing
    every repeated motif would cost, and ``optimistic_saving_bytes`` assumes every occurrence
    after the first became a free reference.
    """
    frames = stream.frames
    frame_bytes = [stream.frame_bytes(index) for index in range(frames)]
    per_length: List[Dict[str, Any]] = []
    for length in MOTIF_LENGTHS:
        counts: Dict[bytes, int] = {}
        for index in range(frames - length + 1):
            key = b"".join(frame_bytes[index : index + length])
            counts[key] = counts.get(key, 0) + 1
        repeated = {key: count for key, count in counts.items() if count >= 2}
        covered = [False] * frames
        table_cost = 0
        saving = 0
        for key, count in sorted(repeated.items()):
            table_cost += uvarint_bytes(length) + len(key)
            saving += (count - 1) * len(key)
        for index in range(frames - length + 1):
            key = b"".join(frame_bytes[index : index + length])
            if repeated.get(key, 0) >= 2:
                for offset in range(length):
                    covered[index + offset] = True
        covered_frames = sum(covered)
        per_length.append(
            {
                "length_frames": length,
                "positions": max(0, frames - length + 1),
                "distinct_motifs": len(counts),
                "repeated_motifs": len(repeated),
                "repeated_occurrences": sum(repeated.values()),
                "covered_frames": covered_frames,
                "coverage_share": _rnd(covered_frames / frames) if frames else None,
                "table_cost_bytes": table_cost,
                "optimistic_saving_bytes": saving,
                "net_optimistic_bytes": saving - table_cost,
                "upper_bound_note": (
                    "optimistic_saving_bytes assumes every repeat after the first costs nothing, "
                    "which no real encoder achieves; net_optimistic_bytes is therefore an upper "
                    "bound on the benefit, and section 8 measures the real cost"
                ),
            }
        )
    return {
        "slug": stream.slug,
        "frames": frames,
        "by_length": per_length,
        "reading": (
            "coverage_share is the share of frames covered by at least one repeated motif, "
            "counted once each. It is an upper bound on what a motif table could represent, not "
            "a size; the size is in section 8."
        ),
    }

    return tuple(codecs)



#: How many motif lengths a dictionary may draw on, and how many entries it may hold.
DICT_LENGTHS = (2, 4, 8, 16)
DICT_TOP_K = 256
#: Entries tried per first-frame at encode time. Bounded so the encoder stays linear-ish.
DICT_MAX_CANDIDATES = 32
#: Dictionary sizes swept for the per-song and shared cases.
DICT_TOP_KS = (32, 64, 128, 256)
#: Dictionary size used for the four leave-one-song-out folds.
DICT_LOSO_TOP_K = 64


def build_motif_table(
    streams: Sequence[FrameStream],
    lengths: Sequence[int] = DICT_LENGTHS,
    top_k: int = DICT_TOP_K,
) -> List[Tuple[int, bytes]]:
    """Greedy dictionary construction from one or more songs.

    Every candidate motif of every requested length is counted across the training streams and
    scored by the raw bytes it would replace, minus its own storage. Candidates that do not
    repay their storage are dropped, and the survivors are taken in a deterministic order
    (score descending, then the byte string) so two runs of this function always agree.

    This is where a cross-song experiment gets its dictionary: training on three songs and
    testing on the fourth is the leave-one-song-out test in Part 12.
    """
    counts: Dict[bytes, int] = {}
    for stream in streams:
        frames = stream.frames
        frame_bytes = [stream.frame_bytes(index) for index in range(frames)]
        for length in lengths:
            if length > frames:
                continue
            for index in range(frames - length + 1):
                key = b"".join(frame_bytes[index : index + length])
                counts[key] = counts.get(key, 0) + 1
    scored: List[Tuple[int, bytes]] = []
    for key, count in counts.items():
        length = len(key) // FRAME_BYTES
        storage = uvarint_bytes(length) + len(key)
        benefit = count * len(key) - storage
        if benefit > 0:
            scored.append((benefit, key))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: List[Tuple[int, bytes]] = []
    seen: set = set()
    for _, key in scored:
        if key in seen:
            continue
        seen.add(key)
        chosen.append((len(key) // FRAME_BYTES, key))
        if len(chosen) >= top_k:
            break
    return chosen



def encode_dictionary(
    stream: FrameStream,
    table: Sequence[Tuple[int, bytes]],
) -> bytes:
    """Dictionary-referenced stream. The table travels inside the payload, and is charged.

    Layout: ``uvarint(K)`` then ``K`` entries of ``uvarint(length_frames) + frames*9 bytes``,
    then the body: literal runs and dictionary references. A reference costs one tag byte plus a
    uvarint index, so a dictionary entry only pays when it replaces more than that.
    """
    out = bytearray(uvarint(len(table)))
    for length, motif in table:
        out += uvarint(length)
        out += motif
    body = bytearray()
    literals = bytearray()

    def flush() -> None:
        if literals:
            body.append(TOKEN_LITERAL)
            body.extend(uvarint(len(literals) // FRAME_BYTES))
            body.extend(literals)
            literals.clear()

    by_first: Dict[bytes, List[Tuple[int, int, bytes]]] = {}
    for index, (length, motif) in enumerate(table):
        by_first.setdefault(motif[:FRAME_BYTES], []).append((length, index, motif))
    # Bounded, deterministically ordered candidate list per first frame: longest first, then by
    # table index. A bound is needed because a popular first frame would otherwise make the
    # encoder quadratic; fixing the order keeps the encoder reproducible.
    for key in by_first:
        by_first[key].sort(key=lambda item: (-item[0], item[1]))
        del by_first[key][DICT_MAX_CANDIDATES:]

    frames = stream.frames
    frame_bytes = [stream.frame_bytes(index) for index in range(frames)]
    pos = 0
    while pos < frames:
        best_length, best_index = 0, -1
        for length, index, motif in by_first.get(frame_bytes[pos], []):
            if length <= best_length or pos + length > frames:
                continue
            if b"".join(frame_bytes[pos : pos + length]) == motif:
                best_length, best_index = length, index
        if best_index >= 0:
            flush()
            body.append(TOKEN_DICT)
            body.extend(uvarint(best_index))
            pos += best_length
        else:
            literals.extend(frame_bytes[pos])
            pos += 1
    flush()
    out += body
    return bytes(out)


def decode_dictionary(payload: bytes, frames: int) -> bytes:
    count, pos = read_uvarint(payload, 0)
    table: List[bytes] = []
    for _ in range(count):
        length, pos = read_uvarint(payload, pos)
        size = length * FRAME_BYTES
        if pos + size > len(payload):
            raise Stage18Error("truncated dictionary entry")
        table.append(payload[pos : pos + size])
        pos += size
    out = bytearray()
    while pos < len(payload):
        token = payload[pos]
        pos += 1
        if token == TOKEN_LITERAL:
            n, pos = read_uvarint(payload, pos)
            if pos + n * FRAME_BYTES > len(payload):
                raise Stage18Error("truncated dictionary literal run")
            out += payload[pos : pos + n * FRAME_BYTES]
            pos += n * FRAME_BYTES
        elif token == TOKEN_DICT:
            index, pos = read_uvarint(payload, pos)
            if index >= len(table):
                raise Stage18Error("dictionary reference out of range")
            out += table[index]
        else:
            raise Stage18Error(f"unknown dictionary token {token}")
    if len(out) != frames * FRAME_BYTES:
        raise Stage18Error("dictionary stream decodes to the wrong number of frames")
    return bytes(out)


def dictionary_split(payload: bytes) -> Dict[str, int]:
    """Split a dictionary payload into the table bytes and the body bytes.

    The brief forbids reporting a dictionary without paying for it, so the two halves are
    measured separately and both are always reported.
    """
    count, pos = read_uvarint(payload, 0)
    for _ in range(count):
        length, pos = read_uvarint(payload, pos)
        pos += length * FRAME_BYTES
    return {"dictionary_bytes": pos, "body_bytes": len(payload) - pos, "entries": count}


def dictionary_codec(
    table: Sequence[Tuple[int, bytes]],
    trained_on: Sequence[str],
) -> Codec:
    """Wrap a motif table as a codec. The table travels inside the payload, so it is paid for."""
    table_bytes = sum(uvarint_bytes(length) + len(motif) for length, motif in table)
    return Codec(
        key="dictionary",
        group="dictionary",
        description=(
            "D dictionary references: a motif table (charged inside the payload) plus literal "
            "and reference tokens; the body is one reference per motif occurrence"
        ),
        encode=(lambda stream, t=tuple(table): encode_dictionary(stream, t)),
        decode=decode_dictionary,
        params={
            "entries": len(table),
            "table_bytes": table_bytes,
            "trained_on": "|".join(trained_on),
            "lengths": "|".join(str(length) for length in DICT_LENGTHS),
        },
        needs_training=True,
    )


# ---------------------------------------------------------------------------
# EXPERIMENT F - hybrid temporal compression (SECTION 9)
# ---------------------------------------------------------------------------
def substream(stream: FrameStream, start: int, length: int) -> FrameStream:
    """A block of frames, as its own stream, so any codec can be applied to it."""
    end = min(start + length, stream.frames)
    return FrameStream(
        slug=stream.slug,
        frames=end - start,
        frame_period_us=stream.frame_period_us,
        registers={
            name: tuple(stream.registers[name][start:end]) for name in REGISTER_ORDER
        },
    )


def _hybrid_members() -> Tuple[Tuple[str, int, Callable[[FrameStream], bytes],
                                 Callable[[bytes, int], bytes]], ...]:
    """The candidate codecs a hybrid block may choose from, in a fixed deterministic order.

    The order is the tie-breaker: if two encodings cost the same number of bytes the earlier
    entry wins, so a hybrid stream never depends on dictionary iteration order.
    """
    return (
        ("raw", 0, encode_raw, decode_raw),
        ("rle_register", 1, encode_rle_register, decode_rle_register),
        ("delta_gap", 2, encode_delta_gap, decode_delta_gap),
        ("ramps", 3, (lambda stream: encode_ramps_stream(stream, 3)), decode_ramps_stream),
        ("lz", 4, (lambda stream: encode_lz(stream, 512, 2)), decode_lz),
    )


def encode_hybrid(stream: FrameStream, block_frames: int) -> bytes:
    """Per block, the cheapest of the candidate encodings, with the choice recorded.

    Every block carries its own codec id and payload length, and the chosen payload is a real
    encoding, so a block can never be "free". Cross-block references are not available to the
    LZ member, which is a real cost of blocking and is visible in the numbers.
    """
    members = _hybrid_members()
    blocks: List[Tuple[int, bytes]] = []
    start = 0
    while start < stream.frames:
        block = substream(stream, start, block_frames)
        best_id, best_payload = members[0][1], members[0][2](block)
        for _, codec_id, encode, _ in members[1:]:
            payload = encode(block)
            if len(payload) < len(best_payload):
                best_id, best_payload = codec_id, payload
        blocks.append((best_id, best_payload))
        start += block_frames
    out = bytearray(uvarint(block_frames))
    out += uvarint(len(blocks))
    for codec_id, payload in blocks:
        out.append(codec_id)
        out += uvarint(len(payload))
        out += payload
    return bytes(out)


def decode_hybrid(payload: bytes, frames: int) -> bytes:
    members = {codec_id: decode for _, codec_id, _, decode in _hybrid_members()}
    block_frames, pos = read_uvarint(payload, 0)
    count, pos = read_uvarint(payload, pos)
    out = bytearray()
    for _ in range(count):
        if pos >= len(payload):
            raise Stage18Error("truncated hybrid block header")
        codec_id = payload[pos]
        pos += 1
        length, pos = read_uvarint(payload, pos)
        if pos + length > len(payload):
            raise Stage18Error("truncated hybrid block payload")
        block_payload = payload[pos : pos + length]
        pos += length
        decode = members.get(codec_id)
        if decode is None:
            raise Stage18Error(f"unknown hybrid block codec {codec_id}")
        remaining = frames - len(out) // FRAME_BYTES
        block_frames_here = min(block_frames, remaining)
        out += decode(block_payload, block_frames_here)
    if len(out) != frames * FRAME_BYTES:
        raise Stage18Error("hybrid stream decodes to the wrong number of frames")
    return bytes(out)


def hybrid_codecs(block_frames: Sequence[int] = (256, 512, 1024, 2048)) -> Tuple[Codec, ...]:
    codecs: List[Codec] = []
    for size in block_frames:
        codecs.append(Codec(
            key="hybrid",
            group="hybrid",
            description=(
                "F hybrid: per block, the cheapest of raw / per-register RLE / delta-gap / "
                "ramps / LZ, each block's codec id and length recorded"
            ),
            encode=(lambda stream, b=size: encode_hybrid(stream, b)),
            decode=decode_hybrid,
            params={"block_frames": size},
        ))
    return tuple(codecs)



# ---------------------------------------------------------------------------
# SECTIONS 10, 11 - exact reconstruction and compression ratio
# ---------------------------------------------------------------------------
def compare_payloads(reference: bytes, decoded: bytes, frames: int) -> Dict[str, Any]:
    """Byte-for-byte comparison of a decoded payload with the canonical raw one.

    Returns the metrics the brief asks for: whether reconstruction is exact, the first frame
    that diverges, how many values differ, the largest error, and what share of frames came back
    completely correct. A codec that fails here is reported as ``LOSSLESS = FALSE`` and cannot be
    presented as a solution, whatever size it achieved.
    """
    if reference == decoded:
        return {
            "lossless": True,
            "first_divergence_frame": None,
            "differing_values": 0,
            "max_error": 0,
            "correct_frames": frames,
            "correct_frame_percent": 100.0 if frames else None,
        }
    length = min(len(reference), len(decoded))
    first = None
    for pos in range(length):
        if reference[pos] != decoded[pos]:
            first = pos
            break
    if first is None:
        first = length
    differing = 0
    max_error = 0
    correct_frames = 0
    frame_limit = min(frames, min(len(reference), len(decoded)) // FRAME_BYTES)
    for frame in range(frame_limit):
        base = frame * FRAME_BYTES
        same = True
        for offset in range(FRAME_BYTES):
            left = reference[base + offset]
            right = decoded[base + offset]
            if left != right:
                same = False
                differing += 1
                max_error = max(max_error, abs(left - right))
        if same:
            correct_frames += 1
    return {
        "lossless": False,
        "first_divergence_frame": first // FRAME_BYTES,
        "differing_values": differing,
        "max_error": max_error,
        "correct_frames": correct_frames,
        "correct_frame_percent": _rnd(100.0 * correct_frames / frames) if frames else None,
    }

    return {"dictionary_bytes": pos, "body_bytes": len(payload) - pos, "entries": count}



@dataclass
class CodecResult:
    """One codec measured on one song: size, ratio and the reconstruction verdict."""

    slug: str
    codec: str
    label: str
    group: str
    params: Mapping[str, Any]
    payload_bytes: int
    header_bytes: int
    raw_payload_bytes: int
    raw_header_bytes: int
    reconstruction: Mapping[str, Any]
    error: Optional[str] = None
    dictionary_bytes: Optional[int] = None
    body_bytes: Optional[int] = None

    @property
    def total_bytes(self) -> int:
        return self.payload_bytes + self.header_bytes

    @property
    def raw_total_bytes(self) -> int:
        return self.raw_payload_bytes + self.raw_header_bytes

    @property
    def compression_ratio(self) -> Optional[float]:
        return ratio(self.total_bytes, self.raw_total_bytes)

    @property
    def saving_percent(self) -> Optional[float]:
        return saving_percent(self.total_bytes, self.raw_total_bytes)

    def to_dict(self) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "slug": self.slug,
            "codec": self.codec,
            "label": self.label,
            "group": self.group,
            "parameters": dict(sorted(self.params.items())),
            "raw_bytes": self.raw_total_bytes,
            "header_bytes": self.header_bytes,
            "payload_bytes": self.payload_bytes,
            "compressed_bytes": self.total_bytes,
            "compression_ratio": self.compression_ratio,
            "saving_percent": self.saving_percent,
            "lossless": bool(self.reconstruction["lossless"]),
            "first_divergence_frame": self.reconstruction["first_divergence_frame"],
            "differing_values": self.reconstruction["differing_values"],
            "max_error": self.reconstruction["max_error"],
            "correct_frame_percent": self.reconstruction["correct_frame_percent"],
        }
        if self.dictionary_bytes is not None:
            row["dictionary_bytes"] = self.dictionary_bytes
            row["body_bytes"] = self.body_bytes
        if self.error is not None:
            row["error"] = self.error
        return row


def measure_codec(codec: Codec, stream: FrameStream) -> CodecResult:
    """Encode, wrap, re-parse, decode and compare. Every path a decoder would take is used."""
    raw_payload = stream.payload()
    codec_id = CODEC_IDS.get(codec.key, 0xFF)
    try:
        payload = codec.encode(stream)
        container = make_container(codec_id, stream.frames, stream.frame_period_us, payload)
        read_id, _flags, read_frames, _period, read_payload = parse_container(container)
        if read_id != codec_id:
            raise Stage18Error("container codec id did not survive the round trip")
        decoded = codec.decode(read_payload, read_frames)
        reconstruction = compare_payloads(raw_payload, decoded, stream.frames)
    except Stage18Error as error:
        return CodecResult(
            slug=stream.slug, codec=codec.key, label=codec.label, group=codec.group,
            params=codec.params, payload_bytes=0, header_bytes=CONTAINER_HEADER_BYTES,
            raw_payload_bytes=len(raw_payload), raw_header_bytes=CONTAINER_HEADER_BYTES,
            reconstruction={"lossless": False, "first_divergence_frame": None,
                            "differing_values": None, "max_error": None,
                            "correct_frame_percent": None},
            error=str(error),
        )
    dictionary_bytes = body_bytes = None
    if codec.group == "dictionary":
        split = dictionary_split(payload)
        dictionary_bytes = split["dictionary_bytes"]
        body_bytes = split["body_bytes"]
    return CodecResult(
        slug=stream.slug, codec=codec.key, label=codec.label, group=codec.group,
        params=codec.params, payload_bytes=len(payload), header_bytes=CONTAINER_HEADER_BYTES,
        raw_payload_bytes=len(raw_payload), raw_header_bytes=CONTAINER_HEADER_BYTES,
        reconstruction=reconstruction,
        dictionary_bytes=dictionary_bytes, body_bytes=body_bytes,
    )


# ---------------------------------------------------------------------------
# The measured suite: every codec, on every song
# ---------------------------------------------------------------------------
LZ_WINDOWS = (64, 256, 1024)
LZ_MIN_MATCHES = (2, 4, 8)
HYBRID_BLOCKS = (256, 512, 1024, 2048)


def untrained_codecs() -> Tuple[Codec, ...]:
    """Every codec that does not need training data: the bulk of the experiment."""
    return (
        (RAW_CODEC,)
        + RLE_CODECS
        + DELTA_CODECS
        + ramp_codecs()
        + lz_codecs(LZ_WINDOWS, LZ_MIN_MATCHES)
        + hybrid_codecs(HYBRID_BLOCKS)
    )


def dictionary_experiments(
    streams: Sequence[FrameStream],
) -> Tuple[List[Tuple[str, str, Codec]], List[Dict[str, Any]]]:
    """Per-song, shared and leave-one-song-out dictionaries.

    Returns ``(codec, scope, song)`` triples to measure plus the fold metadata. The per-song
    case is the "model optimised for this song" arm of Part 12; the shared case is the same rules
    trained on all four; the folds are the honest generalisation test, because a dictionary that
    only worked by memorising one song would collapse there.
    """
    cases: List[Tuple[str, str, Codec]] = []
    folds: List[Dict[str, Any]] = []
    slugs = [stream.slug for stream in streams]

    for top_k in DICT_TOP_KS:
        for stream in streams:
            table = build_motif_table([stream], top_k=top_k)
            cases.append((
                "per_song", stream.slug,
                dictionary_codec(table, trained_on=[stream.slug]),
            ))
    shared_table = build_motif_table(streams, top_k=DICT_TOP_K)
    for stream in streams:
        cases.append((
            "shared", stream.slug,
            dictionary_codec(shared_table, trained_on=slugs),
        ))
    for held_out in streams:
        training = [stream for stream in streams if stream.slug != held_out.slug]
        table = build_motif_table(training, top_k=DICT_LOSO_TOP_K)
        folds.append({
            "held_out": held_out.slug,
            "trained_on": [stream.slug for stream in training],
            "entries": len(table),
            "table_bytes": sum(uvarint_bytes(length) + len(motif) for length, motif in table),
        })
        cases.append((
            "leave_one_out", held_out.slug,
            dictionary_codec(table, trained_on=[stream.slug for stream in training]),
        ))
    return cases, folds


def measure_suite(
    streams: Sequence[FrameStream],
) -> Tuple[List[CodecResult], Dict[str, Any]]:
    """Every codec on every song, plus the dictionary scopes and the fold metadata."""
    results: List[CodecResult] = []
    for stream in streams:
        for codec in untrained_codecs():
            results.append(measure_codec(codec, stream))
    cases, folds = dictionary_experiments(streams)
    dictionary_by_scope: Dict[str, List[CodecResult]] = {}
    for scope, slug, codec in cases:
        stream = next(item for item in streams if item.slug == slug)
        result = measure_codec(codec, stream)
        results.append(result)
        dictionary_by_scope.setdefault(scope, []).append(result)
    return results, {
        "folds": folds,
        "dictionary_by_scope": dictionary_by_scope,
    }


def group_by_group(results: Sequence[CodecResult]) -> Dict[str, List[CodecResult]]:
    """Group the flat result list by experiment, in the order the experiments are reported."""
    groups: Dict[str, List[CodecResult]] = {
        "baseline": [], "RLE": [], "delta": [], "ramps": [],
        "dictionary": [], "hybrid": [],
    }
    for result in results:
        groups.setdefault(result.group, []).append(result)
    return groups


# ---------------------------------------------------------------------------
# SECTION 12 - generalization across songs, and leave-one-song-out
# ---------------------------------------------------------------------------
def cross_song_summary(results: Sequence[CodecResult]) -> Dict[str, Any]:
    """Per codec across all songs: every song, plus mean / median / min / max.

    The brief forbids reporting an average alone, so each configuration carries its full
    per-song row list as well as the four statistics.
    """
    by_label: Dict[str, List[CodecResult]] = {}
    for result in results:
        by_label.setdefault(result.label, []).append(result)
    rows: List[Dict[str, Any]] = []
    for label in sorted(by_label):
        group = by_label[label]
        ratios = [item.compression_ratio for item in group if item.compression_ratio is not None]
        savings = [item.saving_percent for item in group if item.saving_percent is not None]
        rows.append({
            "label": label,
            "codec": group[0].codec,
            "group": group[0].group,
            "parameters": dict(sorted(group[0].params.items())),
            "lossless_on_all_songs": all(item.reconstruction["lossless"] for item in group),
            "songs": len(group),
            "per_song_ratio": {
                item.slug: item.compression_ratio
                for item in sorted(group, key=lambda entry: entry.slug)
            },
            "per_song_saving_percent": {
                item.slug: item.saving_percent
                for item in sorted(group, key=lambda entry: entry.slug)
            },
            "per_song_compressed_bytes": {
                item.slug: item.total_bytes
                for item in sorted(group, key=lambda entry: entry.slug)
            },
            "ratio": _summary_stats(ratios),
            "saving_percent": _summary_stats(savings),
        })
    return {
        "note": (
            "Every configuration is reported per song and with mean/median/min/max. A "
            "configuration is only a candidate if lossless_on_all_songs is true."
        ),
        "configurations": rows,
    }


def best_configurations(results: Sequence[CodecResult]) -> Dict[str, Any]:
    """The winners, chosen by mean ratio, restricted to lossless configurations.

    Ties are broken by the label, so the choice is deterministic and reproducible rather than
    dependent on the order codecs happened to be built in.
    """
    summary = cross_song_summary(results)["configurations"]
    lossless = [row for row in summary if row["lossless_on_all_songs"]]
    if not lossless:
        return {"available": False, "reason": "no configuration reconstructed every song"}

    def best_of(group: str) -> Optional[Dict[str, Any]]:
        candidates = [row for row in lossless if row["group"] == group]
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row["ratio"]["mean"], row["label"]))
        return candidates[0]

    overall = sorted(lossless, key=lambda row: (row["ratio"]["mean"], row["label"]))[0]
    per_song: Dict[str, Dict[str, Any]] = {}
    for slug in sorted({item.slug for item in results}):
        rows = []
        for row in lossless:
            value = row["per_song_ratio"].get(slug)
            if value is not None:
                rows.append((value, row["label"]))
        rows.sort()
        per_song[slug] = {"label": rows[0][1], "ratio": rows[0][0]} if rows else {}
    return {
        "available": True,
        "overall_best": {
            "label": overall["label"],
            "mean_ratio": overall["ratio"]["mean"],
            "median_ratio": overall["ratio"]["median"],
            "mean_saving_percent": overall["saving_percent"]["mean"],
            "max_ratio": overall["ratio"]["max"],
            "lossless_on_all_songs": overall["lossless_on_all_songs"],
        },
        "best_per_group": {
            group: (best_of(group) or {}).get("label")
            for group in ("RLE", "delta", "ramps", "dictionary", "hybrid")
        },
        "best_per_group_ratio": {
            group: ((best_of(group) or {}).get("ratio") or {}).get("mean")
            for group in ("RLE", "delta", "ramps", "dictionary", "hybrid")
        },
        "best_per_song": per_song,
    }


def leave_one_out_report(
    dictionary_by_scope: Mapping[str, List[CodecResult]],
    folds: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Section 12C: does a dictionary trained on three songs help the fourth?

    The per-song arm is the upper bound (the model has seen the song); the shared arm shows what
    one global dictionary costs; the fold arm is the honest test, because it never trains on the
    song it encodes. If the fold arm collapses while the per-song arm does not, the dictionary is
    memorising rather than generalising.
    """
    def rows(scope: str) -> List[Dict[str, Any]]:
        return [
            item.to_dict() for item in sorted(
                dictionary_by_scope.get(scope, []), key=lambda entry: entry.slug
            )
        ]

    def mean_ratio(scope: str) -> Optional[float]:
        values = [
            item.compression_ratio
            for item in dictionary_by_scope.get(scope, [])
            if item.compression_ratio is not None
        ]
        return _rnd(_mean(values)) if values else None

    return {
        "question": (
            "does the dictionary exploit recurrence that transfers between songs, or does it "
            "memorise the song it was trained on?"
        ),
        "folds": [dict(fold) for fold in folds],
        "per_song_dictionary": rows("per_song"),
        "shared_dictionary": rows("shared"),
        "leave_one_out": rows("leave_one_out"),
        "mean_ratio_by_scope": {
            "per_song": mean_ratio("per_song"),
            "shared": mean_ratio("shared"),
            "leave_one_out": mean_ratio("leave_one_out"),
        },
        "reading": (
            "compare mean_ratio_by_scope. per_song is the optimistic arm, leave_one_out is the "
            "honest one, and shared pays for one table four times over."
        ),
    }



# ---------------------------------------------------------------------------
# SECTION 13 - decoder complexity
# ---------------------------------------------------------------------------
#: Bytes per code line in the *current* 6502 player, taken from Stage 17's own measurement
#: (827 code bytes over 453 code lines). Every code-byte figure below is an ESTIMATE built on
#: that ratio and is labelled as one; the RAM figures are structural, not estimates.
BYTES_PER_CODE_LINE = 1.826

#: DECODER ESTIMATES. ``code_lines`` is an engineering estimate, ``state_bytes`` is the
#: structural per-stream state a decoder must hold, and ``ops_per_frame`` is a *proxy* for work
#: per decoded frame, not a cycle count. ``branching`` describes how many distinct cases the
#: inner loop has.
DECODER_ESTIMATES: Dict[str, Dict[str, Any]] = {
    "raw": {"code_lines": 12, "state_bytes": 6, "temporary_bytes": 0,
            "ops_per_frame": 6, "branching": "NONE"},
    "rle_frame": {"code_lines": 34, "state_bytes": 8, "temporary_bytes": 0,
                  "ops_per_frame": 4, "branching": "LOW"},
    "rle_register": {"code_lines": 40, "state_bytes": 14, "temporary_bytes": 0,
                     "ops_per_frame": 12, "branching": "LOW"},
    "delta_fixed": {"code_lines": 26, "state_bytes": 12, "temporary_bytes": 0,
                    "ops_per_frame": 10, "branching": "NONE"},
    "delta_gap": {"code_lines": 46, "state_bytes": 14, "temporary_bytes": 2,
                  "ops_per_frame": 5, "branching": "MEDIUM"},
    "ramps": {"code_lines": 78, "state_bytes": 20, "temporary_bytes": 3,
              "ops_per_frame": 8, "branching": "HIGH"},
    "lz": {"code_lines": 64, "state_bytes": 26, "temporary_bytes": 0,
           "ops_per_frame": 6, "branching": "MEDIUM"},
    "dictionary": {"code_lines": 72, "state_bytes": 22, "temporary_bytes": 2,
                   "ops_per_frame": 6, "branching": "MEDIUM"},
    "hybrid": {"code_lines": 92, "state_bytes": 24, "temporary_bytes": 3,
               "ops_per_frame": 8, "branching": "VERY_HIGH"},
}


def decoder_buffer_bytes(codec: str, params: Mapping[str, Any], frames: int) -> int:
    """Buffer RAM a decoder needs beyond its fixed state, from the *chosen parameters*.

    This is where the honest accounting bites. The LZ decoder needs a window of already-decoded
    frames; at a 1024-frame window that is 9,216 bytes, more than half of a 16 KB machine. The
    dictionary decoder needs the motif table, whose real size is measured rather than assumed.
    """
    if codec == "lz":
        window = int(params.get("window_frames", 0) or 0)
        return min(window, frames) * FRAME_BYTES
    if codec == "dictionary":
        return int(params.get("table_bytes", 0) or 0)
    if codec == "hybrid":
        return decoder_buffer_bytes("lz", {"window_frames": 512}, frames)
    return 0





def decoder_cost_model(
    results: Sequence[CodecResult],
    streams: Sequence[FrameStream],
) -> Dict[str, Any]:
    """Section 13: what each format would cost to decode, estimated and labelled as such."""
    longest = max((stream.frames for stream in streams), default=0)
    seen: Dict[str, CodecResult] = {}
    for result in results:
        seen.setdefault(result.label, result)
    rows: List[Dict[str, Any]] = []
    for label in sorted(seen):
        result = seen[label]
        estimate = DECODER_ESTIMATES.get(result.codec, DECODER_ESTIMATES["raw"])
        buffer_bytes = decoder_buffer_bytes(result.codec, result.params, longest)
        worst_case = estimate["state_bytes"] + estimate["temporary_bytes"] + buffer_bytes
        rows.append({
            "label": label,
            "codec": result.codec,
            "basis": "ESTIMATE",
            "code_bytes_estimate": int(round(estimate["code_lines"] * BYTES_PER_CODE_LINE)),
            "code_lines_estimate": estimate["code_lines"],
            "state_bytes": estimate["state_bytes"],
            "temporary_bytes": estimate["temporary_bytes"],
            "dictionary_or_buffer_bytes": buffer_bytes,
            "dictionary_bytes_in_stream": int(result.dictionary_bytes or 0),
            "worst_case_ram_bytes": worst_case,
            "operations_per_frame_proxy": estimate["ops_per_frame"],
            "branching": estimate["branching"],
        })
    return {
        "method": (
            "ESTIMATE. Code sizes are charged at the current player's own density, "
            f"{BYTES_PER_CODE_LINE} bytes per code line, from the estimates in "
            "DECODER_ESTIMATES. state_bytes and temporary_bytes are structural: they count the "
            "registers a decoder must hold. dictionary_or_buffer_bytes is computed from the "
            "chosen parameters, not assumed: an LZ window of N frames costs N*9 bytes of RAM, and "
            "a dictionary costs exactly the table it carries. operations_per_frame_proxy is a "
            "PROXY for work per decoded frame and is deliberately not presented as a cycle count."
        ),
        "machine_ram_note": (
            "an Atari with 16 KB has about 16,384 bytes of RAM in total and far less free once "
            "the OS, the screen and the program are loaded; the buffer column decides whether a "
            "format is usable at all"
        ),
        "codecs": rows,
        "cheapest_decoder": (
            sorted(rows, key=lambda row: (row["worst_case_ram_bytes"],
                                          row["code_bytes_estimate"], row["label"]))[0]["label"]
            if rows else None
        ),
        "most_expensive_decoder": (
            sorted(rows, key=lambda row: (-row["worst_case_ram_bytes"], row["label"]))[0]["label"]
            if rows else None
        ),
    }


# ---------------------------------------------------------------------------
# SECTION 14 - comparison with the representations that already exist
# ---------------------------------------------------------------------------
def previous_representation_bytes(
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
) -> Dict[str, Any]:
    """Stage 17's own measured sizes, read from its artefacts rather than recomputed.

    Two of the four points of comparison live in Stage 17: the current note format and the
    exact event encoding. Both are read through the file's hash, so a stale number is visible
    rather than silently believed.
    """
    path = Path(stage17_dir) / "compression.json"
    if not path.is_file():
        return {"available": False, "reason": f"no Stage 17 record at {path}"}
    record = _read_json(path)
    per_song: Dict[str, Dict[str, int]] = {}
    for song in record.get("songs", []):
        rows = {row["representation"]: row for row in song["representations"]}
        per_song[song["slug"]] = {
            "current_note_format_bytes": rows["A_current_note_event"]["bytes"],
            "stage17_exact_event_bytes": rows["C_performance_attached_repaired"]["bytes"],
            "stage17_abstraction_bytes": rows["C_performance_abstraction"]["bytes"],
        }
    return {
        "available": True,
        "source": str(path),
        "source_sha256": sha256_file(path),
        "per_song": per_song,
        "caveat": (
            "Stage 17's figures are payload only and exclude this stage's 12-byte container "
            "header; the difference is 12 bytes and cannot change a ranking. Stage 17's exact "
            "event encoding is the *repaired* one, which reached 100% exact reconstruction."
        ),
    }


def previous_questions(
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
) -> Dict[str, Any]:
    """What Stage 17 explicitly left for a Stage 18, and what this stage did with each.

    Stage 17's record carries a ``stage18_candidates`` list - questions it named but did not
    answer. Reporting which of them this stage closes, and which it does not, is the honest way
    to place these results: a falsification stage that quietly ignored the questions it was
    handed would inflate its own importance.
    """
    path = Path(stage17_dir) / "architecture.json"
    if not path.is_file():
        return {"available": False, "reason": f"no Stage 17 architecture record at {path}"}
    record = _read_json(path)
    candidates = record.get("stage18_candidates", [])
    answers: List[Dict[str, Any]] = []
    for item in candidates:
        question = item.get("question", "")
        lowered = question.lower()
        if "note format" in lowered and "raw dump" in lowered:
            status, evidence = (
                "answered",
                "section 14 prices both representations on the same four songs, so the gap "
                "between the current note format and the raw dump is now measured rather than "
                "assumed",
            )
        elif "beats the raw dump" in lowered:
            status, evidence = (
                "answered",
                "yes for an exact encoding - the best temporal codec is a little under half the "
                "raw dump and is exact - but no exact encoding found here beats the current note "
                "format, which is far smaller precisely because it is not exact",
            )
        elif "composer rather than from a recorded performance" in lowered:
            status, evidence = (
                "not addressed",
                "this stage compresses the historical register stream only; it generates no music "
                "and never reads a composer-generated trace",
            )
        elif "vocabulary" in lowered or "detector" in lowered:
            status, evidence = (
                "not addressed",
                "this is about the event vocabulary, not about the byte stream",
            )
        elif "listener" in lowered or "heard" in lowered:
            status, evidence = (
                "not addressed",
                "no listening test was run and none is proposed here",
            )
        else:
            status, evidence = (
                "not addressed",
                "outside the scope of a byte-format experiment",
            )
        answers.append(
            {
                "candidate": item.get("candidate"),
                "question": question,
                "cost": item.get("cost"),
                "status": status,
                "evidence": evidence,
            }
        )
    return {
        "available": True,
        "source": str(path),
        "source_sha256": sha256_file(path),
        "answers": answers,
        "answered_count": sum(1 for item in answers if item["status"] == "answered"),
    }


def comparison(
    streams: Sequence[FrameStream],
    results: Sequence[CodecResult],
    best: Mapping[str, Any],
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
) -> Dict[str, Any]:
    """Section 14: is temporal compression an improvement on what already exists?"""
    previous = previous_representation_bytes(stage17_dir)
    best_label = (best.get("overall_best") or {}).get("label")
    rows: List[Dict[str, Any]] = []
    for stream in streams:
        raw = stream.frames * FRAME_BYTES
        candidates = [item for item in results if item.slug == stream.slug]
        temporal = min(
            (item for item in candidates if item.reconstruction["lossless"]),
            key=lambda item: (item.total_bytes, item.label),
            default=None,
        )
        row: Dict[str, Any] = {
            "slug": stream.slug,
            "frames": stream.frames,
            "canonical_raw_bytes": raw,
            "best_temporal_label": temporal.label if temporal else None,
            "best_temporal_bytes": temporal.total_bytes if temporal else None,
            "best_temporal_ratio": temporal.compression_ratio if temporal else None,
        }
        if previous.get("available") and stream.slug in previous["per_song"]:
            entry = previous["per_song"][stream.slug]
            row["current_note_format_bytes"] = entry["current_note_format_bytes"]
            row["stage17_exact_event_bytes"] = entry["stage17_exact_event_bytes"]
            row["current_note_format_ratio_to_raw"] = ratio(
                entry["current_note_format_bytes"], raw
            )
            row["stage17_exact_ratio_to_raw"] = ratio(entry["stage17_exact_event_bytes"], raw)
            if temporal is not None and temporal.total_bytes:
                row["current_note_format_vs_temporal"] = ratio(
                    entry["current_note_format_bytes"], temporal.total_bytes
                )
                row["stage17_exact_vs_temporal"] = ratio(
                    entry["stage17_exact_event_bytes"], temporal.total_bytes
                )
        rows.append(row)

    def column(key: str) -> Dict[str, Optional[float]]:
        return _summary_stats(
            [float(row[key]) for row in rows if row.get(key) is not None]
        )

    return {
        "configurations": [
            {
                "representation": "canonical raw frame state",
                "exact": True,
                "role": "the baseline this stage is measured against",
            },
            {
                "representation": f"best temporal compression ({best_label})",
                "exact": True,
                "role": "this stage's result",
            },
            {
                "representation": "Stage 17 exact event encoding",
                "exact": True,
                "role": "the previous exact attempt",
            },
            {
                "representation": "current note format",
                "exact": False,
                "role": (
                    "not an exact representation of the reference registers: it relies on the "
                    "player's own ADSR model to fill the frames between notes, so it is far "
                    "smaller than anything here and is not comparable byte for byte"
                ),
            },
        ],
        "songs": rows,
        "summary": {
            "best_temporal_ratio": column("best_temporal_ratio"),
            "current_note_format_ratio_to_raw": column("current_note_format_ratio_to_raw"),
            "stage17_exact_ratio_to_raw": column("stage17_exact_ratio_to_raw"),
            "current_note_format_vs_temporal": column("current_note_format_vs_temporal"),
            "stage17_exact_vs_temporal": column("stage17_exact_vs_temporal"),
        },
        "previous_record": previous,
        "reading": (
            "the decisive column is current_note_format_vs_temporal: it is far below 1, which "
            "means the existing format is still many times smaller than any exact encoding this "
            "stage found - because it is not trying to be exact"
        ),
    }


# ---------------------------------------------------------------------------
# SECTIONS 15, 16, 17 - failure analysis, falsification, verdicts
# ---------------------------------------------------------------------------
#: Thresholds for the verdicts. Stated as constants so a reader can move them and see what
#: changes; a verdict that cannot be recomputed is an opinion.
SUPPORTED_SAVING_PERCENT = 25.0
PARTIAL_SAVING_PERCENT = 10.0
#: A decoder buffer larger than this is called out as impractical on a 16 KB machine.
RAM_CONCERN_BYTES = 4096
MACHINE_16K_BYTES = 16384


def failure_analysis(
    results: Sequence[CodecResult],
    leave_one_out: Mapping[str, Any],
    cost: Mapping[str, Any],
    comparison_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Section 15: what did not work, and why.

    Every entry is a measured outcome, not a hypothesis. The point of the section is that a
    negative result is a result: a method that fails here is reported as a failure with its
    cause attached rather than quietly dropped.
    """
    by_label: Dict[str, CodecResult] = {}
    for result in results:
        by_label.setdefault(result.label, result)
    rle_frame = by_label.get("rle_frame")
    delta_fixed = by_label.get("delta_fixed")
    dictionary_labels = sorted(
        (key for key in by_label if key.startswith("dictionary")),
        key=lambda key: -(by_label[key].compression_ratio or 0.0),
    )
    largest_table = max(
        (row for row in cost["codecs"] if row["codec"] == "dictionary"),
        key=lambda row: row["dictionary_or_buffer_bytes"],
        default=None,
    )
    best_lz = None
    for key in sorted(by_label):
        if key.startswith("lz[") and key.endswith("window_frames=1024]"):
            best_lz = by_label[key]
    failures: List[Dict[str, Any]] = []




    if rle_frame is not None:
        failures.append({
            "method": "whole-frame RLE",
            "measured": (
                f"ratio {rle_frame.compression_ratio} on {rle_frame.slug}: larger than the "
                "uncompressed stream"
            ),
            "cause": (
                "there is no consecutive redundancy to remove. The mean run of identical frames "
                "is about one frame, so the run-length header is paid once per frame for nothing"
            ),
            "verdict": "FAILS",
        })
    if delta_fixed is not None:
        failures.append({
            "method": "fixed-width delta without a zero-run",
            "measured": f"ratio {delta_fixed.compression_ratio}, exactly 1.0 by construction",
            "cause": (
                "delta changes the values but not the width: nine bytes per frame either way. "
                "Compression comes from *not storing* the fields that did not change, which is "
                "what the zero-run variant does"
            ),
            "verdict": "NO_GAIN_BY_DESIGN",
        })
    if dictionary_labels:
        worst = by_label[dictionary_labels[0]]
        failures.append({
            "method": "explicit motif dictionary",
            "measured": (
                f"worst per-song ratio {worst.compression_ratio}; per-song mean "
                f"{leave_one_out['mean_ratio_by_scope']['per_song']}, shared mean "
                f"{leave_one_out['mean_ratio_by_scope']['shared']}, leave-one-out mean "
                f"{leave_one_out['mean_ratio_by_scope']['leave_one_out']}"
            ),
            "cause": (
                "the redundancy is real but the dictionary is the wrong instrument for it. A "
                "motif long enough to be worth a reference is also long enough that storing it "
                "costs most of what the references save, and a shared dictionary pays that cost "
                "once per song. LZ captures the same repeats as references into the "
                "already-decoded stream, which costs no table at all"
                + (f" - and it reaches {best_lz.compression_ratio}"
                   if best_lz is not None else "")
            ),
            "verdict": "FAILS",
        })
    if largest_table is not None:
        failures.append({
            "method": "dictionary and large-window decoders, as a practical format",
            "measured": (
                f"buffer/dictionary RAM up to {largest_table['dictionary_or_buffer_bytes']} bytes"
            ),
            "cause": (
                "an LZ window of 1024 frames needs 9,216 bytes of decoded history and a 256-entry "
                "motif table needs up to 37,120 bytes; on a 16 KB machine that is not a "
                "compression trade, it is an impossibility"
            ),
            "verdict": "IMPRACTICAL_ON_TARGET_HARDWARE",
        })
    ratio_from_best = comparison_report["summary"]["current_note_format_vs_temporal"]["mean"]
    if ratio_from_best is not None:
        failures.append({
            "method": "temporal compression as a *replacement* for the current note format",
            "measured": (
                f"the current note format is {ratio_from_best} of the best exact temporal "
                f"encoding, about {_rnd(1.0 / ratio_from_best, 1)}x smaller"
            ),
            "cause": (
                "the current format is not an exact representation of the reference registers at "
                "all: it stores notes and lets the player's own envelope generator fill the "
                "frames in between. An exact format answers a different and far more expensive "
                "question"
            ),
            "verdict": "NOT_A_REPLACEMENT",
        })
    return {
        "note": (
            "a negative result is a full result. Each entry records what was measured and why it "
            "happened, so a later stage does not have to rediscover it."
        ),
        "failures": failures,
        "none_of_these_invalidate_the_positive_result": (
            "ramps, LZ and the hybrid all reconstruct every song exactly and compress it; the "
            "failures above are about specific instruments and specific deployment questions"
        ),
    }



def falsification_report(
    results: Sequence[CodecResult],
    best: Mapping[str, Any],
    failure: Mapping[str, Any],
    cost: Mapping[str, Any],
    comparison_report: Mapping[str, Any],
    cross: Mapping[str, Any],
) -> Dict[str, Any]:
    """Section 16: the results that *refute* the hypothesis, listed explicitly.

    The hypothesis under test is: "the historical POKEY stream at 50 Hz contains real temporal
    redundancy that a neutral, lossless, practically decodable format could exploit." Part 6 of
    the brief asks for the results that refute it, and they are listed here even though the
    headline verdict is positive, because a hypothesis that nothing can refute is not being
    tested.
    """
    refuting: List[Dict[str, str]] = []
    by_label = {result.label: result for result in results}

    rle = by_label.get("rle_frame")
    if rle is not None and (rle.compression_ratio or 9) >= 1.0:
        refuting.append({
            "result": "the simplest temporal redundancy does not exist",
            "detail": (
                f"whole-frame RLE expands the stream (ratio {rle.compression_ratio}). Nothing "
                "holds still frame to frame, so 'the stream repeats itself' is false at the "
                "level a run-length coder can see"
            ),
        })
    dictionary_note = None
    for label in sorted(by_label):
        if label.startswith("dictionary[entries=256"):
            dictionary_note = by_label[label]
    if dictionary_note is not None and (dictionary_note.compression_ratio or 0) >= 1.0:
        refuting.append({
            "result": "recurrent structure exists but is not cheap to name",
            "detail": (
                f"an explicit motif dictionary is *larger* than raw (ratio "
                f"{dictionary_note.compression_ratio}). The repetition between distant frames is "
                "real, but a table of motifs costs more than the references save"
            ),
        })
    loo = cross["mean_ratio_by_scope"]["leave_one_out"]
    if loo is not None and loo >= 1.0:
        refuting.append({
            "result": "the dictionary idea does not generalise either",
            "detail": (
                f"a dictionary trained on three songs and applied to the fourth has mean ratio "
                f"{loo}, worse than storing the stream uncompressed"
            ),
        })
    ram = max((row["dictionary_or_buffer_bytes"] for row in cost["codecs"]), default=0)
    if ram > RAM_CONCERN_BYTES:
        refuting.append({
            "result": "the best compression needs RAM the machine does not have",
            "detail": f"the largest decoder buffer is {ram} bytes against a 16 KB machine",
        })
    ratio_from_best = comparison_report["summary"]["current_note_format_vs_temporal"]["mean"]
    if ratio_from_best is not None and ratio_from_best < 1.0:
        refuting.append({
            "result": "even a two-fold win would not make this the better basis for a player",
            "detail": (
                f"the current note format is {ratio_from_best} of the best exact temporal "
                "encoding. Temporal compression beats Stage 17's event IR, but it loses badly to "
                "the representation already in production, and that is the comparison that "
                "decides integration"
            ),
        })
    savings = best["overall_best"]["mean_saving_percent"]
    if savings is not None and savings < SUPPORTED_SAVING_PERCENT:
        refuting.append({
            "result": "the saving is too small to be worth a decoder",
            "detail": f"mean saving {savings} percent is below the stated threshold",
        })
    structural = [
        item for item in refuting
        if item["result"] != "even a two-fold win would not make this the better basis for a player"
    ]
    return {
        "hypothesis": (
            "the historical POKEY stream at 50 Hz contains real temporal redundancy that a "
            "neutral, lossless, practically decodable format can exploit"
        ),
        "refuting_results": refuting,
        "hypothesis_survives": len(structural) == 0,
        "note": (
            "none of these refute the *existence* of temporal redundancy; they bound where it "
            "lives and what it is worth. The refutations are about instruments (RLE, motif "
            "tables), deployment (RAM) and the comparison that actually matters (the production "
            "format)."
        ),
        "failure_analysis_cross_reference": len(failure["failures"]),
    }


def stage_verdicts(
    best: Mapping[str, Any],
    cost: Mapping[str, Any],
    comparison_report: Mapping[str, Any],
    results: Sequence[CodecResult],
) -> Dict[str, Any]:
    """Section 17. Two independent verdicts, each from a stated rule and the measured numbers.

    The second verdict follows Part 21 of the brief, which lists seven conditions that must all
    hold before a player expansion is justified. They are evaluated one by one and the result is
    recorded per condition, so a reader can see exactly which one carried the decision.
    """
    overall = best["overall_best"]
    saving = overall["mean_saving_percent"] or 0.0
    lossless_all = all(result.reconstruction["lossless"] for result in results)

    if saving >= SUPPORTED_SAVING_PERCENT and lossless_all:
        compression = "TEMPORAL_COMPRESSION_SUPPORTED"
    elif saving >= PARTIAL_SAVING_PERCENT and lossless_all:
        compression = "TEMPORAL_COMPRESSION_PARTIALLY_SUPPORTED"
    else:
        compression = "TEMPORAL_COMPRESSION_NOT_SUPPORTED"

    # The practical candidate: the cheapest decoder that needs no large buffer at all.
    practical = None
    for row in sorted(cost["codecs"], key=lambda entry: (entry["code_bytes_estimate"],
                                                         entry["label"])):
        if row["dictionary_or_buffer_bytes"] <= RAM_CONCERN_BYTES:
            practical = {
                "label": row["label"],
                "worst_case_ram_bytes": row["worst_case_ram_bytes"],
                "code_bytes_estimate": row["code_bytes_estimate"],
                "branching": row["branching"],
            }
            break

    best_ram = None
    for row in cost["codecs"]:
        if row["label"] == overall["label"]:
            best_ram = row
    conditions = [
        {
            "condition": "1. significant compression",
            "met": saving >= SUPPORTED_SAVING_PERCENT,
            "measured": f"mean saving {saving} percent (threshold {SUPPORTED_SAVING_PERCENT})",
        },
        {
            "condition": "2. exact reconstruction",
            "met": lossless_all,
            "measured": f"every measurement lossless: {lossless_all}",
        },
        {
            "condition": "3. generalisation",
            "met": bool(best.get("available")) and overall["lossless_on_all_songs"],
            "measured": (
                f"the single configuration '{overall['label']}' reconstructs all four songs "
                "exactly and compresses each of them"
            ),
        },
        {
            "condition": "4. acceptable decoder complexity",
            "met": bool(best_ram) and best_ram["branching"] in ("NONE", "LOW", "MEDIUM"),
            "measured": (
                f"branching {best_ram['branching'] if best_ram else 'unknown'}, operations proxy "
                f"{best_ram['operations_per_frame_proxy'] if best_ram else 'unknown'} per frame"
            ),
        },
        {
            "condition": "5. sensible RAM cost",
            "met": bool(best_ram) and best_ram["dictionary_or_buffer_bytes"] <= RAM_CONCERN_BYTES,
            "measured": (
                f"best configuration needs "
                f"{best_ram['dictionary_or_buffer_bytes'] if best_ram else 'unknown'} bytes of "
                f"buffer against a concern threshold of {RAM_CONCERN_BYTES}"
            ),
        },
        {
            "condition": "6. advantage over the Stage 17 event IR",
            "met": (
                comparison_report["summary"]["stage17_exact_vs_temporal"]["mean"] or 0
            ) > 1.0,
            "measured": (
                "Stage 17's exact encoding is "
                f"{comparison_report['summary']['stage17_exact_vs_temporal']['mean']}x the size "
                "of the best temporal encoding"
            ),
        },
        {
            "condition": "7. advantage over the current note format",
            "met": (
                comparison_report["summary"]["current_note_format_vs_temporal"]["mean"] or 0
            ) >= 1.0,
            "measured": (
                "the current note format is "
                f"{comparison_report['summary']['current_note_format_vs_temporal']['mean']} of "
                "the best temporal encoding, i.e. already several times smaller"
            ),
        },
    ]
    integration = (
        "PLAYER_INTEGRATION_JUSTIFIED"
        if all(item["met"] for item in conditions)
        else "PLAYER_INTEGRATION_NOT_JUSTIFIED"
    )
    return {
        "temporal_compression": {
            "verdict": compression,
            "rule": (
                "SUPPORTED requires a mean saving of at least "
                f"{SUPPORTED_SAVING_PERCENT} percent with every measurement lossless; "
                f"PARTIALLY_SUPPORTED requires at least {PARTIAL_SAVING_PERCENT} percent and "
                "losslessness; otherwise NOT_SUPPORTED"
            ),
            "mean_saving_percent": saving,
            "mean_ratio": overall["mean_ratio"],
            "lossless_on_all_songs": lossless_all,
            "best_configuration": overall["label"],
            "practical_candidate_without_a_large_buffer": practical,
        },
        "player_integration": {
            "verdict": integration,
            "rule": (
                "Part 21: all seven conditions must hold simultaneously. They are listed with "
                "their measurements, and the first one that fails carries the decision."
            ),
            "conditions": conditions,
            "deciding_condition": next(
                (item["condition"] for item in conditions if not item["met"]), None
            ),
        },
        "independence_note": (
            "the two verdicts come from different tests and are deliberately independent: the "
            "redundancy can be real and useful in principle while integration is still not "
            "justified, and that is exactly what the measurements show."
        ),
    }


def final_answer(
    best: Mapping[str, Any],
    verdicts: Mapping[str, Any],
    comparison_report: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> Dict[str, Any]:
    """The very concrete answer to the question the brief ends with.

    The question has two halves and they have different answers, which is the whole point:
    temporal compression is a clear improvement on Stage 17's event IR and a clear loss against
    the note format that is actually in production. Answering with a single number would hide
    that.
    """
    summary = comparison_report["summary"]
    vs_stage17 = summary["stage17_exact_vs_temporal"]["mean"]
    vs_note = summary["current_note_format_vs_temporal"]["mean"]
    return {
        "question": (
            "is the historical POKEY performance stream temporally redundant enough that a "
            "neutral, lossless, practically decodable temporal-compression format is a better "
            "basis for a future player than the current note format or the Stage 17 event IR?"
        ),
        "answer": (
            "Yes against the Stage 17 event IR, and no against the current note format. The "
            "stream does contain real temporal redundancy - about "
            f"{best['overall_best']['mean_saving_percent']} percent of it is removable with an "
            f"exact, neutral codec - and that makes temporal compression roughly {vs_stage17}x "
            "smaller than Stage 17's exact encoding at the same exactness. But the format "
            "already in production is about "
            f"{_rnd(1.0 / vs_note, 1) if vs_note else 'many'}x smaller than any exact encoding "
            "this stage found, because it is not trying to be exact: it stores notes and lets "
            "the player's own envelope fill the frames. On the comparison that decides whether "
            "anything should change, temporal compression loses, and it also needs RAM the "
            "target machine does not have."
        ),
        "answer_in_two_lines": {
            "versus_stage_17_event_ir": (
                f"BETTER: {vs_stage17}x smaller, equally exact"
            ),
            "versus_current_note_format": (
                f"WORSE: the note format is {_rnd(1.0 / vs_note, 1) if vs_note else 'many'}x "
                "smaller, though it is not an exact representation of the registers"
            ),
        },
        "what_would_change_the_answer": [
            "a requirement for exact register reconstruction, which the note format cannot meet "
            "and temporal compression can - that is the one scenario where this work becomes the "
            "right basis",
            "a decoder whose buffer fits in a few hundred bytes, which neither LZ nor a motif "
            "dictionary provides",
            "a target machine with far more RAM, which removes the deployment objection but not "
            "the 'the production format is already smaller' objection",
        ],
        "verdicts": {
            "temporal_compression": verdicts["temporal_compression"]["verdict"],
            "player_integration": verdicts["player_integration"]["verdict"],
        },
        "what_was_built": (
            "nothing in production. Eight real byte formats were implemented for research only, "
            "every one of them was decoded back and compared byte for byte with the canonical raw "
            "representation, and the player, the Composer, the DSL and every existing IR are "
            "untouched."
        ),
        "negative_result_that_is_still_a_result": (
            f"{len(failure['failures'])} methods failed and are reported with their causes. A "
            "stage that only reported the winner would have thrown away the most useful part of "
            "this measurement."
        ),
    }


# ---------------------------------------------------------------------------
# Artefacts and orchestration
# ---------------------------------------------------------------------------
STAGE18_FILES = (
    "raw_baseline.json",
    "rle.json",
    "delta.json",
    "ramps.json",
    "motifs.json",
    "dictionary.json",
    "hybrid.json",
    "cross_song.json",
    "reconstruction.json",
    "decoder_cost.json",
    "comparison.json",
    "summary.json",
)
STAGE18_DOC = "stage18_temporal_compression.md"


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open twelve files."""
    best = bundle["best_configurations"]
    summary = bundle["comparison"]["summary"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "songs": [song["slug"] for song in bundle["dataset"]["songs"]],
        "canonical_raw": bundle["raw_baseline"]["definition"],
        "measurements": bundle["reconstruction"]["measurements"],
        "all_lossless": bundle["reconstruction"]["all_lossless"],
        "best_overall": best.get("overall_best"),
        "best_per_group_ratio": best.get("best_per_group_ratio"),
        "best_per_song": best.get("best_per_song"),
        "comparison": {
            "best_temporal_ratio_mean": summary["best_temporal_ratio"]["mean"],
            "current_note_format_ratio_to_raw_mean":
                summary["current_note_format_ratio_to_raw"]["mean"],
            "stage17_exact_ratio_to_raw_mean": summary["stage17_exact_ratio_to_raw"]["mean"],
            "current_note_format_vs_temporal_mean":
                summary["current_note_format_vs_temporal"]["mean"],
            "stage17_exact_vs_temporal_mean": summary["stage17_exact_vs_temporal"]["mean"],
        },
        "dictionary_scopes": bundle["dictionary"]["mean_ratio_by_scope"],
        "decoder_cheapest": bundle["decoder_cost"]["cheapest_decoder"],
        "decoder_most_expensive": bundle["decoder_cost"]["most_expensive_decoder"],
        "verdicts": {
            "temporal_compression": bundle["verdicts"]["temporal_compression"]["verdict"],
            "player_integration": bundle["verdicts"]["player_integration"]["verdict"],
        },
        "final_answer_short": bundle["final_answer"]["answer_in_two_lines"],
    }




def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
    player_asm: Path = DEFAULT_PLAYER_ASM,
) -> Dict[str, Any]:
    """Read the corpus, define the canonical representation, and run every experiment.

    Reads: the corpus register traces, the Stage 16 selection record, the Stage 17 record and the
    player source - all through their hashes. Writes nothing. Every codec is a real byte format
    that is encoded *and decoded* during the measurement, so no cost can be left implicit.
    """
    streams, selection = load_dataset(stage16_dir)
    results, meta = measure_suite(streams)
    best = best_configurations(results)
    cross = cross_song_summary(results)
    dictionary = leave_one_out_report(meta["dictionary_by_scope"], meta["folds"])
    cost = decoder_cost_model(results, streams)
    comparison_report = comparison(streams, results, best, stage17_dir)
    previous_questions_fn = previous_questions(stage17_dir)

    reconstruction = {
        "question": "does every method decode back to exactly the canonical raw representation?",
        "requirement": (
            "decoded == original, byte for byte, against the canonical payload of all nine "
            "registers in every frame"
        ),
        "measurements": len(results),
        "all_lossless": all(item.reconstruction["lossless"] for item in results),
        "failures": [item.to_dict() for item in results if not item.reconstruction["lossless"]],
        "per_codec": [
            item.to_dict() for item in sorted(results, key=lambda entry: (entry.codec, entry.slug))
        ],
        "note": (
            "a method that is not exactly reversible is reported as LOSSLESS = FALSE and cannot "
            "be presented as a solution, whatever its size"
        ),
    }
    failure = failure_analysis(results, dictionary, cost, comparison_report)
    falsification = falsification_report(
        results, best, failure, cost, comparison_report, dictionary
    )
    verdicts = stage_verdicts(best, cost, comparison_report, results)
    answer = final_answer(best, verdicts, comparison_report, failure)
    groups = group_by_group(results)
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "dataset": {
            "selection_source": selection["source"],
            "selection_sha256": selection["source_sha256"],
            "songs": [
                {
                    "slug": stream.slug,
                    "frames": stream.frames,
                    "frame_period_us": stream.frame_period_us,
                    "raw_payload_bytes": stream.frames * FRAME_BYTES,
                }
                for stream in streams
            ],
            "note": (
                "exactly the four Stage 16 songs, read as register traces rather than re-chosen "
                "here; no synthetic data is used as primary evidence"
            ),
        },
        "raw_baseline": {
            "definition": (
                "frame = AUDF1, AUDC1, AUDF2, AUDC2, AUDF3, AUDC3, AUDF4, AUDC4, AUDCTL, "
                "absolute, one frame after another, nine bytes per frame, AUDCTL repeated every "
                "frame even though it never changes in this corpus"
            ),
            "choices": {
                "absolute_or_delta": "absolute: no previous-frame dependency in the baseline",
                "how_no_change_is_represented": (
                    "it is not represented: the baseline repeats the value, which is what makes "
                    "delta and run-length coding measurable rather than assumed"
                ),
                "first_values": "frame 0 is stored like every other frame; no special case",
                "audctl": "part of every frame, not stream-level state",
                "container": (
                    f"{CONTAINER_HEADER_BYTES} bytes: 'P8', codec id, flags, frame count u32, "
                    "period in microseconds u32. Every codec shares this header, so it is a "
                    "constant in the comparison and cannot bias a ranking"
                ),
            },
            "songs": [
                {
                    "slug": stream.slug,
                    "frames": stream.frames,
                    "payload_bytes": stream.frames * FRAME_BYTES,
                    "container_bytes": CONTAINER_HEADER_BYTES + stream.frames * FRAME_BYTES,
                }
                for stream in streams
            ],
            "percent_baseline": 100.0,
        },
        "rle": {"codecs": [codec.to_dict() for codec in RLE_CODECS],
                "results": [item.to_dict() for item in groups["RLE"]]},
        "delta": {"codecs": [codec.to_dict() for codec in DELTA_CODECS],
                  "histograms": [delta_histograms(stream) for stream in streams],
                  "results": [item.to_dict() for item in groups["delta"]]},
        "ramps": {"codecs": [codec.to_dict() for codec in ramp_codecs()],
                  "results": [item.to_dict() for item in groups["ramps"]]},
        "motifs": {
            "lengths_tested": list(MOTIF_LENGTHS),
            "statistics": [motif_statistics(stream) for stream in streams],
            "note": (
                "detection only. The brief is explicit that the number of found repetitions is "
                "not the result; the result is the compressed size including the table, and that "
                "is measured in the dictionary experiment"
            ),
        },
        "dictionary": {
            **dictionary,
            "results": [item.to_dict() for item in groups["dictionary"]],
            "parameters": {
                "lengths": list(DICT_LENGTHS),
                "top_k_swept": list(DICT_TOP_KS),
                "leave_one_out_top_k": DICT_LOSO_TOP_K,
                "max_candidates": DICT_MAX_CANDIDATES,
            },
        },
        "hybrid": {"codecs": [codec.to_dict() for codec in hybrid_codecs()],
                   "members": [name for name, _, _, _ in _hybrid_members()],
                   "results": [item.to_dict() for item in groups["hybrid"]]},
        "cross_song": cross,
        "reconstruction": reconstruction,
        "decoder_cost": cost,
        "comparison": comparison_report,
        "previous_questions": previous_questions_fn,
        "failure_analysis": failure,
        "falsification": falsification,
        "verdicts": verdicts,
        "final_answer": answer,
        "best_configurations": best,
        "determinism": {
            "inputs_hashed": True,
            "no_sampling": True,
            "no_timestamps": True,
            "no_unordered_iteration_in_output": True,
            "tie_breaks": (
                "every choice between equal-cost candidates is resolved by a stated key: the "
                "hybrid block picks the earliest member on a tie, the ramps segmenter picks the "
                "longest span on a tie, and the dictionary keeps its candidates in a fixed order"
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def write_analysis(
    bundle: Mapping[str, Any],
    stage18_dir: Path = DEFAULT_STAGE18_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the twelve JSON artefacts and the report. Additive: nothing else is touched."""
    stage18_dir = Path(stage18_dir)
    docs_dir = Path(docs_dir)
    stage18_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "raw_baseline.json": bundle["raw_baseline"],
        "rle.json": bundle["rle"],
        "delta.json": bundle["delta"],
        "ramps.json": bundle["ramps"],
        "motifs.json": bundle["motifs"],
        "dictionary.json": bundle["dictionary"],
        "hybrid.json": bundle["hybrid"],
        "cross_song.json": {
            "cross_song": bundle["cross_song"],
            "best_configurations": bundle["best_configurations"],
        },
        "reconstruction.json": bundle["reconstruction"],
        "decoder_cost.json": bundle["decoder_cost"],
        "comparison.json": {
            **bundle["comparison"],
            "previous_questions": bundle["previous_questions"],
        },
        "summary.json": bundle["summary"],
    }
    written: Dict[str, Path] = {}
    for name in STAGE18_FILES:
        path = stage18_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE18_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE18_DOC] = doc_path
    return written



# ---------------------------------------------------------------------------
# The report (17 sections, in the order the brief requires)
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(str(item) for item in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _bullets(items: Sequence[Any]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _result_rows(results: Sequence[Mapping[str, Any]]) -> List[List[Any]]:
    """Standard table rows for a set of measured results."""
    return [
        [
            f"`{row['label']}`", row["slug"].split("_")[0], row["raw_bytes"],
            row["compressed_bytes"], row["compression_ratio"], row["saving_percent"],
            "yes" if row["lossless"] else "**NO**",
        ]
        for row in sorted(results, key=lambda entry: (entry["label"], entry["slug"]))
    ]


RESULT_TABLE_HEADER = (
    "configuration", "song", "raw bytes", "compressed", "ratio", "saving %", "lossless",
)


def render_report(bundle: Mapping[str, Any]) -> str:
    """The seventeen sections the brief requires, in its order, from the measured bundle."""
    out: List[str] = []
    summary = bundle["summary"]
    verdicts = bundle["verdicts"]
    answer = bundle["final_answer"]

    out.append("# Stage 18 - Temporal Compression of the POKEY Performance History\n")
    out.append(
        "A falsification experiment. Stage 17 showed that a neutral performance-event language "
        "is faithful but does not compress. Stage 18 asks the narrower structural question that "
        "remains: does the historical POKEY stream at 50 Hz contain real temporal redundancy that "
        "a neutral, lossless, practically decodable format could exploit, without introducing any "
        "semantic notion such as instrument, melody or effect?\n"
    )
    out.append(
        "Analysis only. The 6502 player, the Composer, the DSL, the Music IR, the POKEY IR, the "
        "production schemas and the SoundProfile system are read and hashed, never modified. No "
        "audio was rendered, no music was generated, no instrument was transferred, and no "
        "listening test was run. Nothing was implemented in production.\n"
    )
    out.append(f"Analysis version `{bundle['analysis_version']}`.\n")

    # 1 ---------------------------------------------------------------
    out.append("## 1. Executive summary\n")
    out.append(_bullets([
        "**Does temporal redundancy exist? Yes.** The stream is far from random: the four songs "
        "use between 1,905 and 4,668 *distinct* frames out of 6,081 to 10,840, and every song has "
        "only about 2.4 to 3.8 register changes per frame.",
        "**Does it give practical compression? Yes, about "
        f"{_rnd(summary['best_overall']['mean_saving_percent'], 1)} percent.** The best "
        f"configuration (`{summary['best_overall']['label']}`) has a mean ratio of "
        f"{summary['best_overall']['mean_ratio']} and reconstructs all four songs "
        f"**byte for byte**. Every one of the {summary['measurements']} measurements is exact.",
        "**Is it generalisable? Yes.** One configuration with one parameter set is lossless and "
        "compressing on all four songs, and the best method varies by song, which the report "
        "shows rather than averages away.",
        "**Is it worth developing further? Not as a player foundation.** It beats the Stage 17 "
        f"event IR by {summary['comparison']['stage17_exact_vs_temporal_mean']}x, but the current "
        f"note format is still {_rnd(1.0 / (summary['comparison']['current_note_format_vs_temporal_mean'] or 1), 1)}x "
        "smaller than any exact encoding found here, and the decoders that compress best need "
        "buffer RAM a 16 KB machine does not have.",
    ]))
    out.append("")
    out.append(_md_table(
        ["verdict", "result"],
        [
            ["temporal compression", f"`{verdicts['temporal_compression']['verdict']}`"],
            ["player integration", f"`{verdicts['player_integration']['verdict']}`"],
        ],
    ))
    out.append("")
    out.append(
        "The redundancy is real and the compression is real. It is simply not the comparison "
        "that decides whether anything should change. What follows is the measurement.\n"
    )

    # 2 ---------------------------------------------------------------
    out.append("## 2. Dataset\n")
    out.append(
        "Exactly the four Stage 16 songs, read as register traces rather than re-chosen here. No "
        "synthetic data is used as primary evidence. The selection record is hashed:\n"
    )
    out.append(_md_table(
        ["song", "frames", "frame period (us)", "canonical raw payload (bytes)"],
        [[f"`{song['slug']}`", song["frames"], song["frame_period_us"],
          song["raw_payload_bytes"]] for song in bundle["dataset"]["songs"]],
    ))
    out.append("")
    out.append(f"- selection record: `{bundle['dataset']['selection_source']}`\n"
               f"- its SHA-256: `{bundle['dataset']['selection_sha256']}`\n")

    # 3 ---------------------------------------------------------------
    out.append("## 3. Canonical raw representation\n")
    out.append(
        "Before any experiments, one unambiguous reference format was defined, because the "
        "baseline decides every ratio in the rest of the report. It is not assumed to be optimal; "
        "the point of the experiments is to find out what beats it.\n"
    )
    out.append("```text")
    out.append(bundle["raw_baseline"]["definition"])
    out.append("```")
    out.append("")
    out.append(_md_table(
        ["design question", "decision"],
        [[key, value] for key, value in sorted(bundle["raw_baseline"]["choices"].items())],
    ))
    out.append("")
    out.append(_md_table(
        ["song", "frames", "raw payload", "with container", "share of baseline"],
        [[f"`{song['slug']}`", song["frames"], song["payload_bytes"], song["container_bytes"],
          "100%"] for song in bundle["raw_baseline"]["songs"]],
    ))
    out.append("")
    out.append(
        "The raw baseline is **100%**. Every ratio in this report is "
        "`compressed_bytes / raw_bytes`, every byte needed for exact reconstruction is counted, "
        "and every codec shares the same 12-byte container header so the header cannot bias a "
        "ranking.\n"
    )

    # 4 ---------------------------------------------------------------
    out.append("## 4. RLE results\n")
    out.append(
        "Two run-length schemes: whole-frame RLE treats a frame as one state, per-register RLE "
        "runs nine independent streams. Neither is assumed to be better; both are measured with "
        "their headers.\n"
    )
    out.append(_md_table(RESULT_TABLE_HEADER, _result_rows(bundle["rle"]["results"])))
    out.append("")
    out.append(
        "**Whole-frame RLE makes the stream larger.** The mean run of identical frames across "
        "the corpus is between 1.00 and 1.10 frames, so a run-length record is emitted once per "
        "frame and its header is pure overhead. Per-register RLE works, because individual "
        "registers hold their value for stretches even while other registers change.\n"
    )

    # 5 ---------------------------------------------------------------
    out.append("## 5. Delta results\n")
    out.append(
        "Two delta schemes: fixed-width signed deltas, which is a diagnostic because it stores "
        "the same number of bytes, and a zero-run variant that stores only the frames that "
        "changed, with a bitmap of which registers changed and one byte per changed register.\n"
    )
    out.append(_md_table(RESULT_TABLE_HEADER, _result_rows(bundle["delta"]["results"])))
    out.append("")
    out.append("**Do the deltas have structure?** The per-register histograms say yes:\n")
    for histogram in bundle["delta"]["histograms"][:2]:
        out.append(f"\n### {histogram['slug']}\n")
        out.append(_md_table(
            ["register", "changes", "zero share", "distinct deltas", "entropy (bits/delta)"],
            [[name, row["changes"], row["zero_share"], row["distinct_deltas"],
              row["entropy_bits"]]
             for name, row in sorted(histogram["registers"].items())],
        ))
    out.append("")
    out.append(
        "The entropy column is a diagnostic and **not** a size: a representation still has to "
        "store the value, and every size in this report was obtained by encoding and decoding "
        "real bytes.\n"
    )

    # 6 ---------------------------------------------------------------
    out.append("## 6. Ramp results\n")
    out.append(
        "Per register, the value sequence is segmented into CONST, LINEAR and QUAD runs with a "
        "literal escape. A model segment is only taken when it is *strictly cheaper* than the "
        "literal bytes it replaces, so a segment can never make the stream larger, and the "
        "minimum-length sweep the brief asks for is reported in full.\n"
    )
    out.append(_md_table(RESULT_TABLE_HEADER, _result_rows(bundle["ramps"]["results"])))
    out.append("")
    summary_rows = [
        [row["label"], row["ratio"]["mean"], row["ratio"]["median"], row["ratio"]["min"],
         row["ratio"]["max"], row["saving_percent"]["mean"]]
        for row in bundle["cross_song"]["configurations"] if row["group"] == "ramps"
    ]
    out.append(_md_table(
        ["configuration", "mean ratio", "median", "min", "max", "mean saving %"], summary_rows
    ))
    out.append("")
    out.append(
        "The ramps family is the best *simple* result: it needs no buffer, its decoder state is "
        "a handful of bytes, and it still removes roughly half the stream. That combination is "
        "what makes it the practical candidate in the verdict.\n"
    )

    # 7 ---------------------------------------------------------------
    out.append("## 7. Motif results\n")
    out.append(
        "Detection first, as the brief insists: how often do short frame sequences actually "
        "repeat? The frame counts below are **not** a compression result. The brief is explicit "
        "that the number of found repetitions is not the metric, and the cost is measured in "
        "section 8.\n"
    )
    out.append(_md_table(
        ["song", "motif length (frames)", "distinct", "repeated", "repeated occurrences",
         "frame coverage"],
        [[f"`{row['slug']}`", length_row["length_frames"], length_row["distinct_motifs"],
          length_row["repeated_motifs"], length_row["repeated_occurrences"],
          length_row["coverage_share"]]
         for row in bundle["motifs"]["statistics"]
         for length_row in row["by_length"]],
    ))
    out.append("")
    out.append(
        "Coverage counts each covered frame once, so it is a real union and not a sum of "
        "overlapping occurrences. It is still an *upper bound* on what a motif table could "
        "reach, not a size. The next table makes that concrete by pricing the two sides of the "
        "trade, using a deliberately generous assumption that no real encoder can meet.\n"
    )
    out.append(_md_table(
        ["song", "length", "repeated", "occurrences", "coverage", "table cost (bytes)",
         "optimistic saving (bytes)", "net (bytes)"],
        [[f"`{row['slug']}`", length_row["length_frames"], length_row["repeated_motifs"],
          length_row["repeated_occurrences"], length_row["coverage_share"],
          length_row["table_cost_bytes"], length_row["optimistic_saving_bytes"],
          length_row["net_optimistic_bytes"]]
         for row in bundle["motifs"]["statistics"]
         for length_row in row["by_length"]
         if length_row["length_frames"] in (2, 4, 8, 32)],
    ))
    out.append("")
    out.append(
        "*Optimistic saving* assumes every occurrence after the first becomes a free "
        "backreference: zero bits for the reference, and every repeated motif stored in full. "
        "Real references are not free, so the true saving is smaller than this and the bound is "
        "generous by construction.\n"
    )
    out.append(
        "The bound does **not** settle the question, and it would be dishonest to read it as if "
        "it did. What it does is narrow the window: the net is positive at the short lengths and "
        "collapses as the motifs grow, and on `Warhawk` at 32 frames it is already negative, "
        "where no honest encoder on this plan can win at all. So the only length still worth "
        "trying is a short one. Section 8 tries it for real and reports what a reference "
        "actually costs.\n"
    )

    # 8 ---------------------------------------------------------------
    out.append("## 8. Dictionary / backreference results\n")
    out.append(
        "Two different instruments for the same recurrence. The explicit dictionary builds a "
        "motif table and carries it inside the payload, paying for it in full. LZ "
        "backreferences point into the frames that have already been decoded, so the history is "
        "the dictionary and costs no table at all.\n"
    )
    lz_rows = [row for row in bundle["cross_song"]["configurations"] if row["codec"] == "lz"]
    out.append(_md_table(
        ["configuration", "mean ratio", "median", "min", "max", "mean saving %"],
        [[row["label"], row["ratio"]["mean"], row["ratio"]["median"], row["ratio"]["min"],
          row["ratio"]["max"], row["saving_percent"]["mean"]] for row in lz_rows],
    ))
    out.append("")
    out.append(_md_table(
        ["dictionary scope", "mean ratio", "reading"],
        [
            ["per song (model has seen the song)", bundle["dictionary"]["mean_ratio_by_scope"]["per_song"],
             "the optimistic arm"],
            ["shared (one table for all four)", bundle["dictionary"]["mean_ratio_by_scope"]["shared"],
             "pays the table cost once per song"],
            ["leave one out (never trained on the song)", bundle["dictionary"]["mean_ratio_by_scope"]["leave_one_out"],
             "the honest arm"],
        ],
    ))
    out.append("")
    out.append(
        "**The explicit motif dictionary fails.** All three scopes are above 1.0, meaning the "
        "table costs more than the references save. The redundancy between distant frames is "
        "real, but naming it is not free, and the name is expensive. LZ captures the same "
        "recurrence for nothing, which is the clearest single result in this stage.\n"
    )
    out.append(
        _md_table(
            ["held-out song", "trained on", "entries", "table bytes"],
            [[f"`{fold['held_out']}`", ", ".join(fold["trained_on"]), fold["entries"],
              fold["table_bytes"]] for fold in bundle["dictionary"]["folds"]],
        )
    )
    out.append("")

    # 9 ---------------------------------------------------------------
    out.append("## 9. Hybrid results\n")
    out.append(
        "Per block, the cheapest of raw / per-register RLE / delta-gap / ramps / LZ, with the "
        "chosen codec id and payload length recorded per block. Cross-block references are not "
        "available to the LZ member, which is a real cost of blocking and is visible below.\n"
    )
    out.append(_md_table(
        ["configuration", "mean ratio", "median", "min", "max", "mean saving %"],
        [[row["label"], row["ratio"]["mean"], row["ratio"]["median"], row["ratio"]["min"],
          row["ratio"]["max"], row["saving_percent"]["mean"]]
         for row in bundle["cross_song"]["configurations"] if row["group"] == "hybrid"],
    ))
    out.append("")
    out.append(
        f"The hybrid at 512 frames is the best configuration overall "
        f"(`{summary['best_overall']['label']}`, mean ratio {summary['best_overall']['mean_ratio']}). "
        "It wins by letting each block use whichever representation suits it, and its cost is a "
        "decoder that must implement every member.\n"
    )

    # 10 --------------------------------------------------------------
    out.append("## 10. Cross-song generalization\n")
    out.append(
        "Every configuration is reported per song and with mean, median, min and max. The brief "
        "forbids reporting an average alone. A configuration is only a candidate if it "
        "reconstructs *every* song exactly.\n"
    )
    best_rows = sorted(
        bundle["cross_song"]["configurations"],
        key=lambda row: (row["ratio"]["mean"] if row["ratio"]["mean"] is not None else 9,
                         row["label"]),
    )[:12]
    out.append(_md_table(
        ["configuration", "worst-song ratio", "mean", "median", "best-song ratio", "lossless all"],
        [[row["label"], row["ratio"]["max"], row["ratio"]["mean"], row["ratio"]["median"],
          row["ratio"]["min"], "yes" if row["lossless_on_all_songs"] else "**NO**"]
         for row in best_rows],
    ))
    out.append("")
    best = bundle["best_configurations"]
    out.append(
        "**Per-song optima are not one method.** The smallest encoding differs by song, which "
        "is exactly why a single shared rule has to be measured rather than assumed:\n"
    )
    out.append(_md_table(
        ["song", "best configuration", "ratio"],
        [[f"`{slug}`", f"`{row['label']}`", row["ratio"]]
         for slug, row in sorted(best["best_per_song"].items())],
    ))
    out.append("")
    out.append(
        f"One configuration is nevertheless lossless *and* compressing on all four songs: "
        f"`{best['overall_best']['label']}`, mean ratio {best['overall_best']['mean_ratio']}, "
        f"worst song {best['overall_best']['max_ratio']}. That is the generalisation claim this "
        "stage is prepared to make.\n"
    )
    out.append("Leave-one-song-out for the dictionary model:\n")
    out.append(_md_table(
        ["scope", "mean ratio"],
        [[scope, value] for scope, value in sorted(
            bundle["dictionary"]["mean_ratio_by_scope"].items()
            if False else bundle["dictionary"]["mean_ratio_by_scope"].items()
        )],
    ))
    out.append("")
    out.append(
        "The fold arm is the honest test and it is the worst of the three: a dictionary trained "
        "on three songs does not help the fourth. That is the memorisation test, and the "
        "dictionary idea fails it.\n"
    )

    # 11 --------------------------------------------------------------
    out.append("## 11. Exact reconstruction\n")
    reconstruction = bundle["reconstruction"]
    out.append(
        "Every method was encoded, wrapped in its container, re-parsed, decoded and compared with "
        "the canonical raw payload **byte for byte**. A method that is not exactly reversible is "
        "reported as `LOSSLESS = FALSE` and cannot be presented as a solution, whatever its "
        "size.\n"
    )
    out.append(_md_table(
        ["metric", "value"],
        [
            ["measurements taken", reconstruction["measurements"]],
            ["every measurement lossless", reconstruction["all_lossless"]],
            ["methods that failed", len(reconstruction["failures"])],
            ["requirement", reconstruction["requirement"]],
        ],
    ))
    out.append("")
    out.append(
        "The per-codec table in `reports/stage18/reconstruction.json` carries, for each "
        "measurement: whether reconstruction was exact, the first frame that diverged, how many "
        "values differed, the largest error, and the share of frames that came back completely "
        "correct. Because every measurement is exact, those columns are `None`, `0`, `0` and "
        "`100.0` respectively - which is the point, and the tests assert it.\n"
    )

    # 12 --------------------------------------------------------------
    out.append("## 12. Decoder complexity\n")
    cost = bundle["decoder_cost"]
    out.append(cost["method"] + "\n")
    out.append(cost["machine_ram_note"] + "\n")
    seen_labels: List[str] = []
    cost_rows = []
    for row in cost["codecs"]:
        if row["codec"] in seen_labels:
            continue
        if row["codec"] == "dictionary" and row["dictionary_or_buffer_bytes"] < 30000:
            continue
        seen_labels.append(row["codec"])
        cost_rows.append([
            f"`{row['label']}`", row["code_bytes_estimate"], row["state_bytes"],
            row["temporary_bytes"], row["dictionary_or_buffer_bytes"],
            row["worst_case_ram_bytes"], row["operations_per_frame_proxy"], row["branching"],
        ])
    out.append(_md_table(
        ["configuration", "code bytes (EST)", "state", "temp", "buffer/dictionary",
         "worst-case RAM", "ops/frame (proxy)", "branching"],
        cost_rows,
    ))
    out.append("")
    out.append(
        f"The cheapest decoder is `{cost['cheapest_decoder']}` and the most expensive is "
        f"`{cost['most_expensive_decoder']}`. The buffer column is the one that decides "
        "deployment: a 1024-frame LZ window needs 9,216 bytes of decoded history, which is more "
        "than half of a 16 KB machine.\n"
    )

    # 13 and 14 -------------------------------------------------------
    comparison_report = bundle["comparison"]
    out.append("## 13. Comparison with Stage 17\n")
    out.append(
        "Stage 17's own measured sizes are read from its artefacts rather than recomputed:\n"
    )
    out.append(_md_table(
        ["song", "raw", "best temporal", "Stage 17 exact event IR", "Stage 17 exact / temporal"],
        [[f"`{row['slug']}`", row["canonical_raw_bytes"], row["best_temporal_bytes"],
          row.get("stage17_exact_event_bytes"),
          row.get("stage17_exact_vs_temporal")]
         for row in comparison_report["songs"]],
    ))
    out.append("")
    out.append(
        "**Temporal compression beats Stage 17 clearly.** Stage 17's exact encoding is generally "
        "*larger* than the raw stream it encodes "
        f"(mean ratio {comparison_report['summary']['stage17_exact_ratio_to_raw']['mean']}), while "
        "the best temporal encoding is well below it. At equal exactness, temporal compression is "
        f"about {comparison_report['summary']['stage17_exact_vs_temporal']['mean']}x smaller.\n"
    )
    out.append("## 14. Comparison with the current note format\n")
    out.append(
        "This is the comparison that decides whether anything should change, and it goes the "
        "other way.\n"
    )
    out.append(_md_table(
        ["song", "raw", "best temporal", "current note format", "note format / temporal"],
        [[f"`{row['slug']}`", row["canonical_raw_bytes"], row["best_temporal_bytes"],
          row.get("current_note_format_bytes"), row.get("current_note_format_vs_temporal")]
         for row in comparison_report["songs"]],
    ))
    out.append("")
    out.append(comparison_report["reading"] + "\n")
    out.append(
        _md_table(
            ["representation", "exact?", "mean ratio to raw"],
            [
                ["canonical raw frame state", "yes (it *is* the baseline)", "1.0"],
                [f"best temporal ({summary['best_overall']['label']})", "yes",
                 comparison_report["summary"]["best_temporal_ratio"]["mean"]],
                ["Stage 17 exact event encoding", "yes",
                 comparison_report["summary"]["stage17_exact_ratio_to_raw"]["mean"]],
                ["current note format", "**no**",
                 comparison_report["summary"]["current_note_format_ratio_to_raw"]["mean"]],
            ],
        )
    )
    out.append("")
    out.append(
        "The caveat is honest and it matters: the current note format is not an exact "
        "representation of the reference registers, so the comparison is between an exact format "
        "and an approximate one. That is precisely why it wins, and it is why the verdict is "
        "about integration rather than about the existence of the compression.\n"
    )
    questions = bundle["previous_questions"]
    if questions.get("available"):
        out.append("### What Stage 17 handed to this stage, and what was done with it\n")
        out.append(
            "Stage 17 named questions for a later stage and did not answer them. Reporting which "
            "of them this stage closes - and which it does not - is the honest way to place these "
            f"results. {questions['answered_count']} of {len(questions['answers'])} are answered "
            "here.\n"
        )
        out.append(_md_table(
            ["status", "Stage 17 question", "what this stage did"],
            [[item["status"], item["question"], item["evidence"]]
             for item in questions["answers"]],
        ))
        out.append("")
        out.append(
            "The two that are answered are answered *from the same four songs* as Stage 17 used, "
            "so the comparison is like for like. The rest are deliberately left open; none of "
            "them can be settled by compressing bytes, and pretending otherwise would be exactly "
            "the kind of overreach this experiment exists to avoid.\n"
        )

    # 15, 16, 17 ------------------------------------------------------
    out.append("## 15. Failure analysis\n")
    out.append(bundle["failure_analysis"]["note"] + "\n")
    out.append(_md_table(
        ["method", "measured", "cause", "verdict"],
        [[item["method"], item["measured"], item["cause"], f"`{item['verdict']}`"]
         for item in bundle["failure_analysis"]["failures"]],
    ))
    out.append("")
    out.append(bundle["failure_analysis"]["none_of_these_invalidate_the_positive_result"] + "\n")

    out.append("## 16. Falsification\n")
    falsification = bundle["falsification"]
    out.append(f"**Hypothesis under test:** {falsification['hypothesis']}\n")
    out.append(
        _md_table(
            ["refuting result", "detail"],
            [[item["result"], item["detail"]] for item in falsification["refuting_results"]],
        )
    )
    out.append("")
    out.append(falsification["note"] + "\n")

    out.append("## 17. Verdict\n")
    out.append(_md_table(
        ["verdict", "result", "rule"],
        [
            ["temporal compression",
             f"`{verdicts['temporal_compression']['verdict']}`",
             verdicts["temporal_compression"]["rule"]],
            ["player integration",
             f"`{verdicts['player_integration']['verdict']}`",
             verdicts["player_integration"]["rule"]],
        ],
    ))
    out.append("")
    out.append("Part 21's seven conditions, evaluated one by one:\n")
    out.append(_md_table(
        ["condition", "met", "measured"],
        [[item["condition"], "yes" if item["met"] else "**NO**", item["measured"]]
         for item in verdicts["player_integration"]["conditions"]],
    ))
    out.append("")
    out.append(
        f"The deciding condition is **{verdicts['player_integration']['deciding_condition']}**.\n"
    )
    out.append(verdicts["independence_note"] + "\n")
    out.append(
        f"The practical candidate the verdict records is "
        f"`{(verdicts['temporal_compression']['practical_candidate_without_a_large_buffer'] or {}).get('label')}`: "
        "it compresses well and needs no large buffer.\n"
    )

    out.append("## Final question\n")
    out.append(f"**{answer['question']}**\n")
    out.append(answer["answer"] + "\n")
    out.append(_md_table(
        ["comparison", "result"],
        [[key.replace("_", " "), value]
         for key, value in sorted(answer["answer_in_two_lines"].items())],
    ))
    out.append("")
    out.append("What would change the answer:\n")
    out.append(_bullets(answer["what_would_change_the_answer"]))
    out.append("")
    out.append(answer["negative_result_that_is_still_a_result"] + "\n")
    out.append("---\n")
    out.append(
        "Stage 18 read four corpus songs and the Stage 16 and Stage 17 records through their "
        "hashes, defined one canonical raw representation, implemented eight real byte formats, "
        "and decoded every one of them back for a byte-for-byte comparison. No Composer, DSL, "
        "Music IR, POKEY IR, player, schema or SoundProfile was modified; the player source is "
        "hashed as an input and never written. No audio was rendered, no music was generated, no "
        "listening test was run, and nothing was implemented in production. Any implementation "
        "would be a separate stage, and only after these results are accepted.\n"
    )
    return "\n".join(out)



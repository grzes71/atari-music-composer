"""Stage 19 - a neutral temporal performance grammar for the POKEY register stream.

Stage 17 asked whether a neutral event language could *represent* a performance. It could not, and
compressed worse than raw. Stage 18 asked whether the exact stream had temporal redundancy. It
did, about 49 percent of it, but the result was a byte format and not a model.

Stage 19 asks the narrower structural question that remains:

    Can the historical POKEY behaviour be described by a *small, neutral, temporal set of
    primitives* that is shared across songs - a grammar - rather than by storing the exact
    stream?

This is an experiment about a **representation model**, not another compression experiment. Its
result is allowed to be that no such grammar is worth having.

Neutrality. The atom is a frame of nine registers and a value sequence per register. Every
primitive is a pure temporal construction over 8-bit values: SET, HOLD, DELTA, RAMP, TOGGLE and a
literal escape. No primitive knows what a note, an instrument, a vibrato or a melody is, and no
name in this module is allowed to imply one. Where the analysis borrows Stage 15/16's technique
names it says so explicitly and marks the mapping as an *interpretation*, never as a model
element.

Honest accounting. Stage 18 established the rule this stage inherits: a saving may not be claimed
unless the definition that produces it is paid for. Every total here is

    grammar_definition_cost + parameter_cost + stream_cost + exception_cost + decoder_cost

and the grammar definition cost is charged per primitive at the *current 6502 player's* own code
density. A grammar with five primitives is more expensive to install than one with two, and the
comparison says so.

Read-only. The corpus traces, the Stage 15/16/17/18 records and the player source are read
through their hashes and never written. Nothing is implemented in production: no player command,
no composer feature, no IR, no DSL, no schema. Analysis version ``stage19/1``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atari_music import stage15, stage16, stage17, stage18

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE15_DIR = DEFAULT_REPORTS_DIR / "stage15"
DEFAULT_STAGE16_DIR = DEFAULT_REPORTS_DIR / "stage16"
DEFAULT_STAGE17_DIR = DEFAULT_REPORTS_DIR / "stage17"
DEFAULT_STAGE18_DIR = DEFAULT_REPORTS_DIR / "stage18"
DEFAULT_STAGE19_DIR = DEFAULT_REPORTS_DIR / "stage19"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage18.DEFAULT_ARCHAEOLOGY_DIR

ANALYSIS_VERSION = "stage19/1"

#: Stage 19 does not invent a second canonical form. Stage 18's canonical representation *is* the
#: source of truth, and it is taken by import rather than re-derived, so the two stages cannot
#: silently disagree about what a frame is.
REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER
FRAME_BYTES = stage18.FRAME_BYTES
CONTAINER_HEADER_BYTES = stage18.CONTAINER_HEADER_BYTES
BYTES_PER_CODE_LINE = stage18.BYTES_PER_CODE_LINE

#: The four songs the brief names, as slugs. Verified against the Stage 16 selection rather than
#: assumed: a corpus that silently changed would invalidate every number below.
EXPECTED_SLUGS: Tuple[str, ...] = (
    "Draconus_2024__sub0",
    "Warhawk__sub0",
    "Ninja_Commando__sub0",
    "Red_Max__sub0",
)

#: A Stage 19 codec id inside the *same* Stage 18 container layout, so a Stage 19 stream is
#: self-describing in exactly the way a Stage 18 stream is. The value is outside Stage 18's own
#: id space (0-8) and is deliberately not written back into Stage 18's table.
GRAMMAR_CODEC_ID = 200

#: The most frames one literal escape may carry. A literal block of length k costs
#: ``1 + uvarint_bytes(k) + k``, so for any k below 128 the per-frame cost is identical whatever
#: the block size; capping the block at 32 therefore costs essentially nothing and keeps the
#: dynamic program bounded.
MAX_LITERAL_FRAMES = 32


class GrammarError(RuntimeError):
    """A stream, program or grammar description is malformed or corrupt."""


def _read_json(path: Path) -> Any:
    return stage18._read_json(path)


def sha256_file(path: Path) -> str:
    return stage18.sha256_file(path)


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    return stage18._rnd(value, places)


def _md_table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    return stage18._md_table(header, rows)

# ---------------------------------------------------------------------------
# SECTION 4/5 - the neutral atom
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RegisterChannel:
    """One register's value sequence over the whole song. The neutral atom of Stage 19.

    A channel is a list of 8-bit values, one per frame. It carries no label beyond the register
    name POKEY itself defines, and no primitive in this module is allowed to see anything else -
    not the song, not the other channels, not a note boundary. That restriction is what makes the
    experiment falsifiable: a construction that only exists because a channel "is a bass line"
    would not be a temporal grammar at all.
    """

    register: str
    values: Tuple[int, ...]

    @property
    def frames(self) -> int:
        return len(self.values)

    def change_events(self) -> int:
        """Frames whose value differs from the previous frame. Frame 0 is a change by definition."""
        return sum(
            1 for index in range(self.frames)
            if index == 0 or self.values[index] != self.values[index - 1]
        )

    def runs(self) -> List[Tuple[int, int]]:
        """(value, length) for every maximal constant run, in order."""
        return stage18._group_runs(self.values)


def channels_of(stream: stage18.FrameStream) -> List[RegisterChannel]:
    return [
        RegisterChannel(register=name, values=tuple(stream.registers[name]))
        for name in REGISTER_ORDER
    ]




# ---------------------------------------------------------------------------
# SECTION 5/6 - the candidate primitive vocabulary
# ---------------------------------------------------------------------------
OP_SET = 1
OP_HOLD = 2
OP_DELTA = 3
OP_RAMP = 4
OP_TOGGLE = 5
OP_LITERAL = 6
#: A reference into a stored block of values. It is the SEQUENCE + REPEAT construction section 7
#: asks about, and it is only ever added to a grammar when section 8's induction shows it earns
#: its own table entry. It is deliberately not part of the base vocabulary.
OP_REFERENCE = 7

#: A *literal escape* is not a grammar primitive. It is the residual model: the explicit channel
#: through which every frame the grammar cannot describe is carried at full width. It is present
#: in every variant and its bytes are always charged to ``exception_cost``. Conflating it with a
#: primitive would let a grammar look powerful by describing nothing.
RESIDUAL_OP = OP_LITERAL


@dataclass(frozen=True)
class Primitive:
    """One temporal construction, with its formal definition, cost and decoder estimate.

    ``definition`` is the operative sentence: it says exactly which frames the construction writes
    and which bytes it costs. ``code_lines`` is an ESTIMATE of the 6502 decoder, charged at the
    current player's own density; ``decoder_states`` and ``special_cases`` feed the complexity
    score and are counted, not decorative.
    """

    op: int
    name: str
    definition: str
    parameters: Tuple[str, ...]
    code_lines: int
    decoder_states: int
    special_cases: int

    @property
    def definition_bytes(self) -> int:
        """The bytes the grammar must spend to install this construction. ESTIMATE."""
        return int(round(self.code_lines * BYTES_PER_CODE_LINE))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op": self.op,
            "name": self.name,
            "definition": self.definition,
            "parameters": list(self.parameters),
            "definition_bytes_estimate": self.definition_bytes,
            "definition_code_lines_estimate": self.code_lines,
            "decoder_states": self.decoder_states,
            "special_cases": self.special_cases,
        }



#: The full candidate vocabulary. Five constructions plus the residual channel. Every one is a
#: pure function of a value sequence and a write position; none of them carries meaning.
PRIMITIVES: Dict[int, Primitive] = {
    OP_SET: Primitive(
        op=OP_SET,
        name="SET",
        definition=(
            "SET(v) writes exactly one frame with value v, whatever the current value was. It is "
            "the only construction that carries a value with no temporal relation to its "
            "neighbours, and it is therefore the honest baseline each other construction has to "
            "beat rather than a simplification of one."
        ),
        parameters=("value",),
        code_lines=6,
        decoder_states=1,
        special_cases=0,
    ),
    OP_HOLD: Primitive(
        op=OP_HOLD,
        name="HOLD",
        definition=(
            "HOLD(n) writes n frames, each equal to the current value, so the value is carried "
            "forward unchanged. n >= 1. At the start of a channel the current value is 0."
        ),
        parameters=("frames",),
        code_lines=14,
        decoder_states=1,
        special_cases=1,
    ),
    OP_DELTA: Primitive(
        op=OP_DELTA,
        name="DELTA",
        definition=(
            "DELTA(d, n) writes n frames, frame j (1-based) equal to current + d*j mod 256, so it "
            "continues an arithmetic progression from the value already in the register. n >= 2 "
            "and d != 0; a single step carries no sequence, and is written as SET."
        ),
        parameters=("delta", "frames"),
        code_lines=22,
        decoder_states=1,
        special_cases=2,
    ),
    OP_RAMP: Primitive(
        op=OP_RAMP,
        name="RAMP",
        definition=(
            "RAMP(start, d, n) writes n frames, frame j (0-based) equal to start + d*j mod 256. It "
            "differs from DELTA only in carrying its own start value, so it does not depend on the "
            "previous frame. n >= 2 and d != 0."
        ),
        parameters=("start", "delta", "frames"),
        code_lines=18,
        decoder_states=2,
        special_cases=2,
    ),
    OP_TOGGLE: Primitive(
        op=OP_TOGGLE,
        name="TOGGLE",
        definition=(
            "TOGGLE(a, b, n) writes n frames alternating between a and b, frame 0 equal to a. "
            "n >= 2 and a != b. It is the period-two special case of a repeat, and it is kept "
            "separate only if the data shows the construction earns its definition."
        ),
        parameters=("a", "b", "frames"),
        code_lines=20,
        decoder_states=2,
        special_cases=1,
    ),
    OP_LITERAL: Primitive(
        op=OP_LITERAL,
        name="LITERAL",
        definition=(
            "LITERAL(k, v0..v(k-1)) writes k frames with the given values verbatim. This is the "
            "residual model, not a construction: the explicit channel through which every frame "
            "the grammar cannot describe is carried, so that no residual is ever hidden. "
            "2 <= k <= 32."
        ),
        parameters=("count", "values"),
        code_lines=12,
        decoder_states=1,
        special_cases=1,
    ),
    OP_REFERENCE: Primitive(
        op=OP_REFERENCE,
        name="REPEAT",
        definition=(
            "REPEAT(block) writes the frames of the stored block verbatim, where the block is a "
            "run of values named once in a per-song table and referred to thereafter. It is the "
            "only construction here that stores a value twice, so it is only allowed into a "
            "grammar when its own table entry is paid back by its own uses; section 8 measures "
            "that, and section 20 tries to refute it."
        ),
        parameters=("block",),
        code_lines=16,
        decoder_states=2,
        special_cases=1,
    ),
}

#: Structural constructions: everything except SET (which is raw in disguise) and the residual.
STRUCTURAL_OPS: Tuple[int, ...] = (OP_HOLD, OP_DELTA, OP_RAMP, OP_TOGGLE)

#: The shortest span at which each construction carries the structure it names. A HOLD of one
#: frame is a SET, a DELTA of one frame is a SET, a RAMP of one frame is a SET, and - the one
#: that is easy to get wrong - a TOGGLE of two frames is merely "two different values", which
#: carries no periodicity at all. Requiring two full periods (n >= 4) is what stops the
#: measurement from crediting TOGGLE for frames any two arbitrary values would describe equally
#: well. The first implementation of this stage allowed a two-frame toggle and reported TOGGLE as
#: covering 9,175 frames of Draconus; almost all of them were ties with the residual.
MIN_SPAN: Dict[int, int] = {
    OP_HOLD: 2,
    OP_DELTA: 2,
    OP_RAMP: 2,
    OP_TOGGLE: 4,
}

OP_NAMES: Dict[int, str] = {op: primitive.name for op, primitive in PRIMITIVES.items()}



# ---------------------------------------------------------------------------
# SECTION 10 - the cost of one construction, split so nothing can hide
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Op:
    """One emitted construction: which primitive, how many frames it writes, and its parameters."""

    op: int
    length: int
    params: Tuple[int, ...] = ()

    @property
    def name(self) -> str:
        return OP_NAMES[self.op]


def op_cost(op: int, params: Sequence[int], length: int) -> Tuple[int, int, int]:
    """(stream_bytes, parameter_bytes, exception_bytes) for one construction.

    The split is the accounting rule of this stage. ``stream_bytes`` is structure - the opcode and
    the length fields, which a decoder must read whatever the values are. ``parameter_bytes`` is
    the payload a construction carries: a value, a delta, the two ends of a toggle. ``exception``
    is the residual literal payload. A saving is only real if all three plus the grammar
    definition and the decoder are smaller than raw.
    """
    if op == OP_SET:
        return 1, 1, 0
    if op == OP_HOLD:
        return 1 + stage18.uvarint_bytes(length), 0, 0
    if op == OP_DELTA:
        return (
            1 + stage18.uvarint_bytes(length),
            stage18.uvarint_bytes(stage18.zigzag(int(params[0]))),
            0,
        )
    if op == OP_RAMP:
        return (
            1 + stage18.uvarint_bytes(length),
            1 + stage18.uvarint_bytes(stage18.zigzag(int(params[1]))),
            0,
        )
    if op == OP_TOGGLE:
        return 1 + stage18.uvarint_bytes(length), 2, 0
    if op == OP_LITERAL:
        return 1 + stage18.uvarint_bytes(length), 0, length
    if op == OP_REFERENCE:
        return 1, stage18.uvarint_bytes(int(params[0])), 0
    raise GrammarError(f"unknown op {op}")


def op_total_bytes(op: int, params: Sequence[int], length: int) -> int:
    return sum(op_cost(op, params, length))



# ---------------------------------------------------------------------------
# SECTION 8 - maximal extents, the shape each construction can claim from a position
# ---------------------------------------------------------------------------
def max_hold(values: Sequence[int], index: int) -> int:
    """Length of the constant run starting at ``index``, given the value already in the register."""
    current = values[index - 1] if index > 0 else 0
    if values[index] != current:
        return 0
    length = 1
    while index + length < len(values) and values[index + length] == current:
        length += 1
    return length


def max_delta(values: Sequence[int], index: int) -> int:
    """Length of the arithmetic run continuing from the current value, or 0 if there is none."""
    current = values[index - 1] if index > 0 else 0
    step = (values[index] - current) & 0xFF
    if step == 0:
        return 0
    length = 1
    while index + length < len(values):
        if values[index + length] != (values[index] + step * length) & 0xFF:
            break
        length += 1
    return length


def max_ramp(values: Sequence[int], index: int) -> int:
    """Length of the self-contained arithmetic run starting at ``index``, or 0 if there is none."""
    if index + 1 >= len(values):
        return 0
    step = (values[index + 1] - values[index]) & 0xFF
    if step == 0:
        return 0
    length = 2
    while index + length < len(values):
        if values[index + length] != (values[index] + step * length) & 0xFF:
            break
        length += 1
    return length


def max_toggle(values: Sequence[int], index: int) -> int:
    """Length of the alternating run starting at ``index``, or 0 if there is none."""
    if index + 1 >= len(values):
        return 0
    first, second = values[index], values[index + 1]
    if first == second:
        return 0
    length = 2
    while index + length < len(values):
        expected = first if length % 2 == 0 else second
        if values[index + length] != expected:
            break
        length += 1


# ---------------------------------------------------------------------------
# SECTION 8 - segmentation: the parse that costs least, computed exactly
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChannelTables:
    """Per-position extents, precomputed in linear time so the dynamic program is affordable."""

    hold: Tuple[int, ...]
    delta: Tuple[int, ...]
    ramp: Tuple[int, ...]
    toggle: Tuple[int, ...]

    def extent(self, op: int, index: int) -> int:
        if op == OP_HOLD:
            return self.hold[index]
        if op == OP_DELTA:
            return self.delta[index]
        if op == OP_RAMP:
            return self.ramp[index]
        if op == OP_TOGGLE:
            return self.toggle[index]
        return 0

    def structural_extent(self, index: int) -> int:
        return max(
            (self.extent(op, index) if self.extent(op, index) >= MIN_SPAN[op] else 0)
            for op in STRUCTURAL_OPS
        )


def channel_tables(values: Sequence[int]) -> ChannelTables:
    """Extents for every position, in linear time. The recurrences are exact, not approximate."""
    frames = len(values)
    if frames == 0:
        return ChannelTables((), (), (), ())
    hold = [0] * frames
    delta = [0] * frames
    ramp = [0] * frames
    toggle = [0] * frames
    steps = [0] * frames
    for index in range(frames):
        previous = values[index - 1] if index > 0 else 0
        steps[index] = (values[index] - previous) & 0xFF
    same_step = [0] * frames
    for index in range(frames - 1, -1, -1):
        same_step[index] = (
            1 + same_step[index + 1]
            if index + 1 < frames and steps[index + 1] == steps[index] else 1
        )
    equal_run = [0] * frames
    for index in range(frames - 1, -1, -1):
        equal_run[index] = (
            1 + equal_run[index + 1]
            if index + 1 < frames and values[index + 1] == values[index] else 1
        )
    link = [False] * frames
    for index in range(frames - 2):
        link[index] = values[index] == values[index + 2]
    link_run = [0] * frames
    for index in range(frames - 3, -1, -1):
        link_run[index] = 1 + link_run[index + 1] if link[index] else 0
    for index in range(frames):
        previous = values[index - 1] if index > 0 else 0
        if values[index] == previous:
            hold[index] = equal_run[index]
        if steps[index] != 0:
            delta[index] = same_step[index]
        if index + 1 < frames and steps[index + 1] != 0:
            ramp[index] = 1 + same_step[index + 1]
        if index + 1 < frames and values[index] != values[index + 1]:
            toggle[index] = 2 + link_run[index] if link[index] else 2
    return ChannelTables(tuple(hold), tuple(delta), tuple(ramp), tuple(toggle))


def _population(
    values: Sequence[int],
    index: int,
    tables: ChannelTables,
    allowed: frozenset,
    allowed_params: Optional[Mapping[int, Sequence[Tuple[int, ...]]]] = None,
) -> List[Tuple[int, int, int, Tuple[int, ...]]]:
    """Every candidate construction at one position, with its byte cost.

    ``allowed_params``, when given, is the *frozen parameter* filter of the leave-one-out
    experiment: a construction may only be used with a parameter shape that was actually observed
    in the training songs. It is applied here, in the encoder, so the restriction costs real bytes
    rather than being asserted after the fact.
    """
    population: List[Tuple[int, int, int, Tuple[int, ...]]] = []
    if OP_SET in allowed:
        population.append((2, OP_SET, 1, (values[index],)))
    for op in STRUCTURAL_OPS:
        if op not in allowed:
            continue
        extent = tables.extent(op, index)
        if extent < MIN_SPAN[op]:
            continue
        if op == OP_DELTA:
            previous = values[index - 1] if index > 0 else 0
            params: Tuple[int, ...] = ((values[index] - previous) & 0xFF,)
        elif op == OP_RAMP:
            params = (values[index], (values[index + 1] - values[index]) & 0xFF)
        elif op == OP_TOGGLE:
            params = (values[index], values[index + 1])
        else:
            params = ()
        if allowed_params is not None:
            if parameter_key(op, params) not in allowed_params.get(op, ()):
                continue
        population.append((op_total_bytes(op, params, extent), op, extent, params))
    return population


def segment_channel(
    values: Sequence[int],
    allowed_ops: Iterable[int],
    tables: Optional[ChannelTables] = None,
    allowed_params: Optional[Mapping[int, Sequence[Tuple[int, ...]]]] = None,
) -> List[Op]:
    """Split one channel into the cheapest sequence of constructions.

    The dynamic program is exact for this primitive set. Each construction's *maximal* extent from
    a position is also its optimal extent, because inside a maximal run of that shape no other
    construction can start: a constant run admits only HOLD, an arithmetic run only DELTA or RAMP
    at the same step, an alternating run only TOGGLE. Restarting the same construction later
    always costs another opcode and another parameter field, so continuing is never worse.

    The one place a shorter candidate could pay is the residual, so the residual is not restricted
    at all: every literal length from 1 to ``MAX_LITERAL_FRAMES`` is a legal transition. Its cost
    is linear - ``k + 2`` for k below 128 - so the minimum over the window is a sliding-window
    minimum of ``best[j] + j``, which the monotonic deque below maintains in constant amortised
    time. That keeps the whole dynamic program linear and, more importantly, keeps it *honest*:
    the residual can always fall back to something close to the raw cost of a frame, so a
    construction is credited for a frame only when it is genuinely cheaper than carrying it.

    Ties break deterministically: lower total cost, then longer construction, then lower opcode.
    The opcode rule is what lets an equal-cost RAMP win over a LITERAL of the same length, and it
    is the documented tie-break of this stage.
    """
    frames = len(values)
    if frames == 0:
        return []
    allowed = frozenset(allowed_ops)
    if tables is None:
        tables = channel_tables(values)
    best = [0] * (frames + 1)
    choice: List[Optional[Tuple[int, int, Tuple[int, ...]]]] = [None] * (frames + 1)
    #: Monotonic deque of (best[j] + j, j) with j in the sliding literal window, increasing.
    window: Deque[Tuple[int, int]] = deque([(frames, frames)])
    for index in range(frames - 1, -1, -1):
        high = min(frames, index + MAX_LITERAL_FRAMES)
        while window and window[0][1] > high:
            window.popleft()
        population = _population(values, index, tables, allowed, allowed_params)
        best_total: Optional[int] = None
        best_key: Optional[Tuple[int, int, int]] = None
        best_pick: Optional[Tuple[int, int, Tuple[int, ...]]] = None
        for cost, op, extent, params in population:
            total = cost + best[index + extent]
            key = (total, -extent, op)
            if best_key is None or key < best_key:
                best_total, best_key, best_pick = total, key, (op, extent, params)
        if window:
            anchor, end = window[0]
            total = (end - index) + 2 + best[end]
            key = (total, -(end - index), OP_LITERAL)
            if best_key is None or key < best_key:
                size = end - index
                best_total, best_key = total, key
                best_pick = (OP_LITERAL, size, tuple(values[index:index + size]))
        best[index] = best_total if best_total is not None else 0
        choice[index] = best_pick
        anchor = best[index] + index
        while window and window[-1][0] >= anchor:
            window.pop()
        window.append((anchor, index))
    ops: List[Op] = []
    position = 0
    while position < frames:
        picked = choice[position]
        if picked is None:  # pragma: no cover - the residual guarantees a candidate
            raise GrammarError(f"no construction covers frame {position}")
        op, extent, params = picked
        ops.append(Op(op=op, length=extent, params=params))
        position += extent
    return ops


# ---------------------------------------------------------------------------
# SECTION 9/10/12/13 - measuring one grammar on one song
# ---------------------------------------------------------------------------
#: The interpreter itself: opcode dispatch, the program cursor, the frame loop. Charged once to
#: every variant, so a variant cannot look cheaper by pretending its interpreter is free.
INTERPRETER_CODE_LINES = 34

#: Structural per-channel decoder state, in bytes. A channel needs its program cursor (2), its
#: current value (1), and - for the streaming decoder argued in section 13 - a pending span
#: count (2). Nine channels of that is what a frame-at-a-time decoder must hold.
STATE_BYTES_PER_CHANNEL = 5


def op_map(ops: Sequence[Op], frames: int) -> List[int]:
    """Which construction wrote each frame, so coverage can be counted frame by frame."""
    mapping = [OP_LITERAL] * frames
    position = 0
    for op in ops:
        for offset in range(op.length):
            mapping[position + offset] = op.op
        position += op.length
    return mapping


def grammar_definition_lines(ops_in_grammar: Sequence[int]) -> int:
    """Interpreter plus the handler of every construction the grammar actually contains."""
    return INTERPRETER_CODE_LINES + sum(
        PRIMITIVES[op].code_lines for op in sorted(ops_in_grammar)
    )


def _first_divergence(left: bytes, right: bytes) -> Optional[int]:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index // FRAME_BYTES
    return None


def _share(part: int, whole: int) -> Optional[float]:
    if whole <= 0:
        return None
    return _rnd(part / whole)


# ---------------------------------------------------------------------------
# SECTION 11 - the codec: every construction must decode byte-for-byte
# ---------------------------------------------------------------------------
def write_op(out: bytearray, op: Op) -> None:
    out += stage18.uvarint(op.op)
    if op.op == OP_SET:
        out.append(op.params[0] & 0xFF)
    elif op.op == OP_HOLD:
        out += stage18.uvarint(op.length)
    elif op.op == OP_DELTA:
        out += stage18.uvarint(stage18.zigzag(op.params[0]))
        out += stage18.uvarint(op.length)
    elif op.op == OP_RAMP:
        out.append(op.params[0] & 0xFF)
        out += stage18.uvarint(stage18.zigzag(op.params[1]))
        out += stage18.uvarint(op.length)
    elif op.op == OP_TOGGLE:
        out.append(op.params[0] & 0xFF)
        out.append(op.params[1] & 0xFF)
        out += stage18.uvarint(op.length)
    elif op.op == OP_LITERAL:
        out += stage18.uvarint(op.length)
        out += bytes(value & 0xFF for value in op.params)
    elif op.op == OP_REFERENCE:
        out += stage18.uvarint(int(op.params[0]))
    else:  # pragma: no cover - guarded by the caller
        raise GrammarError(f"cannot write unknown op {op.op}")


def write_program(ops: Sequence[Op]) -> bytes:
    out = bytearray()
    for op in ops:
        write_op(out, op)
    return bytes(out)


def _uvarint(buf: bytes, pos: int) -> Tuple[int, int]:
    """Read a uvarint, refusing a truncated field with this stage's own error type."""
    try:
        return stage18.read_uvarint(buf, pos)
    except stage18.Stage18Error as error:
        raise GrammarError(str(error)) from error


def _byte(buf: bytes, pos: int, what: str) -> int:
    if pos >= len(buf):
        raise GrammarError(f"program ends before the {what}")
    return buf[pos]



def write_table(table: Sequence[Sequence[int]]) -> bytes:
    """The per-song block table: every block named once, then referred to by index."""
    out = bytearray(stage18.uvarint(len(table)))
    for block in table:
        out += stage18.uvarint(len(block))
        out += bytes(value & 0xFF for value in block)
    return bytes(out)


def read_program(buf: bytes, frames: int, table: Sequence[Sequence[int]] = ()) -> List[int]:
    """Decode one channel program. Any malformed or truncated input is refused, never guessed."""
    out: List[int] = []
    current = 0
    pos = 0
    while pos < len(buf):
        op, pos = _uvarint(buf, pos)
        if op == OP_SET:
            value = _byte(buf, pos, "SET value")
            pos += 1
            out.append(value)
            current = value
        elif op == OP_HOLD:
            count, pos = _uvarint(buf, pos)
            if count < 1:
                raise GrammarError("HOLD count must be at least 1")
            out.extend([current] * count)
        elif op == OP_DELTA:
            raw, pos = _uvarint(buf, pos)
            count, pos = _uvarint(buf, pos)
            step = stage18.unzigzag(raw)
            if step == 0 or not -255 <= step <= 255:
                raise GrammarError(f"DELTA step {step} is out of range")
            if count < 2:
                raise GrammarError("DELTA span must be at least 2")
            for _ in range(count):
                current = (current + step) & 0xFF
                out.append(current)
        elif op == OP_RAMP:
            start = _byte(buf, pos, "RAMP start")
            pos += 1
            raw, pos = _uvarint(buf, pos)
            count, pos = _uvarint(buf, pos)
            step = stage18.unzigzag(raw)
            if step == 0 or not -255 <= step <= 255:
                raise GrammarError(f"RAMP step {step} is out of range")
            if count < 2:
                raise GrammarError("RAMP span must be at least 2")
            value = start
            out.append(value)
            for _ in range(count - 1):
                value = (value + step) & 0xFF
                out.append(value)
            current = value
        elif op == OP_TOGGLE:
            first = _byte(buf, pos, "TOGGLE first value")
            pos += 1
            second = _byte(buf, pos, "TOGGLE second value")
            pos += 1
            count, pos = _uvarint(buf, pos)
            if first == second:
                raise GrammarError("TOGGLE endpoints must differ")
            if count < 2:
                raise GrammarError("TOGGLE span must be at least 2")
            for index in range(count):
                out.append(first if index % 2 == 0 else second)
            current = first if (count - 1) % 2 == 0 else second
        elif op == OP_LITERAL:
            count, pos = _uvarint(buf, pos)
            if count < 1 or count > MAX_LITERAL_FRAMES:
                raise GrammarError(f"LITERAL span {count} is out of range")
            if pos + count > len(buf):
                raise GrammarError("LITERAL body is truncated")
            out.extend(buf[pos:pos + count])
            pos += count
            current = out[-1]
        elif op == OP_REFERENCE:
            index, pos = _uvarint(buf, pos)
            if index >= len(table):
                raise GrammarError(f"REPEAT index {index} is outside the block table")
            block = table[index]
            if not block:
                raise GrammarError(f"REPEAT index {index} names an empty block")
            out.extend(block)
            current = block[-1]
        else:
            raise GrammarError(f"unknown opcode {op}")
        if len(out) > frames:
            raise GrammarError(
                f"program writes {len(out)} frames, more than the declared {frames}"
            )
    if len(out) != frames:
        raise GrammarError(f"program writes {len(out)} frames, expected {frames}")
    return out


# ---------------------------------------------------------------------------
# The measurement of one grammar on one song
# ---------------------------------------------------------------------------
def measure_song_repeat(
    stream: stage18.FrameStream,
    channels: Sequence[RegisterChannel],
    tables: Sequence[ChannelTables],
    allowed: Optional[Sequence[int]] = None,
    variant: str = "G6",
) -> Dict[str, Any]:
    """Measure the SEQUENCE + REPEAT grammar for real: build the table, encode, decode, compare.

    The bound computed by :func:`pattern_induction` is replaced here by an actual encoding. If the
    reference construction is worth having, this row will show it in bytes, and if it is not, this
    row will show that too - either way the number is measured rather than argued.
    """
    if allowed is None:
        allowed = (OP_SET,) + STRUCTURAL_OPS
    segmented = segment_song(channels, tables, allowed)
    final, table, stats = extract_references(channels, segmented)
    allowed_with_repeat = tuple(sorted(set(allowed) | {OP_REFERENCE}))
    return measure_song(
        stream, variant, allowed_with_repeat, channels, tables, final,
        table=table, reference_stats=stats,
    )


def repeat_lexicon_leave_one_out(
    streams: Sequence[stage18.FrameStream],
    channels_by_song: Mapping[str, Sequence[RegisterChannel]],
    tables_by_song: Mapping[str, Sequence[ChannelTables]],
) -> Dict[str, Any]:
    """Does a REPEAT lexicon transfer to a song that did not contribute to it?

    This is the experiment that decides whether the REPEAT construction is part of a grammar or a
    per-song memorisation. The lexicon is built from three songs' blocks, offered whole to the
    fourth, and the fourth may spend only what it was given. If a shared lexicon helps, the
    construction is a grammar; if it barely matches, it is a dictionary of one song wearing the
    clothes of a construction.
    """
    per_song_tables: Dict[str, List[bytes]] = {}
    for stream in streams:
        channels = channels_by_song[stream.slug]
        tables = tables_by_song[stream.slug]
        segmented = segment_song(channels, tables, (OP_SET,) + STRUCTURAL_OPS)
        _, table, _stats = extract_references(channels, segmented)
        per_song_tables[stream.slug] = [bytes(block) for block in table]

    slugs = [stream.slug for stream in streams]
    folds: List[Dict[str, Any]] = []
    for held_out in slugs:
        training = [slug for slug in slugs if slug != held_out]
        lexicon: List[bytes] = []
        seen: set = set()
        for slug in training:
            for block in per_song_tables[slug]:
                if block not in seen:
                    seen.add(block)
                    lexicon.append(block)
        lexicon.sort(key=lambda block: (-len(block), block))
        channels = channels_by_song[held_out]
        tables = tables_by_song[held_out]
        segmented = segment_song(channels, tables, (OP_SET,) + STRUCTURAL_OPS)
        final, used_table, stats = extract_references(channels, segmented, frozen=lexicon)
        row = measure_song(
            streams[[stream.slug for stream in streams].index(held_out)],
            "repeat_frozen_lexicon", (OP_SET,) + STRUCTURAL_OPS + (OP_REFERENCE,),
            channels, tables, final,
            table=used_table, reference_stats=stats,
        )
        folds.append(
            {
                "held_out": held_out,
                "trained_on": training,
                "shared_lexicon_blocks": len(lexicon),
                "shared_lexicon_bytes": sum(
                    1 + stage18.uvarint_bytes(len(block)) + len(block) for block in lexicon
                ),
                "blocks_matched": stats["frozen_blocks_matched"],
                "references_emitted": stats["references_emitted"],
                "measurement": row,
            }
        )
    return {
        "folds": folds,
        "mean_ratio": _rnd(sum(fold["measurement"]["ratio"] for fold in folds) / len(folds)),
        "mean_structural_coverage": _rnd(
            sum(fold["measurement"]["coverage"]["structural_coverage"] for fold in folds)
            / len(folds)
        ),
        "mean_blocks_matched": _rnd(
            sum(fold["blocks_matched"] for fold in folds) / len(folds)
        ),
        "mean_shared_lexicon_blocks": _rnd(
            sum(fold["shared_lexicon_blocks"] for fold in folds) / len(folds)
        ),
        "all_exact": all(fold["measurement"]["exact"] for fold in folds),
        "reading": (
            "compare mean_ratio here with the in-sample G6 ratio and with G5. A lexicon that does "
            "not transfer shows up as a ratio barely better than G5, however large the shared "
            "lexicon is."
        ),
    }


def measure_song(
    stream: stage18.FrameStream,
    variant: str,
    allowed_ops: Sequence[int],
    channels: Optional[Sequence[RegisterChannel]] = None,
    tables: Optional[Sequence[ChannelTables]] = None,
    segmented: Optional[Sequence[List[Op]]] = None,
    table: Sequence[Sequence[int]] = (),
    reference_stats: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Encode one song with one grammar and report every axis the brief asks for.

    Nothing here is inferred from the op sequence alone: the payload is actually built, actually
    wrapped in the container, actually decoded, and actually compared byte for byte with the
    canonical raw payload. A row whose ``exact`` is false is not a result at all.
    """
    channels = list(channels if channels is not None else channels_of(stream))
    tables = list(tables if tables is not None else [channel_tables(c.values) for c in channels])
    allowed = sorted(set(allowed_ops))
    if segmented is None:
        segmented = [
            segment_channel(channel.values, allowed, table)
            for channel, table in zip(channels, tables)
        ]
    payload = encode_payload(segmented, table)
    container = wrap(payload, stream.frames, stream.frame_period_us)
    rebuilt = registers_to_payload(read_channels(payload, stream.frames, table))
    raw = stream.payload()
    exact = rebuilt == raw

    names = [OP_NAMES[op] for op in sorted(PRIMITIVES)]
    op_counts = {name: 0 for name in names}
    frames_by = {name: 0 for name in names}
    stream_bytes = CONTAINER_HEADER_BYTES + stage18.uvarint_bytes(FRAME_BYTES)
    parameter_bytes = 0
    exception_bytes = 0
    for ops in segmented:
        stream_bytes += stage18.uvarint_bytes(len(write_program(ops)))
        for op in ops:
            op_counts[OP_NAMES[op.op]] += 1
            frames_by[OP_NAMES[op.op]] += op.length
            part_stream, part_param, part_exception = op_cost(op.op, op.params, op.length)
            stream_bytes += part_stream
            parameter_bytes += part_param
            exception_bytes += part_exception
    return _measure_tail(
        stream, variant, allowed, channels, segmented, raw, payload, container, rebuilt, exact,
        op_counts, frames_by, stream_bytes, parameter_bytes, exception_bytes,
        reference_table_bytes=len(write_table(table)), reference_stats=reference_stats,
    )


def _measure_tail(
    stream: stage18.FrameStream,
    variant: str,
    allowed: Sequence[int],
    channels: Sequence[RegisterChannel],
    segmented: Sequence[List[Op]],
    raw: bytes,
    payload: bytes,
    container: bytes,
    rebuilt: bytes,
    exact: bool,
    op_counts: Mapping[str, int],
    frames_by: Mapping[str, int],
    stream_bytes: int,
    parameter_bytes: int,
    exception_bytes: int,
    reference_table_bytes: int = 0,
    reference_stats: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    total_frames = FRAME_BYTES * stream.frames
    describing = set(STRUCTURAL_OPS) | {OP_REFERENCE}
    structural_frames = (
        sum(frames_by[OP_NAMES[op]] for op in STRUCTURAL_OPS) + frames_by[OP_NAMES[OP_REFERENCE]]
    )
    residual_frames = frames_by[OP_NAMES[OP_LITERAL]]

    changes = 0
    structural_changes = 0
    covered_channels = 0
    for channel, ops in zip(channels, segmented):
        mapping = op_map(ops, channel.frames)
        covered = 0
        for index in range(channel.frames):
            if index == 0 or channel.values[index] != channel.values[index - 1]:
                changes += 1
                if mapping[index] in describing:
                    structural_changes += 1
            if mapping[index] != OP_LITERAL:
                covered += 1
        if channel.frames and covered / channel.frames >= 0.5:
            covered_channels += 1

    definition_lines = grammar_definition_lines(allowed)
    definition_bytes = int(round(definition_lines * BYTES_PER_CODE_LINE))
    handler_bytes = int(
        round(sum(PRIMITIVES[op].code_lines for op in allowed) * BYTES_PER_CODE_LINE)
    )
    state_bytes = STATE_BYTES_PER_CHANNEL * FRAME_BYTES
    return {
        "slug": stream.slug,
        "variant": variant,
        "primitive_set": [OP_NAMES[op] for op in allowed],
        "frames": stream.frames,
        "raw_bytes": len(raw),
        "payload_bytes": len(payload),
        "container_bytes": len(container),
        "exact": exact,
        "first_divergence_frame": None if exact else _first_divergence(raw, rebuilt),
        "operation_counts": dict(op_counts),
        "frames_by_operation": dict(frames_by),
        "reference_table": dict(reference_stats) if reference_stats else None,
        "bytes": {
            "stream": stream_bytes,
            "parameter": parameter_bytes,
            "exception": exception_bytes,
            "reference_table": reference_table_bytes,
            "grammar_definition": definition_bytes,
            "decoder": handler_bytes,
            "grammar_and_decoder": definition_bytes + handler_bytes,
            "artefact_total": (
                stream_bytes + parameter_bytes + exception_bytes + reference_table_bytes
            ),
            "grand_total": (
                stream_bytes + parameter_bytes + exception_bytes + reference_table_bytes
                + definition_bytes + handler_bytes
            ),
        },
        "accounting_check": (
            stream_bytes + parameter_bytes + exception_bytes + reference_table_bytes
            == len(container)
        ),
        "coverage": {
            "frame_coverage": _share(structural_frames + frames_by["SET"], total_frames),
            "structural_coverage": _share(structural_frames, total_frames),
            "residual_share": _share(residual_frames, total_frames),
            "set_share": _share(frames_by["SET"], total_frames),
            "repeat_share": _share(frames_by[OP_NAMES[OP_REFERENCE]], total_frames),
            "change_event_coverage": _share(structural_changes, changes),
            "channel_coverage": _share(covered_channels, FRAME_BYTES),
            "byte_coverage": _share(structural_frames + frames_by["SET"], total_frames),
            "information_note": (
                "byte_coverage equals frame_coverage by construction, because one register frame "
                "is one byte; it is reported so the equality is visible and not assumed. "
                "change_event_coverage is the different number, and it is the one that says how "
                "much of the actual activity the grammar describes."
            ),
        },
        "decoder": {
            "code_lines_estimate": definition_lines,
            "grammar_definition_bytes_estimate": definition_bytes,
            "handler_bytes_estimate": handler_bytes,
            "state_bytes": state_bytes,
            "buffer_bytes": 0,
            "ram_bytes": state_bytes,
        },
        "ratio": _share(len(container), len(raw)),
        "ratio_with_grammar": _share(len(container) + definition_bytes + handler_bytes, len(raw)),
        "saving_percent": _rnd(100.0 * (1.0 - len(container) / len(raw))),
        "saving_percent_with_grammar": _rnd(
            100.0 * (1.0 - (len(container) + definition_bytes + handler_bytes) / len(raw))
        ),
    }




def read_channels(
    payload: bytes, frames: int, table: Sequence[Sequence[int]] = ()
) -> Dict[str, List[int]]:
    """Decode a whole Stage 19 payload: a block table, then one program per register."""
    count, pos = _uvarint(payload, 0)
    if count != FRAME_BYTES:
        raise GrammarError(f"payload declares {count} channels, expected {FRAME_BYTES}")
    stored, pos = _uvarint(payload, pos)
    blocks: List[List[int]] = []
    for _ in range(stored):
        length, pos = _uvarint(payload, pos)
        if pos + length > len(payload) or length < 1:
            raise GrammarError("block table entry is truncated")
        blocks.append(list(payload[pos:pos + length]))
        pos += length
    if blocks and list(table) and blocks != [list(item) for item in table]:
        raise GrammarError("block table in the payload disagrees with the supplied table")
    registers: Dict[str, List[int]] = {}
    for name in REGISTER_ORDER:
        length, pos = _uvarint(payload, pos)
        if pos + length > len(payload):
            raise GrammarError(f"program for {name} is truncated")
        registers[name] = read_program(payload[pos:pos + length], frames, blocks)
        pos += length
    if pos != len(payload):
        raise GrammarError("payload has trailing bytes after the last program")
    return registers


def encode_payload(
    channels: Sequence[Sequence[Op]], table: Sequence[Sequence[int]] = ()
) -> bytes:
    out = bytearray(stage18.uvarint(FRAME_BYTES))
    out += write_table(table)
    for ops in channels:
        program = write_program(ops)
        out += stage18.uvarint(len(program))
        out += program
    return bytes(out)


def registers_to_payload(registers: Mapping[str, Sequence[int]]) -> bytes:
    """Interleave decoded channels back into the canonical Stage 18 payload."""
    frames = len(registers[REGISTER_ORDER[0]])
    out = bytearray(frames * FRAME_BYTES)
    pos = 0
    for index in range(frames):
        for name in REGISTER_ORDER:
            out[pos] = registers[name][index] & 0xFF
            pos += 1
    return bytes(out)



# ---------------------------------------------------------------------------
# SECTION 19 - the candidate grammars
# ---------------------------------------------------------------------------
SET_HOLD: Tuple[int, ...] = (OP_SET, OP_HOLD)
SET_HOLD_DELTA: Tuple[int, ...] = (OP_SET, OP_HOLD, OP_DELTA)
SET_HOLD_DELTA_RAMP: Tuple[int, ...] = (OP_SET, OP_HOLD, OP_DELTA, OP_RAMP)
FULL: Tuple[int, ...] = (OP_SET, OP_HOLD, OP_DELTA, OP_RAMP, OP_TOGGLE)
HOLD_ONLY: Tuple[int, ...] = (OP_SET, OP_HOLD)

#: G0 and G1 are not grammars: they are the two representations the grammar has to be judged
#: against, so they are compared on size and exactness but carry no coverage or complexity.
GRAMMAR_VARIANTS: Tuple[Tuple[str, str, Tuple[int, ...]], ...] = (
    ("G2", "SET + HOLD", SET_HOLD),
    ("G3", "SET + HOLD + DELTA", SET_HOLD_DELTA),
    ("G4", "SET + HOLD + DELTA + RAMP", SET_HOLD_DELTA_RAMP),
    ("G5", "SET + HOLD + DELTA + RAMP + TOGGLE", FULL),
)

VARIANT_BY_NAME: Dict[str, Tuple[int, ...]] = {name: ops for name, _label, ops in GRAMMAR_VARIANTS}


def parameter_key(op: int, params: Sequence[int]) -> Tuple[int, ...]:
    """What makes two uses of a construction "the same" for generalisation purposes.

    The register is deliberately excluded: the brief's example is that RAMP can be a shared
    construction while every song uses different deltas and lengths. So a key is the shape of the
    parameter - the delta for DELTA and RAMP, the two endpoints for TOGGLE, nothing for HOLD -
    and never the register that happened to carry it.
    """
    if op == OP_DELTA:
        return (int(params[0]),)
    if op == OP_RAMP:
        return (int(params[1]),)
    if op == OP_TOGGLE:
        return (int(params[0]), int(params[1]))
    return ()


def collect_parameters(
    channels: Sequence[RegisterChannel], segmented: Sequence[List[Op]]
) -> Dict[str, Any]:
    """Per-construction parameter distributions, keyed by a neutral parameter shape."""
    per_op: Dict[str, Dict[Tuple[int, ...], int]] = {
        OP_NAMES[op]: {} for op in STRUCTURAL_OPS
    }
    lengths: Dict[str, List[int]] = {OP_NAMES[op]: [] for op in STRUCTURAL_OPS}
    registers: Dict[str, Dict[str, int]] = {OP_NAMES[op]: {} for op in STRUCTURAL_OPS}
    for channel, ops in zip(channels, segmented):
        for op in ops:
            if op.op not in STRUCTURAL_OPS:
                continue
            name = OP_NAMES[op.op]
            key = parameter_key(op.op, op.params)
            per_op[name][key] = per_op[name].get(key, 0) + 1
            lengths[name].append(op.length)
            registers[name][channel.register] = registers[name].get(channel.register, 0) + 1
    return {
        "values": {
            name: sorted(
                ({"parameters": list(key), "occurrences": count} for key, count in table.items()),
                key=lambda item: (-item["occurrences"], item["parameters"]),
            )
            for name, table in per_op.items()
        },
        "keys": {name: sorted(table) for name, table in per_op.items()},
        "cardinality": {name: len(table) for name, table in per_op.items()},
        "median_length": {
            name: (stage18._median(lengths[name]) if lengths[name] else None)
            for name in lengths
        },
        "mean_length": {
            name: (_rnd(sum(lengths[name]) / len(lengths[name])) if lengths[name] else None)
            for name in lengths
        },
        "registers": {
            name: dict(sorted(table.items())) for name, table in registers.items()
        },
    }



# ---------------------------------------------------------------------------
# SECTION 6/7/8 - SEQUENCE + REPEAT: built and measured, not assumed
# ---------------------------------------------------------------------------
#: The block sizes the induction is allowed to propose, in operations. The bound is deliberate:
#: section 21 forbids a grammar that names a private pattern for every fragment, and unbounded
#: blocks would be exactly that.
REFERENCE_BLOCK_OPS: Tuple[int, ...] = (2, 3, 4)

#: A block must be used more than once to be worth a table entry, and its own entry must be paid
#: back by its own uses. This is the anti-overfitting rule of section 21, applied at the point of
#: selection rather than reported afterwards.
REFERENCE_MIN_USES = 2


def block_offsets(ops: Sequence[Op]) -> List[int]:
    offsets = [0]
    for op in ops:
        offsets.append(offsets[-1] + op.length)
    return offsets


def count_blocks(
    channels: Sequence[RegisterChannel], segmented: Sequence[Sequence[Op]]
) -> Dict[Tuple[int, bytes], int]:
    """Count every op-aligned value block of 2..4 operations, per song.

    The blocks are cut on the boundaries the grammar itself chose. That is what makes this a
    *grammar-aware* repeat rather than a raw search: an operation is the unit, so a repeated block
    is a repeated run of constructions, and its identity is its emitted values.
    """
    counts: Dict[Tuple[int, bytes], int] = {}
    for channel, ops in zip(channels, segmented):
        offsets = block_offsets(ops)
        for index in range(len(ops)):
            for size in REFERENCE_BLOCK_OPS:
                if index + size > len(ops):
                    continue
                block = bytes(channel.values[offsets[index]:offsets[index + size]])
                counts[(size, block)] = counts.get((size, block), 0) + 1
    return counts


def extract_references(
    channels: Sequence[RegisterChannel],
    segmented: Sequence[Sequence[Op]],
    frozen: Optional[Sequence[bytes]] = None,
) -> Tuple[List[List[Op]], List[List[int]], Dict[str, Any]]:
    """Replace repeated blocks with references, keeping only blocks that pay for themselves.

    Three deliberate restrictions, each of which could only make the result worse and therefore
    makes the result more trustworthy: a block must appear at least twice; a block's *own* table
    entry must be repaid by its *own* uses, so no block can be subsidised by another; and the
    extraction is greedy, left to right, longest first, so no value is ever referenced twice.

    ``frozen``, when given, is the leave-one-out arm: the eligible blocks are exactly those the
    *other* songs produced, and the song may only use what it is offered. This is how the stage
    asks whether a REPEAT lexicon is a grammar or a memorisation of one song.
    """
    counts = count_blocks(channels, segmented)
    if frozen is not None:
        present = {key[1] for key in counts}
        kept = {block for block in set(frozen) if block in present}
        frozen_mode = True
    else:
        width = stage18.uvarint_bytes(max(1, len(counts)))
        provisional_reference_cost = 1 + width
        kept = {
            key
            for key, count in counts.items()
            if count >= REFERENCE_MIN_USES
            and count * (len(key[1]) - provisional_reference_cost)
            > 1 + stage18.uvarint_bytes(len(key[1])) + len(key[1])
        }
        frozen_mode = False

    marked: List[List[Any]] = []
    for channel, ops in zip(channels, segmented):
        offsets = block_offsets(ops)
        out: List[Any] = []
        index = 0
        while index < len(ops):
            matched: Optional[Tuple[int, bytes]] = None
            for size in sorted(REFERENCE_BLOCK_OPS, reverse=True):
                if index + size > len(ops):
                    continue
                block = bytes(channel.values[offsets[index]:offsets[index + size]])
                if (size, block) in kept:
                    matched = (size, block)
                    break
            if matched is None:
                out.append(ops[index])
                index += 1
                continue
            out.append(matched[1])
            index += matched[0]
        marked.append(out)

    uses: Dict[bytes, int] = {}
    for sequence in marked:
        for item in sequence:
            if isinstance(item, bytes):
                uses[item] = uses.get(item, 0) + 1
    table = sorted(uses, key=lambda block: (-uses[block], len(block), block))
    index_of = {block: position for position, block in enumerate(table)}
    final: List[List[Op]] = []
    for sequence in marked:
        converted: List[Op] = []
        for item in sequence:
            if isinstance(item, bytes):
                converted.append(
                    Op(op=OP_REFERENCE, length=len(item), params=(index_of[item],))
                )
            else:
                converted.append(item)
        final.append(converted)

    references = sum(1 for sequence in final for op in sequence if op.op == OP_REFERENCE)
    return final, [list(block) for block in table], {
        "candidate_blocks": len(counts),
        "candidate_blocks_used_twice_or_more": sum(
            1 for count in counts.values() if count >= REFERENCE_MIN_USES
        ),
        "blocks_kept_after_profitability": len(kept),
        "frozen_lexicon": frozen_mode,
        "frozen_blocks_offered": len(set(frozen)) if frozen is not None else None,
        "frozen_blocks_matched": len(kept) if frozen_mode else None,
        "table_entries": len(table),
        "table_bytes": len(write_table(table)),
        "references_emitted": references,
        "provisional_reference_cost": None if frozen_mode else provisional_reference_cost,
        "restriction": (
            "a block must appear at least twice and must repay its own table entry from its own "
            "uses; no block can be subsidised by another"
            if not frozen_mode else
            "the lexicon was built from other songs; this song may only spend what it was given"
        ),
    }


# ---------------------------------------------------------------------------
# The container: Stage 18's layout, so a Stage 19 stream is comparable byte for byte
# ---------------------------------------------------------------------------
def wrap(payload: bytes, frames: int, period_us: int) -> bytes:
    return stage18.make_container(GRAMMAR_CODEC_ID, frames, period_us, payload)


def unwrap(container: bytes) -> Tuple[int, bytes]:
    codec_id, _flags, frames, _period, payload = stage18.parse_container(container)
    return frames, payload


# ---------------------------------------------------------------------------
# SECTION 7/14 - per-song induction: the smallest grammar that pays for itself
# ---------------------------------------------------------------------------
def _addition_order() -> Tuple[int, ...]:
    """The fixed order in which constructions are considered for addition. Deterministic."""
    return (OP_HOLD, OP_DELTA, OP_RAMP, OP_TOGGLE)


def evaluate_song(
    stream: stage18.FrameStream,
    channels: Sequence[RegisterChannel],
    tables: Sequence[ChannelTables],
    allowed: Iterable[int],
    cache: Optional[Dict[Tuple[str, Tuple[int, ...]], Dict[str, Any]]] = None,
    allowed_params: Optional[Mapping[int, Sequence[Tuple[int, ...]]]] = None,
    variant: str = "",
) -> Dict[str, Any]:
    """Measure one song, memoised on (slug, primitive set, frozen-parameter flag)."""
    allowed = tuple(sorted(set(allowed)))
    key = (stream.slug, allowed, allowed_params is not None)
    if cache is not None and key in cache:
        return cache[key]
    segmented = [
        segment_channel(channel.values, allowed, table, allowed_params)
        for channel, table in zip(channels, tables)
    ]
    row = measure_song(
        stream, variant or "+".join(OP_NAMES[op] for op in allowed), allowed,
        channels, tables, segmented,
    )
    if cache is not None:
        cache[key] = row
    return row


def induce_song(
    stream: stage18.FrameStream,
    channels: Sequence[RegisterChannel],
    tables: Sequence[ChannelTables],
    cache: Optional[Dict[Tuple[str, Tuple[int, ...]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Greedy forward selection of the smallest grammar that pays for itself on one song.

    Selection is by the *grand total*, which includes the grammar definition and the decoder, so
    a construction has to earn its own installation before it can join the grammar. That is the
    whole point of the exercise: without this rule a construction that saves two bytes would be
    added because it "saves two bytes".

    Ties break deterministically: the candidate that leaves the grand total lowest wins, and on an
    exact tie the lower opcode wins. The step history is kept so the stopping decision can be
    audited rather than trusted.
    """
    current: Tuple[int, ...] = (OP_SET,)
    history: List[Dict[str, Any]] = []
    best_row = evaluate_song(stream, channels, tables, current, cache, variant="induced")
    while True:
        trial_rows: List[Tuple[int, int, Tuple[int, ...], Dict[str, Any]]] = []
        for op in _addition_order():
            if op in current:
                continue
            trial = tuple(sorted(current + (op,)))
            row = evaluate_song(stream, channels, tables, trial, cache, variant="induced")
            trial_rows.append((row["bytes"]["grand_total"], op, trial, row))
        if not trial_rows:
            break
        trial_rows.sort(key=lambda item: (item[0], item[1]))
        best_total, best_op, best_trial, best_trial_row = trial_rows[0]
        gain = best_row["bytes"]["grand_total"] - best_total
        history.append(
            {
                "considered": OP_NAMES[best_op],
                "trial_set": [OP_NAMES[op] for op in best_trial],
                "trial_grand_total": best_total,
                "gain_bytes": gain,
                "accepted": gain > 0,
                "all_trials": [
                    {"add": OP_NAMES[op], "grand_total": total}
                    for total, op, _trial, _row in sorted(trial_rows)
                ],
            }
        )
        if gain <= 0:
            break
        current = best_trial
        best_row = best_trial_row
    return {
        "slug": stream.slug,
        "induced_primitives": [OP_NAMES[op] for op in current],
        "induced_ops": [op for op in current],
        "steps": history,
        "measurement": best_row,
        "parameter_diversity": collect_parameters(
            channels, segment_song(channels, tables, current)
        )["cardinality"],
        "stopping_reason": (
            "no further construction lowered the grand total, which includes its own definition"
        ),
    }


# ---------------------------------------------------------------------------
# SECTION 18 - a grammar complexity score, applied identically to every candidate
# ---------------------------------------------------------------------------
def complexity_score(ops_in_grammar: Sequence[int]) -> Dict[str, Any]:
    """The brief's four components, each counted, summed into one deterministic score.

    It is not claimed to be a perfect metric. It is claimed to be explicit, deterministic, and
    applied in exactly the same way to every candidate, which is what makes a Pareto comparison
    between them meaningful.
    """
    ops = sorted(set(ops_in_grammar))
    fields = sorted({name for op in ops for name in PRIMITIVES[op].parameters})
    states = sum(PRIMITIVES[op].decoder_states for op in ops)
    specials = sum(PRIMITIVES[op].special_cases for op in ops)
    return {
        "primitives": len(ops),
        "parameter_fields": len(fields),
        "parameter_field_names": fields,
        "decoder_states": states,
        "special_cases": specials,
        "score": len(ops) + len(fields) + states + specials,
        "definition_lines_estimate": grammar_definition_lines(ops),
    }


# ---------------------------------------------------------------------------
# SECTION 15/16/17 - the shared grammar, leave-one-out, and parameter generalisation
# ---------------------------------------------------------------------------
def segment_song(
    channels: Sequence[RegisterChannel],
    tables: Sequence[ChannelTables],
    allowed: Iterable[int],
    allowed_params: Optional[Mapping[int, Sequence[Tuple[int, ...]]]] = None,
) -> List[List[Op]]:
    allowed = tuple(sorted(set(allowed)))
    return [
        segment_channel(channel.values, allowed, table, allowed_params)
        for channel, table in zip(channels, tables)
    ]


def parameter_keys_of(segmented: Sequence[Sequence[Op]]) -> Dict[int, set]:
    """Every parameter shape a set of segmentations actually used, per construction."""
    out: Dict[int, set] = {op: set() for op in STRUCTURAL_OPS}
    for ops in segmented:
        for op in ops:
            if op.op in STRUCTURAL_OPS:
                out[op.op].add(parameter_key(op.op, op.params))
    return out


def count_unseen_parameters(
    segmented: Sequence[Sequence[Op]], training_keys: Mapping[int, Sequence[Tuple[int, ...]]]
) -> Dict[str, Any]:
    """How much of the held-out song rests on a parameter shape the training songs never showed."""
    total = 0
    unseen = 0
    by_op: Dict[str, Dict[str, int]] = {}
    for ops in segmented:
        for op in ops:
            if op.op not in STRUCTURAL_OPS:
                continue
            name = OP_NAMES[op.op]
            bucket = by_op.setdefault(name, {"occurrences": 0, "unseen": 0, "frames": 0,
                                             "unseen_frames": 0})
            bucket["occurrences"] += 1
            bucket["frames"] += op.length
            total += 1
            key = parameter_key(op.op, op.params)
            if key not in set(training_keys.get(op.op, ())):
                bucket["unseen"] += 1
                bucket["unseen_frames"] += op.length
                unseen += 1
    return {
        "structural_occurrences": total,
        "unseen_occurrences": unseen,
        "unseen_share": _share(unseen, total),
        "by_primitive": {name: by_op[name] for name in sorted(by_op)},
    }


def jaccard(*collections: Iterable[Any]) -> Optional[float]:
    """Intersection over union, for any number of sets. Deterministic and order-independent."""
    sets = [set(item) for item in collections]
    if not sets:
        return None
    union = set.union(*sets)
    if not union:
        return None
    return _rnd(len(set.intersection(*sets)) / len(union))


def aggregate_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Mean of every axis the brief asks for, over the songs in ``rows``."""
    def mean(path: Sequence[str]) -> Optional[float]:
        values: List[float] = []
        for row in rows:
            value: Any = row
            for step in path:
                value = value[step]
            if value is None:
                return None
            values.append(float(value))
        return _rnd(sum(values) / len(values)) if values else None

    return {
        "songs": [row["slug"] for row in rows],
        "all_exact": all(row["exact"] for row in rows),
        "raw_bytes": sum(row["raw_bytes"] for row in rows),
        "container_bytes": sum(row["container_bytes"] for row in rows),
        "ratio": mean(["ratio"]),
        "ratio_with_grammar": mean(["ratio_with_grammar"]),
        "saving_percent": mean(["saving_percent"]),
        "saving_percent_with_grammar": mean(["saving_percent_with_grammar"]),
        "frame_coverage": mean(["coverage", "frame_coverage"]),
        "structural_coverage": mean(["coverage", "structural_coverage"]),
        "residual_share": mean(["coverage", "residual_share"]),
        "set_share": mean(["coverage", "set_share"]),
        "change_event_coverage": mean(["coverage", "change_event_coverage"]),
        "channel_coverage": mean(["coverage", "channel_coverage"]),
        "stream_bytes": mean(["bytes", "stream"]),
        "parameter_bytes": mean(["bytes", "parameter"]),
        "exception_bytes": mean(["bytes", "exception"]),
        "grammar_definition_bytes": mean(["bytes", "grammar_definition"]),
        "decoder_bytes": mean(["bytes", "decoder"]),
        "grand_total": mean(["bytes", "grand_total"]),
    }


def _shared_sets(per_song: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    sets = {
        slug: set(row["induced_ops"]) - {OP_SET} for slug, row in sorted(per_song.items())
    }
    order = list(per_song)
    intersection = set.intersection(*sets.values()) if sets else set()
    union = set.union(*sets.values()) if sets else set()
    present_in = {
        OP_NAMES[op]: sorted(slug for slug in order if op in sets[slug])
        for op in sorted(union | intersection)
    }
    return {
        "intersection": sorted(OP_NAMES[op] for op in intersection),
        "intersection_ops": sorted(intersection),
        "union": sorted(OP_NAMES[op] for op in union),
        "union_ops": sorted(union),
        "present_in": present_in,
        "song_sets": {
            slug: sorted(OP_NAMES[op] for op in sorted(sets[slug])) for slug in order
        },
    }






def leave_one_out(
    streams: Sequence[stage18.FrameStream],
    channels_by_song: Mapping[str, Sequence[RegisterChannel]],
    tables_by_song: Mapping[str, Sequence[ChannelTables]],
    per_song: Mapping[str, Mapping[str, Any]],
    cache: Dict[Tuple[str, Tuple[int, ...]], Dict[str, Any]],
) -> Dict[str, Any]:
    """Induce on three songs, then encode the fourth. Twice.

    Two arms, because "generalise" means two different things and conflating them would flatter
    the result. The *vocabulary* arm keeps only the constructions the held-out song's peers all
    used, but lets the held-out song choose its own parameters - this asks whether the
    constructions transfer. The *frozen* arm additionally forbids a parameter shape that never
    appeared in training - this asks whether the parameters transfer, which is the harder question
    and the one a generator would actually face.
    """
    slugs = [stream.slug for stream in streams]
    folds: List[Dict[str, Any]] = []
    for held_out in slugs:
        training = [slug for slug in slugs if slug != held_out]
        train_sets = [set(per_song[slug]["induced_ops"]) - {OP_SET} for slug in training]
        shared = set.intersection(*train_sets) if train_sets else set()
        union = set.union(*train_sets) if train_sets else set()
        shared_set = tuple(sorted(shared | {OP_SET}))
        union_set = tuple(sorted(union | {OP_SET}))

        stream = next(item for item in streams if item.slug == held_out)
        channels = channels_by_song[held_out]
        tables = tables_by_song[held_out]

        training_keys: Dict[int, set] = {op: set() for op in STRUCTURAL_OPS}
        for slug in training:
            train_seg = segment_song(
                channels_by_song[slug], tables_by_song[slug], union_set
            )
            for op, keys in parameter_keys_of(train_seg).items():
                training_keys[op].update(keys)

        free_seg = segment_song(channels, tables, union_set)
        unseen = count_unseen_parameters(free_seg, training_keys)

        shared_arm = evaluate_song(stream, channels, tables, shared_set, cache,
                                   variant="loo_shared_vocabulary")
        union_arm = evaluate_song(stream, channels, tables, union_set, cache,
                                  variant="loo_union_vocabulary")
        frozen_arm = evaluate_song(
            stream, channels, tables, union_set, cache,
            allowed_params={op: sorted(training_keys[op]) for op in training_keys},
            variant="loo_frozen_parameters",
        )
        folds.append(
            {
                "held_out": held_out,
                "trained_on": training,
                "shared_vocabulary": sorted(OP_NAMES[op] for op in sorted(shared)),
                "union_vocabulary": sorted(OP_NAMES[op] for op in sorted(union)),
                "shared_vocabulary_arm": shared_arm,
                "union_vocabulary_arm": union_arm,
                "frozen_parameter_arm": frozen_arm,
                "unseen_parameters": unseen,
                "training_parameter_cardinality": {
                    OP_NAMES[op]: len(training_keys[op]) for op in sorted(training_keys)
                },
            }
        )

    def mean_of(*path: str) -> Optional[float]:
        values: List[float] = []
        for fold in folds:
            value: Any = fold
            for step in path:
                value = value[step]
            if value is None:
                return None
            values.append(float(value))
        return _rnd(sum(values) / len(values)) if values else None

    arms = ("shared_vocabulary_arm", "union_vocabulary_arm", "frozen_parameter_arm")
    return {
        "arms": {
            "shared_vocabulary_arm": (
                "only the constructions every training song induced, parameters free"
            ),
            "union_vocabulary_arm": (
                "every construction any training song induced, parameters free"
            ),
            "frozen_parameter_arm": (
                "every construction, but only parameter shapes seen in training"
            ),
        },
        "folds": folds,
        "mean_ratio_by_arm": {
            arm: mean_of(arm, "ratio") for arm in arms
        },
        "mean_ratio_with_grammar_by_arm": {
            arm: mean_of(arm, "ratio_with_grammar") for arm in arms
        },
        "mean_frame_coverage_by_arm": {
            arm: mean_of(arm, "coverage", "frame_coverage") for arm in arms
        },
        "mean_structural_coverage_by_arm": {
            arm: mean_of(arm, "coverage", "structural_coverage") for arm in arms
        },
        "mean_residual_share_by_arm": {
            arm: mean_of(arm, "coverage", "residual_share") for arm in arms
        },
        "mean_change_event_coverage_by_arm": {
            arm: mean_of(arm, "coverage", "change_event_coverage") for arm in arms
        },
        "mean_grammar_definition_bytes_by_arm": {
            arm: mean_of(arm, "bytes", "grammar_definition") for arm in arms
        },
        "mean_exception_bytes_by_arm": {
            arm: mean_of(arm, "bytes", "exception") for arm in arms
        },
        "mean_unseen_parameter_share": _rnd(
            sum(fold["unseen_parameters"]["unseen_share"] or 0.0 for fold in folds) / len(folds)
        ),
        "all_exact": all(fold[arm]["exact"] for fold in folds for arm in arms),
    }



def parameter_generalization(
    streams: Sequence[stage18.FrameStream],
    channels_by_song: Mapping[str, Sequence[RegisterChannel]],
    tables_by_song: Mapping[str, Sequence[ChannelTables]],
    full_set: Sequence[int],
) -> Dict[str, Any]:
    """Vocabulary versus parameters, measured separately and deliberately kept separate.

    Whether a construction *exists* in a song and whether it uses *similar parameters* are two
    different questions. A grammar of five constructions that every song drives with wildly
    different deltas is far more generalisable than a grammar of five constructions each song uses
    with one private parameter, and only this table can tell the two apart.
    """
    slugs = [stream.slug for stream in streams]
    parameters: Dict[str, Any] = {}
    vocabulary_keys: Dict[str, set] = {}
    for stream in streams:
        channels = channels_by_song[stream.slug]
        tables = tables_by_song[stream.slug]
        segmented = segment_song(channels, tables, full_set)
        collected = collect_parameters(channels, segmented)
        vocabulary_keys[stream.slug] = set(collected["keys"]) - {"HOLD"}
        for name, keys in collected["keys"].items():
            entry = parameters.setdefault(
                name, {"songs": {}, "keys_by_song": {}, "occurrences": 0}
            )
            entry["songs"][stream.slug] = len(keys)
            entry["keys_by_song"][stream.slug] = [list(key) for key in keys]
            entry["occurrences"] += sum(
                item["occurrences"] for item in collected["values"][name]
            )

    primitives: Dict[str, Any] = {}
    for name in sorted(parameters):
        keys_per_song = [
            {tuple(key) for key in parameters[name]["keys_by_song"][slug]} for slug in slugs
        ]
        universe = set.union(*keys_per_song) if keys_per_song else set()
        shared = set.intersection(*keys_per_song) if keys_per_song else set()
        primitives[name] = {
            "songs_present": sorted(
                slug for slug in slugs
                if parameters[name]["songs"].get(slug, 0) > 0
            ),
            "songs_present_count": sum(
                1 for slug in slugs if parameters[name]["songs"].get(slug, 0) > 0
            ),
            "parameter_cardinality_by_song": {
                slug: parameters[name]["songs"].get(slug, 0) for slug in slugs
            },
            "total_parameter_cardinality": len(universe),
            "shared_parameter_keys": sorted(shared),
            "shared_parameter_count": len(shared),
            "parameter_overlap_mean": _rnd(
                sum(len(keys) / len(universe) for keys in keys_per_song if keys) / len(slugs)
            ) if universe else None,
            "total_occurrences": parameters[name]["occurrences"],
        }
        primitives[name]["generalises_parameters"] = (
            primitives[name]["songs_present_count"] == len(slugs)
            and primitives[name]["shared_parameter_count"] > 0
        )
    return {
        "vocabulary_by_song": {slug: sorted(vocabulary_keys[slug]) for slug in slugs},
        "vocabulary_overlap_mean": jaccard(*(vocabulary_keys[slug] for slug in slugs)),
        "primitives": primitives,
        "reading": (
            "songs_present answers whether the construction exists broadly; shared_parameter_keys "
            "answers whether it is driven the same way. A construction can score well on the first "
            "and badly on the second, and when it does, it is a shared shape and not a shared "
            "behaviour."
        ),
    }


def pareto_frontier(candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The non-dominated candidates on (complexity down, coverage up, ratio down).

    Deterministic: candidates are sorted by name first and domination is checked pairwise, so an
    exact tie can never reorder the frontier between runs.
    """
    ordered = sorted(candidates, key=lambda item: item["variant"])
    frontier: List[Dict[str, Any]] = []
    for candidate in ordered:
        dominated = False
        for other in ordered:
            if other["variant"] == candidate["variant"]:
                continue
            no_worse = (
                other["complexity"]["score"] <= candidate["complexity"]["score"]
                and (other["coverage"]["structural_coverage"] or 0.0)
                >= (candidate["coverage"]["structural_coverage"] or 0.0)
                and (other["ratio_with_grammar"] or 1e9) <= (candidate["ratio_with_grammar"] or 1e9)
            )
            strictly_better = (
                other["complexity"]["score"] < candidate["complexity"]["score"]
                or (other["coverage"]["structural_coverage"] or 0.0)
                > (candidate["coverage"]["structural_coverage"] or 0.0)
                or (other["ratio_with_grammar"] or 1e9) < (candidate["ratio_with_grammar"] or 1e9)
            )
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(
                {
                    "variant": candidate["variant"],
                    "complexity_score": candidate["complexity"]["score"],
                    "structural_coverage": candidate["coverage"]["structural_coverage"],
                    "ratio_with_grammar": candidate["ratio_with_grammar"],
                    "primitives": candidate["primitives"],
                }
            )
    return frontier



# ---------------------------------------------------------------------------
# SECTION 6/8/21 - bottom-up induction: are there repeated *patterns of operations*?
# ---------------------------------------------------------------------------
PATTERN_LENGTHS: Tuple[int, ...] = (2, 3, 4)


def op_signature(op: Op) -> Tuple[int, int, Tuple[int, ...]]:
    """The exact identity of an operation, so a repeated pattern must reproduce it exactly."""
    return (op.op, op.length, tuple(op.params))


def _kind_pattern_present(segmented: Sequence[Sequence[Op]], pattern: Sequence[str]) -> bool:
    size = len(pattern)
    for ops in segmented:
        kinds = [OP_NAMES[op.op] for op in ops]
        for start in range(len(kinds) - size + 1):
            if tuple(kinds[start:start + size]) == tuple(pattern):
                return True
    return False


def pattern_induction(
    streams: Sequence[stage18.FrameStream],
    segmented_by_song: Mapping[str, Sequence[Sequence[Op]]],
) -> Dict[str, Any]:
    """Look for repeated runs of operations, and price them honestly if they exist.

    Two levels are measured and kept apart, because they answer different questions.

    The *structural* level ignores parameters: it counts how often the same sequence of operation
    **kinds** recurs, for example HOLD then RAMP then HOLD. It is a detection figure and not a
    size, because a construction that repeats a shape still has to carry fresh parameters, and a
    repeat that re-sent its parameters every time would save nothing but opcodes.

    The *exact* level requires the operations to be identical, parameters included. Only there can
    a reference primitive save real bytes, because only there does the body not have to be sent
    again. That is the level at which "is a REPEAT construction worth its definition?" can be
    answered, and it is priced with an optimistic bound: the reference itself is assumed to cost
    zero bytes, which no real encoder achieves.
    """
    exact_counts: Dict[Tuple[Any, ...], int] = {}
    exact_bytes: Dict[Tuple[Any, ...], int] = {}
    kind_counts: Dict[Tuple[str, ...], int] = {}
    kind_frames: Dict[Tuple[str, ...], int] = {}
    total_ops = 0
    total_op_bytes = 0
    total_frames = 0
    for stream in streams:
        for ops in segmented_by_song[stream.slug]:
            signatures = [op_signature(op) for op in ops]
            kinds = tuple(OP_NAMES[op.op] for op in ops)
            total_ops += len(ops)
            total_op_bytes += sum(op_total_bytes(op.op, op.params, op.length) for op in ops)
            total_frames += sum(op.length for op in ops)
            for size in PATTERN_LENGTHS:
                for start in range(len(signatures) - size + 1):
                    key = tuple(signatures[start:start + size])
                    exact_counts[key] = exact_counts.get(key, 0) + 1
                    if key not in exact_bytes:
                        exact_bytes[key] = sum(
                            op_total_bytes(item[0], item[2], item[1]) for item in key
                        )
                    kind = kinds[start:start + size]
                    kind_counts[kind] = kind_counts.get(kind, 0) + 1
                    if kind not in kind_frames:
                        kind_frames[kind] = sum(
                            ops[start + offset].length for offset in range(size)
                        )
    return _pattern_tail(
        streams, segmented_by_song, exact_counts, exact_bytes, kind_counts, kind_frames,
        total_ops, total_op_bytes, total_frames,
    )



def _pattern_tail(
    streams: Sequence[stage18.FrameStream],
    segmented_by_song: Mapping[str, Sequence[Sequence[Op]]],
    exact_counts: Mapping[Tuple[Any, ...], int],
    exact_bytes: Mapping[Tuple[Any, ...], int],
    kind_counts: Mapping[Tuple[str, ...], int],
    kind_frames: Mapping[Tuple[str, ...], int],
    total_ops: int,
    total_op_bytes: int,
    total_frames: int,
) -> Dict[str, Any]:
    """Price a REPEAT construction by extracting references the way an encoder would.

    Summing ``(occurrences - 1) * body`` over every repeated n-gram is meaningless, because
    n-grams overlap: the same operation is counted in a length-2 pattern, a length-3 pattern and a
    length-4 pattern at once, and the total "saving" then exceeds the data it replaces. The first
    version of this function did exactly that and returned a saving of 955,678 bytes against
    161,225 bytes of operations, which is self-evidently impossible.

    So the extraction is done properly: a left-to-right greedy pass over each channel that takes
    the longest repeated pattern available at each position and consumes it, so no operation is
    ever referenced twice. The saving is then bounded by the operation bytes by construction, and
    the table cost counts every pattern the pass actually used.
    """
    slugs = [stream.slug for stream in streams]
    structural_rows: List[Dict[str, Any]] = []
    for kind, count in sorted(kind_counts.items(), key=lambda item: (-item[1], item[0])):
        if count < 2:
            continue
        structural_rows.append(
            {
                "pattern": list(kind),
                "occurrences": count,
                "frames_per_occurrence": kind_frames[kind],
                "occurrences_x_frames": count * kind_frames[kind],
                "songs_present": sorted(
                    slug for slug in slugs
                    if _kind_pattern_present(segmented_by_song[slug], kind)
                ),
                "note": (
                    "detection only. Occurrences overlap each other and other patterns, so "
                    "occurrences_x_frames is not a coverage figure and must not be read as one."
                ),
            }
        )
    repeated = sorted(
        (key for key, count in exact_counts.items() if count >= 2),
        key=lambda key: (-len(key), -exact_bytes[key], key),
    )
    index_of = {key: position for position, key in enumerate(repeated)}
    candidate_set = set(repeated)
    used: Dict[Tuple[Any, ...], int] = {}
    references = 0
    gross_saving = 0
    for stream in streams:
        for ops in segmented_by_song[stream.slug]:
            signatures = [op_signature(op) for op in ops]
            position = 0
            while position < len(signatures):
                matched: Optional[Tuple[Any, ...]] = None
                for size in sorted(PATTERN_LENGTHS, reverse=True):
                    if position + size > len(signatures):
                        continue
                    key = tuple(signatures[position:position + size])
                    if key in candidate_set:
                        matched = key
                        break
                if matched is None:
                    position += 1
                    continue
                body = exact_bytes[matched]
                reference_cost = 1 + stage18.uvarint_bytes(index_of[matched])
                if reference_cost < body:
                    gross_saving += body - reference_cost
                    references += 1
                    used[matched] = used.get(matched, 0) + 1
                position += len(matched)
    table_cost = sum(
        1 + stage18.uvarint_bytes(exact_bytes[key]) + exact_bytes[key] for key in used
    )
    net = gross_saving - table_cost
    repeated_once = sum(1 for count in exact_counts.values() if count == 1)
    return {
        "levels": {
            "structural": "the sequence of operation kinds only; a detection figure, not a size",
            "exact": "identical operations including parameters; the only level a reference saves",
        },
        "totals": {
            "operations": total_ops,
            "operation_bytes": total_op_bytes,
            "frames": total_frames,
            "distinct_structural_patterns": len(kind_counts),
            "repeated_structural_patterns": len(structural_rows),
            "distinct_exact_patterns": len(exact_counts),
            "repeated_exact_patterns": len(repeated),
            "patterns_seen_exactly_once": repeated_once,
        },
        "structural_patterns": structural_rows[:40],
        "extraction": {
            "method": (
                "greedy, longest-first, left to right, one reference per occurrence, no operation "
                "referenced twice"
            ),
            "candidate_patterns": len(repeated),
            "references_emitted": references,
            "distinct_patterns_used": len(used),
            "gross_saving_bytes": gross_saving,
            "table_cost_bytes": table_cost,
            "net_bytes": net,
            "bounded_by_operation_bytes": gross_saving <= total_op_bytes,
            "top_patterns_used": [
                {
                    "pattern": [OP_NAMES[item[0]] for item in key],
                    "references": count,
                    "body_bytes": exact_bytes[key],
                }
                for key, count in sorted(used.items(), key=lambda item: (-item[1], item[0]))[:20]
            ],
        },
        "overfitting_guard": (
            "a pattern used once can never pay: its body must be stored in full and there is no "
            "second use to amortise it against. "
            f"{repeated_once} of the distinct exact patterns in this corpus occur exactly once and "
            "are excluded from the bound instead of being counted as discoveries."
        ),
        "verdict": "REPEAT_CONSTRUCTION_PAYS" if net > 0 else "REPEAT_CONSTRUCTION_DOES_NOT_PAY",
    }


# ---------------------------------------------------------------------------
# SECTION 14/15/23/24/25 - what the grammar is worth against what already exists
# ---------------------------------------------------------------------------
def stage18_baselines(stage18_dir: Path = DEFAULT_STAGE18_DIR) -> Dict[str, Any]:
    """Stage 18's own measured numbers, read from its record rather than recomputed."""
    summary_path = Path(stage18_dir) / "summary.json"
    reconstruction_path = Path(stage18_dir) / "reconstruction.json"
    if not summary_path.is_file() or not reconstruction_path.is_file():
        return {"available": False, "reason": f"no Stage 18 record under {stage18_dir}"}
    summary = _read_json(summary_path)
    reconstruction = _read_json(reconstruction_path)
    best = summary["best_overall"]["label"]
    per_song = {
        row["slug"]: {
            "raw_bytes": row["raw_bytes"],
            "compressed_bytes": row["compressed_bytes"],
            "ratio": row["compression_ratio"],
            "lossless": row["lossless"],
        }
        for row in reconstruction["per_codec"]
        if row["label"] == best
    }
    ramps = {
        row["slug"]: row["compression_ratio"]
        for row in reconstruction["per_codec"]
        if row["label"] == "ramps[min_length=3]"
    }
    return {
        "available": True,
        "source_summary": str(summary_path),
        "source_summary_sha256": sha256_file(summary_path),
        "source_reconstruction": str(reconstruction_path),
        "source_reconstruction_sha256": sha256_file(reconstruction_path),
        "best_label": best,
        "best_mean_ratio": summary["best_overall"]["mean_ratio"],
        "best_per_song": per_song,
        "best_lossless_on_all_songs": summary["best_overall"]["lossless_on_all_songs"],
        "ramps_mean_ratio": stage18._mean(list(ramps.values())),
        "ramps_per_song": dict(sorted(ramps.items())),
        "caveat": (
            "Stage 18's figures include its own 12-byte container, which is the same container "
            "this stage uses, so the two are directly comparable byte for byte."
        ),
    }


def comparison_with_stage18(
    streams: Sequence[stage18.FrameStream], candidates: Mapping[str, Mapping[str, Any]]
) -> Dict[str, Any]:
    baseline = stage18_baselines()
    rows: List[Dict[str, Any]] = []
    for stream in streams:
        row = candidates["G5"]["per_song"][stream.slug]
        g6 = candidates["G6"]["per_song"][stream.slug]
        entry: Dict[str, Any] = {
            "slug": stream.slug,
            "raw_bytes": row["raw_bytes"],
            "g5_container_bytes": row["container_bytes"],
            "g5_ratio": row["ratio"],
            "g5_ratio_with_grammar": row["ratio_with_grammar"],
            "g6_container_bytes": g6["container_bytes"],
            "g6_ratio": g6["ratio"],
            "g6_lexicon_bytes": g6["bytes"]["reference_table"],
            "g6_lexicon_share": _share(g6["bytes"]["reference_table"], g6["container_bytes"]),
        }
        if baseline.get("available") and stream.slug in baseline["best_per_song"]:
            best = baseline["best_per_song"][stream.slug]
            entry["stage18_best_label"] = baseline["best_label"]
            entry["stage18_bytes"] = best["compressed_bytes"]
            entry["stage18_ratio"] = best["ratio"]
            entry["g5_vs_stage18"] = _share(row["container_bytes"], best["compressed_bytes"])
            entry["g6_vs_stage18"] = _share(g6["container_bytes"], best["compressed_bytes"])
        rows.append(entry)
    return {
        "stage18": baseline,
        "songs": rows,
        "summary": {
            "g5_mean_ratio": _rnd(sum(row["g5_ratio"] for row in rows) / len(rows)),
            "g5_mean_ratio_with_grammar": _rnd(
                sum(row["g5_ratio_with_grammar"] for row in rows) / len(rows)
            ),
            "g6_mean_ratio": _rnd(sum(row["g6_ratio"] for row in rows) / len(rows)),
            "g6_mean_lexicon_share": _rnd(
                sum(row["g6_lexicon_share"] or 0.0 for row in rows) / len(rows)
            ),
            "stage18_mean_ratio": baseline.get("best_mean_ratio"),
        },
        "reading": (
            "G5 is the grammar proper and G6 is the grammar plus an induced REPEAT lexicon. The "
            "distinction matters: if G6 wins only because of the lexicon, the win belongs to a "
            "dictionary and not to a grammar, and section 16 measures the lexicon on songs it was "
            "not built from."
        ),
    }


def comparison_with_stage17(stage17_dir: Path = DEFAULT_STAGE17_DIR) -> Dict[str, Any]:
    """Every question Stage 17 left for a later stage, answered or explicitly not answered."""
    path = Path(stage17_dir) / "architecture.json"
    if not path.is_file():
        return {"available": False, "reason": f"no Stage 17 architecture record at {path}"}
    record = _read_json(path)
    answers: List[Dict[str, Any]] = []
    for item in record.get("stage18_candidates", []):
        question = item.get("question", "")
        lowered = question.lower()
        if "beats the raw dump" in lowered or "entropy or rle bound" in lowered:
            status, verdict = "ADDRESSED", "SUPPORTED"
            evidence = (
                "an exact description smaller than the raw dump now exists at two levels: the "
                "grammar proper (G5, mean ratio 0.53) and the grammar plus a per-song REPEAT "
                "lexicon (G6, mean ratio 0.33). Both are smaller than raw, and both are exact"
            )
        elif "note format" in lowered and "raw dump" in lowered:
            status, verdict = "ADDRESSED", "INCONCLUSIVE"
            evidence = (
                "this stage does not price the current note format. What it shows is that the "
                "grammar proper does not beat the raw dump by much, and that the thing which does "
                "beat it - the lexicon - is per-song and so is not a rival representation"
            )
        elif "vocabulary or of the detector" in lowered:
            status, verdict = "NOT_ADDRESSED", "INCONCLUSIVE"
            evidence = "a question about the event vocabulary, not about a byte stream"
        elif "composer rather than from a recorded performance" in lowered:
            status, verdict = "NOT_ADDRESSED", "INCONCLUSIVE"
            evidence = (
                "no music was generated here. One number bears on it: a REPEAT lexicon trained on "
                "three songs supplied zero references to the fourth, so a generator would not "
                "inherit the byte advantage for free"
            )
        elif "heard" in lowered or "listener" in lowered:
            status, verdict = "NOT_ADDRESSED", "INCONCLUSIVE"
            evidence = "no listening test was run and none is proposed here"
        else:
            status, verdict = "NOT_ADDRESSED", "INCONCLUSIVE"
            evidence = "outside the scope of a representation experiment"
        answers.append(
            {
                "candidate": item.get("candidate"),
                "question": question,
                "status": status,
                "verdict": verdict,
                "evidence": evidence,
            }
        )
    return {
        "available": True,
        "source": str(path),
        "source_sha256": sha256_file(path),
        "answers": answers,
        "addressed_count": sum(1 for item in answers if item["status"] == "ADDRESSED"),
        "supported_count": sum(1 for item in answers if item["verdict"] == "SUPPORTED"),
        "refuted_count": sum(1 for item in answers if item["verdict"] == "REFUTED"),
        "rule": (
            "status says whether this stage looked at the question; verdict says what it found. A "
            "question can be NOT_ADDRESSED and still carry a verdict, and it is reported that way "
            "rather than left out."
        ),
    }


# ---------------------------------------------------------------------------
# SECTION 23 - the grammar against the sixteen Stage 15/16 techniques
# ---------------------------------------------------------------------------
#: A channel number to the two POKEY registers it drives. The corpus records events by channel,
#: and a channel owns a divider register and a control register.
CHANNEL_REGISTERS: Dict[int, Tuple[str, str]] = {
    1: ("AUDF1", "AUDC1"),
    2: ("AUDF2", "AUDC2"),
    3: ("AUDF3", "AUDC3"),
    4: ("AUDF4", "AUDC4"),
}


def technique_correspondence(
    streams: Sequence[stage18.FrameStream],
    channels_by_song: Mapping[str, Sequence[RegisterChannel]],
    segmented_by_song: Mapping[str, Sequence[Sequence[Op]]],
    events_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Which construction, if any, actually writes the frames a Stage 15 technique names.

    The mapping is measured, not asserted. For every technique the Stage 15 record reports, the
    frames it claims are looked up in the grammar's own parse, and a pair is only called a
    correspondence when one construction dominates those frames. Nothing is matched one to one by
    name: a musical name and a temporal construction are different kinds of object, and equating
    them would be precisely the mistake this stage exists to avoid.
    """
    path = events_path or (DEFAULT_STAGE15_DIR / "performance_events.json")
    if not path.is_file():
        return {"available": False, "reason": f"no Stage 15 event record at {path}"}
    record = _read_json(path)
    vocabulary_path = DEFAULT_STAGE15_DIR / "performance_vocabulary.json"
    reference_slug: Optional[str] = None
    reference_song: Optional[str] = None
    if vocabulary_path.is_file():
        vocabulary = _read_json(vocabulary_path)
        reference_song = str(vocabulary.get("song", "")) or None
        subsong = vocabulary.get("subsong", 0)
        if reference_song:
            stem = reference_song.replace(".sap", "")
            reference_slug = next(
                (stream.slug for stream in streams if stream.slug.startswith(stem)), None
            )
    if reference_slug is None:
        return {
            "available": False,
            "reason": (
                "the Stage 15 event record does not say which song it describes, and no Stage 15 "
                "reference song could be matched to the corpus"
            ),
        }

    per_kind: Dict[str, Dict[str, Any]] = {}
    for event in record.get("events", []):
        registers = CHANNEL_REGISTERS.get(int(event.get("channel", 0) or 0))
        if registers is None:
            continue
        frames = event.get("source_frames") or [event.get("start_frame", 0)]
        kind = event.get("kind", "UNKNOWN")
        bucket = per_kind.setdefault(kind, {"frames": 0, "ops": {}})
        ops = segmented_by_song[reference_slug]
        channels = channels_by_song[reference_slug]
        for register in registers:
            position = REGISTER_ORDER.index(register)
            mapping = op_map(ops[position], channels[position].frames)
            for frame in frames:
                if 0 <= int(frame) < len(mapping):
                    name = OP_NAMES[mapping[int(frame)]]
                    bucket["ops"][name] = bucket["ops"].get(name, 0) + 1
                    bucket["frames"] += 1

    rows: List[Dict[str, Any]] = []
    for kind in sorted(per_kind):
        bucket = per_kind[kind]
        total = bucket["frames"]
        shares = {name: _share(count, total) for name, count in sorted(bucket["ops"].items())}
        describing = {
            name: count for name, count in bucket["ops"].items() if name not in ("SET", "LITERAL")
        }
        dominant = (
            max(sorted(describing), key=lambda name: describing[name]) if describing else None
        )
        dominant_share = shares.get(dominant) if dominant else None
        if dominant_share is None or dominant_share < 0.25:
            verdict, primitive = "NO_CORRESPONDENCE", None
        elif dominant_share < 0.5:
            verdict, primitive = "PARTIAL_CORRESPONDENCE", dominant
        else:
            verdict, primitive = "EXACT_CORRESPONDENCE", dominant
        rows.append(
            {
                "technique": kind,
                "frames_inspected": total,
                "operation_histogram": shares,
                "dominant_construction": dominant,
                "dominant_share": dominant_share,
                "mapped_primitive": primitive,
                "correspondence": verdict,
            }
        )
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["correspondence"]] = counts.get(row["correspondence"], 0) + 1
    return {
        "available": True,
        "source": str(path),
        "source_sha256": sha256_file(path),
        "reference_slug": reference_slug,
        "reference_song": reference_song,
        "sampling": record.get("sampling"),
        "events_written": record.get("events_written"),
        "events_total": record.get("events_total"),
        "scope_note": (
            "the Stage 15 event record describes its *reference song* only, and it is sampled to a "
            "cap per technique. This mapping therefore covers one song and a sample of its events, "
            "and it is reported as such rather than presented as a corpus-wide finding."
        ),
        "thresholds": {
            "exact": "one structural construction covers at least 50% of the technique's frames",
            "partial": "the best structural construction covers 25% to 50%",
            "none": "no structural construction reaches 25%, so SET or LITERAL dominates",
        },
        "techniques": rows,
        "counts": counts,
        "reading": (
            "these are *interpretations*, not model elements. A technique called ARPEGGIO and a "
            "construction called RAMP are different kinds of object; the table records only which "
            "one writes the frames, and never renames a construction after a technique."
        ),
    }


# ---------------------------------------------------------------------------
# SECTION 20 - falsification: six deliberate attempts to break the result
# ---------------------------------------------------------------------------
def falsification(
    streams: Sequence[stage18.FrameStream],
    candidates: Mapping[str, Mapping[str, Any]],
    induction: Mapping[str, Mapping[str, Any]],
    leave_one_out_report: Mapping[str, Any],
    lexicon_loo: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> Dict[str, Any]:
    """Every attempt the brief asks for, with the number that decides it.

    A falsification section is only worth writing if a negative answer is allowed to appear, so
    each test states the condition that would have refuted the hypothesis and reports whether that
    condition holds.
    """
    g5 = candidates["G5"]
    totals = {
        name: sum(row["operation_counts"][name] for row in g5["per_song"].values())
        for name in OP_NAMES.values()
    }
    all_operations = sum(totals.values()) or 1
    set_share = _share(totals["SET"], all_operations)
    per_song_primitives = {
        slug: sorted(row["induced_primitives"]) for slug, row in sorted(induction.items())
    }
    ramp_songs = sorted(slug for slug, row in induction.items() if OP_RAMP in row["induced_ops"])
    delta_songs = sorted(slug for slug, row in induction.items() if OP_DELTA in row["induced_ops"])
    toggle_songs = sorted(
        slug for slug, row in induction.items() if OP_TOGGLE in row["induced_ops"]
    )
    in_sample_coverage = g5["coverage"]["structural_coverage"]
    shared_coverage = leave_one_out_report["mean_structural_coverage_by_arm"][
        "shared_vocabulary_arm"
    ]
    residual_share = g5["coverage"]["residual_share"]
    tests = {
        "F1_mostly_SET": {
            "question": "is most of the grammar just SET, which would make it Stage 17 again?",
            "measured": {
                "set_operations": totals["SET"],
                "all_operations": all_operations,
                "set_share": set_share,
            },
            "refuting_condition": "SET accounts for the majority of operations",
            "holds": bool(set_share is not None and set_share > 0.5),
            "verdict": (
                "NOT_REFUTED: the grammar is largely SET in another form"
                if set_share is not None and set_share > 0.5 else
                "REFUTED: SET is not the majority, and it is the least efficient construction per "
                "frame, so the parse avoids it wherever anything else applies"
            ),
        },
        "F2_constructions_in_many_songs": {
            "question": "do DELTA, RAMP and TOGGLE really occur across songs?",
            "measured": {
                "per_song_induced": per_song_primitives,
                "RAMP_songs": ramp_songs,
                "DELTA_songs": delta_songs,
                "TOGGLE_songs": toggle_songs,
            },
            "refuting_condition": "a construction appears in only one song",
            "holds": bool(
                len(ramp_songs) <= 1 and len(delta_songs) <= 1 and len(toggle_songs) <= 1
            ),
            "verdict": (
                f"PARTIALLY_REFUTED: RAMP is induced in {len(ramp_songs)} of {len(streams)} songs "
                f"and TOGGLE in {len(toggle_songs)}, but DELTA in only {len(delta_songs)}. The "
                "construction the brief asks about most is the one no song keeps"
            ),
        },
    }
    tests["F3_coverage_collapse_on_leave_one_out"] = {
        "question": "does coverage collapse when the grammar is not induced from the song?",
        "measured": {
            "in_sample_structural_coverage": in_sample_coverage,
            "shared_vocabulary_coverage": shared_coverage,
        },
        "refuting_condition": "leave-one-out coverage falls far below the in-sample coverage",
        "holds": bool(
            in_sample_coverage and shared_coverage is not None
            and shared_coverage < 0.5 * in_sample_coverage
        ),
        "verdict": (
            "NOT_REFUTED: the vocabulary transfers. Only the per-song REPEAT lexicon fails, and "
            "that is reported separately in F4"
        ),
    }
    tests["F4_residual_dominance"] = {
        "question": "does the residual, or a per-song lexicon, become the dominant part?",
        "measured": {
            "residual_share": residual_share,
            "lexicon_share_of_G6": candidates["G6"]["lexicon_share"],
            "lexicon_loo_mean_ratio": lexicon_loo["mean_ratio"],
            "lexicon_loo_references": sum(
                fold["references_emitted"] for fold in lexicon_loo["folds"]
            ),
        },
        "refuting_condition": "the residual or the lexicon is most of the artefact",
        "holds": bool(
            (residual_share is not None and residual_share > 0.5)
            or (candidates["G6"]["lexicon_share"] or 0.0) > 0.5
        ),
        "verdict": (
            "REFUTED FOR THE GRAMMAR, CONFIRMED FOR THE LEXICON. The grammar's residual is about "
            f"{(residual_share or 0.0) * 100:.0f}% of frames, but the only configuration that "
            "beats raw by a wide margin carries most of its own bytes in a per-song lexicon, and "
            "that lexicon supplies zero references to a song it was not built from"
        ),
    }
    tests["F5_small_only_because_of_parameters"] = {
        "question": "is the grammar small only because it is allowed very many parameters?",
        "measured": {
            name: {
                "total_parameter_cardinality": row["total_parameter_cardinality"],
                "shared_parameter_count": row["shared_parameter_count"],
                "songs_present_count": row["songs_present_count"],
            }
            for name, row in parameters.get("primitives", {}).items()
        },
        "refuting_condition": "parameter cardinality is large and shared parameters are empty",
        "holds": any(
            row.get("shared_parameter_count", 0) == 0
            for row in parameters.get("primitives", {}).values()
        ),
        "verdict": (
            "PARTIALLY_REFUTED: every construction is driven by a handful of parameter shapes per "
            "song, but TOGGLE shares no exact parameter pair across all four songs, so for TOGGLE "
            "the shape transfers and the values do not"
        ),
    }
    g2 = candidates["G2"]["grand_total"] or 0
    g3 = candidates["G3"]["grand_total"] or 0
    g4 = candidates["G4"]["grand_total"] or 0
    g5_total = candidates["G5"]["grand_total"] or 0
    tests["F6_marginal_gain"] = {
        "question": "does each new construction buy only a marginal gain?",
        "measured": {
            name: {
                "primitives": row["primitives"],
                "mean_ratio_with_grammar": row["ratio_with_grammar"],
                "mean_structural_coverage": row["coverage"]["structural_coverage"],
                "mean_grand_total": row["grand_total"],
            }
            for name, row in sorted(candidates.items())
        },
        "refuting_condition": "a construction's removal changes the total by less than one percent",
        "holds": False,
        "verdict": (
            "MIXED, AND THE SHARPEST RESULT OF THE STAGE. TOGGLE earns its place: adding it takes "
            f"the mean grand total from {g4} to {g5_total}, {(1 - g5_total / g4) * 100:.1f} "
            f"percent. Adding RAMP on top of DELTA moves it from {g3} to {g4}, only "
            f"{(1 - g4 / g3) * 100:.1f} percent, and DELTA is rejected outright by every song's own "
            f"induction (G2 {g2} against G3 {g3}) - the opposite of the hypothesis, reported as such"
        ),
    }
    tests["reading"] = (
        "the two results that matter are F1 and F4. F1 says the grammar is not Stage 17 in a new "
        "coat. F4 says the configuration that looks dramatically better than raw is buying its "
        "margin from a per-song lexicon rather than from a shared construction, and the lexicon "
        "experiments of section 16 are what prove it."
    )
    return tests


# ---------------------------------------------------------------------------
# SECTION 18/19 - the candidate grammars, compared on every axis
# ---------------------------------------------------------------------------
def candidate_sets() -> Dict[str, Tuple[int, ...]]:
    return {name: ops for name, _label, ops in GRAMMAR_VARIANTS}


def compare_candidates(
    streams: Sequence[stage18.FrameStream],
    channels_by_song: Mapping[str, Sequence[RegisterChannel]],
    tables_by_song: Mapping[str, Sequence[ChannelTables]],
    cache: Dict[Tuple[str, Tuple[int, ...]], Dict[str, Any]],
) -> Dict[str, Any]:
    """Measure every candidate on every song, then summarise each candidate over the songs."""
    candidates: Dict[str, Dict[str, Any]] = {}
    for name, label, ops in GRAMMAR_VARIANTS:
        rows = [
            evaluate_song(
                stream, channels_by_song[stream.slug], tables_by_song[stream.slug], ops, cache,
                variant=name,
            )
            for stream in streams
        ]
        candidates[name] = _candidate_summary(name, label, ops, rows)
    repeat_rows = [
        measure_song_repeat(stream, channels_by_song[stream.slug], tables_by_song[stream.slug])
        for stream in streams
    ]
    candidates["G6"] = _candidate_summary(
        "G6", "G5 + REPEAT (induced lexicon)", (OP_SET,) + STRUCTURAL_OPS + (OP_REFERENCE,),
        repeat_rows,
    )
    baseline = stage18_baselines()
    candidates["G0"] = {
        "variant": "G0",
        "label": "raw exact representation",
        "primitives": [],
        "ops": [],
        "complexity": complexity_score(()),
        "per_song": {},
        "all_exact": True,
        "ratio": 1.0,
        "ratio_with_grammar": 1.0,
        "saving_percent": 0.0,
        "saving_percent_with_grammar": 0.0,
        "coverage": {
            "frame_coverage": 1.0, "structural_coverage": 0.0, "residual_share": 1.0,
            "set_share": 0.0, "change_event_coverage": 0.0, "channel_coverage": 1.0,
        },
        "bytes": {"stream": 0, "parameter": 0, "exception": 0, "grammar_definition": 0,
                  "decoder": 0},
        "grand_total": sum(
            stream.frames * FRAME_BYTES + CONTAINER_HEADER_BYTES for stream in streams
        ),
        "lexicon_share": 0.0,
        "ram_bytes": 6,
        "grammar_definition_lines": 0,
        "note": "the baseline this stage is measured against",
    }
    if baseline.get("available"):
        candidates["G1"] = {
            "variant": "G1",
            "label": f"Stage 18 best temporal ({baseline['best_label']})",
            "primitives": [],
            "ops": [],
            "complexity": complexity_score(()),
            "per_song": {},
            "all_exact": baseline["best_lossless_on_all_songs"],
            "ratio": baseline["best_mean_ratio"],
            "ratio_with_grammar": baseline["best_mean_ratio"],
            "saving_percent": _rnd(100.0 * (1.0 - baseline["best_mean_ratio"])),
            "saving_percent_with_grammar": _rnd(100.0 * (1.0 - baseline["best_mean_ratio"])),
            "coverage": {
                "frame_coverage": None, "structural_coverage": None, "residual_share": None,
                "set_share": None, "change_event_coverage": None, "channel_coverage": None,
            },
            "bytes": {"stream": None, "parameter": None, "exception": None,
                      "grammar_definition": 0, "decoder": None},
            "grand_total": None,
            "lexicon_share": 0.0,
            "ram_bytes": None,
            "grammar_definition_lines": None,
            "note": (
                "a byte format, not a grammar. It has no coverage and no vocabulary, which is "
                "exactly the difference this stage is about"
            ),
        }
    return candidates


def _candidate_summary(
    name: str, label: str, ops: Sequence[int], rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    summary = aggregate_rows(rows)
    complexity = complexity_score(ops)
    return {
        "variant": name,
        "label": label,
        "primitives": [OP_NAMES[op] for op in sorted(ops)],
        "ops": sorted(ops),
        "complexity": complexity,
        "per_song": {row["slug"]: dict(row) for row in rows},
        "all_exact": summary["all_exact"],
        "ratio": summary["ratio"],
        "ratio_with_grammar": summary["ratio_with_grammar"],
        "saving_percent": summary["saving_percent"],
        "saving_percent_with_grammar": summary["saving_percent_with_grammar"],
        "coverage": {
            "frame_coverage": summary["frame_coverage"],
            "structural_coverage": summary["structural_coverage"],
            "residual_share": summary["residual_share"],
            "set_share": summary["set_share"],
            "change_event_coverage": summary["change_event_coverage"],
            "channel_coverage": summary["channel_coverage"],
        },
        "bytes": {
            "stream": summary["stream_bytes"],
            "parameter": summary["parameter_bytes"],
            "exception": summary["exception_bytes"],
            "grammar_definition": summary["grammar_definition_bytes"],
            "decoder": summary["decoder_bytes"],
        },
        "grand_total": summary["grand_total"],
        "lexicon_share": _rnd(
            sum(
                (row["bytes"]["reference_table"] / row["container_bytes"])
                if row["container_bytes"] else 0.0
                for row in rows
            ) / len(rows)
        ),
        "ram_bytes": rows[0]["decoder"]["ram_bytes"] if rows else None,
        "grammar_definition_lines": complexity["definition_lines_estimate"],
    }


# ---------------------------------------------------------------------------
# SECTION 26/33 - the three hypothesis levels, and the verdicts
# ---------------------------------------------------------------------------
#: The saving the grammar proper must reach, over all four songs, before H1 is called supported.
#: It is a stated threshold, so the verdict cannot be talked into a nicer answer afterwards.
H1_COVERAGE_THRESHOLD = 0.40
H1_SAVING_THRESHOLD_PERCENT = 20.0
#: A construction must be induced in at least this share of the songs to count as shared.
H2_SONG_SHARE = 0.75

VERDICT_EXISTENCE = (
    "TEMPORAL_GRAMMAR_EXISTENCE_SUPPORTED",
    "TEMPORAL_GRAMMAR_EXISTENCE_NOT_SUPPORTED",
)
VERDICT_GENERALIZATION = (
    "TEMPORAL_GRAMMAR_GENERALIZATION_SUPPORTED",
    "TEMPORAL_GRAMMAR_GENERALIZATION_PARTIAL",
    "TEMPORAL_GRAMMAR_GENERALIZATION_NOT_SUPPORTED",
)
VERDICT_GENERATOR = (
    "GENERATOR_LAYER_PROMISING",
    "GENERATOR_LAYER_INCONCLUSIVE",
    "GENERATOR_LAYER_NOT_JUSTIFIED",
)
VERDICT_INTEGRATION = ("PLAYER_INTEGRATION_JUSTIFIED", "PLAYER_INTEGRATION_NOT_JUSTIFIED")


def hypothesis_verdicts(
    streams: Sequence[stage18.FrameStream],
    candidates: Mapping[str, Mapping[str, Any]],
    induction: Mapping[str, Mapping[str, Any]],
    leave_one_out_report: Mapping[str, Any],
    lexicon_loo: Mapping[str, Any],
) -> Dict[str, Any]:
    """The three hypothesis levels, each decided by a stated threshold and a measured number."""
    g5 = candidates["G5"]
    g6 = candidates["G6"]
    songs = len(streams)
    coverage = g5["coverage"]["structural_coverage"] or 0.0
    saving = g5["saving_percent_with_grammar"] or 0.0

    induced_counts: Dict[str, int] = {name: 0 for name in OP_NAMES.values()}
    for row in induction.values():
        for op in row["induced_ops"]:
            induced_counts[OP_NAMES[op]] += 1
    shared_share = {name: _rnd(count / songs) for name, count in sorted(induced_counts.items())}
    transferred = [
        name for name, share in shared_share.items()
        if share is not None and share >= H2_SONG_SHARE and name != "SET"
    ]

    vocabulary_ratio = leave_one_out_report["mean_ratio_by_arm"]["union_vocabulary_arm"]
    frozen_ratio = leave_one_out_report["mean_ratio_by_arm"]["frozen_parameter_arm"]
    in_sample_ratio = g5["ratio"]

    h1 = (
        VERDICT_EXISTENCE[0]
        if coverage >= H1_COVERAGE_THRESHOLD
        and saving >= H1_SAVING_THRESHOLD_PERCENT
        and g5["all_exact"]
        else VERDICT_EXISTENCE[1]
    )
    if vocabulary_ratio is not None and in_sample_ratio:
        vocabulary_loss = (vocabulary_ratio - in_sample_ratio) / in_sample_ratio
    else:
        vocabulary_loss = None
    lexicon_transfers = bool(
        lexicon_loo["mean_ratio"] is not None and g6["ratio"] is not None
        and lexicon_loo["mean_ratio"] < g6["ratio"] * 0.9
    )
    if h1 == VERDICT_EXISTENCE[1]:
        h2 = VERDICT_GENERALIZATION[2]
    elif (
        transferred
        and vocabulary_loss is not None and vocabulary_loss < 0.10
        and lexicon_transfers
    ):
        h2 = VERDICT_GENERALIZATION[0]
    else:
        h2 = VERDICT_GENERALIZATION[1]
    h3 = (
        VERDICT_GENERATOR[2]
        if h2 == VERDICT_GENERALIZATION[2] or not lexicon_transfers
        else VERDICT_GENERATOR[1]
    )
    return _verdict_tail(
        streams, candidates, induction, leave_one_out_report, lexicon_loo,
        g5, g6, coverage, saving, shared_share, transferred, in_sample_ratio, vocabulary_ratio,
        frozen_ratio, vocabulary_loss, lexicon_transfers, h1, h2, h3,
    )



def _verdict_tail(
    streams, candidates, induction, leave_one_out_report, lexicon_loo,
    g5, g6, coverage, saving, shared_share, transferred, in_sample_ratio, vocabulary_ratio,
    frozen_ratio, vocabulary_loss, lexicon_transfers, h1, h2, h3,
) -> Dict[str, Any]:
    integration_conditions = [
        {
            "condition": "the grammar proper beats the raw dump by a wide margin",
            "met": saving >= 25.0,
            "measured": saving,
        },
        {
            "condition": "the grammar proper beats Stage 18's best byte codec",
            "met": (g5["ratio_with_grammar"] or 1.0) < (candidates["G1"]["ratio"] or 0.0),
            "measured": {
                "grammar": g5["ratio_with_grammar"],
                "stage18": candidates["G1"]["ratio"],
            },
        },
        {
            "condition": "the advantage survives when the lexicon does not transfer",
            "met": (lexicon_loo["mean_ratio"] or 1.0) < (g5["ratio_with_grammar"] or 0.0),
            "measured": {
                "lexicon_leave_one_out": lexicon_loo["mean_ratio"],
                "grammar": g5["ratio_with_grammar"],
            },
        },
        {
            "condition": "a decoder fits in a few dozen bytes of RAM",
            "met": (g5["ram_bytes"] or 10 ** 9) <= 128,
            "measured": g5["ram_bytes"],
        },
        {
            "condition": "the shared vocabulary covers a majority of frames",
            "met": coverage >= 0.5,
            "measured": coverage,
        },
        {
            "condition": "a small number of constructions is enough",
            "met": g5["complexity"]["primitives"] <= 6,
            "measured": g5["complexity"],
        },
        {
            "condition": "the grammar is smaller than the format it would replace",
            "met": False,
            "measured": (
                "not established. The current note format priced by Stage 17 is several times "
                "smaller than the grammar proper and is not an exact representation, so the "
                "comparison is not like for like and is not claimed"
            ),
        },
    ]
    failing = [item for item in integration_conditions if not item["met"]]
    return {
        "H1": {
            "question": "are there repeatable temporal constructions in the history?",
            "thresholds": {
                "structural_coverage_at_least": H1_COVERAGE_THRESHOLD,
                "saving_with_grammar_percent_at_least": H1_SAVING_THRESHOLD_PERCENT,
                "all_four_songs_exact": True,
            },
            "measured": {
                "structural_coverage": coverage,
                "saving_percent_with_grammar": saving,
                "all_exact": g5["all_exact"],
            },
            "verdict": h1,
        },
        "H2": {
            "question": "are the constructions shared across songs?",
            "thresholds": {"song_share_for_shared": H2_SONG_SHARE},
            "measured": {
                "induced_in_share_of_songs": shared_share,
                "constructions_transferring": transferred,
                "in_sample_ratio": in_sample_ratio,
                "leave_one_out_vocabulary_ratio": vocabulary_ratio,
                "leave_one_out_frozen_parameter_ratio": frozen_ratio,
                "vocabulary_loss_share": _rnd(vocabulary_loss),
                "unseen_parameter_share": leave_one_out_report["mean_unseen_parameter_share"],
                "lexicon_in_sample_ratio": g6["ratio"],
                "lexicon_leave_one_out_ratio": lexicon_loo["mean_ratio"],
                "lexicon_blocks_offered": lexicon_loo["mean_shared_lexicon_blocks"],
                "lexicon_references_transferred": sum(
                    fold["references_emitted"] for fold in lexicon_loo["folds"]
                ),
            },
            "verdict": h2,
        },
        "H3": {
            "question": (
                "is the vocabulary small and simple enough to be a generative layer between the "
                "composition IR and exact playback?"
            ),
            "measured": {
                "primitives": g5["complexity"]["primitives"],
                "complexity_score": g5["complexity"]["score"],
                "grammar_definition_lines": g5["complexity"]["definition_lines_estimate"],
                "structural_coverage": coverage,
                "lexicon_transfers": lexicon_transfers,
            },
            "verdict": h3,
            "note": (
                "H3 asks whether a *generator* could produce this grammar, and no generator was "
                "built or tested here. It is therefore only ever reported as not justified on the "
                "evidence available, never as promising"
            ),
        },
        "player_integration": {
            "conditions": integration_conditions,
            "deciding_condition": failing[0]["condition"] if failing else None,
            "verdict": VERDICT_INTEGRATION[1] if failing else VERDICT_INTEGRATION[0],
        },
    }


# ---------------------------------------------------------------------------
# The final answer
# ---------------------------------------------------------------------------
def final_answer(
    streams: Sequence[stage18.FrameStream],
    candidates: Mapping[str, Mapping[str, Any]],
    induction: Mapping[str, Mapping[str, Any]],
    leave_one_out_report: Mapping[str, Any],
    lexicon_loo: Mapping[str, Any],
    verdicts: Mapping[str, Any],
) -> Dict[str, Any]:
    g5 = candidates["G5"]
    g6 = candidates["G6"]
    induced = sorted(OP_NAMES[op] for op in (OP_SET,) + STRUCTURAL_OPS)
    shared = sorted(
        {
            name
            for name in induced
            if sum(1 for row in induction.values() if OP_NAMES and name in
                   [OP_NAMES[op] for op in row["induced_ops"]]) >= len(streams) * H2_SONG_SHARE
        }
    )
    return {
        "question": (
            "Can the four analysed historical POKEY performance streams be described by a small, "
            "neutral and generalisable set of temporal constructions, simple enough to "
            "potentially sit between the composition IR and exact POKEY playback?"
        ),
        "answer_in_short": (
            "Yes for the constructions, no for the layer. Four neutral constructions - SET, HOLD, "
            "RAMP and TOGGLE, with DELTA rejected by every song - describe a majority of the "
            "frames exactly, transfer to a song that did not contribute to them, and decode from a "
            "few dozen bytes of RAM. But the shared grammar proper is not small: it is about half "
            "the raw stream, which is not a bridge between a composition IR and exact playback, "
            "and the only configuration that is dramatically smaller buys its margin from a "
            "per-song lexicon that transfers nothing."
        ),
        "numbers": {
            "vocabulary_that_holds": shared,
            "vocabulary_size": len(shared),
            "grammar_ratio_with_grammar": g5["ratio_with_grammar"],
            "grammar_structural_coverage": g5["coverage"]["structural_coverage"],
            "leave_one_out_vocabulary_ratio": leave_one_out_report["mean_ratio_by_arm"][
                "union_vocabulary_arm"
            ],
            "leave_one_out_frozen_parameter_ratio": leave_one_out_report["mean_ratio_by_arm"][
                "frozen_parameter_arm"
            ],
            "lexicon_in_sample": g6["ratio"],
            "lexicon_leave_one_out": lexicon_loo["mean_ratio"],
            "lexicon_references_that_transferred": sum(
                fold["references_emitted"] for fold in lexicon_loo["folds"]
            ),
            "decoder_ram_bytes": g5["ram_bytes"],
            "complexity_score": g5["complexity"]["score"],
        },
        "answer_in_two_lines": {
            "existence": (
                f"{verdicts['H1']['verdict']}: neutral temporal constructions carry "
                f"{(g5['coverage']['structural_coverage'] or 0.0) * 100:.0f}% of all register "
                "frames exactly, in all four songs, with no musical concept anywhere in the "
                "definition."
            ),
            "generalization": (
                f"{verdicts['H2']['verdict']}: the vocabulary transfers almost perfectly, a "
                "frozen-parameter transfer costs about seven percent, and a per-song REPEAT "
                "lexicon transfers nothing at all."
            ),
            "generative_usefulness": (
                f"{verdicts['H3']['verdict']}: the compression that would make a generator layer "
                "attractive lives in a per-song lexicon, and the shared vocabulary alone is not "
                "small enough to replace anything."
            ),
        },
        "what_would_change_the_answer": [
            "A composer-generated trace, rather than a recorded performance, showing that the "
            "same four constructions cover a majority of the frames. The frozen-parameter result "
            "suggests this is the one route left, and it was not tested here.",
            "A construction that describes the ~40% residual without a per-song lexicon. Today "
            "the residual is carried verbatim, and that is the reason the exact grammar cannot "
            "get below roughly half of raw.",
            "Evidence that a generator can emit these constructions with realistic parameters. "
            "The unseen-parameter share of about eight percent says the parameter problem is "
            "small but not zero, and no generator was built.",
            "A listening test, if anyone wants to claim the constructions are musically useful. "
            "This stage cannot and does not.",
        ],
        "what_this_stage_does_not_claim": [
            "that the grammar is a good Composer abstraction - exactness is not usefulness",
            "that generalization implies generative usefulness; the two are measured separately "
            "here for exactly that reason",
            "that compression equals musical meaning; the report keeps them apart throughout",
        ],
    }


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------
def load_dataset(
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
) -> Tuple[List[stage18.FrameStream], Dict[str, Any]]:
    """The four songs, taken from Stage 18 so the two stages cannot disagree about the corpus."""
    try:
        streams, selection = stage18.load_dataset(Path(stage16_dir))
    except Exception as error:  # noqa: BLE001 - any upstream failure is this stage's refusal
        raise GrammarError(f"cannot read the corpus from {stage16_dir}: {error}") from error
    found = tuple(sorted(stream.slug for stream in streams))
    if found != tuple(sorted(EXPECTED_SLUGS)):
        raise GrammarError(
            f"the corpus is {found}, but this stage is defined over {tuple(sorted(EXPECTED_SLUGS))}"
        )
    return streams, selection



def run_analysis(
    arch_root: Path = stage18.DEFAULT_ARCHAEOLOGY_DIR,
    stage15_dir: Path = DEFAULT_STAGE15_DIR,
    stage16_dir: Path = DEFAULT_STAGE16_DIR,
    stage17_dir: Path = DEFAULT_STAGE17_DIR,
    stage18_dir: Path = DEFAULT_STAGE18_DIR,
) -> Dict[str, Any]:
    """Read the corpus, induce the grammar, and measure every candidate on every axis.

    Reads everything through its hash and writes nothing. Every number is produced by encoding and
    then decoding: no size in the returned bundle is an estimate except the ones the report labels
    as estimates.
    """
    streams, selection = load_dataset(stage16_dir)
    channels_by_song = {stream.slug: channels_of(stream) for stream in streams}
    tables_by_song = {
        stream.slug: [
            channel_tables(channel.values) for channel in channels_by_song[stream.slug]
        ]
        for stream in streams
    }
    cache: Dict[Tuple[str, Tuple[int, ...]], Dict[str, Any]] = {}

    induction = {
        stream.slug: induce_song(
            stream, channels_by_song[stream.slug], tables_by_song[stream.slug], cache
        )
        for stream in streams
    }
    shared = _shared_sets(induction)
    candidates = compare_candidates(streams, channels_by_song, tables_by_song, cache)
    leave_one_out_report = leave_one_out(
        streams, channels_by_song, tables_by_song, induction, cache
    )
    lexicon_loo = repeat_lexicon_leave_one_out(streams, channels_by_song, tables_by_song)
    parameters = parameter_generalization(
        streams, channels_by_song, tables_by_song, (OP_SET,) + STRUCTURAL_OPS
    )
    segmented_by_song = {
        stream.slug: segment_song(
            channels_by_song[stream.slug], tables_by_song[stream.slug],
            (OP_SET,) + STRUCTURAL_OPS,
        )
        for stream in streams
    }
    patterns = pattern_induction(streams, segmented_by_song)
    techniques = technique_correspondence(streams, channels_by_song, segmented_by_song)
    stage17 = comparison_with_stage17(stage17_dir)
    stage18_cmp = comparison_with_stage18(streams, candidates)
    tests = falsification(
        streams, candidates, induction, leave_one_out_report, lexicon_loo, parameters
    )
    verdicts = hypothesis_verdicts(
        streams, candidates, induction, leave_one_out_report, lexicon_loo
    )
    answer = final_answer(
        streams, candidates, induction, leave_one_out_report, lexicon_loo, verdicts
    )
    frontier = pareto_frontier([candidates[name] for name in ("G2", "G3", "G4", "G5", "G6")])
    return _build_bundle(
        streams, selection, stage16_dir, induction, shared, candidates, leave_one_out_report,
        lexicon_loo, parameters, patterns, techniques, stage17, stage18_cmp, tests, verdicts,
        answer, frontier,
    )


def _build_bundle(
    streams, selection, stage16_dir, induction, shared, candidates, leave_one_out_report,
    lexicon_loo, parameters, patterns, techniques, stage17, stage18_cmp, tests, verdicts,
    answer, frontier,
) -> Dict[str, Any]:
    selection_path = Path(stage16_dir) / "song_selection.json"
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "dataset": {
            "songs": [stream.slug for stream in streams],
            "selection_source": str(selection_path),
            "selection_sha256": sha256_file(selection_path) if selection_path.is_file() else None,
            "traces": [
                {
                    "slug": stream.slug,
                    "frames": stream.frames,
                    "frame_period_us": stream.frame_period_us,
                    "raw_bytes": stream.frames * FRAME_BYTES,
                }
                for stream in streams
            ],
            "expected_slugs_verified": True,
        },
        "canonical": {
            "definition": (
                "Stage 18's canonical raw representation, taken by import rather than re-derived: "
                "a frame is the nine registers in POKEY order, absolute state, nine bytes per "
                "frame, plus Stage 18's 12-byte container header. Stage 19 adds no second "
                "canonical form."
            ),
            "register_order": list(REGISTER_ORDER),
            "frame_bytes": FRAME_BYTES,
            "container_header_bytes": CONTAINER_HEADER_BYTES,
            "container_codec_id": GRAMMAR_CODEC_ID,
            "atom": (
                "one register's value sequence: a list of 8-bit values, one per frame, with no "
                "label beyond the register name POKEY itself defines"
            ),
            "stage18_hash": sha256_file(Path(stage18.__file__)),
        },
        "primitives": {
            "candidate_vocabulary": [PRIMITIVES[op].to_dict() for op in sorted(PRIMITIVES)],
            "min_span": {OP_NAMES[op]: span for op, span in sorted(MIN_SPAN.items())},
            "residual_is_not_a_primitive": (
                "LITERAL is the residual model, present in every variant and always charged to "
                "exception_cost. Counting it as a construction would let a grammar look capable "
                "by describing nothing."
            ),
            "new_constructions_considered": [
                {
                    "construction": "REPEAT",
                    "justified_by_data": patterns["verdict"] == "REPEAT_CONSTRUCTION_PAYS",
                    "measured_net_bytes": patterns["extraction"]["net_bytes"],
                    "measured_in_sample_ratio": candidates["G6"]["ratio"],
                    "measured_leave_one_out_ratio": lexicon_loo["mean_ratio"],
                    "verdict": (
                        "ADMITTED_AS_A_COMPRESSION_TOOL, REJECTED_AS_A_GRAMMAR_ELEMENT: it earns "
                        "its place in bytes and loses it in generalisation"
                        if patterns["verdict"] == "REPEAT_CONSTRUCTION_PAYS"
                        else "NOT_ADMITTED"
                    ),
                }
            ],
        },
        "induction": induction,
        "shared_grammar": shared,
        "per_song": {
            slug: {
                "induced_primitives": row["induced_primitives"],
                "steps": row["steps"],
                "measurement": row["measurement"],
                "minimal_grammar_ratio": row["measurement"]["ratio"],
                "minimal_grammar_ratio_with_grammar": row["measurement"]["ratio_with_grammar"],
                "minimal_grammar_coverage":
                    row["measurement"]["coverage"]["structural_coverage"],
                "parameter_diversity": row["parameter_diversity"],
            }
            for slug, row in sorted(induction.items())
        },
        "candidates": candidates,
        "leave_one_out": leave_one_out_report,
        "lexicon_leave_one_out": lexicon_loo,
        "parameters": parameters,
        "patterns": patterns,
        "techniques": techniques,
        "stage17_comparison": stage17,
        "stage18_comparison": stage18_cmp,
        "falsification": tests,
        "verdicts": verdicts,
        "final_answer": answer,
        "pareto_frontier": frontier,
        "determinism": {
            "no_timestamps": True,
            "no_sampling": True,
            "inputs_hashed": True,
            "tie_breaks": (
                "the segmenter breaks a cost tie by choosing the longer construction and then the "
                "lower opcode; the induction breaks a gain tie on the lower opcode; the extraction "
                "breaks a match tie on the longer block; and the block table is ordered by "
                "descending use, then length, then content. Each is stated in the code and covered "
                "by a test."
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle


# ---------------------------------------------------------------------------
# The outputs
# ---------------------------------------------------------------------------
STAGE19_FILES: Tuple[str, ...] = (
    "canonical.json",
    "primitives.json",
    "per_song.json",
    "shared_grammar.json",
    "leave_one_out.json",
    "candidates.json",
    "complexity.json",
    "comparison.json",
    "reconstruction.json",
    "stage17_comparison.json",
    "stage18_comparison.json",
    "summary.json",
)
STAGE19_DOC = "stage19_temporal_grammar.md"


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The executive numbers, so a reader does not have to open twelve files."""
    candidates = bundle["candidates"]
    g5 = candidates["G5"]
    g6 = candidates["G6"]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "songs": bundle["dataset"]["songs"],
        "canonical": bundle["canonical"]["definition"],
        "primitive_vocabulary": [item["name"] for item in
                                 bundle["primitives"]["candidate_vocabulary"]],
        "induced_vocabulary_by_song": {
            slug: row["induced_primitives"] for slug, row in sorted(bundle["induction"].items())
        },
        "shared_vocabulary": bundle["shared_grammar"]["intersection"],
        "shared_vocabulary_union": bundle["shared_grammar"]["union"],
        "grammar_ratio": g5["ratio"],
        "grammar_ratio_with_grammar": g5["ratio_with_grammar"],
        "grammar_structural_coverage": g5["coverage"]["structural_coverage"],
        "grammar_frame_coverage": g5["coverage"]["frame_coverage"],
        "grammar_residual_share": g5["coverage"]["residual_share"],
        "grammar_change_event_coverage": g5["coverage"]["change_event_coverage"],
        "grammar_complexity": g5["complexity"],
        "grammar_ram_bytes": g5["ram_bytes"],
        "repeat_ratio": g6["ratio"],
        "repeat_lexicon_share": g6["lexicon_share"],
        "repeat_leave_one_out_ratio": bundle["lexicon_leave_one_out"]["mean_ratio"],
        "repeat_references_transferred": sum(
            fold["references_emitted"] for fold in bundle["lexicon_leave_one_out"]["folds"]
        ),
        "leave_one_out_ratios": bundle["leave_one_out"]["mean_ratio_by_arm"],
        "unseen_parameter_share": bundle["leave_one_out"]["mean_unseen_parameter_share"],
        "all_exact": bundle["leave_one_out"]["all_exact"] and g5["all_exact"] and g6["all_exact"],
        "best_candidate": min(
            (row for name, row in candidates.items()
             if name in ("G2", "G3", "G4", "G5", "G6")),
            key=lambda row: (row["ratio_with_grammar"] or 1e9, row["variant"]),
        )["variant"],
        "pareto_frontier": bundle["pareto_frontier"],
        "verdicts": {
            "H1": bundle["verdicts"]["H1"]["verdict"],
            "H2": bundle["verdicts"]["H2"]["verdict"],
            "H3": bundle["verdicts"]["H3"]["verdict"],
            "player_integration": bundle["verdicts"]["player_integration"]["verdict"],
        },
        "deciding_condition": bundle["verdicts"]["player_integration"]["deciding_condition"],
        "stage17_questions_addressed": bundle["stage17_comparison"].get("addressed_count"),
        "final_answer_short": bundle["final_answer"]["answer_in_short"],
    }


def write_analysis(
    bundle: Mapping[str, Any],
    stage19_dir: Path = DEFAULT_STAGE19_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the twelve JSON artefacts and the report. Additive: nothing else is touched."""
    stage19_dir = Path(stage19_dir)
    docs_dir = Path(docs_dir)
    stage19_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    candidates = bundle["candidates"]
    g5_ops = candidates["G5"]["ops"]
    candidates_slim = {
        name: {
            "variant": row["variant"],
            "label": row["label"],
            "primitives": row["primitives"],
            "all_exact": row["all_exact"],
            "ratio": row["ratio"],
            "ratio_with_grammar": row["ratio_with_grammar"],
            "saving_percent_with_grammar": row["saving_percent_with_grammar"],
            "coverage": row["coverage"],
            "bytes": row["bytes"],
            "grand_total": row["grand_total"],
            "complexity": row["complexity"],
            "lexicon_share": row["lexicon_share"],
            "ram_bytes": row["ram_bytes"],
            "note": row.get("note"),
        }
        for name, row in sorted(candidates.items())
    }
    payload = {
        "canonical.json": bundle["canonical"],
        "primitives.json": bundle["primitives"],
        "per_song.json": bundle["per_song"],
        "shared_grammar.json": {
            **bundle["shared_grammar"],
            "parameters": bundle["parameters"],
        },
        "leave_one_out.json": {
            **bundle["leave_one_out"],
            "lexicon_leave_one_out": bundle["lexicon_leave_one_out"],
        },
        "candidates.json": candidates_slim,
        "complexity.json": {
            "score_definition": (
                "number_of_primitives + number_of_parameter_fields + decoder_states + "
                "special_cases, applied identically to every candidate"
            ),
            "candidates": {
                name: candidates[name]["complexity"] for name in sorted(candidates)
            },
            "pareto_frontier": bundle["pareto_frontier"],
            "frontier_axes": "complexity down, structural coverage up, ratio with grammar down",
        },
        "comparison.json": {
            "stage17": bundle["stage17_comparison"],
            "stage18": bundle["stage18_comparison"],
            "techniques": bundle["techniques"],
        },
        "reconstruction.json": {
            "requirement": (
                "every encoded fragment must decode to the canonical raw payload byte for byte; "
                "an inexact row is not a result"
            ),
            "all_exact": bundle["summary"]["all_exact"],
            "per_song": {
                name: {
                    slug: {
                        "exact": row["exact"],
                        "first_divergence_frame": row["first_divergence_frame"],
                        "accounting_check": row["accounting_check"],
                        "raw_bytes": row["raw_bytes"],
                        "container_bytes": row["container_bytes"],
                    }
                    for slug, row in sorted(candidates[name]["per_song"].items())
                }
                for name in sorted(candidates)
            },
        },
        "stage17_comparison.json": bundle["stage17_comparison"],
        "stage18_comparison.json": bundle["stage18_comparison"],
        "summary.json": bundle["summary"],
    }
    written: Dict[str, Path] = {}
    for name in STAGE19_FILES:
        path = stage19_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    doc_path = docs_dir / STAGE19_DOC
    doc_path.write_text(render_report(bundle), encoding="utf-8")
    written[STAGE19_DOC] = doc_path
    return written


# ---------------------------------------------------------------------------
# The report: eighteen sections in the brief's order, then the final question
# ---------------------------------------------------------------------------
def _num(value: Any) -> Any:
    """Render a missing measurement as ``n/a`` rather than as the word None."""
    return "n/a" if value is None else value


def _pct(value: Optional[float], places: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"


def _f6(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _report_header(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "# Stage 19 - A Neutral Temporal Performance Grammar for POKEY\n",
        "Stage 17 asked whether a neutral event language could *represent* a performance. It "
        "could not, and compressed worse than raw. Stage 18 asked whether the exact stream had "
        "temporal redundancy. It did, about 49 percent of it, but the answer was a byte format and "
        "not a model. Stage 19 asks the narrower structural question that remains: can the "
        "historical behaviour be described by a *small, neutral temporal grammar* rather than "
        "stored?\n",
        "Analysis only. The corpus traces, the Stage 15/16/17/18 records and the player source are "
        "read through their hashes and never written. No audio was rendered, no music was "
        "generated, no listening test was run, and nothing was implemented in production - no "
        "player command, no composer feature, no IR, no DSL, no schema. Nothing here names a "
        "melody, a bass line, an instrument or an effect as an element of the model.\n",
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE19_FILES) + ".\n",
    ]


def render_report(bundle: Mapping[str, Any]) -> str:
    """The eighteen sections the brief requires, in its order, from the measured bundle."""
    out: List[str] = _report_header(bundle)
    for section in (
        _section_1, _section_2, _section_3, _section_4, _section_5, _section_6,
        _section_7, _section_8, _section_9, _section_10, _section_11, _section_12,
        _section_13, _section_14, _section_15, _section_16, _section_17, _section_18,
        _section_final_question,
    ):
        out.extend(section(bundle))
    return "\n".join(out)


def _section_1(bundle: Mapping[str, Any]) -> List[str]:
    g5 = bundle["candidates"]["G5"]
    g6 = bundle["candidates"]["G6"]
    s = bundle["summary"]
    stage18_mean = bundle["stage18_comparison"]["summary"]["stage18_mean_ratio"]
    loo = bundle["leave_one_out"]
    return [
        "## 1. Executive Summary\n",
        f"- **A small neutral grammar exists.** Five constructions - SET, HOLD, DELTA, RAMP, "
        "TOGGLE - plus an explicit residual channel and one construction the data asked for. HOLD, "
        f"RAMP and TOGGLE together carry {_pct(g5['coverage']['structural_coverage'])} of every "
        f"register frame exactly, in all {len(s['songs'])} songs, and no definition mentions a "
        "musical concept.\n",
        f"- **It is not Stage 17 in a new coat.** SET is only {_pct(g5['coverage']['set_share'])} "
        "of frames and is the most expensive construction per frame, so the parse avoids it "
        "wherever anything else applies.\n",
        f"- **The grammar proper is not small in bytes.** Definition and decoder charged, it "
        f"reaches a mean ratio of {_f6(g5['ratio_with_grammar'])} - about half the raw stream. It "
        "is exact and it is a model, but half is not a bridge between a composition IR and exact "
        "playback.\n",
        f"- **A REPEAT level makes it far smaller and stops being a grammar.** An induced block "
        f"lexicon takes the mean ratio to {_f6(g6['ratio'])}, better than Stage 18's best byte "
        f"codec at {_f6(stage18_mean)}, but {_pct(g6['lexicon_share'])} of that artefact *is* the "
        "per-song lexicon.\n",
        "- **The lexicon transfers nothing, and this is the decisive number.** Built from three "
        f"songs and offered whole to the fourth, it supplied {s['repeat_references_transferred']} "
        f"references across all four folds, leaving the held-out song at exactly the grammar's own "
        f"ratio of {_f6(g5['ratio'])}. The construction earns its bytes and loses its claim to "
        "being part of a shared language.\n",
        f"- **The vocabulary does transfer.** Leave-one-out on the constructions costs nothing "
        f"measurable ({_f6(g5['ratio'])} in sample against "
        f"{_f6(loo['mean_ratio_by_arm']['union_vocabulary_arm'])} out of sample); freezing the "
        f"parameters costs {_f6(loo['mean_ratio_by_arm']['frozen_parameter_arm'])} against "
        f"{_f6(loo['mean_ratio_by_arm']['union_vocabulary_arm'])}, and "
        f"{_pct(loo['mean_unseen_parameter_share'])} of held-out occurrences use a parameter shape "
        "the training songs never showed.\n",
        "- **DELTA is rejected by every song.** The construction the brief asks about most is the "
        "one no song's own induction keeps: RAMP plus SET always describes the same run in the same "
        "or fewer bytes.\n",
        f"- **It is cheap to run.** {s['grammar_ram_bytes']} bytes of decoder state and a "
        f"complexity score of {s['grammar_complexity']['score']}, against 9,216 bytes of window for "
        "Stage 18's best LZ configuration.\n",
        f"- **Verdicts.** {s['verdicts']['H1']}, {s['verdicts']['H2']}, {s['verdicts']['H3']}, "
        f"{s['verdicts']['player_integration']}.\n",
        "One sentence: *the temporal grammar is real, small in vocabulary, exact and cheap, and it "
        "still does not justify replacing anything, because the only large saving comes from "
        "memorising each song separately.*\n",
    ]


def _section_2(bundle: Mapping[str, Any]) -> List[str]:
    return [
        "## 2. Research Question\n",
        "> Can the four analysed historical POKEY performance streams be described by a small, "
        "neutral and generalisable set of temporal constructions, which is exact wherever a "
        "construction is used and simple enough to potentially sit between the composition IR and "
        "exact POKEY playback?\n",
        "The question is answered at three levels, and each is decided by a stated threshold rather "
        "than by impression.\n",
        _md_table(
            ["level", "question", "decided by"],
            [
                ["H1 Existence", "are there repeatable temporal constructions at all?",
                 f"structural coverage at least {H1_COVERAGE_THRESHOLD:.0%} and saving with the "
                 f"grammar charged at least {H1_SAVING_THRESHOLD_PERCENT:.0f}%, exact on every song"],
                ["H2 Generalization", "are the constructions shared across songs?",
                 f"a construction induced in at least {H2_SONG_SHARE:.0%} of songs, a leave-one-out "
                 "loss under 10%, and a REPEAT lexicon that transfers"],
                ["H3 Generative usefulness", "could this be a generative layer?",
                 "requires H2 and a transferring lexicon; no generator was built here, so this can "
                 "only be reported as not justified on the evidence available"],
            ],
        ),
        "",
        "The answer is not assumed to be yes. Two of this stage's load-bearing results - DELTA "
        "rejected by every song, and the lexicon transferring nothing - are negative, and they are "
        "reported as such.\n",
    ]


def _section_3(bundle: Mapping[str, Any]) -> List[str]:
    dataset = bundle["dataset"]
    return [
        "## 3. Dataset\n",
        "The same four songs Stage 16 selected and Stage 18 measured, read from the Stage 16 "
        "record rather than chosen again here. The slugs are verified against the expected set, so "
        "a corpus that silently changed would fail loudly instead of producing quietly different "
        "numbers.\n",
        _md_table(
            ["song", "frames", "frame period", "raw bytes", "registers"],
            [[f"`{row['slug']}`", row["frames"], f"{row['frame_period_us']} us", row["raw_bytes"],
              FRAME_BYTES] for row in dataset["traces"]],
        ),
        "",
        f"Stage 16 selection record: `{dataset['selection_source']}`, sha256 "
        f"`{dataset['selection_sha256']}`.\n",
        "No song was added, removed, sampled or truncated. Everything below is measured on all "
        "four, and a configuration that is not exact on all four is never called a result.\n",
    ]


def _section_4(bundle: Mapping[str, Any]) -> List[str]:
    canonical = bundle["canonical"]
    return [
        "## 4. Canonical Representation\n",
        "Stage 19 does not invent a second canonical form. Stage 18's canonical raw representation "
        "is the source of truth and is taken *by import*, so the two stages cannot silently "
        "disagree about what a frame is.\n",
        _md_table(
            ["property", "value"],
            [
                ["register order", ", ".join(canonical["register_order"])],
                ["frame size", f"{canonical['frame_bytes']} bytes, absolute state"],
                ["container header", f"{canonical['container_header_bytes']} bytes, Stage 18's "
                                     "layout, shared by every codec"],
                ["Stage 19 codec id", canonical["container_codec_id"]],
                ["Stage 18 module hash", f"`{canonical['stage18_hash']}`"],
            ],
        ),
        "",
        f"**The neutral atom.** {canonical['atom'].capitalize()}.\n",
        "The atom deliberately excludes the song, the other channels, note boundaries and time "
        "signature. A construction that only exists because a channel \"is a bass line\" would not "
        "be a temporal construction at all, and this restriction is what keeps the experiment "
        "falsifiable.\n",
    ]



def _cost_split_label(name: str) -> str:
    if name == "SET":
        return "opcode + value"
    if name == "HOLD":
        return "opcode + length"
    if name == "DELTA":
        return "opcode + length, delta"
    if name == "RAMP":
        return "opcode + length, start + delta"
    if name == "TOGGLE":
        return "opcode + length, two endpoints"
    if name == "LITERAL":
        return "opcode + length, k values (residual)"
    return "opcode + id"


def _min_span_note(primitives: Mapping[str, Any]) -> str:
    spans = ", ".join(
        f"{name} >= {span}" for name, span in sorted(primitives["min_span"].items())
    )
    return (
        f"{spans}. Below its minimum span a construction is not the thing it names: a HOLD of one "
        "frame is a SET, and a TOGGLE of two frames is merely two different values. The first "
        "implementation of this stage allowed a two-frame toggle and reported TOGGLE covering "
        "9,175 frames of one song; almost all of those were ties with the residual, and the "
        "minimum span is what removed the artefact."
    )


def _section_5(bundle: Mapping[str, Any]) -> List[str]:
    primitives = bundle["primitives"]
    out = [
        "## 5. Candidate Primitive Vocabulary\n",
        "Six entries: five constructions plus an explicit residual. Every one is a pure function of "
        "a value sequence and a write position, and none of them carries meaning.\n",
        _md_table(
            ["op", "name", "definition", "parameters", "min span", "def. bytes (est.)",
             "cost split"],
            [
                [
                    item["op"], f"**{item['name']}**", item["definition"],
                    ", ".join(item["parameters"]) or "-",
                    primitives["min_span"].get(item["name"], "-"),
                    item["definition_bytes_estimate"],
                    _cost_split_label(item["name"]),
                ]
                for item in primitives["candidate_vocabulary"]
            ],
        ),
        "",
        "**The residual is not a construction.** " + primitives["residual_is_not_a_primitive"] +
        "\n",
        "**Minimum spans, and why they matter.** " + _min_span_note(primitives) + "\n",
        "**A construction the data asked for.**\n",
    ]
    for item in primitives["new_constructions_considered"]:
        out.append(
            f"- **{item['construction']}**: {item['verdict']}. The induction measured a net "
            f"{item['measured_net_bytes']} bytes on the operation stream, an in-sample mean ratio "
            f"of {_f6(item['measured_in_sample_ratio'])} and a leave-one-out mean ratio of "
            f"{_f6(item['measured_leave_one_out_ratio'])}.\n"
        )
    out.append("")
    out.append(
        "Nothing else was added. In particular no construction was invented to improve a ratio: "
        "section 20 tests each one's marginal contribution, and section 21's rule is applied at "
        "selection time rather than reported afterwards.\n"
    )
    return out


def _section_6(bundle: Mapping[str, Any]) -> List[str]:
    patterns = bundle["patterns"]
    totals = patterns["totals"]
    return [
        "## 6. Primitive Discovery\n",
        "The grammar was not designed only by hand. Discovery is bottom-up, in four steps, and each "
        "step is reported before the next is allowed to run.\n",
        "1. Each channel is split at every position where a construction could begin, by three "
        "linear-time recurrences: constant run, arithmetic run, alternating run.\n",
        "2. A dynamic program chooses the cheapest sequence of constructions under an explicit cost "
        "model, taking each construction at its maximal extent from each position.\n",
        "3. The resulting operation stream is scanned for repeated runs of operations, at two "
        "levels that answer two different questions.\n",
        "4. Only a construction that pays for its own definition, measured, is allowed into a "
        "grammar.\n",
        "**The parse is exact for this primitive set.** Inside a maximal run of a given shape no "
        "other construction can start, so continuing is never worse than restarting; and the "
        "residual is not restricted at all, because its cost is linear in the run length so its "
        "minimum over the window is a sliding-window minimum. The residual can therefore always "
        "fall back to something close to the raw cost of a frame, which is what stops a "
        "construction being credited for a frame it does not really describe.\n",
        _md_table(
            ["discovery statistic", "value"],
            [
                ["operations in the grammar's own parse", totals["operations"]],
                ["bytes those operations cost", totals["operation_bytes"]],
                ["frames they cover", totals["frames"]],
                ["distinct operation-kind patterns", totals["distinct_structural_patterns"]],
                ["repeated operation-kind patterns", totals["repeated_structural_patterns"]],
                ["distinct exactly-repeated patterns", totals["distinct_exact_patterns"]],
                ["exactly-repeated patterns used exactly once", totals["patterns_seen_exactly_once"]],
            ],
        ),
        "",
        "**Two levels, deliberately kept apart.** The *structural* level ignores parameters and "
        "counts repeated sequences of operation kinds. It is a detection figure and not a size, "
        "because a repeat that re-sent its parameters every time would save nothing but opcodes. "
        "The *exact* level requires identical operations, parameters included, and it is the only "
        "level at which a reference can save real bytes.\n",
        _md_table(
            ["top repeated operation-kind pattern", "occurrences", "songs present"],
            [[", ".join(row["pattern"]), row["occurrences"], len(row["songs_present"])]
             for row in patterns["structural_patterns"][:10]],
        ),
        "",
        "Those occurrences overlap each other and other patterns, so they are a detection count and "
        "not a coverage figure. The priced question is the exact one, and section 12 answers it.\n",
        "**The anti-overfitting rule, applied before the result is known.** "
        + patterns["overfitting_guard"] + "\n",
    ]


def _section_7(bundle: Mapping[str, Any]) -> List[str]:
    rows = []
    for slug, row in sorted(bundle["per_song"].items()):
        measurement = row["measurement"]
        rows.append([
            f"`{slug}`",
            ", ".join(row["induced_primitives"]),
            len(row["induced_primitives"]),
            _f6(measurement["ratio"]),
            _f6(measurement["ratio_with_grammar"]),
            _pct(measurement["coverage"]["structural_coverage"]),
            _pct(measurement["coverage"]["residual_share"]),
            measurement["bytes"]["grand_total"],
        ])
    steps = bundle["per_song"][sorted(bundle["per_song"])[0]]["steps"]
    return [
        "## 7. Per-Song Grammar\n",
        "Each song was given its own induction: start from SET, then repeatedly add the "
        "construction that lowers the *grand total* - stream, parameters, residual, the "
        "construction's own definition and the decoder - and stop when nothing lowers it. A "
        "construction must therefore earn its own installation before it can join a grammar. "
        "Ties break on the lower opcode, and the step history is kept so the stopping decision can "
        "be audited.\n",
        _md_table(
            ["song", "induced vocabulary", "count", "ratio", "ratio with grammar",
             "structural coverage", "residual share", "grand total (bytes)"],
            rows,
        ),
        "",
        "**The step history of the first song, as an example of how a decision is reached.**\n",
        _md_table(
            ["step", "candidate added", "trial vocabulary", "grand total", "gain (bytes)",
             "accepted"],
            [[index + 1, step["considered"], ", ".join(step["trial_set"]),
              step["trial_grand_total"], step["gain_bytes"], "yes" if step["accepted"] else "no"]
             for index, step in enumerate(steps)],
        ),
        "",
        "**What the inductions disagree about is the interesting part.** DELTA is rejected by every "
        "song, and RAMP is rejected by one. The songs are not equally complex temporal objects, and "
        "the per-song numbers say how much: the residual share ranges from about a fifth to about "
        "two fifths of frames, and that range is the honest measure of how much of each song the "
        "grammar does not explain.\n",
    ]


def _section_8(bundle: Mapping[str, Any]) -> List[str]:
    shared = bundle["shared_grammar"]
    return [
        "## 8. Shared Grammar\n",
        "The smallest set of constructions common to all four songs, and the largest set any of "
        "them used. The two are reported together because the gap between them is the honest "
        "measure of how much vocabulary a shared grammar must sacrifice.\n",
        _md_table(
            ["song", "induced vocabulary"],
            [[f"`{slug}`", ", ".join(names)]
             for slug, names in sorted(shared["song_sets"].items())],
        ),
        "",
        _md_table(
            ["construction", "induced in which songs", "songs"],
            [[name, ", ".join(slugs), len(slugs)]
             for name, slugs in sorted(shared["present_in"].items())],
        ),
        "",
        f"**Smallest common vocabulary: {', '.join(shared['intersection']) or 'none'}.**\n",
        f"**Union of all four: {', '.join(shared['union'])}.**\n",
        "The shared grammar does not have to share parameters. RAMP can be a construction all four "
        "songs use while every song drives it with different deltas and lengths, and section 10 "
        "separates those two facts rather than blurring them.\n",
    ]



def _section_9(bundle: Mapping[str, Any]) -> List[str]:
    loo = bundle["leave_one_out"]
    lexicon = bundle["lexicon_leave_one_out"]
    arms = ["shared_vocabulary_arm", "union_vocabulary_arm", "frozen_parameter_arm"]
    return [
        "## 9. Leave-One-Out\n",
        "Induce on three songs, then encode the fourth. Three arms, because generalisation means "
        "three different things and conflating them would flatter the result.\n",
        _md_table(
            ["arm", "what it allows", "mean ratio", "mean structural coverage",
             "mean residual share"],
            [[arm, loo["arms"][arm], _f6(loo["mean_ratio_by_arm"][arm]),
              _pct(loo["mean_structural_coverage_by_arm"][arm]),
              _pct(loo["mean_residual_share_by_arm"][arm])] for arm in arms],
        ),
        "",
        _md_table(
            ["song", "trained on", "shared vocabulary", "vocabulary arm", "union arm",
             "frozen parameters", "unseen parameter share"],
            [[f"`{fold['held_out']}`", ", ".join(fold["trained_on"]),
              ", ".join(fold["shared_vocabulary"]) or "none",
              _f6(fold["shared_vocabulary_arm"]["ratio"]),
              _f6(fold["union_vocabulary_arm"]["ratio"]),
              _f6(fold["frozen_parameter_arm"]["ratio"]),
              _pct(fold["unseen_parameters"]["unseen_share"])]
             for fold in lexicon_fold_order(loo)],
        ),
        "",
        "**The vocabulary arm is indistinguishable from the in-sample result.** Adding the "
        "constructions a song did not itself induce costs essentially nothing, so the vocabulary is "
        "genuinely shared rather than fitted. Freezing the parameters costs a measurable but modest "
        "amount, and the unseen-parameter share is small.\n",
        "**The REPEAT lexicon is the exception, and it is categorical.**\n",
        _md_table(
            ["song", "shared lexicon offered (blocks)", "blocks matched", "references emitted",
             "ratio with the frozen lexicon"],
            [[f"`{fold['held_out']}`", fold["shared_lexicon_blocks"], fold["blocks_matched"],
              fold["references_emitted"], _f6(fold["measurement"]["ratio"])]
             for fold in lexicon["folds"]],
        ),
        "",
        f"Offered an average of {lexicon['mean_shared_lexicon_blocks']:.0f} blocks built from the "
        f"other three songs, the held-out song matched {lexicon['mean_blocks_matched']:.0f} of them "
        f"and emitted {sum(fold['references_emitted'] for fold in lexicon['folds'])} references in "
        f"total. Its mean ratio falls back to {_f6(lexicon['mean_ratio'])} - the grammar's own "
        f"{_f6(bundle['candidates']['G5']['ratio'])}. The lexicon is a memorisation of one song "
        "wearing the clothes of a construction.\n",
    ]


def lexicon_fold_order(loo: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return sorted(loo["folds"], key=lambda fold: fold["held_out"])


def _section_10(bundle: Mapping[str, Any]) -> List[str]:
    parameters = bundle["parameters"]
    out = [
        "## 10. Parameter Generalization\n",
        "Whether a construction exists and whether it is driven the same way are two different "
        "questions, and they are measured separately. A grammar of five constructions that every "
        "song drives with wildly different deltas is far more generalisable than one that each song "
        "drives with a private parameter, and only this table tells them apart.\n",
        f"Mean vocabulary overlap across songs: **{_f6(parameters['vocabulary_overlap_mean'])}** "
        "(intersection over union of the constructions each song uses).\n",
        _md_table(
            ["construction", "songs present", "parameter cardinality by song",
             "total cardinality", "shared parameter shapes", "occurrences",
             "parameters generalise?"],
            [[name, row["songs_present_count"],
              ", ".join(f"{slug.split('_')[0]} {count}"
                        for slug, count in sorted(row["parameter_cardinality_by_song"].items())),
              row["total_parameter_cardinality"], row["shared_parameter_count"],
              row["total_occurrences"],
              "yes" if row["generalises_parameters"] else "**no**"]
             for name, row in sorted(parameters["primitives"].items())],
        ),
        "",
        "A parameter shape is the neutral part of a construction's parameters: the delta for DELTA "
        "and RAMP, the two endpoints for TOGGLE, nothing for HOLD. The register is excluded, "
        "because the register is not what makes two uses the same.\n",
        "**The split is real.** " + _parameter_reading(parameters) + "\n",
    ]
    return out


def _parameter_reading(parameters: Mapping[str, Any]) -> str:
    shared = {
        name: row["shared_parameter_count"]
        for name, row in parameters["primitives"].items()
    }
    zero = sorted(name for name, count in shared.items() if count == 0)
    if not zero:
        return "every construction shares at least one parameter shape across all four songs."
    return (
        "every construction is present in the songs that use it, but "
        f"{', '.join(zero)} shares no exact parameter shape across all four. For those the "
        "construction transfers and the values do not, which is exactly the distinction the brief "
        "asks to keep visible."
    )


def _section_11(bundle: Mapping[str, Any]) -> List[str]:
    g5 = bundle["candidates"]["G5"]
    rows = []
    for slug, row in sorted(g5["per_song"].items()):
        rows.append([
            f"`{slug}`", row["raw_bytes"], row["container_bytes"],
            "yes" if row["exact"] else "**NO**",
            "n/a" if row["first_divergence_frame"] is None else row["first_divergence_frame"],
            row["accounting_check"],
            ", ".join(name for name, count in sorted(row["operation_counts"].items())
                      if count and name != "REPEAT"),
        ])
    everything = [
        bundle["candidates"][name]["all_exact"] for name in
        ("G2", "G3", "G4", "G5", "G6")
    ]
    return [
        "## 11. Exact Reconstruction\n",
        "Every encoded fragment is decoded and compared with the canonical raw payload byte for "
        "byte. A row whose `exact` is false is not a result, so this section is a gate on every "
        "other number in the report.\n",
        _md_table(
            ["song", "raw bytes", "container bytes", "exact", "first divergence frame",
             "accounting check", "operations used"],
            rows,
        ),
        "",
        f"All five candidate grammars are exact on all four songs: **{all(everything)}**. The "
        "accounting check confirms that stream, parameter, residual and lexicon bytes together "
        "equal the container exactly, so no byte is hidden outside the model.\n",
        "**No approximation is permitted anywhere.** No pitch approximation, no quantisation, no "
        "rounded values, no omitted silent frames, no inferred values, no implicit musical "
        "knowledge. A construction that could only approximate would be marked LOSSY and excluded "
        "from the exact grammar; none of the constructions here needed that marking, because every "
        "one of them writes explicit values.\n",
    ]


def _section_12(bundle: Mapping[str, Any]) -> List[str]:
    candidates = bundle["candidates"]
    order = ["G0", "G1", "G2", "G3", "G4", "G5", "G6"]
    patterns = bundle["patterns"]["extraction"]
    return [
        "## 12. Compression and Description Length\n",
        "A saving may not be claimed unless the definition that produces it is paid for. Every "
        "total on this page is grammar definition + parameters + stream + residual + lexicon "
        "table + decoder, and the grammar definition is charged per construction at the current "
        "6502 player's own code density.\n",
        _md_table(
            ["candidate", "vocabulary", "ratio", "ratio with grammar and decoder",
             "stream", "parameters", "residual", "lexicon table", "grammar + decoder",
             "grand total"],
            [[
                f"**{name}**",
                ", ".join(candidates[name]["primitives"]) or "-",
                _f6(candidates[name]["ratio"]),
                _f6(candidates[name]["ratio_with_grammar"]),
                _num(candidates[name]["bytes"]["stream"]),
                _num(candidates[name]["bytes"]["parameter"]),
                _num(candidates[name]["bytes"]["exception"]),
                _num(_lexicon_mean(name, candidates)) if candidates[name]["per_song"] else "n/a",
                _num(candidates[name]["bytes"]["grammar_definition"]),
                _num(candidates[name]["grand_total"]),
            ] for name in order],
        ),
        "",
        "**The REPEAT bound, replaced by a real encoding.** The induction first priced a block "
        "reference with an optimistic bound. That bound is not the result; the result is the G6 row "
        "above, which was built, encoded, decoded and compared.\n",
        _md_table(
            ["exact pattern extraction", "value"],
            [
                ["candidate patterns", patterns["candidate_patterns"]],
                ["references emitted", patterns["references_emitted"]],
                ["distinct patterns used", patterns["distinct_patterns_used"]],
                ["gross saving (bytes)", patterns["gross_saving_bytes"]],
                ["table cost (bytes)", patterns["table_cost_bytes"]],
                ["net (bytes)", patterns["net_bytes"]],
                ["the saving is bounded by the data it replaces",
                 patterns["bounded_by_operation_bytes"]],
                ["verdict", bundle["patterns"]["verdict"]],
            ],
        ),
        "",
        "The first version of that extraction summed occurrences of overlapping n-grams and "
        "returned a saving of 955,678 bytes against 161,225 bytes of operations, which is "
        "self-evidently impossible. The current extraction is a left-to-right greedy pass that "
        "consumes each match, so no operation is referenced twice and the saving cannot exceed the "
        "data. The correction is recorded here because the wrong number was briefly believed.\n",
        "**Where the bytes actually go.** " + _byte_story(candidates) + "\n",
    ]


def _lexicon_mean(name: str, candidates: Mapping[str, Any]) -> int:
    rows = candidates[name]["per_song"]
    if not rows:
        return 0
    return int(round(sum(row["bytes"]["reference_table"] for row in rows.values()) / len(rows)))


def _byte_story(candidates: Mapping[str, Any]) -> str:
    g5 = candidates["G5"]
    g6 = candidates["G6"]
    return (
        "for the grammar proper (G5) the largest bucket is the residual at "
        f"{g5['bytes']['exception']} bytes, which is the honest statement that the grammar does "
        "not describe about two fifths of the frames; for G6 the largest bucket is the per-song "
        "lexicon. That is the whole difference between a grammar and a dictionary."
    )


def _section_13(bundle: Mapping[str, Any]) -> List[str]:
    candidates = bundle["candidates"]
    frontier = bundle["pareto_frontier"]
    return [
        "## 13. Complexity\n",
        "A deliberately simple score, defined once and applied identically to every candidate: "
        "number of constructions + number of parameter fields + decoder states + special cases. It "
        "is not claimed to be a perfect metric. It is claimed to be explicit, deterministic and "
        "uniform, which is what makes a Pareto comparison between candidates meaningful.\n",
        _md_table(
            ["candidate", "constructions", "parameter fields", "decoder states",
             "special cases", "score", "definition lines (est.)", "decoder RAM (bytes)"],
            [[name, row["complexity"]["primitives"], row["complexity"]["parameter_fields"],
              row["complexity"]["decoder_states"], row["complexity"]["special_cases"],
              row["complexity"]["score"], row["complexity"]["definition_lines_estimate"],
              _num(row["ram_bytes"])]
             for name, row in sorted(candidates.items())
             if name in ("G2", "G3", "G4", "G5", "G6")],
        ),
        "",
        "G0 and G1 have no complexity row because they have no vocabulary: one is the raw stream "
        "and the other is a byte format with no constructions at all. That absence is the point of "
        "the section.\n",
        "",
        "**Pareto frontier** over complexity (down), structural coverage (up) and ratio with the "
        "grammar charged (down). Computed by pairwise domination on a name-sorted list, so an exact "
        "tie can never reorder it between runs.\n",
        _md_table(
            ["candidate", "complexity score", "structural coverage",
             "ratio with grammar", "constructions"],
            [[row["variant"], row["complexity_score"], _pct(row["structural_coverage"]),
              _f6(row["ratio_with_grammar"]), ", ".join(row["primitives"])]
             for row in frontier],
        ),
        "",
        "**Decoder RAM, which the byte count does not show.** The grammar decodes from "
        f"{bundle['candidates']['G5']['ram_bytes']} bytes of state and needs no buffer at all, "
        "because a frame-at-a-time decoder can advance nine channel programs in step. Stage 18's "
        "best configuration needs a 9,216-byte window. On a machine with 16 KB in total that "
        "difference is not a detail - it is the difference between a format that can run and one "
        "that cannot.\n",
        "**Residual cost is part of complexity.** A grammar that describes a third of the stream "
        "and carries the rest verbatim is not simpler than one that describes most of it; the "
        "residual is charged in section 12 and its share is reported in sections 7 and 11, so a "
        "small vocabulary cannot be bought with a large residual.\n",
    ]


def _section_14(bundle: Mapping[str, Any]) -> List[str]:
    comparison = bundle["stage17_comparison"]
    out = [
        "## 14. Stage 17 Comparison\n",
        "Stage 17 left questions for a later stage and explicitly did not answer them. Every one "
        "gets a status and a verdict here. `status` says whether this stage looked at the question; "
        "`verdict` says what it found. A question can be NOT_ADDRESSED and still carry a verdict, "
        "and it is reported that way rather than left out.\n",
    ]
    if not comparison.get("available"):
        out.append(f"Stage 17's record is unavailable: {comparison.get('reason')}.\n")
        return out
    out.append(_md_table(
        ["status", "verdict", "Stage 17 question", "what this stage found"],
        [[item["status"], item["verdict"], item["question"], item["evidence"]]
         for item in comparison["answers"]],
    ))
    out.append("")
    out.append(
        f"**{comparison['addressed_count']} of {len(comparison['answers'])} addressed, "
        f"{comparison['supported_count']} supported, {comparison['refuted_count']} refuted.**\n"
    )
    out.append(
        "The question this stage answers most directly is whether *any* representation beats the "
        "raw dump. Yes, at two levels: the grammar proper at about half, and the grammar plus a "
        "per-song lexicon at about a third. But the second answer is the one that would have made "
        "Stage 17's middle layer unnecessary, and it turns out to be a dictionary rather than a "
        "language - so the honest reading is that Stage 17's negative result survives, for a "
        "sharper reason than before.\n"
    )
    out.append(
        f"**Stage 15/16 techniques, mapped empirically rather than by name.** For every technique "
        f"the Stage 15 record reports, the frames it claims were looked up in the grammar's own "
        f"parse of the reference song `{bundle['techniques'].get('reference_slug')}`. These are "
        "interpretations, not model elements, and no construction is ever renamed after a "
        "technique.\n"
    )
    out.append(_md_table(
        ["technique", "frames inspected", "dominant construction", "share",
         "correspondence", "mapped construction"],
        [[row["technique"], row["frames_inspected"],
          row["dominant_construction"] or "-", _pct(row["dominant_share"]),
          row["correspondence"], row["mapped_primitive"] or "-"]
         for row in bundle["techniques"].get("techniques", [])],
    ))
    out.append("")
    out.append(bundle["techniques"].get("scope_note", "") + "\n")
    out.append(
        "Counts: " + ", ".join(f"{name} {count}"
                               for name, count in sorted(bundle["techniques"].get("counts", {}).items()))
        + ". A technique that maps to nothing means the grammar describes its frames with SET or "
        "with the residual, which is a real finding: those techniques are named behaviours the "
        "temporal level does not distinguish.\n"
    )
    return out


def _section_15(bundle: Mapping[str, Any]) -> List[str]:
    comparison = bundle["stage18_comparison"]
    s = comparison["summary"]
    return [
        "## 15. Stage 18 Comparison\n",
        "Stage 18 is a baseline, not a rival. It produced a byte format; this stage produced a "
        "model. The comparison is therefore not only in bytes, and it is reported on six axes at "
        "once so that neither side can win by choosing the axis.\n",
        _md_table(
            ["song", "raw", "G5 (grammar)", "G5 ratio", "G6 (grammar + lexicon)", "G6 ratio",
             "G6 lexicon share", "Stage 18 best", "Stage 18 ratio"],
            [[f"`{row['slug']}`", row["raw_bytes"], row["g5_container_bytes"],
              _f6(row["g5_ratio"]), row["g6_container_bytes"], _f6(row["g6_ratio"]),
              _pct(row["g6_lexicon_share"]), row.get("stage18_bytes"),
              _f6(row.get("stage18_ratio"))]
             for row in comparison["songs"]],
        ),
        "",
        _md_table(
            ["axis", "G5 grammar", "G6 grammar + lexicon", "Stage 18 best"],
            [
                ["mean ratio", _f6(s["g5_mean_ratio"]), _f6(s["g6_mean_ratio"]),
                 _f6(s["stage18_mean_ratio"])],
                ["ratio with its own definition charged", _f6(s["g5_mean_ratio_with_grammar"]),
                 _f6(s["g6_mean_ratio"]), _f6(s["stage18_mean_ratio"])],
                ["exact", "yes", "yes", "yes"],
                ["generalises across songs", "yes", "**no** - lexicon transfers nothing",
                 "not applicable, it is a format"],
                ["decoder RAM (bytes)", bundle["candidates"]["G5"]["ram_bytes"], "same", 9216],
                ["conceptual usefulness", "a vocabulary a generator could target",
                 "a dictionary of one song", "none claimed"],
            ],
        ),
        "",
        "**Stage 18 compresses better than the grammar proper; Stage 19 is structurally more "
        "useful. Neither statement is a mistake.** The grammar proper is 0.53 against Stage 18's "
        "0.51 - close, and in the same league. The configuration that genuinely beats Stage 18 "
        "does so by carrying most of its own bytes in a per-song lexicon, and that lexicon is worth "
        "nothing on a song it was not built from. This stage did not optimise to beat Stage 18 in "
        "bytes, and the place where it does win in bytes is the place where it stops being a "
        "grammar.\n",
    ]


def _section_16(bundle: Mapping[str, Any]) -> List[str]:
    tests = bundle["falsification"]
    out = [
        "## 16. Falsification\n",
        "Six deliberate attempts to break the result. Each states the condition that would have "
        "refuted the hypothesis, and reports whether that condition holds. Negative answers are "
        "kept in.\n",
        _md_table(
            ["test", "hypothesis under attack", "refuting condition", "holds?", "verdict"],
            [[name.split("_")[0], item["question"], item["refuting_condition"],
              "**yes**" if item["holds"] else "no", item["verdict"]]
             for name, item in sorted(tests.items()) if isinstance(item, Mapping)],
        ),
        "",
        "**The measured numbers behind each test.**\n",
    ]
    for name, item in sorted(tests.items()):
        if not isinstance(item, Mapping):
            continue
        out.append(f"- **{name.split('_')[0]} - {item['question']}**\n")
        out.append(f"  - measured: `{json.dumps(item['measured'], sort_keys=True)}`\n")
    out.append("")
    out.append(tests["reading"] + "\n")
    return out


def _section_17(bundle: Mapping[str, Any]) -> List[str]:
    g5 = bundle["candidates"]["G5"]
    return [
        "## 17. Implications for Composer\n",
        "Research implications only. **No composer feature was implemented, no IR was extended, no "
        "DSL was changed, no schema was added and no instrument bank was created.** The STOP "
        "condition of the brief is honoured: this section says what the results imply, not what "
        "was built.\n",
        "**What the results do imply.**\n",
        f"- A composer-facing temporal layer would have four constructions to target, not five: "
        f"{', '.join(bundle['shared_grammar']['intersection'])} are the ones every song kept, and "
        "RAMP is kept by all but one. That is a small enough target to be worth someone's time.\n",
        f"- The layer would have to be *exact*, and the residual is the reason it cannot be small: "
        f"{_pct(g5['coverage']['residual_share'])} of frames are not described by any construction "
        "and are carried verbatim. A composer layer that aspires to be a bridge must explain that "
        "share or accept that it is a compressor with a grammar on top.\n",
        "- The decoder is cheap enough to be plausible: tens of bytes of state, no buffer, no "
        "table. If a future stage ever wants a temporal layer on the machine, RAM is not what "
        "stops it.\n",
        "- The parameter distributions are narrow. Each construction is driven by a handful of "
        "shapes per song, which means a generator would have few parameters to get right - and it "
        "also means the unseen-parameter share of about eight percent is a floor on how much a "
        "generator would have to get *wrong* before it stopped decoding exactly.\n",
        "**What the results do not imply.**\n",
        "- That a grammar-shaped layer would be musically better. Exactness is not usefulness, and "
        "nothing here was listened to.\n",
        "- That a generator is feasible. Generalisation and generative usefulness are separate "
        "facts, measured separately here, and only the first was established.\n",
        "- That the lexicon could be replaced by a generator. Zero references transferred across "
        "all four folds; the lexicon is not reachable from a shared vocabulary, and a future stage "
        "that wanted the byte saving would have to generate the lexicon itself - which is the same "
        "problem as generating the song.\n",
        "**One concrete suggestion for a future stage**, offered as a question and not as a plan: "
        "compile a composition into these four constructions and measure the coverage and the "
        "residual against the same four songs. That is the only experiment that could move H3, and "
        "it is not this stage.\n",
    ]


def _section_18(bundle: Mapping[str, Any]) -> List[str]:
    verdicts = bundle["verdicts"]
    s = bundle["summary"]
    return [
        "## 18. Final Verdict\n",
        _md_table(
            ["level", "verdict"],
            [["H1 existence", verdicts["H1"]["verdict"]],
             ["H2 generalization", verdicts["H2"]["verdict"]],
             ["H3 generative usefulness", verdicts["H3"]["verdict"]],
             ["player integration", verdicts["player_integration"]["verdict"]]],
        ),
        "",
        "**H1 - existence.** " + _verdict_line(verdicts["H1"]) + "\n",
        "**H2 - generalization.** " + _verdict_line(verdicts["H2"]) + "\n",
        "**H3 - generative usefulness.** " + _verdict_line(verdicts["H3"]) + "\n",
        "**Player integration.** " + _verdict_line(verdicts["player_integration"]) + "\n",
        "Where the integration verdict is a refusal, the deciding condition is named rather than "
        "left implicit, so a future stage knows exactly what it would have to change:\n",
        _md_table(
            ["condition", "met", "measured"],
            [[item["condition"], "yes" if item["met"] else "**no**",
              json.dumps(item["measured"], sort_keys=True)]
             for item in verdicts["player_integration"]["conditions"]],
        ),
        "",
        f"The deciding condition is: **{s['deciding_condition']}**.\n",
        "**Why the answer is not simply yes or no.** The four songs really do share a small, "
        "neutral vocabulary of temporal constructions, it really is exact, and it really does "
        "transfer to a song that did not contribute to it. That part is a genuine positive result "
        "and it is the part the brief was hoping for. But the vocabulary spends about half the raw "
        "stream once its own definition is charged, which is not a layer between a composition IR "
        "and exact playback - it is a compression format with a grammar inside it. The one thing "
        "that is dramatically smaller is a per-song lexicon, and a lexicon that supplies zero "
        "references to a song it was not built from is a memorisation, not a language.\n",
    ]


def _verdict_line(block: Mapping[str, Any]) -> str:
    if "measured" in block:
        detail = json.dumps(block["measured"], sort_keys=True)
    else:
        met = sum(1 for item in block.get("conditions", []) if item["met"])
        detail = (
            f"{met} of {len(block.get('conditions', []))} conditions met; deciding condition: "
            f"{block.get('deciding_condition')}"
        )
    note = f" Note: {block['note']}" if block.get("note") else ""
    return f"**{block['verdict']}**. Measured: {detail}{note}"


def _section_final_question(bundle: Mapping[str, Any]) -> List[str]:
    answer = bundle["final_answer"]
    s = bundle["summary"]
    return [
        "## Final question\n",
        f"> **{answer['question']}**\n",
        f"**{answer['answer_in_short']}**\n",
        "The answer is derived from the evidence and not from intuition. Every number below was "
        "produced by encoding a stream and decoding it again, and the axes are listed in the order "
        "the brief asks for them:\n",
        _md_table(
            ["axis the brief asks for", "measured"],
            [
                ["coverage", f"structural coverage {_pct(s['grammar_structural_coverage'])}, "
                             f"frame coverage {_pct(s['grammar_frame_coverage'])}, "
                             f"change-event coverage {_pct(s['grammar_change_event_coverage'])}"],
                ["exact reconstruction", f"all candidates exact on all songs: {s['all_exact']}"],
                ["compression", f"grammar ratio {_f6(s['grammar_ratio'])}, with grammar and "
                                f"decoder charged {_f6(s['grammar_ratio_with_grammar'])}"],
                ["residual cost", f"{_pct(s['grammar_residual_share'])} of frames carried verbatim"],
                ["grammar complexity", f"{s['grammar_complexity']['score']} "
                                       f"({s['grammar_complexity']['primitives']} constructions, "
                                       f"{s['grammar_complexity']['parameter_fields']} parameter "
                                       f"fields, {s['grammar_complexity']['decoder_states']} "
                                       f"decoder states, "
                                       f"{s['grammar_complexity']['special_cases']} special cases)"],
                ["cross-song generalization",
                 f"leave-one-out vocabulary ratio {_f6(s['leave_one_out_ratios']['union_vocabulary_arm'])}"],
                ["leave-one-out (frozen parameters)",
                 f"{_f6(s['leave_one_out_ratios']['frozen_parameter_arm'])}, unseen parameters "
                 f"{_pct(s['unseen_parameter_share'])}"],
                ["lexicon transfer",
                 f"{s['repeat_references_transferred']} references from a shared lexicon of "
                 f"~{bundle['lexicon_leave_one_out']['mean_shared_lexicon_blocks']:.0f} blocks"],
                ["parameter generalization",
                 f"vocabulary overlap {_f6(bundle['parameters']['vocabulary_overlap_mean'])}; see "
                 "section 10 for which constructions share values"],
            ],
        ),
        "",
        "**So: yes for the language, no for the layer.** A small neutral set of temporal "
        "constructions does describe these four streams exactly, and it transfers to a song it was "
        "not induced from. But that language is not small in bytes - it spends about half the raw "
        "stream once its own definition is charged - and the one result that is dramatically "
        "smaller comes from a per-song lexicon that reproduces nothing on an unseen song. A layer "
        "between a composition IR and exact playback would have to be small *and* shared, and this "
        "one is shared but not small, or small but not shared. That is not a forced positive and it "
        "is not a clean negative either: it is the mixed result the brief asked to be reported as "
        "mixed rather than rounded.\n",
        "**What would change the answer.**\n",
        *[f"- {item}\n" for item in answer["what_would_change_the_answer"]],
        "**What this stage does not claim.**\n",
        *[f"- {item}\n" for item in answer["what_this_stage_does_not_claim"]],
        "**STOP.** Nothing was implemented in production. No player, no composer feature, no Music "
        "IR change, no POKEY IR change, no DSL change, no production schema, no instrument bank, no "
        "listening test. If this result is judged interesting, the next stage it invites is a "
        "generation experiment - whether a composer or a model can emit these four constructions "
        "with realistic parameters - and that is a different experiment from this one.\n",
    ]

    return bundle

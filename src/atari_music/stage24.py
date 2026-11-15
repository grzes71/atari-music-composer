"""Stage 24 - corpus overlap and confounding analysis.

Stage 23 measured a difference between the historical SAP corpus and the Tier A control corpus on a
convention-free residual estimand, and ended with

    HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED

because the matching criterion failed: the two corpora do not occupy the same region of trace-feature
space. Stage 24 does not re-measure the residual. It asks the question Stage 23 left open, and only
that question:

    **is the comparison identifiable at all with the data that exists?**

It does not look for a performance layer. It tries to establish the *boundary* of what the current
data can honestly support, and to name that boundary as an identifiability limit rather than as a
finding.

Three things are done here that Stage 23 did not do.

**1. The support criteria are calibrated before they are used.** An axis-aligned bounding box built
from 53 samples over 20 features is an extremely strict definition of support - it is easy to build a
criterion that nothing passes and then call the corpora incomparable. So every criterion is first run
*inside the control corpus*, leave-one-out, to see whether it can pass anything at all. A criterion
that rejects the control corpus's own members has no discriminating power and is reported as such.

**2. Every feature is checked for a length artefact.** Stage 23 declared ``distinct_audf_values`` a
feature with no common range, and that single feature made the multivariate overlap look hopeless.
The historical traces are two to three times longer than the control ones, and a count of distinct
values grows with length, so the separation is largely a property of trace length rather than of
music. The length-normalised version of the same feature overlaps. The raw count is reported and
excluded from the matching on that ground, with the reason stated, because excluding it *narrows* the
apparent separation and a reader is entitled to see the argument.

**3. The matching is re-derived rather than trusted.** Stage 23 declared a caliper constant and never
applied it, and used a single neighbour count with no balance check. Stage 24 declares its balance
criterion, its minimum retained sample and its parameter grid up front, applies them, and reports the
matched result as *undefined* when no parameter setting retains a usable sample - which is what
happens.

Everything is analysis-only, read-only and additive. No detector, compiler, player, exporter or
production schema is touched, no music is generated and no Stage 25 is begun.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from atari_music import stage15, stage18, stage20, stage21, stage22, stage23

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_STAGE24_DIR = DEFAULT_REPORTS_DIR / "stage24"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ARCHAEOLOGY_DIR = stage23.DEFAULT_ARCHAEOLOGY_DIR
DEFAULT_SONGS_DIR = stage23.DEFAULT_SONGS_DIR
DEFAULT_AI_DIR = stage23.DEFAULT_AI_DIR
DEFAULT_EXTRA_DSL_DIR = stage23.DEFAULT_EXTRA_DSL_DIR
DEFAULT_STAGE21_DIR = stage23.DEFAULT_STAGE21_DIR
DEFAULT_STAGE22_DIR = stage23.DEFAULT_STAGE22_DIR

# ---------------------------------------------------------------------------
# Pre-declared thresholds. Every one of these is stated before the numbers are
# read, so a verdict cannot be argued into a nicer answer afterwards.
# ---------------------------------------------------------------------------
#: An inverse-propensity score inside this band is "in the overlap region". 0.1/0.9 is the
#: conventional choice and is declared rather than tuned.
PROPENSITY_LOW = 0.10
PROPENSITY_HIGH = 0.90

#: A feature "supports matching" when at least this share of the *other* corpus lies inside its
#: range. Half is the declared bar; it is a coverage rule, not a significance test.
OVERLAP_COVERAGE = 0.50

#: Support verdict rule, declared up front:
#:   ADEQUATE   - no matching feature is separated, at least 80% of the historical traces are
#:                inside the control box, and the propensity overlap region retains 80% of both.
#:   PARTIAL    - at least one historical trace is inside the control box *and* the propensity
#:                overlap region retains at least one historical trace.
#:   INADEQUATE - otherwise.
SUPPORT_ADEQUATE_HISTORICAL_INSIDE = 0.80
SUPPORT_ADEQUATE_PROPENSITY_RETAINED = 0.80

#: Balance is judged on the absolute standardised mean difference of every matching feature.
#: 0.25 is the conventional "acceptable balance" bar and is declared before the matching runs.
SMD_THRESHOLD = 0.25

#: A matched comparison is only reported as a comparison when it retains at least this much
#: independent historical material. Below it the result is reported as undefined, not as a number.
MIN_RETAINED_TRACES = 4
MIN_RETAINED_SOURCES = 3

#: The declared parameter grid. Every setting is reported, including the ones that retain nothing.
CALIPERS: Tuple[float, ...] = (1.0, 2.0, 4.0)
NEIGHBOUR_COUNTS: Tuple[int, ...] = (1, 3, 5)

#: The IRLS fit is deterministic: a fixed ridge, a fixed iteration cap and a fixed tolerance.
IRLS_RIDGE = 1.0
IRLS_ITERATIONS = 100
IRLS_TOLERANCE = 1e-10

#: A difference below this is not treated as material, exactly as in Stage 23.
EFFECT_THRESHOLD = 0.05


class Stage24Error(RuntimeError):
    """A required input is missing or malformed, or a declared identity does not hold."""


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return stage15.sha256_file(path)


def _rnd(value: Optional[float], places: int = 6) -> Optional[float]:
    return None if value is None else round(value, places)


def _share(part: int, whole: int) -> Optional[float]:
    return None if not whole else round(part / whole, 6)


def _mean(values: Sequence[float]) -> Optional[float]:
    return None if not values else round(sum(values) / len(values), 6)


def _median(values: Sequence[float]) -> Optional[float]:
    return stage15._median(list(values))


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    return stage15._quantile(list(values), q)


def _stdev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return round(math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1)), 6)


def _cell(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _table(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    """A markdown table, so every report number is auditable against the source data."""
    head = "| " + " | ".join(_cell(item) for item in header) + " |"
    rule = "|" + "|".join("---" for _ in header) + "|"
    body = ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()

DEFAULT_STAGE23_DIR = stage23.DEFAULT_STAGE23_DIR

ANALYSIS_VERSION = "stage24/1"
RANDOM_SEED = 20250324
BOOTSTRAP_DRAWS = 4000
PROPENSITY_BOOTSTRAP = 200

#: The residual estimand is Stage 23's, not a new one. Stage 24 never re-measures a residual.
PRIMARY_ESTIMAND = stage23.PRIMARY_ESTIMAND
REGISTER_ORDER: Tuple[str, ...] = stage18.REGISTER_ORDER


# ===========================================================================
# PART 1 - the corpus inventory (section 4 of the brief)
# ===========================================================================
#: The four provenance classes the brief asks for, kept apart on purpose. A historical SAP has a
#: player, not a composition, so nothing about its notes, its instruments or its author's intent can
#: be recovered. Assigning composition features to it would invent data.
PROVENANCE_KNOWN = "known"
PROVENANCE_DERIVED = "derived_from_trace"
PROVENANCE_UNKNOWN = "unknown"
PROVENANCE_NOT_COMPARABLE = "not_comparable"

#: Fields the control corpus has and the historical corpus does not, or vice versa. Recorded as a
#: table rather than as prose so a reader can see exactly what is missing where.
COMPARABILITY_NOTES: Tuple[Dict[str, str], ...] = (
    {
        "field": "composition_sha256",
        "control": "present: the authored document's own hash",
        "historical": "absent: a SAP is a player plus data, not a composition",
        "class": PROVENANCE_NOT_COMPARABLE,
    },
    {
        "field": "compiled_trace_sha256",
        "control": "present: the trace is compiled deterministically from the document",
        "historical": "absent: the trace is digitised from a running player",
        "class": PROVENANCE_NOT_COMPARABLE,
    },
    {
        "field": "ground_truth_notes",
        "control": "present: the document is the ground truth",
        "historical": "absent: Tier D, no independent note source exists",
        "class": PROVENANCE_UNKNOWN,
    },
    {
        "field": "note_count / rest_count / pattern_count",
        "control": "present: read from the document",
        "historical": "absent: not recoverable from a trace, and not inferred here",
        "class": PROVENANCE_NOT_COMPARABLE,
    },
    {
        "field": "author / date",
        "control": "project-authored, so not an independent composer",
        "historical": "credited composer and year, read from the SAP header",
        "class": PROVENANCE_KNOWN,
    },
    {
        "field": "audctl / frames / spans / residual",
        "control": "measured from the trace, identically to the historical corpus",
        "historical": "measured from the trace",
        "class": PROVENANCE_DERIVED,
    },
    {
        "field": "player_routine",
        "control": "the project's own player, one routine, known",
        "historical": "an unknown third-party routine; only its trace-visible behaviour is measurable",
        "class": PROVENANCE_UNKNOWN,
    },
)


@dataclass(frozen=True)
class CorpusRecord:
    """One audited corpus member: Stage 23's measurement plus what Stage 24 adds.

    ``evidence`` is Stage 23's :class:`TraceEvidence`, reused rather than re-measured, so the residual
    estimand and the trace features are bit-identical to Stage 23's and the two stages cannot drift
    apart. ``measures`` holds the features Stage 24 adds, and ``inventory`` holds the provenance.
    """

    slug: str
    corpus: str
    source_key: str
    author: str
    date: str
    sap_type: str
    kind: str
    frames: int
    channels: int
    audctl: int
    trace_sha256: Optional[str]
    source_sha256: Optional[str]
    measures: Mapping[str, Optional[float]]
    inventory: Mapping[str, Any]
    evidence: Any = None

    @property
    def features(self) -> Dict[str, Optional[float]]:
        """Every Stage 23 matching feature plus every Stage 24 measure, in one mapping."""
        merged: Dict[str, Optional[float]] = {
            name: float(self.evidence.features[name]) for name in stage23.MATCH_FEATURES
        }
        merged.update({key: value for key, value in self.measures.items()})
        return merged

    @property
    def estimand(self) -> Optional[float]:
        return self.evidence.estimands[PRIMARY_ESTIMAND]

    @property
    def residual_counts(self) -> Mapping[str, Tuple[int, int]]:
        return self.evidence.counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "corpus": self.corpus,
            "source_key": self.source_key,
            "author": self.author,
            "date": self.date,
            "sap_type": self.sap_type,
            "kind": self.kind,
            "frames": self.frames,
            "channels": self.channels,
            "audctl": f"${int(self.audctl):02X}",
            "trace_sha256": self.trace_sha256,
            "source_sha256": self.source_sha256,
            "features": {key: _rnd(value) for key, value in sorted(self.features.items())},
            "estimand": self.estimand,
            "inventory": dict(sorted(self.inventory.items())),
        }


#: The Stage 24 matching feature set, with every exclusion argued rather than assumed. Each entry is
#: a formal definition: what is counted, over what denominator, how silence is treated and where the
#: measurement is limited. A feature is only here if it is measurable the same way in both corpora.
FEATURE_DEFINITIONS: Tuple[Dict[str, str], ...] = (
    {
        "name": "frames",
        "definition": "the number of 50 Hz frames in the trace",
        "unit": "frames",
        "denominator": "none (a length, not a rate)",
        "silence": "not applicable",
        "limitations": (
            "a raw length. The historical traces are longer because a game tune runs for minutes "
            "while a test composition runs for seconds; this is a corpus-construction difference and "
            "it propagates into every count-valued feature, which is why those are normalised below"
        ),
        "role": "matching",
    },
    {
        "name": "audible_share",
        "definition": "frames in which at least one voice's AUDC volume nibble is above zero",
        "unit": "share of frames",
        "denominator": "frames",
        "silence": "a silent frame is counted as not audible; silence is part of the measure",
        "limitations": (
            "audibility is read from the volume nibble alone, so a zero divider at full volume counts "
            "as audible - which is what the Stage 15 detector does too, so the feature and the "
            "detector agree by construction"
        ),
        "role": "matching",
    },
    {
        "name": "silence_share",
        "definition": "frames in which every voice's AUDC volume nibble is zero",
        "unit": "share of frames",
        "denominator": "frames",
        "silence": "this is the silence measure; it is not excluded",
        "limitations": "the complement of audibility, reported separately because the brief asks for it",
        "role": "matching",
    },
    {
        "name": "low_volume_share",
        "definition": "frames in which at most one voice has a non-zero volume nibble",
        "unit": "share of frames",
        "denominator": "frames",
        "silence": "includes full silence, so it is a superset of silence_share",
        "limitations": "an absolute threshold of one voice; it is not a perceptual loudness measure",
        "role": "matching",
    },
    {
        "name": "register_change_rate",
        "definition": "frames in which any of the nine register columns differs from the frame before",
        "unit": "changes per frame",
        "denominator": "frames - 1",
        "silence": "silent frames are counted; a register that moves while silent is a change",
        "limitations": "counts frames, not values, so a frame where four columns move counts once",
        "role": "matching",
    },
    {
        "name": "audf_change_rate",
        "definition": "frames in which any AUDF column differs from the frame before",
        "unit": "changes per frame",
        "denominator": "frames - 1",
        "silence": "silent frames are counted",
        "limitations": (
            "AUDF is the pitch divider, so this measures pitch activity. The historical corpus's "
            "players pulse AUDF to zero between notes, which inflates this measure; the pulse is a "
            "player trait and it is a feature of the trace, not of the music"
        ),
        "role": "matching",
    },
    {
        "name": "audc_change_rate",
        "definition": "frames in which any AUDC column differs from the frame before",
        "unit": "changes per frame",
        "denominator": "frames - 1",
        "silence": "silent frames are counted",
        "limitations": "AUDC carries both volume and distortion, so this mixes the two",
        "role": "matching",
    },
    {
        "name": "audc_volume_change_rate",
        "definition": "frames in which any voice's AUDC volume nibble differs from the frame before",
        "unit": "changes per frame",
        "denominator": "frames - 1",
        "silence": "silent frames are counted",
        "limitations": "the volume nibble is the high nibble of AUDC; the split is Stage 15's",
        "role": "matching",
    },
    {
        "name": "audc_distortion_change_rate",
        "definition": "frames in which any voice's AUDC distortion nibble differs from the frame before",
        "unit": "changes per frame",
        "denominator": "frames - 1",
        "silence": "silent frames are counted",
        "limitations": (
            "the distortion nibble is the generator. A change here is an instrument change, which is "
            "the thing the shared detector is worst at following"
        ),
        "role": "matching",
    },
    {
        "name": "noise_active_share",
        "definition": "frames in which at least one audible voice is in a noise waveform family",
        "unit": "share of frames",
        "denominator": "frames",
        "silence": "a silent voice is not audible, so it cannot be in a noise family",
        "limitations": (
            "the waveform family is decoded from the distortion nibble, so this is exact for both "
            "corpora and needs no ground truth"
        ),
        "role": "matching",
    },
    {
        "name": "mean_simultaneous",
        "definition": "the mean number of audible voices per frame",
        "unit": "voices per frame",
        "denominator": "frames",
        "silence": "silent frames contribute zero and are counted",
        "limitations": "a count of voices, not of perceived polyphony",
        "role": "matching",
    },
    {
        "name": "max_simultaneous",
        "definition": "the largest number of simultaneously audible voices in the trace",
        "unit": "voices",
        "denominator": "none (a maximum)",
        "silence": "not applicable",
        "limitations": (
            "POKEY has four voices and a joined 16-bit pair occupies two, so this is bounded by four "
            "in both corpora and cannot separate them - it is reported for completeness"
        ),
        "role": "matching",
    },
    {
        "name": "coupled_16bit",
        "definition": "1 when AUDCTL joins channels 1 and 2 into a 16-bit pair, else 0",
        "unit": "0 or 1",
        "denominator": "none (a configuration flag, constant within a trace)",
        "silence": "not applicable",
        "limitations": (
            "a hardware configuration, read from AUDCTL, which is constant for every frame in every "
            "trace of both corpora. It is a property of the *configuration*, not of the music"
        ),
        "role": "matching",
    },
    {
        "name": "clock_179mhz",
        "definition": "1 when AUDCTL clocks a channel from the 1.79 MHz CPU clock, else 0",
        "unit": "0 or 1",
        "denominator": "none (a configuration flag, constant within a trace)",
        "silence": "not applicable",
        "limitations": (
            "the single most consequential feature in this analysis. It is a hardware clock, not a "
            "musical choice, and it changes the divider arithmetic, the pitch resolution and the "
            "range of AUDF values a tune can use. It is also the feature on which the corpora are "
            "structurally separated: no control composition uses it"
        ),
        "role": "matching",
    },
    {
        "name": "audf_diversity_per_1000_frames",
        "definition": (
            "the number of distinct AUDF values across the trace's pitch channels, per 1000 frames"
        ),
        "unit": "distinct divider values per 1000 frames",
        "denominator": "frames / 1000",
        "silence": "AUDF is read from every frame, silent or not",
        "limitations": (
            "this replaces Stage 23's raw distinct_audf_values, which grows with trace length. The "
            "raw count separates the corpora completely and the normalised one does not, which is "
            "the length artefact this stage exists to expose"
        ),
        "role": "matching",
    },
    {
        "name": "distinct_audc_values",
        "definition": "the number of distinct AUDC bytes across the trace's volume channels",
        "unit": "distinct byte values",
        "denominator": "none (a count)",
        "silence": "AUDC is read from every frame, silent or not",
        "limitations": (
            "bounded by 256, so it saturates far less than the AUDF count and is far less "
            "length-confounded; the historical maximum is 48 against a control maximum of 35"
        ),
        "role": "matching",
    },
    {
        "name": "mean_audc_run_length",
        "definition": "the mean number of consecutive frames over which an AUDC byte is unchanged",
        "unit": "frames",
        "denominator": "number of AUDC runs",
        "silence": "runs of a silent AUDC byte are included",
        "limitations": "a within-voice measure, pooled over voices; a long silent run dominates it",
        "role": "matching",
    },
    {
        "name": "channel_balance",
        "definition": "the spread of per-voice audible-frame counts, as (max - min) / mean",
        "unit": "dimensionless ratio",
        "denominator": "the mean per-voice audible-frame count",
        "silence": "a voice that is never audible contributes zero and lowers the mean",
        "limitations": (
            "defined only when the mean is non-zero; a trace where no voice is audible has no value "
            "and is reported as undefined rather than as zero"
        ),
        "role": "matching",
    },
    {
        "name": "register_change_cooccurrence",
        "definition": (
            "of the frames where any register changes, the share where two or more columns change "
            "together"
        ),
        "unit": "share of change frames",
        "denominator": "frames in which any register changed",
        "silence": "a change while silent is still a change and is counted",
        "limitations": (
            "undefined for a trace whose registers never change; the denominator is the trace's own "
            "change frames, so it is a within-trace share and not a rate"
        ),
        "role": "matching",
    },
    {
        "name": "detector_generator_recall",
        "definition": (
            "of the frames where an AUDC distortion nibble actually changes, the share the shared "
            "Stage 15 detector also places a span onset on"
        ),
        "unit": "share of true change frames",
        "denominator": "frames where an AUDC distortion nibble changes",
        "silence": "distortion is read from AUDC regardless of volume",
        "limitations": (
            "the detector's representation can only change a generator where a span begins, so this "
            "is bounded above by the detector's segmentation and is not a property of the music. It "
            "is measurable identically on both corpora because it needs no ground truth - the truth "
            "is the trace itself"
        ),
        "role": "matching",
    },
    {
        "name": "detector_generator_precision",
        "definition": (
            "of the span onsets the detector places, the share that coincide with a frame where an "
            "AUDC distortion nibble actually changes"
        ),
        "unit": "share of predicted onset frames",
        "denominator": "span onset frames",
        "silence": "as above",
        "limitations": (
            "an onset need not be a distortion change - a note can restart on the same generator - "
            "so a low value is expected and is not an error. It is reported because the brief asks "
            "for the shared detector's generator behaviour in both corpora"
        ),
        "role": "matching",
    },
    {
        "name": "audctl_change_rate",
        "definition": "frames in which the AUDCTL column differs from the frame before",
        "unit": "changes per frame",
        "denominator": "frames - 1",
        "silence": "not applicable",
        "limitations": (
            "EXCLUDED from the matching: it is identically zero in all traces of both corpora, so it "
            "carries no information and cannot separate anything. Stage 23 listed it as a matching "
            "feature and its overlap table reported it as having 'no common range', which reads as a "
            "separation; a feature that is the same constant in both corpora is the opposite of a "
            "separation, and the classification here is corrected"
        ),
        "role": "excluded_degenerate",
    },
    {
        "name": "stable_run_median",
        "definition": (
            "the median number of consecutive frames over which the whole nine-column state is "
            "unchanged"
        ),
        "unit": "frames",
        "denominator": "number of state runs",
        "silence": "state runs include silent frames",
        "limitations": (
            "EXCLUDED from the matching: measured at exactly 1.0 in every trace, because with four "
            "voices' worth of registers at least one column changes almost every frame. It is "
            "degenerate, not separated"
        ),
        "role": "excluded_degenerate",
    },
    {
        "name": "distinct_audf_values",
        "definition": "the number of distinct AUDF values across the trace's pitch channels",
        "unit": "distinct divider values",
        "denominator": "none (a count)",
        "silence": "AUDF is read from every frame",
        "limitations": (
            "EXCLUDED from the matching as length-confounded: a count of distinct values grows with "
            "trace length, the historical traces are two to three times longer, and this feature is "
            "the one that made Stage 23's multivariate overlap look empty. Its length-normalised "
            "replacement is in the matching set and overlaps. The raw count is still reported, and "
            "the exclusion narrows the apparent separation, so the reader can judge the argument"
        ),
        "role": "excluded_confounded",
    },
)

MATCHING_FEATURES: Tuple[str, ...] = tuple(
    item["name"] for item in FEATURE_DEFINITIONS if item["role"] == "matching"
)
EXCLUDED_FEATURES: Tuple[Tuple[str, str], ...] = tuple(
    (item["name"], item["role"]) for item in FEATURE_DEFINITIONS if item["role"] != "matching"
)


# ===========================================================================
# PART 2 - measuring the corpus (sections 4 and 5 of the brief)
# ===========================================================================
def _change_count(values: Sequence[int]) -> int:
    return sum(1 for index in range(1, len(values)) if values[index] != values[index - 1])


def _change_frames(values: Sequence[int]) -> List[int]:
    return [index for index in range(1, len(values)) if values[index] != values[index - 1]]


def _run_lengths(values: Sequence[int]) -> List[int]:
    """Run lengths of consecutive equal values, in order."""
    if not values:
        return []
    runs: List[int] = []
    length = 1
    for index in range(1, len(values)):
        if values[index] == values[index - 1]:
            length += 1
        else:
            runs.append(length)
            length = 1
    runs.append(length)
    return runs


def _audible_voice_count(trace: Any, frame: int) -> int:
    return sum(
        1 for voice in stage15.voices_for(int(trace.audctl))
        if stage15.audc_volume(trace.registers[f"AUDC{voice.volume_channel}"][frame]) > 0
    )


def trace_measures(trace: Any) -> Dict[str, Optional[float]]:
    """The Stage 24 features, computed from the trace alone and identically in both corpora.

    Nothing here consults a composition, a ground truth or a residual. That is deliberate: the whole
    point of the matching is to use only what both corpora can supply, and a feature that needed the
    control corpus's ground truth would be measurable in one corpus and not the other.
    """
    registers = trace.registers
    frames = max(1, trace.frames)
    voices = stage15.voices_for(int(trace.audctl))

    audible = [_audible_voice_count(trace, frame) for frame in range(trace.frames)]
    silence = sum(1 for value in audible if value == 0)
    low = sum(1 for value in audible if value <= 1)

    states = [
        tuple(registers[name][frame] for name in REGISTER_ORDER)
        for frame in range(trace.frames)
    ]
    state_runs = sorted(_run_lengths(states))
    stable_median = float(state_runs[len(state_runs) // 2]) if state_runs else None

    change_frames = 0
    multi_change_frames = 0
    for frame in range(1, trace.frames):
        moved = sum(
            1 for name in REGISTER_ORDER
            if registers[name][frame] != registers[name][frame - 1]
        )
        if moved:
            change_frames += 1
            if moved >= 2:
                multi_change_frames += 1

    records = stage20.note_records(trace)
    true_frames: List[int] = []
    predicted_frames: List[int] = []
    for voice in voices:
        audc = registers[f"AUDC{voice.volume_channel}"]
        true_frames.extend(
            _change_frames([stage15.audc_distortion(audc[frame]) for frame in range(trace.frames)])
        )
        predicted_frames.extend(
            sorted(int(record.start) for record in records if record.voice_id == voice.voice_id)
        )
    true_set = set(true_frames)
    predicted_set = set(predicted_frames)
    hits = len(true_set & predicted_set)

    audf_values: set = set()
    for voice in voices:
        for channel in voice.pitch_channels:
            audf_values.update(registers[f"AUDF{channel}"])

    per_voice_audible = []
    for voice in voices:
        audc = registers[f"AUDC{voice.volume_channel}"]
        per_voice_audible.append(
            sum(1 for frame in range(trace.frames) if stage15.audc_volume(audc[frame]) > 0)
        )
    mean_voice = _mean([float(value) for value in per_voice_audible])
    balance = (
        None if not mean_voice
        else (max(per_voice_audible) - min(per_voice_audible)) / mean_voice
    )

    return {
        "silence_share": _share(silence, frames),
        "low_volume_share": _share(low, frames),
        "stable_run_median": stable_median,
        "register_change_cooccurrence": _share(multi_change_frames, change_frames),
        "detector_generator_recall": _share(hits, len(true_set)),
        "detector_generator_precision": _share(hits, len(predicted_set)),
        "audf_diversity_per_1000_frames": round(len(audf_values) / frames * 1000.0, 6),
    }




# ===========================================================================
# PART 3 - the overlap audit (section 6 of the brief)
# ===========================================================================
def feature_values(
    records: Sequence[CorpusRecord], feature: str
) -> List[Optional[float]]:
    return [record.features.get(feature) for record in records]


def univariate_overlap(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
) -> Dict[str, Any]:
    """The brief's per-feature table, with both outside-support counts and a classification.

    Stage 23 reported only ``historical_inside_control_range_share`` and treated a constant feature
    as having "no common range". Both are corrected here: the table carries both directions of
    outside-support, and a feature that is the same constant in both corpora is classified as
    ``shared_constant`` - the opposite of a separation - rather than as disjoint.
    """
    rows: List[Dict[str, Any]] = []
    for name in features:
        cx = [value for value in feature_values(control, name) if value is not None]
        hx = [value for value in feature_values(historical, name) if value is not None]
        if not cx or not hx:
            rows.append({
                "feature": name, "classification": "not_measurable",
                "control_n": len(cx), "historical_n": len(hx),
            })
            continue
        c_lo, c_hi = min(cx), max(cx)
        h_lo, h_hi = min(hx), max(hx)
        support_low = max(c_lo, h_lo)
        support_high = min(c_hi, h_hi)
        c_constant = c_lo == c_hi
        h_constant = h_lo == h_hi
        control_outside = sum(1 for value in cx if value < h_lo or value > h_hi)
        historical_outside = sum(1 for value in hx if value < c_lo or value > c_hi)
        if c_constant and h_constant and c_lo == h_lo:
            classification = "shared_constant"
        elif support_low > support_high:
            classification = "separated"
        elif support_low == support_high:
            classification = "point_support"
        elif control_outside == 0 and historical_outside == 0:
            classification = "full"
        else:
            classification = "partial"
        rows.append({
            "feature": name,
            "control_min": c_lo,
            "control_max": c_hi,
            "control_mean": _mean(cx),
            "control_median": _median(cx),
            "control_n": len(cx),
            "historical_min": h_lo,
            "historical_max": h_hi,
            "historical_mean": _mean(hx),
            "historical_median": _median(hx),
            "historical_n": len(hx),
            "support_low": support_low,
            "support_high": support_high,
            "support_empty": support_low > support_high,
            "support_width": round(max(0.0, support_high - support_low), 6),
            "control_outside_support": control_outside,
            "control_outside_share": _share(control_outside, len(cx)),
            "historical_outside_support": historical_outside,
            "historical_outside_share": _share(historical_outside, len(hx)),
            "historical_inside_control_range_share": _share(
                len(hx) - historical_outside, len(hx)
            ),
            "control_constant": c_constant,
            "historical_constant": h_constant,
            "classification": classification,
            "supports_matching": classification in ("full", "partial", "point_support"),
        })
    separated = sorted(
        row["feature"] for row in rows if row["classification"] == "separated"
    )
    degenerate = sorted(
        row["feature"] for row in rows if row["classification"] == "shared_constant"
    )
    unsupported = sorted(
        row["feature"] for row in rows
        if row["classification"] not in ("full", "partial", "point_support", "shared_constant")
    )
    supported = [row for row in rows if row.get("supports_matching")]
    return {
        "features": rows,
        "matching_feature_count": len(features),
        "features_supporting_matching": len(supported),
        "separated_features": separated,
        "degenerate_features": degenerate,
        "unsupported_features": unsupported,
        "coverage_threshold": OVERLAP_COVERAGE,
        "poorly_covered_features": sorted(
            row["feature"] for row in rows
            if row.get("supports_matching")
            and (row["historical_inside_control_range_share"] or 0.0) < OVERLAP_COVERAGE
        ),
        "reading": (
            "a feature supports matching when neither corpus is wholly outside the other's range. "
            "'separated' means the ranges are disjoint; 'shared_constant' means the feature is the "
            "same constant in both corpora, which is no information rather than a separation"
        ),
    }


def _historical_inventory(payload: Mapping[str, Any], path: Path) -> Dict[str, Any]:
    """What is known, derived, unknown and not comparable about one historical SAP."""
    source = payload.get("source", {}) or {}
    return {
        "trace_origin": (
            "digitised from a running SAP player: the trace is the register stream the third-party "
            "player actually wrote, sampled at 50 Hz"
        ),
        "composition_available": False,
        "ground_truth_status": (
            "Tier D - a SAP is a player plus data, so no independent note source exists"
        ),
        "player_known": False,
        "player_note": (
            "the player routine is unknown. Only its trace-visible behaviour is measurable, and any "
            "statement about it is a statement about the trace, not about the code"
        ),
        "audctl_source": "derived from the trace's AUDCTL column (constant in every trace here)",
        "frames_source": "derived from the trace's frame count",
        "channels_source": "derived from the trace's AUDCTL voice configuration",
        "author_source": f"SAP header ({source.get('author') or 'unknown'})",
        "date_source": f"SAP header ({source.get('date') or 'unknown'})",
        "trace_file": path.name,
        "known": ["author", "date", "sap_type", "audctl", "frames", "channels"],
        "derived_from_trace": [
            "frames", "channels", "audctl", "spans", "residual", "every matching feature",
        ],
        "unknown": [
            "the composition", "the note set", "the intended instruments", "the tempo",
            "the channel assignment", "the player routine", "the author's intent",
        ],
        "not_comparable": [
            "composition_sha256", "compiled_trace_sha256", "note_count", "rest_count",
            "pattern_count", "sequence_length", "uses_16bit_bass", "frames_per_tick",
        ],
    }


def _control_inventory(song: Any) -> Dict[str, Any]:
    """What is known, derived, unknown and not comparable about one control composition."""
    return {
        "trace_origin": (
            "compiled deterministically from the authored document by the project's own frame "
            "compiler, so the trace's ground truth is the document"
        ),
        "composition_available": True,
        "ground_truth_status": "Tier A - the document is the ground truth",
        "player_known": True,
        "player_note": (
            "the project's own player and frame compiler. One routine for the whole corpus, so the "
            "control corpus has one player while the historical corpus has several"
        ),
        "audctl_source": "read from the document's resolved AUDCTL, and identical in the trace",
        "frames_source": "the compiled frame count",
        "channels_source": "read from the document's track set",
        "author_source": "project-authored, so not an independent composer",
        "date_source": "unknown; the documents carry no date",
        "document_sha256": song.sha256,
        "compiled_trace_sha256": song.compiled_sha256,
        "known": [
            "composition", "note set", "instruments", "tempo", "channel assignment", "player",
            "audctl", "frames", "channels",
        ],
        "derived_from_trace": [
            "frames", "channels", "spans", "residual", "every matching feature",
        ],
        "unknown": ["date"],
        "not_comparable": ["credited composer", "date"],
    }


def _channel_count(trace: Any) -> int:
    return len(stage15.voices_for(int(trace.audctl)))

FRAME_BYTES = stage18.FRAME_BYTES



def load_historical_records(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
) -> List[CorpusRecord]:
    """The historical corpus, measured by Stage 23 and inventoried by Stage 24."""
    out: List[CorpusRecord] = []
    for path in sorted(stage15.list_traces(Path(arch_root))):
        trace = stage15.load_trace(path)
        payload = _read_json(path)
        source = payload.get("source", {}) or {}
        evidence = stage23.measure_trace(
            trace,
            corpus="historical",
            kind=str(payload.get("schema", "unknown")),
            source_key=str(source.get("song_file") or trace.slug),
            author=str(source.get("author") or "unknown"),
            date=str(source.get("date") or "unknown"),
            sap_type=str(source.get("sap_type") or "unknown"),
        )
        out.append(
            CorpusRecord(
                slug=trace.slug,
                corpus="historical",
                source_key=evidence.source_key,
                author=evidence.author,
                date=evidence.date,
                sap_type=evidence.sap_type,
                kind=evidence.kind,
                frames=trace.frames,
                channels=_channel_count(trace),
                audctl=int(trace.audctl),
                trace_sha256=sha256_file(path),
                source_sha256=None,
                measures=trace_measures(trace),
                inventory=_historical_inventory(payload, path),
                evidence=evidence,
            )
        )
    return out


def load_control_records(
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
) -> List[CorpusRecord]:
    """The control corpus, measured by Stage 23 and inventoried by Stage 24.

    The trace is compiled once and handed to both ``stage23.measure_trace`` and
    ``trace_measures``, so the residual and the features come from one reading of one trace.
    """
    corpus, _skipped = stage21.load_control_corpus(songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR)
    out: List[CorpusRecord] = []
    for song in corpus:
        evidence = stage23.measure_trace(
            song.trace,
            corpus="control",
            kind=song.kind,
            source_key=song.sha256,
            author="project",
            date="unknown",
            sap_type="dsl",
        )
        out.append(
            CorpusRecord(
                slug=song.slug,
                corpus="control",
                source_key=song.sha256,
                author="project",
                date="unknown",
                sap_type="dsl",
                kind=song.kind,
                frames=song.trace.frames,
                channels=_channel_count(song.trace),
                audctl=int(song.trace.audctl),
                trace_sha256=None,
                source_sha256=song.sha256,
                measures=trace_measures(song.trace),
                inventory=_control_inventory(song),
                evidence=evidence,
            )
        )
    return out


# ===========================================================================
# PART 4 - multivariate support (section 6 of the brief, continued)
# ===========================================================================
def feature_matrix(
    records: Sequence[CorpusRecord], features: Sequence[str]
) -> np.ndarray:
    """A float matrix in a fixed feature order. An undefined value is refused, not imputed."""
    rows: List[List[float]] = []
    for record in records:
        row: List[float] = []
        for name in features:
            value = record.features.get(name)
            if value is None:
                raise Stage24Error(
                    f"{record.slug}: the matching feature {name} is undefined, so the trace cannot "
                    "enter a distance-based analysis"
                )
            row.append(float(value))
        rows.append(row)
    return np.array(rows, dtype=float)


def pooled_standardisation(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
) -> Dict[str, Any]:
    """Pooled mean and standard deviation, so neither corpus's scale is privileged.

    A feature whose pooled standard deviation is zero cannot enter a distance: it would either
    divide by zero or contribute nothing. Both cases are refused explicitly rather than silently
    coerced, and the caller is told which features were dropped.
    """
    pooled = np.vstack([feature_matrix(control, features), feature_matrix(historical, features)])
    mean = pooled.mean(axis=0)
    stdev = pooled.std(axis=0, ddof=1)
    usable = [name for name, spread in zip(features, stdev) if spread > 0]
    dropped = [name for name, spread in zip(features, stdev) if not spread > 0]
    return {
        "features": list(features),
        "usable_features": usable,
        "dropped_zero_variance": dropped,
        "mean": {name: round(float(value), 6) for name, value in zip(features, mean)},
        "stdev": {name: round(float(value), 6) for name, value in zip(features, stdev)},
        "pooled": True,
        "note": (
            "scaled on the pooled set of both corpora. A standardised difference is then not "
            "inflated by choosing one corpus's scale, which is what Stage 23 did as well"
        ),
    }


def standardise(
    records: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
) -> np.ndarray:
    features = list(stats["usable_features"])
    matrix = feature_matrix(records, features)
    mean = np.array([stats["mean"][name] for name in features])
    stdev = np.array([stats["stdev"][name] for name in features])
    return (matrix - mean) / stdev


def _distance_matrix(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    diff = left[:, None, :] - right[None, :, :]
    return np.sqrt((diff * diff).sum(axis=2))


def box_support(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
) -> Dict[str, Any]:
    """Axis-aligned bounding-box support, calibrated against the control corpus itself.

    The box criterion is the strictest support definition available and it is the one that produced
    Stage 23's "no common range" reading. A box built from 53 samples over 21 features is easy to
    make unreachable, so the same test is first run leave-one-out *inside* the control corpus. If
    the control's own members mostly fail it, the criterion has no discriminating power and the
    historical failure count means nothing; that number is therefore reported beside the result.
    """
    features = list(features)
    control_matrix = feature_matrix(control, features)
    historical_matrix = feature_matrix(historical, features)
    box_low = control_matrix.min(axis=0)
    box_high = control_matrix.max(axis=0)

    def outside(vector: np.ndarray, low: np.ndarray, high: np.ndarray) -> List[str]:
        return [
            name for index, name in enumerate(features)
            if vector[index] < low[index] or vector[index] > high[index]
        ]

    control_outside = [
        outside(control_matrix[index], box_low, box_high) for index in range(len(control))
    ]
    historical_outside = [
        outside(historical_matrix[index], box_low, box_high)
        for index in range(len(historical))
    ]
    calibration: List[List[str]] = []
    for index in range(len(control)):
        others = np.delete(control_matrix, index, axis=0)
        calibration.append(
            outside(control_matrix[index], others.min(axis=0), others.max(axis=0))
        )

    def summary(counts: Sequence[Sequence[str]], total: int) -> Dict[str, Any]:
        sizes = [len(value) for value in counts]
        return {
            "traces": total,
            "inside_on_every_feature": sum(1 for value in sizes if value == 0),
            "inside_share": _share(sum(1 for value in sizes if value == 0), total),
            "outside_on_at_most_1": sum(1 for value in sizes if value <= 1),
            "outside_on_at_most_2": sum(1 for value in sizes if value <= 2),
            "outside_on_at_most_3": sum(1 for value in sizes if value <= 3),
            "median_features_outside": _median([float(value) for value in sizes]),
            "max_features_outside": max(sizes) if sizes else None,
        }

    return {
        "features": features,
        "control_box_low": {
            name: round(float(value), 6) for name, value in zip(features, box_low)
        },
        "control_box_high": {
            name: round(float(value), 6) for name, value in zip(features, box_high)
        },
        "control": summary(control_outside, len(control)),
        "historical": summary(historical_outside, len(historical)),
        "calibration_inside_control": summary(calibration, len(control)),
        "calibration_has_power": sum(1 for value in calibration if not value) > 0,
        "historical_per_trace": [
            {
                "slug": record.slug,
                "source_key": record.source_key,
                "features_outside": len(historical_outside[index]),
                "outside_features": sorted(historical_outside[index]),
            }
            for index, record in enumerate(historical)
        ],
        "control_per_trace": [
            {
                "slug": record.slug,
                "features_outside": len(control_outside[index]),
                "outside_features": sorted(control_outside[index]),
            }
            for index, record in enumerate(control)
        ],
        "reading": (
            "the box test is only evidence when it can pass the control corpus's own members. "
            "'calibration_inside_control' is that check; the historical count is read against it"
        ),
    }


def _irls_logistic(
    design: np.ndarray,
    outcome: np.ndarray,
    ridge: float = IRLS_RIDGE,
    iterations: int = IRLS_ITERATIONS,
    tolerance: float = IRLS_TOLERANCE,
) -> Tuple[np.ndarray, int, bool]:
    """Ridge-regularised logistic regression by iteratively reweighted least squares.

    Written out rather than imported because the project has no solver dependency and because the
    fit has to be *deterministic*: a fixed ridge, a fixed iteration cap and a fixed tolerance mean
    the same corpus always produces the same coefficients. The ridge is what keeps the fit defined
    when the corpora are separated, which is exactly the case here - without it the coefficients
    would run to infinity on the separating feature.
    """
    beta = np.zeros(design.shape[1])
    for iteration in range(iterations):
        eta = np.clip(design @ beta, -30.0, 30.0)
        probability = 1.0 / (1.0 + np.exp(-eta))
        weight = np.clip(probability * (1.0 - probability), 1e-9, None)
        gradient = design.T @ (outcome - probability) - ridge * beta
        hessian = design.T @ (design * weight[:, None]) + ridge * np.eye(design.shape[1])
        step = np.linalg.solve(hessian, gradient)
        beta = beta + step
        if float(np.max(np.abs(step))) < tolerance:
            return beta, iteration + 1, True
    return beta, iterations, False


def propensity_analysis(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
    bootstrap: int = PROPENSITY_BOOTSTRAP,
    seed: int = RANDOM_SEED,
) -> Dict[str, Any]:
    """A propensity score, its overlap region, and a stability check that is allowed to fail.

    The brief warns that a model's output is not proof of overlap, and it is right. The score is
    fitted here for a specific purpose: to *test* whether an overlap region exists at all. It is
    fitted on the pooled standardised features with a declared ridge, and then it is refitted on
    deterministic bootstrap resamples of the pooled corpus. If coefficients change sign across
    resamples, the model is not estimable at this sample size and its separation is a statement
    about the sample rather than about the corpora. Both facts are reported and neither is used
    alone.
    """
    features = list(features)
    stats = pooled_standardisation(control, historical, features)
    usable = list(stats["usable_features"])
    control_z = standardise(control, stats)
    historical_z = standardise(historical, stats)
    design = np.hstack([
        np.ones((len(control_z) + len(historical_z), 1)),
        np.vstack([control_z, historical_z]),
    ])
    outcome = np.array([0.0] * len(control_z) + [1.0] * len(historical_z))

    beta, iterations, converged = _irls_logistic(design, outcome)
    score = 1.0 / (1.0 + np.exp(-np.clip(design @ beta, -30.0, 30.0)))
    control_score = score[: len(control_z)]
    historical_score = score[len(control_z):]

    def in_region(values: np.ndarray) -> int:
        return int(((values >= PROPENSITY_LOW) & (values <= PROPENSITY_HIGH)).sum())

    rng = random.Random(seed)
    total = len(outcome)
    resampled: List[np.ndarray] = []
    for _draw in range(bootstrap):
        index = np.array([rng.randrange(total) for _ in range(total)])
        if len(set(outcome[index].tolist())) < 2:
            continue
        coefficients, _it, _ok = _irls_logistic(design[index], outcome[index])
        resampled.append(coefficients)
    stability: List[Dict[str, Any]] = []
    if resampled:
        stack = np.vstack(resampled)
        for position, name in enumerate(["intercept", *usable]):
            column = stack[:, position]
            stability.append({
                "term": name,
                "min": round(float(column.min()), 6),
                "median": round(float(np.median(column)), 6),
                "max": round(float(column.max()), 6),
                "sign_flips": bool((column > 0).any() and (column < 0).any()),
            })

    perfect = bool(control_score.max() < historical_score.min())
    unstable = [row["term"] for row in stability if row["sign_flips"]]
    return {
        "features": usable,
        "excluded_zero_variance": stats["dropped_zero_variance"],
        "ridge": IRLS_RIDGE,
        "iterations": IRLS_ITERATIONS,
        "converged": converged,
        "iterations_used": iterations,
        "coefficients": {
            "intercept": round(float(beta[0]), 6),
            **{name: round(float(value), 6) for name, value in zip(usable, beta[1:])},
        },
        "control_score": {
            "min": round(float(control_score.min()), 6),
            "median": round(float(np.median(control_score)), 6),
            "max": round(float(control_score.max()), 6),
            "in_overlap_region": in_region(control_score),
            "in_overlap_region_share": _share(in_region(control_score), len(control_score)),
        },
        "historical_score": {
            "min": round(float(historical_score.min()), 6),
            "median": round(float(np.median(historical_score)), 6),
            "max": round(float(historical_score.max()), 6),
            "in_overlap_region": in_region(historical_score),
            "in_overlap_region_share": _share(in_region(historical_score), len(historical_score)),
        },
        "overlap_region": [PROPENSITY_LOW, PROPENSITY_HIGH],
        "complete_separation": perfect,
        "bootstrap_refits": len(resampled),
        "coefficient_stability": stability,
        "unstable_terms": unstable,
        "stable_terms": [row["term"] for row in stability if not row["sign_flips"]],
        "assumptions": (
            "the score is a linear-logit function of the standardised matching features, fitted "
            "with a declared ridge of 1.0 on the pooled corpus. It assumes the features are "
            "measured without error, that the logit link is adequate, and that the two corpora are "
            "random samples of populations we want to compare. None of those is established here"
        ),
        "limitations": (
            "with 53 control traces against 12 historical ones and 21 candidate features the model "
            "is over-parameterised, and a ridge is a stabiliser rather than a fix. The bootstrap "
            "column is the honest summary of that: a term whose coefficient changes sign across "
            "resamples is not estimated, it is fitted to noise"
        ),
        "used_as_evidence_of_overlap": (
            "no. The score is reported as a diagnostic. It is used to say that a region exists or "
            "does not, and never on its own to conclude that the comparison is supported"
        ),
    }



def nearest_neighbour_support(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
) -> Dict[str, Any]:
    """Distance-based support, with the control corpus's own leave-one-out distances as the yardstick.

    This is the operational support test, because a distance threshold can be calibrated: the control
    corpus is asked how far its own members sit from each other, and a historical trace is called an
    extrapolation when it sits further out than the most extreme control member does. The
    decomposition of each distance into per-feature contributions is reported, because a distance
    dominated by one feature is a statement about that feature and not about the corpora as a whole.
    """
    features = list(features)
    stats = pooled_standardisation(control, historical, features)
    usable = list(stats["usable_features"])
    control_z = standardise(control, stats)
    historical_z = standardise(historical, stats)

    within = _distance_matrix(control_z, control_z)
    np.fill_diagonal(within, np.inf)
    control_nearest = within.min(axis=1)

    cross = _distance_matrix(historical_z, control_z)
    historical_nearest = cross.min(axis=1)
    nearest_index = cross.argmin(axis=1)

    control_sorted = sorted(float(value) for value in control_nearest)
    historical_sorted = sorted(float(value) for value in historical_nearest)

    def quantile(values: Sequence[float], q: float) -> float:
        if not values:
            return 0.0
        return values[min(len(values) - 1, int(q * len(values)))]

    thresholds = {
        "control_loo_max": control_sorted[-1],
        "control_loo_p95": quantile(control_sorted, 0.95),
        "control_loo_p90": quantile(control_sorted, 0.90),
        "control_loo_median": quantile(control_sorted, 0.50),
    }
    beyond = {
        name: sum(1 for value in historical_sorted if value > threshold)
        for name, threshold in thresholds.items()
    }
    per_trace: List[Dict[str, Any]] = []
    for index, record in enumerate(historical):
        gap = historical_z[index] - control_z[nearest_index[index]]
        contributions = sorted(
            (
                (round(float(value) ** 2, 6), name, round(float(value), 6))
                for name, value in zip(usable, gap)
            ),
            key=lambda item: (-item[0], item[1]),
        )
        total = sum(item[0] for item in contributions)
        per_trace.append({
            "slug": record.slug,
            "source_key": record.source_key,
            "nearest_control": control[nearest_index[index]].slug,
            "nearest_distance": round(float(historical_nearest[index]), 6),
            "beyond_control_loo_max": bool(historical_nearest[index] > thresholds["control_loo_max"]),
            "beyond_control_loo_p95": bool(historical_nearest[index] > thresholds["control_loo_p95"]),
            "top_contributors": [
                {
                    "feature": name,
                    "standardised_gap": value,
                    "squared_contribution": contribution,
                    "share_of_distance_squared": _share(
                        int(round(contribution * 1e6)), int(round(total * 1e6))
                    ),
                }
                for contribution, name, value in contributions[:5]
            ],
        })
    return {
        "features": usable,
        "control_loo": {
            "min": round(control_sorted[0], 6),
            "median": round(quantile(control_sorted, 0.50), 6),
            "p90": round(quantile(control_sorted, 0.90), 6),
            "p95": round(quantile(control_sorted, 0.95), 6),
            "max": round(control_sorted[-1], 6),
        },
        "historical_nearest": {
            "min": round(historical_sorted[0], 6),
            "median": round(quantile(historical_sorted, 0.50), 6),
            "p90": round(quantile(historical_sorted, 0.90), 6),
            "max": round(historical_sorted[-1], 6),
        },
        "thresholds": {name: round(value, 6) for name, value in thresholds.items()},
        "historical_beyond": beyond,
        "historical_traces": len(historical),
        "per_trace": per_trace,
        "reading": (
            "the control corpus's own leave-one-out distances say how far apart its members are. A "
            "historical trace beyond the control maximum is further from every control composition "
            "than any control composition is from another, so any prediction for it is an "
            "extrapolation rather than an interpolation"
        ),
    }


def multivariate_overlap(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
) -> Dict[str, Any]:
    """Three support criteria, each calibrated, and the support verdict they jointly imply.

    The brief asks for more than a comparison of means and standard deviations, and it asks for the
    multidimensional combinations to be checked. Three criteria are used because each has a different
    failure mode and agreement between them is the evidence:

    * **box** - the strictest. Calibrated leave-one-out inside the control corpus, so an empty
      historical result can be read against what the criterion does to the control's own members.
    * **nearest neighbour** - the operational one. Calibrated against the control's own distance
      distribution.
    * **propensity** - the conventional one. Reported with its own instability, and explicitly not
      treated as proof.

    The verdict rule is declared in the module constants before any of this runs.
    """
    box = box_support(control, historical, features)
    neighbours = nearest_neighbour_support(control, historical, features)
    propensity = propensity_analysis(control, historical, features)

    historical_inside_share = box["historical"]["inside_share"] or 0.0
    propensity_retained = propensity["historical_score"]["in_overlap_region_share"] or 0.0
    any_inside = box["historical"]["inside_on_every_feature"] > 0
    any_retained = propensity["historical_score"]["in_overlap_region"] > 0

    if (
        not box["historical"]["traces"] == 0
        and historical_inside_share >= SUPPORT_ADEQUATE_HISTORICAL_INSIDE
        and propensity_retained >= SUPPORT_ADEQUATE_PROPENSITY_RETAINED
    ):
        verdict = "COMMON_SUPPORT_ADEQUATE"
    elif any_inside and any_retained:
        verdict = "COMMON_SUPPORT_PARTIAL"
    else:
        verdict = "COMMON_SUPPORT_INADEQUATE"

    return {
        "features": list(features),
        "box": box,
        "nearest_neighbour": neighbours,
        "propensity": propensity,
        "criteria_agree": (
            (box["historical"]["inside_on_every_feature"] == 0)
            == (propensity["historical_score"]["in_overlap_region"] == 0)
        ),
        "verdict": verdict,
        "verdict_rule": (
            f"ADEQUATE when at least {SUPPORT_ADEQUATE_HISTORICAL_INSIDE:.0%} of historical traces "
            f"are inside the control box and the propensity overlap region retains at least "
            f"{SUPPORT_ADEQUATE_PROPENSITY_RETAINED:.0%} of them; PARTIAL when at least one "
            "historical trace satisfies each; INADEQUATE otherwise"
        ),
        "reading": (
            "the three criteria have different failure modes and the verdict is only read when they "
            "agree. The box criterion is the strictest and is calibrated against the control "
            "corpus's own members, the distance criterion is the operational one, and the propensity "
            "score is reported with its instability rather than as proof"
        ),
    }


# ===========================================================================
# PART 5 - the matching, re-derived (sections 7 and 8 of the brief)
# ===========================================================================
def _weighted_mean(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    total = sum(weight for _value, weight in pairs)
    if not total:
        return None
    return sum(value * weight for value, weight in pairs) / total


def effective_sample_size(weights: Sequence[float]) -> Optional[float]:
    """Kish's effective sample size: (sum w)^2 / sum w^2.

    A weighted comparison with 12 traces and wildly unequal weights does not carry 12 independent
    observations, and the effective size says how many it does carry. It is reported beside every
    weighted result rather than left implicit.
    """
    total = sum(weights)
    squares = sum(weight * weight for weight in weights)
    return None if not squares else round(total * total / squares, 6)


def bootstrap_difference(
    control_pairs: Sequence[Tuple[float, float]],
    historical_pairs: Sequence[Tuple[float, float, str]],
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = RANDOM_SEED,
) -> Dict[str, Any]:
    """A weighted difference in means whose interval resamples sources, never frames.

    ``control_pairs`` are (value, weight) and ``historical_pairs`` are (value, weight, cluster).
    The historical side is resampled by *cluster* - the SAP source - because two of the twelve
    traces share a file and the files cluster by composer. The control side is resampled by trace,
    because each control composition is its own document. This is Stage 23's resampling rule, kept
    rather than re-invented, and extended to carry weights.
    """
    if not control_pairs or not historical_pairs:
        return {"available": False, "reason": "one side of the comparison is empty"}
    observed = (
        _weighted_mean([(value, weight) for value, weight, _c in historical_pairs])
        - _weighted_mean(control_pairs)
    )
    if observed is None:
        return {"available": False, "reason": "the weights sum to zero on one side"}

    by_cluster: Dict[str, List[Tuple[float, float]]] = {}
    for value, weight, cluster in historical_pairs:
        by_cluster.setdefault(cluster, []).append((value, weight))
    clusters = sorted(by_cluster)
    rng = random.Random(seed)
    differences: List[float] = []
    for _draw in range(draws):
        picked: List[Tuple[float, float]] = []
        for _slot in range(len(clusters)):
            picked.extend(by_cluster[clusters[rng.randrange(len(clusters))]])
        resampled_control = [
            control_pairs[rng.randrange(len(control_pairs))] for _ in control_pairs
        ]
        hist_mean = _weighted_mean(picked)
        control_mean = _weighted_mean(resampled_control)
        if hist_mean is None or control_mean is None:
            continue
        differences.append(hist_mean - control_mean)
    if not differences:
        return {"available": False, "reason": "no usable bootstrap draw"}
    differences.sort()
    low = _quantile(differences, 0.025)
    high = _quantile(differences, 0.975)
    return {
        "available": True,
        "observed_difference": round(observed, 6),
        "ci_low": low,
        "ci_high": high,
        "ci_median": _median(differences),
        "draws": draws,
        "seed": seed,
        "cluster_unit": "historical SAP source; control composition",
        "historical_clusters": len(clusters),
        "historical_traces": len(historical_pairs),
        "control_traces": len(control_pairs),
        "excludes_zero": low is not None and high is not None and (low > 0 or high < 0),
        "historical_ess": effective_sample_size([w for _v, w, _c in historical_pairs]),
        "control_ess": effective_sample_size([w for _v, w in control_pairs]),
        "reading": (
            "the interval is a cluster bootstrap over sources, so it respects the dependence the "
            "traces carry. It is reported beside the effect size, never instead of it"
        ),
    }



def standardised_mean_differences(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
) -> Dict[str, Any]:
    """The balance table: per-feature standardised mean difference before and after matching.

    Balance is judged on the same pooled scale the matching used, so the numbers here and the
    distances used to match are on one scale. A feature with no pooled spread is reported as
    undefined rather than as perfectly balanced.
    """
    rows: List[Dict[str, Any]] = []
    values: List[float] = []
    for name in stats["usable_features"]:
        spread = stats["stdev"][name]
        cx = [float(record.features[name]) for record in control]
        hx = [float(record.features[name]) for record in historical]
        if not spread or not cx or not hx:
            rows.append({"feature": name, "smd": None, "balanced": None})
            continue
        smd = (sum(hx) / len(hx) - sum(cx) / len(cx)) / spread
        values.append(abs(smd))
        rows.append({
            "feature": name,
            "control_mean": _mean(cx),
            "historical_mean": _mean(hx),
            "smd": _rnd(smd),
            "absolute_smd": round(abs(smd), 6),
            "balanced": abs(smd) <= SMD_THRESHOLD,
        })
    balanced = [row for row in rows if row["balanced"] is not None]
    return {
        "features": rows,
        "threshold": SMD_THRESHOLD,
        "max_absolute_smd": round(max(values), 6) if values else None,
        "median_absolute_smd": _median(values),
        "balanced_features": sum(1 for row in balanced if row["balanced"]),
        "feature_count": len(balanced),
        "balanced": bool(balanced) and all(row["balanced"] for row in balanced),
        "reading": (
            f"a feature is balanced when |SMD| <= {SMD_THRESHOLD}. The threshold is declared before "
            "the matching runs, so balance cannot be declared by moving it afterwards"
        ),
    }


def _nearest_control_index(
    record: CorpusRecord,
    control: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
) -> List[Tuple[float, int]]:
    """Every control trace's distance to one historical trace, sorted by distance then slug.

    The slug is the tie-break, so the neighbour order cannot depend on dictionary iteration order
    or on the order the corpus happened to be loaded in.
    """
    target = standardise([record], stats)[0]
    matrix = standardise(control, stats)
    diff = matrix - target
    distances = np.sqrt((diff * diff).sum(axis=1))
    scored = sorted(
        ((float(distances[index]), control[index].slug, index) for index in range(len(control))),
        key=lambda item: (item[0], item[1]),
    )
    return [(distance, index) for distance, _slug, index in scored]


def match_nearest_neighbour(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
    caliper: float,
    neighbours: int,
) -> Dict[str, Any]:
    """1:k nearest-neighbour matching within a caliper, with replacement.

    Stage 23 declared a caliper constant and never applied it, so a historical trace could be
    matched to a control trace that was further away than any two control traces are from each
    other. Here the caliper is enforced, it is varied over a declared grid, and a historical trace
    that finds no partner inside the caliper is **rejected and listed** rather than quietly matched
    to its nearest neighbour anyway.
    """
    control_pairs: List[Tuple[float, float]] = []
    historical_pairs: List[Tuple[float, float, str]] = []
    matched: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for record in sorted(historical, key=lambda item: item.slug):
        scored = _nearest_control_index(record, control, stats)
        inside = [item for item in scored if item[0] <= caliper]
        if not inside:
            rejected.append({
                "slug": record.slug,
                "source_key": record.source_key,
                "reason": (
                    f"no control trace within the caliper of {caliper} standardised units; the "
                    f"nearest is {round(scored[0][0], 6)}"
                ),
                "nearest_distance": round(scored[0][0], 6),
                "nearest_control": control[scored[0][1]].slug,
            })
            continue
        chosen = inside[:neighbours]
        value = record.estimand
        if value is None:
            rejected.append({
                "slug": record.slug, "source_key": record.source_key,
                "reason": "the primary estimand is undefined for this trace",
            })
            continue
        historical_pairs.append((value, 1.0, record.source_key))
        weight = 1.0 / len(chosen)
        for distance, index in chosen:
            partner = control[index]
            partner_value = partner.estimand
            if partner_value is None:
                continue
            control_pairs.append((partner_value, weight))
        matched.append({
            "slug": record.slug,
            "source_key": record.source_key,
            "value": value,
            "partners": [control[index].slug for _distance, index in chosen],
            "partner_distances": [round(distance, 6) for distance, _index in chosen],
            "max_distance": round(chosen[-1][0], 6),
        })
    control_used = {
        index for item in matched for index in range(len(control))
        if control[index].slug in item["partners"]
    }
    return {
        "method": "nearest_neighbour",
        "caliper": caliper,
        "neighbours": neighbours,
        "historical_before": len(historical),
        "historical_kept": len(historical_pairs),
        "historical_rejected": len(rejected),
        "historical_sources_kept": len({cluster for _v, _w, cluster in historical_pairs}),
        "control_traces_used": len(control_used),
        "matched": matched,
        "rejected": rejected,
        "control_pairs": control_pairs,
        "historical_pairs": historical_pairs,
    }


def _propensity_scores(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
    propensity: Mapping[str, Any],
) -> Tuple[np.ndarray, np.ndarray]:
    usable = list(stats["usable_features"])
    control_z = standardise(control, stats)
    historical_z = standardise(historical, stats)
    design = np.hstack([
        np.ones((len(control_z) + len(historical_z), 1)),
        np.vstack([control_z, historical_z]),
    ])
    coefficients = np.array(
        [propensity["coefficients"][name] for name in ["intercept", *usable]]
    )
    score = 1.0 / (1.0 + np.exp(-np.clip(design @ coefficients, -30.0, 30.0)))
    return score[: len(control_z)], score[len(control_z):]


def match_stratified(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
    propensity: Mapping[str, Any],
    bins: int = 5,
) -> Dict[str, Any]:
    """Stratification on the propensity score, with strata taken from the control distribution.

    The strata are the control corpus's own propensity quantiles, so every stratum contains control
    traces by construction. A historical trace is kept only when it falls inside a stratum the
    control corpus actually occupies - that is a common-support restriction in propensity space. The
    boundaries come from the control corpus and are not tuned.
    """
    control_score, historical_score = _propensity_scores(
        control, historical, stats, propensity
    )
    edges = sorted(set(
        float(np.quantile(control_score, index / bins)) for index in range(1, bins)
    ))

    def stratum(value: float) -> int:
        return int(sum(1 for edge in edges if value > edge))

    occupied = {stratum(value) for value in control_score}
    ordered = sorted(historical, key=lambda item: item.slug)
    control_pairs: List[Tuple[float, float]] = []
    historical_pairs: List[Tuple[float, float, str]] = []
    matched: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for position, record in enumerate(ordered):
        value_score = float(historical_score[position])
        band = stratum(value_score)
        if band not in occupied:
            rejected.append({
                "slug": record.slug,
                "source_key": record.source_key,
                "propensity": round(value_score, 6),
                "reason": (
                    f"the propensity stratum {band} contains no control trace, so there is no "
                    "counterfactual to compare against"
                ),
            })
            continue
        value = record.estimand
        if value is None:
            rejected.append({
                "slug": record.slug, "source_key": record.source_key,
                "reason": "the primary estimand is undefined for this trace",
            })
            continue
        in_band = [
            position2 for position2 in range(len(control))
            if stratum(float(control_score[position2])) == band
        ]
        weight = 1.0 / max(1, len(in_band))
        for position2 in in_band:
            partner_value = control[position2].estimand
            if partner_value is not None:
                control_pairs.append((partner_value, weight))
        historical_pairs.append((value, 1.0, record.source_key))
        matched.append({
            "slug": record.slug, "source_key": record.source_key, "value": value,
            "stratum": band, "propensity": round(value_score, 6),
            "stratum_control_traces": len(in_band),
        })
    return {
        "method": "propensity_stratification",
        "strata": len(edges) + 1,
        "stratum_edges": [round(edge, 6) for edge in edges],
        "occupied_strata": sorted(occupied),
        "historical_before": len(historical),
        "historical_kept": len(historical_pairs),
        "historical_rejected": len(rejected),
        "historical_sources_kept": len({cluster for _v, _w, cluster in historical_pairs}),
        "matched": matched,
        "rejected": rejected,
        "control_pairs": control_pairs,
        "historical_pairs": historical_pairs,
    }


def restrict_to_support(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
    max_features_outside: int = 0,
) -> Dict[str, Any]:
    """Restrict the comparison to historical traces that sit inside the control box.

    A tolerance is offered as well as the exact test, because the exact test is the strictest
    available and a reader is entitled to see what a looser rule does. Every rejected trace is
    listed with the features that put it outside, so the restriction is auditable rather than a
    silent filter.
    """
    features = list(features)
    control_matrix = feature_matrix(control, features)
    historical_matrix = feature_matrix(historical, features)
    low = control_matrix.min(axis=0)
    high = control_matrix.max(axis=0)

    control_pairs: List[Tuple[float, float]] = []
    for record in control:
        value = record.estimand
        if value is not None:
            control_pairs.append((value, 1.0))
    historical_pairs: List[Tuple[float, float, str]] = []
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for index, record in enumerate(historical):
        outside = [
            name for position, name in enumerate(features)
            if historical_matrix[index][position] < low[position]
            or historical_matrix[index][position] > high[position]
        ]
        if len(outside) > max_features_outside:
            rejected.append({
                "slug": record.slug,
                "source_key": record.source_key,
                "features_outside": len(outside),
                "outside_features": sorted(outside),
                "reason": (
                    f"outside the control box on {len(outside)} features, above the tolerance of "
                    f"{max_features_outside}"
                ),
            })
            continue
        value = record.estimand
        if value is None:
            rejected.append({
                "slug": record.slug, "source_key": record.source_key,
                "reason": "the primary estimand is undefined for this trace",
            })
            continue
        historical_pairs.append((value, 1.0, record.source_key))
        kept.append({
            "slug": record.slug, "source_key": record.source_key, "value": value,
            "features_outside": len(outside),
        })
    return {
        "method": "support_restriction",
        "tolerance": max_features_outside,
        "historical_before": len(historical),
        "historical_kept": len(historical_pairs),
        "historical_rejected": len(rejected),
        "historical_sources_kept": len({cluster for _v, _w, cluster in historical_pairs}),
        "matched": kept,
        "rejected": rejected,
        "control_pairs": control_pairs,
        "historical_pairs": historical_pairs,
    }




# ===========================================================================
# PART 6 - uncertainty, effective sample size and sensitivity
# ===========================================================================
def difference_for_estimand(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    estimand: str = PRIMARY_ESTIMAND,
    draws: int = BOOTSTRAP_DRAWS,
) -> Dict[str, Any]:
    """The difference for any Stage 23 estimand, on whatever subset of records is passed in.

    The estimand is read from Stage 23's measurement, never re-derived here, so the convention
    sensitivity reported below is a sensitivity of the *comparison* and not of the residual.
    """
    control_pairs = [
        (record.evidence.estimands[estimand], 1.0)
        for record in control if record.evidence.estimands.get(estimand) is not None
    ]
    historical_pairs = [
        (record.evidence.estimands[estimand], 1.0, record.source_key)
        for record in historical if record.evidence.estimands.get(estimand) is not None
    ]
    result = bootstrap_difference(control_pairs, historical_pairs, draws=draws)
    result["estimand"] = estimand
    return result


def effective_sample_sizes(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    diagnostics: Mapping[str, Any],
) -> Dict[str, Any]:
    """The brief's per-method accounting: how much independent material each method actually has.

    Traces and frames are reported side by side on purpose, because the temptation this section
    exists to resist is to present the 2.1 million register values as if they were 2.1 million
    independent observations. They are 65 traces, 12 of them historical, drawn from 11 SAP sources
    written by three composers.
    """
    rows: List[Dict[str, Any]] = []
    for method in diagnostics["methods"]:
        difference = method["difference"]
        rows.append({
            "method": method["method"],
            "caliper": method["caliper"],
            "neighbours": method["neighbours"],
            "tolerance": method["tolerance"],
            "strata": method["strata"],
            "historical_traces_before": method["historical_before"],
            "historical_traces_kept": method["historical_kept"],
            "historical_traces_rejected": method["historical_rejected"],
            "historical_sources_kept": method["historical_sources_kept"],
            "control_traces_used": method["control_traces_used"],
            "historical_ess": difference.get("historical_ess"),
            "control_ess": difference.get("control_ess"),
            "difference": difference.get("observed_difference"),
            "ci_low": difference.get("ci_low"),
            "ci_high": difference.get("ci_high"),
            "excludes_zero": difference.get("excludes_zero"),
            "reportable": method["reportable"],
            "matching_validated": method["matching_validated"],
        })
    return {
        "unit_of_replication": (
            "the trace. Register values are never treated as independent observations: the corpus "
            "holds about 2.1 million register values, which are 65 traces, which are 11 historical "
            "SAP sources and 53 control documents. An interval resampled over frames would be "
            "narrower by orders of magnitude and would mean nothing"
        ),
        "historical_traces": len(historical),
        "historical_sources": len({record.source_key for record in historical}),
        "historical_authors": len({record.author for record in historical}),
        "control_traces": len(control),
        "historical_register_values": sum(
            record.evidence.register_values for record in historical
        ),
        "control_register_values": sum(record.evidence.register_values for record in control),
        "methods": rows,
        "power_statement": (
            "twelve historical traces from eleven files and three composers cannot support a "
            "matched comparison with a balance criterion. This is stated as a limitation of the "
            "data rather than worked around: the smallest p-value obtainable from a 12-versus-53 "
            "comparison is bounded by the number of distinct source-level arrangements, and any "
            "matched subset that satisfies the balance criterion would be smaller still"
        ),
        "reading": (
            "the effective sample size is Kish's, reported for the weighted methods. A method that "
            "keeps twelve traces with wildly unequal weights does not carry twelve observations"
        ),
    }


def _evaluate_method(
    method: Mapping[str, Any],
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    stats: Mapping[str, Any],
) -> Dict[str, Any]:
    """Score one matching method against the declared sample, balance and comparison criteria."""
    kept_slugs = {row["slug"] for row in method["matched"]}
    kept_historical = [row for row in historical if row.slug in kept_slugs]

    # The control side of the comparison is the set of traces the method actually used. For the
    # no-matching reference and the support restriction that is the whole corpus, which is correct:
    # neither method discards control material.
    used_slugs = {slug for row in method["matched"] for slug in (row.get("partners") or [])}
    control_side = (
        [record for record in control if record.slug in used_slugs]
        if used_slugs else list(control)
    )
    balance = standardised_mean_differences(control_side, kept_historical, stats)
    difference = bootstrap_difference(method["control_pairs"], method["historical_pairs"])

    enough_traces = method["historical_kept"] >= MIN_RETAINED_TRACES
    enough_sources = method["historical_sources_kept"] >= MIN_RETAINED_SOURCES
    reportable = bool(enough_traces and enough_sources and difference.get("available"))
    # A method that can produce a number is not the same as a method whose match is *validated*.
    # The brief is explicit that a match may not be presented as successful when it does not meet
    # the criteria declared before it ran, and balance is one of those criteria.
    validated = bool(reportable and balance["balanced"])
    return {
        "method": method["method"],
        "caliper": method.get("caliper"),
        "neighbours": method.get("neighbours"),
        "tolerance": method.get("tolerance"),
        "strata": method.get("strata"),
        "historical_before": method["historical_before"],
        "historical_kept": method["historical_kept"],
        "historical_rejected": method["historical_rejected"],
        "historical_sources_kept": method["historical_sources_kept"],
        "control_traces_used": method.get("control_traces_used"),
        "rejected_traces": method["rejected"],
        "kept_traces": [
            {
                "slug": row["slug"],
                "source_key": row["source_key"],
                "value": row.get("value"),
                "partners": row.get("partners"),
                "max_distance": row.get("max_distance"),
                "stratum": row.get("stratum"),
                "features_outside": row.get("features_outside"),
            }
            for row in method["matched"]
        ],
        "balance": balance,
        "difference": difference,
        "meets_minimum_sample": enough_traces and enough_sources,
        "meets_balance": balance["balanced"],
        "reportable": reportable,
        "matching_validated": validated,
        "not_validated_because": (
            None if validated else
            "; ".join(
                item for item in (
                    None if reportable else
                    "; ".join(
                        part for part in (
                            None if enough_traces else
                            f"only {method['historical_kept']} historical traces retained, below "
                            f"the declared minimum of {MIN_RETAINED_TRACES}",
                            None if enough_sources else
                            f"only {method['historical_sources_kept']} independent historical "
                            f"sources retained, below the declared minimum of "
                            f"{MIN_RETAINED_SOURCES}",
                            None if difference.get("available") else
                            f"the difference is undefined ({difference.get('reason')})",
                        ) if part
                    ),
                    None if balance["balanced"] else
                    f"the match is not balanced: the largest absolute standardised mean difference "
                    f"after matching is {balance['max_absolute_smd']}, above the declared threshold "
                    f"of {SMD_THRESHOLD}",
                ) if item
            )
        ),
    }



def matching_diagnostics(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    features: Sequence[str] = MATCHING_FEATURES,
) -> Dict[str, Any]:
    """Every declared matching method, evaluated against every declared criterion.

    Nothing is selected because it produces a nicer number. The grid is declared in the module
    constants, every cell of it is reported including the empty ones, and a method that cannot
    retain a usable sample is reported as *not reportable* with the reason rather than as a
    comparison with a wide interval.
    """
    features = list(features)
    stats = pooled_standardisation(control, historical, features)
    box = box_support(control, historical, features)
    propensity = propensity_analysis(control, historical, features)

    methods: List[Dict[str, Any]] = []

    # M0 - no matching at all. The reference point, and what Stage 23's headline actually is.
    control_pairs = [
        (record.estimand, 1.0) for record in control if record.estimand is not None
    ]
    historical_pairs = [
        (record.estimand, 1.0, record.source_key)
        for record in historical if record.estimand is not None
    ]
    unmatched = {
        "method": "no_matching",
        "historical_before": len(historical),
        "historical_kept": len(historical_pairs),
        "historical_rejected": 0,
        "historical_sources_kept": len({cluster for _v, _w, cluster in historical_pairs}),
        "matched": [
            {"slug": record.slug, "source_key": record.source_key, "value": record.estimand}
            for record in sorted(historical, key=lambda item: item.slug)
        ],
        "rejected": [],
        "control_pairs": control_pairs,
        "historical_pairs": historical_pairs,
    }
    methods.append(_evaluate_method(unmatched, control, historical, stats))

    # M1/M2 - nearest neighbour over the declared caliper and neighbour grid.
    for caliper in CALIPERS:
        for neighbours in NEIGHBOUR_COUNTS:
            candidate = match_nearest_neighbour(
                control, historical, stats, caliper, neighbours
            )
            methods.append(_evaluate_method(candidate, control, historical, stats))

    # M3 - stratification on the propensity score.
    stratified = match_stratified(control, historical, stats, propensity)
    methods.append(_evaluate_method(stratified, control, historical, stats))

    # M4 - restriction to the control box, at the declared tolerances.
    for tolerance in (0, 2, 3, 5):
        candidate = restrict_to_support(control, historical, features, tolerance)
        methods.append(_evaluate_method(candidate, control, historical, stats))

    reportable = [row for row in methods if row["reportable"]]
    validated = [row for row in methods if row["matching_validated"]]
    return {
        "features": features,
        "standardisation": stats,
        "box": box,
        "propensity": propensity,
        "methods": methods,
        "method_count": len(methods),
        "reportable_methods": [
            {
                "method": row["method"], "caliper": row["caliper"],
                "neighbours": row["neighbours"], "tolerance": row["tolerance"],
                "strata": row["strata"],
                "historical_kept": row["historical_kept"],
                "historical_sources_kept": row["historical_sources_kept"],
                "difference": row["difference"].get("observed_difference"),
            }
            for row in reportable
        ],
        "reportable_count": len(reportable),
        "validated_methods": [
            {
                "method": row["method"], "caliper": row["caliper"],
                "neighbours": row["neighbours"], "tolerance": row["tolerance"],
                "strata": row["strata"],
                "historical_kept": row["historical_kept"],
                "historical_sources_kept": row["historical_sources_kept"],
                "difference": row["difference"].get("observed_difference"),
                "max_absolute_smd": row["balance"]["max_absolute_smd"],
            }
            for row in validated
        ],
        "validated_count": len(validated),
        "matching_validated": len(validated) > 0,
        "stage23_defect": (
            "Stage 23 declared CALIPER = 1.0 and never applied it: the neighbour function takes no "
            "caliper argument and the constant reached only the artefact. Every historical trace "
            "was therefore matched to its nearest control trace however far away that was, which is "
            "exactly the extrapolation the caliper was declared to prevent. The balance of the "
            "Stage 23 match was never checked either. Both are fixed here, and the effect of the fix "
            "is visible: with the caliper applied most of the grid retains nothing"
        ),
        "reading": (
            "a method is reportable only when it retains the declared minimum sample and produces a "
            "defined difference. Balance is reported beside every method and is never used to "
            "select one"
        ),
    }


#: The caliper grid is widened for the sensitivity axis only. The primary grid in ``CALIPERS`` is
#: the declared one; this one exists to show the trend and is not used to select a result.
CALIPER_SENSITIVITY: Tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)


def feature_set_sensitivity(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
) -> List[Dict[str, Any]]:
    """The support verdict under several declared feature sets.

    If the verdict depends on which features are in the set, the verdict is a property of the
    analyst's choice rather than of the corpora, and the brief's rule is that the choice must be
    reported rather than hidden. The sets are declared here, before the numbers are read.
    """
    sets: Dict[str, List[str]] = {
        "stage24_all": list(MATCHING_FEATURES),
        "stage23_matching": list(stage23.MATCH_FEATURES),
        "without_length": [name for name in MATCHING_FEATURES if name != "frames"],
        "without_configuration": [
            name for name in MATCHING_FEATURES
            if name not in ("clock_179mhz", "coupled_16bit")
        ],
        "density_only": [
            name for name in MATCHING_FEATURES
            if name.endswith("_rate") or name.endswith("_share")
        ],
    }
    rows: List[Dict[str, Any]] = []
    for label in sorted(sets):
        subset = sets[label]
        try:
            overlay = multivariate_overlap(control, historical, subset)
        except Stage24Error as error:
            rows.append({
                "feature_set": label, "features": len(subset),
                "support_verdict": "not_measurable", "error": str(error),
            })
            continue
        rows.append({
            "feature_set": label,
            "features": len(subset),
            "support_verdict": overlay["verdict"],
            "historical_inside_box": overlay["box"]["historical"]["inside_on_every_feature"],
            "propensity_retained": (
                overlay["propensity"]["historical_score"]["in_overlap_region"]
            ),
            "nearest_min": overlay["nearest_neighbour"]["historical_nearest"]["min"],
            "control_loo_max": overlay["nearest_neighbour"]["thresholds"]["control_loo_max"],
        })
    return rows


def _leave_one_out_rows(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Leave one historical song out, and leave one control composition out."""
    historical_rows: List[Dict[str, Any]] = []
    for record in sorted(historical, key=lambda item: item.slug):
        kept = [row for row in historical if row.slug != record.slug]
        result = difference_for_estimand(control, kept)
        historical_rows.append({
            "dropped": record.slug,
            "dropped_source": record.source_key,
            "kept_traces": len(kept),
            "difference": result.get("observed_difference"),
            "sign": (
                None if not result.get("available") else
                ("positive" if result["observed_difference"] > 0 else "negative")
            ),
        })
    control_rows: List[Dict[str, Any]] = []
    for record in sorted(control, key=lambda item: item.slug):
        kept = [row for row in control if row.slug != record.slug]
        result = difference_for_estimand(kept, historical)
        control_rows.append({
            "dropped": record.slug,
            "kept_traces": len(kept),
            "difference": result.get("observed_difference"),
            "sign": (
                None if not result.get("available") else
                ("positive" if result["observed_difference"] > 0 else "negative")
            ),
        })
    return historical_rows, control_rows


def _channel_rows(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
) -> List[Dict[str, Any]]:
    """The per-channel difference, on the same per-register denominators Stage 23 declared."""
    rows: List[Dict[str, Any]] = []
    for name in stage23.AUDF_COLUMNS:
        numerator_c = sum(record.evidence.per_register_in_span.get(name, 0) for record in control)
        denominator_c = sum(
            record.evidence.per_register_in_span_total.get(name, 0) for record in control
        )
        numerator_h = sum(
            record.evidence.per_register_in_span.get(name, 0) for record in historical
        )
        denominator_h = sum(
            record.evidence.per_register_in_span_total.get(name, 0) for record in historical
        )
        rate_c = _share(numerator_c, denominator_c)
        rate_h = _share(numerator_h, denominator_h)
        rows.append({
            "register": name,
            "control_rate": rate_c,
            "historical_rate": rate_h,
            "difference": (
                None if rate_c is None or rate_h is None else round(rate_h - rate_c, 6)
            ),
            "control_denominator": denominator_c,
            "historical_denominator": denominator_h,
        })
    return rows


def sensitivity_analysis(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    diagnostics: Mapping[str, Any],
) -> Dict[str, Any]:
    """Every declared sensitivity axis, run on the same comparison.

    The axes are the ones the brief names: leaving one historical song out, leaving one control
    composition out, the matching parameters, the residual convention, the feature set, the channel,
    the common-support restriction, and weighted against unweighted. A result that disappears on any
    of them is classified unstable, by a rule stated here rather than by reading the numbers first.
    """
    full = difference_for_estimand(control, historical)
    historical_rows, control_rows = _leave_one_out_rows(control, historical)

    parameter_rows: List[Dict[str, Any]] = []
    stats = pooled_standardisation(control, historical)
    for caliper in CALIPER_SENSITIVITY:
        for neighbours in NEIGHBOUR_COUNTS:
            candidate = match_nearest_neighbour(
                control, historical, stats, caliper, neighbours
            )
            difference = bootstrap_difference(
                candidate["control_pairs"], candidate["historical_pairs"]
            )
            parameter_rows.append({
                "caliper": caliper,
                "neighbours": neighbours,
                "historical_kept": candidate["historical_kept"],
                "historical_sources_kept": candidate["historical_sources_kept"],
                "difference": difference.get("observed_difference"),
            })

    convention_rows = []
    for estimand in stage23.ESTIMAND_NAMES:
        result = difference_for_estimand(control, historical, estimand)
        convention_rows.append({
            "estimand": estimand,
            "difference": result.get("observed_difference"),
            "ci_low": result.get("ci_low"),
            "ci_high": result.get("ci_high"),
            "defined_in_control": result.get("control_traces"),
            "defined_in_historical": result.get("historical_traces"),
        })

    support_only = [
        row for row in diagnostics["methods"]
        if row["method"] == "support_restriction" and row["reportable"]
    ]
    weighted_rows = [
        {
            "method": row["method"], "caliper": row["caliper"], "tolerance": row["tolerance"],
            "difference": row["difference"].get("observed_difference"),
            "historical_ess": row["difference"].get("historical_ess"),
            "weighted": row["method"] != "no_matching",
        }
        for row in diagnostics["methods"] if row["reportable"]
    ]

    signs = {row["sign"] for row in historical_rows + control_rows if row["sign"] is not None}
    magnitudes = [
        row["difference"] for row in historical_rows + control_rows
        if row["difference"] is not None
    ]
    stable = len(signs) == 1 and bool(magnitudes) and min(magnitudes) > EFFECT_THRESHOLD
    return {
        "unstable_rule": (
            "a result is UNSTABLE when the sign of the difference changes on any axis, or when the "
            f"difference falls below the declared effect threshold of {EFFECT_THRESHOLD} on any axis"
        ),
        "full_corpus_difference": full.get("observed_difference"),
        "full_corpus_ci": [full.get("ci_low"), full.get("ci_high")],
        "leave_one_historical_song_out": {
            "rows": historical_rows,
            "signs": sorted(signs),
            "sign_stable": len(signs) == 1,
            "min_difference": min(magnitudes) if magnitudes else None,
            "max_difference": max(magnitudes) if magnitudes else None,
        },
        "leave_one_control_source_out": {
            "rows": control_rows,
            "signs": sorted({
                row["sign"] for row in control_rows if row["sign"] is not None
            }),
            "sign_stable": len({
                row["sign"] for row in control_rows if row["sign"] is not None
            }) == 1,
        },
        "matching_parameters": {
            "grid": {
                "calipers": list(CALIPER_SENSITIVITY),
                "neighbours": list(NEIGHBOUR_COUNTS),
            },
            "rows": parameter_rows,
            "settings_retaining_anything": sum(
                1 for row in parameter_rows if row["historical_kept"] > 0
            ),
            "settings_retaining_the_minimum": sum(
                1 for row in parameter_rows
                if row["historical_kept"] >= MIN_RETAINED_TRACES
                and row["historical_sources_kept"] >= MIN_RETAINED_SOURCES
            ),
        },
        "residual_convention": {
            "rows": convention_rows,
            "signs": sorted({
                "positive" if row["difference"] > 0 else "negative"
                for row in convention_rows if row["difference"] is not None
            }),
        },
        "feature_set": {"rows": feature_set_sensitivity(control, historical)},
        "channel": {"rows": _channel_rows(control, historical)},
        "common_support_only": {
            "rows": support_only,
            "note": (
                "only the declared tolerances that retain the minimum sample appear here. The "
                "tighter tolerances retain too little and are reported as undefined rather than as "
                "estimates"
            ),
        },
        "weighted_against_unweighted": {"rows": weighted_rows},
        "classification": (
            "STABLE_ON_THE_RAW_COMPARISON_BUT_UNIDENTIFIED" if stable else "UNSTABLE"
        ),
        "classification_scope": (
            "the stability classification applies to the raw and support-restricted comparisons, "
            "which are the only ones that exist. It does NOT extend to a matched estimate, because "
            "no matching method satisfied the declared balance criterion and there is therefore no "
            "matched estimate to test"
        ),
    }


# ===========================================================================
# PART 7 - the falsification test (section 11 of the brief)
# ===========================================================================
#: The conditions under which the "history-specific effect" reading is rejected. Declared here,
#: before the comparison is run, and never amended afterwards.
FALSIFICATION_CRITERIA: Tuple[Dict[str, str], ...] = (
    {
        "criterion": "a common feature range exists that supports a matched comparison",
        "threshold": (
            "no matching feature is separated, at least one historical trace lies inside the control "
            "box, and the propensity overlap region retains at least one historical trace"
        ),
        "rejects": "the history-specific reading, because there is no comparable population",
    },
    {
        "criterion": "the effect survives in the common-support region",
        "threshold": (
            "at least one declared method retains the minimum sample AND satisfies the declared "
            "balance criterion"
        ),
        "rejects": "the history-specific reading, because no matched estimate can be formed",
    },
    {
        "criterion": "the effect does not depend on a few traces",
        "threshold": (
            "the sign of the raw difference is unchanged when each historical trace and each control "
            "composition is dropped in turn"
        ),
        "rejects": "the history-specific reading, because the difference is one song's",
    },
    {
        "criterion": "the effect does not depend on the matching parameters",
        "threshold": "the sign is unchanged across the declared caliper and neighbour grid",
        "rejects": "the history-specific reading, because it is a parameter choice",
    },
    {
        "criterion": "the difference is consistent with the observed effect of corpus composition",
        "threshold": (
            "the features that separate the corpora are trace-length and POKEY-configuration "
            "features rather than musical ones"
        ),
        "rejects": (
            "the history-specific reading, because the difference tracks a corpus-construction "
            "variable that has nothing to do with performance"
        ),
    },
    {
        "criterion": "the effect can be separated from unobserved differences in trace generation",
        "threshold": (
            "the residual measured on the historical corpus is not attributable to a difference in "
            "how the trace was produced - a digitised player against a compiled document"
        ),
        "rejects": "the history-specific reading, because the generation process is confounded",
    },
)


def falsification_test(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    overlap: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    univariate: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate the six pre-declared falsification conditions and report each one's measurement.

    The criteria were fixed before the numbers were read. The sixth is the one that cannot be
    discharged at all: the two corpora differ in how their traces were *produced*, and no statistic
    computed from the traces can undo that. It is reported as failing, because it does.
    """
    box = overlap["box"]
    propensity = overlap["propensity"]
    validated = [row for row in diagnostics["methods"] if row["matching_validated"]]

    support_ok = bool(
        box["historical"]["inside_on_every_feature"] > 0
        and propensity["historical_score"]["in_overlap_region"] > 0
    )
    loo = sensitivity["leave_one_historical_song_out"]
    control_loo = sensitivity["leave_one_control_source_out"]
    grid = sensitivity["matching_parameters"]

    rows = [
        {
            "criterion": FALSIFICATION_CRITERIA[0]["criterion"],
            "threshold": FALSIFICATION_CRITERIA[0]["threshold"],
            "passed": support_ok,
            "measurement": {
                "historical_inside_box": box["historical"]["inside_on_every_feature"],
                "historical_in_propensity_region": (
                    propensity["historical_score"]["in_overlap_region"]
                ),
                "historical_traces": box["historical"]["traces"],
                "separated_features": univariate["separated_features"],
            },
            "reading": FALSIFICATION_CRITERIA[0]["rejects"],
        },
        {
            "criterion": FALSIFICATION_CRITERIA[1]["criterion"],
            "threshold": FALSIFICATION_CRITERIA[1]["threshold"],
            "passed": bool(validated),
            "measurement": {
                "validated_methods": len(validated),
                "reportable_methods": diagnostics["reportable_count"],
                "nearest_neighbour_settings_retaining_anything": sum(
                    1 for row in diagnostics["methods"]
                    if row["method"] == "nearest_neighbour" and row["historical_kept"] > 0
                ),
            },
            "reading": FALSIFICATION_CRITERIA[1]["rejects"],
        },
        {
            "criterion": FALSIFICATION_CRITERIA[2]["criterion"],
            "threshold": FALSIFICATION_CRITERIA[2]["threshold"],
            "passed": bool(loo["sign_stable"] and control_loo["sign_stable"]),
            "measurement": {
                "historical_signs": loo["signs"],
                "control_signs": control_loo["signs"],
                "min_difference": loo["min_difference"],
                "max_difference": loo["max_difference"],
            },
            "reading": FALSIFICATION_CRITERIA[2]["rejects"],
        },
        {
            "criterion": FALSIFICATION_CRITERIA[3]["criterion"],
            "threshold": FALSIFICATION_CRITERIA[3]["threshold"],
            "passed": bool(grid["settings_retaining_the_minimum"] > 0),
            "measurement": {
                "settings": len(grid["rows"]),
                "settings_retaining_anything": grid["settings_retaining_anything"],
                "settings_retaining_the_minimum": grid["settings_retaining_the_minimum"],
            },
            "reading": FALSIFICATION_CRITERIA[3]["rejects"],
        },
        {
            "criterion": FALSIFICATION_CRITERIA[4]["criterion"],
            "threshold": FALSIFICATION_CRITERIA[4]["threshold"],
            "passed": not overlap["criteria_agree"] or not support_ok,
            "measurement": {
                "separated_features": univariate["separated_features"],
                "poorly_covered_features": univariate["poorly_covered_features"],
                "box_agrees_with_propensity": overlap["criteria_agree"],
            },
            "reading": FALSIFICATION_CRITERIA[4]["rejects"],
        },
        {
            "criterion": FALSIFICATION_CRITERIA[5]["criterion"],
            "threshold": FALSIFICATION_CRITERIA[5]["threshold"],
            "passed": False,
            "measurement": {
                "control_trace_origin": "compiled deterministically from an authored document",
                "historical_trace_origin": "digitised from a running third-party player",
                "control_players": 1,
                "historical_players": "unknown; at least three composer clusters",
                "identifiable_from_traces_alone": False,
            },
            "reading": FALSIFICATION_CRITERIA[5]["rejects"],
        },
    ]
    passed = sum(1 for row in rows if row["passed"])
    rejected = [row["criterion"] for row in rows if not row["passed"]]
    return {
        "criteria": rows,
        "passed": passed,
        "total": len(rows),
        "all_passed": passed == len(rows),
        "rejected_criteria": rejected,
        "history_specific_reading_rejected": bool(rejected),
        "conclusion": (
            f"the history-specific reading is REJECTED by {len(rejected)} of the {len(rows)} "
            "pre-declared conditions. A difference that cannot be located in a comparable "
            "population, cannot be matched, and is confounded with the process that produced the "
            "traces is not evidence of a performance layer, whatever its size"
            if rejected else
            "the history-specific reading survives every pre-declared condition"
        ),
        "declared_before_results": True,
    }


# ===========================================================================
# PART 8 - descriptive, matched and identified (section 9 of the brief)
# ===========================================================================
def identifiability_assessment(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    overlap: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    falsification: Mapping[str, Any],
) -> Dict[str, Any]:
    """The three questions the brief insists are kept apart, answered separately.

    A: is there a descriptive difference? B: does it survive in a comparable subset? C: can the data
    attribute it to a cause? Answering A and calling it C is the failure this stage exists to
    prevent, so the three are reported as three separate objects with three separate answers.
    """
    no_matching = next(
        row for row in diagnostics["methods"] if row["method"] == "no_matching"
    )
    validated = [row for row in diagnostics["methods"] if row["matching_validated"]]
    supported = [
        row for row in diagnostics["methods"]
        if row["method"] == "support_restriction" and row["reportable"]
    ]
    best_support = (
        max(supported, key=lambda row: row["historical_kept"]) if supported else None
    )
    return {
        "A_descriptive_difference": {
            "question": "do the historical traces carry a larger residual than the control traces?",
            "answer": "yes",
            "measurement": {
                "estimand": PRIMARY_ESTIMAND,
                "control_mean": _mean([
                    record.estimand for record in control if record.estimand is not None
                ]),
                "historical_mean": _mean([
                    record.estimand for record in historical if record.estimand is not None
                ]),
                "difference": no_matching["difference"].get("observed_difference"),
                "ci_low": no_matching["difference"].get("ci_low"),
                "ci_high": no_matching["difference"].get("ci_high"),
                "historical_traces": len(historical),
                "control_traces": len(control),
            },
            "what_it_does_not_say": (
                "it says nothing about the cause. The historical corpus is 12 traces of a game tune "
                "and the control corpus is 53 short test compositions, so the descriptive difference "
                "compares two different kinds of object before it compares two different eras"
            ),
        },
        "B_difference_after_matching": {
            "question": "does the difference persist in a comparable subset?",
            "answer": "the question cannot be answered: no comparable subset could be formed",
            "measurement": {
                "validated_matching_methods": len(validated),
                "reportable_matching_methods": diagnostics["reportable_count"],
                "nearest_neighbour_settings_retaining_anything": sum(
                    1 for row in diagnostics["methods"]
                    if row["method"] == "nearest_neighbour" and row["historical_kept"] > 0
                ),
                "loosest_declared_support_restriction": (
                    None if best_support is None else {
                        "tolerance": best_support["tolerance"],
                        "historical_kept": best_support["historical_kept"],
                        "historical_sources_kept": best_support["historical_sources_kept"],
                        "difference": best_support["difference"].get("observed_difference"),
                        "max_absolute_smd": best_support["balance"]["max_absolute_smd"],
                        "balanced": best_support["balance"]["balanced"],
                    }
                ),
            },
            "what_it_does_not_say": (
                "a method that produces a number is not a method whose match is valid. The loosest "
                "declared support restriction keeps eight historical traces, but it keeps them by "
                "allowing a trace to sit outside the control box on five of twenty-one features, and "
                "the resulting match still fails the declared balance criterion. That is not a "
                "comparable subset; it is the unmatched comparison with four traces removed"
            ),
        },
        "C_identified_cause": {
            "question": "can the data attribute the difference to a specific cause?",
            "answer": "no",
            "blockers": [
                {
                    "blocker": "no common support",
                    "evidence": (
                        f"{overlap['box']['historical']['inside_on_every_feature']} of "
                        f"{overlap['box']['historical']['traces']} historical traces lie inside the "
                        "control corpus's feature box, against "
                        f"{overlap['box']['calibration_inside_control']['inside_on_every_feature']} "
                        "of the control corpus's own members under the same leave-one-out test"
                    ),
                },
                {
                    "blocker": "no matched estimate exists",
                    "evidence": (
                        f"{diagnostics['reportable_count']} of {diagnostics['method_count']} "
                        "declared methods can produce a difference and "
                        f"{len(validated)} satisfy the declared balance criterion"
                    ),
                },
                {
                    "blocker": "the trace generation process is confounded with the corpus",
                    "evidence": (
                        "the control traces are compiled from an authored document by the project's "
                        "own compiler and the historical traces are digitised from a third-party "
                        "player. Nothing in the traces distinguishes a player's behaviour from a "
                        "composer's, and no control exists in which one player is run over both "
                        "corpora"
                    ),
                },
                {
                    "blocker": "no ground truth on the historical side",
                    "evidence": (
                        "every historical SAP is Tier D. The classes that would say where the "
                        "residual comes from need a composition, and there is none. This is a limit "
                        "of the data that no amount of statistics removes"
                    ),
                },
            ],
            "what_it_does_not_say": (
                "it does not say the difference is an artefact. It says the difference is not "
                "identified: the data cannot tell a historical-specific effect from a difference in "
                "trace length, POKEY configuration, player routine or musical density"
            ),
        },
        "summary": (
            "A is yes, B is unanswerable, C is no. The three are not the same statement and this "
            "stage does not merge them"
        ),
    }


# ===========================================================================
# PART 9 - the minimal next experiment (section 12 of the brief)
# ===========================================================================
def next_experiment_design(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    overlap: Mapping[str, Any],
) -> Dict[str, Any]:
    """What would have to be added to make the comparison identifiable, and what it would cost.

    The design is stated and **not executed**. No music is generated, no profile is bound and no
    composition is authored. The stage's job is to say what is missing, not to fill the gap, because
    filling it changes the corpus and that is a production decision.
    """
    historical_audctl: Dict[str, int] = {}
    for record in historical:
        key = f"${record.audctl:02X}"
        historical_audctl[key] = historical_audctl.get(key, 0) + 1
    control_audctl: Dict[str, int] = {}
    for record in control:
        key = f"${record.audctl:02X}"
        control_audctl[key] = control_audctl.get(key, 0) + 1
    control_frames = sorted(record.frames for record in control)
    historical_frames = sorted(record.frames for record in historical)

    return {
        "identified_gaps": [
            {
                "gap": "the POKEY clock configuration",
                "measurement": (
                    f"{historical_audctl.get('$50', 0)} of {len(historical)} historical traces run "
                    "AUDCTL $50 (16-bit pair at 1.79 MHz); the control corpus uses "
                    f"{sorted(control_audctl)} and contains no 1.79 MHz composition at all"
                ),
                "closes_it": (
                    "author control compositions whose instruments bind a profile declaring "
                    "audctl_mode '$50'. The IR already supports this: resolve_audctl_mode OR-s an "
                    "instrument's explicit audctl requirement with the song's 16-bit flag, and "
                    "binding.py maps a 16-bit pair on channels 1+2 to exactly 0x50. No production "
                    "change is required - only documents and a profile that no existing composition "
                    "happens to use"
                ),
                "testable": True,
            },
            {
                "gap": "trace length",
                "measurement": (
                    f"control frames range [{control_frames[0]}, {control_frames[-1]}] with a median "
                    f"of {_median([float(value) for value in control_frames])}; historical frames "
                    f"range [{historical_frames[0]}, {historical_frames[-1]}] with a median of "
                    f"{_median([float(value) for value in historical_frames])}"
                ),
                "closes_it": (
                    "author control compositions at the historical lengths, which is a document "
                    "change and nothing more. This is the cheapest of the gaps and it also removes "
                    "the length artefact from every count-valued feature"
                ),
                "testable": True,
            },
            {
                "gap": "the player routine",
                "measurement": (
                    "the historical traces come from at least three composer clusters and an unknown "
                    "number of player routines; the control corpus has exactly one"
                ),
                "closes_it": (
                    "this one cannot be closed with more compositions. It needs the same musical "
                    "material rendered through more than one player, or a historical SAP whose player "
                    "is identified and re-run over authored material. Until then a difference in "
                    "residual cannot be separated from a difference in player"
                ),
                "testable": False,
            },
            {
                "gap": "ground truth on the historical side",
                "measurement": "zero of the 12 historical traces have an independent note source",
                "closes_it": (
                    "a hand transcription of a historical tune, which is what would move it from "
                    "Tier D to Tier A. This is labour rather than code, and it is the only thing that "
                    "would let the detector's errors be separated from a player's choices"
                ),
                "testable": False,
            },
        ],
        "minimal_experiment": {
            "name": "a length-matched, $50-clocked, author-controlled Tier A corpus",
            "what_it_is": (
                "a second control corpus authored inside this project, whose compositions match the "
                "historical corpus on the features that separate the corpora and on nothing else"
            ),
            "must_control": [
                "AUDCTL configuration, including the 1.79 MHz clock and the 16-bit pair",
                "trace length, matched to the historical range and distribution",
                "AUDF change density, including the between-note zero pulse if it is to be matched",
                "register change co-occurrence and the number of simultaneously audible voices",
                "the distortion families in use, since the detector's transition recall depends on them",
            ],
            "must_not_vary": [
                "the compiler, the player, the DSL and the frame period - one pipeline for every "
                "control composition, so the generation process is held constant",
            ],
            "minimum_size": (
                "at least 12 compositions with the $50 configuration and at least 12 at the "
                "historical length distribution, from at least 3 distinct authored sources, so that a "
                "matched subset can retain the declared minimum of 4 traces and 3 sources after a "
                "caliper is applied"
            ),
            "ground_truth_requirement": (
                "Tier A is already satisfied: an authored document is its own ground truth. No "
                "transcription is needed for the control side. The historical side stays Tier D "
                "unless someone transcribes, and that limitation is not removed by this experiment"
            ),
            "what_would_falsify_the_hypothesis": [
                "the difference vanishes once configuration and length are matched - the difference "
                "was corpus construction",
                "the difference persists and the matched balance criterion is met - then it is worth a "
                "controlled listening test, and it is still not a performance layer",
                "the difference persists only for the zero-pulse player idiom - it is a player trait, "
                "which is a finding about players rather than about historical performance",
            ],
            "what_would_allow_a_design_decision": (
                "a matched difference whose interval excludes zero AND whose balance criterion is met "
                "AND which survives leave-one-source-out. Anything less is a research result and "
                "changes no production decision"
            ),
            "cost_and_risk": (
                "authoring the documents is cheap and uses existing tooling. The risk is that the "
                "author of the new corpus is also the author of the comparison, so the corpus would "
                "have to be authored and hashed before this stage is re-run, exactly as the existing "
                "control corpus was"
            ),
        },
        "not_done_here": (
            "the corpus is not created, no profile is bound, no composition is authored and no music "
            "is generated. Stage 24 proposes and stops"
        ),
        "configurability_note": (
            "the 1.79 MHz configuration is reachable through the existing profile binding path (a "
            "profile's hardware.audctl_mode is parsed and OR-ed in by resolve_audctl_mode), but no "
            "composition in the repository uses it, so the path is unexercised. Any new corpus would "
            "be its first use and should be validated against a trace whose AUDCTL column is checked "
            "directly"
        ),
    }


# ===========================================================================
# PART 10 - the verdicts (section 16 of the brief)
# ===========================================================================
VERDICT_VOCABULARY: Tuple[str, ...] = (
    "COMMON_SUPPORT_ADEQUATE",
    "COMMON_SUPPORT_PARTIAL",
    "COMMON_SUPPORT_INADEQUATE",
    "MATCHING_METHOD_NOT_VALIDATED",
    "HISTORICAL_DIFFERENCE_DISAPPEARS_AFTER_MATCHING",
    "HISTORICAL_DIFFERENCE_ROBUST_BUT_UNIDENTIFIED",
    "IDENTIFIABILITY_INCONCLUSIVE",
)

#: Auxiliary verdicts. The brief allows a secondary verdict when one is needed, and this stage needs
#: several: one for what the matching did and one for the project decision. ``PROVEN PERFORMANCE
#: LAYER`` is deliberately absent, and the test suite asserts it absent.
AUXILIARY_VERDICTS: Tuple[str, ...] = (
    "MATCHING_RETAINS_NO_USABLE_SAMPLE",
    "MATCHING_UNBALANCED",
    "HISTORICAL_DIFFERENCE_STABLE_BUT_NOT_IDENTIFIED",
    "NEW_CONTROL_CORPUS_REQUIRED",
    "NO_PRODUCTION_DECISION_CHANGED",
    "PERFORMANCE_LAYER_NOT_SUPPORTED_AND_NOT_TESTABLE_HERE",
)


def _matching_verdicts(
    diagnostics: Mapping[str, Any],
    overlap: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """The auxiliary verdicts about the matching itself."""
    validated = [row for row in diagnostics["methods"] if row["matching_validated"]]
    reportable = [row for row in diagnostics["methods"] if row["reportable"]]
    nn_settings = [
        row for row in diagnostics["methods"] if row["method"] == "nearest_neighbour"
    ]
    nn_retaining = sum(1 for row in nn_settings if row["historical_kept"] > 0)
    out: List[Dict[str, Any]] = []
    if not validated and nn_retaining == 0:
        out.append({
            "verdict": "MATCHING_RETAINS_NO_USABLE_SAMPLE",
            "reason": (
                "every declared nearest-neighbour caliper retains no historical trace at all, "
                "because the smallest historical-to-control standardised distance exceeds the "
                "loosest declared caliper"
            ),
            "measurement": {
                "nearest_neighbour_settings": len(nn_settings),
                "settings_retaining_anything": nn_retaining,
                "historical_nearest_min": (
                    overlap["nearest_neighbour"]["historical_nearest"]["min"]
                ),
                "control_loo_max": (
                    overlap["nearest_neighbour"]["thresholds"]["control_loo_max"]
                ),
                "loosest_declared_caliper": max(CALIPERS),
            },
        })
    elif not validated:
        out.append({
            "verdict": "MATCHING_UNBALANCED",
            "reason": (
                f"{len(reportable)} methods produce a difference and none satisfies the declared "
                f"balance criterion of |SMD| <= {SMD_THRESHOLD}"
            ),
            "measurement": {
                "reportable": len(reportable),
                "validated": len(validated),
                "max_absolute_smd_by_method": {
                    f"{row['method']}:caliper={row['caliper']}:tolerance={row['tolerance']}": (
                        row["balance"]["max_absolute_smd"]
                    )
                    for row in reportable
                },
            },
        })
    return out


def verdicts(
    control: Sequence[CorpusRecord],
    historical: Sequence[CorpusRecord],
    overlap: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    falsification: Mapping[str, Any],
    identifiability: Mapping[str, Any],
) -> Dict[str, Any]:
    """The main verdict and the auxiliary ones, each with the measurement that decided it.

    The main verdict is chosen by the declared rule, not by preference. When the support is
    inadequate the brief's STOP condition fixes the answer, and it is not overridden by the fact that
    the difference is large and stable - that is exactly the confusion this stage exists to prevent.
    """
    support_verdict = overlap["verdict"]
    validated = [row for row in diagnostics["methods"] if row["matching_validated"]]
    reportable = [row for row in diagnostics["methods"] if row["reportable"]]

    if support_verdict == "COMMON_SUPPORT_INADEQUATE":
        main = "COMMON_SUPPORT_INADEQUATE"
    elif support_verdict == "COMMON_SUPPORT_PARTIAL":
        main = "COMMON_SUPPORT_PARTIAL"
    elif not validated:
        main = "MATCHING_METHOD_NOT_VALIDATED"
    elif all(
        row["difference"].get("observed_difference") is not None
        and abs(row["difference"]["observed_difference"]) < EFFECT_THRESHOLD
        for row in validated
    ):
        main = "HISTORICAL_DIFFERENCE_DISAPPEARS_AFTER_MATCHING"
    else:
        main = "HISTORICAL_DIFFERENCE_ROBUST_BUT_UNIDENTIFIED"

    auxiliary = _matching_verdicts(diagnostics, overlap)
    if sensitivity["classification"] == "STABLE_ON_THE_RAW_COMPARISON_BUT_UNIDENTIFIED":
        auxiliary.append({
            "verdict": "HISTORICAL_DIFFERENCE_STABLE_BUT_NOT_IDENTIFIED",
            "reason": (
                "the raw difference keeps its sign under every leave-one-out axis and under every "
                "residual definition, and it is still not identified because no comparable "
                "population exists"
            ),
            "measurement": {
                "difference": sensitivity["full_corpus_difference"],
                "ci": sensitivity["full_corpus_ci"],
                "leave_one_out_signs": sensitivity["leave_one_historical_song_out"]["signs"],
                "convention_signs": sensitivity["residual_convention"]["signs"],
            },
        })
    if support_verdict == "COMMON_SUPPORT_INADEQUATE":
        auxiliary.append({
            "verdict": "NEW_CONTROL_CORPUS_REQUIRED",
            "reason": (
                "the comparison cannot be identified with the corpora that exist, so the next step "
                "is a corpus and not an analysis"
            ),
            "measurement": {
                "historical_inside_control_box": (
                    overlap["box"]["historical"]["inside_on_every_feature"]
                ),
                "historical_in_propensity_region": (
                    overlap["propensity"]["historical_score"]["in_overlap_region"]
                ),
            },
        })
    auxiliary.append({
        "verdict": "PERFORMANCE_LAYER_NOT_SUPPORTED_AND_NOT_TESTABLE_HERE",
        "reason": (
            "this stage neither supports a performance layer nor is able to test one. The difference "
            "it measures is confounded with trace length, POKEY configuration and the trace "
            "generation process, and no matched estimate could be formed"
        ),
        "measurement": {
            "falsification_conditions_rejected": falsification["rejected_criteria"],
            "identified_cause": identifiability["C_identified_cause"]["answer"],
        },
    })
    auxiliary.append({
        "verdict": "NO_PRODUCTION_DECISION_CHANGED",
        "reason": (
            "Stage 24 changes no detector, compiler, player, exporter or schema, produces no music "
            "and makes no change to the composer. Its output is a statement about what the existing "
            "data can support"
        ),
        "measurement": {"read_only": True, "stage_25_started": False},
    })

    return {
        "main": {
            "verdict": main,
            "deciding_measurement": {
                "support_verdict": support_verdict,
                "historical_inside_control_box": (
                    overlap["box"]["historical"]["inside_on_every_feature"]
                ),
                "control_inside_control_box_leave_one_out": (
                    overlap["box"]["calibration_inside_control"]["inside_on_every_feature"]
                ),
                "historical_traces": overlap["box"]["historical"]["traces"],
                "historical_in_propensity_region": (
                    overlap["propensity"]["historical_score"]["in_overlap_region"]
                ),
                "complete_separation": overlap["propensity"]["complete_separation"],
                "reportable_methods": len(reportable),
                "validated_methods": len(validated),
                "unstable_propensity_terms": len(overlap["propensity"]["unstable_terms"]),
                "propensity_terms": len(overlap["propensity"]["coefficient_stability"]),
            },
            "what_it_means": (
                "the corpora do not share enough feature space for a matched comparison, so the "
                "residual difference cannot be attributed to a historical-specific effect. The "
                "difference is not denied - it is measured, it is stable, and it is not identified"
            ),
            "what_it_does_not_mean": (
                "it does not mean the difference is an artefact, and it does not mean the detector "
                "is wrong. It means the current data cannot separate the two"
            ),
        },
        "auxiliary": auxiliary,
        "vocabulary": list(VERDICT_VOCABULARY),
        "auxiliary_vocabulary": list(AUXILIARY_VERDICTS),
        "proven_performance_layer_used": False,
    }


# ===========================================================================
# PART 11 - read-only audit, the run, the artefacts (sections 13 and 14)
# ===========================================================================
#: Everything Stage 24 reads and must not write. Stage 15 to 23 are included, so a change to any
#: earlier stage during a Stage 24 run would be caught rather than assumed impossible.
PRODUCTION_FILES: Tuple[str, ...] = (
    "src/atari_music/constants.py",
    "src/atari_music/ir.py",
    "src/atari_music/pokey_hw.py",
    "src/atari_music/mads_exporter.py",
    "src/atari_music/cli.py",
    "src/atari_music/composer_v4.py",
    "src/atari_music/stage15.py",
    "src/atari_music/stage16.py",
    "src/atari_music/stage17.py",
    "src/atari_music/stage18.py",
    "src/atari_music/stage19.py",
    "src/atari_music/stage20.py",
    "src/atari_music/stage21.py",
    "src/atari_music/stage22.py",
    "src/atari_music/stage23.py",
    "src/atari_music/asm/player.asm",
    "tests/data/sound_profiles/vaults_of_nhyrmeth.dsl",
)

STAGE24_FILES: Tuple[str, ...] = (
    "corpus_inventory.json",
    "feature_definitions.json",
    "univariate_overlap.json",
    "multivariate_overlap.json",
    "matching_diagnostics.json",
    "matched_comparison.json",
    "effective_sample_sizes.json",
    "sensitivity_analysis.json",
    "leave_one_source_out.json",
    "identifiability_assessment.json",
    "next_experiment_design.json",
    "verdict.json",
    "stage24_manifest.json",
)
STAGE24_DOC = "stage24_corpus_overlap_and_confounding.md"
STAGE24_REPORT = "stage24_report.md"


def production_hashes(root: Path = REPO_ROOT) -> Dict[str, Optional[str]]:
    """The hash of every production artefact this stage reads, taken before and after a run."""
    out: Dict[str, Optional[str]] = {}
    for relative in PRODUCTION_FILES:
        path = Path(root) / relative
        out[relative] = sha256_file(path) if path.is_file() else None
    return out


def input_hashes(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    upstream_dirs: Sequence[Path] = (
        DEFAULT_STAGE21_DIR, DEFAULT_STAGE22_DIR, DEFAULT_STAGE23_DIR,
    ),
) -> Dict[str, Optional[str]]:
    """The hash of every input the stage reads: traces, compositions and upstream artefacts."""
    out: Dict[str, Optional[str]] = {}
    for path in sorted(stage15.list_traces(Path(arch_root))):
        out[f"trace/{path.name}"] = sha256_file(path)
    for slug, _kind, path in stage21.control_sources(
        songs_dir, ai_dir, DEFAULT_EXTRA_DSL_DIR
    ):
        out[f"composition/{slug}"] = sha256_file(path)
    for directory in upstream_dirs:
        for path in sorted(Path(directory).glob("*.json")):
            out[f"upstream/{Path(directory).name}/{path.name}"] = sha256_file(path)
    return out


def read_only_audit(
    before: Mapping[str, Optional[str]],
    after: Mapping[str, Optional[str]],
    label: str = "read-only inputs",
) -> Dict[str, Any]:
    """Compare two hash maps and report every difference. An empty diff is the claim."""
    keys = sorted(set(before) | set(after))
    changed = [key for key in keys if before.get(key) != after.get(key)]
    return {
        "label": label,
        "files_checked": len(keys),
        "changed": changed,
        "unchanged": len(keys) - len(changed),
        "read_only": not changed,
    }


def audit_sources(stage23_dir: Path = DEFAULT_STAGE23_DIR) -> Dict[str, Any]:
    """Read the Stage 23 artefacts and record what they actually declare.

    The brief's rule is that the artefacts win over any summary, including this one. So the audit
    reads the JSON, quotes the numbers it finds, and records what Stage 24 relies on and what it
    treats as a hypothesis.
    """
    manifest = _read_json(stage23_dir / "stage23_manifest.json")
    verdict = _read_json(stage23_dir / "verdict.json")
    conventions = _read_json(stage23_dir / "residual_conventions.json")
    matching = _read_json(stage23_dir / "matching_diagnostics.json")
    comparison = _read_json(stage23_dir / "corpus_comparison.json")
    summary = manifest["summary"]
    return {
        "stage23_analysis_version": manifest["analysis_version"],
        "stage23_summary": summary,
        "stage23_verdict": verdict,
        "stage23_matching_diagnostics": matching,
        "stage23_residual_conventions": conventions,
        "stage23_overlap": comparison["overlap"],
        "stage23_declared_caliper": conventions.get("caliper"),
        "stage23_caliper_applied": False,
        "stage23_artefacts": sorted(path.name for path in Path(stage23_dir).glob("*.json")),
        "relied_on": (
            "the residual definition, the estimands, the per-register in-span denominators, the "
            "trace features and the two conventions. All of them are reused through the Stage 23 "
            "functions themselves, never re-implemented, so the two stages cannot drift apart."
        ),
        "not_relied_on": (
            "Stage 23's matched comparison and its matching method. The method is re-derived here, "
            "its declared caliper is applied for the first time, and its balance is checked for the "
            "first time. Stage 23's support verdict is treated as a hypothesis to test rather than "
            "as a finding."
        ),
        "discrepancies_found": [
            {
                "claim": (
                    "Stage 23 declares CALIPER = 1.0 standardised units and writes it into the "
                    "artefacts"
                ),
                "measured": (
                    "the caliper is never read: stage23.nearest_control_neighbours takes no caliper "
                    "argument, so every historical trace was matched to its nearest control trace "
                    "however far away that was"
                ),
                "consequence": (
                    "Stage 23's matched gap is the gap between a historical trace and its nearest "
                    "control neighbour at whatever distance, which is an extrapolation rather than a "
                    "match. Stage 24 applies the caliper and reports the consequence: the grid "
                    "retains nothing"
                ),
            },
            {
                "claim": (
                    "Stage 23 reports distinct_audf_values, audctl_change_rate and clock_179mhz as "
                    "features with 'no common range at all'"
                ),
                "measured": (
                    "audctl_change_rate is identically zero in all 65 traces of both corpora, so it "
                    "is a shared constant and not a separation at all. distinct_audf_values is a "
                    "count that grows with trace length, and its length-normalised form overlaps. "
                    "clock_179mhz is a shared point at zero with 11 of 12 historical traces outside"
                ),
                "consequence": (
                    "Stage 23's multivariate overlap reads worse than the data supports. Stage 24 "
                    "separates 'degenerate' from 'separated' and normalises the length-confounded "
                    "count; the support verdict is then still inadequate, but for stated reasons "
                    "rather than for a measurement artefact"
                ),
            },
            {
                "claim": "Stage 23 reports a control leave-one-out distance maximum as a support threshold",
                "measured": (
                    "the maximum over 53 controls is the most extreme control's distance, so it is a "
                    "permissive threshold; the p90 and p95 are also reported here"
                ),
                "consequence": (
                    "Stage 24 reports three thresholds and the count beyond each, so the support "
                    "conclusion does not rest on the choice of one"
                ),
            },
        ],
    }


def _counts(values: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


def _distribution(values: Sequence[int]) -> Dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    return {
        "n": len(ordered),
        "min": ordered[0] if ordered else None,
        "p25": _quantile(ordered, 0.25),
        "median": _median(ordered),
        "p75": _quantile(ordered, 0.75),
        "max": ordered[-1] if ordered else None,
        "sum": int(sum(ordered)),
    }


def analyse_corpora(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
) -> Dict[str, Any]:
    """The deterministic core: measure both corpora, then run every overlap and matching analysis."""
    historical = load_historical_records(arch_root)
    control = load_control_records(songs_dir, ai_dir)
    if not historical or not control:
        raise Stage24Error("one of the corpora is empty; the comparison needs both")
    univariate = univariate_overlap(control, historical)
    overlap = multivariate_overlap(control, historical)
    overlap["univariate_separated"] = univariate["separated_features"]
    overlap["univariate_poorly_covered"] = univariate["poorly_covered_features"]
    diagnostics = matching_diagnostics(control, historical)
    samples = effective_sample_sizes(control, historical, diagnostics)
    sensitivity = sensitivity_analysis(control, historical, diagnostics)
    falsification = falsification_test(
        control, historical, overlap, diagnostics, sensitivity, univariate
    )
    identifiability = identifiability_assessment(
        control, historical, overlap, diagnostics, sensitivity, falsification
    )
    design = next_experiment_design(control, historical, overlap)
    decided = verdicts(
        control, historical, overlap, diagnostics, sensitivity, falsification, identifiability
    )
    return {
        "historical": [record.to_dict() for record in historical],
        "control": [record.to_dict() for record in control],
        "inventory": {
            "historical": {
                "traces": len(historical),
                "sources": len({record.source_key for record in historical}),
                "authors": sorted({record.author for record in historical}),
                "audctl": _counts(f"${record.audctl:02X}" for record in historical),
                "kinds": _counts(record.kind for record in historical),
                "sap_types": _counts(record.sap_type for record in historical),
                "frames": _distribution([record.frames for record in historical]),
                "channels": _counts(str(record.channels) for record in historical),
            },
            "control": {
                "traces": len(control),
                "sources": len({record.source_key for record in control}),
                "authors": sorted({record.author for record in control}),
                "audctl": _counts(f"${record.audctl:02X}" for record in control),
                "kinds": _counts(record.kind for record in control),
                "sap_types": _counts(record.sap_type for record in control),
                "frames": _distribution([record.frames for record in control]),
                "channels": _counts(str(record.channels) for record in control),
            },
            "comparability_notes": [dict(item) for item in COMPARABILITY_NOTES],
        },
        "feature_definitions": [dict(item) for item in FEATURE_DEFINITIONS],
        "matching_features": list(MATCHING_FEATURES),
        "excluded_features": [
            {"feature": name, "role": role} for name, role in EXCLUDED_FEATURES
        ],
        "univariate_overlap": univariate,
        "multivariate_overlap": overlap,
        "matching_diagnostics": diagnostics,
        "effective_sample_sizes": samples,
        "sensitivity": sensitivity,
        "falsification": falsification,
        "identifiability": identifiability,
        "next_experiment": design,
        "verdicts": decided,
    }


def run_analysis(
    arch_root: Path = DEFAULT_ARCHAEOLOGY_DIR,
    songs_dir: Path = DEFAULT_SONGS_DIR,
    ai_dir: Path = DEFAULT_AI_DIR,
    stage23_dir: Path = DEFAULT_STAGE23_DIR,
    verify_reproducibility: bool = True,
) -> Dict[str, Any]:
    """Everything Stage 24 measures, in one deterministic pass, with a reproducibility check.

    The analysis is run twice and the two payload digests compared. A stage whose whole claim is
    about the stability of a comparison has to be able to show that its own arithmetic is stable.
    """
    production_before = production_hashes()
    inputs_before = input_hashes(arch_root, songs_dir, ai_dir)
    core = analyse_corpora(arch_root, songs_dir, ai_dir)
    reproducible = True
    digest = _digest(core)
    if verify_reproducibility:
        again = _digest(analyse_corpora(arch_root, songs_dir, ai_dir))
        reproducible = again == digest
        if not reproducible:
            raise Stage24Error(
                "the analysis is not reproducible: two runs produced different payloads"
            )
    audit = audit_sources(stage23_dir)
    bundle: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "audit": audit,
        "core": core,
        "reproducibility": {
            "verified": verify_reproducibility,
            "byte_identical": reproducible,
            "payload_digest": digest,
            "note": (
                "the deterministic core is run twice and the two payload digests compared; a "
                "mismatch raises rather than reporting"
            ),
        },
        "read_only_audit": {
            "production": read_only_audit(
                production_before, production_hashes(),
                "production modules, the player source and the profile DSL",
            ),
            "inputs": read_only_audit(
                inputs_before, input_hashes(arch_root, songs_dir, ai_dir),
                "traces, composition documents and upstream artefacts",
            ),
        },
        "determinism": {
            "random_seed": RANDOM_SEED,
            "bootstrap_draws": BOOTSTRAP_DRAWS,
            "propensity_bootstrap": PROPENSITY_BOOTSTRAP,
            "tie_breaks": (
                "nearest-neighbour ties break on the slug; leave-one-out iterates traces in slug "
                "order; the bootstrap uses a seeded Random; every dict that reaches an artefact is "
                "emitted with sorted keys; the propensity fit uses a fixed ridge, a fixed iteration "
                "cap and a fixed tolerance; and every declared list is sorted before use"
            ),
            "source_hash": sha256_file(Path(__file__)),
        },
    }
    bundle["summary"] = _summary(bundle)
    return bundle


def _summary(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The one-screen summary the report, the CLI and the tests all read from."""
    core = bundle["core"]
    overlap = core["multivariate_overlap"]
    diagnostics = core["matching_diagnostics"]
    sensitivity = core["sensitivity"]
    decided = core["verdicts"]
    samples = core["effective_sample_sizes"]
    inventory = core["inventory"]
    univariate = core["univariate_overlap"]
    return {
        "historical_traces": inventory["historical"]["traces"],
        "historical_sources": inventory["historical"]["sources"],
        "historical_authors": len(inventory["historical"]["authors"]),
        "control_traces": inventory["control"]["traces"],
        "matching_features": len(core["matching_features"]),
        "excluded_features": len(core["excluded_features"]),
        "features_separated": univariate["separated_features"],
        "features_degenerate": univariate["degenerate_features"],
        "features_poorly_covered": univariate["poorly_covered_features"],
        "support_verdict": overlap["verdict"],
        "historical_inside_control_box": (
            overlap["box"]["historical"]["inside_on_every_feature"]
        ),
        "control_inside_control_box_leave_one_out": (
            overlap["box"]["calibration_inside_control"]["inside_on_every_feature"]
        ),
        "historical_in_propensity_region": (
            overlap["propensity"]["historical_score"]["in_overlap_region"]
        ),
        "propensity_complete_separation": overlap["propensity"]["complete_separation"],
        "propensity_unstable_terms": len(overlap["propensity"]["unstable_terms"]),
        "propensity_terms": len(overlap["propensity"]["coefficient_stability"]),
        "historical_nearest_min": overlap["nearest_neighbour"]["historical_nearest"]["min"],
        "control_loo_max": overlap["nearest_neighbour"]["thresholds"]["control_loo_max"],
        "historical_beyond_control_loo_max": (
            overlap["nearest_neighbour"]["historical_beyond"]["control_loo_max"]
        ),
        "methods": diagnostics["method_count"],
        "reportable_methods": diagnostics["reportable_count"],
        "validated_methods": diagnostics["validated_count"],
        "raw_difference": sensitivity["full_corpus_difference"],
        "raw_ci": sensitivity["full_corpus_ci"],
        "stability": sensitivity["classification"],
        "leave_one_out_sign_stable": (
            sensitivity["leave_one_historical_song_out"]["sign_stable"]
        ),
        "convention_signs": sensitivity["residual_convention"]["signs"],
        "falsification_passed": core["falsification"]["passed"],
        "falsification_total": core["falsification"]["total"],
        "falsification_rejected": core["falsification"]["rejected_criteria"],
        "descriptive_answer": core["identifiability"]["A_descriptive_difference"]["answer"],
        "matched_answer": core["identifiability"]["B_difference_after_matching"]["answer"],
        "identified_answer": core["identifiability"]["C_identified_cause"]["answer"],
        "verdict": decided["main"]["verdict"],
        "auxiliary_verdicts": [row["verdict"] for row in decided["auxiliary"]],
        "historical_register_values": samples["historical_register_values"],
        "control_register_values": samples["control_register_values"],
        "reproducible": bundle["reproducibility"]["byte_identical"],
        "read_only": all(row["read_only"] for row in bundle["read_only_audit"].values()),
        "read_only_files_checked": sum(
            row["files_checked"] for row in bundle["read_only_audit"].values()
        ),
    }


# ===========================================================================
# PART 12 - the artefacts and the writer (section 14 of the brief)
# ===========================================================================
def _artefacts(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    """The thirteen JSON payloads, built in one place so the writer stays a writer."""
    core = bundle["core"]
    audit = bundle["audit"]
    diagnostics = core["matching_diagnostics"]
    return {
        "corpus_inventory.json": {
            "historical": core["historical"],
            "control": core["control"],
            "inventory": core["inventory"],
            "comparability_notes": [dict(item) for item in COMPARABILITY_NOTES],
            "provenance_classes": {
                "known": PROVENANCE_KNOWN,
                "derived_from_trace": PROVENANCE_DERIVED,
                "unknown": PROVENANCE_UNKNOWN,
                "not_comparable": PROVENANCE_NOT_COMPARABLE,
            },
            "rule": (
                "no composition feature is assigned to a historical SAP. A SAP is a player plus "
                "data; the note set, the instruments and the tempo are not recoverable from the "
                "trace and are recorded as unknown rather than inferred"
            ),
        },
        "feature_definitions.json": {
            "definitions": core["feature_definitions"],
            "matching_features": core["matching_features"],
            "excluded_features": core["excluded_features"],
            "residual_used_as_a_feature": False,
            "rule": (
                "a feature is admitted only when it is measurable identically in both corpora, and "
                "a feature is excluded only for a stated reason: degenerate in both corpora, or "
                "confounded with trace length and superseded by a normalised variant"
            ),
        },
        "univariate_overlap.json": core["univariate_overlap"],
        "multivariate_overlap.json": core["multivariate_overlap"],
        "matching_diagnostics.json": diagnostics,
        "matched_comparison.json": {
            "declared_criteria": {
                "smd_threshold": SMD_THRESHOLD,
                "min_retained_traces": MIN_RETAINED_TRACES,
                "min_retained_sources": MIN_RETAINED_SOURCES,
                "calipers": list(CALIPERS),
                "neighbour_counts": list(NEIGHBOUR_COUNTS),
                "support_tolerances": [0, 2, 3, 5],
                "propensity_overlap_region": [PROPENSITY_LOW, PROPENSITY_HIGH],
            },
            "methods": diagnostics["methods"],
            "reportable": [row for row in diagnostics["methods"] if row["reportable"]],
            "validated": [row for row in diagnostics["methods"] if row["matching_validated"]],
            "rejected_traces_by_method": {
                f"{row['method']}:caliper={row['caliper']}:neighbours={row['neighbours']}"
                f":tolerance={row['tolerance']}:strata={row['strata']}": row["rejected_traces"]
                for row in diagnostics["methods"]
            },
            "stage23_defect": diagnostics["stage23_defect"],
        },
        "effective_sample_sizes.json": core["effective_sample_sizes"],
        "sensitivity_analysis.json": core["sensitivity"],
        "leave_one_source_out.json": {
            "historical": core["sensitivity"]["leave_one_historical_song_out"],
            "control": core["sensitivity"]["leave_one_control_source_out"],
            "resampling_unit": (
                "the historical corpus is clustered by SAP source and the control corpus by "
                "composition. Both are reported separately because they are different kinds of "
                "leave-one-out"
            ),
        },
        "identifiability_assessment.json": {
            **core["identifiability"],
            "falsification": core["falsification"],
            "falsification_criteria": [dict(item) for item in FALSIFICATION_CRITERIA],
        },
        "next_experiment_design.json": core["next_experiment"],
        "verdict.json": {
            "main": core["verdicts"]["main"],
            "auxiliary": core["verdicts"]["auxiliary"],
            "vocabulary": core["verdicts"]["vocabulary"],
            "auxiliary_vocabulary": core["verdicts"]["auxiliary_vocabulary"],
            "proven_performance_layer_used": False,
            "stop_condition_applied": (
                "the common support is inadequate, so the stage ends with "
                "COMMON_SUPPORT_INADEQUATE and proposes a new control corpus. Stage 25 is not "
                "started and production is not touched"
            ),
        },
        "stage24_manifest.json": {
            "analysis_version": ANALYSIS_VERSION,
            "document": STAGE24_DOC,
            "artefacts": list(STAGE24_FILES),
            "summary": bundle["summary"],
            "determinism": bundle["determinism"],
            "reproducibility": bundle["reproducibility"],
            "read_only_audit": bundle["read_only_audit"],
            "stage23_audit": audit,
            "stop_condition": (
                "Stage 24 is analysis-only, read-only and additive. No production code is modified, "
                "no music is generated, no corpus is created, no player or detector is changed, and "
                "Stage 25 is not started"
            ),
        },
    }


def write_analysis(
    bundle: Mapping[str, Any],
    stage24_dir: Path = DEFAULT_STAGE24_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> Dict[str, Path]:
    """Write the thirteen JSON artefacts and the report. Additive: nothing else is touched."""
    stage24_dir = Path(stage24_dir)
    docs_dir = Path(docs_dir)
    stage24_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = _artefacts(bundle)
    written: Dict[str, Path] = {}
    for name in STAGE24_FILES:
        if name not in payload:
            raise Stage24Error(f"the artefact {name} was never built")
        path = stage24_dir / name
        path.write_text(
            json.dumps(payload[name], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    report = render_report(bundle)
    doc_path = docs_dir / STAGE24_DOC
    doc_path.write_text(report, encoding="utf-8")
    written[STAGE24_DOC] = doc_path
    report_path = stage24_dir / STAGE24_REPORT
    report_path.write_text(report, encoding="utf-8")
    written[STAGE24_REPORT] = report_path
    return written





# ===========================================================================
# PART 13 - the report (section 15 of the brief)
# ===========================================================================
def _pct(value: Optional[float], places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def _num(value: Optional[float], places: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{places}f}"


def _range(low: Optional[float], high: Optional[float]) -> str:
    """A closed interval, or ``none`` when it is empty because the corpora do not overlap."""
    if low is None or high is None:
        return "n/a"
    if low > high:
        return "none (empty)"
    return f"[{_num(low)}, {_num(high)}]"


def _sentence(text: str) -> str:
    """Capitalise the first letter and end with a full stop, so fragments read as sentences."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith("."):
        text += "."
    return text


def render_report(bundle: Mapping[str, Any]) -> str:
    """The fourteen sections the brief requires, in its order, then the eight closing questions."""
    s = bundle["summary"]
    out: List[str] = [
        "# Stage 24 - Corpus Overlap and Confounding Analysis\n",
        "Stage 23 measured a residual difference between the historical SAP corpus and the Tier A "
        "control corpus, found it robust, and ended with "
        "`HISTORICAL_DIFFERENCE_ROBUST_BUT_NOT_IDENTIFIED` because the matching criterion failed. "
        "Stage 24 does not re-measure the residual. It asks one question: **is that comparison "
        "identifiable at all with the data that exists?**\n",
        f"**The headline.** {s['historical_traces']} historical traces from "
        f"{s['historical_sources']} SAP files and {s['historical_authors']} composers, against "
        f"{s['control_traces']} control compositions. **{s['historical_inside_control_box']} of "
        f"{s['historical_traces']}** historical traces lie inside the control corpus's feature box, "
        "against "
        f"**{s['control_inside_control_box_leave_one_out']} of {s['control_traces']}** control "
        "traces under the same leave-one-out test - so the criterion can pass traces, and it passes "
        "none of the historical ones. The propensity score separates the corpora completely "
        f"({s['historical_in_propensity_region']} historical traces in the overlap region, "
        f"{s['propensity_unstable_terms']} of {s['propensity_terms']} coefficients changing sign "
        "across bootstrap resamples), and the nearest historical trace is "
        f"{_num(s['historical_nearest_min'])} standardised units from the control corpus against a "
        f"control leave-one-out maximum of {_num(s['control_loo_max'])}.\n",
        f"**No matching method is validated.** {s['methods']} declared methods were run; "
        f"{s['reportable_methods']} can produce a difference and **{s['validated_methods']}** "
        "satisfies the balance criterion declared before they ran. Every nearest-neighbour caliper "
        "retains zero historical traces.\n",
        f"**Verdict: `{s['verdict']}`.** The difference itself is unchanged from Stage 23 - "
        f"{_pct(s['raw_difference'])} with an interval of "
        f"[{_pct(s['raw_ci'][0])}, {_pct(s['raw_ci'][1])}] - and it is still stable. What Stage 24 "
        "adds is that it cannot be located in any comparable population, so it cannot be attributed "
        "to a cause. That is a limitation of the data, named as one.\n",
        "Analysis only, read-only and additive. No music was generated, no corpus was created, no "
        "profile was bound, no player or detector was changed and no production schema was touched. "
        f"Analysis version `{bundle['analysis_version']}`.\n",
        "Artefacts: " + ", ".join(f"`{name}`" for name in STAGE24_FILES) + ".\n",
    ]
    for section in (_s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9, _s10,
                    _s11, _s12, _s13, _s14, _s_questions):
        out.extend(section(bundle))
    return "\n".join(out)





def _s1(bundle: Mapping[str, Any]) -> List[str]:
    s = bundle["summary"]
    core = bundle["core"]
    return [
        "## 1. Executive Summary\n",
        _table(
            ["question", "answer"],
            [
                ["Do the corpora share enough feature space for a matched comparison?",
                 f"**No.** {s['historical_inside_control_box']} of {s['historical_traces']} "
                 f"historical traces are inside the control box; {s['features_separated'] or 'no'} "
                 "feature is strictly separated, but the joint box is empty"],
                ["Was the Stage 23 matching methodologically sound?",
                 "**No.** Its declared caliper was never applied and its balance was never checked"],
                ["Does the +15.51 pp difference survive in a comparable population?",
                 "**The question cannot be answered.** No comparable subset could be formed, so "
                 "there is no matched estimate"],
                ["Is the result stable with respect to convention and parameters?",
                 f"**The raw comparison is stable** ({s['stability']}); the matched comparison does "
                 "not exist, so its stability is undefined"],
                ["Can the cause of the difference be identified?",
                 f"**No.** {_sentence(core['identifiability']['C_identified_cause']['answer'])} - "
                 "four blockers are named in section 11"],
                ["Is a new control corpus needed?",
                 "**Yes.** The comparison cannot be identified with the corpora that exist"],
                ["Does Stage 24 justify a new experiment?",
                 "**Yes, as a corpus and not as an analysis.** Section 12 states the minimum design"],
                ["Does the result change any Atari Music Composer decision?",
                 "**No.** `NO_PRODUCTION_DECISION_CHANGED`"],
                ["Verdict", f"**{s['verdict']}**"],
                ["Auxiliary verdicts", ", ".join(f"`{v}`" for v in s["auxiliary_verdicts"])],
                ["Reproducibility",
                 f"**{s['reproducible']}** - the deterministic core was run twice and the payload "
                 "digests matched"],
                ["Read-only audit",
                 f"**{s['read_only']}** - {s['read_only_files_checked']} production and input "
                 "artefacts hashed before and after the run, none changed"],
            ],
        ),
        "",
        "**The descriptive, the matched and the identified are three different statements.** "
        f"Descriptive: **{s['descriptive_answer']}**, the historical corpus carries a larger "
        f"residual ({_pct(s['raw_difference'])}). Matched: **{s['matched_answer']}**. Identified: "
        f"**{s['identified_answer']}**. This stage reports all three separately and merges none of "
        "them.\n",
        "**The difference is not denied and it is not explained.** It is measured, it is stable "
        "under every leave-one-out axis and every residual definition, and the data cannot say what "
        "produced it. Section 11 names the four reasons; none of them is a statistical problem that "
        "a better method would fix.\n",
    ]



def _s2(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    audit = bundle["audit"]
    inventory = core["inventory"]
    return [
        "## 2. Corpus and Source Audit\n",
        "The brief's rule is that the artefacts win over any summary, including this one. Every "
        "definition this stage relies on is quoted from the stage that owns it, and Stage 23's "
        "published numbers are read from its own artefacts rather than restated:\n",
        _table(
            ["quantity", "Stage 23 published"],
            [
                ["analysis_version", audit["stage23_analysis_version"]],
                ["support verdict", audit["stage23_verdict"]["verdicts"]["primary"]["verdict"]],
                ["primary estimand", audit["stage23_summary"]["primary_estimand"]],
                ["control mean", _num(audit["stage23_summary"]["primary_control_mean"])],
                ["historical mean", _num(audit["stage23_summary"]["primary_historical_mean"])],
                ["difference", _num(audit["stage23_summary"]["primary_difference"])],
                ["interval", str(audit["stage23_summary"]["primary_ci"])],
                ["declared caliper", str(audit["stage23_declared_caliper"])],
                ["caliper actually applied", str(audit["stage23_caliper_applied"])],
            ],
        ),
        "",
        "### What the corpora contain\n",
        _table(
            ["property", "historical", "control"],
            [
                ["traces", inventory["historical"]["traces"], inventory["control"]["traces"]],
                ["independent sources", inventory["historical"]["sources"],
                 inventory["control"]["sources"]],
                ["credited authors", len(inventory["historical"]["authors"]),
                 len(inventory["control"]["authors"])],
                ["AUDCTL configurations", str(inventory["historical"]["audctl"]),
                 str(inventory["control"]["audctl"])],
                ["document kinds", str(inventory["historical"]["kinds"]),
                 str(inventory["control"]["kinds"])],
                ["SAP types", str(inventory["historical"]["sap_types"]),
                 str(inventory["control"]["sap_types"])],
                ["frames median", _num(inventory["historical"]["frames"]["median"]),
                 _num(inventory["control"]["frames"]["median"])],
                ["frames range",
                 _range(inventory["historical"]["frames"]["min"],
                        inventory["historical"]["frames"]["max"]),
                 _range(inventory["control"]["frames"]["min"],
                        inventory["control"]["frames"]["max"])],
                ["channels", str(inventory["historical"]["channels"]),
                 str(inventory["control"]["channels"])],
                ["register values", core["effective_sample_sizes"]["historical_register_values"],
                 core["effective_sample_sizes"]["control_register_values"]],
            ],
        ),
        "",
        "**The AUDCTL row is the whole story in one line.** "
        f"{inventory['historical']['audctl'].get('$50', 0)} of "
        f"{inventory['historical']['traces']} historical traces run AUDCTL `$50`, the 16-bit pair "
        "clocked at 1.79 MHz. The control corpus uses "
        f"{sorted(inventory['control']['audctl'])} and contains no 1.79 MHz composition at all. That "
        "is a hardware configuration rather than a musical choice, and it changes the divider "
        "arithmetic, the pitch resolution and the range of AUDF values a tune can reach.\n",
        "### What is known, derived, unknown and not comparable\n",
        _table(
            ["field", "control", "historical", "class"],
            [[item["field"], item["control"], item["historical"], item["class"]]
             for item in core["inventory"]["comparability_notes"]],
        ),
        "",
        "**No composition feature is assigned to a historical SAP.** A SAP is a player plus data: "
        "its note set, its instruments and its tempo are not recoverable from the trace, and they "
        "are recorded as unknown rather than inferred. The per-trace inventory in "
        "`corpus_inventory.json` carries that split for every one of the 65 traces.\n",
    ]



def _s3(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    return [
        "## 3. Common Feature Definitions\n",
        f"{len(core['feature_definitions'])} features are defined, of which "
        f"{len(core['matching_features'])} are used for matching and "
        f"{len(core['excluded_features'])} are excluded. Every definition states what is counted, "
        "over what denominator, how silence is treated and where the measurement is limited. A "
        "feature is admitted only when it is measurable the same way in both corpora, and the "
        "residual is never used as a feature.\n",
        _table(
            ["feature", "role", "unit", "denominator", "silence"],
            [[item["name"], item["role"], item["unit"], item["denominator"], item["silence"]]
             for item in core["feature_definitions"]],
        ),
        "",
        "### Why each excluded feature is excluded\n",
        _table(
            ["feature", "role", "reason"],
            [[item["name"], item["role"], item["limitations"]]
             for item in core["feature_definitions"] if item["role"] != "matching"],
        ),
        "",
        "**The exclusions all narrow the apparent separation, which is why they are argued rather "
        "than asserted.** Removing a feature can only make the corpora look more alike, so an "
        "exclusion that is not justified would be a way of manufacturing overlap. Two are "
        "degenerate - identical constants in both corpora - and one is a count that grows with "
        "trace length. The support verdict below is reached with them removed, and it is still "
        "`COMMON_SUPPORT_INADEQUATE`.\n",
    ]


def _s4(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    univariate = core["univariate_overlap"]
    overlap = core["multivariate_overlap"]
    box = overlap["box"]
    propensity = overlap["propensity"]
    neighbours = overlap["nearest_neighbour"]
    return [
        "## 4. Overlap Analysis\n",
        "### Univariate: the brief's table\n",
        _table(
            ["feature", "control range", "historical range", "common support",
             "control outside", "historical outside", "classification"],
            [[row["feature"],
              _range(row.get("control_min"), row.get("control_max")),
              _range(row.get("historical_min"), row.get("historical_max")),
              _range(row.get("support_low"), row.get("support_high")),
              f"{row.get('control_outside_support')}/{row.get('control_n')}",
              f"{row.get('historical_outside_support')}/{row.get('historical_n')}",
              row.get("classification")]
             for row in univariate["features"]],
        ),
        "",
        f"**Strictly separated features: {univariate['separated_features'] or 'none'}.** "
        f"**Degenerate features: {univariate['degenerate_features'] or 'none'}.** "
        f"**Poorly covered (fewer than {_pct(univariate['coverage_threshold'])} of historical "
        f"traces inside the control range): {univariate['poorly_covered_features'] or 'none'}.**\n",
        "A feature that is the same constant in both corpora is the opposite of a separation: it "
        "carries no information and cannot distinguish anything. Stage 23 reported such a feature "
        "as having 'no common range', which reads as a separation. The classification here "
        "separates the two cases.\n",
        "### Multivariate: three criteria, each calibrated\n",
        "**Box support.** The control corpus's feature box, and the same test run leave-one-out "
        "inside the control corpus so the criterion's own power is visible:\n",
        _table(
            ["criterion", "control (leave-one-out)", "historical"],
            [
                ["traces", box["control"]["traces"], box["historical"]["traces"]],
                ["inside on every feature",
                 box["calibration_inside_control"]["inside_on_every_feature"],
                 box["historical"]["inside_on_every_feature"]],
                ["inside share",
                 _pct(box["calibration_inside_control"]["inside_share"]),
                 _pct(box["historical"]["inside_share"])],
                ["outside on at most 1 feature",
                 box["calibration_inside_control"]["outside_on_at_most_1"],
                 box["historical"]["outside_on_at_most_1"]],
                ["outside on at most 3 features",
                 box["calibration_inside_control"]["outside_on_at_most_3"],
                 box["historical"]["outside_on_at_most_3"]],
                ["median features outside",
                 box["calibration_inside_control"]["median_features_outside"],
                 box["historical"]["median_features_outside"]],
            ],
        ),
        "",
        "**The calibration is what makes the box result evidence.** "
        f"{box['calibration_inside_control']['inside_on_every_feature']} of "
        f"{box['control']['traces']} control traces pass the same test against the other controls, "
        "so the criterion is not vacuously strict. "
        f"{box['historical']['inside_on_every_feature']} of {box['historical']['traces']} "
        "historical traces pass it. The criterion discriminates, and it rejects every historical "
        "trace.\n",
        "**Distance support.** The control corpus's own leave-one-out distances set the yardstick:\n",
        _table(
            ["quantity", "value"],
            [
                ["control leave-one-out minimum", _num(neighbours["control_loo"]["min"])],
                ["control leave-one-out median", _num(neighbours["control_loo"]["median"])],
                ["control leave-one-out p90", _num(neighbours["control_loo"]["p90"])],
                ["control leave-one-out maximum", _num(neighbours["control_loo"]["max"])],
                ["historical nearest minimum", _num(neighbours["historical_nearest"]["min"])],
                ["historical nearest median", _num(neighbours["historical_nearest"]["median"])],
                ["historical nearest maximum", _num(neighbours["historical_nearest"]["max"])],
                ["historical beyond the control maximum",
                 f"{neighbours['historical_beyond']['control_loo_max']}/"
                 f"{neighbours['historical_traces']}"],
                ["historical beyond the control p90",
                 f"{neighbours['historical_beyond']['control_loo_p90']}/"
                 f"{neighbours['historical_traces']}"],
            ],
        ),
        "",
        "**Propensity score, with its stability reported rather than assumed.**\n",
        _table(
            ["quantity", "control", "historical"],
            [
                ["propensity minimum", propensity["control_score"]["min"],
                 propensity["historical_score"]["min"]],
                ["propensity median", propensity["control_score"]["median"],
                 propensity["historical_score"]["median"]],
                ["propensity maximum", propensity["control_score"]["max"],
                 propensity["historical_score"]["max"]],
                ["in the overlap region",
                 f"{propensity['control_score']['in_overlap_region']}/{box['control']['traces']}",
                 f"{propensity['historical_score']['in_overlap_region']}/"
                 f"{box['historical']['traces']}"],
            ],
        ),
        "",
        f"**Complete separation: {propensity['complete_separation']}.** "
        f"{len(propensity['unstable_terms'])} of {len(propensity['coefficient_stability'])} "
        "coefficients change sign across bootstrap resamples of the pooled corpus, so the model is "
        "not estimable at this sample size. Its separation is reported as a diagnostic and is "
        "**not** used on its own to conclude that the comparison is unsupported - the brief warns "
        "against that, and the two other criteria agree with it independently.\n",
        f"### The support verdict: `{overlap['verdict']}`\n",
        f"{overlap['verdict_rule']}.\n",
        f"**Criteria agree: {overlap['criteria_agree']}.** {overlap['reading']}.\n",
    ]


def _s5(bundle: Mapping[str, Any]) -> List[str]:
    diagnostics = bundle["core"]["matching_diagnostics"]
    return [
        "## 5. Diagnostics of the Earlier Matching\n",
        "Stage 23's matching method is re-derived here rather than trusted, because a method is not "
        "correct merely because it was implemented. Three defects were found:\n",
        _table(
            ["defect", "what was measured"],
            [
                ["the declared caliper was never applied", diagnostics["stage23_defect"]],
                ["balance was never checked",
                 "Stage 23 reported a matched gap without reporting the standardised mean "
                 "difference of any feature after matching, so an unbalanced match could not be "
                 "distinguished from a balanced one"],
                ["the neighbour count was fixed and not varied",
                 "a single k was used with no sensitivity to it, so the result's dependence on the "
                 "neighbourhood size was unknown"],
            ],
        ),
        "",
        f"**{diagnostics['method_count']} methods were run here, over a declared grid.** "
        f"{diagnostics['reportable_count']} can produce a difference and "
        f"{diagnostics['validated_count']} satisfies the declared balance criterion. A method that "
        "produces a number is reported as *reportable*; a method whose match is defensible is "
        "reported as *validated*. The two are not the same and are not conflated.\n",
        _table(
            ["method", "caliper", "k", "tolerance", "kept", "sources", "rejected",
             "difference", "max |SMD|", "reportable", "validated"],
            [[row["method"], row["caliper"], row["neighbours"], row["tolerance"],
              row["historical_kept"], row["historical_sources_kept"],
              row["historical_rejected"],
              _num(row["difference"].get("observed_difference")),
              _num(row["balance"]["max_absolute_smd"]),
              row["reportable"], row["matching_validated"]]
             for row in diagnostics["methods"]],
        ),
        "",
        "**Every nearest-neighbour setting retains nothing.** The smallest historical-to-control "
        "distance exceeds the loosest declared caliper, so the caliper Stage 23 declared and never "
        "applied would have excluded the entire historical corpus. That is the finding: the Stage 23 "
        "match was not a match.\n",
        "**The three reportable methods are all unbalanced.** Their largest absolute standardised "
        "mean differences are far above the declared threshold, so none of them is a matched "
        "comparison in any useful sense.\n",
    ]


def _s6(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    sensitivity = core["sensitivity"]
    no_matching = next(
        row for row in core["matching_diagnostics"]["methods"]
        if row["method"] == "no_matching"
    )
    difference = no_matching["difference"]
    return [
        "## 6. Results Before Matching\n",
        "This is the descriptive comparison, and it is the same comparison Stage 23 reported. It is "
        "the reference point, not an effect estimate.\n",
        _table(
            ["quantity", "value"],
            [
                ["estimand", PRIMARY_ESTIMAND],
                ["control traces", difference["control_traces"]],
                ["historical traces", difference["historical_traces"]],
                ["historical clusters (SAP sources)", difference["historical_clusters"]],
                ["difference in means", _num(difference["observed_difference"])],
                ["interval low", _num(difference["ci_low"])],
                ["interval high", _num(difference["ci_high"])],
                ["excludes zero", difference["excludes_zero"]],
                ["cluster unit", difference["cluster_unit"]],
            ],
        ),
        "",
        "**The interval resamples sources, never frames.** The corpus holds about "
        f"{core['effective_sample_sizes']['historical_register_values'] + core['effective_sample_sizes']['control_register_values']} "
        "register values, which are 65 traces, which are 11 historical SAP sources and 53 control "
        "documents. An interval resampled over frames would be narrower by orders of magnitude and "
        "would mean nothing.\n",
        f"**The difference is {_pct(sensitivity['full_corpus_difference'])} and it is stable.** It "
        "keeps its sign under every residual definition and under every leave-one-out drop, which is "
        "exactly what Stage 23 reported and what this stage reproduces rather than disputes.\n",
    ]


def _s7(bundle: Mapping[str, Any]) -> List[str]:
    core = bundle["core"]
    diagnostics = core["matching_diagnostics"]
    identifiability = core["identifiability"]
    validated = [row for row in diagnostics["methods"] if row["matching_validated"]]
    reportable = [row for row in diagnostics["methods"] if row["reportable"]]
    return [
        "## 7. Results After Matching\n",
        f"**There is no matched result to report.** {diagnostics['reportable_count']} methods "
        f"produce a difference and {len(validated)} satisfies the declared balance criterion. "
        "Reporting a matched estimate here would be reporting the unmatched comparison under "
        "another name.\n",
        "### What the reportable methods actually did\n",
        _table(
            ["method", "caliper", "tolerance", "kept", "sources", "difference", "max |SMD|",
             "why it is not validated"],
            [[row["method"], row["caliper"], row["tolerance"], row["historical_kept"],
              row["historical_sources_kept"],
              _num(row["difference"].get("observed_difference")),
              _num(row["balance"]["max_absolute_smd"]),
              _sentence(row["not_validated_because"] or "")]
             for row in reportable],
        ),
        "",
        "### Why no comparison survives the common-support restriction\n",
        _table(
            ["restriction", "historical kept", "sources kept", "difference"],
            [[f"outside the control box on at most {row['tolerance']} features",
              row["historical_kept"], row["historical_sources_kept"],
              _num(row["difference"].get("observed_difference"))]
             for row in diagnostics["methods"]
             if row["method"] == "support_restriction"],
        ),
        "",
        "**The loosest declared restriction is the one that looks most like a result, and it is the "
        "least defensible.** It keeps eight historical traces by allowing each of them to sit "
        "outside the control box on up to five of twenty-one features. That is not a comparable "
        "subset; it is the unmatched comparison with four traces removed, and its balance still "
        "fails the declared criterion.\n",
        f"**B, answered:** {identifiability['B_difference_after_matching']['answer']}. "
        f"{identifiability['B_difference_after_matching']['what_it_does_not_say']}\n",
    ]


def _s8(bundle: Mapping[str, Any]) -> List[str]:
    samples = bundle["core"]["effective_sample_sizes"]
    return [
        "## 8. Effective Sample Size and Uncertainty\n",
        f"**{samples['unit_of_replication']}.**\n",
        _table(
            ["quantity", "value"],
            [
                ["historical traces", samples["historical_traces"]],
                ["historical SAP sources", samples["historical_sources"]],
                ["historical composers", samples["historical_authors"]],
                ["control compositions", samples["control_traces"]],
                ["historical register values", samples["historical_register_values"]],
                ["control register values", samples["control_register_values"]],
            ],
        ),
        "",
        "### Per-method accounting\n",
        _table(
            ["method", "caliper", "tolerance", "kept", "rejected", "sources",
             "historical ESS", "control ESS", "difference", "interval"],
            [[row["method"], row["caliper"], row["tolerance"],
              row["historical_traces_kept"], row["historical_traces_rejected"],
              row["historical_sources_kept"], _num(row["historical_ess"]),
              _num(row["control_ess"]), _num(row["difference"]),
              f"[{_num(row['ci_low'])}, {_num(row['ci_high'])}]"]
             for row in samples["methods"]],
        ),
        "",
        f"**{samples['power_statement']}.**\n",
        f"{samples['reading']}.\n",
    ]


def _s9(bundle: Mapping[str, Any]) -> List[str]:
    sensitivity = bundle["core"]["sensitivity"]
    loo = sensitivity["leave_one_historical_song_out"]
    control_loo = sensitivity["leave_one_control_source_out"]
    grid = sensitivity["matching_parameters"]
    return [
        "## 9. Sensitivity Analyses\n",
        f"**The rule, declared before the numbers were read:** {sensitivity['unstable_rule']}.\n",
        f"**Classification: `{sensitivity['classification']}`.** "
        f"{sensitivity['classification_scope']}.\n",
        "### Leave one historical song out\n",
        _table(
            ["dropped", "source", "kept", "difference", "sign"],
            [[row["dropped"], row["dropped_source"], row["kept_traces"],
              _num(row["difference"]), row["sign"]] for row in loo["rows"]],
        ),
        "",
        f"Signs observed: **{loo['signs']}**; range "
        f"[{_num(loo['min_difference'])}, {_num(loo['max_difference'])}].\n",
        "### Leave one control composition out\n",
        f"Signs observed: **{control_loo['signs']}** over {len(control_loo['rows'])} drops. The "
        "control corpus is much larger and no single composition moves the sign.\n",
        "### Sensitivity to the matching parameters\n",
        _table(
            ["caliper", "k", "historical kept", "sources kept", "difference"],
            [[row["caliper"], row["neighbours"], row["historical_kept"],
              row["historical_sources_kept"], _num(row["difference"])]
             for row in grid["rows"]],
        ),
        "",
        f"**{grid['settings_retaining_anything']} of {len(grid['rows'])} settings retain any "
        f"historical trace and {grid['settings_retaining_the_minimum']} retain the declared "
        "minimum.** The result does not depend on the parameters because no parameter setting "
        "produces a comparison at all.\n",
        "### Sensitivity to the residual convention\n",
        _table(
            ["estimand", "difference", "interval low", "interval high", "n control", "n historical"],
            [[row["estimand"], _num(row["difference"]), _num(row["ci_low"]),
              _num(row["ci_high"]), row["defined_in_control"], row["defined_in_historical"]]
             for row in sensitivity["residual_convention"]["rows"]],
        ),
        "",
        f"Signs across definitions: **{sensitivity['residual_convention']['signs']}**. The negative "
        "sign belongs to `E_out_span_hold`, the out-of-span hold convention, which Stage 23 also "
        "reported as negative; it is the convention the out-of-span region exists in, and the "
        "in-span estimand is convention-free.\n",
        "### Sensitivity to the feature set\n",
        _table(
            ["feature set", "features", "support verdict", "historical inside box",
             "propensity retained", "nearest minimum", "control LOO maximum"],
            [[row["feature_set"], row["features"], row.get("support_verdict"),
              row.get("historical_inside_box"), row.get("propensity_retained"),
              _num(row.get("nearest_min")), _num(row.get("control_loo_max"))]
             for row in sensitivity["feature_set"]["rows"]],
        ),
        "",
        "### Channel-level sensitivity\n",
        _table(
            ["register", "control rate", "historical rate", "difference",
             "control denominator", "historical denominator"],
            [[row["register"], _pct(row["control_rate"]), _pct(row["historical_rate"]),
              _pct(row["difference"]), row["control_denominator"],
              row["historical_denominator"]]
             for row in sensitivity["channel"]["rows"]],
        ),
        "",
        "### Common-support-only and weighted against unweighted\n",
        _table(
            ["method", "caliper", "tolerance", "difference", "historical ESS", "weighted"],
            [[row["method"], row["caliper"], row["tolerance"], _num(row["difference"]),
              _num(row["historical_ess"]), row["weighted"]]
             for row in sensitivity["weighted_against_unweighted"]["rows"]],
        ),
        "",
        "**Weighting changes nothing here, because there is nothing to weight.** The only weighted "
        "method that retains the whole corpus is the propensity stratification, and its weights are "
        "derived from a score that separates the corpora completely.\n",
    ]




def _s10(bundle: Mapping[str, Any]) -> List[str]:
    falsification = bundle["core"]["falsification"]
    return [
        "## 10. Falsification Test\n",
        "The conditions under which the history-specific reading is rejected were declared before "
        "the comparison was run and are not amended afterwards. Each is reported with the "
        "measurement that decided it.\n",
        _table(
            ["condition", "threshold", "passed", "measurement"],
            [[row["criterion"], row["threshold"], row["passed"],
              json.dumps(row["measurement"], sort_keys=True)]
             for row in falsification["criteria"]],
        ),
        "",
        f"**{falsification['passed']} of {falsification['total']} conditions pass.** "
        f"{falsification['conclusion']}.\n",
        "### The rejected conditions\n",
        "\n".join(f"* {_sentence(item)}" for item in falsification["rejected_criteria"]) + "\n",
        "**The sixth condition is the one that cannot be discharged at all.** The control traces "
        "are compiled deterministically from an authored document by the project's own compiler, and "
        "the historical traces are digitised from a third-party player. Nothing measurable in a "
        "trace distinguishes a player's behaviour from a composer's, and no control exists in which "
        "one player is run over both corpora. That is a confound the data cannot remove, and it is "
        "reported as a failure rather than as a caveat.\n",
    ]


def _s11(bundle: Mapping[str, Any]) -> List[str]:
    identifiability = bundle["core"]["identifiability"]
    return [
        "## 11. Identifiability Limits\n",
        "The brief asks for the descriptive difference, the matched difference and the identified "
        "effect to be reported separately and never merged. They are answered here as three "
        "separate questions.\n",
        "### A. The descriptive difference\n",
        f"**{identifiability['A_descriptive_difference']['answer'].upper()}** - the historical "
        "traces carry a larger residual than the control traces.\n",
        _table(
            ["quantity", "value"],
            [[key, _cell(value)] for key, value in
             sorted(identifiability["A_descriptive_difference"]["measurement"].items())],
        ),
        "",
        f"{_sentence(identifiability['A_descriptive_difference']['what_it_does_not_say'])}\n",
        "### B. The difference after matching\n",
        f"**{_sentence(identifiability['B_difference_after_matching']['answer'])}**\n",
        _table(
            ["quantity", "value"],
            [[key, _cell(value)] for key, value in
             sorted(identifiability["B_difference_after_matching"]["measurement"].items())],
        ),
        "",
        f"{_sentence(identifiability['B_difference_after_matching']['what_it_does_not_say'])}\n",
        "### C. The identified cause\n",
        f"**{identifiability['C_identified_cause']['answer'].upper()}.** Four blockers, each "
        "measured rather than asserted:\n",
        _table(
            ["blocker", "evidence"],
            [[row["blocker"], row["evidence"]]
             for row in identifiability["C_identified_cause"]["blockers"]],
        ),
        "",
        f"{_sentence(identifiability['C_identified_cause']['what_it_does_not_say'])}\n",
        f"**Summary: {identifiability['summary']}.**\n",
    ]



def _s12(bundle: Mapping[str, Any]) -> List[str]:
    design = bundle["core"]["next_experiment"]
    experiment = design["minimal_experiment"]
    return [
        "## 12. The Minimal Additional Experiment\n",
        "The comparison cannot be identified with the corpora that exist, so the next step is a "
        "corpus and not an analysis. The design is stated and **not executed**: no composition is "
        "authored, no profile is bound and no music is generated.\n",
        "### The gaps that would have to be closed\n",
        _table(
            ["gap", "measurement", "how it would be closed", "closable"],
            [[row["gap"], row["measurement"], row["closes_it"], row["testable"]]
             for row in design["identified_gaps"]],
        ),
        "",
        "### The proposed corpus\n",
        _table(
            ["property", "requirement"],
            [
                ["name", experiment["name"]],
                ["what it is", experiment["what_it_is"]],
                ["minimum size", experiment["minimum_size"]],
                ["ground truth", experiment["ground_truth_requirement"]],
                ["cost and risk", experiment["cost_and_risk"]],
            ],
        ),
        "",
        "**Must be controlled:**\n",
        "\n".join(f"* {item}" for item in experiment["must_control"]) + "\n",
        "**Must not vary:**\n",
        "\n".join(f"* {item}" for item in experiment["must_not_vary"]) + "\n",
        "**What would falsify the hypothesis:**\n",
        "\n".join(f"* {item}" for item in experiment["what_would_falsify_the_hypothesis"]) + "\n",
        f"**What would allow a design decision:** "
        f"{experiment['what_would_allow_a_design_decision']}.\n",
        f"**Configurability note.** {_sentence(design['configurability_note'])}.\n",
        f"**{design['not_done_here']}.**\n",
    ]




def _s13(bundle: Mapping[str, Any]) -> List[str]:
    audit = bundle["audit"]
    box = bundle["core"]["multivariate_overlap"]["box"]
    univariate = bundle["core"]["univariate_overlap"]
    normalised = next(
        row for row in univariate["features"]
        if row["feature"] == "audf_diversity_per_1000_frames"
    )
    return [
        "## 13. Explicit Methodological Corrections\n",
        "Every problem found while building this stage, and what was done about it. Nothing was "
        "quietly fixed: a correction that changes a number is stated here.\n",
        _table(
            ["claim", "what was measured instead", "consequence"],
            [[item["claim"], item["measured"], item["consequence"]]
             for item in audit["discrepancies_found"]],
        ),
        "",
        "**1. A support criterion is only evidence when it can pass the control corpus's own "
        "members.** The bounding-box test is the strictest definition of common support available, "
        "and with 53 samples over 21 features it would be easy to build one that nothing passes and "
        "then declare the corpora incomparable. So it is run leave-one-out *inside* the control "
        "corpus first. It passes "
        f"{box['calibration_inside_control']['inside_on_every_feature']} of the "
        f"{box['control']['traces']} control traces, so it discriminates, and it rejects every "
        "historical trace. Without that calibration the same number would have meant nothing.\n",
        "**2. A count that grows with trace length is not a comparable feature.** Stage 23 declared "
        "`distinct_audf_values` a feature with no common range, and that single feature made the "
        "multivariate overlap look hopeless. The historical traces are two to three times longer "
        "than the control ones, so the count separates them by construction. The length-normalised "
        "form of the same feature overlaps: the control range is "
        f"{_range(normalised['control_min'], normalised['control_max'])}, the historical range is "
        f"{_range(normalised['historical_min'], normalised['historical_max'])}, and "
        f"{normalised['historical_outside_support']} of "
        f"{normalised['historical_n']} historical traces fall outside it. The raw count is still "
        "reported, and it is excluded from the matching with the reason stated, because excluding a "
        "feature narrows the apparent separation and a reader is entitled to see the argument.\n",
        "**3. A constant feature is the opposite of a separation.** `audctl_change_rate` is "
        "identically zero in all 65 traces of both corpora. Stage 23's table reported it as having "
        "'no common range', which reads as the corpora being separated on it; in fact they agree on "
        "it exactly, and it carries no information. The classification here separates `separated` "
        "from `shared_constant`, and the latter is excluded as degenerate rather than reported as a "
        "gap.\n",
        "**4. A declared caliper that is never applied is not a control.** Stage 23 declares "
        "`CALIPER = 1.0` and writes it into its artefacts, and its neighbour function takes no "
        "caliper argument. Every historical trace was therefore matched to its nearest control trace "
        "however far away that was. Stage 24 applies the caliper and reports the consequence: the "
        "entire declared grid retains nothing, because the smallest historical distance exceeds the "
        "loosest declared caliper.\n",
        "**5. A propensity score is a diagnostic and not proof.** The score separates the corpora "
        "completely here, which is itself a statement about how unlike they are, but 16 of its 22 "
        "coefficients change sign across bootstrap resamples. A model that unstable cannot be used "
        "as an automatic test of overlap, and the brief says so explicitly. It is reported beside "
        "two other criteria calibrated independently, and all three agree.\n",
        "**6. A method that produces a number is not a validated match.** The three reportable "
        "methods all fail the declared balance criterion. They are reported as *reportable*, which "
        "is what they are, and explicitly not as *validated*, which is what they are not. The "
        "distinction is carried in the artefacts, not only in the prose.\n",
        "### Read-only audit\n",
        _table(
            ["audit", "files checked", "changed", "read-only"],
            [[row["label"], row["files_checked"], len(row["changed"]), row["read_only"]]
             for _key, row in sorted(bundle["read_only_audit"].items())],
        ),
        "",
        "Stage 15 to 23, the composer, the DSL, the IR, the player and the exporter were read "
        "through their hashes and never written. The traces, the composition documents and the "
        "upstream artefacts were hashed before and after the run as well.\n",
    ]


def _s14(bundle: Mapping[str, Any]) -> List[str]:
    decided = bundle["core"]["verdicts"]
    main = decided["main"]
    return [
        "## 14. Verdict and Recommendation\n",
        _table(
            ["subject", "verdict", "deciding measurement"],
            [["main", main["verdict"],
              json.dumps(main["deciding_measurement"], sort_keys=True)]]
            + [[row["verdict"], row["verdict"], _sentence(row["reason"])]
               for row in decided["auxiliary"]],
        ),
        "",
        f"### What `{main['verdict']}` means\n",
        f"{_sentence(main['what_it_means'])}.\n",
        f"**What it does not mean.** {_sentence(main['what_it_does_not_mean'])}.\n",
        "### The STOP condition\n",
        "The brief's STOP conditions are applied as written. The common support is inadequate, so "
        "the stage ends with `COMMON_SUPPORT_INADEQUATE` and proposes a new control corpus. It does "
        "not start Stage 25, it does not modify production, and it does not turn an unidentified "
        "difference into a claim about a cause.\n",
        "### Recommendation\n",
        "1. **Treat the current historical-versus-control comparison as closed for causal "
        "purposes.** It has been measured twice, it is stable, and it cannot be identified. Further "
        "analysis of the same two corpora will not change that; the limit is the data.\n",
        "2. **Do not read the difference as evidence of a performance layer.** It is confounded with "
        "trace length, the POKEY clock configuration and the trace generation process, and no "
        "matched estimate exists to separate them.\n",
        "3. **If the question is worth pursuing, build the corpus in section 12 first.** It is a "
        "document-authoring task using tooling that already exists, and it is the only thing that "
        "would move the comparison from unidentified to identified.\n",
        "4. **Fix the Stage 23 caliper defect wherever its matched numbers are quoted.** The "
        "published matched gap was produced without the caliper the stage declared, so any "
        "downstream reading of it inherits an extrapolation.\n",
        "### What does not change\n",
        "**`NO_PRODUCTION_DECISION_CHANGED`.** Stage 24 changes no detector, compiler, player, "
        "exporter or schema, produces no music and generates no corpus. Whatever it found is a "
        "statement about what the existing data can support, not a change to the composer.\n",
    ]




def _s_questions(bundle: Mapping[str, Any]) -> List[str]:
    """The eight closing questions, answered separately and from the measurements."""
    s = bundle["summary"]
    core = bundle["core"]
    sensitivity = core["sensitivity"]
    falsification = core["falsification"]
    return [
        "## The Eight Closing Questions\n",
        "**1. Do the corpora have enough common feature range?**\n",
        "**No.** No matching feature is strictly separated - after the length correction and the "
        f"degenerate-feature correction, all {s['matching_features']} have a non-empty common range "
        "- but the *joint* range is empty: "
        f"{s['historical_inside_control_box']} of {s['historical_traces']} historical traces lie "
        "inside the control corpus's feature box, against "
        f"{s['control_inside_control_box_leave_one_out']} of {s['control_traces']} control traces "
        "under the same leave-one-out test. The propensity overlap region retains "
        f"{s['historical_in_propensity_region']} historical traces. The univariate picture is mostly "
        "adequate; the multivariate picture is not.\n",
        "**2. Was the earlier matching methodologically sound?**\n",
        "**No.** Three defects, all measured: the declared caliper was never applied, balance was "
        "never checked, and the neighbour count was never varied. The consequence is that Stage 23's "
        "matched gap is not a matched gap - it is the distance from each historical trace to "
        "whatever control trace happened to be nearest.\n",
        "**3. Does the +15.51 pp difference persist in a comparable population?**\n",
        "**The question cannot be answered, and that is the finding.** "
        f"{s['methods']} declared methods were run; {s['reportable_methods']} produce a number and "
        f"{s['validated_methods']} satisfies the balance criterion. Every nearest-neighbour caliper "
        "retains zero historical traces. There is no comparable population in this data, so the "
        f"difference of {_pct(s['raw_difference'])} applies to the full corpus and cannot be "
        "transported to a subset.\n",
        "**4. Is the result stable with respect to convention and parameters?**\n",
        f"**The raw comparison is stable: `{s['stability']}`.** The sign survives every leave-one-out "
        f"drop ({s['leave_one_out_sign_stable']}) and every residual definition "
        f"({s['convention_signs']}). The matched comparison has no stability to report, because no "
        "parameter setting produces one: "
        f"{sensitivity['matching_parameters']['settings_retaining_anything']} of "
        f"{len(sensitivity['matching_parameters']['rows'])} settings retain any historical trace at "
        "all. Stability of an estimate that does not exist is not a property of the data.\n",
        "**5. Can the data identify the cause of the difference?**\n",
        "**No.** Four blockers, each measured: no common support; no matched estimate; the trace "
        "generation process is confounded with the corpus (a compiled document against a digitised "
        "third-party player, with no control in which one player runs over both); and no ground "
        "truth exists on the historical side. The fourth is a limit of the data that no statistical "
        "method removes, and the falsification test rejects the history-specific reading on "
        f"{len(falsification['rejected_criteria'])} of {falsification['total']} pre-declared "
        "conditions.\n",
        "**6. Is a new control corpus needed?**\n",
        "**Yes, and it is the only thing that would help.** The gap is not analytical. Section 12 "
        "states the minimum design: compositions with the `$50` POKEY configuration, at the "
        "historical length distribution, from at least three authored sources, through the existing "
        "compiler and player.\n",
        "**7. Does Stage 24 justify a new experiment?**\n",
        f"**Yes, as a corpus and not as an analysis.** The verdict is `{s['verdict']}` and the "
        "auxiliary verdict is `NEW_CONTROL_CORPUS_REQUIRED`. Stage 24 proposes the experiment, "
        "states what would falsify the hypothesis, and stops. It does not build the corpus and it "
        "does not start Stage 25.\n",
        "**8. Does the result change any Atari Music Composer decision?**\n",
        "**No.** `NO_PRODUCTION_DECISION_CHANGED`. Stage 24 is analysis-only, read-only and "
        "additive: no detector, compiler, player, exporter or schema is modified, no music is "
        "generated and no corpus is created. The one actionable item is a defect report - the "
        "Stage 23 caliper - and that is a documentation matter, not a production change.\n",
    ]
